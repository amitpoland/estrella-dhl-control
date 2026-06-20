"""test_reprocess_parity_sales.py — reprocess-parity fixes for the sales lane.

Pins the two SAFE fixes (Gap #1 filter fallback, Gap #2 status flip):

  Gap #1  get_sales_packing_lines(physical_only=True) must return reparse-written
          rows (price_source='excel_symbol'/'') when the batch has NO canonical
          'packing_xlsx_value' rows — AND must still de-dup to the canonical row
          when both row types exist (no double-count regression).

  Gap #2  the reprocess sales branch flips shipment_documents.extraction_status
          to 'extracted' (mechanism via update_document_status + call-site grep).

Gap #3 (FK id scheme) intentionally NOT changed here — latent, not the symptom,
and risky against existing data. Gap #4 (draft sync) already present in reprocess.

Run: python -m pytest tests/test_reprocess_parity_sales.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import document_db as ddb


@pytest.fixture()
def docdb(tmp_path):
    ddb.init_document_db(tmp_path / "documents.db")
    return tmp_path


def _row(pc, dn, price, src, cur="EUR"):
    return {
        "client_name": "C", "client_ref": "", "product_code": pc, "design_no": dn,
        "bag_id": "", "quantity": 1.0, "remarks": "",
        "unit_price": price, "total_value": price, "currency": cur, "price_source": src,
    }


# ── Gap #1 ──────────────────────────────────────────────────────────────────

def test_physical_only_returns_reparse_rows_when_no_canonical(docdb):
    """Reparse-only batch (only excel_symbol/'' rows) — physical_only must
    surface them, not return []."""
    B = "BATCH_REPARSE_ONLY"
    ddb.store_sales_packing_lines("sd1", B, [
        _row("P1", "D1", 10.0, "excel_symbol"),
        _row("P2", "D2", 20.0, ""),
    ])
    phys = ddb.get_sales_packing_lines(B, physical_only=True)
    assert len(phys) == 2, "reparse rows must be visible to physical_only (Gap #1)"


def test_physical_only_dedups_when_both_row_types_exist(docdb):
    """Regression: a batch with BOTH packing_xlsx_value + excel_symbol per item
    must still return ONE canonical row per item — no double-count."""
    B = "BATCH_DUAL"
    ddb.store_sales_packing_lines("sd1", B, [
        _row("P1", "D1", 10.0, "packing_xlsx_value", cur="USD"),
        _row("P1", "D1", 15.0, "excel_symbol"),
    ])
    phys = ddb.get_sales_packing_lines(B, physical_only=True)
    assert len(phys) == 1, "physical_only must de-dup to the canonical row"
    assert phys[0]["price_source"] == "packing_xlsx_value"
    allrows = ddb.get_sales_packing_lines(B, physical_only=False)
    assert len(allrows) == 2, "non-physical must return all authority rows"


# ── Gap #2 ──────────────────────────────────────────────────────────────────

def test_update_document_status_flips_extraction_status(docdb):
    """Mechanism: update_document_status flips shipment_documents off 'pending'."""
    B = "BATCH_STATUS"
    doc_id = ddb.register_document(
        batch_id=B, document_type="sales_packing_list",
        file_name="s.xlsx", awb="X9", source="intake",
    )
    assert doc_id
    ddb.update_document_status(doc_id, extraction_status="extracted", parser_status="complete")
    rows = ddb.get_documents_for_batch(B, document_type="sales_packing_list")
    assert rows and rows[0]["extraction_status"] == "extracted"
    assert rows[0]["parser_status"] == "complete"


def test_reprocess_sales_branch_calls_update_document_status():
    """Call-site: the reprocess handler now flips status in the sales branch."""
    src = (Path(__file__).resolve().parents[1] / "app" / "api" / "routes_packing.py").read_text(encoding="utf-8")
    assert "update_document_status(" in src, "reprocess must call update_document_status"
    assert 'extraction_status="extracted"' in src
