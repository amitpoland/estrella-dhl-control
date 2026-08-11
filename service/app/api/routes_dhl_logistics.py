"""
routes_dhl_logistics.py — DHL Logistics Control Tower endpoints.

Read projection (API key or session):
  GET /api/v1/dhl/logistics/projection
  GET /api/v1/dhl/logistics/shipments/{awb}
  GET /api/v1/dhl/logistics/export/csv

Admin reporting-resolution writes (session admin only — never rewrite tracking):
  POST /api/v1/dhl/logistics/shipments/{awb}/resolve
  POST /api/v1/dhl/logistics/shipments/{awb}/reopen
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from ..auth.dependencies import require_admin
from ..core.security import require_api_key
from ..services import dhl_logistics_projector as projector
from ..services import dhl_logistics_resolution_db as resdb
from ..services.dhl_logistics_intelligence_pdf import render_logistics_intelligence_pdf

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/dhl/logistics", tags=["dhl-logistics"])
_auth = Depends(require_api_key)

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

_VIEW_PATTERN = "^(active|delivered|attention|historical|resolved|resolved_history|all)$"


class ResolveBody(BaseModel):
    direction: Literal["inbound", "outbound"]
    resolution_status: Literal["historical_delivered", "closed_no_longer_operational"]
    comment: str = Field(..., min_length=1, max_length=2000)
    manual_delivered_at: Optional[str] = Field(None, max_length=64)
    manual_location: Optional[str] = Field(None, max_length=200)


class ReopenBody(BaseModel):
    direction: Literal["inbound", "outbound"]
    comment: str = Field(..., min_length=1, max_length=2000)


def _actor(user: dict) -> str:
    return (
        str(user.get("username") or user.get("email") or user.get("sub") or user.get("id") or "admin")
    )


@router.get("/projection", dependencies=[_auth])
def get_logistics_projection(
    direction: str = Query("all", pattern="^(all|inbound|outbound)$"),
    view: str = Query("active", pattern=_VIEW_PATTERN),
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
    view: str = Query("active", pattern=_VIEW_PATTERN),
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
    body = projector.rows_to_logistics_csv(
        payload.get("rows") or [],
        filters=payload.get("filters_applied"),
    )
    fname = f"dhl_logistics_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return Response(
        content=body,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            **_NO_STORE_HEADERS,
        },
    )


@router.get("/export/pdf", dependencies=[_auth])
def export_logistics_pdf(
    direction: str = Query("all", pattern="^(all|inbound|outbound)$"),
    view: str = Query("active", pattern=_VIEW_PATTERN),
    q: Optional[str] = Query(None, max_length=120),
    stage: Optional[str] = Query(None, max_length=80),
    needs_attention_only: bool = Query(False),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
) -> Response:
    """Estrella-branded Logistics Intelligence PDF (Lesson G no-store)."""
    payload = projector.project_logistics(
        direction=direction,
        view=view,
        q=q,
        stage=stage,
        needs_attention_only=needs_attention_only,
        date_from=date_from,
        date_to=date_to,
    )
    pdf_bytes = render_logistics_intelligence_pdf(payload)
    fname = f"logistics_intelligence_{datetime.now(timezone.utc).strftime('%Y%m%d')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            **_NO_STORE_HEADERS,
        },
    )


@router.post("/shipments/{awb}/resolve")
def resolve_logistics_shipment(
    awb: str,
    body: ResolveBody,
    user: dict = Depends(require_admin),
) -> JSONResponse:
    """Admin-only reporting resolution. Does not rewrite DHL/customs/PZ/carrier data."""
    awb = (awb or "").strip()
    if not awb:
        raise HTTPException(status_code=400, detail="awb required")
    row = projector.project_shipment_detail(awb)
    if row is None:
        raise HTTPException(status_code=404, detail="Shipment not found in logistics projection")
    if str(row.get("direction") or "") != body.direction:
        raise HTTPException(status_code=400, detail="direction does not match projection row")

    prev = {
        "classification": row.get("classification"),
        "transport_status": row.get("transport_status"),
        "customs_status": row.get("customs_status"),
        "needs_attention": row.get("needs_attention"),
        "created_at_utc": row.get("created_at_utc"),
    }
    try:
        saved = resdb.resolve(
            awb=awb,
            direction=body.direction,
            resolution_status=body.resolution_status,
            comment=body.comment,
            resolved_by=_actor(user),
            manual_delivered_at=body.manual_delivered_at,
            manual_location=body.manual_location,
            previous_projection=prev,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    refreshed = projector.project_shipment_detail(awb)
    return JSONResponse(
        content={"ok": True, "resolution": saved, "row": refreshed},
        headers=_NO_STORE_HEADERS,
    )


@router.post("/shipments/{awb}/reopen")
def reopen_logistics_shipment(
    awb: str,
    body: ReopenBody,
    user: dict = Depends(require_admin),
) -> JSONResponse:
    """Admin-only undo of a reporting resolution."""
    awb = (awb or "").strip()
    if not awb:
        raise HTTPException(status_code=400, detail="awb required")
    row = projector.project_shipment_detail(awb)
    if row is None:
        raise HTTPException(status_code=404, detail="Shipment not found in logistics projection")
    if str(row.get("direction") or "") != body.direction:
        raise HTTPException(status_code=400, detail="direction does not match projection row")

    prev = {
        "classification": row.get("classification"),
        "transport_status": row.get("transport_status"),
        "manual_resolution": row.get("manual_resolution"),
    }
    try:
        saved = resdb.reopen(
            awb=awb,
            direction=body.direction,
            comment=body.comment,
            resolved_by=_actor(user),
            previous_projection=prev,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="No active resolution to reopen") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    refreshed = projector.project_shipment_detail(awb)
    return JSONResponse(
        content={"ok": True, "resolution": saved, "row": refreshed},
        headers=_NO_STORE_HEADERS,
    )
