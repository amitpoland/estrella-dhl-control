from __future__ import annotations

"""
routes_proposals.py — Parser Fix Proposal endpoints.

POST   /api/v1/proposals/capture          — capture a new proposal (internal)
GET    /api/v1/proposals                  — list proposals (filter: ?status=pending)
GET    /api/v1/proposals/summary          — counts by status/risk
POST   /api/v1/proposals/{id}/approve     — approve proposal
POST   /api/v1/proposals/{id}/reject      — reject proposal {reason: "..."}
GET    /api/v1/proposals/{id}             — get single proposal detail
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ..core.logging import get_logger
from ..core.security import require_api_key

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/proposals", tags=["proposals"])
_auth  = Depends(require_api_key)

# ── Lazy import ───────────────────────────────────────────────────────────────

def _m():
    try:
        import parser_fix_proposals as _mod
        return _mod
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="parser_fix_proposals module not available",
        )


# ── Request / Response models ─────────────────────────────────────────────────

class CaptureRequest(BaseModel):
    field_missing:  str
    failure_reason: str
    text_snippet:   str  = ""
    supplier_key:   str  = ""
    batch_id:       str  = ""
    invoice_file:   str  = ""


class RejectRequest(BaseModel):
    reason: str = ""


class SuggestedRule(BaseModel):
    type:              str
    description:       str
    label_to_search:   Optional[str] = None
    regex_pattern:     Optional[str] = None
    confidence:        str = "low"


class ProposalItem(BaseModel):
    proposal_id:      str
    created_at:       str
    status:           str
    supplier_key:     str
    batch_id:         str
    invoice_file:     str
    field_missing:    str
    failure_reason:   str
    text_snippet:     str
    suggested_rule:   dict
    risk_level:       str
    approved_by:      Optional[str]
    approved_at:      Optional[str]
    applied_as:       Optional[str]
    rejection_reason: Optional[str]


class SummaryResponse(BaseModel):
    total:     int
    pending:   int
    approved:  int
    applied:   int
    rejected:  int
    by_status: dict
    by_risk:   dict


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/capture", dependencies=[_auth])
def capture(req: CaptureRequest) -> dict:
    """Capture a new parser fix proposal (called internally by the processor)."""
    mod = _m()
    try:
        result = mod.capture_proposal(
            field_missing  = req.field_missing,
            failure_reason = req.failure_reason,
            text_snippet   = req.text_snippet,
            supplier_key   = req.supplier_key,
            batch_id       = req.batch_id,
            invoice_file   = req.invoice_file,
        )
    except Exception as exc:
        log.exception("Proposal capture error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Proposal capture failed: {exc}",
        )
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result["error"],
        )
    log.info(
        "Proposal captured: id=%s field=%s risk=%s",
        result.get("proposal_id"), req.field_missing, result.get("risk_level"),
    )
    return result


@router.get("", dependencies=[_auth])
def list_proposals(status: Optional[str] = Query(None, description="Filter by status")) -> List[dict]:
    """List all proposals, optionally filtered by status (pending|approved|applied|rejected)."""
    mod = _m()
    try:
        return mod.get_proposals(status_filter=status)
    except Exception as exc:
        log.exception("Proposal list error: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Could not load proposals: {exc}",
        )


@router.get("/summary", dependencies=[_auth], response_model=SummaryResponse)
def get_summary() -> SummaryResponse:
    """Return proposal counts by status and risk level."""
    mod = _m()
    try:
        raw = mod.get_proposal_summary()
    except Exception as exc:
        log.exception("Proposal summary error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Could not load summary: {exc}")
    return SummaryResponse(**raw)


@router.get("/{proposal_id}", dependencies=[_auth])
def get_proposal(proposal_id: str) -> dict:
    """Return a single proposal by ID."""
    mod = _m()
    try:
        proposal = mod.get_proposal(proposal_id)
    except Exception as exc:
        log.exception("Proposal get error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Could not load proposal: {exc}")
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proposal '{proposal_id}' not found",
        )
    return proposal


@router.post("/{proposal_id}/approve", dependencies=[_auth])
def approve(proposal_id: str) -> dict:
    """
    Approve a proposal.

    - safe proposals → converted to invoice_learning_agent hint immediately
      (applied_as = "learning_hint")
    - review/restricted proposals → applied_as = "code_change_required"
      (manual code review step still required)
    """
    mod = _m()
    try:
        result = mod.approve_proposal(proposal_id)
    except Exception as exc:
        log.exception("Proposal approve error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Approval failed: {exc}")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    log.info(
        "Proposal approved: id=%s applied_as=%s",
        proposal_id, result.get("applied_as"),
    )
    return result


@router.post("/{proposal_id}/reject", dependencies=[_auth])
def reject(proposal_id: str, req: RejectRequest = RejectRequest()) -> dict:
    """Reject a proposal with an optional reason."""
    mod = _m()
    try:
        result = mod.reject_proposal(proposal_id, reason=req.reason)
    except Exception as exc:
        log.exception("Proposal reject error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Rejection failed: {exc}")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    log.info("Proposal rejected: id=%s reason=%s", proposal_id, req.reason)
    return result
