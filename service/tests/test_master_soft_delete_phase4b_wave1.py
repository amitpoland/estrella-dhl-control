"""test_master_soft_delete_phase4b_wave1.py — Phase 4B Wave 1.

Six legacy entities in master_data_db.py migrated to soft-delete:
  hs_codes, units, incoterms, vat_config, fx_rates, designs

Matrix mirrors Phase 4A:
  - soft-delete sets active=false + deleted_at; audit op=delete
  - default list excludes inactive
  - active=false list includes inactive
  - get-by-id/code returns inactive with active=false + deleted_at
  - restore resets active=true and deleted_at=null; audit op=restore
  - hard delete blocked when flag false (409)
  - hard delete blocked for master_editor when flag true (403)
  - hard delete allowed for master_admin when flag true (204 + audit hard_delete)
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


# ── Entity registry ─────────────────────────────────────────────────────────
#
# Each entity carries enough metadata to drive the full matrix without
# special casing. `key_path` returns "/{code}" for natural-keyed
# entities; for surrogate-id ones it's a function applied to the create
# response.

ENTITIES = [
    {
        "name":          "hs_codes",
        "api":           "/api/v1/hs-codes",
        "create_method": "PUT",   # natural-key upsert
        "create_path":   lambda body: f"/71132100",
        "create_body":   {"description_pl": "x"},
        "pk_from_resp":  lambda body: "71132100",
        "list_key":      "hs_codes",
    },
    {
        "name":          "units",
        "api":           "/api/v1/units",
        "create_method": "PUT",
        "create_path":   lambda body: f"/szt",
        "create_body":   {"name_pl": "sztuka"},
        "pk_from_resp":  lambda body: "szt",
        "list_key":      "units",
    },
    {
        "name":          "incoterms",
        "api":           "/api/v1/incoterms",
        "create_method": "PUT",
        "create_path":   lambda body: f"/EXW",
        "create_body":   {"name": "Ex Works"},
        "pk_from_resp":  lambda body: "EXW",
        "list_key":      "incoterms",
    },
    {
        "name":          "vat_config",
        "api":           "/api/v1/vat-config",
        "create_method": "POST",   # surrogate id
        "create_path":   lambda body: "/",
        "create_body":   {"country": "PL", "rate_pct": "23"},
        "pk_from_resp":  lambda body: str(body["id"]),
        "list_key":      "vat_config",
    },
    {
        "name":          "fx_rates",
        "api":           "/api/v1/fx-rates",
        "create_method": "POST",
        "create_path":   lambda body: "/",
        "create_body":   {"rate_date": "2026-05-28", "from_currency": "USD",
                           "to_currency": "PLN", "rate": "3.6506"},
        "pk_from_resp":  lambda body: str(body["id"]),
        "list_key":      "fx_rates",
    },
    {
        "name":          "designs",
        "api":           "/api/v1/designs",
        "create_method": "PUT",
        "create_path":   lambda body: f"/D-R-1",
        "create_body":   {"display_name": "Round 1ct"},
        "pk_from_resp":  lambda body: "D-R-1",
        "list_key":      "designs",
    },
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "TESTKEY")
    monkeypatch.setattr(settings, "master_audit_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", False)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", False)
    import app.api.routes_master_data as md
    md._DB_PATH = tmp_path / "master_data.sqlite"
    app = FastAPI()
    for r in (md.hs_router, md.units_router, md.incoterms_router,
              md.vat_router, md.fx_router, md.designs_router):
        app.include_router(r)
    return TestClient(app, raise_server_exceptions=True)


_HDR = {"X-API-Key": "TESTKEY"}


def _seed(client, ent) -> str:
    """Create one row; return the stringified pk for use in URL paths."""
    url = ent["api"] + ent["create_path"](ent["create_body"])
    if ent["create_method"] == "PUT":
        r = client.put(url, json=ent["create_body"], headers=_HDR)
        assert r.status_code == 200, r.text
    else:
        r = client.post(url, json=ent["create_body"], headers=_HDR)
        assert r.status_code == 201, r.text
    return ent["pk_from_resp"](r.json())


# ── Soft delete ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_soft_delete_sets_active_false_and_deleted_at(client, ent):
    pk = _seed(client, ent)
    r = client.delete(f"{ent['api']}/{pk}", headers=_HDR)
    assert r.status_code == 204, r.text
    g = client.get(f"{ent['api']}/{pk}", headers=_HDR)
    assert g.status_code == 200
    body = g.json()
    assert body["active"] is False
    assert body.get("deleted_at"), f"deleted_at must be set; got {body}"


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_soft_delete_audit_op_is_delete(client, ent):
    pk = _seed(client, ent)
    client.delete(f"{ent['api']}/{pk}", headers=_HDR)
    rows = list_audit(entity=ent["name"], pk=pk)
    delete_rows = [r for r in rows if r["op"] == "delete"]
    assert len(delete_rows) == 1
    assert delete_rows[0]["before_json"] is not None
    assert delete_rows[0]["after_json"] is None


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_default_list_excludes_inactive(client, ent):
    pk = _seed(client, ent)
    client.delete(f"{ent['api']}/{pk}", headers=_HDR)
    r = client.get(f"{ent['api']}/", headers=_HDR)
    assert r.status_code == 200
    list_key = ent["list_key"]
    records = r.json()[list_key]
    # The deleted record must be absent. Use a robust pk comparison —
    # natural keys are strings; surrogate ids may be ints in the payload.
    def _pk_of(rec):
        for k in ("id", "design_code", "hs_code", "code"):
            v = rec.get(k)
            if v is not None and v != "":
                return str(v)
        return None
    pks = [_pk_of(rec) for rec in records]
    assert pk not in pks
    assert r.json()["count"] == 0


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_active_false_list_includes_inactive(client, ent):
    pk = _seed(client, ent)
    client.delete(f"{ent['api']}/{pk}", headers=_HDR)
    r = client.get(f"{ent['api']}/?active=false", headers=_HDR)
    assert r.status_code == 200
    records = r.json()[ent["list_key"]]
    def _pk_of(rec):
        for k in ("id", "design_code", "hs_code", "code"):
            v = rec.get(k)
            if v is not None and v != "":
                return str(v)
        return None
    pks = [_pk_of(rec) for rec in records]
    assert pk in pks


# ── Restore ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_restore_sets_active_true_and_clears_deleted_at(client, ent):
    pk = _seed(client, ent)
    client.delete(f"{ent['api']}/{pk}", headers=_HDR)
    r = client.post(f"{ent['api']}/{pk}/restore", headers=_HDR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active"] is True
    assert body.get("deleted_at") in (None, "")


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_restore_writes_audit_row_with_op_restore(client, ent):
    pk = _seed(client, ent)
    client.delete(f"{ent['api']}/{pk}", headers=_HDR)
    client.post(f"{ent['api']}/{pk}/restore", headers=_HDR)
    rows = list_audit(entity=ent["name"], pk=pk)
    restore_rows = [r for r in rows if r["op"] == "restore"]
    assert len(restore_rows) == 1
    assert restore_rows[0]["before_json"]["active"] is False
    assert restore_rows[0]["after_json"]["active"] is True


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_restore_returns_404_on_missing(client, ent):
    # Use a clearly-nonexistent pk per entity shape.
    if ent["create_method"] == "POST":
        bogus = "999999"
    elif ent["name"] == "hs_codes":
        bogus = "99999998"
    else:
        bogus = "NOPE-NEVER"
    r = client.post(f"{ent['api']}/{bogus}/restore", headers=_HDR)
    assert r.status_code == 404


# ── Hard-delete gating ──────────────────────────────────────────────────────

@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_hard_delete_blocked_when_flag_off(client, ent):
    pk = _seed(client, ent)
    r = client.delete(f"{ent['api']}/{pk}?hard=true", headers=_HDR)
    assert r.status_code == 409
    assert "Hard delete is disabled" in r.text
    g = client.get(f"{ent['api']}/{pk}", headers=_HDR)
    assert g.status_code == 200
    assert g.json()["active"] is True


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_hard_delete_blocked_for_master_editor_session_when_flag_on(
        client, ent, monkeypatch):
    pk = _seed(client, ent)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_editor"}):
        r = client.delete(f"{ent['api']}/{pk}?hard=true",
                          cookies={"pz_session": "fake"})
    assert r.status_code == 403
    assert "master_admin" in r.text


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_hard_delete_allowed_for_master_admin_session_when_flag_on(
        client, ent, monkeypatch):
    pk = _seed(client, ent)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_admin"}), \
         patch("app.auth.dependencies.get_current_user_optional",
               return_value={"id": "u", "role": "master_admin"}):
        r = client.delete(f"{ent['api']}/{pk}?hard=true",
                          cookies={"pz_session": "fake"})
    assert r.status_code == 204, r.text
    g = client.get(f"{ent['api']}/{pk}", headers=_HDR)
    assert g.status_code == 404


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_hard_delete_audit_op_is_hard_delete(client, ent, monkeypatch):
    pk = _seed(client, ent)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    r = client.delete(f"{ent['api']}/{pk}?hard=true", headers=_HDR)
    assert r.status_code == 204
    rows = list_audit(entity=ent["name"], pk=pk)
    hd = [r for r in rows if r["op"] == "hard_delete"]
    assert len(hd) == 1
    assert hd[0]["after_json"] is None


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_hard_delete_admin_api_key_works_when_flag_on(client, ent, monkeypatch):
    pk = _seed(client, ent)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    r = client.delete(f"{ent['api']}/{pk}?hard=true", headers=_HDR)
    assert r.status_code == 204


# ── 404 sanity ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_soft_delete_404_on_missing(client, ent):
    if ent["create_method"] == "POST":
        bogus = "999999"
    elif ent["name"] == "hs_codes":
        bogus = "99999998"
    else:
        bogus = "NOPE-NEVER"
    r = client.delete(f"{ent['api']}/{bogus}", headers=_HDR)
    assert r.status_code == 404
