"""
test_dhl_followup_send_now.py

Tests for the customs_docs_received milestone guard on
POST /api/v1/dhl-followup/{batch_id}/send-now.

Coverage:
  1. 409 when customs_docs.received is True (SAD already uploaded)
  2. 422 when dhl_followup is not active (existing guard, sanity check)
  3. 200 / pass-through when customs_docs.received is False and SLA is active
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
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

def _active_followup_state():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "active": True,
        "trigger_reason": "customs_trigger",
        "trigger_time": now,
        "first_followup_at": now,
        "next_followup_at": now,
        "followup_count": 1,
        "last_followup_at": None,
        "stopped_at": None,
        "stop_reason": None,
    }


def _write_audit(storage: Path, batch_id: str, data: dict) -> Path:
    d = storage / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / "audit.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _send_now(client, batch_id: str):
    return client.post(
        f"/api/v1/dhl-followup/{batch_id}/send-now",
        json={"approved_by": "test_operator"},
    )


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_send_now_blocked_when_customs_docs_received(client, tmp_storage):
    """SAD already uploaded → 409 with customs_docs_received guard."""
    _write_audit(tmp_storage, "B_SN_SAD", {
        "batch_id":      "B_SN_SAD",
        "awb":           "1111111111",
        "dhl_followup":  _active_followup_state(),
        "customs_docs":  {"received": True, "received_at": datetime.now(timezone.utc).isoformat()},
    })
    r = _send_now(client, "B_SN_SAD")
    assert r.status_code == 409
    body = r.json()
    assert body.get("detail", {}).get("guard") == "customs_docs_received"


def test_send_now_blocked_when_followup_not_active(client, tmp_storage):
    """Existing guard: 422 when SLA is not active."""
    _write_audit(tmp_storage, "B_SN_INACTIVE", {
        "batch_id":     "B_SN_INACTIVE",
        "awb":          "2222222222",
        "dhl_followup": {"active": False},
    })
    r = _send_now(client, "B_SN_INACTIVE")
    assert r.status_code == 422


def test_send_now_proceeds_when_customs_docs_not_received(client, tmp_storage):
    """No customs docs yet → guard does not block (proceeds to email build)."""
    _write_audit(tmp_storage, "B_SN_OK", {
        "batch_id":     "B_SN_OK",
        "awb":          "3333333333",
        "dhl_followup": _active_followup_state(),
        # customs_docs absent → field not received
    })
    with (
        patch("app.services.dhl_followup_email_builder.build_dhl_followup_email",
              return_value={"to": "odprawacelna@dhl.com", "subject": "Follow-up",
                            "body_html": "<p>test</p>", "body_text": "test",
                            "email_type": "dhl_followup"}),
        patch("app.services.email_service.queue_email", return_value="email-id-ok"),
        patch("app.services.email_sender._smtp_configured", return_value=False),
    ):
        r = _send_now(client, "B_SN_OK")
    # SMTP not configured → returns queued=True, not 409/422
    assert r.status_code == 200
    assert r.json().get("queued") is True
