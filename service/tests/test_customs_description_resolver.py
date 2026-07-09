"""
Regression tests for the canonical customs Product Description resolver
(description_engine.resolve_product_description_for_customs) and the
pre-generation guard `descriptions_missing_for_customs`.

Business rules under test:
  - single authority for V1 + V2 (shared route POST /dhl/generate-description)
  - source priority: shipment correction -> product_descriptions(source='manual')
    -> non-generic invoice classifier -> STOP missing_description
  - NEVER return generic fallback ("Wyrób jubilerski" / "metal szlachetny")
  - forbidden-token read-back guard remains active (not weakened)
"""
import re
from pathlib import Path

import pytest

from app.services import description_engine as de

GENERIC = "Wyrób jubilerski"
PLACEHOLDER_DESC = "(placeholder — PZ engine will populate)"
REAL_RING_DESC = "PCS, 14KT Gold,Stud Jewelry DIA&CLS Ring"


@pytest.fixture
def no_product_master(monkeypatch):
    """Default: product_descriptions has no approved row for the code."""
    monkeypatch.setattr(de.ddb, "get_product_description", lambda pc: None)


def _row(product_code="EJL/1", description=REAL_RING_DESC, invoice="EJL-1", pos=1, item_type=""):
    return {
        "product_code": product_code,
        "original_description": description,
        "description": description,
        "invoice_number": invoice,
        "line_position": pos,
        "item_type": item_type,
    }


# ── source priority ──────────────────────────────────────────────────────────

def test_resolver_uses_shipment_correction_first(no_product_master):
    res = de.resolve_product_description_for_customs(
        product_code="EJL/1",
        invoice_row=_row(),
        corrections={"EJL/1": {"description_pl": "Pierścionek z 14-karatowego złota z diamentami"}},
    )
    assert res["status"] == "ok"
    assert res["source"] == "operator_correction_shipment"
    assert res["description_pl"] == "Pierścionek z 14-karatowego złota z diamentami"


def test_resolver_uses_approved_product_master_manual(monkeypatch):
    monkeypatch.setattr(
        de.ddb, "get_product_description",
        lambda pc: {"source": "manual", "description_pl": "Bransoletka ze złota", "material_pl": "złoto"},
    )
    res = de.resolve_product_description_for_customs(
        product_code="EJL/2", invoice_row=_row(product_code="EJL/2"), corrections={},
    )
    assert res["status"] == "ok"
    assert res["source"] == "product_master_manual"
    assert res["description_pl"] == "Bransoletka ze złota"


def test_resolver_ignores_non_manual_product_description(monkeypatch):
    # An 'auto' row (possibly poisoned) is NOT an approved authority — must fall
    # through to the classifier, not be trusted.
    monkeypatch.setattr(
        de.ddb, "get_product_description",
        lambda pc: {"source": "auto", "description_pl": GENERIC},
    )
    res = de.resolve_product_description_for_customs(
        product_code="EJL/3", invoice_row=_row(product_code="EJL/3"), corrections={},
    )
    # real ring desc classifies fine -> classifier source, non-generic
    assert res["status"] == "ok"
    assert res["source"] == "invoice_classifier"
    assert GENERIC not in (res["description_pl"] or "")


# ── never fabricate ──────────────────────────────────────────────────────────

def test_resolver_blocks_generic_placeholder_row(no_product_master):
    res = de.resolve_product_description_for_customs(
        product_code="EJL/380-1",
        invoice_row=_row(product_code="EJL/380-1", description=PLACEHOLDER_DESC),
        corrections={},
    )
    assert res["status"] == "missing_description"
    assert res["source"] is None
    assert res["description_pl"] is None
    assert res["forbidden_token"]  # reports which generic token would have appeared


def test_resolver_never_returns_generic_text(no_product_master):
    # Real classifiable line -> ok and definitely not the generic fallback.
    res = de.resolve_product_description_for_customs(
        product_code="EJL/1", invoice_row=_row(), corrections={},
    )
    assert res["status"] == "ok"
    assert res["source"] == "invoice_classifier"
    assert GENERIC not in (res["description_pl"] or "")
    assert "metal szlachetny" not in (res["description_pl"] or "")


def test_resolver_rejects_correction_that_is_still_generic(no_product_master):
    res = de.resolve_product_description_for_customs(
        product_code="EJL/1",
        invoice_row=_row(description=PLACEHOLDER_DESC),
        corrections={"EJL/1": {"description_pl": GENERIC}},
    )
    assert res["status"] == "missing_description"


def test_resolver_missing_when_no_code(no_product_master):
    res = de.resolve_product_description_for_customs(
        product_code="", invoice_row=_row(product_code=""), corrections={},
    )
    assert res["status"] == "missing_description"


# ── batch guard helper ───────────────────────────────────────────────────────

def test_find_missing_flags_placeholder_and_passes_clean(no_product_master):
    rows = [
        _row(product_code="EJL/378-1", description=REAL_RING_DESC),
        _row(product_code="EJL/380-1", description=PLACEHOLDER_DESC, invoice="EJL-380", pos=1),
    ]
    missing = de.find_missing_customs_descriptions(rows, {})
    assert len(missing) == 1
    assert missing[0]["product_code"] == "EJL/380-1"
    assert missing[0]["invoice"] == "EJL-380"
    assert missing[0]["reason"]
    assert "suggested_correction_route" in missing[0]


def test_find_missing_empty_when_all_clean(no_product_master):
    rows = [
        _row(product_code="EJL/378-1", description=REAL_RING_DESC),
        _row(product_code="EJL/379-1", description="PCS, 18KT Gold,LGD Gold Stud Jewell Bracelet"),
    ]
    assert de.find_missing_customs_descriptions(rows, {}) == []


# ── guard-active invariants (forbidden-token read-back NOT weakened) ──────────

def test_generate_route_still_has_forbidden_token_readback():
    src = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_dhl_clearance.py"
    text = src.read_text(encoding="utf-8")
    assert "polish_desc_forbidden_tokens" in text
    assert "descriptions_missing_for_customs" in text  # new pre-gen guard present
    # both generate routes call the STAMPING resolver (generation source, not
    # validation-only) — V1 and V2 share this exact backend path.
    assert text.count("resolve_and_stamp_customs_descriptions") >= 2


def test_forbidden_tokens_cover_generic_strings():
    assert GENERIC in de.FORBIDDEN_DESC_TOKENS
    assert "metal szlachetny" in de.FORBIDDEN_DESC_TOKENS


# ── authority REPLACEMENT: resolver is the generation source (verdict A) ──────

def test_resolve_and_stamp_marks_approved_rows(no_product_master):
    rows = [_row(product_code="EJL/1", description=REAL_RING_DESC)]
    missing = de.resolve_and_stamp_customs_descriptions(rows, {})
    assert missing == []
    r = rows[0]
    assert r["_desc_authoritative"] is True
    assert r["_resolved_source"] == "invoice_classifier"
    assert r["_resolved_description_pl"]
    assert GENERIC not in r["_resolved_description_pl"]


def test_resolve_and_stamp_does_not_stamp_missing(no_product_master):
    rows = [_row(product_code="EJL/380-1", description=PLACEHOLDER_DESC)]
    missing = de.resolve_and_stamp_customs_descriptions(rows, {})
    assert len(missing) == 1
    assert "_resolved_description_pl" not in rows[0]
    assert "_desc_authoritative" not in rows[0]


def test_audit_rows_and_sad_consume_resolver_stamp(no_product_master):
    # process_batch_items feeds BOTH audit rows and the SAD JSON. Prove it emits
    # the stamped resolver value, not the classifier's own text.
    cde = de._load_customs_engine()
    assert cde is not None, "customs_description_engine must be importable"
    row = {
        "product_code": "EJL/9", "invoice_number": "EJL-9", "line_position": 1,
        "description": REAL_RING_DESC, "quantity": 1, "line_total": 100,
        "_desc_authoritative": True,
        "_resolved_description_pl": "ZATWIERDZONY OPIS PL",
        "_resolved_material_pl": "złoto próby 585",
        "_resolved_name_pl": "Pierścionek",
        "_resolved_source": "product_master_manual",
    }
    lines = cde.process_batch_items({"rows": [row]})
    assert len(lines) == 1
    assert lines[0]["polish_customs_description"] == "ZATWIERDZONY OPIS PL"
    assert lines[0]["material"] == "złoto próby 585"
    assert lines[0]["_desc_authoritative"] is True


def test_process_batch_items_unstamped_falls_back_to_classifier():
    # Golden-safety: direct/unstamped engine calls behave exactly as before.
    cde = de._load_customs_engine()
    assert cde is not None
    lines = cde.process_batch_items({"rows": [{
        "product_code": "EJL/8", "invoice_number": "EJL-8", "line_position": 1,
        "description": REAL_RING_DESC, "quantity": 1, "line_total": 100,
    }]})
    assert lines[0]["_desc_authoritative"] is False
    assert "Pier" in lines[0]["polish_customs_description"]  # classifier authored
    assert GENERIC not in lines[0]["polish_customs_description"]


def test_pdf_authoritative_overrides_poisoned_auto_row(monkeypatch):
    # A poisoned source='auto' product_descriptions row must NOT override the
    # resolver-approved value at PDF render time.
    monkeypatch.setattr(
        de.ddb, "get_product_description",
        lambda pc: {"source": "auto", "description_pl": GENERIC, "description_line": GENERIC},
    )
    block = de.get_description_block(
        "EJL/7", "RING", description_en="Ring", authoritative_pl="Pierścionek ze złota próby 585",
    )
    assert block["source"] == "resolver"
    assert block["description_pl"] == "Pierścionek ze złota próby 585"
    assert GENERIC not in block["description_line"]


def test_get_description_block_without_authoritative_unchanged(monkeypatch):
    # Other callers (e.g. proforma birth path) are unaffected: with no
    # authoritative_pl, an existing row is still returned as before.
    sentinel = {"source": "manual", "description_pl": "X", "description_line": "X"}
    monkeypatch.setattr(de.ddb, "get_product_description", lambda pc: sentinel)
    block = de.get_description_block("EJL/6", "RING", description_en="Ring")
    assert block is sentinel


def test_pdf_renderer_wires_authoritative_pl():
    from app.core.config import settings
    engine = Path(settings.engine_dir) / "customs_description_engine.py"
    text = engine.read_text(encoding="utf-8")
    # process_batch_items consumes the stamp; the PDF renderer forwards it.
    assert "_desc_authoritative" in text
    assert "authoritative_pl" in text
    assert "_resolved_description_pl" in text


# ── FUNCTION-INTERNAL guard: covers ALL callers incl. automation ──────────────

import json  # noqa: E402


def _engine():
    cde = de._load_customs_engine()
    assert cde is not None, "customs_description_engine must be importable"
    return cde


def test_engine_package_blocks_missing_before_any_write(tmp_path, monkeypatch, no_product_master):
    cde = _engine()
    called = {"pdf": False, "sad": False}
    monkeypatch.setattr(cde, "generate_polish_description_pdf",
                        lambda *a, **k: called.__setitem__("pdf", True) or {"generated": True})
    monkeypatch.setattr(cde, "generate_sad_ready_json",
                        lambda *a, **k: called.__setitem__("sad", True) or {"generated": True})
    batch = {"rows": [{
        "product_code": "EJL/380-1", "invoice_number": "E380", "line_position": 1,
        "description": PLACEHOLDER_DESC, "quantity": 0, "line_total": 0,
    }]}
    pkg = cde.generate_customs_description_package(batch, "AWB1", str(tmp_path))
    assert pkg["blocked"] is True
    assert pkg["guard"] == "descriptions_missing_for_customs"
    assert pkg["pdf"]["generated"] is False and pkg["json"]["generated"] is False
    assert called == {"pdf": False, "sad": False}  # blocked BEFORE any write
    assert pkg["missing"][0]["product_code"] == "EJL/380-1"


def test_engine_readback_unlinks_pdf_and_sad_on_forbidden(tmp_path, monkeypatch, no_product_master):
    cde = _engine()
    pdf_path = tmp_path / "desc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 not-a-real-pdf")  # pdfplumber fails -> [] (fine)
    sad_path = tmp_path / "sad.json"
    sad_path.write_text(json.dumps({"lines": [
        {"polish_customs_description": "Wyrób jubilerski — wyrób jubilerski do noszenia.",
         "material": "metal szlachetny"}
    ]}), encoding="utf-8")
    monkeypatch.setattr(cde, "generate_polish_description_pdf",
                        lambda *a, **k: {"generated": True, "output_path": str(pdf_path), "filename": "desc.pdf"})
    monkeypatch.setattr(cde, "generate_sad_ready_json",
                        lambda *a, **k: {"generated": True, "output_path": str(sad_path), "filename": "sad.json"})
    batch = {"rows": [{
        "product_code": "EJL/1", "invoice_number": "E1", "line_position": 1,
        "description": REAL_RING_DESC, "quantity": 1, "line_total": 100,
    }]}
    pkg = cde.generate_customs_description_package(batch, "AWB2", str(tmp_path))
    assert pkg["blocked"] is True
    assert pkg["guard"] == "polish_desc_forbidden_tokens"
    assert "Wyrób jubilerski" in pkg["tokens"]
    assert not pdf_path.exists()   # bad PDF unlinked
    assert not sad_path.exists()   # SAD-orphan fixed: bad SAD JSON also unlinked


def test_engine_sad_scan_ignores_unknown_item_type(tmp_path):
    # "UNKNOWN" as item_type metadata must NOT false-block; only description
    # fields are scanned.
    cde = _engine()
    p = tmp_path / "sad2.json"
    p.write_text(json.dumps({"lines": [
        {"item_type": "UNKNOWN", "polish_customs_description": "Pierścionek ze złota", "material": "złoto"}
    ]}), encoding="utf-8")
    assert cde._scan_sad_json_for_forbidden(str(p), de.FORBIDDEN_DESC_TOKENS) == []


def test_enforce_guards_false_bypasses_internal_guard(tmp_path, monkeypatch, no_product_master):
    # Golden/CLI reuse can opt out; default stays protective.
    cde = _engine()
    monkeypatch.setattr(cde, "generate_polish_description_pdf",
                        lambda *a, **k: {"generated": True, "output_path": None, "filename": "x"})
    monkeypatch.setattr(cde, "generate_sad_ready_json",
                        lambda *a, **k: {"generated": True, "output_path": None, "filename": "y"})
    batch = {"rows": [{"product_code": "EJL/380-1", "invoice_number": "E380",
                       "line_position": 1, "description": PLACEHOLDER_DESC,
                       "quantity": 0, "line_total": 0}]}
    pkg = cde.generate_customs_description_package(batch, "AWB3", str(tmp_path), enforce_guards=False)
    assert not pkg.get("blocked")  # guard bypassed by explicit opt-out


# ── all callers covered / parity ──────────────────────────────────────────────

def test_both_routes_translate_engine_block():
    src = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_dhl_clearance.py"
    text = src.read_text(encoding="utf-8")
    assert text.count("_translate_blocked_package(batch_id, pkg)") >= 2
    assert "descriptions_missing_for_customs" in text
    assert text.count("polish_desc_forbidden_tokens") >= 2  # translate + backstop


def test_route_readback_uses_shared_constant():
    src = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_dhl_clearance.py"
    text = src.read_text(encoding="utf-8")
    assert "from ..services.description_engine import PDF_FORBIDDEN_TOKENS" in text
    assert de.PDF_FORBIDDEN_TOKENS[-1] == "■"
    assert "wyrób jubilerski" in de.PDF_FORBIDDEN_TOKENS  # lowercase covered


def test_automation_callers_fail_safe_on_block():
    from app.core.config import settings
    mon = Path(__file__).resolve().parents[1] / "app" / "services" / "active_shipment_monitor.py"
    mtext = mon.read_text(encoding="utf-8")
    assert 'get("blocked")' in mtext
    # Within the generation block, the blocked-return must precede marking the
    # batch generated. Scope to text after the engine call to avoid unrelated
    # earlier occurrences of polish_desc_generated_at elsewhere in the module.
    seg = mtext[mtext.index("generate_customs_description_package("):]
    assert 'get("blocked")' in seg
    assert seg.index('get("blocked")') < seg.index("polish_desc_generated_at")
    dch = Path(settings.engine_dir) / "dhl_clearance_handler.py"
    assert 'get("blocked")' in dch.read_text(encoding="utf-8")
