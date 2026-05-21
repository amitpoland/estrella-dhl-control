"""
customs_position_aggregator.py — Aggregate packing-row customs lines
into invoice-position customs lines.

OPERATOR SPEC (post Phase-1 / Phase-2)
---------------------------------------

The Polish Description PDF was generating 245 descriptions across 42
pages because the customs description engine rendered one line per
packing row. The output was correct but operationally unsuitable for
DHL customs officers — they need ONE consolidated description per
invoice position, not per piece.

Authority split:

  Packing Description Report     → packing_lines (245 rows, 42 pages)
                                    Warehouse / audit / reconciliation
  Customs Description Report     → aggregated invoice positions
                                    (~8-10 positions, 2-5 pages)
                                    DHL customs / SAD / ZC429

This module owns the **aggregation function**. The packing row source
chain (PR #259 packing-first authority) is unchanged. The aggregation
runs AFTER row injection and BEFORE customs description rendering.

AGGREGATION KEY
---------------

Rows are grouped by ``(uom, metal_canonical, stone_phrase_pl)`` — the
three fields that determine the customs-grade product description.
Item type (Ring/Pendant/Bracelet/...) is concatenated into the
position label but NOT used as a separate position dimension —
matching the supplier's own invoice categorisation where multiple
jewellery types appear under one "PCS, <metal>, <stones>" header.

For each position:

  product_code:        ``<invoice_no>-POS-<seq>``
  quantity:            sum of source row quantities
  line_total:          sum of source row line_totals
  unit_price:          line_total / quantity
  polish_customs_description / description_en:
                       carries the metal + stone phrase + concatenated
                       item types (e.g. ``Pierścionki, Wisiorki,
                       Bransoletki ze srebra próby 925 wysadzany
                       cyrkoniami``)
  item_type:           pluralised English item-type list
  source_row_count:    metadata for traceability
  source_packing_codes: list of underlying packing product codes

SAFETY
------

Pure / deterministic. Never raises. Never modifies inputs (returns a
new list). Does NOT compute CIF / freight / insurance / duty / VAT.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# PL plural forms for item types (for the concatenated position label)
# ─────────────────────────────────────────────────────────────────────────────

_PL_PLURAL: Dict[str, str] = {
    "RING":      "Pierścionki",
    "PENDANT":   "Wisiorki",
    "EARRINGS":  "Kolczyki",
    "EARRING":   "Kolczyki",
    "BRACELET":  "Bransoletki",
    "BANGLE":    "Bransoletki sztywne",
    "NECKLACE":  "Naszyjniki",
    "CHAIN":     "Łańcuszki",
    "CUFFLINKS": "Spinki do mankietów",
    "CUFFLINK":  "Spinki do mankietów",
}

_EN_PLURAL: Dict[str, str] = {
    "RING":      "RINGS",
    "PENDANT":   "PENDANTS",
    "EARRINGS":  "EARRINGS",
    "EARRING":   "EARRINGS",
    "BRACELET":  "BRACELETS",
    "BANGLE":    "BANGLES",
    "NECKLACE":  "NECKLACES",
    "CHAIN":     "CHAINS",
    "CUFFLINKS": "CUFFLINKS",
    "CUFFLINK":  "CUFFLINKS",
}


def _pl_plural(item_type_upper: str) -> str:
    """Polish plural for an item-type key. Falls back to the key
    unchanged when no mapping exists."""
    return _PL_PLURAL.get(item_type_upper, item_type_upper.capitalize())


def _en_plural(item_type_upper: str) -> str:
    return _EN_PLURAL.get(item_type_upper, item_type_upper)


# ─────────────────────────────────────────────────────────────────────────────
# Stone-phrase extraction (PL / EN sides) from a per-row description
# ─────────────────────────────────────────────────────────────────────────────


# These match the operator-locked vocabulary used by
# routes_dhl_clearance._global_render_pl_en. We extract the stone
# phrase from existing per-row PL/EN text so this aggregator stays
# decoupled from the renderer module.
_PL_STONE_PATTERNS: Tuple[str, ...] = (
    "wysadzany cyrkoniami i kamieniami kolorowymi",
    "wysadzany diamentami i cyrkoniami",
    "z diamentami laboratoryjnymi",
    "wysadzany kamieniami kolorowymi",
    "wysadzany cyrkoniami",
    "z diamentami",
)

_EN_STONE_PATTERNS: Tuple[str, ...] = (
    "CZ & Colour Stone Jewellery",
    "Diamond & CZ Stud Jewellery",
    "Lab Grown Diamond Jewellery",
    "Colour Stone Jewellery",
    "CZ Stud Jewellery",
    "Diamond Jewellery",
    "Plain Jewellery",
)


def _extract_pl_stone(desc_pl: str) -> str:
    """Return the trailing stone phrase from a PL row description, or
    empty string when none matched (= plain jewellery)."""
    if not desc_pl:
        return ""
    for p in _PL_STONE_PATTERNS:
        if p in desc_pl:
            return p
    return ""


def _extract_en_stone(desc_en: str) -> str:
    if not desc_en:
        return "Plain Jewellery"
    for p in _EN_STONE_PATTERNS:
        if p in desc_en:
            return p
    return "Plain Jewellery"


_PL_METAL_PATTERNS: Tuple[str, ...] = (
    "ze srebra próby 925",
    "ze złota próby 375",
    "ze złota próby 585",
    "ze złota próby 750",
    "ze złota próby 916",
    "z platyny próby 950",
    "z platyny próby 900",
)


def _extract_pl_metal(desc_pl: str) -> str:
    if not desc_pl:
        return ""
    for p in _PL_METAL_PATTERNS:
        if p in desc_pl:
            return p
    return ""


_EN_METAL_PATTERNS: Tuple[str, ...] = (
    "925 Silver", "09KT Gold", "14KT Gold", "18KT Gold", "22KT Gold",
    "PT950 Platinum", "PT900 Platinum",
)


def _extract_en_metal(desc_en: str) -> str:
    if not desc_en:
        return ""
    for p in _EN_METAL_PATTERNS:
        if p in desc_en:
            return p
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def aggregate_packing_rows_to_invoice_positions(
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Group per-row customs lines by ``(uom, metal_canonical,
    stone_phrase_pl)`` and emit one aggregated row per group.

    Inputs are the per-line dicts produced by
    ``routes_dhl_clearance._inject_rows_from_packing_lines``:

        {
          "invoice_number":             "088/2026-2027",
          "line_position":              1,
          "product_code":               "088/2026-2027-1",
          "description":                "09KT Gold LGD ... BRACELET",
          "polish_customs_description": "Bransoletka ze złota próby 375 ...",
          "description_en":             "09KT Gold Lab Grown Diamond Jewellery BRACELET",
          "item_type":                  "BRACELET",
          "item_type_pl":               "Bransoletka",
          "quantity":                   1.0,
          "line_total":                 232.00,
          "uom":                        "PCS",
          ...
        }

    Output: one dict per invoice position with the same shape PLUS:

        "source_row_count":    int   — how many packing rows folded in
        "source_packing_codes": list — the underlying product_codes
        "_position_seq":       int   — 1-based sequence within batch

    Pure function. Returns a new list. Never raises.

    When the input is empty or any row lacks the keys needed to derive
    a position key, returns the input unchanged (caller falls back to
    per-row authority).
    """
    if not rows:
        return list(rows)

    # Detect whether all rows have the renderer's output fields. If
    # not, we can't safely aggregate (caller's per-row authority is
    # preserved).
    sample = rows[0]
    if not all(k in sample for k in ("uom", "polish_customs_description",
                                     "description_en", "item_type",
                                     "line_total", "quantity")):
        return list(rows)

    groups: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    order:  List[Tuple[str, str, str]] = []

    for r in rows:
        uom    = str(r.get("uom") or "PCS").upper()
        pl     = str(r.get("polish_customs_description") or "")
        en     = str(r.get("description_en") or "")
        metal_pl = _extract_pl_metal(pl)
        metal_en = _extract_en_metal(en)
        stone_pl = _extract_pl_stone(pl)
        stone_en = _extract_en_stone(en)

        key = (uom, metal_pl, stone_pl)
        if key not in groups:
            order.append(key)
            groups[key] = {
                "_uom":           uom,
                "_metal_pl":      metal_pl,
                "_metal_en":      metal_en,
                "_stone_pl":      stone_pl,
                "_stone_en":      stone_en,
                "_item_types":    [],       # preserves insertion order
                "_item_types_set": set(),
                "invoice_no":     str(r.get("invoice_number") or
                                       r.get("invoice_no") or ""),
                "quantity_sum":   0.0,
                "line_total_sum": 0.0,
                "source_rows":    [],
                "currency":       str(r.get("currency") or "USD"),
            }

        g = groups[key]
        item_type = str(r.get("item_type") or "").upper()
        if item_type and item_type not in g["_item_types_set"]:
            g["_item_types"].append(item_type)
            g["_item_types_set"].add(item_type)
        try:
            g["quantity_sum"]   += float(r.get("quantity")   or 0)
            g["line_total_sum"] += float(r.get("line_total") or 0)
        except (TypeError, ValueError):
            pass
        g["source_rows"].append(str(r.get("product_code") or ""))

    out: List[Dict[str, Any]] = []
    for seq, key in enumerate(order, start=1):
        g = groups[key]
        item_types = g["_item_types"]
        # Build the position label: concatenate plural item types in
        # the order they appear, followed by metal + stone phrases.
        pl_items = [_pl_plural(t) for t in item_types] if item_types else []
        en_items = [_en_plural(t) for t in item_types] if item_types else []

        # PL: "Pierścionki, Wisiorki, Bransoletki ze srebra próby 925
        #      wysadzany cyrkoniami"
        pl_desc_parts: List[str] = []
        if pl_items:
            pl_desc_parts.append(", ".join(pl_items))
        if g["_metal_pl"]:
            pl_desc_parts.append(g["_metal_pl"])
        if g["_stone_pl"]:
            pl_desc_parts.append(g["_stone_pl"])
        pl_desc = " ".join(pl_desc_parts).strip()

        # EN: "925 Silver CZ Stud Jewellery RINGS, PENDANTS, BRACELETS"
        en_parts: List[str] = []
        if g["_metal_en"]:
            en_parts.append(g["_metal_en"])
        if g["_stone_en"]:
            en_parts.append(g["_stone_en"])
        if en_items:
            en_parts.append(", ".join(en_items))
        en_desc = " ".join(en_parts).strip()

        invoice_no   = g["invoice_no"] or "INVOICE"
        product_code = f"{invoice_no}-POS-{seq}"

        qty       = float(g["quantity_sum"])
        line_tot  = round(float(g["line_total_sum"]), 2)
        unit_p    = round(line_tot / qty, 6) if qty > 0 else 0.0

        # Use the first item_type as the canonical EN type for customs
        # description engine grouping (operator spec: ONE customs row per
        # position; the engine groups by item_type so a unique
        # per-position synthetic type keeps each position as its own row).
        item_type_synth = (item_types[0] if item_types else "UNCATEGORISED").upper()

        out.append({
            "invoice_number":             invoice_no,
            "line_position":              seq,
            "product_code":               product_code,
            "description":                en_desc,
            "polish_customs_description": pl_desc,
            "description_en":             en_desc,
            "description_pl":             pl_desc,
            "item_type":                  item_type_synth,
            "item_type_pl":               (pl_items[0] if pl_items
                                            else "Wyrób biżuteryjny"),
            "material":                   "",
            "quantity":                   qty,
            "unit_price":                 unit_p,
            "line_total":                 line_tot,
            "line_total_usd":             line_tot,
            "hsn_code":                   "",
            "currency":                   g["currency"],
            "uom":                        g["_uom"],
            "source_row_count":           len(g["source_rows"]),
            "source_packing_codes":       list(g["source_rows"]),
            "_position_seq":              seq,
            "_supplier_profile":          "global_jewellery",
            "_rows_source":               "packing_lines_aggregated_to_invoice_positions",
        })

    return out


def position_count(rows: List[Dict[str, Any]]) -> int:
    """Convenience: how many distinct invoice positions would result
    from aggregating these rows. Used by tests and observability."""
    return len(aggregate_packing_rows_to_invoice_positions(rows))
