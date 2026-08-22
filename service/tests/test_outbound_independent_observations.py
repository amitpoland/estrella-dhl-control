"""Statistical independence is a property of the terminating event, not of a direction.

Several parcels handed to DHL in one drop are ONE observation of how long that
handover took, scanned several times. Counting the scans independently inflates
the gate, the median and the headline.

PR #1328 proposed a single global 900-second threshold for every outbound stage.
Live re-measurement on 2026-08-22 disproved that as a universal rule, so it is
not what ships here:

    acceptance   bursts 0,2,2,2,2,2,9 s   next observed gap 1080 s   SEPARATED
    delivered    bursts 0,0 s             next observed gap 3481 s   SEPARATED
    departed     0x16, 430, 720 s         next 915, 1009, 1530 s     CONTINUOUS
    processed    0x16, ... 697, 858 s     next 960, 960, 986 s       CONTINUOUS

A boundary drawn at 900 s through a continuous distribution manufactures an
independence claim the data does not support, so departed-terminating stages
keep exact-event semantics.

These tests pin WHY clustering is and is not applied, so a later refactor cannot
quietly generalise the tolerance back to every stage.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import dhl_logistics_intelligence as intel
from app.services import dhl_logistics_targets as targets

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _sample(hours, seconds_before_now, awb="AWB"):
    return {"hours": float(hours),
            "end_ts": NOW - timedelta(seconds=seconds_before_now),
            "awb": awb}


def _dto(samples, *, transition_id="booking_to_acceptance", terminating_event="acceptance",
         scope="outbound", label="Booking to Acceptance"):
    return intel._transition_period_dto(
        samples, transition_id=transition_id, label=label, now=NOW,
        terminating_event=terminating_event, scope=scope)


# ── the policy itself ────────────────────────────────────────────────────────

def test_the_policy_is_keyed_by_terminating_event_not_by_direction():
    assert targets.independence_tolerance_seconds("acceptance", "outbound") == 900
    assert targets.independence_tolerance_seconds("delivered", "outbound") == 900


def test_stages_without_a_proven_boundary_get_no_tolerance():
    """departed and processed_at_facility have continuous gap distributions.
    Absent from the table means absent from clustering — that is the default."""
    assert targets.independence_tolerance_seconds("departed", "outbound") is None
    assert targets.independence_tolerance_seconds("processed_at_facility", "outbound") is None
    assert targets.independence_tolerance_seconds("destination", "outbound") is None


def test_the_policy_does_not_reach_into_an_unmeasured_scope():
    """The bands were measured on outbound events. Inbound was not measured, so
    it keeps its existing semantics rather than inheriting a foreign tolerance."""
    assert targets.independence_tolerance_seconds("acceptance", "inbound") is None
    assert targets.independence_tolerance_seconds("delivered", "inbound") is None


def test_the_enabled_set_is_exactly_the_two_measured_events():
    """A guard against silent generalisation: adding an event here without
    publishing its gap distribution should fail this test first."""
    assert set(targets.INDEPENDENCE_POLICY_BY_TERMINATING_EVENT) == {"acceptance", "delivered"}


# ── clustering behaviour ─────────────────────────────────────────────────────

def test_one_handover_scanned_thirteen_times_is_not_thirteen_observations():
    """THE DEFECT. Thirteen parcels dropped together, scanned seconds apart."""
    samples = [_sample(120 + i, 3600 - i * 2, "AWB%d" % i) for i in range(13)]
    dto = _dto(samples)
    assert dto["n_shipments"] == 13
    assert dto["n_independent"] == 1
    assert dto["independence_basis"] == "burst_tolerance_900s"


def test_a_burst_cannot_clear_the_publication_floor_on_its_own():
    """The gate counts independent observations where an authority exists, so a
    single physical collection cannot look like a measured population."""
    samples = [_sample(120, 3600 - i * 2, "AWB%d" % i) for i in range(13)]
    dto = _dto(samples)
    dto["target_hours"] = 12.0
    dto["publishable"] = True
    assert intel._ranking_exclusion(dto) == "insufficient_recent_samples"


def test_events_beyond_the_tolerance_stay_independent():
    """1080 s is the smallest real gap observed between acceptance events, and
    it is deliberately NOT merged: merging an ambiguous pair would understate
    independence rather than overstate it."""
    samples = [_sample(120, 5000), _sample(130, 5000 - 1080)]
    dto = _dto(samples)
    assert dto["n_independent"] == 2


def test_departed_events_at_720_and_915_seconds_are_not_merged():
    """THE NEGATIVE PIN. Both gaps exist in the live departed distribution, one
    either side of 900 s, with no band between them. A future blanket tolerance
    would collapse them and this test is what stops it."""
    samples = [_sample(10, 4000), _sample(11, 4000 - 720), _sample(12, 4000 - 720 - 915)]
    dto = _dto(samples, transition_id="acceptance_to_departure",
               terminating_event="departed", label="Acceptance to Departure")
    assert dto["independence_basis"] == "exact_event"
    assert dto["n_independent"] == 3 == dto["n_shipments"]
    assert dto["independence_tolerance_seconds"] is None


def test_delivered_duplicate_scans_collapse_where_the_band_supports_it():
    samples = [_sample(200, 900), _sample(201, 900)]
    dto = _dto(samples, transition_id="booking_to_delivered",
               terminating_event="delivered", label="Booking to Delivered")
    assert dto["n_shipments"] == 2
    assert dto["n_independent"] == 1


# ── what the numbers mean downstream ─────────────────────────────────────────

def test_ranking_uses_the_median_of_per_observation_medians():
    """Nine repeats of one slow handover must not outvote four fast ones."""
    slow = [_sample(100, 8000 - i * 2, "S%d" % i) for i in range(9)]
    fast = ([_sample(10, 40000)] + [_sample(10, 80000)]
            + [_sample(10, 120000)] + [_sample(10, 160000)])
    dto = _dto(slow + fast)
    assert dto["n_shipments"] == 13
    assert dto["n_independent"] == 5
    # Row median would be 100 (nine of thirteen rows). Per-observation median of
    # [100, 10, 10, 10, 10] is 10.
    assert dto["current_30d"]["median"] == 100.0
    assert dto["ranking_typical"] == 10.0


def test_a_stage_without_the_authority_keeps_its_row_median_for_ranking():
    samples = [_sample(100, 8000 - i * 2, "S%d" % i) for i in range(9)]
    dto = _dto(samples, transition_id="acceptance_to_departure",
               terminating_event="departed", label="Acceptance to Departure")
    assert dto["ranking_typical"] is None


def test_both_counts_are_always_published():
    dto = _dto([_sample(120, 3600 - i * 2, "A%d" % i) for i in range(4)])
    assert dto["n_shipments"] == 4
    assert dto["n_independent"] == 1
    assert dto["inflation_ratio"] == 4.0


def test_inflation_is_labelled_from_the_raw_to_independent_ratio():
    dto = _dto([_sample(120, 3600 - i * 2, "A%d" % i) for i in range(4)])
    assert dto["inflation_flagged"] is True


def test_no_inflation_is_not_labelled():
    samples = [_sample(120, 40000), _sample(130, 80000)]
    dto = _dto(samples)
    assert dto["inflation_ratio"] == 1.0
    assert dto["inflation_flagged"] is False


def test_an_unclustered_stage_is_never_inflation_flagged():
    """Its ratio is 1.0 by construction; flagging it would be noise."""
    samples = [_sample(10, 4000 - i * 2, "D%d" % i) for i in range(6)]
    dto = _dto(samples, transition_id="acceptance_to_departure",
               terminating_event="departed", label="Acceptance to Departure")
    assert dto["inflation_flagged"] is False


# ── the sentence a manager reads ─────────────────────────────────────────────

def test_headline_names_the_observation_noun_and_carries_both_counts():
    top = {"id": "booking_to_acceptance", "label": "Booking to Acceptance",
           "excess_human": "2d 21h", "excess_vs_target_hours": 69.66,
           "n_independent": 6, "n_shipments": 13,
           "observation_noun": "collections",
           "independence_basis": "burst_tolerance_900s"}
    line = intel._top_headline(top)
    assert "6 collections" in line
    assert "13 shipment" in line
    assert "on 13 recent" not in line          # the bare, misleading N


def test_headline_does_not_duplicate_a_count_that_did_not_change():
    top = {"id": "booking_to_delivered", "label": "Booking to Delivered",
           "excess_human": "3d 13h", "excess_vs_target_hours": 85.69,
           "n_independent": 12, "n_shipments": 12,
           "observation_noun": "deliveries",
           "independence_basis": "burst_tolerance_900s"}
    assert intel._top_headline(top) == (
        "Whole export, booking to delivered is taking 3d 13h longer than target, "
        "on 12 recent deliveries")


def test_headline_falls_back_cleanly_when_nothing_is_slow():
    assert intel._top_headline(None) == "No step is provably running slow right now"


def test_the_noun_comes_from_what_the_stage_terminates_on():
    assert intel._observation_noun("acceptance", 2) == "collections"
    assert intel._observation_noun("delivered", 1) == "delivery"
    assert intel._observation_noun("departed", 3) == "departures"
    assert intel._observation_noun(None, 2) == "observations"


# ── authority boundary ───────────────────────────────────────────────────────

def test_the_statistical_layer_does_not_touch_canonical_event_identity():
    """`tracking_normalizer._dedup_key` owns raw event identity — whether two
    records are the same scan. This layer owns statistical weight — how many
    independent observations a set of scans represents. Two concerns, two
    owners; this pin keeps them apart.

    Written against the OPERATION, not the string: this module's docstrings
    deliberately name `tracking_normalizer._dedup_key` to say what it does NOT
    do, and a substring pin would fail on its own documentation. What must be
    absent is an import or a call.
    """
    import ast
    with open(intel.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
    assert not any("tracking_normalizer" in m for m in imported), imported
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    called |= {n.func.attr for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for forbidden in ("_dedup_key", "append_tracking_events", "_make_event_id"):
        assert forbidden not in called, forbidden


def test_the_statistical_layer_writes_no_tracking_state():
    with open(intel.__file__, encoding="utf-8") as fh:
        text = fh.read()
    for forbidden in ("INSERT INTO", "UPDATE ", "DELETE FROM", "commit()"):
        assert forbidden not in text, "intelligence layer must stay read-only: %r" % forbidden


@pytest.mark.parametrize("scope", ["inbound", "outbound"])
def test_every_stage_publishes_an_independence_basis(scope):
    """No stage may be silent about how its population was counted."""
    dto = _dto([_sample(10, 1000)], scope=scope)
    assert dto["independence_basis"] in ("exact_event", "burst_tolerance_900s")


def test_without_the_policy_the_burst_reads_as_thirteen_and_clears_the_floor(monkeypatch):
    """FAIL-WITHOUT-FIX, as a counterfactual rather than an absent-API error.

    Running the old tests against unpatched main fails with TypeError because
    the parameters did not exist yet — that proves nothing about the defect. So
    the proof is run on the SAME code path with the policy emptied: the thirteen
    parcels of one handover reappear as thirteen observations and clear the
    publication floor, which is exactly the live defect. The policy is what does
    the work; the plumbing alone does not.
    """
    monkeypatch.setattr(targets, "INDEPENDENCE_POLICY_BY_TERMINATING_EVENT", {})
    samples = [_sample(120, 3600 - i * 2, "AWB%d" % i) for i in range(13)]
    dto = _dto(samples)
    assert dto["n_independent"] == 13          # the inflation, restored
    assert dto["independence_basis"] == "exact_event"
    dto["target_hours"] = 12.0
    dto["publishable"] = True
    assert intel._ranking_exclusion(dto) is None   # one handover clears the gate

    monkeypatch.undo()
    fixed = _dto(samples)
    fixed["target_hours"] = 12.0
    fixed["publishable"] = True
    assert fixed["n_independent"] == 1
    assert intel._ranking_exclusion(fixed) == "insufficient_recent_samples"
