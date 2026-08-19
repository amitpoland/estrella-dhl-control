"""Tracking, ePOD and document images are OPTIONAL adapter capabilities.

Booking is the only contract every carrier must honour. Before this, DHL's
extra methods existed nowhere in the base class and callers probed for them
with getattr(), which cannot tell "this carrier has no ePOD service" apart
from "someone typo'd the method name". The base now declares one shape per
capability and one way to decline it.
"""
from __future__ import annotations

import inspect

import pytest

from app.services.carrier.adapters.base import AbstractCarrierAdapter
from app.services.carrier.adapters.fedex import FedExSandboxAdapter
from app.services.carrier.adapters.live import DhlExpressLiveAdapter
from app.services.carrier.adapters.shadow import DhlExpressShadowAdapter
from app.services.carrier.models.shipment import CarrierCapabilityUnsupported

OPTIONAL = (
    "track_shipment",
    "fetch_electronic_pod",
    "fetch_electronic_pod_outcome",
    "fetch_document_image",
)


class _Minimal(AbstractCarrierAdapter):
    """A carrier that only books — still a valid adapter."""

    def create_shipment(self, request):  # pragma: no cover - never called
        raise AssertionError

    def get_shipment(self, tracking_ref):  # pragma: no cover - never called
        raise AssertionError


@pytest.mark.parametrize("name", OPTIONAL)
def test_a_booking_only_adapter_is_instantiable(name):
    """Optional means optional: no abstractmethod may block instantiation."""
    assert callable(getattr(_Minimal(), name))


@pytest.mark.parametrize("name", OPTIONAL)
def test_declining_raises_the_capability_signal_not_a_carrier_error(name):
    fn = getattr(_Minimal(), name)
    kwargs = {"pickup_year_month": "2026-08"} if name == "fetch_document_image" else {}
    with pytest.raises(CarrierCapabilityUnsupported):
        fn("1234567890", **kwargs)


@pytest.mark.parametrize("name", OPTIONAL)
def test_dhl_overrides_every_capability_with_a_matching_signature(name):
    """The base shape is copied from DHL — it must not drift away from it."""
    assert name in DhlExpressLiveAdapter.__dict__, f"DHL no longer implements {name}"
    base_sig = inspect.signature(getattr(AbstractCarrierAdapter, name))
    live_sig = inspect.signature(getattr(DhlExpressLiveAdapter, name))
    assert base_sig.parameters.keys() == live_sig.parameters.keys(), name


@pytest.mark.parametrize("adapter", [FedExSandboxAdapter, DhlExpressShadowAdapter])
@pytest.mark.parametrize("name", OPTIONAL)
def test_carriers_without_the_service_inherit_the_decline(adapter, name):
    """An adapter must never fake a capability with empty bytes or a stub dict."""
    assert name not in adapter.__dict__, (
        f"{adapter.__name__} defines {name} — if that is real, drop this pin; "
        "if it is a stub, delete the stub and let the base decline."
    )


def test_callers_route_through_the_contract_not_getattr():
    """getattr-probing cannot distinguish 'unsupported' from 'misspelled'."""
    from app.services.carrier import document_image_service, epod_service

    for mod in (epod_service, document_image_service):
        src = inspect.getsource(mod)
        assert "CarrierCapabilityUnsupported" in src, mod.__name__
        for name in OPTIONAL:
            assert f'getattr(adapter, "{name}"' not in src, f"{mod.__name__}:{name}"


def test_an_unsupported_capability_is_skipped_never_an_error(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services.carrier import epod_service as es, factory

    monkeypatch.setattr(settings, "carrier_api_status", "live", raising=False)
    monkeypatch.setattr(settings, "carrier_storage_root", tmp_path, raising=False)
    monkeypatch.setattr(factory, "get_adapter", lambda cfg: _Minimal())
    monkeypatch.setattr(
        es, "epod_file_path", lambda batch_id, tracking_ref: None, raising=False
    )
    out = es.ensure_epod_result("SHIPMENT_CAP_1", "1234567890")
    assert out.status == "skipped", out
    assert out.detail == "no_fetch", out
