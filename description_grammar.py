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

Origin: Migration A of the Description Engine Phase 2 campaign.
Phase 1 (PR #509, SHA 9c1c9df, 2026-06-08) upgraded the root engine grammar.
This module extracts those dictionaries so they can be shared.
"""
from __future__ import annotations

from typing import Optional


# ── Item type → Polish name (singular, title case) ───────────────────────────
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

# ── Gold/silver/platinum purity → Polish name (nominative) ───────────────────
# Used in field displays: "złoto próby 585"
# Generic SILVER and PLATINUM entries removed: word alone carries no próby →
# falls to "metal szlachetny" → checker creates Inbox proposal.
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
# Masculine → wysadzany, Feminine → wysadzana, Plural → wysadzane
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

# ── Stone abbreviations → Polish stone name (None = no stones) ───────────────
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
