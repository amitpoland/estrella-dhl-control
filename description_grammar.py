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


# ═══════════════════════════════════════════════════════════════════════════════
# Item-type normalisation — THE single authority
# ═══════════════════════════════════════════════════════════════════════════════
#
# EJL/Ethos packing lists carry 3-letter category codes in the "Ctg" column
# ("RNG", "BRC", "PND"); the grammar tables above are keyed by long names
# ("RING", "BRACELET", "PENDANT").  Nothing bridged the two, so
# render_product_description_en("RNG") fell through to "RNG".title() == "Rng"
# and the Polish half degraded to the generic "Wyrób jubilerski — ...", which was
# then upserted with source='auto' and locked forever (Campaign 4, 23 rows).
#
# The alias map lives HERE — next to the tables it keys into — and nowhere else.
# Consumers are thin wrappers that adapt the casing to their own contract:
#   description_engine._normalise_item_type       (UPPER, falls back to raw)
#   invoice_packing_extractor._canonical_item_type (lower, falls back to a-z squash)
#   routes_dhl_clearance._normalise_type_key       (UPPER, falls back to raw)
# Do NOT re-declare a local copy — a "keep in sync" comment is not a mechanism.

import re as _re

# Normalised token (a-z only, lowercase) -> canonical ITEM_TYPE_PL/ITEM_TYPE_EN key.
ITEM_TYPE_ALIASES: dict[str, str] = {
    # Pendant
    "pnd": "PENDANT",  "pend": "PENDANT", "pendant": "PENDANT",
    # Ring
    "rng": "RING",     "ring": "RING",
    # Earring — every EJL alias including 2-letter and plural forms
    "erg": "EARRING",  "er": "EARRING",   "ers": "EARRING",
    "ear": "EARRING",  "ears": "EARRING",
    "earring": "EARRING", "earrings": "EARRING",
    "prs": "EARRING",   # EJL packing "PRS" (pairs) = earrings
    # Bracelet
    "brc": "BRACELET", "br": "BRACELET",  "bracelet": "BRACELET",
    # Necklace
    "nck": "NECKLACE", "nec": "NECKLACE", "nk": "NECKLACE",
    "necklace": "NECKLACE",
    # Bangle
    "bng": "BANGLE",   "ban": "BANGLE",   "bangle": "BANGLE",
    # Brooch
    "bro": "BROOCH",   "brooch": "BROOCH",
    # Cufflinks
    "cfl": "CUFFLINK", "cuf": "CUFFLINK", "cufflink": "CUFFLINK",
    "cufflinks": "CUFFLINK",
    # Chain
    "chn": "CHAIN",    "chain": "CHAIN",
}

# Longest-first so "cufflinks" wins over "cufflink" when scanning free text.
_ALIAS_BY_LENGTH = sorted(ITEM_TYPE_ALIASES.items(), key=lambda kv: -len(kv[0]))

# Rendered English labels ("Ring", "Jewellery Set") — used to recognise a
# description that is nothing but a category label.
_EN_LABELS = {_re.sub(r"[^a-z]", "", v.lower()) for v in ITEM_TYPE_EN.values()}


def _squash(value: str) -> str:
    """Lowercase and drop everything that is not a-z."""
    return _re.sub(r"[^a-z]", "", (value or "").lower())


def canonical_item_type(value: str) -> str:
    """Direct-hit normalisation: item-type token -> canonical grammar key.

    Returns the UPPERCASE key shared by :data:`ITEM_TYPE_PL` and
    :data:`ITEM_TYPE_EN`, or ``""`` when *value* is not a recognised item type.
    Callers decide their own fallback — this function never guesses.

    Examples::

        canonical_item_type("RNG")      -> "RING"
        canonical_item_type("ring")     -> "RING"
        canonical_item_type("STUD")     -> "STUD"   (table key, no alias needed)
        canonical_item_type("14KT")     -> ""
    """
    norm = _squash(value)
    if not norm:
        return ""
    canon = ITEM_TYPE_ALIASES.get(norm)
    if canon:
        return canon
    upper = norm.upper()
    return upper if upper in ITEM_TYPE_PL else ""


def canonical_item_type_fuzzy(value: str) -> str:
    """:func:`canonical_item_type` plus a substring scan over free text.

    Used by the invoice/packing extractor, which matches item types out of
    supplier description strings ("14KT Gold Bracelet 7 inch" -> ``BRACELET``).
    Only tokens of 4+ characters are scanned, so "er"/"br" cannot false-match.
    Returns ``""`` when nothing is recognised.
    """
    direct = canonical_item_type(value)
    if direct:
        return direct
    norm = _squash(value)
    if not norm:
        return ""
    for token, canon in _ALIAS_BY_LENGTH:
        if len(token) >= 4 and token in norm:
            return canon
    return ""


def is_item_type_token(value: str) -> bool:
    """True when *value* is nothing but a category label.

    Direct hit only — "Gold Jewellery Ring" is a description, "Rng" is not.
    Used to reject manufactured abbreviations that were written into
    ``product_descriptions.description_en``.
    """
    norm = _squash(value)
    if not norm:
        return False
    return (
        norm in ITEM_TYPE_ALIASES
        or norm.upper() in ITEM_TYPE_PL
        or norm in _EN_LABELS
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Material-component semantics — THE single material parser
# ═══════════════════════════════════════════════════════════════════════════════
#
# Governing invariant:
#
#     Normalization may improve language.
#     It may NEVER remove a material component present in the source.
#
# Before this block, TWO independent parsers each kept exactly ONE metal:
#
#   commercial — pz_import_processor.normalize_family() / get_karat()
#       returned a single family + a single purity token, so
#       "18KT Gold,LGD Stud PT950 Com" rendered platinum-only.
#   customs    — customs_description_engine.normalize_item_description()
#       scanned GOLD_PURITY with a first-match-wins ``break``; the dict is
#       ordered gold -> silver -> steel -> platinum, so gold always won and
#       "SILVER Plain 10kt Gold Com" rendered gold-only.
#
# Mixed-metal goods ("Com" = combination on Estrella/EJL invoices) therefore
# lost a material that is physically present, and the loss propagated into the
# commercial invoice, the customs declaration, wFirma, and customer documents.
#
# Both engines now consume ``parse_material_components()``.  This module
# IDENTIFIES materials; it does not render sentences.  Each engine keeps its
# own vocabulary (customs says "18-karatowego złota (próba 750)", the
# commercial builder says "ze złota próby 18 karatów") — those are two roles,
# not two copies, and unifying their wording would silently rewrite persisted
# golden rows.  No third generator is introduced here.

from dataclasses import dataclass, field


# ── Bare metal words — a metal name with NO próba evidence ────────────────────
# "SILVER" on an invoice line is evidence of silver.  It is NOT evidence of
# próba 925 — the commercial builder used to print "próby 925" for any silver
# row, inventing a hallmark the source never stated.
#
# Deliberately kept OUT of GOLD_PURITY: that dict means "purity code -> próba",
# every consumer treats a hit as a confirmed próba, and its length is pinned by
# service/tests/test_description_grammar_parity.py.
#
# Only SILVER is listed.  Bare "GOLD"/"PLATINUM" are NOT tokens: they appear as
# noise next to a real purity code on nearly every line ("18KT Gold"), and
# "gold plated silver" would be read as solid gold.  Adding one is a scope
# decision, not a typo fix.
BARE_METAL_TOKENS: dict[str, str] = {
    "SILVER": "srebro",
}

BARE_METAL_GENITIVE: dict[str, str] = {
    "SILVER": "srebra",
}

BARE_METAL_GENITIVE_PRODUCT: dict[str, str] = {
    "SILVER": "srebra",
}

BARE_METAL_PREPOSITIONAL: dict[str, str] = {
    "SILVER": "ze srebra",
}

BARE_METAL_SHORT: dict[str, str] = {
    "SILVER": "Ag",
}


# ── Metal family per material key ─────────────────────────────────────────────
# Explicit, not derived from the Polish strings: a reviewer must be able to see
# which metal a key means without parsing prose.
_MATERIAL_METAL: dict[str, str] = {
    "9KT": "gold", "09KT": "gold", "10KT": "gold", "14KT": "gold",
    "18KT": "gold", "22KT": "gold", "24KT": "gold",
    "925": "silver", "SL925": "silver", "SILVER": "silver",
    "SS": "steel",
    "PT950": "platinum", "PT900": "platinum", "PT850": "platinum",
}

# Polish stem + English word per metal family.  The stems are what
# check_material_completeness() looks for, so they must survive every
# declension the renderers produce:
#   złoto / złota / złotem      -> "złot"
#   srebro / srebra / srebrny   -> "srebr"
#   platyna / platyny           -> "platyn"
#   stal / stali / stalowy      -> "stal"
_METAL_PL_STEM: dict[str, str] = {
    "gold": "złot", "silver": "srebr", "platinum": "platyn", "steel": "stal",
}
_METAL_EN: dict[str, str] = {
    "gold": "Gold", "silver": "Silver", "platinum": "Platinum", "steel": "Steel",
}

# Numeric part of a purity key, used by renderers that spell the próba out.
_PURITY_DIGITS: dict[str, str] = {
    "9KT": "9", "09KT": "9", "10KT": "10", "14KT": "14",
    "18KT": "18", "22KT": "22", "24KT": "24",
    "925": "925", "SL925": "925",
    "PT950": "950", "PT900": "900", "PT850": "850",
    "SS": "", "SILVER": "",
}

# Legacy display token.  "09KT" and "9KT" are the same próba; the commercial
# builder has always printed the un-padded form, and golden rows depend on it.
_DISPLAY_KEY: dict[str, str] = {"09KT": "9KT"}


# ── Combination marker ────────────────────────────────────────────────────────
# EJL/Estrella invoices mark a mixed-material piece with "Com" (combination):
#   "PCS, SILVER Plain 10kt Gold Com Jewell RING"
# Nothing in the platform recognised this token before.
COMBINATION_RE = _re.compile(r"\bCOM(?:B|BO|BINATION)?\b", _re.IGNORECASE)

# All material tokens, longest-first so "SL925" wins over "925" and "09KT"
# over "9KT" when two alternatives could start at the same offset.
_ALL_MATERIAL_KEYS: list = sorted(
    list(GOLD_PURITY.keys()) + list(BARE_METAL_TOKENS.keys()),
    key=len,
    reverse=True,
)
_ALL_PURITY_RE = _re.compile(
    r"\b(" + "|".join(_re.escape(k) for k in _ALL_MATERIAL_KEYS) + r")\b",
    _re.IGNORECASE,
)

# Stone abbreviations, longest-first ("DIA&CLS" before "DIA", "PLAIN" before
# nothing).  Keys come from STONE_ABBR — no second stone table.
_STONE_KEYS_BY_LENGTH: list = sorted(STONE_ABBR.keys(), key=len, reverse=True)

# Lab-grown markers.  "NAT DIA" (natural diamond) is the explicit opposite;
# a diamond with neither marker is reported as natural, which is what the
# supplier's unqualified "DIA" has always meant.
_LAB_GROWN_RE = _re.compile(
    r"\b(?:LGD|LG|LAB|LAB[\s-]?GROWN|LAB[\s-]?CREATED)\b", _re.IGNORECASE
)
_DIAMOND_PL = {"diamenty", "diamenty i kamienie szlachetne"}
_LAB_DIAMOND_PL = "diamenty laboratoryjne"

# review_reason values — stable strings, asserted by tests and surfaced to the
# operator as ``description_review_required``.
REVIEW_NO_MATERIAL = "no_material_recognized"
REVIEW_NO_COMBINATION_MARKER = "multiple_materials_without_combination_marker"


@dataclass
class MaterialComponent:
    """ONE material present in a source row.

    A row may carry several.  ``purity_key`` is the token as matched in the
    source (``"18KT"``, ``"SL925"``, ``"SILVER"``); every other field is the
    resolved form, looked up once at parse time so no consumer re-parses.

    ``has_purity`` is False for a bare metal word.  A renderer MUST NOT print
    a próba for such a component — that is the "925 invented from nothing"
    defect this dataclass exists to prevent.
    """

    purity_key: str
    metal: str
    has_purity: bool
    purity_nominative_pl: str
    purity_genitive_pl: str
    purity_genitive_product_pl: str
    metal_prepositional_pl: str
    short_code: str
    en_metal: str
    en_label: str
    pl_stem: str
    display_key: str
    purity_digits: str


@dataclass
class ParsedMaterial:
    """Every material the source row states, plus what could not be resolved.

    ``components`` preserves SOURCE ORDER — "SILVER Plain 10kt Gold Com" is
    silver-then-gold, and the commercial description reads in that order.

    ``description_review_required`` is the honest-uncertainty channel: the
    parser surfaces ambiguity instead of manufacturing a confident answer.
    """

    components: list = field(default_factory=list)
    construction: str = "single"
    stone_abbr: str = ""
    stone_pl: Optional[str] = None
    natural_or_lab: Optional[str] = None
    description_review_required: bool = False
    review_reason: str = ""

    @property
    def metal_keys(self) -> list:
        """Purity keys in source order — the material identity of the row."""
        return [c.purity_key for c in self.components]

    @property
    def is_combination(self) -> bool:
        return self.construction == "combination"


def _build_component(purity_key: str) -> MaterialComponent:
    """Resolve one matched token into a fully-populated component."""
    key = purity_key.upper()
    metal = _MATERIAL_METAL.get(key, "")
    has_purity = key in GOLD_PURITY
    display_key = _DISPLAY_KEY.get(key, key)
    en_metal = _METAL_EN.get(metal, "")

    if has_purity:
        nominative = GOLD_PURITY[key]
        genitive = PURITY_GENITIVE.get(key, "")
        genitive_product = PURITY_GENITIVE_PRODUCT.get(key, "")
        prepositional = METAL_PREPOSITIONAL.get(key, "")
        short_code = SHORT_DESC_METAL.get(key, "")
    else:
        nominative = BARE_METAL_TOKENS.get(key, "")
        genitive = BARE_METAL_GENITIVE.get(key, "")
        genitive_product = BARE_METAL_GENITIVE_PRODUCT.get(key, "")
        prepositional = BARE_METAL_PREPOSITIONAL.get(key, "")
        short_code = BARE_METAL_SHORT.get(key, "")

    # English label — the form each renderer places next to the item type.
    # Gold and platinum lead with the purity code ("18KT Gold", "PT950
    # Platinum"); silver leads with the metal, matching the wording the
    # commercial builder has always emitted for silver rows.
    if not has_purity:
        en_label = en_metal
    elif metal == "silver":
        en_label = f"{en_metal} {display_key}"
    elif metal == "steel":
        en_label = "Stainless Steel"
    else:
        en_label = f"{display_key} {en_metal}"

    return MaterialComponent(
        purity_key=key,
        metal=metal,
        has_purity=has_purity,
        purity_nominative_pl=nominative,
        purity_genitive_pl=genitive,
        purity_genitive_product_pl=genitive_product,
        metal_prepositional_pl=prepositional,
        short_code=short_code,
        en_metal=en_metal,
        en_label=en_label,
        pl_stem=_METAL_PL_STEM.get(metal, ""),
        display_key=display_key,
        purity_digits=_PURITY_DIGITS.get(key, ""),
    )


def _resolve_stone(raw: str) -> tuple:
    """Return ``(stone_abbr, stone_pl, natural_or_lab)`` for a raw row.

    Advisory only — the customs engine keeps its own stone extraction, which is
    byte-pinned by existing tests.  This is what the commercial side and the
    review flag consult.
    """
    stone_abbr = ""
    for key in _STONE_KEYS_BY_LENGTH:
        if _re.search(r"\b" + _re.escape(key) + r"\b", raw, _re.IGNORECASE):
            stone_abbr = key
            break

    stone_pl = STONE_ABBR.get(stone_abbr) if stone_abbr else None

    lab = bool(_LAB_GROWN_RE.search(raw))
    if lab:
        natural_or_lab = "lab_grown"
        if stone_pl in _DIAMOND_PL or stone_pl is None and stone_abbr in ("LGD", "LG", "LAB"):
            stone_pl = _LAB_DIAMOND_PL
    elif stone_pl in _DIAMOND_PL:
        natural_or_lab = "natural"
    else:
        natural_or_lab = None

    return stone_abbr, stone_pl, natural_or_lab


def parse_material_components(raw: str) -> ParsedMaterial:
    """Identify EVERY material stated in a raw source row.

    This is the single material authority.  It never guesses: a row whose
    materials cannot be resolved comes back with ``components == []`` and
    ``description_review_required=True`` rather than a manufactured metal.

    Rules:

    * ALL matches are kept, in source order — never first-match-wins.
    * A bare metal word is dropped only when the SAME metal also appears with
      a purity code ("SL925 Silver" is one silver component, not two).
    * Two spellings of the same próba collapse ("09KT" and "9KT").
    * Two metals with no ``Com`` marker keep BOTH components and raise the
      review flag — the ambiguity is surfaced, the material is not discarded.

    Examples::

        parse_material_components("PCS, 18KT Gold,LGD Stud PT950 Com ...")
            -> components ["18KT", "PT950"], construction "combination"
        parse_material_components("PCS, SILVER Plain 10kt Gold Com ...")
            -> components ["SILVER", "10KT"]   (no próba on the silver)
        parse_material_components("PCS, Fancy Jewell RING")
            -> components [], description_review_required=True
    """
    text = raw or ""

    matched: list = []
    for m in _ALL_PURITY_RE.finditer(text):
        key = m.group(1).upper()
        if key not in matched:
            matched.append(key)

    # A bare metal word next to the same metal's purity code is the same
    # material stated twice ("SL925 Silver"), not a second component.
    metals_with_purity = {
        _MATERIAL_METAL.get(k) for k in matched if k in GOLD_PURITY
    }
    matched = [
        k for k in matched
        if k in GOLD_PURITY or _MATERIAL_METAL.get(k) not in metals_with_purity
    ]

    components: list = []
    seen_identity: set = set()
    for key in matched:
        component = _build_component(key)
        # "9KT" and "09KT" resolve to the same próba — one material.
        identity = (component.metal, component.purity_nominative_pl)
        if identity in seen_identity:
            continue
        seen_identity.add(identity)
        components.append(component)

    stone_abbr, stone_pl, natural_or_lab = _resolve_stone(text)
    has_marker = bool(COMBINATION_RE.search(text))

    parsed = ParsedMaterial(
        components=components,
        construction="combination" if len(components) > 1 else "single",
        stone_abbr=stone_abbr,
        stone_pl=stone_pl,
        natural_or_lab=natural_or_lab,
    )

    if not components:
        parsed.description_review_required = True
        parsed.review_reason = REVIEW_NO_MATERIAL
    elif len(components) > 1 and not has_marker:
        # Both metals are kept.  The operator is told the source did not say
        # which construction it is.
        parsed.description_review_required = True
        parsed.review_reason = REVIEW_NO_COMBINATION_MARKER

    return parsed


def check_material_completeness(
    parsed: ParsedMaterial,
    description_pl: str,
    description_en: str,
) -> tuple:
    """The generation invariant: recognized source materials ⊆ final description.

    Returns ``(ok, reason)``.  ``ok`` is False when a material the source
    stated is absent from either language — that is a material fact removed by
    normalization, which is exactly what this campaign forbids.

    Checked at METAL level, not at próba level: a renderer that prints the
    wrong hallmark is a different (louder) defect, while a renderer that drops
    "platinum" from a gold+platinum piece is the silent one.  Callers that need
    próba parity use verify_description_parity() instead.

    A row with no recognized material cannot fail — nothing was recognized, so
    nothing could be lost; ``description_review_required`` covers that case.
    """
    if parsed is None or not parsed.components:
        return True, ""

    pl = (description_pl or "").lower()
    en = (description_en or "").lower()

    missing: list = []
    for c in parsed.components:
        label = f"{(c.en_metal or c.metal or c.purity_key).lower()} ({c.purity_key})"
        if c.pl_stem and c.pl_stem not in pl:
            missing.append(f"{label} missing from PL")
        if c.en_metal and c.en_metal.lower() not in en:
            missing.append(f"{label} missing from EN")

    if missing:
        return False, "material lost in normalization: " + "; ".join(missing)
    return True, ""
