"""
product_authority_resolver.py — the ONE canonical product-identity resolver.

Authority contract (accepted design report, Phase 0–2):
  * invoice_lines      = immutable product_code MINT (invoice_no + line_position).
  * packing_lines      = per-piece OPERATIONAL authority (this module reads it).
  * product_master     = cross-batch REGISTRY / advisory — NOT a billing gate.
  * sales_packing_lines = sales projection.

Canonical authority rules (verbatim from the task):
  1. packing_lines is the per-piece authority.
  2. product_code = invoice_no + invoice_line_position is mixed-lot authority.
  3. design_no is descriptive, not unique.
  4. one product_code may cover multiple design rows and quantities.
  5. a billed product_code "wins" if it validates against packing_lines.
  6. billed quantity must not exceed available packing quantity.
  7. design_no-alone is only a fallback when product_code authority is absent.
  8. NULL/blank product_code rows must not inflate ambiguity candidates.
  9. product_master is advisory only and must not become a hard gate.

Before this module, the design_no→product_code derivation was duplicated in
design_product_bridge.populate_from_packing, proforma_draft_sync, and
sales_packing_matcher (three slightly-different ``SELECT DISTINCT design_no,
product_code`` queries), which produced the false-ambiguity symptoms #684/#686
patched. This module is the single source those resolvers now call. It is
read-only with respect to packing_lines and writes nothing.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class PackingAuthorityUnavailable(RuntimeError):
    """Raised internally when packing_lines (the per-piece product authority)
    cannot be READ — packing_db not initialised, locked, missing table, or a
    query error. This is DISTINCT from a successful read that returns zero rows.

    The resolver converts it into a structured ``authority_available=False``
    snapshot so the proforma readiness gate can FAIL CLOSED (billing safety): the
    system must never let an over-bill pass ``ready=true`` merely because it could
    not read the authority to prove product_code validity / available quantity /
    over-bill status (OQ-PR689-OVERBILL-FAILCLOSED).
    """


# ── packing_lines read (the one authority read) ──────────────────────────────

def _packing_rows(
    batch_id: str,
    *,
    packing_db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Return all packing_lines rows for the batch (per-piece grain).

    Uses the standard ``packing_db.get_packing_lines_for_batch`` in production; a
    ``packing_db_path`` override (tests / batch-isolation callers) reads that db
    directly with the identical projection.

    RAISES ``PackingAuthorityUnavailable`` when the read itself FAILS (packing_db
    not initialised, locked, missing table, or query error) so the caller can
    fail CLOSED. Returns ``[]`` ONLY for a genuinely empty result — no batch_id,
    or a SUCCESSFUL read of a batch that has zero packing rows — never to mask a
    read failure.
    """
    bid = (batch_id or "").strip()
    if not bid:
        return []
    if packing_db_path is not None:
        try:
            with sqlite3.connect(str(packing_db_path)) as con:
                con.row_factory = sqlite3.Row
                rows = con.execute(
                    "SELECT design_no, product_code, quantity, invoice_no, "
                    "invoice_line_position FROM packing_lines WHERE batch_id=?",
                    (bid,),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            raise PackingAuthorityUnavailable(
                f"packing read failed for {bid!r}: {type(exc).__name__}: {exc}"
            ) from exc
    from . import packing_db as _pdb  # noqa: PLC0415
    if getattr(_pdb, "_db_path", None) is None:
        raise PackingAuthorityUnavailable(
            "packing_db is not initialised — cannot read product authority")
    try:
        return list(_pdb.get_packing_lines_for_batch(bid) or [])
    except Exception as exc:
        raise PackingAuthorityUnavailable(
            f"packing read failed for {bid!r}: {type(exc).__name__}: {exc}"
        ) from exc


def resolve_batch_product_authority(
    batch_id: str,
    *,
    packing_rows: Optional[List[Dict[str, Any]]] = None,
    packing_db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """ONE read of packing_lines → the canonical product-authority snapshot.

    Returns::

        {
          "batch_id":                   str,
          "design_to_product_codes":    {design_no(stripped): [product_code, …]},
              # rule 3/4/8 — case-preserved keys, NULL/blank rows excluded
          "available_by_product_code":  {product_code: total_quantity},   # rule 6
          "invoice_by_product_code":    {product_code: invoice_no},
          "product_codes":              set(non-blank product_codes),
          "rows_scanned":               int,   # distinct non-blank (design, code) pairs
          "rows_skipped":               int,   # distinct pairs with a blank side
        }

    ``design_to_product_codes`` keys are the *stripped* (case-preserved) design_no
    to match the historical bridge / proforma_draft_sync behaviour; callers that
    need normalised keys (sales_packing_matcher) re-key the returned map.
    """
    # Authority availability: an injected ``packing_rows`` (incl. empty) is a
    # successful read. Otherwise read packing_lines; a read FAILURE fails CLOSED
    # (authority_available=False) — never silently treated as an empty batch.
    authority_available = True
    authority_error = ""
    if packing_rows is not None:
        rows = packing_rows
    else:
        try:
            rows = _packing_rows(batch_id, packing_db_path=packing_db_path)
        except PackingAuthorityUnavailable as exc:
            authority_available = False
            authority_error = str(exc)
            rows = []

    design_to_codes: Dict[str, set] = {}
    available: Dict[str, float] = {}
    invoice_by: Dict[str, str] = {}
    product_codes: set = set()
    seen_pairs: set = set()
    skipped_pairs: set = set()

    for r in (rows or []):
        d = str(r.get("design_no") or "").strip()
        p = str(r.get("product_code") or "").strip()

        # Available quantity is summed per product_code over ALL rows (rule 6).
        if p:
            try:
                q = float(r.get("quantity") or 0)
            except (TypeError, ValueError):
                q = 0.0
            available[p] = available.get(p, 0.0) + q
            invoice_by.setdefault(p, str(r.get("invoice_no") or ""))
            product_codes.add(p)

        # Design candidates exclude any pair with a blank side (rule 8).
        if not d or not p:
            skipped_pairs.add((d, p))
            continue
        seen_pairs.add((d, p))
        design_to_codes.setdefault(d, set()).add(p)

    return {
        "batch_id":                  (batch_id or "").strip(),
        "design_to_product_codes":   {d: sorted(c) for d, c in design_to_codes.items()},
        "available_by_product_code": available,           # raw sums (no rounding)
        "invoice_by_product_code":   invoice_by,
        "product_codes":             product_codes,
        "rows_scanned":              len(seen_pairs),
        "rows_skipped":              len(skipped_pairs),
        "authority_available":       authority_available,  # False → fail closed
        "authority_error":           authority_error,
    }


def design_to_product_codes(
    batch_id: str,
    *,
    packing_rows: Optional[List[Dict[str, Any]]] = None,
    packing_db_path: Optional[Path] = None,
) -> Dict[str, List[str]]:
    """Canonical ``{design_no(stripped): [product_code, …]}`` for the batch.

    This replaces the three duplicated ``SELECT DISTINCT design_no, product_code``
    queries. NULL/blank product_code rows are excluded (rule 8).
    """
    return resolve_batch_product_authority(
        batch_id, packing_rows=packing_rows, packing_db_path=packing_db_path,
    )["design_to_product_codes"]


def available_quantity_by_product_code(
    batch_id: str,
    *,
    packing_rows: Optional[List[Dict[str, Any]]] = None,
    packing_db_path: Optional[Path] = None,
) -> Dict[str, float]:
    """Canonical available purchase quantity per product_code (rule 6)."""
    return resolve_batch_product_authority(
        batch_id, packing_rows=packing_rows, packing_db_path=packing_db_path,
    )["available_by_product_code"]


def validate_billed_product_code(
    batch_id: str,
    product_code: str,
    design_no: Optional[str] = None,
    *,
    packing_rows: Optional[List[Dict[str, Any]]] = None,
    packing_db_path: Optional[Path] = None,
) -> bool:
    """True iff ``product_code`` exists in packing_lines for the batch (rule 5).

    When ``design_no`` is given, additionally require that the product_code is a
    valid candidate for that design (rule 7 — design context, never a guess).
    """
    pc = str(product_code or "").strip()
    if not pc:
        return False
    snap = resolve_batch_product_authority(
        batch_id, packing_rows=packing_rows, packing_db_path=packing_db_path)
    if pc not in snap["product_codes"]:
        return False
    if design_no:
        d = str(design_no).strip()
        return pc in snap["design_to_product_codes"].get(d, [])
    return True


# ── billed-line reconciliation (single home for #684 + #686 logic) ───────────

def reconcile_billed_ambiguity(
    ambiguous_design_codes: Dict[str, Any],
    draft_lines: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """#684 — reconcile batch-level design_no ambiguity against what is billed.

    A design only blocks when a BILLED line cannot be pinned to a valid
    product_code (rules 5/7). A billed line whose product_code is a valid
    candidate resolves it; a not-billed design is a batch artifact. The code is
    only VALIDATED against the candidate set, never guessed. Pure function.

    Returns ``{genuinely_ambiguous, resolved, not_billed}``.
    """
    def _norm(s: Any) -> str:
        return str(s or "").strip().upper()

    billed_by_design: Dict[str, List[str]] = {}
    for ln in (draft_lines or []):
        billed_by_design.setdefault(_norm(ln.get("design_no")), []).append(
            _norm(ln.get("product_code")))

    genuinely_ambiguous: Dict[str, List[str]] = {}
    resolved:            Dict[str, List[str]] = {}
    not_billed:          List[str] = []

    for design, codes in (ambiguous_design_codes or {}).items():
        candidates = {_norm(c) for c in (codes or [])}
        billed_pcs = billed_by_design.get(_norm(design))
        if not billed_pcs:
            not_billed.append(design)
            continue
        if all(pc and pc in candidates for pc in billed_pcs):
            resolved[design] = sorted({pc for pc in billed_pcs})
        else:
            genuinely_ambiguous[design] = sorted(codes)

    return {
        "genuinely_ambiguous": genuinely_ambiguous,
        "resolved":            resolved,
        "not_billed":          not_billed,
    }


def analyze_product_code_billing(
    draft_lines:      List[Dict[str, Any]],
    available_by_pc:  Dict[str, float],
    invoice_by_pc:    Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """#686 — aggregate billed quantity per product_code vs available quantity.

    A product_code MAY be billed on several draft lines (mixed lot) up to the
    available packing quantity (rule 4); only an OVER-bill (billed > available,
    rule 6) is a billing failure. Never auto-corrects/merges/picks. Pure.

    Returns one entry per product_code billed on >1 line OR over-billed; entries
    with ``over_billed=True`` listed first.
    """
    invoice_by_pc = invoice_by_pc or {}

    def _q(v: Any) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    agg: Dict[str, Dict[str, Any]] = {}
    for i, ln in enumerate(draft_lines or []):
        pc = str(ln.get("product_code") or "").strip()
        if not pc:
            continue
        d = str(ln.get("design_no") or "").strip()
        e = agg.setdefault(pc, {"billed": 0.0, "lines": [], "designs": set()})
        qty = _q(ln.get("qty"))
        e["billed"] += qty
        e["lines"].append({"idx": i, "line_id": ln.get("line_id"),
                           "design_no": d, "qty": qty})
        if d:
            e["designs"].add(d)

    out: List[Dict[str, Any]] = []
    for pc, e in agg.items():
        avail = _q(available_by_pc.get(pc))
        # 1e-9 absolute tolerance. ``quantity`` is a PIECE COUNT: only the
        # piece-count column aliases (qty / quantity / pcs / pcs_qty / qty_pcs
        # / nos) feed it; weight is captured separately in gross/net_weight.
        # It is integer-valued in practice (REAL column only for schema
        # flexibility), and a sum of integer-valued float64s is exact (integers
        # below 2**53 have no representation error), so the epsilon never masks
        # a real 1-piece over-bill — it only absorbs the tiny decimal→binary
        # representation error if a supplier ever ships a fractional quantity
        # (~1e-14 at these magnitudes, well under 1e-9).
        over = e["billed"] > avail + 1e-9
        if len(e["lines"]) > 1 or over:
            out.append({
                "product_code":  pc,
                "invoice_no":    invoice_by_pc.get(pc, ""),
                "billed_qty":    round(e["billed"], 4),
                "available_qty": round(avail, 4),
                "over_billed":   over,
                "line_count":    len(e["lines"]),
                "design_nos":    sorted(e["designs"]),
                "lines":         e["lines"],
            })
    out.sort(key=lambda x: (not x["over_billed"], x["product_code"]))
    return out


def reconcile_billed_lines(
    batch_id: str,
    draft_lines: List[Dict[str, Any]],
    *,
    ambiguous_design_codes: Optional[Dict[str, Any]] = None,
    packing_rows: Optional[List[Dict[str, Any]]] = None,
    packing_db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Combined billed-line reconciliation against the packing authority.

    Runs the #684 ambiguity reconciliation (operator-resolution-aware
    ``ambiguous_design_codes`` is supplied by the caller, since operator
    resolutions live in design_product_bridge) and the #686 over-bill analysis
    (quantity vs the authority snapshot) in one call.

    Returns ``{"ambiguity": {...}, "duplicates": [...], "available_by_product_code": {...}}``.
    """
    snap = resolve_batch_product_authority(
        batch_id, packing_rows=packing_rows, packing_db_path=packing_db_path)
    amb = reconcile_billed_ambiguity(ambiguous_design_codes or {}, draft_lines)
    dup = analyze_product_code_billing(
        draft_lines, snap["available_by_product_code"],
        snap["invoice_by_product_code"])
    return {
        "ambiguity":                 amb,
        "duplicates":                dup,
        "available_by_product_code": snap["available_by_product_code"],
    }


# ── C-3g: registered-goods sync-state query (product authority) ──────────────
# The wFirma-goods sync state (confirmed wfirma_product_id + the display name
# as last synced to wFirma) is owned by the sync layer (wfirma_db). Business
# surfaces that need it — resolve-drift detection, sync-names before-value,
# invoice line-name enrichment — ask the product authority through this
# narrow, purpose-named API instead of reading raw cache rows. Replaces the
# retired transitional passthroughs get_cached_product/_batch/
# list_cached_products (Phase-C C-3g; C-1d declared residual 2).

def get_registered_goods_state(product_code: str) -> Optional[Dict[str, Any]]:
    """Return {"wfirma_product_id", "product_name"} for a code, or None.

    ``product_name`` is the goods display name as last synced to wFirma —
    NOT the legal description (that is the description_engine's authority).
    """
    from . import wfirma_db as _wfdb  # sync layer — authority-internal read
    if _wfdb._db_path is None:
        return None
    row = _wfdb.get_product(product_code)
    if not row:
        return None
    return {
        "wfirma_product_id": (row.get("wfirma_product_id") or "").strip(),
        "product_name":      (row.get("product_name") or "").strip(),
    }


def get_registered_goods_state_batch(codes: List[str]) -> Dict[str, Dict[str, Any]]:
    """Batch form of get_registered_goods_state: {code: state} for known codes."""
    from . import wfirma_db as _wfdb  # sync layer — authority-internal read
    if _wfdb._db_path is None or not codes:
        return {}
    rows = _wfdb.get_products_batch(list(codes)) or {}
    return {
        code: {
            "wfirma_product_id": (r.get("wfirma_product_id") or "").strip(),
            "product_name":      (r.get("product_name") or "").strip(),
        }
        for code, r in rows.items() if r
    }


__all__ = [
    "PackingAuthorityUnavailable",
    "resolve_batch_product_authority",
    "design_to_product_codes",
    "available_quantity_by_product_code",
    "validate_billed_product_code",
    "reconcile_billed_ambiguity",
    "analyze_product_code_billing",
    "reconcile_billed_lines",
    "get_registered_goods_state",
    "get_registered_goods_state_batch",
]
