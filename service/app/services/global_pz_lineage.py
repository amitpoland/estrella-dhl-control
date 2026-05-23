"""
global_pz_lineage.py — Invoice-to-packing relational authority for Global Jewellery.

Maps the three-layer structure for every Global shipment:

    Invoice summary position (INV-NN)
        → packing list rows (individual items by serial number)
            → PZ line (grouped wFirma warehouse document line)

AUTHORITY MODEL
---------------
This module does NOT compute landed cost, VAT, freight, or duty.
It provides the structural lineage — which packing rows belong to which
invoice position, and which invoice positions feed which PZ line.

STATUS MODEL (4 independent dimensions)
----------------------------------------
Every ``LineageResult`` carries four separate match-quality flags:

    shipment_total_match       — do aggregate qty / FOB totals balance?
    invoice_position_match     — is every position slot exactly matched?
    packing_row_assignment_match — was every packing row assigned once?
    pz_line_visibility_match   — does every PZ line expose its full breakdown?

Each dimension is independently: FULL / WARNING / PARTIAL / UNMATCHED / N/A.

``match_status`` (top-level) is the worst of the four dimensions mapped to:
    FULL_MATCH / WARNING_MATCH / PARTIAL_MATCH / UNMATCHED

Rule: ``match_status`` is NEVER ``FULL_MATCH`` if any invoice-position link
is PARTIAL or OVERFLOW (i.e. if ``invoice_position_match != "FULL"``).

MATCHING ALGORITHM
------------------
Tier 1 — Primary (exact):
    (unit, metal_en, stone_family, item_type) must match an invoice position
    that contains that item_type in its product rows.

Tier 2 — Fallback (OCR-metal tolerance):
    When tier-1 fails, try (unit, stone_family, item_type). This handles
    packing PDFs where OCR misreads the metal column (e.g. a 14KT Gold item
    parsed as 925SL but with an LGD stone_detail that uniquely identifies the
    position).

Budget allocation:
    When multiple invoice positions share the same match key, rows are
    allocated to positions in position_no order, filling each position's
    item-type budget before spilling to the next.  This sharing is never
    silent: any affected link receives a ``confidence_reason`` naming the
    shared positions, and ``invoice_position_match`` is set to WARNING or
    lower — never FULL.

Duplicate enforcement:
    Each packing serial_no is tracked in a seen-set.  Any serial that
    appears more than once in ``packing_rows`` is recorded in
    ``duplicate_assignments`` and skipped on subsequent appearances.

STONE CLASSIFICATION
--------------------
Stone family is derived from a packing row's ``stone_detail`` field using the
same vocabulary as ``global_invoice_position_parser._STONE_RULES``:

    Lab Grown Diamond Jewellery   — stone_detail contains LAB / LGD
    Diamond & CZ Stud Jewellery   — stone_detail contains natural Diamond + CZ
    CZ & Colour Stone Jewellery   — stone_detail contains CZ + colour-stone term
    CZ Stud Jewellery             — stone_detail contains CZ only
    Colour Stone Jewellery        — stone_detail contains colour stone, no CZ
    Diamond Jewellery             — stone_detail contains natural Diamond only
    Plain Jewellery               — stone_detail empty / no matching tokens

INPUTS / OUTPUTS
----------------
``build_global_pz_lineage(invoice_positions, packing_rows)`` takes:
    - invoice_positions : from ``parse_invoice_positions_from_text / _from_pdf``
    - packing_rows      : from ``parse_global_packing_pdf / parse_global_packing_excel``
    - pz_rows           : optional list from pz_rows.json (for PZ line lineage)

Returns ``LineageResult`` with:
    - position_links    : one PositionRowLink per (invoice_pos, item_type) slot
    - pz_line_lineages  : one PZLineLineage per PZ output line
    - unmatched_packing_serials   : rows that could not be assigned
    - unmatched_invoice_positions : positions with no assigned packing rows
    - duplicate_assignments       : packing serials seen more than once
    - shipment_total_match / invoice_position_match /
      packing_row_assignment_match / pz_line_visibility_match
    - match_status      : FULL_MATCH / WARNING_MATCH / PARTIAL_MATCH / UNMATCHED

Pure function. No DB writes. Never raises. Returns a LineageResult with
match_status=UNMATCHED on any fatal input error.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


__all__ = [
    "build_global_pz_lineage",
    "LineageResult",
    "PositionRowLink",
    "CategoryBreakdownItem",
    "PZLineLineage",
    "classify_stone_from_detail",
    "packing_metal_to_en",
    "item_type_unit",
]


# ─────────────────────────────────────────────────────────────────────────────
# Stone vocabulary (matches global_invoice_position_parser._STONE_RULES output)
# ─────────────────────────────────────────────────────────────────────────────

_STONE_LGD        = "Lab Grown Diamond Jewellery"
_STONE_DIA_CZ     = "Diamond & CZ Stud Jewellery"
_STONE_CZ_CLS     = "CZ & Colour Stone Jewellery"
_STONE_CZ         = "CZ Stud Jewellery"
_STONE_COLOUR     = "Colour Stone Jewellery"
_STONE_DIA        = "Diamond Jewellery"
_STONE_PLAIN      = "Plain Jewellery"

# Colour-stone keywords that appear in packing list stone_detail lines.
# Ordered longest-first to avoid partial-token false positives.
_CLS_TERMS: Tuple[str, ...] = (
    "TOURMALINE", "AQUAMARINE", "TANZANITE", "MALACHITE",
    "AMETHYST", "SAPPHIRE", "EMERALD", "GARNET", "TOPAZ",
    "PERIDOT", "SPINEL", "CITRINE",
    "RUBY", "OPAL", "ONYX", "PEARL",
)


def classify_stone_from_detail(stone_detail: str) -> str:
    """Map a packing row ``stone_detail`` string to a stone-family label.

    The returned string uses the same vocabulary as
    ``global_invoice_position_parser._STONE_RULES`` (stone_en field).

    Returns ``"Plain Jewellery"`` for empty / unrecognised input.
    """
    sd = (stone_detail or "").upper()
    if not sd.strip():
        return _STONE_PLAIN

    has_lab     = bool(re.search(r"\bLAB\b|\bLGD\b",                   sd))
    has_dia     = bool(re.search(r"\bDIAMOND\b|\bROUND CUT DIAMOND\b|\bDIA\b", sd))
    has_cz      = bool(re.search(r"\bCZ\b",                            sd))
    has_cls     = any(t in sd for t in _CLS_TERMS)

    if has_lab:
        return _STONE_LGD
    if has_dia and has_cz:
        return _STONE_DIA_CZ
    if has_cz and has_cls:
        return _STONE_CZ_CLS
    if has_cz:
        return _STONE_CZ
    if has_dia:
        return _STONE_DIA
    if has_cls:
        return _STONE_COLOUR
    return _STONE_PLAIN


# ─────────────────────────────────────────────────────────────────────────────
# Metal normalisation (packing row → English label matching invoice positions)
# ─────────────────────────────────────────────────────────────────────────────

_PACKING_METAL_TO_EN: Tuple[Tuple[str, str], ...] = (
    # (substring in packing row metal (upper), en_label matching invoice)
    ("925",      "925 Silver"),
    ("SILVER",   "925 Silver"),
    ("22KT",     "22KT Gold"),
    ("22",       "22KT Gold"),
    ("18KT",     "18KT Gold"),
    ("18",       "18KT Gold"),
    ("14KT",     "14KT Gold"),
    ("14",       "14KT Gold"),
    ("9KT",      "09KT Gold"),
    ("09KT",     "09KT Gold"),
    ("9",        "09KT Gold"),   # bare "9" from Global packing PDF
    ("PT950",    "PT950 Platinum"),
    ("PT900",    "PT900 Platinum"),
)


def packing_metal_to_en(metal: str) -> str:
    """Normalise packing row metal column to the English label used in
    invoice positions (matching ``global_invoice_position_parser`` output).

    Returns the input unchanged when no rule matches.
    """
    u = (metal or "").upper().strip()
    for substr, en in _PACKING_METAL_TO_EN:
        if substr in u:
            return en
    return metal


# ─────────────────────────────────────────────────────────────────────────────
# Unit determination from item_type
# ─────────────────────────────────────────────────────────────────────────────

_PRS_TYPES = frozenset({"EARRING", "EARRINGS"})


def item_type_unit(item_type: str) -> str:
    """Return 'PRS' for earring-category items, 'PCS' for all others."""
    return "PRS" if (item_type or "").upper() in _PRS_TYPES else "PCS"


# ─────────────────────────────────────────────────────────────────────────────
# Status severity ordering
# ─────────────────────────────────────────────────────────────────────────────

# Higher number = worse.  "N/A" is neutral (does not degrade overall status).
_DIM_SEVERITY: Dict[str, int] = {
    "FULL":      0,
    "N/A":       0,
    "WARNING":   1,
    "PARTIAL":   2,
    "UNMATCHED": 3,
}

_DIM_TO_OVERALL: Dict[str, str] = {
    "FULL":      "FULL_MATCH",
    "WARNING":   "WARNING_MATCH",
    "PARTIAL":   "PARTIAL_MATCH",
    "N/A":       "FULL_MATCH",
    "UNMATCHED": "UNMATCHED",
}


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PositionRowLink:
    """Relational link between one (invoice position, item_type) slot and
    the packing rows assigned to it.

    One ``PositionRowLink`` exists per item_type within each invoice position.
    For a single-type position (e.g. INV-01 Bracelet), there is one link.
    For a four-type position (INV-04: Bangle, Bracelet, Pendant, Ring), there
    are four links — all pointing to the same ``position_no``.

    ``invoice_position_no`` preserves the INV-NN numbering from the invoice
    parser independently of the PZ product-code sequence.

    Packing serials in ``packing_serials`` are the supplier's original row
    numbers from the packing list, not internally derived indexes.
    """
    position_no:              int       # invoice position number (INV-NN)
    invoice_item_type:        str       # e.g. "BRACELET"
    unit:                     str       # PCS / PRS
    metal_en:                 str       # "925 Silver", "09KT Gold", …
    stone_en:                 str       # "CZ Stud Jewellery", "Lab Grown Diamond…", …
    invoice_qty:              float     # quantity declared in invoice
    invoice_value_usd:        float     # USD value declared in invoice

    # Assigned packing rows (supplier serial numbers, preserved as-is)
    packing_serials:          List[int] = field(default_factory=list)
    style_codes:              List[str] = field(default_factory=list)
    packing_qty_sum:          float     = 0.0
    packing_value_sum:        float     = 0.0

    # Quality indicators
    match_status:             str       = "EMPTY"
    # FULL     — packing_qty == invoice_qty within tolerance
    # PARTIAL  — packing_qty < invoice_qty (rows short of declaration)
    # OVERFLOW — packing_qty > invoice_qty (more rows than budgeted)
    # EMPTY    — no packing rows assigned

    match_tier:               str       = ""
    # EXACT              — matched on (unit, metal_en, stone_en, item_type)
    # OCR_METAL_FALLBACK — metal column in packing PDF misread; matched on
    #                      (unit, stone_en, item_type) only
    # MIXED              — some rows via EXACT, some via OCR_METAL_FALLBACK
    # UNASSIGNED         — no rows assigned (link is EMPTY)

    confidence_reason:        str       = ""
    # Non-empty on every PARTIAL, OVERFLOW, or ambiguous link.
    # Explains WHY the match is imperfect:
    #   "packing_qty 9 exceeds invoice_qty 8 by 1; stone family 'CZ & Colour
    #    Stone Jewellery' shared across positions [2, 8]; row allocation is
    #    order-dependent — cannot guarantee per-position accuracy"

    stone_family_shared_positions: List[int] = field(default_factory=list)
    # Other invoice position_no values that share the same stone-family
    # match key. Non-empty → budget-fill is order-dependent between them.


@dataclass
class CategoryBreakdownItem:
    """One item-type slot within a mixed PZ line."""
    item_type:           str
    invoice_qty:         float
    packing_qty_sum:     float
    invoice_value_usd:   float
    packing_value_sum:   float
    packing_serials:     List[int] = field(default_factory=list)
    style_codes:         List[str] = field(default_factory=list)


@dataclass
class PZLineLineage:
    """Full lineage for a single PZ output line.

    Each PZ line corresponds to one authority row (INV-NN) from the engine.
    Mixed positions expose all underlying item types via ``category_breakdown``
    — no category is silently hidden behind the ``canonical_item_type``.

    ``pz_position_no`` is the sequential 1-based PZ line number (product-code
    sequence).  ``invoice_position_no`` is the INV-NN invoice numbering.
    These are tracked separately: for most shipments they coincide, but they
    may diverge if the PZ was assembled in a different order than the invoice.
    """
    pz_product_code:     str       # e.g. "088/2026-2027-2"
    pz_position_no:      int       # 1-based PZ line sequence (from product_code)
    canonical_item_type: str       # first item type (engine grouping key)
    pz_qty:              float     # total PZ line qty (sum of all item types)
    pz_value_usd:        float     # total USD value
    metal_en:            str
    stone_en:            str
    invoice_position_no: int       # INV-NN that drives this PZ line
    # Full breakdown — one entry per item_type within the position.
    # Single-type positions have exactly one entry.
    category_breakdown:  List[CategoryBreakdownItem] = field(default_factory=list)
    all_packing_serials: List[int] = field(default_factory=list)
    all_style_codes:     List[str] = field(default_factory=list)
    match_status:        str       = "EMPTY"


@dataclass
class LineageResult:
    """Complete invoice-to-packing-to-PZ relational mapping for one Global
    Jewellery shipment.

    4-dimensional status model
    --------------------------
    shipment_total_match       FULL / WARNING / PARTIAL / UNMATCHED
    invoice_position_match     FULL / WARNING / PARTIAL / UNMATCHED
    packing_row_assignment_match FULL / WARNING / PARTIAL / UNMATCHED
    pz_line_visibility_match   FULL / WARNING / N/A

    Status semantics:
        FULL     — dimension fully satisfied; no deviations
        WARNING  — dimension satisfied at aggregate level but per-slot
                   deviations exist (OVERFLOW rows, OCR-metal fallback,
                   stone-family ambiguity); operator should review
        PARTIAL  — dimension not satisfied; some rows unmatched or positions
                   empty; escalation required
        UNMATCHED — fatal; cannot compute
        N/A      — not applicable (pz_line_visibility when no pz_rows given)

    match_status (top-level) is the worst single dimension mapped to:
        FULL_MATCH / WARNING_MATCH / PARTIAL_MATCH / UNMATCHED

    Rule: match_status is NEVER FULL_MATCH when any position link is
    PARTIAL or OVERFLOW (i.e. when invoice_position_match != "FULL").
    """
    invoice_no:                   str
    invoice_position_count:       int
    packing_row_count:            int
    pz_line_count:                int

    # Primary output: one link per (invoice_pos, item_type) slot
    position_links:               List[PositionRowLink]  = field(default_factory=list)
    # PZ-level lineage (populated when pz_rows are provided)
    pz_line_lineages:             List[PZLineLineage]    = field(default_factory=list)

    # Reconciliation
    unmatched_packing_serials:    List[int]              = field(default_factory=list)
    unmatched_invoice_positions:  List[int]              = field(default_factory=list)
    duplicate_assignments:        List[int]              = field(default_factory=list)

    # Aggregate totals for cross-check
    total_invoice_qty:            float = 0.0
    total_packing_qty:            float = 0.0
    total_invoice_fob_usd:        float = 0.0
    total_packing_fob_usd:        float = 0.0

    # 4-dimensional status
    shipment_total_match:         str   = "UNMATCHED"
    invoice_position_match:       str   = "UNMATCHED"
    packing_row_assignment_match: str   = "UNMATCHED"
    pz_line_visibility_match:     str   = "N/A"

    # Overall (worst dimension)
    match_status:                 str   = "UNMATCHED"

    notes:                        List[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────


def _empty_result(invoice_no: str, note: str) -> LineageResult:
    return LineageResult(
        invoice_no=invoice_no,
        invoice_position_count=0,
        packing_row_count=0,
        pz_line_count=0,
        match_status="UNMATCHED",
        notes=[note],
    )


def _normalise_type(t: str) -> str:
    """Uppercase + singular-form EARRING normalisation."""
    u = (t or "").upper().strip()
    if u == "EARRINGS":
        return "EARRING"
    return u


def _worst_overall(dims: Dict[str, str]) -> str:
    """Return the overall match_status string for the worst dimension."""
    worst_sev = -1
    worst_dim = "FULL"
    for v in dims.values():
        sev = _DIM_SEVERITY.get(v, 0)
        if sev > worst_sev:
            worst_sev = sev
            worst_dim = v
    return _DIM_TO_OVERALL.get(worst_dim, "UNMATCHED")


def _make_confidence_reason(
    link:         "PositionRowLink",
    link_ambig:   Dict[int, bool],
) -> str:
    """Build the human-readable confidence_reason for a PositionRowLink.

    Returns empty string for a clean FULL / EXACT match with no ambiguity.
    Always returns a non-empty string for PARTIAL, OVERFLOW, or any link
    where stone-family sharing or OCR fallback was involved.
    """
    lid = id(link)
    is_ambiguous = link_ambig.get(lid, False)

    if link.match_status == "EMPTY":
        return "no packing rows assigned to this invoice slot"

    # Clean case: FULL + EXACT + no ambiguity
    if (link.match_status == "FULL"
            and link.match_tier == "EXACT"
            and not is_ambiguous
            and not link.stone_family_shared_positions):
        return ""

    parts: List[str] = []
    delta = link.packing_qty_sum - link.invoice_qty

    if link.match_status == "OVERFLOW":
        parts.append(
            f"packing_qty {link.packing_qty_sum:.0f} exceeds invoice_qty "
            f"{link.invoice_qty:.0f} by {delta:.0f}"
        )
    elif link.match_status == "PARTIAL":
        parts.append(
            f"packing_qty {link.packing_qty_sum:.0f} short of invoice_qty "
            f"{link.invoice_qty:.0f} by {abs(delta):.0f}"
        )

    if link.match_tier in ("OCR_METAL_FALLBACK", "MIXED"):
        parts.append(
            "OCR-metal fallback used — packing metal column differs from invoice"
        )

    if link.stone_family_shared_positions:
        shared = sorted([link.position_no] + link.stone_family_shared_positions)
        if is_ambiguous:
            parts.append(
                f"stone family '{link.stone_en}' shared across positions {shared}; "
                f"row allocation is order-dependent — cannot guarantee "
                f"per-position accuracy"
            )
        else:
            parts.append(
                f"stone family '{link.stone_en}' shared across positions {shared}; "
                f"qty matched but allocation may include rows from adjacent positions"
            )

    return "; ".join(parts) if parts else ""


def _compute_dimensions(
    all_links:          List["PositionRowLink"],
    unmatched_serials:  List[int],
    duplicate_serials:  List[int],
    total_inv_qty:      float,
    total_pack_qty:     float,
    total_inv_fob:      float,
    total_pack_fob:     float,
    pz_lineages:        Optional[List["PZLineLineage"]],
) -> Dict[str, str]:
    """Compute the 4-dimensional status dict."""
    dims: Dict[str, str] = {}

    # ── Shipment total match ──────────────────────────────────────────────
    if not all_links:
        dims["shipment_total"] = "UNMATCHED"
    else:
        qty_ok  = abs(total_pack_qty - total_inv_qty) < 0.5
        fob_ok  = abs(total_pack_fob - total_inv_fob) < 1.0
        if qty_ok and fob_ok:
            dims["shipment_total"] = "FULL"
        elif qty_ok:
            # qty balances but value is off — possible unit-price discrepancy
            dims["shipment_total"] = "WARNING"
        else:
            dims["shipment_total"] = "PARTIAL"

    # ── Invoice position match ────────────────────────────────────────────
    if not all_links:
        dims["invoice_position"] = "UNMATCHED"
    elif all(lk.match_status == "FULL" for lk in all_links):
        dims["invoice_position"] = "FULL"
    elif any(lk.match_status == "EMPTY" for lk in all_links):
        # At least one position slot has zero packing rows
        dims["invoice_position"] = "PARTIAL"
    else:
        # All slots have rows but some are OVERFLOW or PARTIAL
        dims["invoice_position"] = "WARNING"

    # ── Packing row assignment match ──────────────────────────────────────
    if not all_links:
        dims["packing_row"] = "UNMATCHED"
    elif duplicate_serials or unmatched_serials:
        dims["packing_row"] = "PARTIAL"
    elif any(lk.match_status == "OVERFLOW" for lk in all_links):
        # All rows assigned but some positions exceeded their budget
        dims["packing_row"] = "WARNING"
    else:
        dims["packing_row"] = "FULL"

    # ── PZ line visibility match ──────────────────────────────────────────
    if pz_lineages is None:
        dims["pz_visibility"] = "N/A"
    elif all(lin.category_breakdown for lin in pz_lineages):
        dims["pz_visibility"] = "FULL"
    else:
        dims["pz_visibility"] = "WARNING"

    return dims


# ─────────────────────────────────────────────────────────────────────────────
# Main public function
# ─────────────────────────────────────────────────────────────────────────────


def build_global_pz_lineage(
    invoice_positions: List[Dict[str, Any]],
    packing_rows:      List[Dict[str, Any]],
    pz_rows:           Optional[List[Dict[str, Any]]] = None,
    invoice_no:        str = "",
) -> LineageResult:
    """Build the invoice→packing→PZ relational authority for one Global batch.

    Parameters
    ----------
    invoice_positions:
        Output of ``parse_invoice_positions_from_text / _from_pdf``.
        Each dict must have: position_no, unit, metal_en, stone_en, rows
        (where rows is a list of {type, qty, amount}).
    packing_rows:
        Output of ``parse_global_packing_pdf / parse_global_packing_excel``.
        Each dict must have: serial_no, item_type, metal, stone_detail,
        quantity, unit_price (FOB), design_no.
    pz_rows:
        Optional. Contents of pz_rows.json. When provided, the function
        additionally populates ``pz_line_lineages``.
    invoice_no:
        Invoice number string (used in result label only).

    Returns
    -------
    LineageResult — never raises, returns UNMATCHED on fatal error.
    """
    try:
        return _run_matching(invoice_positions, packing_rows, pz_rows, invoice_no)
    except Exception as exc:  # noqa: BLE001
        return _empty_result(
            invoice_no,
            f"FATAL: {type(exc).__name__}: {exc}",
        )


def _run_matching(
    invoice_positions: List[Dict[str, Any]],
    packing_rows:      List[Dict[str, Any]],
    pz_rows:           Optional[List[Dict[str, Any]]],
    invoice_no:        str,
) -> LineageResult:
    notes: List[str] = []

    if not invoice_positions:
        return _empty_result(invoice_no, "invoice_positions is empty")
    if not packing_rows:
        return _empty_result(invoice_no, "packing_rows is empty")

    # ── Step 1: Build budget table from invoice positions ─────────────────
    # Two lookup structures, both ordered by position_no:
    #   exact_index[(unit, metal_en, stone_en, item_type)] = [PositionRowLink, ...]
    #   fallback_index[(unit, stone_en, item_type)] = [PositionRowLink, ...]

    all_links: List[PositionRowLink] = []
    exact_index:    Dict[Tuple, List[PositionRowLink]] = {}
    fallback_index: Dict[Tuple, List[PositionRowLink]] = {}

    for pos in sorted(invoice_positions, key=lambda p: p.get("position_no", 0)):
        pos_no   = pos.get("position_no", 0)
        unit     = (pos.get("unit") or "PCS").upper()
        metal_en = pos.get("metal_en") or ""
        stone_en = pos.get("stone_en") or _STONE_PLAIN

        type_qty:   Dict[str, float] = {}
        type_value: Dict[str, float] = {}
        for row in pos.get("rows", []):
            t   = _normalise_type(row.get("type") or "")
            qty = float(row.get("qty")    or 0)
            val = float(row.get("amount") or 0)
            type_qty[t]   = type_qty.get(t, 0.0) + qty
            type_value[t] = type_value.get(t, 0.0) + val

        for itype, qty in type_qty.items():
            link = PositionRowLink(
                position_no=pos_no,
                invoice_item_type=itype,
                unit=unit,
                metal_en=metal_en,
                stone_en=stone_en,
                invoice_qty=qty,
                invoice_value_usd=type_value.get(itype, 0.0),
            )
            all_links.append(link)

            ekey = (unit, metal_en, stone_en, itype)
            exact_index.setdefault(ekey, []).append(link)

            fkey = (unit, stone_en, itype)
            fallback_index.setdefault(fkey, []).append(link)

    # ── Ambiguous key detection ───────────────────────────────────────────
    # A key is ambiguous when multiple invoice positions share it.
    # Rows assigned to ambiguous keys receive stone_family_shared_positions
    # and a confidence_reason explaining the order-dependence.

    ambiguous_exact: Set[Tuple]    = {
        k for k, v in exact_index.items()
        if len({lk.position_no for lk in v}) > 1
    }
    ambiguous_fallback: Set[Tuple] = {
        k for k, v in fallback_index.items()
        if len({lk.position_no for lk in v}) > 1
    }

    # Pre-populate stone_family_shared_positions on every link
    for link in all_links:
        fkey = (link.unit, link.stone_en, link.invoice_item_type)
        shared = [
            lk.position_no for lk in fallback_index.get(fkey, [])
            if lk.position_no != link.position_no
        ]
        if shared:
            link.stone_family_shared_positions = sorted(set(shared))

    # ── Step 2: Assign packing rows ───────────────────────────────────────
    seen_serials:    Set[int]        = set()
    duplicate_serials: List[int]     = []
    unmatched_serials: List[int]     = []
    link_tier_set:   Dict[int, set]  = {}   # id(link) → {"EXACT" / "OCR_METAL_FALLBACK"}
    link_ambig:      Dict[int, bool] = {}   # id(link) → was ambiguous key used?

    for pr in packing_rows:
        serial = int(pr.get("serial_no") or 0)

        # Enforce exactly-once assignment
        if serial in seen_serials:
            duplicate_serials.append(serial)
            notes.append(
                f"[duplicate] serial {serial} already assigned — skipped"
            )
            continue
        seen_serials.add(serial)

        itype  = _normalise_type(pr.get("item_type") or "")
        metal  = packing_metal_to_en(pr.get("metal") or "")
        stone_d = pr.get("stone_detail") or pr.get("stone_type") or ""
        stone_f = classify_stone_from_detail(stone_d)
        unit    = item_type_unit(itype)
        qty     = float(pr.get("quantity") or 1.0)
        fob     = float(pr.get("unit_price") or pr.get("total_value") or 0.0)
        design  = (pr.get("design_no") or "").strip()

        link, tier = _find_best_link(
            unit, metal, stone_f, itype, exact_index, fallback_index,
        )

        if link is None:
            unmatched_serials.append(serial)
            notes.append(
                f"[unmatched] sr={serial} type={itype} metal={metal} "
                f"stone={stone_f}"
            )
            continue

        link.packing_serials.append(serial)
        link.packing_qty_sum   += qty
        link.packing_value_sum += fob
        if design:
            link.style_codes.append(design)

        lid = id(link)
        link_tier_set.setdefault(lid, set()).add(tier)

        # Mark as ambiguous if the key that resolved this assignment is shared
        ekey = (unit, metal, stone_f, itype)
        fkey = (unit, stone_f, itype)
        if tier == "EXACT" and ekey in ambiguous_exact:
            link_ambig[lid] = True
        elif tier == "OCR_METAL_FALLBACK" and fkey in ambiguous_fallback:
            link_ambig[lid] = True

    # ── Step 3: Per-link match_status and match_tier ──────────────────────
    for link in all_links:
        lid   = id(link)
        tiers = link_tier_set.get(lid, set())

        if not tiers:
            link.match_tier = "UNASSIGNED"
        elif len(tiers) == 1:
            link.match_tier = next(iter(tiers))
        else:
            link.match_tier = "MIXED"

        if not link.packing_serials:
            link.match_status = "EMPTY"
        elif abs(link.packing_qty_sum - link.invoice_qty) < 1e-3:
            link.match_status = "FULL"
        elif link.packing_qty_sum < link.invoice_qty:
            link.match_status = "PARTIAL"
        else:
            link.match_status = "OVERFLOW"

    # ── Step 4: Fill confidence reasons ──────────────────────────────────
    for link in all_links:
        link.confidence_reason = _make_confidence_reason(link, link_ambig)

    # ── Step 5: Identify unmatched invoice positions ──────────────────────
    pos_link_map: Dict[int, List[PositionRowLink]] = {}
    for link in all_links:
        pos_link_map.setdefault(link.position_no, []).append(link)

    unmatched_positions: List[int] = [
        pos_no for pos_no, links in pos_link_map.items()
        if all(lk.match_status == "EMPTY" for lk in links)
    ]

    # ── Step 6: Aggregate totals ──────────────────────────────────────────
    total_inv_qty  = sum(lk.invoice_qty        for lk in all_links)
    total_pack_qty = sum(lk.packing_qty_sum    for lk in all_links)
    total_inv_fob  = sum(lk.invoice_value_usd  for lk in all_links)
    total_pack_fob = sum(lk.packing_value_sum  for lk in all_links)

    # ── Step 7: Build PZ line lineages (if pz_rows provided) ─────────────
    pz_lineages: Optional[List[PZLineLineage]] = None
    if pz_rows:
        pz_lineages = _build_pz_lineages(pz_rows, pos_link_map, invoice_positions)

    # ── Step 8: 4-dimensional status ──────────────────────────────────────
    dims = _compute_dimensions(
        all_links, unmatched_serials, duplicate_serials,
        total_inv_qty, total_pack_qty, total_inv_fob, total_pack_fob,
        pz_lineages,
    )

    overall = _worst_overall(dims)

    return LineageResult(
        invoice_no=invoice_no,
        invoice_position_count=len(invoice_positions),
        packing_row_count=len(packing_rows),
        pz_line_count=len(pz_rows) if pz_rows else 0,
        position_links=all_links,
        pz_line_lineages=pz_lineages if pz_lineages else [],
        unmatched_packing_serials=unmatched_serials,
        unmatched_invoice_positions=unmatched_positions,
        duplicate_assignments=duplicate_serials,
        total_invoice_qty=total_inv_qty,
        total_packing_qty=total_pack_qty,
        total_invoice_fob_usd=total_inv_fob,
        total_packing_fob_usd=total_pack_fob,
        shipment_total_match=dims["shipment_total"],
        invoice_position_match=dims["invoice_position"],
        packing_row_assignment_match=dims["packing_row"],
        pz_line_visibility_match=dims["pz_visibility"],
        match_status=overall,
        notes=notes,
    )


def _find_best_link(
    unit:           str,
    metal_en:       str,
    stone_family:   str,
    item_type:      str,
    exact_index:    Dict[Tuple, List[PositionRowLink]],
    fallback_index: Dict[Tuple, List[PositionRowLink]],
) -> Tuple[Optional[PositionRowLink], str]:
    """Return the best PositionRowLink for a packing row, plus the tier string.

    Tier 1: exact match on (unit, metal_en, stone_family, item_type).
    Tier 2: fallback on (unit, stone_family, item_type) — ignores metal.

    Within each tier, returns the first link with remaining budget.  If all
    budget is exhausted, returns the last candidate to allow overflow (so
    every packing row is assigned).  Returns (None, "NONE") only when no
    link exists at all.
    """
    # Tier 1 — with remaining budget
    for link in exact_index.get((unit, metal_en, stone_family, item_type), []):
        if link.packing_qty_sum < link.invoice_qty:
            return link, "EXACT"

    # Tier 1 — budget exhausted; allow overflow on exact candidate
    candidates_exact = exact_index.get((unit, metal_en, stone_family, item_type), [])
    if candidates_exact:
        return candidates_exact[-1], "EXACT"

    # Tier 2 — with remaining budget
    for link in fallback_index.get((unit, stone_family, item_type), []):
        if link.packing_qty_sum < link.invoice_qty:
            return link, "OCR_METAL_FALLBACK"

    # Tier 2 — budget exhausted; allow overflow on fallback candidate
    candidates_fb = fallback_index.get((unit, stone_family, item_type), [])
    if candidates_fb:
        return candidates_fb[-1], "OCR_METAL_FALLBACK"

    return None, "NONE"


def _build_pz_lineages(
    pz_rows:           List[Dict[str, Any]],
    pos_link_map:      Dict[int, List[PositionRowLink]],
    invoice_positions: List[Dict[str, Any]],
) -> List[PZLineLineage]:
    """Build PZLineLineage objects from the matched link data.

    ``pz_position_no`` (sequential PZ line number, from product_code order) and
    ``invoice_position_no`` (INV-NN numbering) are stored separately.
    """
    inv_pos_lookup: Dict[int, Dict] = {
        p.get("position_no", 0): p for p in invoice_positions
    }

    lineages: List[PZLineLineage] = []
    for seq_no, pz_row in enumerate(pz_rows, start=1):
        pc     = pz_row.get("product_code") or ""
        pos_no = _extract_pz_position(pc)
        qty    = float(pz_row.get("quantity") or 0)
        val    = float(
            pz_row.get("unit_netto_pln") or
            pz_row.get("line_total") or
            pz_row.get("line_total_usd") or 0
        )
        itype  = (pz_row.get("item_type") or "").upper()

        inv_pos  = inv_pos_lookup.get(pos_no, {})
        metal_en = inv_pos.get("metal_en") or ""
        stone_en = inv_pos.get("stone_en") or ""

        links       = pos_link_map.get(pos_no, [])
        all_serials: List[int] = []
        all_styles:  List[str] = []
        breakdown:   List[CategoryBreakdownItem] = []

        for lk in links:
            all_serials.extend(lk.packing_serials)
            all_styles.extend(lk.style_codes)
            breakdown.append(CategoryBreakdownItem(
                item_type=lk.invoice_item_type,
                invoice_qty=lk.invoice_qty,
                packing_qty_sum=lk.packing_qty_sum,
                invoice_value_usd=lk.invoice_value_usd,
                packing_value_sum=lk.packing_value_sum,
                packing_serials=list(lk.packing_serials),
                style_codes=list(lk.style_codes),
            ))

        pz_status = (
            "FULL"    if breakdown and all(
                abs(b.packing_qty_sum - b.invoice_qty) < 1e-3
                for b in breakdown
            )
            else "PARTIAL" if breakdown
            else "EMPTY"
        )

        lineages.append(PZLineLineage(
            pz_product_code=pc,
            pz_position_no=seq_no,          # sequential PZ line number
            canonical_item_type=itype,
            pz_qty=qty,
            pz_value_usd=val,
            metal_en=metal_en,
            stone_en=stone_en,
            invoice_position_no=pos_no,      # INV-NN numbering
            category_breakdown=breakdown,
            all_packing_serials=sorted(set(all_serials)),
            all_style_codes=sorted(set(all_styles)),
            match_status=pz_status,
        ))

    return lineages


def _extract_pz_position(product_code: str) -> int:
    """Extract the 1-based invoice position number from a PZ product code.

    Supported formats (invoice position numbering preserved separately from
    the PZ sequential position):
        "088/2026-2027-1"          → 1   (root engine format)
        "088/2026-2027-INV-01"     → 1   (authority row format)
        "088/2026-2027-POS-3"      → 3   (customs aggregator format)
    """
    m = re.search(r"-INV-0*(\d+)$", product_code)
    if m:
        return int(m.group(1))
    m = re.search(r"-POS-0*(\d+)$", product_code)
    if m:
        return int(m.group(1))
    m = re.search(r"-(\d+)$", product_code)
    if m:
        return int(m.group(1))
    return 0
