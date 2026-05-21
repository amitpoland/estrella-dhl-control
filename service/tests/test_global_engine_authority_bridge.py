"""Global PZ Engine Parser Quantity Fix — Authority Bridge tests (2026-05-21).

Validates `_try_invoice_from_authority_rows`, `_validate_authority_rows`,
and `_build_invoice_from_authority_rows` in `pz_import_processor`.

The bridge consumes PR #269 invoice-position rows from audit.json when the
engine would otherwise re-parse the source PDF (and fail on Global format).
Every failure mode must fall through cleanly to the legacy regex parser by
returning None — no exceptions, no silent partial data.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import pz_import_processor as p


# ── Fixture helpers ──────────────────────────────────────────────────────────

def _good_rows():
    """10 invoice-position rows mirroring the production fixture
    SHIPMENT_4789974092 — qty 245 (PCS 183 + PRS 62), FOB 3172."""
    return [
        {"line_position": 1, "quantity": 2.0,   "uom": "PCS", "line_total_usd": 604.0,  "unit_price": 302.0, "item_type": "BRACELET", "invoice_number": "088/2026-2027", "description_en": "09KT Gold Lab Grown Diamond Jewellery BRACELETS", "description_pl": "Bransoletki ze złota próby 375 z diamentami laboratoryjnymi", "hsn_code": ""},
        {"line_position": 2, "quantity": 23.0,  "uom": "PCS", "line_total_usd": 162.0,  "unit_price": 7.04,  "item_type": "PENDANT",  "invoice_number": "088/2026-2027", "description_en": "925 Silver CZ & Colour Stone Jewellery PENDANTS", "description_pl": "Wisiorki ze srebra próby 925 z cyrkoniami i kamieniami kolorowymi", "hsn_code": ""},
        {"line_position": 3, "quantity": 2.0,   "uom": "PCS", "line_total_usd": 46.0,   "unit_price": 23.0,  "item_type": "RING",     "invoice_number": "088/2026-2027", "description_en": "925 Silver Diamond & CZ Stud Jewellery RINGS", "description_pl": "Pierścionki ze srebra próby 925 z diamentami i cyrkoniami", "hsn_code": ""},
        {"line_position": 4, "quantity": 153.0, "uom": "PCS", "line_total_usd": 1065.0, "unit_price": 6.96,  "item_type": "BRACELET", "invoice_number": "088/2026-2027", "description_en": "925 Silver CZ Stud Jewellery BRACELETS", "description_pl": "Bransoletki ze srebra próby 925 z cyrkoniami", "hsn_code": ""},
        {"line_position": 5, "quantity": 2.0,   "uom": "PCS", "line_total_usd": 161.0,  "unit_price": 80.5,  "item_type": "RING",     "invoice_number": "088/2026-2027", "description_en": "925 Silver CZ Stud Jewellery RINGS", "description_pl": "Pierścionki ze srebra próby 925 z cyrkoniami", "hsn_code": ""},
        {"line_position": 6, "quantity": 1.0,   "uom": "PCS", "line_total_usd": 12.0,   "unit_price": 12.0,  "item_type": "RING",     "invoice_number": "088/2026-2027", "description_en": "925 Silver Plain Jewellery RINGS", "description_pl": "Pierścionki ze srebra próby 925", "hsn_code": ""},
        {"line_position": 7, "quantity": 1.0,   "uom": "PRS", "line_total_usd": 659.0,  "unit_price": 659.0, "item_type": "EARRING",  "invoice_number": "088/2026-2027", "description_en": "14KT Gold Lab Grown Diamond Jewellery EARRINGS", "description_pl": "Kolczyki ze złota próby 585 z diamentami laboratoryjnymi", "hsn_code": ""},
        {"line_position": 8, "quantity": 4.0,   "uom": "PRS", "line_total_usd": 58.0,   "unit_price": 14.5,  "item_type": "EARRING",  "invoice_number": "088/2026-2027", "description_en": "925 Silver CZ & Colour Stone Jewellery EARRINGS", "description_pl": "Kolczyki ze srebra próby 925 z cyrkoniami i kamieniami kolorowymi", "hsn_code": ""},
        {"line_position": 9, "quantity": 56.0,  "uom": "PRS", "line_total_usd": 400.0,  "unit_price": 7.14,  "item_type": "EARRING",  "invoice_number": "088/2026-2027", "description_en": "925 Silver CZ Stud Jewellery EARRINGS", "description_pl": "Kolczyki ze srebra próby 925 z cyrkoniami", "hsn_code": ""},
        {"line_position":10, "quantity": 1.0,   "uom": "PRS", "line_total_usd": 5.0,    "unit_price": 5.0,   "item_type": "EARRING",  "invoice_number": "088/2026-2027", "description_en": "925 Silver Plain Jewellery EARRINGS", "description_pl": "Kolczyki ze srebra próby 925", "hsn_code": ""},
    ]


def _good_audit(rows):
    return {
        "_rows_source": "invoice_positions_authority",
        "_customs_aggregation": {
            "source": "commercial_invoice_lines",
            "position_count": len(rows),
            "fob_sum_preserved": 3172.0,
        },
        "invoice_totals": {
            "total_fob_usd":       3172.0,
            "total_freight_usd":   125.0,
            "total_insurance_usd": 25.0,
            "total_cif_usd":       3322.0,
        },
        "rows": rows,
    }


def _layout(tmp_path: Path, audit: dict):
    """Create outputs/{batch}/source/invoices/inv.pdf + outputs/{batch}/audit.json
    layout. Returns the pdf path."""
    batch = tmp_path / "BATCH_X"
    inv_dir = batch / "source" / "invoices"
    inv_dir.mkdir(parents=True)
    pdf = inv_dir / "inv.pdf"
    pdf.write_bytes(b"%PDF-1.4 stub")
    (batch / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return pdf


# ── 1. Audit absent → None (fall through) ────────────────────────────────────
def test_returns_none_when_audit_missing(tmp_path):
    pdf = tmp_path / "BATCH_X" / "source" / "invoices" / "inv.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"stub")
    log = []
    assert p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log) is None


# ── 2. _rows_source mismatch (stale PR #267 aggregate) rejected ──────────────
def test_returns_none_when_rows_source_is_stale_aggregate(tmp_path):
    audit = _good_audit(_good_rows())
    audit["_rows_source"] = "packing_lines_aggregated_to_invoice_positions"
    pdf = _layout(tmp_path, audit)
    log = []
    assert p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log) is None


# ── 3. Empty rows → None ─────────────────────────────────────────────────────
def test_returns_none_when_rows_empty(tmp_path):
    audit = _good_audit([])
    pdf = _layout(tmp_path, audit)
    log = []
    assert p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log) is None


# ── 4. Forbidden tokens rejected ─────────────────────────────────────────────
@pytest.mark.parametrize("tok", [
    "UNKNOWN", "metal szlachetny", "Wyrób jubilerski",
    "grouped invoice aggregate", "wysadzany",
])
def test_returns_none_when_forbidden_token_present(tmp_path, tok):
    rows = _good_rows()
    rows[0]["description_en"] = f"foo {tok} bar"
    audit = _good_audit(rows)
    pdf = _layout(tmp_path, audit)
    log = []
    assert p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log) is None
    assert any("forbidden token" in l.lower() for l in log)


# ── 5. Zero qty or zero value rejected ───────────────────────────────────────
def test_returns_none_when_row_qty_zero(tmp_path):
    rows = _good_rows()
    rows[0]["quantity"] = 0
    audit = _good_audit(rows)
    pdf = _layout(tmp_path, audit)
    log = []
    assert p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log) is None


def test_returns_none_when_row_line_total_zero(tmp_path):
    rows = _good_rows()
    rows[0]["line_total_usd"] = 0
    audit = _good_audit(rows)
    pdf = _layout(tmp_path, audit)
    log = []
    assert p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log) is None


# ── 6. FOB drift > $1 rejected ───────────────────────────────────────────────
def test_returns_none_when_fob_drift_exceeds_one_dollar(tmp_path):
    rows = _good_rows()
    rows[0]["line_total_usd"] = 999999.0   # massive drift
    audit = _good_audit(rows)
    pdf = _layout(tmp_path, audit)
    log = []
    assert p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log) is None
    assert any("fob drift" in l.lower() for l in log)


def test_accepts_small_drift_under_one_dollar(tmp_path):
    rows = _good_rows()
    rows[0]["line_total_usd"] += 0.4   # rows sum drifts +0.40, still < $1
    audit = _good_audit(rows)
    pdf = _layout(tmp_path, audit)
    log = []
    res = p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log)
    assert res is not None


# ── 7. Happy path — production fixture shape ─────────────────────────────────
def test_returns_invoice_dict_on_production_fixture(tmp_path):
    audit = _good_audit(_good_rows())
    pdf = _layout(tmp_path, audit)
    log = []
    res = p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log)
    assert res is not None
    assert res["invoice_format"] == "global_jewellery"
    assert res["invoice_no"] == "088/2026-2027"
    assert res["_authority_source"] == "invoice_positions_authority"


# ── 8. items[] shape: count, qty sum, value sum ──────────────────────────────
def test_built_items_match_authority_totals(tmp_path):
    audit = _good_audit(_good_rows())
    pdf = _layout(tmp_path, audit)
    log = []
    res = p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log)
    assert len(res["items"]) == 10
    qty_sum = sum(it["quantity"] for it in res["items"])
    val_sum = sum(it["total_usd"] for it in res["items"])
    assert qty_sum == 245
    assert abs(val_sum - 3172.0) < 0.01


def test_freight_insurance_cif_carried_from_audit(tmp_path):
    audit = _good_audit(_good_rows())
    pdf = _layout(tmp_path, audit)
    log = []
    res = p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log)
    assert res["fob_usd"] == 3172.0
    assert res["freight_usd"] == 125.0
    assert res["insurance_usd"] == 25.0
    assert abs(res["cif_usd"] - 3322.0) < 0.01


# ── 9. PCS / PRS unit split preserved ────────────────────────────────────────
def test_pcs_prs_unit_split(tmp_path):
    audit = _good_audit(_good_rows())
    pdf = _layout(tmp_path, audit)
    log = []
    res = p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log)
    pcs = sum(it["quantity"] for it in res["items"] if it["unit"] == "PCS")
    prs = sum(it["quantity"] for it in res["items"] if it["unit"] == "PRS")
    assert pcs == 183
    assert prs == 62


# ── 10. Log carries [AUTHORITY-BRIDGE] marker ────────────────────────────────
def test_audit_bridge_logs_authority_marker(tmp_path):
    audit = _good_audit(_good_rows())
    pdf = _layout(tmp_path, audit)
    log = []
    p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log)
    assert any("[AUTHORITY-BRIDGE]" in l for l in log)


# ── 11. Malformed audit.json never raises — returns None ─────────────────────
def test_malformed_audit_falls_through_silently(tmp_path):
    batch = tmp_path / "BATCH_X"
    inv_dir = batch / "source" / "invoices"
    inv_dir.mkdir(parents=True)
    pdf = inv_dir / "inv.pdf"
    pdf.write_bytes(b"stub")
    (batch / "audit.json").write_text("{not valid json", encoding="utf-8")
    log = []
    assert p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log) is None
    # Bridge Persistence rename — diagnostic format is now
    # "[bridge_miss] reason=raised exception=..."
    assert any("reason=raised" in l for l in log) or any("reason=audit_file_absent" in l for l in log)


# ── 12. Non-list rows rejected ───────────────────────────────────────────────
def test_returns_none_when_rows_not_a_list(tmp_path):
    audit = _good_audit({})
    audit["rows"] = "not-a-list"
    pdf = _layout(tmp_path, audit)
    log = []
    assert p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log) is None
