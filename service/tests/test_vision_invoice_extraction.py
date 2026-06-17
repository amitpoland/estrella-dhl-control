"""
test_vision_invoice_extraction.py — advisory image-only invoice recovery layer.

Covers ``vision_extractor`` functions that recover purchase-accounting inputs
(supplier / FOB / goods lines) from an image-only commercial invoice into the
ADVISORY ``audit["vision_invoice"]`` proposal — the layer that lets an operator
later unblock PZ for a shipment whose invoice never parsed:

  * validate_invoice_extraction        — schema validation, itemization flag
  * _merge_vision_invoice              — sticky operator_confirmed + field-merge
  * run_image_only_invoice_extraction  — orchestrator: image-only gating,
                                         engine-already-parsed no-op, retry
                                         safety, engine-authority untouched
  * audit_merge.merge_regenerated_audit preserving vision_invoice (incl. a
    sticky operator_confirmed=true) across an engine regeneration

All AI is monkeypatched — no network. Synthetic PDFs are built with PyMuPDF.

Authority isolation is pinned separately in
``test_vision_invoice_negative_scope`` — this module pins the extraction /
persistence behaviour and the "engine authority untouched" invariant.
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
from app.services import audit_merge


# ── PDF builders ──────────────────────────────────────────────────────────────

def _make_image_only_pdf(path: Path) -> None:
    """Vector content, NO extractable text — stands in for a scanned invoice."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(40, 40, 555, 800), color=(0, 0, 0), fill=(0.85, 0.85, 0.85))
    page.draw_rect(fitz.Rect(80, 120, 515, 300), color=(0.2, 0.2, 0.2))
    doc.save(str(path))
    doc.close()


def _patch_gateway(monkeypatch, responses):
    monkeypatch.setattr(ai_gateway, "is_available", lambda: True)
    seq = list(responses)
    calls = {"n": 0}

    def fake_call_vision(**kwargs):
        i = calls["n"]
        calls["n"] += 1
        return seq[i] if i < len(seq) else None

    monkeypatch.setattr(ai_gateway, "call_vision", fake_call_vision)
    return calls


_GOOD_INVOICE_JSON = json.dumps({
    "supplier": "GLOBAL JEWELLERY LLC",
    "invoice_no": "INV-122",
    "currency": "USD",
    "fob_usd": 700.0,
    "itemization_available": True,
    "line_items": [
        {"description": "GOLD RING 18K", "hsn": "71131900", "quantity": 2,
         "unit_price": 200, "total": 400, "gross_weight_g": 12.5, "net_weight_g": 11.0},
        {"description": "GOLD PENDANT", "hsn": "71131900", "quantity": 1,
         "unit_price": 300, "total": 300},
    ],
    "confidence": 0.88,
    "source_page": 1,
    "source_reason": "Description / Qty / Amount table",
})


# ══════════════════════════════════════════════════════════════════════════════
# validate_invoice_extraction
# ══════════════════════════════════════════════════════════════════════════════

def test_validate_keeps_clean_line_items():
    clean, errs = vision_extractor.validate_invoice_extraction(json.loads(_GOOD_INVOICE_JSON))
    assert clean["supplier"] == "GLOBAL JEWELLERY LLC"
    assert clean["currency"] == "USD"
    assert clean["fob_usd"] == 700.0
    assert len(clean["line_items"]) == 2
    assert clean["line_items"][0]["hsn"] == "71131900"
    assert clean["line_items"][0]["total_usd"] == 400.0
    assert clean["itemization_unavailable"] is False
    assert errs == []


def test_validate_drops_numberless_line_item():
    clean, errs = vision_extractor.validate_invoice_extraction({
        "itemization_available": True,
        "line_items": [
            {"description": "REAL ROW", "quantity": 1, "total": 50},
            {"description": "JUST A LABEL, NO NUMBERS"},   # dropped
        ],
        "confidence": 0.7,
    })
    assert len(clean["line_items"]) == 1
    assert clean["itemization_unavailable"] is False
    assert any("line item" in e for e in errs)


def test_validate_itemization_unavailable_when_no_rows():
    clean, _ = vision_extractor.validate_invoice_extraction({
        "supplier": "ACME", "itemization_available": False,
        "line_items": [], "confidence": 0.6,
    })
    assert clean["line_items"] == []
    assert clean["itemization_unavailable"] is True
    # supplier-only is still a usable recovery (handled at orchestrator level).
    assert clean["supplier"] == "ACME"


def test_validate_never_keeps_zero_fob():
    clean, _ = vision_extractor.validate_invoice_extraction(
        {"fob_usd": 0, "confidence": 0.9, "itemization_available": False, "line_items": []}
    )
    assert "fob_usd" not in clean  # zero is not a value, never fabricated


def test_validate_defaults_confidence_when_missing():
    clean, errs = vision_extractor.validate_invoice_extraction(
        {"supplier": "X", "line_items": [], "itemization_available": False}
    )
    assert clean["confidence"] == 0.0
    assert any("confidence" in e for e in errs)


# ══════════════════════════════════════════════════════════════════════════════
# _merge_vision_invoice — sticky + field-merge
# ══════════════════════════════════════════════════════════════════════════════

def _prov(fields, conf=0.88):
    return {
        "extraction_method": "vision_llm", "model_attempt": "primary",
        "extraction_confidence": conf, "source_file": "inv_122.pdf",
        "source_reason": "table", "validation_errors": [], "fields": fields,
    }


def test_merge_writes_advisory_block_operator_unconfirmed():
    audit = {}
    clean, _ = vision_extractor.validate_invoice_extraction(json.loads(_GOOD_INVOICE_JSON))
    wrote = vision_extractor._merge_vision_invoice(audit, clean, _prov(clean))
    assert wrote is True
    vi = audit["vision_invoice"]
    assert vi["operator_confirmed"] is False
    assert vi["source"] == "vision_llm"
    assert vi["supplier"] == "GLOBAL JEWELLERY LLC"
    assert vi["fob_usd"] == 700.0
    assert len(vi["line_items"]) == 2
    assert vi["itemization_unavailable"] is False
    assert "extracted_at" in vi


def test_merge_is_sticky_on_operator_confirmed():
    audit = {"vision_invoice": {"operator_confirmed": True, "supplier": "OPERATOR PICK",
                                "fob_usd": 1234.0, "line_items": []}}
    clean, _ = vision_extractor.validate_invoice_extraction(json.loads(_GOOD_INVOICE_JSON))
    wrote = vision_extractor._merge_vision_invoice(audit, clean, _prov(clean))
    assert wrote is False  # confirmed proposal is owned by the operator
    # Untouched — machine extraction did NOT overwrite the operator's value.
    assert audit["vision_invoice"]["supplier"] == "OPERATOR PICK"
    assert audit["vision_invoice"]["fob_usd"] == 1234.0


def test_merge_field_merge_keeps_prior_scalar_when_new_is_null():
    audit = {"vision_invoice": {"operator_confirmed": False, "supplier": "PRIOR SUPPLIER",
                                "line_items": []}}
    # New run reads FOB (in USD) but NOT supplier → prior supplier must survive.
    clean = {"fob_usd": 500.0, "currency": "USD", "line_items": [],
             "itemization_unavailable": True, "confidence": 0.7}
    vision_extractor._merge_vision_invoice(audit, clean, _prov(clean, conf=0.7))
    vi = audit["vision_invoice"]
    assert vi["supplier"] == "PRIOR SUPPLIER"  # not lost
    assert vi["fob_usd"] == 500.0              # new value applied
    assert vi["operator_confirmed"] is False


def test_merge_withholds_fob_when_currency_not_usd():
    """USD-only discipline: a FOB figure read under an unknown / non-USD currency
    must NOT be written as fob_usd — mirrors the CIF fallback's USD gate. An
    unknown currency is not USD; mislabelling a foreign amount as dollars would
    feed a wrong purchase-accounting value downstream."""
    # Unknown currency → withhold
    audit = {"vision_invoice": {"operator_confirmed": False, "line_items": []}}
    clean = {"fob_usd": 900.0, "line_items": [], "confidence": 0.8}  # no currency
    vision_extractor._merge_vision_invoice(audit, clean, _prov(clean, conf=0.8))
    assert "fob_usd" not in audit["vision_invoice"], "unknown currency must withhold fob_usd"

    # Explicit non-USD currency → withhold
    audit2 = {"vision_invoice": {"operator_confirmed": False, "line_items": []}}
    clean2 = {"fob_usd": 900.0, "currency": "EUR", "line_items": [], "confidence": 0.8}
    vision_extractor._merge_vision_invoice(audit2, clean2, _prov(clean2, conf=0.8))
    assert "fob_usd" not in audit2["vision_invoice"], "EUR must not become fob_usd"
    assert audit2["vision_invoice"]["currency"] == "EUR"  # currency itself is recorded

    # A prior USD fob is left untouched when a later run reads a non-USD currency.
    audit3 = {"vision_invoice": {"operator_confirmed": False, "fob_usd": 700.0,
                                 "currency": "USD", "line_items": []}}
    clean3 = {"fob_usd": 900.0, "currency": "EUR", "line_items": [], "confidence": 0.8}
    vision_extractor._merge_vision_invoice(audit3, clean3, _prov(clean3, conf=0.8))
    assert audit3["vision_invoice"]["fob_usd"] == 700.0  # prior USD value preserved


# ══════════════════════════════════════════════════════════════════════════════
# run_image_only_invoice_extraction — orchestrator
# ══════════════════════════════════════════════════════════════════════════════

def _batch_dir(tmp_path, audit: dict) -> Path:
    out = tmp_path / "batch"
    (out / "source" / "invoices").mkdir(parents=True)
    (out / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return out


def test_orchestrator_writes_proposal_for_image_only_invoice(tmp_path, monkeypatch):
    _patch_gateway(monkeypatch, [_GOOD_INVOICE_JSON])
    audit = {"inputs": {"invoices": ["inv_122.pdf"]}, "invoice_totals": {}, "rows": [],
             "status": "failed"}
    out = _batch_dir(tmp_path, audit)
    _make_image_only_pdf(out / "source" / "invoices" / "inv_122.pdf")

    res = vision_extractor.run_image_only_invoice_extraction(out, "B1")
    assert res["ran"] is True and res["wrote"] is True

    written = json.loads((out / "audit.json").read_text(encoding="utf-8"))
    vi = written["vision_invoice"]
    assert vi["operator_confirmed"] is False
    assert vi["supplier"] == "GLOBAL JEWELLERY LLC"
    assert len(vi["line_items"]) == 2
    assert vi["itemization_unavailable"] is False


def test_orchestrator_leaves_engine_authority_untouched(tmp_path, monkeypatch):
    """The advisory layer must NEVER mutate engine authority — invoice_totals,
    rows, customs_declaration stay byte-identical (process_batch inputs unchanged,
    so the engine's failed state is preserved)."""
    _patch_gateway(monkeypatch, [_GOOD_INVOICE_JSON])
    audit = {
        "inputs": {"invoices": ["inv_122.pdf"]},
        "invoice_totals": {"total_fob_usd": 0, "total_cif_usd": 0},
        "rows": [],
        "customs_declaration": {"sad_invoice_value_usd": 0, "cn_code": "71131900"},
        "status": "failed",
        "engine_error": "FOB USD = 0.00 — cannot compute freight share",
    }
    out = _batch_dir(tmp_path, audit)
    _make_image_only_pdf(out / "source" / "invoices" / "inv_122.pdf")

    before = json.loads((out / "audit.json").read_text(encoding="utf-8"))
    vision_extractor.run_image_only_invoice_extraction(out, "B1")
    after = json.loads((out / "audit.json").read_text(encoding="utf-8"))

    assert after["invoice_totals"] == before["invoice_totals"]
    assert after["rows"] == before["rows"]
    assert after["customs_declaration"] == before["customs_declaration"]
    assert after["status"] == "failed"
    assert after["engine_error"] == before["engine_error"]
    assert "vision_invoice" in after  # only NEW key added


def test_orchestrator_noop_when_engine_already_parsed(tmp_path, monkeypatch):
    calls = _patch_gateway(monkeypatch, [_GOOD_INVOICE_JSON])
    audit = {"invoice_totals": {"total_fob_usd": 700}, "rows": [{"x": 1}]}
    out = _batch_dir(tmp_path, audit)
    _make_image_only_pdf(out / "source" / "invoices" / "inv_122.pdf")

    res = vision_extractor.run_image_only_invoice_extraction(out, "B1")
    assert res["ran"] is False
    assert "already parsed" in res["reason"]
    assert calls["n"] == 0  # no vision call when not needed


def test_orchestrator_noop_when_operator_confirmed(tmp_path, monkeypatch):
    calls = _patch_gateway(monkeypatch, [_GOOD_INVOICE_JSON])
    audit = {"invoice_totals": {}, "rows": [],
             "vision_invoice": {"operator_confirmed": True, "supplier": "LOCKED"}}
    out = _batch_dir(tmp_path, audit)
    _make_image_only_pdf(out / "source" / "invoices" / "inv_122.pdf")

    res = vision_extractor.run_image_only_invoice_extraction(out, "B1")
    assert res["ran"] is False
    assert "operator_confirmed" in res["reason"]
    assert calls["n"] == 0


def test_orchestrator_retry_safety_skips_same_version(tmp_path, monkeypatch):
    _patch_gateway(monkeypatch, [_GOOD_INVOICE_JSON])
    audit = {"invoice_totals": {}, "rows": []}
    out = _batch_dir(tmp_path, audit)
    _make_image_only_pdf(out / "source" / "invoices" / "inv_122.pdf")

    r1 = vision_extractor.run_image_only_invoice_extraction(out, "B1")
    assert r1["wrote"] is True

    # Second run, same file version → no second model call, recorded as skipped.
    calls2 = _patch_gateway(monkeypatch, [_GOOD_INVOICE_JSON])
    r2 = vision_extractor.run_image_only_invoice_extraction(out, "B1")
    assert calls2["n"] == 0
    assert any(d.get("skipped") == "already_attempted_this_version"
               for d in r2["documents"])


# ══════════════════════════════════════════════════════════════════════════════
# audit_merge — vision_invoice survives engine regeneration
# ══════════════════════════════════════════════════════════════════════════════

def test_vision_invoice_in_preserved_keys():
    assert "vision_invoice" in audit_merge.PRESERVED_KEYS


def test_regeneration_preserves_confirmed_proposal():
    existing = {
        "rows": [{"old": 1}],
        "vision_invoice": {"operator_confirmed": True, "supplier": "OPERATOR PICK",
                           "fob_usd": 700.0, "line_items": [{"description": "RING"}]},
    }
    # Engine regen produces fresh rows and (as always) NO vision_invoice key.
    regenerated = {"rows": [{"new": 2}], "totals": {"x": 1}}
    merged = audit_merge.merge_regenerated_audit(existing, regenerated)

    assert merged["rows"] == [{"new": 2}]                 # engine output wins
    assert merged["vision_invoice"]["operator_confirmed"] is True  # preserved
    assert merged["vision_invoice"]["supplier"] == "OPERATOR PICK"
