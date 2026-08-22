"""
dhl_logistics_targets.py — Explicit management transit targets (hours).

Authority: operator-configured constants. NEVER derived from historical P90
or contaminated KPI samples. Changing a target does not alter shipment facts
or event-selection rules in dhl_logistics_projector.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


# Explicit management targets (hours). Source: logistics operating targets —
# not inferred from cohort percentiles.
TRANSITION_TARGETS_HOURS: Dict[str, float] = {
    # Inbound
    "origin_pickup_to_poland": 48.0,
    "poland_to_dhl_email": 24.0,
    "dhl_email_to_dsk": 24.0,
    "dsk_to_agency_sad": 48.0,
    "sad_to_customs_cleared": 24.0,
    "customs_cleared_to_pz": 24.0,
    "sad_to_pz": 48.0,
    "origin_pickup_to_delivered": 120.0,
    # Outbound
    "booking_to_acceptance": 12.0,
    "acceptance_to_departure": 24.0,
    "departure_to_destination": 48.0,
    "destination_to_delivered": 24.0,
    "booking_to_delivered": 96.0,
    "booking_to_first_movement": 24.0,
    "pickup_to_delivery": 72.0,
    "departure_to_delivery": 48.0,
}

# Lane-level end-to-end targets (hours) keyed by "ORIGIN→DEST"
LANE_TARGETS_HOURS: Dict[str, float] = {
    "IN→PL": 120.0,
    "PL→CZ": 48.0,
    "PL→NL": 72.0,
    "PL→DE": 48.0,
    "PL→SK": 48.0,
}

# Share of a stage's cohort that may be excluded for *ordering* defects before
# its duration statistics stop being publishable. Coverage gaps (an endpoint we
# simply never recorded) narrow the sample; ordering defects mean the samples we
# do have describe a sequence that did not happen, which is the failure that
# silently distorts a median. Measured 2026-08-22: at 10% this separates the
# five genuinely disordered stages from the eleven that are merely sparse.
CONTAMINATION_BLOCK_PCT = 10.0

# Two terminating events closer together than this are one physical event.
#
# DHL scans a multi-parcel handover parcel by parcel, so one drop produces
# several "Shipment Accepted" stamps seconds apart. Exact-timestamp de-dup
# counts those as independent observations; they are one.
#
# Measured 2026-08-22 over all outbound acceptance events. Gaps between
# consecutive distinct timestamps fall in two disjoint bands with nothing
# between them:
#     within a handover : 2, 2, 2, 2, 2, 9 seconds, then one at 1080 s
#     between handovers : minimum 4.5 hours
# 900 s sits far above the scan cadence and far below the next real handover,
# and deliberately does NOT merge the 1080 s pair - that gap is ambiguous, and
# merging an ambiguous pair would understate independence rather than overstate
# it. departed / first_movement have no sub-hour gaps at all, so this changes
# nothing for them.
INDEPENDENT_EVENT_GAP_SECONDS = 900

# Minimum samples before a stage may be ranked as a bottleneck, and minimum
# samples in the prior window before a period-over-period delta is publishable.
BOTTLENECK_MIN_N = 5
DELTA_MIN_PREVIOUS_N = 3

# Stage-age watch / action thresholds used by Operations Now risk (hours).
STAGE_AGE_WATCH_HOURS = 14.0
STAGE_AGE_ACTION_HOURS = 24.0
STAGE_AGE_CRITICAL_HOURS = 48.0

TARGETS_AUTHORITY = {
    "kind": "explicit_configured",
    "inferred_from_history": False,
    "note": (
        "Targets are management constants in dhl_logistics_targets.py. "
        "They are never derived from historical P90 or contaminated samples."
    ),
}


def target_hours(transition_id: str) -> Optional[float]:
    v = TRANSITION_TARGETS_HOURS.get(transition_id)
    return float(v) if v is not None else None


def lane_target_hours(lane_id: str) -> Optional[float]:
    v = LANE_TARGETS_HOURS.get(lane_id)
    if v is not None:
        return float(v)
    # Unknown lanes: no silent inference — leave null.
    return None


def targets_payload() -> Dict[str, Any]:
    return {
        "authority": TARGETS_AUTHORITY,
        "transitions_hours": dict(TRANSITION_TARGETS_HOURS),
        "lanes_hours": dict(LANE_TARGETS_HOURS),
        "stage_age_watch_hours": STAGE_AGE_WATCH_HOURS,
        "stage_age_action_hours": STAGE_AGE_ACTION_HOURS,
        "stage_age_critical_hours": STAGE_AGE_CRITICAL_HOURS,
        "contamination_block_pct": CONTAMINATION_BLOCK_PCT,
        "bottleneck_min_n": BOTTLENECK_MIN_N,
        "delta_min_previous_n": DELTA_MIN_PREVIOUS_N,
        "independent_event_gap_seconds": INDEPENDENT_EVENT_GAP_SECONDS,
    }
