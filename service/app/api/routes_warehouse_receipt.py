"""
routes_warehouse_receipt.py — Warehouse receipt quantity confirmation (WAREHOUSE authority).

Endpoints
---------
  GET  /api/v1/warehouse/receipt/{batch_id}
       Per-line expected vs confirmed quantities + batch summary.

  POST /api/v1/warehouse/receipt/confirm
       Operator confirms received quantities by line/batch. Expected quantity is
       resolved from the import packing authority (never trusted from the client),
       so shortage/overage are authoritative. Operator + timestamp + source docs
       are persisted as an audit trail. This is the warehouse-receipt signal that
       replaces mandatory per-piece scanning (scan stays optional traceability
       unless the shipment is serial_controlled).

This endpoint writes to a LOCAL operational store only. It performs NO wFirma /
fiscal write — it records the operator's physical-receipt confirmation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.security import require_api_key
from ..services import warehouse_receipt as wrcpt

router = APIRouter(prefix="/api/v1/warehouse/receipt", tags=["warehouse"])
_auth  = Depends(require_api_key)


@router.get("/{batch_id:path}", dependencies=[_auth])
def receipt_status(batch_id: str) -> JSONResponse:
    """Per-line expected/confirmed quantities + batch receipt summary."""
    return JSONResponse({"ok": True, **wrcpt.get_receipt_status(batch_id)})


class ReceiptLine(BaseModel):
    line_key:     Optional[str] = None
    invoice_no:   Optional[str] = None
    invoice_line_position: Optional[str] = None
    design_no:    Optional[str] = None
    product_code: Optional[str] = None
    accepted_qty: float
    note:         Optional[str] = ""


class ConfirmReceiptRequest(BaseModel):
    batch_id:         str
    lines:            List[ReceiptLine]
    source_documents: Optional[List[str]] = None


@router.post("/confirm", dependencies=[_auth])
def confirm_receipt(
    req: ConfirmReceiptRequest,
    x_operator: str = Header(default="", alias="X-Operator"),
) -> JSONResponse:
    """Confirm received quantities for one or more lines."""
    lines: List[Dict[str, Any]] = [ln.model_dump() for ln in req.lines]
    result = wrcpt.confirm_receipt(
        req.batch_id,
        lines,
        operator=(x_operator or "operator"),
        source_documents=req.source_documents,
    )
    return JSONResponse({"ok": True, **result})
