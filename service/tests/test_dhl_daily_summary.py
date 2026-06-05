"""
test_dhl_daily_summary.py — DHL Daily Operations Report.

Coverage:
  A. GET /api/v1/dhl/daily-summary endpoint (source-grep)
     - registered, auth guarded, read-only
     - returns lane_a_health section
     - returns active_shipments section
     - returns dhl_waiting_queue section
     - returns lane_b_candidates section
     - returns exceptions section
     - returns summary counters
     - never triggers scan, never sends email

  B. JSX dashboard card
     - component exists, calls daily-summary API
     - executive summary grid present
     - data-testid refresh button
     - no scan trigger

  C. Functional: summary returns expected shape (with status file + batches)
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

_ROUTE = Path(__file__).parent.parent / "app" / "api" / "routes_dhl_clearance.py"
_JSX   = Path(__file__).parent.parent / "app" / "static" / "v2" / "dhl-daily-summary.jsx"


def _summary_block(src: str) -> str:
    idx = src.index("daily-summary")
    end = src.find("\n@router.", idx + 10)
    return src[idx:end] if end > idx else src[idx:]


# ══════════════════════════════════════════════════════════════════════════════
# A. Endpoint
# ══════════════════════════════════════════════════════════════════════════════

def test_daily_summary_endpoint_registered():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    assert '@router.get("/daily-summary"' in src


def test_daily_summary_requires_auth():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    # The GET daily-summary decorator line must be followed by _auth within 120 chars
    idx = src.index('@router.get("/daily-summary"')
    assert "_auth" in src[idx:idx+120]


def test_daily_summary_returns_lane_a_health():
    assert "lane_a_health" in _summary_block(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_daily_summary_returns_active_shipments():
    assert "active_shipments" in _summary_block(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_daily_summary_returns_dhl_waiting_queue():
    assert "dhl_waiting_queue" in _summary_block(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_daily_summary_returns_lane_b_candidates():
    assert "lane_b_candidates" in _summary_block(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_daily_summary_returns_exceptions():
    assert "exceptions" in _summary_block(_ROUTE.read_text(encoding="utf-8", errors="replace"))


def test_daily_summary_returns_summary_counters():
    block = _summary_block(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    for f in ["active_shipments", "waiting_for_dhl", "replies_sent_today",
              "scanner_runs_24h", "lane_b_eligible"]:
        assert f in block, f"summary must include '{f}'"


def test_daily_summary_never_triggers_scan():
    block = _summary_block(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    assert "run_ingestion_cycle" not in block
    assert "_ensure_dhl_reply" not in block


def test_daily_summary_never_sends_email():
    block = _summary_block(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    assert "queue_email" not in block
    assert "send_queued_email" not in block


def test_daily_summary_reads_scan_status_path():
    block = _summary_block(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    assert "_scan_status_path" in block or "dhl_auto_scan_status" in block


def test_daily_summary_reads_log_for_24h_history():
    block = _summary_block(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    assert "dhl-auto-scan.log" in block


def test_daily_summary_lane_b_candidates_include_eligibility():
    block = _summary_block(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    assert "eligible" in block
    assert "hours_waiting" in block
    assert "lane_b_status" in block


def test_daily_summary_waiting_queue_sorted_oldest_first():
    block = _summary_block(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    assert "sort" in block and "days_open" in block


def test_daily_summary_no_wfirma():
    block = _summary_block(_ROUTE.read_text(encoding="utf-8", errors="replace"))
    assert "import wfirma" not in block.lower()
    assert "wfirma_api" not in block.lower()


# ══════════════════════════════════════════════════════════════════════════════
# B. JSX dashboard card
# ══════════════════════════════════════════════════════════════════════════════

def test_jsx_exists():
    assert _JSX.exists()


def test_jsx_calls_daily_summary_api():
    assert "daily-summary" in _JSX.read_text(encoding="utf-8", errors="replace")


def test_jsx_refresh_button_testid():
    assert "dhl-summary-refresh" in _JSX.read_text(encoding="utf-8", errors="replace")


def test_jsx_exports_component():
    assert "window.DhlDailySummary" in _JSX.read_text(encoding="utf-8", errors="replace")


def test_jsx_no_scan_trigger():
    src = _JSX.read_text(encoding="utf-8", errors="replace")
    assert "scheduled-inbox-check" not in src


def test_jsx_no_email_send():
    src = _JSX.read_text(encoding="utf-8", errors="replace")
    assert "queue_email" not in src
    assert "send_queued_email" not in src


def test_jsx_has_executive_summary_section():
    assert "Executive Summary" in _JSX.read_text(encoding="utf-8", errors="replace")


def test_jsx_has_dhl_waiting_queue_section():
    assert "Waiting Queue" in _JSX.read_text(encoding="utf-8", errors="replace")


def test_jsx_has_lane_b_candidates_section():
    assert "Lane B Candidates" in _JSX.read_text(encoding="utf-8", errors="replace")


# ══════════════════════════════════════════════════════════════════════════════
# C. Functional
# ══════════════════════════════════════════════════════════════════════════════

def test_daily_summary_returns_expected_shape(tmp_path, monkeypatch):
    """Functional: summary returns correct top-level shape."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key")
    monkeypatch.setattr(settings, "dhl_followup_enabled", False)

    # Minimal status file
    (tmp_path / "dhl_auto_scan_status.json").write_text(json.dumps({
        "status": "success",
        "started_at": "2026-06-05T13:06:03+00:00",
        "completed_at": "2026-06-05T13:09:27+00:00",
        "duration_seconds": 204,
        "batches_checked": 15,
        "received_set": 0,
    }), encoding="utf-8")
    # No batch dirs → active_shipments = []
    (tmp_path / "outputs").mkdir()

    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.get("/api/v1/dhl/daily-summary", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    body = resp.json()

    # Top-level keys
    for key in ["lane_a_health", "active_shipments", "dhl_waiting_queue",
                "lane_b_candidates", "exceptions", "summary", "generated_at"]:
        assert key in body, f"Missing key: {key}"

    # Lane A health from status file
    assert body["lane_a_health"]["last_run_status"] == "success"
    assert body["lane_a_health"]["last_run_duration_s"] == 204

    # Counters
    assert body["summary"]["active_shipments"] == 0
    assert body["summary"]["waiting_for_dhl"] == 0
