"""One authority decides what stage a carrier event is (CT-MASTER W5).

`tracking_normalizer` already owned carrier-event classification, by substring
matching the human description. W2-S1 added a second classifier inside
`dhl_logistics_projector` that read the DHL type code instead. Two
implementations of one concern is a blocking finding, so the map moved into
`tracking_normalizer` and the projector consumes it.

The type code is kept as the primary signal because the description cannot
separate cases the code separates cleanly. Measured 2026-08-22:

    AF "Arrived at DHL Sort Facility LEIPZIG"    -> ARRIVED_ORIGIN_HUB (0.75)
    AR "Arrived at DHL Delivery Facility ARQUES" -> ARRIVED_ORIGIN_HUB (0.75)

A transit hub and the destination-country delivery facility are not the same
event, and while they read the same the leg between them cannot be measured.
"""
from __future__ import annotations

from pathlib import Path

from app.services import dhl_logistics_projector as proj
from app.services import tracking_normalizer as tn


SERVICES = Path(__file__).resolve().parents[1] / "app" / "services"


def test_the_map_lives_in_exactly_one_module():
    projector_src = (SERVICES / "dhl_logistics_projector.py").read_text(encoding="utf-8")
    assert "DHL_TYPE_CODE_STAGES" not in projector_src, (
        "the projector is keeping its own copy of the type-code map again"
    )
    assert hasattr(tn, "DHL_TYPE_CODE_STAGES")
    assert hasattr(tn, "carrier_stage_id")


def test_the_projector_consumes_that_authority_rather_than_reimplementing_it():
    assert proj._carrier_stage_id is tn.carrier_stage_id


def test_sort_facility_and_delivery_facility_stay_distinguishable():
    """The distinction the text matcher cannot make, and the reason the code wins."""
    af = tn.carrier_stage_id({"status": "AF"})
    ar = tn.carrier_stage_id({"status": "AR"})
    assert af == "arrived_facility"
    assert ar == "arrived_destination"
    assert af != ar

    # The text path genuinely cannot tell them apart — this is the measured
    # behaviour that justifies preferring the code, not a hypothetical.
    text_af = tn.normalize_tracking_event(
        {"description": "Arrived at DHL Sort Facility  LEIPZIG-GERMANY", "status": "AF"}
    )["normalized_stage"]
    text_ar = tn.normalize_tracking_event(
        {"description": "Arrived at DHL Delivery Facility  ARQUES-FRANCE", "status": "AR"}
    )["normalized_stage"]
    assert text_af == text_ar, (
        "if the description ever separates these, revisit which signal is primary"
    )


def test_type_code_is_read_from_every_shape_the_pipeline_uses():
    """Poll writes `status`; the normalized store writes `raw_status`; a push
    payload would carry `typeCode`. All three enter the same door."""
    assert tn.carrier_stage_id({"status": "OK"}) == "delivered"
    assert tn.carrier_stage_id({"raw_status": "OK"}) == "delivered"
    assert tn.carrier_stage_id({"typeCode": "OK"}) == "delivered"
    assert tn.carrier_stage_id({"type_code": "OK"}) == "delivered"


def test_an_already_normalised_stage_still_wins():
    assert tn.carrier_stage_id({"normalized_stage": "DELIVERED", "status": "AF"}) == "DELIVERED"


def test_unknown_codes_are_not_guessed():
    assert tn.carrier_stage_id({"status": "ZZ"}) == "event"
    assert tn.carrier_stage_id({}) == "event"


def test_stage_order_vocabulary_is_untouched():
    """The workflow vocabulary drives milestone emission under locked
    invariants. Consolidating the map must not have altered it."""
    assert "ARRIVED_DESTINATION_COUNTRY" in tn.STAGE_ORDER
    assert "DELIVERED" in tn.STAGE_ORDER
    assert tn.normalize_tracking_event({"description": "Delivered"})["normalized_stage"] == "DELIVERED"
    assert tn.normalize_tracking_event({"description": "Shipment picked up"})["normalized_stage"] == "PICKED_UP"
