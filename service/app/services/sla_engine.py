"""
sla_engine.py — Timeline-Based SLA Checker
==========================================
Walks audit["timeline"] event arrays and computes elapsed time between
key clearance workflow stages. Returns SLA violations and warnings.

DISTINCTION from risk_detector.py:
  risk_detector.py   → checks direct timestamp fields on audit
                        (duty_notice_received_at, fedex_arrival_at, etc.)
  sla_engine.py      → walks the structured timeline[] event log
                        and computes time between sequential events

This means sla_engine catches gaps that exist in the event log even when
the underlying fields are absent (e.g. carrier_arrived → no duty_note_received
within 72h — a gap visible in the timeline).

SLA benchmarks (from ONE_YEAR_CLEARANCE_DELAY_SLA_ANALYSIS.md):

  DHL Clearance (3–5 days total):
    arrival → ACS files SAD:        0–1 days (0–24h)
    SAD → ZC429/PZC issued:         1–2 days (24–48h)
    PZC → Ganther duty notice:      1–2 days (24–48h)
    Duty notice → payment:          0–1 days (0–24h, warning: >72h, critical: >168h)
    Payment → cargo released:       0–1 days (0–24h)
    Total DHL SLA:                  120h (5 days)

  FedEx Clearance (6–9 days total):
    arrival → cesja submission:     0–4 days (warning: >24h — human step)
    cesja submit → cesja ack:       immediate (automated)
    cesja ack → DSK to Ganther:     1 day
    DSK → SAD + PZC:                1 day
    PZC → duty + release:           2–3 days
    Total FedEx SLA:                216h (9 days)

READ-ONLY: Never writes to audit. All outputs are advisory warnings only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── SLA thresholds (hours) ─────────────────────────────────────────────────────

# Stage-level thresholds
_SLA_STAGE: Dict[str, Dict[str, int]] = {
    # DHL stages
    "arrival_to_sad": {
        "carrier": "DHL",
        "warning_h": 48,
        "critical_h": 96,
        "from_event": "carrier_arrived",
        "to_event":   "sad_uploaded",
        "code":       "SLA_ARRIVAL_TO_SAD",
        "label":      "Carrier arrived → SAD uploaded",
    },
    "sad_to_pzc": {
        "carrier": "DHL",
        "warning_h": 48,
        "critical_h": 72,
        "from_event": "sad_uploaded",
        "to_event":   "pzc_received",
        "code":       "SLA_SAD_TO_PZC",
        "label":      "SAD uploaded → PZC received",
    },
    "pzc_to_duty": {
        "carrier": "BOTH",
        "warning_h": 48,
        "critical_h": 72,
        "from_event": "pzc_received",
        "to_event":   "duty_note_received",
        "code":       "SLA_PZC_TO_DUTY",
        "label":      "PZC received → Duty notice received",
    },
    "duty_to_payment": {
        "carrier": "BOTH",
        "warning_h": 72,
        "critical_h": 168,
        "from_event": "duty_note_received",
        "to_event":   "payment_confirmed",
        "code":       "SLA_DUTY_TO_PAYMENT",
        "label":      "Duty notice → Payment confirmed",
    },
    "payment_to_release": {
        "carrier": "BOTH",
        "warning_h": 48,
        "critical_h": 96,
        "from_event": "payment_confirmed",
        "to_event":   "clearance_started",
        "code":       "SLA_PAYMENT_TO_RELEASE",
        "label":      "Payment confirmed → Clearance started",
    },
    # FedEx-specific stages
    "fedex_arrival_to_cesja": {
        "carrier": "FEDEX",
        "warning_h": 24,
        "critical_h": 48,
        "from_event": "carrier_arrived",
        "to_event":   "cesja_submitted",
        "code":       "SLA_FEDEX_CESJA_DELAY",
        "label":      "FedEx arrived → Cesja submitted",
    },
    "fedex_cesja_to_dsk": {
        "carrier": "FEDEX",
        "warning_h": 48,
        "critical_h": 96,
        "from_event": "cesja_submitted",
        "to_event":   "dsk_received",
        "code":       "SLA_FEDEX_CESJA_TO_DSK",
        "label":      "Cesja submitted → DSK received",
    },
}

# Full clearance SLA (carrier arrived → clearance complete)
_FULL_SLA_DHL_H   = 120   # 5 days
_FULL_SLA_FEDEX_H = 216   # 9 days

# Timeline event → human-readable name mapping
_EVENT_LABELS: Dict[str, str] = {
    "carrier_arrived":          "Carrier arrived",
    "sad_uploaded":             "SAD uploaded",
    "pzc_received":             "PZC received",
    "duty_note_received":       "Duty notice received",
    "payment_confirmed":        "Payment confirmed",
    "clearance_started":        "Clearance started",
    "cesja_submitted":          "Cesja submitted",
    "dsk_received":             "DSK received",
    "fedex_cesja_pending":      "FedEx cesja pending",
    "dhl_cesja_forwarded":      "DHL cesja forwarded",
    "ganther_invoice_received": "Ganther invoice received",
}


# ── Warning builder ────────────────────────────────────────────────────────────

def _event(name: str, hours_ago: float, detail: Optional[Dict] = None) -> Dict[str, Any]:
    """Create a well-formed timeline event dict for use in tests and data construction.

    Args:
        name:       Event name matching the keys in _SLA_STAGE (e.g. "carrier_arrived").
        hours_ago:  How many hours in the past the event occurred.
        detail:     Optional extra fields (e.g. {"mrn": "26PL44302D005LJ4R0"}).

    Returns:
        {"event": name, "ts": <ISO 8601 UTC string>, "detail": {...}}

    Example::
        timeline = [
            _event("carrier_arrived", 120),
            _event("sad_uploaded",     96),
        ]
        warnings = check_sla(timeline, carrier="DHL")
    """
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {"event": name, "ts": ts, "detail": detail or {}}


def _warn(
    code: str,
    severity: str,
    message: str,
    detail: Optional[Dict] = None,
) -> Dict[str, Any]:
    return {
        "code":     code,
        "severity": severity,
        "message":  message,
        "detail":   detail or {},
        "source":   "sla_engine",
    }


# ── Timeline utilities ────────────────────────────────────────────────────────

def _parse_ts(ts_str: str) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except Exception:
        return None


def _find_event(timeline: List[Dict], event_name: str) -> Optional[Dict]:
    """Find the first occurrence of an event in the timeline."""
    for entry in timeline:
        if entry.get("event") == event_name:
            return entry
    return None


def _find_events(timeline: List[Dict], event_name: str) -> List[Dict]:
    """Find all occurrences of an event in the timeline."""
    return [e for e in timeline if e.get("event") == event_name]


def _hours_between(from_entry: Dict, to_entry: Dict) -> Optional[float]:
    """Compute hours elapsed between two timeline events."""
    t1 = _parse_ts(from_entry.get("ts", ""))
    t2 = _parse_ts(to_entry.get("ts", ""))
    if t1 is None or t2 is None:
        return None
    return (t2 - t1).total_seconds() / 3600.0


def _hours_since_event(entry: Dict) -> Optional[float]:
    """Compute hours elapsed since a timeline event until now."""
    ts = _parse_ts(entry.get("ts", ""))
    if ts is None:
        return None
    return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0


# ── Main SLA checker ──────────────────────────────────────────────────────────

def check_sla(
    timeline: List[Dict[str, Any]],
    carrier: str = "DHL",
    awb: Optional[str] = None,
    batch_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Check SLA compliance from audit timeline events.

    SAFE: Read-only. Returns warnings only — never writes to audit.

    Args:
        timeline:  audit["timeline"] — list of {event, ts, detail} dicts
        carrier:   "DHL" | "FEDEX" (default: "DHL")
        awb:       AWB number for context in warning messages
        batch_id:  Batch ID for context

    Returns:
        List of warning dicts, sorted HIGH severity first.
        Each warning has: code, severity, message, detail, source
    """
    if not timeline:
        return []

    carrier_up = carrier.upper()
    warnings: List[Dict[str, Any]] = []
    ctx = {}
    if awb:
        ctx["awb"] = awb
    if batch_id:
        ctx["batch_id"] = batch_id

    # ── Stage-by-stage checks ─────────────────────────────────────────────────
    for stage_key, stage in _SLA_STAGE.items():
        # Skip FedEx stages for DHL batches and vice versa
        stage_carrier = stage["carrier"]
        if stage_carrier == "DHL" and carrier_up == "FEDEX":
            continue
        if stage_carrier == "FEDEX" and carrier_up == "DHL":
            continue

        from_ev = _find_event(timeline, stage["from_event"])
        to_ev   = _find_event(timeline, stage["to_event"])

        if from_ev is None:
            continue  # Stage hasn't started yet — not a violation

        if to_ev is not None:
            # Both events found — check actual elapsed time
            elapsed = _hours_between(from_ev, to_ev)
            if elapsed is None:
                continue
            if elapsed > stage["critical_h"]:
                warnings.append(_warn(
                    stage["code"],
                    "HIGH",
                    f"{stage['label']}: took {elapsed:.0f}h (critical threshold: {stage['critical_h']}h).",
                    {**ctx, "from_event": stage["from_event"], "to_event": stage["to_event"],
                     "elapsed_h": round(elapsed, 1), "threshold_h": stage["critical_h"]},
                ))
            elif elapsed > stage["warning_h"]:
                warnings.append(_warn(
                    stage["code"],
                    "MEDIUM",
                    f"{stage['label']}: took {elapsed:.0f}h (warning threshold: {stage['warning_h']}h).",
                    {**ctx, "from_event": stage["from_event"], "to_event": stage["to_event"],
                     "elapsed_h": round(elapsed, 1), "threshold_h": stage["warning_h"]},
                ))
        else:
            # Stage started but not completed — check elapsed time since start
            elapsed = _hours_since_event(from_ev)
            if elapsed is None:
                continue
            if elapsed > stage["critical_h"]:
                warnings.append(_warn(
                    f"{stage['code']}_MISSING",
                    "HIGH",
                    f"{stage['label']}: {elapsed:.0f}h elapsed since '{stage['from_event']}' — "
                    f"'{stage['to_event']}' not yet recorded (threshold: {stage['critical_h']}h).",
                    {**ctx, "from_event": stage["from_event"], "to_event": stage["to_event"],
                     "elapsed_h": round(elapsed, 1), "threshold_h": stage["critical_h"],
                     "status": "awaiting_completion"},
                ))
            elif elapsed > stage["warning_h"]:
                warnings.append(_warn(
                    f"{stage['code']}_PENDING",
                    "MEDIUM",
                    f"{stage['label']}: {elapsed:.0f}h elapsed since '{stage['from_event']}' — "
                    f"'{stage['to_event']}' not yet recorded (warning: {stage['warning_h']}h).",
                    {**ctx, "from_event": stage["from_event"], "to_event": stage["to_event"],
                     "elapsed_h": round(elapsed, 1), "threshold_h": stage["warning_h"],
                     "status": "awaiting_completion"},
                ))

    # ── Full clearance SLA ────────────────────────────────────────────────────
    arrival_ev   = _find_event(timeline, "carrier_arrived")
    clearance_ev = _find_event(timeline, "clearance_started")

    if arrival_ev and not clearance_ev:
        full_sla = _FULL_SLA_DHL_H if carrier_up == "DHL" else _FULL_SLA_FEDEX_H
        elapsed  = _hours_since_event(arrival_ev)
        if elapsed is not None and elapsed > full_sla:
            warnings.append(_warn(
                "SLA_FULL_CLEARANCE_BREACH",
                "HIGH",
                f"Full clearance SLA breached: {elapsed:.0f}h since arrival "
                f"(SLA={full_sla}h for {carrier_up}). Clearance not yet started.",
                {**ctx, "arrived_at": arrival_ev.get("ts"), "elapsed_h": round(elapsed, 1),
                 "sla_h": full_sla, "carrier": carrier_up},
            ))
        elif elapsed is not None and elapsed > full_sla * 0.8:
            warnings.append(_warn(
                "SLA_FULL_CLEARANCE_AT_RISK",
                "MEDIUM",
                f"Clearance approaching SLA: {elapsed:.0f}h since arrival "
                f"({full_sla}h limit for {carrier_up}).",
                {**ctx, "arrived_at": arrival_ev.get("ts"), "elapsed_h": round(elapsed, 1),
                 "sla_h": full_sla, "carrier": carrier_up},
            ))

    # ── Ganther invoice overdue check ─────────────────────────────────────────
    inv_events = _find_events(timeline, "ganther_invoice_received")
    for inv_ev in inv_events:
        elapsed = _hours_since_event(inv_ev)
        if elapsed is not None and elapsed > 24 * 14:  # 14 days
            warnings.append(_warn(
                "SLA_GANTHER_INVOICE_OVERDUE",
                "MEDIUM",
                f"Ganther invoice unpaid for {elapsed/24:.0f} days. "
                f"Historical pattern: 2,962 PLN accumulated from delayed payment (Jan 2026).",
                {**ctx, "invoice_ts": inv_ev.get("ts"), "days_unpaid": round(elapsed/24, 1)},
            ))

    # ── Sort HIGH → MEDIUM → LOW ──────────────────────────────────────────────
    _order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    warnings.sort(key=lambda w: _order.get(w["severity"], 3))

    return warnings


# ── Summary helpers ───────────────────────────────────────────────────────────

def compute_stage_durations(
    timeline: List[Dict[str, Any]],
) -> Dict[str, Optional[float]]:
    """
    Compute elapsed hours for each defined stage in the timeline.

    Returns {stage_key: elapsed_hours | None} for all known stages.
    None means the stage cannot be computed (from/to event absent or no timestamp).
    """
    result: Dict[str, Optional[float]] = {}
    for stage_key, stage in _SLA_STAGE.items():
        from_ev = _find_event(timeline, stage["from_event"])
        to_ev   = _find_event(timeline, stage["to_event"])
        if from_ev is not None and to_ev is not None:
            result[stage_key] = _hours_between(from_ev, to_ev)
        else:
            result[stage_key] = None
    return result


def get_sla_summary(
    timeline: List[Dict[str, Any]],
    carrier: str = "DHL",
) -> Dict[str, Any]:
    """
    Return a structured summary of SLA status for a single batch timeline.

    Returns:
        {
          "carrier":           str,
          "stage_durations_h": {stage_key: hours | None},
          "violations":        int,      # stages over critical threshold
          "at_risk":           int,      # stages over warning threshold
          "total_elapsed_h":   float | None,
          "full_sla_h":        int,
          "full_sla_pct":      float | None,   # % of SLA consumed
        }
    """
    carrier_up = carrier.upper()
    full_sla   = _FULL_SLA_DHL_H if carrier_up == "DHL" else _FULL_SLA_FEDEX_H
    durations  = compute_stage_durations(timeline)

    arrival_ev   = _find_event(timeline, "carrier_arrived")
    clearance_ev = _find_event(timeline, "clearance_started")

    total_elapsed: Optional[float] = None
    if arrival_ev and clearance_ev:
        total_elapsed = _hours_between(arrival_ev, clearance_ev)
    elif arrival_ev:
        total_elapsed = _hours_since_event(arrival_ev)

    warnings = check_sla(timeline, carrier=carrier)
    violations = sum(1 for w in warnings if w["severity"] == "HIGH")
    at_risk    = sum(1 for w in warnings if w["severity"] == "MEDIUM")

    return {
        "carrier":           carrier_up,
        "stage_durations_h": durations,
        "violations":        violations,
        "at_risk":           at_risk,
        "total_elapsed_h":   round(total_elapsed, 1) if total_elapsed is not None else None,
        "full_sla_h":        full_sla,
        "full_sla_pct":      round(total_elapsed / full_sla * 100, 1) if total_elapsed else None,
    }
