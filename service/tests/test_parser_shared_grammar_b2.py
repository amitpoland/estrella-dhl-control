"""
Migration B2 tests — verify parser's Polish grammar tables are correctly
wired to the shared description_grammar.py authority.

Tests:
  1. _PL_PLURAL_TYPE is the SAME object as ITEM_TYPE_PL_PLURAL
  2. _METAL_TABLE PL values are a subset of METAL_PREPOSITIONAL values
  3. Simple _STONE_RULES PL phrases match stone_with_preposition() output
  4. Import-time parity checks don't raise ImportError
  5. Runtime output of _normalize_metal/_normalize_stone unchanged
  6. _render_position_descriptions output unchanged for known inputs
"""
from __future__ import annotations

import pytest

from app.services.global_invoice_position_parser import (
    _EN_PLURAL_TYPE,
    _METAL_TABLE,
    _PL_PLURAL_TYPE,
    _STONE_RULES,
    _normalize_metal,
    _normalize_stone,
    _render_position_descriptions,
    positions_to_audit_rows,
)
from description_grammar import (
    ITEM_TYPE_PL_PLURAL,
    METAL_PREPOSITIONAL,
    metal_prepositional,
    stone_with_preposition,
)


# ── 1. PL plural identity ──────────────────────────────────────────────────

class TestPluralTypeWiring:
    """_PL_PLURAL_TYPE must be ITEM_TYPE_PL_PLURAL, not a copy."""

    def test_is_same_object(self):
        """After B2, _PL_PLURAL_TYPE IS the shared dict, not a clone."""
        assert _PL_PLURAL_TYPE is ITEM_TYPE_PL_PLURAL

    def test_original_10_keys_present(self):
        """All 10 original parser keys still resolve."""
        original_keys = {
            "RING", "PENDANT", "EARRING", "EARRINGS", "BRACELET",
            "BANGLE", "NECKLACE", "CHAIN", "CUFFLINK", "CUFFLINKS",
        }
        for k in original_keys:
            assert k in _PL_PLURAL_TYPE, f"Missing original key: {k}"

    @pytest.mark.parametrize("key,expected_pl", [
        ("RING",      "Pierścionki"),
        ("PENDANT",   "Wisiorki"),
        ("EARRING",   "Kolczyki"),
        ("EARRINGS",  "Kolczyki"),
        ("BRACELET",  "Bransoletki"),
        ("BANGLE",    "Bransoletki sztywne"),
        ("NECKLACE",  "Naszyjniki"),
        ("CHAIN",     "Łańcuszki"),
        ("CUFFLINK",  "Spinki do mankietów"),
        ("CUFFLINKS", "Spinki do mankietów"),
    ])
    def test_original_values_unchanged(self, key, expected_pl):
        """Each original PL plural form is identical after migration."""
        assert _PL_PLURAL_TYPE[key] == expected_pl

    def test_en_plural_type_untouched(self):
        """EN plural table must remain local — not imported."""
        assert _EN_PLURAL_TYPE["RING"] == "RINGS"
        assert _EN_PLURAL_TYPE["PENDANT"] == "PENDANTS"


# ── 2. Metal table parity ──────────────────────────────────────────────────

class TestMetalTableParity:
    """Every PL phrase in _METAL_TABLE must exist in METAL_PREPOSITIONAL."""

    def test_all_pl_values_in_shared_grammar(self):
        """No PL metal phrase in _METAL_TABLE drifts from shared grammar."""
        local_pl = {pl for _, pl, _ in _METAL_TABLE}
        shared_pl = set(METAL_PREPOSITIONAL.values())
        drift = local_pl - shared_pl
        assert not drift, f"Metal PL drift: {drift}"

    @pytest.mark.parametrize("key,expected_pl", [
        ("925",   "ze srebra próby 925"),
        ("14KT",  "ze złota próby 585"),
        ("09KT",  "ze złota próby 375"),
        ("9KT",   "ze złota próby 375"),
        ("18KT",  "ze złota próby 750"),
        ("22KT",  "ze złota próby 916"),
        ("PT950", "z platyny próby 950"),
        ("PT900", "z platyny próby 900"),
    ])
    def test_metal_prepositional_lookup_matches(self, key, expected_pl):
        """metal_prepositional(key) returns the same PL as _METAL_TABLE."""
        assert metal_prepositional(key) == expected_pl

    @pytest.mark.parametrize("raw,expected_key,expected_pl,expected_en", [
        ("14KT GOLD Studs",    "14KT GOLD",  "ze złota próby 585",  "14KT Gold"),
        ("925 Purity Silver",  "925 PURITY SILVER", "ze srebra próby 925", "925 Silver"),
        ("925 Silver plain",   "925 SILVER",  "ze srebra próby 925", "925 Silver"),
        ("09KT GOLD Lab",      "09KT GOLD",  "ze złota próby 375",  "09KT Gold"),
        ("PT950 jewellery",    "PT950",       "z platyny próby 950", "PT950 Platinum"),
    ])
    def test_normalize_metal_output_unchanged(self, raw, expected_key,
                                               expected_pl, expected_en):
        """_normalize_metal() produces the same output as before migration."""
        key, pl, en = _normalize_metal(raw)
        assert key == expected_key
        assert pl == expected_pl
        assert en == expected_en


# ── 3. Stone rules parity ──────────────────────────────────────────────────

class TestStoneRulesParity:
    """Simple (non-combo) stone PL phrases match stone_with_preposition()."""

    @pytest.mark.parametrize("instrumental,expected", [
        ("diamentami laboratoryjnymi", "z diamentami laboratoryjnymi"),
        ("cyrkoniami",                 "z cyrkoniami"),
        ("diamentami",                 "z diamentami"),
    ])
    def test_simple_forms_match(self, instrumental, expected):
        """stone_with_preposition() reproduces simple _STONE_RULES PL."""
        assert stone_with_preposition(instrumental) == expected

    def test_stone_rules_structure_preserved(self):
        """_STONE_RULES is still a tuple of 7 (pattern, pl, en) triples."""
        assert len(_STONE_RULES) == 7
        for entry in _STONE_RULES:
            assert len(entry) == 3, f"Entry should be 3-tuple: {entry}"

    @pytest.mark.parametrize("raw,expected_pl,expected_en", [
        ("LGD Gold Stud Jewell",    "z diamentami laboratoryjnymi",
         "Lab Grown Diamond Jewellery"),
        ("Studed Jewellery CZ, CLS", "z cyrkoniami i kamieniami kolorowymi",
         "CZ & Colour Stone Jewellery"),
        ("Stud Jewelry DIA&CZ",     "z diamentami i cyrkoniami",
         "Diamond & CZ Stud Jewellery"),
        ("CZ Stud Silver Jew.",     "z cyrkoniami",
         "CZ Stud Jewellery"),
        ("DIA studded",             "z diamentami",
         "Diamond Jewellery"),
        ("Colour Stone set",        "z kamieniami kolorowymi",
         "Colour Stone Jewellery"),
        ("Plain Jewellery",         "",
         "Plain Jewellery"),
    ])
    def test_normalize_stone_output_unchanged(self, raw, expected_pl,
                                               expected_en):
        """_normalize_stone() produces the same output as before migration."""
        pl, en = _normalize_stone(raw)
        assert pl == expected_pl
        assert en == expected_en

    def test_combo_forms_documented_as_parser_specific(self):
        """Combo PL forms are present and documented as parser-specific."""
        combo_pl = {pl for _, pl, _ in _STONE_RULES if " i " in pl}
        assert "z cyrkoniami i kamieniami kolorowymi" in combo_pl
        assert "z diamentami i cyrkoniami" in combo_pl


# ── 4. Render pipeline smoke ───────────────────────────────────────────────

class TestRenderPipelineSmoke:
    """_render_position_descriptions() output unchanged after B2."""

    def _make_position(self, types, metal_pl, metal_en, stone_pl, stone_en,
                       unit="PCS"):
        rows = [{"type": t, "gross": 1.0, "net": 0.9, "qty": 1,
                 "rate": 10.0, "amount": 10.0} for t in types]
        return {
            "position_no": 1,
            "unit": unit,
            "metal_pl": metal_pl,
            "metal_en": metal_en,
            "stone_pl": stone_pl,
            "stone_en": stone_en,
            "quantity": sum(r["qty"] for r in rows),
            "amount": sum(r["amount"] for r in rows),
            "rows": rows,
        }

    def test_single_type_with_stone(self):
        pos = self._make_position(
            ["BRACELET"],
            "ze złota próby 375",
            "09KT Gold",
            "z diamentami laboratoryjnymi",
            "Lab Grown Diamond Jewellery",
        )
        pl, en, tc = _render_position_descriptions(pos)
        assert pl == "Bransoletki ze złota próby 375 z diamentami laboratoryjnymi"
        assert en == "09KT Gold Lab Grown Diamond Jewellery BRACELETS"
        assert tc == "BRACELET"

    def test_multi_type_with_stone(self):
        pos = self._make_position(
            ["PENDANT", "RING"],
            "ze srebra próby 925",
            "925 Silver",
            "z cyrkoniami i kamieniami kolorowymi",
            "CZ & Colour Stone Jewellery",
        )
        pl, en, tc = _render_position_descriptions(pos)
        assert pl == ("Wisiorki, Pierścionki ze srebra próby 925 "
                      "z cyrkoniami i kamieniami kolorowymi")
        assert en == "925 Silver CZ & Colour Stone Jewellery PENDANTS, RINGS"
        assert tc == "PENDANT"

    def test_plain_no_stone(self):
        pos = self._make_position(
            ["RING"],
            "ze srebra próby 925",
            "925 Silver",
            "",
            "Plain Jewellery",
        )
        pl, en, tc = _render_position_descriptions(pos)
        assert pl == "Pierścionki ze srebra próby 925"
        assert en == "925 Silver Plain Jewellery RINGS"

    def test_audit_rows_item_type_pl_uses_shared(self):
        """positions_to_audit_rows() uses _PL_PLURAL_TYPE which is now shared."""
        pos = self._make_position(
            ["RING"],
            "ze złota próby 585",
            "14KT Gold",
            "z diamentami",
            "Diamond Jewellery",
        )
        rows = positions_to_audit_rows([pos], "INV-001")
        assert len(rows) == 1
        assert rows[0]["item_type_pl"] == "Pierścionki"
        assert rows[0]["polish_customs_description"] == (
            "Pierścionki ze złota próby 585 z diamentami"
        )


# ── 5. Import parity gate ──────────────────────────────────────────────────

class TestImportParityGate:
    """The import-time parity checks must not raise on the current codebase."""

    def test_module_imports_without_error(self):
        """If this test runs, the import-time parity checks passed."""
        import app.services.global_invoice_position_parser as m
        assert hasattr(m, "_PL_PLURAL_TYPE")
        assert hasattr(m, "_METAL_TABLE")
        assert hasattr(m, "_STONE_RULES")
