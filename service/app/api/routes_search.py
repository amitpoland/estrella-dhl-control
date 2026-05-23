"""routes_search.py -- Phase 7: Natural-Language Search Foundation.

GET /api/v1/search

Deterministic only. llm_used=False. No writes. No LLM calls.
GET-only. Read-only authority data.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from ..core.security import require_api_key
from ..core.logging import get_logger
from ..services.search_engine import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    QUERY_MAX_LEN,
    parse_query,
    execute_search,
)

log = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/search",
    tags=["search"],
)

_auth = Depends(require_api_key)

_VALID_DOMAINS = {"document", "customer", "supplier", "product", "shipment"}


@router.get(
    "",
    dependencies=[_auth],
    summary="Natural-language search over authority data",
    description=(
        "Searches customers, suppliers, products, and documents using "
        "deterministic pattern matching and keyword search. "
        "Recognizes: AWB numbers, MRN references, PZ/invoice refs, "
        "UUID batch IDs, HS codes, and free-text keywords. "
        "llm_used=False -- deterministic only. No writes."
    ),
)
def search(
    q: str = Query(
        ...,
        min_length=1,
        max_length=QUERY_MAX_LEN,
        description="Search query. Supports AWB, MRN, PZ/invoice ref, keyword.",
    ),
    domains: str = Query(
        default="",
        description=(
            "Comma-separated domain filter: "
            "document,customer,supplier,product. "
            "Default: all domains."
        ),
    ),
    limit: int = Query(
        default=DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description=f"Max results per domain (1-{MAX_LIMIT}). Default {DEFAULT_LIMIT}.",
    ),
) -> JSONResponse:
    # Parse domain filter
    domain_list = None
    if domains:
        raw_domains = [d.strip().lower() for d in domains.split(",") if d.strip()]
        invalid = [d for d in raw_domains if d not in _VALID_DOMAINS]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unknown domain(s): {invalid}. "
                    f"Valid: {sorted(_VALID_DOMAINS)}"
                ),
            )
        domain_list = raw_domains if raw_domains else None

    try:
        intent = parse_query(q)
        result = execute_search(intent, domains=domain_list, limit=limit)
        return JSONResponse(content=result.to_dict())
    except HTTPException:
        raise
    except Exception as exc:
        log.error("[search] search failed for q=%r: %s", q, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Search failed")
