"""
test_dhl_express_live_adapter_protocol.py — DL-F1 Protocol-level checks.

Pinned by DL-F1 spec rule 1 (live adapter satisfies CarrierAdapter).

Required:
  * isinstance(live, CarrierAdapter) — runtime Protocol check.
  * Each of the four send-side methods exists with the expected
    parameter names.
"""
from __future__ import annotations

import pytest

from app.services.carrier.adapters import base as ab
from app.services.carrier.adapters.dhl_express_live import (
    DHLExpressLiveAdapter,
)


@pytest.fixture()
def live() -> DHLExpressLiveAdapter:
    """Construct with no http_client surface call — never instantiates a
    real httpx.Client because we inject a sentinel."""
    return DHLExpressLiveAdapter(
        base_url="https://example.test/mydhlapi",
        username="u", password="p", account_number="123",
        http_client=object(),  # not called by the Protocol check
    )


# ── 1. Protocol satisfaction ────────────────────────────────────────────────

def test_live_satisfies_carrier_adapter_protocol(live):
    assert isinstance(live, ab.CarrierAdapter)


def test_live_carrier_attribute(live):
    assert live.carrier == "dhl"


# ── Method-existence sanity ────────────────────────────────────────────────

@pytest.mark.parametrize("method", [
    "create_shipment", "cancel_shipment", "fetch_label",
    "schedule_pickup", "parse_webhook_event",
])
def test_live_has_protocol_method(live, method):
    assert callable(getattr(live, method, None)), (
        f"live adapter is missing Protocol method {method!r}"
    )


def test_parse_only_construction_is_allowed():
    """The webhook receiver constructs the live adapter with no args
    to use parse_push_payload only. That construction must succeed —
    send-side methods raise CarrierResponseError on demand instead of
    rejecting at the constructor."""
    parse_only = DHLExpressLiveAdapter()
    assert parse_only.carrier == "dhl"
    # Send-side without credentials → CarrierResponseError, NOT crash
    from app.services.carrier.adapters.base import CarrierResponseError
    from app.services.carrier.base import CarrierAddress, CarrierShipmentRequest, PackageSpec
    req = CarrierShipmentRequest(
        batch_id="B", ship_from=CarrierAddress(name="x"),
        ship_to=CarrierAddress(name="y"),
        packages=(PackageSpec(weight_kg=1, length_cm=1, width_cm=1, height_cm=1),),
    )
    with pytest.raises(CarrierResponseError) as exc:
        parse_only.create_shipment(req)
    assert "credentials" in str(exc.value).lower()


@pytest.mark.parametrize("missing", ["base_url", "username", "password",
                                       "account_number"])
def test_send_side_blocked_when_any_credential_missing(missing):
    """If any of the four required-for-send fields is empty, send-side
    methods raise CarrierResponseError without making an HTTP call."""
    from app.services.carrier.adapters.base import CarrierResponseError
    kwargs = {
        "base_url":       "https://x.test/mydhlapi",
        "username":       "u",
        "password":       "p",
        "account_number": "ACC",
    }
    kwargs[missing] = ""
    adapter = DHLExpressLiveAdapter(http_client=object(), **kwargs)
    with pytest.raises(CarrierResponseError):
        adapter.cancel_shipment("AAA")
