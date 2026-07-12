"""
test_intake_multifile_packing_pairing_wave2.py
==============================================
EJ Dashboard Stabilization Sprint 1, Wave 2 — reviewer-challenge follow-up.

Pins the multi-file packing-slot → block pairing contract.

Bug (inherited from the proven V1 dashboard.html client, left unchanged in
Wave 2): when an operator drops MULTIPLE files into a SINGLE packing-list slot,
the frontend records ONE block for the slot (``packing_index`` = the slot's
first packing-file position). The backend used exact equality
(``b.get("packing_index") == idx``) so only the FIRST file paired with the
block; every subsequent file in the same slot registered with NO
supplier_contractor_id / client_contractor_id and no invoice/document
association.

Fix: the frontend now sends a per-block ``packing_file_count`` and the backend
range-matches ``packing_index <= idx < packing_index + count`` so every file in
a multi-file slot inherits the block's contractor identity.

Backwards compatibility: a payload with NO ``packing_file_count`` (legacy V1
dashboard.html) defaults count to 1 — i.e. the original exact-equality match —
so the single-file contract is unchanged. This is pinned below too.

Fixture pattern mirrors test_intake_idempotency_wave2.py (patched storage_root,
mocked AWB parse + purchase packing extraction).
"""
from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import document_db as ddb
from app.services import packing_db as pdb


@pytest.fixture(scope="module")
def tmp_storage(tmp_path_factory):
    return tmp_path_factory.mktemp("intake_multifile_pack_storage")


@pytest.fixture(scope="module")
def _dbs(tmp_storage):
    ddb.init_document_db(tmp_storage / "documents.db")
    pdb.init_packing_db(tmp_storage / "packing.db")
    return tmp_storage


@pytest.fixture(scope="module")
def client(tmp_storage, _dbs):
    with patch.object(settings, "storage_root", tmp_storage):
        with patch.object(settings, "max_upload_bytes", 20 * 1024 * 1024):
            with TestClient(app, raise_server_exceptions=True) as c:
                yield c


def _pdf(name: str, body: bytes = b"") -> tuple:
    return (name, io.BytesIO(body or f"%PDF-1.4 fake {name}".encode()), "application/pdf")


def _auth() -> dict:
    return {"X-API-KEY": settings.api_key or "test-key"}


def _mock_parsers():
    """Stub the AWB parse + purchase packing extraction. Document registration
    (which carries the contractor id) runs BEFORE extraction, so a raising
    extractor does not hide the pairing under test."""
    awb = patch("app.api.routes_intake.parse_awb_pdf",
                return_value={"awb_number": "", "carrier": "DHL", "confidence": 0.0})
    pack = patch("app.api.routes_intake.process_packing_upload",
                 side_effect=Exception("no packing"))
    return awb, pack


def _pack_cids(batch_id: str, doc_type: str, field: str) -> list:
    """Contractor-id values on every registered packing doc of a type, ordered
    by creation (i.e. upload order)."""
    rows = ddb.get_documents_for_batch(batch_id, doc_type)
    return [(r.get(field) or "").strip() for r in rows]


# ── Purchase: multi-file packing slot ───────────────────────────────────────

def test_multifile_purchase_packing_slot_all_files_inherit_supplier_cid(client):
    """Two files in ONE purchase packing slot → BOTH inherit the block's
    supplier_contractor_id (the fixed range-match)."""
    awb, pack = _mock_parsers()
    with awb, pack:
        r = client.post(
            "/api/v1/shipment/intake",
            data={"tracking_no": "MULTIPACK-P1", "carrier": "DHL",
                  "metadata": json.dumps({
                      "purchase_blocks": [{
                          "invoice_index": 0,
                          "packing_index": 0,
                          "packing_file_count": 2,
                          "supplier_contractor_id": "701",
                      }],
                      "sales_blocks": [],
                  })},
            files=[
                ("invoices", _pdf("INV-1.pdf")),
                ("packing_lists", _pdf("ppack-A.pdf", b"%PDF pack A")),
                ("packing_lists", _pdf("ppack-B.pdf", b"%PDF pack B")),
            ],
            headers=_auth())
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]
    cids = _pack_cids(batch_id, "purchase_packing_list", "supplier_contractor_id")
    assert len(cids) == 2, cids
    # BOTH files — not just the first — carry the block's supplier identity.
    assert cids == ["701", "701"], cids


def test_single_file_purchase_packing_without_count_is_unchanged(client):
    """Backwards compat: a legacy payload with NO packing_file_count (V1
    dashboard.html) still pairs the single file (count defaults to 1)."""
    awb, pack = _mock_parsers()
    with awb, pack:
        r = client.post(
            "/api/v1/shipment/intake",
            data={"tracking_no": "MULTIPACK-P2", "carrier": "DHL",
                  "metadata": json.dumps({
                      "purchase_blocks": [{
                          "invoice_index": 0,
                          "packing_index": 0,
                          # NO packing_file_count — legacy shape.
                          "supplier_contractor_id": "702",
                      }],
                      "sales_blocks": [],
                  })},
            files=[
                ("invoices", _pdf("INV-1.pdf")),
                ("packing_lists", _pdf("ppack-solo.pdf", b"%PDF solo")),
            ],
            headers=_auth())
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]
    cids = _pack_cids(batch_id, "purchase_packing_list", "supplier_contractor_id")
    assert cids == ["702"], cids


# ── Sales: multi-file packing slot ──────────────────────────────────────────

def test_multifile_sales_packing_slot_all_files_inherit_client_cid(client):
    """Two files in ONE sales packing slot → BOTH inherit the block's
    client_contractor_id (the fixed range-match)."""
    awb, pack = _mock_parsers()
    with awb, pack:
        r = client.post(
            "/api/v1/shipment/intake",
            data={"tracking_no": "MULTIPACK-S1", "carrier": "DHL",
                  "metadata": json.dumps({
                      "purchase_blocks": [],
                      "sales_blocks": [{
                          "document_index": -1,
                          "packing_index": 0,
                          "packing_file_count": 2,
                          "client_contractor_id": "901",
                      }],
                  })},
            files=[
                ("invoices", _pdf("INV-1.pdf")),
                ("sales_packing_lists", _pdf("spack-A.pdf", b"%PDF sales A")),
                ("sales_packing_lists", _pdf("spack-B.pdf", b"%PDF sales B")),
            ],
            headers=_auth())
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]
    cids = _pack_cids(batch_id, "sales_packing_list", "client_contractor_id")
    assert len(cids) == 2, cids
    assert cids == ["901", "901"], cids


# ── Consecutive multi-file slots (range gap/overlap) ────────────────────────

def test_consecutive_multifile_purchase_slots_no_range_crosstalk(client):
    """Slot A (2 files, supplier 801) then slot B (3 files, supplier 802) →
    each file inherits ITS OWN slot's supplier. Pins that consecutive
    packing_index+count ranges neither overlap nor leave a gap (the mispairing
    risk when a batch has more than one multi-file packing slot)."""
    awb, pack = _mock_parsers()
    with awb, pack:
        r = client.post(
            "/api/v1/shipment/intake",
            data={"tracking_no": "MULTIPACK-SEQ1", "carrier": "DHL",
                  "metadata": json.dumps({
                      "purchase_blocks": [
                          {"invoice_index": 0, "packing_index": 0, "packing_file_count": 2, "supplier_contractor_id": "801"},
                          {"invoice_index": 1, "packing_index": 2, "packing_file_count": 3, "supplier_contractor_id": "802"},
                      ],
                      "sales_blocks": [],
                  })},
            files=[
                ("invoices", _pdf("INV-A.pdf")),
                ("invoices", _pdf("INV-B.pdf")),
                ("packing_lists", _pdf("A-1.pdf", b"%PDF A1")),
                ("packing_lists", _pdf("A-2.pdf", b"%PDF A2")),
                ("packing_lists", _pdf("B-1.pdf", b"%PDF B1")),
                ("packing_lists", _pdf("B-2.pdf", b"%PDF B2")),
                ("packing_lists", _pdf("B-3.pdf", b"%PDF B3")),
            ],
            headers=_auth())
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]
    cids = _pack_cids(batch_id, "purchase_packing_list", "supplier_contractor_id")
    # Files upload-ordered: 2×slot-A (801) then 3×slot-B (802). No gap/overlap.
    assert cids == ["801", "801", "802", "802", "802"], cids
