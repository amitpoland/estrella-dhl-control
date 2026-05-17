"""
routes_suppliers.py — Read-only supplier dropdown source.

GET /api/v1/suppliers/
    List known suppliers (purchase exporters) for the New Shipment intake
    dropdown. No write side. No new master table — sourced from the
    existing ``wfirma_customers`` mapping so we don't fork identity.

This endpoint is intentionally minimal:
- read-only
- no auth-mutating
- no proforma / PZ / DHL / wFirma write coupling
- returns a stable shape regardless of upstream wfirma schema additions

The shape mirrors customer_master list rows so the modal can treat both
sides (client and supplier) symmetrically.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from ..core.logging import get_logger
from ..core.security import require_api_key
from ..services import wfirma_db as wfdb

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/suppliers", tags=["suppliers"])
_auth  = Depends(require_api_key)


def _row_to_dropdown(r: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a wfirma_customers row to the dropdown shape."""
    return {
        # Stable internal id (wfirma_customers.id) — usable as
        # supplier_contractor_id even when wfirma_customer_id is NULL.
        "contractor_id":     r.get("id") or "",
        # Cross-reference into wFirma when available; never required.
        "wfirma_customer_id": r.get("wfirma_customer_id") or "",
        "name":              r.get("client_name") or "",
        "country":           r.get("country") or "",
        "vat_id":            r.get("vat_id") or "",
        "match_status":      r.get("match_status") or "pending",
    }


@router.get("/", dependencies=[_auth])
def list_suppliers(
    country: Optional[str] = Query(None, description="ISO country filter"),
    limit:   int           = Query(200,  ge=1, le=1000),
) -> Dict[str, Any]:
    """Return suppliers for the purchase-exporter dropdown.

    Sourced from ``wfirma_customers`` (the existing contractor mapping used
    by proforma/PZ). Read-only; never writes; never calls wFirma.
    """
    try:
        rows = wfdb.list_customers()
    except Exception:
        rows = []

    out: List[Dict[str, Any]] = []
    for r in rows:
        if country and (r.get("country") or "").upper() != country.upper():
            continue
        out.append(_row_to_dropdown(r))
        if len(out) >= limit:
            break

    return {"suppliers": out, "count": len(out)}
