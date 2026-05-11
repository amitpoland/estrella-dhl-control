"""
Carrier action routes — shipment creation and state retrieval.

POST /api/v1/carrier/{batch_id}/shipment
    Creates a shipment via CarrierCoordinator.
    503 if carrier_api_status == "pending".
    Returns: batch_id, idempotency_key, mode, state, tracking_ref, simulated.

GET /api/v1/carrier/{batch_id}/shipment
    Returns most-recent recorded shipment for the batch.
    503 if carrier_api_status == "pending".
    Returns: batch_id, idempotency_key, mode, state, simulated, error.
    Note: tracking_ref is never returned — structural DB invariant (column absent).

Auth: X-API-Key header via require_api_key (same pattern as routes_pz.py).
No live DHL calls in shadow mode.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
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
    shipper_account: str
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
    request = ShipmentRequest(
        batch_id=batch_id,
        shipper_account=body.shipper_account,
        recipient_address=body.recipient_address,
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
