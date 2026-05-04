"""
test_dashboard_agency_sad_parse_status.py — Coverage for agency SAD parse status card.

Tests:
  1. UI: testid marker agency-sad-parse-status present in source
  2. UI: "Agency SAD parsed" label present
  3. UI: "SAD partially parsed" label present
  4. UI: "Waiting for file upload" label present
  5. UI: confidence testid present
  6. Backend: parsed status flows through batch_detail
  7. Backend: partial status flows through batch_detail
  8. Backend: awaiting_file status flows through batch_detail
  9. Backend: absent agency_sad_parse → field not injected
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

    batch_id = "TEST_SAD_PARSE_BATCH"
    batch_dir = tmp_path / "outputs" / batch_id
    batch_dir.mkdir(parents=True)

    base = {
        "batch_id":         batch_id,
        "tracking_no":      "9876543210",
        "awb":              "9876543210",
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

def test_ui_sad_parse_testid_present():
    """dashboard.html must contain the agency-sad-parse-status testid marker."""
    assert "agency-sad-parse-status" in _src(), (
        "data-testid='agency-sad-parse-status' missing from dashboard.html"
    )


def test_ui_sad_parse_status_parsed_label():
    """dashboard.html must contain the 'Agency SAD parsed' label."""
    assert "Agency SAD parsed" in _src(), (
        "'Agency SAD parsed' label missing from dashboard.html"
    )


def test_ui_sad_parse_status_partial_label():
    """dashboard.html must contain the 'SAD partially parsed' label."""
    assert "SAD partially parsed" in _src(), (
        "'SAD partially parsed' label missing from dashboard.html"
    )


def test_ui_sad_parse_awaiting_file_label():
    """dashboard.html must contain the 'Waiting for file upload' label."""
    assert "Waiting for file upload" in _src(), (
        "'Waiting for file upload' label missing from dashboard.html"
    )


def test_ui_sad_parse_confidence_testid():
    """dashboard.html must contain the agency-sad-parse-confidence testid."""
    assert "agency-sad-parse-confidence" in _src(), (
        "data-testid='agency-sad-parse-confidence' missing from dashboard.html"
    )


def test_ui_sad_parse_reads_from_audit_field():
    """Card must read from audit.agency_sad_parse (not a derived field)."""
    src = _src()
    idx = src.find("agency-sad-parse-status")
    assert idx != -1
    # The IIFE assigns sadParse within 1200 chars before the testid
    snippet = src[max(0, idx - 1200): idx + 200]
    assert "agency_sad_parse" in snippet, (
        "Card must read audit.agency_sad_parse near the agency-sad-parse-status testid"
    )


# ── Backend tests ─────────────────────────────────────────────────────────────

def test_backend_parsed_status_returned(tmp_path, monkeypatch):
    """batch_detail includes agency_sad_parse.status == 'parsed'."""
    client, batch_id = _make_client(tmp_path, monkeypatch, audit_extra={
        "agency_sad_parse": {
            "status":      "parsed",
            "confidence":  "high",
            "source":      "pdf",
            "parse_version": 1,
        },
    })
    r = client.get(f"/dashboard/batches/{batch_id}")
    assert r.status_code == 200
    body = r.json()
    sp = body.get("agency_sad_parse", {})
    assert sp.get("status") == "parsed", f"Expected parsed, got: {sp}"
    assert sp.get("confidence") == "high"


def test_backend_partial_status_returned(tmp_path, monkeypatch):
    """batch_detail returns agency_sad_parse.status == 'partial'."""
    client, batch_id = _make_client(tmp_path, monkeypatch, audit_extra={
        "agency_sad_parse": {
            "status":     "partial",
            "confidence": "medium",
            "source":     "pdf",
        },
    })
    r = client.get(f"/dashboard/batches/{batch_id}")
    assert r.status_code == 200
    sp = r.json().get("agency_sad_parse", {})
    assert sp.get("status") == "partial"
    assert sp.get("confidence") == "medium"


def test_backend_awaiting_file_status_returned(tmp_path, monkeypatch):
    """batch_detail returns agency_sad_parse.status == 'awaiting_file'."""
    client, batch_id = _make_client(tmp_path, monkeypatch, audit_extra={
        "agency_sad_parse": {
            "status": "awaiting_file",
            "reason": "file_bytes_not_on_disk",
        },
    })
    r = client.get(f"/dashboard/batches/{batch_id}")
    assert r.status_code == 200
    sp = r.json().get("agency_sad_parse", {})
    assert sp.get("status") == "awaiting_file"


def test_backend_no_field_when_absent(tmp_path, monkeypatch):
    """batch_detail with no agency_sad_parse in audit does not inject the field."""
    client, batch_id = _make_client(tmp_path, monkeypatch)
    r = client.get(f"/dashboard/batches/{batch_id}")
    assert r.status_code == 200
    sp = r.json().get("agency_sad_parse")
    assert not sp, f"agency_sad_parse should be absent when not in audit, got: {sp}"
