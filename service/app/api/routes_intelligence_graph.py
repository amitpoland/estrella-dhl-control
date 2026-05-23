"""Intelligence Graph router -- Phase 8 Sprint 2.

GET /api/v1/intelligence/graph

Returns a GraphResult for any batch_id anchor (or anchors that resolve to a
batch_id via a single read-only lookup).

Anchor types:
  batch    -- anchor IS the batch_id (default; no resolution lookup needed)
  awb      -- anchor is an AWB number; resolved to batch_id via documents.db
  customer -- anchor is a customer name; resolved to batch_id via documents.db
  invoice  -- anchor is an invoice reference; resolved to batch_id via documents.db

Builders (which graph builder to call):
  batch    -- build_batch_graph  (default; cross-DB full graph)
  awb      -- build_awb_graph    (AWB + tracking events)
  customer -- build_customer_graph (customer + contractor resolution)
  invoice  -- build_invoice_graph  (invoice lines + customs + PZ)

All combinations of anchor_type x builder are valid.
Resolution happens first; the resolved batch_id is then passed to the builder.

Design rules:
  - GET-only, no writes
  - llm_used=False in every response (structural invariant)
  - All DB connections via _ro_conn() + PRAGMA query_only = ON (in service layer)
  - 422 on invalid anchor_type or builder
  - 404 when anchor resolution yields no matching batch
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key

log = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/intelligence",
    tags=["intelligence-graph"],
)

_auth = Depends(require_api_key)

_VALID_ANCHOR_TYPES = {"batch", "awb", "customer", "invoice"}
_VALID_BUILDERS     = {"batch", "awb", "customer", "invoice"}

_DOC_DB = settings.storage_root / "documents.db"


# ── Private anchor resolvers (read-only lookups) ──────────────────────────────

def _resolve_by_awb(anchor: str, doc_db: Optional[Path] = None) -> Optional[str]:
    """Return the first batch_id whose documents match this AWB. None if not found."""
    db_path = doc_db or _DOC_DB
    if not db_path.exists():
        return None
    try:
        con = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only = ON")
        row = con.execute(
            "SELECT batch_id FROM shipment_documents WHERE awb = ? AND batch_id != '' LIMIT 1",
            (anchor,),
        ).fetchone()
        con.close()
        if row:
            return row["batch_id"]
    except Exception as exc:  # noqa: BLE001
        log.debug("[graph-route] _resolve_by_awb: %s", exc)
    return None


def _resolve_by_customer(anchor: str, doc_db: Optional[Path] = None) -> Optional[str]:
    """Return the first batch_id whose documents reference this customer name (LIKE).

    Checks client_contractor_id exact match first, then falls back to customer
    field if present.  Documents.db does not store a free-text customer name
    directly, so we search by client_contractor_id exact match.
    """
    db_path = doc_db or _DOC_DB
    if not db_path.exists():
        return None
    try:
        con = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only = ON")
        row = con.execute(
            """
            SELECT batch_id FROM shipment_documents
            WHERE client_contractor_id = ? AND batch_id != ''
            LIMIT 1
            """,
            (anchor,),
        ).fetchone()
        con.close()
        if row:
            return row["batch_id"]
    except Exception as exc:  # noqa: BLE001
        log.debug("[graph-route] _resolve_by_customer: %s", exc)
    return None


def _resolve_by_invoice(anchor: str, doc_db: Optional[Path] = None) -> Optional[str]:
    """Return the first batch_id whose documents reference this invoice number."""
    db_path = doc_db or _DOC_DB
    if not db_path.exists():
        return None
    try:
        con = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only = ON")
        row = con.execute(
            """
            SELECT batch_id FROM shipment_documents
            WHERE related_invoice_no = ? AND batch_id != ''
            LIMIT 1
            """,
            (anchor,),
        ).fetchone()
        con.close()
        if row:
            return row["batch_id"]
    except Exception as exc:  # noqa: BLE001
        log.debug("[graph-route] _resolve_by_invoice: %s", exc)
    return None


# ── Route ─────────────────────────────────────────────────────────────────────

@router.get(
    "/graph",
    dependencies=[_auth],
    summary="Intelligence graph for any batch anchor",
    description=(
        "Returns the authority-attributed intelligence graph for a shipment batch. "
        "anchor_type controls how the anchor value maps to a batch_id (batch/awb/"
        "customer/invoice). builder controls which graph builder to call "
        "(batch/awb/customer/invoice). "
        "llm_used=False -- deterministic only. No writes."
    ),
)
def get_graph(
    anchor:      str = Query(..., min_length=1, description="Anchor value (batch_id, AWB, customer id, or invoice ref)"),
    anchor_type: str = Query("batch", description="How anchor maps to batch_id: batch | awb | customer | invoice"),
    builder:     str = Query("batch", description="Graph builder to invoke: batch | awb | customer | invoice"),
) -> JSONResponse:

    # ── Validate params ───────────────────────────────────────────────────────
    if anchor_type not in _VALID_ANCHOR_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid anchor_type '{anchor_type}'. Valid: {sorted(_VALID_ANCHOR_TYPES)}",
        )
    if builder not in _VALID_BUILDERS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid builder '{builder}'. Valid: {sorted(_VALID_BUILDERS)}",
        )

    # ── Resolve anchor to batch_id ────────────────────────────────────────────
    if anchor_type == "batch":
        batch_id = anchor
    elif anchor_type == "awb":
        batch_id = _resolve_by_awb(anchor)
        if batch_id is None:
            raise HTTPException(
                status_code=404,
                detail=f"No batch found for AWB '{anchor}'",
            )
    elif anchor_type == "customer":
        batch_id = _resolve_by_customer(anchor)
        if batch_id is None:
            raise HTTPException(
                status_code=404,
                detail=f"No batch found for customer id '{anchor}'",
            )
    else:  # invoice
        batch_id = _resolve_by_invoice(anchor)
        if batch_id is None:
            raise HTTPException(
                status_code=404,
                detail=f"No batch found for invoice ref '{anchor}'",
            )

    # ── Dispatch to builder ───────────────────────────────────────────────────
    try:
        from ..services.intelligence_graph import (
            build_awb_graph,
            build_batch_graph,
            build_customer_graph,
            build_invoice_graph,
        )

        if builder == "awb":
            result = build_awb_graph(batch_id)
        elif builder == "customer":
            result = build_customer_graph(batch_id)
        elif builder == "invoice":
            result = build_invoice_graph(batch_id)
        else:  # batch (default)
            result = build_batch_graph(batch_id)

        return JSONResponse(content=result.to_dict())

    except HTTPException:
        raise
    except Exception as exc:
        log.error(
            "[graph-route] get_graph(%s, anchor_type=%s, builder=%s) failed: %s",
            anchor, anchor_type, builder, exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Intelligence graph build failed")
