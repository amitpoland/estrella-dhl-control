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
    }


# ── Statistical independence policy ──────────────────────────────────────────
# Several parcels handed over in one drop are ONE observation of how long that
# handover took, scanned several times. Counting the scans as independent
# inflates every figure derived from them.
#
# The policy is keyed by the TERMINATING EVENT, not by direction and not by
# metric name, because burst structure is a property of what the carrier does
# at that event. It is enabled ONLY where the live gap distribution shows two
# separated populations -- a scan burst, then nothing, then the next real
# event. Measured 2026-08-22 over the live outbound population:
#
#   acceptance   bursts 0, 2, 2, 2, 2, 2, 9 s | next observed gap 1080 s
#                -> separated by two orders of magnitude. CLUSTERED.
#   delivered    bursts 0, 0 s                | next observed gap 3481 s
#                -> separated. CLUSTERED.
#   departed     0 x16, then 430, 720 s       | next 915, 1009, 1530 s
#                -> CONTINUOUS across 900 s. NOT CLUSTERED.
#   processed_at_facility
#                0 x16, 18, 33, 233, 349,
#                503, 697, 858 s              | next 960, 960, 986 s
#                -> CONTINUOUS across 900 s. NOT CLUSTERED.
#
# This REPLACES the single global threshold proposed in #1328, whose comment
# asserted "between handovers minimum 4.5 hours" and "departed has no sub-hour
# gaps at all". Re-measurement disproved both: the next acceptance gap is 1080 s,
# not 4.5 h, and departed carries eighteen sub-900 s gaps. A global rule would
# have manufactured an independence boundary the data does not support for two
# of the four stages.
#
# 900 s is retained for the two enabled events because it sits far above their
# observed burst cadence (9 s) and far below their next observed real gap
# (1080 s) -- deliberately NOT merging that 1080 s pair, since an ambiguous pair
# merged understates independence rather than overstating it.
#
# A terminating event absent from this table keeps exact-event semantics. Do not
# add one without publishing the gap distribution that justifies it.
INDEPENDENCE_POLICY_BY_TERMINATING_EVENT = {
    "acceptance": 900,
    "delivered": 900,
}

# The bands above were measured on OUTBOUND events only. Inbound has not been
# measured, and rule: a stage without a proven boundary keeps its existing
# semantics -- so the policy does not silently reach across scopes.
INDEPENDENCE_MEASURED_SCOPES = ("outbound",)

# Raw-to-independent ratio at or above which the count is labelled as inflated,
# so no reader takes a bare N as evidence of that many observations.
INDEPENDENCE_INFLATION_FLAG_RATIO = 1.5


def independence_tolerance_seconds(terminating_event, scope):
    """Seconds within which two terminating events are one physical event.

    None means: no proven burst boundary for this event type in this scope, so
    events stay exactly as observed. None is the default and the safe answer.
    """
    if scope not in INDEPENDENCE_MEASURED_SCOPES:
        return None
    return INDEPENDENCE_POLICY_BY_TERMINATING_EVENT.get(terminating_event)
