"""
tracking_normalizer.py — Standardized goods-movement event model.

Responsibilities:
  - Define normalized movement stages (STAGE_ORDER)
  - Map raw DHL / public / manual wording to stages (normalize_tracking_event)
  - Append normalized events to audit.tracking_events with deduplication
  - Apply workflow-progression flags based on reached stages

Storage contract:
  audit.json["tracking_events"] is a chronological list of normalized events.
  Never overwrites — only appends. Dedup key: (awb, event_time, raw_description, source).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
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


def apply_workflow_progression(
    audit: Dict[str, Any],
    events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Inspect tracking_events and set workflow flags in audit (forward-only).

    Flags set:
      customs_workflow_eligible — any event in CUSTOMS_WORKFLOW_STAGES reached
      clearance_complete        — CUSTOMS_CLEARED reached
      shipment_delivered        — DELIVERED reached
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
