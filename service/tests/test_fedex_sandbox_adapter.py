"""FedEx sandbox adapter — OAuth cache, 401 retry once, production blocked."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.carrier.adapters import fedex as fedex_mod
from app.services.carrier.adapters.fedex import FedExSandboxAdapter
from app.services.carrier.factory import CarrierConfig
from app.services.carrier.models.shipment import CarrierGateError, ShipmentRequest


def _req() -> ShipmentRequest:
    return ShipmentRequest(
        batch_id="BATCH-FX",
        shipper_account="FEDEX",
        recipient_address={"city": "Warsaw", "postal_code": "00-001", "country_code": "PL"},
        declared_value=10.0,
        currency="EUR",
        weight_kg=1.0,
        dimensions={"length_cm": 10, "width_cm": 10, "height_cm": 10},
    )


@pytest.fixture(autouse=True)
def _creds_and_cache(monkeypatch):
    fedex_mod._token_cache.clear()
    monkeypatch.setattr(
        fedex_mod,
        "_fedex_fields",
        lambda: {"client_id": "sandbox-id", "client_secret": "sandbox-secret"},
    )
    yield
    fedex_mod._token_cache.clear()


def test_production_booking_blocked():
    cfg = CarrierConfig(status="live")
    cfg.fedex_allow_production = True  # type: ignore[attr-defined]
    adapter = FedExSandboxAdapter(cfg)
    with pytest.raises(CarrierGateError, match="FEDEX_PRODUCTION_BLOCKED"):
        adapter.create_shipment(_req())


def test_oauth_cached_single_flight():
    adapter = FedExSandboxAdapter(CarrierConfig(status="live"))
    token_resp = MagicMock(status_code=200)
    token_resp.json.return_value = {"access_token": "tok-1"}
    ship_resp = MagicMock(status_code=200, content=b"{}")
    ship_resp.json.return_value = {
        "output": {
            "transactionShipments": [{"masterTrackingNumber": "794000000000"}],
            "transactionId": "txn-1",
        }
    }
    with patch.object(fedex_mod.httpx, "post", side_effect=[token_resp, ship_resp, ship_resp]) as post:
        adapter.create_shipment(_req())
        adapter.create_shipment(_req())
    oauth_calls = [
        c for c in post.call_args_list if "/oauth/token" in str(c.args[0] if c.args else "")
    ]
    assert len(oauth_calls) == 1


def test_ship_401_retries_once_with_fresh_token():
    adapter = FedExSandboxAdapter(CarrierConfig(status="live"))
    token1 = MagicMock(status_code=200)
    token1.json.return_value = {"access_token": "old"}
    token2 = MagicMock(status_code=200)
    token2.json.return_value = {"access_token": "new"}
    unauth = MagicMock(status_code=401, content=b"{}")
    unauth.json.return_value = {}
    ok = MagicMock(status_code=200, content=b"{}")
    ok.json.return_value = {
        "output": {
            "transactionShipments": [{"masterTrackingNumber": "794111"}],
            "transactionId": "txn-2",
        }
    }
    with patch.object(
        fedex_mod.httpx, "post", side_effect=[token1, unauth, token2, ok]
    ):
        result = adapter.create_shipment(_req())
    assert result.tracking_ref == "794111"
    assert result.carrier_transaction_id == "txn-2"


def test_track_not_provisioned():
    adapter = FedExSandboxAdapter(CarrierConfig(status="live"))
    with pytest.raises(CarrierGateError, match="FEDEX_TRACK_NOT_PROVISIONED"):
        adapter.get_shipment("794")


def test_sandbox_base_url():
    adapter = FedExSandboxAdapter(CarrierConfig(status="live"))
    assert adapter._base_url() == "https://apis-sandbox.fedex.com"
