"""
test_dhl_scan_status.py
========================
Tests for the DHL auto-scan status card (PR #458).

Coverage:
  A. GET /api/v1/dhl/auto-scan-status endpoint (source-grep)
     - endpoint registered as GET
     - reads from dhl_auto_scan_status.json
     - never triggers a scan
     - never sends email
     - returns never_run when file absent

  B. POST /scheduled-inbox-check writes status (source-grep)
     - writes "running" status at scan start
     - writes "success" status on completion
     - writes "failed" status on exception
     - status includes all required counts
     - no email sent from status endpoint

  C. JSX status card (source-grep)
     - component exists
     - calls auto-scan-status API
     - data-testid present for refresh button
     - no scan trigger in component
     - no email send in component

  D. PowerShell script writes timed_out
     - script checks for timeout error
     - writes timed_out status
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

_ROUTE     = Path(__file__).parent.parent / "app" / "api" / "routes_dhl_clearance.py"
_STATUS_JSX = Path(__file__).parent.parent / "app" / "static" / "v2" / "dhl-scan-status.jsx"
_SCRIPT    = Path(__file__).parent.parent / "scripts" / "dhl-email-auto-scan.ps1"


# ══════════════════════════════════════════════════════════════════════════════
# A. GET /api/v1/dhl/auto-scan-status endpoint
# ══════════════════════════════════════════════════════════════════════════════

def test_status_endpoint_registered_as_get():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    assert '@router.get("/auto-scan-status"' in src, (
        "GET /api/v1/dhl/auto-scan-status must be registered"
    )


def test_status_endpoint_reads_status_file():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    # The GET endpoint reads dhl_auto_scan_status.json
    idx = src.index('auto-scan-status')
    block = src[idx:idx+1500]
    assert "dhl_auto_scan_status.json" in block or "_scan_status_path" in block


def test_status_endpoint_returns_never_run_when_absent():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    idx = src.index("auto-scan-status")
    block = src[idx:idx+1500]
    assert "never_run" in block, (
        "Status endpoint must return 'never_run' when status file does not exist"
    )


def test_status_endpoint_does_not_trigger_scan():
    """GET status endpoint must not call run_ingestion_cycle or _ensure_dhl_reply."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    # Find only the GET endpoint body (before the POST)
    get_idx = src.index('@router.get("/auto-scan-status"')
    post_idx = src.index('@router.post("/scheduled-inbox-check"')
    get_block = src[get_idx:post_idx]
    assert "run_ingestion_cycle" not in get_block, (
        "GET status endpoint must not trigger a scan"
    )
    assert "_ensure_dhl_reply" not in get_block, (
        "GET status endpoint must not trigger B2"
    )


def test_status_endpoint_no_email_send():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    get_idx = src.index('@router.get("/auto-scan-status"')
    post_idx = src.index('@router.post("/scheduled-inbox-check"')
    get_block = src[get_idx:post_idx]
    assert "queue_email" not in get_block
    assert "send_queued_email" not in get_block


def test_status_endpoint_returns_all_required_fields():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    get_idx = src.index('@router.get("/auto-scan-status"')
    post_idx = src.index('@router.post("/scheduled-inbox-check"')
    get_block = src[get_idx:post_idx]
    required = [
        "started_at", "completed_at", "duration_seconds",
        "batches_checked", "received_set", "b2_triggered", "b2_sent",
        "skipped_inactive", "skipped_excluded", "errors_count",
        "last_error", "next_run_at",
    ]
    for field in required:
        assert field in get_block, f"Status response must include field '{field}'"


def test_status_endpoint_computes_next_run_at():
    """next_run_at must be computed as started_at + 10 minutes."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    get_idx = src.index('@router.get("/auto-scan-status"')
    post_idx = src.index('@router.post("/scheduled-inbox-check"')
    get_block = src[get_idx:post_idx]
    assert "timedelta(minutes=10)" in get_block, (
        "Status endpoint must compute next_run_at as started_at + 10 minutes"
    )


# ══════════════════════════════════════════════════════════════════════════════
# B. POST /scheduled-inbox-check writes status
# ══════════════════════════════════════════════════════════════════════════════

def _inbox_check_block(src: str) -> str:
    idx = src.index('@router.post("/scheduled-inbox-check"')
    end = src.find("\n@router.", idx + 10)
    return src[idx:end] if end > idx else src[idx:]


def test_scan_writes_running_status_at_start():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _inbox_check_block(src)
    # "running" write must appear before the ingestion cycle call
    running_idx = block.index('"running"')
    ingest_idx  = block.index("_run_ing()")
    assert running_idx < ingest_idx, (
        "Status must be written as 'running' BEFORE the ingestion cycle starts"
    )


def test_scan_writes_success_status_on_completion():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _inbox_check_block(src)
    assert '"success"' in block, "Scan must write 'success' status on completion"


def test_scan_writes_failed_status_on_exception():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _inbox_check_block(src)
    assert '"failed"' in block, "Scan must write 'failed' status on exception"


def test_success_status_includes_all_counts():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _inbox_check_block(src)
    # Find the success status write
    success_idx = block.index('"success"')
    success_context = block[success_idx:success_idx+900]
    for count_field in ["batches_checked", "received_set", "b2_triggered",
                        "b2_sent", "skipped_inactive", "skipped_excluded",
                        "errors_count", "last_error"]:
        assert count_field in success_context, (
            f"Success status must include count field '{count_field}'"
        )


def test_scan_writes_duration_seconds():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _inbox_check_block(src)
    assert "duration_seconds" in block


def test_status_helper_uses_write_json_atomic():
    """Status writes must use write_json_atomic (atomic, no partial writes)."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    assert "_write_scan_status" in src
    # The helper must call write_json_atomic
    helper_idx = src.index("def _write_scan_status")
    helper_block = src[helper_idx:helper_idx+300]
    assert "write_json_atomic" in helper_block


# ══════════════════════════════════════════════════════════════════════════════
# C. JSX status card
# ══════════════════════════════════════════════════════════════════════════════

def test_status_jsx_exists():
    assert _STATUS_JSX.exists()


def test_status_jsx_calls_auto_scan_status_api():
    src = _STATUS_JSX.read_text(encoding="utf-8", errors="replace")
    assert "auto-scan-status" in src, (
        "DhlScanStatus component must call /api/v1/dhl/auto-scan-status"
    )


def test_status_jsx_refresh_button_has_testid():
    src = _STATUS_JSX.read_text(encoding="utf-8", errors="replace")
    assert "dhl-scan-status-refresh" in src


def test_status_jsx_does_not_trigger_scan():
    src = _STATUS_JSX.read_text(encoding="utf-8", errors="replace")
    assert "scheduled-inbox-check" not in src, (
        "Status card must never trigger a scan"
    )


def test_status_jsx_no_email_send():
    src = _STATUS_JSX.read_text(encoding="utf-8", errors="replace")
    assert "queue_email" not in src
    assert "send_queued_email" not in src


def test_status_jsx_displays_all_counts():
    src = _STATUS_JSX.read_text(encoding="utf-8", errors="replace")
    for field in ["batches_checked", "received_set", "b2_sent",
                  "skipped_inactive", "errors_count"]:
        assert field in src, f"Status card must display '{field}'"


def test_status_jsx_exports_component():
    src = _STATUS_JSX.read_text(encoding="utf-8", errors="replace")
    assert "window.DhlScanStatus" in src


# ══════════════════════════════════════════════════════════════════════════════
# D. PowerShell script writes timed_out
# ══════════════════════════════════════════════════════════════════════════════

def test_script_writes_timed_out_on_timeout():
    src = _SCRIPT.read_text(encoding="utf-8", errors="replace")
    assert "timed_out" in src, (
        "PS script must write 'timed_out' status when HTTP call times out"
    )
    assert "timed out" in src.lower() or "timeout" in src.lower()


# ══════════════════════════════════════════════════════════════════════════════
# E. Functional test — GET status returns correct shape from file
# ══════════════════════════════════════════════════════════════════════════════

def test_get_status_reads_file_and_returns_shape(tmp_path, monkeypatch):
    """GET auto-scan-status reads the status file and returns the expected shape."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key")

    # Write a success status file
    status_data = {
        "status":           "success",
        "started_at":       "2026-06-05T13:06:03+00:00",
        "completed_at":     "2026-06-05T13:09:27+00:00",
        "duration_seconds": 204.0,
        "batches_checked":  15,
        "received_set":     0,
        "b2_triggered":     0,
        "b2_sent":          0,
        "skipped_inactive": 10,
        "skipped_excluded": 1,
        "errors_count":     0,
        "last_error":       None,
    }
    (tmp_path / "dhl_auto_scan_status.json").write_text(
        json.dumps(status_data), encoding="utf-8"
    )

    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.get(
        "/api/v1/dhl/auto-scan-status",
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["batches_checked"] == 15
    assert body["errors_count"] == 0
    assert body["next_run_at"] is not None   # computed from started_at + 10 min


def test_get_status_returns_never_run_when_file_absent(tmp_path, monkeypatch):
    """Returns never_run when no status file exists."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key")

    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    resp = client.get(
        "/api/v1/dhl/auto-scan-status",
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "never_run"
