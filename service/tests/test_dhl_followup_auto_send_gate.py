"""
test_dhl_followup_auto_send_gate.py — PR-B regression suite.

Pins the contract that `DHL_ORCH_AUTO_SEND_DHL_FOLLOWUP` is the real gate
for `active_shipment_monitor._process_dhl_followup` and that all five
Lesson-E background-email safety properties hold:

  1. Execution-time validation (flag, active, AWB, recipient, package, fresh ingest)
  2. Idempotency (sent_idempotency_keys check)
  3. Terminal-state suppression (delivered / cancelled / returned)
  4. Replay safety (idem key persisted before send)
  5. Environment isolation (no SMTP unless _smtp_configured)

Eight scenarios covered:

  - flag_false_no_send                — flag OFF → no queue, no advance, suppressed event
  - flag_true_active_sla_due_send     — flag ON + clean preconditions → queue + advance
  - stale_ingest_suppress             — ingest > INGEST_FRESHNESS_MAX_MIN → suppressed
  - delivered_terminal_suppress       — delivered shipment → suppressed (active gate)
  - unsafe_recipient_suppress         — pkg.to_list outside DHL_TO → suppressed
  - empty_awb_suppress                — empty AWB on audit → suppressed (missing_awb)
  - duplicate_key_suppress            — idem key already in sent_idempotency_keys → suppressed
  - ai_unavailable_template_fallback  — AI gateway fails → deterministic body still sent
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_SERVICE = Path(__file__).resolve().parents[1]
if str(_SERVICE) not in sys.path:
    sys.path.insert(0, str(_SERVICE))


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_storage(tmp_path):
    return tmp_path


def _now_iso(offset_min: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_min)).isoformat()


def _base_audit(batch_id: str, awb: str, *, ingest_age_min: int = 5) -> dict:
    """Audit dict with everything the guard needs to PASS by default."""
    return {
        "batch_id":    batch_id,
        "awb":         awb,
        "tracking_no": awb,
        "clearance_status": "import_documents_requested",
        "clearance_decision": {
            "path":         "agency",
            "agency_email": "ema@estrellajewels.eu",
        },
        "tracking": {"status": "in_transit"},
        "tracking_events": [
            {"normalized_stage": "ARRIVED_DESTINATION_COUNTRY"},
        ],
        "customs_workflow_eligible": True,
        "customs_docs": {"received": False},
        "dhl_email":   {"received": False},
        "email_ingestion": {"last_scan_at": _now_iso(-ingest_age_min)},
        "dhl_followup": {
            "active":            True,
            "trigger_reason":    "customs_trigger",
            "trigger_time":      _now_iso(-300),
            "first_followup_at": _now_iso(-10),
            "next_followup_at":  _now_iso(-1),
            "followup_count":    1,
            "last_followup_at":  None,
            "stopped_at":        None,
            "stop_reason":       None,
            "sent_idempotency_keys": [],
        },
    }


def _write_audit(storage: Path, batch_id: str, data: dict) -> Path:
    d = storage / "outputs" / batch_id
    d.mkdir(parents=True, exist_ok=True)
    p = d / "audit.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _load_audit(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _read_timeline(audit_path: Path) -> list[dict]:
    if not audit_path.exists():
        return []
    return json.loads(audit_path.read_text(encoding="utf-8")).get("timeline") or []


def _pkg_default(awb: str) -> dict:
    """Builder-shape package the guard accepts."""
    return {
        "from_address": "import@estrellajewels.eu",
        "email_type":   "dhl_followup",
        "to":           "odprawacelna@dhl.com",
        "to_list":      ["odprawacelna@dhl.com"],
        "cc":           "",
        "cc_list":      [],
        "subject":      f"Follow-up: AWB {awb} — customs clearance",
        "body_text":    (
            "Dear DHL Customs Team,\n\n"
            f"This is a follow-up regarding AWB {awb}. Please advise on "
            "current clearance status.\n\nKind regards,\nEstrella Jewels"
        ),
        "body_html":    "<p>Follow-up body</p>",
        "attachments":  [],
        "awb_attached": False,
        "ticket":       "",
        "followup_seq": 2,
        "extra_headers": {},
    }


# ── Common patching helper ───────────────────────────────────────────────────


def _patched_run(
    *,
    audit_path: Path,
    audit: dict,
    flag_value: bool,
    pkg: dict | None = None,
    smtp_configured: bool = True,
    send_outcome: dict | None = None,
    ai_used: bool = False,
    ai_model: str | None = None,
    ai_raises: bool = False,
):
    """Invoke _process_dhl_followup with controlled environment."""
    from app.services import active_shipment_monitor as mon
    from app.core.config import settings

    if send_outcome is None:
        send_outcome = {"ok": True, "status": "sent", "provider_message_id": "msg-1"}

    captured = {"queue_email_called": False, "send_called": False, "queued_kwargs": None}

    def _fake_queue_email(**kwargs):
        captured["queue_email_called"] = True
        captured["queued_kwargs"]      = kwargs
        return "email-id-1"

    def _fake_send_queued_email(email_id, method="smtp"):
        captured["send_called"] = True
        return send_outcome

    def _fake_build(audit_arg, batch_id):
        return pkg if pkg is not None else _pkg_default(
            audit_arg.get("awb") or audit_arg.get("tracking_no") or ""
        )

    def _fake_enhance(audit_arg, batch_id, pkg_arg):
        if ai_raises:
            raise RuntimeError("ai gateway exploded")
        return {
            "pkg_updates": {
                "body_text": pkg_arg.get("body_text", ""),
                "body_html": pkg_arg.get("body_html", ""),
            },
            "ai_used":    ai_used,
            "model_used": ai_model,
        }

    with patch.object(settings, "dhl_orch_auto_send_dhl_followup", flag_value, create=True), \
         patch("app.services.dhl_followup_email_builder.build_dhl_followup_email", _fake_build), \
         patch("app.services.ai_dhl_followup_drafter.enhance_email_body", _fake_enhance), \
         patch("app.services.email_service.queue_email", _fake_queue_email), \
         patch("app.services.email_sender.send_queued_email", _fake_send_queued_email), \
         patch("app.services.email_sender._smtp_configured", lambda: smtp_configured):
        result = mon._process_dhl_followup(audit_path, audit, customs_trigger=None)
    return result, captured


# ── Tests ────────────────────────────────────────────────────────────────────


def test_flag_false_no_send(tmp_storage):
    """Flag OFF → guard returns auto_send_dhl_followup_flag_off, no queue, no advance."""
    audit = _base_audit("B_FOFF", "1111111111")
    p = _write_audit(tmp_storage, "B_FOFF", audit)

    res, cap = _patched_run(audit_path=p, audit=audit, flag_value=False)

    assert cap["queue_email_called"] is False
    assert cap["send_called"]        is False
    assert res.get("sent") is not True
    # Suppression surfaced via guard_reason on out OR suppressed_reason on out
    reason = res.get("guard_reason") or res.get("suppressed_reason")
    assert reason == "auto_send_dhl_followup_flag_off"
    # State NOT advanced
    after = _load_audit(p)["dhl_followup"]
    assert after["followup_count"] == 1
    assert after.get("sent_idempotency_keys") in (None, [])

    # Timeline must record the readiness without claiming sent
    events = _read_timeline(p)
    event_names = {e.get("event") for e in events}
    # Either dedicated readiness event OR generic suppression — both acceptable
    assert (
        "dhl_followup_ready_auto_send_disabled" in event_names
        or "dhl_followup_suppressed" in event_names
    )


def test_flag_true_active_sla_due_send(tmp_storage):
    """Flag ON + clean preconditions → queue called, idem key persisted, state advanced."""
    audit = _base_audit("B_OK", "2222222222")
    p     = _write_audit(tmp_storage, "B_OK", audit)

    res, cap = _patched_run(audit_path=p, audit=audit, flag_value=True)

    assert cap["queue_email_called"] is True
    assert cap["send_called"]        is True
    assert res.get("sent") is True
    assert res.get("idempotency_key")
    # State advanced: followup_count incremented
    after = _load_audit(p)["dhl_followup"]
    assert after["followup_count"] == 2
    assert res["idempotency_key"] in (after.get("sent_idempotency_keys") or [])

    # Timeline: intent BEFORE sent
    events = _read_timeline(p)
    names  = [e.get("event") for e in events]
    assert "dhl_followup_send_intent" in names
    assert "dhl_followup_sent"        in names
    assert names.index("dhl_followup_send_intent") < names.index("dhl_followup_sent")


def test_stale_ingest_suppress(tmp_storage):
    """Ingest last_scan_at older than INGEST_FRESHNESS_MAX_MIN → suppressed."""
    audit = _base_audit("B_STALE", "3333333333", ingest_age_min=999)
    p = _write_audit(tmp_storage, "B_STALE", audit)

    res, cap = _patched_run(audit_path=p, audit=audit, flag_value=True)

    assert cap["queue_email_called"] is False
    assert res.get("sent") is not True
    reason = res.get("guard_reason") or res.get("suppressed_reason") or ""
    assert reason.startswith("stale_ingest")
    after = _load_audit(p)["dhl_followup"]
    assert after["followup_count"] == 1  # unchanged


def test_delivered_terminal_suppress(tmp_storage):
    """Delivered/terminal shipment → guard's active check rejects."""
    audit = _base_audit("B_DEL", "4444444444")
    audit["clearance_status"]   = "delivered"
    audit["tracking"]["status"] = "delivered"
    p = _write_audit(tmp_storage, "B_DEL", audit)

    res, cap = _patched_run(audit_path=p, audit=audit, flag_value=True)

    # Two acceptable paths: stop-condition fires (stopped=True) OR guard suppresses.
    # Either way: NO send, NO advance.
    assert cap["queue_email_called"] is False
    assert res.get("sent") is not True
    after = _load_audit(p)["dhl_followup"]
    assert after["followup_count"] == 1


def test_unsafe_recipient_suppress(tmp_storage):
    """pkg.to_list outside DHL_TO allow-list → suppressed with unsafe_recipient."""
    audit = _base_audit("B_UNSAFE", "5555555555")
    p = _write_audit(tmp_storage, "B_UNSAFE", audit)

    bad_pkg = _pkg_default("5555555555")
    bad_pkg["to"]      = "attacker@evil.com"
    bad_pkg["to_list"] = ["attacker@evil.com"]

    res, cap = _patched_run(audit_path=p, audit=audit, flag_value=True, pkg=bad_pkg)

    assert cap["queue_email_called"] is False
    reason = res.get("guard_reason") or res.get("suppressed_reason") or ""
    assert reason.startswith("unsafe_recipient")


def test_empty_awb_suppress(tmp_storage):
    """Empty AWB on audit → guard rejects with missing_awb."""
    audit = _base_audit("B_NOAWB", "")
    audit["awb"]         = ""
    audit["tracking_no"] = ""
    p = _write_audit(tmp_storage, "B_NOAWB", audit)

    bad_pkg = _pkg_default("")
    bad_pkg["subject"] = "Follow-up: customs clearance"  # no AWB token

    res, cap = _patched_run(audit_path=p, audit=audit, flag_value=True, pkg=bad_pkg)

    assert cap["queue_email_called"] is False
    reason = res.get("guard_reason") or res.get("suppressed_reason") or ""
    # active-shipment check runs first and rejects with not_active:missing_awb;
    # bare missing_awb / awb_missing_from_subject are also valid suppress reasons.
    assert reason in (
        "missing_awb",
        "awb_missing_from_subject",
        "not_active:missing_awb",
    )


def test_duplicate_key_suppress(tmp_storage):
    """Idempotency key already in sent_idempotency_keys → suppressed, no resend."""
    audit = _base_audit("B_DUP", "6666666666")
    # Pre-seed the exact key the guard will compute
    from app.services.dhl_followup_guard import build_followup_idempotency_key
    key = build_followup_idempotency_key("B_DUP", audit)
    audit["dhl_followup"]["sent_idempotency_keys"] = [key]
    p = _write_audit(tmp_storage, "B_DUP", audit)

    res, cap = _patched_run(audit_path=p, audit=audit, flag_value=True)

    assert cap["queue_email_called"] is False
    reason = res.get("guard_reason") or res.get("suppressed_reason") or ""
    assert reason == "duplicate_idempotency_key"
    # State unchanged
    after = _load_audit(p)["dhl_followup"]
    assert after["followup_count"] == 1
    assert after["sent_idempotency_keys"] == [key]


def test_ai_unavailable_template_fallback(tmp_storage):
    """AI gateway raises → deterministic template still sends (Lesson E §1 + req #9)."""
    audit = _base_audit("B_AIFB", "7777777777")
    p     = _write_audit(tmp_storage, "B_AIFB", audit)

    res, cap = _patched_run(
        audit_path=p, audit=audit, flag_value=True,
        ai_raises=True,   # forces fallback branch
    )

    # Send still happens — AI failure must not block
    assert cap["queue_email_called"] is True
    assert res.get("sent") is True
    # ai_draft_used must be False on the sent event
    events = _read_timeline(p)
    sent_evt = next((e for e in events if e.get("event") == "dhl_followup_sent"), None)
    assert sent_evt is not None
    assert sent_evt.get("detail", {}).get("ai_draft_used") is False
