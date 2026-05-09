"""
dhl_express_live_request.py — Pure-logic mapping from
``CarrierShipmentRequest`` into the DHL MyDHL API JSON body.

DL-F1 scope
-----------
Pure logic. No HTTP, no DB, no env reads. Tested independently of the
HTTP transport so the request body stays a small, easy-to-review unit.

The mapping table here is the single source of truth on which Estrella
field lands at which DHL JSON path. Adapter changes that affect the
wire format must touch this file (and only this file) so reviewers
can see the diff at a glance.

Public API
----------
  build_create_shipment_body(request, *, account_number,
                             planned_shipping_dt=None) -> dict

Conventions
-----------
* Empty optional fields are emitted as empty strings, not omitted —
  DHL's schema validates presence rather than emptiness in some cases,
  and consistent shape simplifies fixture comparison in tests.
* The default ``productCode`` is ``P`` (EXPRESS WORLDWIDE) — Estrella's
  primary service. Callers should set ``request.service_code`` to the
  DHL productCode their account is provisioned for.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from ..base import CarrierAddress, CarrierShipmentRequest, PackageSpec


# ── Defaults ────────────────────────────────────────────────────────────────

#: DHL EXPRESS WORLDWIDE — the workhorse service for Estrella's lanes.
_DEFAULT_PRODUCT_CODE: str = "P"

#: Incoterm used when the caller doesn't specify. DAP = Delivered At
#: Place. Customs duty paid by the recipient. Mirrors Estrella's
#: standard outbound contract.
_DEFAULT_INCOTERM: str = "DAP"

#: DHL output template for self-service A4 PDF labels. Provisioned on
#: every Estrella account.
_DEFAULT_LABEL_TEMPLATE: str = "ECOM26_84_001"


# ── Address / package mappers ───────────────────────────────────────────────

def _address_to_dhl(addr: CarrierAddress) -> Dict[str, Any]:
    """Translate a CarrierAddress into DHL's
    {postalAddress, contactInformation} pair."""
    return {
        "postalAddress": {
            "addressLine1": addr.street_1 or "",
            "addressLine2": addr.street_2 or "",
            "cityName":     addr.city or "",
            "postalCode":   addr.postal_code or "",
            "countryCode":  addr.country or "",
        },
        "contactInformation": {
            "fullName":     addr.name or "",
            "companyName":  addr.company or addr.name or "",
            "phone":        addr.phone or "",
            "emailAddress": addr.email or "",
        },
    }


def _package_to_dhl(pkg: PackageSpec) -> Dict[str, Any]:
    """Translate a PackageSpec into a DHL packages[] entry."""
    return {
        "weight":     pkg.weight_kg,
        "dimensions": {
            "length": pkg.length_cm,
            "width":  pkg.width_cm,
            "height": pkg.height_cm,
        },
        "description":        pkg.description or "",
        "customerReferences": [],
    }


def _customer_references(req: CarrierShipmentRequest) -> list:
    """Translate batch_id / reference into DHL customerReferences[]."""
    refs: list = []
    if req.batch_id:
        # typeCode "CU" = customer reference
        refs.append({"value": req.batch_id, "typeCode": "CU"})
    if req.reference and req.reference != req.batch_id:
        # typeCode "AAO" = additional reference (the second slot)
        refs.append({"value": req.reference, "typeCode": "AAO"})
    return refs


def _planned_shipping_default() -> str:
    """Default plannedShippingDateAndTime = now + 1 hour, ISO-8601 UTC."""
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def _declared_value_total(req: CarrierShipmentRequest) -> float:
    """Sum of declared_value across all packages."""
    return sum(p.declared_value or 0.0 for p in req.packages)


def _declared_currency(req: CarrierShipmentRequest) -> str:
    """First package's currency wins; fallback USD."""
    if req.packages:
        return req.packages[0].declared_currency or "USD"
    return "USD"


def _content_description(req: CarrierShipmentRequest) -> str:
    """First non-empty package description; fallback to a generic
    string so DHL's schema validation passes."""
    for pkg in req.packages:
        if pkg.description:
            return pkg.description
    return "Goods"


# ── Public builder ──────────────────────────────────────────────────────────

#: DHL document type code for a commercial invoice.
_PLT_INV_TYPE_CODE: str = "INV"

#: DHL "shipper of record" signature on PLT-attached customs declarations.
#: Account-level constant for Estrella; if the DHL account is provisioned
#: with a different signatory name the live adapter callers can override.
_PLT_DEFAULT_SIGNATURE_NAME: str = "Estrella Jewels"


def build_create_shipment_body(
    request: CarrierShipmentRequest,
    *,
    account_number:           str,
    planned_shipping_dt:      Optional[str] = None,
    incoterm:                 str = _DEFAULT_INCOTERM,
    label_template:           str = _DEFAULT_LABEL_TEMPLATE,
    paperless_trade_pdf_bytes: Optional[bytes] = None,
    paperless_trade_signature_name: str = _PLT_DEFAULT_SIGNATURE_NAME,
) -> Dict[str, Any]:
    """Translate *request* into a DHL ``POST /shipments`` JSON body.

    Required: a non-empty *account_number*. Empty values raise
    ValueError so the adapter cannot accidentally send a request DHL
    will reject for a billing reason.

    Paperless Trade
    ---------------
    When *paperless_trade_pdf_bytes* is non-empty, the body gains:
      * ``content.exportDeclaration`` describing the declared invoice
      * ``documentImages[0]`` carrying the base64-encoded PDF bytes
        as ``typeCode = "INV"``.

    The caller (live adapter) is responsible for:
      * checking the operator-level feature flag,
      * running the ``dhl_paperless_trade.validate_paperless_trade_pdf``
        validator,
      * passing only validated bytes here.

    The body is deterministic given identical inputs — this lets
    request-mapping tests pin field placement without timestamp churn
    by passing a fixed *planned_shipping_dt*.
    """
    if not (account_number or "").strip():
        raise ValueError("account_number is required")
    if request is None:
        raise ValueError("request is required")
    if not request.packages:
        raise ValueError("request must carry at least one package")

    planned_dt = planned_shipping_dt or _planned_shipping_default()

    body: Dict[str, Any] = {
        "plannedShippingDateAndTime": planned_dt,
        "pickup": {
            # Estrella books pickups via the dedicated /pickups endpoint
            # — never inline on the shipment.
            "isRequested": False,
        },
        "productCode": (
            request.service_code or _DEFAULT_PRODUCT_CODE
        ),
        "accounts": [{
            "typeCode": "shipper",
            "number":   account_number,
        }],
        "customerDetails": {
            "shipperDetails":  _address_to_dhl(request.ship_from),
            "receiverDetails": _address_to_dhl(request.ship_to),
        },
        "content": {
            "packages":              [_package_to_dhl(p) for p in request.packages],
            "isCustomsDeclarable":   True,
            "declaredValue":         _declared_value_total(request),
            "declaredValueCurrency": _declared_currency(request),
            "description":           _content_description(request),
            "incoterm":              incoterm,
            "unitOfMeasurement":     "metric",
        },
        "customerReferences": _customer_references(request),
        "outputImageProperties": {
            "encodingFormat": "pdf",
            "imageOptions": [{
                "typeCode":     "label",
                "templateName": label_template,
                "isRequested":  True,
            }],
        },
    }

    if paperless_trade_pdf_bytes:
        # Inline the customs invoice as a Paperless Trade attachment.
        # Discipline: this branch fires ONLY when the caller has
        # already run the validator. The base64 encoding lives in
        # memory for the duration of the HTTP call only — never
        # persisted alongside the manifest or the shadow log.
        body["content"]["exportDeclaration"] = {
            "lineItems":         [],   # DHL infers from packages
            "invoice": {
                "number":        request.reference or request.batch_id,
                "date":          planned_dt[:10],
                "function":      "import",
                "signatureName": paperless_trade_signature_name,
            },
            "exportReason":      "permanent",
            "additionalCharges": [],
            "placeOfIncoterm":   request.ship_from.city or "Warsaw",
            "shipmentType":      "commercial",
        }
        body["documentImages"] = [{
            "typeCode":    _PLT_INV_TYPE_CODE,
            "imageFormat": "PDF",
            "content":     base64.b64encode(
                paperless_trade_pdf_bytes
            ).decode("ascii"),
        }]

    return body
