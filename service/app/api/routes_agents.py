"""
routes_agents.py — Agent intelligence endpoints.

Endpoints
---------
  GET /api/v1/agents/decision/{batch_id}
      Returns the decision engine output for a batch:
      highest-priority action, reason, next_step, and full sorted list.

      200 — always; check ``status`` field ("idle" | "action_required")
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..core.security import require_api_key

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])
_auth  = Depends(require_api_key)


@router.get("/decision/{batch_id:path}", dependencies=[_auth])
def get_decision(batch_id: str) -> JSONResponse:
    """
    Run the decision engine for *batch_id* and return the top action.

    The response is always 200 — callers check ``status`` field:
    - ``"action_required"`` — primary_action is set
    - ``"idle"``            — no pending proposals, batch is on track
    """
    from ..agents.decision_engine import decide
    result = decide(batch_id)
    return JSONResponse(result)
