"""Bridge FOB self-compute (2026-05-21).

When audit.invoice_totals.total_fob_usd is missing or zero, the bridge
must derive FOB from the row line_total_usd sum so calculate_landed
does not fail at "FOB USD = 0.00 — cannot compute freight share".
"""
from __future__ import annotations

import json
from pathlib import Path

import pz_import_processor as p


def _rows():
    return [
        {"line_position": 1, "quantity": 2.0,  "uom": "PCS", "line_total_usd": 604.0,
         "unit_price": 302.0, "item_type": "BRACELET", "invoice_number": "088/2026-2027",
         "description_en": "09KT Gold Lab Grown Diamond Jewellery BRACELETS",
         "description_pl": "Bransoletki", "hsn_code": ""},
        {"line_position": 2, "quantity": 23.0, "uom": "PCS", "line_total_usd": 162.0,
         "unit_price": 7.04,  "item_type": "PENDANT",  "invoice_number": "088/2026-2027",
         "description_en": "925 Silver CZ & Colour Stone Jewellery PENDANTS",
         "description_pl": "Wisiorki", "hsn_code": ""},
    ]


def _audit_no_totals(rows):
    return {
        "_rows_source": "invoice_positions_authority",
        "_pz_engine_authority_rows": rows,
        "_pz_engine_authority_meta": {
            "source": "invoice_positions_authority",
            "fob_sum_preserved": 766.0,
            "row_count": len(rows),
        },
        # invoice_totals deliberately absent — simulates the operator's
        # manual audit patch path and the fresh-batch path.
        "rows": rows,
    }


def _layout(tmp_path: Path, audit: dict) -> Path:
    batch = tmp_path / "BATCH_X"
    inv_dir = batch / "source" / "invoices"
    inv_dir.mkdir(parents=True)
    pdf = inv_dir / "inv.pdf"
    pdf.write_bytes(b"%PDF stub")
    (batch / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return pdf


def test_fob_derived_from_row_sum_when_invoice_totals_missing(tmp_path):
    audit = _audit_no_totals(_rows())
    pdf = _layout(tmp_path, audit)
    log = []
    res = p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log)
    assert res is not None
    assert res["fob_usd"] == 766.0
    assert any("FOB derived from authority rows" in l for l in log)


def test_fob_derived_when_invoice_totals_present_but_zero(tmp_path):
    audit = _audit_no_totals(_rows())
    audit["invoice_totals"] = {
        "total_fob_usd": 0,
        "total_freight_usd": 0,
        "total_insurance_usd": 0,
    }
    pdf = _layout(tmp_path, audit)
    log = []
    res = p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log)
    assert res is not None
    assert res["fob_usd"] == 766.0


def test_fob_from_invoice_totals_when_present_and_nonzero(tmp_path):
    audit = _audit_no_totals(_rows())
    # invoice_totals.total_fob_usd must equal row sum within $1 to pass
    # the bridge reconciler (PR #271 contract).
    audit["invoice_totals"] = {
        "total_fob_usd": 766.0,
        "total_freight_usd": 50.0,
        "total_insurance_usd": 10.0,
    }
    pdf = _layout(tmp_path, audit)
    log = []
    res = p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log)
    assert res is not None
    # Existing invoice_totals win — only self-compute when missing/zero.
    assert res["fob_usd"] == 766.0
    assert res["freight_usd"] == 50.0
    assert res["insurance_usd"] == 10.0
    assert not any("FOB derived from authority rows" in l for l in log)


def test_fob_falls_back_to_meta_when_rows_have_zero_totals(tmp_path):
    """Edge: rows present but each row.line_total_usd is zero (parser bug)
    should still allow FOB recovery from the meta sidecar."""
    rows = _rows()
    for r in rows:
        r["line_total_usd"] = 0
    # Validation now rejects zero-value rows (PR #271 contract). This
    # documents that meta_fob fallback only triggers when rows are valid
    # but invoice_totals is missing — not when rows themselves are broken.
    audit = _audit_no_totals(rows)
    pdf = _layout(tmp_path, audit)
    log = []
    res = p._try_invoice_from_authority_rows(str(pdf), "inv.pdf", log)
    # Validation rejects → bridge returns None.
    assert res is None
    assert any("validation_failed" in l for l in log)
