"""
routes_monitor.py — Active shipment monitor endpoints.

POST /api/v1/monitor/active-shipments/run — sweep all active shipments.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from ..core.security import require_api_key
from ..services.active_shipment_monitor import scan_active_shipments

log    = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/monitor", tags=["monitor"])
_auth  = Depends(require_api_key)


@router.post("/active-shipments/run", dependencies=[_auth])
async def run_active_shipment_monitor(
    force: bool = Query(False, description="Include terminal shipments (testing/backfill)."),
) -> Dict[str, Any]:
    """
    Sweep all active shipments. For each:
      - Apply cached email intelligence if found
      - Dispatch new email_scan task only if no recent pending task exists
      - Compute SLA flags
    Returns the action summary; never blocks on individual failures.
    """
    return scan_active_shipments(force=force)
