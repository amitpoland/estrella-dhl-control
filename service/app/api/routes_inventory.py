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
