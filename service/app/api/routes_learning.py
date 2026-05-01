from __future__ import annotations

"""
routes_learning.py — Invoice learning feedback & pattern inspection endpoints.

POST /api/v1/invoice-learning/feedback          — submit parse feedback (correct/incorrect)
GET  /api/v1/invoice-learning/summary           — all suppliers with confidence/counts
GET  /api/v1/invoice-learning/patterns/{key}    — single supplier pattern detail
"""

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..core.logging import get_logger
from ..core.security import require_api_key

log   = get_logger(__name__)
router = APIRouter(prefix="/api/v1/invoice-learning", tags=["invoice-learning"])
_auth  = Depends(require_api_key)

# ── Lazy import so the service can start even if the learning agent is missing ──

def _agent():
    try:
        import invoice_learning_agent as _m
        return _m
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="invoice_learning_agent module not available",
        )


# ── Request/Response models ───────────────────────────────────────────────────

class FeedbackRequest(BaseModel):
    batch_id:          str
    invoice_no:        str           = ""
    supplier_key:      str           = ""   # normalized supplier key
    layout_fingerprint: str          = ""   # SHA256[:12] from learning_trace
    correct:           bool          = True
    field_corrections: Dict[str, str] = {}  # label field key → corrected label string


class FeedbackResponse(BaseModel):
    supplier_key:          str
    confirmed_count:       int
    confidence:            str
    promoted:              bool
    correct:               bool
    failed_count:          int
    downgraded:            Optional[bool] = False
    made_unstable:         Optional[bool] = False
    layout_is_unstable:    Optional[bool] = False
    consecutive_failures:  Optional[int]  = None
    reliability_pct:       Optional[int]  = None


class PatternSummaryItem(BaseModel):
    supplier_key:    str
    confidence:      str
    confirmed_count: int
    failed_count:    int
    item_types_seen: List[str]
    last_seen:       str
    any_unstable:    Optional[bool]   = False
    reliability_pct: Optional[int]    = 100
    last_failed:     Optional[str]    = None


class SummaryResponse(BaseModel):
    suppliers: List[PatternSummaryItem]
    total:     int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/feedback", response_model=FeedbackResponse, dependencies=[_auth])
def submit_feedback(req: FeedbackRequest) -> FeedbackResponse:
    """Record human feedback for a parsed invoice.

    Pass ``correct=True`` (parse was right) or ``correct=False`` (parse was wrong).
    Optional ``field_corrections`` map corrected label keys → corrected label strings;
    only ``*_label`` / ``*_pattern`` / ``*_words`` keys are accepted.
    """
    m = _agent()
    if not req.supplier_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="supplier_key is required",
        )

    try:
        result = m.record_feedback(
            supplier_key       = req.supplier_key,
            layout_fingerprint = req.layout_fingerprint,
            correct            = req.correct,
            field_corrections  = req.field_corrections,
        )
    except Exception as exc:
        log.exception("Learning feedback error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Learning feedback failed: {exc}",
        )

    log.info(
        "Learning feedback: supplier=%s correct=%s confidence=%s count=%s",
        result["supplier_key"], result["correct"],
        result["confidence"], result["confirmed_count"],
    )
    return FeedbackResponse(**result)


@router.get("/summary", response_model=SummaryResponse, dependencies=[_auth])
def get_summary() -> SummaryResponse:
    """Return confidence summary for all known suppliers."""
    m = _agent()
    try:
        raw = m.get_summary()
    except Exception as exc:
        log.exception("Learning summary error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not load summary: {exc}",
        )
    supplier_list = raw.get("suppliers", raw) if isinstance(raw, dict) else raw
    items = [PatternSummaryItem(**{k: v for k, v in s.items()
                                   if k in PatternSummaryItem.__fields__})
             for s in supplier_list]
    return SummaryResponse(suppliers=items, total=len(items))


@router.get("/patterns/{supplier_key}", dependencies=[_auth])
def get_patterns(supplier_key: str) -> dict:
    """Return full pattern detail for a single supplier (forbidden financial fields stripped)."""
    m = _agent()
    try:
        detail = m.get_pattern_detail(supplier_key)
    except Exception as exc:
        log.exception("Learning pattern detail error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not load pattern: {exc}",
        )
    if detail is None or "error" in detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No patterns found for supplier '{supplier_key}'",
        )
    return detail


@router.delete("/patterns/{supplier_key}", dependencies=[_auth])
def delete_patterns(supplier_key: str) -> dict:
    """Delete all learned patterns for a supplier (manual reset).

    Use when a supplier has significantly changed their invoice layout or
    patterns have become unreliable.  The supplier will be re-learned from
    the next successfully processed invoice.
    """
    m = _agent()
    try:
        result = m.reset_supplier_patterns(supplier_key)
    except Exception as exc:
        log.exception("Learning pattern reset error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not reset patterns: {exc}",
        )
    if not result.get("deleted"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.get("error", f"No patterns for '{supplier_key}'"),
        )
    log.info("Learning patterns RESET for supplier=%s", supplier_key)
    return result
