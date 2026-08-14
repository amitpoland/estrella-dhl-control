"""
routes_customer_enrichment.py — internal business API for Client Master
external enrichment (Cowork research proposals + operator acceptance).

Authority: Customer Master. This file exposes the enrichment task/proposal
store and the acceptance flow; the only Customer Master write happens inside
customer_external_enrichment.accept_enrichment_proposal (via
customer_master_db.update_enrichment_fields + audit_safe).

Feature gating (DHL-webhook convention, routes_carrier_webhook.py): the router
is registered unconditionally in main.py; every route depends on
_require_enrichment_enabled, which raises 503 while
customer_external_enrichment_enabled is False. Fail closed by default.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..core.audit import actor_from_request
from ..core.config import settings
from ..core.role_gate import MASTER_ADMIN, MASTER_EDITOR, require_role_or_apikey
from ..core.security import require_api_key
from ..services import customer_external_enrichment as enrichment
from ..services.customer_external_enrichment import (
    ProposalStateError,
    StaleProposalError,
)

router = APIRouter(prefix="/api/v1", tags=["customer-enrichment"])

_auth = Depends(require_api_key)
_write_auth = Depends(require_role_or_apikey(MASTER_ADMIN, MASTER_EDITOR))


def _cm_db():
    return settings.storage_root / "customer_master.sqlite"


def _enrich_db():
    return settings.storage_root / "customer_enrichment.sqlite"


def _require_enrichment_enabled() -> None:
    """503 while the feature flag is off — endpoints exist but are dark."""
    if not settings.customer_external_enrichment_enabled:
        raise HTTPException(
            status_code=503,
            detail="Customer external enrichment is not enabled on this server.",
        )


_enabled = Depends(_require_enrichment_enabled)


@router.get("/customer-master/{contractor_id}/enrichment",
            dependencies=[_enabled, _auth])
def get_enrichment(contractor_id: str):
    """Latest enrichment task + proposals + evidence for one contractor."""
    task = enrichment.get_enrichment_for_contractor(_enrich_db(), contractor_id)
    return {"contractor_id": contractor_id, "task": task}


@router.post("/customer-master/{contractor_id}/enrichment/research",
             dependencies=[_enabled, _write_auth])
def run_research(contractor_id: str, request: Request):
    """Create a research task for this contractor's missing fields."""
    if enrichment.has_open_task(_enrich_db(), contractor_id):
        raise HTTPException(
            status_code=409,
            detail="An enrichment task is already pending or researching "
                   "for this contractor.",
        )
    try:
        result = enrichment.run_customer_enrichment(
            contractor_id, _cm_db(), _enrich_db(),
            trigger="operator", actor=actor_from_request(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return result


@router.get("/customer-enrichment/status", dependencies=[_enabled, _auth])
def enrichment_status():
    """Canonical status contract (CLAUDE.md status-endpoint shape)."""
    return enrichment.get_enrichment_status(_enrich_db())


@router.post("/customer-enrichment/proposals/{proposal_id}/accept",
             dependencies=[_enabled, _write_auth])
def accept_proposal(proposal_id: str, request: Request):
    """Accept one proposal — the only Customer Master write in this feature."""
    try:
        return enrichment.accept_enrichment_proposal(
            _enrich_db(), _cm_db(), proposal_id,
            actor=actor_from_request(request), request=request,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except StaleProposalError:
        raise HTTPException(
            status_code=409, detail={"error": "ENRICHMENT_PROPOSAL_STALE"})
    except ProposalStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/customer-enrichment/proposals/{proposal_id}/reject",
             dependencies=[_enabled, _write_auth])
def reject_proposal(proposal_id: str, request: Request):
    """Reject one proposal. No Customer Master write."""
    try:
        return enrichment.reject_enrichment_proposal(
            _enrich_db(), proposal_id, actor=actor_from_request(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ProposalStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
