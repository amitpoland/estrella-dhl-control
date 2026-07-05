"""
Accounting document reads (Wave 4 — Item 3A).

Endpoint
--------
  GET /api/v1/accounting/documents/{doc_type}
      doc_type ∈ {invoice, credit_note} — DOCUMENTED wFirma reads.

Authority: wFirma (Accounting Authority). Read-only via the proven
`invoices/find` transport (`wfirma_client.list_invoices_by_type`). No local
mirror, no duplicate authority. Consumer: the Accounting hub Invoice / Credit
Note grids (accounting-hub.jsx AccDocGrid).

Item 3B (WZ/PW/RW/MM warehouse-document reads) is intentionally NOT served here —
those reads are UNDOCUMENTED in the wFirma API and are recorded as a Wave-4
sandbox-verification task; the UI stays honest `Backend Pending`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core.security import require_api_key
from ..services import wfirma_client

router = APIRouter(prefix="/api/v1/accounting", tags=["accounting"])

# Same auth posture as the sibling accounting reads (proforma/search,
# dashboard/batches): X-API-Key, dev-bypassed when no key is configured.
_auth = Depends(require_api_key)

# doc_type → wFirma invoice type. Only DOCUMENTED types are mapped.
_DOC_TYPE_MAP = {
    "invoice":     "normal",       # faktura VAT
    "credit_note": "correction",   # faktura korygująca
}


@router.get("/documents/{doc_type}", dependencies=[_auth])
def list_accounting_documents(
    doc_type: str,
    start: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
) -> dict:
    """
    Return one page of accounting documents of the given type from wFirma.

    Response: {"doc_type", "wfirma_type", "rows": [...], "count": int}.
    Each row: number · date · party · net · tax · gross · currency · state · wfirma_id.

    Errors: 404 unsupported/undocumented type · 400 invalid arg · 502 wFirma read failure.
    """
    wfirma_type = _DOC_TYPE_MAP.get(doc_type)
    if not wfirma_type:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unsupported accounting document type '{doc_type}'. "
                "Documented: invoice, credit_note. WZ/PW/RW/MM warehouse-document "
                "reads are undocumented in wFirma (sandbox-verification pending)."
            ),
        )
    try:
        result = wfirma_client.list_invoices_by_type(wfirma_type, start=start, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (RuntimeError, ConnectionError) as exc:
        raise HTTPException(status_code=502, detail=f"wFirma read failed: {exc}")
    return {"doc_type": doc_type, "wfirma_type": wfirma_type, **result}
