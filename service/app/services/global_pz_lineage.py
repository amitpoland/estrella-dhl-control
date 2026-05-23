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
    item-type budget before spilling to the next.

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
    - match_status      : FULL_MATCH / PARTIAL_MATCH / UNMATCHED

Pure function. No DB writes. Never raises. Returns a LineageResult with
match_status=UNMATCHED on any fatal input error.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


__all__ = [
    "build_global_pz_lineage",
    "LineageResult",
    "PositionRowLink",
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
    """
    position_no:         int
    invoice_item_type:   str       # e.g. "BRACELET"
    unit:                str       # PCS / PRS
    metal_en:            str       # "925 Silver", "09KT Gold", …
    stone_en:            str       # "CZ Stud Jewellery", "Lab Grown Diamond…", …
    invoice_qty:         float     # quantity declared in invoice
    invoice_value_usd:   float     # USD value declared in invoice
    packing_serials:     List[int] = field(default_factory=list)
    style_codes:         List[str] = field(default_factory=list)
    packing_qty_sum:     float     = 0.0
    packing_value_sum:   float     = 0.0
    match_status:        str       = "EMPTY"  # FULL / PARTIAL / OVERFLOW / EMPTY


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
    """
    pz_product_code:     str       # e.g. "088/2026-2027-2"
    pz_position_no:      int       # 1-based PZ line sequence
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
    Jewellery shipment."""
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

    # Aggregate totals for cross-check
    total_invoice_qty:            float = 0.0
    total_packing_qty:            float = 0.0
    total_invoice_fob_usd:        float = 0.0
    total_packing_fob_usd:        float = 0.0

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
    # budget_key → (position_no, item_type_norm) → PositionRowLink
    # A single position can contribute N budget entries (one per item type).
    #
    # We build two lookup structures:
    #   exact_index[(unit, metal_en, stone_en, item_type)] = [PositionRowLink, ...]
    #   fallback_index[(unit, stone_en, item_type)] = [PositionRowLink, ...]
    # Both are ordered by position_no so budget-fill is deterministic.

    all_links: List[PositionRowLink] = []

    exact_index:    Dict[Tuple, List[PositionRowLink]] = {}
    fallback_index: Dict[Tuple, List[PositionRowLink]] = {}

    for pos in sorted(invoice_positions, key=lambda p: p.get("position_no", 0)):
        pos_no   = pos.get("position_no", 0)
        unit     = (pos.get("unit") or "PCS").upper()
        metal_en = pos.get("metal_en") or ""
        stone_en = pos.get("stone_en") or _STONE_PLAIN

        # Accumulate per-item-type budgets from position rows
        type_qty:   Dict[str, float] = {}
        type_value: Dict[str, float] = {}
        for row in pos.get("rows", []):
            t     = _normalise_type(row.get("type") or "")
            qty   = float(row.get("qty")    or 0)
            val   = float(row.get("amount") or 0)
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

    # ── Step 2: Classify each packing row ────────────────────────────────
    # Derive (unit, metal_en, stone_family) for each packing row and find
    # the best matching PositionRowLink(s) to assign it to.

    unmatched_serials: List[int] = []

    for pr in packing_rows:
        serial   = int(pr.get("serial_no") or 0)
        itype    = _normalise_type(pr.get("item_type") or "")
        metal    = packing_metal_to_en(pr.get("metal") or "")
        stone_d  = pr.get("stone_detail") or pr.get("stone_type") or ""
        stone_f  = classify_stone_from_detail(stone_d)
        unit     = item_type_unit(itype)
        qty      = float(pr.get("quantity") or 1.0)
        fob      = float(pr.get("unit_price") or pr.get("total_value") or 0.0)
        design   = (pr.get("design_no") or "").strip()

        # Find a link with remaining budget
        link = _find_best_link(
            unit, metal, stone_f, itype,
            exact_index, fallback_index,
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

    # ── Step 3: Compute per-link match_status ─────────────────────────────
    for link in all_links:
        if not link.packing_serials:
            link.match_status = "EMPTY"
        elif abs(link.packing_qty_sum - link.invoice_qty) < 1e-3:
            link.match_status = "FULL"
        elif link.packing_qty_sum < link.invoice_qty:
            link.match_status = "PARTIAL"
        else:
            link.match_status = "OVERFLOW"  # more packing rows than budgeted

    # ── Step 4: Identify unmatched invoice positions ──────────────────────
    unmatched_positions: List[int] = []
    pos_link_map: Dict[int, List[PositionRowLink]] = {}
    for link in all_links:
        pos_link_map.setdefault(link.position_no, []).append(link)

    for pos_no, links in pos_link_map.items():
        if all(lk.match_status == "EMPTY" for lk in links):
            unmatched_positions.append(pos_no)

    # ── Step 5: Aggregate totals ──────────────────────────────────────────
    total_inv_qty   = sum(lk.invoice_qty           for lk in all_links)
    total_pack_qty  = sum(lk.packing_qty_sum        for lk in all_links)
    total_inv_fob   = sum(lk.invoice_value_usd      for lk in all_links)
    total_pack_fob  = sum(lk.packing_value_sum      for lk in all_links)

    # ── Step 6: Build PZ line lineages (if pz_rows provided) ─────────────
    pz_lineages: List[PZLineLineage] = []
    if pz_rows:
        pz_lineages = _build_pz_lineages(pz_rows, pos_link_map, invoice_positions)

    # ── Step 7: Overall match_status ─────────────────────────────────────
    if not unmatched_serials and not unmatched_positions:
        overall = "FULL_MATCH"
    elif all_links and any(lk.match_status != "EMPTY" for lk in all_links):
        overall = "PARTIAL_MATCH"
    else:
        overall = "UNMATCHED"

    return LineageResult(
        invoice_no=invoice_no,
        invoice_position_count=len(invoice_positions),
        packing_row_count=len(packing_rows),
        pz_line_count=len(pz_rows) if pz_rows else 0,
        position_links=all_links,
        pz_line_lineages=pz_lineages,
        unmatched_packing_serials=unmatched_serials,
        unmatched_invoice_positions=unmatched_positions,
        total_invoice_qty=total_inv_qty,
        total_packing_qty=total_pack_qty,
        total_invoice_fob_usd=total_inv_fob,
        total_packing_fob_usd=total_pack_fob,
        match_status=overall,
        notes=notes,
    )


def _find_best_link(
    unit:           str,
    metal_en:       str,
    stone_family:   str,
    item_type:      str,
    exact_index:    Dict[Tuple, List["PositionRowLink"]],
    fallback_index: Dict[Tuple, List["PositionRowLink"]],
) -> Optional["PositionRowLink"]:
    """Return the first PositionRowLink in the index that still has
    remaining budget, preferring exact metal+stone match over fallback.

    "Remaining budget" = invoice_qty > packing_qty_sum.  We allow
    budget overflow (so the link is returned even when overdrawn) to
    ensure every packing row is assigned.  The caller records OVERFLOW
    status on the link during step 3.
    """
    # Tier 1: exact (unit, metal_en, stone_family, item_type)
    for link in exact_index.get((unit, metal_en, stone_family, item_type), []):
        if link.packing_qty_sum < link.invoice_qty:
            return link

    # Tier 1 exhausted — try overflow on exact match before falling back
    candidates_exact = exact_index.get((unit, metal_en, stone_family, item_type), [])
    if candidates_exact:
        return candidates_exact[-1]  # assign to last bucket (overflow)

    # Tier 2: fallback (unit, stone_family, item_type) — ignores metal
    for link in fallback_index.get((unit, stone_family, item_type), []):
        if link.packing_qty_sum < link.invoice_qty:
            return link

    if (unit, stone_family, item_type) in fallback_index:
        return fallback_index[(unit, stone_family, item_type)][-1]

    return None


def _build_pz_lineages(
    pz_rows:       List[Dict[str, Any]],
    pos_link_map:  Dict[int, List[PositionRowLink]],
    invoice_positions: List[Dict[str, Any]],
) -> List[PZLineLineage]:
    """Build PZLineLineage objects from the matched link data.

    The PZ rows use 1-based position sequence that maps directly to
    invoice position_no (INV-01 → PZ position 1, etc.).
    """
    # Build lookup: position_no → invoice position dict
    inv_pos_lookup: Dict[int, Dict] = {
        p.get("position_no", 0): p for p in invoice_positions
    }

    lineages: List[PZLineLineage] = []
    for pz_row in pz_rows:
        pc       = pz_row.get("product_code") or ""
        pos_no   = _extract_pz_position(pc)
        qty      = float(pz_row.get("quantity") or 0)
        val      = float(pz_row.get("unit_netto_pln") or
                         pz_row.get("line_total") or
                         pz_row.get("line_total_usd") or 0)
        itype    = (pz_row.get("item_type") or "").upper()
        desc_en  = pz_row.get("description_en") or ""

        # Derive metal_en and stone_en from invoice position if available
        inv_pos  = inv_pos_lookup.get(pos_no, {})
        metal_en = inv_pos.get("metal_en") or ""
        stone_en = inv_pos.get("stone_en") or ""

        links    = pos_link_map.get(pos_no, [])
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
            "FULL"      if all(b.item_type != "" and abs(b.packing_qty_sum - b.invoice_qty) < 1e-3
                               for b in breakdown) and breakdown
            else "PARTIAL" if breakdown
            else "EMPTY"
        )

        lineages.append(PZLineLineage(
            pz_product_code=pc,
            pz_position_no=pz_rows.index(pz_row) + 1,
            canonical_item_type=itype,
            pz_qty=qty,
            pz_value_usd=val,
            metal_en=metal_en,
            stone_en=stone_en,
            invoice_position_no=pos_no,
            category_breakdown=breakdown,
            all_packing_serials=sorted(set(all_serials)),
            all_style_codes=sorted(set(all_styles)),
            match_status=pz_status,
        ))

    return lineages


def _extract_pz_position(product_code: str) -> int:
    """Extract the 1-based invoice position number from a PZ product code.

    Supported formats:
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
    # Root engine format: everything after the last "-" is the position
    m = re.search(r"-(\d+)$", product_code)
    if m:
        return int(m.group(1))
    return 0
