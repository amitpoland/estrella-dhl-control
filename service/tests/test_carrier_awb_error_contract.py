"""AWB HTTP 500 incident (2026-08-18) — booking error contract + duplicate-AWB guards.

Three defects at one shared boundary, all pinned here.

1. ROUTE CONTRACT. ``CarrierAllowlistError`` and ``CarrierConfigError`` are
   SIBLINGS of ``CarrierGateError`` in models/shipment.py, not subclasses. The
   booking route caught only ``CarrierGateError``, so an operational refusal
   (batch not on the live allowlist, carrier not configured) escaped FastAPI as
   an unexplained HTTP 500. Known operational failures must return the
   structured business error contract this route already uses elsewhere.

2. DUPLICATE-AWB WINDOW. ``_execute`` used to run the shadow log + redaction
   between the provider write and the COMPLETE update. Anything raising in that
   window left a PENDING row with no tracking_ref for a shipment DHL had really
   created, and ``_handle_existing`` re-entered ``_execute`` on retry -> a second
   live AWB. Adapter truth is now persisted first and the audit block can no
   longer fail the request.

3. AMBIGUOUS PROVIDER STATE. A transport error used to escape as a 500 with the
   row left PENDING, so the operator's retry re-invoked the adapter. A lost
   reply now fails CLOSED: the key is parked terminal and the operator is told
   to reconcile at the carrier instead.

The batch id below is synthetic. The production batch of the incident is named
only in the campaign report, never in this repository.

No live carrier call is made anywhere in this module.
"""
from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_carrier_actions import router as actions_router
from app.auth.dependencies import get_current_user
from app.core.security import require_api_key
from app.services.carrier.adapters.live import DhlExpressLiveAdapter
from app.services.carrier.coordinator import CarrierCoordinator, CoordinatorConfig
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import (
    CarrierAllowlistError,
    CarrierConfigError,
    CarrierGateError,
    CarrierProviderStateUnknownError,
    ShipmentMode,
    ShipmentRequest,
    ShipmentResult,
    ShipmentState,
    compute_idempotency_key,
)
from app.services.carrier.persistence.shipment_db import get_shipment

_MOCK_STORAGE_ROOT = Path(tempfile.mkdtemp(prefix="pz-awb-errctr-"))

# Synthetic stand-in for the incident batch. The digits are an INBOUND import
# AWB (audit.json source=intake_upload); they grant no booking authority.
_INBOUND_AWB = "1000000001"
INCIDENT_BATCH = "SHIPMENT_" + _INBOUND_AWB + "_2026-08_aaaa1111"


# -- exception model -----------------------------------------------------------


def test_carrier_errors_are_siblings_not_subclasses():
    """The mechanical cause of the 500 -- pin it so a future refactor is visible."""
    assert not issubclass(CarrierAllowlistError, CarrierGateError)
    assert not issubclass(CarrierConfigError, CarrierGateError)
    assert not issubclass(CarrierProviderStateUnknownError, CarrierGateError)


# -- route contract ------------------------------------------------------------


@contextmanager
def _patched_settings(**overrides):
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.carrier_storage_root = None
        mock_settings.storage_root = _MOCK_STORAGE_ROOT
        for name, value in overrides.items():
            setattr(mock_settings, name, value)
        yield mock_settings


@pytest.fixture(autouse=True)
def _incoterm_resolved(monkeypatch):
    monkeypatch.setattr(
        "app.api.routes_carrier_actions._resolve_booking_incoterm",
        lambda **kwargs: {"value": "DAP", "source": "customer_master"},
    )
    # Recipient address has ONE authority (Customer Master via client_ref) and
    # resolves BEFORE this route's other checks. These fixtures carry no
    # Customer Master rows, so stub the derivation the way the Incoterm
    # authority is stubbed above — the address contract itself is pinned in
    # test_carrier_routes_awb_authority.py.
    monkeypatch.setattr(
        "app.services.awb_address_authority.derive_awb_address_authority",
        lambda batch_id, storage_root, client_ref=None: {
            "name": "Stub Customer", "street": "Stub Street 1",
            "city": "Stub City", "country": "PL", "source": "bill_to",
        },
    )


@contextmanager
def _client_raising(exc):
    """TestClient whose coordinator raises `exc` from create_shipment().

    raise_server_exceptions=False is deliberate: it makes an unhandled
    exception observable as a real 500 response, which is exactly the
    pre-fix behaviour this module forbids.
    """
    app = FastAPI()
    app.include_router(actions_router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1, "email": "t@test.internal", "role": "logistics",
        "is_active": True, "is_approved": True,
    }
    coord = MagicMock()
    coord.create_shipment.side_effect = exc
    with _patched_settings():
        from app.api.routes_carrier_actions import _get_coordinator
        app.dependency_overrides[_get_coordinator] = lambda: coord
        yield TestClient(app, raise_server_exceptions=False)


def _post(client):
    return client.post(
        "/api/v1/carrier/" + INCIDENT_BATCH + "/shipment",
        json={
            "shipper_account": "TEST_ACC",
            "recipient_address": {"name": "N", "street": "S", "city": "C",
                                  "country": "Poland", "phone": "+48100200300"},
            "declared_value": 100.0,
            "currency": "USD",
            "weight_kg": 1.0,
            "dimensions": {"length": 10, "width": 10, "height": 10},
        },
    )


def test_allowlist_refusal_is_structured_422_never_500():
    exc = CarrierAllowlistError(
        "batch_id '" + INCIDENT_BATCH + "' is not in carrier_live_allowlist."
    )
    with _client_raising(exc) as client:
        resp = _post(client)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "CARRIER_LIVE_ALLOWLIST_BLOCKED"
    assert detail["guidance"]
    # The operator must be told no chargeable write happened.
    assert "no live carrier request was sent" in detail["guidance"].lower()


def test_carrier_config_error_is_structured_422_never_500():
    with _client_raising(CarrierConfigError("FEDEX_NOT_CONFIGURED")) as client:
        resp = _post(client)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "CARRIER_NOT_CONFIGURED"
    # No silent carrier substitution may be suggested.
    assert "substitute" in detail["guidance"].lower()


def test_provider_state_unknown_is_structured_422_never_500():
    """The opposite message to the two above: a write MAY have landed."""
    exc = CarrierProviderStateUnknownError(
        "DHL did not return a usable response (ReadTimeout) after the "
        "create-shipment request was sent."
    )
    with _client_raising(exc) as client:
        resp = _post(client)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "CARRIER_PROVIDER_STATE_UNKNOWN"
    guidance = detail["guidance"].lower()
    # It must NOT claim nothing was sent, and it must send the operator to the
    # carrier rather than back to the button.
    assert "no live carrier request was sent" not in guidance
    assert "was sent" in guidance
    assert "carrier portal" in guidance


def test_gate_error_contract_unchanged():
    """The pre-existing CarrierGateError -> 422 string contract must not move."""
    with _client_raising(CarrierGateError("Receiver phone is required")) as client:
        resp = _post(client)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Receiver phone is required"


# -- adapter: transport-error classification -----------------------------------
#
# The distinction is the whole safety property. ConnectError means the request
# never left this host (retry is free); a read timeout means it did (retry may
# buy a second AWB).


def _live_config() -> CarrierConfig:
    return CarrierConfig(
        status="live",
        api_key="test-key",
        api_secret="test-secret",
        api_url="https://express.api.dhl.example",
        account_number="000000000",
        live_allowlist="*",
    )


def _live_request() -> ShipmentRequest:
    return ShipmentRequest(
        batch_id=INCIDENT_BATCH,
        shipper_account="000000000",
        recipient_address={
            "name": "Test Receiver", "street": "ul. Testowa 1", "city": "Warsaw",
            "postal_code": "00-001", "country_code": "PL", "phone": "+48123456789",
        },
        declared_value=1000.0,
        currency="EUR",
        weight_kg=5.0,
        dimensions={"length_cm": 30, "width_cm": 20, "height_cm": 10},
        incoterm="DAP",
    )


@contextmanager
def _live_adapter_post_raising(exc, tmp_path):
    """DhlExpressLiveAdapter whose shipment POST raises `exc`.

    httpx.Client is patched module-wide, so the /rates discovery GET is mocked
    too; it is forced non-success so the adapter falls back to the requested
    product code and nothing is cached.
    """
    settings_mock = MagicMock()
    settings_mock.dhl_express_shipper_country_code = "IN"
    settings_mock.dhl_express_shipper_city = "Mumbai"
    settings_mock.dhl_express_shipper_postal_code = "400001"
    settings_mock.carrier_storage_root = None
    settings_mock.storage_root = tmp_path
    with patch("app.core.config.settings", settings_mock), \
            patch("httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.get.return_value.is_success = False
        client.post.side_effect = exc
        yield DhlExpressLiveAdapter(_live_config())


def test_connect_error_is_a_gate_error_nothing_was_sent(tmp_path):
    with _live_adapter_post_raising(httpx.ConnectError("refused"), tmp_path) as adapter:
        with pytest.raises(CarrierGateError) as excinfo:
            adapter.create_shipment(_live_request())
    assert "No shipment was created" in str(excinfo.value)


def test_lost_reply_is_provider_state_unknown(tmp_path):
    """ReadTimeout: the POST went out, the answer did not come back."""
    with _live_adapter_post_raising(httpx.ReadTimeout("timed out"), tmp_path) as adapter:
        with pytest.raises(CarrierProviderStateUnknownError):
            adapter.create_shipment(_live_request())


def test_connect_timeout_is_not_misread_as_a_lost_reply(tmp_path):
    """ConnectTimeout subclasses TimeoutException -- handler order matters."""
    with _live_adapter_post_raising(httpx.ConnectTimeout("t"), tmp_path) as adapter:
        with pytest.raises(CarrierGateError):
            adapter.create_shipment(_live_request())


# -- coordinator: duplicate-AWB window -----------------------------------------


def _config(tmp_path) -> CoordinatorConfig:
    return CoordinatorConfig(
        carrier_config=CarrierConfig(status="shadow"),
        shipment_db_path=tmp_path / "shipments.db",
        shadow_log_db_path=tmp_path / "shadow.db",
    )


def _req(batch_id: str = INCIDENT_BATCH) -> ShipmentRequest:
    return ShipmentRequest(
        batch_id=batch_id,
        shipper_account="ACC-001",
        recipient_address={"name": "Test", "country": "PL"},
        declared_value=999.0,
        currency="USD",
        weight_kg=3.0,
        dimensions={"length": 30, "width": 20, "height": 15},
    )


class _CountingAdapter:
    """Stands in for the LIVE adapter. Counts provider writes; performs none."""

    carrier_id = "DHL"

    def __init__(self, tracking_ref="1234567890", pre_flight_error=None,
                 provider_error=None):
        self.calls = 0
        self._tracking_ref = tracking_ref
        self._pre_flight_error = pre_flight_error
        self._provider_error = provider_error

    def create_shipment(self, request):
        if self._pre_flight_error is not None:
            # Mirrors live.py: the allowlist/credential guards are the FIRST
            # statements of create_shipment, ahead of every HTTP call. A raise
            # here means the provider was never contacted.
            raise self._pre_flight_error
        self.calls += 1
        if self._provider_error is not None:
            # Raised AFTER the write is counted: the request left the host.
            raise self._provider_error
        return ShipmentResult(
            idempotency_key="ignored",
            mode=ShipmentMode.LIVE,
            state=ShipmentState.PENDING,
            tracking_ref=self._tracking_ref,
            simulated=False,
        )


@contextmanager
def _coordinator_with(adapter, tmp_path):
    with patch.object(CarrierCoordinator, "_adapter_for", return_value=adapter):
        yield CarrierCoordinator(_config(tmp_path))


def test_audit_failure_after_provider_write_still_returns_the_booking(tmp_path):
    """The duplicate-AWB window: DHL created the AWB, the audit write blew up.

    A booked, chargeable AWB must never be hidden behind an HTTP 500 -- the
    operator would see a failure and press the button again.
    """
    adapter = _CountingAdapter(tracking_ref="9988776655")
    req = _req()
    key = compute_idempotency_key(req)

    with _coordinator_with(adapter, tmp_path) as coord:
        with patch(
            "app.services.carrier.coordinator._shadow_log_append",
            side_effect=RuntimeError("database is locked"),
        ):
            result = coord.create_shipment(req)

        assert result.tracking_ref == "9988776655"
        row = get_shipment(coord._config.shipment_db_path, key)
        assert row["state"] == ShipmentState.COMPLETE.value
        assert row["tracking_ref"] == "9988776655"
        assert adapter.calls == 1

        # The operator retries anyway. It must replay, not re-book.
        replay = coord.create_shipment(req)

    assert adapter.calls == 1, "retry re-invoked the adapter -> duplicate live AWB"
    assert replay.replayed is True
    assert replay.tracking_ref == "9988776655"


def test_lost_reply_parks_the_key_and_refuses_the_retry(tmp_path):
    """Fail CLOSED: an ambiguous provider write must not be retried blindly."""
    adapter = _CountingAdapter(
        provider_error=CarrierProviderStateUnknownError("reply lost after send"),
    )
    req = _req()
    key = compute_idempotency_key(req)

    with _coordinator_with(adapter, tmp_path) as coord:
        with pytest.raises(CarrierProviderStateUnknownError):
            coord.create_shipment(req)

        row = get_shipment(coord._config.shipment_db_path, key)
        assert row["state"] == ShipmentState.FAILED.value, (
            "a PENDING row would let _handle_existing re-enter _execute"
        )
        assert row["tracking_ref"] is None

        # The retry is refused at the coordinator, before the adapter.
        with pytest.raises(CarrierGateError) as excinfo:
            coord.create_shipment(req)

    assert adapter.calls == 1, "retry re-invoked the adapter -> duplicate live AWB"
    # The refusal must not send the operator round the changed-parameter bypass.
    assert "reconcile at the carrier" in str(excinfo.value)


def test_pre_flight_refusal_sends_no_provider_write(tmp_path):
    """PROVIDER_WRITE_NOT_SENT: the guard fires before any HTTP call.

    The exception type must reach the route unchanged so the route can map it
    to the structured contract; translating it inside the adapter or the
    coordinator would re-hide it behind a generic error.
    """
    exc = CarrierAllowlistError(
        "batch_id '" + INCIDENT_BATCH + "' is not in carrier_live_allowlist."
    )
    adapter = _CountingAdapter(pre_flight_error=exc)
    req = _req()

    with _coordinator_with(adapter, tmp_path) as coord:
        with pytest.raises(CarrierAllowlistError):
            coord.create_shipment(req)
        row = get_shipment(coord._config.shipment_db_path, compute_idempotency_key(req))

    assert adapter.calls == 0
    # The crash-safe anchor exists but carries no provider truth, and it stays
    # PENDING so the operator can retry the same key once the gate is opened.
    assert row["state"] == ShipmentState.PENDING.value
    assert row["tracking_ref"] is None


def test_inbound_awb_in_batch_id_is_not_a_booking(tmp_path):
    """An imported/customs AWB reference is not booking authority.

    INCIDENT_BATCH embeds an inbound AWB (audit.json source=intake_upload).
    Existing-booking detection must key off carrier_shipments, never off the
    digits in the batch name -- otherwise the first booking of such a batch
    would be replayed as if it had already happened.
    """
    adapter = _CountingAdapter(tracking_ref="5544332211")
    with _coordinator_with(adapter, tmp_path) as coord:
        assert get_shipment(coord._config.shipment_db_path,
                            compute_idempotency_key(_req())) is None
        result = coord.create_shipment(_req())

    assert adapter.calls == 1, "batch digits were mistaken for an existing booking"
    assert result.replayed is False
    assert result.tracking_ref == "5544332211"
