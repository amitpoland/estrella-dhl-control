"""Workflow Intelligence router -- Phase 9.

GET /api/v1/workflow/intelligence

Returns a unified workflow status report for a single batch, aggregating
signals from batch_readiness, intelligence_graph, and master_data_intelligence.

Query parameters:
  batch_id  (str)  -- target batch identifier
  awb       (str)  -- DHL AWB number; resolved to batch_id via documents.db
  domain    (str)  -- optional domain filter; limits blockers/warnings to one domain
  limit     (int)  -- unused at batch-level; reserved for future multi-batch endpoint

One of batch_id or awb is required. If both are given, batch_id takes precedence.
If neither is given, returns 422.

Design rules:
  - GET-only, no writes
  - llm_used=False in every response (structural invariant)
  - No ai_gateway, no Anthropic, no LLM
  - No wFirma / DHL / customs / accounting / PZ write mutations
  - 422 on missing batch_id + awb; 404 when AWB resolves to no batch
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..services.workflow_intelligence import (
    get_workflow_intelligence,
    resolve_batch_id_from_awb,
)

log = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/workflow",
    tags=["workflow-intelligence"],
)

_auth = Depends(require_api_key)

_VALID_DOMAINS = {"warehouse", "sales", "wfirma", "dhl", "graph", "readiness"}

_DOC_DB = settings.storage_root / "documents.db"


@router.get(
    "/intelligence",
    dependencies=[_auth],
    summary="Workflow intelligence for a single batch",
    description=(
        "Aggregates batch_readiness, intelligence_graph, and master_data_intelligence "
        "signals into a unified workflow status. "
        "Returns workflow_status (BLOCKED | INCOMPLETE | READY | UNKNOWN), "
        "blockers, warnings, missing_links, readiness_impact, and a plain-text "
        "recommendation for the operator. "
        "llm_used=False -- deterministic only. No writes."
    ),
)
def workflow_intelligence(
    batch_id: Optional[str] = Query(
        default=None,
        description="Target batch identifier. Takes precedence over awb if both given.",
    ),
    awb: Optional[str] = Query(
        default=None,
        description="DHL AWB number; resolved to batch_id via documents.db.",
    ),
    domain: Optional[str] = Query(
        default=None,
        description=(
            "Filter output to one domain: "
            "warehouse | sales | wfirma | dhl | graph | readiness"
        ),
    ),
    limit: int = Query(
        default=10,
        ge=1,
        le=100,
        description="Reserved for future multi-batch use. Ignored in current endpoint.",
    ),
) -> JSONResponse:
    # ── Validate domain filter ────────────────────────────────────────────────
    if domain is not None and domain not in _VALID_DOMAINS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid domain '{domain}'. "
                f"Valid values: {sorted(_VALID_DOMAINS)}"
            ),
        )

    # ── Resolve batch_id ─────────────────────────────────────────────────────
    resolved_batch_id: Optional[str] = None

    if batch_id:
        resolved_batch_id = batch_id.strip()
    elif awb:
        resolved_batch_id = resolve_batch_id_from_awb(awb.strip(), doc_db=_DOC_DB)
        if resolved_batch_id is None:
            raise HTTPException(
                status_code=404,
                detail=f"AWB '{awb}' could not be resolved to a batch_id in documents.db",
            )
    else:
        raise HTTPException(
            status_code=422,
            detail="Either 'batch_id' or 'awb' is required.",
        )

    # ── Execute ───────────────────────────────────────────────────────────────
    try:
        result = get_workflow_intelligence(
            batch_id=resolved_batch_id,
            domain=domain,
        )
        return JSONResponse(content=result.to_dict())

    except Exception as exc:
        log.error(
            "[workflow-route] get_workflow_intelligence failed for %s: %s",
            resolved_batch_id, exc, exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Workflow intelligence service failed",
        )
