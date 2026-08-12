"""RBAC Slice 2b — Gate 3 catalogue binding for users.admin / system.settings.admin.

Authority: ``require_users_admin`` / ``require_system_settings_admin`` compose
``require_admin`` (session) + ``require_permission(...)`` (catalogue). Deny-path
first: logistics / crm / viewer / accounts must 403 before side effects.

Explicitly deferred (charter STOP until /security-review): 2c DHL/AWB, 2d
PZ/proforma/wFirma fiscal, 2e inventory/warehouse.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth.permissions import has_permission

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / "service" / "app"
_DEPS = _APP / "auth" / "dependencies.py"
_ROUTES_AUTH = _APP / "api" / "routes_auth.py"
_ROUTES_ADMIN = _APP / "api" / "routes_admin.py"
_ROUTES_BACKUP = _APP / "api" / "routes_admin_backup.py"

_DENY_ROLES = ("logistics", "crm", "viewer", "accounts", "auditor")
_USER_WRITES = ("approve", "reject", "role", "deactivate", "activate")


@pytest.fixture()
def auth_env(monkeypatch, tmp_path):
    from app.core.config import settings
    from app.auth.database import init_db

    db_path = tmp_path / "users.db"
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "auth_db_path", str(db_path))
    monkeypatch.setattr(settings, "api_key", "test-slice2b-key")
    init_db(db_path)
    return settings


def _session_client(role: str) -> TestClient:
    from app.main import app
    from app.auth.service import create_user, create_token

    email = f"{role}_{uuid.uuid4().hex[:10]}@example.test"
    user = create_user(
        full_name=f"Test {role}",
        company_name="EJ",
        email=email,
        password="Test1234!",
        role=role,
        is_approved=True,
    )
    client = TestClient(app)
    client.cookies.set("pz_session", create_token(user["id"], role))
    return client


# ── Structural pins ──────────────────────────────────────────────────────────


def test_slice2b_helpers_compose_require_admin_and_permission():
    src = _DEPS.read_text(encoding="utf-8")
    assert "def require_users_admin" in src
    assert "def require_system_settings_admin" in src
    assert 'require_permission("users.admin")' in src
    assert 'require_permission("system.settings.admin")' in src
    # No-widen: helpers still Depend on require_admin.
    assert "Depends(require_admin)" in src


def test_user_admin_routes_use_require_users_admin():
    src = _ROUTES_AUTH.read_text(encoding="utf-8")
    for action in _USER_WRITES:
        dec = rf'@router\.post\("/users/\{{user_id\}}/{action}"\)'
        m = re.search(dec, src)
        assert m, action
        after = src[m.end() : m.end() + 350]
        assert "require_users_admin" in after, (action, after[:200])
        assert "Depends(require_admin)" not in after
    # List + recovery also catalogue-bound.
    assert "admin_list_users(user: dict = Depends(require_users_admin))" in src
    assert "Depends(require_users_admin)" in src


def test_system_admin_routes_use_require_system_settings_admin():
    admin = _ROUTES_ADMIN.read_text(encoding="utf-8")
    backup = _ROUTES_BACKUP.read_text(encoding="utf-8")
    assert "require_system_settings_admin" in admin
    assert "Depends(require_admin)" not in admin
    assert "require_system_settings_admin" in backup
    assert "Depends(require_admin)" not in backup
    for needle in (
        'email-queue/{email_id}/sent',
        'email-queue/{queue_id}/send',
        'product-master/backfill',
        'authority-drift',
    ):
        assert needle in admin, needle
    assert 'prefix="/api/v1/admin/backup"' in backup
    assert "def backup_run" in backup
    assert "def backup_prune" in backup


def test_catalogue_denies_non_admin_users_admin_and_system_settings():
    for role in _DENY_ROLES:
        assert not has_permission(role, "users.admin"), role
        assert not has_permission(role, "system.settings.admin"), role
    assert has_permission("admin", "users.admin")
    assert has_permission("admin", "system.settings.admin")


# ── Deny-path (before side effects) ──────────────────────────────────────────


@pytest.mark.parametrize("role", _DENY_ROLES)
@pytest.mark.parametrize("action", _USER_WRITES)
def test_deny_roles_cannot_hit_user_admin_writes(auth_env, role, action):
    client = _session_client(role)
    with patch("app.api.routes_auth.approve_user") as m_approve, patch(
        "app.api.routes_auth.reject_user"
    ) as m_reject, patch("app.api.routes_auth.set_user_role") as m_role, patch(
        "app.api.routes_auth.set_user_active"
    ) as m_active:
        r = client.post(f"/auth/users/some-id/{action}", json={"role": "viewer"})
        assert r.status_code == 403, (role, action, r.status_code, r.text[:200])
        assert m_approve.call_count == 0
        assert m_reject.call_count == 0
        assert m_role.call_count == 0
        assert m_active.call_count == 0


@pytest.mark.parametrize("role", _DENY_ROLES)
def test_deny_roles_cannot_list_users(auth_env, role):
    client = _session_client(role)
    r = client.get("/auth/users")
    assert r.status_code == 403, (role, r.status_code, r.text[:200])


@pytest.mark.parametrize("role", _DENY_ROLES)
def test_deny_roles_cannot_hit_system_admin_writes(auth_env, role):
    client = _session_client(role)
    with patch("app.api.routes_admin.mark_sent") as m_sent, patch(
        "app.services.email_sender.send_queued_email"
    ) as m_send, patch(
        "app.services.product_master_backfill.backfill_from_invoice_lines"
    ) as m_bf, patch("app.api.routes_admin_backup.run_backup") as m_bak:
        r1 = client.post("/api/v1/admin/email-queue/qid/sent", json={})
        r2 = client.post("/api/v1/admin/email-queue/qid/send", json={})
        r3 = client.post("/api/v1/admin/product-master/backfill", json={"dry_run": True})
        r4 = client.post("/api/v1/admin/backup/run")
        for label, r in (("sent", r1), ("send", r2), ("backfill", r3), ("backup", r4)):
            assert r.status_code == 403, (role, label, r.status_code, r.text[:200])
        assert m_sent.call_count == 0
        assert m_send.call_count == 0
        assert m_bf.call_count == 0
        assert m_bak.call_count == 0


def test_api_key_alone_cannot_widen_into_user_admin(auth_env):
    """require_admin remains — valid key must not approve users without session."""
    from app.main import app

    client = TestClient(app)
    with patch("app.api.routes_auth.approve_user") as m_approve:
        r = client.post(
            "/auth/users/some-id/approve",
            headers={"X-API-Key": "test-slice2b-key"},
        )
        assert r.status_code in (401, 403), r.status_code
        assert m_approve.call_count == 0


def test_admin_session_reaches_user_list(auth_env):
    client = _session_client("admin")
    r = client.get("/auth/users")
    assert r.status_code == 200, r.text[:300]
    assert isinstance(r.json(), list)


def test_fiscal_tier0_still_unbound_in_this_slice():
    """Slice 2b must not silently bind 2d fiscal writes."""
    for path, markers in (
        (_APP / "api" / "routes_proforma.py", ("to-invoice", "approve")),
        (_APP / "api" / "routes_wfirma.py", ("pz_create",)),
    ):
        text = path.read_text(encoding="utf-8")
        assert "require_permission(" not in text or "require_users_admin" not in text
        # Fiscal files must not use Slice 2b helpers.
        assert "require_users_admin" not in text
        assert "require_system_settings_admin" not in text
