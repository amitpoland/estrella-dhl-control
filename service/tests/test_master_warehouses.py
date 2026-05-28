"""test_master_warehouses.py — Phase 3 warehouses entity."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    for p in (str(here.parents[1]), str(here.parents[2])):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.audit import list_audit
from app.core.config import settings
from app.services import warehouses_db as W


# ── DB-layer ────────────────────────────────────────────────────────────────

def test_init_idempotent(tmp_path):
    db = tmp_path / "w.sqlite"
    W.init_db(db); W.init_db(db)
    assert W.list_warehouses(db) == []


def test_validate_code():
    assert W.validate_warehouse({"code": "lowercase"})
    assert not W.validate_warehouse({"code": "WH-WARSAW-01"})


@pytest.mark.parametrize("cat,ok", [
    ("own", True),
    ("supplier", True),
    ("customer_consignment", True),
    ("transit", True),
    ("customs_hold", True),
    ("warehouse", False),
    ("OWN", False),       # case-sensitive
])
def test_category_enum(cat, ok):
    errs = W.validate_warehouse({"code": "WH1", "category": cat})
    if ok:
        assert errs == []
    else:
        assert errs


@pytest.mark.parametrize("cc,ok", [
    ("PL", True),
    ("IN", True),
    ("pl", False),
    ("POL", False),
    ("P", False),
])
def test_country_code_validation(cc, ok):
    errs = W.validate_warehouse({"code": "WH1", "country_code": cc})
    if ok:
        assert errs == []
    else:
        assert any("country_code" in e for e in errs)


def test_upsert_and_get(tmp_path):
    db = tmp_path / "w.sqlite"
    W.init_db(db)
    rec = W.upsert_warehouse(db, {"code": "WH-WAW-01", "name": "Warsaw HQ",
                                  "category": "own", "country_code": "PL",
                                  "city": "Warsaw"})
    assert rec.code == "WH-WAW-01"
    assert rec.category == "own"
    assert rec.country_code == "PL"


def test_upsert_then_update(tmp_path):
    db = tmp_path / "w.sqlite"
    W.init_db(db)
    r1 = W.upsert_warehouse(db, {"code": "WH1", "category": "own",
                                 "country_code": "PL"})
    r2 = W.upsert_warehouse(db, {"code": "WH1", "category": "transit",
                                 "country_code": "PL"})
    assert r2.category == "transit"
    assert r2.created_at == r1.created_at


def test_list_filters(tmp_path):
    db = tmp_path / "w.sqlite"
    W.init_db(db)
    W.upsert_warehouse(db, {"code": "WH-A", "category": "own", "country_code": "PL"})
    W.upsert_warehouse(db, {"code": "WH-B", "category": "transit", "country_code": "IN"})
    W.upsert_warehouse(db, {"code": "WH-C", "category": "own", "country_code": "PL",
                            "active": False})
    assert len(W.list_warehouses(db)) == 3
    assert len(W.list_warehouses(db, active=True)) == 2
    assert len(W.list_warehouses(db, category="own")) == 2


def test_delete(tmp_path):
    db = tmp_path / "w.sqlite"
    W.init_db(db)
    W.upsert_warehouse(db, {"code": "WH-A", "category": "own", "country_code": "PL"})
    assert W.delete_warehouse(db, "WH-A") is True
    assert W.delete_warehouse(db, "WH-A") is False


# ── API + audit + role ──────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "TESTKEY")
    monkeypatch.setattr(settings, "master_audit_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", False)
    from app.api.routes_master_jewelry import warehouses_router
    app = FastAPI()
    app.include_router(warehouses_router)
    return TestClient(app, raise_server_exceptions=True)


_HDR = {"X-API-Key": "TESTKEY"}


def test_api_put_get(client):
    r = client.put("/api/v1/warehouses/WH-WAW-01",
                   json={"name": "Warsaw HQ", "category": "own",
                         "country_code": "PL", "city": "Warsaw"},
                   headers=_HDR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["country_code"] == "PL"
    g = client.get("/api/v1/warehouses/WH-WAW-01", headers=_HDR)
    assert g.status_code == 200


def test_api_invalid_category_rejected(client):
    r = client.put("/api/v1/warehouses/WH1",
                   json={"category": "rented", "country_code": "PL"}, headers=_HDR)
    assert r.status_code == 422


def test_api_invalid_country_rejected(client):
    r = client.put("/api/v1/warehouses/WH1",
                   json={"category": "own", "country_code": "pl"}, headers=_HDR)
    assert r.status_code == 422


def test_api_put_audit_create_then_update(client):
    client.put("/api/v1/warehouses/WH1",
               json={"category": "own", "country_code": "PL"}, headers=_HDR)
    client.put("/api/v1/warehouses/WH1",
               json={"category": "transit", "country_code": "PL"}, headers=_HDR)
    rows = list_audit(entity="warehouses", pk="WH1")
    ops = [r["op"] for r in rows]
    assert "create" in ops and "update" in ops
    update_row = [r for r in rows if r["op"] == "update"][0]
    assert update_row["diff_json"]["category"] == {"before": "own", "after": "transit"}


def test_api_delete_audit_with_before(client):
    client.put("/api/v1/warehouses/WH1",
               json={"category": "own", "country_code": "PL"}, headers=_HDR)
    r = client.delete("/api/v1/warehouses/WH1", headers=_HDR)
    assert r.status_code == 204
    [d] = [r for r in list_audit(entity="warehouses") if r["op"] == "delete"]
    assert d["before_json"]["code"] == "WH1"
    assert d["after_json"] is None


def test_role_gate_flag_on_editor_writes(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_editor"}):
        r = client.put("/api/v1/warehouses/WH1",
                       json={"category": "own", "country_code": "PL"},
                       cookies={"pz_session": "fake"})
    assert r.status_code == 200


def test_role_gate_flag_on_legacy_admin_blocked(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "admin"}):
        r = client.put("/api/v1/warehouses/WH1",
                       json={"category": "own", "country_code": "PL"},
                       cookies={"pz_session": "fake"})
    assert r.status_code == 403
