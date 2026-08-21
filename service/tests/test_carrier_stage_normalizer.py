"""One normaliser for carrier tracking events (CT-MASTER W2-S1).

Before `_carrier_stage_id`, the DHL type code sat unread in `ev["status"]` and
every carrier event was emitted with the literal stage id "event". Four fixed
transitions could therefore never close a single duration sample:

    booking_to_acceptance      N=1  (95.5% excluded)
    acceptance_to_departure    N=6  (72.7% excluded)
    departure_to_destination   N=0  (100%  excluded)
    destination_to_delivered   N=0  (100%  excluded)

Measured against the production replica after the fix: 14 / 20 / 13 / 13.
Evidence: campaign/evidence/W0/, campaign/reports/W2-report.md.

These pins exist so a future refactor cannot quietly go back to dropping the
code. The code vocabulary is censused from this account's own tracking cache
(962 events, 21 distinct codes) — it is the carrier contract as received, not
an invented mapping.
"""
from __future__ import annotations

from app.services import dhl_logistics_projector as proj


# Verbatim event shapes from storage/outputs/*/tracking_cache.json.
_REAL_EVENTS = [
    ({"timestamp": "2026-08-21T15:39:26", "location": "WARSAW - PL",
      "status": "SA", "description": "Shipment Accepted"}, "acceptance"),
    ({"timestamp": "2026-08-21T21:42:46", "location": "WARSAW - PL",
      "status": "PL", "description": "Processed at WARSAW-POLAND"}, "processed_at_facility"),
    ({"timestamp": "2026-08-21T22:10:58", "location": "WARSAW - PL",
      "status": "DF", "description": "Shipment has departed from a DHL facility WARSAW-POLAND"}, "departed"),
    ({"timestamp": "2026-08-22T00:06:22", "location": "LEIPZIG - DE",
      "status": "AF", "description": "Arrived at DHL Sort Facility  LEIPZIG-GERMANY"}, "arrived_facility"),
    ({"timestamp": "2026-08-22T03:00:00", "location": "ARQUES - FR",
      "status": "AR", "description": "Arrived at DHL Delivery Facility  ARQUES-FRANCE"}, "arrived_destination"),
    ({"timestamp": "2026-08-22T07:00:00", "location": "ARQUES - FR",
      "status": "WC", "description": "Shipment is out with courier for delivery"}, "out_for_delivery"),
    ({"timestamp": "2026-08-22T11:00:00", "location": "ARQUES - FR",
      "status": "OK", "description": "Delivered"}, "delivered"),
    ({"timestamp": "2026-08-20T09:00:00", "location": "MUMBAI - IN",
      "status": "PU", "description": "Shipment picked up"}, "pickup"),
]


def test_real_cached_events_normalise_to_semantic_stages():
    for ev, expected in _REAL_EVENTS:
        assert proj._carrier_stage_id(ev) == expected, ev


def test_sort_facility_is_not_destination_arrival():
    """AF is a transit hub, AR is the in-country delivery facility.

    Collapsing them would close departure->destination on the first Leipzig
    hop and report a few hours of transit as the whole destination leg.
    """
    af = proj._carrier_stage_id({"status": "AF", "description": "Arrived at DHL Sort Facility  LEIPZIG-GERMANY"})
    ar = proj._carrier_stage_id({"status": "AR", "description": "Arrived at DHL Delivery Facility  ARQUES-FRANCE"})
    assert af != ar
    assert ar == "arrived_destination"


def test_already_normalised_stage_wins_over_type_code():
    ev = {"normalized_stage": "DELIVERED", "status": "AF", "description": "x"}
    assert proj._carrier_stage_id(ev) == "DELIVERED"


def test_unknown_code_is_left_as_event_never_guessed():
    """A wrong stage id silently closes a duration against the wrong milestone.

    An unrecognised code must degrade to "event" (excluded, counted, visible),
    never to a plausible neighbour.
    """
    assert proj._carrier_stage_id({"status": "ZZ", "description": "Something new"}) == "event"
    assert proj._carrier_stage_id({"description": "no code at all"}) == "event"
    assert proj._carrier_stage_id({}) == "event"


def test_every_censused_code_has_a_mapping():
    """The 21 codes observed in production must all resolve.

    Census: 962 events across storage/outputs/*/tracking_cache.json.
    A code that silently falls through to "event" is a stage that stops
    being measurable without anything failing.
    """
    censused = {
        "PL", "DF", "RR", "AF", "OK", "OH", "CC", "PU", "UD", "CR", "IC",
        "WC", "SA", "AR", "TR", "SD", "SM", "CD", "ND", "AD", "CA",
    }
    unmapped = {c for c in censused if proj._carrier_stage_id({"status": c}) == "event"}
    assert not unmapped, "censused DHL codes with no mapping: %s" % sorted(unmapped)


def test_acceptance_lookup_is_not_shadowed_by_processed_events():
    """`_row_timestamp_map` resolves acceptance from a want-set that contains
    "processed". PL fires at every hub, so mapping it to "processed" would make
    acceptance resolve to whichever hub happened to be first in the list.
    """
    assert proj._carrier_stage_id({"status": "PL"}) == "processed_at_facility"


def test_destination_resolves_from_out_for_delivery_when_no_delivery_facility():
    """Shipments whose AR event never arrives still reach the destination
    country — WC proves it. Without this the leg stays unmeasurable."""
    row = {
        "milestones": [
            {"stage_id": "departed", "timestamp_utc": "2026-08-22T00:00:00+00:00"},
            {"stage_id": "out_for_delivery", "timestamp_utc": "2026-08-22T07:00:00+00:00"},
            {"stage_id": "delivered", "timestamp_utc": "2026-08-22T11:00:00+00:00"},
        ],
        "delivered_at_utc": "2026-08-22T11:00:00+00:00",
    }
    tsmap = proj._row_timestamp_map(row)
    assert tsmap["destination"] is not None
    assert proj._hours_between(tsmap["destination"], tsmap["delivered"]) == 4.0
