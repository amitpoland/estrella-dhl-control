"""
test_inventory_state_mark_direct_dispatch.py — Operator-facing route to
mark DIRECT_DISPATCH_READY.

Covers POST /api/v1/inventory-state/mark-direct-dispatch.

Pins:
  1. happy path marks selected lines DIRECT_DISPATCH_READY
  2. missing operator → 400
  3. missing customer_allocation → 400
  4. missing customs evidence → 400
  5. scan_code outside batch → per-line rejected
  6. missing RECEIVE event → per-line rejected
  7. already DIRECT_DISPATCH_READY → idempotent already_ready
  8. PURCHASE_TRANSIT lines become Proforma-eligible after route call
  9. caller-supplied customs_cleared bool is ignored — the route derives it
"""
from __future__ import annotations

import json
import sqlite3
import uuid
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


BATCH = "BATCH_DD_ROUTE"


@pytest.fixture(autouse=True)
def _prime_vat_code_cache():
    _wc._VAT_CODE_ID_CACHE["23"] = "222"
    yield
    _wc._VAT_CODE_ID_CACHE.pop("23", None)


@pytest.fixture()
def storage(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    wdb.init_warehouse_db(tmp_path / "warehouse.db")
    ddb.init_document_db(tmp_path / "documents.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    (tmp_path / "outputs" / BATCH).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def client(storage):
    from app.main import app
    with patch.object(settings, "storage_root", storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


def _seed_packing(design_no: str, product_code: str, pack_sr: float = 1.0) -> str:
    pdb.upsert_packing_lines([{
        "batch_id":              BATCH,
        "invoice_no":            "INV/X",
        "invoice_line_position": int(pack_sr),
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
        "pack_sr":               pack_sr,
        "unit_price":            0.0,
        "total_value":           0.0,
    }])
    return f"{product_code}|sr{int(pack_sr)}|{design_no}"


def _seed_purchase(scan_code: str) -> None:
    ise.transition(scan_code=scan_code, to_state=ise.PURCHASE_TRANSIT,
                   batch_id=BATCH)


def _seed_receive(scan_code: str) -> None:
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


def _write_audit(storage, **fields) -> None:
    p = storage / "outputs" / BATCH / "audit.json"
    p.write_text(json.dumps(fields), encoding="utf-8")


URL = "/api/v1/inventory-state/mark-direct-dispatch"


# ── 1. Happy path ────────────────────────────────────────────────────────────

def test_happy_path_marks_lines_direct_dispatch_ready(client, storage):
    sc1 = _seed_packing("D-001", "EJL/DD/1", 1.0)
    sc2 = _seed_packing("D-002", "EJL/DD/2", 2.0)
    for sc in (sc1, sc2):
        _seed_purchase(sc); _seed_receive(sc)
    _write_audit(storage, wfirma_export={"wfirma_pz_doc_id": "183484963"})

    r = client.post(URL, headers=_auth(), json={
        "batch_id":            BATCH,
        "scan_codes":          [sc1, sc2],
        "operator":            "amit",
        "customer_allocation": "Clear-Diamonds Ltd",
        "evidence_note":       "AWB 6049349806 direct DHL→client",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["transitioned"] == 2
    assert body["already_ready"] == 0
    assert body["rejected"] == 0
    assert "wfirma_export.wfirma_pz_doc_id" in body["customs_signals"]
    for res in body["results"]:
        assert res["outcome"] == "transitioned"
        assert res["state"]   == ise.DIRECT_DISPATCH_READY

    for sc in (sc1, sc2):
        assert ise.get_state(sc)["state"] == ise.DIRECT_DISPATCH_READY


# ── 2. Missing operator ─────────────────────────────────────────────────────

def test_missing_operator_rejected(client, storage):
    sc = _seed_packing("D-003", "EJL/DD/3")
    _seed_purchase(sc); _seed_receive(sc)
    _write_audit(storage, wfirma_export={"wfirma_pz_doc_id": "1"})

    r = client.post(URL, headers=_auth(), json={
        "batch_id": BATCH, "scan_codes": [sc],
        "operator": "", "customer_allocation": "X",
    })
    assert r.status_code == 400
    assert "operator" in r.text


# ── 3. Missing customer_allocation ──────────────────────────────────────────

def test_missing_customer_rejected(client, storage):
    sc = _seed_packing("D-004", "EJL/DD/4")
    _seed_purchase(sc); _seed_receive(sc)
    _write_audit(storage, wfirma_export={"wfirma_pz_doc_id": "1"})

    r = client.post(URL, headers=_auth(), json={
        "batch_id": BATCH, "scan_codes": [sc],
        "operator": "amit", "customer_allocation": "  ",
    })
    assert r.status_code == 400
    assert "customer_allocation" in r.text


# ── 4. Missing customs evidence ─────────────────────────────────────────────

def test_no_customs_evidence_rejected(client, storage):
    sc = _seed_packing("D-005", "EJL/DD/5")
    _seed_purchase(sc); _seed_receive(sc)
    # audit.json present but contains NO clearance signals
    _write_audit(storage, status="failed")

    r = client.post(URL, headers=_auth(), json={
        "batch_id": BATCH, "scan_codes": [sc],
        "operator": "amit", "customer_allocation": "X",
    })
    assert r.status_code == 400
    assert "customs/PZ clearance evidence missing" in r.text
    # And state must still be PURCHASE_TRANSIT.
    assert ise.get_state(sc)["state"] == ise.PURCHASE_TRANSIT


def test_no_audit_json_rejected(client, storage):
    sc = _seed_packing("D-005b", "EJL/DD/5b")
    _seed_purchase(sc); _seed_receive(sc)
    # No audit.json at all.
    r = client.post(URL, headers=_auth(), json={
        "batch_id": BATCH, "scan_codes": [sc],
        "operator": "amit", "customer_allocation": "X",
    })
    assert r.status_code == 400
    assert "customs/PZ clearance evidence missing" in r.text


# ── 5. scan_code outside batch ──────────────────────────────────────────────

def test_scan_code_outside_batch_rejected_per_line(client, storage):
    sc = _seed_packing("D-006", "EJL/DD/6")
    _seed_purchase(sc); _seed_receive(sc)
    _write_audit(storage, wfirma_export={"wfirma_pz_doc_id": "1"})

    bogus = "EJL/EVIL/9|sr1|HACKED"
    r = client.post(URL, headers=_auth(), json={
        "batch_id": BATCH, "scan_codes": [sc, bogus],
        "operator": "amit", "customer_allocation": "X",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["transitioned"] == 1
    assert body["rejected"] == 1
    by_sc = {res["scan_code"]: res for res in body["results"]}
    assert by_sc[sc]["outcome"]    == "transitioned"
    assert by_sc[bogus]["outcome"] == "rejected"
    assert "does not belong to batch" in by_sc[bogus]["reason"]
    # Bogus scan_code must NOT have a state row.
    assert ise.get_state(bogus) is None


# ── 6. Missing RECEIVE event ────────────────────────────────────────────────

def test_missing_receive_rejected_per_line(client, storage):
    sc_ok      = _seed_packing("D-007a", "EJL/DD/7a", 1.0)
    sc_no_recv = _seed_packing("D-007b", "EJL/DD/7b", 2.0)
    _seed_purchase(sc_ok);     _seed_receive(sc_ok)
    _seed_purchase(sc_no_recv)  # NO _seed_receive
    _write_audit(storage, wfirma_export={"wfirma_pz_doc_id": "1"})

    r = client.post(URL, headers=_auth(), json={
        "batch_id": BATCH, "scan_codes": [sc_ok, sc_no_recv],
        "operator": "amit", "customer_allocation": "X",
    })
    body = r.json()
    by_sc = {res["scan_code"]: res for res in body["results"]}
    assert by_sc[sc_ok]["outcome"]      == "transitioned"
    assert by_sc[sc_no_recv]["outcome"] == "rejected"
    assert "RECEIVE" in by_sc[sc_no_recv]["reason"]
    assert ise.get_state(sc_no_recv)["state"] == ise.PURCHASE_TRANSIT


# ── 7. Idempotency ──────────────────────────────────────────────────────────

def test_already_direct_dispatch_ready_is_idempotent(client, storage):
    sc = _seed_packing("D-008", "EJL/DD/8")
    _seed_purchase(sc); _seed_receive(sc)
    _write_audit(storage, wfirma_export={"wfirma_pz_doc_id": "1"})

    body = {"batch_id": BATCH, "scan_codes": [sc],
            "operator": "amit", "customer_allocation": "X"}
    first  = client.post(URL, headers=_auth(), json=body).json()
    second = client.post(URL, headers=_auth(), json=body).json()
    assert first["transitioned"]   == 1
    assert second["transitioned"]  == 0
    assert second["already_ready"] == 1
    assert second["results"][0]["outcome"] == "already_ready"
    assert second["results"][0]["state"]   == ise.DIRECT_DISPATCH_READY


def test_client_dispatched_also_idempotent(client, storage):
    """A line already at CLIENT_DISPATCHED is reported as already_ready, not
    re-transitioned (which would be illegal)."""
    sc = _seed_packing("D-008b", "EJL/DD/8b")
    _seed_purchase(sc); _seed_receive(sc)
    ise.transition(scan_code=sc, to_state=ise.DIRECT_DISPATCH_READY,
                   operator="amit", customer_allocation="X",
                   customs_cleared=True)
    ise.transition(scan_code=sc, to_state=ise.CLIENT_DISPATCHED)
    _write_audit(storage, wfirma_export={"wfirma_pz_doc_id": "1"})

    r = client.post(URL, headers=_auth(), json={
        "batch_id": BATCH, "scan_codes": [sc],
        "operator": "amit", "customer_allocation": "X",
    })
    body = r.json()
    assert body["already_ready"] == 1
    assert body["results"][0]["state"] == ise.CLIENT_DISPATCHED


# ── 8. PURCHASE_TRANSIT lines become Proforma-eligible ──────────────────────

def test_purchase_transit_lines_become_proforma_eligible(client, storage):
    """End-to-end at the gate level: route promotes the lines, then the
    Proforma preview reports stock_status=direct_dispatch_ready and the
    stock blocker disappears."""
    sc = _seed_packing("D-009", "EJL/DD/9")
    _seed_purchase(sc); _seed_receive(sc)

    # Seed sales row + price + matched product/customer so the preview can run.
    sd = ddb.store_sales_document(
        batch_id=BATCH, document_id=str(uuid.uuid4()),
        data={"client_name": "DD-CLIENT", "client_ref": "REF",
              "sales_doc_no": "SO"},
    )
    ddb.store_sales_packing_lines(sd, BATCH, [{
        "client_name": "DD-CLIENT", "client_ref": "REF",
        "product_code": "D-009", "design_no": "D-009",
        "bag_id": "", "quantity": 1.0, "remarks": "",
        # Sales pricing (canonical source for Proforma):
        "unit_price": 50.0, "currency": "USD",
        "total_value": 50.0, "price_source": "packing_list",
    }])
    ddb.store_invoice_lines("doc-x", BATCH, [{
        "invoice_no": "INV/X", "line_position": 1,
        "product_code": "EJL/DD/9", "description": "",
        "quantity": 1.0, "unit_price": 50.0, "total_value": 50.0,
        "currency": "USD", "rate_usd": 50.0, "amount_usd": 50.0,
    }])
    wfdb.upsert_product(product_code="EJL/DD/9",
                        wfirma_product_id="42", sync_status="matched")
    wfdb.upsert_customer(client_name="DD-CLIENT",
                         wfirma_customer_id="9", country="PL",
                         vat_id="", match_status="matched")
    _write_audit(storage, wfirma_export={"wfirma_pz_doc_id": "183484963"})

    # Preview before — must block.
    pre = client.post(f"/api/v1/proforma/preview/{BATCH}/DD-CLIENT",
                      headers=_auth()).json()
    assert pre["ready"] is False
    assert pre["lines"][0]["stock_status"] == "purchase_transit"

    # Route call.
    r = client.post(URL, headers=_auth(), json={
        "batch_id": BATCH, "scan_codes": [sc],
        "operator": "amit", "customer_allocation": "DD-CLIENT",
    })
    assert r.status_code == 200, r.text
    assert r.json()["transitioned"] == 1

    # Preview after — must clear the stock blocker.
    post = client.post(f"/api/v1/proforma/preview/{BATCH}/DD-CLIENT",
                       headers=_auth()).json()
    assert post["lines"][0]["stock_status"] == "direct_dispatch_ready"
    assert post["lines"][0]["stock_ok"] is True
    assert post["ready"] is True


# ── 9. Caller-supplied customs_cleared is ignored (defence in depth) ────────

def test_caller_cannot_forge_customs_cleared(client, storage):
    """The route derives customs_cleared from audit.json. Even if a malicious
    caller sends customs_cleared=true in the body, the route must reject when
    audit has no clearance signals — the field is not part of the schema."""
    sc = _seed_packing("D-010", "EJL/DD/10")
    _seed_purchase(sc); _seed_receive(sc)
    _write_audit(storage, status="failed")  # no signals

    r = client.post(URL, headers=_auth(), json={
        "batch_id": BATCH, "scan_codes": [sc],
        "operator": "amit", "customer_allocation": "X",
        "customs_cleared": True,         # ignored — not in schema
        "customs_signals": ["forged"],   # ignored
    })
    assert r.status_code == 400
    assert "customs/PZ clearance evidence missing" in r.text
    assert ise.get_state(sc)["state"] == ise.PURCHASE_TRANSIT


# ── Auth wired ──────────────────────────────────────────────────────────────

def test_route_uses_api_key_dependency():
    """Pin: route registration includes the project's require_api_key
    dependency (imported in routes_lifecycle as _auth)."""
    from app.api import routes_lifecycle
    src = open(routes_lifecycle.__file__).read()
    assert ("/inventory-state/mark-direct-dispatch" in src and
            "dependencies=[_auth]" in src)
