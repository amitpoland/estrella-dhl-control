"""
test_debug_health_endpoints.py — regression for two pre-existing debug-endpoint
500s surfaced during Campaign 02.76 Deploy #2 verification (2026-06-13), both
confirmed OUTSIDE the deploy diff (65f9ea7..f36bef4).

BUG 1 — GET /api/v1/debug/health-full returned 500
    UnboundLocalError: local variable 'settings' referenced before assignment.
    `settings` is imported at module level, but a redundant function-local
    `from ..core.config import settings` inside health_full() (Step 13) made
    Python treat `settings` as a local for the whole body — so the Step 2
    reference fired before the local was bound. Fix: drop the local re-import.

BUG 2 — GET /api/v1/debug/storage/health returned 500
    "cannot import name 'storage_health_snapshot' from partially initialized
    module 'app.utils.storage_health' (circular import)". storage_health is a
    stdlib-only utility with no path back to routes_debug, so there is no real
    cycle. The 500 was a lazy-first-import race: FastAPI runs the sync storage/*
    endpoints in a threadpool, and two concurrent first-touches saw the
    half-initialised module in sys.modules. Fix: hoist the import to module
    level (single-threaded startup), which is safe precisely because the
    dependency is acyclic.

These tests pin both endpoints at 200 and assert the structural shape that
prevents regression.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.core.config import settings  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    """App booted with an isolated storage_root and a real API key."""
    with (
        patch.object(settings, "api_key", "real-key"),
        patch.object(settings, "auth_secret_key", "test-secret-not-placeholder"),
        patch.object(settings, "environment", "prod"),
        patch.object(settings, "storage_root", tmp_path),
    ):
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


_HDR = {"X-API-Key": "real-key"}


# ── Integration: the endpoints must not 500 ──────────────────────────────────

def test_health_full_returns_200_not_500(client):
    """BUG 1: health-full must resolve `settings` (no UnboundLocalError → no 500)."""
    r = client.get("/api/v1/debug/health-full", headers=_HDR)
    assert r.status_code == 200, r.text[:500]
    body = r.json()
    # overall may be 'degraded' (sub-checks fail in test env) but must be a real
    # JSON diagnostic, not a 500 stack trace.
    assert "overall" in body and "checks" in body


def test_storage_health_returns_200_not_500(client):
    """BUG 2: storage/health must import cleanly (no circular-import 500)."""
    r = client.get("/api/v1/debug/storage/health", headers=_HDR)
    assert r.status_code == 200, r.text[:500]
    assert "ok" in r.json()


def test_storage_locks_returns_200_not_500(client):
    """Sibling endpoint shares the same (now module-level) import — pin it too."""
    r = client.get("/api/v1/debug/storage/locks", headers=_HDR)
    assert r.status_code == 200, r.text[:500]
    assert "lock_files_found" in r.json()


# ── Structural guards: keep the fixes in place ───────────────────────────────

def test_health_full_has_no_local_settings_reimport():
    """BUG 1 guard: no function-local `settings` import may shadow the module global."""
    import app.api.routes_debug as rd
    src = inspect.getsource(rd.health_full)
    assert "from ..core.config import settings" not in src, (
        "A function-local settings import re-introduces the UnboundLocalError "
        "(settings becomes a local for the whole body)."
    )


def test_storage_health_imported_at_module_level():
    """BUG 2 guard: storage_health symbols imported eagerly, not lazily per-call."""
    import app.api.routes_debug as rd
    # The names must be resolvable as module attributes (eager import succeeded).
    assert hasattr(rd, "storage_health_snapshot")
    assert hasattr(rd, "scan_locks")
    # And the handlers must NOT carry a lazy re-import that re-opens the race.
    for fn in (rd.storage_health, rd.storage_locks):
        body = inspect.getsource(fn)
        assert "from ..utils.storage_health import" not in body, (
            f"{fn.__name__} must rely on the module-level import, not a lazy one."
        )
