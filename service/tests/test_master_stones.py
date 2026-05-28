"""test_master_stones.py — Phase 3 stones entity (DB + API + audit + role)."""
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
from app.services import stones_db as S


# ── DB-layer ────────────────────────────────────────────────────────────────

def test_init_idempotent(tmp_path):
    db = tmp_path / "s.sqlite"
    S.init_db(db); S.init_db(db)
    assert S.list_stones(db) == []


def test_validate_code(tmp_path):
    assert S.validate_stone({"code": "ok"})       # lowercase rejected
    assert S.validate_stone({"code": "A"})        # too short
    assert not S.validate_stone({"code": "DIA-001"})


def test_stone_type_enum():
    assert S.validate_stone({"code": "X1", "stone_type": "topaz"})
    assert not S.validate_stone({"code": "X1", "stone_type": "diamond"})


def test_shape_enum():
    assert S.validate_stone({"code": "X1", "shape": "trapezoid"})
    assert not S.validate_stone({"code": "X1", "shape": "round"})


def test_cert_type_enum():
    assert S.validate_stone({"code": "X1", "cert_type": "Other"})  # case-sensitive
    assert not S.validate_stone({"code": "X1", "cert_type": "GIA"})
    assert not S.validate_stone({"code": "X1", "cert_type": "none"})


def test_carat_weight_no_float():
    """Decimal-as-string discipline — float MUST be rejected."""
    errs = S.validate_stone({"code": "X1", "carat_weight": 1.25})
    assert any("Decimal-as-string" in e for e in errs)


def test_carat_weight_string_decimal_ok():
    assert S.validate_stone({"code": "X1", "carat_weight": "1.25"}) == []
    assert S.validate_stone({"code": "X1", "carat_weight": "0"})     == []


def test_carat_weight_negative_rejected():
    errs = S.validate_stone({"code": "X1", "carat_weight": "-0.5"})
    assert any(">= 0" in e for e in errs)


def test_carat_weight_round_trip_preserves_string(tmp_path):
    db = tmp_path / "s.sqlite"
    S.init_db(db)
    rec = S.upsert_stone(db, {"code": "DIA1", "stone_type": "diamond",
                              "carat_weight": "1.250"})
    # Exact string preserved (trailing zero kept).
    assert rec.carat_weight == "1.250"
    assert isinstance(rec.carat_weight, str)


def test_upsert_create_then_update(tmp_path):
    db = tmp_path / "s.sqlite"
    S.init_db(db)
    rec = S.upsert_stone(db, {"code": "DIA1", "stone_type": "diamond",
                              "shape": "round", "carat_weight": "1.01",
                              "cert_type": "GIA", "cert_id": "GIA-12345",
                              "cert_lab": "GIA New York"})
    assert rec.cert_type == "GIA" and rec.cert_id == "GIA-12345"
    rec2 = S.upsert_stone(db, {"code": "DIA1", "stone_type": "diamond",
                               "shape": "oval", "carat_weight": "1.01"})
    assert rec2.shape == "oval"


def test_list_filters(tmp_path):
    db = tmp_path / "s.sqlite"
    S.init_db(db)
    S.upsert_stone(db, {"code": "D1", "stone_type": "diamond"})
    S.upsert_stone(db, {"code": "R1", "stone_type": "ruby", "active": False})
    assert len(S.list_stones(db, active=True)) == 1
    assert len(S.list_stones(db, stone_type="ruby")) == 1


def test_delete(tmp_path):
    db = tmp_path / "s.sqlite"
    S.init_db(db)
    S.upsert_stone(db, {"code": "D1", "stone_type": "diamond"})
    assert S.delete_stone(db, "D1") is True
    assert S.delete_stone(db, "D1") is False


# ── API + audit + role ──────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "TESTKEY")
    monkeypatch.setattr(settings, "master_audit_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", False)
    from app.api.routes_master_jewelry import stones_router
    app = FastAPI()
    app.include_router(stones_router)
    return TestClient(app, raise_server_exceptions=True)


_HDR = {"X-API-Key": "TESTKEY"}


def test_api_put_get(client):
    r = client.put("/api/v1/stones/DIA-001",
                   json={"stone_type": "diamond", "shape": "round",
                         "carat_weight": "1.05", "cert_type": "GIA",
                         "cert_id": "GIA-9876"},
                   headers=_HDR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["carat_weight"] == "1.05"
    assert body["cert_type"] == "GIA"
    g = client.get("/api/v1/stones/DIA-001", headers=_HDR)
    assert g.status_code == 200


def test_api_put_rejects_float_carat(client):
    r = client.put("/api/v1/stones/DIA-002",
                   json={"stone_type": "diamond", "carat_weight": 1.05},
                   headers=_HDR)
    assert r.status_code == 422


def test_api_put_audit_create(client):
    client.put("/api/v1/stones/DIA-A",
               json={"stone_type": "diamond"}, headers=_HDR)
    [row] = list_audit(entity="stones", pk="DIA-A")
    assert row["op"] == "create"


def test_api_put_audit_update(client):
    client.put("/api/v1/stones/DIA-A",
               json={"stone_type": "diamond", "shape": "round"}, headers=_HDR)
    client.put("/api/v1/stones/DIA-A",
               json={"stone_type": "diamond", "shape": "oval"}, headers=_HDR)
    rows = list_audit(entity="stones", pk="DIA-A")
    ops = [r["op"] for r in rows]
    assert "create" in ops and "update" in ops


def test_api_delete_audit(client):
    client.put("/api/v1/stones/DIA-A",
               json={"stone_type": "diamond"}, headers=_HDR)
    r = client.delete("/api/v1/stones/DIA-A", headers=_HDR)
    assert r.status_code == 204
    [d] = [r for r in list_audit(entity="stones") if r["op"] == "delete"]
    assert d["before_json"]["code"] == "DIA-A"
    assert d["after_json"] is None


def test_role_gate_flag_on_master_admin_writes(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_admin"}):
        r = client.put("/api/v1/stones/DIA-A",
                       json={"stone_type": "diamond"},
                       cookies={"pz_session": "fake"})
    assert r.status_code == 200


def test_role_gate_flag_on_viewer_blocked(client, monkeypatch):
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_viewer"}):
        r = client.put("/api/v1/stones/DIA-A",
                       json={"stone_type": "diamond"},
                       cookies={"pz_session": "fake"})
    assert r.status_code == 403
