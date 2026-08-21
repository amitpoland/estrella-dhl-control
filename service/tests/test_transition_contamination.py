"""Contamination is measured, published, and gates the same window it guards.

CT-MASTER W2-S2/S3. Three defects this pins shut, all measured against the
production replica on 2026-08-22 (campaign/reports/W2-report.md):

1. Coverage and contamination were one undifferentiated `excluded_n`. A stage
   missing an endpoint on half its cohort and a stage whose stamps are in
   impossible order looked identical.
2. A booking record typed in after the carrier already held the parcel was
   treated as a valid time anchor. Three such rows gave booking→delivered
   durations of 0.52h / 2.17h / 2.44h and produced a +7380% period delta.
3. Contamination was computed over the all-time cohort and then used to gate a
   current-window statistic. Six ~38-day-old backfilled bookings suppressed the
   only three real bottlenecks in the dataset.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import dhl_logistics_projector as proj
from app.services import dhl_logistics_targets as targets


NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)


def _outbound_row(awb, booked, delivered=None, first_movement=None):
    row = {
        "awb": awb,
        "direction": "outbound",
        "created_at_utc": booked,
        "delivered_at_utc": delivered,
        "first_movement_at_utc": first_movement,
        "milestones": [],
    }
    return row


def _iso(dt):
    return dt.isoformat()


# ── 1. coverage is not contamination ────────────────────────────────────────

def test_missing_endpoint_is_coverage_not_contamination():
    assert proj._exclusion_kind("missing_dsk") == "coverage"
    assert proj._exclusion_kind("missing_customs_cleared_and_pz") == "coverage"


def test_impossible_ordering_is_contamination():
    for reason in (
        "dsk_before_dhl_email",
        "delivered_before_booked",
        "lifecycle_mismatch_delivered_before_poland",
        "lifecycle_mismatch_booking_created_after_carrier_movement",
        "inverted_or_invalid",
    ):
        assert proj._exclusion_kind(reason) == "contamination", reason


def test_exclusion_reason_names_the_actual_defect():
    """`inverted_or_invalid` told a reader nothing. The reason must say which
    stamp preceded which, because that is the sentence someone has to act on."""
    row = _outbound_row(
        "1", booked=_iso(NOW - timedelta(hours=10)), delivered=_iso(NOW - timedelta(hours=40))
    )
    _hours, _end, reason = proj._transition_sample(row, "booking_to_delivered", "booked", "delivered")
    assert reason == "delivered_before_booked"


# ── 2. a backfilled booking is not a time anchor ─────────────────────────────

def test_booking_created_after_carrier_movement_is_excluded():
    """Verbatim from production: carrier had the parcel 2026-07-11 16:33, the
    booking row was created 2026-07-14 13:12, delivered 2026-07-14 15:44.
    Reported as a 0.52h booking-to-delivery."""
    row = _outbound_row(
        "7924336254",
        booked="2026-07-14T13:12:36+00:00",
        delivered="2026-07-14T15:44:00+00:00",
        first_movement="2026-07-11T16:33:00+00:00",
    )
    hours, _end, reason = proj._transition_sample(row, "booking_to_delivered", "booked", "delivered")
    assert hours is None
    assert reason == "lifecycle_mismatch_booking_created_after_carrier_movement"


def test_booking_ahead_of_carrier_movement_is_a_valid_anchor():
    row = _outbound_row(
        "3110473741",
        booked="2026-08-03T10:34:32+00:00",
        delivered="2026-08-04T10:31:00+00:00",
        first_movement="2026-08-03T14:49:00+00:00",
    )
    hours, _end, reason = proj._transition_sample(row, "booking_to_delivered", "booked", "delivered")
    assert reason is None
    assert round(hours, 2) == 23.94


def test_rule_applies_only_to_booking_anchored_transitions():
    """pickup→delivery must not be judged against the booking record."""
    row = _outbound_row(
        "x",
        booked="2026-07-14T13:12:36+00:00",
        delivered="2026-07-14T15:44:00+00:00",
        first_movement="2026-07-11T16:33:00+00:00",
    )
    row["pickup_at_utc"] = "2026-07-11T16:33:00+00:00"
    hours, _end, reason = proj._transition_sample(row, "pickup_to_delivery", "pickup", "delivered")
    assert reason is None
    assert hours is not None


# ── 3. the gate judges the window it guards ─────────────────────────────────

def _spec():
    return (("booking_to_delivered", "Booking → Delivered", "booked|delivered"),)


def test_historic_contamination_does_not_block_a_clean_current_window():
    """The measured regression: six backfilled bookings, all ~38 days old,
    blocked three stages whose recent samples were entirely clean."""
    rows = []
    # Old and contaminated — booking typed in after the carrier had it.
    for i in range(6):
        d = NOW - timedelta(days=38 + i)
        rows.append(_outbound_row(
            "old%d" % i,
            booked=_iso(d),
            delivered=_iso(d + timedelta(hours=2)),
            first_movement=_iso(d - timedelta(days=3)),
        ))
    # Recent and clean.
    for i in range(16):
        d = NOW - timedelta(days=2 + i)
        rows.append(_outbound_row(
            "new%d" % i,
            booked=_iso(d),
            delivered=_iso(d + timedelta(hours=150)),
            first_movement=_iso(d + timedelta(hours=4)),
        ))

    out = proj._fixed_transition_analytics(rows, _spec(), now=NOW)["booking_to_delivered"]
    assert out["contaminated_n"] == 6
    assert out["contamination_pct"] > targets.CONTAMINATION_BLOCK_PCT
    assert out["contamination_now_pct"] == 0.0
    assert out["publishable"] is True, out["not_publishable_reason"]


def test_contaminated_current_window_does_block():
    rows = []
    for i in range(8):
        d = NOW - timedelta(days=2 + i)
        rows.append(_outbound_row(
            "bad%d" % i,
            booked=_iso(d),
            delivered=_iso(d + timedelta(hours=2)),
            first_movement=_iso(d - timedelta(days=3)),
        ))
    for i in range(4):
        d = NOW - timedelta(days=12 + i)
        rows.append(_outbound_row(
            "ok%d" % i,
            booked=_iso(d),
            delivered=_iso(d + timedelta(hours=100)),
            first_movement=_iso(d + timedelta(hours=4)),
        ))
    out = proj._fixed_transition_analytics(rows, _spec(), now=NOW)["booking_to_delivered"]
    assert out["contamination_now_pct"] > targets.CONTAMINATION_BLOCK_PCT
    assert out["publishable"] is False
    assert out["not_publishable_reason"] == "contaminated_ordering"


def test_a_stage_with_no_samples_is_never_quietly_publishable():
    """sad→customs_cleared has 0 samples and 0% contamination. Zero divided by
    nothing must not read as clean."""
    rows = [_outbound_row("a%d" % i, booked=_iso(NOW - timedelta(days=i))) for i in range(10)]
    out = proj._fixed_transition_analytics(rows, _spec(), now=NOW)["booking_to_delivered"]
    assert out["n"] == 0
    assert out["contamination_now_pct"] == 0.0
    assert out["publishable"] is False
    assert out["not_publishable_reason"] == "insufficient_samples"


def test_one_decision_function_feeds_both_the_values_and_the_counts():
    """collect_transition_samples and _fixed_transition_analytics used to carry
    separate copies of the exclusion rules, so the published median and the
    published exclusion counts could describe different populations."""
    rows = []
    for i in range(6):
        d = NOW - timedelta(days=2 + i)
        rows.append(_outbound_row(
            "r%d" % i,
            booked=_iso(d),
            delivered=_iso(d + timedelta(hours=100)),
            first_movement=_iso(d + timedelta(hours=4)),
        ))
    rows.append(_outbound_row(
        "backfilled",
        booked=_iso(NOW - timedelta(days=3)),
        delivered=_iso(NOW - timedelta(days=3) + timedelta(hours=2)),
        first_movement=_iso(NOW - timedelta(days=6)),
    ))
    samples = proj.collect_transition_samples(rows, "booking_to_delivered", "booked|delivered")
    stats = proj._fixed_transition_analytics(rows, _spec(), now=NOW)["booking_to_delivered"]
    assert len(samples) == stats["n"] == 6
    assert stats["excluded_n"] == 1
    assert "backfilled" not in [s["awb"] for s in samples]
