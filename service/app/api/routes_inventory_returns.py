"""Returns write routes — Phase B.2.

  POST /api/v1/inventory/pieces/{piece_id}/return-from-client
       — Inbound: WAREHOUSE_STOCK | SAMPLE_OUT → RETURNED_FROM_CLIENT.

  POST /api/v1/inventory/pieces/{piece_id}/return-to-producer
       — Outbound: WAREHOUSE_STOCK | RETURNED_FROM_CLIENT
                   → RETURNED_TO_PRODUCER.

  POST /api/v1/inventory/pieces/{piece_id}/return-from-producer
       — Restock: RETURNED_TO_PRODUCER → WAREHOUSE_STOCK.

  POST /api/v1/inventory/pieces/{piece_id}/correction/identity
       — Correct product_code / design_no / batch_id (no state change).

  POST /api/v1/inventory/pieces/{piece_id}/correction/archive-proposal
       — Propose an over-scan / duplicate piece for archive (proposal only).

  GET  /api/v1/inventory/pieces/{piece_id}/corrections
       — Read-only correction audit timeline.

All endpoints require X-API-Key (router-level Depends(require_api_key))
and a caller-supplied `idempotency_key`. Replay returns the prior
event_id (same scan_code + idempotency_key). Correction/QC writes are
additionally role-gated (require_api_key_privileged) with a session-derived
operator — never client free-text.

Single-writer discipline preserved: this router never UPDATEs
inventory_state directly. All state changes via transition(); identity
corrections via inventory_state_engine.correct_identity() (a deliberate,
narrower single-writer sibling — see that function's docstring).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from ..core.config import settings
from ..core.security import require_api_key, require_api_key_privileged
from ..services.inventory_correction_writer import (
    CorrectionError,
    apply_identity_correction,
    propose_archive,
)
from ..services.inventory_qc_writer import QCError, apply_qc_disposition
from ..services.inventory_returns_writer import (
    ReturnsError,
    mark_returned_from_client,
    mark_returned_to_producer,
    return_from_producer_to_stock,
)

_qc_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def resolve_session_operator(
    key: Optional[str] = Security(_qc_key_header),
    pz_session: Optional[str] = Cookie(default=None),
) -> str:
    """Server-derive the operator identity for a privileged QC write.

    Operator is NEVER client-supplied free-text: it comes from the authenticated
    session (a named user) or, for trusted X-API-Key automation, a fixed system
    label. Anonymous callers are rejected (belt-and-suspenders with
    require_api_key_privileged). In dev (api_key unset) returns a dev label.
    """
    import hmac as _hmac  # noqa: PLC0415
    if key and settings.api_key and _hmac.compare_digest(
        key.encode("utf-8"), settings.api_key.encode("utf-8")
    ):
        return "system:api-key"
    if pz_session:
        from ..auth.dependencies import get_current_user_optional  # noqa: PLC0415
        user = get_current_user_optional(pz_session=pz_session)
        if user is not None:
            op = (user.get("username") or user.get("email")
                  or user.get("id") or "").strip()
            if op:
                return str(op)
    if not settings.api_key:
        return "dev-operator"  # dev only — auth disabled upstream
    raise HTTPException(status_code=401, detail="Authentication required")


router = APIRouter(
    prefix="/api/v1/inventory",
    tags=["inventory-returns"],
    dependencies=[Depends(require_api_key)],
)


class ReturnFromClientRequest(BaseModel):
    operator:           str = Field(..., min_length=1)
    return_reason:      str = Field(
        ..., min_length=1,
        description=(
            "Reason enum: warranty_claim, customer_refused, "
            "post_sample_review_reject, dimension_issue, "
            "quality_complaint, wrong_item_shipped, other"
        ),
    )
    origin_context:     str = Field(
        ..., min_length=1,
        description=(
            "Free-text origin pointer (RMA #, sales doc, sample event "
            "id, etc.). Required so the audit row is never anonymous."
        ),
    )
    received_at:        str = Field(
        ..., min_length=1,
        description="ISO 8601 timestamp; must not be in the future",
    )
    idempotency_key:    str = Field(..., min_length=1)
    source_holder_name: Optional[str] = Field(default="")
    notes:              Optional[str] = Field(default="")


class ReturnToProducerRequest(BaseModel):
    operator:                 str = Field(..., min_length=1)
    producer_name:            str = Field(..., min_length=1)
    idempotency_key:          str = Field(..., min_length=1)
    return_reason:            Optional[str] = Field(
        default="",
        description=(
            "Reason enum (one of defect, dimension_out_of_spec, "
            "quality_reject, post_inspection_reject, recall, other). "
            "Either reason or dispatch_reference must be supplied."
        ),
    )
    dispatch_reference:       Optional[str] = Field(
        default="",
        description="Outbound waybill / RMA ref",
    )
    producer_id:              Optional[str] = Field(default="")
    expected_resolution_date: Optional[str] = Field(
        default="",
        description="ISO 8601 date; if given, must be in the future",
    )
    notes:                    Optional[str] = Field(default="")


class ReturnFromProducerRequest(BaseModel):
    operator:        str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)
    notes:           Optional[str] = Field(default="")


_STATUS_FOR_CODE = {
    "INVALID_INPUT":     400,
    "PIECE_NOT_FOUND":   404,
    "WRONG_STATE":       409,
    "MIGRATION_PENDING": 503,
    "DB_UNAVAILABLE":    503,
    "DB_CONSTRAINT":     500,
}


def _map_returns_error(e: ReturnsError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR_CODE.get(e.code, 500),
        detail={"code": e.code, "detail": e.detail},
    )


class QCDispositionRequest(BaseModel):
    """QC disposition of a RETURNED_FROM_CLIENT piece. NOTE: no `operator`
    field — the operator is derived from the authenticated session, never
    accepted as client free-text."""
    decision:        str = Field(
        ..., min_length=1,
        description="One of: restock (→WAREHOUSE_STOCK), repair "
                    "(→RETURNED_TO_PRODUCER), write_off (→WRITTEN_OFF).",
    )
    condition:       Optional[str] = Field(default="")
    inspector:       Optional[str] = Field(default="")
    notes:           Optional[str] = Field(default="")
    # Required only for decision='repair' (RETURNED_TO_PRODUCER evidence).
    producer_name:      Optional[str] = Field(default="")
    dispatch_reference: Optional[str] = Field(default="")
    idempotency_key: str = Field(..., min_length=1)


def _map_qc_error(e: QCError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR_CODE.get(e.code, 500),
        detail={"code": e.code, "detail": e.message},
    )


class IdentityCorrectionRequest(BaseModel):
    """Correct product_code / design_no / batch_id on an existing piece. NOTE:
    no `operator` field — the operator is derived from the authenticated
    session, never accepted as client free-text. Omit a field (leave it
    unset/null) to leave it unchanged."""
    reason:          str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)
    product_code:    Optional[str] = Field(default=None)
    design_no:       Optional[str] = Field(default=None)
    batch_id:        Optional[str] = Field(default=None)


class ArchiveProposalRequest(BaseModel):
    """Propose an over-scan / duplicate piece for archive review. NOTE: no
    `operator` field — session-derived. Proposal only — never auto-applied,
    never a physical delete."""
    reason:          str = Field(..., min_length=1)
    idempotency_key: str = Field(..., min_length=1)


def _map_correction_error(e: CorrectionError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR_CODE.get(e.code, 500),
        detail={"code": e.code, "detail": e.message},
    )


@router.post(
    "/pieces/{piece_id}/qc-disposition",
    dependencies=[Depends(require_api_key_privileged)],
)
def post_qc_disposition(
    piece_id: str,
    payload: QCDispositionRequest,
    operator: str = Depends(resolve_session_operator),
) -> dict:
    """Records a QC disposition on a client-returned piece and drives its
    lifecycle transition via the single state writer. Privileged (role-gated);
    operator is session-derived. This is the backend for the Returns-tab
    Inspect actions (sr-btn-inspect / cr-btn-inspect).

    Decision → transition (only legal from RETURNED_FROM_CLIENT):
      restock → WAREHOUSE_STOCK · repair → RETURNED_TO_PRODUCER ·
      write_off → WRITTEN_OFF (terminal). No accounting / wFirma side effect.

    Errors:
      400 INVALID_INPUT
      403 role not permitted (require_api_key_privileged)
      404 PIECE_NOT_FOUND
      409 WRONG_STATE
      503 DB_UNAVAILABLE
    """
    try:
        return apply_qc_disposition(
            scan_code=piece_id,
            decision=payload.decision,
            operator=operator,
            idempotency_key=payload.idempotency_key,
            condition=payload.condition or "",
            inspector=payload.inspector or "",
            notes=payload.notes or "",
            producer_name=payload.producer_name or "",
            dispatch_reference=payload.dispatch_reference or "",
        )
    except QCError as e:
        raise _map_qc_error(e)


@router.get("/pieces/{piece_id}/qc-dispositions")
def get_qc_dispositions(piece_id: str) -> dict:
    """Read-only QC disposition history for a piece (newest first). Surfaces the
    recorded condition / inspector / decision / notes / producer_name /
    dispatch_reference / operator / disposed_at. Pure read — no mutation."""
    from ..services import warehouse_db as _wdb  # noqa: PLC0415
    return {
        "piece_id": piece_id,
        "dispositions": _wdb.get_qc_dispositions(piece_id),
    }


@router.post(
    "/pieces/{piece_id}/correction/identity",
    dependencies=[Depends(require_api_key_privileged)],
)
def post_identity_correction(
    piece_id: str,
    payload: IdentityCorrectionRequest,
    operator: str = Depends(resolve_session_operator),
) -> dict:
    """Correct product_code / design_no / batch_id on an existing piece
    (Inventory Correction Package A). Privileged (role-gated); operator is
    session-derived. Never changes lifecycle state, never writes Product
    Master, never touches inventory_state_events — an identity fix is not a
    lifecycle transition. Idempotent on (piece_id, idempotency_key).

    Errors:
      400 INVALID_INPUT
      403 role not permitted (require_api_key_privileged)
      404 PIECE_NOT_FOUND
      503 DB_UNAVAILABLE
    """
    try:
        return apply_identity_correction(
            scan_code=piece_id,
            operator=operator,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
            product_code=payload.product_code,
            design_no=payload.design_no,
            batch_id=payload.batch_id,
        )
    except CorrectionError as e:
        raise _map_correction_error(e)


@router.post(
    "/pieces/{piece_id}/correction/archive-proposal",
    dependencies=[Depends(require_api_key_privileged)],
)
def post_archive_proposal(
    piece_id: str,
    payload: ArchiveProposalRequest,
    operator: str = Depends(resolve_session_operator),
) -> dict:
    """Propose an over-scan / duplicate piece for archive review (case 6).
    Records a PROPOSAL only — never mutates inventory_state, never performs a
    physical delete. Privileged (role-gated); operator is session-derived.
    Idempotent on (piece_id, idempotency_key).

    Errors:
      400 INVALID_INPUT
      403 role not permitted (require_api_key_privileged)
      404 PIECE_NOT_FOUND
      503 DB_UNAVAILABLE
    """
    try:
        return propose_archive(
            scan_code=piece_id,
            operator=operator,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
        )
    except CorrectionError as e:
        raise _map_correction_error(e)


@router.get("/pieces/{piece_id}/corrections")
def get_corrections(piece_id: str) -> dict:
    """Read-only correction audit timeline for a piece (newest first).
    Surfaces old/new product_code, design_no, batch_id, reason, operator,
    status, created_at for every correction/archive-proposal. Pure read —
    no mutation."""
    from ..services import warehouse_db as _wdb  # noqa: PLC0415
    return {
        "piece_id": piece_id,
        "corrections": _wdb.get_corrections(piece_id),
    }


@router.post("/pieces/{piece_id}/return-from-client")
def post_return_from_client(
    piece_id: str, payload: ReturnFromClientRequest,
) -> dict:
    """Mark a piece as returned from a client into RMA.

    Errors:
      400 INVALID_INPUT, INVALID_EVIDENCE
      404 PIECE_NOT_FOUND
      409 WRONG_STATE
      503 DB_UNAVAILABLE, MIGRATION_PENDING
    """
    try:
        return mark_returned_from_client(
            scan_code=piece_id,
            operator=payload.operator,
            return_reason=payload.return_reason,
            origin_context=payload.origin_context,
            received_at=payload.received_at,
            idempotency_key=payload.idempotency_key,
            source_holder_name=payload.source_holder_name or "",
            notes=payload.notes or "",
        )
    except ReturnsError as e:
        raise _map_returns_error(e)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_EVIDENCE", "detail": str(e)},
        )


@router.post("/pieces/{piece_id}/return-to-producer")
def post_return_to_producer(
    piece_id: str, payload: ReturnToProducerRequest,
) -> dict:
    """Mark a piece as shipped back to the producer.

    Errors:
      400 INVALID_INPUT, INVALID_EVIDENCE
      404 PIECE_NOT_FOUND
      409 WRONG_STATE
      503 DB_UNAVAILABLE, MIGRATION_PENDING
    """
    try:
        return mark_returned_to_producer(
            scan_code=piece_id,
            operator=payload.operator,
            producer_name=payload.producer_name,
            idempotency_key=payload.idempotency_key,
            return_reason=payload.return_reason or "",
            dispatch_reference=payload.dispatch_reference or "",
            producer_id=payload.producer_id or "",
            expected_resolution_date=payload.expected_resolution_date or "",
            notes=payload.notes or "",
        )
    except ReturnsError as e:
        raise _map_returns_error(e)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_EVIDENCE", "detail": str(e)},
        )


@router.post("/pieces/{piece_id}/return-from-producer")
def post_return_from_producer(
    piece_id: str, payload: ReturnFromProducerRequest,
) -> dict:
    """Mark a producer-shipped piece as back in warehouse stock.

    Errors:
      400 INVALID_INPUT
      404 PIECE_NOT_FOUND
      409 WRONG_STATE
      503 DB_UNAVAILABLE, MIGRATION_PENDING
    """
    try:
        return return_from_producer_to_stock(
            scan_code=piece_id,
            operator=payload.operator,
            idempotency_key=payload.idempotency_key,
            notes=payload.notes or "",
        )
    except ReturnsError as e:
        raise _map_returns_error(e)


# ── C-3c: returns register read (Phase-C Wave 2 — backend only) ──────────────

_ALLOWED_RETURN_DIRECTIONS = {
    "from_client", "to_producer", "restock", "producer_restock",
    "producer_to_rma",
}


@router.get("/returns")
def list_returns(
    direction: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 500,
) -> dict:
    """List returns records from returns_events. 'to_producer' rows carry a
    resolution status ('open' until the linked producer_restock event lands,
    then 'resolved'); other directions are terminal evidence ('recorded').
    Read-only — never mutates inventory_state, never calls wFirma. Backs the
    Goods Return / Return to Producer wireframe tabs (UI wiring is Wave 3 / U-2).

    Query params:
      direction — one of from_client | to_producer | restock |
                  producer_restock | producer_to_rma (omit for all)
      status    — 'open' | 'resolved' | 'recorded' (omit for all)
      limit     — max rows scanned (1..2000, default 500)

    Errors:
      400 INVALID_INPUT (bad direction/status value)
      503 DB_UNAVAILABLE, MIGRATION_PENDING
    """
    from ..services import warehouse_db as wdb
    if wdb._db_path is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "DB_UNAVAILABLE", "detail": "warehouse_db not initialised"},
        )
    if not wdb.ensure_returns_schema():
        raise HTTPException(
            status_code=503,
            detail={"code": "MIGRATION_PENDING",
                    "detail": "returns_events migration not applied — run "
                              "draft_20260512_175238_returns_events"},
        )
    d = (direction or "").strip().lower() or None
    if d is not None and d not in _ALLOWED_RETURN_DIRECTIONS:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_INPUT",
                    "detail": f"direction must be one of "
                              f"{sorted(_ALLOWED_RETURN_DIRECTIONS)}"},
        )
    st = (status or "").strip().lower() or None
    if st not in (None, "open", "resolved", "recorded"):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_INPUT",
                    "detail": "status must be 'open', 'resolved' or 'recorded'"},
        )
    records = wdb.list_returns_records(direction=d, status=st, limit=limit)
    return {"ok": True, "count": len(records), "returns": records}
