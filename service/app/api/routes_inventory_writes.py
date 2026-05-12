"""Inventory write routes — Phase 4.5.

Currently exposes:
  POST /api/v1/inventory/pieces/{piece_id}/location
       — Move a piece to a new physical location. Metadata-only write.
         Does NOT change inventory_state. Requires idempotency_key.

Per Doc 2 button registry: Execution route NOT required (no state
transition). Per Doc 1 v2: single-writer discipline preserved — this
endpoint never calls inventory_state_engine.transition().

Auth: require_api_key (hybrid guard from feat/hybrid-auth-prep when
merged; currently API key only on main).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.security import require_api_key
from ..services.inventory_location_writer import MoveStockError, move_piece


router = APIRouter(
    prefix="/api/v1/inventory",
    tags=["inventory-writes"],
    dependencies=[Depends(require_api_key)],
)


class MoveStockRequest(BaseModel):
    to_location: str = Field(..., min_length=1, description="Target location code")
    operator: str = Field(..., min_length=1, description="Operator name / id")
    idempotency_key: str = Field(
        ..., min_length=1,
        description="Caller-supplied dedupe key. Replays return prior result.",
    )
    note: Optional[str] = Field(default="", description="Free-text note")


@router.post("/pieces/{piece_id}/location")
def move_piece_location(piece_id: str, payload: MoveStockRequest) -> dict:
    """Move a piece to a new physical location.

    Idempotent: same idempotency_key + same target location returns the
    prior result without re-writing. Different target location with the
    same key is NOT a replay — it proceeds as a new move (and will
    create a new idempotency record).

    Errors:
      400 INVALID_INPUT
      404 PIECE_NOT_FOUND
      409 WRONG_STATE          (piece is not in WAREHOUSE_STOCK)
      503 DB_UNAVAILABLE       (warehouse_db not initialised)
      503 MIGRATION_PENDING    (idempotency_key column/index missing —
                                operator must run the draft migration)
    """
    try:
        return move_piece(
            scan_code=piece_id,
            to_location=payload.to_location,
            operator=payload.operator,
            idempotency_key=payload.idempotency_key,
            note=payload.note or "",
        )
    except MoveStockError as e:
        status_for = {
            "INVALID_INPUT":     400,
            "PIECE_NOT_FOUND":   404,
            "WRONG_STATE":       409,
            "MIGRATION_PENDING": 503,
            "DB_UNAVAILABLE":    503,
        }
        raise HTTPException(
            status_code=status_for.get(e.code, 500),
            detail={"code": e.code, "detail": e.detail},
        )
