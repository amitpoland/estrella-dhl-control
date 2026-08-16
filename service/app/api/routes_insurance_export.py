"""Insurance Export Statement routes — read-only declaration composer.

GET  /api/v1/accounting/insurance-export            — full factual report
POST /api/v1/accounting/insurance-export/declaration-preview
POST /api/v1/accounting/insurance-export/declaration.pdf
POST /api/v1/accounting/insurance-export/charge-convergence/run
GET  /api/v1/accounting/insurance-export/charge-convergence/status

The three report/declaration routes are READ-ONLY against every authority:
no wFirma writes, no proforma writes, no shipment writes. Selection is
ephemeral (IDs only); the server re-resolves all monetary values from
canonical facts on every request — the browser never sends amounts.

The charge-convergence pair is the operator surface for the capability that
keeps the recovered-premium authority converged with the issued documents
(services/commercial_charge_convergence.py). wFirma stays READ-ONLY there
too; only the local charge record is written, only in apply mode, and only
when the operator has armed COMMERCIAL_CHARGE_CONVERGENCE_APPLY_ENABLED.

Auth: reports.financial (same guard as the ledgers/statement family).
PDF route carries Lesson G no-store headers (regenerable artifact).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from ..auth.dependencies import require_permission
from ..core.config import settings
from ..core.logging import get_logger
from ..services.commercial_charge_convergence import (
    ChargeConvergenceError,
    ChargeConvergenceWriteDenied,
    get_status as get_charge_convergence_status,
    run_charge_convergence,
)
from ..services.insurance_export_statement import (
    InsuranceExportFetchError,
    UnknownSelectionError,
    assemble_insurance_export_report,
    resolve_declaration_selection,
)

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1/accounting", tags=["insurance-export"])
_auth = Depends(require_permission("reports.financial"))

_DATE_LEN = len("YYYY-MM-DD")

# Lesson G: regenerable generated artifact — downloads must never be cached.
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _proforma_db_path() -> Path:
    return settings.storage_root / "proforma_links.db"


def _carrier_db_path() -> Path:
    # Canonical carrier store — matches routes_carrier_actions/_get_shipment_db_path.
    root = settings.carrier_storage_root or (settings.storage_root / "carrier")
    return root / "carrier_shipments.db"


def _validate_date(label: str, value: str) -> str:
    s = (value or "").strip()
    ok = (
        len(s) == _DATE_LEN
        and s[4] == "-"
        and s[7] == "-"
        and s[:4].isdigit()
        and s[5:7].isdigit()
        and s[8:10].isdigit()
    )
    if not ok:
        raise HTTPException(
            status_code=400, detail=f"{label} must be YYYY-MM-DD, got {value!r}"
        )
    return s


def _validate_period(date_from: str, date_to: str) -> "tuple":
    df = _validate_date("from", date_from)
    dt = _validate_date("to", date_to)
    if df > dt:
        raise HTTPException(
            status_code=400, detail=f"from {df!r} is after to {dt!r}"
        )
    return df, dt


def _id_list(value: Any, label: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail=f"{label} must be a list")
    return [str(v) for v in value]


@router.get("/insurance-export", dependencies=[_auth])
def get_insurance_export(
    date_from: str = Query(..., alias="from"),
    date_to: str = Query(..., alias="to"),
    refresh: int = Query(0),
) -> JSONResponse:
    df, dt = _validate_period(date_from, date_to)
    try:
        report = assemble_insurance_export_report(
            df,
            dt,
            db_path=_proforma_db_path(),
            carrier_db_path=_carrier_db_path(),
            force=bool(refresh),
        )
    except InsuranceExportFetchError as exc:
        log.warning("insurance-export fetch failed: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"code": "INSURANCE_EXPORT_FETCH_FAILED", "detail": str(exc)},
        )
    return JSONResponse(content=report)


@router.post("/insurance-export/declaration-preview", dependencies=[_auth])
def post_declaration_preview(payload: Dict[str, Any] = Body(...)) -> JSONResponse:
    df, dt = _validate_period(
        str(payload.get("period_from") or ""), str(payload.get("period_to") or "")
    )
    doc_ids = _id_list(payload.get("selected_document_ids"), "selected_document_ids")
    adj_ids = _id_list(
        payload.get("selected_adjustment_ids"), "selected_adjustment_ids"
    )
    try:
        selection = resolve_declaration_selection(
            df,
            dt,
            doc_ids,
            adj_ids,
            db_path=_proforma_db_path(),
            carrier_db_path=_carrier_db_path(),
        )
    except UnknownSelectionError as exc:
        return JSONResponse(
            status_code=422,
            content={"code": "UNKNOWN_IDS", "unknown": exc.unknown},
        )
    except InsuranceExportFetchError as exc:
        log.warning("insurance-export preview fetch failed: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"code": "INSURANCE_EXPORT_FETCH_FAILED", "detail": str(exc)},
        )
    return JSONResponse(content=selection)


@router.post("/insurance-export/declaration.pdf", dependencies=[_auth])
def post_declaration_pdf(payload: Dict[str, Any] = Body(...)) -> Response:
    df, dt = _validate_period(
        str(payload.get("period_from") or ""), str(payload.get("period_to") or "")
    )
    doc_ids = _id_list(payload.get("selected_document_ids"), "selected_document_ids")
    adj_ids = _id_list(
        payload.get("selected_adjustment_ids"), "selected_adjustment_ids"
    )
    include_adjustments = bool(payload.get("include_adjustments", True))
    columns = payload.get("columns") or {}
    if not isinstance(columns, dict):
        raise HTTPException(status_code=400, detail="columns must be an object")
    try:
        selection = resolve_declaration_selection(
            df,
            dt,
            doc_ids,
            adj_ids,
            db_path=_proforma_db_path(),
            carrier_db_path=_carrier_db_path(),
        )
    except UnknownSelectionError as exc:
        return JSONResponse(
            status_code=422,
            content={"code": "UNKNOWN_IDS", "unknown": exc.unknown},
        )
    except InsuranceExportFetchError as exc:
        log.warning("insurance-export pdf fetch failed: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"code": "INSURANCE_EXPORT_FETCH_FAILED", "detail": str(exc)},
        )

    # Import here so a ReportLab/font problem degrades only the PDF route.
    from ..services.insurance_export_pdf_renderer import (
        render_insurance_export_statement_pdf,
    )

    pdf_bytes = render_insurance_export_statement_pdf(
        None,
        selected_rows=selection["selected_rows"],
        selected_adjustments=selection["selected_adjustments"],
        declaration_totals=selection["declaration_totals"],
        period=selection["period"],
        columns=columns,
        include_adjustments=include_adjustments,
    )
    filename = "insurance-export-%s-%s.pdf" % (df, dt)
    headers = dict(_NO_STORE_HEADERS)
    headers["Content-Disposition"] = 'attachment; filename="%s"' % filename
    return Response(
        content=pdf_bytes, media_type="application/pdf", headers=headers
    )


@router.post("/insurance-export/charge-convergence/run")
def post_charge_convergence_run(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    user: Optional[Dict[str, Any]] = Depends(require_permission("reports.financial")),
) -> JSONResponse:
    """Run Now — reconcile the charge authority against the issued documents.

    Body (all optional): ``{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD",
    "months": 2, "apply": false}``. Dry run is the default; ``apply`` is
    refused with 409 unless the operator has armed the write gate. The
    response carries the full reconciliation artifact so a dry run IS the
    review document — nothing has to be written to see what would change.
    """
    body = payload or {}
    date_from = str(body.get("from") or "").strip() or None
    date_to = str(body.get("to") or "").strip() or None
    if date_from or date_to:
        if not (date_from and date_to):
            raise HTTPException(status_code=400, detail="from and to must be given together")
        date_from, date_to = _validate_period(date_from, date_to)

    months = body.get("months")
    if months is not None:
        try:
            months = int(months)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="months must be an integer")
        if not 1 <= months <= 120:
            raise HTTPException(status_code=400, detail="months must be between 1 and 120")

    try:
        summary = run_charge_convergence(
            date_from=date_from,
            date_to=date_to,
            months=months,
            apply=bool(body.get("apply")),
            operator=str((user or {}).get("email") or (user or {}).get("username")
                         or (user or {}).get("auth") or "operator"),
        )
    except ChargeConvergenceWriteDenied as exc:
        return JSONResponse(
            status_code=409,
            content={"code": "CHARGE_CONVERGENCE_WRITE_DISABLED", "detail": str(exc)},
        )
    except ChargeConvergenceError as exc:
        log.warning("charge-convergence run failed: %s", exc)
        return JSONResponse(
            status_code=502,
            content={"code": "CHARGE_CONVERGENCE_FAILED", "detail": str(exc),
                     "summary": exc.summary},
        )
    return JSONResponse(content=summary, headers=dict(_NO_STORE_HEADERS))


@router.get("/insurance-export/charge-convergence/status", dependencies=[_auth])
def get_charge_convergence_run_status() -> JSONResponse:
    """The four questions: healthy / when / what happened / can I run it now."""
    return JSONResponse(
        content=get_charge_convergence_status(), headers=dict(_NO_STORE_HEADERS)
    )


__all__ = ["router"]
