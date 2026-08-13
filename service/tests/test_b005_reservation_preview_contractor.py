"""B-005 — end-to-end pin: get_reservation_preview carries contractor fields.

Coverage gap (BACKLOG B-005): DB-layer upsert/get_reservation_draft already
persists ``client_contractor_id``, but no test exercised the public preview
boundary with a full packing + stock + sales-document fixture.

Authority chain under test (no second resolver):
  sales_documents.client_contractor_id
    → build_reservation_plan / get_reservation_preview documents[]
    → upsert_reservation_draft(client_contractor_id=…)
    → get_reservation_draft

This file is intentionally test-only against current main. A PASS closes
B-005 as COVERAGE_ONLY. A FAIL would authorize a production projection fix.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import document_db as ddb
from app.services import packing_db as pdb
from app.services import warehouse_db as wdb
from app.services import wfirma_db as wfdb
from app.services import wfirma_reservation as wr


BATCH = "B005_RES_PREVIEW_CONTRACTOR"
OTHER_BATCH = "B005_OTHER_BATCH_LEAK_GUARD"
CLIENT = "B005 Preview Client"
OTHER_CLIENT = "B005 Other Client"
CID = "CONTRACTOR-B005-CANONICAL"
OTHER_CID = "CONTRACTOR-B005-OTHER"
SKU = "B005/SKU-1"
INV_PC = "EJL/B005/001-1"

_WFIRMA_FULL = dict(
    wfirma_access_key="ACC-KEY",
    wfirma_secret_key="SEC-KEY",
    wfirma_app_key="APP-KEY",
    wfirma_company_id="123456",
    wfirma_warehouse_module_enabled=True,
    wfirma_warehouse_id="WH-B005",
    wfirma_create_product_allowed=False,
    wfirma_create_customer_allowed=False,
)


@pytest.fixture()
def storage(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    # Batch-scoped audit.json (operator-facing evidence surface; preview
    # itself reads warehouse audit helpers, not this file — still required
    # for a realistic full-batch fixture per B-005).
    batch_dir = tmp_path / "batches" / BATCH
    batch_dir.mkdir(parents=True)
    (batch_dir / "audit.json").write_text(
        json.dumps({
            "batch_id": BATCH,
            "client_contractor_id": CID,
            "documents": [{"type": "sales_packing_list"}],
        }, indent=2),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def api(storage):
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


def _seed_full_batch(api, *, batch: str, client: str, cid: str,
                     sku: str = SKU, inv_pc: str = INV_PC) -> str:
    """Packing + invoice + sales doc(with contractor) + stock + wFirma maps."""
    # Canonical sales identity: shipment_documents.id == sales_documents.id.
    doc_id = ddb.register_document(
        batch_id=batch,
        document_type="sales_packing_list",
        file_name=f"sales_pl_{batch}.xlsx",
        source="intake",
        client_contractor_id=cid,
    ) or ""
    assert doc_id

    pline = {
        "packing_document_id": f"pdoc-{doc_id}",
        "batch_id": batch,
        "invoice_no": f"EJL/{batch}/001",
        "invoice_line_position": 1,
        "product_code": inv_pc,
        "design_no": sku,
        "bag_id": "",
        "tray_id": "",
        "item_type": "RNG",
        "uom": "PCS",
        "quantity": 1.0,
        "gross_weight": 1.0,
        "net_weight": 1.0,
        "metal": "18KT",
        "karat": "",
        "stone_type": "",
        "remarks": "",
        "extracted_confidence": 0.95,
        "requires_manual_review": False,
        "pack_sr": 1.0,
        "unit_price": 100.0,
        "total_value": 100.0,
        "batch_no": "",
    }
    pdb.upsert_packing_lines([pline])
    scan_code = wdb.scan_code_for_packing_line(pline)

    ddb.store_invoice_lines(f"inv-{doc_id}", batch, [{
        "invoice_no": f"EJL/{batch}/001",
        "line_position": 1,
        "product_code": inv_pc,
        "description": "B005 item",
        "quantity": 1.0,
        "unit_price": 100.0,
        "total_value": 100.0,
        "currency": "EUR",
        "hs_code": "",
        "gross_weight": 1.0,
        "net_weight": 1.0,
        "rate_usd": 100.0,
        "amount_usd": 100.0,
        "hsn_code": "",
    }])

    sd = ddb.ensure_sales_document_id(
        batch, doc_id,
        client_name=client,
        document_type="sales_packing_list",
        client_contractor_id=cid,
        sales_doc_no=f"SO-{doc_id[:8]}",
    )
    assert sd == doc_id
    ddb.replace_sales_packing_lines(doc_id, batch, [{
        "client_name": client,
        "client_ref": "REF-B005",
        "product_code": sku,
        "design_no": sku,
        "bag_id": "",
        "quantity": 1.0,
        "remarks": "",
        "unit_price": 100.0,
        "currency": "EUR",
        "total_value": 100.0,
        "price_source": "packing_list",
        "client_contractor_id": cid,
    }])

    for action, loc in (("RECEIVE", "MAIN/RECV-01"), ("DISPATCH", "DHL-OUT")):
        r = api.post(
            "/api/v1/warehouse/scan",
            json={"scan_code": scan_code, "action": action,
                  "to_location": loc, "batch_id": batch},
            headers=_auth(),
        )
        assert r.status_code == 200, f"{action} failed: {r.text}"

    wfdb.upsert_customer(client, wfirma_customer_id=f"WF-{cid[:12] or 'EMPTY'}",
                         match_status="matched")
    wfdb.upsert_product(
        inv_pc, wfirma_product_id=f"P-{doc_id[:8]}",
        sync_status="matched", warehouse_id="WH-B005",
    )
    return doc_id


def test_preview_carries_canonical_contractor_fields(storage, api):
    """Unchanged-main reproduction for B-005 — must pass for COVERAGE_ONLY."""
    _seed_full_batch(api, batch=BATCH, client=CLIENT, cid=CID)
    _seed_full_batch(
        api, batch=OTHER_BATCH, client=OTHER_CLIENT, cid=OTHER_CID,
        sku="B005/SKU-OTHER", inv_pc="EJL/B005/OTHER-1",
    )

    # Prove fixture stored the contractor on the sales authority before preview.
    sales = ddb.get_sales_documents(BATCH)
    assert len(sales) == 1
    assert sales[0]["client_contractor_id"] == CID

    with patch.multiple(settings, **_WFIRMA_FULL):
        result = wr.get_reservation_preview(BATCH)

    docs = result["documents"]
    assert len(docs) == 1
    doc = docs[0]
    assert doc["client_name"] == CLIENT
    assert doc["client_contractor_id"] == CID, (
        f"preview dropped canonical contractor; got {doc.get('client_contractor_id')!r}"
    )
    assert doc["contractor_resolved"] is True
    # Name-only path must not invent a different id when sales authority has CID.
    assert doc["client_contractor_id"] != OTHER_CID
    assert doc["client_contractor_id"] != ""

    # Persist boundary: draft stores the same contractor (no name-only overwrite).
    draft = wfdb.get_reservation_draft(BATCH, CLIENT)
    assert draft is not None
    assert draft["client_contractor_id"] == CID

    # Cross-batch isolation: other batch's contractor must not appear.
    with patch.multiple(settings, **_WFIRMA_FULL):
        other = wr.get_reservation_preview(OTHER_BATCH)
    assert len(other["documents"]) == 1
    assert other["documents"][0]["client_contractor_id"] == OTHER_CID
    assert other["documents"][0]["contractor_resolved"] is True
    assert CID not in {
        other["documents"][0]["client_contractor_id"],
    }


def test_preview_unresolved_contractor_is_honest(storage, api):
    """Empty contractor on sales doc → contractor_resolved False, empty id."""
    batch = "B005_UNRESOLVED"
    _seed_full_batch(api, batch=batch, client="NoCid Client", cid="")

    with patch.multiple(settings, **_WFIRMA_FULL):
        result = wr.get_reservation_preview(batch)

    doc = result["documents"][0]
    assert doc["client_contractor_id"] == ""
    assert doc["contractor_resolved"] is False
