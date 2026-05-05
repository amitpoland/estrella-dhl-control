"""
routes_sales.py — Sales linkage endpoint.

Endpoints
---------
  GET /api/v1/sales/linkage/{batch_id}
       Link sales packing lines to live warehouse scan state, with audit gate.

Query params
------------
  mode     : "preview" (default) | "final"
  override : bool (default False) — suppress blocking in final mode
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ..core.security import require_api_key
from ..services import sales_linkage as sl

router = APIRouter(prefix="/api/v1/sales", tags=["sales"])
_auth  = Depends(require_api_key)


@router.get("/linkage/{batch_id:path}", dependencies=[_auth])
def sales_linkage(
    batch_id: str,
    mode:     str  = Query("preview", pattern="^(preview|final)$"),
    override: bool = Query(False),
) -> JSONResponse:
    """
    Link sales packing lines to warehouse scan state for *batch_id*.

    - mode=preview  always returns data with warnings; never blocks
    - mode=final    blocks (returns blocked=True) if audit gate fails,
                    unless override=True
    """
    result = sl.get_sales_linkage(batch_id, mode=mode, override=override)
    status_code = 409 if result.get("blocked") else 200
    return JSONResponse(result, status_code=status_code)
