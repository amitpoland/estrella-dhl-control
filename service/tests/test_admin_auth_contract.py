"""Governance tests for tests/admin_auth.py.

The helper injects authentication into test apps. If it ever over-reaches —
blanket-disabling RBAC, or leaking an admin into the shared app singleton — the
suites that depend on it would go green while the guards they claim to exercise
were switched off. These tests pin the two properties that keep it honest:

  1. it authenticates, and the real role check still runs on top of it
  2. it never outlives its scope on a shared app
"""
from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import pytest

from app.auth.dependencies import get_current_user, require_admin, require_role
from admin_auth import ADMIN_USER, SharedAppLeakError, admin_session, grant_admin


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/admin-only", dependencies=[Depends(require_admin)])
    def _admin_only():
        return {"ok": True}

    @app.get("/logistics-only", dependencies=[Depends(require_role("logistics"))])
    def _logistics_only():
        return {"ok": True}

    @app.get("/whoami")
    def _whoami(user: dict = Depends(get_current_user)):
        return user

    return app


def test_without_the_helper_rbac_routes_are_401():
    """The baseline this helper exists to fix: no session → 401, not a pass."""
    r = TestClient(_app()).get("/admin-only")
    assert r.status_code == 401, f"expected 401 Not authenticated, got {r.status_code}"


def test_grant_admin_authenticates_admin_routes():
    r = TestClient(grant_admin(_app())).get("/admin-only")
    assert r.status_code == 200, f"admin route should pass for an admin, got {r.status_code}"


def test_role_check_still_runs_and_can_still_reject():
    """The load-bearing property: authentication is injected, authorisation is not.

    ``/logistics-only`` admits only 'logistics'. Our admin is authenticated but
    holds the wrong role, so the real ``require_role`` guard must still reject it
    with 403. A helper that overrode ``require_admin``/``require_role`` directly
    would return 200 here and quietly disable RBAC for every suite using it.
    """
    r = TestClient(grant_admin(_app())).get("/logistics-only")
    assert r.status_code == 403, (
        f"expected 403 from the real role guard, got {r.status_code}. "
        "The helper must supply identity only, never bypass the role check."
    )


def test_injected_user_is_the_declared_admin():
    body = TestClient(grant_admin(_app())).get("/whoami").json()
    assert body["role"] == "admin"
    assert body["id"] == ADMIN_USER["id"]


def test_injected_user_is_a_copy_not_the_shared_dict():
    """A route that mutates the user dict must not corrupt ADMIN_USER for later tests."""
    app = grant_admin(_app())
    TestClient(app).get("/whoami")
    fresh = app.dependency_overrides[get_current_user]()
    fresh["role"] = "viewer"
    assert ADMIN_USER["role"] == "admin", "ADMIN_USER was mutated through a handed-out reference"


def test_admin_session_restores_a_clean_app():
    app = _app()
    with admin_session(app):
        assert TestClient(app).get("/admin-only").status_code == 200
    assert get_current_user not in app.dependency_overrides, "override leaked past the with-block"
    assert TestClient(app).get("/admin-only").status_code == 401


def test_admin_session_restores_a_pre_existing_override():
    """Restoring must put back what was there, not blindly delete."""
    app = _app()
    sentinel = lambda: {"id": "outer", "role": "viewer", "is_active": True, "is_approved": True}
    app.dependency_overrides[get_current_user] = sentinel
    with admin_session(app):
        pass
    assert app.dependency_overrides[get_current_user] is sentinel


def test_grant_admin_refuses_the_shared_app_singleton():
    """The unscoped form must not be usable on an app that outlives the test.

    Restoration is deliberately not universal — grant_admin never restores, because
    the apps it serves are built and discarded inside the test. That is only safe
    while it cannot reach the shared singleton, so the separation is enforced here
    rather than left to convention.
    """
    from app.main import app as shared_app

    with pytest.raises(SharedAppLeakError, match="admin_session"):
        grant_admin(shared_app)
    assert get_current_user not in shared_app.dependency_overrides, (
        "the refused call must leave the shared app untouched"
    )


def test_admin_session_is_the_permitted_form_on_the_shared_app():
    from app.main import app as shared_app

    with admin_session(shared_app):
        assert get_current_user in shared_app.dependency_overrides
    assert get_current_user not in shared_app.dependency_overrides


def test_admin_session_restores_after_an_exception():
    app = _app()
    try:
        with admin_session(app):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert get_current_user not in app.dependency_overrides, "override survived an exception"
