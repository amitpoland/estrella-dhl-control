"""Auth coverage for /api/v1/tracking/events* endpoints.

Closes a previously-open surface: the 4 events endpoints had no auth
dependency at all. After this PR they share require_api_key (router-
level dependency).

Pre-existing routing-order caveat (NOT a regression introduced here):
    main.py includes tracking_router BEFORE tracking_db_router.
    tracking_router holds `/{tracking_no}` which is a one-segment
    wildcard at prefix /api/v1/tracking. The bare path
    /api/v1/tracking/events (one segment) therefore matches the
    wildcard, not tracking_db_router. The other 3 events paths are
    multi-segment and resolve to tracking_db_router as intended.

    This is documented as a separate fix (out of scope here per
    "Do not touch main.py" rule). Tests below cover the 3 endpoints
    that actually reach tracking_db_router, plus a router-level
    dependency assertion that proves the auth was wired correctly on
    all 4 declarations.

Cookie path is exercised by monkeypatching the get_current_user_optional
module attribute (require_api_key uses a lazy import + direct call, so
FastAPI dependency_overrides do not apply).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.main import app
from app.core import security as security_module
from app.auth import dependencies as auth_deps


# Endpoints that actually reach routes_tracking_db (multi-segment paths).
# `/api/v1/tracking/events` (single-segment) is swallowed by an earlier
# wildcard; covered by `test_events_endpoints_have_auth_dependency` at the
# router-introspection level.
ENDPOINTS = [
    ("GET",  "/api/v1/tracking/events/some-batch"),
    ("POST", "/api/v1/tracking/events/export"),
    ("GET",  "/api/v1/tracking/events/export/download"),
]


@pytest.fixture(autouse=True)
def _reset_api_key(monkeypatch):
    monkeypatch.setattr(security_module.settings, "api_key", "")
    yield


def _client() -> TestClient:
    return TestClient(app)


def _patch_cookie(monkeypatch, user_or_none):
    def _stub(pz_session=None):
        if not pz_session:
            return None
        return user_or_none
    monkeypatch.setattr(auth_deps, "get_current_user_optional", _stub)


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_empty_api_key_passthrough_not_401(method, path, monkeypatch):
    """Current prod posture preserved: dev pass-through means NOT 401."""
    monkeypatch.setattr(security_module.settings, "api_key", "")
    c = _client()
    r = c.request(method, path)
    assert r.status_code != 401, (
        f"{method} {path} returned 401 with empty api_key — production "
        f"behavior changed. body={r.text!r}"
    )


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_nonempty_api_key_no_auth_rejects(method, path, monkeypatch):
    monkeypatch.setattr(security_module.settings, "api_key", "prod-key")
    _patch_cookie(monkeypatch, None)
    c = _client()
    r = c.request(method, path)
    assert r.status_code == 401, f"{method} {path} expected 401, got {r.status_code}"


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_nonempty_api_key_valid_header_passes(method, path, monkeypatch):
    monkeypatch.setattr(security_module.settings, "api_key", "prod-key")
    _patch_cookie(monkeypatch, None)
    c = _client()
    r = c.request(method, path, headers={"X-API-Key": "prod-key"})
    assert r.status_code != 401, (
        f"{method} {path} returned 401 with valid X-API-Key (got {r.status_code})"
    )


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_nonempty_api_key_valid_cookie_passes(method, path, monkeypatch):
    monkeypatch.setattr(security_module.settings, "api_key", "prod-key")
    _patch_cookie(monkeypatch, {"id": "u1", "role": "viewer"})
    c = _client()
    c.cookies.set("pz_session", "anything")
    r = c.request(method, path)
    assert r.status_code != 401, (
        f"{method} {path} returned 401 with valid pz_session (got {r.status_code})"
    )


def test_no_new_write_methods_on_events_subtree():
    """Sub-tree contains exactly 1 POST (events/export) and 3 GETs.
    No new PUT/PATCH/DELETE introduced by this PR.
    """
    events_routes = [
        r for r in app.routes
        if getattr(r, "path", "").startswith("/api/v1/tracking/events")
    ]
    assert events_routes, "events sub-tree missing"
    forbidden = {"PUT", "PATCH", "DELETE"}
    for route in events_routes:
        methods = set(getattr(route, "methods", set()) or set())
        bad = methods & forbidden
        assert not bad, f"{route.path} introduced forbidden method(s): {bad}"
    posts = [
        r for r in events_routes
        if "POST" in (getattr(r, "methods", set()) or set())
    ]
    assert len(posts) == 1, (
        f"Expected exactly 1 POST on /events subtree (events/export); got "
        f"{[r.path for r in posts]}"
    )


def test_events_endpoints_have_auth_dependency():
    """Router-level Depends(require_api_key) attached so all 4 endpoints
    inherit the auth — including the path currently shadowed by the
    upstream wildcard (when main.py include-order is fixed, the auth is
    already in place)."""
    from app.api.routes_tracking_db import router
    assert router.dependencies, (
        "routes_tracking_db router must declare router-level dependencies "
        "(Depends(require_api_key)) so all 4 /events endpoints inherit auth."
    )
    dep_callables = [d.dependency for d in router.dependencies]
    from app.core.security import require_api_key
    assert require_api_key in dep_callables, (
        "router-level dependencies must include require_api_key"
    )
