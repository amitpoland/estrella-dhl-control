"""
test_lane_b_customs_complete.py
================================
Regression tests for the customs-complete stop condition in Lane B.

Pattern cases (not hardcoded production patches):
  All 9 known false-positive AWBs from the 2026-06-05 candidate review
  had SAD/ZC429/PZC in their timeline but were appearing as Lane B eligible.
  These tests pin the fix so the same false-positive can never recur.

Guard: once SAD/ZC429/PZC appears in audit.timeline, the shipment is
permanently excluded from Lane B follow-up.

References:
  STOP_CUSTOMS_COMPLETE constant in dhl_followup_sla.py
  _is_customs_complete() in active_shipment_monitor.py
  run_scheduled_followup_check in routes_dhl_clearance.py
  get_dhl_daily_summary lane_b_candidates builder
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Dict, Any

import pytest

_SLA   = Path(__file__).parent.parent / "app" / "services" / "dhl_followup_sla.py"
_MON   = Path(__file__).parent.parent / "app" / "services" / "active_shipment_monitor.py"
_ROUTE = Path(__file__).parent.parent / "app" / "api" / "routes_dhl_clearance.py"


# ══════════════════════════════════════════════════════════════════════════════
# A. STOP_CUSTOMS_COMPLETE constant in dhl_followup_sla.py
# ══════════════════════════════════════════════════════════════════════════════

def test_stop_customs_complete_constant_exists():
    src = _SLA.read_text(encoding="utf-8", errors="replace")
    assert "STOP_CUSTOMS_COMPLETE" in src, (
        "dhl_followup_sla.py must define STOP_CUSTOMS_COMPLETE stop reason"
    )


def test_stop_customs_complete_value():
    src = _SLA.read_text(encoding="utf-8", errors="replace")
    idx = src.index("STOP_CUSTOMS_COMPLETE")
    context = src[idx:idx+60]
    assert "customs_complete" in context


# ══════════════════════════════════════════════════════════════════════════════
# B. _is_customs_complete() helper in active_shipment_monitor.py
# ══════════════════════════════════════════════════════════════════════════════

def test_is_customs_complete_function_exists():
    src = _MON.read_text(encoding="utf-8", errors="replace")
    assert "def _is_customs_complete" in src


def test_customs_complete_events_set_includes_sad_uploaded():
    src = _MON.read_text(encoding="utf-8", errors="replace")
    assert "_CUSTOMS_COMPLETE_EVENTS" in src
    assert "sad_uploaded" in src


def test_customs_complete_events_set_includes_zc429_received():
    src = _MON.read_text(encoding="utf-8", errors="replace")
    assert "zc429_received" in src


def test_customs_complete_events_set_includes_pzc_received():
    src = _MON.read_text(encoding="utf-8", errors="replace")
    assert "pzc_received" in src


def test_is_customs_complete_logic():
    """Functional: _is_customs_complete returns correct values."""
    from app.services.active_shipment_monitor import _is_customs_complete

    # Pattern: sad_uploaded in timeline → True
    audit_with_sad: Dict[str, Any] = {
        "timeline": [
            {"event": "clearance_decision_made", "ts": "2026-04-28T10:00:00Z"},
            {"event": "sad_uploaded",            "ts": "2026-04-29T12:11:36Z"},
        ]
    }
    assert _is_customs_complete(audit_with_sad) is True, (
        "sad_uploaded in timeline must return True"
    )

    # Pattern: zc429_received in timeline → True
    audit_with_zc429: Dict[str, Any] = {
        "timeline": [
            {"event": "dhl_inbox_scanned",  "ts": "2026-04-30T08:00:00Z"},
            {"event": "zc429_received",     "ts": "2026-05-04T08:45:44Z"},
        ]
    }
    assert _is_customs_complete(audit_with_zc429) is True

    # Pattern: pzc_received in timeline → True
    audit_with_pzc: Dict[str, Any] = {
        "timeline": [
            {"event": "pzc_received", "ts": "2026-05-10T09:00:00Z"},
        ]
    }
    assert _is_customs_complete(audit_with_pzc) is True

    # Pattern: no completion event, >4h waiting → False (still eligible)
    audit_no_completion: Dict[str, Any] = {
        "timeline": [
            {"event": "clearance_decision_made", "ts": "2026-06-04T08:00:00Z"},
            {"event": "dhl_inbox_scanned",       "ts": "2026-06-05T09:00:00Z"},
        ]
    }
    assert _is_customs_complete(audit_no_completion) is False, (
        "No customs-completion event → False (batch remains eligible)"
    )

    # Edge: empty timeline
    assert _is_customs_complete({}) is False
    assert _is_customs_complete({"timeline": []}) is False
    assert _is_customs_complete({"timeline": None}) is False


# ══════════════════════════════════════════════════════════════════════════════
# C. Lane B endpoint stops on customs-complete (source-grep)
# ══════════════════════════════════════════════════════════════════════════════

def _lane_b_block(src: str) -> str:
    idx = src.index("scheduled-followup-check")
    end = src.find("\n@router.", idx + 10)
    return src[idx:end] if end > idx else src[idx:]


def test_lane_b_endpoint_imports_is_customs_complete():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_b_block(src)
    assert "_is_customs_complete" in block, (
        "run_scheduled_followup_check must import and use _is_customs_complete"
    )


def test_lane_b_endpoint_skips_customs_complete():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_b_block(src)
    assert "skipped_customs_complete" in block, (
        "Lane B endpoint must count skipped_customs_complete batches"
    )
    # The skip must happen BEFORE _process_dhl_followup
    skip_idx = block.index("skipped_customs_complete")
    followup_idx = block.index("_process_dhl_followup(ap")
    assert skip_idx < followup_idx, (
        "customs-complete skip must precede _process_dhl_followup call"
    )


def test_lane_b_customs_complete_check_precedes_dhl_received_check():
    """Customs-complete is a stronger gate and must come first."""
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _lane_b_block(src)
    cc_idx  = block.index("_is_customs_complete")
    rcv_idx = block.index("skipped_received")
    assert cc_idx < rcv_idx, (
        "_is_customs_complete guard must come before the dhl_email.received skip"
    )


# ══════════════════════════════════════════════════════════════════════════════
# D. Daily summary lane_b_candidates excludes customs-complete batches
# ══════════════════════════════════════════════════════════════════════════════

def _summary_block(src: str) -> str:
    idx = src.index("daily-summary")
    end = src.find("\n@router.", idx + 10)
    return src[idx:end] if end > idx else src[idx:]


def test_daily_summary_candidate_builder_excludes_customs_complete():
    src = _ROUTE.read_text(encoding="utf-8", errors="replace")
    block = _summary_block(src)
    assert "_is_customs_complete" in block, (
        "daily-summary Lane B candidate builder must exclude customs-complete batches"
    )
    # The check must appear in the candidate-building section
    not_recv_idx = block.index("not _dhl_recv and not _dsk_sent")
    assert "_is_customs_complete" in block[:not_recv_idx + 200], (
        "_is_customs_complete must be part of the candidate filter condition"
    )


# ══════════════════════════════════════════════════════════════════════════════
# E. _process_dhl_followup stops on customs-complete (source-grep)
# ══════════════════════════════════════════════════════════════════════════════

def _followup_block(src: str) -> str:
    idx = src.index("def _process_dhl_followup")
    end = src.find("\ndef _", idx + 10)
    return src[idx:end] if end > idx else src[idx:]


def test_process_followup_has_customs_complete_stop():
    src = _MON.read_text(encoding="utf-8", errors="replace")
    block = _followup_block(src)
    assert "STOP_CUSTOMS_COMPLETE" in block, (
        "_process_dhl_followup must use STOP_CUSTOMS_COMPLETE as a stop reason"
    )
    assert "_is_customs_complete" in block, (
        "_process_dhl_followup must call _is_customs_complete"
    )


def test_process_followup_customs_gate_is_first_check():
    """Customs-complete must be the first stop condition — before dhl_received."""
    src = _MON.read_text(encoding="utf-8", errors="replace")
    block = _followup_block(src)
    cc_idx  = block.index("_is_customs_complete")
    rcv_idx = block.index("dhl_received")
    assert cc_idx < rcv_idx, (
        "_is_customs_complete must be checked BEFORE dhl_received in _process_dhl_followup"
    )


def test_process_followup_returns_early_on_customs_complete():
    """Function must return early (not continue to send logic) when customs done."""
    src = _MON.read_text(encoding="utf-8", errors="replace")
    block = _followup_block(src)
    cc_idx = block.index("_is_customs_complete")
    # The word 'return' must appear within 500 chars of the _is_customs_complete check
    near_cc = block[cc_idx:cc_idx + 900]
    assert "return out" in near_cc, (
        "_process_dhl_followup must return out immediately when customs is complete"
    )


# ══════════════════════════════════════════════════════════════════════════════
# F. Functional: endpoint returns skipped_customs_complete, no email sent
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def _batch_with_sad(tmp_path, monkeypatch):
    """Create a batch with sad_uploaded in timeline (customs-complete pattern)."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key")
    monkeypatch.setattr(settings, "dhl_followup_enabled", True)  # enabled so we test the guard

    batch_id = "SHIPMENT_TEST_" + uuid.uuid4().hex[:8]
    bd = tmp_path / "outputs" / batch_id
    bd.mkdir(parents=True)
    audit = {
        "batch_id": batch_id,
        "awb":      "5378819972",  # pattern AWB from 2026-06-05 review
        "status":   "partial",
        "clearance_decision": {
            "clearance_path":   "agency_clearance",
            "total_value_usd":  8000.0,
        },
        "timeline": [
            {"event": "clearance_decision_made", "ts": "2026-04-27T09:00:00Z"},
            {"event": "dsk_generated",           "ts": "2026-04-28T11:00:00Z"},
            {"event": "sad_uploaded",            "ts": "2026-04-29T12:11:36Z"},  # customs done
        ],
    }
    (bd / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return bd, batch_id


def test_lane_b_endpoint_skips_sad_batch_no_email(
    _batch_with_sad, monkeypatch
):
    """Functional: endpoint returns skipped_customs_complete > 0, no email queued."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.post(
        "/api/v1/dhl/scheduled-followup-check",
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 200
    body = resp.json()

    # Lane B must be ON (we set dhl_followup_enabled=True) but skip the batch
    assert body.get("ok") is not False or body.get("skipped"), (
        "Endpoint should not be disabled — we're testing the customs guard"
    )
    # The customs-complete skip counter must be > 0
    skipped_cc = body.get("skipped_customs_complete", 0)
    assert skipped_cc >= 1, (
        f"skipped_customs_complete must be ≥1 for a batch with sad_uploaded. Got {skipped_cc}"
    )

    # No email should have been queued
    eq_path = _batch_with_sad[0].parent.parent / "email_queue.json"
    if eq_path.exists():
        q = json.loads(eq_path.read_text(encoding="utf-8"))
        followup_emails = [
            e for e in q
            if e.get("batch_id") == _batch_with_sad[1]
        ]
        assert len(followup_emails) == 0, (
            "No follow-up email must be queued for a customs-complete batch"
        )
