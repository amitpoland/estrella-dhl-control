"""
test_carrier_event_handler.py — DL-E1 webhook event execution engine.

Required coverage:
  1. transit event applies transition to in_transit.
  2. delivered event from handed_to_carrier applies delivered.
  3. duplicate event is deduped and does not add transition.
  4. unknown shipment outcome is no_shipment.
  5. unknown status outcome is ignored.
  6. illegal transition after delivered is ignored.
  7. exception status records message but does not change state.
  8. handler does not raise for accepted-but-ignored events.
  9. handler source does not import FastAPI.
  10. handler source does not import live DHL adapter.
  11. handler source does not import requests/httpx/urllib.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.carrier import carrier_coordinator as cc
from app.services.carrier import carrier_event_db as ced
from app.services.carrier import carrier_event_handler as ceh
from app.services.carrier import carrier_shipment_db as csdb
from app.services.carrier import carrier_state_engine as cse
from app.services.carrier.adapters.dhl_express_stub import DHLExpressStubAdapter
from app.services.carrier.base import CARRIER_DHL, CarrierEvent


_HANDLER_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "services" / "carrier" / "carrier_event_handler.py"
)


@pytest.fixture(scope="module")
def handler_src() -> str:
    return _HANDLER_FILE.read_text(encoding="utf-8")


@pytest.fixture()
def setup(tmp_path):
    """Coordinator + handler bound to tmp_path-isolated DBs."""
    coord = cc.CarrierCoordinator(
        db_path          = tmp_path / "carrier_shipments.db",
        label_store_root = tmp_path / "carrier_labels",
        adapter          = DHLExpressStubAdapter(),
        actor            = "test-handler",
    )
    handler = ceh.CarrierEventHandler(
        coordinator = coord,
        db_path     = tmp_path / "carrier_events.db",
    )
    return coord, handler


def _ev(awb: str, code: str, ts: str = "2026-04-01T10:00:00Z") -> CarrierEvent:
    return CarrierEvent(
        carrier=CARRIER_DHL, awb=awb, event_code=code,
        occurred_at=ts, location="Warsaw", description="test event",
    )


def _seed_handed(coord) -> str:
    """Walk a fresh shipment up to HANDED_TO_CARRIER. Returns the AWB."""
    from app.services.carrier.base import CarrierAddress, CarrierShipmentRequest, PackageSpec
    addr_from = CarrierAddress(name="From", country="PL")
    addr_to = CarrierAddress(name="To", country="US")
    pkg = PackageSpec(weight_kg=0.5, length_cm=20, width_cm=15, height_cm=10)
    req = CarrierShipmentRequest(
        batch_id="B-EH-1", ship_from=addr_from, ship_to=addr_to,
        packages=(pkg,), reference="EH-REF-1",
    )
    out = coord.create_shipment(batch_id="B-EH-1", request=req)
    awb = out["shipment"]["awb"]
    coord.mark_label_printed(carrier=CARRIER_DHL, awb=awb)
    coord.mark_handed_to_carrier(carrier=CARRIER_DHL, awb=awb)
    return awb


# ── 1. transit applies in_transit ──────────────────────────────────────────

def test_transit_event_applies_in_transit(setup):
    coord, handler = setup
    awb = _seed_handed(coord)
    out = handler.handle_event(_ev(awb, "transit"))
    assert out["outcome"] == "applied"
    row = csdb.get_by_awb(CARRIER_DHL, awb)
    assert row["state"] == cse.IN_TRANSIT


# ── 2. delivered from handed_to_carrier ────────────────────────────────────

def test_delivered_from_handed_applies_delivered(setup):
    coord, handler = setup
    awb = _seed_handed(coord)
    out = handler.handle_event(_ev(awb, "delivered"))
    assert out["outcome"] == "applied"
    row = csdb.get_by_awb(CARRIER_DHL, awb)
    assert row["state"] == cse.DELIVERED


def test_returned_from_in_transit_applies_returned(setup):
    coord, handler = setup
    awb = _seed_handed(coord)
    handler.handle_event(_ev(awb, "transit"))
    out = handler.handle_event(_ev(awb, "returned",
                                    ts="2026-04-01T13:00:00Z"))
    assert out["outcome"] == "applied"
    row = csdb.get_by_awb(CARRIER_DHL, awb)
    assert row["state"] == cse.RETURNED


# ── 3. duplicate event is deduped ─────────────────────────────────────────

def test_duplicate_event_is_deduped_and_no_extra_transition(setup):
    coord, handler = setup
    awb = _seed_handed(coord)

    out1 = handler.handle_event(_ev(awb, "transit"))
    assert out1["outcome"] == "applied"
    row = csdb.get_by_awb(CARRIER_DHL, awb)
    transitions_before = csdb.get_transitions(row["id"])

    out2 = handler.handle_event(_ev(awb, "transit"))
    assert out2["outcome"] == "deduped"
    assert out2["event_id"] == out1["event_id"]

    transitions_after = csdb.get_transitions(row["id"])
    assert transitions_before == transitions_after


# ── 4. unknown shipment ───────────────────────────────────────────────────

def test_unknown_shipment_marks_no_shipment(setup):
    _, handler = setup
    out = handler.handle_event(_ev("UNKNOWN-AWB", "transit"))
    assert out["outcome"] == "no_shipment"
    assert out["shipment_id"] is None


# ── 5. unknown status ─────────────────────────────────────────────────────

def test_unknown_status_marks_ignored_with_unknown_flag(setup):
    coord, handler = setup
    awb = _seed_handed(coord)
    out = handler.handle_event(_ev(awb, "scanned-by-aliens"))
    assert out["outcome"] == "ignored"
    assert out["unknown_status_code"] is True
    # State unchanged
    row = csdb.get_by_awb(CARRIER_DHL, awb)
    assert row["state"] == cse.HANDED_TO_CARRIER


# ── 6. illegal transition after delivered ────────────────────────────────

def test_illegal_transition_after_delivered_is_ignored(setup):
    coord, handler = setup
    awb = _seed_handed(coord)

    handler.handle_event(_ev(awb, "delivered",
                             ts="2026-04-01T11:00:00Z"))
    row = csdb.get_by_awb(CARRIER_DHL, awb)
    assert row["state"] == cse.DELIVERED
    transitions_before = csdb.get_transitions(row["id"])

    # An "in_transit" event arriving AFTER delivered is illegal.
    out = handler.handle_event(_ev(awb, "transit",
                                    ts="2026-04-01T12:00:00Z"))
    assert out["outcome"] == "ignored"
    assert "illegal" in (out["reason"] or "").lower()

    transitions_after = csdb.get_transitions(row["id"])
    assert transitions_before == transitions_after
    row = csdb.get_by_awb(CARRIER_DHL, awb)
    assert row["state"] == cse.DELIVERED  # state unchanged


# ── 7. exception records message, no state change ───────────────────────

def test_exception_records_message_but_no_state_change(setup):
    coord, handler = setup
    awb = _seed_handed(coord)
    state_before = csdb.get_by_awb(CARRIER_DHL, awb)["state"]
    transitions_before = csdb.get_transitions(
        csdb.get_by_awb(CARRIER_DHL, awb)["id"],
    )

    out = handler.handle_event(_ev(awb, "exception"))
    assert out["outcome"] == "ignored"
    assert out["unknown_status_code"] is False

    state_after = csdb.get_by_awb(CARRIER_DHL, awb)["state"]
    transitions_after = csdb.get_transitions(
        csdb.get_by_awb(CARRIER_DHL, awb)["id"],
    )
    assert state_before == state_after
    assert transitions_before == transitions_after


# ── 8. handler does not raise for accepted-but-ignored events ──────────

def test_handler_never_raises_for_accepted_but_ignored(setup):
    coord, handler = setup
    awb = _seed_handed(coord)
    handler.handle_event(_ev(awb, "delivered"))

    # All of these should NOT raise.
    handler.handle_event(_ev(awb, "delivered"))           # dedupe
    handler.handle_event(_ev(awb, "transit",
                             ts="2026-04-01T13:00:00Z")) # illegal
    handler.handle_event(_ev(awb, "made-up",
                             ts="2026-04-01T14:00:00Z")) # unknown
    handler.handle_event(_ev("OTHER-AWB", "transit",
                             ts="2026-04-01T15:00:00Z")) # no_shipment
    handler.handle_event(_ev(awb, "exception",
                             ts="2026-04-01T16:00:00Z")) # info


# ── 9-11. Source-grep ────────────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", [
    "import fastapi", "from fastapi",
    "import flask",   "from flask",
])
def test_handler_source_no_web_framework(handler_src, forbidden):
    assert forbidden not in handler_src, (
        f"carrier_event_handler.py contains {forbidden!r} — handler "
        f"is service-layer only."
    )


@pytest.mark.parametrize("forbidden", [
    "DHLExpressLiveAdapter",
    "dhl_express_live",
    "DHLExpressStubAdapter",
    "dhl_express_stub",
])
def test_handler_source_no_concrete_adapter(handler_src, forbidden):
    assert forbidden not in handler_src, (
        f"carrier_event_handler.py contains {forbidden!r} — handler "
        f"is adapter-agnostic; events arrive parsed."
    )


@pytest.mark.parametrize("forbidden", [
    "import requests", "from requests",
    "import httpx",    "from httpx",
    "import urllib",   "from urllib",
])
def test_handler_source_no_http(handler_src, forbidden):
    assert forbidden not in handler_src, (
        f"carrier_event_handler.py contains {forbidden!r}."
    )


def test_handler_source_no_env_reads(handler_src):
    for forbidden in ["os.environ", "os.getenv", "getenv("]:
        assert forbidden not in handler_src, (
            f"carrier_event_handler.py contains {forbidden!r}."
        )
