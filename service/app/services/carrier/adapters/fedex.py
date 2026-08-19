"""FedEx sandbox adapter — same CarrierAdapter Protocol as DHL.

OAuth (official): POST {base}/oauth/token
  grant_type=client_credentials, application/x-www-form-urlencoded
Sandbox base: https://apis-sandbox.fedex.com
Production base: https://apis.fedex.com — refused unless explicitly enabled.

Credentials via resolve_carrier_credentials(fedex, ship_rate, sandbox)
when migrated; otherwise Settings.fedex_client_id/secret (unmigrated).

Does not implement a second credential store, coordinator or tracking client:
get_shipment() delegates to tracking_service._call_fedex, and the party and
document helpers are the ones the DHL adapter already uses.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from typing import TYPE_CHECKING, Optional

import httpx

from .base import AbstractCarrierAdapter
from .live import (
    _build_receiver_details,
    _build_shipper_details,
    _save_shipment_documents,
)
from ..models.shipment import (
    CarrierConfigError,
    CarrierGateError,
    ShipmentMode,
    ShipmentRequest,
    ShipmentResult,
    ShipmentState,
    compute_idempotency_key,
    resolve_packages,
)

if TYPE_CHECKING:
    from ..factory import CarrierConfig

log = logging.getLogger(__name__)

_SANDBOX_BASE = "https://apis-sandbox.fedex.com"
_PROD_BASE = "https://apis.fedex.com"

_token_lock = threading.Lock()
_token_cache: dict[str, tuple[float, str]] = {}


# A FedEx service is a symbolic code (INTERNATIONAL_PRIORITY, ...). The AWB
# modal still sends DHL productCodes ("P"), so a FedEx booking that reaches
# here without an operator-chosen FedEx service is refused rather than given
# a default — picking a service picks a price. Same stance as the DHL adapter
# refusing to invent an Incoterm.
_FEDEX_SERVICE_RE = re.compile(r"^[A-Z][A-Z0-9_]{3,}$")

# FedEx document contentType → the DHL typeCode _save_shipment_documents knows.
_FEDEX_DOC_TYPES = {"LABEL": "label", "COMMERCIAL_INVOICE": "invoice"}


def _fedex_fields() -> dict[str, str]:
    from ..credentials.consumer_bridge import resolve_fedex_secret_fields

    return resolve_fedex_secret_fields("ship_rate", "sandbox")


def _to_fedex_party(details: dict) -> dict:
    """Remap one DHL-shaped party onto the FedEx address/contact shape.

    The builders in live.py hold carrier-independent facts — the Customer
    Master contact-identity rules (company vs person vs name) and the
    company's own dispatch address. FedEx reuses them and renames the keys;
    a second copy of that resolution would drift from the first.
    """
    postal = details.get("postalAddress") or {}
    contact = details.get("contactInformation") or {}

    address = {
        "city": postal.get("cityName") or "",
        "countryCode": postal.get("countryCode") or "",
    }
    if postal.get("postalCode"):
        address["postalCode"] = postal["postalCode"]
    if postal.get("addressLine1"):
        address["streetLines"] = [postal["addressLine1"]]

    party: dict = {"address": address}
    fedex_contact = {}
    for src, dst in (
        ("companyName", "companyName"),
        ("fullName", "personName"),
        ("phone", "phoneNumber"),
        ("email", "emailAddress"),
    ):
        value = (contact.get(src) or "").strip()
        if value:
            fedex_contact[dst] = value
    if fedex_contact:
        party["contact"] = fedex_contact
    return party


def _fedex_documents(body: dict) -> dict:
    """Normalise FedEx shipment documents onto the DHL ``documents`` shape.

    FedEx returns them per shipment (shipmentDocuments) and per piece
    (pieceResponses[].packageDocuments), base64 in ``encodedLabel``; DHL
    returns one flat list of {typeCode, content}. Reshaping here lets both
    carriers persist through the single _save_shipment_documents helper.
    A URL-only document carries no bytes and is skipped — never fetched.

    ponytail: the storage helper names files {batch_id}-{tracking_ref}.pdf,
    so a multi-piece booking keeps only the last label; give the helper a
    per-piece suffix when multi-piece FedEx labels are actually printed.
    """
    docs = []
    shipments = ((body or {}).get("output") or {}).get("transactionShipments") or []
    for shipment in shipments:
        if not isinstance(shipment, dict):
            continue
        raw = list(shipment.get("shipmentDocuments") or [])
        for piece in shipment.get("pieceResponses") or []:
            if isinstance(piece, dict):
                raw.extend(piece.get("packageDocuments") or [])
        for doc in raw:
            if not isinstance(doc, dict):
                continue
            type_code = _FEDEX_DOC_TYPES.get(doc.get("contentType") or "")
            content = doc.get("encodedLabel")
            if type_code and content:
                docs.append({"typeCode": type_code, "content": content})
    return {"documents": docs}


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
        if tracking:
            from ....core.config import settings

            # Same store, same helper the DHL path uses — one document
            # authority, so the existing download endpoints serve FedEx
            # labels without a second persistence path.
            _save_shipment_documents(
                _fedex_documents(body), request.batch_id, tracking, settings
            )
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
        """Resolve FedEx state through the one FedEx tracking client.

        tracking_service._call_fedex already owns FedEx tracking (its own
        read-only credentials, its own status map). A second client here
        would be a second authority for the same fact. COMPLETE only from
        an explicit delivered status, never inferred from age or silence.
        """
        from ...tracking_service import _call_fedex

        ref = (tracking_ref or "").strip()
        if not ref:
            raise CarrierGateError("tracking_ref is required for FedEx tracking")
        data = _call_fedex(ref)
        delivered = (data or {}).get("status") == "delivered"
        return ShipmentResult(
            idempotency_key=hashlib.sha256(ref.encode()).hexdigest(),
            mode=ShipmentMode.LIVE,
            state=ShipmentState.COMPLETE if delivered else ShipmentState.SUBMITTED,
            tracking_ref=ref,
            simulated=False,
        )

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

    def _service_type(self, request: ShipmentRequest) -> str:
        service = (request.product_code or "").strip().upper()
        if not _FEDEX_SERVICE_RE.match(service):
            raise CarrierGateError("FEDEX_SERVICE_NOT_SELECTED")
        return service

    def _ship_payload(self, request: ShipmentRequest) -> dict:
        from ....core.config import settings

        incoterm = (request.incoterm or "").strip().upper()
        if not incoterm:
            raise CarrierGateError(
                "Incoterm missing on ShipmentRequest — refuse to invent DAP for FedEx."
            )
        service = self._service_type(request)
        # resolve_packages() derives one package from the scalar weight +
        # dimensions when the operator entered no split — the same helper DHL
        # and UPS use, so a split is described once.
        packages = resolve_packages(request)
        total_weight = sum(float(pkg.get("weight_kg") or 0) for pkg in packages)

        return {
            "labelResponseOptions": "LABEL",
            "accountNumber": {"value": request.shipper_account},
            "requestedShipment": {
                "shipper": _to_fedex_party(_build_shipper_details(settings)),
                "recipients": [
                    _to_fedex_party(
                        _build_receiver_details(request.recipient_address or {})
                    )
                ],
                "serviceType": service,
                "pickupType": "DROPOFF_AT_FEDEX_LOCATION",
                "packagingType": "YOUR_PACKAGING",
                "shippingChargesPayment": {"paymentType": "SENDER"},
                "labelSpecification": {
                    "imageType": "PDF",
                    "labelStockType": "PAPER_85X11_TOP_HALF_LABEL",
                },
                "customsClearanceDetail": {
                    # Who pays duty follows from the Incoterm — DDP is the
                    # sender, every other term leaves it with the recipient.
                    # Derived from the commercial term, never chosen here.
                    "dutiesPayment": {
                        "paymentType": "SENDER" if incoterm == "DDP" else "RECIPIENT"
                    },
                    "commercialInvoice": {"termsOfSale": incoterm},
                    "commodities": [
                        {
                            "description": request.description or "Jewellery",
                            "quantity": len(packages),
                            "quantityUnits": "PCS",
                            "customsValue": {
                                "amount": request.declared_value,
                                "currency": request.currency,
                            },
                            "weight": {"units": "KG", "value": total_weight},
                        }
                    ],
                },
                "requestedPackageLineItems": [
                    {
                        "weight": {"units": "KG", "value": pkg.get("weight_kg")},
                        "dimensions": {
                            "length": pkg.get("length_cm", 1),
                            "width": pkg.get("width_cm", 1),
                            "height": pkg.get("height_cm", 1),
                            "units": "CM",
                        },
                    }
                    for pkg in packages
                ],
            },
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
