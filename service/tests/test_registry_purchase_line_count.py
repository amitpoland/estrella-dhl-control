"""test_registry_purchase_line_count.py — Document Registry purchase line counts.

The Document Registry (GET /api/v1/upload/shipment/{batch_id}/documents) enriched
per-document line counts for invoice rows (from invoice_lines) and, since #663, for
sales_packing_list rows (from sales_packing_lines). purchase_packing_list extraction
writes to packing.db (packing_lines, keyed by packing_document_id → packing_documents),
a DIFFERENT database from documents.db — so the registry had NO branch for it and
rendered "Lines/Fields: 0" for purchase rows even when lines existed.

The bridge: a Document Registry row is a shipment_documents row; its packing document
shares the same source file, so it resolves by (batch_id, file_hash) — equivalently
(batch_id, file_name) when a hash is absent.

Pins:
  - packing_db.count/get_packing_lines_for_document (new read-only helpers)
  - the two-DB bridge resolves by source_file_hash, with a filename fallback
  - the registry endpoint now surfaces lines_count for purchase_packing_list rows
  - honest 0 when a purchase doc has no lines
  - per-document counts (never the batch total); the invoice/sales branches untouched
  - shipment-detail.html treats purchase_packing_list as a "lines" doc

Run: python -m pytest tests/test_registry_purchase_line_count.py -q
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import document_db as ddb
from app.services import packing_db as pdb


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def storage(tmp_path):
    ddb.init_document_db(tmp_path / "documents.db")
    pdb.init_packing_db(tmp_path / "packing.db")
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app) as c:
            yield c


def _auth() -> dict:
    return {"X-API-KEY": settings.api_key or "test-key"}


def _pl(pdoc_id, batch_id, pc, dn, sr, price=10.0, inv="INV1"):
    """A packing line. Distinct pack_sr keeps the dedup key unique so two rows
    in one document aren't collapsed."""
    return {
        "packing_document_id":   pdoc_id,
        "batch_id":              batch_id,
        "invoice_no":            inv,
        "invoice_line_position": None,
        "product_code":          pc,
        "design_no":             dn,
        "bag_id":                "",
        "pack_sr":               sr,
        "quantity":              1.0,
        "unit_price":            price,
        "total_value":           price,
        "remarks":               dn,
    }


def _registry(client, batch_id):
    r = client.get(f"/api/v1/upload/shipment/{batch_id}/documents", headers=_auth())
    assert r.status_code == 200, r.text
    payload = r.json()
    return {d["document_type"]: d for d in payload["documents"]}, payload


# ── Unit: the new per-document helpers ──────────────────────────────────────

def test_count_and_preview_helpers(storage):
    """count/get_packing_lines_for_document bridge documents.db → packing.db by
    (batch_id, source_file_hash)."""
    B = "B-UNIT"
    H = "hash-unit-1"
    pdoc = pdb.upsert_packing_document(
        batch_id=B, source_file_path="/x/file.xlsx", source_file_hash=H,
    )
    pdb.upsert_packing_lines([
        _pl(pdoc, B, "P1", "D1", 1.0),
        _pl(pdoc, B, "P2", "D2", 2.0),
        _pl(pdoc, B, "P3", "D3", 3.0),
    ])
    assert pdb.count_packing_lines_for_shipment_document(B, H) == 3
    preview = pdb.get_packing_lines_for_shipment_document(B, H, limit=2)
    assert len(preview) == 2, "preview respects the limit"
    # Unknown hash and unknown batch both resolve to nothing — honest 0.
    assert pdb.count_packing_lines_for_shipment_document(B, "nope") == 0
    assert pdb.count_packing_lines_for_shipment_document("nope", H) == 0


def test_helper_resolves_by_filename_when_hash_absent(storage):
    """Robustness: a registry row with an empty file_hash still resolves its
    packing_lines via (batch_id, basename(source_file_path) == file_name)."""
    B = "B-UNIT-FN"
    pdoc = pdb.upsert_packing_document(
        batch_id=B, source_file_path="/srv/in/byname.xlsx", source_file_hash="present",
    )
    pdb.upsert_packing_lines([_pl(pdoc, B, "P1", "D1", 1.0), _pl(pdoc, B, "P2", "D2", 2.0)])
    # No hash supplied → falls back to file_name.
    assert pdb.count_packing_lines_for_shipment_document(B, "", "byname.xlsx") == 2
    # Neither hash nor name → nothing.
    assert pdb.count_packing_lines_for_shipment_document(B, "", "") == 0


# ── Endpoint: the registry surfaces the purchase count ──────────────────────

def test_registry_surfaces_purchase_packing_line_count(client, storage):
    """A purchase_packing_list registry row must report lines_count == the actual
    packing_lines count for that document (was always 0 before the fix)."""
    B = "B-REG-PPL"
    H = "hash-reg-1"
    pdoc = pdb.upsert_packing_document(
        batch_id=B, source_file_path="/x/EJL-300.xlsx", source_file_hash=H,
    )
    pdb.upsert_packing_lines([
        _pl(pdoc, B, "EJL/300-1", "JBR00379", 1.0),
        _pl(pdoc, B, "EJL/300-2", "CSTN00026", 2.0),
        _pl(pdoc, B, "EJL/300-3", "RNG001", 3.0),
    ])
    ddb.register_document(
        batch_id=B, document_type="purchase_packing_list",
        file_name="EJL-300.xlsx", file_hash=H, awb="9158478722", source="intake",
    )
    by_type, _ = _registry(client, B)
    ppl = by_type.get("purchase_packing_list")
    assert ppl is not None, "purchase_packing_list row must be present in the registry"
    assert ppl.get("lines_count") == 3, f"expected 3 packing lines, got {ppl.get('lines_count')!r}"
    assert len(ppl.get("lines_preview") or []) == 3
    assert ppl.get("lines_truncated") is False


def test_registry_purchase_doc_with_no_lines_reports_zero(client, storage):
    """Honest zero: a purchase_packing_list doc with no stored lines reports 0,
    not a spurious count and not an error."""
    B = "B-REG-EMPTY"
    H = "hash-empty"
    pdb.upsert_packing_document(
        batch_id=B, source_file_path="/x/empty.xlsx", source_file_hash=H,
    )
    ddb.register_document(
        batch_id=B, document_type="purchase_packing_list",
        file_name="empty.xlsx", file_hash=H, source="intake",
    )
    by_type, _ = _registry(client, B)
    ppl = by_type.get("purchase_packing_list")
    assert ppl is not None
    assert ppl.get("lines_count") == 0


def test_registry_resolves_by_filename_when_hash_absent(client, storage):
    """End-to-end filename fallback: a shipment_documents row with an empty
    file_hash still surfaces its packing_lines count via the file_name bridge."""
    B = "B-REG-FN"
    pdoc = pdb.upsert_packing_document(
        batch_id=B, source_file_path="/srv/in/byname.xlsx", source_file_hash="onlyHere",
    )
    pdb.upsert_packing_lines([_pl(pdoc, B, "P1", "D1", 1.0), _pl(pdoc, B, "P2", "D2", 2.0)])
    ddb.register_document(
        batch_id=B, document_type="purchase_packing_list",
        file_name="byname.xlsx", file_hash="", source="intake",
    )
    by_type, _ = _registry(client, B)
    assert by_type["purchase_packing_list"].get("lines_count") == 2


def test_registry_counts_are_per_document_not_batch_total(client, storage):
    """No mis-attribution: each purchase_packing_list row reports ITS OWN line
    count, never the batch total. Two docs in one batch, different counts."""
    B = "B-REG-ISO"
    pa = pdb.upsert_packing_document(batch_id=B, source_file_path="/x/a.xlsx", source_file_hash="Ha")
    pb = pdb.upsert_packing_document(batch_id=B, source_file_path="/x/b.xlsx", source_file_hash="Hb")
    pdb.upsert_packing_lines([_pl(pa, B, "A1", "DA1", 1.0)])
    pdb.upsert_packing_lines([_pl(pb, B, "B1", "DB1", 1.0), _pl(pb, B, "B2", "DB2", 2.0)])
    ddb.register_document(batch_id=B, document_type="purchase_packing_list",
                          file_name="a.xlsx", file_hash="Ha", source="intake")
    ddb.register_document(batch_id=B, document_type="purchase_packing_list",
                          file_name="b.xlsx", file_hash="Hb", source="intake")
    assert pdb.count_packing_lines_for_shipment_document(B, "Ha") == 1
    assert pdb.count_packing_lines_for_shipment_document(B, "Hb") == 2
    _, payload = _registry(client, B)
    ppl_rows = [d for d in payload["documents"] if d["document_type"] == "purchase_packing_list"]
    assert sorted(d.get("lines_count") for d in ppl_rows) == [1, 2]


def test_registry_invoice_and_sales_branches_untouched(client, storage):
    """Regression: purchase_packing_list is a NEW elif — it must not shadow the
    invoice branch nor the sales_packing_list branch. A batch with all three
    surfaces each independent count."""
    B = "B-REG-MIXED"
    # invoice row → invoice_lines
    inv = ddb.register_document(batch_id=B, document_type="purchase_invoice",
                                file_name="INV.pdf", file_hash="Hinv", source="intake")
    ddb.store_invoice_lines(inv, B, [
        {"line_position": 1, "product_code": "X", "description": "d", "quantity": 1,
         "unit_price": 1.0, "total_value": 1.0, "currency": "USD"},
    ])
    # sales packing row → sales_packing_lines
    sdoc = ddb.register_document(batch_id=B, document_type="sales_packing_list",
                                 file_name="sales.xlsx", file_hash="Hs", source="reprocess")
    ddb.store_sales_packing_lines(sdoc, B, [
        {"client_name": "C", "product_code": "P1", "design_no": "D1", "quantity": 1.0,
         "unit_price": 1.0, "total_value": 1.0, "currency": "EUR", "price_source": "excel_symbol"},
        {"client_name": "C", "product_code": "P2", "design_no": "D2", "quantity": 1.0,
         "unit_price": 1.0, "total_value": 1.0, "currency": "EUR", "price_source": "excel_symbol"},
    ])
    # purchase packing row → packing.db packing_lines
    pdoc = pdb.upsert_packing_document(batch_id=B, source_file_path="/x/pp.xlsx", source_file_hash="Hp")
    pdb.upsert_packing_lines([
        _pl(pdoc, B, "Q1", "DQ1", 1.0), _pl(pdoc, B, "Q2", "DQ2", 2.0), _pl(pdoc, B, "Q3", "DQ3", 3.0),
    ])
    ddb.register_document(batch_id=B, document_type="purchase_packing_list",
                          file_name="pp.xlsx", file_hash="Hp", source="intake")

    by_type, payload = _registry(client, B)
    assert by_type["purchase_invoice"].get("lines_count") == 1
    assert by_type["sales_packing_list"].get("lines_count") == 2
    assert by_type["purchase_packing_list"].get("lines_count") == 3
    assert payload["count"] == 3


# ── Frontend: the registry UI must render the count for purchase rows ────────

def test_frontend_registry_treats_purchase_packing_as_lines_doc():
    """shipment-detail.html gates the line-count cell on isLinesDoc, which must
    include purchase_packing_list so the backend lines_count surfaces in the UI
    instead of falling to the 'N fields' (0) branch."""
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "shipment-detail.html").read_text(encoding="utf-8")
    assert "const isLinesDoc =" in html, "must define the isLinesDoc gate"
    assert "d.document_type === 'purchase_packing_list'" in html, \
        "isLinesDoc gate must include purchase_packing_list"
    assert "if (isLinesDoc) {" in html, "count cell must gate on isLinesDoc"
    assert "isLinesDoc && linesPreview.length > 0" in html, "preview must gate on isLinesDoc"
