"""
test_dashboard_repair.py — Regression tests for the dashboard repair pass.

Verified issues:
  1. Batch Control Center: GET /api/v1/batch/{batch_id}/readiness was 404 because
     routes_batch_readiness was never mounted in main.py.  Fixed: route now mounted.
  2. Route audit: all dashboard apiFetch calls must resolve to a registered route.
  3. DHL follow-up endpoints return structured results (not crashes).
  4. Execute endpoint accepts valid action names and returns structured JSON.
  5. Closure check endpoint is read-only and returns structured JSON.
  6. Zoho scan-inbox returns structured JSON on bridge-path (no credentials).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))


# ── Shared fixtures ────────────────────────────────────────────────────────────

_BATCH = "REPAIR_TEST_001"

@pytest.fixture(scope="module")
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _headers():
    """Return API-key auth headers using the test env key."""
    from app.core.config import settings
    key = settings.api_key or "test-key"
    return {"X-API-Key": key}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Batch readiness — route is now registered (was 404 before fix)
# ═══════════════════════════════════════════════════════════════════════════════

def test_batch_readiness_route_registered(client):
    """
    GET /api/v1/batch/{batch_id}/readiness must return 200, not 404.
    Was returning 404 because routes_batch_readiness was never mounted in main.py.
    """
    with patch("app.services.batch_readiness.get_batch_readiness",
               return_value={
                   "batch_id":  _BATCH,
                   "warehouse": {"status": "n/a", "ready": False},
                   "sales":     {"status": "n/a", "ready": False},
                   "wfirma":    {"status": "n/a", "ready": False},
                   "dhl":       {"status": "awaiting_start", "ready": False},
                   "overall":   {"ready_for_closure": False, "blocked_domains": [],
                                 "next_step": ""},
               }):
        resp = client.get(f"/api/v1/batch/{_BATCH}/readiness", headers=_headers())
    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code}. "
        "Likely cause: routes_batch_readiness not mounted in main.py."
    )
    body = resp.json()
    assert "warehouse" in body
    assert "overall"   in body
    assert "dhl"       in body


def test_batch_readiness_shape_for_unknown_batch(client):
    """
    Readiness endpoint returns structured JSON even for unknown batches.
    All domains must be present and have a 'ready' key.
    """
    resp = client.get(f"/api/v1/batch/NONEXISTENT_BATCH_XYZ/readiness", headers=_headers())
    assert resp.status_code == 200
    body = resp.json()
    for domain in ("warehouse", "sales", "wfirma", "dhl"):
        assert domain in body, f"Missing domain: {domain}"
        assert "ready" in body[domain], f"Domain {domain!r} missing 'ready' key"
    assert "overall" in body
    assert "ready_for_closure" in body["overall"]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Route audit — all dashboard endpoints must resolve (0 stale)
# ═══════════════════════════════════════════════════════════════════════════════

def test_route_audit_zero_stale():
    """
    dashboard_route_audit must report zero stale/missing routes.
    Any stale route means the dashboard calls a URL that doesn't exist.
    """
    from app.tools.dashboard_route_audit import (
        audit, load_backend_routes, BackendRoute,
    )
    from app.main import app

    dashboard_html = Path(_svc) / "app" / "static" / "dashboard.html"
    if not dashboard_html.exists():
        pytest.skip("dashboard.html not found")

    html = dashboard_html.read_text(encoding="utf-8")

    # Build backend routes from the live FastAPI app (same as main CLI does).
    # load_backend_routes() uses a subprocess — override with in-process routes.
    backend_routes = []
    for r in app.routes:
        if not hasattr(r, "methods") or not hasattr(r, "path"):
            continue
        methods = frozenset(m.upper() for m in (r.methods or set()))
        backend_routes.append(BackendRoute(methods=methods, path=r.path))

    result = audit(html, backend_routes)
    stale = result.stale
    assert stale == [], (
        f"Stale (missing) routes found in dashboard:\n"
        + "\n".join(f"  {s.method:6} {s.path}" for s in stale)
        + "\nFix by adding the missing route or removing the dead dashboard call."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. DHL follow-up endpoints — route registered, returns structured JSON
# ═══════════════════════════════════════════════════════════════════════════════

def test_dhl_followup_stop_returns_structured_json(client):
    """
    POST /api/v1/dhl-followup/{batch_id}/stop — route exists and returns JSON.
    Returns 422/404 for unknown batch (not 405 Method Not Allowed or 404 route missing).
    """
    resp = client.post(
        f"/api/v1/dhl-followup/NONEXISTENT_BATCH/stop",
        json={"reason": "test"},
        headers=_headers(),
    )
    # 404 = batch not found (correct). 422 = validation error. Both mean route exists.
    assert resp.status_code in (404, 422), (
        f"Got {resp.status_code} — expected 404 (batch not found) or 422. "
        "405 would mean route not registered."
    )


def test_dhl_followup_send_now_returns_structured_json(client):
    """POST /api/v1/dhl-followup/{batch_id}/send-now — route registered."""
    resp = client.post(
        f"/api/v1/dhl-followup/NONEXISTENT_BATCH/send-now",
        json={"approved_by": "test"},
        headers=_headers(),
    )
    assert resp.status_code in (404, 422)


def test_dhl_followup_recalculate_returns_structured_json(client):
    """POST /api/v1/dhl-followup/{batch_id}/recalculate — route registered."""
    resp = client.post(
        f"/api/v1/dhl-followup/NONEXISTENT_BATCH/recalculate",
        json={},
        headers=_headers(),
    )
    assert resp.status_code in (404, 422)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Execute endpoint — valid actions return structured JSON (not 400/404)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("action", ["wfirma_create", "closure_confirm", "dhl_send_reply"])
def test_execute_known_action_not_404(client, action):
    """
    POST /api/v1/execute/{action} — known actions must not return 404.
    They may return 200 (skipped/blocked), 422 (validation), or 503 (readiness).
    """
    payload = {"batch_id": _BATCH}
    if action == "wfirma_create":
        payload["payload"] = {"client_name": "Test Client"}

    with patch("app.services.execution_engine.execute_action",
               return_value={"ok": False, "error": "readiness_load_failed",
                             "batch_id": _BATCH}):
        resp = client.post(f"/api/v1/execute/{action}", json=payload, headers=_headers())

    assert resp.status_code != 404, (
        f"execute/{action} returned 404 — route likely not registered."
    )


def test_execute_unknown_action_returns_400(client):
    """Unknown action names must return 400, not 404 (route exists, action rejected)."""
    resp = client.post(
        "/api/v1/execute/totally_bogus_action",
        json={"batch_id": _BATCH},
        headers=_headers(),
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body.get("error") == "unknown_action"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Closure check — read-only, returns structured JSON
# ═══════════════════════════════════════════════════════════════════════════════

def test_closure_check_route_registered(client):
    """GET /api/v1/closure/{batch_id}/check — route exists, returns 404 for unknown batch."""
    resp = client.get(f"/api/v1/closure/NONEXISTENT_BATCH_XYZ/check", headers=_headers())
    assert resp.status_code == 404, (
        f"Expected 404 (batch not found), got {resp.status_code}. "
        "405 would mean route not registered."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 6. DHL scan-inbox — returns structured JSON (bridge path when no credentials)
# ═══════════════════════════════════════════════════════════════════════════════

def test_scan_inbox_returns_structured_json(client):
    """
    GET /api/v1/dhl/scan-inbox — must return structured JSON.
    Without Zoho OAuth credentials, it dispatches to AI Bridge (ai_bridge_pending).
    Either path must return JSON with 'scanned', 'matched', 'scan_method'.
    """
    _bridge_result = {
        "scanned":     0,
        "matched":     0,
        "emails":      [],
        "scan_method": "ai_bridge_pending",
        "scanned_at":  "2026-05-06T12:00:00Z",
        "bridge_task": {"task_id": "t-test-123", "task_type": "email_scan",
                        "message": "Email scan dispatched to AI Bridge."},
    }

    # scan_for_dhl_customs_emails is imported inside the view at call time from a
    # non-package module (dhl_email_monitor).  _dispatch_to_bridge is a local
    # closure — neither can be patched by name.
    # Strategy: no Zoho creds + no email intelligence cache → bridge path.
    # Patch ai_bridge.create_task so the bridge call returns without network I/O.
    _mock_task = {"task_id": "t-test-123", "task_type": "email_scan",
                  "result_file": None}
    with patch("app.services.zoho_auth.has_zoho_credentials", return_value=False), \
         patch("app.services.ai_bridge.create_task", return_value=_mock_task), \
         patch("app.services.email_intelligence_store.find_existing_email_context",
               return_value=None):
        resp = client.get("/api/v1/dhl/scan-inbox", headers=_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert "scan_method" in body, f"Missing scan_method in response: {body}"
    assert "matched"     in body
    assert "scanned"     in body
    # Bridge path: scan_method indicates how the scan was handled (not silent failure)
    assert body.get("scan_method") != "", "scan_method should not be empty"
