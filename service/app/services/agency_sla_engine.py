"""
agency_sla_engine.py — 2-hour SLA + hourly follow-ups for the agency forward.

Mirrors `dhl_followup_sla` but starts at agency_forward_after_dhl.sent_at,
2-hour initial deadline (vs. 4h for DHL), 1-hour repeat. Working hours +
weekends-active rules identical.

Storage:
  audit.sla.agency_followups       int  (count)
  audit.sla.last_followup_at       ISO
  audit.sla.next_followup_at       ISO
  audit.sla.active                 bool
  audit.sla.stop_reason            str | None
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from .dhl_followup_sla import (
    POLAND_TZ, WORK_START, WORK_END,
    next_working_time, _to_poland, _now_poland,
)


AGENCY_INITIAL_WAIT_HOURS = 2
AGENCY_REPEAT_HOURS       = 1


# ── Schedule math ────────────────────────────────────────────────────────────

def calculate_first_agency_followup_at(forward_sent_at: datetime) -> datetime:
    """forward_sent_at + 2h, clamped to next working window."""
    candidate = _to_poland(forward_sent_at) + timedelta(hours=AGENCY_INITIAL_WAIT_HOURS)
    return next_working_time(candidate)


def calculate_next_agency_followup_at(last_followup_at: datetime) -> datetime:
    """last_followup_at + 1h, clamped to next working window."""
    candidate = _to_poland(last_followup_at) + timedelta(hours=AGENCY_REPEAT_HOURS)
    return next_working_time(candidate)


# ── Lifecycle (writes go under audit["sla"]) ─────────────────────────────────

def start_agency_sla(
    audit:           Dict[str, Any],
    forward_sent_at: datetime,
    trigger_reason:  str = "agency_forward_after_dhl_sent",
) -> Dict[str, Any]:
    """Initialise audit.sla for the agency follow-up. Idempotent."""
    sla = audit.get("sla") or {}
    if sla.get("active"):
        return sla
    first_at = calculate_first_agency_followup_at(forward_sent_at)
    sla = {
        "kind":               "agency",
        "active":             True,
        "trigger_reason":     trigger_reason,
        "trigger_time":       _to_poland(forward_sent_at).isoformat(),
        "first_followup_at":  first_at.isoformat(),
        "next_followup_at":   first_at.isoformat(),
        "agency_followups":   0,
        "last_followup_at":   None,
        "stopped_at":         None,
        "stop_reason":        None,
    }
    audit["sla"] = sla
    return sla


def stop_agency_sla(audit: Dict[str, Any], reason: str,
                    when: Optional[datetime] = None) -> Dict[str, Any]:
    sla = audit.get("sla") or {}
    if not sla.get("active"):
        return sla
    sla["active"]      = False
    sla["stopped_at"]  = (when or _now_poland()).astimezone(POLAND_TZ).isoformat()
    sla["stop_reason"] = reason
    audit["sla"] = sla
    return sla


def record_agency_followup_sent(audit: Dict[str, Any],
                                 when: Optional[datetime] = None) -> Dict[str, Any]:
    sla = audit.get("sla") or {}
    if not sla.get("active"):
        return sla
    sent_at = _to_poland(when or _now_poland())
    sla["last_followup_at"] = sent_at.isoformat()
    sla["agency_followups"] = int(sla.get("agency_followups", 0)) + 1
    sla["next_followup_at"] = calculate_next_agency_followup_at(sent_at).isoformat()
    audit["sla"] = sla
    return sla


def is_agency_followup_due(sla: Dict[str, Any],
                            now: Optional[datetime] = None) -> bool:
    if not sla.get("active"):
        return False
    next_at = sla.get("next_followup_at")
    if not next_at:
        return False
    try:
        next_dt = datetime.fromisoformat(str(next_at).replace("Z", "+00:00"))
    except Exception:
        return True
    now_dt = _to_poland(now or _now_poland())
    return _to_poland(next_dt) <= now_dt
