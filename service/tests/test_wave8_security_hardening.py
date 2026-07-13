"""test_wave8_security_hardening.py — focused pins for the Wave 8 deferred
security-hardening slice (certification-first; classified non-blocking).

Covers five behaviourally-testable fixes:

  MEDIUM-1  /api/v1/wfirma/customers/sync-from-wfirma/apply is now admin-gated
            (require_admin), for parity with the customer-master apply route.
  MEDIUM-2  /upload document delete + replace now use the master-role write
            guard (require_role_or_apikey); a non-master session is rejected
            when master_role_enforcement is on, and it is a no-op by default.
  LOW-1     _safe_name() renames Windows reserved device names (CON, NUL, …).
  LOW-2     wFirma :path batch_id routes reject an interior "/" (complete
            traversal check), not only a leading "/".
  LOW-4     admin_set_role refuses to strip the caller's own admin role when
            they are the last active admin (last-admin lockout guard).

LOW-3 (omit the role `values` enum from /master/capabilities) was evaluated
and REJECTED — the role names are not secret (they are already returned to
anonymous callers by the /auth/signup validation error and are pinned in the
public repo), the endpoint is authenticated, and the frontend Roles tab
consumes `values` (master-page.jsx). No code change → no test here.
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


# ── LOW-1 — Windows reserved device names ──────────────────────────────────────

def test_safe_name_renames_windows_reserved_names():
    from app.api.routes_upload import _safe_name as upload_safe_name
    from app.api.routes_intake import _safe_name as intake_safe_name

    for safe_name in (upload_safe_name, intake_safe_name):
        # Reserved names (case-insensitive, with/without extension) get renamed
        # so they can never resolve to a Windows device.
        for reserved in ("CON.pdf", "nul", "COM1.txt", "LPT9.PDF", "AUX", "prn.dat"):
            out = safe_name(reserved)
            assert out.startswith("_"), f"{reserved!r} must be renamed, got {out!r}"
        # Ordinary names that merely START with a reserved stem are untouched.
        for ok in ("contract.pdf", "console.log", "auxiliary.pdf", "invoice.pdf"):
            assert safe_name(ok) == ok, f"{ok!r} must pass through unchanged"


# ── LOW-4 — last-admin lockout guard on admin_set_role ─────────────────────────

def _override_admin(app, admin_user: dict):
    from app.auth.dependencies import require_admin
    app.dependency_overrides[require_admin] = lambda: admin_user
    return require_admin


def test_set_role_blocks_last_admin_self_demotion():
    from app.main import app
    from app.auth.service import create_user, list_users, get_user_by_id

    with TestClient(app) as c:               # startup creates the users table
        # Ensure a clean single-admin world: deactivate any pre-existing admins.
        from app.auth.service import set_user_active
        for u in list_users():
            if u.get("role") == "admin" and u.get("is_active"):
                set_user_active(u["id"], False)

        me = create_user(
            full_name="Sole Admin", company_name="T",
            email=f"sole_admin_{uuid.uuid4().hex[:10]}@example.test",
            password="Sup3r-Secret-Pw!", role="admin", is_approved=True,
        )
        dep = _override_admin(app, {"id": me["id"], "email": me["email"], "role": "admin"})
        try:
            r = c.post(f"/auth/users/{me['id']}/role", json={"role": "viewer"})
            assert r.status_code == 400, r.text
            assert "last active admin" in r.text.lower()
            # The role must NOT have changed.
            assert get_user_by_id(me["id"])["role"] == "admin"
        finally:
            app.dependency_overrides.pop(dep, None)


def test_set_role_allows_self_demotion_when_another_admin_exists():
    from app.main import app
    from app.auth.service import create_user, get_user_by_id

    with TestClient(app) as c:
        me = create_user(
            full_name="Admin One", company_name="T",
            email=f"admin_one_{uuid.uuid4().hex[:10]}@example.test",
            password="Sup3r-Secret-Pw!", role="admin", is_approved=True,
        )
        # A second active admin exists → self-demotion is permitted.
        create_user(
            full_name="Admin Two", company_name="T",
            email=f"admin_two_{uuid.uuid4().hex[:10]}@example.test",
            password="Sup3r-Secret-Pw!", role="admin", is_approved=True,
        )
        dep = _override_admin(app, {"id": me["id"], "email": me["email"], "role": "admin"})
        try:
            r = c.post(f"/auth/users/{me['id']}/role", json={"role": "viewer"})
            assert r.status_code == 200, r.text
            assert get_user_by_id(me["id"])["role"] == "viewer"
        finally:
            app.dependency_overrides.pop(dep, None)


# ── MEDIUM-1 — wFirma customer sync-apply is admin-gated ───────────────────────

_SYNC_APPLY = "/api/v1/wfirma/customers/sync-from-wfirma/apply"


def test_wfirma_sync_apply_rejects_unauthenticated():
    from app.main import app
    with TestClient(app) as c:
        # No session cookie → require_admin rejects (an API key alone no longer
        # grants access to this write, unlike the old require_api_key gate).
        r = c.post(_SYNC_APPLY, headers={"X-API-Key": "not-a-session"},
                   json={"wfirma_ids": ["1"]})
        assert r.status_code in (401, 403), r.text


def test_wfirma_sync_apply_reachable_for_admin():
    from app.main import app
    from app.auth.dependencies import require_admin
    app.dependency_overrides[require_admin] = lambda: {
        "id": "wf-admin", "email": "wf.admin@example.test", "role": "admin",
    }
    try:
        with TestClient(app) as c:
            r = c.post(_SYNC_APPLY, json={"wfirma_ids": ["1"]})
            # Auth passed → handler runs. The write flag defaults off, so the
            # handler returns its 200 "blocked" envelope (no wFirma call).
            assert r.status_code == 200, r.text
            assert r.json().get("mode") == "blocked"
    finally:
        app.dependency_overrides.pop(require_admin, None)


# ── MEDIUM-2 — /upload document delete + replace use the write guard ───────────

def test_document_delete_rejects_nonmaster_session_when_enforced(monkeypatch):
    from app.main import app
    from app.core.config import settings
    from app.auth.service import create_user, create_token

    # Turn role enforcement ON so require_role_or_apikey checks the master role.
    monkeypatch.setattr(settings, "master_role_enforcement", True)

    with TestClient(app) as c:
        u = create_user(
            full_name="Plain Admin", company_name="T",
            email=f"plain_admin_{uuid.uuid4().hex[:10]}@example.test",
            password="Sup3r-Secret-Pw!", role="admin", is_approved=True,
        )
        c.cookies.set("pz_session", create_token(u["id"], "admin"))
        # 'admin' is NOT a master_* role → the write guard rejects with 403.
        # (Under the old require_api_key gate this session would have passed.)
        r = c.request(
            "DELETE",
            "/api/v1/upload/shipment/BATCH_X/documents/DOC_X",
            headers={"X-Confirm-Delete": "true"},
        )
        assert r.status_code == 403, r.text


def test_document_delete_default_config_is_no_op(monkeypatch):
    """With master_role_enforcement OFF (default) the write guard degrades to
    api-key semantics: a valid session reaches the handler (404 for the unknown
    document), proving MEDIUM-2 is a no-op under current config."""
    from app.main import app
    from app.core.config import settings
    from app.auth.service import create_user, create_token

    monkeypatch.setattr(settings, "master_role_enforcement", False)

    with TestClient(app) as c:
        u = create_user(
            full_name="Plain Admin2", company_name="T",
            email=f"plain_admin2_{uuid.uuid4().hex[:10]}@example.test",
            password="Sup3r-Secret-Pw!", role="admin", is_approved=True,
        )
        c.cookies.set("pz_session", create_token(u["id"], "admin"))
        r = c.request(
            "DELETE",
            "/api/v1/upload/shipment/BATCH_X/documents/DOC_MISSING",
            headers={"X-Confirm-Delete": "true"},
        )
        # Auth passed (no 401/403); handler ran and could not find the document.
        assert r.status_code not in (401, 403), r.text


# ── LOW-2 — interior "/" is rejected by :path batch_id guards ──────────────────

def test_wfirma_path_batch_id_rejects_interior_slash():
    from app.main import app
    from app.core.security import require_api_key

    # Neutralise the api-key gate so we exercise the in-handler traversal guard
    # regardless of whether API_KEY is configured in the test environment.
    app.dependency_overrides[require_api_key] = lambda: None
    try:
        with TestClient(app) as c:
            # batch_id captured as "a/b" (interior slash). The complete check
            # ("/" in batch_id or ".." in batch_id) now rejects it with 400;
            # the old check (only "..", leading "/") would have let it through.
            r = c.get("/api/v1/wfirma/shipment/a/b/setup-detail")
            assert r.status_code == 400, r.text
            r2 = c.post("/api/v1/wfirma/shipment/a/b/adopt-pending-found")
            assert r2.status_code == 400, r2.text
    finally:
        app.dependency_overrides.pop(require_api_key, None)
