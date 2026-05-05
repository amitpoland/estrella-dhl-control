"""
routes_reservations.py — Reservation queue API endpoints.

Router prefix: /api/v1
Auth: same _auth dependency as all other routes.

Endpoints
---------
POST /api/v1/products/import-purchase-packing
POST /api/v1/reservations/import-sales-packing
GET  /api/v1/reservations/queue
POST /api/v1/wfirma/products/sync-by-codes
POST /api/v1/reservations/process-pending
POST /api/v1/reservations/{queue_id}/reset
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..core.config import settings
from ..core.logging import get_logger
from ..core.security import require_api_key
from ..services import reservation_db as rdb
from ..services import reservation_worker as rworker

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["reservations"])
_auth  = Depends(require_api_key)


def _db_path() -> Path:
    return settings.storage_root / "reservation_queue.db"


def _ensure_db() -> Path:
    db = _db_path()
    rdb.init_reservation_db(db)
    return db


# ── Request/Response models ───────────────────────────────────────────────────

class PurchasePackingLine(BaseModel):
    design_no:    str
    product_code: str
    description:  str = ""
    metal:        str = ""
    category:     str = ""


class ImportPurchasePackingBody(BaseModel):
    batch_id:   str
    invoice_no: str = ""
    lines:      List[PurchasePackingLine] = Field(default_factory=list)


class SalesPackingLine(BaseModel):
    design_no:  str
    qty:        float
    unit_price: float = 0.0
    currency:   str   = "USD"


class ImportSalesPackingBody(BaseModel):
    batch_id:     str
    client_name:  str
    client_ref:   str = ""
    sales_doc_no: str = ""
    lines:        List[SalesPackingLine] = Field(default_factory=list)


class SyncByCodesBody(BaseModel):
    product_codes: List[str]


class ProcessPendingBody(BaseModel):
    batch_id: Optional[str] = None
    mode:     str            = "dry_run"   # "dry_run" | "live"


class ResetQueueRowBody(BaseModel):
    target_status: str = "pending"   # "pending" | "failed"
    reason:        str = ""


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/products/import-purchase-packing", dependencies=[_auth])
async def import_purchase_packing(body: ImportPurchasePackingBody) -> JSONResponse:
    """
    Import a purchase packing list.
    Creates product_master + design_product_mapping rows.
    """
    db = _ensure_db()
    payload = {
        "batch_id":   body.batch_id,
        "invoice_no": body.invoice_no,
        "lines": [
            {
                "design_no":    ln.design_no,
                "product_code": ln.product_code,
                "description":  ln.description,
                "metal":        ln.metal,
                "category":     ln.category,
            }
            for ln in body.lines
        ],
    }
    result = rworker.import_purchase_packing(db, payload)
    return JSONResponse(result)


@router.post("/reservations/import-sales-packing", dependencies=[_auth])
async def import_sales_packing(body: ImportSalesPackingBody) -> JSONResponse:
    """
    Import a sales packing list.
    Creates reservation_queue rows (status=pending or blocked).
    """
    db = _ensure_db()
    payload = {
        "batch_id":     body.batch_id,
        "client_name":  body.client_name,
        "client_ref":   body.client_ref,
        "sales_doc_no": body.sales_doc_no,
        "lines": [
            {
                "design_no":  ln.design_no,
                "qty":        ln.qty,
                "unit_price": ln.unit_price,
                "currency":   ln.currency,
            }
            for ln in body.lines
        ],
    }
    result = rworker.import_sales_packing(db, payload)
    return JSONResponse(result)


@router.get("/reservations/queue", dependencies=[_auth])
async def get_reservation_queue(
    batch_id: Optional[str] = Query(default=None),
    status:   Optional[str] = Query(default=None),
) -> JSONResponse:
    """Return reservation queue rows, optionally filtered by batch_id and/or status."""
    db   = _ensure_db()
    rows = rdb.list_reservation_queue(db, status=status, batch_id=batch_id)
    return JSONResponse({"count": len(rows), "rows": rows})


@router.post("/wfirma/products/sync-by-codes", dependencies=[_auth])
async def sync_products_by_codes(body: SyncByCodesBody) -> JSONResponse:
    """
    Exact-code search in wFirma for each product_code.
    Updates wfirma_product_mapping. Never creates products in wFirma.
    """
    from ..services.wfirma_client import get_product_by_code as _get

    class _ClientShim:
        """Thin shim so the worker can call client.get_product_by_code()."""
        @staticmethod
        def get_product_by_code(code: str):
            return _get(code)

    db     = _ensure_db()
    result = rworker.sync_wfirma_products_by_codes(db, _ClientShim(), body.product_codes)
    return JSONResponse(result)


@router.post("/reservations/process-pending", dependencies=[_auth])
async def process_pending_reservations(body: ProcessPendingBody) -> JSONResponse:
    """
    Process ready reservations.
    mode='dry_run' returns would_create count without calling wFirma.
    mode='live' creates reservations in wFirma.
    """
    if body.mode not in ("dry_run", "live"):
        raise HTTPException(status_code=422, detail="mode must be 'dry_run' or 'live'")

    from ..services.wfirma_client import create_reservation as _create

    class _ClientShim:
        @staticmethod
        def create_reservation(req):
            return _create(req)

    db     = _ensure_db()
    result = rworker.process_ready_reservations(
        db, _ClientShim(),
        batch_id=body.batch_id,
        mode=body.mode,
    )
    return JSONResponse(result)


@router.post("/reservations/{queue_id}/reset", dependencies=[_auth])
async def reset_queue_row(queue_id: int, body: ResetQueueRowBody) -> JSONResponse:
    """
    Reset a queue row to a target status (pending or failed).
    Useful for retrying failed rows or unsticking stuck rows.
    """
    if body.target_status not in ("pending", "failed"):
        raise HTTPException(status_code=422, detail="target_status must be 'pending' or 'failed'")

    db  = _ensure_db()
    row = rdb.get_reservation_queue_row(db, queue_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Queue row {queue_id} not found")

    rdb.update_queue_status(
        db,
        row_id=queue_id,
        status=body.target_status,
        blocking_reason=body.reason or "",
        last_error="",
    )

    return JSONResponse({
        "ok":         True,
        "queue_id":   queue_id,
        "new_status": body.target_status,
    })
