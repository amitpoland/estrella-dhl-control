"""
test_lifecycle_agency_followup.py

Tests for POST /api/v1/lifecycle/agency-followup.

Coverage
--------
1. invalid batch_id (empty) → 400
2. invalid batch_id (dotdot traversal) → 400
3. invalid batch_id (slash) → 400
4. audit not found → 404
5. audit.status == "completed" → 409
6. agency_cn_followup.queued_at already set → 200 skipped
7. successful queue → 200 ok, audit written with agency_cn_followup block
8. reason appended as plain text; HTML-special chars escaped in body_html
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_SERVICE = Path(__file__).resolve().parents[1]
if str(_SERVICE) not in sys.path:
    sys.path.insert(0, str(_SERVICE))


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_storage(tmp_path):
    return tmp_path


@pytest.fixture()
def client(tmp_storage):
    from app.core.config import settings
    from app.main import app
    with patch.object(settings, "storage_root", tmp_storage):
        yield TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_audit(storage: Path, batch_id: str, data: dict) -> Path:
    d = storage / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / "audit.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _post(client, batch_id: str, reason: str = "test reason"):
    return client.post(
        "/api/v1/lifecycle/agency-followup",
        json={"batch_id": batch_id, "reason": reason},
    )


# ── Batch ID validation ────────────────────────────────────────────────────────

def test_invalid_batch_id_empty(client):
    r = client.post(
        "/api/v1/lifecycle/agency-followup",
        json={"batch_id": "", "reason": "x"},
    )
    assert r.status_code == 400
    assert "batch_id" in r.text.lower() or "empty" in r.text.lower()


def test_invalid_batch_id_dotdot(client):
    r = _post(client, "../etc/passwd")
    assert r.status_code == 400


def test_invalid_batch_id_slash(client):
    r = _post(client, "some/path")
    assert r.status_code == 400


# ── Audit guards ──────────────────────────────────────────────────────────────

def test_audit_missing_returns_404(client):
    r = _post(client, "BATCH_NO_AUDIT_1")
    assert r.status_code == 404


def test_completed_audit_returns_409(client, tmp_storage):
    _write_audit(tmp_storage, "BATCH_DONE_1", {"status": "completed", "awb": "9999"})
    r = _post(client, "BATCH_DONE_1")
    assert r.status_code == 409


def test_already_queued_returns_skipped(client, tmp_storage):
    _write_audit(tmp_storage, "BATCH_SKIP_1", {
        "awb": "1234567890",
        "agency_cn_followup": {
            "queued_at": "2026-01-01T00:00:00+00:00",
            "email_id":  "old-email-id",
            "reason":    "prior reason",
            "to":        "piotr@acspedycja.pl",
        },
    })
    r = _post(client, "BATCH_SKIP_1")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["status"] == "skipped"
    assert data["reason"] == "already_queued"


# ── Successful queue ──────────────────────────────────────────────────────────

def test_successful_queue_writes_audit(client, tmp_storage):
    audit_path = _write_audit(tmp_storage, "BATCH_OK_1", {
        "awb": "1012345678",
        "status": "open",
    })

    with patch("app.services.email_service.queue_email", return_value="test-email-id-001") as mock_q:
        r = _post(client, "BATCH_OK_1", reason="CN mismatch: SAD 7113, invoice 7114")

    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["queued"] is True
    assert data["email_id"] == "test-email-id-001"
    assert data["batch_id"] == "BATCH_OK_1"
    assert mock_q.called

    # audit must have been updated
    updated = json.loads(audit_path.read_text())
    cf = updated.get("agency_cn_followup") or {}
    assert cf.get("queued_at"), "queued_at must be written"
    assert cf.get("email_id") == "test-email-id-001"
    assert cf.get("reason") == "CN mismatch: SAD 7113, invoice 7114"
    assert cf.get("to"), "to must be written"


def test_audit_not_written_on_queue_failure(client, tmp_storage):
    audit_path = _write_audit(tmp_storage, "BATCH_QFAIL_1", {
        "awb": "1012345678",
        "status": "open",
    })

    with patch("app.services.email_service.queue_email", side_effect=ValueError("smtp down")):
        r = _post(client, "BATCH_QFAIL_1")

    assert r.status_code == 502
    updated = json.loads(audit_path.read_text())
    assert not updated.get("agency_cn_followup"), "agency_cn_followup must NOT be written on queue failure"


# ── Reason safety ─────────────────────────────────────────────────────────────

def test_reason_html_escaped_in_body_html(client, tmp_storage):
    """<script> in reason must appear as &lt;script&gt; in body_html, not raw."""
    _write_audit(tmp_storage, "BATCH_XSS_1", {"awb": "9876543210", "status": "open"})

    captured = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return "xss-test-email-id"

    with patch("app.services.email_service.queue_email", side_effect=_capture):
        r = _post(client, "BATCH_XSS_1", reason="<script>alert(1)</script>")

    assert r.status_code == 200
    assert "<script>" not in captured.get("body_html", ""), \
        "raw <script> must not appear in body_html"
    assert "&lt;script&gt;" in captured.get("body_html", ""), \
        "escaped &lt;script&gt; must appear in body_html"
    # plain text body carries it as-is (it's a text field, not rendered as HTML)
    assert "<script>alert(1)</script>" in captured.get("body_text", ""), \
        "plain reason must appear as-is in body_text"


def test_reason_appended_to_body_text(client, tmp_storage):
    _write_audit(tmp_storage, "BATCH_REASON_1", {"awb": "1111111111", "status": "open"})

    captured = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return "reason-test-id"

    with patch("app.services.email_service.queue_email", side_effect=_capture):
        r = _post(client, "BATCH_REASON_1", reason="CN mismatch: 7113 vs 7114")

    assert r.status_code == 200
    assert "CN mismatch: 7113 vs 7114" in captured.get("body_text", "")
