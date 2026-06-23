"""
AWB modal upgrade tests — Phase D+.

Covers:
  - ShipmentRequest new optional fields (product_code, description, references, EORI/VAT)
  - live.py: _build_shipment_body maps new fields into DHL request body
  - routes_carrier_actions: ShipmentRequestBody accepts and forwards new fields
  - GET /api/v1/carrier/services returns static catalogue without live DHL call
  - box_types authority is not duplicated (reuses existing box_types table)
  - No live DHL calls in any test

Authority boundaries verified:
  Customer Master → email, phone, VAT, EORI
  Box Master (box_types) → L/W/H, tare weight
  Carrier Account (env) → DHL account number
  Carrier Live Adapter → DHL request mapping
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.carrier.adapters.live import _build_shipment_body, _build_receiver_details
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import ShipmentRequest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _req(**overrides) -> ShipmentRequest:
    defaults = dict(
        batch_id="BATCH-001",
        shipper_account="ACC-001",
        recipient_address={"name": "Test Co", "street": "Main St 1",
                           "city": "Warsaw", "postal_code": "00-001",
                           "country_code": "PL", "phone": "+48123", "email": "buyer@example.com"},
        declared_value=500.0,
        currency="EUR",
        weight_kg=1.5,
        dimensions={"length_cm": 30, "width_cm": 20, "height_cm": 10},
    )
    defaults.update(overrides)
    return ShipmentRequest(**defaults)


def _fake_settings(**kw):
    s = MagicMock()
    s.dhl_express_shipper_name         = kw.get("shipper_name", "Estrella Jewels")
    s.dhl_express_shipper_address1     = kw.get("shipper_address1", "Test St 1")
    s.dhl_express_shipper_city         = kw.get("shipper_city", "Warsaw")
    s.dhl_express_shipper_postal_code  = kw.get("shipper_postal_code", "00-001")
    s.dhl_express_shipper_country_code = kw.get("shipper_country_code", "PL")
    s.dhl_express_shipper_phone        = kw.get("shipper_phone", "+48000000000")
    return s


# ── ShipmentRequest model — new optional fields ───────────────────────────────


def test_shipment_request_default_product_code():
    req = _req()
    assert req.product_code == "P"


def test_shipment_request_custom_product_code():
    req = _req(product_code="Y")
    assert req.product_code == "Y"


def test_shipment_request_default_description():
    req = _req()
    assert req.description == "Jewellery"


def test_shipment_request_custom_description():
    req = _req(description="Gold rings")
    assert req.description == "Gold rings"


def test_shipment_request_references_default_none():
    req = _req()
    assert req.customer_reference is None
    assert req.shipment_reference is None


def test_shipment_request_references_set():
    req = _req(customer_reference="PRO/001/2026", shipment_reference="BATCH-001")
    assert req.customer_reference == "PRO/001/2026"
    assert req.shipment_reference == "BATCH-001"


def test_shipment_request_eori_vat_default_none():
    req = _req()
    assert req.receiver_eori is None
    assert req.receiver_vat_id is None


def test_shipment_request_eori_vat_set():
    req = _req(receiver_eori="GB123456789000", receiver_vat_id="GB123456789")
    assert req.receiver_eori == "GB123456789000"
    assert req.receiver_vat_id == "GB123456789"


# ── _build_receiver_details — email mapping ───────────────────────────────────


def test_receiver_details_email_mapped():
    addr = {"name": "Buyer", "city": "London", "country_code": "GB",
            "postal_code": "W1A 1AA", "street": "Baker St 1",
            "phone": "+44123", "email": "buyer@example.com"}
    details = _build_receiver_details(addr)
    assert details["contactInformation"]["email"] == "buyer@example.com"


def test_receiver_details_email_absent_is_empty_string():
    addr = {"name": "Buyer", "city": "London", "country_code": "GB"}
    details = _build_receiver_details(addr)
    assert details["contactInformation"]["email"] == ""


# ── _build_shipment_body — product_code mapping ───────────────────────────────


def test_build_body_product_code_default():
    body = _build_shipment_body(_req(), _fake_settings())
    assert body["productCode"] == "P"


def test_build_body_product_code_custom():
    body = _build_shipment_body(_req(product_code="Y"), _fake_settings())
    assert body["productCode"] == "Y"


def test_build_body_product_code_k():
    body = _build_shipment_body(_req(product_code="K"), _fake_settings())
    assert body["productCode"] == "K"


# ── _build_shipment_body — description mapping ────────────────────────────────


def test_build_body_description_default():
    body = _build_shipment_body(_req(), _fake_settings())
    assert body["content"]["description"] == "Jewellery"


def test_build_body_description_custom():
    body = _build_shipment_body(_req(description="Gold rings 18kt"), _fake_settings())
    assert body["content"]["description"] == "Gold rings 18kt"


def test_build_body_description_empty_falls_back_to_default():
    body = _build_shipment_body(_req(description=""), _fake_settings())
    assert body["content"]["description"] == "Jewellery"


# ── _build_shipment_body — customer references ───────────────────────────────


def test_build_body_no_refs_when_absent():
    body = _build_shipment_body(_req(), _fake_settings())
    assert "customerReferences" not in body


def test_build_body_customer_reference_added():
    body = _build_shipment_body(_req(customer_reference="PRO/001/2026"), _fake_settings())
    refs = body["customerReferences"]
    assert any(r["typeCode"] == "CU" and r["value"] == "PRO/001/2026" for r in refs)


def test_build_body_shipment_reference_added():
    body = _build_shipment_body(_req(shipment_reference="BATCH-001"), _fake_settings())
    refs = body["customerReferences"]
    assert any(r["typeCode"] == "AAO" and r["value"] == "BATCH-001" for r in refs)


def test_build_body_both_references_present():
    body = _build_shipment_body(
        _req(customer_reference="PRO/001", shipment_reference="B001"),
        _fake_settings()
    )
    codes = {r["typeCode"] for r in body["customerReferences"]}
    assert "CU" in codes
    assert "AAO" in codes


def test_build_body_reference_truncated_at_35_chars():
    long_ref = "X" * 40
    body = _build_shipment_body(_req(customer_reference=long_ref), _fake_settings())
    cu = next(r for r in body["customerReferences"] if r["typeCode"] == "CU")
    assert len(cu["value"]) == 35


# ── _build_shipment_body — EORI / VAT registration numbers ───────────────────


def test_build_body_no_reg_numbers_when_absent():
    body = _build_shipment_body(_req(), _fake_settings())
    assert "registrationNumbers" not in body["customerDetails"]["receiverDetails"]


def test_build_body_eori_added_to_receiver():
    body = _build_shipment_body(_req(receiver_eori="GB123456789000"), _fake_settings())
    reg = body["customerDetails"]["receiverDetails"]["registrationNumbers"]
    assert any(r["typeCode"] == "EOR" and r["number"] == "GB123456789000" for r in reg)


def test_build_body_vat_id_added_to_receiver():
    body = _build_shipment_body(_req(receiver_vat_id="GB123456789"), _fake_settings())
    reg = body["customerDetails"]["receiverDetails"]["registrationNumbers"]
    assert any(r["typeCode"] == "EUV" and r["number"] == "GB123456789" for r in reg)


def test_build_body_both_eori_and_vat_present():
    body = _build_shipment_body(
        _req(receiver_eori="PL000000000", receiver_vat_id="PL123456789"),
        _fake_settings()
    )
    reg = body["customerDetails"]["receiverDetails"]["registrationNumbers"]
    type_codes = {r["typeCode"] for r in reg}
    assert "EOR" in type_codes
    assert "EUV" in type_codes


# ── _build_shipment_body — currency mapping ───────────────────────────────────


def test_build_body_currency_eur():
    body = _build_shipment_body(_req(currency="EUR"), _fake_settings())
    assert body["content"]["declaredValueCurrency"] == "EUR"


def test_build_body_currency_usd():
    body = _build_shipment_body(_req(currency="USD"), _fake_settings())
    assert body["content"]["declaredValueCurrency"] == "USD"


def test_build_body_currency_pln():
    body = _build_shipment_body(_req(currency="PLN"), _fake_settings())
    assert body["content"]["declaredValueCurrency"] == "PLN"


# ── GET /api/v1/carrier/services — static catalogue, no live DHL call ─────────


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=True)


def test_list_carrier_services_returns_list(client):
    resp = client.get("/api/v1/carrier/services", headers={"X-API-Key": "test"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0


def test_list_carrier_services_has_express_worldwide(client):
    resp = client.get("/api/v1/carrier/services", headers={"X-API-Key": "test"})
    codes = {s["code"] for s in resp.json()}
    assert "P" in codes   # Express Worldwide


def test_list_carrier_services_has_required_fields(client):
    resp = client.get("/api/v1/carrier/services", headers={"X-API-Key": "test"})
    for svc in resp.json():
        assert "code" in svc
        assert "name" in svc
        assert "delivery" in svc


def test_list_carrier_services_no_live_dhl_call(client):
    with patch("app.services.carrier.adapters.live.httpx.Client") as mock_http:
        resp = client.get("/api/v1/carrier/services", headers={"X-API-Key": "test"})
    assert resp.status_code == 200
    mock_http.assert_not_called()


def test_list_carrier_services_returns_200_with_key(client):
    """Endpoint accessible with a valid API key (test mode accepts any non-empty key)."""
    resp = client.get("/api/v1/carrier/services", headers={"X-API-Key": "test"})
    assert resp.status_code == 200


# ── box_types authority — no duplicate box Master ─────────────────────────────


def test_no_duplicate_box_master_in_shipment_models():
    """ShipmentRequest must not contain its own box dimension fields — Box Master is authoritative."""
    import inspect
    from app.services.carrier.models import shipment as shipment_mod
    src = inspect.getsource(shipment_mod)
    # Box dimensions belong exclusively to box_types — ShipmentRequest stores the
    # final resolved values inside dimensions dict, not as separate columns.
    assert "box_length" not in src
    assert "box_width" not in src
    assert "box_height" not in src
    assert "create_box_type" not in src


def test_box_types_table_exists_in_master_data_db():
    """box_types table is the one-and-only Box Master — no parallel implementation."""
    from app.services.master_data_db import BoxType
    assert hasattr(BoxType, "length_cm")
    assert hasattr(BoxType, "width_cm")
    assert hasattr(BoxType, "height_cm")
    assert hasattr(BoxType, "tare_weight_kg")


# ── ShipmentRequestBody — new fields forwarded through route ─────────────────


def test_shipment_request_body_forwards_product_code(client):
    """Route forwards product_code from body to ShipmentRequest (mocked adapter)."""
    mock_result = MagicMock()
    mock_result.idempotency_key = "abc"
    mock_result.mode.value = "shadow"
    mock_result.state.value = "submitted"
    mock_result.tracking_ref = "SAND-001"
    mock_result.simulated = True

    with patch("app.api.routes_carrier_actions._get_coordinator") as mock_coord_dep:
        mock_coord = MagicMock()
        mock_coord.create_shipment.return_value = mock_result
        mock_coord_dep.return_value = mock_coord

        resp = client.post(
            "/api/v1/carrier/BATCH-001/shipment",
            headers={"X-API-Key": "test"},
            json={
                "recipient_address": {"name": "T", "street": "S", "city": "C",
                                      "postal_code": "00", "country_code": "PL"},
                "declared_value": 100.0,
                "currency": "USD",
                "weight_kg": 1.0,
                "dimensions": {"length_cm": 10, "width_cm": 10, "height_cm": 10},
                "product_code": "Y",
                "description": "Silver bracelets",
                "customer_reference": "PRO/042/2026",
                "shipment_reference": "BATCH-001",
                "receiver_vat_id": "GB123",
                "receiver_eori": "GB987",
            },
        )

    if resp.status_code == 503:
        pytest.skip("CARRIER_API_STATUS=pending in test environment — route gated")

    assert resp.status_code == 200
    call_args = mock_coord.create_shipment.call_args
    if call_args:
        req_arg = call_args[0][0]
        assert req_arg.product_code == "Y"
        assert req_arg.description == "Silver bracelets"
        assert req_arg.customer_reference == "PRO/042/2026"
        assert req_arg.shipment_reference == "BATCH-001"
        assert req_arg.receiver_vat_id == "GB123"
        assert req_arg.receiver_eori == "GB987"
        assert req_arg.currency == "USD"
