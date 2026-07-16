"""
test_proforma_privileged_auth.py — backend-safety finding A (2026-07-16).

H-R5 (#502) class closure for routes_proforma.py: every state-mutation route
(POST / PUT / PATCH / DELETE) must use the privileged guard
``require_api_key_privileged`` (via ``_auth_write``) so read-only session
roles (viewer / auditor / master_viewer) are rejected with 403. Read-only GET
routes stay on bare ``require_api_key`` (``_auth``) so viewers keep reading.
X-API-Key automation is admin-equivalent and unchanged.

Tests:
  - Structural pin: no non-GET route in routes_proforma.py depends on bare
    ``_auth``; no GET route depends on ``_auth_write``.
  - Integration: viewer denied (403) on representative mutation routes
    BEFORE any handler logic runs; viewer still reads GETs; admin session and
    X-API-Key are not auth-denied; unauthenticated denied.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.core.config import settings  # noqa: E402

_GCU = "app.auth.dependencies.get_current_user_optional"
_SRC = _SVC / "app" / "api" / "routes_proforma.py"


# ── Structural pin: method → guard mapping over the whole file ───────────────

def _decorator_blocks():
    """Yield (method, block_text, lineno) for every @router.<method>(...) decorator."""
    lines = _SRC.read_text(encoding="utf-8").splitlines()
    method, start, buf = None, 0, []
    for i, ln in enumerate(lines, start=1):
        m = re.match(r"\s*@router\.(get|post|put|patch|delete)\(", ln)
        if m:
            if method is not None:
                yield method, "\n".join(buf), start
            method, start, buf = m.group(1), i, [ln]
        elif re.match(r"\s*(async\s+)?def\s", ln):
            if method is not None:
                yield method, "\n".join(buf), start
            method, buf = None, []
        elif method is not None:
            buf.append(ln)
    if method is not None:
        yield method, "\n".join(buf), start


def test_no_mutation_route_on_bare_auth():
    """Every POST/PUT/PATCH/DELETE decorator must use _auth_write, never bare _auth."""
    offenders = [
        f"line {ln}: @router.{meth}"
        for meth, block, ln in _decorator_blocks()
        if meth != "get" and "dependencies=[_auth]" in block
    ]
    assert not offenders, (
        "mutation routes still on bare require_api_key (use _auth_write): "
        + "; ".join(offenders)
    )


def test_mutation_routes_carry_privileged_guard():
    """Non-GET routes that declare dependencies must use _auth_write."""
    gated = [
        (meth, ln)
        for meth, block, ln in _decorator_blocks()
        if meth != "get" and "dependencies=[_auth_write]" in block
    ]
    # Regression floor: the 2026-07-17 migration moved 41 mutation routes.
    assert len(gated) >= 41, f"expected >=41 privileged mutation routes, got {len(gated)}"


def test_get_routes_stay_readable():
    """GET routes must NOT be write-gated — viewers keep read access."""
    offenders = [
        f"line {ln}"
        for meth, block, ln in _decorator_blocks()
        if meth == "get" and "_auth_write" in block
    ]
    assert not offenders, (
        "GET routes must stay on bare require_api_key: " + "; ".join(offenders)
    )


# ── Integration: real routes via TestClient ──────────────────────────────────

@pytest.fixture()
def prod_client(tmp_path):
    """App booted in prod-like mode (with secrets so the #488 guard passes)."""
    with (
        patch.object(settings, "api_key", "real-key"),
        patch.object(settings, "auth_secret_key", "test-secret-not-placeholder"),
        patch.object(settings, "environment", "prod"),
        patch.object(settings, "storage_root", tmp_path),
    ):
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


_VIEWER = {"role": "viewer", "is_active": 1, "is_approved": 1}
_ADMIN = {"role": "admin", "is_active": 1, "is_approved": 1}

# Representative mutation routes: the guard runs before the handler, so a 403
# must come back even for a nonexistent draft id.
_MUTATIONS = [
    ("patch", "/api/v1/proforma/draft/999999", {"json": {}}),
    ("post", "/api/v1/proforma/draft/999999/cancel", {"json": {}}),
    ("post", "/api/v1/proforma/draft/999999/approve", {"json": {}}),
    ("delete", "/api/v1/proforma/draft/999999", {}),
    ("post", "/api/v1/proforma/draft/999999/send-email", {"json": {}}),
]


@pytest.mark.parametrize("method,url,kw", _MUTATIONS)
def test_mutation_denies_read_only_session(prod_client, method, url, kw):
    with patch(_GCU, return_value=dict(_VIEWER)):
        r = getattr(prod_client, method)(url, cookies={"pz_session": "x"}, **kw)
    assert r.status_code == 403, f"{method.upper()} {url} must 403 for viewer, got {r.status_code}"


@pytest.mark.parametrize("role", ["viewer", "auditor", "master_viewer"])
def test_all_read_only_roles_denied_on_mutation(prod_client, role):
    with patch(_GCU, return_value={"role": role, "is_active": 1, "is_approved": 1}):
        r = prod_client.patch("/api/v1/proforma/draft/999999",
                              json={}, cookies={"pz_session": "x"})
    assert r.status_code == 403


def test_get_still_open_to_viewer(prod_client):
    """A read route must NOT be role-denied for a viewer (may 200/404, never 401/403)."""
    with patch(_GCU, return_value=dict(_VIEWER)):
        r = prod_client.get("/api/v1/proforma/drafts/NO_SUCH_BATCH",
                            cookies={"pz_session": "x"})
    assert r.status_code not in (401, 403), f"viewer GET must stay readable, got {r.status_code}"


def test_mutation_allows_admin_session(prod_client):
    """Admin is NOT auth-denied (may 404/422 on body/state, but never 401/403)."""
    with patch(_GCU, return_value=dict(_ADMIN)):
        r = prod_client.patch("/api/v1/proforma/draft/999999",
                              json={}, cookies={"pz_session": "x"})
    assert r.status_code not in (401, 403), f"admin must not be auth-denied, got {r.status_code}"


def test_mutation_allows_api_key_automation(prod_client):
    """X-API-Key automation path preserved (admin-equivalent, no role check)."""
    r = prod_client.patch("/api/v1/proforma/draft/999999",
                          json={}, headers={"X-API-Key": "real-key"})
    assert r.status_code not in (401, 403), f"X-API-Key must not be auth-denied, got {r.status_code}"


def test_mutation_denies_unauthenticated(prod_client):
    r = prod_client.patch("/api/v1/proforma/draft/999999", json={})
    assert r.status_code in (401, 403)
