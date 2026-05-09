"""
test_carrier_adapter_protocol.py — runtime checks on the CarrierAdapter
Protocol and the shared dataclasses in ``carrier.base``.

Required coverage:
  1. A dummy class with all five required methods + the ``carrier``
     attribute satisfies ``isinstance(x, CarrierAdapter)``.
  2. A class missing any one of the five methods does NOT satisfy
     the Protocol.
  3. ``KNOWN_CARRIERS`` is exactly ("dhl", "fedex", "ups").
  4. ``is_known_carrier`` accepts known and rejects unknown carriers.
  5. ``CarrierAddress``, ``PackageSpec``, ``CarrierShipmentRequest``,
     ``RawShipmentResponse``, ``RawCancelResponse``, ``CarrierEvent``
     are all dataclasses; ``asdict`` round-trips them.
  6. The exception hierarchy is intact: ``CarrierAuthError``,
     ``CarrierRateLimitError``, ``CarrierTransportError``, and
     ``CarrierResponseError`` all subclass ``CarrierAdapterError``.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass

import pytest

from app.services.carrier import base as cb
from app.services.carrier.adapters import base as ab


# ── 1. Dummy adapter satisfies Protocol ────────────────────────────────────

class _GoodAdapter:
    carrier = cb.CARRIER_DHL

    def create_shipment(self, request):
        return cb.RawShipmentResponse(
            awb="X", carrier=self.carrier, label_bytes=b"",
        )

    def cancel_shipment(self, awb, *, reason=""):
        return cb.RawCancelResponse(
            carrier=self.carrier, awb=awb, accepted=True, reason=reason,
        )

    def fetch_label(self, awb, *, fmt="pdf"):
        return b""

    def parse_webhook_event(self, body, headers=None):
        return cb.CarrierEvent(
            carrier=self.carrier, awb="X", event_code="picked_up",
            occurred_at="2026-01-01T00:00:00Z",
        )

    def schedule_pickup(self, awb, *, when_iso, location=None):
        return {"confirmation": "ok"}


def test_good_adapter_satisfies_protocol():
    assert isinstance(_GoodAdapter(), ab.CarrierAdapter)


# ── 2. Missing method fails Protocol check ─────────────────────────────────

@pytest.mark.parametrize("missing", [
    "create_shipment", "cancel_shipment", "fetch_label",
    "parse_webhook_event", "schedule_pickup",
])
def test_missing_method_fails_protocol_check(missing):
    # Build a class with all methods, then remove one
    members = {k: v for k, v in vars(_GoodAdapter).items()}
    members.pop(missing, None)
    Cls = type("Partial", (), members)
    Cls.carrier = cb.CARRIER_DHL  # ensure attr present so absence of method is the only diff
    assert not isinstance(Cls(), ab.CarrierAdapter), (
        f"Adapter missing {missing!r} should fail Protocol check"
    )


# ── 3. Known carriers ───────────────────────────────────────────────────────

def test_known_carriers_constant():
    assert cb.KNOWN_CARRIERS == ("dhl", "fedex", "ups")


@pytest.mark.parametrize("c", ["dhl", "fedex", "ups"])
def test_is_known_carrier_known(c):
    assert cb.is_known_carrier(c) is True


@pytest.mark.parametrize("c", ["", None, "USPS", "DHL", "courier"])
def test_is_known_carrier_unknown(c):
    assert cb.is_known_carrier(c) is False


# ── 4. Dataclass round-trip ─────────────────────────────────────────────────

def test_carrier_address_roundtrip():
    addr = cb.CarrierAddress(
        name="Estrella Jewels",
        company="Estrella Jewels",
        street_1="ul. Marszalkowska 1",
        city="Warsaw",
        postal_code="00-001",
        country="PL",
    )
    assert is_dataclass(addr)
    d = asdict(addr)
    assert d["country"] == "PL"
    assert d["name"] == "Estrella Jewels"


def test_package_spec_roundtrip():
    pkg = cb.PackageSpec(
        weight_kg=1.2, length_cm=20, width_cm=15, height_cm=10,
        declared_value=999.0, declared_currency="USD",
    )
    assert is_dataclass(pkg)
    d = asdict(pkg)
    assert d["declared_currency"] == "USD"
    assert d["weight_kg"] == 1.2


def test_shipment_request_roundtrip():
    addr = cb.CarrierAddress(name="From", country="PL")
    pkg = cb.PackageSpec(weight_kg=1, length_cm=1, width_cm=1, height_cm=1)
    req = cb.CarrierShipmentRequest(
        batch_id="B1", ship_from=addr, ship_to=addr, packages=(pkg,),
        service_code="EXP", reference="R1",
    )
    assert is_dataclass(req)
    d = asdict(req)
    assert d["batch_id"] == "B1"
    assert d["service_code"] == "EXP"
    # packages is a tuple but asdict converts it to a list
    assert len(d["packages"]) == 1


def test_raw_shipment_response_roundtrip():
    rsp = cb.RawShipmentResponse(
        awb="123", carrier="dhl", label_bytes=b"%PDF",
        label_format="pdf",
    )
    assert is_dataclass(rsp)
    # Note: bytes survive asdict
    d = asdict(rsp)
    assert d["awb"] == "123"
    assert d["label_bytes"] == b"%PDF"


def test_raw_cancel_response_roundtrip():
    rsp = cb.RawCancelResponse(
        carrier="dhl", awb="123", accepted=False, reason="too late",
    )
    assert is_dataclass(rsp)
    d = asdict(rsp)
    assert d["accepted"] is False


def test_carrier_event_roundtrip():
    ev = cb.CarrierEvent(
        carrier="dhl", awb="X", event_code="delivered",
        occurred_at="2026-01-01T00:00:00Z", location="Warsaw",
    )
    assert is_dataclass(ev)
    d = asdict(ev)
    assert d["event_code"] == "delivered"


def test_label_artefact_dataclass():
    art = cb.LabelArtefact(sha256="a" * 64, path="/tmp/x", size=10)
    assert is_dataclass(art)
    assert asdict(art)["sha256"] == "a" * 64


# ── 5. Exception hierarchy ─────────────────────────────────────────────────

def test_exception_hierarchy():
    assert issubclass(ab.CarrierAuthError, ab.CarrierAdapterError)
    assert issubclass(ab.CarrierRateLimitError, ab.CarrierAdapterError)
    assert issubclass(ab.CarrierTransportError, ab.CarrierAdapterError)
    assert issubclass(ab.CarrierResponseError, ab.CarrierAdapterError)
    # And CarrierAdapterError itself is a RuntimeError so the
    # coordinator can catch it without resorting to the broad
    # Exception base.
    assert issubclass(ab.CarrierAdapterError, RuntimeError)
