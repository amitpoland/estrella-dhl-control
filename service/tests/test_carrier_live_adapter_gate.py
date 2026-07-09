"""
Phase C tests — DhlExpressLiveAdapter guard layer.

Verifies that the live adapter raises the correct typed exceptions
before any API interaction, and that NotImplementedError marks the
Phase D boundary for callers that pass all guards.

No HTTP. No DB. No credentials leaked.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.services.carrier.adapters.live import DhlExpressLiveAdapter
from app.services.carrier.factory import CarrierConfig, get_adapter
from app.services.carrier.models.shipment import (
    CarrierAllowlistError,
    CarrierConfigError,
    CarrierGateError,
    ShipmentRequest,
)


def _req(batch_id: str = "BATCH-001") -> ShipmentRequest:
    return ShipmentRequest(
        batch_id=batch_id,
        shipper_account="ACC-001",
        # phone is required by the create_shipment receiver-contact gate (#824);
        # without it the guards-pass HTTP tests fail before reaching the mock.
        recipient_address={"name": "Test", "country": "PL", "phone": "+48500600700"},
        declared_value=500.0,
        currency="EUR",
        weight_kg=1.0,
        dimensions={"length": 20, "width": 15, "height": 10},
    )


def _live_adapter(api_key="k", api_secret="s", allowlist="BATCH-001", use_sandbox=False) -> DhlExpressLiveAdapter:
    cfg = CarrierConfig(
        status="live",
        api_key=api_key,
        api_secret=api_secret,
        live_allowlist=allowlist,
        use_sandbox=use_sandbox,
    )
    return DhlExpressLiveAdapter(cfg)


# ── factory gate (pending / unknown) ─────────────────────────────────────────


def test_factory_pending_raises_gate_error():
    with pytest.raises(CarrierGateError):
        get_adapter(CarrierConfig(status="pending"))


def test_factory_unknown_status_raises_gate_error():
    with pytest.raises(CarrierGateError):
        get_adapter(CarrierConfig(status="active"))


# ── allowlist guard ───────────────────────────────────────────────────────────


def test_empty_allowlist_raises_allowlist_error():
    adapter = _live_adapter(allowlist="")
    with pytest.raises(CarrierAllowlistError, match="empty"):
        adapter.create_shipment(_req("BATCH-001"))


def test_batch_not_in_allowlist_raises_allowlist_error():
    adapter = _live_adapter(allowlist="BATCH-PERMITTED")
    with pytest.raises(CarrierAllowlistError, match="BATCH-001"):
        adapter.create_shipment(_req("BATCH-001"))


def test_batch_in_allowlist_passes_allowlist_guard():
    adapter = _live_adapter(allowlist="BATCH-001", api_key=None, api_secret=None)
    # passes allowlist, fails on missing creds — correct progression
    with pytest.raises(CarrierConfigError):
        adapter.create_shipment(_req("BATCH-001"))


def test_allowlist_trims_whitespace():
    adapter = _live_adapter(allowlist=" BATCH-001 , BATCH-002 ", api_key=None, api_secret=None)
    with pytest.raises(CarrierConfigError):
        adapter.create_shipment(_req("BATCH-001"))


def test_allowlist_multi_entry():
    adapter = _live_adapter(allowlist="BATCH-001,BATCH-002", api_key=None, api_secret=None)
    with pytest.raises(CarrierConfigError):
        adapter.create_shipment(_req("BATCH-002"))


# ── credential guard ──────────────────────────────────────────────────────────


def test_missing_api_key_raises_config_error():
    adapter = _live_adapter(api_key=None, api_secret="s", allowlist="BATCH-001")
    with pytest.raises(CarrierConfigError, match="API_KEY"):
        adapter.create_shipment(_req("BATCH-001"))


def test_missing_api_secret_raises_config_error():
    adapter = _live_adapter(api_key="k", api_secret=None, allowlist="BATCH-001")
    with pytest.raises(CarrierConfigError, match="API_SECRET"):
        adapter.create_shipment(_req("BATCH-001"))


def test_empty_api_key_raises_config_error():
    adapter = _live_adapter(api_key="", api_secret="s", allowlist="BATCH-001")
    with pytest.raises(CarrierConfigError):
        adapter.create_shipment(_req("BATCH-001"))


# ── Phase D — HTTP calls (guards pass → real DHL API called) ─────────────────


def test_create_shipment_calls_dhl_api_when_guards_pass():
    """Both guards pass → Phase D makes POST to DHL API (mocked)."""
    adapter = _live_adapter(api_key="k", api_secret="s", allowlist="BATCH-001")
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = {
        "shipmentTrackingNumber": "1234567890",
        "documents": [],
    }
    with patch("app.services.carrier.adapters.live.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp
        result = adapter.create_shipment(_req("BATCH-001"))
    assert result.tracking_ref == "1234567890"
    assert result.simulated is False


def test_get_shipment_calls_dhl_api_with_creds():
    """Credentials present → Phase D makes GET to DHL shipment API (mocked)."""
    adapter = _live_adapter(api_key="k", api_secret="s")
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = {"status": "delivered"}
    with patch("app.services.carrier.adapters.live.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
        result = adapter.get_shipment("SIM-FAKE")
    assert result.tracking_ref == "SIM-FAKE"
    assert result.simulated is False


def test_get_shipment_raises_config_error_without_creds():
    adapter = _live_adapter(api_key=None, api_secret=None, allowlist="BATCH-001")
    with pytest.raises(CarrierConfigError):
        adapter.get_shipment("SIM-FAKE")


# ── credentials never leaked ──────────────────────────────────────────────────


def test_config_error_message_does_not_contain_credential_value():
    adapter = _live_adapter(api_key=None, api_secret="super-secret", allowlist="BATCH-001")
    with pytest.raises(CarrierConfigError) as exc:
        adapter.create_shipment(_req("BATCH-001"))
    assert "super-secret" not in str(exc.value)


def test_allowlist_error_does_not_contain_api_key():
    adapter = _live_adapter(api_key="my-api-key-value", api_secret="s", allowlist="BATCH-OTHER")
    with pytest.raises(CarrierAllowlistError) as exc:
        adapter.create_shipment(_req("BATCH-001"))
    assert "my-api-key-value" not in str(exc.value)


# ── sandbox URL routing ───────────────────────────────────────────────────────


def test_api_path_production_default():
    adapter = _live_adapter(use_sandbox=False)
    assert adapter._api_path() == "/mydhlapi"


def test_api_path_sandbox():
    adapter = _live_adapter(use_sandbox=True)
    assert adapter._api_path() == "/mydhlapi/test"


def test_create_shipment_uses_production_url_by_default():
    """Production URL must not contain /test path segment."""
    adapter = _live_adapter(use_sandbox=False)
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = {"shipmentTrackingNumber": "PROD-AWB-001", "documents": []}
    with patch("app.services.carrier.adapters.live.httpx.Client") as mock_client_cls:
        mock_post = mock_client_cls.return_value.__enter__.return_value.post
        mock_post.return_value = mock_resp
        adapter.create_shipment(_req("BATCH-001"))
    url_called = mock_post.call_args[0][0]
    assert "/mydhlapi/shipments" in url_called
    assert "/mydhlapi/test" not in url_called


def test_create_shipment_uses_sandbox_url_when_flag_set():
    """Sandbox flag routes to /mydhlapi/test/shipments, not /mydhlapi/test/mydhlapi/shipments."""
    adapter = _live_adapter(use_sandbox=True)
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = {"shipmentTrackingNumber": "SAND-AWB-001", "documents": []}
    with patch("app.services.carrier.adapters.live.httpx.Client") as mock_client_cls:
        mock_post = mock_client_cls.return_value.__enter__.return_value.post
        mock_post.return_value = mock_resp
        adapter.create_shipment(_req("BATCH-001"))
    url_called = mock_post.call_args[0][0]
    assert url_called.endswith("/mydhlapi/test/shipments")
    # Guard against the double-path bug: /mydhlapi/test/mydhlapi/test/shipments
    assert url_called.count("/mydhlapi/test") == 1
