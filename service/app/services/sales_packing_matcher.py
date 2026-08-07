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
       exactly one product_code → inject.
    4. still ambiguous → invoice-scoped ascending unit_price pairing
       against purchase packing lots (equal counts, distinct prices,
       qty ≤ lot authority); otherwise leave product_code='' and
       record under designs_ambiguous.
    5. zero candidates → unresolved, leave product_code='' and
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
Equivalent color aliases (e.g. ``YW`` ↔ ``Y``) are normalised before the
key is compared — a purchase ``14KT/Y`` must not reject a sales ``YW``.

When metal cannot disambiguate (same metal, multiple purchase lots), a
third pass pairs unresolved sales rows to packing lots by ascending
``unit_price`` within an invoice-scoped, metal-compatible lot set, only
when counts and distinct prices match and each sales qty fits the lot's
authority qty.  Price never overrides metal family and never invents a
product_code — it only copies an existing purchase packing lot identity.
Never first-wins; never the global design→product_code bridge.

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
from collections import defaultdict
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

# Metal-color aliases: factory sheets use YW / WW / RG etc.; packing often
# stores the single-letter family (Y / W / R).  Map before rejecting a
# candidate.  Bi-color codes like WY (white+yellow) stay distinct.
_COLOR_ALIASES = {
    "YW": "Y", "YG": "Y", "YY": "Y",
    "WW": "W", "WG": "W",
    "RW": "R", "RG": "R", "RP": "R",
    "PW": "P", "PG": "P",
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


def _canon_color(color: Any) -> str:
    """Normalise equivalent metal-color tokens (YW→Y, WW→W, …)."""
    c = re.sub(r"\s+", "", str(color or "").strip().upper())
    if not c:
        return ""
    return _COLOR_ALIASES.get(c, c)


def _metal_key(metal: Any, color: Any) -> str:
    """Fold the two metal spellings to one canonical key.

    Purchase packing_lines: ``metal='14KT/W'``, ``metal_color=''`` (combined).
    Sales parser:           ``metal='14KT'``,   ``metal_color='W'`` (split).
    Both must produce ``'14KT/W'``.  Whitespace removed, uppercased.  When the
    metal already contains '/', it is treated as already-combined and the
    separate color is ignored — but the color segment after '/' is still
    alias-normalised (``14KT/YW`` → ``14KT/Y``).  An empty metal yields ''.
    """
    m = re.sub(r"\s+", "", str(metal or "").strip().upper())
    c = _canon_color(color)
    if not m:
        return ""
    if "/" in m:
        base, _, col = m.partition("/")
        col = _canon_color(col)
        return f"{base}/{col}" if col else base
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
    from .cpa_product_service import design_to_product_codes as _cpa_dtpc  # noqa: PLC0415
    try:
        raw = _cpa_dtpc(batch_id)
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


def _packing_lots_for_batch(
    batch_id: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """Return ``{_norm(design_no): [lot, ...]}`` from purchase packing_lines.

    Each lot carries product_code, unit_price, quantity, invoice_no — the
    invoice-scoped evidence used when metal cannot split multiple lots of
    the same design.  One packing row = one lot identity.
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
                "SELECT design_no, product_code, unit_price, quantity, "
                "invoice_no, metal, metal_color "
                "FROM packing_lines "
                "WHERE batch_id=? "
                "AND product_code IS NOT NULL AND product_code<>''",
                (str(batch_id),),
            ).fetchall()
    except Exception as exc:
        log.warning(
            "[%s] sales matcher: packing-lot lookup failed "
            "(non-fatal): %s", batch_id, exc,
        )
        return {}

    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        d = _norm(r["design_no"])
        p = (r["product_code"] or "").strip()
        if not d or not p:
            continue
        out.setdefault(d, []).append({
            "product_code": p,
            "unit_price":   float(r["unit_price"] or 0),
            "quantity":     float(r["quantity"] or 0),
            "invoice_no":   str(r["invoice_no"] or "").strip(),
            "metal_key":    _metal_key(r["metal"], r["metal_color"]),
        })
    return out


def _try_price_lot_pair(
    sales_group: List[Tuple[int, Dict[str, Any]]],
    lots: List[Dict[str, Any]],
) -> Optional[List[Tuple[int, Dict[str, Any], str]]]:
    """Pair unresolved sales rows to packing lots by ascending unit_price.

    Price is a *tie-breaker only* after stronger identity (unique design,
    then metal-key) has already failed.  Returns
    ``[(matched_index, sales_row, product_code), ...]`` when every gate
    passes; otherwise ``None`` (caller leaves rows ambiguous).

    Gates: equal counts, pairwise-distinct positive prices on both sides,
    each sales qty ≤ lot authority qty.  No first-wins; refuse on any miss.
    Caller must already have filtered *lots* to the same invoice scope and
    metal-compatible set — this helper does not invent identity.
    """
    if not sales_group or not lots:
        return None
    if len(sales_group) != len(lots):
        return None

    sales_prices = [
        float(r.get("unit_price", 0) or 0) for _, r in sales_group
    ]
    lot_prices = [float(lot.get("unit_price", 0) or 0) for lot in lots]
    if len(set(sales_prices)) != len(sales_prices):
        return None
    if len(set(lot_prices)) != len(lot_prices):
        return None
    if any(p <= 0 for p in sales_prices + lot_prices):
        return None

    sales_sorted = sorted(
        sales_group, key=lambda t: float(t[1].get("unit_price", 0) or 0),
    )
    lots_sorted = sorted(
        lots, key=lambda lot: float(lot.get("unit_price", 0) or 0),
    )

    staged: List[Tuple[int, Dict[str, Any], str]] = []
    for (idx, s_row), lot in zip(sales_sorted, lots_sorted):
        pc = (lot.get("product_code") or "").strip()
        if not pc:
            return None
        cap = float(lot.get("quantity", 0) or 0)
        s_qty = float(s_row.get("quantity", 0) or 0)
        if cap and s_qty > cap + 1e-9:
            return None
        staged.append((idx, s_row, pc))
    return staged


def _metal_compatible_lots(
    sales_group: List[Tuple[int, Dict[str, Any]]],
    lots: List[Dict[str, Any]],
) -> Optional[List[Dict[str, Any]]]:
    """Keep only lots whose metal-key agrees with the sales group.

    Price must never assign across metal families.  Rules:
      * every sales row in the group must share one non-empty metal-key;
      * every retained lot must carry that same metal-key;
      * if sales metal is empty or mixed, refuse (return None).
    """
    keys = {
        _metal_key(r.get("metal"), r.get("metal_color"))
        for _, r in sales_group
    }
    if len(keys) != 1:
        return None
    mk = next(iter(keys))
    if not mk:
        return None
    compatible = [lot for lot in lots if (lot.get("metal_key") or "") == mk]
    return compatible if compatible else None


def _apply_invoice_scoped_price_resolution(
    batch_id: str,
    matched: List[Dict[str, Any]],
    pending: List[Tuple[int, str, str, List[str]]],
    designs_ambiguous: Dict[str, List[str]],
    designs_resolved: Dict[str, str],
    counters: Dict[str, int],
) -> None:
    """Resolve multi-lot same-design rows via invoice-scoped price pairing.

    *pending* entries are ``(matched_index, dn_raw, dn_norm, cands)``.
    Mutates *matched* / summary dicts in place.  Prefer lots whose
    ``invoice_no`` matches the sales row's invoice; only fall back to the
    full design lot set when no sales row carries an invoice_no.

    Price runs only after unique-design and metal-key resolution failed, and
    only against lots that still agree on metal-key with the sales group.
    """
    if not pending:
        return
    lots_by_design = _packing_lots_for_batch(batch_id)
    if not lots_by_design:
        return

    # Group pending indices by (design_norm, invoice_scope).
    # invoice_scope = normalised sales invoice_no, or "" when absent.
    groups: Dict[Tuple[str, str], List[Tuple[int, Dict[str, Any], str, List[str]]]] = (
        defaultdict(list)
    )
    for idx, dn_raw, dn, cands in pending:
        row = matched[idx]
        if str(row.get("product_code") or "").strip():
            continue
        inv = str(row.get("invoice_no") or "").strip()
        groups[(dn, inv)].append((idx, row, dn_raw, cands))

    for (dn, inv), group in groups.items():
        all_lots = lots_by_design.get(dn) or []
        if not all_lots:
            continue
        if inv:
            scoped = [
                lot for lot in all_lots
                if str(lot.get("invoice_no") or "").strip() == inv
            ]
            # Invoice-scoped authority only — do not pull lots from other
            # invoices when the sales row names one.
            lots = scoped
        else:
            lots = all_lots

        sales_pairs = [(idx, row) for idx, row, _, _ in group]
        lots = _metal_compatible_lots(sales_pairs, lots) or []
        if not lots:
            continue

        paired = _try_price_lot_pair(sales_pairs, lots)
        if not paired:
            continue

        dn_raw = group[0][2]
        for idx, s_row, pc in paired:
            clone = dict(s_row)
            clone["product_code"] = pc
            clone["resolution_source"] = "batch_packing_lines_price"
            matched[idx] = clone
            designs_resolved[dn_raw] = pc
            counters["rows_resolved"] += 1
            counters["rows_skipped"] -= 1
            log.info(
                "[%s] sales matcher: design %r lot disambiguated via "
                "invoice-scoped price -> %s", batch_id, dn_raw, pc,
            )

        # Drop from ambiguous only when no pending row for this design
        # remains empty.
        still_open = any(
            not str(matched[idx].get("product_code") or "").strip()
            for idx, dn_r, dn_n, _ in pending
            if dn_n == dn and dn_r == dn_raw
        )
        if not still_open:
            designs_ambiguous.pop(dn_raw, None)


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
    # Rows that need the invoice-scoped price pass: (index, dn_raw, dn, cands)
    pending_price: List[Tuple[int, str, str, List[str]]] = []

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
                pending_price.append((len(matched), dn_raw, dn, list(cands)))
                matched.append(r)
                rows_skipped += 1
                log.warning(
                    "[%s] sales matcher: design %r ambiguous in batch "
                    "packing_lines -> %s (metal-key=%r) — deferring to "
                    "invoice-scoped price pass", batch_id, dn_raw, cands, mk,
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

    counters = {"rows_resolved": rows_resolved, "rows_skipped": rows_skipped}
    _apply_invoice_scoped_price_resolution(
        batch_id, matched, pending_price,
        designs_ambiguous, designs_resolved, counters,
    )
    rows_resolved = counters["rows_resolved"]
    rows_skipped = counters["rows_skipped"]

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
