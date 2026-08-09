"""
Accounting document reads — P0 Accounting Hub normalization.

Endpoints
---------
  GET /api/v1/accounting/documents/{doc_type}
      doc_type ∈ {invoice, credit_note, wz, pz, pw, rw}
      MM → 404 (controller not found live — unavailable, not pending)
  GET /api/v1/accounting/documents/{doc_type}/{wfirma_id}/pdf
      Invoice / Credit Note only — delegates to fetch_invoice_pdf.
      disposition=inline|attachment

Authority: wFirma. Read-only. No local accounting mirror. No writes.
Normalization boundary: accounting_documents (top-level XML only).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from ..core.security import require_api_key
from ..services import wfirma_client
from ..services.accounting_documents import (
    WAREHOUSE_TYPES_BLOCKED,
    WAREHOUSE_TYPES_SUPPORTED,
)

router = APIRouter(prefix="/api/v1/accounting", tags=["accounting"])

_auth = Depends(require_api_key)

_INVOICE_DOC_TYPES = {
    "invoice": "normal",
    "credit_note": "correction",
}

_WAREHOUSE_DOC_TYPES = {t.lower(): t for t in WAREHOUSE_TYPES_SUPPORTED}

_NO_STORE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


@router.get("/documents/{doc_type}", dependencies=[_auth])
def list_accounting_documents(
    doc_type: str,
    page: int = Query(1, ge=1, description="1-indexed page; page 1 = newest"),
    limit: int = Query(15, ge=1, le=200),
    year: Optional[str] = Query(
        None,
        description="Calendar year (default=current). Pass 'all' for All Years.",
    ),
    sort: str = Query("date_desc"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    start: Optional[int] = Query(
        None,
        ge=0,
        description="Legacy row offset; ignored when page is provided.",
    ),
) -> dict:
    """One page of normalized accounting documents from wFirma.

    Shared register contract: year + page + limit + sort=date_desc.
    Invoice/CN → invoices/find. Warehouse WZ/PZ/PW/RW → warehouse_documents/find.
    MM is blocked (404) — live controller check failed.
    """
    from ..services.accounting_register_paging import (
        enrich_years_available,
        parse_register_paging,
    )

    key = (doc_type or "").strip().lower()
    paging = parse_register_paging(
        page=page,
        limit=limit,
        year=year,
        sort=sort,
        date_from=date_from,
        date_to=date_to,
    )
    # Legacy start= offset (tests / old clients) maps to page when page==1 default
    # and start was explicitly provided.
    call_page = paging["page"]
    if start is not None and page == 1 and start > 0:
        call_page = (start // paging["limit"]) + 1

    if key in WAREHOUSE_TYPES_BLOCKED or key == "mm":
        raise HTTPException(
            status_code=404,
            detail=(
                "MM warehouse transfers are unavailable: wFirma controller "
                "warehouse_document_m_m / _mm was not found (live check 2026-08-09). "
                "Not implemented — do not treat as Backend Pending."
            ),
        )

    meta = {
        "page": call_page,
        "limit": paging["limit"],
        "year": paging["year"],
        "all_years": paging["all_years"],
        "sort": paging["sort"],
        "date_from": paging["date_from"],
        "date_to": paging["date_to"],
        "years_available": paging["years_available"],
    }

    if key in _INVOICE_DOC_TYPES:
        wfirma_type = _INVOICE_DOC_TYPES[key]
        try:
            result = wfirma_client.list_invoices_by_type(
                wfirma_type,
                limit=paging["limit"],
                page=call_page,
                date_from=paging["date_from"],
                date_to=paging["date_to"],
                sort=paging["sort"],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (RuntimeError, ConnectionError) as exc:
            raise HTTPException(status_code=502, detail=f"wFirma read failed: {exc}") from exc
        years = enrich_years_available(
            paging["years_available"], result.get("rows") or []
        )
        return {
            "doc_type": key,
            "authority": "wfirma.invoices",
            "wfirma_type": wfirma_type,
            **meta,
            "years_available": years,
            **result,
            "page": call_page,
            "limit": paging["limit"],
        }

    if key in _WAREHOUSE_DOC_TYPES:
        wh_type = _WAREHOUSE_DOC_TYPES[key]
        try:
            result = wfirma_client.list_warehouse_documents_by_type(
                wh_type,
                limit=paging["limit"],
                page=call_page,
                date_from=paging["date_from"],
                date_to=paging["date_to"],
                sort=paging["sort"],
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (RuntimeError, ConnectionError) as exc:
            raise HTTPException(status_code=502, detail=f"wFirma read failed: {exc}") from exc
        years = enrich_years_available(
            paging["years_available"], result.get("rows") or []
        )
        return {
            "doc_type": key,
            "authority": "wfirma.warehouse_documents",
            "warehouse_type": wh_type,
            **meta,
            "years_available": years,
            **result,
            "page": call_page,
            "limit": paging["limit"],
        }

    raise HTTPException(
        status_code=404,
        detail=(
            f"Unsupported accounting document type '{doc_type}'. "
            "Supported: invoice, credit_note, wz, pz, pw, rw. "
            "MM is unavailable (controller not found)."
        ),
    )


@router.get("/documents/{doc_type}/{wfirma_id}/pdf", dependencies=[_auth])
def get_accounting_document_pdf(
    doc_type: str,
    wfirma_id: str,
    disposition: str = Query("inline", pattern="^(inline|attachment)$"),
) -> Response:
    """Official Invoice/CN PDF via existing fetch_invoice_pdf authority.

    Warehouse PDF is not exposed — standalone warehouse download is unproven.
    """
    key = (doc_type or "").strip().lower()
    if key not in _INVOICE_DOC_TYPES:
        raise HTTPException(
            status_code=404,
            detail=(
                "PDF proxy is available only for invoice and credit_note. "
                "Warehouse document PDF is unproven and not exposed."
            ),
        )
    iid = (wfirma_id or "").strip()
    if not iid or not iid.isdigit():
        raise HTTPException(status_code=400, detail="wfirma_id must be a numeric id")
    try:
        pdf_bytes = wfirma_client.fetch_invoice_pdf(iid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, ConnectionError) as exc:
        raise HTTPException(status_code=502, detail=f"wFirma PDF fetch failed: {exc}") from exc
    if len(pdf_bytes) < 200:
        raise HTTPException(
            status_code=502,
            detail=f"wFirma returned an unusably small PDF ({len(pdf_bytes)} bytes)",
        )
    filename = f"{key}-{iid}.pdf"
    headers = {
        **_NO_STORE,
        "Content-Disposition": f'{disposition}; filename="{filename}"',
    }
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)
