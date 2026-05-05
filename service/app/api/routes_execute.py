"""
routes_execute.py — Centralized write-action execution endpoint.

All guarded write actions from the dashboard flow through here.
The engine handles readiness checks, idempotency, and audit logging.

Endpoint
--------
  POST /api/v1/execute/{action}
       action : "wfirma_create" | "closure_confirm" | "dhl_send_reply"

  Body (JSON):
    batch_id : str
    payload  : dict  (action-specific; optional)

  Returns:
    200 — ok=True, status="executed" or status="skipped"
    400 — missing batch_id or unknown action
    422 — validation error
    503 — readiness load failed (upstream data not available)
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any, Dict, Optional

from ..core.security import require_api_key
from fastapi import Depends

router = APIRouter(prefix="/api/v1/execute", tags=["execute"])
_auth  = Depends(require_api_key)


class ExecuteRequest(BaseModel):
    batch_id: str
    payload:  Optional[Dict[str, Any]] = None


@router.post("/{action}", dependencies=[_auth])
def execute(action: str, req: ExecuteRequest) -> JSONResponse:
    """
    Execute one controlled write action.

    The execution engine enforces:
    - readiness pre-checks
    - idempotency (duplicate calls return status=skipped)
    - execution log write
    - routing to the correct service handler

    Status codes
    ------------
    200 — action completed (ok=True, status="executed" or "skipped")
          OR action blocked (ok=False, error="blocked") — still 200 so the
          dashboard can display the reason without treating it as a network error
    400 — batch_id missing / action unknown at validation level
    503 — readiness data could not be loaded (upstream failure)
    """
    if not req.batch_id:
        return JSONResponse(
            {"ok": False, "error": "missing_field", "field": "batch_id"},
            status_code=400,
        )

    from ..services.execution_engine import execute_action

    result = execute_action(action, req.batch_id, req.payload)

    # Readiness load failure is a server-side upstream problem
    if result.get("error") == "readiness_load_failed":
        return JSONResponse(result, status_code=503)

    # Unknown action — treat as bad request
    if result.get("error") == "unknown_action":
        return JSONResponse(result, status_code=400)

    return JSONResponse(result, status_code=200)
