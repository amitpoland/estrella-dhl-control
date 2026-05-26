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

from ..core.security import require_api_key
from ..services.dhl_followup_status_projector import (
    project_automation_status,
    project_shipment_rows,
)

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/dhl/followup-automation",
                   tags=["dhl-followup-status"])
_auth  = Depends(require_api_key)


@router.get("/status", dependencies=[_auth])
def get_followup_automation_status() -> Dict[str, Any]:
    """Read-only top-card payload.

    Aggregates flag state, active/monitoring/eligible counts, next-due
    shipment, last sent/suppressed/failure events, today's metrics,
    traffic-light summary.  Pure projection — never raises.
    """
    return project_automation_status()


@router.get("/shipments", dependencies=[_auth])
def get_followup_automation_shipments() -> Dict[str, Any]:
    """Read-only drill-down rows for active shipments.

    Each row contains AWB, mode, status, next_due, last scan, last
    followup event.  Sorted by status priority (eligible first).
    """
    rows: List[Dict[str, Any]] = project_shipment_rows()
    return {"rows": rows, "count": len(rows)}
