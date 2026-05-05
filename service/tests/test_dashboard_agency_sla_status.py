"""
test_dashboard_agency_sla_status.py — Coverage for agency SLA status display.

Tests:
  1. Backend: batch_detail includes agency_sla fields from audit
  2. Backend: agency_sla absent from audit → field not present or empty in response
  3. UI: dashboard.html contains agency-sla-status testid marker
  4. UI: "SLA active" label present in source
  5. UI: "SLA completed" label present in source
  6. UI: SLA card reads from audit.agency_sla (not derived)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

DASHBOARD_HTML = Path(
    "/Users/amitgupta/Downloads/CLI/service/app/static/dashboard.html"
)


def _src() -> str:
    return DASHBOARD_HTML.read_text(encoding="utf-8")


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_client(tmp_path: Path, monkeypatch, audit_extra: dict | None = None):
    from app.api import routes_dashboard as rd
    from app.core.security import require_api_key

    monkeypatch.setattr(rd, "_OUTPUTS", tmp_path / "outputs", raising=False)

    batch_id = "TEST_SLA_BATCH"
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True)

    base = {
        "batch_id":      batch_id,
        "tracking_no":   "9876543210",
        "awb":           "9876543210",
        "status":        "success",
        "clearance_status": "agency_forwarded",
    }
    if audit_extra:
        base.update(audit_extra)
    (batch_dir / "audit.json").write_text(json.dumps(base), encoding="utf-8")

    app = FastAPI()
    app.include_router(rd.router)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app, raise_server_exceptions=True), batch_id


# ── Backend tests ─────────────────────────────────────────────────────────────

def test_dashboard_shows_sla_active(tmp_path, monkeypatch):
    """batch_detail returns agency_sla.started=True, stopped absent/False."""
    client, batch_id = _make_client(tmp_path, monkeypatch, audit_extra={
        "agency_sla": {
            "started":    True,
            "started_at": "2026-05-01T10:00:00+00:00",
        },
    })
    r = client.get(f"/dashboard/batches/{batch_id}")
    assert r.status_code == 200
    body = r.json()
    sla = body.get("agency_sla", {})
    assert sla.get("started") is True, f"agency_sla.started expected True, got: {sla}"
    assert not sla.get("stopped"), f"agency_sla.stopped must be falsy for active SLA, got: {sla}"
    assert sla.get("started_at") == "2026-05-01T10:00:00+00:00"


def test_dashboard_shows_sla_completed(tmp_path, monkeypatch):
    """batch_detail returns agency_sla.stopped=True with stopped_at timestamp."""
    client, batch_id = _make_client(tmp_path, monkeypatch, audit_extra={
        "agency_sla": {
            "started":    True,
            "started_at": "2026-05-01T10:00:00+00:00",
            "stopped":    True,
            "stopped_at": "2026-05-02T14:30:00+00:00",
        },
    })
    r = client.get(f"/dashboard/batches/{batch_id}")
    assert r.status_code == 200
    body = r.json()
    sla = body.get("agency_sla", {})
    assert sla.get("started") is True
    assert sla.get("stopped") is True, f"agency_sla.stopped expected True, got: {sla}"
    assert sla.get("stopped_at") == "2026-05-02T14:30:00+00:00"


def test_dashboard_no_sla_field_when_absent(tmp_path, monkeypatch):
    """batch_detail with no agency_sla in audit does not inject a spurious field."""
    client, batch_id = _make_client(tmp_path, monkeypatch)
    r = client.get(f"/dashboard/batches/{batch_id}")
    assert r.status_code == 200
    body = r.json()
    sla = body.get("agency_sla")
    assert not sla, f"agency_sla should be absent or empty when not in audit, got: {sla}"


# ── UI source-grep tests ──────────────────────────────────────────────────────

def test_ui_sla_status_testid_present():
    """dashboard.html must contain the agency-sla-status testid marker."""
    assert "agency-sla-status" in _src(), (
        "data-testid='agency-sla-status' missing from dashboard.html"
    )


def test_ui_sla_active_label_present():
    """dashboard.html must contain the 'SLA active' label text."""
    assert "Agency SLA active" in _src(), (
        "'Agency SLA active' label missing from dashboard.html"
    )


def test_ui_sla_completed_label_present():
    """dashboard.html must contain the 'SLA completed' label text."""
    assert "Agency SLA completed" in _src(), (
        "'Agency SLA completed' label missing from dashboard.html"
    )


def test_ui_sla_reads_from_audit_agency_sla():
    """SLA card IIFE must read from audit.agency_sla (const sla = audit.agency_sla)."""
    src = _src()
    idx = src.find("agency-sla-status")
    assert idx != -1
    # The assignment const sla = audit.agency_sla is in the IIFE just before the card JSX;
    # search a wider window that covers the opening of the IIFE.
    snippet = src[max(0, idx - 800): idx + 500]
    assert "audit.agency_sla" in snippet, (
        "SLA card must read from audit.agency_sla. "
        "Check that 'const sla = audit.agency_sla' is within the enclosing IIFE."
    )


# ── Trigger label tests ───────────────────────────────────────────────────────

def test_sla_card_shows_start_trigger():
    """SLA card must show the start trigger label 'Agency forward sent'."""
    src = _src()
    idx = src.find("agency-sla-status")
    assert idx != -1
    snippet = src[idx: idx + 2000]
    assert "agency-sla-start-trigger" in snippet, (
        "data-testid='agency-sla-start-trigger' missing from SLA card"
    )
    assert "Agency forward sent" in snippet, (
        "'Agency forward sent' trigger label missing from SLA card"
    )


def test_sla_card_shows_stop_trigger():
    """SLA card must show the stop trigger label 'SAD received' when stopped."""
    src = _src()
    idx = src.find("agency-sla-status")
    assert idx != -1
    snippet = src[idx: idx + 2000]
    assert "agency-sla-stop-trigger" in snippet, (
        "data-testid='agency-sla-stop-trigger' missing from SLA card"
    )
    assert "SAD received" in snippet, (
        "'SAD received' stop trigger label missing from SLA card"
    )
