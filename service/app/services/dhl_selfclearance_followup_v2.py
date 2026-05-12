"""
dhl_selfclearance_followup_v2.py — ADR-014 follow-up cadence scheduler (P0).

NEW service. Coexists with legacy `dhl_followup_sla.py` per Decision 2.
Coordinator routes by `clearance_path`:
    Path A (dhl_self_clearance) → this module
    Path B (agency_clearance)   → legacy dhl_followup_sla.py (untouched)

P0 commitment
=============
Pure schedule decisions. No SMTP. No queue side-effects. The scheduler
returns when the next tick should fire, leaving the actual outbound to P4
wiring.

Cadence (ADR-014 — configurable via settings):
    working hours window (default CET 08:00-16:00, Mon-Fri):
        2h interval
    off-hours (overnight / weekend):
        6h interval
    livelock budget exceeded (default 1 week from activation):
        no more ticks (returns None); operator review marker emitted

Holidays
========
P0 ships a stub `is_holiday(d)` returning False. Operator can patch the
holiday set in a follow-up commit; the schedule policy is decoupled from
holiday data so the calendar can swap without altering ADR-014.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional, Tuple

from ..core.config import settings


# ── Configurable policy (read fresh from settings on each call) ───────────────

def _working_hours_window() -> Tuple[time, time, str]:
    """
    Parse settings.dhl_selfclearance_followup_working_hours_window
    of the shape "HH:MM-HH:MM CET" or "HH:MM-HH:MM". Returns (start, end, tz).
    Falls back to (08:00, 16:00, "CET") on parse error.
    """
    raw = getattr(settings, "dhl_selfclearance_followup_working_hours_window",
                  "08:00-16:00 CET")
    try:
        window, *tz_parts = raw.split()
        start_s, end_s = window.split("-")
        sh, sm = (int(x) for x in start_s.split(":"))
        eh, em = (int(x) for x in end_s.split(":"))
        tz = tz_parts[0] if tz_parts else "CET"
        return time(sh, sm), time(eh, em), tz
    except Exception:
        return time(8, 0), time(16, 0), "CET"


def _working_interval_sec() -> int:
    return int(getattr(settings, "dhl_selfclearance_followup_working_interval_sec",
                       7200))  # 2h


def _offhours_interval_sec() -> int:
    return int(getattr(settings, "dhl_selfclearance_followup_offhours_interval_sec",
                       21600))  # 6h


def _livelock_budget_hours() -> int:
    return int(getattr(settings, "dhl_selfclearance_followup_livelock_budget_hours",
                       168))  # 1 week


# ── Public dataclass ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TickDecision:
    """Outcome of next_tick_time()."""
    next_tick_at:        Optional[datetime]
    interval_sec:        int                 # 0 when next_tick_at is None
    in_working_hours:    bool
    livelock_exhausted:  bool
    livelock_budget_end: datetime

    @property
    def should_fire(self) -> bool:
        return self.next_tick_at is not None and not self.livelock_exhausted


# ── Stubs (operator may patch) ───────────────────────────────────────────────

def is_holiday(d: datetime) -> bool:
    """P0 stub — always False. Operator wires holiday calendar in P4 / ops."""
    return False


# ── Core schedule logic ──────────────────────────────────────────────────────

def is_working_hours(now: datetime) -> bool:
    """Mon-Fri, inside the configured working window, not a holiday."""
    if now.weekday() >= 5:           # 5=Sat, 6=Sun
        return False
    if is_holiday(now):
        return False
    start, end, _tz = _working_hours_window()
    n = now.time()
    return start <= n < end


def livelock_budget_end(activated_at: datetime) -> datetime:
    """Compute the absolute end of the livelock budget window."""
    return activated_at + timedelta(hours=_livelock_budget_hours())


def next_tick_time(
    now:          datetime,
    activated_at: datetime,
) -> TickDecision:
    """
    Decide when the next follow-up tick should fire.

    Returns TickDecision. When the livelock budget is exhausted, next_tick_at
    is None and livelock_exhausted is True.
    """
    end = livelock_budget_end(activated_at)
    if now >= end:
        return TickDecision(
            next_tick_at=None,
            interval_sec=0,
            in_working_hours=is_working_hours(now),
            livelock_exhausted=True,
            livelock_budget_end=end,
        )

    in_wh = is_working_hours(now)
    interval = _working_interval_sec() if in_wh else _offhours_interval_sec()
    candidate = now + timedelta(seconds=interval)
    # Cap at livelock budget end — if interval would push beyond, fire exactly
    # at the budget end so the operator-review marker is emitted promptly.
    if candidate >= end:
        candidate = end
    return TickDecision(
        next_tick_at=candidate,
        interval_sec=interval,
        in_working_hours=in_wh,
        livelock_exhausted=False,
        livelock_budget_end=end,
    )


def utcnow() -> datetime:
    """Helper — UTC now, timezone-aware. Tests inject specific datetimes."""
    return datetime.now(timezone.utc)
