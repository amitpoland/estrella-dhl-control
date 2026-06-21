"""test_registry_review_state.py — Document Registry review-state attachment.

Pins that GET /api/v1/upload/shipment/{batch_id}/documents attaches the backend
review-state authority (review_state / review_reason / review_code) to every row,
reconciling the authoritative purchase-packing status from packing.db so a
complete parse is never rendered as a stale 'pending' or a blank Review column.

Run: python -m pytest tests/test_registry_review_state.py -q
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import document_db as ddb
from app.services import packing_db as pdb


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


def _pl(pdoc_id, batch_id, pc, dn, sr, inv="INV1"):
    return {
        "packing_document_id": pdoc_id, "batch_id": batch_id, "invoice_no": inv,
        "invoice_line_position": None, "product_code": pc, "design_no": dn,
        "bag_id": "", "pack_sr": sr, "quantity": 1.0, "unit_price": 1.0,
        "total_value": 1.0, "remarks": dn,
    }


def _registry(client, batch_id):
    r = client.get(f"/api/v1/upload/shipment/{batch_id}/documents", headers=_auth())
    assert r.status_code == 200, r.text
    payload = r.json()
    return {d["document_type"]: d for d in payload["documents"]}, payload


# ── RC-1: purchase packing complete in packing.db but pending in registry ────

def test_purchase_packing_complete_in_packingdb_pending_in_shipment_docs_is_ready(client, storage):
    """The headline case: packing_documents.extraction_status='complete' with
    lines, but shipment_documents.extraction_status stayed 'pending'. The registry
    must report review_state ready/needs_review — never blank, never 'pending'."""
    B, H = "B-PPL-READY", "hash-ppl-1"
    pdoc = pdb.upsert_packing_document(
        batch_id=B, source_file_path="/x/EJL-300.xlsx", source_file_hash=H,
        extraction_status="complete",
    )
    pdb.upsert_packing_lines([_pl(pdoc, B, "P1", "D1", 1.0), _pl(pdoc, B, "P2", "D2", 2.0)])
    # shipment_documents row keeps the default pending status (the bug condition).
    ddb.register_document(batch_id=B, document_type="purchase_packing_list",
                          file_name="EJL-300.xlsx", file_hash=H, source="intake")
    by_type, _ = _registry(client, B)
    ppl = by_type["purchase_packing_list"]
    assert ppl["review_state"] == "ready"
    assert ppl["review_reason"] and ppl["review_code"]
    # The reconciled (effective) status is surfaced even though the raw column is stale.
    assert ppl["extraction_status"] == "pending"  # raw, untouched by the read path
    assert ppl["extraction_status_effective"] == "complete"


def test_purchase_packing_genuinely_pending_no_packingdb_row_is_needs_review(client, storage):
    """Pre-parse state: a purchase_packing_list row exists in shipment_documents
    but no packing_documents row yet. Must be needs_review (awaiting), never a
    false 'ready' and never blank."""
    B, H = "B-PPL-PENDING", "hash-pending"
    ddb.register_document(batch_id=B, document_type="purchase_packing_list",
                          file_name="pending.xlsx", file_hash=H, source="intake")
    by_type, _ = _registry(client, B)
    ppl = by_type["purchase_packing_list"]
    assert ppl["review_state"] == "needs_review"
    assert ppl["review_code"] == "awaiting_extraction"


def test_review_state_present_even_when_derivation_raises(client, storage, monkeypatch):
    """Never-blank invariant under failure: if the packing-status reconciliation
    raises, the row must still carry a concrete review_state (the endpoint must
    not drop the key)."""
    B, H = "B-PPL-RAISE", "hash-raise"
    pdoc = pdb.upsert_packing_document(batch_id=B, source_file_path="/x/r.xlsx",
                                       source_file_hash=H, extraction_status="complete")
    pdb.upsert_packing_lines([_pl(pdoc, B, "P1", "D1", 1.0)])
    ddb.register_document(batch_id=B, document_type="purchase_packing_list",
                          file_name="r.xlsx", file_hash=H, source="intake")

    def _boom(*a, **k):
        raise RuntimeError("packing.db unavailable")
    monkeypatch.setattr(pdb, "get_packing_status_for_shipment_document", _boom)

    by_type, _ = _registry(client, B)
    ppl = by_type["purchase_packing_list"]
    assert ppl.get("review_state"), "review_state must never be absent/blank"
    assert ppl["review_code"] == "review_derivation_error"


def test_purchase_packing_failed_extraction_is_blocked(client, storage):
    B = "B-PPL-FAIL"
    doc_id = ddb.register_document(batch_id=B, document_type="purchase_packing_list",
                                   file_name="bad.xlsx", file_hash="Hbad", source="intake")
    ddb.update_document_status(doc_id, extraction_status="extraction_failed",
                              parser_status="failed", requires_manual_review=True)
    by_type, _ = _registry(client, B)
    ppl = by_type["purchase_packing_list"]
    assert ppl["review_state"] == "blocked"
    assert ppl["review_code"] == "extraction_failed"


# ── sales packing + contractor gate ─────────────────────────────────────────

def test_sales_packing_resolved_client_is_ready(client, storage):
    B = "B-SPL-READY"
    sdoc = ddb.register_document(batch_id=B, document_type="sales_packing_list",
                                 file_name="sales.xlsx", file_hash="Hs", source="reprocess",
                                 extraction_status="extracted", parser_status="complete")
    ddb.store_sales_packing_lines(sdoc, B, [
        {"client_name": "Clear-Diamonds Ltd.", "product_code": "P1", "design_no": "D1",
         "quantity": 1.0, "unit_price": 1.0, "total_value": 1.0, "currency": "EUR",
         "price_source": "excel_symbol"},
    ])
    by_type, _ = _registry(client, B)
    spl = by_type["sales_packing_list"]
    assert spl["review_state"] == "ready"


def test_sales_packing_unresolved_client_is_blocked(client, storage):
    """The 11→5 silent-drop case: a complete sales packing list with no resolved
    client must surface as blocked (no sales draft will be created), not 'ready'
    and not blank."""
    B = "B-SPL-BLOCK"
    sdoc = ddb.register_document(batch_id=B, document_type="sales_packing_list",
                                 file_name="sales2.xlsx", file_hash="Hs2", source="reprocess",
                                 extraction_status="extracted", parser_status="complete",
                                 client_contractor_id="")
    ddb.store_sales_packing_lines(sdoc, B, [
        {"client_name": "", "product_code": "P1", "design_no": "D1", "quantity": 1.0,
         "unit_price": 1.0, "total_value": 1.0, "currency": "EUR", "price_source": "excel_symbol"},
    ])
    by_type, _ = _registry(client, B)
    spl = by_type["sales_packing_list"]
    assert spl["review_state"] == "blocked"
    assert spl["review_code"] == "client_unresolved"


# ── invariant: every registry row has a concrete review_state ───────────────

def test_every_registry_row_has_non_empty_review_state(client, storage):
    B = "B-MIXED"
    # invoice
    inv = ddb.register_document(batch_id=B, document_type="purchase_invoice",
                                file_name="INV.pdf", file_hash="Hinv", source="intake",
                                extraction_status="extracted", parser_status="complete")
    ddb.store_invoice_lines(inv, B, [
        {"line_position": 1, "product_code": "X", "description": "d", "quantity": 1,
         "unit_price": 1.0, "total_value": 1.0, "currency": "USD"}])
    # awb (non-line)
    ddb.register_document(batch_id=B, document_type="awb", file_name="awb.pdf",
                          file_hash="Hawb", source="intake")
    # purchase packing (complete in packing.db)
    pdoc = pdb.upsert_packing_document(batch_id=B, source_file_path="/x/pp.xlsx",
                                       source_file_hash="Hp", extraction_status="complete")
    pdb.upsert_packing_lines([_pl(pdoc, B, "Q1", "DQ1", 1.0)])
    ddb.register_document(batch_id=B, document_type="purchase_packing_list",
                          file_name="pp.xlsx", file_hash="Hp", source="intake")

    _, payload = _registry(client, B)
    assert payload["count"] == 3
    valid = {"ready", "needs_review", "blocked", "not_applicable"}
    for d in payload["documents"]:
        assert d.get("review_state") in valid, d
        assert d.get("review_reason"), d
        assert d.get("review_code"), d
    by_type = {d["document_type"]: d for d in payload["documents"]}
    assert by_type["awb"]["review_state"] == "not_applicable"
    assert by_type["purchase_invoice"]["review_state"] == "ready"
    assert by_type["purchase_packing_list"]["review_state"] == "ready"


# ── frontend renders backend truth, invents nothing ─────────────────────────

def test_frontend_renders_backend_review_state_no_invented_fallback():
    html = (Path(__file__).resolve().parents[1] / "app" / "static" / "shipment-detail.html").read_text(encoding="utf-8")
    # Renders the backend authority verbatim via reviewBadge.
    assert "const reviewBadge =" in html, "must define reviewBadge helper"
    assert "{reviewBadge(d)}" in html, "Review cell must render reviewBadge(d)"
    assert "d.review_state" in html, "reviewBadge must read backend review_state"
    # Per-row testid (unique per document id), plus a filterable state attr.
    assert "doc-registry-review-${d.id" in html, "Review badge testid must be per-row"
    assert "data-review-state=" in html
    # Extraction column renders the reconciled effective status (RC-1 closed end-to-end).
    assert "d.extraction_status_effective || d.extraction_status" in html, \
        "Extraction column must prefer the reconciled effective status"
    # The old Review cell invented state from requires_manual_review — it must be gone.
    assert "<span style={pillStyle('err')}>Review</span>" not in html, \
        "must not invent Review state from requires_manual_review"
