"""
routes_proforma.py — Read-only wFirma proforma preview.

Exposes a single endpoint that resolves the proforma staging shape from local
data only:
  - sales_packing_lines + sales_documents  (client + qty + design_no)
  - v_sales_to_wfirma view                 (design_no → wfirma product_code)
  - invoice_lines                          (currency + unit_price + FX rate)
  - wfirma_products                        (product_match)
  - warehouse inventory                    (stock_ok)

NO writes. NO live wFirma API calls. NO reservation/proforma row creation.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from ..core.security import require_api_key
from ..core.logging import get_logger
from ..services import document_db as ddb
from ..services import packing_db  as pdb
from ..services import warehouse_db as wdb  # noqa: F401  (kept for cross-DB queries)
from ..services import wfirma_db   as wfdb
from ..services import inventory_state_engine as ise

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/proforma", tags=["proforma"])
_auth  = Depends(require_api_key)


def _norm(s: str) -> str:
    return (s or "").strip().upper()


# ── Stock helpers (read-only, no writes) ─────────────────────────────────────
# Proforma readiness uses the lifecycle state model, not the physical
# DISPATCH scan: a proforma can be issued for goods that are present in
# WAREHOUSE_STOCK but have not yet shipped.

def _scan_codes_per_product(batch_id: str) -> Dict[str, List[str]]:
    """{ wfirma_product_code: [scan_code, ...] } from packing_lines."""
    if pdb._db_path is None:
        return {}
    out: Dict[str, List[str]] = {}
    with sqlite3.connect(str(pdb._db_path), check_same_thread=False) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT product_code, scan_code FROM packing_lines "
            "WHERE batch_id=? AND scan_code IS NOT NULL",
            (batch_id,),
        ).fetchall()
    for r in rows:
        pc = r["product_code"] or ""
        sc = r["scan_code"]    or ""
        if pc and sc:
            out.setdefault(pc, []).append(sc)
    return out


def _state_codes(batch_id: str) -> Dict[str, List[str]]:
    """{ inventory_state: [scan_code, ...] } for this batch."""
    out: Dict[str, List[str]] = {}
    for s in ise.STATES:
        try:
            for row in ise.list_by_state(s, batch_id=batch_id):
                out.setdefault(s, []).append(row["scan_code"])
        except Exception:
            # Engine unavailable — leave empty; downstream stock_ok=False.
            pass
    return out


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("/preview/{batch_id}/{client_name:path}", dependencies=[_auth])
def proforma_preview(batch_id: str, client_name: str) -> JSONResponse:
    """
    Build a read-only proforma preview for one (batch_id, client_name).

    Returns the canonical staging shape so the operator can validate currency,
    product_code mapping, and design_no traceability before a live proforma
    is created in wFirma.
    """
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    client_name = (client_name or "").strip()
    if not client_name:
        raise HTTPException(status_code=400, detail="client_name is required.")

    blocking_reasons: List[str] = []

    # ── 1. Resolution rows (sales → wFirma product_code) ────────────────────
    resolution_rows = [
        r for r in ddb.query_sales_to_wfirma(batch_id)
        if (r.get("client_name") or "").strip() == client_name
    ]
    if not resolution_rows:
        return JSONResponse({
            "ok":               False,
            "batch_id":         batch_id,
            "client_name":      client_name,
            "currency":         "unknown",
            "exchange_rate":    None,
            "ready":            False,
            "blocking_reasons": [f"no sales rows for client {client_name!r}"],
            "lines":            [],
        })

    # ── 2. Invoice pricing index: product_code → (unit_price, currency, fx) ─
    inv_lines = ddb.get_invoice_lines_for_batch(batch_id)
    inv_price:    Dict[str, float] = {}
    inv_currency: Dict[str, str]   = {}
    inv_fx:       Dict[str, Optional[float]] = {}
    for il in inv_lines:
        pc = il.get("product_code") or ""
        if not pc or pc in inv_price:
            continue
        price    = il.get("rate_usd") or il.get("unit_price") or 0
        currency = (il.get("currency") or "").upper() or "unknown"
        fx       = il.get("exchange_rate")
        inv_price[pc]    = float(price or 0)
        inv_currency[pc] = currency
        try:
            inv_fx[pc] = float(fx) if fx not in (None, "") else None
        except (TypeError, ValueError):
            inv_fx[pc] = None

    # ── 3. Stock readiness via inventory_state (NOT warehouse DISPATCH) ─────
    # A proforma may be issued when items are in WAREHOUSE_STOCK.
    # PURCHASE_TRANSIT (not yet received), SALES_TRANSIT (already promised
    # on another proforma/invoice), and CLOSED (delivered) all block
    # availability for a NEW proforma.
    sc_per_product   = _scan_codes_per_product(batch_id)
    state_codes      = _state_codes(batch_id)
    in_warehouse     = set(state_codes.get(ise.WAREHOUSE_STOCK,  []))
    in_purchase      = set(state_codes.get(ise.PURCHASE_TRANSIT, []))
    in_sales_transit = set(state_codes.get(ise.SALES_TRANSIT,    []))
    in_closed        = set(state_codes.get(ise.CLOSED,           []))

    def _stock_status(pc: str) -> str:
        scs = sc_per_product.get(pc, [])
        if not scs:
            return "no_scan_codes"
        if all(sc in in_warehouse for sc in scs):
            return "warehouse_stock"
        if any(sc in in_purchase for sc in scs):
            return "purchase_transit"
        if any(sc in in_sales_transit for sc in scs):
            return "sales_transit"
        if any(sc in in_closed for sc in scs):
            return "closed"
        return "missing_state"

    def _stock_ok(pc: str) -> bool:
        return _stock_status(pc) == "warehouse_stock"

    # ── 4. Build per-line response ──────────────────────────────────────────
    lines: List[Dict[str, Any]] = []
    unmatched_count    = 0
    missing_price      = 0
    missing_product    = 0
    stock_blocked: Counter = Counter()  # stock_status (excluding warehouse_stock)
    line_currencies: List[str] = []
    line_fx:            List[float] = []

    for r in resolution_rows:
        product_code = r.get("wfirma_product_code")  # may be None
        design_no    = r.get("sales_design_no") or ""
        qty          = float(r.get("qty") or 0)

        if not product_code:
            unmatched_count += 1
            lines.append({
                "product_code":  None,
                "design_no":     design_no,
                "qty":           qty,
                "unit_price":    None,
                "currency":      "unknown",
                "exchange_rate": None,
                "line_value":    None,
                "stock_ok":      False,
                "product_match": False,
            })
            continue

        unit_price = inv_price.get(product_code)
        currency   = inv_currency.get(product_code, "unknown")
        fx         = inv_fx.get(product_code)
        line_value = (unit_price * qty) if unit_price is not None else None

        if unit_price is None or currency == "unknown":
            missing_price += 1
        else:
            line_currencies.append(currency)
            if fx is not None:
                line_fx.append(fx)

        prod_rec = wfdb.get_product(product_code) if wfdb._db_path is not None else None
        product_match = bool(
            prod_rec
            and prod_rec.get("wfirma_product_id")
            and prod_rec.get("sync_status") == "matched"
        )
        if not product_match:
            missing_product += 1

        st = _stock_status(product_code)
        s_ok = (st == "warehouse_stock")
        if not s_ok:
            stock_blocked[st] += 1

        lines.append({
            "product_code":  product_code,
            "design_no":     design_no,
            "qty":           qty,
            "unit_price":    unit_price,
            "currency":      currency,
            "exchange_rate": fx,
            "line_value":    line_value,
            "stock_ok":      s_ok,
            "stock_status":  st,
            "product_match": product_match,
        })

    # ── 5. Header currency + FX (dominant across priced lines) ─────────────
    if line_currencies:
        currency = Counter(line_currencies).most_common(1)[0][0]
    else:
        currency = "unknown"
    exchange_rate = (sum(line_fx) / len(line_fx)) if line_fx else None

    # ── 6. Readiness gates ─────────────────────────────────────────────────
    if unmatched_count:
        blocking_reasons.append(
            f"{unmatched_count} sales design(s) not mapped to a wFirma product_code"
        )
    if missing_price:
        blocking_reasons.append(
            f"{missing_price} line(s) missing unit_price or currency in invoice_lines"
        )
    if missing_product:
        blocking_reasons.append(
            f"{missing_product} product(s) not matched in wfirma_products"
        )
    # Stock is reported per state; never written.
    _STATE_BLURB = {
        "purchase_transit": "still in PURCHASE_TRANSIT (not yet received in warehouse)",
        "sales_transit":    "already in SALES_TRANSIT (committed to another proforma/invoice)",
        "closed":           "in CLOSED state (already delivered)",
        "missing_state":    "have no inventory_state record (not seeded)",
        "no_scan_codes":    "have no scan_codes in packing_lines",
    }
    for state, count in stock_blocked.items():
        blurb = _STATE_BLURB.get(state, f"in unexpected state {state!r}")
        blocking_reasons.append(f"{count} product(s) {blurb}")

    # Customer match — local lookup only
    cust = wfdb.get_customer(client_name) if wfdb._db_path is not None else None
    customer_match = bool(
        cust
        and cust.get("wfirma_customer_id")
        and cust.get("match_status") == "matched"
    )
    if not customer_match:
        blocking_reasons.append(
            f"customer {client_name!r} not matched in wfirma_customers"
        )

    ready = not blocking_reasons

    return JSONResponse({
        "ok":               True,
        "batch_id":         batch_id,
        "client_name":      client_name,
        "currency":         currency,
        "exchange_rate":    exchange_rate,
        "ready":            ready,
        "blocking_reasons": blocking_reasons,
        "lines":            lines,
    })
