"""
dhl_followup_sla.py — Working-hour-aware DHL follow-up scheduler.

Owns the schedule math + state lifecycle for unlimited hourly DHL follow-ups
after a customs trigger fires. Pure logic — no I/O, no email send.

Working window:
  Poland TZ (Europe/Warsaw)
  08:00 – 16:00 (inclusive of 08:00, exclusive of 16:00)
  Weekends are ACTIVE (no skipping)

Lifecycle:
  customs trigger → first_followup_at = trigger + 4h, clamped to working window
  after each send → next_followup_at = last_send + 1h, clamped to working window
  stop conditions: DHL email received, DSK received, manual stop, terminal
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any, Dict, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:                                            # Python < 3.9 safety
    from backports.zoneinfo import ZoneInfo                    # type: ignore


# ── Constants ────────────────────────────────────────────────────────────────

POLAND_TZ              = ZoneInfo("Europe/Warsaw")
WORK_START             = time(8, 0)
WORK_END               = time(16, 0)
INITIAL_WAIT_HOURS     = 4
REPEAT_FOLLOWUP_HOURS  = 1
WEEKENDS_ACTIVE        = True


# ── Working-window math ──────────────────────────────────────────────────────

def is_working_time(dt: datetime) -> bool:
    """True if `dt` (any tz) falls inside the 08:00–16:00 Poland window."""
    local = _to_poland(dt)
    if not WEEKENDS_ACTIVE and local.weekday() >= 5:
        return False
    return WORK_START <= local.timetz().replace(tzinfo=None) < WORK_END


def next_working_time(dt: datetime) -> datetime:
    """
    Clamp `dt` forward to the next valid working-window minute (Poland TZ).

    Rules:
      - dt before 08:00         → same day 08:00 Poland
      - dt inside 08:00–16:00   → dt unchanged (in Poland TZ)
      - dt at/after 16:00       → next day 08:00 Poland
      - weekends are NOT skipped (WEEKENDS_ACTIVE = True)

    Returns timezone-aware datetime in Europe/Warsaw.
    """
    local = _to_poland(dt)
    t = local.time()

    # Walk forward day-by-day until we land in the work window
    candidate = local
    while True:
        if not WEEKENDS_ACTIVE and candidate.weekday() >= 5:
            candidate = (candidate + timedelta(days=1)).replace(
                hour=WORK_START.hour, minute=WORK_START.minute, second=0, microsecond=0,
            )
            continue
        ct = candidate.time()
        if ct < WORK_START:
            return candidate.replace(hour=WORK_START.hour, minute=WORK_START.minute,
                                     second=0, microsecond=0)
        if ct < WORK_END:
            return candidate
        # at/after WORK_END → next day 08:00
        candidate = (candidate + timedelta(days=1)).replace(
            hour=WORK_START.hour, minute=WORK_START.minute, second=0, microsecond=0,
        )


def calculate_first_followup_at(trigger_time: datetime) -> datetime:
    """trigger_time + 4 hours, clamped to next working window."""
    candidate = _to_poland(trigger_time) + timedelta(hours=INITIAL_WAIT_HOURS)
    return next_working_time(candidate)


def calculate_next_followup_at(last_followup_time: datetime) -> datetime:
    """last_followup_time + 1 hour, clamped to next working window."""
    candidate = _to_poland(last_followup_time) + timedelta(hours=REPEAT_FOLLOWUP_HOURS)
    return next_working_time(candidate)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _to_poland(dt: datetime) -> datetime:
    """Convert any aware/naive datetime to Europe/Warsaw aware."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=POLAND_TZ)
    return dt.astimezone(POLAND_TZ)


def _now_poland() -> datetime:
    return datetime.now(POLAND_TZ)


# ── State lifecycle ──────────────────────────────────────────────────────────

# Stop reasons surfaced to audit / timeline / UI
STOP_DHL_EMAIL_RECEIVED   = "dhl_email_received"
STOP_DSK_RECEIVED         = "dsk_received"
STOP_MANUAL               = "manual_stop"
STOP_TERMINAL             = "shipment_terminal"
STOP_CUSTOMS_DOCS_RECEIVED = "customs_docs_received"


def should_start_followup(audit: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    Decide whether to start a follow-up SLA for this audit.

    Returns:
      {"reason": "..."} when SLA should start (caller passes to start_followup),
      None otherwise.

    Skip when:
      - DHL email already received
      - shipment terminal (delivered / returned / cancelled / agency_email_sent)
      - dhl_followup already active
    """
    if (audit.get("dhl_email") or {}).get("received"):
        return None
    if (audit.get("dhl_followup") or {}).get("active"):
        return None
    # Terminal status
    cs = audit.get("clearance_status", "")
    if cs in ("agency_email_sent", "delivered"):
        return None
    tr_status = (audit.get("tracking") or {}).get("status", "")
    if tr_status in ("delivered", "returned", "cancelled"):
        return None
    return None  # caller decides start reason from triggers


def start_followup(
    audit:          Dict[str, Any],
    trigger_time:   datetime,
    trigger_reason: str,
) -> Dict[str, Any]:
    """
    Initialize the dhl_followup state on the audit dict.

    Returns the new state. Caller is responsible for persisting the audit.
    Idempotent — if already active, returns existing state unchanged.
    """
    existing = audit.get("dhl_followup") or {}
    if existing.get("active"):
        return existing

    first_at = calculate_first_followup_at(trigger_time)
    state = {
        "active":              True,
        "trigger_time":        _to_poland(trigger_time).isoformat(),
        "trigger_reason":      trigger_reason,
        "first_followup_at":   first_at.isoformat(),
        "next_followup_at":    first_at.isoformat(),
        "followup_count":      0,
        "last_followup_at":    None,
        "stopped_at":          None,
        "stop_reason":         None,
    }
    audit["dhl_followup"] = state
    return state


def record_followup_sent(audit: Dict[str, Any], when: Optional[datetime] = None) -> Dict[str, Any]:
    """Increment count + advance next_followup_at by 1 working hour."""
    state = audit.get("dhl_followup") or {}
    if not state.get("active"):
        return state
    sent_at = _to_poland(when or _now_poland())
    state["last_followup_at"] = sent_at.isoformat()
    state["followup_count"]   = int(state.get("followup_count", 0)) + 1
    state["next_followup_at"] = calculate_next_followup_at(sent_at).isoformat()
    audit["dhl_followup"]     = state
    return state


def stop_followup(
    audit:  Dict[str, Any],
    reason: str,
    when:   Optional[datetime] = None,
) -> Dict[str, Any]:
    """Stop follow-up — sets active=false + stop_reason."""
    state = audit.get("dhl_followup") or {}
    if not state.get("active"):
        return state
    state["active"]      = False
    state["stopped_at"]  = (when or _now_poland()).astimezone(POLAND_TZ).isoformat()
    state["stop_reason"] = reason
    audit["dhl_followup"] = state
    return state


def is_due(state: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """True if current time is at-or-past next_followup_at AND state is active."""
    if not state.get("active"):
        return False
    next_at = state.get("next_followup_at")
    if not next_at:
        return False
    try:
        next_dt = datetime.fromisoformat(str(next_at).replace("Z", "+00:00"))
    except Exception:
        return True   # malformed → fire and self-heal next sweep
    now_dt = _to_poland(now or _now_poland())
    return _to_poland(next_dt) <= now_dt
