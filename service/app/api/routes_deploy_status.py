"""
routes_deploy_status.py — Read-only deployment status endpoint.

Endpoints
---------
  GET /api/v1/deploy/status
       Returns live SHA, deployed_at, PR queue, GATE 2 state, and
       verification gate results. Read-only — no writes, no side effects.
       Auth: X-API-Key (same as all other internal read endpoints).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..core.security import require_api_key
from ..services.deploy_status_service import read_deploy_status

router = APIRouter(prefix="/api/v1/deploy", tags=["deploy"])

_NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma":        "no-cache",
    "Expires":       "0",
}


@router.get("/status", dependencies=[Depends(require_api_key)])
def get_deploy_status() -> JSONResponse:
    """
    Return the current deployment state: live SHA, GATE 2 PR queue,
    verification results, and merged-but-not-deployed warnings.

    Data sources:
    - storage_root/version.json (written by deploy-service.sh)
    - DEPLOY_STATE_MD_PATH env var → TASK_STATE.md (Claude memory directory)

    Both sources are optional; the endpoint always returns 200 with whatever
    data is available, plus a ``warnings`` list describing any missing sources.
    """
    status = read_deploy_status()
    return JSONResponse(content=status, headers=_NO_CACHE)
