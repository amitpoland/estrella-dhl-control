"""
routes_wfirma_reservation.py — wFirma reservation preview + live create.

Endpoints
---------
  GET  /api/v1/wfirma/reservation-preview/{batch_id}
       Reservation readiness preview (persists local drafts/lines for Create).

  GET  /api/v1/wfirma/reservations/dry-run
       Pure dry-run payload for one (batch_id, client_name). Zero wFirma HTTP.
       Zero local draft persist.

  POST /api/v1/wfirma/reservations/create
       Create one wFirma reservation for one (batch_id, client_name).
       Hard-gated by check_wfirma_config criteria + per-draft state.
       Success-reconcile idempotent when already created.

  POST /api/v1/wfirma/reservations/{draft_id}/reset-stuck
       Force a draft stuck in status='submitting' back to 'failed'.
       Allowed only after a 30-minute timeout, or with explicit force=true.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.security import require_api_key
from ..auth.dependencies import require_permission
from ..services import wfirma_reservation as wr
from ..services import wfirma_reservation_create as wrc
from ..services import reservation_customer_parity as rcp

router = APIRouter(prefix="/api/v1/wfirma", tags=["wfirma"])
_auth  = Depends(require_api_key)
_perm_res = Depends(require_permission("wfirma.reservation.create"))


@router.get("/reservation-parity", dependencies=[_auth])
def reservation_parity(batch_id: str = Query(None, description="optional: limit to one batch")) -> dict:
    """WF-3 Slice 2B-1 — READ-ONLY reservation customer-resolution parity report."""
    return rcp.run_reservation_parity(batch_id=batch_id)


@router.get("/reservation-preview/{batch_id:path}", dependencies=[_auth])
def reservation_preview(batch_id: str) -> JSONResponse:
    """Build reservation preview for *batch_id* (persists local drafts/lines)."""
    result = wr.get_reservation_preview(batch_id)
    return JSONResponse(result)


@router.get("/reservations/dry-run", dependencies=[_auth])
def reservation_dry_run(
    batch_id: str = Query(..., description="shipment batch id"),
    client_name: str = Query(..., description="exact client_name"),
) -> JSONResponse:
    """Pure dry-run: commercial payload + XML. Zero wFirma HTTP. Zero persist."""
    result = wr.dry_run_reservation(batch_id, client_name)
    status = 200 if result.get("ok") else 404
    return JSONResponse(result, status_code=status)


class CreateReservationRequest(BaseModel):
    batch_id:    str
    client_name: str


_GATE_CODES_409 = frozenset({
    wrc.GATE_NOT_READY,
    wrc.GATE_DIAGNOSTIC_FAILED,
    wrc.GATE_DRAFT_NOT_FOUND,
    wrc.GATE_DRAFT_NOT_READY,
    wrc.GATE_DRAFT_ALREADY_PROCESSED,
    wrc.GATE_DRAFT_ALREADY_SUBMITTING,
    wrc.GATE_NO_LINES,
    wrc.GATE_CUSTOMER_NOT_MAPPED,
    wrc.GATE_PRODUCTS_NOT_MAPPED,
    wrc.GATE_STOCK_INSUFFICIENT,
    wrc.GATE_WAREHOUSE_NOT_FOUND,
    wrc.GATE_VAT_CODE_NOT_FOUND,
    wrc.SUBMIT_RACE_LOST,
})


@router.post("/reservations/create", dependencies=[_auth, _perm_res])
def create_reservation(req: CreateReservationRequest) -> JSONResponse:
    """
    Create ONE wFirma reservation for the (batch_id, client_name) pair.

    Status codes:
      200 — reservation created OR reconciled existing id
      409 — pre-flight gate failed
      502 — upstream wFirma error
    """
    result = wrc.create_one_reservation(req.batch_id, req.client_name)
    if result["ok"]:
        return JSONResponse(result, status_code=200)

    if result["code"] == wrc.SUBMIT_UPSTREAM_ERROR:
        return JSONResponse(result, status_code=502)
    if result["code"] in _GATE_CODES_409:
        return JSONResponse(result, status_code=409)
    return JSONResponse(result, status_code=500)


@router.post("/reservations/{draft_id}/reset-stuck", dependencies=[_auth, _perm_res])
def reset_stuck_reservation(
    draft_id: str,
    force:    bool = Query(False, description="Override the 30-min timeout"),
) -> JSONResponse:
    """Force a draft stuck in status='submitting' back to 'failed'."""
    result = wrc.reset_stuck_draft(draft_id, force=force)
    if result["ok"]:
        return JSONResponse(result, status_code=200)
    if result["code"] == wrc.GATE_DRAFT_NOT_FOUND:
        return JSONResponse(result, status_code=404)
    return JSONResponse(result, status_code=409)
