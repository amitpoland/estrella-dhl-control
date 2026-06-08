"""
description_grammar.py — Shared grammar dictionaries for Polish customs descriptions.

This module is the SINGLE SOURCE OF TRUTH for all Polish-language grammar
tables used in customs description generation across the platform.

Consumers:
  - customs_description_engine.py  (singular forms — per-product descriptions)
  - global_invoice_position_parser.py  (plural forms — per-position aggregation) [Migration B]
  - polish_description_generator.py  (fallback descriptions) [Migration C]

Architecture rule:
  - Grammar dictionaries live in exactly ONE file (this one).
  - Consumers import what they need — no copy-paste of translation tables.
  - SINGULAR vs PLURAL distinction is preserved: the engine uses singular
    (Pierścionek), the parser uses plural (Pierścionki).

Grammar form inventory (Migration B1):
  - ITEM_TYPE_PL          — singular: "Pierścionek" (engine per-product)
  - ITEM_TYPE_PL_PLURAL   — plural:   "Pierścionki" (parser per-position)
  - GOLD_PURITY           — nominative: "złoto próby 585" (field displays)
  - PURITY_GENITIVE       — karat genitive: "14-karatowego złota (próba 585)" (engine)
  - METAL_PREPOSITIONAL   — old prepositional: "ze złota próby 585" (parser/aggregator)
  - STONE_INSTRUMENTAL    — bare instrumental: "diamentami" (engine after setting verb)
  - STONE_ABBR            — abbreviation -> nominative: "DIA" -> "diamenty"
  - GENDER_SETTING_VERB   — gender agreement: "Pierścionek" -> "wysadzany"

Helper functions:
  - metal_prepositional(key) — lookup from METAL_PREPOSITIONAL
  - stone_with_preposition(instrumental) — "z"/"ze" + instrumental form
  - stone_phrase_from_abbr(abbr) — full chain: abbreviation -> prepositional phrase

Origin: Migration A of the Description Engine Phase 2 campaign.
Phase 1 (PR #509, SHA 9c1c9df, 2026-06-08) upgraded the root engine grammar.
Migration B1: added plural types, prepositional metals, stone phrase helpers.
"""
from __future__ import annotations

from typing import Optional


# ── Item type -> Polish name (singular, title case) ───────────────────────────
# Used in per-product descriptions: "Pierścionek z 14-karatowego złota..."
ITEM_TYPE_PL: dict[str, str] = {
    "RING":      "Pierścionek",
    "EARRINGS":  "Kolczyki",
    "EARRING":   "Kolczyki",
    "BRACELET":  "Bransoletka",
    "BANGLE":    "Bransoletka sztywna",
    "PENDANT":   "Wisiorek",
    "NECKLACE":  "Naszyjnik",
    "BROOCH":    "Broszka",
    "SET":       "Komplet biżuterii",
    "CHAIN":     "Łańcuszek",
    "ANKLET":    "Bransoletka na kostkę",
    "STUD":      "Kolczyki wkrętki",
    "HOOP":      "Kolczyki kółka",
    "CUFFLINKS": "Spinki do mankietów",
    "CUFFLINK":  "Spinki do mankietów",
}

# ── Item type -> Polish name (PLURAL, title case) ────────────────────────────
# Used in aggregated position descriptions: "Pierścionki ze złota próby 585..."
# When multiple items of the same type are grouped under one invoice position
# or packing position, the plural form is used.
# Keys match ITEM_TYPE_PL for consistency.  Items that are inherently plural
# in Polish (Kolczyki, Spinki) have the same form in both tables.
# Origin: Migration B1 — shared grammar forms extension.
ITEM_TYPE_PL_PLURAL: dict[str, str] = {
    "RING":      "Pierścionki",
    "EARRINGS":  "Kolczyki",
    "EARRING":   "Kolczyki",
    "BRACELET":  "Bransoletki",
    "BANGLE":    "Bransoletki sztywne",
    "PENDANT":   "Wisiorki",
    "NECKLACE":  "Naszyjniki",
    "BROOCH":    "Broszki",
    "SET":       "Komplety biżuterii",
    "CHAIN":     "Łańcuszki",
    "ANKLET":    "Bransoletki na kostkę",
    "STUD":      "Kolczyki wkrętki",
    "HOOP":      "Kolczyki kółka",
    "CUFFLINKS": "Spinki do mankietów",
    "CUFFLINK":  "Spinki do mankietów",
}

# ── Gold/silver/platinum purity -> Polish name (nominative) ───────────────────
# Used in field displays: "złoto próby 585"
# Generic SILVER and PLATINUM entries removed: word alone carries no próby ->
# falls to "metal szlachetny" -> checker creates Inbox proposal.
GOLD_PURITY: dict[str, str] = {
    # Gold — karat codes resolve to confirmed próby values
    "9KT":    "złoto próby 375",
    "09KT":   "złoto próby 375",
    "10KT":   "złoto próby 417",
    "14KT":   "złoto próby 585",
    "18KT":   "złoto próby 750",
    "22KT":   "złoto próby 916",
    "24KT":   "złoto próby 999",
    # Silver — numeric próby codes only
    "925":    "srebro próby 925",
    "SL925":  "srebro próby 925",
    # Steel
    "SS":     "stal szlachetna",
    # Platinum — specific approved próby codes only
    "PT950":  "platyna próby 950",
    "PT900":  "platyna próby 900",
    "PT850":  "platyna próby 850",
}

# ── Genitive forms — used after preposition "z" in Polish sentences ──────────
# e.g. "Pierścionek z 14-karatowego złota (próba 585) wysadzany diamentami"
# e.g. "Pierścionek z platyny próby 950 wysadzany diamentami"
# Gold entries use karat-expanded form; silver/platinum stay as-is.
# Origin: operator review of AWB 9938632830 (2026-06-08).
PURITY_GENITIVE: dict[str, str] = {
    # Gold — karat-expanded genitive: "N-karatowego złota (próba NNN)"
    "9KT":    "9-karatowego złota (próba 375)",
    "09KT":   "9-karatowego złota (próba 375)",
    "10KT":   "10-karatowego złota (próba 417)",
    "14KT":   "14-karatowego złota (próba 585)",
    "18KT":   "18-karatowego złota (próba 750)",
    "22KT":   "22-karatowego złota (próba 916)",
    "24KT":   "24-karatowego złota (próba 999)",
    # Silver — numeric codes only (no karat system)
    "925":    "srebra próby 925",
    "SL925":  "srebra próby 925",
    # Steel
    "SS":     "stali szlachetnej",
    # Platinum — specific próby codes only (no karat system)
    "PT950":  "platyny próby 950",
    "PT900":  "platyny próby 900",
    "PT850":  "platyny próby 850",
}

# ── Stone instrumental forms — used after setting verb ────────────────────────
# "wysadzany/a/e diamentami", "wysadzany/a/e kamieniami szlachetnymi"
# Prior to Phase 1 these followed "z" — now they follow "wysadzany/a/e".
STONE_INSTRUMENTAL: dict[str, str] = {
    "diamenty":                            "diamentami",
    "diamenty i kamienie szlachetne":      "diamentami i kamieniami szlachetnymi",
    "kamienie szlachetne":                 "kamieniami szlachetnymi",
    "kamienie jubilerskie":                "kamieniami jubilerskimi",
    "kamienie ozdobne":                    "kamieniami ozdobnymi",
    "diamenty laboratoryjne":              "diamentami laboratoryjnymi",
    "diamenty laboratoryjne laboratoryjne": "diamentami laboratoryjnymi",
    "cyrkonie":                            "cyrkoniami",
    "rubiny":                              "rubinami",
    "szmaragdy":                           "szmaragdami",
    "szafiry":                             "szafirami",
    "perły":                               "perłami",
    "moissanit":                           "moissanitem",
}

# ── Gender-specific setting verb — agrees with item_type_pl noun gender ──────
# Used when stones are present: "Pierścionek ... wysadzany diamentami"
# Masculine -> wysadzany, Feminine -> wysadzana, Plural -> wysadzane
# Origin: operator review of AWB 9938632830 (2026-06-08).
GENDER_SETTING_VERB: dict[str, str] = {
    # Masculine (wysadzany)
    "Pierścionek":           "wysadzany",
    "Wisiorek":              "wysadzany",
    "Naszyjnik":             "wysadzany",
    "Łańcuszek":             "wysadzany",
    "Komplet biżuterii":    "wysadzany",
    # Feminine (wysadzana)
    "Bransoletka":           "wysadzana",
    "Bransoletka sztywna":   "wysadzana",
    "Broszka":               "wysadzana",
    "Bransoletka na kostkę": "wysadzana",
    # Plural (wysadzane)
    "Kolczyki":              "wysadzane",
    "Kolczyki wkrętki":      "wysadzane",
    "Kolczyki kółka":        "wysadzane",
    "Spinki do mankietów":   "wysadzane",
}

# ── Stone abbreviations -> Polish stone name (None = no stones) ───────────────
STONE_ABBR: dict[str, Optional[str]] = {
    "DIA":     "diamenty",
    "DIA&CLS": "diamenty i kamienie szlachetne",
    "DIAM":    "diamenty",
    "CLS":     "kamienie szlachetne",
    "LGD":     "diamenty laboratoryjne",
    "LG":      "diamenty laboratoryjne",
    "LAB":     "diamenty laboratoryjne",
    "PLAIN":   None,
    "CZ":      "cyrkonie",
    "RUBY":    "rubiny",
    "EMERALD": "szmaragdy",
    "SAPPHIRE": "szafiry",
    "PEARL":   "perły",
    "CUBIC":   "cyrkonie",
    "MOISS":   "moissanit",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Migration B1: Prepositional metal forms + stone phrase helpers
# ═══════════════════════════════════════════════════════════════════════════════
#
# The invoice parser, packing renderer, and position aggregator all use
# prepositional metal phrases ("ze złota próby 585") and prepositional
# stone phrases ("z diamentami").  These are distinct from:
#   - GOLD_PURITY (nominative: "złoto próby 585")
#   - PURITY_GENITIVE (karat genitive: "14-karatowego złota (próba 585)")
#   - STONE_INSTRUMENTAL (bare: "diamentami")
#
# The forms below are added so future consumer migrations can import them
# instead of maintaining local copies.  No consumer imports these yet.


# ── Prepositional metal forms ─────────────────────────────────────────────────
# "ze złota próby 585", "ze srebra próby 925", "z platyny próby 950"
#
# Used after item-type plural in position descriptions:
#   "Pierścionki ze złota próby 585 z diamentami"
#
# Preposition rule for this context (matches parser/aggregator convention):
#   "ze" before złota (z-), srebra (s-), stali (s-)
#   "z"  before platyny (p-)
#
# Keys match GOLD_PURITY / PURITY_GENITIVE for consistency.
METAL_PREPOSITIONAL: dict[str, str] = {
    # Gold — "ze złota próby NNN"
    "9KT":    "ze złota próby 375",
    "09KT":   "ze złota próby 375",
    "10KT":   "ze złota próby 417",
    "14KT":   "ze złota próby 585",
    "18KT":   "ze złota próby 750",
    "22KT":   "ze złota próby 916",
    "24KT":   "ze złota próby 999",
    # Silver — "ze srebra próby NNN"
    "925":    "ze srebra próby 925",
    "SL925":  "ze srebra próby 925",
    # Steel — "ze stali szlachetnej"
    "SS":     "ze stali szlachetnej",
    # Platinum — "z platyny próby NNN"
    "PT950":  "z platyny próby 950",
    "PT900":  "z platyny próby 900",
    "PT850":  "z platyny próby 850",
}


# ── Preposition helper (parser/aggregator convention) ─────────────────────────

def _prep_before(word: str) -> str:
    """Return Polish preposition 'z' or 'ze' before an instrumental/genitive noun.

    Uses the parser/aggregator convention: 'ze' before words starting with
    z, ź, ż, s, ś, sz, w (consonant clusters that make 'z' unpronounceable).
    This matches the forms in ``_METAL_TABLE``, ``_GLOBAL_METAL_TABLE``, and
    ``_STONE_RULES`` across the codebase.

    Note: the customs description engine's ``_prep()`` uses a narrower rule
    (only z/ź/ż) — that is intentional for the karat-genitive context and
    is NOT changed by this helper.
    """
    first_ch = (word or "").lstrip().lower()[:1]
    if first_ch in ("z", "ź", "ż", "s", "ś", "w"):
        return "ze"
    return "z"


# ── Helper functions ──────────────────────────────────────────────────────────

def metal_prepositional(purity_key: str) -> str:
    """Look up the prepositional metal phrase for a purity key.

    Returns the phrase used in parser/aggregator position descriptions.

    Examples::

        metal_prepositional("14KT")  -> "ze złota próby 585"
        metal_prepositional("925")   -> "ze srebra próby 925"
        metal_prepositional("PT950") -> "z platyny próby 950"
        metal_prepositional("??")    -> ""
    """
    return METAL_PREPOSITIONAL.get(purity_key, "")


def stone_with_preposition(instrumental: str) -> str:
    """Add the correct Polish preposition before a stone instrumental form.

    Returns the phrase used by the invoice parser's ``_STONE_RULES`` and
    position descriptions (e.g. "z diamentami", "z cyrkoniami").

    Examples::

        stone_with_preposition("diamentami")                -> "z diamentami"
        stone_with_preposition("cyrkoniami")                -> "z cyrkoniami"
        stone_with_preposition("diamentami laboratoryjnymi") -> "z diamentami laboratoryjnymi"
        stone_with_preposition("szmaragdami")               -> "ze szmaragdami"
        stone_with_preposition("")                          -> ""
    """
    if not instrumental or not instrumental.strip():
        return ""
    form = instrumental.strip()
    return f"{_prep_before(form)} {form}"


def stone_phrase_from_abbr(stone_abbr: str) -> str:
    """Full chain: stone abbreviation -> prepositional phrase.

    Chains ``STONE_ABBR`` -> ``STONE_INSTRUMENTAL`` -> ``stone_with_preposition``.
    Returns empty string for PLAIN or unknown abbreviations.

    Examples::

        stone_phrase_from_abbr("DIA")   -> "z diamentami"
        stone_phrase_from_abbr("CZ")    -> "z cyrkoniami"
        stone_phrase_from_abbr("LGD")   -> "z diamentami laboratoryjnymi"
        stone_phrase_from_abbr("PLAIN") -> ""
        stone_phrase_from_abbr("??")    -> ""
    """
    nominative = STONE_ABBR.get(stone_abbr)
    if nominative is None:
        return ""
    instrumental = STONE_INSTRUMENTAL.get(nominative)
    if instrumental is None:
        return ""
    return stone_with_preposition(instrumental)


# ═══════════════════════════════════════════════════════════════════════════════
# Migration B2: English-side dictionaries + short-description codes
# ═══════════════════════════════════════════════════════════════════════════════
#
# These dictionaries support three new output renderers in
# customs_description_engine.py (Phase 2B):
#
#   render_product_description_en()  — "Diamond 14KT Gold Ring"
#   render_short_description()       — "Ring Au585 DIA"
#   render_product_description_pl()  — uses PURITY_GENITIVE_PRODUCT below
#
# No consumer imports these yet — Migration B2 is the first use.
# Consumer migration (invoice, proforma, PZ, product master) is Phase 2C scope.


# ── English item type names (singular, title case) ────────────────────────────
# Used in Product Description EN and Short Description (type prefix).
# Keys match ITEM_TYPE_PL for cross-dict consistency.
# Plural forms are in global_invoice_position_parser._EN_PLURAL_TYPE and
# customs_position_aggregator._EN_PLURAL — migration to ITEM_TYPE_EN_PLURAL is
# Phase 2C scope.
ITEM_TYPE_EN: dict[str, str] = {
    "RING":      "Ring",
    "EARRINGS":  "Earrings",
    "EARRING":   "Earrings",
    "BRACELET":  "Bracelet",
    "BANGLE":    "Bangle",
    "PENDANT":   "Pendant",
    "NECKLACE":  "Necklace",
    "BROOCH":    "Brooch",
    "SET":       "Jewellery Set",
    "CHAIN":     "Chain",
    "ANKLET":    "Anklet",
    "STUD":      "Stud Earrings",
    "HOOP":      "Hoop Earrings",
    "CUFFLINKS": "Cufflinks",
    "CUFFLINK":  "Cufflinks",
}


# ── English stone adjective (used in Product Description EN) ──────────────────
# Key = Polish nominative from STONE_ABBR values.
# Value = English adjective placed BEFORE the metal + type phrase.
# Format: "[Stone Adj] [Purity] [Metal] [Type]" → "Diamond 14KT Gold Ring"
# "Plain" is not included — no-stone items omit the stone adjective entirely.
STONE_EN: dict[str, str] = {
    "diamenty":                            "Diamond",
    "diamenty i kamienie szlachetne":      "Diamond & Colour Stone",
    "kamienie szlachetne":                 "Colour Stone",
    "kamienie jubilerskie":                "Gemstone",
    "kamienie ozdobne":                    "Decorative Stone",
    "diamenty laboratoryjne":              "Lab Diamond",
    "diamenty laboratoryjne laboratoryjne": "Lab Diamond",
    "cyrkonie":                            "CZ",
    "rubiny":                              "Ruby",
    "szmaragdy":                           "Emerald",
    "szafiry":                             "Sapphire",
    "perły":                               "Pearl",
    "moissanit":                           "Moissanite",
}


# ── Short metal codes for Short Description ───────────────────────────────────
# Convention: Au = gold (aurum), Ag = silver (argentum), Pt = platinum.
# Number = próby value (European fineness standard).
# Keys match GOLD_PURITY / PURITY_GENITIVE / METAL_PREPOSITIONAL.
SHORT_DESC_METAL: dict[str, str] = {
    "9KT":    "Au375",
    "09KT":   "Au375",
    "10KT":   "Au417",
    "14KT":   "Au585",
    "18KT":   "Au750",
    "22KT":   "Au916",
    "24KT":   "Au999",
    "925":    "Ag925",
    "SL925":  "Ag925",
    "SS":     "SS",
    "PT950":  "Pt950",
    "PT900":  "Pt900",
    "PT850":  "Pt850",
}


# ── Short stone codes for Short Description ───────────────────────────────────
# Key = Polish nominative from STONE_ABBR values (None key not included).
# Value = compact code used in PZ/audit notes.
# Mirrors the original STONE_ABBR abbreviations so round-trips are consistent.
SHORT_DESC_STONE: dict[str, str] = {
    "diamenty":                            "DIA",
    "diamenty i kamienie szlachetne":      "DIA&CLS",
    "kamienie szlachetne":                 "CLS",
    "kamienie jubilerskie":                "CLS",
    "kamienie ozdobne":                    "STONE",
    "diamenty laboratoryjne":              "LGD",
    "diamenty laboratoryjne laboratoryjne": "LGD",
    "cyrkonie":                            "CZ",
    "rubiny":                              "RUBY",
    "szmaragdy":                           "EMERALD",
    "szafiry":                             "SAPPHIRE",
    "perły":                               "PEARL",
    "moissanit":                           "MOISS",
}


# ── Product description genitive (no parentheses) ─────────────────────────────
# Used in Product Description PL: invoice, proforma, PZ, product master.
# Differs from PURITY_GENITIVE (customs) in that gold entries use
# "próby NNN" (plain genitive prose) instead of "(próba NNN)" (parenthetical
# customs note).
#
# Compare:
#   PURITY_GENITIVE["14KT"]         = "14-karatowego złota (próba 585)"   ← customs
#   PURITY_GENITIVE_PRODUCT["14KT"] = "14-karatowego złota próby 585"     ← product/invoice
#
# Silver and platinum entries are identical in both dicts (no parenthetical form needed).
# Keys match GOLD_PURITY / PURITY_GENITIVE / METAL_PREPOSITIONAL.
PURITY_GENITIVE_PRODUCT: dict[str, str] = {
    "9KT":    "9-karatowego złota próby 375",
    "09KT":   "9-karatowego złota próby 375",
    "10KT":   "10-karatowego złota próby 417",
    "14KT":   "14-karatowego złota próby 585",
    "18KT":   "18-karatowego złota próby 750",
    "22KT":   "22-karatowego złota próby 916",
    "24KT":   "24-karatowego złota próby 999",
    "925":    "srebra próby 925",
    "SL925":  "srebra próby 925",
    "SS":     "stali szlachetnej",
    "PT950":  "platyny próby 950",
    "PT900":  "platyny próby 900",
    "PT850":  "platyny próby 850",
}
