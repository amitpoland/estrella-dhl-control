"""test_master_soft_delete_phase4b_wave2.py — Phase 4B Wave 2.

Composite-key customer child entities:
  - client_addresses    audit pk: customer:{contractor_id}:address:{addr_id}
  - client_carrier_accounts  audit pk: customer:{contractor_id}:carrier_account:{acct_id}

Matrix mirrors Wave 1 (13 scenarios × 2 entities = 26 parametrized base
tests + standalone helpers).
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

ENTITIES = [
    {
        "name":          "client_addresses",
        "list_key":      "addresses",
        "contractor_id": "W-ADDR-1",
        "create_body":   {"label": "HQ", "city": "Warsaw"},
        "pk_template":   "customer:{cid}:address:{sid}",
        "sub_path":      "shipping-addresses",
    },
    {
        "name":          "client_carrier_accounts",
        "list_key":      "accounts",
        "contractor_id": "W-CARR-1",
        "create_body":   {"carrier": "dhl", "account_number": "ABC-W2"},
        "pk_template":   "customer:{cid}:carrier_account:{sid}",
        "sub_path":      "carrier-accounts",
    },
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "TESTKEY")
    monkeypatch.setattr(settings, "master_audit_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", False)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", False)
    import app.api.routes_customer_master as cm
    import app.api.routes_client_addresses as ca
    import app.api.routes_client_carrier_accounts as cca
    import app.api.routes_master_data as md
    cm._DB_PATH  = tmp_path / "customer_master.sqlite"
    ca._DB_PATH  = tmp_path / "customer_master.sqlite"
    cca._DB_PATH = tmp_path / "customer_master.sqlite"
    md._DB_PATH  = tmp_path / "master_data.sqlite"
    app = FastAPI()
    app.include_router(cm.router)
    app.include_router(ca.router)
    app.include_router(cca.router)
    # Phase 4C-ext — carrier-account create requires an active
    # carriers_config row. Seed the carrier the test bodies reference.
    app.include_router(md.carriers_config_router)
    c = TestClient(app, raise_server_exceptions=True)
    c.put("/api/v1/carriers-config/dhl", json={"name": "DHL"}, headers=_HDR)
    return c


_HDR = {"X-API-Key": "TESTKEY"}


def _ensure_contractor(client, contractor_id: str) -> None:
    """Seed the parent customer so the sub-resource has a contractor to attach
    to. Only needed for the in-process test app; no FK is enforced today."""
    client.put(f"/api/v1/customer-master/{contractor_id}",
               json={"bill_to_name": "X", "country": "PL"}, headers=_HDR)


def _seed(client, ent) -> int:
    _ensure_contractor(client, ent["contractor_id"])
    url = f"/api/v1/customer-master/{ent['contractor_id']}/{ent['sub_path']}/"
    r = client.post(url, json=ent["create_body"], headers=_HDR)
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _audit_pk(ent, sub_id: int) -> str:
    return ent["pk_template"].format(cid=ent["contractor_id"], sid=sub_id)


# ── Soft delete ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_soft_delete_sets_active_false_and_deleted_at(client, ent):
    sub_id = _seed(client, ent)
    url = f"/api/v1/customer-master/{ent['contractor_id']}/{ent['sub_path']}/{sub_id}"
    r = client.delete(url, headers=_HDR)
    assert r.status_code == 204, r.text
    # Get-by-id returns 200 with active=false + deleted_at set.
    g = client.get(f"/api/v1/customer-master/{ent['contractor_id']}/"
                   f"{ent['sub_path']}/?active=false", headers=_HDR)
    assert g.status_code == 200
    records = g.json()[ent["list_key"]]
    target = [r for r in records if r["id"] == sub_id]
    assert len(target) == 1
    assert target[0]["active"] is False
    assert target[0].get("deleted_at"), f"deleted_at must be set; got {target[0]}"


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_soft_delete_audit_op_is_delete_with_stable_composite_pk(client, ent):
    sub_id = _seed(client, ent)
    url = f"/api/v1/customer-master/{ent['contractor_id']}/{ent['sub_path']}/{sub_id}"
    client.delete(url, headers=_HDR)
    pk = _audit_pk(ent, sub_id)
    rows = list_audit(entity=ent["name"], pk=pk)
    delete_rows = [r for r in rows if r["op"] == "delete"]
    assert len(delete_rows) == 1
    assert delete_rows[0]["before_json"] is not None
    assert delete_rows[0]["after_json"] is None


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_create_audit_uses_stable_composite_pk(client, ent):
    sub_id = _seed(client, ent)
    pk = _audit_pk(ent, sub_id)
    rows = list_audit(entity=ent["name"], pk=pk)
    create_rows = [r for r in rows if r["op"] == "create"]
    assert len(create_rows) == 1
    # And the pk is a colon-separated string, NOT a JSON object — pin format.
    assert create_rows[0]["pk"].startswith("customer:")
    assert create_rows[0]["pk"].count(":") == 3


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_default_list_excludes_inactive(client, ent):
    sub_id = _seed(client, ent)
    url = f"/api/v1/customer-master/{ent['contractor_id']}/{ent['sub_path']}/{sub_id}"
    client.delete(url, headers=_HDR)
    r = client.get(f"/api/v1/customer-master/{ent['contractor_id']}/"
                   f"{ent['sub_path']}/", headers=_HDR)
    assert r.status_code == 200
    records = r.json()[ent["list_key"]]
    ids = [rec["id"] for rec in records]
    assert sub_id not in ids
    assert r.json()["count"] == 0


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_active_false_list_includes_inactive(client, ent):
    sub_id = _seed(client, ent)
    url = f"/api/v1/customer-master/{ent['contractor_id']}/{ent['sub_path']}/{sub_id}"
    client.delete(url, headers=_HDR)
    r = client.get(f"/api/v1/customer-master/{ent['contractor_id']}/"
                   f"{ent['sub_path']}/?active=false", headers=_HDR)
    assert r.status_code == 200
    ids = [rec["id"] for rec in r.json()[ent["list_key"]]]
    assert sub_id in ids


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_active_true_list_excludes_inactive(client, ent):
    sub_id = _seed(client, ent)
    url = f"/api/v1/customer-master/{ent['contractor_id']}/{ent['sub_path']}/{sub_id}"
    client.delete(url, headers=_HDR)
    r = client.get(f"/api/v1/customer-master/{ent['contractor_id']}/"
                   f"{ent['sub_path']}/?active=true", headers=_HDR)
    ids = [rec["id"] for rec in r.json()[ent["list_key"]]]
    assert sub_id not in ids


# ── Restore ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_restore_sets_active_true_and_clears_deleted_at(client, ent):
    sub_id = _seed(client, ent)
    base = f"/api/v1/customer-master/{ent['contractor_id']}/{ent['sub_path']}"
    client.delete(f"{base}/{sub_id}", headers=_HDR)
    r = client.post(f"{base}/{sub_id}/restore", headers=_HDR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active"] is True
    assert body.get("deleted_at") in (None, "")


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_restore_writes_audit_row_with_op_restore_and_composite_pk(client, ent):
    sub_id = _seed(client, ent)
    base = f"/api/v1/customer-master/{ent['contractor_id']}/{ent['sub_path']}"
    client.delete(f"{base}/{sub_id}", headers=_HDR)
    client.post(f"{base}/{sub_id}/restore", headers=_HDR)
    pk = _audit_pk(ent, sub_id)
    rows = list_audit(entity=ent["name"], pk=pk)
    restore_rows = [r for r in rows if r["op"] == "restore"]
    assert len(restore_rows) == 1
    assert restore_rows[0]["before_json"]["active"] is False
    assert restore_rows[0]["after_json"]["active"] is True
    assert restore_rows[0]["pk"] == pk


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_restore_returns_404_on_missing(client, ent):
    _ensure_contractor(client, ent["contractor_id"])
    base = f"/api/v1/customer-master/{ent['contractor_id']}/{ent['sub_path']}"
    r = client.post(f"{base}/999999/restore", headers=_HDR)
    assert r.status_code == 404


# ── Hard delete gating ──────────────────────────────────────────────────────

@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_hard_delete_blocked_when_flag_off(client, ent):
    sub_id = _seed(client, ent)
    base = f"/api/v1/customer-master/{ent['contractor_id']}/{ent['sub_path']}"
    r = client.delete(f"{base}/{sub_id}?hard=true", headers=_HDR)
    assert r.status_code == 409
    assert "Hard delete is disabled" in r.text
    # Record still exists + active.
    g = client.get(f"{base}/", headers=_HDR)
    ids = [rec["id"] for rec in g.json()[ent["list_key"]]]
    assert sub_id in ids


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_hard_delete_blocked_for_master_editor_session_when_flag_on(
        client, ent, monkeypatch):
    sub_id = _seed(client, ent)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    base = f"/api/v1/customer-master/{ent['contractor_id']}/{ent['sub_path']}"
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_editor"}):
        r = client.delete(f"{base}/{sub_id}?hard=true",
                          cookies={"pz_session": "fake"})
    assert r.status_code == 403
    assert "master_admin" in r.text


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_hard_delete_allowed_for_master_admin_session_when_flag_on(
        client, ent, monkeypatch):
    sub_id = _seed(client, ent)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    base = f"/api/v1/customer-master/{ent['contractor_id']}/{ent['sub_path']}"
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_admin"}), \
         patch("app.auth.dependencies.get_current_user_optional",
               return_value={"id": "u", "role": "master_admin"}):
        r = client.delete(f"{base}/{sub_id}?hard=true",
                          cookies={"pz_session": "fake"})
    assert r.status_code == 204, r.text
    # Record gone (no longer in active OR inactive listings).
    g_all = client.get(f"{base}/?active=false", headers=_HDR)
    ids_all = [rec["id"] for rec in g_all.json()[ent["list_key"]]]
    assert sub_id not in ids_all


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_hard_delete_audit_op_is_hard_delete_with_composite_pk(
        client, ent, monkeypatch):
    sub_id = _seed(client, ent)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    base = f"/api/v1/customer-master/{ent['contractor_id']}/{ent['sub_path']}"
    r = client.delete(f"{base}/{sub_id}?hard=true", headers=_HDR)
    assert r.status_code == 204
    pk = _audit_pk(ent, sub_id)
    rows = list_audit(entity=ent["name"], pk=pk)
    hd = [r for r in rows if r["op"] == "hard_delete"]
    assert len(hd) == 1
    assert hd[0]["pk"] == pk
    assert hd[0]["after_json"] is None


@pytest.mark.parametrize("ent", ENTITIES, ids=lambda e: e["name"])
def test_soft_delete_404_on_missing(client, ent):
    _ensure_contractor(client, ent["contractor_id"])
    base = f"/api/v1/customer-master/{ent['contractor_id']}/{ent['sub_path']}"
    r = client.delete(f"{base}/999999", headers=_HDR)
    assert r.status_code == 404
