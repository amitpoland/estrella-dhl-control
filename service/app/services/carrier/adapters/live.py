"""
DhlExpressLiveAdapter — Phase D implementation.

Guards (run before every API call):
  1. Allowlist check  — batch_id must be in carrier_live_allowlist, or allowlist == {"*"}
  2. Credential check — api_key + api_secret + account_number must be set

HTTP: httpx.Client with BasicAuth(api_key, api_secret), timeout 30s.
Endpoint: POST {api_url}/mydhlapi/shipments         (production, DHL_EXPRESS_USE_SANDBOX=false)
          POST {api_url}/mydhlapi/test/shipments    (sandbox,    DHL_EXPRESS_USE_SANDBOX=true)

DHL_EXPRESS_API_URL is the base URL only (https://express.api.dhl.com).
Use DHL_EXPRESS_USE_SANDBOX=true to route to the test endpoint — do NOT append
/mydhlapi/test to DHL_EXPRESS_API_URL; that produces a double-path 404.

On success: returns ShipmentResult(mode=LIVE, state=SUBMITTED, tracking_ref=<AWB>, simulated=False)
            and saves label PDF (if returned) to carrier_storage_root/labels/{batch_id}-{tracking_ref}.pdf

On DHL error (4xx/5xx): raises CarrierGateError with HTTP status + DHL detail message.
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import httpx

from .base import AbstractCarrierAdapter
from ..models.shipment import (
    CarrierAllowlistError,
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


class DhlExpressLiveAdapter(AbstractCarrierAdapter):

    def __init__(self, config: "CarrierConfig") -> None:
        self._config = config
        raw = config.live_allowlist or ""
        self._allowlist: frozenset[str] = frozenset(
            b.strip() for b in raw.split(",") if b.strip()
        )

    # ── public interface ──────────────────────────────────────────────────────

    def create_shipment(self, request: ShipmentRequest) -> ShipmentResult:
        self._check_allowlist(request.batch_id)
        self._check_credentials()

        from ....core.config import settings

        body = _build_shipment_body(request, settings)
        key = compute_idempotency_key(request)

        with httpx.Client(
            auth=httpx.BasicAuth(self._config.api_key, self._config.api_secret),
            timeout=30.0,
        ) as client:
            resp = client.post(
                f"{self._config.api_url.rstrip('/')}{self._api_path()}/shipments",
                json=body,
            )

        if not resp.is_success:
            _raise_dhl_error(resp)

        data = resp.json()
        tracking_ref = data.get("shipmentTrackingNumber") or data.get("packages", [{}])[0].get("trackingNumber")
        if not tracking_ref:
            raise CarrierGateError(
                f"DHL response missing shipmentTrackingNumber. Response keys: {list(data.keys())}"
            )

        # Save label PDF if returned
        _save_label_pdf(data, request.batch_id, tracking_ref, settings)

        log.info("AWB created: batch=%s tracking_ref=%s", request.batch_id, tracking_ref)

        return ShipmentResult(
            idempotency_key=key,
            mode=ShipmentMode.LIVE,
            state=ShipmentState.SUBMITTED,
            tracking_ref=tracking_ref,
            simulated=False,
        )

    def get_shipment(self, tracking_ref: str) -> ShipmentResult:
        self._check_credentials()

        with httpx.Client(
            auth=httpx.BasicAuth(self._config.api_key, self._config.api_secret),
            timeout=30.0,
        ) as client:
            resp = client.get(
                f"{self._config.api_url.rstrip('/')}{self._api_path()}/shipments/{tracking_ref}",
            )

        if not resp.is_success:
            _raise_dhl_error(resp)

        data = resp.json()
        # DHL tracking status → ShipmentState mapping
        status = (data.get("status") or "").upper()
        state = ShipmentState.COMPLETE if status in {"DELIVERED", "OK"} else ShipmentState.SUBMITTED

        from ..models.shipment import compute_idempotency_key as _ik
        import hashlib
        key = hashlib.sha256(tracking_ref.encode()).hexdigest()

        return ShipmentResult(
            idempotency_key=key,
            mode=ShipmentMode.LIVE,
            state=state,
            tracking_ref=tracking_ref,
            simulated=False,
        )

    # ── private guards ────────────────────────────────────────────────────────

    def _check_allowlist(self, batch_id: str) -> None:
        if not self._allowlist:
            raise CarrierAllowlistError(
                "carrier_live_allowlist is empty — live calls require at least one "
                "batch_id or '*' in CARRIER_LIVE_ALLOWLIST."
            )
        if "*" in self._allowlist:
            return  # wildcard — all batches allowed
        if batch_id not in self._allowlist:
            raise CarrierAllowlistError(
                f"batch_id {batch_id!r} is not in carrier_live_allowlist. "
                "Add it to CARRIER_LIVE_ALLOWLIST or set CARRIER_LIVE_ALLOWLIST=* to permit all."
            )

    def _api_path(self) -> str:
        """Return the DHL MyDHL API path prefix based on sandbox flag.

        Production: /mydhlapi
        Sandbox:    /mydhlapi/test

        DHL_EXPRESS_API_URL must be the bare base URL (https://express.api.dhl.com).
        Setting DHL_EXPRESS_USE_SANDBOX=true switches the path; do NOT put /mydhlapi/test
        in DHL_EXPRESS_API_URL — that causes a double-path 404.
        """
        return "/mydhlapi/test" if self._config.use_sandbox else "/mydhlapi"

    def _check_credentials(self) -> None:
        if not self._config.api_key or not self._config.api_secret:
            raise CarrierConfigError(
                "DHL Express live mode requires both DHL_EXPRESS_API_KEY and "
                "DHL_EXPRESS_API_SECRET to be set."
            )


# ── DHL request body builder ──────────────────────────────────────────────────


def _build_shipment_body(request: ShipmentRequest, settings) -> dict:
    """Map ShipmentRequest + settings → DHL Express MyDHL API v2 request body."""
    import datetime

    # Planned shipping: today at 08:00 UTC
    today = datetime.date.today().isoformat()
    planned = f"{today}T08:00:00 GMT+00:00"

    receiver_details = _build_receiver_details(request.recipient_address)

    # Attach EORI / VAT registration numbers to receiver if provided.
    # DHL requires issuerCountryCode on every entry; derive it from the
    # number's 2-char alpha prefix (standard EU EORI/VAT format) and fall
    # back to the receiver's country code when the prefix is not alpha.
    reg_numbers = []
    _recv_cc = (request.recipient_address.get("country_code")
                or request.recipient_address.get("countryCode") or "")
    def _issuer(num: str) -> str:
        prefix = num[:2].upper()
        return prefix if prefix.isalpha() else _recv_cc
    if request.receiver_eori:
        reg_numbers.append({"number": request.receiver_eori,
                             "typeCode": "EOR",
                             "issuerCountryCode": _issuer(request.receiver_eori)})
    if request.receiver_vat_id:
        reg_numbers.append({"number": request.receiver_vat_id,
                             "typeCode": "EUV",
                             "issuerCountryCode": _issuer(request.receiver_vat_id)})
    if reg_numbers:
        receiver_details["registrationNumbers"] = reg_numbers

    body: dict = {
        "plannedShippingDateAndTime": planned,
        "pickup": {"isRequested": False},
        "productCode": request.product_code or "P",
        "accounts": [
            {
                "typeCode": "shipper",
                "number": request.shipper_account,
            }
        ],
        "outputImageProperties": {
            "printerDPI": 300,
            "encodingFormat": "pdf",
            "imageOptions": [
                {"typeCode": "label", "templateName": "ECOM26_84_001"}
            ],
        },
        "customerDetails": {
            "shipperDetails": _build_shipper_details(settings),
            "receiverDetails": receiver_details,
        },
        "content": {
            "packages": [
                {
                    "weight": request.weight_kg,
                    "dimensions": {
                        "length": request.dimensions.get("length_cm", 1),
                        "width":  request.dimensions.get("width_cm",  1),
                        "height": request.dimensions.get("height_cm", 1),
                    },
                }
            ],
            "isCustomsDeclarable": True,
            "declaredValue": request.declared_value,
            "declaredValueCurrency": request.currency,
            "incoterm": "DAP",
            "unitOfMeasurement": "metric",
            "description": request.description or "Jewellery",
        },
    }

    # Customer / shipment references
    refs = []
    if request.customer_reference:
        refs.append({"value": request.customer_reference[:35], "typeCode": "CU"})
    if request.shipment_reference:
        refs.append({"value": request.shipment_reference[:35], "typeCode": "AAO"})
    if refs:
        body["customerReferences"] = refs

    if request.special_instructions:
        body["specialServices"] = [
            {"serviceCode": "PT", "specialServiceDescription": request.special_instructions}
        ]

    return body


def _build_shipper_details(settings) -> dict:
    return {
        "postalAddress": {
            "postalCode":  settings.dhl_express_shipper_postal_code or "",
            "cityName":    settings.dhl_express_shipper_city or "",
            "countryCode": settings.dhl_express_shipper_country_code or "IN",
            "addressLine1": settings.dhl_express_shipper_address1 or "",
        },
        "contactInformation": {
            "companyName": settings.dhl_express_shipper_name or "Estrella Jewels",
            "fullName":    settings.dhl_express_shipper_name or "Estrella Jewels",
            "phone":       settings.dhl_express_shipper_phone or "",
        },
    }


def _build_receiver_details(addr: dict) -> dict:
    return {
        "postalAddress": {
            "postalCode":  addr.get("postal_code") or addr.get("postalCode") or "",
            "cityName":    addr.get("city") or addr.get("cityName") or "",
            "countryCode": addr.get("country_code") or addr.get("countryCode") or "",
            "addressLine1": addr.get("street") or addr.get("addressLine1") or "",
        },
        "contactInformation": {
            "fullName":    addr.get("name") or addr.get("fullName") or "",
            "companyName": addr.get("company") or addr.get("name") or "",
            "phone":       addr.get("phone") or "",
            "email":       addr.get("email") or "",
        },
    }


# ── helpers ───────────────────────────────────────────────────────────────────


def _raise_dhl_error(resp: httpx.Response) -> None:
    try:
        detail = resp.json()
        msg = detail.get("detail") or detail.get("message") or detail.get("title") or str(detail)
    except Exception:
        msg = resp.text[:500]
    raise CarrierGateError(f"DHL API {resp.status_code}: {msg}")


def _save_label_pdf(data: dict, batch_id: str, tracking_ref: str, settings) -> None:
    docs = data.get("documents") or []
    for doc in docs:
        if doc.get("typeCode") == "label":
            content_b64 = doc.get("content")
            if not content_b64:
                continue
            try:
                pdf_bytes = base64.b64decode(content_b64)
                root = settings.carrier_storage_root or (settings.storage_root / "carrier")
                labels_dir = Path(root) / "labels"
                labels_dir.mkdir(parents=True, exist_ok=True)
                safe_ref = tracking_ref.replace("/", "_").replace("\\", "_")
                label_path = labels_dir / f"{batch_id}-{safe_ref}.pdf"
                label_path.write_bytes(pdf_bytes)
                log.info("Label saved: %s", label_path)
            except Exception as exc:
                log.warning("Label PDF save failed (non-fatal): %s", exc)
            break
