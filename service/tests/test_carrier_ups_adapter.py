"""UPS books through the shared carrier architecture — sandbox only.

Same expectations FedEx already carries: the adapter sends the ShipmentRequest
facts DHL sends (weight, package split, declared value, currency, Incoterm,
shipper identity), reuses the shared party builders and package resolver, and
stays hard-blocked for production. UPS tracking is deliberately not
provisioned here — tracking_service is the only tracking authority.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.carrier.adapters.ups import UpsSandboxAdapter
from app.services.carrier.models.shipment import (
    CarrierConfigError,
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
        batch_id="SHIPMENT_UPS_1",
        shipper_account="A1B2C3",
        recipient_address=dict(_ADDR),
        declared_value=1500.0,
        currency="EUR",
        weight_kg=3.5,
        dimensions={"length_cm": 30, "width_cm": 20, "height_cm": 10},
        product_code="07",
        incoterm="DAP",
        description="Jewellery",
    )
    kwargs.update(over)
    return ShipmentRequest(**kwargs)


def _adapter(*, production: bool = False) -> UpsSandboxAdapter:
    return UpsSandboxAdapter(
        SimpleNamespace(status="live", ups_allow_production=production)
    )


def _fields(monkeypatch, **over):
    out = {"client_id": "cid", "client_secret": "sec"}
    out.update(over)
    monkeypatch.setattr("app.services.carrier.adapters.ups._ups_fields", lambda: out)


# ── The production gate ───────────────────────────────────────────────────────


def test_production_booking_stays_hard_blocked(monkeypatch):
    _fields(monkeypatch)
    with pytest.raises(CarrierGateError) as exc:
        _adapter(production=True).create_shipment(_request())
    assert "UPS_PRODUCTION_BLOCKED" in str(exc.value)


def test_sandbox_is_the_only_base_url():
    assert _adapter()._base_url() == "https://wwwcie.ups.com"


def test_unconfigured_ups_refuses_before_any_network_call(monkeypatch):
    _fields(monkeypatch, client_id="", client_secret="")
    with pytest.raises(CarrierConfigError) as exc:
        _adapter().create_shipment(_request())
    assert "UPS_NOT_CONFIGURED" in str(exc.value)


# ── The factory never substitutes DHL ────────────────────────────────────────


def test_factory_returns_the_adapter_only_when_credentials_resolve(monkeypatch):
    from app.services.carrier import factory as fac
    from app.services.carrier.adapters import ups as ups_mod

    cfg = fac.CarrierConfig(status="live")

    monkeypatch.setattr(ups_mod, "_ups_fields", lambda: {})
    with pytest.raises(CarrierGateError) as exc:
        fac.get_adapter(cfg, "UPS")
    assert "UPS_NOT_CONFIGURED" in str(exc.value)

    monkeypatch.setattr(
        ups_mod, "_ups_fields", lambda: {"client_id": "cid", "client_secret": "sec"}
    )
    assert isinstance(fac.get_adapter(cfg, "UPS"), UpsSandboxAdapter)


def test_a_resolver_fault_reads_as_not_configured_never_as_a_booking(monkeypatch):
    from app.services.carrier.adapters import ups as ups_mod

    def _boom():
        raise RuntimeError("secret store down")

    monkeypatch.setattr(ups_mod, "_ups_fields", _boom)
    assert ups_mod.ups_credentials_present() is False


# ── The payload carries the business facts ────────────────────────────────────


def _shipment(monkeypatch, request=None) -> dict:
    _fields(monkeypatch)
    payload = _adapter()._ship_payload(request or _request())
    return payload["ShipmentRequest"]["Shipment"]


def test_single_package_carries_weight_and_dimensions(monkeypatch):
    packages = _shipment(monkeypatch)["Package"]
    assert len(packages) == 1
    assert packages[0]["PackageWeight"] == {
        "UnitOfMeasurement": {"Code": "KGS"},
        "Weight": "3.5",
    }
    assert packages[0]["Dimensions"] == {
        "UnitOfMeasurement": {"Code": "CM"},
        "Length": "30",
        "Width": "20",
        "Height": "10",
    }


def test_operator_package_split_produces_one_ups_package_each(monkeypatch):
    req = _request(packages=[
        {"weight_kg": 2.0, "length_cm": 20, "width_cm": 15, "height_cm": 10},
        {"weight_kg": 1.5, "length_cm": 30, "width_cm": 20, "height_cm": 10},
    ])
    packages = _shipment(monkeypatch, req)["Package"]
    assert [p["PackageWeight"]["Weight"] for p in packages] == ["2.0", "1.5"]
    assert [p["Dimensions"]["Length"] for p in packages] == ["20", "30"]


def test_declared_value_and_currency_reach_the_invoice_total(monkeypatch):
    assert _shipment(monkeypatch)["InvoiceLineTotal"] == {
        "CurrencyCode": "EUR",
        "MonetaryValue": "1500.00",
    }


def test_incoterm_is_never_invented(monkeypatch):
    _fields(monkeypatch)
    with pytest.raises(CarrierGateError) as exc:
        _adapter()._ship_payload(_request(incoterm=""))
    assert "refuse to invent" in str(exc.value)


def test_duty_payer_is_derived_from_the_incoterm(monkeypatch):
    """DDP means the sender pays duty. Every other term leaves it with the receiver."""
    ddp = _shipment(monkeypatch, _request(incoterm="DDP"))
    assert [c["Type"] for c in ddp["PaymentInformation"]["ShipmentCharge"]] == ["01", "02"]
    exw = _shipment(monkeypatch, _request(incoterm="EXW"))
    assert [c["Type"] for c in exw["PaymentInformation"]["ShipmentCharge"]] == ["01"]
    assert exw["PaymentInformation"]["ShipmentCharge"][0]["BillShipper"] == {
        "AccountNumber": "A1B2C3"
    }


def test_a_dhl_product_code_is_refused_not_defaulted(monkeypatch):
    """P is a DHL productCode; choosing a UPS service chooses a price."""
    _fields(monkeypatch)
    with pytest.raises(CarrierGateError) as exc:
        _adapter()._ship_payload(_request(product_code="P"))
    assert "UPS_SERVICE_NOT_SELECTED" in str(exc.value)


def test_recipient_identity_comes_from_the_shared_party_builder(monkeypatch):
    ship_to = _shipment(monkeypatch)["ShipTo"]
    assert ship_to["Name"] == "Testowa Sp. z o.o."
    assert ship_to["AttentionName"] == "Anna Kowalska"
    assert ship_to["Phone"] == {"Number": "+48000000000"}
    assert ship_to["Address"] == {
        "City": "Warszawa",
        "CountryCode": "PL",
        "PostalCode": "00-001",
        "AddressLine": ["ul. Testowa 1"],
    }
    assert "ShipperNumber" not in ship_to


def test_shipper_identity_is_the_company_address_and_carries_the_account(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "dhl_express_shipper_name", "Estrella Jewels", raising=False)
    monkeypatch.setattr(settings, "dhl_express_shipper_city", "Mumbai", raising=False)
    monkeypatch.setattr(settings, "dhl_express_shipper_address1", "Test Road 9", raising=False)
    monkeypatch.setattr(settings, "dhl_express_shipper_postal_code", "400001", raising=False)
    monkeypatch.setattr(settings, "dhl_express_shipper_country_code", "IN", raising=False)

    shipper = _shipment(monkeypatch)["Shipper"]
    assert shipper["Name"] == "Estrella Jewels"
    assert shipper["Address"]["City"] == "Mumbai"
    assert shipper["Address"]["CountryCode"] == "IN"
    assert shipper["Address"]["AddressLine"] == ["Test Road 9"]
    assert shipper["ShipperNumber"] == "A1B2C3"


def test_customer_packaging_and_a_label_format_are_requested(monkeypatch):
    _fields(monkeypatch)
    payload = _adapter()._ship_payload(_request())
    assert payload["ShipmentRequest"]["Shipment"]["Package"][0]["Packaging"] == {
        "Code": "02"
    }
    assert payload["ShipmentRequest"]["LabelSpecification"] == {
        "LabelImageFormat": {"Code": "GIF"}
    }


# ── Booking end to end, with the carrier mocked ───────────────────────────────


_SHIP_RESPONSE = {
    "ShipmentResponse": {
        "Response": {"TransactionReference": {"TransactionIdentifier": "ups-txn-1"}},
        "ShipmentResults": {"ShipmentIdentificationNumber": "1Z0000000000000001"},
    }
}


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.content = json.dumps(payload).encode()

    def json(self):
        return self._payload


def test_booking_returns_tracking_and_the_transaction_id(monkeypatch):
    from app.services.carrier.adapters import ups as up

    _fields(monkeypatch)
    monkeypatch.setattr(up, "_token_cache", {})
    monkeypatch.setattr(up.httpx, "post", lambda url, **kw: _Resp(200, {"access_token": "tok"}))

    adapter = _adapter()
    monkeypatch.setattr(
        adapter, "_post_ship", lambda url, token, payload: _Resp(200, _SHIP_RESPONSE)
    )

    result = adapter.create_shipment(_request())
    assert result.tracking_ref == "1Z0000000000000001"
    assert result.carrier_transaction_id == "ups-txn-1"
    assert result.state == ShipmentState.SUBMITTED
    assert result.simulated is False


def test_oauth_is_cached_and_basic_authenticated(monkeypatch):
    from app.services.carrier.adapters import ups as up

    _fields(monkeypatch)
    monkeypatch.setattr(up, "_token_cache", {})
    seen = []

    def _post(url, **kw):
        seen.append((url, kw.get("headers", {}).get("Authorization"), kw.get("data")))
        return _Resp(200, {"access_token": "tok"})

    monkeypatch.setattr(up.httpx, "post", _post)
    adapter = _adapter()
    assert adapter._token() == "tok"
    assert adapter._token() == "tok"
    assert len(seen) == 1, seen
    url, auth, data = seen[0]
    assert url == "https://wwwcie.ups.com/security/v1/oauth/token"
    assert auth.startswith("Basic ")
    assert data == {"grant_type": "client_credentials"}


def test_ship_401_retries_once_with_a_fresh_token(monkeypatch):
    from app.services.carrier.adapters import ups as up

    _fields(monkeypatch)
    monkeypatch.setattr(up, "_token_cache", {})
    monkeypatch.setattr(up.httpx, "post", lambda url, **kw: _Resp(200, {"access_token": "tok"}))

    adapter = _adapter()
    calls = []

    def _ship(url, token, payload):
        calls.append(token)
        return _Resp(401 if len(calls) == 1 else 200, _SHIP_RESPONSE)

    monkeypatch.setattr(adapter, "_post_ship", _ship)
    assert adapter.create_shipment(_request()).tracking_ref == "1Z0000000000000001"
    assert len(calls) == 2


def test_a_rejected_oauth_is_an_auth_failure_not_a_booking(monkeypatch):
    from app.services.carrier.adapters import ups as up

    _fields(monkeypatch)
    monkeypatch.setattr(up, "_token_cache", {})
    monkeypatch.setattr(up.httpx, "post", lambda url, **kw: _Resp(401, {}))
    with pytest.raises(CarrierGateError) as exc:
        _adapter().create_shipment(_request())
    assert "UPS_AUTH_FAILED" in str(exc.value)


# ── Single-authority pins ─────────────────────────────────────────────────────


_SRC = Path(__file__).resolve().parents[1] / "app" / "services" / "carrier"


def test_ups_tracking_is_refused_here_not_implemented_twice():
    with pytest.raises(CarrierGateError) as exc:
        _adapter().get_shipment("1Z0000000000000001")
    assert "UPS_TRACK_NOT_PROVISIONED" in str(exc.value)

    src = (_SRC / "adapters" / "ups.py").read_text(encoding="utf-8")
    # no second tracking client and no second document store in the adapter
    assert "/track" not in src
    assert "write_bytes" not in src
    assert "sqlite3" not in src


def test_the_ups_route_gate_stays_closed_until_credentials_exist():
    """No UPS credentials exist anywhere yet, and this campaign books nothing live.

    The booking route keeps its explicit 422 so an operator cannot reach a
    sandbox-only adapter from the production AWB modal. Opening it is a
    one-line change once operator-supplied sandbox credentials land — the
    adapter and the factory branch below are already in place.
    """
    routes = (
        Path(__file__).resolve().parents[1] / "app" / "api" / "routes_carrier_actions.py"
    ).read_text(encoding="utf-8")
    assert '"code": "UPS_NOT_CONFIGURED"' in routes

    factory = (_SRC / "factory.py").read_text(encoding="utf-8")
    assert "UpsSandboxAdapter" in factory
    assert 'raise CarrierGateError("UPS_NOT_CONFIGURED")' in factory
    assert "Never silently routed to DHL" in factory


def test_credentials_resolve_through_the_one_bridge():
    src = (_SRC / "adapters" / "ups.py").read_text(encoding="utf-8")
    assert "resolve_ups_secret_fields" in src
    assert "settings.ups_client_id" not in src

    bridge = (_SRC / "credentials" / "consumer_bridge.py").read_text(encoding="utf-8")
    assert "def resolve_ups_secret_fields(" in bridge
