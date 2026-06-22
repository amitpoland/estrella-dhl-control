"""test_dhl_dsk_chase_sla.py — Post-DSK-reply DHL DSK/cesja chase scheduler (Phase B5).

Pure unit tests for the new SLA authority. No network, no SMTP, no file I/O.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services.dhl_followup_sla import POLAND_TZ, WORK_START  # noqa: E402
from app.services.dhl_dsk_chase_sla import (   # noqa: E402
    STATE_KEY,
    STOP_DSK_DOCS_RECEIVED,
    dsk_reply_sent_at, dsk_docs_received, agency_forward_sent, is_terminal,
    dhl_replied_after_dsk_reply,
    should_start_dsk_chase, start_dsk_chase, record_dsk_chase_sent,
    stop_dsk_chase, is_due,
)


def _pl(year=2026, month=4, day=29, hour=8, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=POLAND_TZ)


def _reply_audit(sent_at_iso, status="sent", **extra):
    """Audit with a CONFIRMED-sent DSK reply by default (status='sent' + sent_at).

    Pass status='queued' to model the not-yet-confirmed / send-failed state.
    """
    a = {
        "batch_id":          "SHIPMENT_T_001",
        "awb":               "9158478722",
        "tracking_no":       "9158478722",
        "clearance_decision": {"clearance_path": "agency_clearance",
                               "total_value_usd": 24235},
        "clearance_status":  "",
        "tracking":          {"status": "in_customs"},
        "dhl_email":         {"received": True, "ticket": "T#1WA2606220000005"},
        "dhl_reply_package": {"email_id": "q1", "status": status,
                              "queued_at": sent_at_iso,
                              "sent_at":   sent_at_iso if status == "sent" else None,
                              "ticket": "T#1WA2606220000005"},
    }
    a.update(extra)
    return a


# ── Trigger resolution: CONFIRMED-sent only (Q2) ─────────────────────────────

def test_trigger_confirmed_sent_via_status():
    out = dsk_reply_sent_at(_reply_audit(_pl(hour=9).isoformat()))   # status='sent'
    assert out is not None and out.hour == 9


def test_trigger_none_when_only_queued():
    """Q2: bare status='queued' (also the send-FAILED state) must NOT trigger."""
    a = _reply_audit(_pl(hour=9).isoformat(), status="queued")
    assert dsk_reply_sent_at(a) is None


def test_trigger_confirmed_via_verified_timeline_even_if_status_not_sent():
    """Q2: a dhl_reply_sent_verified timeline event confirms send even when the
    audit package status was never flipped to 'sent'."""
    a = _reply_audit(_pl(hour=9).isoformat(), status="queued")
    a["timeline"] = [{"event": "dhl_reply_sent_verified", "ts": _pl(hour=10).isoformat()}]
    out = dsk_reply_sent_at(a)
    assert out is not None and out.hour == 10


def test_trigger_none_when_only_build_started():
    """Crash-mid-build pre-marker (build_started_at only) does NOT count."""
    a = {"dhl_reply_package": {"build_started_at": _pl().isoformat()}}
    assert dsk_reply_sent_at(a) is None


def test_trigger_prefers_verified_timeline_over_sent_at():
    a = _reply_audit(_pl(hour=9).isoformat())   # sent_at = 09:00
    a["timeline"] = [{"event": "dhl_reply_sent_verified", "ts": _pl(hour=10).isoformat()}]
    assert dsk_reply_sent_at(a).hour == 10


# ── should_start ─────────────────────────────────────────────────────────────

def test_should_start_when_reply_sent_no_docs():
    out = should_start_dsk_chase(_reply_audit(_pl(hour=9).isoformat()))
    assert out and out["reason"] == "dsk_reply_sent_awaiting_dhl_docs"


def test_should_not_start_non_agency_path():
    a = _reply_audit(_pl(hour=9).isoformat(),
                     clearance_decision={"clearance_path": "carrier_self_clearance"})
    assert should_start_dsk_chase(a) is None


def test_should_not_start_when_docs_received():
    a = _reply_audit(_pl(hour=9).isoformat(),
                     dhl_documents_received={"received": True, "files": [{"type": "DHL_CESJA_DOC"}]})
    assert should_start_dsk_chase(a) is None


def test_should_not_start_when_agency_forward_sent():
    a = _reply_audit(_pl(hour=9).isoformat(), agency_forward_after_dhl={"sent": True})
    assert should_start_dsk_chase(a) is None


def test_should_not_start_when_terminal():
    a = _reply_audit(_pl(hour=9).isoformat(), clearance_status="agency_email_sent")
    assert should_start_dsk_chase(a) is None


def test_should_not_start_when_already_active():
    a = _reply_audit(_pl(hour=9).isoformat())
    a[STATE_KEY] = {"active": True}
    assert should_start_dsk_chase(a) is None


def test_should_not_start_without_reply():
    a = _reply_audit(_pl(hour=9).isoformat())
    a["dhl_reply_package"] = {}
    assert should_start_dsk_chase(a) is None


def test_should_not_start_when_reply_only_queued():
    """Q2: queued-but-not-confirmed reply must not start the chase."""
    a = _reply_audit(_pl(hour=9).isoformat(), status="queued")
    assert should_start_dsk_chase(a) is None


def test_should_start_when_confirmed_via_verified_timeline_only():
    """Q2: verified timeline event starts the chase even if status != 'sent'."""
    a = _reply_audit(_pl(hour=9).isoformat(), status="queued")
    a["timeline"] = [{"event": "dhl_reply_sent_verified", "ts": _pl(hour=9).isoformat()}]
    out = should_start_dsk_chase(a)
    assert out and out["reason"] == "dsk_reply_sent_awaiting_dhl_docs"


# ── Q4: DHL replied after our DSK reply (classification-independent) ─────────

def test_dhl_replied_after_reply_via_inbox_flags():
    a = _reply_audit(_pl(hour=8).isoformat())   # reply sent 08:00
    a["dhl_inbox_flags"] = {"broker_notification": {"received_at": _pl(hour=10).isoformat()}}
    assert dhl_replied_after_dsk_reply(a) is True


def test_dhl_replied_ignores_pre_reply_inbound():
    """The original T# request predates the reply and must NOT count."""
    a = _reply_audit(_pl(hour=10).isoformat())  # reply sent 10:00
    a["dhl_inbox_flags"] = {"translation": {"received_at": _pl(hour=8).isoformat()}}
    assert dhl_replied_after_dsk_reply(a) is False


def test_dhl_replied_via_timeline_marker():
    a = _reply_audit(_pl(hour=8).isoformat())
    a["timeline"] = [{"event": "dhl_documents_received", "ts": _pl(hour=11).isoformat()}]
    assert dhl_replied_after_dsk_reply(a) is True


def test_should_not_start_when_dhl_already_replied():
    a = _reply_audit(_pl(hour=8).isoformat())
    a["dhl_inbox_flags"] = {"broker_notification": {"received_at": _pl(hour=12).isoformat()}}
    assert should_start_dsk_chase(a) is None


# ── Start + schedule math (reuses dhl_followup_sla working window) ───────────

def test_start_first_at_plus_4h_in_window():
    a = _reply_audit(_pl(hour=8).isoformat())   # 08:00 + 4h = 12:00 (in window)
    st = start_dsk_chase(a, _pl(hour=8), "dsk_reply_sent_awaiting_dhl_docs")
    first = datetime.fromisoformat(st["first_followup_at"])
    assert first.day == 29 and first.hour == 12
    assert st["active"] and st["followup_count"] == 0


def test_start_clamps_pre_window_to_0800():
    a = _reply_audit(_pl(hour=2).isoformat())   # 02:00 + 4h = 06:00 → clamp 08:00
    st = start_dsk_chase(a, _pl(hour=2), "r")
    assert datetime.fromisoformat(st["first_followup_at"]).hour == WORK_START.hour


def test_start_idempotent():
    a = _reply_audit(_pl(hour=8).isoformat())
    s1 = start_dsk_chase(a, _pl(hour=8), "r")
    s2 = start_dsk_chase(a, _pl(hour=10), "r")
    assert s1["first_followup_at"] == s2["first_followup_at"]


# ── is_due: no reminder before 4h, due after ────────────────────────────────

def test_not_due_before_4h():
    a = _reply_audit(_pl(hour=8).isoformat())
    st = start_dsk_chase(a, _pl(hour=8), "r")   # first at 12:00
    assert is_due(st, now=_pl(hour=9)) is False


def test_due_after_4h():
    a = _reply_audit(_pl(hour=8).isoformat())
    st = start_dsk_chase(a, _pl(hour=8), "r")   # first at 12:00
    assert is_due(st, now=_pl(hour=13)) is True


def test_repeat_advances_one_working_hour():
    a = _reply_audit(_pl(hour=8).isoformat())
    start_dsk_chase(a, _pl(hour=8), "r")
    record_dsk_chase_sent(a, when=_pl(hour=12))
    assert datetime.fromisoformat(a[STATE_KEY]["next_followup_at"]).hour == 13
    assert a[STATE_KEY]["followup_count"] == 1


# ── Stop predicates ──────────────────────────────────────────────────────────

def test_dsk_docs_received_variants():
    assert dsk_docs_received({"dhl_documents_received": {"received": True, "files": [{}]}})
    assert dsk_docs_received({"dhl_documents_received":
                              {"classification": {"document_types": ["DSK_DOCUMENT"]}}})
    assert dsk_docs_received({"dsk_received": True})
    assert dsk_docs_received({"customs_docs": {"received": True}})
    assert not dsk_docs_received({})


def test_agency_forward_sent_pred():
    assert agency_forward_sent({"agency_forward_after_dhl": {"sent": True}})
    assert not agency_forward_sent({})


def test_is_terminal_pred():
    assert is_terminal({"clearance_status": "delivered"})
    assert is_terminal({"tracking": {"status": "returned"}})
    assert not is_terminal({"clearance_status": ""})


def test_stop_sets_inactive_with_reason():
    a = _reply_audit(_pl(hour=8).isoformat())
    start_dsk_chase(a, _pl(hour=8), "r")
    stop_dsk_chase(a, STOP_DSK_DOCS_RECEIVED)
    assert a[STATE_KEY]["active"] is False
    assert a[STATE_KEY]["stop_reason"] == STOP_DSK_DOCS_RECEIVED
