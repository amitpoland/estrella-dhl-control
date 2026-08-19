"""UPS sandbox adapter — same CarrierAdapter Protocol as DHL and FedEx.

OAuth (official): POST {base}/security/v1/oauth/token
  grant_type=client_credentials, HTTP Basic client_id:client_secret
Sandbox base: https://wwwcie.ups.com
Production base: https://onlinetools.ups.com — refused, mirroring FedEx.

Credentials via resolve_carrier_credentials(ups, ship, sandbox) when
migrated; otherwise Settings.ups_client_id/secret (unmigrated).

Does not implement a second credential store, coordinator, tracking client or
document store: the party builders and the package resolver are the ones the
DHL and FedEx adapters already use.
"""
from __future__ import annotations

import base64
import logging
import re
import threading
import time
from typing import TYPE_CHECKING, Optional

import httpx

from .base import AbstractCarrierAdapter
from .live import _build_receiver_details, _build_shipper_details
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

_SANDBOX_BASE = "https://wwwcie.ups.com"
_PROD_BASE = "https://onlinetools.ups.com"

_token_lock = threading.Lock()
_token_cache: dict[str, tuple[float, str]] = {}


# A UPS service is a two-digit code ("07" Worldwide Express, "65" Saver, ...).
# The AWB modal still sends DHL productCodes ("P"), so a UPS booking that
# reaches here without an operator-chosen UPS service is refused rather than
# given a default — picking a service picks a price. Same stance as FedEx.
_UPS_SERVICE_RE = re.compile(r"^\d{2}$")

# Customer-supplied packaging. UPS-supplied packaging is a different price and
# is never chosen on behalf of the operator.
_CUSTOMER_PACKAGING = "02"


def _ups_fields() -> dict:
    from ..credentials.consumer_bridge import resolve_ups_secret_fields

    return resolve_ups_secret_fields("ship", "sandbox")


def ups_credentials_present() -> bool:
    """True only when both UPS OAuth fields resolve to real, non-blank strings.

    The factory calls this so an unconfigured UPS fails closed there: no
    adapter is handed back that could later be mistaken for a bookable
    carrier, and the booking is never silently routed to DHL.
    """
    try:
        fields = _ups_fields()
    except Exception:  # a resolver fault is "not configured", never a booking
        return False
    cid = fields.get("client_id")
    csec = fields.get("client_secret")
    return bool(
        isinstance(cid, str)
        and cid.strip()
        and isinstance(csec, str)
        and csec.strip()
    )


def _to_ups_party(details: dict, account: Optional[str] = None) -> dict:
    """Remap one DHL-shaped party onto the UPS Name/AttentionName/Address shape.

    The builders in live.py hold carrier-independent facts: the Customer
    Master contact identity and the dispatch address of the company. UPS
    reuses them and renames the keys; a second copy would drift.
    """
    postal = details.get("postalAddress") or {}
    contact = details.get("contactInformation") or {}

    address: dict = {
        "City": postal.get("cityName") or "",
        "CountryCode": postal.get("countryCode") or "",
    }
    if postal.get("postalCode"):
        address["PostalCode"] = postal["postalCode"]
    if postal.get("addressLine1"):
        address["AddressLine"] = [postal["addressLine1"]]

    party: dict = {
        "Name": (contact.get("companyName") or "").strip(),
        "Address": address,
    }
    attention = (contact.get("fullName") or "").strip()
    if attention:
        party["AttentionName"] = attention
    phone = (contact.get("phone") or "").strip()
    if phone:
        party["Phone"] = {"Number": phone}
    email = (contact.get("email") or "").strip()
    if email:
        party["EMailAddress"] = email
    if account:
        party["ShipperNumber"] = account
    return party


class UpsSandboxAdapter(AbstractCarrierAdapter):
    """Sandbox Ship only. Production booking is a hard gate."""

    def __init__(self, config: "CarrierConfig") -> None:
        self._config = config
        self._allow_production = bool(getattr(config, "ups_allow_production", False))

    def _base_url(self) -> str:
        if self._allow_production:
            return _PROD_BASE
        return _SANDBOX_BASE

    def _credentials(self) -> tuple:
        fields = _ups_fields()
        cid = (fields.get("client_id") or "").strip()
        csec = (fields.get("client_secret") or "").strip()
        if not cid or not csec:
            raise CarrierConfigError("UPS_NOT_CONFIGURED")
        return cid, csec

    def _token(self, *, force: bool = False) -> str:
        cid, csec = self._credentials()
        now = time.monotonic()
        with _token_lock:
            if not force:
                hit = _token_cache.get(cid)
                if hit and hit[0] > now + 30:
                    return hit[1]
            token = self._fetch_token(cid, csec)
            _token_cache[cid] = (now + 3300.0, token)
            return token

    def _fetch_token(self, client_id: str, client_secret: str) -> str:
        url = self._base_url().rstrip("/") + "/security/v1/oauth/token"
        basic = base64.b64encode(
            ("%s:%s" % (client_id, client_secret)).encode()
        ).decode()
        resp = httpx.post(
            url,
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": "Basic " + basic,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30.0,
        )
        if resp.status_code in (401, 403):
            raise CarrierGateError("UPS_AUTH_FAILED")
        if resp.status_code >= 400:
            raise CarrierGateError("UPS OAuth HTTP %s" % resp.status_code)
        data = resp.json()
        token = (data.get("access_token") or "").strip()
        if not token:
            raise CarrierGateError("UPS OAuth missing access_token")
        return token

    def create_shipment(self, request: ShipmentRequest) -> ShipmentResult:
        if self._allow_production:
            raise CarrierGateError("UPS_PRODUCTION_BLOCKED")
        self._credentials()
        payload = self._ship_payload(request)
        url = self._base_url().rstrip("/") + "/api/shipments/v1/ship"
        resp = self._post_ship(url, self._token(), payload)
        if resp.status_code == 401:
            resp = self._post_ship(url, self._token(force=True), payload)
        if resp.status_code >= 400:
            raise CarrierGateError("UPS Ship HTTP %s" % resp.status_code)
        body = resp.json() if resp.content else {}
        tracking, txn = self._extract_ids(body)
        # ponytail: the UPS label comes back GIF/ZPL and the shared document
        # store is .pdf named end to end (_save_shipment_documents, the %PDF
        # magic check in routes_carrier_actions, every download route).
        # Persisting it needs one extension parameter threaded through that
        # store — do that when a UPS label is actually printed, never a
        # second document path here.
        return ShipmentResult(
            idempotency_key=compute_idempotency_key(request),
            mode=ShipmentMode.LIVE,
            state=ShipmentState.SUBMITTED,
            tracking_ref=tracking,
            simulated=False,
            service_product=request.product_code,
            carrier_transaction_id=txn,
        )

    def get_shipment(self, tracking_ref: str) -> ShipmentResult:
        """UPS tracking is not provisioned in the single tracking authority.

        tracking_service owns carrier tracking (DHL and FedEx today) and has
        no UPS client. Adding one here would make this adapter a second
        tracking authority for the same fact, so it refuses instead. UPS
        tracking lands in tracking_service or nowhere.
        """
        raise CarrierGateError("UPS_TRACK_NOT_PROVISIONED")

    def _post_ship(self, url: str, token: str, payload: dict):
        return httpx.post(
            url,
            json=payload,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def _service_code(self, request: ShipmentRequest) -> str:
        service = (request.product_code or "").strip()
        if not _UPS_SERVICE_RE.match(service):
            raise CarrierGateError("UPS_SERVICE_NOT_SELECTED")
        return service

    def _ship_payload(self, request: ShipmentRequest) -> dict:
        from ....core.config import settings

        incoterm = (request.incoterm or "").strip().upper()
        if not incoterm:
            raise CarrierGateError(
                "Incoterm missing on ShipmentRequest — refuse to invent DAP for UPS."
            )
        service = self._service_code(request)
        account = request.shipper_account
        # resolve_packages() derives one package from the scalar weight and
        # dimensions when the operator entered no split — the same helper DHL
        # and FedEx use, so a split is described once.
        packages = resolve_packages(request)

        # Transportation is always billed to us. Duty follows the commercial
        # term: DDP means the sender pays it, every other term leaves it with
        # the receiver. Derived from the Incoterm, never chosen here.
        # ponytail: the Incoterm reaches UPS as this duty split only. The
        # printed paper term lives in InternationalForms, whose FormType /
        # Product / InvoiceNumber subtree is a customs-forms slice of its own
        # — a half-filled block is a UPS validation error, not a partial win.
        charges = [{"Type": "01", "BillShipper": {"AccountNumber": account}}]
        if incoterm == "DDP":
            charges.append({"Type": "02", "BillShipper": {"AccountNumber": account}})

        return {
            "ShipmentRequest": {
                "Shipment": {
                    "Description": request.description or "Jewellery",
                    "Shipper": _to_ups_party(_build_shipper_details(settings), account),
                    "ShipTo": _to_ups_party(
                        _build_receiver_details(request.recipient_address or {})
                    ),
                    "PaymentInformation": {"ShipmentCharge": charges},
                    "Service": {"Code": service},
                    "InvoiceLineTotal": {
                        "CurrencyCode": request.currency,
                        "MonetaryValue": "%.2f" % float(request.declared_value),
                    },
                    "Package": [
                        {
                            "Packaging": {"Code": _CUSTOMER_PACKAGING},
                            "Dimensions": {
                                "UnitOfMeasurement": {"Code": "CM"},
                                "Length": str(pkg.get("length_cm", 1)),
                                "Width": str(pkg.get("width_cm", 1)),
                                "Height": str(pkg.get("height_cm", 1)),
                            },
                            "PackageWeight": {
                                "UnitOfMeasurement": {"Code": "KGS"},
                                "Weight": str(pkg.get("weight_kg")),
                            },
                        }
                        for pkg in packages
                    ],
                },
                "LabelSpecification": {"LabelImageFormat": {"Code": "GIF"}},
            }
        }

    def _extract_ids(self, body: dict):
        if not isinstance(body, dict):
            return None, None
        response = body.get("ShipmentResponse") or {}
        results = response.get("ShipmentResults") or {}
        tracking = results.get("ShipmentIdentificationNumber")
        if not tracking:
            packages = results.get("PackageResults") or []
            if isinstance(packages, dict):
                packages = [packages]
            if packages and isinstance(packages[0], dict):
                tracking = packages[0].get("TrackingNumber")
        ref = (response.get("Response") or {}).get("TransactionReference") or {}
        txn = ref.get("TransactionIdentifier") or ref.get("CustomerContext")
        return tracking, txn
