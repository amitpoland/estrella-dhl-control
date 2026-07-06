"""
Carrier action routes — shipment creation, state retrieval, and Path-DOC package.

POST /api/v1/carrier/{batch_id}/shipment
    Creates a shipment via CarrierCoordinator.
    503 if carrier_api_status == "pending".
    Returns: batch_id, idempotency_key, mode, state, tracking_ref, simulated.

GET /api/v1/carrier/{batch_id}/shipment
    Returns most-recent recorded shipment for the batch.
    Returns: batch_id, idempotency_key, mode, state, simulated, error, plus the
    AWB logistics/document contract (tracking_ref, carrier, service_code,
    box_type_code, weight_kg, dimensions, declared_value, currency, created_at,
    label_download_url, commercial_documents_url, documents_available,
    saved_labels_exist). tracking_ref persisted since the 2026-07-06 incident
    fix; legacy rows return null fields honestly.

POST /api/v1/carrier/{batch_id}/label-package   ← Path-DOC (WF4.5)
    Generates outbound customs/shipping document package.
    UNGATED — no carrier_api_status / creds / allowlist check.
    Returns: PDF or ZIP bytes containing invoice + packing list + CN23 (non-EU).
    422 {gaps:[...]} when mandatory inputs are missing.

Auth: X-API-Key header via require_api_key (same pattern as routes_pz.py).
No live DHL calls in shadow mode.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from ..core.security import require_api_key
from ..services.carrier.coordinator import CarrierCoordinator, CoordinatorConfig
from ..services.carrier.factory import CarrierConfig
from ..services.carrier.models.shipment import CarrierGateError, ShipmentRequest
from ..services.carrier.persistence import shipment_db

router = APIRouter(prefix="/api/v1/carrier", tags=["carrier"])


# ── Dependencies ──────────────────────────────────────────────────────────────


def _get_carrier_config() -> CarrierConfig:
    from ..core.config import settings
    if settings.carrier_api_status == "pending":
        raise HTTPException(
            status_code=503,
            detail=(
                "Carrier API is not yet activated (carrier_api_status=pending). "
                "Set CARRIER_API_STATUS=shadow or CARRIER_API_STATUS=live to enable."
            ),
        )
    return CarrierConfig(
        status=settings.carrier_api_status,
        api_key=settings.dhl_express_api_key,
        api_secret=settings.dhl_express_api_secret,
        api_url=settings.dhl_express_api_url,
        use_sandbox=settings.dhl_express_use_sandbox,
        account_number=settings.dhl_express_account_number,
        live_allowlist=settings.carrier_live_allowlist,
    )


def _get_coordinator(
    config: CarrierConfig = Depends(_get_carrier_config),
) -> CarrierCoordinator:
    from ..core.config import settings
    root = settings.carrier_storage_root or (settings.storage_root / "carrier")
    root.mkdir(parents=True, exist_ok=True)
    return CarrierCoordinator(
        CoordinatorConfig(
            carrier_config=config,
            shipment_db_path=root / "carrier_shipments.db",
            shadow_log_db_path=root / "shadow_log.db",
        )
    )


def _get_shipment_db_path() -> Path:
    from ..core.config import settings
    root = settings.carrier_storage_root or (settings.storage_root / "carrier")
    root.mkdir(parents=True, exist_ok=True)
    return root / "carrier_shipments.db"


# ── Label / document location helpers ─────────────────────────────────────────
# The UI never sees filesystem paths — only relative API URLs built here.

import re as _re

_SAFE_REF = _re.compile(r"^[A-Za-z0-9_-]{4,64}$")
_SAFE_BATCH = _re.compile(r"^[A-Za-z0-9_-]{4,128}$")


def _carrier_root() -> Path:
    from ..core.config import settings
    return Path(settings.carrier_storage_root or (settings.storage_root / "carrier"))


def _label_file(batch_id: str, tracking_ref: str) -> Optional[Path]:
    """Resolve the saved label PDF for (batch, AWB). None when absent/invalid.

    Mirrors the naming used by the live adapter's _save_label_pdf():
    labels/{batch_id}-{tracking_ref}.pdf. Inputs are pattern-validated and the
    resolved path is confined to the labels directory (no traversal).
    """
    if not (isinstance(batch_id, str) and isinstance(tracking_ref, str)):
        return None
    if not (_SAFE_BATCH.match(batch_id) and _SAFE_REF.match(tracking_ref)):
        return None
    labels_dir = (_carrier_root() / "labels").resolve()
    candidate = (labels_dir / f"{batch_id}-{tracking_ref}.pdf").resolve()
    if candidate.parent != labels_dir or not candidate.is_file():
        return None
    return candidate


def _batch_has_any_label(batch_id: str) -> bool:
    if not (isinstance(batch_id, str) and _SAFE_BATCH.match(batch_id)):
        return False
    labels_dir = _carrier_root() / "labels"
    if not labels_dir.is_dir():
        return False
    return any(labels_dir.glob(f"{batch_id}-*.pdf"))


def _doc_package_file(batch_id: str) -> Optional[Path]:
    """Saved commercial-document package for the batch, if one exists.

    Path-DOC currently streams packages without saving; this lights up
    automatically if/when packages are persisted under doc_packages/.
    """
    if not (isinstance(batch_id, str) and _SAFE_BATCH.match(batch_id)):
        return None
    pkg_dir = (_carrier_root() / "doc_packages").resolve()
    if not pkg_dir.is_dir():
        return None
    for ext in ("pdf", "zip"):
        candidate = (pkg_dir / f"{batch_id}.{ext}").resolve()
        if candidate.parent == pkg_dir and candidate.is_file():
            return candidate
    return None


_NO_STORE_HEADERS = {
    # Lesson G — download endpoints must never be cached.
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


# ── Request body ──────────────────────────────────────────────────────────────


class ShipmentRequestBody(BaseModel):
    shipper_account: Optional[str] = None  # falls back to DHL_EXPRESS_ACCOUNT_NUMBER setting
    recipient_address: dict
    declared_value: float
    currency: str
    weight_kg: float
    dimensions: dict
    special_instructions: Optional[str] = None
    # Upgraded AWB modal fields — all optional, defaults applied in ShipmentRequest
    product_code: Optional[str] = None        # DHL productCode; defaults to "P"
    description: Optional[str] = None         # shipment description; defaults to "Jewellery"
    customer_reference: Optional[str] = None  # proforma/order reference
    shipment_reference: Optional[str] = None  # internal batch reference
    receiver_vat_id: Optional[str] = None     # receiver EU VAT number
    receiver_eori: Optional[str] = None       # receiver EORI number
    box_type_code: Optional[str] = None       # Box Master profile selected in the modal


# ── Routes ────────────────────────────────────────────────────────────────────


# Static DHL product catalogue — no live DHL call, no credentials required.
# Must appear before /{batch_id} routes to avoid path-parameter capture.
_DHL_SERVICES = [
    {"code": "P", "name": "Express Worldwide",             "delivery": "End of day"},
    {"code": "Y", "name": "Express 12:00",                 "delivery": "By 12:00"},
    {"code": "K", "name": "Express 9:00",                  "delivery": "By 09:00"},
    {"code": "D", "name": "Express Worldwide (Documents)", "delivery": "Documents only"},
    {"code": "T", "name": "Express Domestic",              "delivery": "Domestic service"},
]


@router.get("/services", summary="List available DHL Express product codes (static catalogue)")
def list_carrier_services(_auth: None = Depends(require_api_key)) -> JSONResponse:
    """Returns the static DHL Express product code catalogue.

    No live DHL call is made. Use this to populate the service dropdown in the AWB modal.
    Availability for a specific shipment requires a DHL /rates query (not yet implemented).
    """
    return JSONResponse(_DHL_SERVICES)


@router.post("/{batch_id}/shipment")
def create_shipment(
    batch_id: str,
    body: ShipmentRequestBody,
    _auth: None = Depends(require_api_key),
    coordinator: CarrierCoordinator = Depends(_get_coordinator),
) -> JSONResponse:
    from ..core.config import settings

    # Resolve shipper account — body takes precedence, then settings, then 422
    shipper_account = body.shipper_account or settings.dhl_express_account_number
    if not shipper_account:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "No DHL Express account number configured",
                "code": "SHIPPER_ACCOUNT_MISSING",
                "guidance": "Set DHL_EXPRESS_ACCOUNT_NUMBER in environment or pass shipper_account in request body.",
            },
        )

    # Resolve recipient address via Customer Master authority (Condition 2: feature flag)
    if settings.awb_address_authority_enabled:
        try:
            from ..services.awb_address_authority import (
                derive_awb_address_authority_with_fallback,
                CustomerNotFoundError,
                AddressMissingError
            )

            # Use authority derivation with graceful degradation (Condition 3)
            recipient_address = derive_awb_address_authority_with_fallback(
                batch_id,
                settings.storage_root,
                raw_fallback=body.recipient_address
            )

            # Remove 'source' metadata before passing to carrier API
            carrier_address = {k: v for k, v in recipient_address.items() if k != 'source'}

            # Log address source for audit trail
            import logging
            source = recipient_address.get('source', 'unknown')
            logging.info(f"AWB {batch_id}: address authority source={source}")

        except CustomerNotFoundError as exc:
            # Condition 5: sanitized 422 error response
            raise HTTPException(status_code=422, detail={
                "error": "Customer resolution failed",
                "code": "CUSTOMER_NOT_FOUND",
                "batch_id": batch_id,
                "guidance": "Please ensure the batch has valid customer data in Customer Master or use historical batch override for batches older than 90 days"
            })
        except AddressMissingError as exc:
            # Condition 5: sanitized 422 error response
            raise HTTPException(status_code=422, detail={
                "error": "Address validation failed",
                "code": "ADDRESS_INCOMPLETE",
                "batch_id": batch_id,
                "guidance": "Please complete the customer address in Customer Master (ship-to or bill-to fields required: name, street, city, country)"
            })
    else:
        # Flag OFF = today's behavior unchanged (Condition 2)
        carrier_address = body.recipient_address

    request = ShipmentRequest(
        batch_id=batch_id,
        shipper_account=shipper_account,
        recipient_address=carrier_address,
        declared_value=body.declared_value,
        currency=body.currency,
        weight_kg=body.weight_kg,
        dimensions=body.dimensions,
        special_instructions=body.special_instructions,
        product_code=body.product_code or "P",
        description=body.description or "Jewellery",
        customer_reference=body.customer_reference,
        shipment_reference=body.shipment_reference,
        receiver_vat_id=body.receiver_vat_id,
        receiver_eori=body.receiver_eori,
        box_type_code=body.box_type_code,
    )
    try:
        result = coordinator.create_shipment(request)
    except CarrierGateError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Document link contract — relative API URLs only, never filesystem paths.
    label_download_url = None
    if result.tracking_ref and _label_file(batch_id, result.tracking_ref):
        label_download_url = f"/api/v1/carrier/{batch_id}/label/{result.tracking_ref}"
    commercial_documents_url = None
    if _doc_package_file(batch_id):
        commercial_documents_url = f"/api/v1/carrier/{batch_id}/documents"

    return JSONResponse({
        "batch_id": batch_id,
        "idempotency_key": result.idempotency_key,
        "mode": result.mode.value,
        "state": result.state.value,
        "tracking_ref": result.tracking_ref,
        "simulated": result.simulated,
        # Replay indicator: True when served from the stored COMPLETE row —
        # no adapter call was made, no new DHL shipment was created.
        "replayed": bool(result.replayed),
        "label_download_url": label_download_url,
        "commercial_documents_url": commercial_documents_url,
        "documents_available": commercial_documents_url is not None,
        # Legacy pre-migration rows have no stored tracking_ref; tell the UI
        # whether labels exist on the server for this batch anyway.
        "saved_labels_exist": _batch_has_any_label(batch_id),
        # AWB logistics summary — echoes the shipment intent for display.
        "carrier": "DHL",
        "service_code": (result.service_product if isinstance(result.service_product, str)
                         else (body.product_code or "P")),
        "box_type_code": body.box_type_code,
        "weight_kg": body.weight_kg,
        "dimensions": body.dimensions,
        "declared_value": body.declared_value,
        "currency": body.currency,
    })


@router.get("/{batch_id}/shipment")
def get_shipment(
    batch_id: str,
    _auth: None = Depends(require_api_key),
    _config: CarrierConfig = Depends(_get_carrier_config),
    db_path: Path = Depends(_get_shipment_db_path),
) -> JSONResponse:
    shipment_db.init_db(db_path)
    row = shipment_db.get_shipment_by_batch_id(db_path, batch_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No shipment found for batch {batch_id!r}.",
        )

    tracking_ref = row.get("tracking_ref")
    label_download_url = None
    if tracking_ref and _label_file(batch_id, tracking_ref):
        label_download_url = f"/api/v1/carrier/{batch_id}/label/{tracking_ref}"
    commercial_documents_url = (
        f"/api/v1/carrier/{batch_id}/documents" if _doc_package_file(batch_id) else None
    )

    import json as _json
    dimensions = None
    if row.get("dimensions_json"):
        try:
            dimensions = _json.loads(row["dimensions_json"])
        except (TypeError, ValueError):
            dimensions = None

    return JSONResponse({
        "batch_id": row["batch_id"],
        "idempotency_key": row["idempotency_key"],
        "mode": row["mode"],
        "state": row["state"],
        "simulated": bool(row["simulated"]),
        "error": row["error"],
        # AWB logistics/document visibility (all additive)
        "tracking_ref": tracking_ref,
        "carrier": "DHL",
        "service_code": row.get("service_product"),
        "box_type_code": row.get("box_type_code"),
        "weight_kg": row.get("weight_kg"),
        "dimensions": dimensions,
        "declared_value": row.get("declared_value"),
        "currency": row.get("currency"),
        "created_at": row.get("created_at"),
        "label_download_url": label_download_url,
        "commercial_documents_url": commercial_documents_url,
        "documents_available": commercial_documents_url is not None,
        "saved_labels_exist": _batch_has_any_label(batch_id),
    })


# ── Path-DOC: label package ────────────────────────────────────────────────────


class LabelPackageBody(BaseModel):
    """Request body for POST /api/v1/carrier/{batch_id}/label-package.

    Dimensions and tare weight are resolved from the box_types master table
    by box_type_id (operator selects a pre-defined box at label time).
    Total package weight = sum(packing_lines.gross_weight) + box.tare_weight_kg.
    """
    box_type_id:   int               # required; resolved to dims + tare from box_types
    incoterm:      Optional[str]  = None
    receiver_eori: Optional[str]  = None
    client_name:   Optional[str]  = None


@router.post(
    "/{batch_id}/label-package",
    summary="Path-DOC: generate outbound customs/shipping document package (WF4.5)",
    description=(
        "UNGATED — no carrier_api_status / creds / allowlist check. "
        "Returns a PDF or ZIP containing: commercial invoice (from wFirma, read-only) "
        "+ packing list (generated) + CN23 (generated, non-EU only). "
        "Mandatory: box_type_id (resolved to dims+tare from box_types master). "
        "Non-EU also requires incoterm + receiver_eori. "
        "Receiver address: ship_to_* primary; bill_to_* fallback + advisory. "
        "Soft gaps (blank address, zero weight) are returned as advisories "
        "and do NOT block generation. "
        "422 {gaps:[...]} when mandatory inputs are missing."
    ),
)
async def create_label_package(
    batch_id: str,
    body: LabelPackageBody,
    _auth: None = Depends(require_api_key),
) -> Response:
    """Generate the Path-DOC outbound document package for a batch."""
    try:
        from ..services.carrier.doc_package import (
            LabelPackageInputs,
            LabelPackageGaps,
            LabelPackageResult,
            assemble_label_package,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": f"doc_package unavailable: {exc}", "code": "DOC_PKG_MISSING"},
        ) from exc

    from ..core.config import settings as _settings

    # Resolve box type → dimensions + tare
    try:
        from ..services.master_data_db import get_box_type, init_db as _init_md
        md_db = _settings.storage_root / "master_data.sqlite"
        _init_md(md_db)
        box = get_box_type(md_db, body.box_type_id)
    except Exception as _box_exc:
        box = None

    if box is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Missing mandatory inputs for label package",
                "code":  "LABEL_PACKAGE_GAPS",
                "gaps":  [{"field": "box_type",
                            "reason": (
                                f"box_type_id={body.box_type_id!r} not found in box_types master "
                                "or box_types table is empty. "
                                "Add box types via the master-data API before generating labels."
                            )}],
            },
        )

    inputs = LabelPackageInputs(
        length_cm      = float(box.length_cm or 0),
        width_cm       = float(box.width_cm  or 0),
        height_cm      = float(box.height_cm or 0),
        tare_weight_kg = float(box.tare_weight_kg or 0),
        incoterm       = (body.incoterm or "").strip() or None,
        receiver_eori  = (body.receiver_eori or "").strip() or None,
        client_name    = (body.client_name or "").strip() or None,
    )

    result = assemble_label_package(
        batch_id     = batch_id,
        inputs       = inputs,
        storage_root = _settings.storage_root,
    )

    if isinstance(result, LabelPackageGaps):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Missing mandatory inputs for label package",
                "code":  "LABEL_PACKAGE_GAPS",
                "gaps":  result.gaps,
            },
        )

    # LabelPackageResult
    headers = {"Content-Disposition": f'attachment; filename="{result.filename}"'}
    if result.advisories:
        # Surface advisories in a custom header (JSON-encoded list)
        import json as _json
        headers["X-Label-Advisories"] = _json.dumps(result.advisories)
    return Response(
        content      = result.content,
        media_type   = result.content_type,
        headers      = headers,
    )


# ── Label / document downloads ───────────────────────────────────────────────


@router.get(
    "/{batch_id}/label/{tracking_ref}",
    summary="Download the saved DHL label PDF for a batch AWB",
)
def download_label(
    batch_id: str,
    tracking_ref: str,
    _auth: None = Depends(require_api_key),
) -> Response:
    """Serve the label PDF saved at AWB creation time.

    Inputs are pattern-validated and path-confined to the labels directory;
    filesystem paths are never exposed. 404 when no label exists.
    """
    label = _label_file(batch_id, tracking_ref)
    if label is None:
        raise HTTPException(
            status_code=404,
            detail=f"No saved label for batch {batch_id!r} AWB {tracking_ref!r}.",
        )
    return Response(
        content=label.read_bytes(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="AWB-{tracking_ref}.pdf"',
            **_NO_STORE_HEADERS,
        },
    )


@router.get(
    "/{batch_id}/documents",
    summary="Download the saved commercial-document package for a batch",
)
def download_commercial_documents(
    batch_id: str,
    _auth: None = Depends(require_api_key),
) -> Response:
    """Serve the saved commercial-document package (invoice + packing list +
    CN23) when one has been persisted. 404 when none exists — Path-DOC
    packages generated via POST /label-package are streamed, not saved."""
    pkg = _doc_package_file(batch_id)
    if pkg is None:
        raise HTTPException(
            status_code=404,
            detail=f"No saved commercial-document package for batch {batch_id!r}.",
        )
    media = "application/zip" if pkg.suffix == ".zip" else "application/pdf"
    return Response(
        content=pkg.read_bytes(),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="DOCS-{batch_id}{pkg.suffix}"',
            **_NO_STORE_HEADERS,
        },
    )
