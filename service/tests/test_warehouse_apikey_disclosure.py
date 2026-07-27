"""
SEC-WAREHOUSE-APIKEY-1 — regression suite.

Closes the authenticated-but-unsafe secret disclosure: GET /api/v1/warehouse/config
used to return settings.api_key (an admin-equivalent X-API-Key) to ANY authenticated
session, letting a read-only role escalate. The route is removed; warehouse writes now
require a write-capable role (require_api_key_privileged); the browser authenticates by
session cookie and never fetches/stores/sends the shared key.

Design: positive authorization tests exercise the REAL auth dependency
(require_api_key_privileged) and mock ONLY the warehouse business-service boundary
(warehouse_db). A 200 with the business function called exactly once is the success
proof — a downstream 500 is NEVER treated as success. No real warehouse DB is touched.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.auth.dependencies as authdeps
import app.services.warehouse_db as wdb_mod
import app.services.warehouse_receipt as wrcpt_mod
from app.api.routes_warehouse import router as warehouse_router
from app.api.routes_warehouse_receipt import router as receipt_router
from app.core.config import settings

_APP = Path(__file__).resolve().parents[1] / "app"
_API = _APP / "api"
_STATIC = _APP / "static"

_SCAN_BODY = {"scan_code": "SC1", "action": "RECEIVE",
              "to_location": "T1", "operator": "op", "note": "n"}


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(warehouse_router)
    app.include_router(receipt_router)
    # raise_server_exceptions default (True): an unexpected post-auth 500 raises
    # loudly — it can never be silently mistaken for authorization success.
    return TestClient(app)


@pytest.fixture()
def enforce_key(monkeypatch):
    # The gate only enforces when api_key is configured.
    monkeypatch.setattr(settings, "api_key", "TESTKEY_WAREHOUSE", raising=False)
    monkeypatch.setattr(settings, "environment", "dev", raising=False)
    return "TESTKEY_WAREHOUSE"


@pytest.fixture()
def mock_scan(monkeypatch):
    """Mock ONLY the business boundary: warehouse_db.record_scan + get_movement_history."""
    m = MagicMock(return_value={
        "current_location": "T1", "current_status": "IN_STOCK",
        "updated_at": "2026-07-26T00:00:00Z", "unknown_location": False,
    })
    monkeypatch.setattr(wdb_mod, "record_scan", m)
    monkeypatch.setattr(wdb_mod, "get_movement_history", lambda *a, **k: [])
    return m


def _as_role(monkeypatch, role):
    monkeypatch.setattr(authdeps, "get_current_user_optional",
                        lambda pz_session=None: {"id": 1, "role": role,
                                                 "is_active": True, "is_approved": True})


# ── structural pins ──────────────────────────────────────────────────────────

def test_no_api_route_serializes_settings_api_key():
    offenders = [p.name for p in _API.glob("*.py")
                 if '"api_key": settings.api_key' in p.read_text(encoding="utf-8")
                 or "'api_key': settings.api_key" in p.read_text(encoding="utf-8")]
    assert offenders == [], f"routes serialize settings.api_key: {offenders}"


def test_routes_warehouse_has_no_settings_api_key():
    assert "settings.api_key" not in (_API / "routes_warehouse.py").read_text(encoding="utf-8")


def test_config_route_removed_from_source():
    src = (_API / "routes_warehouse.py").read_text(encoding="utf-8")
    assert 'get("/config")' not in src and "def warehouse_config" not in src


def test_all_warehouse_writes_use_privileged_gate():
    wh = (_API / "routes_warehouse.py").read_text(encoding="utf-8")
    rc = (_API / "routes_warehouse_receipt.py").read_text(encoding="utf-8")
    assert "_auth_write = Depends(require_api_key_privileged)" in wh
    assert "_auth_write = Depends(require_api_key_privileged)" in rc
    assert '@router.post("/scan", dependencies=[_auth_write])' in wh
    assert '@router.post("/locations", dependencies=[_auth_write])' in wh
    assert '@router.post("/confirm", dependencies=[_auth_write])' in rc


def test_config_route_returns_404(client):
    assert client.get("/api/v1/warehouse/config").status_code == 404


# ── POSITIVE authorization (real gate; business mocked; proves execution) ─────

def test_logistics_session_executes_write(client, enforce_key, monkeypatch, mock_scan):
    _as_role(monkeypatch, "logistics")
    r = client.post("/api/v1/warehouse/scan", json=_SCAN_BODY, cookies={"pz_session": "sess"})
    assert r.status_code == 200, r.text
    assert mock_scan.call_count == 1  # business function executed exactly once
    kw = mock_scan.call_args.kwargs
    assert kw["scan_code"] == "SC1"
    assert kw["action"] == "RECEIVE"
    assert kw["to_location"] == "T1"
    assert kw["operator"] == "op"
    assert r.json()["ok"] is True


def test_admin_session_executes_write(client, enforce_key, monkeypatch, mock_scan):
    _as_role(monkeypatch, "admin")
    r = client.post("/api/v1/warehouse/scan", json=_SCAN_BODY, cookies={"pz_session": "sess"})
    assert r.status_code == 200, r.text
    assert mock_scan.call_count == 1


def test_api_key_automation_executes_write(client, enforce_key, mock_scan):
    # valid X-API-Key, NO session cookie → automation compatibility through
    # require_api_key_privileged is proven by a successful execution.
    r = client.post("/api/v1/warehouse/scan", json=_SCAN_BODY,
                    headers={"X-API-Key": enforce_key})
    assert r.status_code == 200, r.text
    assert mock_scan.call_count == 1


# ── SCAN IS OPTIONAL: non-scan writes must NOT require/call a scan ───────────
# record_scan is wired to raise immediately if touched; a successful status proves
# the endpoint is independent of scanning (no scan prerequisite, no record_scan call).

def _forbid_scan(monkeypatch):
    monkeypatch.setattr(wdb_mod, "record_scan",
                        MagicMock(side_effect=AssertionError(
                            "scanning is OPTIONAL — record_scan must not be called")))


def test_locations_write_independent_of_scan(client, enforce_key, monkeypatch):
    _as_role(monkeypatch, "logistics")
    _forbid_scan(monkeypatch)
    up = MagicMock(return_value="loc-1")
    monkeypatch.setattr(wdb_mod, "upsert_location", up)
    r = client.post("/api/v1/warehouse/locations",
                    json={"location_code": "T1", "location_type": "tray"},
                    cookies={"pz_session": "sess"})
    assert r.status_code == 200, r.text          # succeeds with NO prior scan
    assert up.call_count == 1                     # its own business fn ran
    assert r.json()["ok"] is True


def test_receipt_confirm_independent_of_scan(client, enforce_key, monkeypatch):
    _as_role(monkeypatch, "logistics")
    _forbid_scan(monkeypatch)
    cr = MagicMock(return_value={"batch_id": "B1", "confirmed_lines": 1})
    monkeypatch.setattr(wrcpt_mod, "confirm_receipt", cr)
    r = client.post("/api/v1/warehouse/receipt/confirm",
                    json={"batch_id": "B1", "lines": [{"accepted_qty": 1}]},
                    cookies={"pz_session": "sess"})
    assert r.status_code == 200, r.text          # succeeds with NO prior scan
    assert cr.call_count == 1
    assert r.json()["ok"] is True


# ── NEGATIVE authorization (business must NOT execute) ────────────────────────

def test_unauthenticated_rejected(client, enforce_key, mock_scan):
    r = client.post("/api/v1/warehouse/scan", json=_SCAN_BODY)
    assert r.status_code == 401
    assert mock_scan.call_count == 0


@pytest.mark.parametrize("role", ["viewer", "auditor", "master_viewer"])
def test_read_only_roles_forbidden(client, enforce_key, monkeypatch, mock_scan, role):
    _as_role(monkeypatch, role)
    r = client.post("/api/v1/warehouse/scan", json=_SCAN_BODY, cookies={"pz_session": "sess"})
    assert r.status_code == 403
    assert mock_scan.call_count == 0


def test_invalid_api_key_rejected(client, enforce_key, mock_scan):
    r = client.post("/api/v1/warehouse/scan", json=_SCAN_BODY,
                    headers={"X-API-Key": "FRESH_WRONG_KEY"})
    assert r.status_code == 401
    assert mock_scan.call_count == 0


# ── no frontend API-key retrieval remnants ───────────────────────────────────

@pytest.mark.parametrize("page", ["warehouse.html", "dashboard.html"])
def test_no_frontend_key_retrieval_remnants(page):
    src = (_STATIC / page).read_text(encoding="utf-8")
    assert "/warehouse/config" not in src, f"{page} still references removed /config"
    assert "X-API-Key" not in src, f"{page} still sends X-API-Key"
    assert ".api_key" not in src, f"{page} still reads an api_key field"
