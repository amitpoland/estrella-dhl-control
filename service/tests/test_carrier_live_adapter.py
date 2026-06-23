"""
Phase D tests for DhlExpressLiveAdapter.

All DHL API HTTP calls are mocked via unittest.mock — no real network.
settings is patched at app.core.config.settings (the source module) since
create_shipment() does a local `from ....core.config import settings` import.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
import pytest

from app.services.carrier.adapters.live import DhlExpressLiveAdapter
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import (
    CarrierAllowlistError,
    CarrierConfigError,
    CarrierGateError,
    ShipmentMode,
    ShipmentRequest,
    ShipmentState,
)


# ── helpers ────────────────────────────────────────────────────────────────────


def _make_config(
    api_key: str = "test-key",
    api_secret: str = "test-secret",
    api_url: str = "https://express.api.dhl.com",
    account_number: str = "123456789",
    live_allowlist: str = "*",
) -> CarrierConfig:
    return CarrierConfig(
        status="live",
        api_key=api_key,
        api_secret=api_secret,
        api_url=api_url,
        account_number=account_number,
        live_allowlist=live_allowlist,
    )


def _make_request(batch_id: str = "BATCH-001") -> ShipmentRequest:
    return ShipmentRequest(
        batch_id=batch_id,
        shipper_account="123456789",
        recipient_address={
            "name": "Test Receiver",
            "street": "ul. Testowa 1",
            "city": "Warsaw",
            "postal_code": "00-001",
            "country_code": "PL",
            "phone": "+48123456789",
        },
        declared_value=1000.0,
        currency="EUR",
        weight_kg=5.0,
        dimensions={"length_cm": 30, "width_cm": 20, "height_cm": 10},
    )


def _mock_dhl_success(tracking_ref: str = "1234567890") -> MagicMock:
    resp = MagicMock()
    resp.is_success = True
    resp.status_code = 201
    resp.json.return_value = {
        "shipmentTrackingNumber": tracking_ref,
        "packages": [{"trackingNumber": tracking_ref}],
        "documents": [],
    }
    return resp


def _mock_dhl_error(status_code: int = 400, detail: str = "Bad request") -> MagicMock:
    resp = MagicMock()
    resp.is_success = False
    resp.status_code = status_code
    resp.json.return_value = {"detail": detail}
    resp.text = detail
    return resp


@contextmanager
def _mock_settings(tmp_path):
    """Patch app.core.config.settings with minimal shipper identity."""
    mock = MagicMock()
    mock.dhl_express_shipper_name = "Estrella Jewels"
    mock.dhl_express_shipper_address1 = "Test Street 1"
    mock.dhl_express_shipper_city = "Mumbai"
    mock.dhl_express_shipper_postal_code = "400001"
    mock.dhl_express_shipper_country_code = "IN"
    mock.dhl_express_shipper_phone = "+911234567890"
    mock.carrier_storage_root = None
    mock.storage_root = tmp_path
    with patch("app.core.config.settings", mock):
        yield mock


# ── tests ──────────────────────────────────────────────────────────────────────


class TestCreateShipmentSuccess:
    def test_returns_tracking_ref(self, tmp_path):
        config = _make_config()
        adapter = DhlExpressLiveAdapter(config)
        request = _make_request()
        mock_resp = _mock_dhl_success("JD014600009268252948")

        with _mock_settings(tmp_path), patch("httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = mock_resp
            result = adapter.create_shipment(request)

        assert result.tracking_ref == "JD014600009268252948"
        assert result.mode == ShipmentMode.LIVE
        assert result.state == ShipmentState.SUBMITTED
        assert result.simulated is False

    def test_saves_label_pdf_when_returned(self, tmp_path):
        config = _make_config()
        adapter = DhlExpressLiveAdapter(config)
        request = _make_request()

        pdf_bytes = b"%PDF-1.4 fake label content"
        b64_pdf = base64.b64encode(pdf_bytes).decode()
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "shipmentTrackingNumber": "AWB123",
            "documents": [{"typeCode": "label", "content": b64_pdf}],
        }

        with _mock_settings(tmp_path), patch("httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = mock_resp
            result = adapter.create_shipment(request)

        assert result.tracking_ref == "AWB123"
        labels_dir = tmp_path / "carrier" / "labels"
        assert labels_dir.exists()
        label_files = list(labels_dir.glob("*.pdf"))
        assert len(label_files) == 1
        assert label_files[0].read_bytes() == pdf_bytes


class TestCreateShipmentDhlError:
    def test_dhl_400_raises_carrier_gate_error(self, tmp_path):
        config = _make_config()
        adapter = DhlExpressLiveAdapter(config)
        request = _make_request()

        with _mock_settings(tmp_path), patch("httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = _mock_dhl_error(400, "Invalid shipper address")
            with pytest.raises(CarrierGateError, match="DHL API 400"):
                adapter.create_shipment(request)

    def test_dhl_503_raises_carrier_gate_error(self, tmp_path):
        config = _make_config()
        adapter = DhlExpressLiveAdapter(config)
        request = _make_request()

        with _mock_settings(tmp_path), patch("httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = _mock_dhl_error(503, "Service temporarily unavailable")
            with pytest.raises(CarrierGateError, match="DHL API 503"):
                adapter.create_shipment(request)


class TestAllowlist:
    def test_wildcard_allows_any_batch_id(self, tmp_path):
        config = _make_config(live_allowlist="*")
        adapter = DhlExpressLiveAdapter(config)
        request = _make_request("COMPLETELY-RANDOM-BATCH-XYZ")

        with _mock_settings(tmp_path), patch("httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = _mock_dhl_success("AWB-WILD")
            result = adapter.create_shipment(request)
        assert result.tracking_ref == "AWB-WILD"

    def test_empty_allowlist_blocks_all(self):
        config = _make_config(live_allowlist="")
        adapter = DhlExpressLiveAdapter(config)
        with pytest.raises(CarrierAllowlistError, match="carrier_live_allowlist is empty"):
            adapter.create_shipment(_make_request())

    def test_specific_allowlist_blocks_unlisted_batch(self):
        config = _make_config(live_allowlist="BATCH-ALLOWED")
        adapter = DhlExpressLiveAdapter(config)
        with pytest.raises(CarrierAllowlistError, match="not in carrier_live_allowlist"):
            adapter.create_shipment(_make_request("BATCH-OTHER"))

    def test_specific_allowlist_permits_listed_batch(self, tmp_path):
        config = _make_config(live_allowlist="BATCH-001")
        adapter = DhlExpressLiveAdapter(config)
        request = _make_request("BATCH-001")

        with _mock_settings(tmp_path), patch("httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = _mock_dhl_success("AWB999")
            result = adapter.create_shipment(request)
        assert result.tracking_ref == "AWB999"


class TestCredentialCheck:
    def test_missing_api_key_raises_config_error(self):
        config = _make_config(api_key="", live_allowlist="*")
        adapter = DhlExpressLiveAdapter(config)
        with pytest.raises(CarrierConfigError, match="DHL_EXPRESS_API_KEY"):
            adapter.create_shipment(_make_request())

    def test_missing_api_secret_raises_config_error(self):
        config = _make_config(api_secret="", live_allowlist="*")
        adapter = DhlExpressLiveAdapter(config)
        with pytest.raises(CarrierConfigError, match="DHL_EXPRESS_API_SECRET"):
            adapter.create_shipment(_make_request())
