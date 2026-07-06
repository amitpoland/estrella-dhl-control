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

Product discovery (DHL-authoritative):
  Before creating a shipment, GET /rates is called to discover which productCodes DHL
  has entitled for this (account, origin→destination) combination.  Results are cached
  per (api_url, account, origin_cc, dest_cc) for 24 hours — entitlements do not change
  intra-day.  If the rates call fails (network, 4xx, timeout) the requested product_code
  passes through unchanged so that the shipment creation error surfaces the real reason.

On success: returns ShipmentResult(mode=LIVE, state=SUBMITTED, tracking_ref=<AWB>, simulated=False)
            and saves label PDF (if returned) to carrier_storage_root/labels/{batch_id}-{tracking_ref}.pdf

On DHL error (4xx/5xx): raises CarrierGateError with HTTP status + DHL detail message.
"""
from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

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

# ── product capability cache ──────────────────────────────────────────────────
# Key: (api_url, account_number, origin_cc, dest_cc)
# Value: (expires_monotonic, [productCode, ...]) — DHL-ranked, best first
_product_cache: dict = {}
_PRODUCT_CACHE_TTL_SECS: float = 86400.0  # 24 hours


def clear_product_cache() -> None:
    """Flush the module-level product cache. Intended for tests only."""
    _product_cache.clear()


# EU-27 member states (ISO 3166-1 alpha-2). Intra-EU shipments are
# customs-free: isCustomsDeclarable=false and no exportDeclaration
# (DHL 7121 rejects dutiable shipments without an export declaration).
_EU_COUNTRIES: frozenset = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
    "PL", "PT", "RO", "SK", "SI", "ES", "SE",
})


def _is_intra_eu(origin_cc: str, dest_cc: str) -> bool:
    """True when both origin and destination are EU member states."""
    return (
        origin_cc.strip().upper() in _EU_COUNTRIES
        and dest_cc.strip().upper() in _EU_COUNTRIES
    )


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

        # DHL requires receiverDetails.contactInformation.phone (minLength 1).
        # Fail fast with a clear local error instead of a DHL 422 round-trip
        # (2026-07-06: empty-string phone produced "minLength: 1, actual: 0").
        _recv_phone = (request.recipient_address.get("phone") or "").strip()
        if not _recv_phone:
            raise CarrierGateError(
                "Receiver phone is required by DHL Express — add it in the AWB "
                "form or in Customer Master for this client."
            )

        from ....core.config import settings
        import datetime

        planned_date = datetime.date.today().isoformat()
        origin_cc = settings.dhl_express_shipper_country_code or "PL"

        dest_cc = (
            request.recipient_address.get("country_code")
            or request.recipient_address.get("countryCode")
            or ""
        ).upper()

        # The rates query MUST ask for the same dutiable class the shipment
        # will actually be posted with — a dutiable PL→LT query returns [P, 8]
        # while the non-dutiable shipment only accepts [C, T, U, 7, B, W]
        # (DHL 1001 incident, 2026-07-03).
        is_dutiable = not _is_intra_eu(origin_cc, dest_cc)

        available = lookup_available_products(
            api_key=self._config.api_key,
            api_secret=self._config.api_secret,
            api_url=self._config.api_url,
            api_path=self._api_path(),
            account=self._config.account_number or request.shipper_account,
            origin_cc=origin_cc,
            origin_city=settings.dhl_express_shipper_city or "",
            origin_postal=settings.dhl_express_shipper_postal_code or "",
            dest_cc=dest_cc,
            dest_city=request.recipient_address.get("city") or "",
            dest_postal=request.recipient_address.get("postal_code") or "",
            weight_kg=request.weight_kg,
            planned_date=planned_date,
            is_customs_declarable=is_dutiable,
        )
        resolved_product = select_product_code(request.product_code or "P", available)

        body = _build_shipment_body(request, settings, product_code=resolved_product)
        key = compute_idempotency_key(request)

        shipment_url = f"{self._config.api_url.rstrip('/')}{self._api_path()}/shipments"
        if dest_cc == "BR":
            shipment_url += "?bypassPLTError=true"

        with httpx.Client(
            auth=httpx.BasicAuth(self._config.api_key, self._config.api_secret),
            timeout=30.0,
        ) as client:
            resp = client.post(shipment_url, json=body)

        if not resp.is_success:
            _raise_dhl_error(resp)

        data = resp.json()
        tracking_ref = data.get("shipmentTrackingNumber") or data.get("packages", [{}])[0].get("trackingNumber")
        if not tracking_ref:
            raise CarrierGateError(
                f"DHL response missing shipmentTrackingNumber. Response keys: {list(data.keys())}"
            )

        # Save every returned shipment document (label / waybillDoc / receipt /
        # invoice) to its own store — each becomes downloadable separately.
        _save_shipment_documents(data, request.batch_id, tracking_ref, settings)

        log.info("AWB created: batch=%s tracking_ref=%s", request.batch_id, tracking_ref)

        return ShipmentResult(
            idempotency_key=key,
            mode=ShipmentMode.LIVE,
            state=ShipmentState.SUBMITTED,
            tracking_ref=tracking_ref,
            simulated=False,
            service_product=resolved_product,
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


# ── product discovery ─────────────────────────────────────────────────────────

# When the requested product is not entitled on a route, prefer its business
# equivalent over DHL's raw list order (which can lead with unrelated
# products, e.g. C = Medical Express on non-dutiable EU lanes).
# P (Express Worldwide) → U (Express Worldwide EU) → W (Economy Select).
_PRODUCT_EQUIVALENTS: dict = {"P": ("U", "W")}


def lookup_available_products(
    api_key: str,
    api_secret: str,
    api_url: str,
    api_path: str,
    account: str,
    origin_cc: str,
    origin_city: str,
    origin_postal: str,
    dest_cc: str,
    dest_city: str,
    dest_postal: str,
    weight_kg: float,
    planned_date: str,
    is_customs_declarable: bool = True,
) -> List[str]:
    """
    Query DHL GET /rates to discover available productCodes for a route.

    is_customs_declarable MUST match the dutiable class the shipment will be
    posted with — DHL entitles different products per class on the same route
    (dutiable PL→LT: [P, 8]; non-dutiable: [C, T, U, 7, B, W]).

    Returns a list of productCodes ranked by DHL (best option first).
    Returns an empty list on any failure — the caller falls back to the
    operator-supplied product_code in that case. Empty results are NOT
    cached: a transient empty answer must not poison the route for 24h.

    Results are cached per (api_url, account, origin_cc, dest_cc, declarable)
    for 24 hours. City and postal are sent to DHL for routing accuracy but are
    NOT part of the cache key because product entitlements are country-level
    for international.
    """
    cache_key = (api_url, account, origin_cc, dest_cc, is_customs_declarable)
    entry = _product_cache.get(cache_key)
    if entry is not None:
        expires_at, codes = entry
        if time.monotonic() < expires_at:
            return codes
        del _product_cache[cache_key]

    try:
        with httpx.Client(
            auth=httpx.BasicAuth(api_key, api_secret),
            timeout=10.0,
        ) as client:
            resp = client.get(
                f"{api_url.rstrip('/')}{api_path}/rates",
                params={
                    "accountNumber": account,
                    "originCountryCode": origin_cc,
                    "originCityName": origin_city,
                    "originPostalCode": origin_postal,
                    "destinationCountryCode": dest_cc,
                    "destinationCityName": dest_city,
                    "destinationPostalCode": dest_postal,
                    "weight": weight_kg,
                    "length": 10,
                    "width": 10,
                    "height": 10,
                    "plannedShippingDate": planned_date,
                    "isCustomsDeclarable": is_customs_declarable,
                    "unitOfMeasurement": "metric",
                    "nextBusinessDay": False,
                },
            )
        if resp.is_success:
            products_raw = resp.json().get("products") or []
            codes = [p["productCode"] for p in products_raw if p.get("productCode")]
            if codes:
                _product_cache[cache_key] = (
                    time.monotonic() + _PRODUCT_CACHE_TTL_SECS,
                    codes,
                )
            log.info(
                "DHL product discovery %s→%s declarable=%s account=%s: %s",
                origin_cc, dest_cc, is_customs_declarable, account, codes,
            )
            return codes
        log.warning(
            "DHL rates lookup %s: %s (non-fatal, falling back to requested product)",
            resp.status_code,
            resp.text[:200],
        )
        return []
    except Exception as exc:
        log.warning("DHL rates lookup error (non-fatal): %s", exc)
        return []


def select_product_code(requested: str, available: List[str]) -> str:
    """
    Choose the DHL productCode to use based on what the account can actually send.

    Rules (in priority order):
      1. If available is empty (rates lookup failed) → use requested unchanged.
      2. If requested is in available → use requested.
      3. If the requested product has a known equivalent in available, use it
         (P → U → W: Express Worldwide's non-dutiable/EU counterparts — the
         raw rates list can lead with unrelated products like C/Medical Express).
      4. Otherwise → use DHL's first available product and log the change.
    """
    if not available:
        return requested
    if requested in available:
        return requested
    for equivalent in _PRODUCT_EQUIVALENTS.get(requested, ()):
        if equivalent in available:
            log.info(
                "productCode %r not available; using equivalent %r (available: %s)",
                requested, equivalent, available,
            )
            return equivalent
    chosen = available[0]
    log.info(
        "productCode %r not available for this route; "
        "using DHL-ranked alternative %r (available: %s)",
        requested,
        chosen,
        available,
    )
    return chosen


# ── DHL request body builder ──────────────────────────────────────────────────


def _build_shipment_body(
    request: ShipmentRequest,
    settings,
    product_code: Optional[str] = None,
) -> dict:
    """Map ShipmentRequest + settings → DHL Express MyDHL API v2 request body.

    product_code overrides request.product_code when provided (used by the
    product-discovery layer to inject the DHL-authoritative product after
    the GET /rates capability check).
    """
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

    # Intra-EU shipments are customs-free (no exportDeclaration exists yet,
    # so a dutiable intra-EU request would fail DHL validation 7121).
    origin_cc = (settings.dhl_express_shipper_country_code or "PL")
    is_dutiable = not _is_intra_eu(origin_cc, _recv_cc)

    body: dict = {
        "plannedShippingDateAndTime": planned,
        "pickup": {"isRequested": False},
        "productCode": product_code or request.product_code or "P",
        "accounts": [
            {
                "typeCode": "shipper",
                "number": request.shipper_account,
            }
        ],
        "outputImageProperties": {
            "printerDPI": 300,
            "encodingFormat": "pdf",
            # Request the full document set: transport label (attach to
            # package), waybill document (hand to courier), shipment receipt
            # (operator/customer copy). Customs invoice is appended below
            # only when an exportDeclaration exists (DHL requires it).
            "imageOptions": [
                {"typeCode": "label", "templateName": "ECOM26_84_001"},
                {"typeCode": "waybillDoc", "isRequested": True},
                {"typeCode": "receipt", "isRequested": True},
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
            "isCustomsDeclarable": is_dutiable,
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
        refs.append({"value": request.shipment_reference[:35], "typeCode": "CU"})
    if refs:
        body["customerReferences"] = refs

    if request.special_instructions:
        body["specialServices"] = [
            {"serviceCode": "PT", "specialServiceDescription": request.special_instructions}
        ]

    # Brazil: WY (Paperless Trade) required alongside bypassPLTError URL param (DHL CFIT 2026-07-01)
    if _recv_cc.upper() == "BR":
        body["valueAddedServices"] = [{"serviceCode": "WY"}]

    # DHL can only generate the customs/commercial invoice document when an
    # exportDeclaration is present (requested here for when the non-EU
    # exportDeclaration builder lands — currently intra-EU bodies never
    # carry one, so this is inert today).
    if "exportDeclaration" in body["content"]:
        body["outputImageProperties"]["imageOptions"].append(
            {"typeCode": "invoice", "isRequested": True, "invoiceType": "commercial"}
        )

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
    """Map the recipient address onto DHL receiverDetails.

    DHL's schema rejects empty strings (minLength 1) — optional fields
    (postalCode, email) are OMITTED when blank, never sent as "". phone is
    DHL-required and guarded upstream in create_shipment(); it is only
    included here when non-blank so an empty string can never be emitted.
    """
    postal_address: dict = {
        "cityName":    addr.get("city") or addr.get("cityName") or "",
        "countryCode": addr.get("country_code") or addr.get("countryCode") or "",
        "addressLine1": addr.get("street") or addr.get("addressLine1") or "",
    }
    postal_code = (addr.get("postal_code") or addr.get("postalCode") or "").strip()
    if postal_code:
        postal_address["postalCode"] = postal_code

    contact: dict = {
        "fullName":    addr.get("name") or addr.get("fullName") or "",
        "companyName": addr.get("company") or addr.get("name") or "",
    }
    phone = (addr.get("phone") or "").strip()
    if phone:
        contact["phone"] = phone
    email = (addr.get("email") or "").strip()
    if email:
        contact["email"] = email

    return {
        "postalAddress": postal_address,
        "contactInformation": contact,
    }


# ── helpers ───────────────────────────────────────────────────────────────────


def _raise_dhl_error(resp: httpx.Response) -> None:
    try:
        detail = resp.json()
        msg = detail.get("detail") or detail.get("message") or detail.get("title") or str(detail)
        # DHL validation errors ("Multiple problems found, see Additional Details")
        # carry the field-level violations in additionalDetails — surface every
        # entry or the failure is undiagnosable from UI/logs. Response content
        # only; never the request body or credentials.
        extras = detail.get("additionalDetails")
        if extras:
            items = extras if isinstance(extras, list) else [extras]
            parts = []
            for item in items:
                if isinstance(item, dict):
                    text = " ".join(
                        str(item[k]) for k in ("code", "path", "message") if item.get(k)
                    )
                    parts.append(text or str(item))
                else:
                    parts.append(str(item))
            msg = f"{msg} | Additional details: {'; '.join(parts)}"
    except Exception:
        msg = resp.text[:500]
    raise CarrierGateError(f"DHL API {resp.status_code}: {msg}")


# DHL response document typeCode → storage subdirectory. The label keeps its
# historical location/naming so every existing (legacy) label stays
# downloadable unchanged. The invoice (DHL customs/commercial document) lands
# in doc_packages/{batch_id}.pdf — the exact slot the existing
# /documents endpoint + commercial_documents_url contract already serve.
_DOC_TYPE_DIRS = {
    "label":      "labels",
    "waybillDoc": "waybill_docs",
    "receipt":    "shipment_receipts",
}


def _save_shipment_documents(data: dict, batch_id: str, tracking_ref: str, settings) -> None:
    """Persist every base64 document DHL returned, one file per typeCode.

    Non-fatal on any individual failure — the shipment is already booked;
    a missing file only means its download button stays hidden.
    """
    docs = data.get("documents") or []
    root = Path(settings.carrier_storage_root or (settings.storage_root / "carrier"))
    safe_ref = tracking_ref.replace("/", "_").replace("\\", "_")
    for doc in docs:
        type_code = doc.get("typeCode") or ""
        content_b64 = doc.get("content")
        if not content_b64:
            continue
        try:
            pdf_bytes = base64.b64decode(content_b64)
            if type_code in _DOC_TYPE_DIRS:
                target_dir = root / _DOC_TYPE_DIRS[type_code]
                target_dir.mkdir(parents=True, exist_ok=True)
                path = target_dir / f"{batch_id}-{safe_ref}.pdf"
            elif type_code == "invoice":
                target_dir = root / "doc_packages"
                target_dir.mkdir(parents=True, exist_ok=True)
                path = target_dir / f"{batch_id}.pdf"
            else:
                log.info("Unknown DHL document typeCode %r — skipped", type_code)
                continue
            path.write_bytes(pdf_bytes)
            log.info("DHL document saved: type=%s %s", type_code, path)
        except Exception as exc:
            log.warning("DHL document save failed (non-fatal, type=%s): %s", type_code, exc)
