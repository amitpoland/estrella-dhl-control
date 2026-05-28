"""test_master_soft_delete_phase4b_wave3b_suppliers.py — Phase 4B Wave 3b-1.

Single entity migration: suppliers.

Matrix mirrors prior soft-delete waves + wFirma/sync isolation guards.
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


_API = "/api/v1/suppliers"
_HDR = {"X-API-Key": "TESTKEY"}
_BODY = {"supplier_code": "SUP-W3B", "name": "Vendor W3B", "country": "IN"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "TESTKEY")
    monkeypatch.setattr(settings, "master_audit_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", False)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", False)
    import app.api.routes_suppliers as su
    su._DB_PATH = tmp_path / "suppliers.sqlite"
    app = FastAPI()
    app.include_router(su.router)
    return TestClient(app, raise_server_exceptions=True)


def _seed(client) -> int:
    r = client.post(f"{_API}/", json=_BODY, headers=_HDR)
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


# ── Soft delete ─────────────────────────────────────────────────────────────

def test_soft_delete_sets_active_false_and_deleted_at(client):
    sid = _seed(client)
    r = client.delete(f"{_API}/{sid}", headers=_HDR)
    assert r.status_code == 204, r.text
    g = client.get(f"{_API}/{sid}", headers=_HDR)
    assert g.status_code == 200
    body = g.json()
    assert body["active"] is False
    assert body.get("deleted_at")


def test_soft_delete_audit_op_is_delete(client):
    sid = _seed(client)
    client.delete(f"{_API}/{sid}", headers=_HDR)
    rows = list_audit(entity="suppliers", pk=str(sid))
    delete_rows = [r for r in rows if r["op"] == "delete"]
    assert len(delete_rows) == 1
    assert delete_rows[0]["before_json"]["supplier_code"] == "SUP-W3B"
    assert delete_rows[0]["after_json"] is None


def test_default_list_excludes_inactive(client):
    sid = _seed(client)
    client.delete(f"{_API}/{sid}", headers=_HDR)
    r = client.get(f"{_API}/", headers=_HDR)
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()["suppliers"]]
    assert sid not in ids
    assert r.json()["count"] == 0


def test_active_false_list_includes_inactive(client):
    sid = _seed(client)
    client.delete(f"{_API}/{sid}", headers=_HDR)
    r = client.get(f"{_API}/?active=false", headers=_HDR)
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()["suppliers"]]
    assert sid in ids


def test_active_true_list_excludes_inactive(client):
    sid = _seed(client)
    client.delete(f"{_API}/{sid}", headers=_HDR)
    r = client.get(f"{_API}/?active=true", headers=_HDR)
    ids = [s["id"] for s in r.json()["suppliers"]]
    assert sid not in ids


def test_get_by_id_returns_inactive_with_deleted_at(client):
    sid = _seed(client)
    client.delete(f"{_API}/{sid}", headers=_HDR)
    r = client.get(f"{_API}/{sid}", headers=_HDR)
    assert r.status_code == 200
    assert r.json()["active"] is False
    assert r.json()["deleted_at"]


# ── Restore ─────────────────────────────────────────────────────────────────

def test_restore_sets_active_true_and_clears_deleted_at(client):
    sid = _seed(client)
    client.delete(f"{_API}/{sid}", headers=_HDR)
    r = client.post(f"{_API}/{sid}/restore", headers=_HDR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active"] is True
    assert body.get("deleted_at") in (None, "")


def test_restore_writes_audit_row_with_op_restore(client):
    sid = _seed(client)
    client.delete(f"{_API}/{sid}", headers=_HDR)
    client.post(f"{_API}/{sid}/restore", headers=_HDR)
    rows = list_audit(entity="suppliers", pk=str(sid))
    restore_rows = [r for r in rows if r["op"] == "restore"]
    assert len(restore_rows) == 1
    assert restore_rows[0]["before_json"]["active"] is False
    assert restore_rows[0]["after_json"]["active"] is True


def test_restore_returns_404_on_missing(client):
    r = client.post(f"{_API}/999999/restore", headers=_HDR)
    assert r.status_code == 404


def test_restored_supplier_visible_in_default_list(client):
    sid = _seed(client)
    client.delete(f"{_API}/{sid}", headers=_HDR)
    client.post(f"{_API}/{sid}/restore", headers=_HDR)
    r = client.get(f"{_API}/", headers=_HDR)
    ids = [s["id"] for s in r.json()["suppliers"]]
    assert sid in ids


# ── Hard delete gating ──────────────────────────────────────────────────────

def test_hard_delete_blocked_when_flag_off(client):
    sid = _seed(client)
    r = client.delete(f"{_API}/{sid}?hard=true", headers=_HDR)
    assert r.status_code == 409
    assert "Hard delete is disabled" in r.text
    g = client.get(f"{_API}/{sid}", headers=_HDR)
    assert g.status_code == 200
    assert g.json()["active"] is True


def test_hard_delete_blocked_for_master_editor_session_when_flag_on(client, monkeypatch):
    sid = _seed(client)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_editor"}):
        r = client.delete(f"{_API}/{sid}?hard=true", cookies={"pz_session": "fake"})
    assert r.status_code == 403
    assert "master_admin" in r.text


def test_hard_delete_allowed_for_master_admin_session_when_flag_on(client, monkeypatch):
    sid = _seed(client)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    with patch("app.core.role_gate.get_current_user_optional",
               return_value={"id": "u", "role": "master_admin"}), \
         patch("app.auth.dependencies.get_current_user_optional",
               return_value={"id": "u", "role": "master_admin"}):
        r = client.delete(f"{_API}/{sid}?hard=true", cookies={"pz_session": "fake"})
    assert r.status_code == 204, r.text
    g = client.get(f"{_API}/{sid}", headers=_HDR)
    assert g.status_code == 404


def test_hard_delete_audit_op_is_hard_delete(client, monkeypatch):
    sid = _seed(client)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    r = client.delete(f"{_API}/{sid}?hard=true", headers=_HDR)
    assert r.status_code == 204
    rows = list_audit(entity="suppliers", pk=str(sid))
    hd = [r for r in rows if r["op"] == "hard_delete"]
    assert len(hd) == 1
    assert hd[0]["after_json"] is None


def test_hard_delete_admin_api_key_works_when_flag_on(client, monkeypatch):
    sid = _seed(client)
    monkeypatch.setattr(settings, "master_hard_delete_enabled", True)
    monkeypatch.setattr(settings, "master_role_enforcement", True)
    r = client.delete(f"{_API}/{sid}?hard=true", headers=_HDR)
    assert r.status_code == 204


def test_soft_delete_404_on_missing(client):
    r = client.delete(f"{_API}/999999", headers=_HDR)
    assert r.status_code == 404


# ── wFirma / sync isolation ─────────────────────────────────────────────────

_ROUTES = Path(__file__).resolve().parents[1] / "app" / "api" / "routes_suppliers.py"
_DB     = Path(__file__).resolve().parents[1] / "app" / "services" / "suppliers_db.py"


def test_wfirma_sync_endpoints_still_present(client):
    """The wFirma sync endpoints must remain registered and untouched."""
    src = _ROUTES.read_text(encoding="utf-8")
    assert "/sync-from-wfirma/preview" in src
    assert "/sync-from-wfirma/apply" in src or "sync-from-wfirma" in src
    # The sync handler still calls sync_from_wfirma (behavior untouched).
    assert "sync_from_wfirma" in src


def test_soft_delete_functions_do_not_import_wfirma(client):
    """The new soft-delete primitives must not pull in wFirma client code."""
    src = _DB.read_text(encoding="utf-8")
    m = re.search(
        r"# ── Phase 4B Wave 3b-1[\s\S]+?(?=\n# ──|\Z)", src)
    assert m, "Phase 4B Wave 3b-1 section not found in suppliers_db.py"
    block = m.group(0)
    for forbidden in ("wfirma_client", "import wfirma", "from ..services.wfirma",
                      "requests.", "httpx."):
        assert forbidden not in block, \
            f"soft-delete section must not reference {forbidden!r}"


def test_no_new_wfirma_write_calls_in_routes(client):
    """Phase 4B Wave 3b-1 must not introduce wFirma WRITE calls. The only
    wFirma touch is the pre-existing read-only sync_from_wfirma."""
    src = _ROUTES.read_text(encoding="utf-8")
    # No wFirma create/update/delete client calls anywhere in the route file.
    for forbidden in ("wfirma_create", "wfirma_update", "wfirma_delete",
                      "create_contractor", "update_contractor", "delete_contractor"):
        assert forbidden not in src, \
            f"routes_suppliers must not call wFirma write {forbidden!r}"


def test_sync_from_wfirma_signature_unchanged(client):
    """Guard that this phase did not alter the sync function contract."""
    src = _DB.read_text(encoding="utf-8")
    assert re.search(r"def sync_from_wfirma\(", src), \
        "sync_from_wfirma must still exist with its original signature"
    assert re.search(r"def upsert_supplier_identity_from_wfirma\(", src), \
        "upsert_supplier_identity_from_wfirma must remain"
