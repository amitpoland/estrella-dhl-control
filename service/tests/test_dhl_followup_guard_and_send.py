"""test_dhl_followup_guard_and_send.py — PR-B regression suite.

Pins the 8 scenarios from the operator directive (2026-05-26) plus
additional Lesson E coverage.  All tests run pure in-memory — no SMTP
connection, no file I/O beyond a tmp audit, no real ingest.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _make_audit(**overrides: Any) -> Dict[str, Any]:
    """Audit dict for an active shipment past arrival, SLA armed, fresh ingest."""
    now = _now()
    base: Dict[str, Any] = {
        "batch_id":          "SHIPMENT_TEST_001",
        "awb":               "1234567890",
        "tracking_no":       "1234567890",
        "clearance_decision": {"clearance_path": "agency_clearance",
                               "agency_email":   "piotr@acspedycja.pl"},
        "clearance_status":  "",
        "tracking":          {"status": "in_customs"},
        "tracking_events":   [
            {"normalized_stage": "ARRIVED_DESTINATION_COUNTRY",
             "event_time":       _iso(now - timedelta(hours=8)),
             "location":         "WARSAW, POLAND"},
        ],
        "dhl_email":         {"received": False},
        "customs_docs":      {"received": False},
        "dhl_followup":      {
            "active":            True,
            "trigger_time":      _iso(now - timedelta(hours=8)),
            "trigger_reason":    "poland_customs_stage_detected",
            "first_followup_at": _iso(now - timedelta(hours=4)),
            "next_followup_at":  _iso(now - timedelta(minutes=30)),
            "followup_count":    0,
            "last_followup_at":  None,
        },
        "email_ingestion":   {"last_scan_at": _iso(now - timedelta(minutes=5))},
        # 2026-05-26 single-authority mode model: default is manual. Tests
        # that exercise the canonical guard's positive path must enroll
        # the shipment in automatic explicitly. Override per-test as needed.
        "followup":          {"mode": "automatic"},
    }
    base.update(overrides)
    return base


def _make_pkg(awb: str = "1234567890", **overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "from_address": "import@estrellajewels.eu",
        "email_type":   "dhl_followup",
        "to":           "odprawacelna@dhl.com",
        "to_list":      ["odprawacelna@dhl.com"],
        "cc":           "import@estrellajewels.eu, info@estrellajewels.eu",
        "cc_list":      ["import@estrellajewels.eu", "info@estrellajewels.eu"],
        "subject":      f"URGENT follow-up #1 - DSK required - AWB {awb}",
        "body_text":    f"Dear DHL team, AWB {awb} is overdue.",
        "body_html":    f"<p>Dear DHL team, AWB {awb} is overdue.</p>",
        "attachments":  [],
        "followup_seq": 1,
    }
    base.update(overrides)
    return base


# ── Guard unit tests — 8 operator scenarios ─────────────────────────────────


def test_S1_active_no_evidence_sla_elapsed_passes_guard():
    """Active shipment + SLA elapsed + no DHL email evidence → guard OK."""
    from app.services.dhl_followup_guard import validate_followup_send_preconditions
    audit = _make_audit()
    pkg = _make_pkg()
    res = validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert res.ok, f"expected ok, got reason={res.reason}"
    assert res.idempotency_key
    assert "SHIPMENT_TEST_001" in res.idempotency_key
    assert "dhl_followup" in res.idempotency_key
    assert res.primary_to == "odprawacelna@dhl.com"
    assert res.cc_count == 2
    assert res.attach_count == 0
    assert res.sla_age_min is not None and res.sla_age_min >= 470  # ~8h


def test_S2_flag_off_blocks_send():
    """DHL_ORCH_AUTO_SEND_DHL_FOLLOWUP=false → suppressed before any other check."""
    from app.services.dhl_followup_guard import validate_followup_send_preconditions
    audit = _make_audit()
    pkg = _make_pkg()
    res = validate_followup_send_preconditions(audit, pkg, flag_override=False)
    assert not res.ok
    assert res.reason == "auto_send_dhl_followup_flag_off"


def test_S3_delivered_shipment_suppressed():
    """Delivered shipment → not_active suppression."""
    from app.services.dhl_followup_guard import validate_followup_send_preconditions
    audit = _make_audit(clearance_status="delivered")
    pkg = _make_pkg()
    res = validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert not res.ok
    assert res.reason.startswith("not_active:")


def test_S3b_terminal_clearance_suppressed():
    """clearance_status=agency_email_sent (terminal) → suppressed."""
    from app.services.dhl_followup_guard import validate_followup_send_preconditions
    audit = _make_audit(clearance_status="agency_email_sent")
    pkg = _make_pkg()
    res = validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert not res.ok
    assert res.reason.startswith("not_active:")


def test_S4_unsafe_recipient_blocked():
    """Primary TO not in DHL allow-list → unsafe_recipient suppression."""
    from app.services.dhl_followup_guard import validate_followup_send_preconditions
    audit = _make_audit()
    pkg = _make_pkg(to="evil@attacker.com",
                    to_list=["evil@attacker.com"])
    res = validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert not res.ok
    assert res.reason.startswith("unsafe_recipient:")


def test_S4b_missing_awb_blocked():
    """Empty AWB → missing_awb suppression."""
    from app.services.dhl_followup_guard import validate_followup_send_preconditions
    audit = _make_audit(awb="", tracking_no="")
    pkg = _make_pkg()
    res = validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert not res.ok
    # is_active_shipment also keys off AWB, so it can fire first — either is a valid block
    assert "missing_awb" in res.reason


def test_S5_duplicate_idempotency_key_suppressed():
    """Idem key already in audit.dhl_followup.sent_idempotency_keys → blocked."""
    from app.services.dhl_followup_guard import (
        validate_followup_send_preconditions,
        build_followup_idempotency_key,
    )
    audit = _make_audit()
    pkg = _make_pkg()
    # Pre-seed sent keys with the one this slot would generate
    key = build_followup_idempotency_key(audit["batch_id"], audit)
    audit["dhl_followup"]["sent_idempotency_keys"] = [key]
    res = validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert not res.ok
    assert res.reason == "duplicate_idempotency_key"


def test_S6_stale_ingest_blocks_send():
    """last_scan_at older than INGEST_FRESHNESS_MAX_MIN → stale_ingest."""
    from app.services.dhl_followup_guard import (
        validate_followup_send_preconditions, INGEST_FRESHNESS_MAX_MIN,
    )
    old_scan = _now() - timedelta(minutes=INGEST_FRESHNESS_MAX_MIN + 60)
    audit = _make_audit(email_ingestion={"last_scan_at": _iso(old_scan)})
    pkg = _make_pkg()
    res = validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert not res.ok
    assert res.reason.startswith("stale_ingest:")


def test_S6b_ingest_never_run_blocks_send():
    """No email_ingestion record at all → ingest_never_run."""
    from app.services.dhl_followup_guard import validate_followup_send_preconditions
    audit = _make_audit(email_ingestion={})
    pkg = _make_pkg()
    res = validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert not res.ok
    assert res.reason == "ingest_never_run"


def test_S7_cooldown_via_duplicate_key_in_same_slot():
    """Tick 1 sends; tick 2 in same SLA slot would build same key → blocked.

    This is the cooldown semantic: same next_followup_at = same key.
    """
    from app.services.dhl_followup_guard import (
        validate_followup_send_preconditions,
        record_idempotency_key_into_audit,
    )
    audit = _make_audit()
    pkg = _make_pkg()
    r1 = validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert r1.ok
    record_idempotency_key_into_audit(audit, r1.idempotency_key)
    r2 = validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert not r2.ok
    assert r2.reason == "duplicate_idempotency_key"


def test_S8_empty_package_subject_blocked():
    """Builder produced empty subject → empty_subject."""
    from app.services.dhl_followup_guard import validate_followup_send_preconditions
    audit = _make_audit()
    pkg = _make_pkg(subject="")
    res = validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert not res.ok
    assert res.reason == "empty_subject"


def test_S8b_empty_body_blocked():
    from app.services.dhl_followup_guard import validate_followup_send_preconditions
    audit = _make_audit()
    pkg = _make_pkg(body_text="", body_html="")
    res = validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert not res.ok
    assert res.reason == "empty_body"


def test_S8c_subject_without_awb_blocked():
    """AWB sanity check: subject must reference the AWB."""
    from app.services.dhl_followup_guard import validate_followup_send_preconditions
    audit = _make_audit()
    pkg = _make_pkg(subject="URGENT - documents required")
    res = validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert not res.ok
    assert res.reason == "awb_missing_from_subject"


def test_S8d_missing_attachment_file_blocked():
    """Attachment path that doesn't exist → attachment_missing."""
    from app.services.dhl_followup_guard import validate_followup_send_preconditions
    audit = _make_audit()
    pkg = _make_pkg(attachments=[{"label": "AWB", "path": "/nonexistent/awb.pdf"}])
    res = validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert not res.ok
    assert res.reason.startswith("attachment_missing:")


def test_S9_dhl_email_received_makes_inactive():
    """dhl_email.received=True makes shipment inactive via clearance_terminal?
    Actually is_active_shipment only checks clearance_status terminal — but
    upstream _process_dhl_followup stops the SLA before guard runs.  Guard
    itself does NOT need to know about dhl_email.received."""
    from app.services.dhl_followup_guard import validate_followup_send_preconditions
    audit = _make_audit()
    audit["dhl_email"]["received"] = True
    pkg = _make_pkg()
    # Guard remains ok — caller (_process_dhl_followup) handles this earlier.
    res = validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert res.ok  # guard delegates dhl_email check upstream


# ── Idempotency key construction ────────────────────────────────────────────


def test_idempotency_key_deterministic_per_slot():
    """Same next_followup_at + same batch_id → same key."""
    from app.services.dhl_followup_guard import build_followup_idempotency_key
    audit = _make_audit()
    k1 = build_followup_idempotency_key(audit["batch_id"], audit)
    k2 = build_followup_idempotency_key(audit["batch_id"], audit)
    assert k1 == k2
    assert k1 != ""


def test_idempotency_key_changes_when_slot_advances():
    """Different next_followup_at → different key."""
    from app.services.dhl_followup_guard import build_followup_idempotency_key
    audit = _make_audit()
    k1 = build_followup_idempotency_key(audit["batch_id"], audit)
    audit["dhl_followup"]["next_followup_at"] = _iso(_now() + timedelta(hours=1))
    k2 = build_followup_idempotency_key(audit["batch_id"], audit)
    assert k1 != k2


def test_idempotency_key_empty_when_state_incomplete():
    from app.services.dhl_followup_guard import build_followup_idempotency_key
    assert build_followup_idempotency_key("", {}) == ""
    assert build_followup_idempotency_key("BID", {"dhl_followup": {}}) == ""


def test_record_idempotency_key_cap():
    """Bounded list — most recent N retained."""
    from app.services.dhl_followup_guard import record_idempotency_key_into_audit
    audit: Dict[str, Any] = {}
    for i in range(150):
        record_idempotency_key_into_audit(audit, f"k{i}", cap=100)
    keys = audit["dhl_followup"]["sent_idempotency_keys"]
    assert len(keys) == 100
    assert keys[0] == "k50"
    assert keys[-1] == "k149"


# ── Settings flag wiring (Lesson E §5 + §1) ─────────────────────────────────


def test_flag_off_via_settings_blocks(monkeypatch):
    """When flag_override is None, real settings.dhl_orch_auto_send_dhl_followup gates."""
    from app.services.dhl_followup_guard import validate_followup_send_preconditions
    from app.core import config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings, "dhl_orch_auto_send_dhl_followup", False, raising=False)
    audit = _make_audit()
    pkg = _make_pkg()
    res = validate_followup_send_preconditions(audit, pkg)
    assert not res.ok
    assert res.reason == "auto_send_dhl_followup_flag_off"


def test_flag_on_via_settings_passes(monkeypatch):
    from app.services.dhl_followup_guard import validate_followup_send_preconditions
    from app.core import config as cfg_mod
    monkeypatch.setattr(cfg_mod.settings, "dhl_orch_auto_send_dhl_followup", True, raising=False)
    audit = _make_audit()
    pkg = _make_pkg()
    res = validate_followup_send_preconditions(audit, pkg)
    assert res.ok


# ── No-write contract (Lesson K negative scope) ─────────────────────────────


def test_guard_does_not_mutate_audit():
    """Guard is a pure function — no audit mutation."""
    from app.services.dhl_followup_guard import validate_followup_send_preconditions
    import copy
    audit = _make_audit()
    snapshot = copy.deepcopy(audit)
    pkg = _make_pkg()
    validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert audit == snapshot, "guard mutated the audit dict"


def test_guard_does_not_mutate_pkg():
    from app.services.dhl_followup_guard import validate_followup_send_preconditions
    import copy
    audit = _make_audit()
    pkg = _make_pkg()
    snapshot = copy.deepcopy(pkg)
    validate_followup_send_preconditions(audit, pkg, flag_override=True)
    assert pkg == snapshot, "guard mutated the pkg dict"
