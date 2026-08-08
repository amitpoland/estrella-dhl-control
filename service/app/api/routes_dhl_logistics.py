"""
routes_dhl_logistics.py — Read-only DHL Logistics Control Tower endpoints.

Endpoints:
  GET /api/v1/dhl/logistics/projection          — filtered logistics rows + KPIs
  GET /api/v1/dhl/logistics/shipments/{awb}     — one shipment detail + timeline
  GET /api/v1/dhl/logistics/export/csv          — filtered CSV export

Pure projection over existing authorities. No writes. No second tracker.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from ..core.security import require_api_key
from ..services import dhl_logistics_projector as projector

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/dhl/logistics", tags=["dhl-logistics"])
_auth = Depends(require_api_key)

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


@router.get("/projection", dependencies=[_auth])
def get_logistics_projection(
    direction: str = Query("all", pattern="^(all|inbound|outbound)$"),
    view: str = Query("active", pattern="^(active|delivered|attention|all)$"),
    q: Optional[str] = Query(None, max_length=120),
    stage: Optional[str] = Query(None, max_length=80),
    needs_attention_only: bool = Query(False),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> JSONResponse:
    """Read-only logistics Control Tower projection."""
    payload: Dict[str, Any] = projector.project_logistics(
        direction=direction,
        view=view,
        q=q,
        stage=stage,
        needs_attention_only=needs_attention_only,
        date_from=date_from,
        date_to=date_to,
    )
    return JSONResponse(content=payload, headers=_NO_STORE_HEADERS)


@router.get("/shipments/{awb}", dependencies=[_auth])
def get_logistics_shipment(awb: str) -> JSONResponse:
    """Read-only detail for one AWB (inbound or outbound)."""
    row = projector.project_shipment_detail(awb)
    if row is None:
        raise HTTPException(status_code=404, detail="Shipment not found in logistics projection")
    return JSONResponse(content=row, headers=_NO_STORE_HEADERS)


@router.get("/export/csv", dependencies=[_auth])
def export_logistics_csv(
    direction: str = Query("all", pattern="^(all|inbound|outbound)$"),
    view: str = Query("active", pattern="^(active|delivered|attention|all)$"),
    q: Optional[str] = Query(None, max_length=120),
    stage: Optional[str] = Query(None, max_length=80),
    needs_attention_only: bool = Query(False),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> Response:
    """Injection-safe CSV of the filtered logistics projection."""
    payload = projector.project_logistics(
        direction=direction,
        view=view,
        q=q,
        stage=stage,
        needs_attention_only=needs_attention_only,
        date_from=date_from,
        date_to=date_to,
    )
    body = projector.rows_to_logistics_csv(payload.get("rows") or [])
    fname = f"dhl_logistics_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return Response(
        content=body,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            **_NO_STORE_HEADERS,
        },
    )
