"""Operations Intelligence router -- Phase 10.

GET /api/v1/operations/intelligence

Returns a platform-level operations health report aggregating cross-batch
metrics from batch_readiness, master_data_intelligence, and documents.db.

Query parameters:
  period  (str)  -- time window: today | 7d | 30d (default: 7d)
  domain  (str)  -- optional domain filter: warehouse | sales | wfirma | dhl | graph | readiness

Design rules:
  - GET-only, no writes
  - llm_used=False in every response (structural invariant)
  - No ai_gateway, no Anthropic, no LLM
  - No wFirma / DHL / customs / accounting / PZ write mutations
  - 422 on invalid period or domain
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..services.operations_intelligence import (
    _DEFAULT_BATCH_LIMIT,
    _DEFAULT_PERIOD,
    _VALID_PERIODS,
    get_operations_intelligence,
)

log = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/operations",
    tags=["operations-intelligence"],
)

_auth = Depends(require_api_key)

_VALID_DOMAINS = {"warehouse", "sales", "wfirma", "dhl", "graph", "readiness"}


@router.get(
    "/intelligence",
    dependencies=[_auth],
    summary="Platform-level operations intelligence",
    description=(
        "Aggregates cross-batch operational metrics for the given time period. "
        "Returns total_batches, blocked_batches, incomplete_batches, ready_batches, "
        "document_coverage_score, master_data_score, graph_completeness_score, "
        "workflow_risk_summary (HIGH/MEDIUM/LOW aggregate), top_missing_evidence, "
        "top_master_data_gaps, and llm_used=False. "
        "Deterministic only -- no LLM, no writes."
    ),
)
def operations_intelligence(
    period: str = Query(
        default=_DEFAULT_PERIOD,
        description="Time window for batch selection: today | 7d | 30d.",
    ),
    domain: Optional[str] = Query(
        default=None,
        description=(
            "Filter output to one domain: "
            "warehouse | sales | wfirma | dhl | graph | readiness"
        ),
    ),
) -> JSONResponse:
    # ── Validate period ───────────────────────────────────────────────────────
    if period not in _VALID_PERIODS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid period '{period}'. "
                f"Valid values: {sorted(_VALID_PERIODS)}"
            ),
        )

    # ── Validate domain filter ────────────────────────────────────────────────
    if domain is not None and domain not in _VALID_DOMAINS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid domain '{domain}'. "
                f"Valid values: {sorted(_VALID_DOMAINS)}"
            ),
        )

    # ── Execute ───────────────────────────────────────────────────────────────
    try:
        result = get_operations_intelligence(
            period=period,
            domain=domain,
        )
        return JSONResponse(content=result.to_dict())

    except Exception as exc:
        log.error(
            "[ops-route] get_operations_intelligence failed: %s",
            exc, exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Operations intelligence service failed",
        )
