"""
SEC-WAREHOUSE-APIKEY-1 — regression suite.

Closes the authenticated-but-unsafe secret disclosure: GET /api/v1/warehouse/config
used to return settings.api_key (an admin-equivalent X-API-Key) to ANY authenticated
session, letting a read-only role escalate. The route is removed; warehouse writes now
require a write-capable role (require_api_key_privileged); the browser authenticates by
session cookie and never fetches/stores/sends the shared key.

Mix of structural source pins (fast, boot-free) and behavioral role-matrix tests on an
isolated app with the real privileged gate.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.auth.dependencies as authdeps
from app.api.routes_warehouse import router as warehouse_router
from app.api.routes_warehouse_receipt import router as receipt_router
from app.core.config import settings

_APP = Path(__file__).resolve().parents[1] / "app"
_API = _APP / "api"
_STATIC = _APP / "static"


# ── isolated app + client ─────────────────────────────────────────────────────

@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(warehouse_router)
    app.include_router(receipt_router)
    # raise_server_exceptions=False: auth runs BEFORE business logic; a post-auth
    # 500 (e.g. warehouse_db not initialised in this isolated app) still proves the
    # gate ALLOWED the request — we assert on auth (401/403), not business success.
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def enforce_key(monkeypatch):
    # Gate only enforces when api_key is configured and env != prod-misconfig.
    monkeypatch.setattr(settings, "api_key", "TESTKEY_WAREHOUSE", raising=False)
    monkeypatch.setattr(settings, "environment", "dev", raising=False)
    return "TESTKEY_WAREHOUSE"


def _as_role(monkeypatch, role):
    monkeypatch.setattr(authdeps, "get_current_user_optional",
                        lambda pz_session=None: {"id": 1, "role": role, "is_active": True, "is_approved": True})


# ── 1. no route serializes settings.api_key ──────────────────────────────────

def test_no_api_route_serializes_settings_api_key():
    offenders = []
    for p in _API.glob("*.py"):
        src = p.read_text(encoding="utf-8")
        if '"api_key": settings.api_key' in src or "'api_key': settings.api_key" in src:
            offenders.append(p.name)
    assert offenders == [], f"routes serialize settings.api_key: {offenders}"


def test_routes_warehouse_has_no_settings_api_key():
    src = (_API / "routes_warehouse.py").read_text(encoding="utf-8")
    assert "settings.api_key" not in src


# ── 2. /config removed ───────────────────────────────────────────────────────

def test_config_route_removed_from_source():
    src = (_API / "routes_warehouse.py").read_text(encoding="utf-8")
    assert 'get("/config")' not in src
    assert "def warehouse_config" not in src


def test_config_route_returns_404(client):
    assert client.get("/api/v1/warehouse/config").status_code == 404


# ── 3-5. write-route auth matrix (real privileged gate) ──────────────────────

def test_unauthenticated_write_rejected(client, enforce_key):
    # no X-API-Key, no session cookie
    r = client.post("/api/v1/warehouse/scan", json={"scan_code": "X", "action": "RECEIVE"})
    assert r.status_code == 401


def test_read_only_role_write_forbidden(client, enforce_key, monkeypatch):
    _as_role(monkeypatch, "viewer")
    r = client.post("/api/v1/warehouse/scan",
                    json={"scan_code": "X", "action": "RECEIVE"},
                    cookies={"pz_session": "sess"})
    assert r.status_code == 403


def test_write_capable_role_allowed(client, enforce_key, monkeypatch):
    _as_role(monkeypatch, "logistics")
    r = client.post("/api/v1/warehouse/scan",
                    json={"scan_code": "NO_SUCH_CODE", "action": "RECEIVE"},
                    cookies={"pz_session": "sess"})
    # auth PASSED — anything but 401/403 proves the gate allowed the write-capable role.
    assert r.status_code not in (401, 403)


# ── 6. browser flow works without X-API-Key (session cookie only) ────────────

def test_session_write_without_api_key(client, enforce_key, monkeypatch):
    _as_role(monkeypatch, "logistics")
    r = client.post("/api/v1/warehouse/scan",
                    json={"scan_code": "NO_SUCH_CODE", "action": "RECEIVE"},
                    cookies={"pz_session": "sess"})  # NO X-API-Key header
    assert r.status_code not in (401, 403)


# ── 7. invalid API key rejected ──────────────────────────────────────────────

def test_invalid_api_key_rejected(client, enforce_key):
    r = client.post("/api/v1/warehouse/scan",
                    json={"scan_code": "X", "action": "RECEIVE"},
                    headers={"X-API-Key": "WRONG_KEY"})
    assert r.status_code == 401


# ── 8. verified automation flow preserved (valid X-API-Key) ──────────────────

def test_api_key_automation_preserved(client, enforce_key):
    r = client.post("/api/v1/warehouse/scan",
                    json={"scan_code": "NO_SUCH_CODE", "action": "RECEIVE"},
                    headers={"X-API-Key": enforce_key})
    assert r.status_code not in (401, 403)  # automation authorized


# ── 9. no frontend API-key retrieval remnants ────────────────────────────────

@pytest.mark.parametrize("page", ["warehouse.html", "dashboard.html"])
def test_no_frontend_key_retrieval_remnants(page):
    src = (_STATIC / page).read_text(encoding="utf-8")
    assert "/warehouse/config" not in src, f"{page} still references the removed /config route"
    assert "X-API-Key" not in src, f"{page} still sends X-API-Key"
    assert "d.api_key" not in src and ".api_key" not in src, f"{page} still reads an api_key field"
