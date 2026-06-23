"""
Carrier action routes — shipment creation, state retrieval, and Path-DOC package.

POST /api/v1/carrier/{batch_id}/shipment
    Creates a shipment via CarrierCoordinator.
    503 if carrier_api_status == "pending".
    Returns: batch_id, idempotency_key, mode, state, tracking_ref, simulated.

GET /api/v1/carrier/{batch_id}/shipment
    Returns most-recent recorded shipment for the batch.
    503 if carrier_api_status == "pending".
    Returns: batch_id, idempotency_key, mode, state, simulated, error.
    Note: tracking_ref is never returned — structural DB invariant (column absent).

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


# ── Request body ──────────────────────────────────────────────────────────────


class ShipmentRequestBody(BaseModel):
    shipper_account: Optional[str] = None  # falls back to DHL_EXPRESS_ACCOUNT_NUMBER setting
    recipient_address: dict
    declared_value: float
    currency: str
    weight_kg: float
    dimensions: dict
    special_instructions: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────


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
    )
    try:
        result = coordinator.create_shipment(request)
    except CarrierGateError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return JSONResponse({
        "batch_id": batch_id,
        "idempotency_key": result.idempotency_key,
        "mode": result.mode.value,
        "state": result.state.value,
        "tracking_ref": result.tracking_ref,
        "simulated": result.simulated,
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
    return JSONResponse({
        "batch_id": row["batch_id"],
        "idempotency_key": row["idempotency_key"],
        "mode": row["mode"],
        "state": row["state"],
        "simulated": bool(row["simulated"]),
        "error": row["error"],
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
