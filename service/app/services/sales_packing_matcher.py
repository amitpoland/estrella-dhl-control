"""sales_packing_matcher.py — Batch-scoped product_code matcher for
sales packing rows.

Sales packing files carry design_no but no product_code.  This module
resolves the canonical product_code from same-batch purchase
packing_lines evidence ONLY, so the persisted sales_packing_lines row
carries the same canonical identity that was minted by
store_invoice_lines.

Architecture rule (enforced by tests):
    product_code is minted EXACTLY ONCE — by store_invoice_lines in
    document_db.py.  Every downstream surface copies the canonical
    code; none invents one.  This module COPIES, it never invents.

Resolution order, per sales row:
    1. existing non-empty product_code wins (never overwritten).
    2. design_no with exactly ONE candidate in same-batch
       packing_lines  → inject + mark resolution_source.
    3. multiple candidates within same batch → ambiguous, leave
       product_code='' and record under designs_ambiguous.
    4. zero candidates → unresolved, leave product_code='' and
       record under designs_unresolved.

Hard rules:
    * NEVER use design_no as a product_code fallback.
    * NEVER consult the global design_product_mapping registry —
      operational sales sync must be batch-scoped only.
    * NEVER consume invoice_lines (sales rows may N:1 reference the
      same purchase invoice line; consumption semantics belong to
      the purchase-side matcher).
    * No external HTTP / wFirma / SMTP / DHL calls — local-DB only.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List, Tuple

from . import packing_db as _pdb

log = logging.getLogger(__name__)


# ── Batch-scoped lookup ─────────────────────────────────────────────────────

def _design_to_product_codes_for_batch(
    batch_id: str,
) -> Dict[str, List[str]]:
    """Return ``{design_no: sorted([product_code, ...])}`` for *batch_id*.

    Local SELECT against ``packing_db.packing_lines``.  Batch-scoped by
    construction — design collisions across batches cannot leak.
    Empty ``{}`` when packing_db is uninitialised, the batch has no
    purchase packing_lines, or all candidate rows have NULL/empty
    product_code.
    """
    out: Dict[str, set] = {}
    if not (batch_id or "").strip():
        return {}
    db_path = getattr(_pdb, "_db_path", None)
    if db_path is None:
        return {}
    try:
        with sqlite3.connect(str(db_path)) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT DISTINCT design_no, product_code "
                "FROM packing_lines "
                "WHERE batch_id=? "
                "AND product_code IS NOT NULL AND product_code<>''",
                (str(batch_id),),
            ).fetchall()
    except Exception as exc:
        log.warning(
            "[%s] sales matcher: batch-scoped lookup failed "
            "(non-fatal): %s", batch_id, exc,
        )
        return {}
    for r in rows:
        d = (r["design_no"] or "").strip()
        p = (r["product_code"] or "").strip()
        if not d or not p:
            continue
        out.setdefault(d, set()).add(p)
    return {d: sorted(ps) for d, ps in out.items()}


# ── Public matcher ──────────────────────────────────────────────────────────

def match_sales_lines_to_packing(
    batch_id:   str,
    sales_rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Resolve missing ``product_code`` on parsed sales rows using same-
    batch purchase packing_lines evidence ONLY.

    Returns ``(matched_rows, summary)`` where matched_rows preserve the
    input order and length.  Rows whose product_code could not be
    resolved are returned unchanged (still empty); the DB layer's
    skip-empty-pc invariant continues to apply downstream.

    summary shape::

        {
          "designs_resolved":   {design_no: product_code, ...},
          "designs_ambiguous":  {design_no: [product_code, ...], ...},
          "designs_unresolved": [design_no, ...],
          "rows_total":   int,
          "rows_kept_pc": int,   # existing pc preserved
          "rows_resolved":int,
          "rows_skipped": int,   # ambiguous + unresolved + missing design_no
        }
    """
    lookup = _design_to_product_codes_for_batch(batch_id)

    matched: List[Dict[str, Any]] = []
    designs_resolved:   Dict[str, str]       = {}
    designs_ambiguous:  Dict[str, List[str]] = {}
    designs_unresolved: set                  = set()
    rows_total = rows_kept_pc = rows_resolved = rows_skipped = 0

    for r in (sales_rows or []):
        rows_total += 1
        pc = str(r.get("product_code") or "").strip()
        if pc:
            matched.append(r)
            rows_kept_pc += 1
            continue
        dn = str(r.get("design_no") or "").strip()
        if not dn:
            matched.append(r)
            rows_skipped += 1
            continue
        cands = lookup.get(dn, [])
        if len(cands) == 1:
            clone = dict(r)
            clone["product_code"]      = cands[0]
            clone["resolution_source"] = "batch_packing_lines"
            matched.append(clone)
            designs_resolved[dn] = cands[0]
            rows_resolved += 1
        elif len(cands) > 1:
            designs_ambiguous[dn] = list(cands)
            matched.append(r)
            rows_skipped += 1
            log.warning(
                "[%s] sales matcher: design %r ambiguous in batch "
                "packing_lines -> %s — leaving product_code empty",
                batch_id, dn, cands,
            )
        else:
            designs_unresolved.add(dn)
            matched.append(r)
            rows_skipped += 1
            log.info(
                "[%s] sales matcher: design %r unresolvable in batch "
                "packing_lines — leaving product_code empty",
                batch_id, dn,
            )

    summary = {
        "designs_resolved":   designs_resolved,
        "designs_ambiguous":  designs_ambiguous,
        "designs_unresolved": sorted(designs_unresolved),
        "rows_total":         rows_total,
        "rows_kept_pc":       rows_kept_pc,
        "rows_resolved":      rows_resolved,
        "rows_skipped":       rows_skipped,
    }
    return matched, summary
