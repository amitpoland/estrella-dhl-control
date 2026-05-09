"""
test_carrier_event_translator.py — DL-E1 statusCode → state-engine
mapping.

Required coverage:
  1. transit maps to in_transit.
  2. out-for-delivery maps to in_transit.
  3. delivered maps to delivered.
  4. returned maps to returned.
  5. failure maps to returned.
  6. exception maps to no state change.
  7. unknown status maps to no state change with unknown flag.
  8. Pure module source-grep: no FastAPI, no coordinator, no adapter
     imports.

Plus regression-pin tests on case-insensitivity and dash/underscore
tolerance.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.carrier import carrier_event_translator as cet
from app.services.carrier.base import CARRIER_DHL, CarrierEvent


_BUILDER_FILE = (
    Path(__file__).resolve().parents[1]
    / "app" / "services" / "carrier" / "carrier_event_translator.py"
)


@pytest.fixture(scope="module")
def src() -> str:
    return _BUILDER_FILE.read_text(encoding="utf-8")


def _ev(code: str) -> CarrierEvent:
    return CarrierEvent(
        carrier=CARRIER_DHL, awb="X", event_code=code,
        occurred_at="2026-04-01T10:00:00Z",
    )


# ── 1. transit → in_transit ────────────────────────────────────────────────

def test_transit_maps_to_in_transit():
    t = cet.translate(_ev("transit"))
    assert t.target_state == "in_transit"
    assert t.coordinator_method == "record_in_transit"
    assert t.unknown is False


# ── 2. out-for-delivery → in_transit ───────────────────────────────────────

@pytest.mark.parametrize("code", [
    "out-for-delivery", "out_for_delivery",
    "OUT-FOR-DELIVERY", "Out_For_Delivery",
])
def test_out_for_delivery_maps_to_in_transit(code):
    t = cet.translate(_ev(code))
    assert t.target_state == "in_transit"
    assert t.coordinator_method == "record_in_transit"


@pytest.mark.parametrize("code", ["picked-up", "picked_up", "pre-transit"])
def test_other_in_transit_codes(code):
    t = cet.translate(_ev(code))
    assert t.target_state == "in_transit"


# ── 3. delivered → delivered ───────────────────────────────────────────────

@pytest.mark.parametrize("code", ["delivered", "DELIVERED", "success"])
def test_delivered_maps_to_delivered(code):
    t = cet.translate(_ev(code))
    assert t.target_state == "delivered"
    assert t.coordinator_method == "record_delivered"


# ── 4. returned → returned ─────────────────────────────────────────────────

@pytest.mark.parametrize("code", [
    "returned", "return", "return-in-progress", "return_in_progress",
])
def test_returned_maps_to_returned(code):
    t = cet.translate(_ev(code))
    assert t.target_state == "returned"
    assert t.coordinator_method == "record_returned"


# ── 5. failure → returned ──────────────────────────────────────────────────

@pytest.mark.parametrize("code", ["failure", "failure-rto", "FAILURE"])
def test_failure_maps_to_returned(code):
    t = cet.translate(_ev(code))
    assert t.target_state == "returned"
    assert t.coordinator_method == "record_returned"


# ── 6. exception → no state change ─────────────────────────────────────────

@pytest.mark.parametrize("code", [
    "exception", "delay", "customs_hold", "customs-hold",
    "address_issue", "address-issue",
])
def test_exception_codes_do_not_change_state(code):
    t = cet.translate(_ev(code))
    assert t.target_state is None
    assert t.coordinator_method == "record_exception"
    assert t.unknown is False


# ── 7. unknown status → no state change, unknown=True ──────────────────────

@pytest.mark.parametrize("code", [
    "made-up-code", "scanned-by-aliens", "", "  ",
])
def test_unknown_status_marks_unknown(code):
    t = cet.translate(_ev(code))
    assert t.target_state is None
    assert t.coordinator_method == "record_exception"
    assert t.unknown is True


def test_translation_is_a_frozen_dataclass():
    t = cet.translate(_ev("delivered"))
    with pytest.raises(Exception):
        # frozen=True → AttributeError or FrozenInstanceError
        t.target_state = "x"  # type: ignore[misc]


# ── 8. Source-grep: no FastAPI / coordinator / adapter ────────────────────

@pytest.mark.parametrize("forbidden", [
    "import fastapi", "from fastapi",
    "import flask",   "from flask",
])
def test_source_no_web_framework(src, forbidden):
    assert forbidden not in src, (
        f"carrier_event_translator.py contains {forbidden!r} — translator "
        f"is pure logic, no web-framework imports."
    )


@pytest.mark.parametrize("forbidden", [
    "carrier_coordinator",
    "from .carrier_coordinator",
    "from . import carrier_coordinator",
    "CarrierCoordinator",
])
def test_source_no_coordinator_import(src, forbidden):
    assert forbidden not in src, (
        f"carrier_event_translator.py contains {forbidden!r} — translator "
        f"must not couple to the coordinator."
    )


@pytest.mark.parametrize("forbidden", [
    "from .adapters", "from ..adapters",
    "DHLExpressLiveAdapter", "DHLExpressStubAdapter",
    "from ..services.carrier.adapters", "from .services.carrier.adapters",
])
def test_source_no_adapter_import(src, forbidden):
    assert forbidden not in src, (
        f"carrier_event_translator.py contains {forbidden!r} — translator "
        f"is adapter-agnostic; events arrive already parsed."
    )


@pytest.mark.parametrize("forbidden", [
    "import requests", "from requests",
    "import httpx",    "from httpx",
    "import urllib",   "from urllib",
])
def test_source_no_http(src, forbidden):
    assert forbidden not in src, (
        f"carrier_event_translator.py contains {forbidden!r}."
    )


def test_source_no_db_or_io(src):
    for forbidden in ["sqlite3", "open(", ".write_text(", ".read_text(",
                      "Path(", "tempfile"]:
        assert forbidden not in src, (
            f"carrier_event_translator.py contains {forbidden!r} — "
            f"the translator does no I/O."
        )
