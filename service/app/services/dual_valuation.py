"""
dual_valuation.py — Dual-valuation resolver (Atlas Campaign Phase 5, §6).

One backend resolver owns the rule:
  - Purchase invoice value → customs / SAD / PZ cost basis (import cost)
  - Sales packing / proforma value → warehouse / sales value (customer price)

These are TWO DIFFERENT values for the same goods. Mixing them produces incorrect
customs declarations (if you use sales price as CIF) or wrong customer invoices
(if you use import cost as the billing price).

This module provides:
  - resolve_dual_values(batch_id, storage_root) → DualValuation
  - A pure resolver with no side effects and no wFirma calls.

Consumers (UI, proforma builder, SAD generator) call resolve_dual_values and
display/use the appropriate value for their context.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ── Output type ────────────────────────────────────────────────────────────────

@dataclass
class LineValuation:
    """Dual valuation for one product line."""
    product_code:    str
    design_no:       str = ""
    # Purchase / customs side
    purchase_qty:         float = 0.0
    purchase_unit_price:  float = 0.0
    purchase_currency:    str   = ""
    purchase_total_value: float = 0.0
    purchase_source:      str   = ""   # "invoice_lines" | "audit_rows" | "none"
    # Sales / warehouse side
    sales_qty:         float = 0.0
    sales_unit_price:  float = 0.0
    sales_currency:    str   = ""
    sales_total_value: float = 0.0
    sales_source:      str   = ""   # "sales_packing_lines" | "proforma_draft" | "none"


@dataclass
class DualValuation:
    """Resolved dual valuation for a batch.

    purchase_* = customs / SAD / PZ cost basis (from purchase invoice)
    sales_*    = warehouse / sales value (from sales packing list or proforma)
    """
    batch_id:              str
    lines:                 List[LineValuation] = field(default_factory=list)
    # Aggregates
    purchase_total_usd:    float = 0.0
    sales_total_ccy:       float = 0.0
    sales_currency:        str   = ""
    # Metadata
    purchase_source:       str   = "unknown"
    sales_source:          str   = "unknown"
    confidence:            str   = "low"     # "high" | "medium" | "low"
    warnings:              List[str] = field(default_factory=list)


# ── Resolver ───────────────────────────────────────────────────────────────────

def resolve_dual_values(
    batch_id:     str,
    storage_root: Path,
) -> DualValuation:
    """Resolve purchase (customs) and sales (warehouse) values for a batch.

    Read-only. Never raises — errors produce a low-confidence result with warnings.
    All monetary values are in their original currencies (no cross-currency
    conversion; that is the PZ engine's job).
    """
    result = DualValuation(batch_id=batch_id)
    try:
        _fill_purchase_values(result, batch_id, storage_root)
        _fill_sales_values(result, batch_id, storage_root)
        _compute_confidence(result)
    except Exception as exc:
        log.warning("[%s] resolve_dual_values failed: %s", batch_id, exc)
        result.warnings.append(f"Dual-valuation resolution error: {exc}")
        result.confidence = "low"
    return result


def _fill_purchase_values(
    result:       DualValuation,
    batch_id:     str,
    storage_root: Path,
) -> None:
    """Populate purchase-side (import cost) values from invoice_lines."""
    docs_db = storage_root / "documents.db"
    if not docs_db.exists():
        result.warnings.append("documents.db not found — purchase values unavailable")
        result.purchase_source = "none"
        return

    conn = sqlite3.connect(str(docs_db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT product_code, description,
                  quantity, unit_price, total_value, currency,
                  rate_usd, amount_usd
           FROM invoice_lines
           WHERE batch_id=?""",
        (batch_id,),
    ).fetchall()
    conn.close()

    if not rows:
        result.warnings.append("No invoice_lines found for batch — purchase values unavailable")
        result.purchase_source = "none"
        return

    purchase_total_usd = 0.0
    # Build a {product_code: LineValuation} map merging into result.lines
    pm: Dict[str, LineValuation] = {lv.product_code: lv for lv in result.lines}
    for r in rows:
        pc = (r["product_code"] or "").strip()
        if not pc:
            continue
        if pc not in pm:
            pm[pc] = LineValuation(product_code=pc)
        lv = pm[pc]
        lv.purchase_qty        = float(r["quantity"] or 0)
        lv.purchase_unit_price = float(r["unit_price"] or 0)
        lv.purchase_currency   = (r["currency"] or "USD").strip()
        lv.purchase_total_value = float(r["total_value"] or 0)
        lv.purchase_source     = "invoice_lines"
        purchase_total_usd    += float(r["amount_usd"] or 0)

    result.lines = list(pm.values())
    result.purchase_total_usd = purchase_total_usd
    result.purchase_source    = "invoice_lines"


def _fill_sales_values(
    result:       DualValuation,
    batch_id:     str,
    storage_root: Path,
) -> None:
    """Populate sales-side (customer price) values from sales_packing_lines."""
    docs_db = storage_root / "documents.db"
    if not docs_db.exists():
        result.sales_source = "none"
        return

    conn = sqlite3.connect(str(docs_db))
    conn.row_factory = sqlite3.Row
    # sales_packing_lines joined to packing_lines via design_no matching
    try:
        rows = conn.execute(
            """SELECT spl.design_no, spl.unit_price, spl.currency,
                      spl.total_value, SUM(spl.quantity) AS qty,
                      pl.product_code
               FROM sales_packing_lines spl
               LEFT JOIN packing_lines pl
                 ON UPPER(TRIM(pl.design_no)) = UPPER(TRIM(spl.design_no))
                 AND pl.batch_id = spl.batch_id
               WHERE spl.batch_id=?
               GROUP BY spl.design_no, spl.unit_price, spl.currency, pl.product_code""",
            (batch_id,),
        ).fetchall()
    except Exception:
        rows = []
    conn.close()

    if not rows:
        result.sales_source = "none"
        return

    pm: Dict[str, LineValuation] = {lv.product_code: lv for lv in result.lines}
    sales_total = 0.0
    sales_ccy   = ""
    for r in rows:
        pc = (r["product_code"] or "").strip()
        dn = (r["design_no"] or "").strip()
        if not pc and not dn:
            continue
        key = pc or dn
        if key not in pm:
            pm[key] = LineValuation(product_code=key, design_no=dn)
        lv = pm[key]
        lv.design_no        = dn or lv.design_no
        lv.sales_qty        = float(r["qty"] or 0)
        lv.sales_unit_price = float(r["unit_price"] or 0)
        lv.sales_currency   = (r["currency"] or "").strip()
        lv.sales_total_value = float(r["total_value"] or 0)
        lv.sales_source     = "sales_packing_lines"
        sales_total += lv.sales_total_value
        if not sales_ccy and lv.sales_currency:
            sales_ccy = lv.sales_currency

    result.lines            = list(pm.values())
    result.sales_total_ccy  = sales_total
    result.sales_currency   = sales_ccy
    result.sales_source     = "sales_packing_lines"


def _compute_confidence(result: DualValuation) -> None:
    """Assign confidence based on data availability."""
    has_purchase = result.purchase_source == "invoice_lines" and result.lines
    has_sales    = result.sales_source    == "sales_packing_lines"
    if has_purchase and has_sales:
        result.confidence = "high"
    elif has_purchase or has_sales:
        result.confidence = "medium"
    else:
        result.confidence = "low"


def summarize(dv: DualValuation) -> Dict[str, Any]:
    """Return a JSON-serialisable summary for API responses."""
    return {
        "batch_id":           dv.batch_id,
        "purchase_total_usd": round(dv.purchase_total_usd, 2),
        "purchase_source":    dv.purchase_source,
        "sales_total":        round(dv.sales_total_ccy, 2),
        "sales_currency":     dv.sales_currency,
        "sales_source":       dv.sales_source,
        "confidence":         dv.confidence,
        "line_count":         len(dv.lines),
        "warnings":           dv.warnings,
        "lines": [
            {
                "product_code":        lv.product_code,
                "design_no":           lv.design_no,
                "purchase_qty":        lv.purchase_qty,
                "purchase_unit_price": lv.purchase_unit_price,
                "purchase_currency":   lv.purchase_currency,
                "purchase_total":      round(lv.purchase_total_value, 2),
                "purchase_source":     lv.purchase_source,
                "sales_qty":           lv.sales_qty,
                "sales_unit_price":    lv.sales_unit_price,
                "sales_currency":      lv.sales_currency,
                "sales_total":         round(lv.sales_total_value, 2),
                "sales_source":        lv.sales_source,
            }
            for lv in dv.lines
        ],
    }
