"""Master Data Intelligence router — Phase 4 advisory endpoints.

All endpoints are GET-only. No writes. No LLM calls. Advisory output only.

Prefix: /api/v1/master-data/intelligence
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from ..core.security import require_api_key
from ..core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/master-data/intelligence",
    tags=["master-data-intelligence"],
)

_auth = Depends(require_api_key)

_VALID_DOMAINS = {"customer", "product", "finishing", "supplier", "readiness"}


@router.get(
    "",
    dependencies=[_auth],
    summary="Full platform master-data intelligence report",
    description=(
        "Returns advisory scores, completeness metrics, field gaps, "
        "duplicate clusters, and recommendations across all 5 domains. "
        "llm_used=False — deterministic only. No writes."
    ),
)
def platform_report() -> JSONResponse:
    try:
        from ..services.master_data_intelligence import generate_report
        report = generate_report()
        return JSONResponse(content=report.to_dict())
    except Exception as exc:
        log.error("[mdi] platform_report failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Master data intelligence report failed")


@router.get(
    "/{domain}",
    dependencies=[_auth],
    summary="Single-domain master-data intelligence",
    description=(
        "Returns advisory scores for one domain: "
        "customer | product | finishing | supplier | readiness. "
        "llm_used=False — deterministic only. No writes."
    ),
)
def domain_report(domain: str) -> JSONResponse:
    if domain not in _VALID_DOMAINS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown domain '{domain}'. Valid: {sorted(_VALID_DOMAINS)}",
        )
    try:
        from ..services.master_data_intelligence import generate_report
        report = generate_report()
        domain_score = getattr(report, domain)
        return JSONResponse(content={
            "generated_at": report.generated_at,
            "llm_used": report.llm_used,
            "advisory_class": report.advisory_class,
            "domain": domain_score.domain,
            "entity_count": domain_score.entity_count,
            "completeness_score": round(domain_score.completeness_score, 3),
            "confidence": round(domain_score.confidence, 3),
            "field_gaps": [
                {"field": g.field, "affected_count": g.affected_count,
                 "pct": round(g.pct, 1), "severity": g.severity,
                 "advisory": g.advisory}
                for g in domain_score.field_gaps
            ],
            "duplicate_clusters": [
                {"key": c.key, "entity_keys": c.entity_keys,
                 "probability": round(c.probability, 2)}
                for c in domain_score.duplicate_clusters
            ],
            "advisory": domain_score.advisory,
            "recommendations": domain_score.recommendations,
            "details": domain_score.details,
        })
    except HTTPException:
        raise
    except Exception as exc:
        log.error("[mdi] domain_report(%s) failed: %s", domain, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Intelligence report for '{domain}' failed")
