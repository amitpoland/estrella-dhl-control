"""
test_proforma_preview_direct_dispatch.py — Proforma gate accepts direct-
dispatch lifecycle states.

Pins that the new lifecycle states (DIRECT_DISPATCH_READY, CLIENT_DISPATCHED)
make stock_ok=True at the Proforma preview gate, alongside the existing
WAREHOUSE_STOCK path. PURCHASE_TRANSIT must still block.

Reuses the seed helpers from test_proforma_preview by importing them via
pytest's normal collection (we set up the same fixtures inline).
"""
from __future__ import annotations

import sqlite3
import uuid
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import wfirma_client as _wc
from app.services import packing_db   as pdb
from app.services import warehouse_db as wdb
from app.services import document_db  as ddb
from app.services import wfirma_db    as wfdb
from app.services import inventory_state_engine as ise


BATCH = "BATCH_DIRECT_DISPATCH_PFP"


@pytest.fixture(autouse=True)
def _prime_vat_code_cache():
    _wc._VAT_CODE_ID_CACHE["23"]  = "222"
    _wc._VAT_CODE_ID_CACHE["WDT"] = "228"
    _wc._VAT_CODE_ID_CACHE["EXP"] = "229"
    yield
    for k in ("23", "WDT", "EXP"):
        _wc._VAT_CODE_ID_CACHE.pop(k, None)


@pytest.fixture()
def storage(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


def _seed_full(design_no: str, product_code: str, client_name: str):
    pdb.upsert_packing_lines([{
        "batch_id":              BATCH,
        "invoice_no":            "INV/X",
        "invoice_line_position": 1,
        "product_code":          product_code,
        "design_no":             design_no,
        "bag_id":                "",
        "tray_id":               "",
        "item_type":             "RNG",
        "uom":                   "PCS",
        "quantity":              1.0,
        "gross_weight":          0.0,
        "net_weight":            0.0,
        "metal":                 "",
        "karat":                 "",
        "stone_type":            "",
        "remarks":               "",
        "extracted_confidence":  1.0,
        "requires_manual_review": False,
        "pack_sr":               1.0,
        "unit_price":            0.0,
        "total_value":           0.0,
    }])
    sd = ddb.store_sales_document(
        batch_id=BATCH, document_id=str(uuid.uuid4()),
        data={"client_name": client_name, "client_ref": "REF",
              "sales_doc_no": "SO-DD"},
    )
    ddb.store_sales_packing_lines(sd, BATCH, [{
        "client_name":  client_name, "client_ref": "REF",
        "product_code": design_no, "design_no": design_no,
        "bag_id": "", "quantity": 1.0, "remarks": "",
        # Sales pricing (canonical source for Proforma):
        "unit_price":   50.0, "currency": "USD",
        "total_value":  50.0, "price_source": "packing_list",
    }])
    ddb.store_invoice_lines("doc-x", BATCH, [{
        "invoice_no": "INV/X", "line_position": 1,
        "product_code": product_code, "description": "",
        "quantity": 1.0, "unit_price": 50.0, "total_value": 50.0,
        "currency": "USD", "rate_usd": 50.0, "amount_usd": 50.0,
    }])
    wfdb.upsert_product(product_code=product_code,
                        wfirma_product_id="42", sync_status="matched")
    wfdb.upsert_customer(client_name=client_name,
                         wfirma_customer_id="9", country="PL",
                         vat_id="", match_status="matched")


def _seed_receive_event(scan_code: str):
    """Create a RECEIVE movement event so the evidence gate passes."""
    con = sqlite3.connect(str(wdb._db_path))
    con.execute(
        """INSERT INTO inventory_movement_events
           (id, batch_id, scan_code, action, from_location, to_location,
            operator, event_time, note, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (str(uuid.uuid4()), BATCH, scan_code, "RECEIVE",
         "", "MAIN-WH-INBOUND", "amit",
         datetime.now(timezone.utc).isoformat(), "",
         datetime.now(timezone.utc).isoformat()),
    )
    con.commit(); con.close()


def _scan_code_for(design_no: str, product_code: str) -> str:
    return f"{product_code}|sr1|{design_no}"


# ── 1. DIRECT_DISPATCH_READY → ready=True ────────────────────────────────────

def test_direct_dispatch_ready_makes_stock_ok_true(client):
    _seed_full("D-DD-1", "EJL/DD-1", "DIRECT-CLIENT")
    sc = _scan_code_for("D-DD-1", "EJL/DD-1")
    _seed_receive_event(sc)
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT,
                   batch_id=BATCH, product_code="EJL/DD-1", design_no="D-DD-1")
    ise.transition(scan_code=sc, to_state=ise.DIRECT_DISPATCH_READY,
                   operator="amit", customer_allocation="DIRECT-CLIENT",
                   customs_cleared=True)

    body = client.post(f"/api/v1/proforma/preview/{BATCH}/DIRECT-CLIENT",
                       headers=_auth()).json()
    assert body["lines"][0]["stock_ok"]     is True
    assert body["lines"][0]["stock_status"] == "direct_dispatch_ready"
    assert body["ready"] is True


# ── 2. CLIENT_DISPATCHED → ready=True (late-Proforma flow) ──────────────────

def test_client_dispatched_makes_stock_ok_true(client):
    _seed_full("D-CD-1", "EJL/CD-1", "DIRECT-CLIENT")
    sc = _scan_code_for("D-CD-1", "EJL/CD-1")
    _seed_receive_event(sc)
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT,
                   batch_id=BATCH, product_code="EJL/CD-1", design_no="D-CD-1")
    ise.transition(scan_code=sc, to_state=ise.DIRECT_DISPATCH_READY,
                   operator="amit", customer_allocation="DIRECT-CLIENT",
                   customs_cleared=True)
    ise.transition(scan_code=sc, to_state=ise.CLIENT_DISPATCHED)

    body = client.post(f"/api/v1/proforma/preview/{BATCH}/DIRECT-CLIENT",
                       headers=_auth()).json()
    assert body["lines"][0]["stock_ok"]     is True
    assert body["lines"][0]["stock_status"] == "client_dispatched"
    assert body["ready"] is True


# ── 3. WAREHOUSE_STOCK still eligible (regression) ──────────────────────────

def test_warehouse_stock_still_eligible(client):
    _seed_full("D-WS-1", "EJL/WS-1", "WS-CLIENT")
    sc = _scan_code_for("D-WS-1", "EJL/WS-1")
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT,
                   batch_id=BATCH, product_code="EJL/WS-1", design_no="D-WS-1")
    ise.transition(scan_code=sc, to_state=ise.WAREHOUSE_STOCK)

    body = client.post(f"/api/v1/proforma/preview/{BATCH}/WS-CLIENT",
                       headers=_auth()).json()
    assert body["lines"][0]["stock_ok"]     is True
    assert body["lines"][0]["stock_status"] == "warehouse_stock"


# ── 4. PURCHASE_TRANSIT still blocks ────────────────────────────────────────

def test_purchase_transit_still_blocks(client):
    _seed_full("D-PT-1", "EJL/PT-1", "PT-CLIENT")
    sc = _scan_code_for("D-PT-1", "EJL/PT-1")
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT,
                   batch_id=BATCH, product_code="EJL/PT-1", design_no="D-PT-1")
    body = client.post(f"/api/v1/proforma/preview/{BATCH}/PT-CLIENT",
                       headers=_auth()).json()
    assert body["lines"][0]["stock_ok"]     is False
    assert body["lines"][0]["stock_status"] == "purchase_transit"
    assert body["ready"] is False


# ── 5. RECEIVE alone does not promote (no DIRECT_DISPATCH_READY) ────────────

def test_receive_alone_does_not_make_stock_ok(client):
    """Inserting a RECEIVE movement event does not change inventory_state.
    The gate must still see the line as PURCHASE_TRANSIT."""
    _seed_full("D-RA-1", "EJL/RA-1", "RA-CLIENT")
    sc = _scan_code_for("D-RA-1", "EJL/RA-1")
    ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT,
                   batch_id=BATCH, product_code="EJL/RA-1", design_no="D-RA-1")
    _seed_receive_event(sc)  # physical scan happened, but no transition

    body = client.post(f"/api/v1/proforma/preview/{BATCH}/RA-CLIENT",
                       headers=_auth()).json()
    assert body["lines"][0]["stock_ok"]     is False
    assert body["lines"][0]["stock_status"] == "purchase_transit"
