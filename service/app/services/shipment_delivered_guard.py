"""shipment_delivered_guard.py — canonical "shipment is closed" check.

Operator rule (final, no exceptions in this layer):
    If shipment status is delivered, the shipment is closed.
    No follow-up email, no retry replay, no scheduler reactivation,
    no DSK reminder, no invoice reminder, no broker escalation.
    Re-opening requires an explicit operator action OUTSIDE this guard.

This module is intentionally PURE and TINY:
  - no DB writes
  - no HTTP / wFirma / PZ / DHL email send
  - no scheduler / queue mutation (callers handle their own state)
  - one read-only audit.json lookup per check
  - deterministic boolean output

The single check is performed:
  1. at email-send execution time (email_sender.send_queued_email) so
     stale queued jobs created before delivery are suppressed
  2. at scheduler decision time (active_shipment_monitor) so we never
     enqueue new follow-ups for a delivered shipment
  3. at any manual-resend operator surface that funnels through (1)

The rule is intentionally pessimistic: when audit cannot be loaded
(missing batch_id, missing file, parse error), the guard returns
ALLOWED so legitimate sends are never blocked by metadata gaps.  The
caller is responsible for surface-level visibility (status returned,
toast message, etc.).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.config import settings
from ..core.logging import get_logger

log = get_logger(__name__)


# Anomaly A1 (Phase 2 shadow observation): normalized stages that mean
# "still active" if they appear AFTER a DELIVERED / CLOSED event.  These
# represent legitimate transport / customs reactivation (e.g. shipment
# returned to depot, customs re-opened the case).  Any one such event
# after the last DELIVERED/CLOSED means the shipment is NOT closed.
_REACTIVE_AFTER_DELIVERED: frozenset[str] = frozenset({
    "SHIPMENT_CREATED", "LABEL_CREATED", "PICKED_UP",
    "DEPARTED_ORIGIN", "ARRIVED_ORIGIN_HUB", "DEPARTED_ORIGIN_HUB",
    "IN_TRANSIT", "ARRIVED_DESTINATION_COUNTRY",
    "CUSTOMS_PENDING", "CUSTOMS_DOCUMENTS_REQUESTED",
    "CUSTOMS_DOCUMENTS_SENT", "CUSTOMS_UNDER_REVIEW",
    "CUSTOMS_CLEARED",  # post-DELIVERED clearance flip means re-opened
    "HANDED_TO_BROKER", "OUT_FOR_DELIVERY",
})

# Terminal/closure stages that signal the shipment IS closed.  EXCEPTION
# is included here because DHL routinely emits an EXCEPTION event
# immediately after DELIVERED with descriptions like "Shipment closed"
# or "Status update completed" — this is a closure marker, not a
# reactivation.  See AWBs 2519243856 / 3483447564 / 8523214840 in the
# 2026-05-19 Phase 2 telemetry where DELIVERED → EXCEPTION pairs
# represent normal closure, not a real exception.
_TERMINAL_AFTER_DELIVERED: frozenset[str] = frozenset({
    "DELIVERED", "CLOSED", "EXCEPTION",
})


def _is_delivered_by_tracking_events(audit: Dict[str, Any]) -> bool:
    """Walk ``audit.tracking_events`` and return True iff the latest
    DELIVERED/CLOSED event is not followed by any reactive stage.

    Conservative: returns False on any malformed input or empty event
    list.  An ambiguous event (unknown normalized_stage) after DELIVERED
    is treated as neither reactive nor terminal — it preserves whatever
    classification the LAST clear event implied.
    """
    if not isinstance(audit, dict):
        return False
    events = audit.get("tracking_events") or []
    if not isinstance(events, list) or not events:
        return False
    # Walk events; track last clear delivered/closed and any reactive
    # event after it.  Linear pass; O(n).
    last_delivered_idx: Optional[int] = None
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            continue
        stage = str(ev.get("normalized_stage") or "").strip().upper()
        if stage in ("DELIVERED", "CLOSED"):
            last_delivered_idx = i
    if last_delivered_idx is None:
        return False
    # Any reactive stage after the last DELIVERED/CLOSED?
    for ev in events[last_delivered_idx + 1:]:
        if not isinstance(ev, dict):
            continue
        stage = str(ev.get("normalized_stage") or "").strip().upper()
        if stage in _REACTIVE_AFTER_DELIVERED:
            return False
    return True


def is_audit_delivered(audit: Dict[str, Any]) -> bool:
    """Return True iff the audit represents a shipment whose status is
    `delivered` (= closed).

    Multiple independent surfaces are honoured; any one positive hit is
    sufficient.  The cascade matches the canonical detection used in
    active_shipment_monitor._is_active so the scheduler and the sender
    agree:

      1. ``audit["tracking"]["status"] == "delivered"`` — the tracking
         poller's canonical normalised state (set by
         tracking_service.py:782 when DHL reports DL).
      2. ``audit["delivered_at"]`` is non-empty — a future canonical
         ISO timestamp slot reserved for the same signal; honoured here
         in advance.
      3. ``audit["proactive_dispatch_delivered_at"]`` is non-empty —
         legacy slot set by active_shipment_monitor at proactive-
         dispatch time.
      4. ``audit["tracking_events"]`` contains a DELIVERED or CLOSED
         normalized_stage and no reactive stage appears after it
         (anomaly A1 fix; covers older audits whose top-level
         ``tracking.status`` was never written to "delivered").

    Pure / side-effect free.  Never raises on malformed input.
    """
    if not isinstance(audit, dict):
        return False
    # (1) Normalised tracking state
    tr = audit.get("tracking") or {}
    if isinstance(tr, dict):
        if str(tr.get("status") or "").strip().lower() == "delivered":
            return True
    # (2) Canonical delivered_at (future canonical slot — honour now)
    if str(audit.get("delivered_at") or "").strip():
        return True
    # (3) Proactive-dispatch delivered_at (legacy slot)
    if str(audit.get("proactive_dispatch_delivered_at") or "").strip():
        return True
    # (4) Tracking-events fallback (anomaly A1, Phase 2 finding)
    if _is_delivered_by_tracking_events(audit):
        return True
    return False


def load_audit_for_batch(batch_id: str) -> Optional[Dict[str, Any]]:
    """Read the per-batch ``audit.json`` from storage (read-only).

    Returns the parsed dict or ``None`` when the file is absent /
    unreadable.  Never raises.  Used by :func:`check_send_allowed`
    and any caller that needs the same lookup logic.
    """
    bid = (batch_id or "").strip()
    if not bid:
        return None
    for sub in ("outputs", "working"):
        p = settings.storage_root / sub / bid / "audit.json"
        try:
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning(
                "shipment_delivered_guard: failed to read %s: %s",
                p, exc,
            )
            return None
    return None


# ── PR-211 extension: spec alias + idempotency-key helper ────────────────
#
# Operator spec calls the canonical check ``is_shipment_closed_for_followup``.
# Provide that name as the public alias of ``is_audit_delivered`` so callers
# can use the spec wording.  Same behaviour, no semantic change.

def is_shipment_closed_for_followup(audit: Dict[str, Any]) -> bool:
    """Spec-named alias of :func:`is_audit_delivered`.

    A shipment is closed for follow-up iff its delivered state is true on
    any of the canonical surfaces (``tracking.status``, ``delivered_at``,
    ``proactive_dispatch_delivered_at``).  Pure; never raises.
    """
    return is_audit_delivered(audit)


def build_idempotency_key(batch_id: str,
                          email_type: str = "",
                          to: str = "",
                          purpose: str = "") -> str:
    """Build a deterministic idempotency key for a follow-up email.

    Key shape: ``"{batch_id}|{email_type}|{recipients_csv_lower}|{purpose}"``.

    - ``batch_id`` distinguishes shipments
    - ``email_type`` distinguishes follow-up purpose category
      (e.g. ``"agency"`` / ``"dhl_reply"`` / ``"agency_followup"``)
    - ``to`` is normalised: split on comma, trimmed, lowercased, sorted
      so ``"A@x,B@y"`` and ``"b@y, a@x"`` produce identical keys
    - ``purpose`` is optional free-form discriminator (e.g.
      ``"sad_overdue"``) supplied by the caller when ``email_type`` is
      too coarse

    Pure / deterministic / side-effect free.  Used by queue-time
    deduplication to refuse duplicate pending entries for the same
    shipment+type+recipient.
    """
    bid_n   = (batch_id   or "").strip()
    type_n  = (email_type or "").strip().lower()
    pur_n   = (purpose    or "").strip().lower()
    to_addrs = sorted({
        a.strip().lower()
        for a in str(to or "").split(",")
        if a.strip()
    })
    return f"{bid_n}|{type_n}|{','.join(to_addrs)}|{pur_n}"


def check_send_allowed(batch_id: str) -> Dict[str, Any]:
    """Single decision point for "may this batch's queued follow-up
    actually be sent now?"

    Return shape::

        {
          "allowed":     bool,
          "reason":      str,       # machine-readable
          "audit_found": bool,
          "delivered":   bool,
        }

    Semantics:
      - When the audit cannot be loaded (missing batch_id, file absent,
        parse error), the guard returns ``allowed=True`` with
        ``audit_found=False``.  This is deliberate: a guard that
        accidentally blocks every send because of a path glitch would
        cause far more operational harm than the rule it enforces.
        Caller still sees ``audit_found=False`` in the result and can
        decide whether to log / flag it.
      - When the audit IS loaded and ``is_audit_delivered`` returns
        True, the guard returns ``allowed=False`` with reason
        ``"shipment_delivered"``.  This is the hard rule.
    """
    bid = (batch_id or "").strip()
    if not bid:
        return {
            "allowed":     True,
            "reason":      "no_batch_id_guard_skipped",
            "audit_found": False,
            "delivered":   False,
        }
    audit = load_audit_for_batch(bid)
    if audit is None:
        return {
            "allowed":     True,
            "reason":      "audit_not_found_guard_skipped",
            "audit_found": False,
            "delivered":   False,
        }
    delivered = is_audit_delivered(audit)
    if delivered:
        return {
            "allowed":     False,
            "reason":      "shipment_delivered",
            "audit_found": True,
            "delivered":   True,
        }
    return {
        "allowed":     True,
        "reason":      "shipment_not_delivered",
        "audit_found": True,
        "delivered":   False,
    }


# ── Stale-queue expiry ─────────────────────────────────────────────────────

# Operator-configurable but intentionally conservative.  A queued
# follow-up older than this is almost certainly stale: the shipment
# either already delivered, was resolved by a different channel, or
# was rolled back manually.  Refusing the send is safer than firing.
STALE_QUEUE_DAYS = 14


def is_queue_entry_stale(queue_entry: Dict[str, Any],
                         *,
                         now_iso: Optional[str] = None,
                         max_age_days: int = STALE_QUEUE_DAYS) -> bool:
    """Return True iff the queue entry's ``queued_at`` is older than
    ``max_age_days``.  Pure / side-effect free.

    ``now_iso`` overrides the clock — test-only.  Default is utcnow().
    """
    if not isinstance(queue_entry, dict):
        return False
    qa = str(queue_entry.get("queued_at") or "").strip()
    if not qa:
        return False
    try:
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        if now_iso:
            now = _dt.fromisoformat(now_iso.replace("Z", "+00:00"))
        else:
            now = _dt.now(_tz.utc)
        queued = _dt.fromisoformat(qa.replace("Z", "+00:00"))
        if queued.tzinfo is None:
            queued = queued.replace(tzinfo=_tz.utc)
        return (now - queued) > _td(days=int(max_age_days))
    except Exception:
        return False
