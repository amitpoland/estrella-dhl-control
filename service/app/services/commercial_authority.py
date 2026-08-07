"""Commercial document authority — shared projection + blank-only repair.

Canonical chain:
  Sales Packing (commercial variants / price / Client PO)
    → draft editable_lines (working copy)
    → Proforma / Commercial Packing List / CMR (read)
  Purchase Packing → physical gross/net + product_code identity;
                     may fill BLANK sales variant fields only when Sales
                     Packing never carried them (manual allocation / legacy).
  Product Master product_local.origin_country → ISO origin (never invent).

Never invents commercial values. Never writes wFirma.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# Variant fields that Sales Packing owns for commercial documents.
# client_po is Sales-only (Purchase Packing has no Client PO column).
_VARIANT_FROM_PURCHASE = (
    "karat",
    "metal",
    "metal_color",
    "quality_string",
    "stone_type",
    "size",
    "diamond_weight",
    "color_weight",
    "item_type",
)
_VARIANT_SALES_ONLY = ("client_po",)


def _truthy(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, (int, float)):
        try:
            return float(v) != 0.0
        except (TypeError, ValueError):
            return False
    s = str(v).strip()
    return bool(s) and s not in ("—", "-", "0", "0.0")


def purchase_variant_fields(pl: Dict[str, Any]) -> Dict[str, Any]:
    """Extract commercial-usable variant identity from a purchase packing row."""
    def _wt(key: str) -> float:
        try:
            return float(pl.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    metal = str(pl.get("metal") or "").strip()
    karat = str(pl.get("karat") or "").strip()
    metal_color = str(pl.get("metal_color") or "").strip()
    # Some purchase extracts encode "14KT/W" in metal only.
    if metal and "/" in metal and not karat:
        parts = metal.split("/", 1)
        karat = parts[0].strip()
        if not metal_color and len(parts) > 1:
            metal_color = parts[1].strip()
    return {
        "item_type":      str(pl.get("item_type") or "").strip(),
        "karat":          karat,
        "metal":          metal,
        "metal_color":    metal_color,
        "quality_string": str(pl.get("quality_string") or "").strip(),
        "stone_type":     str(pl.get("stone_type") or "").strip(),
        "size":           str(pl.get("size") or "").strip(),
        "diamond_weight": _wt("diamond_weight"),
        "color_weight":   _wt("color_weight"),
    }


def sales_row_to_draft_input(r: Dict[str, Any], *, currency: str = "") -> Dict[str, Any]:
    """ONE reshape: sales_packing_lines row → draft birth/reset input.

    Replaces duplicated hand-maps in routes_proforma reset and intake callers.
    """
    from .proforma_invoice_link_db import _sales_variant_fields

    qty = r.get("qty", r.get("quantity", 0)) or 0
    try:
        qty_f = float(qty)
    except (TypeError, ValueError):
        qty_f = 0.0
    try:
        up_f = float(r.get("unit_price", 0) or 0)
    except (TypeError, ValueError):
        up_f = 0.0
    cur = str(r.get("currency") or currency or "").upper()
    out = {
        "product_code": str(r.get("product_code") or "").strip(),
        "design_no":    str(r.get("design_no") or "").strip(),
        "qty":          qty_f,
        "unit_price":   up_f,
        "currency":     cur,
        "price_source": str(r.get("price_source") or ""),
        "client_ref":   str(r.get("client_ref") or ""),
        # name_pl generator attrs (fallback only)
        "ctg":     str(r.get("ctg") or r.get("category") or r.get("item_type") or ""),
        "kt":      str(r.get("kt") or r.get("karat") or ""),
        "col":     str(r.get("col") or r.get("metal_color") or ""),
        "quality": str(r.get("quality") or r.get("quality_string") or ""),
        **_sales_variant_fields(r),
    }
    return out


def _purchase_index(batch_id: str) -> Dict[str, Dict[str, Any]]:
    """product_code / design_no → first purchase packing row with variants."""
    from . import packing_db as pdb

    idx: Dict[str, Dict[str, Any]] = {}
    for pl in (pdb.get_packing_lines_for_batch(batch_id) or []):
        fields = purchase_variant_fields(pl)
        if not any(_truthy(fields[k]) for k in _VARIANT_FROM_PURCHASE):
            continue
        pc = str(pl.get("product_code") or "").strip()
        dn = str(pl.get("design_no") or "").strip()
        if pc and pc not in idx:
            idx[pc] = fields
        if dn:
            key = f"dn:{dn.casefold()}"
            if key not in idx:
                idx[key] = fields
    return idx


def enrich_sales_line_blanks_from_purchase(
    sales_ln: Dict[str, Any],
    purchase_idx: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[str]]:
    """Fill only blank variant fields on a sales line from purchase index.

    Never overwrites a non-blank Sales Packing value. Never sets client_po
    from purchase (no such authority).
    """
    pc = str(sales_ln.get("product_code") or "").strip()
    dn = str(sales_ln.get("design_no") or "").strip()
    src = None
    if pc and pc in purchase_idx:
        src = purchase_idx[pc]
    elif dn and f"dn:{dn.casefold()}" in purchase_idx:
        src = purchase_idx[f"dn:{dn.casefold()}"]
    if not src:
        return dict(sales_ln), []
    out = dict(sales_ln)
    filled: List[str] = []
    for k in _VARIANT_FROM_PURCHASE:
        if _truthy(out.get(k)):
            continue
        if _truthy(src.get(k)):
            out[k] = src[k]
            filled.append(k)
    return out, filled


def backfill_sales_variants_from_purchase(batch_id: str) -> Dict[str, Any]:
    """Blank-only UPDATE of sales_packing_lines from purchase packing.

    Safe for legacy sales rows / manual allocations that omitted variants.
    Does not invent Client PO. Does not touch drafts (caller may reset).
    """
    from . import document_db as ddb

    if not batch_id:
        return {"ok": False, "error": "batch_id required"}
    purchase_idx = _purchase_index(batch_id)
    if not purchase_idx:
        return {"ok": True, "batch_id": batch_id, "updated": 0, "reason": "no_purchase_variants"}

    rows = ddb.get_sales_packing_lines(batch_id) or []
    if not rows:
        return {"ok": True, "batch_id": batch_id, "updated": 0, "reason": "no_sales_rows"}

    db_path = getattr(ddb, "_db_path", None)
    if db_path is None:
        return {"ok": False, "error": "document_db not initialised"}

    updated = 0
    field_hits: Dict[str, int] = {}
    with sqlite3.connect(str(db_path)) as con:
        for r in rows:
            enriched, filled = enrich_sales_line_blanks_from_purchase(r, purchase_idx)
            if not filled:
                continue
            rid = r.get("id")
            if not rid:
                continue
            sets = []
            vals: List[Any] = []
            for k in filled:
                sets.append(f"{k}=?")
                vals.append(enriched[k])
                field_hits[k] = field_hits.get(k, 0) + 1
            vals.append(rid)
            con.execute(
                f"UPDATE sales_packing_lines SET {', '.join(sets)} WHERE id=?",
                vals,
            )
            updated += 1
        con.commit()

    log.info(
        "[%s] commercial_authority: backfilled %d sales rows from purchase (%s)",
        batch_id, updated, field_hits,
    )
    return {
        "ok": True,
        "batch_id": batch_id,
        "updated": updated,
        "field_hits": field_hits,
        "purchase_keys": len(purchase_idx),
    }


def repair_editable_draft_from_sales(
    proforma_db: Path,
    draft_id: int,
    operator: str,
) -> Dict[str, Any]:
    """Reset one editable draft from current sales_packing_lines (canonical).

    Uses the same OCC-safe reset as the operator endpoint. Refuses locked states.
    Never invents commercial values — only projects current Sales Packing.
    """
    from . import document_db as ddb
    from . import proforma_invoice_link_db as pildb
    from .proforma_draft_sync import resolve_sales_lines_for_batch

    d = pildb.get_draft_by_id(proforma_db, int(draft_id))
    if d is None:
        return {"ok": False, "draft_id": draft_id, "error": "not_found"}
    state = (d.draft_state or "").strip()
    if state not in ("draft", "editing", "post_failed", ""):
        return {
            "ok": False,
            "draft_id": draft_id,
            "error": "locked_state",
            "state": state,
        }

    all_rows = ddb.get_sales_packing_lines(d.batch_id) or []
    target = (d.client_name or "").strip().upper()
    matched = [
        r for r in all_rows
        if (r.get("client_name") or "").strip().upper() == target
    ]
    if not matched:
        return {"ok": False, "draft_id": draft_id, "error": "no_sales_rows"}

    sales_lines = [
        sales_row_to_draft_input(r, currency=d.currency or "")
        for r in matched
    ]
    sales_lines, _resolution = resolve_sales_lines_for_batch(d.batch_id, sales_lines)
    try:
        updated = pildb.reset_draft_from_sales_packing(
            proforma_db,
            int(draft_id),
            operator,
            d.updated_at,
            sales_lines=sales_lines,
            reset_all=False,
            name_pl_lookup=ddb.get_product_description,
            desc_generate=None,
        )
    except Exception as exc:
        return {
            "ok": False,
            "draft_id": draft_id,
            "error": type(exc).__name__,
            "detail": str(exc),
            "state": state,
        }
    return {
        "ok": True,
        "draft_id": draft_id,
        "batch_id": d.batch_id,
        "client": d.client_name,
        "state": state,
        "lines": len(sales_lines),
        "new_updated_at": getattr(updated, "updated_at", None),
    }
