"""
sales_packing_parser.py — Parse EJL tab-separated sales packing lists.

Column layout (EJL/26-27/244 and compatible formats):
    Sr | Ctg | Design | Design Description | Kt | Col | Quality | Qty
    | Value (EUR) | Total Value (EUR)

"Value (EUR)"       → unit EUR sales price
"Total Value (EUR)" → line net EUR (qty × unit_price)

The parser is tolerant of minor header variations: parenthesised suffixes
like "(EUR)" are stripped, and whitespace/dash variants are normalised to
underscores before matching.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple


# ── Description vocabulary ────────────────────────────────────────────────────

_CATEGORY_PL: Dict[str, str] = {
    "PND": "wisiorek",
    "RNG": "pierścionek",
    "EAR": "kolczyki",
    "BRC": "bransoletka",
    "BAN": "bransoletka",
    "NEC": "naszyjnik",
    "BRO": "broszka",
    "SET": "zestaw biżuterii",
    "CHR": "zawieszka",
    "CUF": "spinki do mankietów",
}
_CATEGORY_EN: Dict[str, str] = {
    "PND": "pendant",
    "RNG": "ring",
    "EAR": "earrings",
    "BRC": "bracelet",
    "BAN": "bracelet",
    "NEC": "necklace",
    "BRO": "brooch",
    "SET": "jewellery set",
    "CHR": "charm",
    "CUF": "cufflinks",
}

_KARAT_PL: Dict[str, str] = {
    "14KT": "14-karatowego",
    "18KT": "18-karatowego",
    "10KT": "10-karatowego",
    "9KT":  "9-karatowego",
    "22KT": "22-karatowego",
    "24KT": "24-karatowego",
    "PT":   "platynowego",
    "SS":   "srebrnego",
    "925":  "srebrnego",
}
_KARAT_EN: Dict[str, str] = {
    "14KT": "14kt",
    "18KT": "18kt",
    "10KT": "10kt",
    "9KT":  "9kt",
    "22KT": "22kt",
    "24KT": "24kt",
    "PT":   "platinum",
    "SS":   "silver",
    "925":  "silver",
}

_COLOR_PL: Dict[str, str] = {
    "W":  "białego",
    "Y":  "żółtego",
    "R":  "różowego",
    "WY": "białego i żółtego",
    "WR": "białego i różowego",
    "YR": "żółtego i różowego",
    "TT": "dwukolorowego",
}
_COLOR_EN: Dict[str, str] = {
    "W":  "white",
    "Y":  "yellow",
    "R":  "rose",
    "WY": "white and yellow",
    "WR": "white and rose",
    "YR": "yellow and rose",
    "TT": "two-tone",
}


def _stones_from_quality(quality: str) -> Tuple[str, str]:
    """Return (pl_stones, en_stones) label from a quality string like GH-SI1 or GH-SI1/RUBY."""
    q = (quality or "").strip().upper()
    parts = re.split(r"[/,+]", q)
    pl_parts, en_parts = [], []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if re.match(r"^[A-Z]{1,4}-[A-Z0-9]+", p):
            pl_parts.append("diamentami")
            en_parts.append("diamonds")
        elif "RUBY" in p:
            pl_parts.append("rubinami")
            en_parts.append("rubies")
        elif "EMERALD" in p or "EMLD" in p:
            pl_parts.append("szmaragdami")
            en_parts.append("emeralds")
        elif "SAPPH" in p or "SAPH" in p:
            pl_parts.append("szafirami")
            en_parts.append("sapphires")
        elif "PEARL" in p:
            pl_parts.append("perłami")
            en_parts.append("pearls")
        else:
            pl_parts.append("kamieniami")
            en_parts.append("stones")
    if not pl_parts:
        return "kamieniami", "stones"
    pl = " i ".join(dict.fromkeys(pl_parts))
    en = " and ".join(dict.fromkeys(en_parts))
    return pl, en


def generate_description(ctg: str, kt: str, col: str, quality: str) -> Tuple[str, str]:
    """Return (pl_desc, en_desc) commercial description strings."""
    cat_pl = _CATEGORY_PL.get((ctg or "").upper().strip(), "wyrób")
    cat_en = _CATEGORY_EN.get((ctg or "").upper().strip(), "item")
    kar_pl = _KARAT_PL.get((kt or "").upper().strip(), "")
    kar_en = _KARAT_EN.get((kt or "").upper().strip(), "")
    col_pl = _COLOR_PL.get((col or "").upper().strip(), "")
    col_en = _COLOR_EN.get((col or "").upper().strip(), "")
    stones_pl, stones_en = _stones_from_quality(quality)

    if kar_pl:
        if col_pl:
            pl = f"{cat_pl} z {kar_pl} {col_pl} złota z {stones_pl}"
            en = f"{kar_en} {col_en} gold {cat_en} with {stones_en}"
        else:
            pl = f"{cat_pl} z {kar_pl} złota z {stones_pl}"
            en = f"{kar_en} gold {cat_en} with {stones_en}"
    else:
        pl = f"{cat_pl} z {stones_pl}"
        en = f"{cat_en} with {stones_en}"
    return pl, en


# ── Header normalisation ──────────────────────────────────────────────────────

def _normalise_header(raw: str) -> str:
    """Strip parenthesised suffixes, lowercase, compress whitespace/dashes → underscore."""
    s = re.sub(r"\s*\([^)]*\)", "", raw)
    s = s.lower().strip()
    s = re.sub(r"[\s\-]+", "_", s)
    return s


# ── Row dataclass ─────────────────────────────────────────────────────────────

@dataclass
class SalesPackingRow:
    sr:           int
    ctg:          str
    product_code: str
    kt:           str
    col:          str
    quality:      str
    qty:          int
    unit_price:   Decimal
    line_total:   Decimal
    desc_pl:      str
    desc_en:      str


def _parse_eur(s: str) -> Optional[Decimal]:
    """Parse a EUR amount cell, returning None if blank or non-numeric."""
    s = (s or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_ejl_sales_packing(
    text: str,
) -> Tuple[List[SalesPackingRow], Optional[Decimal]]:
    """Parse EJL tab-separated sales packing text.

    Returns (rows, grand_total_eur).  grand_total_eur is None when no
    "Grand Total" row is found.  Rows with a non-integer Sr (subtotals,
    category headers) are skipped.
    """
    rows: List[SalesPackingRow] = []
    grand_total: Optional[Decimal] = None

    lines = text.splitlines()
    headers: Optional[List[str]] = None
    col_idx: Dict[str, int] = {}

    for line in lines:
        if not line.strip():
            continue
        cells = line.split("\t")

        # ── Find header row ───────────────────────────────────────────────
        if headers is None:
            norm = [_normalise_header(c) for c in cells]
            if "sr" in norm and "design" in norm:
                headers = norm
                col_idx = {h: i for i, h in enumerate(headers)}
            continue

        # ── Grand Total sentinel ──────────────────────────────────────────
        first = cells[0].strip().lower()
        if first == "grand total":
            last_val = cells[-1].strip().replace(",", "")
            try:
                grand_total = Decimal(last_val)
            except InvalidOperation:
                pass
            continue

        # ── Data rows ─────────────────────────────────────────────────────
        def _get(key: str, default: str = "") -> str:
            idx = col_idx.get(key)
            if idx is None:
                return default
            return cells[idx].strip() if idx < len(cells) else default

        sr_raw = _get("sr")
        if not sr_raw.isdigit():
            continue

        sr  = int(sr_raw)
        ctg = _get("ctg")
        design = _get("design")
        kt  = _get("kt")
        col = _get("col")
        quality = _get("quality")

        qty_raw = _get("qty")
        try:
            qty = int(qty_raw)
        except (ValueError, TypeError):
            continue

        unit_price = _parse_eur(_get("value"))
        line_total = _parse_eur(_get("total_value"))

        if unit_price is None or line_total is None:
            continue

        desc_pl, desc_en = generate_description(ctg, kt, col, quality)

        rows.append(SalesPackingRow(
            sr=sr,
            ctg=ctg,
            product_code=design,
            kt=kt,
            col=col,
            quality=quality,
            qty=qty,
            unit_price=unit_price,
            line_total=line_total,
            desc_pl=desc_pl,
            desc_en=desc_en,
        ))

    return rows, grand_total


# ── Validation ────────────────────────────────────────────────────────────────

def validate_grand_total(
    rows: List[SalesPackingRow],
    grand_total: Optional[Decimal],
    tolerance: Decimal = Decimal("0.02"),
) -> Optional[str]:
    """Return an error string if the row sum doesn't match grand_total, else None."""
    if grand_total is None:
        return None
    computed = sum(r.line_total for r in rows)
    diff = abs(computed - grand_total)
    if diff > tolerance:
        return (
            f"Row sum {computed} differs from Grand Total {grand_total} "
            f"by {diff} (tolerance {tolerance})"
        )
    return None


# ── Patch lookup ──────────────────────────────────────────────────────────────

def build_patch_lookup(
    rows: List[SalesPackingRow],
) -> Dict[str, SalesPackingRow]:
    """Return {product_code: SalesPackingRow}, first-occurrence wins."""
    out: Dict[str, SalesPackingRow] = {}
    for row in rows:
        if row.product_code and row.product_code not in out:
            out[row.product_code] = row
    return out
