"""
test_auth_admin_audit.py — the five admin user-management actions must write to
the unified master_audit trail (Wave 7 follow-up; folded onto the #908 branch).

Verifies the audit envelope requested for the change:
  * exactly ONE master_audit row per successful action;
  * actor + reason attribution present;
  * password hashes NEVER appear in the audit payload;
  * audit failure is non-fatal to the primary user-management write.

Admin-authorization and self-target protection are pinned separately (and remain
unchanged) by test_auth_admin_user_routes.py — this file only covers the audit
behaviour that is new. Users/audit tables are created by the app startup
lifespan, so all fixtures act INSIDE the TestClient context.
"""
from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient


def _admin_client():
    from app.main import app
    from app.auth.dependencies import require_admin
    app.dependency_overrides[require_admin] = lambda: {
        "id": "audit-admin-1", "email": "audit.admin@example.test", "role": "admin",
    }
    return app, require_admin


def _mk_target(role: str = "viewer") -> dict:
    from app.auth.service import create_user
    return create_user(
        full_name="Audit Target", company_name="Test Co",
        email=f"audit_target_{uuid.uuid4().hex[:10]}@example.test",
        password="Sup3r-Secret-Pw!", role=role, is_approved=True,
    )


def test_role_change_writes_exactly_one_audit_row_with_actor_and_reason():
    from app.core.audit import list_audit
    app, dep = _admin_client()
    try:
        with TestClient(app) as c:            # startup creates the users/audit tables
            uid = _mk_target(role="viewer")["id"]
            r = c.post(f"/auth/users/{uid}/role", json={"role": "accounts"})
            assert r.status_code == 200, r.text
            rows = list_audit(entity="users", op="role", pk=uid)
        assert len(rows) == 1, f"expected exactly 1 audit row, got {len(rows)}"
        row = rows[0]
        assert row["actor"], "audit row must record the acting admin"
        assert row["reason"] and "role" in row["reason"].lower(), \
            "audit row must record a reason naming the role change"
        assert row["before_json"] and row["after_json"]
    finally:
        app.dependency_overrides.pop(dep, None)


def test_audit_payload_never_contains_password_hash():
    from app.core.audit import list_audit
    app, dep = _admin_client()
    try:
        with TestClient(app) as c:
            uid = _mk_target()["id"]
            assert c.post(f"/auth/users/{uid}/deactivate").status_code == 200
            rows = list_audit(entity="users", pk=uid)
        assert rows, "expected at least one audit row"
        blob = json.dumps(rows)
        assert "password_hash" not in blob, "audit payload must not carry password_hash"
        assert "Sup3r-Secret-Pw" not in blob, "audit payload must not carry the raw password"
    finally:
        app.dependency_overrides.pop(dep, None)


def test_each_action_writes_exactly_one_row():
    from app.core.audit import list_audit
    app, dep = _admin_client()
    try:
        with TestClient(app) as c:
            for action in ("approve", "activate", "deactivate"):
                uid = _mk_target()["id"]
                assert c.post(f"/auth/users/{uid}/{action}").status_code == 200
                rows = list_audit(entity="users", op=action, pk=uid)
                assert len(rows) == 1, f"{action}: expected 1 row, got {len(rows)}"
                assert rows[0]["actor"] and rows[0]["reason"]
    finally:
        app.dependency_overrides.pop(dep, None)


def test_audit_failure_is_non_fatal_to_the_write(monkeypatch):
    """If audit persistence raises, the primary user-management write and its
    200 response are unaffected (audit_safe swallows the failure)."""
    import app.core.audit as audit_mod
    from app.auth.service import get_user_by_id
    app, dep = _admin_client()

    def _boom(*a, **k):
        raise RuntimeError("simulated audit backend failure")
    monkeypatch.setattr(audit_mod, "write_audit", _boom)

    try:
        with TestClient(app) as c:
            uid = _mk_target(role="viewer")["id"]
            r = c.post(f"/auth/users/{uid}/role", json={"role": "logistics"})
            assert r.status_code == 200, r.text
            assert get_user_by_id(uid)["role"] == "logistics"   # primary write survived
    finally:
        app.dependency_overrides.pop(dep, None)
