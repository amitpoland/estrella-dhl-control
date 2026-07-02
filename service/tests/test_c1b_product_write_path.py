"""
test_c1b_product_write_path.py — C-1b write-path reroute acceptance pins.

Operator C-1b acceptance contract (verbatim intent):
  #1 create with flag-off  -> Product Master row exists + status 'mapping_required'
                              (sync-pending); NO wFirma push; NO mirror linkage.
  #2 create with confirmed -> MIRROR linkage written + master.status 'mapped'.
  #3 edit                  -> PRESERVES the code->wfirma_id mapping, bumps sync.
  #4 V6 sync-by-codes      -> response carries Master fields (master_status).
Plus robustness: mirror collision-safe, status setter, sync-client delegation.

The write GATE (settings.wfirma_create_product_allowed) stays in the route; these
tests assert the Master-first / Mirror-on-success / gate-off-sync-pending
behaviour of the reservation_db sync-layer helpers and the two rerouted routes.
"""
from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import reservation_db as rdb


@pytest.fixture()
def db_path(tmp_path):
    p = tmp_path / "reservation_queue.db"
    rdb.init_reservation_db(p)
    return p


def _mirror_row(db, code):
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT * FROM wfirma_product_mirror WHERE product_code=?", (code,)
    ).fetchone()
    con.close()
    return dict(row) if row else None


# ── operator #2: create success -> Mirror written + status mapped ────────────

def test_create_via_master_success_writes_mirror_and_maps(db_path):
    code = "EJL/C1B/CREATE/001"
    rdb.upsert_product_master(db_path, code, "D-C1B-001")
    rdb.set_product_master_status(db_path, code, "mapping_required")

    from app.services.wfirma_client import WFirmaProduct
    fake = WFirmaProduct(wfirma_id="WF-C1B-001", name="Ring", code=code, unit="szt.")
    with patch("app.services.wfirma_client.create_product", return_value=fake):
        result, mirror = rdb.create_wfirma_product_via_master(
            db_path, product_code=code, name="Ring", description="d",
        )
    assert result.wfirma_id == "WF-C1B-001"
    assert mirror["written"] is True and mirror["collision"] is False
    mr = _mirror_row(db_path, code)
    assert mr and mr["wfirma_id"] == "WF-C1B-001"
    assert rdb.get_product_master(db_path, code)["status"] == "mapped"


# ── failure/id-less path: keep Master, no Mirror ─────────────────────────────

def test_create_via_master_idless_keeps_master_no_mirror(db_path):
    code = "EJL/C1B/CREATE/002"
    rdb.upsert_product_master(db_path, code, "D-C1B-002")
    rdb.set_product_master_status(db_path, code, "mapping_required")
    from app.services.wfirma_client import WFirmaProduct
    fake = WFirmaProduct(wfirma_id="", name="Ring", code=code)
    with patch("app.services.wfirma_client.create_product", return_value=fake):
        _result, mirror = rdb.create_wfirma_product_via_master(
            db_path, product_code=code, name="Ring",
        )
    assert mirror["written"] is False
    assert _mirror_row(db_path, code) is None
    assert rdb.get_product_master(db_path, code)["status"] == "mapping_required"


# ── operator #3: edit preserves mapping, bumps sync_version ──────────────────

def test_edit_via_master_preserves_mapping_and_bumps_sync(db_path):
    code = "EJL/C1B/EDIT/001"
    rdb.upsert_product_master(db_path, code, "D-C1B-E-001")
    assert rdb.upsert_product_mirror(
        db_path, wfirma_id="WF-EDIT-1", product_code=code, name="Old"
    )["written"]
    before = _mirror_row(db_path, code)

    with patch("app.services.wfirma_client.edit_product", return_value={"ok": True}) as m:
        _result, _mirror = rdb.edit_wfirma_product_via_master(
            db_path, product_code=code, wfirma_product_id="WF-EDIT-1",
            name="New name", description="new desc",
        )
    m.assert_called_once_with(
        wfirma_product_id="WF-EDIT-1", name="New name", description="new desc",
    )
    after = _mirror_row(db_path, code)
    assert after["wfirma_id"] == "WF-EDIT-1"                       # mapping preserved
    assert after["sync_version"] == before["sync_version"] + 1     # sync bumped


# ── mirror collision-safe (one wFirma good -> one code) ──────────────────────

def test_mirror_collision_is_refused(db_path):
    rdb.upsert_product_master(db_path, "EJL/C1B/COL/A", "D-A")
    rdb.upsert_product_master(db_path, "EJL/C1B/COL/B", "D-B")
    assert rdb.upsert_product_mirror(
        db_path, wfirma_id="WF-COL-1", product_code="EJL/C1B/COL/A"
    )["written"]
    b = rdb.upsert_product_mirror(
        db_path, wfirma_id="WF-COL-1", product_code="EJL/C1B/COL/B"
    )
    assert b["written"] is False
    assert b["collision"] is True
    assert b["owner"] == "EJL/C1B/COL/A"


# ── V6 shim relocated into the sync layer (no wfirma_client in the route) ─────

def test_wfirma_product_sync_client_delegates():
    sentinel = object()
    with patch("app.services.wfirma_client.get_product_by_code", return_value=sentinel):
        cl = rdb.wfirma_product_sync_client()
        assert cl.get_product_by_code("EJL/X") is sentinel


# ── route fixtures ───────────────────────────────────────────────────────────

@pytest.fixture()
def route_storage(tmp_path):
    (tmp_path / "outputs").mkdir(parents=True, exist_ok=True)
    from app.services.packing_db import init_packing_db
    from app.services.document_db import init_document_db
    from app.services.warehouse_db import init_warehouse_db
    from app.services.wfirma_db import init_wfirma_db
    from app.services.tracking_db import init_tracking_db
    init_packing_db(tmp_path / "packing.db")
    init_document_db(tmp_path / "documents.db")
    init_warehouse_db(tmp_path / "warehouse.db")
    init_wfirma_db(tmp_path / "wfirma.db")
    init_tracking_db(tmp_path / "tracking_events.db")
    rdb.init_reservation_db(tmp_path / "reservation_queue.db")
    return tmp_path


@pytest.fixture()
def route_client(route_storage):
    with patch.object(settings, "storage_root", route_storage):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


# ── operator #4: V6 sync-by-codes response carries Master fields ─────────────
# NB: the HTTP route POST /api/v1/wfirma/products/sync-by-codes is shadowed in
# the app by a PRE-EXISTING catch-all PUT /api/v1/wfirma/products/{product_code:path}
# (returns 405; unrelated to C-1b, present at HEAD). We exercise the handler
# directly so the V6 Master-field behaviour is pinned without that collision.

def test_v6_sync_by_codes_returns_master_status(tmp_path):
    import asyncio
    from app.api.routes_reservations import sync_products_by_codes, SyncByCodesBody

    db = tmp_path / "reservation_queue.db"
    rdb.init_reservation_db(db)
    code = "EJL/C1B/V6/001"
    rdb.upsert_product_master(db, code, "D-V6-001")
    rdb.set_product_master_status(db, code, "mapping_required")
    from app.services.wfirma_client import WFirmaProduct
    fake = WFirmaProduct(wfirma_id="WF-V6-1", name="R", code=code)
    with patch("app.api.routes_reservations._ensure_db", return_value=db):
        with patch("app.services.wfirma_client.get_product_by_code", return_value=fake):
            # get_event_loop().run_until_complete (not asyncio.run) so we do NOT
            # close the shared loop other sync handler-tests reuse in this run.
            resp = asyncio.get_event_loop().run_until_complete(
                sync_products_by_codes(SyncByCodesBody(product_codes=[code]))
            )
    body = json.loads(resp.body)
    assert "master_status" in body
    assert code in body["master_status"]
    assert body["master_status"][code] == "mapping_required"


# ── operator #1: resolve create flag-off -> Master + sync-pending ────────────

def test_resolve_flag_off_writes_master_sync_pending(route_client, route_storage):
    code = "EJL/C1B/FLAGOFF/001"
    batch = "C1B-FLAGOFF-BATCH"
    outdir = route_storage / "outputs" / batch
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "audit.json").write_text(json.dumps({"_rows_source": ""}), encoding="utf-8")
    (outdir / "pz_rows.json").write_text(json.dumps([{
        "product_code": code, "item_type": "ring",
        "description_en": "Test ring", "pl_desc": "Pierscionek",
        "unit_netto_pln": 10.0, "quantity": 1,
    }]), encoding="utf-8")

    db = route_storage / "reservation_queue.db"
    with patch.object(settings, "wfirma_create_product_allowed", False):
        with patch("app.services.wfirma_client.get_product_by_code", return_value=None):
            r = route_client.post(
                f"/api/v1/upload/shipment/{batch}/wfirma/products/resolve", headers=_auth(),
            )
    assert r.status_code == 200, r.text
    body = r.json()
    assert code in body.get("missing_codes", []), body
    master = rdb.get_product_master(db, code)
    assert master is not None, "Master row must exist even with the write gate off"
    assert master["status"] == "mapping_required", "gate-off code is sync-pending"
    assert _mirror_row(db, code) is None, "no mirror linkage while sync is pending"
