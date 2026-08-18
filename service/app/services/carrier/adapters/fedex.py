"""FedEx sandbox adapter — same CarrierAdapter Protocol as DHL.

OAuth (official): POST {base}/oauth/token
  grant_type=client_credentials, application/x-www-form-urlencoded
Sandbox base: https://apis-sandbox.fedex.com
Production base: https://apis.fedex.com — refused unless explicitly enabled.

Credentials via resolve_carrier_credentials(fedex, ship_rate, sandbox)
when migrated; otherwise Settings.fedex_client_id/secret (unmigrated).

Does not implement a second credential store, coordinator, or tracking client.
Tracking remains tracking_service._call_fedex until that path is wired to
the same resolver.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Optional

import httpx

from .base import AbstractCarrierAdapter
from ..models.shipment import (
    CarrierConfigError,
    CarrierGateError,
    ShipmentMode,
    ShipmentRequest,
    ShipmentResult,
    ShipmentState,
    compute_idempotency_key,
)

if TYPE_CHECKING:
    from ..factory import CarrierConfig

log = logging.getLogger(__name__)

_SANDBOX_BASE = "https://apis-sandbox.fedex.com"
_PROD_BASE = "https://apis.fedex.com"

_token_lock = threading.Lock()
_token_cache: dict[str, tuple[float, str]] = {}


def _fedex_fields() -> dict[str, str]:
    from ..credentials.consumer_bridge import resolve_fedex_secret_fields

    return resolve_fedex_secret_fields("ship_rate", "sandbox")


class FedExSandboxAdapter(AbstractCarrierAdapter):
    """Sandbox Ship only. Production booking is a hard gate."""

    def __init__(self, config: "CarrierConfig") -> None:
        self._config = config
        self._allow_production = bool(
            getattr(config, "fedex_allow_production", False)
        )

    def _base_url(self) -> str:
        if self._allow_production:
            return _PROD_BASE
        return _SANDBOX_BASE

    def _credentials(self) -> tuple[str, str]:
        fields = _fedex_fields()
        cid = (fields.get("client_id") or "").strip()
        csec = (fields.get("client_secret") or "").strip()
        if not cid or not csec:
            raise CarrierConfigError("FEDEX_NOT_CONFIGURED")
        return cid, csec

    def _token(self, *, force: bool = False) -> str:
        cid, csec = self._credentials()
        cache_key = cid
        now = time.monotonic()
        with _token_lock:
            if not force:
                hit = _token_cache.get(cache_key)
                if hit and hit[0] > now + 30:
                    return hit[1]
            token = self._fetch_token(cid, csec)
            _token_cache[cache_key] = (now + 3300.0, token)
            return token

    def _fetch_token(self, client_id: str, client_secret: str) -> str:
        url = self._base_url().rstrip("/") + "/oauth/token"
        resp = httpx.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )
        if resp.status_code in (401, 403):
            raise CarrierGateError("FEDEX_AUTH_FAILED")
        if resp.status_code >= 400:
            raise CarrierGateError(f"FedEx OAuth HTTP {resp.status_code}")
        data = resp.json()
        token = (data.get("access_token") or "").strip()
        if not token:
            raise CarrierGateError("FedEx OAuth missing access_token")
        return token

    def create_shipment(self, request: ShipmentRequest) -> ShipmentResult:
        if self._allow_production:
            raise CarrierGateError("FEDEX_PRODUCTION_BLOCKED")
        self._credentials()
        token = self._token()
        url = self._base_url().rstrip("/") + "/ship/v1/shipments"
        payload = self._ship_payload(request)
        resp = self._post_ship(url, token, payload)
        if resp.status_code == 401:
            token = self._token(force=True)
            resp = self._post_ship(url, token, payload)
        if resp.status_code >= 400:
            raise CarrierGateError(f"FedEx Ship HTTP {resp.status_code}")
        body = resp.json() if resp.content else {}
        tracking, txn = self._extract_ids(body)
        key = compute_idempotency_key(request)
        return ShipmentResult(
            idempotency_key=key,
            mode=ShipmentMode.LIVE,
            state=ShipmentState.SUBMITTED,
            tracking_ref=tracking,
            simulated=False,
            service_product=request.product_code,
            carrier_transaction_id=txn,
        )

    def get_shipment(self, tracking_ref: str) -> ShipmentResult:
        raise CarrierGateError("FEDEX_TRACK_NOT_PROVISIONED")

    def _post_ship(self, url: str, token: str, payload: dict) -> httpx.Response:
        return httpx.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-locale": "en_US",
            },
            timeout=30.0,
        )

    def _ship_payload(self, request: ShipmentRequest) -> dict:
        addr = request.recipient_address or {}
        return {
            "requestedShipment": {
                "shipper": {"address": {"countryCode": "PL"}},
                "recipients": [
                    {
                        "address": {
                            "city": addr.get("city") or "",
                            "postalCode": addr.get("postal_code") or addr.get("postalCode") or "",
                            "countryCode": (
                                addr.get("country_code") or addr.get("countryCode") or ""
                            ),
                        }
                    }
                ],
                "pickupType": "DROPOFF_AT_FEDEX_LOCATION",
                "packagingType": "YOUR_PACKAGING",
            }
        }

    def _extract_ids(self, body: dict) -> tuple[Optional[str], Optional[str]]:
        txn = None
        if isinstance(body, dict):
            txn = (
                body.get("transactionId")
                or (body.get("output") or {}).get("transactionId")
                or (body.get("output") or {}).get("transactionShipments", [{}])[0].get(
                    "masterTrackingNumber"
                )
            )
            shipments = (body.get("output") or {}).get("transactionShipments") or []
            tracking = None
            if shipments and isinstance(shipments[0], dict):
                tracking = shipments[0].get("masterTrackingNumber")
            return tracking, txn
        return None, None
