"""Sample-out write routes — Phase B.1.

  POST /api/v1/inventory/pieces/{piece_id}/sample-out
       — Move a piece WAREHOUSE_STOCK → SAMPLE_OUT. Routes through
         inventory_state_engine.transition() with evidence gate.

  POST /api/v1/inventory/pieces/{piece_id}/sample-return
       — Move a piece SAMPLE_OUT → WAREHOUSE_STOCK. Routes through
         inventory_state_engine.transition().

Both endpoints require X-API-Key (router-level Depends(require_api_key))
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
from ..services.inventory_sample_writer import (
    SampleOutError,
    sample_out,
    sample_return,
)


router = APIRouter(
    prefix="/api/v1/inventory",
    tags=["inventory-sample"],
    dependencies=[Depends(require_api_key)],
)


class SampleOutRequest(BaseModel):
    operator: str = Field(..., min_length=1, description="Operator user id")
    recipient_client_name: str = Field(
        ..., min_length=1,
        description="Recipient client name (display + lookup key)",
    )
    recipient_client_id: Optional[str] = Field(
        default="", description="Client id if known in master data",
    )
    expected_return_date: str = Field(
        ..., min_length=1,
        description="ISO 8601 date; must be in the future",
    )
    sample_reason: str = Field(
        ..., min_length=1,
        description=(
            "Reason enum: customer_review, quality_check, marketing_photo, "
            "trade_show, other"
        ),
    )
    idempotency_key: str = Field(
        ..., min_length=1,
        description="Caller-supplied dedupe key; replays return prior result",
    )
    notes: Optional[str] = Field(default="", description="Free-text note")


class SampleReturnRequest(BaseModel):
    operator: str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)
    notes: Optional[str] = Field(default="", description="Free-text note")


_STATUS_FOR_CODE = {
    "INVALID_INPUT":           400,
    "PIECE_NOT_FOUND":         404,
    "WRONG_STATE":             409,
    "RECIPIENT_OVERDUE_BLOCK": 409,
    "NO_OPEN_SAMPLE_OUT":      409,
    "MIGRATION_PENDING":       503,
    "DB_UNAVAILABLE":          503,
}


def _map_sample_error(e: SampleOutError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR_CODE.get(e.code, 500),
        detail={"code": e.code, "detail": e.detail},
    )


@router.post("/pieces/{piece_id}/sample-out")
def post_sample_out(piece_id: str, payload: SampleOutRequest) -> dict:
    """Mark a piece as sampled out to a client.

    Errors:
      400 INVALID_INPUT, INVALID_EVIDENCE
      404 PIECE_NOT_FOUND
      409 WRONG_STATE
      409 RECIPIENT_OVERDUE_BLOCK
      503 DB_UNAVAILABLE, MIGRATION_PENDING
    """
    try:
        return sample_out(
            scan_code=piece_id,
            operator=payload.operator,
            recipient_client_name=payload.recipient_client_name,
            recipient_client_id=payload.recipient_client_id or "",
            expected_return_date=payload.expected_return_date,
            sample_reason=payload.sample_reason,
            idempotency_key=payload.idempotency_key,
            notes=payload.notes or "",
        )
    except SampleOutError as e:
        raise _map_sample_error(e)
    except ValueError as e:
        # Engine-level evidence rejection (missing recipient, bad reason,
        # past expected_return_date). Surfaced as 400 INVALID_EVIDENCE
        # so the operator UI can show the specific gap.
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_EVIDENCE", "detail": str(e)},
        )


@router.post("/pieces/{piece_id}/sample-return")
def post_sample_return(piece_id: str, payload: SampleReturnRequest) -> dict:
    """Mark a sampled-out piece as returned to warehouse stock.

    Errors:
      400 INVALID_INPUT
      404 PIECE_NOT_FOUND
      409 WRONG_STATE
      409 NO_OPEN_SAMPLE_OUT
      503 DB_UNAVAILABLE, MIGRATION_PENDING
    """
    try:
        return sample_return(
            scan_code=piece_id,
            operator=payload.operator,
            idempotency_key=payload.idempotency_key,
            notes=payload.notes or "",
        )
    except SampleOutError as e:
        raise _map_sample_error(e)


# ── C-3b: sample register read (Phase-C Wave 2 — backend only) ───────────────

@router.get("/samples")
def list_samples(
    status: Optional[str] = None,
    recipient: Optional[str] = None,
    limit: int = 500,
) -> dict:
    """List sample records: one per sample-out event, paired with its return
    event when present. Read-only — never mutates inventory_state, never
    calls wFirma. Backs the Sample Out / Sample Return wireframe tabs
    (UI wiring is Wave 3 / U-1).

    Query params:
      status    — 'open' | 'returned' (omit for all)
      recipient — case-insensitive substring on recipient_client_name
      limit     — max out-events scanned (1..2000, default 500)

    Errors:
      400 INVALID_INPUT (bad status value)
      503 DB_UNAVAILABLE, MIGRATION_PENDING
    """
    from ..services import warehouse_db as wdb
    if wdb._db_path is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "DB_UNAVAILABLE", "detail": "warehouse_db not initialised"},
        )
    if not wdb.ensure_sample_out_schema():
        raise HTTPException(
            status_code=503,
            detail={"code": "MIGRATION_PENDING",
                    "detail": "sample_out_events migration not applied"},
        )
    st = (status or "").strip().lower() or None
    if st not in (None, "open", "returned"):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_INPUT",
                    "detail": "status must be 'open' or 'returned'"},
        )
    records = wdb.list_sample_records(
        status=st, recipient_client_name=recipient, limit=limit,
    )
    return {"ok": True, "count": len(records), "samples": records}
