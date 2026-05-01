"""
test_dhl_event_parsing.py — Event-stream parsing & priority-based status derivation.

Ensures the DHL tracking parser:
  - captures ALL events (not just events[0])
  - normalises events into {timestamp, location, status, description}
  - sorts events ASC by timestamp
  - derives status from event description priority (Delivered wins over In Transit)
  - returns events array in the API response so the UI can render full movement
"""
from __future__ import annotations

from app.services.tracking_service import (
    _normalise_dhl_events,
    _derive_status_from_events,
    _DHL_EVENT_PRIORITY,
)


def _ev(ts, loc, cc, desc):
    return {
        "timestamp": ts,
        "location":  {"address": {"addressLocality": loc, "countryCode": cc}},
        "description": desc,
    }


# ── Normalisation ────────────────────────────────────────────────────────────

def test_normalise_sorts_ascending_by_timestamp():
    raw = [
        _ev("2026-04-25T14:22:00Z", "Warsaw", "PL", "Delivered"),
        _ev("2026-04-19T10:00:00Z", "Mumbai", "IN", "Picked up"),
        _ev("2026-04-21T11:00:00Z", "Hong Kong", "HK", "Departed Facility"),
    ]
    out = _normalise_dhl_events(raw)
    assert [e["timestamp"] for e in out] == [
        "2026-04-19T10:00:00Z",
        "2026-04-21T11:00:00Z",
        "2026-04-25T14:22:00Z",
    ]


def test_normalise_includes_all_events():
    raw = [_ev(f"2026-04-2{i}T10:00:00Z", "X", "PL", f"Event {i}") for i in range(5)]
    out = _normalise_dhl_events(raw)
    assert len(out) == 5


def test_normalise_formats_location():
    raw = [_ev("2026-04-25T10:00:00Z", "Warsaw", "PL", "Delivered")]
    out = _normalise_dhl_events(raw)
    assert out[0]["location"] == "WARSAW - PL"


def test_normalise_handles_missing_location():
    raw = [{"timestamp": "2026-04-25T10:00:00Z", "description": "Delivered"}]
    out = _normalise_dhl_events(raw)
    assert out[0]["location"] == ""
    assert out[0]["description"] == "Delivered"


def test_normalise_empty_input():
    assert _normalise_dhl_events([])    == []
    assert _normalise_dhl_events(None)  == []


# ── Status derivation ────────────────────────────────────────────────────────

def test_delivered_wins_over_in_transit():
    raw = [
        _ev("2026-04-19T10:00Z", "Mumbai",  "IN", "Picked up"),
        _ev("2026-04-21T10:00Z", "HK",      "HK", "In transit"),
        _ev("2026-04-25T14:00Z", "Warsaw",  "PL", "Delivered"),
    ]
    key, label = _derive_status_from_events(raw)
    assert key   == "delivered"
    assert label == "Delivered"


def test_with_delivery_courier_maps_to_out_for_delivery():
    raw = [_ev("2026-04-25T08:00Z", "Warsaw", "PL", "With delivery courier")]
    key, label = _derive_status_from_events(raw)
    assert key == "out_for_delivery"


def test_clearance_complete_maps_to_cleared():
    raw = [_ev("2026-04-24T19:00Z", "Warsaw", "PL", "Clearance processing complete")]
    key, label = _derive_status_from_events(raw)
    assert key == "cleared"


def test_picked_up_maps_to_picked_up():
    raw = [_ev("2026-04-19T10:00Z", "Mumbai", "IN", "Picked up")]
    key, label = _derive_status_from_events(raw)
    assert key == "picked_up"


def test_empty_events_returns_in_transit_default():
    assert _derive_status_from_events([])    == ("in_transit", "In Transit")
    assert _derive_status_from_events(None)  == ("in_transit", "In Transit")


def test_unknown_event_descriptions_default_to_in_transit():
    raw = [_ev("2026-04-25T10:00Z", "X", "PL", "Some custom event nobody mapped")]
    key, label = _derive_status_from_events(raw)
    assert key == "in_transit"


def test_priority_table_has_delivered_first():
    """Regression guard: 'delivered' MUST be the highest-priority entry."""
    first_keyword = _DHL_EVENT_PRIORITY[0][0]
    assert first_keyword == "delivered"


def test_event_status_field_also_searched():
    """If description is empty but status field has content, status is still derived."""
    raw = [{"timestamp": "2026-04-25T10:00Z", "status": "delivered", "description": ""}]
    key, label = _derive_status_from_events(raw)
    assert key == "delivered"
