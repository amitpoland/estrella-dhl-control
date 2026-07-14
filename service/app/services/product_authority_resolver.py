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
    # Packing pieces that carry a design_no but NO product_code assignment. These
    # are real received/transit pieces the over-bill gate cannot credit to any
    # product_code (product_code is the assignment key, and it is blank here — e.g.
    # a packing list that yielded design-only, so ``invoice_line_position`` /
    # ``product_code`` were never stamped). They are NOT counted as available
    # quantity (that would invent availability); they are surfaced as EVIDENCE so a
    # bare "available 0" is explained by the operator-repair reality: a piece exists
    # for the design but its product_code assignment is missing.
    unassigned_by_design: Dict[str, Dict[str, Any]] = {}

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
        elif d:
            # design present, product_code blank → unassigned packing evidence.
            try:
                uq = float(r.get("quantity") or 0)
            except (TypeError, ValueError):
                uq = 0.0
            u = unassigned_by_design.setdefault(
                d, {"quantity": 0.0, "count": 0, "invoice_no": ""})
            u["quantity"] += uq
            u["count"]    += 1
            if not u["invoice_no"]:
                u["invoice_no"] = str(r.get("invoice_no") or "")

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
        "unassigned_by_design":      unassigned_by_design,  # design_no → {quantity,count,invoice_no}
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
    draft_lines:          List[Dict[str, Any]],
    available_by_pc:      Dict[str, float],
    invoice_by_pc:        Optional[Dict[str, str]] = None,
    unassigned_by_design: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """#686 — aggregate billed quantity per product_code vs available quantity.

    A product_code MAY be billed on several draft lines (mixed lot) up to the
    available packing quantity (rule 4); only an OVER-bill (billed > available,
    rule 6) is a billing failure. Never auto-corrects/merges/picks. Pure.

    Returns one entry per product_code billed on >1 line OR over-billed; entries
    with ``over_billed=True`` listed first.
    """
    invoice_by_pc = invoice_by_pc or {}
    unassigned_by_design = unassigned_by_design or {}

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
            entry = {
                "product_code":  pc,
                "invoice_no":    invoice_by_pc.get(pc, ""),
                "billed_qty":    round(e["billed"], 4),
                "available_qty": round(avail, 4),
                "over_billed":   over,
                "line_count":    len(e["lines"]),
                "design_nos":    sorted(e["designs"]),
                "lines":         e["lines"],
            }
            # EVIDENCE (not availability): when over-billed, attach any packing
            # pieces that exist for THIS code's design(s) but carry no product_code
            # assignment. This explains a low/zero available without inventing it —
            # the gate still blocks; the operator sees the real unassigned piece(s)
            # to repair via the product-code assignment path. Never added to
            # available_qty, never auto-assigned.
            if over:
                unassigned: List[Dict[str, Any]] = []
                for dn in sorted(e["designs"]):
                    u = unassigned_by_design.get(dn)
                    if u and _q(u.get("quantity")) > 0:
                        unassigned.append({
                            "design_no":  dn,
                            "quantity":   round(_q(u.get("quantity")), 4),
                            "count":      int(u.get("count") or 0),
                            "invoice_no": u.get("invoice_no", ""),
                        })
                if unassigned:
                    entry["unassigned_packing"] = unassigned
            out.append(entry)
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


# ── deterministic position-key packing auto-assignment planner ───────────────
# Replaces the REJECTED pack_sr-sequence resolver. Historical production
# validation disproved the assumption that ``pack_sr`` order equals invoice-line
# order (45.7% of multi-row invoices reversed; 16.7% of eligible invoices would
# have been stamped with the WRONG product_code — e.g. EJL/26-27/390, /207,
# /297). The ONLY canonical link between a design-only packing piece and its
# product identity is the EXACT invoice-line key:
#
#     packing_lines.batch_id + norm(invoice_no) + packing_lines.invoice_line_position
#         ==
#     invoice_lines.batch_id + norm(invoice_no) + invoice_lines.line_position   (active)
#
# This planner is PURE and read-only. It NEVER uses pack_sr, row order, design
# order, quantity totals, or draft lines to guess identity. It emits an
# assignment ONLY on an exact, unique, quantity-consistent, non-conflicting key
# match that holds for the ENTIRE invoice group; anything missing, duplicate,
# inactive, blank, conflicting, or quantity-inconsistent yields NO assignment and
# falls through to the operator-confirmation writer (Part 2). The stamp itself is
# delegated to the canonical design-keyed writer
# ``packing_db.assign_product_code_to_unassigned_design`` — so this planner also
# guarantees the design-keyed, batch-wide write stays invoice-atomic (a design is
# writable only when EVERY one of its unassigned rows batch-wide resolves through
# a clean invoice to the SAME code).

def _norm_inv(v: Any) -> str:
    return str(v or "").strip()


def _to_position(v: Any) -> Optional[int]:
    """Coerce a line position to a positive int, else None (→ no key)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or not float(f).is_integer():     # NaN or non-integer → no key
        return None
    iv = int(f)
    return iv if iv > 0 else None


def _read_packing_full(
    batch_id: str, packing_db_path: Optional[Path],
) -> List[Dict[str, Any]]:
    """Full packing rows (incl. ``id``) for the planner. Raises on read failure."""
    bid = (batch_id or "").strip()
    if packing_db_path is not None:
        with sqlite3.connect(str(packing_db_path)) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT id, invoice_no, invoice_line_position, product_code, "
                "design_no, quantity FROM packing_lines WHERE batch_id=?",
                (bid,),
            ).fetchall()
        return [dict(r) for r in rows]
    from . import packing_db as _pdb  # noqa: PLC0415
    if getattr(_pdb, "_db_path", None) is None:
        raise PackingAuthorityUnavailable(
            "packing_db is not initialised — cannot plan position-key assignment")
    return list(_pdb.get_packing_lines_for_batch(bid) or [])


def _read_active_invoice_lines(
    batch_id: str, documents_db_path: Optional[Path],
) -> List[Dict[str, Any]]:
    """Active invoice lines (the product_code MINT) for the planner."""
    bid = (batch_id or "").strip()
    if documents_db_path is not None:
        with sqlite3.connect(str(documents_db_path)) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT invoice_no, line_position, product_code, quantity, active "
                "FROM invoice_lines WHERE batch_id=? AND active=1",
                (bid,),
            ).fetchall()
        return [dict(r) for r in rows]
    from . import document_db as _ddb  # noqa: PLC0415
    return list(_ddb.get_invoice_lines_for_batch(bid) or [])


def plan_position_key_assignments(
    batch_id: str,
    *,
    packing_rows:  Optional[List[Dict[str, Any]]] = None,
    invoice_lines: Optional[List[Dict[str, Any]]] = None,
    packing_db_path:   Optional[Path] = None,
    documents_db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Plan deterministic packing product_code assignments by EXACT position key.

    Pure + read-only. Returns::

        {
          "batch_id":         str,
          "status":           "deterministic" | "none",
          "assignments":      [{"design_no", "product_code", "expected_count",
                                "rows": [{"row_id","invoice_no",
                                          "invoice_line_position","quantity"}…]}],
          "refusals":         [{"invoice_no", "reason", ...}],
          "invoices_scanned": int,
        }

    A read failure (packing/invoice authority unreadable) returns an EMPTY plan
    (status ``none``) — the readiness over-bill guard fails closed on its own, and
    the caller treats an empty plan as "assign nothing".
    """
    bid = str(batch_id or "").strip()
    out: Dict[str, Any] = {"batch_id": bid, "status": "none",
                           "assignments": [], "refusals": [], "invoices_scanned": 0}
    if packing_rows is None and not bid:
        return out

    def _q(v: Any) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    try:
        prows = (packing_rows if packing_rows is not None
                 else _read_packing_full(bid, packing_db_path))
        irows = (invoice_lines if invoice_lines is not None
                 else _read_active_invoice_lines(bid, documents_db_path))
    except Exception:
        # Authority unreadable → assign nothing (fail closed elsewhere).
        return out

    # Active invoice-line codes indexed by (norm invoice_no, position). Blank
    # invoice_no / position are dropped; duplicate positions are kept so the
    # per-row check can detect and refuse them (rule: exactly one active line).
    inv_by_pos: Dict[Any, List[Dict[str, Any]]] = {}
    for r in irows:
        if int(r.get("active", 1) or 0) != 1:       # respect injected active flag
            continue
        inv = _norm_inv(r.get("invoice_no"))
        pos = _to_position(r.get("line_position"))
        if not inv or pos is None:
            continue
        inv_by_pos.setdefault((inv, pos), []).append(
            {"code": str(r.get("product_code") or "").strip(),
             "qty": _q(r.get("quantity"))})

    # Total packing quantity per (invoice, position) across ALL rows (assigned +
    # unassigned) — the quantity-consistency check: the packing at a position
    # must exactly account for the invoice line's quantity.
    pack_qty_by_pos: Dict[Any, float] = {}
    pack_by_inv: Dict[str, List[Dict[str, Any]]] = {}
    for r in prows:
        inv = _norm_inv(r.get("invoice_no"))
        pack_by_inv.setdefault(inv, []).append(r)
        pos = _to_position(r.get("invoice_line_position"))
        if inv and pos is not None:
            pack_qty_by_pos[(inv, pos)] = pack_qty_by_pos.get((inv, pos), 0.0) + _q(r.get("quantity"))

    # Per-invoice: a clean invoice is one where EVERY unassigned packing row has
    # an exact, unique, non-blank, quantity-consistent invoice-line match. Any
    # deviation refuses the WHOLE invoice group (never a partial assignment).
    row_code: Dict[str, str] = {}      # packing row id → matched code (clean invoices)
    clean_invoices: set = set()
    for inv, rows in pack_by_inv.items():
        if not inv:
            continue
        out["invoices_scanned"] += 1
        unassigned = [r for r in rows if not str(r.get("product_code") or "").strip()]
        if not unassigned:
            continue                    # nothing to do (idempotent no-op)
        reason: Optional[str] = None
        matched: List[Any] = []
        for r in unassigned:
            pos = _to_position(r.get("invoice_line_position"))
            if pos is None:
                reason = "a packing row has no invoice_line_position (no deterministic key)"
                break
            cands = inv_by_pos.get((inv, pos))
            if not cands:
                reason = f"no active invoice line at position {pos}"
                break
            if len(cands) != 1:
                reason = f"duplicate active invoice line at position {pos}"
                break
            code = cands[0]["code"]
            if not code:
                reason = f"invoice line at position {pos} has a blank product_code"
                break
            if abs(pack_qty_by_pos.get((inv, pos), 0.0) - cands[0]["qty"]) > 1e-9:
                reason = (f"quantity mismatch at position {pos} "
                          f"(packing {pack_qty_by_pos.get((inv, pos), 0.0):g} vs "
                          f"invoice {cands[0]['qty']:g})")
                break
            matched.append((r, code))
        if reason is not None:
            out["refusals"].append({"invoice_no": inv, "reason": reason})
            continue
        clean_invoices.add(inv)
        for r, code in matched:
            row_code[str(r.get("id"))] = code

    # Design-keyed writer safety + invoice atomicity. The Part 2 writer stamps a
    # design's unassigned rows BATCH-WIDE, so a design may be written only when
    # ALL of its unassigned rows (across the batch) resolved through a clean
    # invoice to ONE code. Blank design cannot be written (writer requires it) →
    # blocked. A blocked design blocks every invoice it appears in; a blocked
    # invoice blocks every design in it — resolved to a fixpoint.
    design_rows: Dict[str, List[Dict[str, Any]]] = {}
    design_invs: Dict[str, set] = {}
    inv_designs: Dict[str, set] = {}
    for r in prows:
        if str(r.get("product_code") or "").strip():
            continue                    # already assigned — never overwrite
        d = str(r.get("design_no") or "").strip()
        rid = str(r.get("id"))
        inv = _norm_inv(r.get("invoice_no"))
        design_rows.setdefault(d, []).append({
            "row_id": rid, "invoice_no": inv,
            "invoice_line_position": _to_position(r.get("invoice_line_position")),
            "quantity": _q(r.get("quantity")),
            "code": row_code.get(rid),
        })
        design_invs.setdefault(d, set()).add(inv)
        inv_designs.setdefault(inv, set()).add(d)

    blocked_designs: set = set()
    design_code: Dict[str, str] = {}
    for d, items in design_rows.items():
        codes = {it["code"] for it in items if it["code"]}
        unmatched = any(it["code"] is None for it in items)
        if not d or unmatched or len(codes) != 1:
            blocked_designs.add(d)
        else:
            design_code[d] = next(iter(codes))

    blocked_invoices: set = {inv for inv in pack_by_inv
                             if inv and inv not in clean_invoices}
    changed = True
    while changed:
        changed = False
        for inv in list(blocked_invoices):
            for d in inv_designs.get(inv, ()):
                if d not in blocked_designs:
                    blocked_designs.add(d); changed = True
        for d in list(blocked_designs):
            for inv in design_invs.get(d, ()):
                if inv not in blocked_invoices:
                    blocked_invoices.add(inv); changed = True

    for d, code in design_code.items():
        if d in blocked_designs:
            continue
        rows = design_rows[d]
        out["assignments"].append({
            "design_no":      d,
            "product_code":   code,
            "expected_count": len(rows),
            "rows":           [{"row_id": it["row_id"],
                                "invoice_no": it["invoice_no"],
                                "invoice_line_position": it["invoice_line_position"],
                                "quantity": it["quantity"]} for it in rows],
        })

    out["assignments"].sort(key=lambda a: (a["rows"][0]["invoice_no"], a["product_code"]))
    out["status"] = "deterministic" if out["assignments"] else "none"
    return out


__all__ = [
    "PackingAuthorityUnavailable",
    "resolve_batch_product_authority",
    "design_to_product_codes",
    "available_quantity_by_product_code",
    "validate_billed_product_code",
    "reconcile_billed_ambiguity",
    "analyze_product_code_billing",
    "reconcile_billed_lines",
    "plan_position_key_assignments",
    "get_registered_goods_state",
    "get_registered_goods_state_batch",
]
