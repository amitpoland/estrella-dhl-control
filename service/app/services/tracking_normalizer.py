"""
tracking_normalizer.py — Standardized goods-movement event model.

Responsibilities:
  - Define normalized movement stages (STAGE_ORDER)
  - Map raw DHL / public / manual wording to stages (normalize_tracking_event)
  - Append normalized events to audit.tracking_events with deduplication
  - Apply workflow-progression flags based on reached stages
  - Emit exactly two operator-meaningful timeline milestones from tracking
    state (carrier_arrived_poland, carrier_delivered)

Storage contract:
  audit.json["tracking_events"] is a chronological list of normalized events.
  Never overwrites — only appends. Dedup key: (awb, event_time, raw_description, source).

Timeline milestone contract (locked invariants — see _MILESTONE_ALLOWLIST):
  - tracking_normalizer may write ONLY the events in _MILESTONE_ALLOWLIST.
  - dedup oracle = scan of audit["timeline"] for the dedup key.
  - canonical dedup key = (event_name, detail["milestone_ts"]).
  - audit side-fields (carrier_arrived_at_poland_at, shipment_delivered) are
    advisory mirrors — NEVER consulted for milestone dedup decisions.
  - clearance_status is NOT mutated by this module.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

# ── Normalized movement stages ────────────────────────────────────────────────

STAGE_ORDER: List[str] = [
    "SHIPMENT_CREATED",
    "LABEL_CREATED",
    "PICKED_UP",
    "DEPARTED_ORIGIN",
    "ARRIVED_ORIGIN_HUB",
    "DEPARTED_ORIGIN_HUB",
    "IN_TRANSIT",
    "ARRIVED_DESTINATION_COUNTRY",
    "CUSTOMS_PENDING",
    "CUSTOMS_DOCUMENTS_REQUESTED",
    "CUSTOMS_DOCUMENTS_SENT",
    "CUSTOMS_UNDER_REVIEW",
    "CUSTOMS_CLEARED",
    "HANDED_TO_BROKER",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "EXCEPTION",
    "CLOSED",
]

_STAGE_RANK: Dict[str, int] = {s: i for i, s in enumerate(STAGE_ORDER)}

VALID_STAGES: FrozenSet[str] = frozenset(STAGE_ORDER)

VALID_SOURCES: FrozenSet[str] = frozenset(
    {"dhl_api", "public_tracking", "manual", "email", "system"}
)

# Stages that enable the customs document workflow
CUSTOMS_WORKFLOW_STAGES: FrozenSet[str] = frozenset({
    "CUSTOMS_DOCUMENTS_REQUESTED",
    "CUSTOMS_DOCUMENTS_SENT",
    "CUSTOMS_UNDER_REVIEW",
    "CUSTOMS_CLEARED",
})

# ── DHL self-clearance signal tokens (W-5 / P0 — ADR-013 / P3 watcher input) ──
#
# Additive vocabulary, layered on top of STAGE_ORDER. These are *signal* tokens
# the P3 tracking watcher will react to (P0 introduces only the vocabulary +
# detection rules; P3 wires the reactor).
#
# Locked at P0 (consumers in P2-P5 must reference these literals verbatim):
SIGNAL_POLAND_ARRIVAL:     str = "poland_arrival"
SIGNAL_CUSTOMS_PROCESSING: str = "customs_processing"
SIGNAL_CUSTOMS_HOLD:       str = "customs_hold"
SIGNAL_DELAY:              str = "delay"
SIGNAL_REJECTED_PAPERWORK: str = "rejected_paperwork"

SELFCLEARANCE_SIGNAL_TOKENS: FrozenSet[str] = frozenset({
    SIGNAL_POLAND_ARRIVAL,
    SIGNAL_CUSTOMS_PROCESSING,
    SIGNAL_CUSTOMS_HOLD,
    SIGNAL_DELAY,
    SIGNAL_REJECTED_PAPERWORK,
})

# Substring detection rules for emitting self-clearance signal tokens.
# Independent of _NORMALIZE_RULES (those map to STAGE_ORDER). These rules run
# AGAINST the same raw_description + raw_status blob and return the set of
# matched tokens (a single event may emit multiple tokens; e.g. a customs hold
# *and* a delay).
_SIGNAL_RULES: List[Tuple[str, str]] = [
    # poland_arrival — destination country is Poland on this event
    # (also detected by tracking_normalizer milestone emitter via location,
    # but the signal token is convenient for the P3 watcher to consume directly)
    ("arrived at destination country - poland",  SIGNAL_POLAND_ARRIVAL),
    ("arrived warsaw",                           SIGNAL_POLAND_ARRIVAL),
    # customs_processing — customs is actively reviewing
    ("under customs review",                     SIGNAL_CUSTOMS_PROCESSING),
    ("customs processing",                       SIGNAL_CUSTOMS_PROCESSING),
    ("customs status updated",                   SIGNAL_CUSTOMS_PROCESSING),
    # customs_hold — shipment held / clearance blocked
    ("clearance on hold",                        SIGNAL_CUSTOMS_HOLD),
    ("held by customs",                          SIGNAL_CUSTOMS_HOLD),
    ("shipment on hold",                         SIGNAL_CUSTOMS_HOLD),
    # delay — general delay / exception markers
    ("shipment delayed",                         SIGNAL_DELAY),
    ("delivery delayed",                         SIGNAL_DELAY),
    ("delay in transit",                         SIGNAL_DELAY),
    # rejected_paperwork — customs returned the documents
    ("documents rejected",                       SIGNAL_REJECTED_PAPERWORK),
    ("paperwork rejected",                       SIGNAL_REJECTED_PAPERWORK),
    ("clearance rejected",                       SIGNAL_REJECTED_PAPERWORK),
    ("incorrect documentation",                  SIGNAL_REJECTED_PAPERWORK),
]


def extract_selfclearance_signals(raw_event: Dict[str, Any]) -> FrozenSet[str]:
    """
    Inspect a raw tracking event dict and return the set of self-clearance
    signal tokens detected. Empty frozenset if none matched.

    Pure function. Reads only raw_description / description / status. Does
    not mutate the event, does not consult location (callers can do that).
    """
    raw_description = (
        raw_event.get("raw_description")
        or raw_event.get("description")
        or raw_event.get("status")
        or raw_event.get("statusCode")
        or ""
    )
    raw_status = (
        raw_event.get("raw_status")
        or raw_event.get("status")
        or raw_event.get("statusCode")
        or ""
    )
    blob = (str(raw_description) + " " + str(raw_status)).lower()
    found: set = set()
    for phrase, token in _SIGNAL_RULES:
        if phrase in blob:
            found.add(token)
    # Poland arrival is also detectable via location country code.
    loc = raw_event.get("location") or raw_event.get("loc") or ""
    if _country_code_from_location(str(loc)) == "PL":
        found.add(SIGNAL_POLAND_ARRIVAL)
    return frozenset(found)

# ── Timeline milestone allowlist (LOCKED — runtime-enforced) ──────────────────
# tracking_normalizer may write ONLY these events into audit["timeline"].
# Any other event name passed to _emit_milestone raises ValueError.
# Extending this set requires fresh architecture review — adding a transport-
# class event here would reintroduce the timeline/tracking_events drift problem
# the architecture-correction cycle was designed to prevent.
_MILESTONE_ALLOWLIST: FrozenSet[str] = frozenset({
    "carrier_arrived_poland",
    "carrier_delivered",
})

# ── Normalization rules ───────────────────────────────────────────────────────
# Ordered most-specific first.
# Each entry: (lower-cased substring, normalized_stage, confidence 0.0–1.0)

_NORMALIZE_RULES: List[Tuple[str, str, float]] = [
    # Delivery — most terminal, highest priority
    ("delivered",                                  "DELIVERED",                   1.0),
    # Out for delivery
    ("with delivery courier",                      "OUT_FOR_DELIVERY",            1.0),
    ("out for delivery",                           "OUT_FOR_DELIVERY",            1.0),
    ("delivery in progress",                       "OUT_FOR_DELIVERY",            0.9),
    # Customs cleared
    ("clearance processing complete",              "CUSTOMS_CLEARED",             1.0),
    ("released by customs",                        "CUSTOMS_CLEARED",             1.0),
    ("customs clearance successful",               "CUSTOMS_CLEARED",             1.0),
    ("clearance complete",                         "CUSTOMS_CLEARED",             0.9),
    # Customs documents requested
    ("further clearance processing is required",   "CUSTOMS_DOCUMENTS_REQUESTED", 1.0),
    ("additional information required",            "CUSTOMS_DOCUMENTS_REQUESTED", 0.9),
    ("documents required",                         "CUSTOMS_DOCUMENTS_REQUESTED", 0.9),
    ("awaiting customs documents",                 "CUSTOMS_DOCUMENTS_REQUESTED", 1.0),
    # Customs documents sent (system-generated when operator sends docs)
    ("documents submitted",                        "CUSTOMS_DOCUMENTS_SENT",      1.0),
    ("customs documents sent",                     "CUSTOMS_DOCUMENTS_SENT",      1.0),
    # Customs under review
    ("customs status updated",                     "CUSTOMS_UNDER_REVIEW",        0.9),
    ("under customs review",                       "CUSTOMS_UNDER_REVIEW",        1.0),
    ("customs processing",                         "CUSTOMS_UNDER_REVIEW",        0.85),
    # Customs pending — generic customs hit
    ("clearance event",                            "CUSTOMS_PENDING",             0.9),
    ("customs",                                    "CUSTOMS_PENDING",             0.7),
    # Arrived at destination country
    ("arrived at destination country",             "ARRIVED_DESTINATION_COUNTRY", 1.0),
    ("arrived at customs",                         "ARRIVED_DESTINATION_COUNTRY", 0.9),
    ("arrived destination",                        "ARRIVED_DESTINATION_COUNTRY", 0.85),
    # Hub transitions
    ("departed facility",                          "DEPARTED_ORIGIN_HUB",         0.9),
    ("departed",                                   "DEPARTED_ORIGIN",             0.8),
    ("arrived at facility",                        "ARRIVED_ORIGIN_HUB",          0.85),
    ("arrived at",                                 "ARRIVED_ORIGIN_HUB",          0.75),
    # In transit / facility processing
    ("processed at facility",                      "IN_TRANSIT",                  0.9),
    ("processed at",                               "IN_TRANSIT",                  0.85),
    ("in transit",                                 "IN_TRANSIT",                  0.9),
    ("transit",                                    "IN_TRANSIT",                  0.75),
    # Picked up
    ("shipment picked up",                         "PICKED_UP",                   1.0),
    ("picked up",                                  "PICKED_UP",                   0.9),
    ("collected by dhl",                           "PICKED_UP",                   1.0),
    ("collected",                                  "PICKED_UP",                   0.8),
    # Label / pre-shipment
    ("shipment information received",              "LABEL_CREATED",               1.0),
    ("shipment information transmitted",           "LABEL_CREATED",               1.0),
    ("electronic notification received",           "LABEL_CREATED",               0.9),
    ("label created",                              "LABEL_CREATED",               1.0),
    ("label printed",                              "LABEL_CREATED",               0.95),
    ("order processed",                            "SHIPMENT_CREATED",            0.85),
]

# ── Stage colour palette (for the dashboard) ──────────────────────────────────

STAGE_COLORS: Dict[str, str] = {
    "SHIPMENT_CREATED":            "#6b7280",
    "LABEL_CREATED":               "#6b7280",
    "PICKED_UP":                   "#2563eb",
    "DEPARTED_ORIGIN":             "#2563eb",
    "ARRIVED_ORIGIN_HUB":          "#2563eb",
    "DEPARTED_ORIGIN_HUB":         "#2563eb",
    "IN_TRANSIT":                  "#2563eb",
    "ARRIVED_DESTINATION_COUNTRY": "#0891b2",
    "CUSTOMS_PENDING":             "#d97706",
    "CUSTOMS_DOCUMENTS_REQUESTED": "#dc2626",
    "CUSTOMS_DOCUMENTS_SENT":      "#16a34a",
    "CUSTOMS_UNDER_REVIEW":        "#d97706",
    "CUSTOMS_CLEARED":             "#16a34a",
    "HANDED_TO_BROKER":            "#7c3aed",
    "OUT_FOR_DELIVERY":            "#d97706",
    "DELIVERED":                   "#16a34a",
    "EXCEPTION":                   "#dc2626",
    "CLOSED":                      "#6b7280",
}


# ── Core functions ────────────────────────────────────────────────────────────

def stage_rank(stage: str) -> int:
    """Progression rank (0 = earliest). Unknown stages return -1."""
    return _STAGE_RANK.get(stage, -1)


def stage_ge(a: str, b: str) -> bool:
    """True if stage *a* is at least as advanced as stage *b*."""
    return stage_rank(a) >= stage_rank(b)


def normalize_tracking_event(
    raw_event: Dict[str, Any],
    *,
    source: str = "dhl_api",
    awb: str = "",
    batch_id: str = "",
) -> Dict[str, Any]:
    """
    Map a raw tracking event dict to the normalized event schema.

    Input keys (all optional — falls back gracefully):
      raw_description, description, status, statusCode,
      raw_status, timestamp, event_time, location, loc

    Returns a normalized event dict.
    confidence=0.0 and requires_manual_review=True when no rule matched.
    Manual events (source='manual') always set confidence=1.0 if stage is valid.
    """
    raw_description = (
        raw_event.get("raw_description")
        or raw_event.get("description")
        or raw_event.get("status")
        or raw_event.get("statusCode")
        or ""
    ).strip()
    raw_status = (
        raw_event.get("raw_status")
        or raw_event.get("status")
        or raw_event.get("statusCode")
        or ""
    ).strip()
    event_time = (
        raw_event.get("event_time")
        or raw_event.get("timestamp")
        or ""
    ).strip()
    location = (
        raw_event.get("location")
        or raw_event.get("loc")
        or ""
    ).strip()

    if source not in VALID_SOURCES:
        source = "manual"

    # Manual events may carry a pre-validated stage
    if source == "manual":
        explicit_stage = (raw_event.get("normalized_stage") or "").strip().upper()
        if explicit_stage in VALID_STAGES:
            return {
                "event_id":               _make_event_id(awb, event_time, raw_description, source),
                "batch_id":               batch_id,
                "awb":                    awb,
                "source":                 source,
                "raw_status":             raw_status or explicit_stage,
                "raw_description":        raw_description or explicit_stage.replace("_", " ").title(),
                "normalized_stage":       explicit_stage,
                "location":               location,
                "event_time":             event_time,
                "captured_at":            _now_utc(),
                "confidence":             1.0,
                "requires_manual_review": False,
            }

    blob = (raw_description + " " + raw_status).lower()
    matched_stage: str = "EXCEPTION"
    confidence: float = 0.0
    for keyword, stage, conf in _NORMALIZE_RULES:
        if keyword in blob:
            matched_stage = stage
            confidence = conf
            break

    return {
        "event_id":               _make_event_id(awb, event_time, raw_description, source),
        "batch_id":               batch_id,
        "awb":                    awb,
        "source":                 source,
        "raw_status":             raw_status,
        "raw_description":        raw_description,
        "normalized_stage":       matched_stage,
        "location":               location,
        "event_time":             event_time,
        "captured_at":            _now_utc(),
        "confidence":             confidence,
        "requires_manual_review": confidence == 0.0,
    }


def _make_event_id(awb: str, event_time: str, raw_description: str, source: str) -> str:
    """Stable 16-hex ID derived from the dedup key fields."""
    key = f"{awb}|{event_time}|{raw_description}|{source}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _dedup_key(event: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return (
        event.get("awb", ""),
        event.get("event_time", ""),
        event.get("raw_description", ""),
        event.get("source", ""),
    )


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_tracking_events(
    audit: Dict[str, Any],
    new_events: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], int]:
    """
    Append *new_events* to audit["tracking_events"], deduplicating by
    (awb, event_time, raw_description, source).

    Returns (updated_audit, added_count).
    """
    existing: List[Dict[str, Any]] = list(audit.get("tracking_events") or [])
    existing_keys = {_dedup_key(e) for e in existing}
    added = 0
    for ev in new_events:
        k = _dedup_key(ev)
        if k not in existing_keys:
            existing.append(ev)
            existing_keys.add(k)
            added += 1
    # Keep chronological order
    existing.sort(key=lambda e: (e.get("event_time") or "", e.get("captured_at") or ""))
    audit["tracking_events"] = existing
    return audit, added


def _country_code_from_location(loc: str) -> str:
    """
    Parse the 2-letter country code from a normalized DHL location string.

    Canonical DHL format:  "CITY - COUNTRY NAME - CC"
    Examples:
      "WARSAW - POLAND - PL"                 → "PL"
      "HONG KONG - HONG KONG SAR, CHINA - HK" → "HK"
      "MUMBAI (BOMBAY) - INDIA - IN"         → "IN"
      "LEIPZIG - GERMANY - DE"               → "DE"

    Returns "" when the location is empty, mis-formatted, or the trailing
    segment is not a 2-letter alphabetic code.

    Pure string operation — no I/O, no audit access.
    """
    if not loc:
        return ""
    # rsplit on " - " (space-dash-space) — strict separator used by DHL
    parts = loc.rsplit(" - ", 1)
    if len(parts) != 2:
        return ""
    cc = parts[1].strip().upper()
    if len(cc) == 2 and cc.isalpha():
        return cc
    return ""


def _emit_milestone(
    audit:        Dict[str, Any],
    event_name:   str,
    milestone_ts: str,
    detail:       Dict[str, Any],
) -> bool:
    """
    Append a transport-class milestone to audit["timeline"] iff its dedup key
    is not already present.

    Dedup oracle (binding):  scan audit["timeline"] for existing entries whose
                             event name is in _MILESTONE_ALLOWLIST and whose
                             detail["milestone_ts"] equals *milestone_ts*.
    Dedup key                = (event_name, milestone_ts).
    The dedup oracle is the timeline ITSELF — never side-fields, never the
    write timestamp, never cached state.

    Returns True if appended, False if dedup-skipped.
    Raises ValueError when *event_name* is not in _MILESTONE_ALLOWLIST.

    Schema (FROZEN — see milestone schema invariant):
      {
        "event":          <event_name>,
        "trigger_source": "dhl_api",
        "actor":          "system",
        "ts":             <append/write timestamp — NEVER used for dedup>,
        "detail":         {**detail, "milestone_ts": <canonical dedup ts>},
      }
    """
    if event_name not in _MILESTONE_ALLOWLIST:
        raise ValueError(
            f"tracking_normalizer cannot emit timeline event {event_name!r} — "
            f"only {sorted(_MILESTONE_ALLOWLIST)} are permitted. "
            f"Adding new transport-class timeline events requires architecture "
            f"review."
        )

    timeline: List[Dict[str, Any]] = audit.setdefault("timeline", [])

    # Build dedup-key set from the timeline ONLY (the canonical oracle).
    emitted_keys = {
        (
            e.get("event"),
            (e.get("detail") or {}).get("milestone_ts"),
        )
        for e in timeline
        if e.get("event") in _MILESTONE_ALLOWLIST
    }

    key = (event_name, milestone_ts)
    if key in emitted_keys:
        return False

    timeline.append({
        "event":          event_name,
        "trigger_source": "dhl_api",
        "actor":          "system",
        "ts":             _now_utc(),
        "detail":         {**detail, "milestone_ts": milestone_ts},
    })
    return True


def _earliest_event_time(events: List[Dict[str, Any]]) -> str:
    """Return the earliest non-empty event_time from *events*, or ""."""
    times = [e.get("event_time", "") for e in events if e.get("event_time")]
    if not times:
        return ""
    return min(times)


def apply_workflow_progression(
    audit: Dict[str, Any],
    events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Inspect tracking_events, set workflow flags (forward-only), and emit
    operator-meaningful milestones into audit["timeline"].

    Flags set (existing — unchanged):
      customs_workflow_eligible — any event in CUSTOMS_WORKFLOW_STAGES reached
      clearance_complete        — CUSTOMS_CLEARED reached
      shipment_delivered        — DELIVERED reached

    Milestones emitted into timeline (exactly-once per shipment, dedup'd by
    timeline-scan against (event_name, milestone_ts)):
      carrier_arrived_poland — earliest event with country_code == "PL"
      carrier_delivered      — earliest event with normalized_stage == "DELIVERED"

    Advisory side-fields written (mirrors only — NOT consulted for dedup):
      carrier_arrived_at_poland_at  ← earliest PL event_time
      shipment_delivered            ← bool flag (existing)

    This function does NOT mutate clearance_status — that is owned by the
    email/orchestration layer.

    Caller responsibility:
      In-memory mutation only. Persistence + locking live in the caller, OR
      use apply_workflow_progression_locked() which wraps load+mutate+write
      under the per-batch advisory lock.
    """
    if events is None:
        events = audit.get("tracking_events") or []

    stages = {e.get("normalized_stage") for e in events}

    if not audit.get("customs_workflow_eligible"):
        if stages & CUSTOMS_WORKFLOW_STAGES:
            audit["customs_workflow_eligible"] = True

    if not audit.get("clearance_complete"):
        if "CUSTOMS_CLEARED" in stages:
            audit["clearance_complete"] = True

    if not audit.get("shipment_delivered"):
        if "DELIVERED" in stages:
            audit["shipment_delivered"] = True

    awb = audit.get("awb") or audit.get("tracking_no") or ""

    # ── carrier_arrived_poland ────────────────────────────────────────────────
    pl_events = [
        e for e in events
        if _country_code_from_location(e.get("location", "")) == "PL"
    ]
    first_pl_event_time = _earliest_event_time(pl_events)
    if first_pl_event_time:
        appended = _emit_milestone(
            audit,
            "carrier_arrived_poland",
            first_pl_event_time,
            {
                "awb":                 awb,
                "first_pl_event_time": first_pl_event_time,
            },
        )
        # Advisory mirror — written only on first emission, never consulted
        # by dedup. Future runs continue to dedup against the timeline.
        if appended and not audit.get("carrier_arrived_at_poland_at"):
            audit["carrier_arrived_at_poland_at"] = first_pl_event_time

    # ── carrier_delivered ────────────────────────────────────────────────────
    delivered_events = [
        e for e in events if e.get("normalized_stage") == "DELIVERED"
    ]
    delivered_event_time = _earliest_event_time(delivered_events)
    if delivered_event_time:
        _emit_milestone(
            audit,
            "carrier_delivered",
            delivered_event_time,
            {
                "awb":                  awb,
                "delivered_event_time": delivered_event_time,
            },
        )

    return audit


def apply_workflow_progression_locked(
    batch_id:   str,
    *,
    audit_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Lock-aware wrapper around apply_workflow_progression for production callers.

    Acquires the per-batch advisory write lock, reads audit.json fresh,
    applies workflow progression (including milestone emission), and persists
    atomically. Exactly-once milestone emission is guaranteed by the
    combination of:
      1. timeline-scan dedup oracle inside _emit_milestone, and
      2. the per-batch flock serialising read/mutate/write across processes.

    Use this wrapper from any production code path where audit.json is
    persisted after milestone-touching mutation. The plain
    apply_workflow_progression() remains available for unit tests and
    in-memory composition (e.g. callers that already hold the lock).
    """
    # Local imports to avoid hard coupling at module load time and keep the
    # tests that import only the pure helpers fast.
    from ..core.config import settings
    from ..utils.batch_lock import batch_write_lock
    from ..utils.io import write_json_atomic

    if audit_path is None:
        audit_path = settings.storage_root / "outputs" / batch_id / "audit.json"

    with batch_write_lock(batch_id):
        with open(audit_path, "r", encoding="utf-8") as fh:
            audit = json.load(fh)
        audit = apply_workflow_progression(audit)
        write_json_atomic(audit_path, audit)
    return audit


def normalize_dhl_events_batch(
    raw_events: List[Dict[str, Any]],
    *,
    awb: str = "",
    batch_id: str = "",
) -> List[Dict[str, Any]]:
    """
    Normalize a list of raw DHL API events in one call.
    Each raw event should have keys: timestamp, location, status, description.
    """
    result = []
    for ev in raw_events or []:
        normalized = normalize_tracking_event(
            ev, source="dhl_api", awb=awb, batch_id=batch_id,
        )
        result.append(normalized)
    return result
