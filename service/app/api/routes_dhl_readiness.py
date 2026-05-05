"""
routes_dhl_readiness.py — DHL customs pipeline readiness endpoint.

Endpoints
---------
  GET  /api/v1/dhl/readiness/{batch_id}
       Read-only reconstruction of the DHL clearance pipeline state from
       the existing audit trail.  No writes, no side effects.

All other methods on this path return 405 Method Not Allowed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..core.security import require_api_key
from ..services import dhl_readiness as dr

router = APIRouter(prefix="/api/v1/dhl", tags=["dhl-readiness"])
_auth  = Depends(require_api_key)


@router.get("/readiness/{batch_id:path}", dependencies=[_auth])
def dhl_readiness(batch_id: str) -> JSONResponse:
    """
    Reconstruct the DHL customs clearance pipeline state for *batch_id*.

    Reads the per-batch ``audit.json`` timeline and the tracking-events DB.
    Returns a structured readiness object that covers:
    - 7-stage pipeline status (awaiting_start → customs_cleared)
    - AWB and carrier extracted from the audit trail
    - Timestamps for each pipeline milestone
    - SLA breach detection (no response within 3 days of last outbound)
    - Missing document list and next required action

    This endpoint is **read-only** — it never writes, never sends email,
    and never triggers any side effects.
    """
    result = dr.get_dhl_readiness(batch_id)
    return JSONResponse(result)
