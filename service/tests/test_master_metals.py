"""test_master_metals.py — Phase 3 metals entity (DB + API + audit + role)."""
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
from app.services import metals_db as M


# ── DB-layer tests ──────────────────────────────────────────────────────────

def test_init_db_idempotent(tmp_path):
    db = tmp_path / "metals.sqlite"
    M.init_db(db); M.init_db(db)
    assert db.exists()
    assert M.list_metals(db) == []


def test_validate_code_regex():
    assert M.validate_metal({"code": ""})    # missing
    assert M.validate_metal({"code": "ab"})  # lowercase
    assert M.validate_metal({"code": "A"})   # too short
    assert M.validate_metal({"code": "X" * 33})  # too long
    assert not M.validate_metal({"code": "AU750"})
    assert not M.validate_metal({"code": "AG-925"})


@pytest.mark.parametrize("metal_type,purity,ok", [
    ("gold",      750, True),
    ("gold",      999, True),
    ("gold",      777, False),
    ("silver",    925, True),
    ("silver",    800, True),
    ("silver",    925.5, True),     # 925.5 → int(925) — but float fails int; check below
    ("silver",    900, False),
    ("platinum",  950, True),
    ("platinum",  925, False),
    ("palladium", 999, True),
    ("other",     1,   True),
    ("other",     999, True),
    ("other",     0,   False),
    ("other",     1000, False),
])
def test_purity_validation(metal_type, purity, ok):
    errs = M.validate_metal({"code": "X1", "metal_type": metal_type,
                             "purity_pct": purity})
    if ok:
        assert errs == [], f"unexpected: {errs}"
    else:
        assert errs, "expected validation failure"


def test_metal_type_enum_validation():
    errs = M.validate_metal({"code": "X1", "metal_type": "uranium"})
    assert any("metal_type must be one of" in e for e in errs)


def test_upsert_create_then_update(tmp_path):
    db = tmp_path / "m.sqlite"
    M.init_db(db)
    rec = M.upsert_metal(db, {"code": "AU750", "name": "18K Gold",
                              "metal_type": "gold", "purity_pct": 750})
    assert rec.code == "AU750"
    assert rec.metal_type == "gold"
    assert rec.purity_pct == 750
    assert rec.created_at == rec.updated_at  # first write
    rec2 = M.upsert_metal(db, {"code": "AU750", "name": "18K Gold (updated)",
                               "metal_type": "gold", "purity_pct": 750})
    assert rec2.name == "18K Gold (updated)"
    assert rec2.created_at == rec.created_at  # preserved
    assert rec2.updated_at >= rec.updated_at


def test_list_filters(tmp_path):
    db = tmp_path / "m.sqlite"
    M.init_db(db)
    M.upsert_metal(db, {"code": "AU750", "metal_type": "gold", "purity_pct": 750})
    M.upsert_metal(db, {"code": "AG925", "metal_type": "silver", "purity_pct": 925})
    M.upsert_metal(db, {"code": "PT950", "metal_type": "platinum", "purity_pct": 950,
                        "active": False})
    assert len(M.list_metals(db)) == 3
    assert len(M.list_metals(db, active=True))  == 2
    assert len(M.list_metals(db, active=False)) == 1
    assert len(M.list_metals(db, metal_type="gold")) == 1


def test_delete_returns_false_for_missing(tmp_path):
    db = tmp_path / "m.sqlite"
    M.init_db(db)
    assert M.delete_metal(db, "MISSING") is False
    M.upsert_metal(db, {"code": "AU750", "metal_type": "gold", "purity_pct": 750})
    assert M.delete_metal(db, "AU750") is True
    assert M.get_metal(db, "AU750") is None


def test_purity_no_float_coercion(tmp_path):
    db = tmp_path / "m.sqlite"
    M.init_db(db)
    # Float input is coerced to int via int(750.0) — that's allowed since the
    # field is stored as INTEGER. But float that loses precision is rejected
    # by the validator if it can't int-convert cleanly.
    rec = M.upsert_metal(db, {"code": "AU750", "metal_type": "gold",
                              "purity_pct": 750.0})
    assert rec.purity_pct == 750
    assert isinstance(rec.purity_pct, int)


# ── API + audit + role-gate tests ───────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "TESTKEY")
    monkeypatch.setattr(settings, "master_audit_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", False)
    from app.api.routes_master_jewelry import metals_router
    app = FastAPI()
    app.include_router(metals_router)
    return TestClient(app, raise_server_exceptions=True)


_HDR = {"X-API-Key": "TESTKEY"}


def test_api_list_empty(client):
    r = client.get("/api/v1/metals/", headers=_HDR)
    assert r.status_code == 200
    assert r.json() == {"count": 0, "metals": []}


def test_api_put_then_get(client):
    r = client.put("/api/v1/metals/AU750",
                   json={"name": "18K Gold", "metal_type": "gold",
                         "purity_pct": 750}, headers=_HDR)
    assert r.status_code == 200, r.text
    assert r.json()["purity_pct"] == 750
    r = client.get("/api/v1/metals/AU750", headers=_HDR)
    assert r.status_code == 200
    assert r.json()["metal_type"] == "gold"


def test_api_put_rejects_invalid_purity(client):
    r = client.put("/api/v1/metals/AU777",
                   json={"metal_type": "gold", "purity_pct": 777}, headers=_HDR)
    assert r.status_code == 422
    assert "purity_pct" in r.text


def test_api_put_writes_create_audit(client):
    client.put("/api/v1/metals/AU750",
               json={"metal_type": "gold", "purity_pct": 750}, headers=_HDR)
    [row] = list_audit(entity="metals", pk="AU750")
    assert row["op"] == "create"
    assert row["after_json"]["purity_pct"] == 750


def test_api_second_put_writes_update_audit(client):
    client.put("/api/v1/metals/AU750",
               json={"metal_type": "gold", "purity_pct": 750,
                     "purity_label": "18K"}, headers=_HDR)
    client.put("/api/v1/metals/AU750",
               json={"metal_type": "gold", "purity_pct": 750,
                     "purity_label": "18K stamped"}, headers=_HDR)
    rows = list_audit(entity="metals", pk="AU750")
    ops = [r["op"] for r in rows]
    assert "create" in ops and "update" in ops


def test_api_delete_writes_audit_with_before(client):
    client.put("/api/v1/metals/AU750",
               json={"metal_type": "gold", "purity_pct": 750}, headers=_HDR)
    r = client.delete("/api/v1/metals/AU750", headers=_HDR)
    assert r.status_code == 204
    rows = list_audit(entity="metals", pk="AU750")
    [d] = [r for r in rows if r["op"] == "delete"]
    assert d["before_json"]["code"] == "AU750"
    assert d["after_json"] is None


def test_api_delete_404_on_missing(client):
    r = client.delete("/api/v1/metals/NOPE", headers=_HDR)
    assert r.status_code == 404


# ── Role gate behaviour (flag on) ───────────────────────────────────────────

def test_role_gate_flag_on_master_editor_writes(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_editor"}):
        r = client.put("/api/v1/metals/AU750",
                       json={"metal_type": "gold", "purity_pct": 750},
                       cookies={"pz_session": "fake"})
    assert r.status_code == 200


def test_role_gate_flag_on_viewer_blocked(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_viewer"}):
        r = client.put("/api/v1/metals/AU750",
                       json={"metal_type": "gold", "purity_pct": 750},
                       cookies={"pz_session": "fake"})
    assert r.status_code == 403


def test_role_gate_flag_on_legacy_admin_blocked(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "admin"}):
        r = client.put("/api/v1/metals/AU750",
                       json={"metal_type": "gold", "purity_pct": 750},
                       cookies={"pz_session": "fake"})
    assert r.status_code == 403


def test_role_gate_flag_on_read_still_works_with_apikey(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    r = client.get("/api/v1/metals/", headers=_HDR)
    assert r.status_code == 200
