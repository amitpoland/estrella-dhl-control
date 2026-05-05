"""
routes_warehouse_audit.py — Read-only audit endpoints for warehouse gap detection.

Endpoints
---------
  GET /api/v1/warehouse/audit/{batch_id}
       Full audit report: missing scans, stuck inventory, invalid flows,
       orphan records, and completion summary.

  GET /api/v1/warehouse/audit/{batch_id}/summary
       Completion summary only (lightweight, suitable for dashboards).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..core.security import require_api_key
from ..services import warehouse_audit as waudit

router = APIRouter(prefix="/api/v1/warehouse", tags=["warehouse-audit"])
_auth  = Depends(require_api_key)


@router.get("/audit/{batch_id:path}", dependencies=[_auth])
def warehouse_audit(
    batch_id:        str,
    stuck_threshold: int = 24,
) -> JSONResponse:
    """
    Full audit report for a batch.

    Query params:
      stuck_threshold  — hours before an item at RECV* is considered stuck (default 24)
    """
    missing   = waudit.get_missing_scans(batch_id)
    stuck     = waudit.get_stuck_inventory(batch_id, threshold_hours=stuck_threshold)
    invalid   = waudit.get_invalid_flows(batch_id)
    orphans   = waudit.get_orphan_inventory(batch_id)
    summary   = waudit.get_batch_completion(batch_id)

    return JSONResponse({
        "batch_id":       batch_id,
        "missing_scans":  missing,
        "stuck_inventory": stuck,
        "invalid_flows":  invalid,
        "orphan_inventory": orphans,
        "summary": summary,
    })


@router.get("/audit-summary/{batch_id:path}", dependencies=[_auth])
def warehouse_audit_summary(batch_id: str) -> JSONResponse:
    """
    Completion summary only — lighter call for dashboards.

    Uses /audit-summary/ prefix to avoid the greedy {batch_id:path} pattern
    on the full audit route capturing '/summary' as part of the batch_id.
    """
    return JSONResponse(waudit.get_batch_completion(batch_id))
