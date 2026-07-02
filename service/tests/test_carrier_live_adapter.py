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

    def _raise_with_body(self, tmp_path, body: dict, status_code: int = 400) -> str:
        """Run create_shipment against a mocked DHL error body; return the message."""
        config = _make_config()
        adapter = DhlExpressLiveAdapter(config)
        request = _make_request()

        resp = MagicMock()
        resp.is_success = False
        resp.status_code = status_code
        resp.json.return_value = body
        resp.text = str(body)

        with _mock_settings(tmp_path), patch("httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = resp
            with pytest.raises(CarrierGateError) as exc_info:
                adapter.create_shipment(request)
        return str(exc_info.value)

    def test_dhl_422_additional_details_strings_all_surfaced(self, tmp_path):
        """Every string entry in additionalDetails appears in the raised error."""
        msg = self._raise_with_body(tmp_path, {
            "detail": "Multiple problems found, see Additional Details",
            "additionalDetails": [
                "#/content/declaredValue: is not allowed for non dutiable shipment",
                "#/customerDetails/receiverDetails/postalAddress/postalCode: invalid format",
                "997: The requested product is not available",
            ],
        }, status_code=422)

        assert "DHL API 422" in msg
        assert "Multiple problems found" in msg
        assert "declaredValue: is not allowed" in msg
        assert "postalCode: invalid format" in msg
        assert "997: The requested product is not available" in msg

    def test_dhl_422_additional_details_dict_entries_surfaced(self, tmp_path):
        """Dict-form entries surface code, path and message fields."""
        msg = self._raise_with_body(tmp_path, {
            "detail": "Multiple problems found, see Additional Details",
            "additionalDetails": [
                {"code": "7121", "path": "#/content/exportDeclaration",
                 "message": "exportDeclaration is mandatory when product is dutiable"},
            ],
        }, status_code=422)

        assert "7121" in msg
        assert "#/content/exportDeclaration" in msg
        assert "exportDeclaration is mandatory" in msg

    def test_dhl_error_without_additional_details_unchanged(self, tmp_path):
        """Simple DHL errors keep the original single-line message shape."""
        msg = self._raise_with_body(
            tmp_path, {"detail": "Invalid shipper address"}, status_code=400
        )
        assert msg == "DHL API 400: Invalid shipper address"
        assert "Additional details" not in msg


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


class TestRegistrationNumbers:
    """DHL requires issuerCountryCode on every registrationNumbers entry (422 otherwise)."""

    def _make_request_with_regs(self, eori=None, vat=None, country="DE"):
        from app.services.carrier.models.shipment import ShipmentRequest
        return ShipmentRequest(
            batch_id="BATCH-REG",
            shipper_account="123456789",
            recipient_address={
                "name": "Test GmbH",
                "street": "Hauptstrasse 1",
                "city": "Berlin",
                "postal_code": "10115",
                "country_code": country,
                "phone": "+4930123456",
            },
            declared_value=500.0,
            currency="EUR",
            weight_kg=2.0,
            dimensions={"length_cm": 20, "width_cm": 15, "height_cm": 10},
            receiver_eori=eori,
            receiver_vat_id=vat,
        )

    def _get_body(self, request, tmp_path):
        from app.services.carrier.adapters.live import _build_shipment_body
        mock_settings = MagicMock()
        mock_settings.dhl_express_shipper_name = "Estrella"
        mock_settings.dhl_express_shipper_address1 = "ul. Sabaly 58"
        mock_settings.dhl_express_shipper_city = "Warszawa"
        mock_settings.dhl_express_shipper_postal_code = "02-174"
        mock_settings.dhl_express_shipper_country_code = "PL"
        mock_settings.dhl_express_shipper_phone = "+48516081994"
        return _build_shipment_body(request, mock_settings)

    def test_eori_includes_issuer_country_code_from_prefix(self, tmp_path):
        req = self._make_request_with_regs(eori="DE123456789012345")
        body = self._get_body(req, tmp_path)
        reg = body["customerDetails"]["receiverDetails"]["registrationNumbers"][0]
        assert reg["typeCode"] == "EOR"
        assert reg["issuerCountryCode"] == "DE"

    def test_vat_includes_issuer_country_code_from_prefix(self, tmp_path):
        req = self._make_request_with_regs(vat="PL1234567890")
        body = self._get_body(req, tmp_path)
        reg = body["customerDetails"]["receiverDetails"]["registrationNumbers"][0]
        assert reg["typeCode"] == "EUV"
        assert reg["issuerCountryCode"] == "PL"

    def test_numeric_prefix_falls_back_to_receiver_country(self, tmp_path):
        req = self._make_request_with_regs(eori="123456789", country="FR")
        body = self._get_body(req, tmp_path)
        reg = body["customerDetails"]["receiverDetails"]["registrationNumbers"][0]
        assert reg["issuerCountryCode"] == "FR"

    def test_no_reg_numbers_produces_no_key(self, tmp_path):
        req = self._make_request_with_regs()
        body = self._get_body(req, tmp_path)
        assert "registrationNumbers" not in body["customerDetails"]["receiverDetails"]


class TestCustomerReferences:
    """DHL 7021: AAO is not a valid customerReferences typeCode (must be CU, FF, etc.)."""

    def _get_body(self, request, tmp_path):
        from app.services.carrier.adapters.live import _build_shipment_body
        mock_settings = MagicMock()
        mock_settings.dhl_express_shipper_name = "Estrella"
        mock_settings.dhl_express_shipper_address1 = "ul. Sabaly 58"
        mock_settings.dhl_express_shipper_city = "Warszawa"
        mock_settings.dhl_express_shipper_postal_code = "02-174"
        mock_settings.dhl_express_shipper_country_code = "PL"
        mock_settings.dhl_express_shipper_phone = "+48516081994"
        return _build_shipment_body(request, mock_settings)

    def _make_req(self, customer_ref=None, shipment_ref=None):
        return ShipmentRequest(
            batch_id="BATCH-REF",
            shipper_account="123456789",
            recipient_address={
                "name": "Test Co",
                "street": "Test St 1",
                "city": "Berlin",
                "postal_code": "10115",
                "country_code": "DE",
                "phone": "+4930000000",
            },
            declared_value=100.0,
            currency="EUR",
            weight_kg=1.0,
            dimensions={"length_cm": 10, "width_cm": 10, "height_cm": 10},
            customer_reference=customer_ref,
            shipment_reference=shipment_ref,
        )

    def test_aao_never_emitted(self, tmp_path):
        req = self._make_req(customer_ref="CUST-001", shipment_ref="SHIP-001")
        body = self._get_body(req, tmp_path)
        refs = body.get("customerReferences", [])
        type_codes = [r.get("typeCode") for r in refs]
        assert "AAO" not in type_codes, f"AAO must not appear in customerReferences; got {refs}"

    def test_shipment_reference_uses_cu(self, tmp_path):
        req = self._make_req(shipment_ref="SHIP-REF-001")
        body = self._get_body(req, tmp_path)
        refs = body.get("customerReferences", [])
        assert len(refs) == 1
        assert refs[0]["typeCode"] == "CU"
        assert refs[0]["value"] == "SHIP-REF-001"

    def test_customer_reference_uses_cu(self, tmp_path):
        req = self._make_req(customer_ref="CUST-REF-001")
        body = self._get_body(req, tmp_path)
        refs = body.get("customerReferences", [])
        assert len(refs) == 1
        assert refs[0]["typeCode"] == "CU"
        assert refs[0]["value"] == "CUST-REF-001"

    def test_both_references_both_use_cu(self, tmp_path):
        req = self._make_req(customer_ref="CUST-001", shipment_ref="SHIP-001")
        body = self._get_body(req, tmp_path)
        refs = body.get("customerReferences", [])
        assert len(refs) == 2
        assert all(r["typeCode"] == "CU" for r in refs)

    def test_no_references_omits_key(self, tmp_path):
        req = self._make_req()
        body = self._get_body(req, tmp_path)
        assert "customerReferences" not in body
