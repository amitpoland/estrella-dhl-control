"""
routes_dhl_followup_status.py — Read-only visibility endpoints for the
DHL follow-up automation status card + drill-down table.

Endpoints:
  GET /api/v1/dhl/followup-automation/status     — top card payload
  GET /api/v1/dhl/followup-automation/shipments  — drill-down rows

Both are pure projections over existing dhl_followup state + timeline
events.  No writes, no enqueue, no new authority.  Lesson E compliance:
this module cannot mutate audit state or send anything.

Lesson F compliance: single domain authority (DHL follow-up). Backend
produces the authoritative shape; the V2 page renders it dumbly.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..core.security import require_api_key
from ..services.dhl_followup_status_projector import (
    project_automation_status,
    project_shipment_rows,
)

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/dhl/followup-automation",
                   tags=["dhl-followup-status"])
_auth  = Depends(require_api_key)

# Operator-fresh data: every load must reflect the latest audit state.
# A cached "ACTIVE" badge after a flag toggle would mislead the operator.
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma":        "no-cache",
    "Expires":       "0",
}


@router.get("/status", dependencies=[_auth])
def get_followup_automation_status() -> JSONResponse:
    """Read-only top-card payload.

    Aggregates flag state, active/monitoring/eligible counts, next-due
    shipment, last sent/suppressed/failure events, today's metrics,
    traffic-light summary.  Pure projection — never raises.

    Cache-Control: no-store — operator must see flag flips and recent
    timeline events immediately, not a stale browser copy.
    """
    return JSONResponse(content=project_automation_status(),
                        headers=_NO_STORE_HEADERS)


@router.get("/shipments", dependencies=[_auth])
def get_followup_automation_shipments() -> JSONResponse:
    """Read-only drill-down rows for active shipments.

    Each row contains AWB, mode, status, next_due, last scan, last
    followup event.  Sorted by status priority (eligible first).
    """
    rows: List[Dict[str, Any]] = project_shipment_rows()
    return JSONResponse(content={"rows": rows, "count": len(rows)},
                        headers=_NO_STORE_HEADERS)
