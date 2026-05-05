"""
routes_batch_readiness.py — Aggregated batch readiness endpoint.

Endpoints
---------
  GET  /api/v1/batch/{batch_id}/readiness
       Read-only aggregated readiness across warehouse, sales, wFirma, and DHL.
       No writes. No side effects.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..core.security import require_api_key
from ..services import batch_readiness as br

router = APIRouter(prefix="/api/v1/batch", tags=["batch-readiness"])
_auth  = Depends(require_api_key)


@router.get("/{batch_id}/readiness", dependencies=[_auth])
def batch_readiness(batch_id: str) -> JSONResponse:
    """
    Return aggregated readiness state across all four domains for *batch_id*.

    Reads:
    - warehouse audit (packing completion vs scan coverage)
    - sales linkage (invoice linkage quality)
    - wFirma draft state (reservation configured / created / blocked)
    - DHL customs pipeline (audit.json timeline + tracking_db)

    All reads are wrapped in safe fallbacks — one unavailable domain does not
    crash the endpoint.  Unavailable domains return status ``n/a``.

    This endpoint is **read-only** — it never writes to any database,
    never sends email, and never triggers side effects.
    """
    result = br.get_batch_readiness(batch_id)
    return JSONResponse(result)
