"""test_master_soft_delete_phase4a.py — Phase 4A soft-delete + restore.

Three jewelry entities only. Per-entity matrix:
  - soft-delete sets active=false + deleted_at; audit op=delete
  - default list excludes inactive
  - active=false list includes inactive (and excludes active)
  - get-by-code returns inactive records with active=false + deleted_at
  - restore resets active=true, deleted_at=null; audit op=restore
  - hard delete (?hard=true) blocked when flag false → 409
  - hard delete blocked for master_editor even with flag true → 403
  - hard delete allowed for master_admin when flag true → 204 + audit hard_delete
"""
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


# ── Parametrisation across the three Phase 3/4A entities ────────────────────

ENTITIES = [
    {
        "name": "metals",
        "router": "metals_router",
        "api":   "/api/v1/metals",
        "code":  "AU750",
        "create_body": {"metal_type": "gold", "purity_pct": 750},
    },
    {
        "name": "stones",
        "router": "stones_router",
        "api":   "/api/v1/stones",
        "code":  "DIA-1",
        "create_body": {"stone_type": "diamond"},
    },
    {
        "name": "warehouses",
        "router": "warehouses_router",
        "api":   "/api/v1/warehouses",
        "code":  "WH-A",
        "create_body": {"category": "own", "country_code": "PL"},
    },
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "TESTKEY")
    monkeypatch.setattr(settings, "master_audit_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", False)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", False)
    from app.api import routes_master_jewelry as rj
    app = FastAPI()
    app.include_router(rj.metals_router)
    app.include_router(rj.stones_router)
    app.include_router(rj.warehouses_router)
    return TestClient(app, raise_server_exceptions=True)


_HDR = {"X-API-Key": "TESTKEY"}


def _seed(client, ent):
    r = client.put(f"{ent['api']}/{ent['code']}",
                   json=ent["create_body"], headers=_HDR)
    assert r.status_code == 200, r.text


# ── Soft delete ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_soft_delete_sets_active_false_and_deleted_at(client, ent):
    _seed(client, ent)
    r = client.delete(f"{ent['api']}/{ent['code']}", headers=_HDR)
    assert r.status_code == 204
    # Get-by-code still returns the (inactive) record with deleted_at set.
    g = client.get(f"{ent['api']}/{ent['code']}", headers=_HDR)
    assert g.status_code == 200
    body = g.json()
    assert body["active"] is False
    assert body.get("deleted_at"), f"deleted_at must be set; got {body}"


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_soft_delete_audit_op_is_delete(client, ent):
    _seed(client, ent)
    client.delete(f"{ent['api']}/{ent['code']}", headers=_HDR)
    rows = list_audit(entity=ent["name"], pk=ent["code"])
    delete_rows = [r for r in rows if r["op"] == "delete"]
    assert len(delete_rows) == 1
    # Soft-delete audit shape: before populated, after = None (parity with
    # legacy hard-delete consumers).
    assert delete_rows[0]["before_json"]["code"] == ent["code"]
    assert delete_rows[0]["after_json"] is None


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_default_list_excludes_inactive(client, ent):
    _seed(client, ent)
    client.delete(f"{ent['api']}/{ent['code']}", headers=_HDR)
    r = client.get(f"{ent['api']}/", headers=_HDR)
    assert r.status_code == 200
    body = r.json()
    codes = [m["code"] for m in body[ent["name"]]]
    assert ent["code"] not in codes
    assert body["count"] == 0


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_active_false_list_includes_inactive(client, ent):
    _seed(client, ent)
    client.delete(f"{ent['api']}/{ent['code']}", headers=_HDR)
    r = client.get(f"{ent['api']}/?active=false", headers=_HDR)
    assert r.status_code == 200
    codes = [m["code"] for m in r.json()[ent["name"]]]
    assert ent["code"] in codes


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_active_true_list_excludes_inactive(client, ent):
    _seed(client, ent)
    client.delete(f"{ent['api']}/{ent['code']}", headers=_HDR)
    r = client.get(f"{ent['api']}/?active=true", headers=_HDR)
    codes = [m["code"] for m in r.json()[ent["name"]]]
    assert ent["code"] not in codes


# ── Restore ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_restore_sets_active_true_and_clears_deleted_at(client, ent):
    _seed(client, ent)
    client.delete(f"{ent['api']}/{ent['code']}", headers=_HDR)
    r = client.post(f"{ent['api']}/{ent['code']}/restore", headers=_HDR)
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is True
    assert body.get("deleted_at") in (None, "")


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_restore_writes_audit_row_with_op_restore(client, ent):
    _seed(client, ent)
    client.delete(f"{ent['api']}/{ent['code']}", headers=_HDR)
    client.post(f"{ent['api']}/{ent['code']}/restore", headers=_HDR)
    rows = list_audit(entity=ent["name"], pk=ent["code"])
    restore_rows = [r for r in rows if r["op"] == "restore"]
    assert len(restore_rows) == 1
    # Before = inactive record; after = restored record.
    assert restore_rows[0]["before_json"]["active"] is False
    assert restore_rows[0]["after_json"]["active"] is True


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_restore_returns_404_on_missing(client, ent):
    r = client.post(f"{ent['api']}/NEVER-EXISTED/restore", headers=_HDR)
    assert r.status_code == 404


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_restored_record_visible_in_default_list(client, ent):
    _seed(client, ent)
    client.delete(f"{ent['api']}/{ent['code']}", headers=_HDR)
    client.post(f"{ent['api']}/{ent['code']}/restore", headers=_HDR)
    r = client.get(f"{ent['api']}/", headers=_HDR)
    codes = [m["code"] for m in r.json()[ent["name"]]]
    assert ent["code"] in codes


# ── Hard delete gating ──────────────────────────────────────────────────────

@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_hard_delete_blocked_when_flag_off(client, ent, monkeypatch):
    _seed(client, ent)
    # flag already False from fixture; reaffirm.
    monkeypatch.setattr(settings, "master_hard_delete_enabled", False)
    r = client.delete(f"{ent['api']}/{ent['code']}?hard=true", headers=_HDR)
    assert r.status_code == 409
    assert "Hard delete is disabled" in r.text
    # Record still exists (untouched).
    g = client.get(f"{ent['api']}/{ent['code']}", headers=_HDR)
    assert g.status_code == 200
    assert g.json()["active"] is True


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_hard_delete_blocked_for_master_editor_session_when_flag_on(
        client, ent, monkeypatch):
    _seed(client, ent)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_editor"}):
        r = client.delete(f"{ent['api']}/{ent['code']}?hard=true",
                          cookies={"pz_session": "fake"})
    assert r.status_code == 403
    assert "master_admin" in r.text


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_hard_delete_allowed_for_master_admin_session_when_flag_on(
        client, ent, monkeypatch):
    _seed(client, ent)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    # Patch both the role_gate lookup (route dependency) AND the
    # auth.dependencies lookup (hard-delete guard fallback path).
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_admin"}), \
         patch("app.auth.dependencies.get_current_user_optional",
               return_value={"id": "u", "role": "master_admin"}):
        r = client.delete(f"{ent['api']}/{ent['code']}?hard=true",
                          cookies={"pz_session": "fake"})
    assert r.status_code == 204, r.text
    # Record is gone.
    g = client.get(f"{ent['api']}/{ent['code']}", headers=_HDR)
    assert g.status_code == 404


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_hard_delete_audit_op_is_hard_delete(client, ent, monkeypatch):
    _seed(client, ent)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    r = client.delete(f"{ent['api']}/{ent['code']}?hard=true", headers=_HDR)
    assert r.status_code == 204
    rows = list_audit(entity=ent["name"], pk=ent["code"])
    hd = [r for r in rows if r["op"] == "hard_delete"]
    assert len(hd) == 1
    assert hd[0]["before_json"]["code"] == ent["code"]
    assert hd[0]["after_json"] is None


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_hard_delete_admin_api_key_works_when_flag_on(client, ent, monkeypatch):
    """Direct X-API-Key bypass must satisfy the hard-delete guard."""
    _seed(client, ent)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    r = client.delete(f"{ent['api']}/{ent['code']}?hard=true", headers=_HDR)
    assert r.status_code == 204


# ── 404 sanity ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_soft_delete_404_on_missing(client, ent):
    r = client.delete(f"{ent['api']}/NEVER-EXISTED", headers=_HDR)
    assert r.status_code == 404
