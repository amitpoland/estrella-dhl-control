"""
routes_ai_advisory.py — Read-only AI advisory endpoints (Phase 1).

Class: R (read-only AI). See docs/ai-governance/ai-capability-map.md.

Endpoints
---------
  GET /api/v1/ai/advisory/workflow-blockers/{batch_id}
      Returns a plain-English explanation of why this batch's workflow
      is blocked (or, if not blocked, that it is ready).

This router declares GET endpoints only. No write methods are permitted
on this surface — `test_ai_advisory_no_writes.py` enforces this with a
source-grep test.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..core.security import require_api_key
from ..services.ai_advisory import AdvisoryError, explain_workflow_blockers

router = APIRouter(prefix="/api/v1/ai/advisory", tags=["ai-advisory"])
_auth = Depends(require_api_key)


@router.get("/workflow-blockers/{batch_id}", dependencies=[_auth])
def workflow_blockers(batch_id: str) -> JSONResponse:
    """
    Read-only "why is this workflow blocked?" explanation.

    Status codes
    ------------
    200 — explanation returned (whether ready or not — both are valid states)
    400 — batch_id empty / invalid shape
    503 — underlying readiness load failed
    """
    if not batch_id or not isinstance(batch_id, str):
        return JSONResponse(
            {"ok": False, "error": "missing_field", "field": "batch_id"},
            status_code=400,
        )

    try:
        result = explain_workflow_blockers(batch_id)
    except AdvisoryError as exc:
        return JSONResponse(
            {"ok": False, "error": "readiness_load_failed", "detail": str(exc)},
            status_code=503,
        )

    return JSONResponse({"ok": True, **result}, status_code=200)
