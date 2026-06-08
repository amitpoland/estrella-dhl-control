"""
Migration B1 parity tests — verify new shared grammar forms reproduce
existing consumer vocabulary exactly.

These tests prove that:
  1. ITEM_TYPE_PL_PLURAL matches parser _PL_PLURAL_TYPE + aggregator _PL_PLURAL
  2. METAL_PREPOSITIONAL matches parser _METAL_TABLE PL columns
  3. metal_prepositional() returns correct forms for all purity keys
  4. stone_with_preposition() reproduces parser _STONE_RULES PL phrases
  5. stone_phrase_from_abbr() chains correctly through the full pipeline
  6. _prep_before() implements the parser/aggregator preposition convention
  7. Key-set consistency across all grammar dictionaries

NO consumer code is imported — this tests grammar module in isolation.
Consumer wiring is Migration B2 scope.
"""
from __future__ import annotations

import pytest

from description_grammar import (
    GENDER_SETTING_VERB,
    GOLD_PURITY,
    ITEM_TYPE_PL,
    ITEM_TYPE_PL_PLURAL,
    METAL_PREPOSITIONAL,
    PURITY_GENITIVE,
    STONE_ABBR,
    STONE_INSTRUMENTAL,
    _prep_before,
    metal_prepositional,
    stone_phrase_from_abbr,
    stone_with_preposition,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Section 1: ITEM_TYPE_PL_PLURAL parity with parser/aggregator
# ═══════════════════════════════════════════════════════════════════════════════

# Parser's _PL_PLURAL_TYPE (global_invoice_position_parser.py line 91)
_PARSER_PL_PLURAL_TYPE = {
    "RING":      "Pierścionki",
    "PENDANT":   "Wisiorki",
    "EARRING":   "Kolczyki",
    "EARRINGS":  "Kolczyki",
    "BRACELET":  "Bransoletki",
    "BANGLE":    "Bransoletki sztywne",
    "NECKLACE":  "Naszyjniki",
    "CHAIN":     "Łańcuszki",
    "CUFFLINK":  "Spinki do mankietów",
    "CUFFLINKS": "Spinki do mankietów",
}

# Aggregator's _PL_PLURAL (customs_position_aggregator.py line 66)
_AGGREGATOR_PL_PLURAL = {
    "RING":      "Pierścionki",
    "PENDANT":   "Wisiorki",
    "EARRING":   "Kolczyki",
    "EARRINGS":  "Kolczyki",
    "BRACELET":  "Bransoletki",
    "BANGLE":    "Bransoletki sztywne",
    "NECKLACE":  "Naszyjniki",
    "CHAIN":     "Łańcuszki",
    "CUFFLINK":  "Spinki do mankietów",
    "CUFFLINKS": "Spinki do mankietów",
}


class TestItemTypePlPluralParity:
    """ITEM_TYPE_PL_PLURAL must be a superset of parser + aggregator plurals."""

    def test_is_dict(self) -> None:
        assert isinstance(ITEM_TYPE_PL_PLURAL, dict)

    def test_not_empty(self) -> None:
        assert len(ITEM_TYPE_PL_PLURAL) >= 10

    def test_contains_all_parser_keys(self) -> None:
        """Every key in parser's _PL_PLURAL_TYPE must exist in shared grammar."""
        missing = set(_PARSER_PL_PLURAL_TYPE) - set(ITEM_TYPE_PL_PLURAL)
        assert not missing, f"Parser keys missing from ITEM_TYPE_PL_PLURAL: {missing}"

    def test_contains_all_aggregator_keys(self) -> None:
        """Every key in aggregator's _PL_PLURAL must exist in shared grammar."""
        missing = set(_AGGREGATOR_PL_PLURAL) - set(ITEM_TYPE_PL_PLURAL)
        assert not missing, f"Aggregator keys missing from ITEM_TYPE_PL_PLURAL: {missing}"

    @pytest.mark.parametrize("key,expected", list(_PARSER_PL_PLURAL_TYPE.items()))
    def test_parser_value_identity(self, key: str, expected: str) -> None:
        """Shared grammar value must be byte-identical to parser value."""
        assert ITEM_TYPE_PL_PLURAL[key] == expected

    @pytest.mark.parametrize("key,expected", list(_AGGREGATOR_PL_PLURAL.items()))
    def test_aggregator_value_identity(self, key: str, expected: str) -> None:
        """Shared grammar value must be byte-identical to aggregator value."""
        assert ITEM_TYPE_PL_PLURAL[key] == expected

    def test_keys_superset_of_singular(self) -> None:
        """ITEM_TYPE_PL_PLURAL must have at least all keys from ITEM_TYPE_PL."""
        missing = set(ITEM_TYPE_PL) - set(ITEM_TYPE_PL_PLURAL)
        assert not missing, f"Singular keys missing from plural: {missing}"

    def test_inherently_plural_items_match(self) -> None:
        """Items that are inherently plural in Polish should have same form."""
        for key in ("EARRINGS", "EARRING", "CUFFLINKS", "CUFFLINK"):
            assert ITEM_TYPE_PL[key] == ITEM_TYPE_PL_PLURAL[key], (
                f"{key}: singular={ITEM_TYPE_PL[key]!r} != plural={ITEM_TYPE_PL_PLURAL[key]!r}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2: METAL_PREPOSITIONAL parity with parser/packing metal tables
# ═══════════════════════════════════════════════════════════════════════════════

# Parser's _METAL_TABLE PL column (global_invoice_position_parser.py line 120)
_PARSER_METAL_TABLE_PL = {
    "925 PURITY SILVER": "ze srebra próby 925",
    "925 SILVER":        "ze srebra próby 925",
    "14KT GOLD":         "ze złota próby 585",
    "09KT GOLD":         "ze złota próby 375",
    "9KT GOLD":          "ze złota próby 375",
    "18KT GOLD":         "ze złota próby 750",
    "22KT GOLD":         "ze złota próby 916",
    "PT950":             "z platyny próby 950",
    "PT900":             "z platyny próby 900",
}

# Aggregator _PL_METAL_PATTERNS (customs_position_aggregator.py line 153)
_AGGREGATOR_METAL_PATTERNS = (
    "ze srebra próby 925",
    "ze złota próby 375",
    "ze złota próby 585",
    "ze złota próby 750",
    "ze złota próby 916",
    "z platyny próby 950",
    "z platyny próby 900",
)


class TestMetalPrepositionalParity:
    """METAL_PREPOSITIONAL must reproduce all metal phrases used by parser + aggregator."""

    def test_is_dict(self) -> None:
        assert isinstance(METAL_PREPOSITIONAL, dict)

    def test_not_empty(self) -> None:
        assert len(METAL_PREPOSITIONAL) >= 13

    def test_all_gold_purity_keys_present(self) -> None:
        """Every key in GOLD_PURITY must have a prepositional form."""
        missing = set(GOLD_PURITY) - set(METAL_PREPOSITIONAL)
        assert not missing, f"GOLD_PURITY keys missing from METAL_PREPOSITIONAL: {missing}"

    def test_parser_metal_values_covered(self) -> None:
        """Every PL phrase from parser's _METAL_TABLE must appear as a METAL_PREPOSITIONAL value."""
        shared_values = set(METAL_PREPOSITIONAL.values())
        for material_desc, pl_phrase in _PARSER_METAL_TABLE_PL.items():
            assert pl_phrase in shared_values, (
                f"Parser phrase {pl_phrase!r} (from {material_desc!r}) not in METAL_PREPOSITIONAL values"
            )

    def test_aggregator_metal_patterns_covered(self) -> None:
        """Every phrase from aggregator's _PL_METAL_PATTERNS must appear in METAL_PREPOSITIONAL values."""
        shared_values = set(METAL_PREPOSITIONAL.values())
        for pattern in _AGGREGATOR_METAL_PATTERNS:
            assert pattern in shared_values, (
                f"Aggregator pattern {pattern!r} not in METAL_PREPOSITIONAL values"
            )

    @pytest.mark.parametrize(
        "key,expected",
        [
            ("14KT", "ze złota próby 585"),
            ("9KT", "ze złota próby 375"),
            ("09KT", "ze złota próby 375"),
            ("18KT", "ze złota próby 750"),
            ("22KT", "ze złota próby 916"),
            ("24KT", "ze złota próby 999"),
            ("10KT", "ze złota próby 417"),
            ("925", "ze srebra próby 925"),
            ("SL925", "ze srebra próby 925"),
            ("SS", "ze stali szlachetnej"),
            ("PT950", "z platyny próby 950"),
            ("PT900", "z platyny próby 900"),
            ("PT850", "z platyny próby 850"),
        ],
    )
    def test_metal_prepositional_lookup(self, key: str, expected: str) -> None:
        """metal_prepositional() must return the exact phrase for each purity key."""
        assert metal_prepositional(key) == expected

    def test_metal_prepositional_unknown_key(self) -> None:
        """Unknown key returns empty string."""
        assert metal_prepositional("UNKNOWN") == ""
        assert metal_prepositional("") == ""

    def test_gold_uses_ze(self) -> None:
        """All gold entries must start with 'ze' (złota starts with z)."""
        for key in ("9KT", "09KT", "10KT", "14KT", "18KT", "22KT", "24KT"):
            assert METAL_PREPOSITIONAL[key].startswith("ze "), (
                f"Gold key {key!r}: expected 'ze ...' got {METAL_PREPOSITIONAL[key]!r}"
            )

    def test_silver_uses_ze(self) -> None:
        """Silver entries must start with 'ze' (srebra starts with s)."""
        for key in ("925", "SL925"):
            assert METAL_PREPOSITIONAL[key].startswith("ze "), (
                f"Silver key {key!r}: expected 'ze ...' got {METAL_PREPOSITIONAL[key]!r}"
            )

    def test_platinum_uses_z(self) -> None:
        """Platinum entries must start with 'z' (platyny starts with p)."""
        for key in ("PT950", "PT900", "PT850"):
            assert METAL_PREPOSITIONAL[key].startswith("z "), (
                f"Platinum key {key!r}: expected 'z ...' got {METAL_PREPOSITIONAL[key]!r}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3: _prep_before() preposition helper
# ═══════════════════════════════════════════════════════════════════════════════

class TestPrepBefore:
    """_prep_before() must use the parser/aggregator convention (broader than engine's _prep)."""

    @pytest.mark.parametrize(
        "word,expected",
        [
            # z-initial → "ze"
            ("złota", "ze"),
            ("źrenicami", "ze"),
            ("żelaza", "ze"),
            # s-initial → "ze"
            ("srebra", "ze"),
            ("stali", "ze"),
            ("ślimakami", "ze"),
            ("szmaragdami", "ze"),
            ("szafirami", "ze"),
            # w-initial → "ze"
            ("wolframu", "ze"),
            # p-initial → "z"
            ("platyny", "z"),
            ("perłami", "z"),
            # d-initial → "z"
            ("diamentami", "z"),
            # c-initial → "z"
            ("cyrkoniami", "z"),
            # k-initial → "z"
            ("kamieniami", "z"),
            # r-initial → "z"
            ("rubinami", "z"),
            # m-initial → "z"
            ("moissanitem", "z"),
        ],
    )
    def test_preposition_choice(self, word: str, expected: str) -> None:
        assert _prep_before(word) == expected

    def test_empty_string(self) -> None:
        assert _prep_before("") == "z"

    def test_none_returns_z(self) -> None:
        # None is technically not str but helper should handle gracefully
        assert _prep_before(None) == "z"  # type: ignore[arg-type]

    def test_whitespace_prefix(self) -> None:
        """Leading whitespace should be stripped before checking first char."""
        assert _prep_before("  złota") == "ze"
        assert _prep_before("  platyny") == "z"

    def test_case_insensitive(self) -> None:
        """Helper should be case-insensitive."""
        assert _prep_before("Złota") == "ze"
        assert _prep_before("Srebra") == "ze"
        assert _prep_before("Platyny") == "z"


# ═══════════════════════════════════════════════════════════════════════════════
# Section 4: stone_with_preposition() parity with parser stone phrases
# ═══════════════════════════════════════════════════════════════════════════════

# Parser's _STONE_RULES PL column (global_invoice_position_parser.py line 154)
_PARSER_STONE_PL = {
    "diamentami laboratoryjnymi":           "z diamentami laboratoryjnymi",
    "cyrkoniami i kamieniami kolorowymi":   "z cyrkoniami i kamieniami kolorowymi",
    "diamentami i cyrkoniami":              "z diamentami i cyrkoniami",
    "cyrkoniami":                           "z cyrkoniami",
    "diamentami":                           "z diamentami",
    "kamieniami kolorowymi":                "z kamieniami kolorowymi",
}


class TestStoneWithPreposition:
    """stone_with_preposition() must reproduce parser _STONE_RULES PL phrases."""

    @pytest.mark.parametrize(
        "instrumental,expected",
        list(_PARSER_STONE_PL.items()),
    )
    def test_parser_stone_phrases(self, instrumental: str, expected: str) -> None:
        """Each parser stone phrase must be reproduced exactly."""
        assert stone_with_preposition(instrumental) == expected

    @pytest.mark.parametrize(
        "instrumental,expected",
        [
            ("diamentami", "z diamentami"),
            ("diamentami i kamieniami szlachetnymi", "z diamentami i kamieniami szlachetnymi"),
            ("kamieniami szlachetnymi", "z kamieniami szlachetnymi"),
            ("kamieniami jubilerskimi", "z kamieniami jubilerskimi"),
            ("kamieniami ozdobnymi", "z kamieniami ozdobnymi"),
            ("diamentami laboratoryjnymi", "z diamentami laboratoryjnymi"),
            ("cyrkoniami", "z cyrkoniami"),
            ("rubinami", "z rubinami"),
            ("szmaragdami", "ze szmaragdami"),
            ("szafirami", "ze szafirami"),
            ("perłami", "z perłami"),
            ("moissanitem", "z moissanitem"),
        ],
    )
    def test_all_stone_instrumentals(self, instrumental: str, expected: str) -> None:
        """Every STONE_INSTRUMENTAL value must produce a valid prepositional phrase."""
        assert stone_with_preposition(instrumental) == expected

    def test_empty_string(self) -> None:
        assert stone_with_preposition("") == ""

    def test_whitespace_only(self) -> None:
        assert stone_with_preposition("   ") == ""

    def test_strips_whitespace(self) -> None:
        assert stone_with_preposition("  diamentami  ") == "z diamentami"


# ═══════════════════════════════════════════════════════════════════════════════
# Section 5: stone_phrase_from_abbr() full chain
# ═══════════════════════════════════════════════════════════════════════════════

class TestStonePhraseFromAbbr:
    """stone_phrase_from_abbr() chains STONE_ABBR → STONE_INSTRUMENTAL → preposition."""

    @pytest.mark.parametrize(
        "abbr,expected",
        [
            ("DIA", "z diamentami"),
            ("DIAM", "z diamentami"),
            ("DIA&CLS", "z diamentami i kamieniami szlachetnymi"),
            ("CLS", "z kamieniami szlachetnymi"),
            ("LGD", "z diamentami laboratoryjnymi"),
            ("LG", "z diamentami laboratoryjnymi"),
            ("LAB", "z diamentami laboratoryjnymi"),
            ("CZ", "z cyrkoniami"),
            ("CUBIC", "z cyrkoniami"),
            ("RUBY", "z rubinami"),
            ("EMERALD", "ze szmaragdami"),
            ("SAPPHIRE", "ze szafirami"),
            ("PEARL", "z perłami"),
            ("MOISS", "z moissanitem"),
        ],
    )
    def test_known_abbreviations(self, abbr: str, expected: str) -> None:
        assert stone_phrase_from_abbr(abbr) == expected

    def test_plain_returns_empty(self) -> None:
        """PLAIN means no stones — must return empty string."""
        assert stone_phrase_from_abbr("PLAIN") == ""

    def test_unknown_returns_empty(self) -> None:
        assert stone_phrase_from_abbr("UNKNOWN") == ""
        assert stone_phrase_from_abbr("") == ""

    def test_chains_match_direct_preposition(self) -> None:
        """For every abbreviation with a known stone, chained result must equal
        stone_with_preposition applied to the instrumental form directly."""
        for abbr, nominative in STONE_ABBR.items():
            if nominative is None:
                continue
            instrumental = STONE_INSTRUMENTAL.get(nominative)
            if instrumental is None:
                continue
            chained = stone_phrase_from_abbr(abbr)
            direct = stone_with_preposition(instrumental)
            assert chained == direct, (
                f"Abbr {abbr!r}: chained={chained!r} != direct={direct!r}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Section 6: Cross-dictionary key consistency
# ═══════════════════════════════════════════════════════════════════════════════

class TestCrossDictionaryConsistency:
    """Verify key-set alignment across all grammar dictionaries."""

    def test_gold_purity_keys_match_purity_genitive(self) -> None:
        """GOLD_PURITY and PURITY_GENITIVE must have identical key sets."""
        assert set(GOLD_PURITY) == set(PURITY_GENITIVE)

    def test_gold_purity_keys_match_metal_prepositional(self) -> None:
        """GOLD_PURITY and METAL_PREPOSITIONAL must have identical key sets."""
        assert set(GOLD_PURITY) == set(METAL_PREPOSITIONAL)

    def test_item_type_keys_match_plural(self) -> None:
        """ITEM_TYPE_PL and ITEM_TYPE_PL_PLURAL must have identical key sets."""
        assert set(ITEM_TYPE_PL) == set(ITEM_TYPE_PL_PLURAL)

    def test_gender_verb_values_subset_of_singular(self) -> None:
        """Every key in GENDER_SETTING_VERB must be a VALUE in ITEM_TYPE_PL."""
        singular_values = set(ITEM_TYPE_PL.values())
        for noun in GENDER_SETTING_VERB:
            assert noun in singular_values, (
                f"GENDER_SETTING_VERB key {noun!r} not found in ITEM_TYPE_PL values"
            )

    def test_all_purity_forms_have_same_proby_number(self) -> None:
        """For each purity key, the próby number must be consistent across dictionaries."""
        import re
        proby_re = re.compile(r"próby?\s+(\d+)")
        for key in GOLD_PURITY:
            forms = {
                "GOLD_PURITY": GOLD_PURITY[key],
                "PURITY_GENITIVE": PURITY_GENITIVE[key],
                "METAL_PREPOSITIONAL": METAL_PREPOSITIONAL[key],
            }
            numbers = {}
            for dict_name, form in forms.items():
                m = proby_re.search(form)
                if m:
                    numbers[dict_name] = m.group(1)
            # All found numbers must be the same
            unique = set(numbers.values())
            if len(unique) > 1:
                pytest.fail(
                    f"Key {key!r}: próby number mismatch across forms: {numbers}"
                )


# ═══════════════════════════════════════════════════════════════════════════════
# Section 7: Non-regression — existing Phase 1 dictionaries unchanged
# ═══════════════════════════════════════════════════════════════════════════════

class TestPhase1DictionariesUnchanged:
    """Migration B1 must NOT modify any Phase 1 dictionary."""

    def test_item_type_pl_count(self) -> None:
        """ITEM_TYPE_PL must have exactly 15 entries (Phase 1 count)."""
        assert len(ITEM_TYPE_PL) == 15

    def test_gold_purity_count(self) -> None:
        """GOLD_PURITY must have exactly 13 entries (Phase 1 count)."""
        assert len(GOLD_PURITY) == 13

    def test_purity_genitive_count(self) -> None:
        """PURITY_GENITIVE must have exactly 13 entries (Phase 1 count)."""
        assert len(PURITY_GENITIVE) == 13

    def test_stone_instrumental_count(self) -> None:
        """STONE_INSTRUMENTAL must have exactly 13 entries (Phase 1 count)."""
        assert len(STONE_INSTRUMENTAL) == 13

    def test_gender_setting_verb_count(self) -> None:
        """GENDER_SETTING_VERB must have exactly 13 entries (Phase 1 count)."""
        assert len(GENDER_SETTING_VERB) == 13

    def test_stone_abbr_count(self) -> None:
        """STONE_ABBR must have exactly 15 entries (Phase 1 count)."""
        assert len(STONE_ABBR) == 15

    def test_ring_singular_unchanged(self) -> None:
        assert ITEM_TYPE_PL["RING"] == "Pierścionek"

    def test_14kt_nominative_unchanged(self) -> None:
        assert GOLD_PURITY["14KT"] == "złoto próby 585"

    def test_14kt_genitive_unchanged(self) -> None:
        assert PURITY_GENITIVE["14KT"] == "14-karatowego złota (próba 585)"

    def test_diamond_instrumental_unchanged(self) -> None:
        assert STONE_INSTRUMENTAL["diamenty"] == "diamentami"

    def test_ring_setting_verb_unchanged(self) -> None:
        assert GENDER_SETTING_VERB["Pierścionek"] == "wysadzany"

    def test_dia_abbr_unchanged(self) -> None:
        assert STONE_ABBR["DIA"] == "diamenty"

    def test_plain_abbr_unchanged(self) -> None:
        assert STONE_ABBR["PLAIN"] is None
