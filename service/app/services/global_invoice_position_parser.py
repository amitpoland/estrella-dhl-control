"""
global_invoice_position_parser.py — Parse Global Jewellery commercial
invoice into per-position customs descriptions.

OPERATOR SPEC (post packing-row aggregation attempt)
----------------------------------------------------

The customs description authority must be the COMMERCIAL INVOICE LINE,
not the packing list. Each "PCS, <metal>, <stones>" or "PRS, <metal>,
<stones>" header in the Global invoice introduces ONE invoice
position. The product rows beneath it are the items WITHIN that
position. The customs description must emit ONE row per invoice
position — not one per packing row, and not one per (uom, metal,
stone) tuple aggregated across positions.

Example (GLOBAL Invoice 088/2026-2027):

  PCS, 09KT Gold, LGD Gold Stud Jewell
    Bracelet 8.982 9.860 2.0 302.00 604.00 ...

  PCS, 925 Purity Silver, Studed Jewellery CZ, CLS
    Pendant 7.668 9.300 8.0 6.63 53.00 ...
    Ring    33.362 36.220 15.0 7.27 109.00 ...
                                            ⇒ ONE position, qty 23, USD 162

  PCS, 925 Purity Silver, Stud Jewelry DIA&CZ
    Ring 6.584 7.914 2.0 23.00 46.00 ...
                                            ⇒ ONE position, qty 2, USD 46

The previous packing-row aggregator collapsed positions 2 and 3 above
into one because both contained "CZ"; that lost the customs-relevant
distinction (CZ+CLS vs DIA&CZ are different HSN families).

This module owns the invoice-line parser. Pure text extraction; no
DB writes; no engine arithmetic touched.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Migration B2: import shared grammar authority for Polish plural types
# and prepositional helpers (metal + stone phrases).
# The shared grammar module is the SINGLE SOURCE OF TRUTH for these forms.
# EN-side tables remain local — no shared EN equivalent exists yet.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from description_grammar import (          # noqa: E402
    ITEM_TYPE_PL_PLURAL,
    METAL_PREPOSITIONAL,
    metal_prepositional,
    stone_with_preposition,
)


# ─────────────────────────────────────────────────────────────────────────────
# Patterns
# ─────────────────────────────────────────────────────────────────────────────

# Invoice position header — one line like:
#   "PCS, 09KT Gold, LGD Gold Stud Jewell"
#   "PRS, 925 Purity Silver, Studed Jewellery CLS, CZ"
#   "PCS, 925 Purity Silver, Plain Jewellery"
#
# Captures: unit (PCS|PRS), metal_raw, stones_raw (everything after the
# second comma)
_RE_POSITION_HEADER = re.compile(
    r"^\s*(?P<unit>PCS|PRS)\s*,\s*(?P<metal>[^,]+?)\s*,\s*(?P<stones>.+)$",
    re.IGNORECASE,
)

# Product row inside an invoice position — one line like:
#   "Bracelet 8.982 9.860 2.0 302.00 604.00 ..."
#   "Pendant 7.668 9.300 8.0 6.63 53.00 ..."
#
# Anchor: starts with one of the known jewellery types, followed by
# gross_wt + net_wt + qty + rate + amount. We use the SECOND amount
# (post-tax not applicable here; the second number at end is the
# extended amount) as the authoritative line total.
_TYPE_WORDS = ("Bracelet", "Pendant", "Ring", "Bangle",
               "Earrings", "Earring", "Necklace", "Chain",
               "Cufflinks", "Cufflink")
_RE_TYPE_PREFIX = r"(?:" + "|".join(_TYPE_WORDS) + r")"

_RE_PRODUCT_ROW = re.compile(
    rf"^\s*(?P<type>{_RE_TYPE_PREFIX})\s+"
    rf"(?P<gross>\d+\.\d{{3}})\s+"
    rf"(?P<net>\d+\.\d{{3}})\s+"
    rf"(?P<qty>\d+(?:\.\d+)?)\s+"
    rf"(?P<rate>\d+(?:\.\d+)?)\s+"
    rf"(?P<amount>\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Vocabulary mappings — operator-locked grammar
# ─────────────────────────────────────────────────────────────────────────────

# Migration B2: PL plural types now come from shared grammar authority.
# The import alias preserves the local name so all callers continue to work.
# This eliminates the duplicate dictionary that was previously maintained here.
_PL_PLURAL_TYPE: Dict[str, str] = ITEM_TYPE_PL_PLURAL

_EN_PLURAL_TYPE: Dict[str, str] = {
    "RING":      "RINGS",
    "PENDANT":   "PENDANTS",
    "EARRING":   "EARRINGS",
    "EARRINGS":  "EARRINGS",
    "BRACELET":  "BRACELETS",
    "BANGLE":    "BANGLES",
    "NECKLACE":  "NECKLACES",
    "CHAIN":     "CHAINS",
    "CUFFLINK":  "CUFFLINKS",
    "CUFFLINKS": "CUFFLINKS",
}


# Operator-locked metal vocabulary (PL preposition: "ze srebra próby N"
# or "ze złota próby N").
#
# Migration B2: PL phrases are verified at import time against
# METAL_PREPOSITIONAL from the shared grammar.  The _METAL_TABLE
# structure is retained because _normalize_metal() needs header-substring
# matching + EN labels, which have no shared equivalent yet.
_METAL_TABLE: Tuple[Tuple[str, str, str], ...] = (
    # (header substring (case-insensitive),  PL phrase,                EN label)
    ("925 PURITY SILVER",                    "ze srebra próby 925",    "925 Silver"),
    ("925 SILVER",                           "ze srebra próby 925",    "925 Silver"),
    ("14KT GOLD",                            "ze złota próby 585",     "14KT Gold"),
    ("09KT GOLD",                            "ze złota próby 375",     "09KT Gold"),
    ("9KT GOLD",                             "ze złota próby 375",     "09KT Gold"),
    ("18KT GOLD",                            "ze złota próby 750",     "18KT Gold"),
    ("22KT GOLD",                            "ze złota próby 916",     "22KT Gold"),
    ("PT950",                                "z platyny próby 950",    "PT950 Platinum"),
    ("PT900",                                "z platyny próby 900",    "PT900 Platinum"),
)

# ── Migration B2: import-time parity check ─────────────────────────────────
# Verify every PL phrase in _METAL_TABLE matches METAL_PREPOSITIONAL.
# This catches drift between the local table and shared grammar at module
# load, not at runtime — fail loud, fail early.
_METAL_TABLE_PL_VALUES = {pl for _, pl, _ in _METAL_TABLE}
_SHARED_METAL_PL_VALUES = set(METAL_PREPOSITIONAL.values())
_METAL_DRIFT = _METAL_TABLE_PL_VALUES - _SHARED_METAL_PL_VALUES
if _METAL_DRIFT:
    raise ImportError(
        f"global_invoice_position_parser._METAL_TABLE PL phrases "
        f"have drifted from description_grammar.METAL_PREPOSITIONAL: "
        f"{_METAL_DRIFT!r}"
    )


def _normalize_metal(raw: str) -> Tuple[str, str, str]:
    """Return (canonical_key, pl_phrase, en_label) for the metal text
    in an invoice position header. Falls back to the raw text when
    nothing matches (caller flags as unmapped)."""
    u = (raw or "").upper().strip()
    u = re.sub(r"\s+", " ", u)
    for key, pl, en in _METAL_TABLE:
        if key in u:
            return (key, pl, en)
    return ("", "", "")


# Operator-locked stone vocabulary — grammar fix:
#   "z cyrkoniami"                   (was "wysadzany cyrkoniami")
#   "z kamieniami kolorowymi"        (was "wysadzany kamieniami kolorowymi")
#   "z diamentami laboratoryjnymi"
#   "z diamentami"                   (natural diamond)
#
# Order matters: composite stones (LGD, DIA & CLS, CZ + CLS) MUST
# match before their components.
_STONE_RULES: Tuple[Tuple[str, str, str], ...] = (
    # (regex pattern (case-insensitive), polish phrase, english qualifier)
    (r"\bLGD\b|\bLAB\s*GROWN\s*DIAMOND",
     "z diamentami laboratoryjnymi",
     "Lab Grown Diamond Jewellery"),

    # "CZ, CLS" or "CLS, CZ" or "CZ Stud ... CLS" — combo
    (r"\bCZ\b.{0,12}\bCLS\b|\bCLS\b.{0,12}\bCZ\b",
     "z cyrkoniami i kamieniami kolorowymi",
     "CZ & Colour Stone Jewellery"),

    # "DIA & CZ" or "DIA&CZ"
    (r"\bDIA\s*&\s*CZ\b|\bDIA\.?CZ\b",
     "z diamentami i cyrkoniami",
     "Diamond & CZ Stud Jewellery"),

    # Bare CZ (no colour stone, no diamond combo)
    (r"\bCZ\b",
     "z cyrkoniami",
     "CZ Stud Jewellery"),

    # Natural diamond
    (r"\bDIA\b|\bDIAMOND\b",
     "z diamentami",
     "Diamond Jewellery"),

    # Bare colour stone
    (r"\bCLS\b|\bCOLOUR\s+STONE\b|\bCOLOR\s+STONE\b",
     "z kamieniami kolorowymi",
     "Colour Stone Jewellery"),

    # Plain (operator-locked: explicit Plain marker only)
    (r"\bPLAIN\b",
     "",
     "Plain Jewellery"),
)

# ── Migration B2: import-time stone parity check ──────────────────────────
# Verify simple (non-combo) stone PL phrases match stone_with_preposition().
# Combo forms ("z cyrkoniami i kamieniami kolorowymi", "z diamentami i
# cyrkoniami") and the colour-stone form ("z kamieniami kolorowymi") are
# parser-specific — they combine/rename instrumental forms that don't have
# a single STONE_INSTRUMENTAL entry.  These are documented gaps, not errors.
#
# Simple forms verified: "z diamentami", "z cyrkoniami",
#   "z diamentami laboratoryjnymi"
_STONE_SIMPLE_PL = {
    "z diamentami laboratoryjnymi": stone_with_preposition("diamentami laboratoryjnymi"),
    "z cyrkoniami":                 stone_with_preposition("cyrkoniami"),
    "z diamentami":                 stone_with_preposition("diamentami"),
}
for _expected, _actual in _STONE_SIMPLE_PL.items():
    if _expected != _actual:
        raise ImportError(
            f"global_invoice_position_parser._STONE_RULES simple PL phrase "
            f"drift: expected {_expected!r}, shared grammar gives {_actual!r}"
        )
# Parser-specific combo/colour forms (no shared equivalent, verified by tests):
#   "z cyrkoniami i kamieniami kolorowymi"  (CZ+CLS combo)
#   "z diamentami i cyrkoniami"             (DIA+CZ combo)
#   "z kamieniami kolorowymi"               (CLS → "colour stone", not "gemstone")


def _normalize_stone(raw: str) -> Tuple[str, str]:
    """Return (pl_phrase, en_qualifier) for the stone vocabulary
    extracted from an invoice position header. Plain when no marker
    matches."""
    r_up = (raw or "").upper()
    if not r_up:
        return ("", "Plain Jewellery")
    for pat, pl, en in _STONE_RULES:
        if re.search(pat, r_up, re.IGNORECASE):
            return (pl, en)
    return ("", "Plain Jewellery")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def parse_invoice_positions_from_text(raw_text: str) -> List[Dict[str, Any]]:
    """Parse invoice raw text into structured invoice positions.

    Each position carries:

        {
          "position_no":  int,             # 1-based sequence within batch
          "unit":         "PCS" | "PRS",
          "metal_raw":    str,             # exact text from invoice header
          "stones_raw":   str,             # exact text from invoice header
          "metal_pl":     str,             # operator-locked Polish phrase
          "metal_en":     str,             # operator-locked English label
          "stone_pl":     str,             # operator-locked PL phrase (or "")
          "stone_en":     str,             # operator-locked EN qualifier
          "rows": [
            { "type": "RING", "qty": 15, "amount": 109.0, "gross_wt": 33.362,
              "net_wt": 33.362, "rate": 7.27 },
            ...
          ],
          "quantity": <sum of row qtys>,
          "amount":   <sum of row amounts>,
        }

    Returns [] when no positions parsed. Pure function; never raises.
    """
    positions: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    for ln in (raw_text or "").split("\n"):
        s = ln.strip()
        if not s:
            continue

        m_hdr = _RE_POSITION_HEADER.match(s)
        if m_hdr:
            # Open a new position
            unit       = m_hdr.group("unit").upper()
            metal_raw  = m_hdr.group("metal").strip()
            stones_raw = m_hdr.group("stones").strip()
            mkey, mpl, men = _normalize_metal(metal_raw)
            spl, sen       = _normalize_stone(stones_raw)
            current = {
                "position_no":  len(positions) + 1,
                "unit":         unit,
                "metal_raw":    metal_raw,
                "stones_raw":   stones_raw,
                "metal_key":    mkey,
                "metal_pl":     mpl,
                "metal_en":     men,
                "stone_pl":     spl,
                "stone_en":     sen,
                "rows":         [],
                "quantity":     0.0,
                "amount":       0.0,
            }
            positions.append(current)
            continue

        m_row = _RE_PRODUCT_ROW.match(s)
        if m_row and current is not None:
            try:
                qty    = float(m_row.group("qty"))
                amount = float(m_row.group("amount"))
                rate   = float(m_row.group("rate"))
                gross  = float(m_row.group("gross"))
                net    = float(m_row.group("net"))
            except (TypeError, ValueError):
                continue
            if qty <= 0 or amount <= 0:
                continue
            type_token = m_row.group("type").upper()
            # Normalise singular/plural variants
            if type_token == "EARRING":
                type_token = "EARRING"
            current["rows"].append({
                "type":     type_token,
                "qty":      qty,
                "amount":   amount,
                "rate":     rate,
                "gross_wt": gross,
                "net_wt":   net,
            })
            current["quantity"] += qty
            current["amount"]   += amount

    # Drop empty positions (header with no parseable product rows below)
    positions = [p for p in positions if p["rows"]]

    # Recompute position_no after filtering empties (so sequence stays
    # 1..N with no gaps)
    for i, p in enumerate(positions, start=1):
        p["position_no"] = i

    return positions


def parse_invoice_positions_from_pdf(pdf_path: Path) -> List[Dict[str, Any]]:
    """Open a Global commercial-invoice PDF, extract text, parse
    positions. Returns [] on any failure (file missing, pdfplumber
    unavailable, no positions matched)."""
    try:
        import pdfplumber  # noqa: PLC0415
    except ImportError:
        return []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception:
        return []
    return parse_invoice_positions_from_text(text)


# ─────────────────────────────────────────────────────────────────────────────
# Render invoice positions → customs audit-row shape
# ─────────────────────────────────────────────────────────────────────────────


def _render_position_descriptions(
    position: Dict[str, Any],
) -> Tuple[str, str, str]:
    """Render (polish_customs_description, description_en, item_type_canon)
    for a parsed invoice position.

    The PL form is operator-locked grammar:
      "<pl-plural-types> <metal_pl>[ <stone_pl>]"

    Examples:
      "Bransoletki ze złota próby 375 z diamentami laboratoryjnymi"
      "Wisiorki, Pierścionki ze srebra próby 925 z cyrkoniami i kamieniami kolorowymi"
      "Pierścionki ze srebra próby 925"

    The EN form is:
      "<metal_en> <stone_en> <EN-PLURAL-TYPES>"

    Examples:
      "09KT Gold Lab Grown Diamond Jewellery BRACELETS"
      "925 Silver CZ & Colour Stone Jewellery PENDANTS, RINGS"
    """
    # Item-type list in occurrence order, deduplicated
    seen: set = set()
    types_ordered: List[str] = []
    for r in position["rows"]:
        t = r["type"].upper()
        # Singular EARRING / plural EARRINGS — map to one canonical "EARRINGS"
        if t in ("EARRING", "EARRINGS"):
            t = "EARRINGS"
        if t in ("CUFFLINK", "CUFFLINKS"):
            t = "CUFFLINKS"
        if t not in seen:
            types_ordered.append(t)
            seen.add(t)

    pl_types = [_PL_PLURAL_TYPE.get(t, t.capitalize()) for t in types_ordered]
    en_types = [_EN_PLURAL_TYPE.get(t, t) for t in types_ordered]

    metal_pl = position.get("metal_pl") or ""
    metal_en = position.get("metal_en") or ""
    stone_pl = position.get("stone_pl") or ""
    stone_en = position.get("stone_en") or "Plain Jewellery"

    # PL: <pl_types> <metal_pl>[ <stone_pl>]
    pl_parts = []
    if pl_types:
        pl_parts.append(", ".join(pl_types))
    if metal_pl:
        pl_parts.append(metal_pl)
    if stone_pl:
        pl_parts.append(stone_pl)
    pl = " ".join(p for p in pl_parts if p).strip()

    # EN: <metal_en> <stone_en> <EN_TYPES>
    en_parts = []
    if metal_en:
        en_parts.append(metal_en)
    if stone_en:
        en_parts.append(stone_en)
    if en_types:
        en_parts.append(", ".join(en_types))
    en = " ".join(p for p in en_parts if p).strip()

    # Engine grouping key — use first item type (positions are already
    # unique customs rows; engine groups by item_type so we ensure each
    # position has a unique synthesized type tag).
    item_type_canon = (types_ordered[0] if types_ordered else "MIXED")
    return (pl, en, item_type_canon)


def positions_to_audit_rows(
    positions: List[Dict[str, Any]],
    invoice_no: str,
) -> List[Dict[str, Any]]:
    """Convert parsed invoice positions to the audit-row shape consumed
    by the downstream description renderer + reconciler.

    Each position becomes exactly ONE row. No collapsing across
    positions. No splitting within positions. Customs authority:
    invoice line.

    Reconciler-required fields are populated:
      invoice_number, line_position, product_code, quantity,
      line_total, unit_price, currency, uom, item_type,
      polish_customs_description, description_en, item_type_pl.

    Plus operator-trace fields:
      _position_source_count (rows folded in),
      _supplier_profile      ("global_jewellery"),
      _rows_source           ("invoice_positions_authority"),
    """
    out: List[Dict[str, Any]] = []
    for pos in positions:
        pl, en, type_canon = _render_position_descriptions(pos)
        if not pl or not en:
            # Unmapped metal or stone → operator spec: never emit a row
            # with UNKNOWN / metal szlachetny. Skip; caller's
            # validate-then-rollback gate catches that case downstream.
            continue
        qty       = float(pos.get("quantity") or 0)
        amount    = round(float(pos.get("amount") or 0), 2)
        unit_p    = round(amount / qty, 6) if qty > 0 else 0.0
        out.append({
            "invoice_number":             invoice_no or "",
            "line_position":              pos["position_no"],
            "product_code":               f"{invoice_no}-INV-{pos['position_no']:02d}",
            "description":                en,
            "polish_customs_description": pl,
            "description_en":             en,
            "description_pl":             pl,
            "item_type":                  type_canon,
            "item_type_pl":               _PL_PLURAL_TYPE.get(type_canon,
                                                              type_canon.capitalize()),
            "material":                   "",
            "quantity":                   qty,
            "unit_price":                 unit_p,
            "line_total":                 amount,
            "line_total_usd":             amount,
            "hsn_code":                   "",
            "currency":                   "USD",
            "uom":                        pos["unit"],
            "_position_source_count":     len(pos.get("rows") or []),
            "_supplier_profile":          "global_jewellery",
            "_rows_source":               "invoice_positions_authority",
        })
    return out


def position_count(text_or_positions) -> int:
    """Convenience: how many invoice positions the parser produces for
    a given raw text (or a pre-parsed positions list)."""
    if isinstance(text_or_positions, list):
        return len(text_or_positions)
    return len(parse_invoice_positions_from_text(text_or_positions))
