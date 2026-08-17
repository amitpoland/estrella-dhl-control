"""
routes_treasury.py — Treasury balances, bank import, daily CFO close.

Write surfaces require reports.financial + role admin|accounts.
Never mutates wFirma. Additive treasury.sqlite only.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..auth.dependencies import require_permission, require_role
from ..services.bank_statement_import import (
    confirm_import_batch,
    parse_csv_balances,
    parse_xlsx_balances,
    save_preview_batch,
)
from ..services.treasury_db import (
    BalanceSnapshot,
    CLOSE_STATUSES,
    SOURCE_TYPES,
    insert_balance_snapshot,
    insert_daily_close,
    latest_balances_as_of,
    treasury_db_path,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/treasury", tags=["treasury"])

_auth = Depends(require_permission("reports.financial"))
_writer = Depends(require_role("admin", "accounts"))


def _db() -> Path:
    from ..core.config import settings
    return treasury_db_path(Path(settings.storage_root))


def _operator_from_user(user: dict) -> str:
    """Session-derived audit attribution (never a hardcoded 'api')."""
    for key in ("email", "username", "id", "sub"):
        raw = user.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()[:120]
    return "unknown"


class ManualBalanceBody(BaseModel):
    effective_date: str
    account_location: str
    currency: str
    closing_balance: str
    reference_note: str = ""
    correction_of_id: Optional[int] = None


class DailyCloseBody(BaseModel):
    close_date: str
    status: str = Field(..., description="INCOMPLETE|READY_TO_CLOSE|CLOSED|CORRECTED")
    bank_balances_ok: bool = False
    cash_captured_ok: bool = False
    ar_refreshed_ok: bool = False
    ap_refreshed_ok: bool = False
    statements_ok: bool = False
    exceptions_reviewed: bool = False
    notes: str = ""
    correction_of_id: Optional[int] = None


@router.get("/balances", dependencies=[_auth])
def get_balances(as_of: str = Query(..., description="YYYY-MM-DD")) -> JSONResponse:
    if len(as_of) != 10 or as_of[4] != "-" or as_of[7] != "-":
        raise HTTPException(status_code=400, detail="as_of must be YYYY-MM-DD")
    rows = latest_balances_as_of(_db(), as_of)
    return JSONResponse({
        "as_of": as_of,
        "count": len(rows),
        "rows": rows,
        "source": "treasury.sqlite",
        "authority": "local_treasury_projection",
    })


@router.post("/balances/manual", dependencies=[_auth])
def post_manual_balance(
    body: ManualBalanceBody,
    user: dict = _writer,
) -> JSONResponse:
    try:
        bal = Decimal(str(body.closing_balance).replace(",", "."))
    except (InvalidOperation, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid closing_balance: {exc}") from exc
    op = _operator_from_user(user)
    try:
        row_id = insert_balance_snapshot(
            _db(),
            BalanceSnapshot(
                effective_date=body.effective_date,
                account_location=body.account_location.strip(),
                currency=body.currency.strip().upper(),
                closing_balance=bal,
                source="MANUAL",
                operator=op,
                reference_note=body.reference_note or None,
                correction_of_id=body.correction_of_id,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"ok": True, "id": row_id, "source": "MANUAL", "operator": op})


@router.post("/imports/preview", dependencies=[_auth])
async def preview_bank_import(
    file: UploadFile = File(...),
    default_account: str = Form(""),
    user: dict = _writer,
) -> JSONResponse:
    raw = await file.read()
    name = file.filename or "upload"
    lower = name.lower()
    if lower.endswith(".csv"):
        preview = parse_csv_balances(raw, filename=name, default_account=default_account)
    elif lower.endswith(".xlsx") or lower.endswith(".xls"):
        preview = parse_xlsx_balances(raw, filename=name, default_account=default_account)
    else:
        raise HTTPException(status_code=400, detail="supported formats: CSV, XLSX")
    op = _operator_from_user(user)
    save_preview_batch(_db(), preview, uploaded_by=op)
    return JSONResponse(preview.to_dict())


@router.post("/imports/{batch_id}/confirm", dependencies=[_auth])
def confirm_bank_import(
    batch_id: str,
    user: dict = _writer,
) -> JSONResponse:
    op = _operator_from_user(user)
    try:
        result = confirm_import_batch(_db(), batch_id, operator=op)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result)


@router.post("/daily-close", dependencies=[_auth])
def post_daily_close(
    body: DailyCloseBody,
    user: dict = _writer,
) -> JSONResponse:
    if body.status not in CLOSE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {CLOSE_STATUSES}",
        )
    op = _operator_from_user(user)
    try:
        row_id = insert_daily_close(
            _db(),
            close_date=body.close_date,
            status=body.status,
            bank_balances_ok=body.bank_balances_ok,
            cash_captured_ok=body.cash_captured_ok,
            ar_refreshed_ok=body.ar_refreshed_ok,
            ap_refreshed_ok=body.ap_refreshed_ok,
            statements_ok=body.statements_ok,
            exceptions_reviewed=body.exceptions_reviewed,
            closed_by=op,
            correction_of_id=body.correction_of_id,
            notes=body.notes or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"ok": True, "id": row_id, "status": body.status, "closed_by": op})


@router.get("/meta", dependencies=[_auth])
def treasury_meta() -> JSONResponse:
    return JSONResponse({
        "source_types": list(SOURCE_TYPES),
        "close_statuses": list(CLOSE_STATUSES),
        "import_formats": ["CSV", "XLSX"],
        "authority": "local_treasury_projection",
        "wfirma_writes": False,
    })
