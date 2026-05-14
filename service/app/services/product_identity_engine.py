"""
product_identity_engine.py — Canonical product identity resolution.

Single source of truth for:
  - Parsing and validating EJL / 417 Global product codes
  - Assigning confidence tiers (HIGH / MEDIUM / LOW) to product identities
  - Detecting generic/fallback descriptions that are not wFirma-eligible
  - Composing description_bilingual (Polish-first / English-after-slash)
  - Parsing compound quality strings from packing XLSX

This module is READ-ONLY with respect to storage.
It never creates products, never writes to wFirma, never posts proformas.
Write operations are gated behind wfirma_product_auto_register.py (flag-gated)
and are intentionally NOT wired in this PR.

Confidence tiers
----------------
HIGH   — item_type (specific) + karat (known) + metal_color (known)
         + stone_type present + non-generic description_pl
MEDIUM — item_type (specific) + karat (known) + non-generic description_pl
LOW    — item_type missing/unknown, OR karat missing, OR description_pl is
         a known generic fallback

wFirma eligibility: HIGH and MEDIUM only.
LOW requires operator review via description_engine.set_manual_block().

417 Global product codes
------------------------
"417 Global Invoice-N" codes are NOT globally unique — two different 417 Global
shipments would each have a line-1 with the same code. These are always
flagged requires_manual_code=True and wfirma_eligible=False regardless of
confidence. The operator must assign a scoped identifier before registration.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

# ── Generic fallback description guard ────────────────────────────────────────

# These descriptions are forbidden as wFirma product names because they convey
# no product-specific information.  Any description_pl that normalises to one
# of these is blocked (wfirma_eligible=False, confidence=LOW).
_GENERIC_PATTERNS: frozenset[str] = frozenset({
    "biżuteria złota",
    "biżuteria srebrna",
    "biżuteria",
    "wyrób jubilerski",
    "wyrób",
    "towar",
    "gold jewellery",        # English fallback sometimes stored in pl_desc
    "silver jewellery",
})

GENERIC_FALLBACK_DESCRIPTIONS: frozenset[str] = frozenset({
    "Biżuteria złota",
    "Biżuteria srebrna",
    "Biżuteria",
    "Wyrób jubilerski",
    "Wyrób",
    "Towar",
})

# item_type strings that must never appear as a product_code key in the
# product_descriptions table.  The stubs keyed by these names are legacy
# garbage that must be deleted (migration forward-compat section).
FORBIDDEN_PRODUCT_CODE_KEYS: frozenset[str] = frozenset({
    "RING", "PENDANT", "BRACELET", "EARRINGS", "EARRING",
    "NECKLACE", "BANGLE", "ANKLET", "CUFFLINK", "CUFFLINKS",
    "SET", "BROOCH", "CHAIN", "STUD", "HOOP",
})

# ── Known canonical values ────────────────────────────────────────────────────

KNOWN_KARAT_VALUES: frozenset[str] = frozenset({
    "9KT", "09KT", "10KT", "14KT", "18KT", "22KT", "24KT",
    "925", "SL925", "SILVER", "SS",
})

KNOWN_METAL_COLORS: frozenset[str] = frozenset({
    "W", "Y", "P", "R",
    "WPD", "YPD", "RPD",
    "WY", "WP", "YP",
})

CANONICAL_ITEM_TYPES: frozenset[str] = frozenset({
    "RING", "RINGS",
    "PENDANT", "PENDANTS",
    "EARRING", "EARRINGS",
    "BRACELET", "BRACELETS",
    "NECKLACE", "NECKLACES",
    "BANGLE", "BANGLES",
    "ANKLET", "ANKLETS",
    "CUFFLINK", "CUFFLINKS",
    "SET", "SETS",
    "BROOCH",
    "CHAIN",
    "STUD",
    "HOOP",
})

# ── Product code patterns ─────────────────────────────────────────────────────

# EJL full:  EJL/26-27/148-1
# EJL short: EJL/26-27/100  (single-line invoice — line suffix optional)
# Space variant: "EJL/26-27/100 -1" — some older batches emit a space before
# the dash.  Both "EJL/26-27/100-1" and "EJL/26-27/100 -1" are valid EJL.
_EJL_RE = re.compile(
    r"^(?P<prefix>EJL)"
    r"/(?P<year>\d{2}-\d{2})"
    r"/(?P<invoice_seq>\d+)"
    r"(?:\s*-(?P<line_pos>\d+))?$",
    re.IGNORECASE,
)

# 417 Global: "417 Global Invoice-13"
_G417_RE = re.compile(
    r"^(?P<prefix>417\s+Global\s+Invoice)"
    r"-(?P<line_pos>\d+)$",
    re.IGNORECASE,
)

# ── Named stones that appear in quality strings ────────────────────────────────

_NAMED_STONE_WORDS: frozenset[str] = frozenset({
    "EMERALD", "SAPPHIRE", "RUBY", "PEARL", "AMETHYST",
    "ALEXANDRITE", "TOPAZ", "GARNET", "AQUAMARINE",
    "BLUE SAPPHIRE", "YELLOW SAPPHIRE", "ORANGE SAPPHIRE",
    "PINK SAPPHIRE", "GREEN SAPPHIRE",
})

_LAB_SEGMENT_RE = re.compile(r"\bLAB\b", re.IGNORECASE)


# ── Quality string parser ─────────────────────────────────────────────────────

@dataclass
class QualityComponents:
    """Parsed components of a packing XLSX quality string."""
    raw:               str
    diamond_primary:   str       # e.g. "F-VS" (first diamond grade segment)
    diamond_secondary: str       # e.g. "E-VVS" (second grade, when compound)
    lab_grown:         bool
    named_stones:      List[str] # e.g. ["Emerald", "Blue Sapphire"]
    is_compound:       bool      # True when raw contains multiple comma segments


def parse_quality_string(raw: str) -> QualityComponents:
    """
    Parse a compound quality string from a packing XLSX Quality column.

    Examples handled:
      "F-VS LAB"                      → lab_grown=True, primary="F-VS"
      "GH-SI"                         → primary="GH-SI"
      "G-VS LAB,E-VVS LAB"           → primary="G-VS", secondary="E-VVS", lab=True
      "F-VS LAB,EMERALD"              → lab=True, named_stones=["Emerald"]
      "G-VS,Blue Sapphire,Amethyst"   → primary="G-VS", named_stones=[...]
      ""                              → all empty / defaults
    """
    raw = (raw or "").strip()
    if not raw:
        return QualityComponents(
            raw="", diamond_primary="", diamond_secondary="",
            lab_grown=False, named_stones=[], is_compound=False,
        )

    segments = [s.strip() for s in raw.split(",") if s.strip()]
    is_compound = len(segments) > 1

    diamond_segs: List[str] = []
    named_stones: List[str] = []
    lab_grown = False

    for seg in segments:
        seg_up = seg.upper()

        if _LAB_SEGMENT_RE.search(seg_up):
            lab_grown = True

        # Check for named stones (longest match first to catch "Blue Sapphire")
        matched_stone = None
        for stone in sorted(_NAMED_STONE_WORDS, key=len, reverse=True):
            if stone.upper() in seg_up:
                matched_stone = stone.title()
                break

        if matched_stone:
            named_stones.append(matched_stone)
        else:
            # Remove LAB token and trim; keep the grade portion (e.g. "F-VS")
            grade = _LAB_SEGMENT_RE.sub("", seg).strip(" ,").strip()
            if grade:
                diamond_segs.append(grade)

    return QualityComponents(
        raw=raw,
        diamond_primary=diamond_segs[0] if len(diamond_segs) >= 1 else "",
        diamond_secondary=diamond_segs[1] if len(diamond_segs) >= 2 else "",
        lab_grown=lab_grown,
        named_stones=named_stones,
        is_compound=is_compound,
    )


# ── Product code parser ───────────────────────────────────────────────────────

@dataclass
class ProductCodeParsed:
    """Parsed components of a raw product_code string."""
    product_code:        str
    supplier_prefix:     str   # "EJL" | "417G" | "UNKNOWN"
    invoice_no:          str
    line_position:       int   # 0 when absent (single-line invoice)
    is_globally_unique:  bool
    requires_manual_code: bool  # True for 417G and UNKNOWN


def parse_product_code(product_code: str) -> ProductCodeParsed:
    """
    Parse an EJL-format or 417-Global-format product code.

    EJL codes are globally unique (supplier_prefix + fiscal_year +
    invoice_number + line_position uniquely identifies one commercial line
    across all batches and all time).

    417 Global codes are NOT globally unique — they are positional within a
    single shipment document.  Two different 417 Global shipments each have
    a line-1 that would share the same product_code string.  These require
    operator-assigned scoped identifiers before wFirma registration.

    Returns ProductCodeParsed with all extracted fields.
    """
    pc = (product_code or "").strip()

    # ── EJL format ─────────────────────────────────────────────────────────
    m = _EJL_RE.match(pc)
    if m:
        year     = m.group("year")
        seq      = m.group("invoice_seq")
        line_pos = int(m.group("line_pos")) if m.group("line_pos") else 0
        inv_no   = f"EJL/{year}/{seq}"
        return ProductCodeParsed(
            product_code=pc,
            supplier_prefix="EJL",
            invoice_no=inv_no,
            line_position=line_pos,
            is_globally_unique=True,
            requires_manual_code=False,
        )

    # ── 417 Global format ──────────────────────────────────────────────────
    m = _G417_RE.match(pc)
    if m:
        line_pos = int(m.group("line_pos"))
        return ProductCodeParsed(
            product_code=pc,
            supplier_prefix="417G",
            invoice_no="417 Global Invoice",
            line_position=line_pos,
            is_globally_unique=False,
            requires_manual_code=True,
        )

    # ── Unknown format ─────────────────────────────────────────────────────
    return ProductCodeParsed(
        product_code=pc,
        supplier_prefix="UNKNOWN",
        invoice_no="",
        line_position=0,
        is_globally_unique=False,
        requires_manual_code=True,
    )


# ── Generic description guard ─────────────────────────────────────────────────

def is_generic_description(description_pl: str) -> bool:
    """
    Return True when description_pl is a known generic fallback that is not
    acceptable as a wFirma product name.

    These descriptions are forbidden as wFirma product names because they
    give no product-specific information:
      "Biżuteria złota", "Biżuteria srebrna", "Biżuteria",
      "Wyrób jubilerski", "Wyrób", "Towar"

    Also returns True for empty or whitespace-only strings.
    """
    if not description_pl or not description_pl.strip():
        return True
    normalized = description_pl.strip().lower()
    return normalized in _GENERIC_PATTERNS


# ── Confidence model ──────────────────────────────────────────────────────────

def assign_confidence(
    *,
    item_type:      str,
    karat:          str,
    metal_color:    str = "",
    stone_type:     str = "",
    description_pl: str = "",
) -> str:
    """
    Assign a confidence tier to a product identity record.

    HIGH   — item_type is specific (in CANONICAL_ITEM_TYPES)
             AND karat is known (in KNOWN_KARAT_VALUES)
             AND metal_color is known (in KNOWN_METAL_COLORS)
             AND stone_type is present
             AND description_pl is not generic.

    MEDIUM — item_type is specific
             AND karat is known
             AND description_pl is not generic.

    LOW    — anything else (missing item_type, missing karat, generic
             description, 417G code — these all collapse to LOW).

    Returns one of: "HIGH", "MEDIUM", "LOW".
    """
    it = (item_type or "").strip().upper()
    kt = (karat or "").strip().upper()
    mc = (metal_color or "").strip().upper()
    st = (stone_type or "").strip()

    # Normalise known aliases
    if it == "EARRING":
        it = "EARRINGS"
    if it == "CUFFLINK":
        it = "CUFFLINKS"

    item_ok  = it in CANONICAL_ITEM_TYPES
    karat_ok = kt in KNOWN_KARAT_VALUES
    color_ok = mc in KNOWN_METAL_COLORS
    desc_ok  = not is_generic_description(description_pl)

    if item_ok and karat_ok and color_ok and st and desc_ok:
        return "HIGH"
    if item_ok and karat_ok and desc_ok:
        return "MEDIUM"
    return "LOW"


# ── Bilingual description composer ────────────────────────────────────────────

def compose_bilingual(description_pl: str, description_en: str) -> str:
    """
    Compose the canonical bilingual product description line.

    Format: "{Polish} / {English}"
    Polish is ALWAYS first. Never reversed.
    If one side is empty, returns only the non-empty side (no trailing slash).

    Examples:
      compose_bilingual("Pierścionek ze złota", "Diamond RING")
        → "Pierścionek ze złota / Diamond RING"
      compose_bilingual("Pierścionek ze złota", "")
        → "Pierścionek ze złota"
    """
    pl = (description_pl or "").strip()
    en = (description_en or "").strip()
    if pl and en:
        return f"{pl} / {en}"
    return pl or en


# ── Full product identity resolver ────────────────────────────────────────────

@dataclass
class ProductIdentity:
    """
    Canonical product identity record.

    This is the output of resolve_product_identity().  All fields are
    derived from the supplied inputs; no DB reads or writes occur.

    Use wfirma_eligible to gate any registration attempt:
      True  → may be passed to wfirma_product_auto_register (when flag is on)
      False → requires operator review via description_engine.set_manual_block()
    """
    product_code:           str
    supplier_prefix:        str
    invoice_no:             str
    line_position:          int
    design_no:              str
    item_type:              str
    karat:                  str
    metal_color:            str
    quality_string:         str
    stone_type:             str
    description_pl:         str
    description_en:         str
    description_bilingual:  str
    customs_description_pl: str
    unit_price_eur:         float
    unit_price_usd:         float
    hs_code:                str
    confidence:             str        # "HIGH" | "MEDIUM" | "LOW"
    source:                 str
    missing_fields:         List[str]  # fields that were empty/unknown at resolve time
    is_globally_unique:     bool
    requires_manual_code:   bool
    wfirma_eligible:        bool       # True iff confidence in (HIGH, MEDIUM) and not requires_manual_code


def resolve_product_identity(
    product_code: str,
    *,
    design_no:              str   = "",
    item_type:              str   = "",
    karat:                  str   = "",
    metal_color:            str   = "",
    quality_string:         str   = "",
    stone_type:             str   = "",
    description_pl:         str   = "",
    description_en:         str   = "",
    customs_description_pl: str   = "",
    unit_price_eur:         float = 0.0,
    unit_price_usd:         float = 0.0,
    hs_code:                str   = "",
    source:                 str   = "pz_rows",
) -> ProductIdentity:
    """
    Resolve the canonical product identity for a product_code.

    READ-ONLY — no writes, no API calls.  Accepts inputs from any upstream
    source (invoice_lines, pz_rows, packing_lines) and computes all derived
    fields: bilingual description, stone_type (from quality_string when not
    supplied), confidence tier, missing-field list, and wFirma eligibility.

    Inputs should be provided as empty strings / 0.0 when not available.
    """
    parsed = parse_product_code(product_code)

    # Normalise item_type aliases
    it = (item_type or "").strip().upper()
    if it == "EARRING":
        it = "EARRINGS"
    if it == "CUFFLINK":
        it = "CUFFLINKS"

    # Effective stone_type: use caller-supplied value first, then derive from
    # quality_string if the caller left stone_type blank.
    eff_stone = (stone_type or "").strip()
    if not eff_stone and quality_string:
        qc = parse_quality_string(quality_string)
        if qc.lab_grown:
            eff_stone = "LAB_DIAMOND"
        elif qc.named_stones:
            eff_stone = qc.named_stones[0].upper()
        elif qc.diamond_primary:
            eff_stone = "DIAMOND"

    # Confidence — 417G is always LOW regardless of other fields because it
    # is not globally unique and cannot be safely registered in wFirma.
    if parsed.requires_manual_code:
        confidence = "LOW"
    else:
        confidence = assign_confidence(
            item_type=it,
            karat=karat,
            metal_color=metal_color,
            stone_type=eff_stone,
            description_pl=description_pl,
        )

    # Bilingual description (Polish first, always)
    bil = compose_bilingual(description_pl, description_en)

    # Missing fields list — helps operator understand what to supply
    missing: List[str] = []
    if not it or it not in CANONICAL_ITEM_TYPES:
        missing.append("item_type")
    kt_up = (karat or "").strip().upper()
    if not kt_up or kt_up not in KNOWN_KARAT_VALUES:
        missing.append("karat")
    if not (metal_color or "").strip():
        missing.append("metal_color")
    if not quality_string:
        missing.append("quality_string")
    if not description_pl or is_generic_description(description_pl):
        missing.append("description_pl")
    if not description_en:
        missing.append("description_en")
    if not hs_code:
        missing.append("hs_code")

    # wFirma eligibility: must be HIGH or MEDIUM confidence, globally unique
    # code, and non-generic description.
    wfirma_eligible = (
        confidence in ("HIGH", "MEDIUM")
        and not parsed.requires_manual_code
        and not is_generic_description(description_pl)
    )

    return ProductIdentity(
        product_code=product_code,
        supplier_prefix=parsed.supplier_prefix,
        invoice_no=parsed.invoice_no,
        line_position=parsed.line_position,
        design_no=(design_no or "").strip(),
        item_type=it,
        karat=(karat or "").strip().upper(),
        metal_color=(metal_color or "").strip().upper(),
        quality_string=(quality_string or "").strip(),
        stone_type=eff_stone,
        description_pl=(description_pl or "").strip(),
        description_en=(description_en or "").strip(),
        description_bilingual=bil,
        customs_description_pl=(customs_description_pl or "").strip(),
        unit_price_eur=float(unit_price_eur or 0.0),
        unit_price_usd=float(unit_price_usd or 0.0),
        hs_code=(hs_code or "").strip(),
        confidence=confidence,
        source=(source or "pz_rows").strip(),
        missing_fields=missing,
        is_globally_unique=parsed.is_globally_unique,
        requires_manual_code=parsed.requires_manual_code,
        wfirma_eligible=wfirma_eligible,
    )
