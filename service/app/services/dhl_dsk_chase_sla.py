"""
dhl_dsk_chase_sla.py — Post-DSK-reply DHL DSK/cesja chase scheduler.

NEW SLA AUTHORITY (Phase B5). This is a SEPARATE authority from the pre-T#
``dhl_followup_sla`` (which chases DHL *before* DHL emails and stops the moment
any DHL email arrives). This phase covers the window AFTER Estrella has sent the
signed DSK broker-notification reply to DHL and is waiting for DHL to issue the
DSK number / cesja documents.

Lifecycle (state lives on ``audit["dhl_dsk_chase"]`` — never on dhl_followup):
  start    : DSK reply sent (audit.dhl_reply_package queued/sent) AND agency path
             AND no DHL docs yet AND not terminal.
  first    : dsk_reply_sent_at + 4h, clamped to the working window.
  repeat   : last_send + 1h, clamped to the working window.
  stop     : DHL DSK/cesja docs received | DSK/cesja classified | agency forward
             sent | shipment terminal.

Schedule math + working-window convention are REUSED from dhl_followup_sla so
both phases share one definition of "working hours". Only the state key, the
trigger source, and the stop conditions differ.

Pure module — no I/O, no email, no queue. The caller
(active_shipment_monitor._process_dsk_chase) owns all persistence and sending.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

# Reuse the existing working-window convention + schedule math (single source).
# First reminder = trigger + 4h; repeat = +1h; both clamped to the working
# window — identical convention to dhl_followup_sla (INITIAL_WAIT_HOURS=4,
# REPEAT_FOLLOWUP_HOURS=1), via the shared calculate_* helpers below.
from .dhl_followup_sla import (
    POLAND_TZ,
    calculate_first_followup_at,
    calculate_next_followup_at,
    is_due,            # Q1: reuse — is_due(state, now) is state-key-agnostic
    _to_poland,
    _now_poland,
    _try_parse_iso,
)

STATE_KEY = "dhl_dsk_chase"

# Stop reasons surfaced to audit / timeline / UI
STOP_DSK_DOCS_RECEIVED   = "dhl_dsk_docs_received"
STOP_AGENCY_FORWARD_SENT = "agency_forward_sent"
STOP_TERMINAL            = "shipment_terminal"
STOP_DHL_THREAD_REPLY    = "dhl_thread_reply_after_dsk_reply"
STOP_MANUAL              = "manual_stop"

# DHL document types (from dhl_document_classifier) that mean "DSK/cesja arrived".
_DSK_DOC_TYPES = frozenset({"DHL_CESJA_DOC", "DSK_DOCUMENT"})


# ── Trigger resolution (start authority) ─────────────────────────────────────

def dsk_reply_sent_at(audit: Dict[str, Any]) -> Optional[datetime]:
    """Resolve when the EJ→DHL DSK authorization reply was CONFIRMED sent.

    Q2 hardening: a bare ``dhl_reply_package.status == "queued"`` is NOT
    sufficient — that is also the state left behind when the SMTP send FAILED
    (the status only flips to "sent" on confirmed delivery). Starting the chase
    on a failed send would nag DHL for a DSK we never actually delivered.

    A CONFIRMED-sent signal is therefore required — either:
      - a ``dhl_reply_sent_verified`` timeline event (written by
        email_sender.send_queued_email on confirmed SMTP delivery), OR
      - ``dhl_reply_package.status == "sent"`` (set by the same callback).

    Timestamp priority (most → least specific):
      1. ``dhl_reply_sent_verified`` timeline ts
      2. dhl_reply_package.sent_at
      3. dhl_reply_package.queued_at  (defensive fallback when status=="sent"
         but no explicit sent_at was written)
    Returns timezone-aware datetime, or None when the reply is not confirmed sent.
    """
    pkg = audit.get("dhl_reply_package") or {}

    verified_ts: Optional[datetime] = None
    for evt in audit.get("timeline") or []:
        if isinstance(evt, dict) and evt.get("event") == "dhl_reply_sent_verified":
            ts = _try_parse_iso(evt.get("ts"))
            if ts is not None:
                verified_ts = ts
                break

    confirmed = (pkg.get("status") == "sent") or (verified_ts is not None)
    if not confirmed:
        return None

    return verified_ts or _try_parse_iso(pkg.get("sent_at")) or _try_parse_iso(pkg.get("queued_at"))


# ── Stop-condition predicates (pure, audit-only) ─────────────────────────────

def dsk_docs_received(audit: Dict[str, Any]) -> bool:
    """True once DHL has returned the DSK/cesja documents (audit surfaces only).

    The monitor adds an email-evidence-store fallback before calling stop; this
    predicate is the deterministic, file-grounded part.
    """
    docs = audit.get("dhl_documents_received") or {}
    if docs.get("received") and (docs.get("files") or docs.get("classification")):
        return True
    cls = docs.get("classification") or {}
    types = cls.get("document_types") or []
    if any(t in _DSK_DOC_TYPES for t in types):
        return True
    if audit.get("dsk_received"):
        return True
    if (audit.get("customs_docs") or {}).get("received"):
        return True
    return False


def agency_forward_sent(audit: Dict[str, Any]) -> bool:
    """True once the post-DHL agency forward has been sent (workflow advanced)."""
    return bool((audit.get("agency_forward_after_dhl") or {}).get("sent"))


def is_terminal(audit: Dict[str, Any]) -> bool:
    """True when the shipment is closed/terminal — no further chasing."""
    cs = audit.get("clearance_status", "")
    if cs in ("agency_email_sent", "delivered"):
        return True
    tr = (audit.get("tracking") or {}).get("status", "")
    return tr in ("delivered", "returned", "cancelled")


# DHL-inbound timeline markers written independently of doc validation/classification.
_DHL_INBOUND_EVENTS = frozenset({
    "flag_dhl_event",
    "dhl_docs_classified_and_registered",
    "dhl_documents_received",
    "dhl_response_received",
})


def dhl_replied_after_dsk_reply(
    audit:         Dict[str, Any],
    reply_sent_at: Optional[datetime] = None,
) -> bool:
    """Q4 hardening — classification-INDEPENDENT signal that DHL has responded on
    the thread AFTER our DSK reply went out.

    Prevents indefinite hourly nagging when DHL HAS replied but document
    ingestion/classification failed (so ``dhl_documents_received`` was never
    populated and ``dsk_docs_received`` stays False). Reads only surfaces that
    are written BEFORE / independently of document validation:

      - ``audit.dhl_inbox_flags[<type>].received_at`` — event_trigger_engine
        records these for any ``role==dhl`` inbound of a flagged type
        (translation / broker_notification / carrier_status), independent of
        whether the attachments later classify/validate.
      - DHL-inbound timeline markers (``flag_dhl_event``, etc.).

    Only inbound strictly AFTER the DSK reply counts — the original T# request
    (which predates the reply) is correctly ignored by the timestamp compare.
    """
    if reply_sent_at is None:
        reply_sent_at = dsk_reply_sent_at(audit)
    if reply_sent_at is None:
        return False
    cutoff = _to_poland(reply_sent_at)

    flags = audit.get("dhl_inbox_flags") or {}
    if isinstance(flags, dict):
        for v in flags.values():
            if isinstance(v, dict):
                ts = _try_parse_iso(v.get("received_at"))
                if ts is not None and _to_poland(ts) > cutoff:
                    return True

    for evt in audit.get("timeline") or []:
        if isinstance(evt, dict) and evt.get("event") in _DHL_INBOUND_EVENTS:
            ts = _try_parse_iso(evt.get("ts"))
            if ts is not None and _to_poland(ts) > cutoff:
                return True

    return False


# ── Start decision ───────────────────────────────────────────────────────────

def should_start_dsk_chase(audit: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Decide whether to start the post-reply DSK chase SLA.

    Returns {"reason": ...} when the SLA should start, else None.

    Start when ALL hold:
      - agency-clearance path (only the agency/DSK flow issues a DSK)
      - the EJ→DHL DSK reply has been sent (dsk_reply_sent_at is not None)
      - DHL has NOT yet returned the DSK/cesja docs
      - agency forward not already sent
      - shipment not terminal
      - SLA not already active
    """
    if (audit.get(STATE_KEY) or {}).get("active"):
        return None

    # Agency/DSK path only — pre-spec aliases normalized via clearance_path_alias.
    try:
        from .clearance_path_alias import is_agency_clearance
        path = (audit.get("clearance_decision") or {}).get("clearance_path")
        if not is_agency_clearance(path):
            return None
    except Exception:
        return None

    trig = dsk_reply_sent_at(audit)
    if trig is None:
        return None
    if (dsk_docs_received(audit) or agency_forward_sent(audit)
            or is_terminal(audit) or dhl_replied_after_dsk_reply(audit, trig)):
        return None
    return {"reason": "dsk_reply_sent_awaiting_dhl_docs"}


# ── State lifecycle ──────────────────────────────────────────────────────────

def start_dsk_chase(
    audit:          Dict[str, Any],
    trigger_time:   datetime,
    trigger_reason: str,
) -> Dict[str, Any]:
    """Initialize ``audit["dhl_dsk_chase"]``. Idempotent — no-op if active.

    Caller persists the audit.
    """
    existing = audit.get(STATE_KEY) or {}
    if existing.get("active"):
        return existing

    first_at = calculate_first_followup_at(trigger_time)
    state = {
        "active":                True,
        "trigger_time":          _to_poland(trigger_time).isoformat(),
        "trigger_reason":        trigger_reason,
        "first_followup_at":     first_at.isoformat(),
        "next_followup_at":      first_at.isoformat(),
        "followup_count":        0,
        "last_followup_at":      None,
        "stopped_at":            None,
        "stop_reason":           None,
        "sent_idempotency_keys": [],
    }
    audit[STATE_KEY] = state
    return state


def record_dsk_chase_sent(audit: Dict[str, Any], when: Optional[datetime] = None) -> Dict[str, Any]:
    """Increment count + advance next_followup_at by one working hour."""
    state = audit.get(STATE_KEY) or {}
    if not state.get("active"):
        return state
    sent_at = _to_poland(when or _now_poland())
    state["last_followup_at"] = sent_at.isoformat()
    state["followup_count"]   = int(state.get("followup_count", 0)) + 1
    state["next_followup_at"] = calculate_next_followup_at(sent_at).isoformat()
    audit[STATE_KEY] = state
    return state


def stop_dsk_chase(
    audit:  Dict[str, Any],
    reason: str,
    when:   Optional[datetime] = None,
) -> Dict[str, Any]:
    """Stop the chase — sets active=False + stop_reason. Idempotent."""
    state = audit.get(STATE_KEY) or {}
    if not state.get("active"):
        return state
    state["active"]      = False
    state["stopped_at"]  = (when or _now_poland()).astimezone(POLAND_TZ).isoformat()
    state["stop_reason"] = reason
    audit[STATE_KEY] = state
    return state


__all__ = [
    "STATE_KEY",
    "STOP_DSK_DOCS_RECEIVED", "STOP_AGENCY_FORWARD_SENT", "STOP_TERMINAL",
    "STOP_DHL_THREAD_REPLY", "STOP_MANUAL",
    "dsk_reply_sent_at", "dsk_docs_received", "agency_forward_sent", "is_terminal",
    "dhl_replied_after_dsk_reply",
    "should_start_dsk_chase", "start_dsk_chase", "record_dsk_chase_sent",
    "stop_dsk_chase", "is_due",
]
