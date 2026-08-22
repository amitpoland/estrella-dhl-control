"""Outbound bottlenecks are gated and ranked on independent observations.

CT-DEDUP-S1. Five parcels handed to DHL in one drop are ONE observation of how
long collection took, repeated five times. Counting rows lets a stage clear the
N>=5 floor on a single real event, and inflates every figure derived from it.

Measured on the production replica, 2026-08-22 (campaign/evidence/W7/dedup):

    booking_to_first_movement   13 shipments   5 collection events   2.60x
    acceptance_to_departure     13 shipments   4 departures          3.25x
    booking_to_acceptance       13 shipments   6 collection events   2.17x

booking_to_acceptance needed the gap tolerance to show up at all: DHL scans a
multi-parcel handover parcel by parcel, so one drop lands as five "Shipment
Accepted" stamps 2-9 seconds apart. Exact-timestamp de-dup called those five
independent observations. Measured gaps split cleanly - 2..9s within a
handover, then nothing until 4.5h - so INDEPENDENT_EVENT_GAP_SECONDS collapses
the burst and leaves every genuine event alone.

Ranking on rows put booking_to_first_movement second at +108.10h. Ranked on its
5 independent collection events it is +59.44h and third. Inbound measured 1.00x
on all eight stages and is deliberately left alone.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services import dhl_logistics_intelligence as intel
from app.services import dhl_logistics_targets as targets


NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)
SRC = Path(__file__).resolve().parents[1] / "app" / "services" / "dhl_logistics_intelligence.py"


def _samples(spec):
    """spec: list of (days_ago, hours, shared_event_key).

    Rows sharing a key share one terminating timestamp exactly; different keys
    are spaced 6h apart, comfortably beyond INDEPENDENT_EVENT_GAP_SECONDS, so
    they are genuinely separate events rather than one scan burst.
    """
    out = []
    for days, hours, key in spec:
        end = NOW - timedelta(days=days, hours=6 * key)
        out.append({"hours": float(hours), "end_ts": end})
    return out


def _dto(spec, *, tid="booking_to_first_movement", scope="outbound"):
    return intel._transition_period_dto(
        _samples(spec), transition_id=tid, label="x", now=NOW, scope=scope
    )


# ── the pin the slice exists for ────────────────────────────────────────────

def test_a_bare_row_count_cannot_clear_the_outbound_ranking_gate():
    """13 shipments, ONE collection event. Rows say 13, evidence says 1."""
    spec = [(2, 130.0, 1)] * 13          # all thirteen share one terminating event
    dto = _dto(spec)
    dto["publishable"] = True

    assert dto["current_30d"]["n"] == 13, "row count should still be reported"
    assert dto["current_30d"]["n_independent"] == 1, "one shared event = one observation"

    ranking = intel.build_bottleneck_ranking({"inbound": {}, "outbound": {"booking_to_first_movement": dto}})
    assert ranking["ranked"] == [], "a stage resting on one real event must not rank"
    assert ranking["excluded"][0]["reason"] == "insufficient_recent_samples"


def test_the_gate_reads_n_independent_not_n():
    """Same 13 rows, now spread across 5 distinct events -> clears the floor."""
    spec = [(2, 130.0, k) for k in range(5)] + [(2, 130.0, 0)] * 8
    dto = _dto(spec)
    dto["publishable"] = True
    assert dto["current_30d"]["n"] == 13
    assert dto["current_30d"]["n_independent"] == 5
    ranking = intel.build_bottleneck_ranking({"inbound": {}, "outbound": {"booking_to_first_movement": dto}})
    assert len(ranking["ranked"]) == 1
    assert ranking["ranked"][0]["n"] == 5, "rank must rest on events, not rows"
    assert ranking["ranked"][0]["n_rows"] == 13
    assert ranking["ranked"][0]["basis"] == "independent_events"


def test_ranking_uses_the_clustered_median_not_the_row_median():
    """One slow event repeated 9 times must not outvote three fast ones."""
    spec = [(2, 200.0, 0)] * 9 + [(3, 30.0, 1), (4, 30.0, 2), (5, 30.0, 3), (6, 30.0, 4)]
    dto = _dto(spec)
    dto["publishable"] = True
    assert dto["current_30d"]["n"] == 13
    assert dto["current_30d"]["n_independent"] == 5
    # row median is dragged to 200 by the repeats; clustered median is 30
    assert dto["current_30d"]["typical"] == 200.0
    assert dto["current_30d"]["typical_independent"] == 30.0
    ranking = intel.build_bottleneck_ranking({"inbound": {}, "outbound": {"booking_to_first_movement": dto}})
    ranked = ranking["ranked"]
    target = targets.target_hours("booking_to_first_movement")
    assert ranked[0]["excess_vs_target_hours"] == round(30.0 - target, 2)


# ── inbound must be untouched ───────────────────────────────────────────────

def test_inbound_is_not_clustered_and_still_ranks_on_rows():
    spec = [(2, 130.0, 1)] * 13
    dto = intel._transition_period_dto(
        _samples(spec), transition_id="poland_to_dhl_email", label="x", now=NOW, scope="inbound"
    )
    dto["publishable"] = True
    assert dto["n_independent"] is None
    assert dto["current_30d"]["n_independent"] is None
    assert dto["inflation_ratio"] is None
    ranking = intel.build_bottleneck_ranking({"inbound": {"poland_to_dhl_email": dto}, "outbound": {}})
    assert len(ranking["ranked"]) == 1, "inbound behaviour must be unchanged"
    assert ranking["ranked"][0]["basis"] == "rows"
    assert ranking["ranked"][0]["n"] == 13


# ── inflation flag ──────────────────────────────────────────────────────────

def test_inflation_over_the_ratio_is_flagged():
    spec = [(2, 130.0, k) for k in range(5)] + [(2, 130.0, 0)] * 8   # 13 rows / 5 events
    dto = _dto(spec)
    assert dto["inflation_ratio"] == 2.6
    assert dto["inflated"] is True


def test_no_inflation_is_not_flagged():
    spec = [(2 + k, 130.0, k) for k in range(6)]                     # 6 rows / 6 events
    dto = _dto(spec)
    assert dto["inflation_ratio"] == 1.0
    assert dto["inflated"] is False


# ── the headline must never quote a bare outbound row count ─────────────────

def test_management_headline_names_events_and_shipments():
    top = {
        "id": "booking_to_first_movement", "label": "x",
        "excess_vs_target_hours": 59.44, "excess_human": "2d 11h 26m",
        "n": 5, "n_rows": 13, "n_independent": 5, "observation_noun": "collection events",
    }
    line = intel._top_headline(top)
    assert "5 collection events" in line
    assert "13 shipments" in line
    assert "on 13 recent shipments" not in line, "bare row count must not reach the card"


def test_headline_falls_back_cleanly_for_inbound():
    top = {"id": "poland_to_dhl_email", "label": "x", "excess_vs_target_hours": 5.0,
           "excess_human": "5h", "n": 7, "n_rows": None, "n_independent": None,
           "observation_noun": None}
    assert "7 recent shipments" in intel._top_headline(top)


# ── source-grep pins: the card cannot regress to a bare N ───────────────────

def test_ranked_entry_always_carries_both_counts():
    spec = [(2, 130.0, k) for k in range(6)]
    dto = _dto(spec); dto["publishable"] = True
    entry = intel.build_bottleneck_ranking({"inbound": {}, "outbound": {"booking_to_first_movement": dto}})["ranked"][0]
    for field in ("n", "n_rows", "n_independent", "observation_noun", "inflation_ratio", "basis"):
        assert field in entry, field


def test_the_gate_is_not_reading_the_row_count():
    """Guards the exact regression: _ranking_exclusion must go through
    _ranking_basis, never straight to current_30d["n"]."""
    src = SRC.read_text(encoding="utf-8")
    start = src.index("def _ranking_exclusion(")
    body = src[start:src.index("def _ranking_basis(")]
    assert "_ranking_basis(dto)" in body
    assert 'cur.get("n") or 0' not in body, "the outbound gate is reading rows again"
