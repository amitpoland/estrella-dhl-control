"""test_dhl_dsk_chase_guard_and_send.py — Phase B5 guard + monitor send path.

Covers the operator's required scenarios for the post-DSK-reply chase:
  - no reminder before 4h
  - reminder due after 4h (sends, flag on)
  - stops when dhl_documents_received exists
  - stops when agency forward sent
  - no duplicate sends (idempotency)
  - flag off → no send
  - AWB 9158478722-style: T# received + DSK reply sent + no DHL docs → eligible

All email send paths are MOCKED — no real SMTP, no live queue mutation.
"""
from __future__ import annotations

import contextlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.services.dhl_followup_sla import POLAND_TZ  # noqa: E402


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _pl_iso(hour: int) -> str:
    """Fixed weekday in-window Poland time in 2026-04 (far in the past vs now)."""
    return datetime(2026, 4, 29, hour, 0, tzinfo=POLAND_TZ).isoformat()


def _audit(**ov):
    now = _now()
    a = {
        "batch_id":          "SHIPMENT_DSK_001",
        "awb":               "9158478722",
        "tracking_no":       "9158478722",
        "clearance_decision": {"clearance_path": "agency_clearance",
                               "total_value_usd": 24235},
        "clearance_status":  "",
        "tracking":          {"status": "in_customs"},
        "dhl_email":         {"received": True, "ticket": "T#1WA2606220000005",
                              "received_at": _iso(now - timedelta(hours=6))},
        "dhl_reply_package": {"email_id": "q1", "status": "sent",
                              "queued_at": _iso(now - timedelta(hours=6)),
                              "sent_at":   _iso(now - timedelta(hours=6)),
                              "send_verified": True,
                              "ticket": "T#1WA2606220000005"},
        "email_ingestion":   {"last_scan_at": _iso(now - timedelta(minutes=5))},
        "followup":          {"mode": "automatic"},
    }
    a.update(ov)
    return a


def _pkg(awb: str = "9158478722", **ov):
    base = {
        "from_address": "import@estrellajewels.eu",
        "email_type":   "dhl_dsk_chase",
        "to":           "odprawacelna@dhl.com",
        "to_list":      ["odprawacelna@dhl.com"],
        "cc":           "info@estrellajewels.eu, import@estrellajewels.eu",
        "cc_list":      ["info@estrellajewels.eu", "import@estrellajewels.eu",
                         "account@estrellajewels.eu"],
        "subject":      f"Re: T#1WA2606220000005 – DSK issuance reminder #1 – AWB {awb}",
        "body_text":    f"reminder AWB {awb}",
        "body_html":    f"<p>{awb}</p>",
        "attachments":  [],
    }
    base.update(ov)
    return base


def _due_chase_state():
    """An active chase whose next_followup_at is far in the past → due now."""
    return {
        "active":                True,
        "trigger_time":          _pl_iso(8),
        "trigger_reason":        "dsk_reply_sent_awaiting_dhl_docs",
        "first_followup_at":     _pl_iso(12),
        "next_followup_at":      _pl_iso(12),
        "followup_count":        0,
        "last_followup_at":      None,
        "sent_idempotency_keys": [],
    }


def _write_audit(tmp_path, audit) -> Path:
    bdir = tmp_path / audit["batch_id"]
    bdir.mkdir(parents=True, exist_ok=True)
    p = bdir / "audit.json"
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


# ── Guard unit tests ─────────────────────────────────────────────────────────

def test_guard_flag_off_blocks():
    from app.services.dhl_dsk_chase_guard import validate_dsk_chase_send_preconditions
    res = validate_dsk_chase_send_preconditions(_audit(), _pkg(), flag_override=False)
    assert not res.ok and res.reason == "auto_send_dsk_chase_flag_off"


def test_guard_manual_mode_blocks():
    from app.services.dhl_dsk_chase_guard import validate_dsk_chase_send_preconditions
    a = _audit(followup={"mode": "manual"})
    res = validate_dsk_chase_send_preconditions(a, _pkg(), flag_override=True)
    assert not res.ok and res.reason == "manual_mode"


def test_guard_ok_uses_dsk_chase_key_namespace(monkeypatch):
    import app.services.dhl_orchestrator as orch
    monkeypatch.setattr(orch, "is_active_shipment", lambda audit: (True, "active"))
    from app.services.dhl_dsk_chase_guard import validate_dsk_chase_send_preconditions
    a = _audit()
    a["dhl_dsk_chase"] = _due_chase_state()
    res = validate_dsk_chase_send_preconditions(a, _pkg(), flag_override=True)
    assert res.ok, res.reason
    assert "dhl_dsk_chase" in res.idempotency_key
    assert res.primary_to == "odprawacelna@dhl.com"


# ── Monitor send-path integration ───────────────────────────────────────────

@pytest.fixture
def _send_patches(monkeypatch):
    """Mock every external side-effect: lock, active check, queue, SMTP, store."""
    import app.utils.proposal_lock as plock
    import app.services.dhl_orchestrator as orch
    import app.services.email_service as esvc
    import app.services.email_sender as esnd
    import app.services.email_evidence_store as estore

    monkeypatch.setattr(plock, "proposal_write_lock",
                        lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(orch, "is_active_shipment", lambda audit: (True, "active"))
    monkeypatch.setattr(estore, "get_summary", lambda awb: {})

    queue_mock = MagicMock(return_value="qid-1")
    send_mock  = MagicMock(return_value={"ok": True, "status": "sent",
                                         "provider_message_id": "PM1"})
    monkeypatch.setattr(esvc, "queue_email", queue_mock)
    monkeypatch.setattr(esnd, "send_queued_email", send_mock)
    monkeypatch.setattr(esnd, "_smtp_configured", lambda: True)
    return {"queue": queue_mock, "send": send_mock}


def _flag_on(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "dhl_orch_auto_send_dsk_chase", True)


def test_process_starts_chase_not_due_yet(_send_patches, tmp_path, monkeypatch):
    """Fresh reply (queued just now) → chase starts, first is +4h → NOT sent yet."""
    _flag_on(monkeypatch)
    a = _audit(dhl_reply_package={"email_id": "q1", "status": "sent",
                                  "queued_at": _iso(_now()),
                                  "sent_at":   _iso(_now()),
                                  "send_verified": True,
                                  "ticket": "T#1WA2606220000005"})
    p = _write_audit(tmp_path, a)
    from app.services.active_shipment_monitor import _process_dsk_chase
    out = _process_dsk_chase(p, json.loads(p.read_text()))
    assert out["started"] is True
    assert out["sent"] is False
    saved = json.loads(p.read_text())
    assert saved["dhl_dsk_chase"]["active"] is True
    _send_patches["queue"].assert_not_called()


def test_process_sends_when_due_flag_on(_send_patches, tmp_path, monkeypatch):
    _flag_on(monkeypatch)
    a = _audit()
    a["dhl_dsk_chase"] = _due_chase_state()
    p = _write_audit(tmp_path, a)
    from app.services.active_shipment_monitor import _process_dsk_chase
    out = _process_dsk_chase(p, json.loads(p.read_text()))
    assert out["sent"] is True, out
    _send_patches["queue"].assert_called_once()
    saved = json.loads(p.read_text())
    assert saved["dhl_dsk_chase"]["followup_count"] == 1
    assert saved["dhl_dsk_chase"]["sent_idempotency_keys"]


def test_process_not_due_before_4h(_send_patches, tmp_path, monkeypatch):
    _flag_on(monkeypatch)
    a = _audit()
    st = _due_chase_state()
    st["next_followup_at"] = _iso(_now() + timedelta(hours=2))   # future → not due
    a["dhl_dsk_chase"] = st
    p = _write_audit(tmp_path, a)
    from app.services.active_shipment_monitor import _process_dsk_chase
    out = _process_dsk_chase(p, json.loads(p.read_text()))
    assert out["sent"] is False
    _send_patches["queue"].assert_not_called()


def test_process_flag_off_no_send(_send_patches, tmp_path):
    """Flag NOT enabled (default False) → guard suppresses, nothing sent."""
    a = _audit()
    a["dhl_dsk_chase"] = _due_chase_state()
    p = _write_audit(tmp_path, a)
    from app.services.active_shipment_monitor import _process_dsk_chase
    out = _process_dsk_chase(p, json.loads(p.read_text()))
    assert out["sent"] is False
    assert out.get("suppressed_reason") == "auto_send_dsk_chase_flag_off"
    _send_patches["queue"].assert_not_called()


def test_process_stops_when_docs_received(_send_patches, tmp_path, monkeypatch):
    _flag_on(monkeypatch)
    a = _audit()
    a["dhl_dsk_chase"] = _due_chase_state()
    a["dhl_documents_received"] = {"received": True, "files": [{"type": "DHL_CESJA_DOC"}]}
    p = _write_audit(tmp_path, a)
    from app.services.active_shipment_monitor import _process_dsk_chase
    out = _process_dsk_chase(p, json.loads(p.read_text()))
    assert out["stopped"] is True
    saved = json.loads(p.read_text())
    assert saved["dhl_dsk_chase"]["active"] is False
    assert saved["dhl_dsk_chase"]["stop_reason"] == "dhl_dsk_docs_received"
    _send_patches["queue"].assert_not_called()


def test_process_stops_when_agency_forward_sent(_send_patches, tmp_path, monkeypatch):
    _flag_on(monkeypatch)
    a = _audit()
    a["dhl_dsk_chase"] = _due_chase_state()
    a["agency_forward_after_dhl"] = {"sent": True}
    p = _write_audit(tmp_path, a)
    from app.services.active_shipment_monitor import _process_dsk_chase
    out = _process_dsk_chase(p, json.loads(p.read_text()))
    assert out["stopped"] is True
    saved = json.loads(p.read_text())
    assert saved["dhl_dsk_chase"]["stop_reason"] == "agency_forward_sent"
    _send_patches["queue"].assert_not_called()


def test_process_no_duplicate_send_same_slot(_send_patches, tmp_path, monkeypatch):
    _flag_on(monkeypatch)
    a = _audit()
    st = _due_chase_state()
    dup_key = f"{a['batch_id']}|dhl_dsk_chase|{st['next_followup_at']}"
    st["sent_idempotency_keys"] = [dup_key]   # slot already sent
    a["dhl_dsk_chase"] = st
    p = _write_audit(tmp_path, a)
    from app.services.active_shipment_monitor import _process_dsk_chase
    out = _process_dsk_chase(p, json.loads(p.read_text()))
    assert out["sent"] is False
    assert out.get("suppressed_reason") == "duplicate_idempotency_key"
    _send_patches["queue"].assert_not_called()


def test_awb_9158478722_style_eligible_starts_and_sends(_send_patches, tmp_path, monkeypatch):
    """Headline case: T# received + DSK reply sent (past) + no DHL docs → fires."""
    _flag_on(monkeypatch)
    a = _audit(dhl_reply_package={"email_id": "q1", "status": "sent",
                                  "queued_at": _pl_iso(8),   # far past → first (12:00) due
                                  "sent_at":   _pl_iso(8),
                                  "send_verified": True,
                                  "ticket": "T#1WA2606220000005"})
    # no dhl_dsk_chase state, no dhl_documents_received
    p = _write_audit(tmp_path, a)
    from app.services.active_shipment_monitor import _process_dsk_chase
    out = _process_dsk_chase(p, json.loads(p.read_text()))
    assert out["started"] is True
    assert out["sent"] is True, out
    _send_patches["queue"].assert_called_once()


def test_process_stops_on_dhl_thread_reply_without_docs(_send_patches, tmp_path, monkeypatch):
    """Q4: DHL replied on the thread after our DSK reply, but docs never
    classified (no dhl_documents_received) → chase STOPS (no indefinite nag)."""
    _flag_on(monkeypatch)
    a = _audit()                       # confirmed-sent reply 6h ago
    a["dhl_dsk_chase"] = _due_chase_state()
    # NO dhl_documents_received; DHL inbound flagged AFTER the reply went out.
    a["dhl_inbox_flags"] = {"broker_notification": {"received_at": _iso(_now())}}
    p = _write_audit(tmp_path, a)
    from app.services.active_shipment_monitor import _process_dsk_chase
    out = _process_dsk_chase(p, json.loads(p.read_text()))
    assert out["stopped"] is True
    saved = json.loads(p.read_text())
    assert saved["dhl_dsk_chase"]["active"] is False
    assert saved["dhl_dsk_chase"]["stop_reason"] == "dhl_thread_reply_after_dsk_reply"
    _send_patches["queue"].assert_not_called()


# ── Concurrency: start condition must hold the per-batch lock ────────────────
#
# GATE-4 / PR #719 deploy-gate salvage (deploy-persistence-storage-reviewer):
# the START read-modify-write must run under the SAME _b5_lock(batch_id) the
# send path uses, with an in-lock re-read + not-active re-check. Otherwise two
# concurrent monitor sweeps both observe not-active and both write a start —
# a last-writer-wins double-start. This test deliberately uses the REAL
# per-batch lock (NOT the _send_patches nullcontext mock) so contention is real.

def test_concurrent_start_attempts_produce_single_start(tmp_path, monkeypatch):
    """Two monitor sweeps racing the START condition collapse to exactly ONE
    start — one first_followup_at, one dhl_dsk_chase_started timeline event.

    The two threads are rendezvoused at the pre-lock eligibility gate so both
    pass it BEFORE either writes — the precise TOCTOU window the lock closes.
    Pre-fix (start RMW outside the lock) both threads write a start and both
    return started=True; this assertion (exactly one start) goes red there.
    """
    import threading
    import app.utils.proposal_lock as plock
    import app.services.dhl_dsk_chase_sla as sla

    plock._reset_locks_for_tests()

    # Eligible, FRESH reply → after start the first follow-up is +4h (future),
    # so the send path is never reached (no SMTP / queue side-effects to mock).
    a = _audit(dhl_reply_package={"email_id": "q1", "status": "sent",
                                  "queued_at": _iso(_now()),
                                  "sent_at":   _iso(_now()),
                                  "send_verified": True,
                                  "ticket": "T#1WA2606220000005"})
    p = _write_audit(tmp_path, a)

    # Rendezvous the two threads at the pre-lock eligibility gate so both pass
    # it before either acquires the write lock. Only the first two calls (the
    # per-thread pre-lock gate) wait; the winner's in-lock re-check call (3rd)
    # must NOT block or the fixed code would deadlock holding the lock.
    gate          = threading.Barrier(2)
    seen          = {"n": 0}
    seen_lock     = threading.Lock()
    real_should   = sla.should_start_dsk_chase

    def _gated_should_start(audit):
        with seen_lock:
            seen["n"] += 1
            mine = seen["n"]
        res = real_should(audit)
        if mine <= 2:
            try:
                gate.wait(timeout=5)
            except threading.BrokenBarrierError:
                pass
        return res

    monkeypatch.setattr(sla, "should_start_dsk_chase", _gated_should_start)

    from app.services.active_shipment_monitor import _process_dsk_chase

    results: list = []
    res_lock = threading.Lock()

    def _run():
        out = _process_dsk_chase(p, json.loads(p.read_text()))
        with res_lock:
            results.append(out)

    t1 = threading.Thread(target=_run)
    t2 = threading.Thread(target=_run)
    t1.start(); t2.start()
    t1.join(timeout=10); t2.join(timeout=10)
    assert not t1.is_alive() and not t2.is_alive(), "threads deadlocked"

    # Exactly one sweep performed the start; neither sent (not due yet).
    started = [o for o in results if o.get("started")]
    assert len(started) == 1, f"expected exactly one start, got {len(results)} results: {results}"
    assert all(not o.get("sent") for o in results)

    # Disk shows a single coherent active chase.
    saved = json.loads(p.read_text())
    chase = saved["dhl_dsk_chase"]
    assert chase["active"] is True
    assert chase["followup_count"] == 0

    # Exactly one start was recorded on the timeline — no duplicate event.
    started_events = [e for e in saved.get("timeline", [])
                      if e.get("event") == "dhl_dsk_chase_started"]
    assert len(started_events) == 1, started_events

    # The thread that lost the race adopted the winner's authoritative state
    # instead of writing a second start.
    losers = [o for o in results if not o.get("started")]
    assert len(losers) == 1
    loser_state = losers[0].get("state_after") or {}
    assert loser_state.get("active") is True
    assert loser_state.get("first_followup_at") == chase["first_followup_at"]
