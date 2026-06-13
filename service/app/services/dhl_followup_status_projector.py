"""
dhl_followup_status_projector.py — Read-only projection over DHL follow-up state.

PURE READ ONLY.  No writes.  No new authority.  Aggregates existing
``dhl_followup`` state, timeline events, and orchestrator flags into a
shape suitable for a visibility dashboard card and drill-down table.

Lesson F compliance — single domain authority (DHL follow-up automation).
Backend produces the authoritative shape; the V2 page is a dumb renderer.

Lesson E compliance — this module CANNOT send, queue, or schedule emails.
It only reads existing state.  Importable with zero side effects.

Public API:
  project_automation_status() -> dict
      Top-card shape: flag state, counters, traffic-light, last events,
      today's metrics.

  project_shipment_rows() -> list[dict]
      Per-shipment drill-down rows: AWB, mode, status, next_due, last_scan.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# Statuses for the drill-down rows.
ST_ELIGIBLE     = "Eligible"
ST_MONITORING   = "Monitoring"
ST_WAITING      = "Waiting"
ST_SUPPRESSED   = "Suppressed"
ST_FAILED       = "Failed"
ST_INACTIVE     = "Inactive"
ST_STOPPED      = "Stopped"

# Follow-up-related timeline event types we project from.
EV_SENT        = "dhl_followup_sent"
EV_SUPPRESSED  = "dhl_followup_suppressed"
EV_FAILED      = "dhl_followup_send_failed"
EV_STOPPED     = "dhl_followup_stopped"


# ── Internal helpers ─────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _audit_paths() -> List[Path]:
    """Enumerate audit.json files under storage_root/outputs.  Read-only."""
    try:
        from ..core.config import settings
        base = settings.storage_root / "outputs"
    except Exception as exc:
        log.warning("status_projector: settings load failed: %s", exc)
        return []
    if not base.exists():
        return []
    out: List[Path] = []
    for p in base.glob("SHIPMENT_*/audit.json"):
        if "backup_before_regen" in str(p):
            continue
        out.append(p)
    return out


def _read_audit(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("status_projector: cannot read %s: %s", path, exc)
        return None


def _flag_on() -> bool:
    try:
        from ..core.config import settings
        return bool(getattr(settings, "dhl_orch_auto_send_dhl_followup", False))
    except Exception:
        return False


def _is_active(audit: Dict[str, Any]) -> Tuple[bool, str]:
    """Delegate to orchestrator authority — never duplicate the rule."""
    try:
        from .dhl_orchestrator import is_active_shipment
        return is_active_shipment(audit)
    except Exception as exc:
        log.warning("status_projector: is_active_shipment failed: %s", exc)
        return False, f"active_check_error:{exc!s}"[:80]


def _awb_of(audit: Dict[str, Any]) -> str:
    return str(audit.get("awb") or audit.get("tracking_no") or "").strip()


def _mode_fields(audit: Dict[str, Any], flag_on: bool) -> Dict[str, str]:
    """Read shipment-level follow-up mode from the SINGLE authority and
    produce truthful UI fields.

    Delegates to ``dhl_followup_mode.get_mode`` + ``is_mode_explicit`` (PR #373
    single-authority rule). NEVER re-derive mode from ``dhl_followup.active`` /
    ``stopped_at`` — that would create a second authority.

    State matrix (truth-table for the UI):

      | mode field on audit | global flag | mode_state    | mode_label              |
      |---------------------|-------------|---------------|-------------------------|
      | "automatic"         | any         | "automatic"   | "Automatic"             |
      | "manual" (explicit) | any         | "manual"      | "Manual"                |
      | missing / invalid   | true        | "unset"       | "Default (Global on)"   |
      | missing / invalid   | false       | "unset"       | "Default"               |

    The "unset" state is the critical fix: previously this was silently
    rendered as "Manual", making the default look like an operator decision.
    """
    try:
        from .dhl_followup_mode import get_mode, is_mode_explicit
        explicit = is_mode_explicit(audit)
        if explicit:
            resolved = get_mode(audit)  # "manual" or "automatic"
            if resolved == "automatic":
                return {"mode_state": "automatic", "mode_label": "Automatic"}
            return {"mode_state": "manual", "mode_label": "Manual"}
        # Not explicitly set on the audit — show truthful "Default" rather
        # than impersonating an operator-set "Manual".
        if flag_on:
            return {"mode_state": "unset", "mode_label": "Default (Global on)"}
        return {"mode_state": "unset", "mode_label": "Default"}
    except Exception as exc:
        log.warning("status_projector: dhl_followup_mode lookup failed: %s", exc)
        return {"mode_state": "unset", "mode_label": "Default"}


def _sad_phase(audit: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """Delegate to the SLA's pure derivation. Returns the SAD-phase dict
    even on error (status "None") so callers never branch on exceptions."""
    try:
        from .dhl_followup_sla import derive_sad_followup_status
        return derive_sad_followup_status(audit, now)
    except Exception as exc:
        log.warning("status_projector: sad-phase derivation failed: %s", exc)
        return {"phase": "none", "status": "None", "next_due_at": None,
                "eligible": False, "waiting_for": None,
                "dsk_received_at": None, "reason": f"derive_error:{exc!s}"[:80]}


def _shipment_status(
    audit:    Dict[str, Any],
    active:   bool,
    state:    Dict[str, Any],
    now:      datetime,
) -> Tuple[str, Optional[datetime]]:
    """Compute drill-down status + next_due datetime.

    Status precedence (dhl phase):
      1. INACTIVE — shipment is not active (delivered / terminal / missing AWB)
      2. STOPPED  — dhl_followup.stopped_at present
      3. FAILED   — last followup event was a failure (most recent of the 3)
      4. SUPPRESSED — last followup event was a suppression
      5. ELIGIBLE — active + next_followup_at <= now
      6. MONITORING — active + next_followup_at > now
      7. WAITING  — active but no next_followup_at scheduled yet

    SAD-phase override:
      When the shipment is still active AND the dhl-phase status is
      STOPPED or WAITING AND the SAD-phase derivation reports phase
      "sad_followup", the row reports the SAD-phase status (eligible
      or monitoring) with the SAD-phase next_due. This prevents the
      silent Waiting / Stopped state when DSK has arrived but SAD/ZC429
      is still missing and follow-up IS required.
    """
    next_due = _parse_iso(state.get("next_followup_at"))
    if not active:
        return ST_INACTIVE, next_due
    if state.get("stopped_at"):
        # Original dhl phase is closed. Check whether the SAD phase
        # should take over for this row's status surface.
        sad = _sad_phase(audit, now)
        if sad.get("phase") == "sad_followup":
            sad_due = _parse_iso(sad.get("next_due_at"))
            return (ST_ELIGIBLE if sad.get("eligible") else ST_MONITORING), sad_due
        return ST_STOPPED, next_due

    # Look at last followup-related timeline event for failure/suppression flag
    last_evt = _latest_followup_event(audit)
    if last_evt:
        ev = last_evt.get("event") or ""
        if ev == EV_FAILED:
            return ST_FAILED, next_due
        if ev == EV_SUPPRESSED:
            return ST_SUPPRESSED, next_due

    if next_due is None:
        # No dhl-phase schedule yet. SAD phase may still apply when DSK
        # arrived without ever running the dhl-phase SLA (manual upload,
        # backfill, evidence-only). Surface SAD eligibility instead of a
        # silent Waiting.
        sad = _sad_phase(audit, now)
        if sad.get("phase") == "sad_followup":
            sad_due = _parse_iso(sad.get("next_due_at"))
            return (ST_ELIGIBLE if sad.get("eligible") else ST_MONITORING), sad_due
        return ST_WAITING, None
    if next_due <= now:
        return ST_ELIGIBLE, next_due
    return ST_MONITORING, next_due


def _latest_followup_event(audit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tl = audit.get("timeline") or []
    if not isinstance(tl, list):
        return None
    for evt in reversed(tl):
        if not isinstance(evt, dict):
            continue
        if evt.get("event") in (EV_SENT, EV_SUPPRESSED, EV_FAILED, EV_STOPPED):
            return evt
    return None


def _latest_event_of_type(
    audits: List[Dict[str, Any]],
    event_type: str,
) -> Optional[Dict[str, Any]]:
    """Find the most recent event of a given type across all audits.

    Returns a dict {ts, awb, batch_id, detail} or None.
    """
    best: Optional[Dict[str, Any]] = None
    best_ts: Optional[datetime] = None
    for audit in audits:
        tl = audit.get("timeline") or []
        if not isinstance(tl, list):
            continue
        for evt in tl:
            if not isinstance(evt, dict):
                continue
            if evt.get("event") != event_type:
                continue
            ts = _parse_iso(evt.get("ts"))
            if ts is None:
                continue
            if best_ts is None or ts > best_ts:
                best_ts = ts
                best = {
                    "ts":       evt.get("ts"),
                    "awb":      _awb_of(audit),
                    "batch_id": str(audit.get("batch_id") or ""),
                    "actor":    evt.get("actor"),
                    "detail":   evt.get("detail") or {},
                }
    return best


def _count_events_today(
    audits: List[Dict[str, Any]],
    event_type: str,
    now: datetime,
) -> int:
    """Count events of a type whose ts >= start-of-day-UTC."""
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    n = 0
    for audit in audits:
        tl = audit.get("timeline") or []
        if not isinstance(tl, list):
            continue
        for evt in tl:
            if not isinstance(evt, dict):
                continue
            if evt.get("event") != event_type:
                continue
            ts = _parse_iso(evt.get("ts"))
            if ts is None:
                continue
            if ts >= start_of_day:
                n += 1
    return n


def _count_ai_used_today(audits: List[Dict[str, Any]], now: datetime) -> Tuple[int, int]:
    """Return (ai_used_count, ai_fallback_count) for today's followup sends."""
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    ai_used = 0
    fallback = 0
    for audit in audits:
        tl = audit.get("timeline") or []
        if not isinstance(tl, list):
            continue
        for evt in tl:
            if not isinstance(evt, dict):
                continue
            if evt.get("event") != EV_SENT:
                continue
            ts = _parse_iso(evt.get("ts"))
            if ts is None or ts < start_of_day:
                continue
            detail = evt.get("detail") or {}
            if detail.get("ai_used") is True:
                ai_used += 1
            elif detail.get("ai_used") is False:
                fallback += 1
    return ai_used, fallback


def _humanise_age(ts: Optional[datetime], now: datetime) -> Optional[str]:
    """Return human-readable age like '5 min ago', '2h 14m ago'.  None if ts is None."""
    if ts is None:
        return None
    delta = now - ts
    secs = int(delta.total_seconds())
    if secs < 0:
        # Future timestamp — use 'in Xm' framing
        secs = -secs
        if secs < 60:
            return f"in {secs}s"
        mins = secs // 60
        if mins < 60:
            return f"in {mins}m"
        hours = mins // 60
        rem_m = mins % 60
        return f"in {hours}h {rem_m}m"
    if secs < 60:
        return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins} min ago"
    hours = mins // 60
    rem_m = mins % 60
    if hours < 24:
        return f"{hours}h {rem_m}m ago"
    days = hours // 24
    return f"{days}d ago"


# ── Public API ───────────────────────────────────────────────────────────────

def project_automation_status(*, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Aggregate top-card shape.

    Returns dict with keys:
      flag_on:               bool
      status_label:          "ACTIVE" | "DISABLED"
      active_shipments:      int
      monitoring:            int  (active AND next_due in future)
      eligible_now:          int  (active AND next_due <= now)
      next_due:              {awb, batch_id, due_at, due_in_human} | None
      last_sent:             {ts, awb, batch_id, detail} | None
      last_suppressed:       {ts, awb, batch_id, detail} | None
      last_failure:          {ts, awb, batch_id, detail} | None
      sent_today:            int
      suppressed_today:      int
      failed_today:          int
      ai_used_today:         int
      ai_fallback_today:     int
      traffic_light:         {ready, waiting, problems}
      generated_at:          ISO8601
    """
    if now is None:
        now = _now_utc()

    flag_on = _flag_on()
    paths = _audit_paths()
    audits: List[Dict[str, Any]] = []
    for p in paths:
        a = _read_audit(p)
        if a is not None:
            audits.append(a)

    active_count    = 0
    monitoring      = 0
    eligible_now    = 0
    suppressed_now  = 0
    failed_now      = 0
    mode_automatic  = 0
    mode_manual     = 0
    mode_unset      = 0
    next_due_pick:  Optional[Tuple[datetime, str, str]] = None  # (dt, awb, batch_id)

    for audit in audits:
        active, _why = _is_active(audit)
        if not active:
            continue
        active_count += 1
        state = audit.get("dhl_followup") or {}
        status, next_dt = _shipment_status(audit, active, state, now)
        mf = _mode_fields(audit, flag_on)
        ms = mf["mode_state"]
        if ms == "automatic":
            mode_automatic += 1
        elif ms == "manual":
            mode_manual += 1
        else:
            mode_unset += 1
        if status == ST_MONITORING:
            monitoring += 1
            if next_dt and (next_due_pick is None or next_dt < next_due_pick[0]):
                next_due_pick = (
                    next_dt,
                    _awb_of(audit),
                    str(audit.get("batch_id") or ""),
                )
        elif status == ST_ELIGIBLE:
            eligible_now += 1
        elif status == ST_SUPPRESSED:
            suppressed_now += 1
        elif status == ST_FAILED:
            failed_now += 1

    last_sent       = _latest_event_of_type(audits, EV_SENT)
    last_suppressed = _latest_event_of_type(audits, EV_SUPPRESSED)
    last_failure    = _latest_event_of_type(audits, EV_FAILED)

    sent_today       = _count_events_today(audits, EV_SENT, now)
    suppressed_today = _count_events_today(audits, EV_SUPPRESSED, now)
    failed_today     = _count_events_today(audits, EV_FAILED, now)
    ai_used_today, ai_fallback_today = _count_ai_used_today(audits, now)

    next_due_obj: Optional[Dict[str, Any]] = None
    if next_due_pick:
        dt, awb, bid = next_due_pick
        next_due_obj = {
            "awb":           awb,
            "batch_id":      bid,
            "due_at":        dt.isoformat(),
            "due_in_human":  _humanise_age(dt, now),  # negative-age -> 'in Xh Ym'
        }

    return {
        "flag_on":           flag_on,
        "status_label":      "ACTIVE" if flag_on else "DISABLED",
        "active_shipments":  active_count,
        "monitoring":        monitoring,
        "eligible_now":      eligible_now,
        "next_due":          next_due_obj,
        "last_sent":         last_sent,
        "last_suppressed":   last_suppressed,
        "last_failure":      last_failure,
        "sent_today":        sent_today,
        "suppressed_today":  suppressed_today,
        "failed_today":      failed_today,
        "ai_used_today":     ai_used_today,
        "ai_fallback_today": ai_fallback_today,
        "traffic_light": {
            "ready":    eligible_now,
            "waiting":  monitoring,
            "problems": failed_now + suppressed_now,
        },
        "mode_distribution": {
            "automatic": mode_automatic,
            "manual":    mode_manual,
            "unset":     mode_unset,
        },
        # True iff global auto-send is on, there ARE active shipments,
        # but NONE of them have an explicit shipment-level mode set.
        # This is the "all-Manual looks like operator decision but is
        # actually default" misleading-UI condition.
        "missing_shipment_mode_warning": bool(
            flag_on
            and active_count > 0
            and (mode_automatic + mode_manual) == 0
        ),
        "generated_at":      now.isoformat(),
    }

    # B6 Authority injection (flag-gated additive key)
    try:
        from ..core.config import settings
        if getattr(settings, "dhl_followup_authority_advisory", False):
            from .dhl_followup_authority import summarize_followup_authority
            # Generate rows for summary (reusing existing logic)
            authority_rows = project_shipment_rows(now=now)
            result["authority_summary"] = summarize_followup_authority(authority_rows)
    except Exception as exc:
        log.warning("status_projector: authority_summary failed: %s", exc)

    return result


def project_shipment_rows(*, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Per-shipment drill-down rows (active shipments only).

    Each row:
      {
        awb, batch_id, mode, status, next_due_at, next_due_human,
        last_scan_at, last_scan_human, last_event_ts, last_event_type
      }

    Mode:
      Delegates to ``dhl_followup_mode.get_mode`` + ``is_mode_explicit``
      (PR #373 single authority). Each row exposes BOTH:

        - ``mode_state``: machine-readable ``"automatic" | "manual" | "unset"``
        - ``mode_label``: human-readable; truthfully distinguishes
          operator-set "Manual" from default-fallback "Default".

      The projector NEVER re-derives mode from active/stopped flags.
      ``mode`` is preserved as a back-compat alias for ``mode_label``.
    """
    if now is None:
        now = _now_utc()

    flag_on = _flag_on()
    rows: List[Dict[str, Any]] = []
    for p in _audit_paths():
        audit = _read_audit(p)
        if audit is None:
            continue
        active, _why = _is_active(audit)
        if not active:
            continue
        state = audit.get("dhl_followup") or {}
        status, next_dt = _shipment_status(audit, active, state, now)
        mf = _mode_fields(audit, flag_on)

        last_scan_dt = _parse_iso((audit.get("email_ingestion") or {}).get("last_scan_at"))
        last_evt = _latest_followup_event(audit)
        last_evt_ts   = last_evt.get("ts") if last_evt else None
        last_evt_type = last_evt.get("event") if last_evt else None

        sad = _sad_phase(audit, now)
        row_dict = {
            "awb":             _awb_of(audit),
            "batch_id":        str(audit.get("batch_id") or ""),
            "mode":            mf["mode_label"],  # back-compat alias
            "mode_label":      mf["mode_label"],
            "mode_state":      mf["mode_state"],
            "status":          status,
            "next_due_at":     next_dt.isoformat() if next_dt else None,
            "next_due_human":  _humanise_age(next_dt, now) if next_dt else None,
            "last_scan_at":    last_scan_dt.isoformat() if last_scan_dt else None,
            "last_scan_human": _humanise_age(last_scan_dt, now),
            "last_event_ts":   last_evt_ts,
            "last_event_type": last_evt_type,
            # SAD-phase surface (visibility only — operator-actionable truth
            # when DSK is in but SAD/ZC429 still pending). Read-only fields:
            # the V2 page renders them but never sends.
            "phase":               "sad_followup" if sad.get("phase") == "sad_followup" else "dhl_followup",
            "sad_followup_reason": sad.get("reason"),
            "waiting_for":         sad.get("waiting_for"),
            "dsk_received_at":     sad.get("dsk_received_at"),
        }

        # B6 Authority injection (flag-gated additive keys)
        try:
            from ..core.config import settings
            if getattr(settings, "dhl_followup_authority_advisory", False):
                from .dhl_followup_authority import derive_followup_authority
                authority_result = derive_followup_authority(row_dict)
                row_dict["followup_authority"] = authority_result["followup_authority"]
                row_dict["authority_reason"] = authority_result["authority_reason"]
                row_dict["authority_evidence"] = authority_result["authority_evidence"]
        except Exception as exc:
            log.warning("status_projector: row authority derivation failed: %s", exc)

        rows.append(row_dict)

    # Sort: ELIGIBLE first, then MONITORING by next_due asc, then others.
    status_order = {
        ST_ELIGIBLE:    0,
        ST_FAILED:      1,
        ST_SUPPRESSED:  2,
        ST_MONITORING:  3,
        ST_WAITING:     4,
        ST_STOPPED:     5,
        ST_INACTIVE:    6,
    }
    rows.sort(key=lambda r: (
        status_order.get(r["status"], 99),
        r.get("next_due_at") or "9999-99-99",
        r.get("awb") or "",
    ))
    return rows
