"""test_registry_sales_line_count.py — Document Registry sales line counts.

The Document Registry (GET /api/v1/upload/shipment/{batch_id}/documents) enriched
per-document line counts only for invoice rows (from invoice_lines). sales_packing_list
extraction writes to sales_packing_lines (keyed by sales_document_id == the
shipment_documents.id), and its data lands in neither document_extracted_fields nor
invoice_lines — so the registry rendered "Lines/Fields: 0" for sales rows even when
84 lines existed.

Pins:
  - document_db.count/get_sales_packing_lines_for_document (new helpers)
  - the registry endpoint now surfaces lines_count for sales_packing_list rows
  - honest 0 when a sales doc has no lines
  - the invoice enrichment branch is untouched (elif), still returns its row

Run: python -m pytest tests/test_registry_sales_line_count.py -q
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import document_db as ddb


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def storage(tmp_path):
    ddb.init_document_db(tmp_path / "documents.db")
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app) as c:
            yield c


def _auth() -> dict:
    return {"X-API-KEY": settings.api_key or "test-key"}


def _spl(pc, dn, qty=1.0, price=10.0, src="excel_symbol"):
    return {
        "client_name": "C", "client_ref": "", "product_code": pc, "design_no": dn,
        "bag_id": "", "quantity": qty, "remarks": "",
        "unit_price": price, "total_value": price, "currency": "EUR", "price_source": src,
    }


def _registry(client, batch_id):
    r = client.get(f"/api/v1/upload/shipment/{batch_id}/documents", headers=_auth())
    assert r.status_code == 200, r.text
    return {d["document_type"]: d for d in r.json()["documents"]}, r.json()


# ── Unit: the new per-document helpers ──────────────────────────────────────

def test_count_and_preview_helpers(storage):
    """count/get_sales_packing_lines_for_document resolve by sales_document_id
    (== the shipment_documents.id the reprocess path uses)."""
    B = "B-UNIT"
    doc_id = "shipdoc-1"
    ddb.store_sales_packing_lines(doc_id, B, [
        _spl("P1", "D1"), _spl("P2", "D2"), _spl("P3", "D3"),
    ])
    assert ddb.count_sales_packing_lines_for_document(doc_id) == 3
    preview = ddb.get_sales_packing_lines_for_document(doc_id, limit=2)
    assert len(preview) == 2, "preview respects the limit"
    assert ddb.count_sales_packing_lines_for_document("nope") == 0


# ── Endpoint: the registry surfaces the sales count ─────────────────────────

def test_registry_surfaces_sales_packing_line_count(client, storage):
    """A sales_packing_list registry row must report lines_count == the actual
    sales_packing_lines count for that document (was always 0 before the fix)."""
    B = "B-REG-SALES"
    doc_id = ddb.register_document(
        batch_id=B, document_type="sales_packing_list",
        file_name="EJL-300-Client.xlsx", awb="9158478722", source="reprocess",
    )
    ddb.store_sales_packing_lines(doc_id, B, [
        _spl("EJL/300-1", "JBR00379"), _spl("EJL/300-2", "CSTN00026"),
        _spl("EJL/300-3", "RNG001"),
    ])
    by_type, _ = _registry(client, B)
    sales = by_type.get("sales_packing_list")
    assert sales is not None, "sales_packing_list row must be present in the registry"
    assert sales.get("lines_count") == 3, f"expected 3 sales lines, got {sales.get('lines_count')!r}"
    assert len(sales.get("lines_preview") or []) == 3
    assert sales.get("lines_truncated") is False


def test_registry_sales_doc_with_no_lines_reports_zero(client, storage):
    """Honest zero: a sales_packing_list doc with no stored lines reports 0,
    not a spurious count and not an error."""
    B = "B-REG-EMPTY"
    ddb.register_document(
        batch_id=B, document_type="sales_packing_list",
        file_name="empty.xlsx", awb="X", source="reprocess",
    )
    by_type, _ = _registry(client, B)
    sales = by_type.get("sales_packing_list")
    assert sales is not None
    assert sales.get("lines_count") == 0


def test_registry_invoice_branch_untouched(client, storage):
    """Regression: the sales branch is an elif, so a purchase_invoice row in the
    same batch still flows through the invoice enrichment (and a sales row is
    counted independently) — neither shadows the other."""
    B = "B-REG-MIXED"
    ddb.register_document(
        batch_id=B, document_type="purchase_invoice",
        file_name="INV.pdf", awb="X", source="intake",
    )
    sdoc = ddb.register_document(
        batch_id=B, document_type="sales_packing_list",
        file_name="sales.xlsx", awb="X", source="reprocess",
    )
    ddb.store_sales_packing_lines(sdoc, B, [_spl("P1", "D1"), _spl("P2", "D2")])
    by_type, payload = _registry(client, B)
    assert "purchase_invoice" in by_type, "invoice row must still be returned"
    assert by_type["sales_packing_list"].get("lines_count") == 2
    assert payload["count"] == 2


def test_registry_resolves_intake_keyed_sales_lines(client, storage):
    """Robustness: the intake path keys sales_packing_lines to a freshly-minted
    sales_documents.id (whose document_id back-references the
    shipment_documents.id), NOT to doc_id directly. The registry must resolve
    the count via that back-ref — not only the reprocess shape
    (sales_document_id == doc_id)."""
    B = "B-REG-INTAKE"
    doc_id = ddb.register_document(
        batch_id=B, document_type="sales_packing_list",
        file_name="intake.xlsx", awb="X", source="intake",
    )
    sd_id = ddb.store_sales_document(
        batch_id=B, document_id=doc_id,
        data={"document_type": "sales_packing_list", "extraction_status": "pending"},
    )
    assert sd_id and sd_id != doc_id, "intake mints a random sales_documents.id"
    ddb.store_sales_packing_lines(sd_id, B, [_spl("P1", "D1"), _spl("P2", "D2")])
    # Direct helper resolves via the document_id back-ref:
    assert ddb.count_sales_packing_lines_for_document(doc_id) == 2
    # And the registry endpoint surfaces it:
    by_type, _ = _registry(client, B)
    assert by_type["sales_packing_list"].get("lines_count") == 2


def test_registry_counts_are_per_document_not_batch_total(client, storage):
    """No mis-attribution: each sales_packing_list row reports ITS OWN line
    count (across both FK shapes), never the batch total — the document_id
    back-ref resolver must not bleed doc B's lines into doc A."""
    B = "B-REG-ISO"
    a = ddb.register_document(batch_id=B, document_type="sales_packing_list",
                              file_name="a.xlsx", awb="X", source="intake")
    b = ddb.register_document(batch_id=B, document_type="sales_packing_list",
                              file_name="b.xlsx", awb="X", source="intake")
    # doc A: reprocess shape (sales_document_id == doc_id), 1 line
    ddb.store_sales_packing_lines(a, B, [_spl("A1", "DA1")])
    # doc B: intake shape (random sales_documents.id, document_id == b), 2 lines
    sd_b = ddb.store_sales_document(batch_id=B, document_id=b,
                                    data={"document_type": "sales_packing_list"})
    ddb.store_sales_packing_lines(sd_b, B, [_spl("B1", "DB1"), _spl("B2", "DB2")])
    assert ddb.count_sales_packing_lines_for_document(a) == 1
    assert ddb.count_sales_packing_lines_for_document(b) == 2


# ── Frontend: the registry UI must render the count for sales rows ──────────

def test_frontend_registry_treats_sales_packing_as_lines_doc():
    """shipment-detail.html gates the line-count cell on isLinesDoc (= invoice OR
    sales_packing_list), so the backend lines_count actually surfaces in the UI
    instead of falling to the 'N fields' (0) branch."""
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "shipment-detail.html").read_text(encoding="utf-8")
    assert "const isLinesDoc =" in html, "must define the isLinesDoc gate"
    assert "sales_packing_list" in html
    assert "if (isLinesDoc) {" in html, "count cell must gate on isLinesDoc"
    assert "isLinesDoc && linesPreview.length > 0" in html, "preview must gate on isLinesDoc"
