"""
routes_ai_advisory.py -- Read-only AI advisory endpoints (Phase 2).

Class: R (read-only AI). See docs/ai-governance/ai-capability-map.md.

Endpoints
---------
  GET /api/v1/ai/advisory/workflow-blockers/{batch_id}
      Returns a plain-English explanation of why this batch's workflow
      is blocked (or, if not blocked, that it is ready). Phase 2: may
      include an LLM-synthesised summary when ai_advisory_llm_enabled=True.

  GET /api/v1/ai/advisory/status
      Returns current advisory subsystem status: flag state, gateway
      availability, daily cost, model configured. Read-only observability.

This router declares GET endpoints only. No write methods are permitted
on this surface -- test_ai_advisory_no_writes.py enforces this with a
source-grep test.
"""
from __future__ import annotations

import time

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

    Phase 2: summary may be LLM-synthesised when ai_advisory_llm_enabled=True.
    llm_used=True iff an LLM call succeeded for this response.
    model_used=<model_id> iff llm_used=True, else null.
    generated_at=<ISO-8601 UTC>.

    Status codes
    ------------
    200 -- explanation returned (ready or blocked are both valid; llm_used varies)
    400 -- batch_id empty / invalid shape
    503 -- underlying readiness load failed
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


@router.get("/status", dependencies=[_auth])
def advisory_status() -> JSONResponse:
    """
    Read-only observability: current advisory subsystem configuration and
    runtime health. No side effects.

    Returns
    -------
    {
        "ok":                     bool,
        "ai_advisory_llm_enabled": bool,
        "ai_parser_enabled":       bool,
        "gateway_available":       bool,
        "model":                   str,
        "max_tokens_per_call":     int,
        "budget_usd_per_day":      float,
        "spent_usd_today":         float,
        "budget_ok":               bool,
        "cache_ttl_seconds":       int,
        "generated_at":            str,
    }
    """
    from ..core.config import settings  # noqa: PLC0415

    llm_enabled = bool(getattr(settings, "ai_advisory_llm_enabled", False))
    ai_parser_enabled = bool(getattr(settings, "ai_parser_enabled", False))
    model = str(getattr(settings, "ai_advisory_model", ""))
    max_tokens = int(getattr(settings, "ai_advisory_max_tokens_per_call", 1000))
    budget = float(getattr(settings, "ai_advisory_budget_usd_per_day", 1.0))
    cache_ttl = int(getattr(settings, "ai_advisory_cache_ttl_seconds", 300))

    # Phase 2B provider fields
    cowork_enabled    = bool(getattr(settings, "ai_cowork_enabled", False))
    fallback_enabled  = bool(getattr(settings, "ai_fallback_enabled", False))
    provider_pref     = str(getattr(settings, "ai_provider_preference", "claude_cowork"))

    # Gateway availability: checks api key + ai_parser_enabled (or cowork enabled)
    gateway_available = False
    try:
        from ..services import ai_gateway as gw  # noqa: PLC0415
        gateway_available = gw.is_available()
    except Exception:
        pass

    # Cowork availability: enabled (stub is always "available" when enabled)
    cowork_available = cowork_enabled

    # Today's spend from ledger
    spent_today = 0.0
    try:
        from ..services import ai_call_ledger as ledger  # noqa: PLC0415
        spent_today = ledger.get_daily_cost_usd()
    except Exception:
        pass

    budget_ok = (budget <= 0) or (spent_today < budget)

    # Compute active provider based on config.
    # Rule: gateway_available is the outer gate.  A provider can only be
    # "active" if the gateway itself is usable (enabled + API key present).
    # Checking cowork_enabled BEFORE gateway_available produced the
    # contradiction where active_provider="claude_cowork" while
    # gateway_available=false — fixed here.
    if not gateway_available:
        active_provider = "none"
    elif cowork_enabled and provider_pref == "claude_cowork":
        active_provider = "claude_cowork"
    else:
        active_provider = "anthropic_api"

    # Admin API key health check (optional — None if admin key not configured)
    api_key_health = None
    try:
        from ..services import ai_gateway as gw  # noqa: PLC0415
        api_key_health = gw.check_key_health()
    except Exception:
        pass

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    return JSONResponse({
        "ok":                      True,
        "ai_advisory_llm_enabled": llm_enabled,
        "ai_parser_enabled":       ai_parser_enabled,
        "gateway_available":       gateway_available,
        "model":                   model,
        "max_tokens_per_call":     max_tokens,
        "budget_usd_per_day":      budget,
        "spent_usd_today":         round(spent_today, 6),
        "budget_ok":               budget_ok,
        "cache_ttl_seconds":       cache_ttl,
        "generated_at":            generated_at,
        "cowork_enabled":          cowork_enabled,
        "cowork_available":        cowork_available,
        "fallback_enabled":        fallback_enabled,
        "provider_preference":     provider_pref,
        "active_provider":         active_provider,
        "api_key_health":          api_key_health,
    }, status_code=200)
