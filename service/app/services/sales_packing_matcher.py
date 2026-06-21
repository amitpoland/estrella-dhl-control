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
    3. multiple candidates within same batch → try the secondary
       (design_no, metal-key) disambiguation; if that resolves to
       exactly one product_code → inject; otherwise ambiguous, leave
       product_code='' and record under designs_ambiguous.
    4. zero candidates → unresolved, leave product_code='' and
       record under designs_unresolved.

Matching keys are NORMALISED on both sides (uppercase, trimmed,
internal whitespace collapsed) so trivial case/spacing differences
between the purchase and sales spellings of the same design do not
cause a false miss.

Metal-key alignment: purchase packing_lines store the metal combined as
``metal='14KT/W'`` with ``metal_color=''`` empty, while the sales packing
parser splits the Excel ``Kt``/``Col`` columns into ``metal='14KT'`` +
``metal_color='W'``.  ``_metal_key`` folds both shapes to one canonical
form (``'14KT/W'``) so the secondary disambiguation actually lines up.

Reasons: every row that is left unresolved is recorded with an explicit
reason (``unresolved_reasons``) — AMBIGUOUS_MATCH, MISSING_PURCHASE_AUTHORITY,
or LEGITIMATE_SUPPLEMENTARY_ROW — so nothing is silently dropped.

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
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from . import packing_db as _pdb

log = logging.getLogger(__name__)

# Category tokens that appear in the Excel "Design" column when the client
# packing list gave no real design number (e.g. a plain "PND" pendant row).
# Such rows are genuine supplementary rows: they CANNOT carry an authoritative
# product_code and are classified LEGITIMATE_SUPPLEMENTARY_ROW rather than a
# matcher failure.  This list is advisory (classification only) — it does not
# change which bucket the row falls into, so existing behaviour is preserved.
_CATEGORY_TOKENS = {
    "PND", "NCK", "BRC", "RNG", "EAR", "BNG", "BRA", "PEN", "CHN",
    "SET", "ANK", "NOSE", "TOE", "CUFF", "BCL", "CL", "MN", "PDT",
}


# ── Normalisation helpers ────────────────────────────────────────────────────

def _norm(s: Any) -> str:
    """Uppercase, trim, collapse internal whitespace runs to a single space.

    Used as the design-match key on BOTH the purchase and sales sides so a
    trivial case/spacing difference in the same design number does not cause a
    false miss.  Deliberately does NOT merge slash/dash variants — design
    numbers like ``JBR00254-1.50`` must stay distinct.
    """
    return re.sub(r"\s+", " ", str(s or "").strip().upper())


def _metal_key(metal: Any, color: Any) -> str:
    """Fold the two metal spellings to one canonical key.

    Purchase packing_lines: ``metal='14KT/W'``, ``metal_color=''`` (combined).
    Sales parser:           ``metal='14KT'``,   ``metal_color='W'`` (split).
    Both must produce ``'14KT/W'``.  Whitespace removed, uppercased.  When the
    metal already contains '/', it is treated as already-combined and the
    separate color is ignored.  An empty metal yields '' (no key).
    """
    m = re.sub(r"\s+", "", str(metal or "").strip().upper())
    c = re.sub(r"\s+", "", str(color or "").strip().upper())
    if not m:
        return ""
    if "/" in m:
        return m
    if c:
        return m + "/" + c
    return m


# ── Batch-scoped lookups ─────────────────────────────────────────────────────

def _design_to_product_codes_for_batch(batch_id: str) -> Dict[str, List[str]]:
    """Return ``{_norm(design_no): sorted([product_code, ...])}`` for *batch_id*.

    Local SELECT against ``packing_db.packing_lines``.  Batch-scoped by
    construction.  Empty ``{}`` when packing_db is uninitialised, the batch has
    no purchase packing_lines, or all candidate rows have NULL/empty
    product_code.  Keys are normalised (uppercase/trim/collapse-ws).
    """
    if not (batch_id or "").strip():
        return {}
    # Canonical authority (packing_lines) — single resolver. It returns a
    # stripped-key (case-preserved) map; this matcher keys by the NORMALISED
    # design_no, so re-key and merge codes for designs that normalise to the same
    # key — preserving the historical behaviour exactly. See ADR-product-authority.
    from .product_authority_resolver import design_to_product_codes  # noqa: PLC0415
    try:
        raw = design_to_product_codes(batch_id)
    except Exception as exc:
        log.warning(
            "[%s] sales matcher: batch-scoped lookup failed "
            "(non-fatal): %s", batch_id, exc,
        )
        return {}
    out: Dict[str, set] = {}
    for d, codes in raw.items():
        nd = _norm(d)
        if not nd:
            continue
        out.setdefault(nd, set()).update(codes)
    return {d: sorted(ps) for d, ps in out.items()}


def _design_metal_to_product_code_for_batch(
    batch_id: str,
) -> Dict[Tuple[str, str], str]:
    """Return ``{(_norm(design_no), _metal_key(metal, color)): product_code}``.

    Secondary disambiguation when the same design_no appears multiple times in
    the batch in different metal variants (e.g. the same ring in white vs
    yellow gold → two product_codes).  Only triples that resolve to exactly ONE
    product_code are kept — ambiguous triples are omitted so the caller falls
    back to the unresolved path rather than guessing.

    ``_metal_key`` folds the purchase (combined ``'14KT/W'``) and sales (split
    ``'14KT'`` + ``'W'``) spellings to the same canonical key.
    """
    if not (batch_id or "").strip():
        return {}
    db_path = getattr(_pdb, "_db_path", None)
    if db_path is None:
        return {}
    try:
        with sqlite3.connect(str(db_path)) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT design_no, metal, metal_color, product_code "
                "FROM packing_lines "
                "WHERE batch_id=? "
                "AND product_code IS NOT NULL AND product_code<>''",
                (str(batch_id),),
            ).fetchall()
    except Exception as exc:
        log.warning(
            "[%s] sales matcher: metal-disambiguation lookup failed "
            "(non-fatal): %s", batch_id, exc,
        )
        return {}

    by_key: Dict[Tuple[str, str], set] = {}
    for r in rows:
        d = _norm(r["design_no"])
        p = (r["product_code"] or "").strip()
        if not d or not p:
            continue
        k = (d, _metal_key(r["metal"], r["metal_color"]))
        by_key.setdefault(k, set()).add(p)

    return {k: next(iter(v)) for k, v in by_key.items() if len(v) == 1}


# ── Public matcher ──────────────────────────────────────────────────────────

def match_sales_lines_to_packing(
    batch_id:   str,
    sales_rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Resolve missing ``product_code`` on parsed sales rows using same-batch
    purchase packing_lines evidence ONLY.

    Returns ``(matched_rows, summary)`` where matched_rows preserve the input
    order and length.  Rows whose product_code could not be resolved are
    returned unchanged (still empty); the DB layer's skip-empty-pc invariant
    continues to apply downstream.

    summary shape (backward-compatible keys + additive classification)::

        {
          "designs_resolved":     {design_no: product_code, ...},
          "designs_ambiguous":    {design_no: [product_code, ...], ...},
          "designs_unresolved":   [design_no, ...],   # zero candidates
          "designs_supplementary":[design_no, ...],   # category-token rows
          "unresolved_reasons":   {design_no: reason},# per-design reason
          "rows_total":   int,
          "rows_kept_pc": int,
          "rows_resolved":int,
          "rows_skipped": int,
        }

    reason ∈ {AMBIGUOUS_MATCH, MISSING_PURCHASE_AUTHORITY,
              LEGITIMATE_SUPPLEMENTARY_ROW}.
    """
    lookup       = _design_to_product_codes_for_batch(batch_id)
    metal_lookup = _design_metal_to_product_code_for_batch(batch_id)

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
        dn_raw = str(r.get("design_no") or "").strip()
        dn = _norm(dn_raw)
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
            designs_resolved[dn_raw] = cands[0]
            rows_resolved += 1
        elif len(cands) > 1:
            mk = _metal_key(r.get("metal"), r.get("metal_color"))
            resolved_pc: Optional[str] = metal_lookup.get((dn, mk))
            if resolved_pc:
                clone = dict(r)
                clone["product_code"]      = resolved_pc
                clone["resolution_source"] = "batch_packing_lines_metal"
                matched.append(clone)
                designs_resolved[dn_raw] = resolved_pc
                rows_resolved += 1
                log.info(
                    "[%s] sales matcher: design %r disambiguated via "
                    "metal-key %r -> %s", batch_id, dn_raw, mk, resolved_pc,
                )
            else:
                designs_ambiguous[dn_raw] = list(cands)
                matched.append(r)
                rows_skipped += 1
                log.warning(
                    "[%s] sales matcher: design %r ambiguous in batch "
                    "packing_lines -> %s (metal-key=%r) — leaving "
                    "product_code empty", batch_id, dn_raw, cands, mk,
                )
        else:
            designs_unresolved.add(dn_raw)
            matched.append(r)
            rows_skipped += 1
            log.info(
                "[%s] sales matcher: design %r unresolvable in batch "
                "packing_lines — leaving product_code empty",
                batch_id, dn_raw,
            )

    # ── Additive classification: reason per unresolved design ────────────────
    # Never leave a row unresolved without a recorded reason.  Category-token
    # designs (e.g. "PND" with no real design number) are LEGITIMATE
    # supplementary rows, not matcher failures.
    designs_supplementary = sorted(
        {d for d in list(designs_ambiguous.keys()) + list(designs_unresolved)
         if _norm(d) in _CATEGORY_TOKENS}
    )
    unresolved_reasons: Dict[str, str] = {}
    for d in designs_ambiguous:
        unresolved_reasons[d] = (
            "LEGITIMATE_SUPPLEMENTARY_ROW" if _norm(d) in _CATEGORY_TOKENS
            else "AMBIGUOUS_MATCH"
        )
    for d in designs_unresolved:
        unresolved_reasons[d] = (
            "LEGITIMATE_SUPPLEMENTARY_ROW" if _norm(d) in _CATEGORY_TOKENS
            else "MISSING_PURCHASE_AUTHORITY"
        )

    summary = {
        "designs_resolved":      designs_resolved,
        "designs_ambiguous":     designs_ambiguous,
        "designs_unresolved":    sorted(designs_unresolved),
        "designs_supplementary": designs_supplementary,
        "unresolved_reasons":    unresolved_reasons,
        "rows_total":            rows_total,
        "rows_kept_pc":          rows_kept_pc,
        "rows_resolved":         rows_resolved,
        "rows_skipped":          rows_skipped,
    }
    return matched, summary
