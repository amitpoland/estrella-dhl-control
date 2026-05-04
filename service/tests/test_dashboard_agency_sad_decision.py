"""
test_dashboard_agency_sad_decision.py — Coverage for agency SAD decision card.

Tests:
  1. UI: testid agency-sad-decision present in source
  2. UI: "Safe to run PZ" label present
  3. UI: "Not safe to run PZ" label present
  4. UI: reason testid present
  5. UI: evaluated-at testid present
  6. UI: reads from audit.agency_sad_decision
  7. Backend: safe decision flows through batch_detail
  8. Backend: blocked decision flows through batch_detail
  9. Backend: absent agency_sad_decision not injected
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

    batch_id = "TEST_SAD_DEC_BATCH"
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True)

    base = {
        "batch_id":         batch_id,
        "tracking_no":      "1234500000",
        "awb":              "1234500000",
        "status":           "success",
        "clearance_status": "agency_forwarded",
    }
    if audit_extra:
        base.update(audit_extra)
    (batch_dir / "audit.json").write_text(json.dumps(base), encoding="utf-8")

    app = FastAPI()
    app.include_router(rd.router)
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app, raise_server_exceptions=True), batch_id


# ── UI source-grep tests ──────────────────────────────────────────────────────

def test_ui_decision_testid_present():
    assert "agency-sad-decision" in _src(), (
        "data-testid='agency-sad-decision' missing from dashboard.html"
    )


def test_ui_safe_label_present():
    assert "Safe to run PZ" in _src(), (
        "'Safe to run PZ' label missing from dashboard.html"
    )


def test_ui_blocked_label_present():
    assert "Not safe to run PZ" in _src(), (
        "'Not safe to run PZ' label missing from dashboard.html"
    )


def test_ui_reason_testid_present():
    assert "agency-sad-decision-reason" in _src(), (
        "data-testid='agency-sad-decision-reason' missing from dashboard.html"
    )


def test_ui_evaluated_at_testid_present():
    assert "agency-sad-decision-evaluated-at" in _src(), (
        "data-testid='agency-sad-decision-evaluated-at' missing from dashboard.html"
    )


def test_ui_reads_from_audit_field():
    src = _src()
    idx = src.find("agency-sad-decision")
    assert idx != -1
    snippet = src[max(0, idx - 800): idx + 300]
    assert "agency_sad_decision" in snippet, (
        "Card must read audit.agency_sad_decision near the testid"
    )


# ── Backend tests ─────────────────────────────────────────────────────────────

def test_backend_safe_decision_returned(tmp_path, monkeypatch):
    client, batch_id = _make_client(tmp_path, monkeypatch, audit_extra={
        "agency_sad_decision": {
            "safe_to_run_pz": True,
            "reason":         "validated",
            "evaluated_at":   "2026-05-05T10:00:00+00:00",
        },
    })
    r = client.get(f"/dashboard/batches/{batch_id}")
    assert r.status_code == 200
    dec = r.json().get("agency_sad_decision", {})
    assert dec.get("safe_to_run_pz") is True
    assert dec.get("reason") == "validated"


def test_backend_blocked_decision_returned(tmp_path, monkeypatch):
    client, batch_id = _make_client(tmp_path, monkeypatch, audit_extra={
        "agency_sad_decision": {
            "safe_to_run_pz": False,
            "reason":         "mrn_mismatch",
            "evaluated_at":   "2026-05-05T10:00:00+00:00",
        },
    })
    r = client.get(f"/dashboard/batches/{batch_id}")
    assert r.status_code == 200
    dec = r.json().get("agency_sad_decision", {})
    assert dec.get("safe_to_run_pz") is False
    assert dec.get("reason") == "mrn_mismatch"


def test_backend_no_field_when_absent(tmp_path, monkeypatch):
    client, batch_id = _make_client(tmp_path, monkeypatch)
    r = client.get(f"/dashboard/batches/{batch_id}")
    assert r.status_code == 200
    assert not r.json().get("agency_sad_decision"), (
        "agency_sad_decision must not be injected when absent from audit"
    )


# ── MRN comparison UI tests ───────────────────────────────────────────────────

def _mrn_region() -> str:
    src = _src()
    idx = src.find("agency-sad-mrn-comparison")
    assert idx != -1, "agency-sad-mrn-comparison testid missing from dashboard.html"
    return src[max(0, idx - 200): idx + 1200]


def test_mrn_diff_visible_when_present():
    region = _mrn_region()
    assert "MRN Comparison" in region, "'MRN Comparison' label missing"
    assert "agency-sad-mrn-parsed" in region, "agency-sad-mrn-parsed testid missing"
    assert "agency-sad-mrn-declared" in region, "agency-sad-mrn-declared testid missing"
    assert "mrn_parsed" in region, "mrn_parsed field reference missing"
    assert "mrn_declared" in region, "mrn_declared field reference missing"
    assert "mrn_parsed && sadDecision.mrn_declared" in region, (
        "guard condition missing — block must only render when both fields present"
    )


def test_mrn_diff_highlight_on_mismatch():
    region = _mrn_region()
    assert "mrn_match === false" in region, (
        "mrn_match === false check missing — mismatch must trigger red highlight"
    )
    assert "badge-red-text" in region, (
        "badge-red-text color missing — mismatch values must be highlighted red"
    )


def test_mrn_diff_not_rendered_when_missing():
    region = _mrn_region()
    assert "mrn_match === true" in region, (
        "mrn_match === true check missing — match indicator must be conditional"
    )
    assert "agency-sad-mrn-match-ok" in region, (
        "agency-sad-mrn-match-ok testid missing — green tick must have testid"
    )
