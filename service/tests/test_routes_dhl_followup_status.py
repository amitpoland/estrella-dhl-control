"""
test_routes_dhl_followup_status.py — Contract tests for the read-only
DHL follow-up automation status endpoints.

Coverage:
  1. GET /status returns 200 + expected shape
  2. GET /shipments returns 200 + rows envelope
  3. /status counters reflect synthetic audits on disk
  4. /shipments rows match synthetic audits and exclude inactive ones
  5. Endpoints are read-only (no POST verb registered)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_SERVICE = Path(__file__).resolve().parents[1]
if str(_SERVICE) not in sys.path:
    sys.path.insert(0, str(_SERVICE))


_NOW = datetime.now(timezone.utc)


@pytest.fixture()
def tmp_storage(tmp_path):
    return tmp_path


@pytest.fixture()
def client(tmp_storage):
    from app.core.config import settings
    from app.main import app
    with patch.object(settings, "storage_root", tmp_storage):
        yield TestClient(app)


def _write_audit(storage: Path, batch_id: str, data: dict) -> Path:
    d = storage / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / "audit.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _active_audit(
    *,
    awb:           str,
    batch_id:      str,
    next_followup_at: str | None = None,
    timeline:      list | None = None,
    stopped_at:    str | None = None,
) -> dict:
    state = {"active": True}
    if next_followup_at is not None:
        state["next_followup_at"] = next_followup_at
    if stopped_at is not None:
        state["stopped_at"] = stopped_at
    return {
        "batch_id":           batch_id,
        "awb":                awb,
        "tracking_no":        awb,
        "clearance_decision": {"clearance_path": "self_clearance"},
        "clearance_status":   "in_progress",
        "dhl_followup":       state,
        "timeline":           timeline or [],
    }


# ── 1. /status 200 + shape ───────────────────────────────────────────────────

def test_status_endpoint_returns_expected_shape(client, tmp_storage):
    r = client.get("/api/v1/dhl/followup-automation/status")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "flag_on", "status_label",
        "active_shipments", "monitoring", "eligible_now",
        "next_due", "last_sent", "last_suppressed", "last_failure",
        "sent_today", "suppressed_today", "failed_today",
        "ai_used_today", "ai_fallback_today",
        "traffic_light", "generated_at",
    ):
        assert key in body, f"missing key {key}"
    assert body["status_label"] in ("ACTIVE", "DISABLED")
    assert set(body["traffic_light"].keys()) == {"ready", "waiting", "problems"}


# ── 2. /shipments 200 + envelope ─────────────────────────────────────────────

def test_shipments_endpoint_envelope(client, tmp_storage):
    r = client.get("/api/v1/dhl/followup-automation/shipments")
    assert r.status_code == 200
    body = r.json()
    assert "rows" in body and isinstance(body["rows"], list)
    assert "count" in body and body["count"] == len(body["rows"])


# ── 3. /status counters reflect on-disk audits ───────────────────────────────

def test_status_counters_reflect_audits_on_disk(client, tmp_storage):
    future = (_NOW + timedelta(hours=2)).isoformat()
    past   = (_NOW - timedelta(minutes=5)).isoformat()
    _write_audit(tmp_storage, "SHIPMENT_MON_1", _active_audit(
        awb="MONITOR_A", batch_id="SHIPMENT_MON_1", next_followup_at=future))
    _write_audit(tmp_storage, "SHIPMENT_ELI_1", _active_audit(
        awb="ELIGIBLE_A", batch_id="SHIPMENT_ELI_1", next_followup_at=past))

    r = client.get("/api/v1/dhl/followup-automation/status")
    assert r.status_code == 200
    body = r.json()
    assert body["active_shipments"] == 2
    assert body["monitoring"] == 1
    assert body["eligible_now"] == 1
    assert body["next_due"]["awb"] == "MONITOR_A"


# ── 4. /shipments rows exclude inactive ──────────────────────────────────────

def test_shipments_rows_exclude_inactive(client, tmp_storage):
    past = (_NOW - timedelta(minutes=5)).isoformat()
    _write_audit(tmp_storage, "SHIPMENT_ACTIVE", _active_audit(
        awb="ACTIVE_A", batch_id="SHIPMENT_ACTIVE", next_followup_at=past))
    # Inactive: no AWB → is_active_shipment fails on missing_awb
    _write_audit(tmp_storage, "SHIPMENT_NOAWB", {
        "batch_id":           "SHIPMENT_NOAWB",
        "awb":                "",
        "clearance_decision": {"clearance_path": "self_clearance"},
        "clearance_status":   "in_progress",
        "dhl_followup":       {"active": True},
    })

    r = client.get("/api/v1/dhl/followup-automation/shipments")
    assert r.status_code == 200
    body = r.json()
    awbs = [row["awb"] for row in body["rows"]]
    assert "ACTIVE_A" in awbs
    assert "" not in awbs
    assert body["count"] == 1


# ── 5a. Cache-Control: no-store on both endpoints ────────────────────────────

def test_endpoints_emit_no_store_cache_headers(client, tmp_storage):
    """Operator must see flag flips and recent events immediately, not stale."""
    for url in (
        "/api/v1/dhl/followup-automation/status",
        "/api/v1/dhl/followup-automation/shipments",
    ):
        r = client.get(url)
        assert r.status_code == 200
        cc = r.headers.get("cache-control", "").lower()
        assert "no-store" in cc, f"missing no-store on {url}: {cc!r}"


# ── 5. Endpoints are read-only (POST not registered) ─────────────────────────

def test_endpoints_are_get_only(client, tmp_storage):
    # POST /status should 405 (Method Not Allowed) or 404 — never 200
    r_post = client.post("/api/v1/dhl/followup-automation/status", json={})
    assert r_post.status_code in (404, 405)
    r_post2 = client.post("/api/v1/dhl/followup-automation/shipments", json={})
    assert r_post2.status_code in (404, 405)
