"""
Inventory read-only routes.

Currently exposes:
  GET /api/v1/inventory/stage2/aggregate — 5-bucket Stage 2 summary.

NO POST/PUT/PATCH/DELETE. Future write paths must be added in
separate router files with explicit SECURITY review.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core.security import require_api_key
from ..services.inventory_batch_state import get_batch_state
from ..services.inventory_piece_view import get_piece_detail
from ..services.inventory_stage2_aggregator import aggregate_stage2


router = APIRouter(
    prefix="/api/v1/inventory",
    tags=["inventory"],
    dependencies=[Depends(require_api_key)],
)


def _validate_as_of(as_of: Optional[str]) -> Optional[str]:
    if as_of is None:
        return None
    try:
        # Accept ISO 8601; handle the "Z" UTC suffix that
        # datetime.fromisoformat() supports only on Python 3.11+.
        normalized = as_of.replace("Z", "+00:00") if as_of.endswith("Z") else as_of
        datetime.fromisoformat(normalized)
        return as_of  # echo verbatim
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid as_of timestamp: {as_of!r} — expected ISO 8601",
        )


@router.get("/stage2/aggregate")
def get_stage2_aggregate(
    as_of: Optional[str] = Query(
        None,
        description="Optional ISO 8601 timestamp. Echoed verbatim. "
                    "If omitted, server uses current UTC time.",
    ),
) -> dict:
    """Read-only Stage 2 aggregation. GET only."""
    validated = _validate_as_of(as_of)
    return aggregate_stage2(as_of=validated)


@router.get("/pieces/{piece_id}")
def get_inventory_piece_detail(
    piece_id: str,
    as_of: Optional[str] = Query(
        None,
        description="Optional ISO 8601 timestamp. Echoed verbatim. "
                    "If omitted, server uses current UTC time.",
    ),
) -> dict:
    """Read-only per-piece inventory detail. Returns state row + history.

    Honest empty: unknown piece_id yields found=False (HTTP 200, not 404).
    """
    validated = _validate_as_of(as_of)
    return get_piece_detail(piece_id, as_of=validated)


@router.get("/state/{batch_id}")
def get_inventory_state_for_batch(
    batch_id: str,
    as_of: Optional[str] = Query(
        None,
        description="Optional ISO 8601 timestamp. Echoed verbatim. "
                    "If omitted, server uses current UTC time.",
    ),
) -> dict:
    """Read-only per-batch inventory state. Returns counts + per-piece list.

    Honest empty: an unknown batch_id yields zero counts and an empty
    pieces list (HTTP 200, not 404). Callers distinguish via `total`.
    """
    validated = _validate_as_of(as_of)
    return get_batch_state(batch_id, as_of=validated)


# ── BE-2: Stock Promotion Notes (PROJECT_STATE DECISIONS "BE-2 Stock
# Promotion Note", 2026-07-02). Read-only — the Notes are WRITTEN solely by
# run_stock_promotion() via stock_promotion_note_db. GET only, per this
# file's contract.

@router.get("/promotion-notes/{batch_id}")
def list_promotion_notes(batch_id: str) -> dict:
    """Note headers for a batch, newest first.

    Honest empty: unknown batch_id yields an empty list (HTTP 200).
    """
    from ..services.stock_promotion_note_db import list_notes
    notes = list_notes(batch_id)
    return {"batch_id": batch_id, "total": len(notes), "notes": notes}


@router.get("/promotion-note/{note_no:path}")
def get_promotion_note(note_no: str) -> dict:
    """One Note, header + lines. note_no contains slashes (SPN/NNN/YYYY) —
    the :path converter follows the routes_warehouse location_code:path
    precedent. Unknown note_no → 404 NOTE_NOT_FOUND.
    """
    from ..services.stock_promotion_note_db import get_note
    note = get_note(note_no)
    if note is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOTE_NOT_FOUND",
                    "detail": f"promotion note {note_no!r} not found"},
        )
    return note
