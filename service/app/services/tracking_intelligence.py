"""
tracking_intelligence.py — Time-based follow-up intelligence for DHL shipments.

Reads the normalized DHL event stream and decides:
  - what stage the shipment is in
  - what event is expected next
  - how long that should take
  - whether the current state is delayed
  - what action the operator should take next

This is purely advisory — it does not mutate audit state. The dashboard
reads the result and renders a "Next Expected Action" panel.

Public API:
    evaluate_tracking_intelligence(events, audit=None) -> dict
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ── Stage rules ──────────────────────────────────────────────────────────────
# Each rule: (location_substr_or_status, stage_label, expected_next, expected_within_hours, recommended_action)
# Order matters — first match wins. Bias toward terminal/late stages so we
# always pick the most-advanced applicable rule.

_STAGE_RULES: List[Dict[str, Any]] = [
    {
        "match_status":   "delivered",
        "stage":          "delivered",
        "expected_next":  None,
        "expected_within_hours": None,
        "action":         "Stop tracking. Confirm POD on file.",
    },
    {
        "match_status":   "out_for_delivery",
        "stage":          "out_for_delivery",
        "expected_next":  "delivered",
        "expected_within_hours": 12,
        "action":         "Wait for delivery confirmation.",
    },
    {
        "match_status":   "cleared",
        "stage":          "customs_cleared",
        "expected_next":  "out_for_delivery",
        "expected_within_hours": 24,
        "action":         "Customs cleared — courier handover imminent.",
    },
    {
        "match_status":   "in_customs",
        "stage":          "in_customs",
        "expected_next":  "clearance_complete",
        "expected_within_hours": 48,
        "action":         "Customs processing in progress. If >48h, contact agency.",
    },
    {
        "match_location": "WARSAW",
        "stage":          "at_warsaw",
        "expected_next":  "DHL customs notification email",
        "expected_within_hours": 6,
        "action":         "Expect DHL Agencja Celna email shortly. If not received in 6h, run 'Find DHL Emails'.",
    },
    {
        "match_location": "LEIPZIG",
        "stage":          "transit_eu_hub",
        "expected_next":  "Arrival at Warsaw",
        "expected_within_hours": 24,
        "action":         "In EU hub — Warsaw arrival expected within 24h.",
    },
    {
        "match_location": "HONG KONG",
        "stage":          "transit_asia_hub",
        "expected_next":  "Departure for EU (Leipzig)",
        "expected_within_hours": 18,
        "action":         "In Asia hub — EU leg starts within ~18h.",
    },
    {
        "match_location": "MUMBAI",
        "stage":          "origin_dispatched",
        "expected_next":  "Arrival at Hong Kong",
        "expected_within_hours": 12,
        "action":         "Departed origin — HK arrival within ~12h.",
    },
]


def _last_event(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return the most-recent event from a sorted-ASC list, or {}."""
    return events[-1] if events else {}


def _hours_since(ts: Optional[str]) -> Optional[float]:
    """Hours elapsed since `ts` (ISO 8601). None if ts is missing/unparseable."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except Exception:
        return None


def _pick_rule(
    last_status:   str,
    last_location: str,
) -> Dict[str, Any]:
    """Find the first matching stage rule for the last event."""
    status_lower = (last_status or "").lower()
    loc_upper    = (last_location or "").upper()
    for rule in _STAGE_RULES:
        if rule.get("match_status") and rule["match_status"] == status_lower:
            return rule
    for rule in _STAGE_RULES:
        if rule.get("match_location") and rule["match_location"] in loc_upper:
            return rule
    return {
        "stage":                  "in_transit",
        "expected_next":          "Next checkpoint",
        "expected_within_hours":  24,
        "action":                 "Standard transit. Re-check in 24h.",
    }


# ── Trigger detection ────────────────────────────────────────────────────────
# Tracking events that indicate a customs workflow has started — these MUST
# trigger an immediate DHL email scan, not just a UI hint.

_CUSTOMS_TRIGGER_PHRASES: List[str] = [
    "customs clearance status updated",
    "clearance event",
    "processed for clearance",
    "shipment is on hold",   # only when customs context — see below
    "customs status updated",
    "released by customs",
]

# Phrases that contextualize an "on hold" event as customs-related
_ON_HOLD_CUSTOMS_CONTEXT: List[str] = [
    "customs",
    "clearance",
    "broker",
    "duty",
    "agencja",
]


def _matches_customs_trigger(description: str) -> bool:
    """True if the event description signals a customs-workflow trigger."""
    if not description:
        return False
    d = description.lower()
    for phrase in _CUSTOMS_TRIGGER_PHRASES:
        if phrase == "shipment is on hold":
            if phrase in d and any(c in d for c in _ON_HOLD_CUSTOMS_CONTEXT):
                return True
        elif phrase in d:
            return True
    return False


def detect_tracking_triggers(
    events: List[Dict[str, Any]],
    audit:  Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Inspect the event stream and return a list of action triggers.

    Triggers:
      DHL_CUSTOMS_EMAIL_CHECK_REQUIRED
          A customs-related tracking event was seen → run email scan now.
      DESTINATION_COUNTRY_REACHED
          Shipment hit Warsaw/Poland → DHL email expected within 6h.

    Returns an empty list when nothing actionable was found. Read-only.
    """
    out: List[Dict[str, Any]] = []
    if not events:
        return out

    awb = ""
    if audit:
        awb = (
            audit.get("awb")
            or audit.get("tracking_no")
            or (audit.get("batch_meta") or {}).get("awb")
            or ""
        )

    # Walk newest-first to get the most recent customs trigger
    customs_triggered = False
    for ev in reversed(events):
        desc = ev.get("description", "") or ev.get("status", "")
        if _matches_customs_trigger(desc):
            out.append({
                "trigger":    "DHL_CUSTOMS_EMAIL_CHECK_REQUIRED",
                "awb":        awb,
                "event_time": ev.get("timestamp"),
                "location":   ev.get("location", ""),
                "description": desc,
                "reason":     "DHL tracking indicates customs process started",
            })
            customs_triggered = True
            break  # one customs trigger is enough; latest wins

    # Destination arrival — only emit if not already triggered above for the
    # same event (avoids redundancy when "Customs clearance status updated"
    # itself happened at Warsaw)
    last = events[-1]
    last_loc = (last.get("location", "") or "").upper()
    if ("WARSAW" in last_loc or "POLAND" in last_loc) and not customs_triggered:
        # Skip if DHL email already received (no point re-flagging)
        already_received = bool((audit or {}).get("dhl_email", {}).get("received"))
        if not already_received:
            out.append({
                "trigger":         "DESTINATION_COUNTRY_REACHED",
                "awb":             awb,
                "event_time":      last.get("timestamp"),
                "location":        last.get("location", ""),
                "expected_action": "check_dhl_email",
                "reason":          "Shipment at destination — DHL customs email expected within 6h",
            })

    return out


def evaluate_tracking_intelligence(
    events: List[Dict[str, Any]],
    audit:  Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evaluate the current tracking state and produce an intelligence summary.

    Args:
        events: normalized DHL event list (sorted ASC), each with
                {timestamp, location, status, description}.
        audit:  optional batch audit dict for cross-references (e.g.
                clearance_status, dhl_email presence). Used to refine
                recommended_action for the at_warsaw stage.

    Returns:
        dict with keys:
          stage                  — e.g. transit_eu_hub / at_warsaw / delivered
          last_location          — last known location
          last_event_at          — ISO timestamp of last event
          hours_since_last_event — float, None if unknown
          expected_next          — human-readable next event description
          expected_within_hours  — int, max time before delay flag fires
          delay_flag             — bool, true when overdue
          delay_hours            — float, how many hours overdue (>=0)
          recommended_action     — string operator hint
    """
    last = _last_event(events) if events else {}
    last_status   = last.get("status", "")
    last_location = last.get("location", "")
    last_ts       = last.get("timestamp")
    elapsed       = _hours_since(last_ts)

    rule = _pick_rule(last_status, last_location)

    expected_within = rule.get("expected_within_hours")
    delay_flag      = False
    delay_hours     = 0.0
    if expected_within is not None and elapsed is not None and elapsed > expected_within:
        delay_flag  = True
        delay_hours = round(elapsed - expected_within, 1)

    # Stage-specific audit-aware refinement
    action = rule.get("action", "")
    if rule.get("stage") == "at_warsaw" and audit is not None:
        if (audit.get("dhl_email") or {}).get("received"):
            action = "DHL email already received — proceed with clearance flow."
        elif delay_flag:
            action = (
                f"DHL email overdue by {delay_hours:.1f}h. Run 'Find DHL Emails' "
                "or contact DHL Agencja Celna directly."
            )

    return {
        "stage":                  rule.get("stage", "unknown"),
        "last_location":          last_location,
        "last_event_at":          last_ts,
        "hours_since_last_event": round(elapsed, 1) if elapsed is not None else None,
        "expected_next":          rule.get("expected_next"),
        "expected_within_hours":  expected_within,
        "delay_flag":             delay_flag,
        "delay_hours":            delay_hours,
        "recommended_action":     action,
    }
