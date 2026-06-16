"""
test_vision_extraction_fallback.py — image-only OCR/AI CIF fallback contract.

Covers the automatic vision fallback that fires when a DHL waybill / invoice is
an image-only (scanned) PDF and the text-based parsers leave CIF UNKNOWN:

  * document_text_quality.assess_pdf_text_quality — image-only vs text
  * document_text_quality.needs_vision_fallback   — gating logic
  * vision_extractor.validate_extraction          — schema validation / CIF math
  * vision_extractor.extract_fields_via_vision    — two-attempt extraction
                                                    (primary + secondary fallback)
  * vision_extractor.run_image_only_cif_fallback  — orchestrator: merge-not-
                                                    replace writes, retry-safety,
                                                    no-write-on-failure, USD-only
  * cif_resolver.resolve_cif consuming vision-written authority keys
  * the load-bearing invariant: UNKNOWN is None, never a fabricated 0.00

All AI is monkeypatched — no network. Synthetic PDFs are generated with PyMuPDF.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

fitz = pytest.importorskip("fitz")  # PyMuPDF — required to build/raster test PDFs

from app.services import ai_gateway, vision_extractor
from app.services import document_text_quality as dtq
from app.services.cif_resolver import resolve_cif, CIF_RESOLVED, CIF_UNKNOWN


# ── PDF builders ──────────────────────────────────────────────────────────────

def _make_image_only_pdf(path: Path) -> None:
    """A page with vector content but NO extractable text — stands in for a scan."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(40, 40, 555, 800), color=(0, 0, 0), fill=(0.85, 0.85, 0.85))
    page.draw_rect(fitz.Rect(80, 120, 515, 300), color=(0.2, 0.2, 0.2))
    doc.save(str(path))
    doc.close()


def _make_text_pdf(path: Path, text: str) -> None:
    """A normal text-bearing PDF."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), text, fontsize=12)
    doc.save(str(path))
    doc.close()


# ── document_text_quality ─────────────────────────────────────────────────────

def test_assess_detects_image_only_pdf(tmp_path):
    p = tmp_path / "scan.pdf"
    _make_image_only_pdf(p)
    q = dtq.assess_pdf_text_quality(str(p))
    assert q["exists"] is True
    assert q["image_only_pdf"] is True
    assert q["extracted_text_chars"] < dtq.DOC_TEXT_MIN_CHARS


def test_assess_detects_text_pdf(tmp_path):
    p = tmp_path / "doc.pdf"
    _make_text_pdf(p, "CUSTOMS VALUE USD 732.00\nInvoice INV-1\nFOB 700 Freight 20 Insurance 12")
    q = dtq.assess_pdf_text_quality(str(p), expected_labels=["customs", "value"])
    assert q["image_only_pdf"] is False
    assert q["has_numeric_values"] is True
    assert q["has_expected_labels"] is True


def test_assess_missing_file_is_conservative(tmp_path):
    q = dtq.assess_pdf_text_quality(str(tmp_path / "nope.pdf"))
    assert q["exists"] is False
    assert q["image_only_pdf"] is True  # conservative default so caller may try vision


def test_needs_vision_fallback_gating(tmp_path):
    img = tmp_path / "scan.pdf"
    _make_image_only_pdf(img)
    txt = tmp_path / "txt.pdf"
    _make_text_pdf(txt, "CUSTOMS VALUE USD 500 lots of real text here to exceed threshold")

    img_q = dtq.assess_pdf_text_quality(str(img))
    txt_q = dtq.assess_pdf_text_quality(str(txt))

    # Value already resolved → never run, regardless of document.
    run, _ = dtq.needs_vision_fallback(img_q, value_missing=False)
    assert run is False

    # Image-only + value missing → run.
    run, reason = dtq.needs_vision_fallback(img_q, value_missing=True)
    assert run is True and "image-only" in reason

    # Text-bearing + value missing → do NOT run (text-parse issue, not image-only).
    run, _ = dtq.needs_vision_fallback(txt_q, value_missing=True)
    assert run is False


# ── validate_extraction ───────────────────────────────────────────────────────

def test_validate_derives_cif_from_components():
    clean, errs = vision_extractor.validate_extraction(
        {"fob_usd": 700, "freight_usd": 20, "insurance_usd": 12, "confidence": 0.9},
        vision_extractor.DOC_INVOICE,
    )
    assert clean["cif_usd"] == 732.0
    assert clean.get("cif_derived") is True
    assert errs == []


def test_validate_rejects_impossible_cif():
    clean, errs = vision_extractor.validate_extraction(
        {"cif_usd": 2e9, "confidence": 0.9}, vision_extractor.DOC_INVOICE
    )
    assert "cif_usd" not in clean  # implausible amount dropped
    assert any("cif_usd" in e for e in errs)


def test_validate_rejects_bad_currency():
    clean, errs = vision_extractor.validate_extraction(
        {"custom_val_amount": 100, "custom_val_currency": "US Dollar", "confidence": 0.8},
        vision_extractor.DOC_WAYBILL,
    )
    assert "custom_val_currency" not in clean
    assert any("currency" in e for e in errs)


def test_validate_flags_cif_component_variance():
    clean, errs = vision_extractor.validate_extraction(
        {"cif_usd": 900, "fob_usd": 700, "freight_usd": 20, "insurance_usd": 12,
         "confidence": 0.8},
        vision_extractor.DOC_INVOICE,
    )
    # CIF kept (model asserted it) but variance vs 732 is flagged for review.
    assert clean["cif_usd"] == 900.0
    assert any("variance" in e for e in errs)


def test_validate_never_keeps_zero_amount():
    clean, _ = vision_extractor.validate_extraction(
        {"custom_val_amount": 0, "confidence": 0.9}, vision_extractor.DOC_WAYBILL
    )
    assert "custom_val_amount" not in clean  # zero is not a value


# ── extract_fields_via_vision (monkeypatched gateway) ─────────────────────────

def _patch_gateway(monkeypatch, responses):
    """Patch ai_gateway.is_available→True and call_vision to yield `responses`
    in order (a list; each item is a return value for one call_vision call)."""
    monkeypatch.setattr(ai_gateway, "is_available", lambda: True)
    seq = list(responses)
    calls = {"n": 0}

    def fake_call_vision(**kwargs):
        i = calls["n"]
        calls["n"] += 1
        return seq[i] if i < len(seq) else None

    monkeypatch.setattr(ai_gateway, "call_vision", fake_call_vision)
    return calls


def test_extract_primary_success(tmp_path, monkeypatch):
    p = tmp_path / "awb.pdf"
    _make_image_only_pdf(p)
    canned = json.dumps({
        "awb_number": "2315714531", "custom_val_amount": 732.0,
        "custom_val_currency": "USD", "confidence": 0.92,
        "source_page": 1, "source_text_or_visual_reason": "Customs Value USD 732.00",
    })
    calls = _patch_gateway(monkeypatch, [canned])
    prov = vision_extractor.extract_fields_via_vision(str(p), vision_extractor.DOC_WAYBILL, "b1")
    assert prov["ok"] is True
    assert prov["extraction_method"] == "vision_llm"
    assert prov["model_attempt"] == "primary"
    assert prov["fields"]["custom_val_amount"] == 732.0
    assert calls["n"] == 1  # secondary not needed


def test_extract_secondary_fallback(tmp_path, monkeypatch):
    p = tmp_path / "awb.pdf"
    _make_image_only_pdf(p)
    canned = json.dumps({
        "custom_val_amount": 500.0, "custom_val_currency": "USD", "confidence": 0.7,
        "source_page": 1, "source_text_or_visual_reason": "Declared Value 500 USD",
    })
    # Primary returns None → must escalate to secondary.
    calls = _patch_gateway(monkeypatch, [None, canned])
    prov = vision_extractor.extract_fields_via_vision(str(p), vision_extractor.DOC_WAYBILL, "b1")
    assert prov["ok"] is True
    assert prov["extraction_method"] == "vision_llm_fallback"
    assert prov["model_attempt"] == "secondary"
    assert calls["n"] == 2


def test_extract_both_attempts_fail(tmp_path, monkeypatch):
    p = tmp_path / "awb.pdf"
    _make_image_only_pdf(p)
    _patch_gateway(monkeypatch, [None, None])
    prov = vision_extractor.extract_fields_via_vision(str(p), vision_extractor.DOC_WAYBILL, "b1")
    assert prov["ok"] is False
    assert prov["extraction_method"] == "failed"


def test_extract_unavailable_gateway_noop(tmp_path, monkeypatch):
    p = tmp_path / "awb.pdf"
    _make_image_only_pdf(p)
    monkeypatch.setattr(ai_gateway, "is_available", lambda: False)
    prov = vision_extractor.extract_fields_via_vision(str(p), vision_extractor.DOC_WAYBILL, "b1")
    assert prov["ok"] is False
    assert "ai_gateway_unavailable" in prov["failed_layers"]


# ── Orchestrator: run_image_only_cif_fallback ─────────────────────────────────

def _make_batch(tmp_path, *, awb=True, invoice=False, audit_extra=None) -> Path:
    out = tmp_path / "batch1"
    (out / "source" / "awb").mkdir(parents=True, exist_ok=True)
    (out / "source" / "invoices").mkdir(parents=True, exist_ok=True)
    if awb:
        _make_image_only_pdf(out / "source" / "awb" / "awb.pdf")
    if invoice:
        _make_image_only_pdf(out / "source" / "invoices" / "inv.pdf")
    audit = {"batch_id": "batch1", "invoice_names": ["inv.pdf"]}
    if audit_extra:
        audit.update(audit_extra)
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return out


def _read_audit(out: Path) -> dict:
    return json.loads((out / "audit.json").read_text(encoding="utf-8"))


def test_orchestrator_writes_awb_custom_val_and_resolves(tmp_path, monkeypatch):
    out = _make_batch(tmp_path, awb=True)
    canned = json.dumps({
        "awb_number": "2315714531", "custom_val_amount": 732.0,
        "custom_val_currency": "USD", "confidence": 0.93,
        "source_page": 1, "source_text_or_visual_reason": "Customs Value USD 732.00",
    })
    _patch_gateway(monkeypatch, [canned])

    res = vision_extractor.run_image_only_cif_fallback(out, "batch1")
    assert res["ran"] is True
    assert res["wrote"] is True

    audit = _read_audit(out)
    assert audit["awb_customs"]["value_usd"] == 732.0
    assert audit["awb_customs"]["currency"] == "USD"
    assert audit["awb_customs"]["gap"] is False
    # cif_resolver now resolves from the vision-written authority key.
    r = resolve_cif(audit)
    assert r["cif_state"] == CIF_RESOLVED
    assert r["cif_usd"] == 732.0
    assert r["cif_source"] == "awb_customs.value_usd"


def test_orchestrator_invoice_writes_precheck_cif(tmp_path, monkeypatch):
    out = _make_batch(tmp_path, awb=False, invoice=True)
    canned = json.dumps({
        "invoice_no": "INV-1", "fob_usd": 700, "freight_usd": 20, "insurance_usd": 12,
        "custom_val_currency": "USD", "confidence": 0.9, "source_page": 1,
        "source_text_or_visual_reason": "CIF 732",
    })
    _patch_gateway(monkeypatch, [canned])

    res = vision_extractor.run_image_only_cif_fallback(out, "batch1")
    assert res["wrote"] is True
    audit = _read_audit(out)
    assert audit["dhl_precheck"]["invoice_cif_total_usd"] == 732.0
    assert audit["dhl_precheck"]["cif_source"] == "vision_llm"
    r = resolve_cif(audit)
    assert r["cif_state"] == CIF_RESOLVED
    assert r["cif_usd"] == 732.0


def test_orchestrator_merge_not_replace_preserves_siblings(tmp_path, monkeypatch):
    # awb_customs already holds an unrelated sibling field that must survive.
    out = _make_batch(tmp_path, awb=True, audit_extra={
        "awb_customs": {"source_pdf": "awb.pdf", "value_usd": None, "gap": True},
    })
    canned = json.dumps({
        "custom_val_amount": 732.0, "custom_val_currency": "USD", "confidence": 0.9,
        "source_page": 1, "source_text_or_visual_reason": "Customs Value 732 USD",
    })
    _patch_gateway(monkeypatch, [canned])

    vision_extractor.run_image_only_cif_fallback(out, "batch1")
    audit = _read_audit(out)
    assert audit["awb_customs"]["value_usd"] == 732.0
    assert audit["awb_customs"]["source_pdf"] == "awb.pdf"  # sibling preserved


def test_orchestrator_non_usd_awb_withheld_stays_unknown(tmp_path, monkeypatch):
    out = _make_batch(tmp_path, awb=True)
    canned = json.dumps({
        "custom_val_amount": 800.0, "custom_val_currency": "EUR", "confidence": 0.95,
        "source_page": 1, "source_text_or_visual_reason": "Customs Value EUR 800",
    })
    _patch_gateway(monkeypatch, [canned])

    res = vision_extractor.run_image_only_cif_fallback(out, "batch1")
    assert res["wrote"] is False  # USD-only — never auto-convert
    audit = _read_audit(out)
    assert resolve_cif(audit)["cif_state"] == CIF_UNKNOWN
    assert resolve_cif(audit)["cif_usd"] is None  # never fabricated 0.0


def test_orchestrator_low_confidence_withheld(tmp_path, monkeypatch):
    out = _make_batch(tmp_path, awb=True)
    canned = json.dumps({
        "custom_val_amount": 732.0, "custom_val_currency": "USD", "confidence": 0.2,
        "source_page": 1, "source_text_or_visual_reason": "faint, unsure",
    })
    _patch_gateway(monkeypatch, [canned])

    res = vision_extractor.run_image_only_cif_fallback(out, "batch1")
    assert res["wrote"] is False
    assert resolve_cif(_read_audit(out))["cif_state"] == CIF_UNKNOWN


def test_orchestrator_failed_extraction_keeps_unknown_never_zero(tmp_path, monkeypatch):
    out = _make_batch(tmp_path, awb=True)
    _patch_gateway(monkeypatch, [None, None])  # both attempts fail

    res = vision_extractor.run_image_only_cif_fallback(out, "batch1")
    assert res["wrote"] is False
    r = resolve_cif(_read_audit(out))
    assert r["cif_state"] == CIF_UNKNOWN
    assert r["cif_usd"] is None  # the load-bearing invariant: never 0.00


def test_orchestrator_noop_when_cif_already_resolved(tmp_path, monkeypatch):
    out = _make_batch(tmp_path, awb=True, audit_extra={
        "invoice_totals": {"total_cif_usd": 1000.0},
    })
    calls = _patch_gateway(monkeypatch, [json.dumps({"custom_val_amount": 1})])
    res = vision_extractor.run_image_only_cif_fallback(out, "batch1")
    assert res["ran"] is False  # CIF already resolved → no vision call
    assert calls["n"] == 0


def test_orchestrator_retry_safety_skips_same_version(tmp_path, monkeypatch):
    out = _make_batch(tmp_path, awb=True)
    _patch_gateway(monkeypatch, [None, None])  # first run fails, records signature

    res1 = vision_extractor.run_image_only_cif_fallback(out, "batch1")
    assert res1["wrote"] is False

    # Second run with a gateway that WOULD succeed — but the file version is
    # unchanged, so the orchestrator must skip re-extraction (no infinite retry).
    calls = _patch_gateway(monkeypatch, [json.dumps({
        "custom_val_amount": 732.0, "custom_val_currency": "USD", "confidence": 0.9,
        "source_page": 1, "source_text_or_visual_reason": "x",
    })])
    res2 = vision_extractor.run_image_only_cif_fallback(out, "batch1")
    assert calls["n"] == 0  # retry-safety: same version not re-attempted
    assert res2["wrote"] is False


def test_orchestrator_blank_currency_awb_withheld_stays_unknown(tmp_path, monkeypatch):
    """A waybill amount with a blank / unreadable currency is never assumed USD.
    Unknown currency → withhold; CIF stays UNKNOWN (never relabelled as USD
    authority, never fabricated 0.00). Regression for the blank-currency gate."""
    out = _make_batch(tmp_path, awb=True)
    canned = json.dumps({
        "custom_val_amount": 732.0, "custom_val_currency": "", "confidence": 0.95,
        "source_page": 1, "source_text_or_visual_reason": "Value 732, currency unreadable",
    })
    _patch_gateway(monkeypatch, [canned])

    res = vision_extractor.run_image_only_cif_fallback(out, "batch1")
    assert res["wrote"] is False  # blank currency never assumed USD
    audit = _read_audit(out)
    assert audit.get("awb_customs", {}).get("value_usd") is None  # no USD write
    r = resolve_cif(audit)
    assert r["cif_state"] == CIF_UNKNOWN
    assert r["cif_usd"] is None  # the load-bearing invariant: never 0.00
    doc = audit["vision_extraction"]["runs"][-1]["documents"][-1]
    assert doc["write"] == "withheld_unknown_currency"


def test_orchestrator_non_usd_invoice_withheld_stays_unknown(tmp_path, monkeypatch):
    """An invoice whose document currency is legibly non-USD must withhold every
    USD-named write even when a cif_usd number is present — a wrong CIF that looks
    'resolved' is worse than a preserved UNKNOWN gap. Regression for the invoice
    currency gate."""
    out = _make_batch(tmp_path, awb=False, invoice=True)
    canned = json.dumps({
        "invoice_no": "INV-EUR", "cif_usd": 732.0, "custom_val_currency": "EUR",
        "confidence": 0.93, "source_page": 1,
        "source_text_or_visual_reason": "Total 732 EUR",
    })
    _patch_gateway(monkeypatch, [canned])

    res = vision_extractor.run_image_only_cif_fallback(out, "batch1")
    assert res["wrote"] is False  # USD-only — non-USD invoice withheld
    audit = _read_audit(out)
    assert audit.get("dhl_precheck", {}).get("invoice_cif_total_usd") is None
    r = resolve_cif(audit)
    assert r["cif_state"] == CIF_UNKNOWN
    assert r["cif_usd"] is None  # never fabricated 0.0
    doc = audit["vision_extraction"]["runs"][-1]["documents"][-1]
    assert doc["write"] == "withheld_non_usd_invoice(EUR)"


def test_orchestrator_blank_currency_invoice_withheld_stays_unknown(tmp_path, monkeypatch):
    """An invoice with a USD-named amount but a BLANK / unreadable currency is
    never assumed USD — the invoice path enforces the same USD-only discipline as
    the waybill path. CIF stays UNKNOWN. Regression for the invoice blank-currency
    gate (the silent non-USD-as-USD write hole found in review)."""
    out = _make_batch(tmp_path, awb=False, invoice=True)
    canned = json.dumps({
        "invoice_no": "INV-NOCUR", "cif_usd": 732.0, "confidence": 0.93,
        "source_page": 1, "source_text_or_visual_reason": "Total 732 (currency unreadable)",
    })
    _patch_gateway(monkeypatch, [canned])

    res = vision_extractor.run_image_only_cif_fallback(out, "batch1")
    assert res["wrote"] is False  # blank currency never assumed USD
    audit = _read_audit(out)
    assert audit.get("dhl_precheck", {}).get("invoice_cif_total_usd") is None
    r = resolve_cif(audit)
    assert r["cif_state"] == CIF_UNKNOWN
    assert r["cif_usd"] is None  # never fabricated 0.0
    doc = audit["vision_extraction"]["runs"][-1]["documents"][-1]
    assert doc["write"] == "withheld_unknown_currency_invoice"


def test_orchestrator_last_method_none_on_full_skip_run(tmp_path, monkeypatch):
    """last_method honesty: a run in which every document is skipped (no model
    call this run) records last_method None — never a stale 'vision_llm' that
    falsely implies a model was invoked. Regression for the provenance fix."""
    out = _make_batch(tmp_path, awb=True)
    # First run attempts + fails → records the file signature in attempted_signatures.
    _patch_gateway(monkeypatch, [None, None])
    vision_extractor.run_image_only_cif_fallback(out, "batch1")
    audit = _read_audit(out)
    assert audit["vision_extraction"]["last_method"] == "failed"  # a method WAS tried

    # Second run: same file version → fully skipped, no model call this run.
    calls = _patch_gateway(monkeypatch, [json.dumps({
        "custom_val_amount": 732.0, "custom_val_currency": "USD", "confidence": 0.9,
        "source_page": 1, "source_text_or_visual_reason": "x",
    })])
    vision_extractor.run_image_only_cif_fallback(out, "batch1")
    assert calls["n"] == 0  # retry-safety: nothing called this run
    audit = _read_audit(out)
    assert audit["vision_extraction"]["last_method"] is None  # honest: no method this run


def test_resolver_unknown_is_none_not_zero():
    """Direct contract pin: an empty audit resolves UNKNOWN with cif_usd None."""
    r = resolve_cif({"invoice_names": ["x.pdf"]})
    assert r["cif_state"] == CIF_UNKNOWN
    assert r["cif_usd"] is None
    assert r["extraction_gap"] is not None
