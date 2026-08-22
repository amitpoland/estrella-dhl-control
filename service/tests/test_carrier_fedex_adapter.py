"""FedEx books through the shared carrier architecture — sandbox only.

The adapter must send the same ShipmentRequest facts DHL sends (weight,
package split, declared value, currency, Incoterm, shipper identity), persist
its documents through the one document helper, and read tracking through the
one FedEx tracking client. Production booking stays hard-blocked.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.carrier.adapters.fedex import FedExSandboxAdapter
from app.services.carrier.models.shipment import (
    CarrierGateError,
    ShipmentRequest,
    ShipmentState,
)

_ADDR = {
    "company": "Testowa Sp. z o.o.",
    "person": "Anna Kowalska",
    "street": "ul. Testowa 1",
    "city": "Warszawa",
    "postal_code": "00-001",
    "country_code": "PL",
    "phone": "+48000000000",
}


def _request(**over) -> ShipmentRequest:
    kwargs = dict(
        batch_id="SHIPMENT_FDX_1",
        shipper_account="123456789",
        recipient_address=dict(_ADDR),
        declared_value=1500.0,
        currency="EUR",
        weight_kg=3.5,
        dimensions={"length_cm": 30, "width_cm": 20, "height_cm": 10},
        product_code="INTERNATIONAL_PRIORITY",
        incoterm="DAP",
        description="Jewellery",
    )
    kwargs.update(over)
    return ShipmentRequest(**kwargs)


def _adapter(*, production: bool = False) -> FedExSandboxAdapter:
    return FedExSandboxAdapter(
        SimpleNamespace(status="live", fedex_allow_production=production)
    )


# ── The production gate ───────────────────────────────────────────────────────


def test_production_booking_stays_hard_blocked(monkeypatch):
    monkeypatch.setattr(
        "app.services.carrier.adapters.fedex._fedex_fields",
        lambda *_a, **_k: {"client_id": "cid", "client_secret": "sec"},
    )
    with pytest.raises(CarrierGateError) as exc:
        _adapter(production=True).create_shipment(_request())
    assert "FEDEX_PRODUCTION_BLOCKED" in str(exc.value)


def test_sandbox_is_the_default_base_url():
    assert _adapter()._base_url() == "https://apis-sandbox.fedex.com"


# ── The payload carries the business facts ────────────────────────────────────


def _shipment(request=None) -> dict:
    return _adapter()._ship_payload(request or _request())["requestedShipment"]


def test_single_package_carries_weight_and_dimensions():
    items = _shipment()["requestedPackageLineItems"]
    assert len(items) == 1
    assert items[0]["weight"] == {"units": "KG", "value": 3.5}
    assert items[0]["dimensions"] == {
        "length": 30, "width": 20, "height": 10, "units": "CM",
    }


def test_operator_package_split_produces_one_line_item_each():
    req = _request(packages=[
        {"weight_kg": 2.0, "length_cm": 20, "width_cm": 15, "height_cm": 10},
        {"weight_kg": 1.5, "length_cm": 30, "width_cm": 20, "height_cm": 10},
    ])
    ship = _shipment(req)
    assert [i["weight"]["value"] for i in ship["requestedPackageLineItems"]] == [2.0, 1.5]
    commodity = ship["customsClearanceDetail"]["commodities"][0]
    assert commodity["quantity"] == 2
    assert commodity["weight"] == {"units": "KG", "value": 3.5}


def test_declared_value_currency_and_description_reach_customs():
    commodity = _shipment()["customsClearanceDetail"]["commodities"][0]
    assert commodity["customsValue"] == {"amount": 1500.0, "currency": "EUR"}
    assert commodity["description"] == "Jewellery"


def test_incoterm_is_sent_and_never_invented():
    assert _shipment()["customsClearanceDetail"]["commercialInvoice"] == {
        "termsOfSale": "DAP"
    }
    with pytest.raises(CarrierGateError) as exc:
        _shipment(_request(incoterm=""))
    assert "refuse to invent" in str(exc.value)


def test_duty_payer_is_derived_from_the_incoterm():
    """DDP means the sender pays duty. Every other term does not."""
    assert _shipment(_request(incoterm="DDP"))["customsClearanceDetail"][
        "dutiesPayment"
    ] == {"paymentType": "SENDER"}
    assert _shipment(_request(incoterm="EXW"))["customsClearanceDetail"][
        "dutiesPayment"
    ] == {"paymentType": "RECIPIENT"}


def test_a_dhl_product_code_is_refused_not_defaulted():
    """P is a DHL productCode; choosing a FedEx service chooses a price."""
    with pytest.raises(CarrierGateError) as exc:
        _shipment(_request(product_code="P"))
    assert "FEDEX_SERVICE_NOT_SELECTED" in str(exc.value)


def test_recipient_identity_comes_from_the_shared_party_builder():
    recipient = _shipment()["recipients"][0]
    assert recipient["address"] == {
        "city": "Warszawa",
        "countryCode": "PL",
        "postalCode": "00-001",
        "streetLines": ["ul. Testowa 1"],
    }
    assert recipient["contact"] == {
        "companyName": "Testowa Sp. z o.o.",
        "personName": "Anna Kowalska",
        "phoneNumber": "+48000000000",
    }


def test_shipper_identity_is_the_company_address_not_a_bare_country(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "dhl_express_shipper_name", "Estrella Jewels", raising=False)
    monkeypatch.setattr(settings, "dhl_express_shipper_city", "Mumbai", raising=False)
    monkeypatch.setattr(settings, "dhl_express_shipper_address1", "Test Road 9", raising=False)
    monkeypatch.setattr(settings, "dhl_express_shipper_postal_code", "400001", raising=False)
    monkeypatch.setattr(settings, "dhl_express_shipper_country_code", "IN", raising=False)

    shipper = _shipment()["shipper"]
    assert shipper["address"]["city"] == "Mumbai"
    assert shipper["address"]["countryCode"] == "IN"
    assert shipper["address"]["streetLines"] == ["Test Road 9"]
    assert shipper["contact"]["companyName"] == "Estrella Jewels"


def test_account_number_is_the_shipper_account_on_the_request():
    assert _adapter()._ship_payload(_request())["accountNumber"] == {"value": "123456789"}


# ── Booking end to end, with the carrier mocked ───────────────────────────────


_LABEL = base64.b64encode(b"%PDF-1.4 fedex label").decode()

_SHIP_RESPONSE = {
    "transactionId": "txn-abc",
    "output": {
        "transactionShipments": [
            {
                "masterTrackingNumber": "794600000001",
                "pieceResponses": [
                    {"packageDocuments": [
                        {"contentType": "LABEL", "docType": "PDF", "encodedLabel": _LABEL},
                    ]}
                ],
            }
        ]
    },
}


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.content = json.dumps(payload).encode()

    def json(self):
        return self._payload


def test_booking_returns_tracking_and_persists_the_label(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services.carrier.adapters import fedex as fx

    monkeypatch.setattr(settings, "carrier_storage_root", tmp_path, raising=False)
    monkeypatch.setattr(fx, "_fedex_fields", lambda *_a, **_k: {"client_id": "cid", "client_secret": "sec"})
    monkeypatch.setattr(fx, "_token_cache", {})
    monkeypatch.setattr(fx.httpx, "post", lambda url, **kw: _Resp(200, {"access_token": "tok"}))

    adapter = _adapter()
    monkeypatch.setattr(
        adapter, "_post_ship", lambda url, token, payload: _Resp(200, _SHIP_RESPONSE)
    )

    result = adapter.create_shipment(_request())

    assert result.tracking_ref == "794600000001"
    assert result.carrier_transaction_id == "txn-abc"
    assert result.state == ShipmentState.SUBMITTED
    # This booking went to the FedEx sandbox, so it is recorded as simulated.
    # A production booking (both gates cleared) is the one that is not.
    assert result.simulated is True
    label = tmp_path / "labels" / "SHIPMENT_FDX_1-794600000001.pdf"
    assert label.exists(), sorted(p.name for p in tmp_path.rglob("*"))
    assert label.read_bytes().startswith(b"%PDF")


def test_a_url_only_document_is_skipped_not_fetched():
    from app.services.carrier.adapters.fedex import _fedex_documents

    out = _fedex_documents({"output": {"transactionShipments": [
        {"pieceResponses": [{"packageDocuments": [
            {"contentType": "LABEL", "url": "https://example.invalid/label.pdf"},
        ]}]}
    ]}})
    assert out == {"documents": []}


# ── Tracking goes through the one FedEx client ────────────────────────────────


def test_get_shipment_delegates_to_the_single_tracking_client(monkeypatch):
    from app.services import tracking_service as ts

    seen = []
    monkeypatch.setattr(
        ts, "_call_fedex",
        lambda ref: seen.append(ref) or {"status": "delivered", "source": "fedex_api"},
    )
    out = _adapter().get_shipment("794600000001")
    assert seen == ["794600000001"]
    assert out.state == ShipmentState.COMPLETE
    assert out.tracking_ref == "794600000001"


def test_delivered_is_only_from_an_explicit_delivered_status(monkeypatch):
    from app.services import tracking_service as ts

    monkeypatch.setattr(ts, "_call_fedex", lambda ref: {"status": "in_transit"})
    assert _adapter().get_shipment("794600000001").state == ShipmentState.SUBMITTED


def test_blank_tracking_ref_is_refused():
    with pytest.raises(CarrierGateError):
        _adapter().get_shipment("   ")


def test_there_is_no_second_fedex_tracking_client():
    src = (
        Path(__file__).resolve().parents[1]
        / "app" / "services" / "carrier" / "adapters" / "fedex.py"
    ).read_text(encoding="utf-8")
    assert "track/v1/trackingnumbers" not in src
    assert "_call_fedex" in src
    # documents persist through the shared helper, not a private writer
    assert "_save_shipment_documents" in src
    assert "write_bytes" not in src
