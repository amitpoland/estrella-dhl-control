"""test_master_soft_delete_phase4b_wave3b_customers.py — Phase 4B Wave 3b-2.

Single entity migration: customer_master.

Matrix mirrors prior soft-delete waves + the Phase 4C child-write RI
activation (inactive customer rejects new address / carrier-account writes)
+ wFirma/sync isolation guards.
"""
from __future__ import annotations

import re
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


_API = "/api/v1/customer-master"
_HDR = {"X-API-Key": "TESTKEY"}
_CID = "W-3B2"
_BODY = {"bill_to_name": "Acme W3B2", "country": "PL"}


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
    app.include_router(md.carriers_config_router)  # for carrier RI seeding
    c = TestClient(app, raise_server_exceptions=True)
    # Seed an active carrier so the carrier-account RI test isolates the
    # CUSTOMER inactivity (not a missing carrier).
    c.put("/api/v1/carriers-config/dhl", json={"name": "DHL"}, headers=_HDR)
    return c


def _seed(client) -> None:
    r = client.put(f"{_API}/{_CID}", json=_BODY, headers=_HDR)
    assert r.status_code == 200, r.text


# ── Soft delete ─────────────────────────────────────────────────────────────

def test_soft_delete_sets_active_false_and_deleted_at(client):
    _seed(client)
    r = client.delete(f"{_API}/{_CID}", headers=_HDR)
    assert r.status_code == 204, r.text
    g = client.get(f"{_API}/{_CID}", headers=_HDR)
    assert g.status_code == 200
    body = g.json()
    assert body["active"] is False
    assert body.get("deleted_at")


def test_soft_delete_audit_op_is_delete(client):
    _seed(client)
    client.delete(f"{_API}/{_CID}", headers=_HDR)
    rows = list_audit(entity="customers", pk=_CID)
    delete_rows = [r for r in rows if r["op"] == "delete"]
    assert len(delete_rows) == 1
    assert delete_rows[0]["before_json"]["bill_to_contractor_id"] == _CID
    assert delete_rows[0]["after_json"] is None


def test_default_list_excludes_inactive(client):
    _seed(client)
    client.delete(f"{_API}/{_CID}", headers=_HDR)
    r = client.get(f"{_API}/", headers=_HDR)
    assert r.status_code == 200
    ids = [c["bill_to_contractor_id"] for c in r.json()["customers"]]
    assert _CID not in ids


def test_active_false_list_includes_inactive(client):
    _seed(client)
    client.delete(f"{_API}/{_CID}", headers=_HDR)
    r = client.get(f"{_API}/?active=false", headers=_HDR)
    assert r.status_code == 200
    ids = [c["bill_to_contractor_id"] for c in r.json()["customers"]]
    assert _CID in ids


def test_active_true_list_excludes_inactive(client):
    _seed(client)
    client.delete(f"{_API}/{_CID}", headers=_HDR)
    r = client.get(f"{_API}/?active=true", headers=_HDR)
    ids = [c["bill_to_contractor_id"] for c in r.json()["customers"]]
    assert _CID not in ids


def test_get_by_id_returns_inactive_with_deleted_at(client):
    _seed(client)
    client.delete(f"{_API}/{_CID}", headers=_HDR)
    r = client.get(f"{_API}/{_CID}", headers=_HDR)
    assert r.status_code == 200
    assert r.json()["active"] is False
    assert r.json()["deleted_at"]


# ── PUT must not reactivate a soft-deleted customer ─────────────────────────

def test_put_does_not_reactivate_soft_deleted_customer(client):
    """Editing an inactive customer via PUT must NOT silently reactivate it
    (upsert does not touch active/deleted_at)."""
    _seed(client)
    client.delete(f"{_API}/{_CID}", headers=_HDR)
    r = client.put(f"{_API}/{_CID}",
                   json={"bill_to_name": "Acme renamed", "country": "PL"},
                   headers=_HDR)
    assert r.status_code == 200
    g = client.get(f"{_API}/{_CID}", headers=_HDR)
    assert g.json()["active"] is False, "PUT must not reactivate"
    assert g.json()["bill_to_name"] == "Acme renamed"


# ── Restore ─────────────────────────────────────────────────────────────────

def test_restore_sets_active_true_and_clears_deleted_at(client):
    _seed(client)
    client.delete(f"{_API}/{_CID}", headers=_HDR)
    r = client.post(f"{_API}/{_CID}/restore", headers=_HDR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active"] is True
    assert body.get("deleted_at") in (None, "")


def test_restore_writes_audit_row_with_op_restore(client):
    _seed(client)
    client.delete(f"{_API}/{_CID}", headers=_HDR)
    client.post(f"{_API}/{_CID}/restore", headers=_HDR)
    rows = list_audit(entity="customers", pk=_CID)
    restore_rows = [r for r in rows if r["op"] == "restore"]
    assert len(restore_rows) == 1
    assert restore_rows[0]["before_json"]["active"] is False
    assert restore_rows[0]["after_json"]["active"] is True


def test_restore_returns_404_on_missing(client):
    r = client.post(f"{_API}/NEVER/restore", headers=_HDR)
    assert r.status_code == 404


# ── Hard delete gating ──────────────────────────────────────────────────────

def test_hard_delete_blocked_when_flag_off(client):
    _seed(client)
    r = client.delete(f"{_API}/{_CID}?hard=true", headers=_HDR)
    assert r.status_code == 409
    assert "Hard delete is disabled" in r.text
    assert client.get(f"{_API}/{_CID}", headers=_HDR).json()["active"] is True


def test_hard_delete_blocked_for_master_editor_when_flag_on(client, monkeypatch):
    _seed(client)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_editor"}):
        r = client.delete(f"{_API}/{_CID}?hard=true", cookies={"pz_session": "fake"})
    assert r.status_code == 403
    assert "master_admin" in r.text


def test_hard_delete_allowed_for_master_admin_when_flag_on(client, monkeypatch):
    _seed(client)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_admin"}), \
         patch("app.auth.dependencies.get_current_user_optional",
               return_value={"id": "u", "role": "master_admin"}):
        r = client.delete(f"{_API}/{_CID}?hard=true", cookies={"pz_session": "fake"})
    assert r.status_code == 204, r.text
    assert client.get(f"{_API}/{_CID}", headers=_HDR).status_code == 404


def test_hard_delete_audit_op_is_hard_delete(client, monkeypatch):
    _seed(client)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    r = client.delete(f"{_API}/{_CID}?hard=true", headers=_HDR)
    assert r.status_code == 204
    hd = [r for r in list_audit(entity="customers", pk=_CID) if r["op"] == "hard_delete"]
    assert len(hd) == 1
    assert hd[0]["after_json"] is None


def test_soft_delete_404_on_missing(client):
    r = client.delete(f"{_API}/NEVER", headers=_HDR)
    assert r.status_code == 404


# ── Phase 4C child-write RI activation (the key Wave 3b-2 behavior) ──────────

def test_address_create_rejects_inactive_customer(client):
    """Once the customer is inactive, the Phase 4C check_customer_exists
    future-hook (getattr active) must reject new address writes with 409
    reference_conflict reason=inactive."""
    _seed(client)
    client.delete(f"{_API}/{_CID}", headers=_HDR)
    r = client.post(f"{_API}/{_CID}/shipping-addresses/",
                    json={"label": "HQ", "city": "Warsaw"}, headers=_HDR)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "reference_conflict"
    assert detail["field"] == "contractor_id"
    assert detail["entity"] == "customers"
    assert detail["key"] == _CID
    assert detail["reason"] == "inactive"


def test_carrier_account_create_rejects_inactive_customer(client):
    _seed(client)
    client.delete(f"{_API}/{_CID}", headers=_HDR)
    r = client.post(f"{_API}/{_CID}/carrier-accounts/",
                    json={"carrier": "dhl", "account_number": "X1"}, headers=_HDR)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "reference_conflict"
    assert detail["entity"] == "customers"
    assert detail["reason"] == "inactive"


def test_child_writes_succeed_again_after_customer_restore(client):
    """After restoring the customer, child writes succeed (RI hook clears)."""
    _seed(client)
    client.delete(f"{_API}/{_CID}", headers=_HDR)
    client.post(f"{_API}/{_CID}/restore", headers=_HDR)
    r = client.post(f"{_API}/{_CID}/shipping-addresses/",
                    json={"label": "HQ", "city": "Warsaw"}, headers=_HDR)
    assert r.status_code == 201, r.text


def test_active_customer_child_writes_unaffected(client):
    """Sanity: an active customer accepts child writes (no false-positive RI)."""
    _seed(client)
    r = client.post(f"{_API}/{_CID}/shipping-addresses/",
                    json={"label": "HQ", "city": "Warsaw"}, headers=_HDR)
    assert r.status_code == 201, r.text


# ── wFirma / sync isolation ─────────────────────────────────────────────────

_ROUTES = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_customer_master.py"
_DB     = Path(__file__).resolve().parents[1] / "app" / "services" / "customer_master_db.py"


def test_wfirma_sync_endpoints_still_present(client):
    src = _ROUTES.read_text(encoding="utf-8")
    assert "/sync-from-wfirma/preview" in src
    assert "/sync-from-wfirma/apply" in src
    assert "/dictionaries" in src
    assert "/dictionaries/refresh" in src


def test_soft_delete_functions_do_not_import_wfirma(client):
    src = _DB.read_text(encoding="utf-8")
    m = re.search(r"# ── Phase 4B Wave 3b-2[\s\S]+?(?=\n__all__|\Z)", src)
    assert m, "Phase 4B Wave 3b-2 section not found in customer_master_db.py"
    block = m.group(0)
    for forbidden in ("wfirma_client", "import wfirma", "requests.", "httpx."):
        assert forbidden not in block, \
            f"soft-delete section must not reference {forbidden!r}"


def test_no_new_wfirma_write_calls_in_routes(client):
    src = _ROUTES.read_text(encoding="utf-8")
    for forbidden in ("wfirma_create", "wfirma_update", "wfirma_delete",
                      "create_contractor", "update_contractor", "delete_contractor"):
        assert forbidden not in src, \
            f"routes_customer_master must not call wFirma write {forbidden!r}"
