"""Product Master status is a projection of confirmed canonical mapping.

Invariant: confirmed wFirma mapping (mirror id + cache sync_status='matched')
projects product_master.status='mapped'. Pending / missing / mismatched ids
must not flip mapping_required. Repeat projection is idempotent.

Covers register_product_identity (shared by adopt / update-and-adopt /
create-and-adopt) plus the HTTP mapping-success paths.
"""
from __future__ import annotations

from dataclasses import dataclass
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import reservation_db as rdb
from app.services import wfirma_db as wfdb


CODE = "EJL/26-27/PROJ-1"
WFID = "51677283"


@dataclass
class _WFStub:
    wfirma_id: str = WFID
    name: str = "Pierścionek"
    code: str = CODE
    unit: str = "szt."
    count: float = 0.0
    reserved: float = 0.0


@pytest.fixture
def dbs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    monkeypatch.setattr(settings, "environment", "dev", raising=False)
    rdb.init_reservation_db(tmp_path / "reservation_queue.db")
    wfdb.init_wfirma_db(tmp_path / "wfirma.db")
    return tmp_path / "reservation_queue.db"


def _seed_master(db_path, code=CODE, status="mapping_required"):
    rdb.upsert_product_master(db_path, code, "D-PROJ")
    rdb.set_product_master_status(db_path, code, status)


def _register(db_path, *, wfirma_id, sync_status, cache_id=None, also=None):
    return rdb.register_product_identity(
        db_path,
        wfirma_id=wfirma_id,
        product_code=CODE,
        name="Pierścionek",
        also_set_master_status=also,
        cache_kwargs=dict(
            product_code=CODE,
            wfirma_product_id=cache_id if cache_id is not None else wfirma_id,
            product_name_pl="Pierścionek",
            unit="szt.",
            vat_rate="23",
            sync_status=sync_status,
        ),
    )


def test_confirmed_helper_projects_mapped_only_on_match():
    assert rdb.confirmed_mapping_master_status(
        wfirma_id=WFID,
        cache_kwargs={"wfirma_product_id": WFID, "sync_status": "matched"},
    ) == "mapped"
    assert rdb.confirmed_mapping_master_status(
        wfirma_id="",
        cache_kwargs={"wfirma_product_id": "", "sync_status": "pending"},
    ) is None
    assert rdb.confirmed_mapping_master_status(
        wfirma_id=WFID,
        cache_kwargs={"wfirma_product_id": WFID, "sync_status": "pending_adoption"},
    ) is None
    assert rdb.confirmed_mapping_master_status(
        wfirma_id=WFID,
        cache_kwargs={"wfirma_product_id": "OTHER", "sync_status": "matched"},
    ) is None
    assert rdb.confirmed_mapping_master_status(
        wfirma_id=WFID,
        cache_kwargs={"wfirma_product_id": WFID, "sync_status": "matched"},
        also_set_master_status="mapped",
    ) == "mapped"


def test_register_matched_projects_master_mapped(dbs):
    _seed_master(dbs)
    result = _register(dbs, wfirma_id=WFID, sync_status="matched")
    assert result["collision"] is False
    assert rdb.get_product_master(dbs, CODE)["status"] == "mapped"


def test_register_matched_is_idempotent(dbs):
    _seed_master(dbs)
    _register(dbs, wfirma_id=WFID, sync_status="matched")
    _register(dbs, wfirma_id=WFID, sync_status="matched")
    assert rdb.get_product_master(dbs, CODE)["status"] == "mapped"


def test_empty_id_does_not_flip_mapping_required(dbs):
    _seed_master(dbs)
    _register(dbs, wfirma_id="", sync_status="pending", cache_id="")
    assert rdb.get_product_master(dbs, CODE)["status"] == "mapping_required"


def test_pending_sync_status_does_not_flip(dbs):
    _seed_master(dbs)
    _register(dbs, wfirma_id=WFID, sync_status="pending_adoption")
    assert rdb.get_product_master(dbs, CODE)["status"] == "mapping_required"


def test_mismatched_cache_id_does_not_flip(dbs):
    _seed_master(dbs)
    _register(dbs, wfirma_id=WFID, sync_status="matched", cache_id="NOT-THE-SAME")
    assert rdb.get_product_master(dbs, CODE)["status"] == "mapping_required"


@pytest.fixture
def client(dbs, monkeypatch):
    monkeypatch.setattr(settings, "wfirma_create_product_allowed", True, raising=False)
    monkeypatch.setattr(settings, "wfirma_edit_product_allowed", True, raising=False)
    return TestClient(app)


def test_create_and_adopt_projects_master_mapped(dbs, client, monkeypatch):
    _seed_master(dbs)
    from app.services import wfirma_client as wc
    from app.services import description_engine as deng

    monkeypatch.setattr(wc, "get_product_by_code", lambda code: None)
    monkeypatch.setattr(wc, "find_vat_code_id", lambda rate: "222")
    monkeypatch.setattr(
        deng, "get_description_block",
        lambda **kw: {
            "name_pl": "Pierścionek",
            "description_line": "Pierścionek / RING",
            "description_block": "block",
        },
    )
    monkeypatch.setattr(
        wc, "create_product",
        lambda **kw: _WFStub(wfirma_id=WFID, code=CODE),
    )
    r = client.post(
        f"/api/v1/wfirma/goods/create-and-adopt/{CODE}",
        json={"item_type": "", "description_en": "RING"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["wfirma_product_id"] == WFID
    assert r.json().get("incomplete_convergence") is False
    assert rdb.get_product_master(dbs, CODE)["status"] == "mapped"


def test_adopt_projects_master_mapped(dbs, client, monkeypatch):
    _seed_master(dbs)
    from app.services import wfirma_client as wc

    monkeypatch.setattr(
        wc, "get_product_by_code",
        lambda code: _WFStub(wfirma_id=WFID, code=CODE),
    )
    r = client.post(f"/api/v1/wfirma/goods/adopt/{CODE}")
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "adopted"
    assert r.json().get("incomplete_convergence") is False
    assert rdb.get_product_master(dbs, CODE)["status"] == "mapped"


def test_update_and_adopt_projects_master_mapped(dbs, client, monkeypatch):
    _seed_master(dbs)
    from app.services import wfirma_client as wc

    monkeypatch.setattr(
        wc, "get_product_by_code",
        lambda code: _WFStub(wfirma_id=WFID, name="Old", code=CODE),
    )
    monkeypatch.setattr(
        wc, "edit_product",
        lambda wfirma_product_id, **kw: {
            "wfirma_id": wfirma_product_id,
            "name": kw.get("name") or "Old",
            "code": CODE,
            "unit": "szt.",
        },
    )
    r = client.post(
        f"/api/v1/wfirma/goods/update-and-adopt/{CODE}",
        json={"name": "Updated name"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "updated_and_adopted"
    assert r.json().get("incomplete_convergence") is False
    assert rdb.get_product_master(dbs, CODE)["status"] == "mapped"


def test_failed_create_does_not_flip_master(dbs, client, monkeypatch):
    _seed_master(dbs)
    from app.services import wfirma_client as wc
    from app.services import description_engine as deng

    monkeypatch.setattr(wc, "get_product_by_code", lambda code: None)
    monkeypatch.setattr(wc, "find_vat_code_id", lambda rate: "222")
    monkeypatch.setattr(
        deng, "get_description_block",
        lambda **kw: {
            "name_pl": "Pierścionek",
            "description_line": "Pierścionek / RING",
            "description_block": "block",
        },
    )

    def _boom(**kw):
        raise RuntimeError("goods/add failed")

    monkeypatch.setattr(wc, "create_product", _boom)
    r = client.post(
        f"/api/v1/wfirma/goods/create-and-adopt/{CODE}",
        json={"item_type": "", "description_en": "RING"},
    )
    assert r.status_code == 502
    assert rdb.get_product_master(dbs, CODE)["status"] == "mapping_required"


def test_create_blocked_flag_off_does_not_flip_master(dbs, client, monkeypatch):
    _seed_master(dbs)
    monkeypatch.setattr(settings, "wfirma_create_product_allowed", False, raising=False)
    r = client.post(
        f"/api/v1/wfirma/goods/create-and-adopt/{CODE}",
        json={"item_type": "", "description_en": "RING"},
    )
    assert r.status_code == 403
    assert rdb.get_product_master(dbs, CODE)["status"] == "mapping_required"


def test_auto_register_explicit_mapped_still_projects(dbs):
    """auto-register already passes also_set_master_status='mapped'; keep that path."""
    _seed_master(dbs)
    result = _register(
        dbs, wfirma_id=WFID, sync_status="matched", also="mapped",
    )
    assert result["collision"] is False
    assert rdb.get_product_master(dbs, CODE)["status"] == "mapped"
