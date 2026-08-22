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
        # FedEx service + Incoterm are now required rather than defaulted —
        # the adapter refuses to choose a priced service or invent a term.
        product_code="INTERNATIONAL_PRIORITY",
        incoterm="DAP",
    )


@pytest.fixture(autouse=True)
def _creds_and_cache(monkeypatch):
    fedex_mod._token_cache.clear()
    monkeypatch.setattr(
        fedex_mod,
        "_fedex_fields",
        lambda *_a, **_k: {"client_id": "sandbox-id", "client_secret": "sandbox-secret"},
    )
    yield
    fedex_mod._token_cache.clear()


def test_production_booking_blocked_without_the_configuration_flag():
    """MIGRATED 2026-08-22. Previously the flag was turned ON here and the
    booking was still blocked, because the (now retired) carrier_live_allowlist
    clause was empty. The allowlist no longer gates anything; the flag does, and
    it is configuration rather than a per-shipment release."""
    cfg = CarrierConfig(status="live")
    assert cfg.fedex_allow_production is False      # default: sandbox
    adapter = FedExSandboxAdapter(cfg)
    with pytest.raises(CarrierGateError, match="FEDEX_PRODUCTION_BLOCKED"):
        adapter._check_production_allowed(_req().batch_id)
    assert adapter._base_url() == "https://apis-sandbox.fedex.com"


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


def test_tracking_is_provisioned_through_the_shared_client(monkeypatch):
    """Was FEDEX_TRACK_NOT_PROVISIONED — now delegated, never re-implemented.

    Full behaviour (delivered mapping, blank ref, no second client) lives in
    test_carrier_fedex_adapter.py.
    """
    from app.services import tracking_service as ts

    monkeypatch.setattr(ts, "_call_fedex", lambda ref: {"status": "in_transit"})
    adapter = FedExSandboxAdapter(CarrierConfig(status="live"))
    assert adapter.get_shipment("794").tracking_ref == "794"


def test_sandbox_base_url():
    adapter = FedExSandboxAdapter(CarrierConfig(status="live"))
    assert adapter._base_url() == "https://apis-sandbox.fedex.com"
