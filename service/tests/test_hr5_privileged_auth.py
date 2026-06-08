"""
test_hr5_privileged_auth.py — Issue #502 Phase 1 (H-R5).

Closes viewer privilege escalation: bare ``require_api_key`` accepted ANY
approved session (incl. read-only roles) on admin / runtime-flags / execute /
debug-mutation routes. The fix adds ``require_api_key_privileged`` (X-API-Key OR
write-capable session) and applies it to the 5 privileged POST routes.

Tests:
  - Unit: require_api_key_privileged role/auth matrix (the single chokepoint).
  - Structural: the 5 privileged routes use the privileged guard; safe GET
    reads remain on require_api_key.
  - Integration: viewer denied (403), admin allowed, unauth denied (401),
    read diagnostics still open to viewer.
  - Fail-closed (PR #488) preserved.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.core.config import settings  # noqa: E402
from app.core.security import (  # noqa: E402
    require_api_key_privileged,
    _READ_ONLY_ROLES,
    _WRITE_CAPABLE_ROLES,
)

_GCU = "app.auth.dependencies.get_current_user_optional"


def _call(key=None, session=None):
    return require_api_key_privileged(key=key, pz_session=session)


# ── Unit: the chokepoint ─────────────────────────────────────────────────────

class TestPrivilegedGuard:
    def setup_method(self):
        self._p = [patch.object(settings, "api_key", "real-key"),
                   patch.object(settings, "environment", "prod")]
        for p in self._p:
            p.start()

    def teardown_method(self):
        for p in self._p:
            p.stop()

    def test_valid_api_key_allowed(self):
        assert _call(key="real-key") is None  # trusted automation path preserved

    def test_no_auth_denied_401(self):
        with pytest.raises(HTTPException) as e:
            _call()
        assert e.value.status_code == 401

    def test_invalid_session_denied_401(self):
        with patch(_GCU, return_value=None):
            with pytest.raises(HTTPException) as e:
                _call(session="bad")
            assert e.value.status_code == 401

    @pytest.mark.parametrize("role", ["viewer", "auditor", "master_viewer"])
    def test_read_only_role_denied_403(self, role):
        with patch(_GCU, return_value={"role": role}):
            with pytest.raises(HTTPException) as e:
                _call(session="sess")
            assert e.value.status_code == 403

    @pytest.mark.parametrize("role", ["admin", "accounts", "logistics",
                                      "master_admin", "master_editor"])
    def test_write_capable_role_allowed(self, role):
        with patch(_GCU, return_value={"role": role}):
            assert _call(session="sess") is None

    def test_role_sets_match_audit(self):
        assert _READ_ONLY_ROLES == frozenset({"viewer", "auditor", "master_viewer"})
        assert _WRITE_CAPABLE_ROLES == frozenset(
            {"admin", "accounts", "logistics", "master_admin", "master_editor"}
        )
        # No role is both read-only and write-capable.
        assert _READ_ONLY_ROLES.isdisjoint(_WRITE_CAPABLE_ROLES)

    @pytest.mark.parametrize("bad", [None, "", {"id": 1}])
    def test_missing_or_empty_role_denied_403_failclosed(self, bad):
        """Fail-closed: a session with no determinable write-capable role is denied."""
        user = bad if isinstance(bad, dict) else {"role": bad}
        with patch(_GCU, return_value=user):
            with pytest.raises(HTTPException) as e:
                _call(session="sess")
            assert e.value.status_code == 403

    def test_unknown_role_denied_403_failclosed(self):
        """Allowlist: a role not in the write-capable set is denied (fail-closed)."""
        with patch(_GCU, return_value={"role": "some_future_role"}):
            with pytest.raises(HTTPException) as e:
                _call(session="sess")
            assert e.value.status_code == 403


class TestFailClosedPreserved:
    def test_prod_no_api_key_503(self):
        with patch.object(settings, "api_key", ""), patch.object(settings, "environment", "prod"):
            with pytest.raises(HTTPException) as e:
                _call()
            assert e.value.status_code == 503

    def test_dev_no_api_key_allowed(self):
        with patch.object(settings, "api_key", ""), patch.object(settings, "environment", "dev"):
            assert _call() is None


# ── Structural: the 5 privileged routes use the privileged guard ─────────────

_PRIVILEGED = [
    ("api/routes_execute.py", "/{action}"),
    ("api/routes_admin_runtime_flags.py", "/self-clearance"),
    ("api/routes_admin_dhl_clearance.py", "/proactive-dispatch/{batch_id}"),
    ("api/routes_debug.py", "/clear-test-sessions"),
    ("api/routes_debug.py", "/post-pz-test"),
]


@pytest.mark.parametrize("relpath,route", _PRIVILEGED)
def test_privileged_routes_use_privileged_guard(relpath, route):
    src = (_SVC / "app" / relpath).read_text(encoding="utf-8")
    # Inspect the @router.post(...) decorator block for this exact route path.
    blocks = re.findall(r"@router\.post\((.*?)\)", src, re.DOTALL)
    matching = [b for b in blocks if f'"{route}"' in b]
    assert matching, f"no @router.post decorator for {route} in {relpath}"
    assert all("_privileged" in b for b in matching), (
        f"@router.post for {route} in {relpath} must use _privileged, not _auth"
    )


def test_safe_get_reads_remain_on_auth():
    """Read-only diagnostics must stay readable (require_api_key, viewer OK)."""
    dbg = (_SVC / "app" / "api" / "routes_debug.py").read_text(encoding="utf-8")
    for getroute in ("/health-full", "/storage/health", "/storage/locks", "/pending"):
        idx = dbg.find(f'"{getroute}"')
        assert idx != -1
        window = dbg[max(0, idx - 80): idx + 80]
        assert "_privileged" not in window, f"GET {getroute} must NOT be privileged-gated (read)"


# ── Integration: real routes via TestClient ──────────────────────────────────

@pytest.fixture()
def prod_client(tmp_path):
    """App booted in prod-like mode (with secrets so #488 guard passes)."""
    with (
        patch.object(settings, "api_key", "real-key"),
        patch.object(settings, "auth_secret_key", "test-secret-not-placeholder"),
        patch.object(settings, "environment", "prod"),
        patch.object(settings, "storage_root", tmp_path),
    ):
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def test_execute_denies_viewer(prod_client):
    with patch(_GCU, return_value={"role": "viewer", "is_active": 1, "is_approved": 1}):
        r = prod_client.post("/api/v1/execute/noop", json={"batch_id": "B1"},
                             cookies={"pz_session": "x"})
    assert r.status_code == 403


def test_runtime_flag_post_denies_viewer(prod_client):
    with patch(_GCU, return_value={"role": "viewer", "is_active": 1, "is_approved": 1}):
        r = prod_client.post("/api/v1/admin/runtime-flags/self-clearance",
                             json={"flag": "x", "value": True}, cookies={"pz_session": "x"})
    assert r.status_code == 403


def test_debug_clear_sessions_denies_viewer(prod_client):
    with patch(_GCU, return_value={"role": "viewer", "is_active": 1, "is_approved": 1}):
        r = prod_client.post("/api/v1/debug/clear-test-sessions", cookies={"pz_session": "x"})
    assert r.status_code == 403


def test_privileged_route_allows_admin(prod_client):
    """Admin session is NOT blocked by the auth guard (may 400/422 on body, but not 401/403-auth)."""
    with patch(_GCU, return_value={"role": "admin", "is_active": 1, "is_approved": 1}):
        r = prod_client.post("/api/v1/execute/noop", json={"batch_id": "B1"},
                             cookies={"pz_session": "x"})
    assert r.status_code != 403, "admin must not be auth-denied"
    assert r.status_code != 401


def test_privileged_route_allows_api_key(prod_client):
    """X-API-Key automation path preserved (not auth-denied)."""
    r = prod_client.post("/api/v1/execute/noop", json={"batch_id": "B1"},
                         headers={"X-API-Key": "real-key"})
    assert r.status_code not in (401, 403)


def test_unauthenticated_denied(prod_client):
    r = prod_client.post("/api/v1/execute/noop", json={"batch_id": "B1"})
    assert r.status_code in (401, 403)


def test_read_diagnostic_open_to_viewer(prod_client):
    """A safe GET diagnostic stays accessible to a viewer (read contract)."""
    with patch(_GCU, return_value={"role": "viewer", "is_active": 1, "is_approved": 1}):
        r = prod_client.get("/api/v1/debug/storage/health", cookies={"pz_session": "x"})
    assert r.status_code != 403, "viewer must still read safe diagnostics"
