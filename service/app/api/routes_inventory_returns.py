"""Returns write routes — Phase B.2.

  POST /api/v1/inventory/pieces/{piece_id}/return-from-client
       — Inbound: WAREHOUSE_STOCK | SAMPLE_OUT → RETURNED_FROM_CLIENT.

  POST /api/v1/inventory/pieces/{piece_id}/return-to-producer
       — Outbound: WAREHOUSE_STOCK | RETURNED_FROM_CLIENT
                   → RETURNED_TO_PRODUCER.

  POST /api/v1/inventory/pieces/{piece_id}/return-from-producer
       — Restock: RETURNED_TO_PRODUCER → WAREHOUSE_STOCK.

All endpoints require X-API-Key (router-level Depends(require_api_key))
and a caller-supplied `idempotency_key`. Replay returns the prior
event_id (same scan_code + idempotency_key).

Single-writer discipline preserved: this router never UPDATEs
inventory_state directly. All state changes via transition().
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.security import require_api_key
from ..services.inventory_returns_writer import (
    ReturnsError,
    mark_returned_from_client,
    mark_returned_to_producer,
    return_from_producer_to_stock,
)


router = APIRouter(
    prefix="/api/v1/inventory",
    tags=["inventory-returns"],
    dependencies=[Depends(require_api_key)],
)


class ReturnFromClientRequest(BaseModel):
    operator:           str = Field(..., min_length=1)
    return_reason:      str = Field(
        ..., min_length=1,
        description=(
            "Reason enum: warranty_claim, customer_refused, "
            "post_sample_review_reject, dimension_issue, "
            "quality_complaint, wrong_item_shipped, other"
        ),
    )
    origin_context:     str = Field(
        ..., min_length=1,
        description=(
            "Free-text origin pointer (RMA #, sales doc, sample event "
            "id, etc.). Required so the audit row is never anonymous."
        ),
    )
    received_at:        str = Field(
        ..., min_length=1,
        description="ISO 8601 timestamp; must not be in the future",
    )
    idempotency_key:    str = Field(..., min_length=1)
    source_holder_name: Optional[str] = Field(default="")
    notes:              Optional[str] = Field(default="")


class ReturnToProducerRequest(BaseModel):
    operator:                 str = Field(..., min_length=1)
    producer_name:            str = Field(..., min_length=1)
    idempotency_key:          str = Field(..., min_length=1)
    return_reason:            Optional[str] = Field(
        default="",
        description=(
            "Reason enum (one of defect, dimension_out_of_spec, "
            "quality_reject, post_inspection_reject, recall, other). "
            "Either reason or dispatch_reference must be supplied."
        ),
    )
    dispatch_reference:       Optional[str] = Field(
        default="",
        description="Outbound waybill / RMA ref",
    )
    producer_id:              Optional[str] = Field(default="")
    expected_resolution_date: Optional[str] = Field(
        default="",
        description="ISO 8601 date; if given, must be in the future",
    )
    notes:                    Optional[str] = Field(default="")


class ReturnFromProducerRequest(BaseModel):
    operator:        str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)
    notes:           Optional[str] = Field(default="")


_STATUS_FOR_CODE = {
    "INVALID_INPUT":     400,
    "PIECE_NOT_FOUND":   404,
    "WRONG_STATE":       409,
    "MIGRATION_PENDING": 503,
    "DB_UNAVAILABLE":    503,
    "DB_CONSTRAINT":     500,
}


def _map_returns_error(e: ReturnsError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR_CODE.get(e.code, 500),
        detail={"code": e.code, "detail": e.detail},
    )


@router.post("/pieces/{piece_id}/return-from-client")
def post_return_from_client(
    piece_id: str, payload: ReturnFromClientRequest,
) -> dict:
    """Mark a piece as returned from a client into RMA.

    Errors:
      400 INVALID_INPUT, INVALID_EVIDENCE
      404 PIECE_NOT_FOUND
      409 WRONG_STATE
      503 DB_UNAVAILABLE, MIGRATION_PENDING
    """
    try:
        return mark_returned_from_client(
            scan_code=piece_id,
            operator=payload.operator,
            return_reason=payload.return_reason,
            origin_context=payload.origin_context,
            received_at=payload.received_at,
            idempotency_key=payload.idempotency_key,
            source_holder_name=payload.source_holder_name or "",
            notes=payload.notes or "",
        )
    except ReturnsError as e:
        raise _map_returns_error(e)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_EVIDENCE", "detail": str(e)},
        )


@router.post("/pieces/{piece_id}/return-to-producer")
def post_return_to_producer(
    piece_id: str, payload: ReturnToProducerRequest,
) -> dict:
    """Mark a piece as shipped back to the producer.

    Errors:
      400 INVALID_INPUT, INVALID_EVIDENCE
      404 PIECE_NOT_FOUND
      409 WRONG_STATE
      503 DB_UNAVAILABLE, MIGRATION_PENDING
    """
    try:
        return mark_returned_to_producer(
            scan_code=piece_id,
            operator=payload.operator,
            producer_name=payload.producer_name,
            idempotency_key=payload.idempotency_key,
            return_reason=payload.return_reason or "",
            dispatch_reference=payload.dispatch_reference or "",
            producer_id=payload.producer_id or "",
            expected_resolution_date=payload.expected_resolution_date or "",
            notes=payload.notes or "",
        )
    except ReturnsError as e:
        raise _map_returns_error(e)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_EVIDENCE", "detail": str(e)},
        )


@router.post("/pieces/{piece_id}/return-from-producer")
def post_return_from_producer(
    piece_id: str, payload: ReturnFromProducerRequest,
) -> dict:
    """Mark a producer-shipped piece as back in warehouse stock.

    Errors:
      400 INVALID_INPUT
      404 PIECE_NOT_FOUND
      409 WRONG_STATE
      503 DB_UNAVAILABLE, MIGRATION_PENDING
    """
    try:
        return return_from_producer_to_stock(
            scan_code=piece_id,
            operator=payload.operator,
            idempotency_key=payload.idempotency_key,
            notes=payload.notes or "",
        )
    except ReturnsError as e:
        raise _map_returns_error(e)
