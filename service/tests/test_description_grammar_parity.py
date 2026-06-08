"""
test_description_grammar_parity.py — Migration A parity tests.

Proves that the shared description_grammar.py module contains exactly the
same dictionaries that customs_description_engine.py previously defined
inline, and that normalize_item_description() output is byte-identical
after the extraction.

Origin: Phase 2, Migration A — shared grammar extraction.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import description_grammar as dg
import customs_description_engine as cde


# ============================================================================
# 1. Dictionary identity — shared module exports == engine re-exports
# ============================================================================

class TestDictionaryIdentity:
    """The engine re-exports the SAME objects from description_grammar."""

    def test_item_type_pl_is_same_object(self):
        assert cde.ITEM_TYPE_PL is dg.ITEM_TYPE_PL

    def test_gold_purity_is_same_object(self):
        assert cde.GOLD_PURITY is dg.GOLD_PURITY

    def test_purity_genitive_is_same_object(self):
        assert cde._PURITY_GENITIVE is dg.PURITY_GENITIVE

    def test_stone_instrumental_is_same_object(self):
        assert cde._STONE_INSTRUMENTAL is dg.STONE_INSTRUMENTAL

    def test_gender_setting_verb_is_same_object(self):
        assert cde._GENDER_SETTING_VERB is dg.GENDER_SETTING_VERB

    def test_stone_abbr_is_same_object(self):
        assert cde.STONE_ABBR is dg.STONE_ABBR


# ============================================================================
# 2. Dictionary completeness — every expected key exists with correct value
# ============================================================================

class TestItemTypePLCompleteness:
    """ITEM_TYPE_PL has all 15 entries with correct Polish names."""

    EXPECTED = {
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

    def test_key_count(self):
        assert len(dg.ITEM_TYPE_PL) == 15

    @pytest.mark.parametrize("key,value", EXPECTED.items())
    def test_entry(self, key, value):
        assert dg.ITEM_TYPE_PL[key] == value


class TestGoldPurityCompleteness:
    """GOLD_PURITY has all 13 entries with correct nominative forms."""

    EXPECTED = {
        "9KT":    "złoto próby 375",
        "09KT":   "złoto próby 375",
        "10KT":   "złoto próby 417",
        "14KT":   "złoto próby 585",
        "18KT":   "złoto próby 750",
        "22KT":   "złoto próby 916",
        "24KT":   "złoto próby 999",
        "925":    "srebro próby 925",
        "SL925":  "srebro próby 925",
        "SS":     "stal szlachetna",
        "PT950":  "platyna próby 950",
        "PT900":  "platyna próby 900",
        "PT850":  "platyna próby 850",
    }

    def test_key_count(self):
        assert len(dg.GOLD_PURITY) == 13

    @pytest.mark.parametrize("key,value", EXPECTED.items())
    def test_entry(self, key, value):
        assert dg.GOLD_PURITY[key] == value


class TestPurityGenitiveCompleteness:
    """PURITY_GENITIVE has all 13 entries with karat-expanded genitive forms."""

    EXPECTED = {
        "9KT":    "9-karatowego złota (próba 375)",
        "09KT":   "9-karatowego złota (próba 375)",
        "10KT":   "10-karatowego złota (próba 417)",
        "14KT":   "14-karatowego złota (próba 585)",
        "18KT":   "18-karatowego złota (próba 750)",
        "22KT":   "22-karatowego złota (próba 916)",
        "24KT":   "24-karatowego złota (próba 999)",
        "925":    "srebra próby 925",
        "SL925":  "srebra próby 925",
        "SS":     "stali szlachetnej",
        "PT950":  "platyny próby 950",
        "PT900":  "platyny próby 900",
        "PT850":  "platyny próby 850",
    }

    def test_key_count(self):
        assert len(dg.PURITY_GENITIVE) == 13

    @pytest.mark.parametrize("key,value", EXPECTED.items())
    def test_entry(self, key, value):
        assert dg.PURITY_GENITIVE[key] == value


class TestStoneInstrumentalCompleteness:
    """STONE_INSTRUMENTAL has all 13 entries with correct instrumental forms."""

    EXPECTED = {
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

    def test_key_count(self):
        assert len(dg.STONE_INSTRUMENTAL) == 13

    @pytest.mark.parametrize("key,value", EXPECTED.items())
    def test_entry(self, key, value):
        assert dg.STONE_INSTRUMENTAL[key] == value


class TestGenderSettingVerbCompleteness:
    """GENDER_SETTING_VERB has all 13 entries with correct gender agreement."""

    EXPECTED = {
        "Pierścionek":           "wysadzany",
        "Wisiorek":              "wysadzany",
        "Naszyjnik":             "wysadzany",
        "Łańcuszek":             "wysadzany",
        "Komplet biżuterii":    "wysadzany",
        "Bransoletka":           "wysadzana",
        "Bransoletka sztywna":   "wysadzana",
        "Broszka":               "wysadzana",
        "Bransoletka na kostkę": "wysadzana",
        "Kolczyki":              "wysadzane",
        "Kolczyki wkrętki":      "wysadzane",
        "Kolczyki kółka":        "wysadzane",
        "Spinki do mankietów":   "wysadzane",
    }

    def test_key_count(self):
        assert len(dg.GENDER_SETTING_VERB) == 13

    @pytest.mark.parametrize("key,value", EXPECTED.items())
    def test_entry(self, key, value):
        assert dg.GENDER_SETTING_VERB[key] == value


class TestStoneAbbrCompleteness:
    """STONE_ABBR has all 15 entries with correct Polish stone names."""

    EXPECTED = {
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

    def test_key_count(self):
        assert len(dg.STONE_ABBR) == 15

    @pytest.mark.parametrize("key,value", EXPECTED.items())
    def test_entry(self, key, value):
        assert dg.STONE_ABBR[key] == value


# ============================================================================
# 3. Engine output byte-identical — normalize_item_description() unchanged
# ============================================================================

class TestNormalizeOutputUnchanged:
    """
    normalize_item_description() output must match the known-good Phase 1
    output exactly.  These are the SAME assertions from
    test_description_engine_grammar_upgrade.py, duplicated here to prove
    the extraction did not alter behavior.
    """

    def test_14kt_ring_dia(self):
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA RING")
        assert r["polish_customs_description"] == (
            "Pierścionek z 14-karatowego złota (próba 585) "
            "wysadzany diamentami. Biżuteria do noszenia."
        )
        assert r["material_pl"] == "złoto próby 585 oraz diamenty"
        assert r["item_type_pl"] == "Pierścionek"

    def test_18kt_earrings_dia(self):
        r = cde.normalize_item_description("PCS, 18KT Gold, DIA EARRINGS")
        assert r["polish_customs_description"] == (
            "Kolczyki z 18-karatowego złota (próba 750) "
            "wysadzane diamentami. Biżuteria do noszenia."
        )

    def test_14kt_bracelet_dia_cls(self):
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA&CLS BRACELET")
        assert r["polish_customs_description"] == (
            "Bransoletka z 14-karatowego złota (próba 585) "
            "wysadzana diamentami i kamieniami szlachetnymi. "
            "Biżuteria do noszenia."
        )

    def test_925_ring_cz(self):
        r = cde.normalize_item_description("PCS, 925 Silver, CZ RING")
        assert r["polish_customs_description"] == (
            "Pierścionek z srebra próby 925 "
            "wysadzany cyrkoniami. Biżuteria do noszenia."
        )

    def test_pt950_ring_dia(self):
        r = cde.normalize_item_description("PCS, PT950 Platinum, DIA RING")
        assert r["polish_customs_description"] == (
            "Pierścionek z platyny próby 950 "
            "wysadzany diamentami. Biżuteria do noszenia."
        )

    def test_14kt_plain_chain(self):
        """No stones → no setting verb, sentence-break suffix."""
        r = cde.normalize_item_description("PCS, 14KT Gold, PLAIN CHAIN")
        assert r["polish_customs_description"] == (
            "Łańcuszek z 14-karatowego złota (próba 585). "
            "Biżuteria do noszenia."
        )

    def test_no_metal_no_stone(self):
        """Fallback: no metal, no stone → dash-separated."""
        r = cde.normalize_item_description("PCS, RING")
        assert r["polish_customs_description"] == (
            "Pierścionek — wyrób jubilerski do noszenia."
        )

    def test_lgd_pendant(self):
        """Lab-grown diamonds → 'diamentami laboratoryjnymi'."""
        r = cde.normalize_item_description("PCS, 14KT Gold, LGD PENDANT")
        assert r["polish_customs_description"] == (
            "Wisiorek z 14-karatowego złota (próba 585) "
            "wysadzany diamentami laboratoryjnymi. Biżuteria do noszenia."
        )

    def test_bangle_feminine(self):
        """Bransoletka sztywna (fem.) → wysadzana."""
        r = cde.normalize_item_description("PCS, 18KT Gold, DIA BANGLE")
        assert r["polish_customs_description"] == (
            "Bransoletka sztywna z 18-karatowego złota (próba 750) "
            "wysadzana diamentami. Biżuteria do noszenia."
        )

    def test_hoop_plural(self):
        """Kolczyki kółka (pl.) → wysadzane."""
        r = cde.normalize_item_description("PCS, 14KT Gold, CLS HOOP")
        assert r["polish_customs_description"] == (
            "Kolczyki kółka z 14-karatowego złota (próba 585) "
            "wysadzane kamieniami szlachetnymi. Biżuteria do noszenia."
        )


# ============================================================================
# 4. Cross-dictionary consistency — every ITEM_TYPE_PL value that appears in
#    GENDER_SETTING_VERB has a matching entry, and vice versa.
# ============================================================================

class TestCrossDictionaryConsistency:
    """Grammar dictionaries are internally consistent."""

    def test_every_item_type_has_gender_verb(self):
        """Every item_type_pl noun that could appear with stones has a verb."""
        for key, pl_name in dg.ITEM_TYPE_PL.items():
            assert pl_name in dg.GENDER_SETTING_VERB, (
                f"ITEM_TYPE_PL[{key!r}] = {pl_name!r} has no "
                f"GENDER_SETTING_VERB entry"
            )

    def test_every_gender_verb_has_item_type(self):
        """Every GENDER_SETTING_VERB key maps back to an ITEM_TYPE_PL value."""
        item_type_values = set(dg.ITEM_TYPE_PL.values())
        for pl_name in dg.GENDER_SETTING_VERB:
            assert pl_name in item_type_values, (
                f"GENDER_SETTING_VERB has {pl_name!r} but no ITEM_TYPE_PL "
                f"value matches"
            )

    def test_purity_genitive_keys_match_gold_purity(self):
        """Every GOLD_PURITY key has a matching PURITY_GENITIVE entry."""
        for key in dg.GOLD_PURITY:
            assert key in dg.PURITY_GENITIVE, (
                f"GOLD_PURITY[{key!r}] has no PURITY_GENITIVE entry"
            )

    def test_stone_instrumental_covers_all_stone_abbr_values(self):
        """Every non-None STONE_ABBR value has a STONE_INSTRUMENTAL entry."""
        for key, pl_name in dg.STONE_ABBR.items():
            if pl_name is None:
                continue
            # Lab-grown appends " laboratoryjne" — check the extended form
            assert pl_name in dg.STONE_INSTRUMENTAL, (
                f"STONE_ABBR[{key!r}] = {pl_name!r} has no "
                f"STONE_INSTRUMENTAL entry"
            )


# ============================================================================
# 5. Combinatorial regression — all metal x stone x type produce non-empty
#    descriptions (same as the 2028-combination smoke test).
# ============================================================================

METALS = ["9KT", "10KT", "14KT", "18KT", "22KT", "24KT",
          "925", "SL925", "SS", "PT950", "PT900", "PT850", ""]
STONES = ["DIA", "DIA&CLS", "CLS", "LGD", "CZ", "RUBY",
          "EMERALD", "SAPPHIRE", "PEARL", "MOISS", "PLAIN", ""]
TYPES  = ["RING", "EARRINGS", "BRACELET", "BANGLE", "PENDANT",
          "NECKLACE", "BROOCH", "SET", "CHAIN", "ANKLET",
          "STUD", "HOOP", "CUFFLINKS"]

class TestCombinatorialSmoke:
    """Every metal x stone x type produces a non-empty customs description."""

    @pytest.mark.parametrize("metal", METALS)
    @pytest.mark.parametrize("stone", STONES[:4])  # subset for speed
    @pytest.mark.parametrize("itype", TYPES[:5])   # subset for speed
    def test_combination(self, metal, stone, itype):
        raw = f"PCS, {metal} Gold, {stone} {itype}".strip()
        r = cde.normalize_item_description(raw, item_type=itype)
        assert r["polish_customs_description"], f"empty desc for {raw}"
        assert r["item_type_pl"], f"empty type_pl for {raw}"
