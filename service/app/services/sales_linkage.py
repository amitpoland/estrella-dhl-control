"""
sales_linkage.py — Link sales packing lines to warehouse scan state.

Match key (corrected):
  sales.product_code  ──►  packing.design_no   (both carry the SKU / design code)

  Sales rows use the bare SKU as product_code (e.g. "CSTR07596").
  Packing rows store the invoice line reference as product_code
    (e.g. "EJL/26-27/013-2") and the SKU as design_no.
  Therefore the link is:  sales.product_code → packing.design_no

  Matching is normalised: uppercase + strip + collapse-spaces, so minor
  casing/spacing differences in extracted text never block a real match.

  Duplicate design_nos (same SKU in multiple invoice lines) are handled by
  collecting all scan_codes and returning the best warehouse status across them.

Status classification (best-of-all-matches):
  ready            — any matched scan has current_status = 'dispatched'
  pending_dispatch — any matched scan has current_status in ('packed', 'picked')
  not_ready        — scanned but at receive/move stage
  missing_scan     — no warehouse record found for any matched scan_code

Audit gate:
  missing_scans > 0 OR invalid_flows > 0 OR orphan_inventory > 0
  → ready_for_invoice = False
  preview: warn only; final: block unless override=True
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from typing import Any, Dict, List, Optional, Set

from ..core.logging import get_logger
from . import document_db as ddb
from . import packing_db as pdb
from . import warehouse_db as wdb
from . import warehouse_audit as waudit

log = get_logger(__name__)


# ── Status classification ─────────────────────────────────────────────────────

_READY_STATUSES   = {"dispatched"}
_PENDING_STATUSES = {"packed", "picked"}

# Priority order for best-status resolution (higher index = better)
_STATUS_PRIORITY = {"missing_scan": 0, "not_ready": 1, "pending_dispatch": 2, "ready": 3}


def _classify_one(wh_row: Optional[Dict[str, Any]]) -> str:
    if wh_row is None:
        return "missing_scan"
    status = (wh_row.get("current_status") or "").lower()
    if status in _READY_STATUSES:
        return "ready"
    if status in _PENDING_STATUSES:
        return "pending_dispatch"
    return "not_ready"


def _best_status(statuses: List[str]) -> str:
    """Return the most favourable status from a list."""
    return max(statuses, key=lambda s: _STATUS_PRIORITY.get(s, 0))


# ── Normalisation ─────────────────────────────────────────────────────────────

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    """Uppercase, strip, collapse internal whitespace."""
    return _WS.sub(" ", (s or "").strip()).upper()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ready() -> bool:
    return (
        ddb._db_path is not None
        and pdb._db_path is not None
        and wdb._db_path is not None
    )


def _wcon() -> sqlite3.Connection:
    con = sqlite3.connect(str(wdb._db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


# ── Main linkage ──────────────────────────────────────────────────────────────

def get_sales_linkage(
    batch_id: str,
    *,
    mode: str = "preview",
    override: bool = False,
) -> Dict[str, Any]:
    """
    Return warehouse-linked state for all sales packing lines in *batch_id*.

    Parameters
    ----------
    batch_id : str
    mode     : "preview" (always allow, show warnings) |
               "final"   (block if audit gate fails, unless override=True)
    override : bool — suppress blocking in final mode (explicit operator choice)

    Returns
    -------
    {
        "batch_id":           str,
        "mode":               str,
        "ready_for_invoice":  bool,
        "blocked":            bool,
        "blocking_reasons":   list[str],
        "audit_warnings":     list[str],
        "items":              list[item_dict],
        "summary": {
            "total":            int,
            "ready":            int,
            "pending_dispatch": int,
            "not_ready":        int,
            "missing_scan":     int,
            "total_value":      float,  # sum of invoice_line.total_value for this batch
            "currency":         str | None,  # dominant currency from invoice_lines
        }
    }
    """
    empty = _empty_response(batch_id, mode)

    if not _ready() or not batch_id:
        return empty

    # ── 1. Load sales rows ────────────────────────────────────────────────────
    # physical_only=True: get only the purchase-authority rows (packing_xlsx_value).
    # The sales-price import adds a second row per item (excel_symbol) with a
    # different price source; both represent the same physical item.  For scan
    # linkage we count physical goods, not price authorities — returning all 292
    # rows for a 146-line batch would double the "not-scanned" count.
    sales_rows = ddb.get_sales_packing_lines(batch_id, physical_only=True)
    if not sales_rows:
        return empty

    # ── 2. Build design_no → [scan_codes] index from packing_lines ───────────
    #
    # KEY INSIGHT: packing.design_no == sales.product_code (both = SKU).
    # packing.product_code = invoice line ref (e.g. "EJL/26-27/015-6") — not used here.
    # Multiple packing lines may share a design_no (same SKU across invoice lines).
    #
    packing_rows = pdb.get_packing_lines_for_batch(batch_id)
    dn_index: Dict[str, List[str]] = {}   # norm(design_no) → [scan_code, ...]
    for pl in packing_rows:
        dn  = _norm(pl.get("design_no") or "")
        sc  = pl.get("scan_code") or wdb.scan_code_for_packing_line(pl)
        if dn and sc:
            dn_index.setdefault(dn, []).append(sc)

    # ── 3. Load all warehouse rows for this batch in one query ────────────────
    with _wcon() as con:
        wh_rows = con.execute(
            "SELECT * FROM inventory_current_location WHERE batch_id=?",
            (batch_id,),
        ).fetchall()
    wh_index: Dict[str, Dict] = {r["scan_code"]: dict(r) for r in wh_rows}

    # ── 4. Link each sales row ────────────────────────────────────────────────
    items: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {
        "ready": 0, "pending_dispatch": 0, "not_ready": 0, "missing_scan": 0,
    }

    for sr in sales_rows:
        # Sales carries SKU as product_code (and also as design_no — they match)
        product_code = (sr.get("product_code") or "").strip()
        design_no    = (sr.get("design_no")    or "").strip()

        # Lookup key: normalised SKU against packing.design_no
        lookup_key = _norm(product_code) or _norm(design_no)

        scan_codes: List[str] = dn_index.get(lookup_key, [])

        # Evaluate warehouse status for each matching scan_code
        matched_wh: List[Dict] = [wh_index[sc] for sc in scan_codes if sc in wh_index]
        per_status = [_classify_one(r) for r in matched_wh] if matched_wh else ["missing_scan"]
        status     = _best_status(per_status)
        counts[status] += 1

        # Best warehouse row for display
        best_wh = _best_wh_row(matched_wh)

        item: Dict[str, Any] = {
            "sales_document_id":  sr.get("sales_document_id"),
            "client_name":        sr.get("client_name"),
            "client_ref":         sr.get("client_ref"),
            "product_code":       product_code,
            "design_no":          design_no,
            "bag_id":             sr.get("bag_id") or "",
            "quantity":           sr.get("quantity"),
            "matched_scan_codes": scan_codes,
            "warehouse_status":   status,
        }
        if best_wh:
            item["current_location"] = best_wh.get("current_location")
            item["wh_status"]        = best_wh.get("current_status")
        items.append(item)

    # ── 5. Audit gate ─────────────────────────────────────────────────────────
    audit_warnings:   List[str] = []
    blocking_reasons: List[str] = []
    ready_for_invoice           = True

    missing_scans = waudit.get_missing_scans(batch_id)
    invalid_flows = waudit.get_invalid_flows(batch_id)
    orphans       = waudit.get_orphan_inventory(batch_id)

    # Authority separation (2026-06-22): warehouse scan completeness, scan-flow
    # validity, and orphan records are WAREHOUSE / physical-traceability signals.
    # They are advisory only — they MUST NOT be promoted into hard blockers that
    # gate sales-invoice readiness (and, downstream, must never reach IMPORT_PZ
    # readiness). They stay in `audit_warnings`; they are NOT appended to
    # `blocking_reasons`. A genuine final-dispatch stop, if ever required, must be
    # a SALES-authority gate with an explicit business rule + regression test.
    if missing_scans:
        audit_warnings.append(
            f"{len(missing_scans)} packing line(s) awaiting warehouse confirmation "
            f"(advisory — optional traceability)"
        )

    if invalid_flows:
        audit_warnings.append(
            f"{len(invalid_flows)} invalid scan flow(s) detected "
            f"(advisory — e.g. DISPATCH without RECEIVE)"
        )

    if orphans:
        audit_warnings.append(
            f"{len(orphans)} orphan warehouse record(s) with no matching packing line "
            f"(advisory)"
        )

    if blocking_reasons:
        ready_for_invoice = False

    blocked = (
        not ready_for_invoice
        and mode == "final"
        and not override
    )

    # ── 6. Invoice totals for summary (read-only — never modifies invoice data) ──
    inv_lines     = ddb.get_invoice_lines_for_batch(batch_id)
    summary_value = round(sum(float(il.get("total_value") or 0) for il in inv_lines), 2)
    currency_ctr  = Counter(
        (il.get("currency") or "").strip().upper()
        for il in inv_lines
        if (il.get("currency") or "").strip()
    )
    summary_currency: Optional[str] = (
        currency_ctr.most_common(1)[0][0] if currency_ctr else None
    )

    return {
        "batch_id":          batch_id,
        "mode":              mode,
        "ready_for_invoice": ready_for_invoice,
        "blocked":           blocked,
        "blocking_reasons":  blocking_reasons if blocked else [],
        "audit_warnings":    audit_warnings,
        "items":             items,
        "summary": {
            "total":            len(items),
            "ready":            counts["ready"],
            "pending_dispatch": counts["pending_dispatch"],
            "not_ready":        counts["not_ready"],
            "missing_scan":     counts["missing_scan"],
            "total_value":      summary_value,
            "currency":         summary_currency,
        },
    }


def _best_wh_row(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the warehouse row with the best (most dispatched) status."""
    if not rows:
        return None
    return max(rows, key=lambda r: _STATUS_PRIORITY.get(_classify_one(r), 0))


def _empty_response(batch_id: str, mode: str) -> Dict[str, Any]:
    return {
        "batch_id":          batch_id,
        "mode":              mode,
        "ready_for_invoice": False,
        "blocked":           False,
        "blocking_reasons":  [],
        "audit_warnings":    [],
        "items":             [],
        "summary": {
            "total": 0, "ready": 0,
            "pending_dispatch": 0, "not_ready": 0, "missing_scan": 0,
            "total_value": 0.0,
            "currency":    None,
        },
    }
