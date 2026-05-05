"""
routes_wfirma_reservation.py — wFirma reservation preview + live create.

Endpoints
---------
  GET  /api/v1/wfirma/reservation-preview/{batch_id}
       Grouped reservation preview per sales document (client), ready for
       submission to wFirma once all conditions are met.

  POST /api/v1/wfirma/reservations/create
       Create one wFirma reservation for one (batch_id, client_name).
       Hard-gated by check_wfirma_config criteria + per-draft state.

  POST /api/v1/wfirma/reservations/{draft_id}/reset-stuck
       Force a draft stuck in status='submitting' back to 'failed'.
       Allowed only after a 30-minute timeout, or with explicit force=true.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.security import require_api_key
from ..services import wfirma_reservation as wr
from ..services import wfirma_reservation_create as wrc

router = APIRouter(prefix="/api/v1/wfirma", tags=["wfirma"])
_auth  = Depends(require_api_key)


@router.get("/reservation-preview/{batch_id:path}", dependencies=[_auth])
def reservation_preview(batch_id: str) -> JSONResponse:
    """
    Build a wFirma reservation preview for *batch_id*.

    Groups sales packing lines by client (sales_document) and invoice
    product_code.  Returns readiness state, stock check, and per-row
    unit prices from invoice_lines.

    ready_to_create = True only when:
      - warehouse audit is clean (no missing_scans, invalid_flows, orphans)
      - all rows have stock confirmed in warehouse
      - all clients have a non-empty customer name
    """
    result = wr.get_reservation_preview(batch_id)
    return JSONResponse(result)


# ── Live create (Phase 3.A — single client, gate-protected) ──────────────────

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


@router.post("/reservations/create", dependencies=[_auth])
def create_reservation(req: CreateReservationRequest) -> JSONResponse:
    """
    Create ONE wFirma reservation for the (batch_id, client_name) pair.

    Status codes:
      200 — reservation created; body contains wfirma_reservation_id
      409 — pre-flight gate failed; body.code identifies which gate
      502 — upstream wFirma returned an error; body.error has details
    """
    result = wrc.create_one_reservation(req.batch_id, req.client_name)
    if result["ok"]:
        return JSONResponse(result, status_code=200)

    if result["code"] == wrc.SUBMIT_UPSTREAM_ERROR:
        return JSONResponse(result, status_code=502)
    if result["code"] in _GATE_CODES_409:
        return JSONResponse(result, status_code=409)
    # Unknown failure — treat as server error so it shows up in monitoring
    return JSONResponse(result, status_code=500)


@router.post("/reservations/{draft_id}/reset-stuck", dependencies=[_auth])
def reset_stuck_reservation(
    draft_id: str,
    force:    bool = Query(False, description="Override the 30-min timeout"),
) -> JSONResponse:
    """
    Force a draft stuck in status='submitting' back to 'failed'.
    Use only when you have confirmed no submission is actually in flight.
    """
    result = wrc.reset_stuck_draft(draft_id, force=force)
    if result["ok"]:
        return JSONResponse(result, status_code=200)
    if result["code"] == wrc.GATE_DRAFT_NOT_FOUND:
        return JSONResponse(result, status_code=404)
    return JSONResponse(result, status_code=409)
