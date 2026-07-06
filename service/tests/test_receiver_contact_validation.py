"""
DHL receiver contact validation (2026-07-06).

DHL rejects empty strings in receiverDetails/contactInformation
("phone: expected minLength: 1, actual: 0"). The builder used to emit ""
for every blank field. Pins:

  - the builder NEVER emits phone/email/postalCode as empty strings —
    blank optionals are omitted entirely
  - a blank receiver phone fails fast in create_shipment() with a clear
    CarrierGateError BEFORE any DHL HTTP call
  - a valid customer still sends phone + email
  - the AWB modal requires phone and blocks submit locally

No live DHL calls anywhere.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.carrier.adapters.live import (
    DhlExpressLiveAdapter,
    _build_receiver_details,
    _build_shipment_body,
)
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import CarrierGateError, ShipmentRequest


JSX = Path(__file__).resolve().parents[1] / "app" / "static" / "v2" / "proforma-detail.jsx"


def _req(phone="+48123456789", email="ops@example.com", postal="00-001"):
    return ShipmentRequest(
        batch_id="BATCH-CONTACT",
        shipper_account="427294774",
        recipient_address={
            "name": "Test Receiver", "street": "ul. Testowa 1", "city": "Warsaw",
            "postal_code": postal, "country_code": "PL",
            "phone": phone, "email": email,
        },
        declared_value=100.0, currency="EUR", weight_kg=1.0,
        dimensions={"length_cm": 10, "width_cm": 10, "height_cm": 10},
    )


def _fake_settings():
    mock = MagicMock()
    mock.dhl_express_shipper_name = "Estrella Jewels"
    mock.dhl_express_shipper_address1 = "ul. Sabaly 58"
    mock.dhl_express_shipper_city = "Warszawa"
    mock.dhl_express_shipper_postal_code = "02-174"
    mock.dhl_express_shipper_country_code = "PL"
    mock.dhl_express_shipper_phone = "+48516081994"
    return mock


# ── builder: no empty strings, omit blank optionals ───────────────────────────


class TestReceiverDetailsBuilder:
    def test_blank_phone_key_omitted_never_empty_string(self):
        d = _build_receiver_details({"name": "X", "city": "W", "country_code": "PL",
                                     "street": "S", "phone": ""})
        assert "phone" not in d["contactInformation"]

    def test_blank_email_key_omitted(self):
        d = _build_receiver_details({"name": "X", "city": "W", "country_code": "PL",
                                     "street": "S", "phone": "+48111", "email": ""})
        assert "email" not in d["contactInformation"]

    def test_blank_postal_code_omitted(self):
        d = _build_receiver_details({"name": "X", "city": "W", "country_code": "PL",
                                     "street": "S", "phone": "+48111"})
        assert "postalCode" not in d["postalAddress"]

    def test_whitespace_only_treated_as_blank(self):
        d = _build_receiver_details({"name": "X", "city": "W", "country_code": "PL",
                                     "street": "S", "phone": "  ", "email": " "})
        assert "phone" not in d["contactInformation"]
        assert "email" not in d["contactInformation"]

    def test_valid_contact_fields_still_sent(self):
        d = _build_receiver_details(_req().recipient_address)
        assert d["contactInformation"]["phone"] == "+48123456789"
        assert d["contactInformation"]["email"] == "ops@example.com"
        assert d["postalAddress"]["postalCode"] == "00-001"

    def test_full_body_contains_no_empty_string_contact_values(self):
        body = _build_shipment_body(_req(email="", postal=""), _fake_settings())
        contact = body["customerDetails"]["receiverDetails"]["contactInformation"]
        postal = body["customerDetails"]["receiverDetails"]["postalAddress"]
        assert "" not in contact.values()
        assert "postalCode" not in postal
        assert "email" not in contact


# ── adapter: fail fast before DHL ─────────────────────────────────────────────


class TestPhonePreflightGuard:
    def _adapter(self):
        return DhlExpressLiveAdapter(CarrierConfig(
            status="live", api_key="k", api_secret="s",
            api_url="https://express.api.dhl.com", use_sandbox=False,
            account_number="427294774", live_allowlist="*",
        ))

    def test_blank_phone_raises_clear_error_with_zero_http_calls(self):
        with patch("httpx.Client") as mock_cls:
            with pytest.raises(CarrierGateError, match="Receiver phone is required by DHL Express"):
                self._adapter().create_shipment(_req(phone=""))
        mock_cls.assert_not_called()  # no rates GET, no shipment POST

    def test_whitespace_phone_also_rejected(self):
        with patch("httpx.Client") as mock_cls:
            with pytest.raises(CarrierGateError, match="Receiver phone is required"):
                self._adapter().create_shipment(_req(phone="   "))
        mock_cls.assert_not_called()

    def test_valid_phone_reaches_dhl_with_phone_in_payload(self, tmp_path):
        settings = _fake_settings()
        settings.carrier_storage_root = None
        settings.storage_root = tmp_path
        rates = MagicMock(); rates.is_success = True
        rates.json.return_value = {"products": [{"productCode": "U"}]}
        ship = MagicMock(); ship.is_success = True
        ship.json.return_value = {"shipmentTrackingNumber": "AWB-OK", "documents": []}
        with patch("app.core.config.settings", settings), patch("httpx.Client") as mock_cls:
            client = mock_cls.return_value.__enter__.return_value
            client.get.return_value = rates
            client.post.return_value = ship
            result = self._adapter().create_shipment(_req())
        assert result.tracking_ref == "AWB-OK"
        body = client.post.call_args[1]["json"]
        contact = body["customerDetails"]["receiverDetails"]["contactInformation"]
        assert contact["phone"] == "+48123456789"
        assert contact["email"] == "ops@example.com"


# ── modal pins ────────────────────────────────────────────────────────────────


class TestModalPhoneRequired:
    def _src(self):
        return JSX.read_text(encoding="utf-8")

    def test_phone_label_marked_required(self):
        assert "Phone * (required by DHL)" in self._src()

    def test_submit_blocked_locally_with_exact_message(self):
        src = self._src()
        assert "Receiver phone is required by DHL Express." in src
        assert "if (!(form.phone || '').trim())" in src

    def test_field_hint_present(self):
        assert 'data-testid="awb-phone-missing-hint"' in self._src()

    def test_email_remains_optional(self):
        src = self._src()
        assert 'htmlFor="awb-email" style={labelStyle}>Email</label>' in src
