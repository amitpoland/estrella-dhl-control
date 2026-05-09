"""
routes_correction_registry.py — Read/write surface for the operator
correction-learning registry.

Design rules
------------
- POST is operator-driven. The body must include `operator`. The route
  itself never derives or guesses a correction; it only records what
  the operator explicitly submitted via the dashboard or another
  authenticated client.
- All other endpoints are read-only.
- The registry NEVER triggers wFirma writes, SMTP, DHL, PZ, or Proforma
  flows. It is an isolated memory layer.
- The `explain` endpoint is the single source of provenance for any
  future suggestion surface that wants to prefill a value.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from ..core.logging import get_logger
from ..core.security import require_api_key
from ..services import correction_registry as cr

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/corrections", tags=["corrections"])
_auth  = Depends(require_api_key)


# ── Schemas ──────────────────────────────────────────────────────────────────

class EvidenceRef(BaseModel):
    type: str = Field(..., description="audit | email | shipment | document | proposal | other")
    ref:  str = Field(..., description="opaque reference value")


class CorrectionIn(BaseModel):
    correction_type: str
    entity_type:     str = ""
    entity_key:      str = ""
    old_value:       Any = ""
    new_value:       Any = ""
    shipment_id:     str = ""
    batch_id:        str = ""
    operator:        str = Field(..., min_length=1,
                                 description="Operator id/name (required).")
    module_source:   str = ""
    confidence:      float = 0.0
    notes:           str = ""
    approved:        bool = True
    evidence_refs:   List[EvidenceRef] = []


# ── Append-only write ────────────────────────────────────────────────────────

@router.post("", dependencies=[_auth])
def post_correction(body: CorrectionIn) -> Dict[str, Any]:
    """
    Append one correction. This is the only write endpoint. It does
    not mutate any other DB or trigger any side-effects.
    """
    if body.correction_type not in cr.SUPPORTED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported correction_type. "
                   f"Allowed: {sorted(cr.SUPPORTED_TYPES)}",
        )
    try:
        rid = cr.record_correction(
            correction_type=body.correction_type,
            entity_type=body.entity_type,
            entity_key=body.entity_key,
            old_value=body.old_value,
            new_value=body.new_value,
            shipment_id=body.shipment_id,
            batch_id=body.batch_id,
            operator=body.operator,
            module_source=body.module_source,
            confidence=body.confidence,
            notes=body.notes,
            approved=body.approved,
            evidence_refs=[r.model_dump() for r in body.evidence_refs],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "id": rid}


# ── Read-only retrieval ──────────────────────────────────────────────────────

@router.get("", dependencies=[_auth])
def get_corrections(
    correction_type: Optional[str] = Query(None),
    entity_key:      Optional[str] = Query(None),
    shipment_id:     Optional[str] = Query(None),
    batch_id:        Optional[str] = Query(None),
    approved:        Optional[bool] = Query(None),
    operator:        Optional[str] = Query(None),
    limit:           int = Query(200, ge=1, le=5000),
) -> Dict[str, Any]:
    rows = cr.list_corrections(
        correction_type=correction_type,
        entity_key=entity_key,
        shipment_id=shipment_id,
        batch_id=batch_id,
        approved=approved,
        operator=operator,
        limit=limit,
    )
    return {"ok": True, "count": len(rows), "rows": rows}


@router.get("/last-accepted", dependencies=[_auth])
def get_last_accepted(
    correction_type: str = Query(...),
    entity_key:      str = Query(...),
) -> Dict[str, Any]:
    if correction_type not in cr.SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported correction_type")
    row = cr.get_last_accepted(correction_type, entity_key)
    return {"ok": True, "row": row}


@router.get("/rejected", dependencies=[_auth])
def get_rejected(
    correction_type: str = Query(...),
    entity_key:      str = Query(...),
    limit:           int = Query(20, ge=1, le=200),
) -> Dict[str, Any]:
    if correction_type not in cr.SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported correction_type")
    rows = cr.get_rejected(correction_type, entity_key, limit=limit)
    return {"ok": True, "count": len(rows), "rows": rows}


@router.get("/frequency", dependencies=[_auth])
def get_frequency(
    correction_type: str = Query(...),
    entity_key:      str = Query(...),
) -> Dict[str, Any]:
    if correction_type not in cr.SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported correction_type")
    return {"ok": True, "frequency": cr.get_frequency(correction_type, entity_key)}


@router.get("/confidence", dependencies=[_auth])
def get_confidence(
    correction_type: str = Query(...),
    entity_key:      str = Query(...),
) -> Dict[str, Any]:
    if correction_type not in cr.SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported correction_type")
    return {"ok": True, "confidence": cr.confidence_score(correction_type, entity_key)}


@router.get("/explain", dependencies=[_auth])
def get_explanation(
    correction_type: str = Query(...),
    entity_key:      str = Query(...),
    limit:           int = Query(25, ge=1, le=500),
) -> Dict[str, Any]:
    """
    Provenance envelope for one (correction_type, entity_key). Any
    future prefill / suggestion surface MUST consume this so the
    operator can see exactly which historical decisions back the hint.
    """
    if correction_type not in cr.SUPPORTED_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported correction_type")
    return {"ok": True, "explanation": cr.explain_for(
        correction_type, entity_key, limit=limit)}


@router.get("/stats", dependencies=[_auth])
def get_stats() -> Dict[str, Any]:
    return {"ok": True, "stats": cr.stats_overview()}


@router.get("/types", dependencies=[_auth])
def list_types() -> Dict[str, Any]:
    return {"ok": True, "types": sorted(cr.SUPPORTED_TYPES)}
