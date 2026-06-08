"""
Migration B3 tests — verify aggregator's Polish grammar tables are correctly
wired to the shared description_grammar.py authority.

Tests:
  1. _PL_PLURAL is the SAME object as ITEM_TYPE_PL_PLURAL
  2. _PL_METAL_PATTERNS are a subset of METAL_PREPOSITIONAL values
  3. _PL_STONE_PATTERNS document OLD "wysadzany" + NEW "z" duality
  4. Import-time parity checks don't raise ImportError
  5. Aggregation output unchanged for known inputs
  6. _pl_plural() fallback behavior preserved
"""
from __future__ import annotations

import pytest

from app.services.customs_position_aggregator import (
    _EN_PLURAL,
    _PL_METAL_PATTERNS,
    _PL_PLURAL,
    _PL_STONE_PATTERNS,
    _EN_STONE_PATTERNS,
    _extract_pl_metal,
    _extract_pl_stone,
    _extract_en_stone,
    _pl_plural,
    _en_plural,
    aggregate_packing_rows_to_invoice_positions,
)
from description_grammar import (
    ITEM_TYPE_PL_PLURAL,
    METAL_PREPOSITIONAL,
)


# ── 1. PL plural identity ──────────────────────────────────────────────────

class TestPluralWiring:
    """_PL_PLURAL must be ITEM_TYPE_PL_PLURAL, not a copy."""

    def test_is_same_object(self):
        assert _PL_PLURAL is ITEM_TYPE_PL_PLURAL

    def test_original_10_keys_present(self):
        original_keys = {
            "RING", "PENDANT", "EARRING", "EARRINGS", "BRACELET",
            "BANGLE", "NECKLACE", "CHAIN", "CUFFLINK", "CUFFLINKS",
        }
        for k in original_keys:
            assert k in _PL_PLURAL, f"Missing original key: {k}"

    @pytest.mark.parametrize("key,expected_pl", [
        ("RING",      "Pierścionki"),
        ("PENDANT",   "Wisiorki"),
        ("EARRINGS",  "Kolczyki"),
        ("EARRING",   "Kolczyki"),
        ("BRACELET",  "Bransoletki"),
        ("BANGLE",    "Bransoletki sztywne"),
        ("NECKLACE",  "Naszyjniki"),
        ("CHAIN",     "Łańcuszki"),
        ("CUFFLINKS", "Spinki do mankietów"),
        ("CUFFLINK",  "Spinki do mankietów"),
    ])
    def test_original_values_unchanged(self, key, expected_pl):
        assert _PL_PLURAL[key] == expected_pl

    def test_pl_plural_fallback(self):
        """Unknown types fall back to capitalized key."""
        assert _pl_plural("UNKNOWN_TYPE") == "Unknown_type"

    def test_en_plural_untouched(self):
        """EN plural table must remain local — not imported."""
        assert _EN_PLURAL["RING"] == "RINGS"
        assert _en_plural("UNKNOWN") == "UNKNOWN"


# ── 2. Metal pattern parity ────────────────────────────────────────────────

class TestMetalPatternParity:
    """Every PL metal pattern must exist in METAL_PREPOSITIONAL values."""

    def test_all_patterns_in_shared_grammar(self):
        shared = set(METAL_PREPOSITIONAL.values())
        local = set(_PL_METAL_PATTERNS)
        drift = local - shared
        assert not drift, f"Metal pattern drift: {drift}"

    @pytest.mark.parametrize("pattern", list(_PL_METAL_PATTERNS))
    def test_each_pattern_in_shared(self, pattern):
        assert pattern in METAL_PREPOSITIONAL.values()

    @pytest.mark.parametrize("desc_pl,expected_metal", [
        ("Pierścionki ze złota próby 585 z diamentami",
         "ze złota próby 585"),
        ("Bransoletki ze srebra próby 925 wysadzany cyrkoniami",
         "ze srebra próby 925"),
        ("Naszyjniki z platyny próby 950",
         "z platyny próby 950"),
        ("Wisiorki ze złota próby 375 z diamentami laboratoryjnymi",
         "ze złota próby 375"),
        ("something without metal", ""),
    ])
    def test_extract_pl_metal_output_unchanged(self, desc_pl, expected_metal):
        assert _extract_pl_metal(desc_pl) == expected_metal


# ── 3. Stone pattern documentation ─────────────────────────────────────────

class TestStonePatternDuality:
    """_PL_STONE_PATTERNS contains BOTH old "wysadzany" and new "z" forms."""

    def test_pattern_count_unchanged(self):
        assert len(_PL_STONE_PATTERNS) == 6

    def test_wysadzany_forms_present(self):
        """Old packing-renderer forms still present (needed for extraction)."""
        wysadzany = [p for p in _PL_STONE_PATTERNS if "wysadzany" in p]
        assert len(wysadzany) == 4

    def test_z_prefix_forms_present(self):
        """New parser forms present (for invoice-position source rows)."""
        z_forms = [p for p in _PL_STONE_PATTERNS
                   if p.startswith("z ") and "wysadzany" not in p]
        assert len(z_forms) == 2

    @pytest.mark.parametrize("desc_pl,expected_stone", [
        ("Bransoletki ze złota próby 375 wysadzany cyrkoniami",
         "wysadzany cyrkoniami"),
        ("Pierścionki ze srebra próby 925 z diamentami",
         "z diamentami"),
        ("Wisiorki ze złota próby 585 z diamentami laboratoryjnymi",
         "z diamentami laboratoryjnymi"),
        ("Naszyjniki ze złota próby 750 wysadzany kamieniami kolorowymi",
         "wysadzany kamieniami kolorowymi"),
        ("Pierścionki ze złota próby 585",
         ""),
    ])
    def test_extract_pl_stone_output_unchanged(self, desc_pl, expected_stone):
        assert _extract_pl_stone(desc_pl) == expected_stone

    def test_en_stone_patterns_untouched(self):
        """EN stone patterns remain local — 7 entries, no shared equivalent."""
        assert len(_EN_STONE_PATTERNS) == 7
        assert "Plain Jewellery" in _EN_STONE_PATTERNS


# ── 4. Aggregation smoke tests ─────────────────────────────────────────────

class TestAggregationSmoke:
    """aggregate_packing_rows_to_invoice_positions() output unchanged."""

    def _make_row(self, item_type, metal_pl, metal_en,
                  stone_pl, stone_en, qty=1.0, total=100.0):
        return {
            "invoice_number": "INV-001",
            "line_position": 1,
            "product_code": f"INV-001-{item_type}-1",
            "description": f"{metal_en} {stone_en} {item_type}",
            "polish_customs_description": (
                f"{_pl_plural(item_type)} {metal_pl}"
                + (f" {stone_pl}" if stone_pl else "")
            ),
            "description_en": f"{metal_en} {stone_en} {item_type}",
            "item_type": item_type,
            "item_type_pl": _pl_plural(item_type),
            "quantity": qty,
            "line_total": total,
            "uom": "PCS",
            "currency": "USD",
        }

    def test_single_group(self):
        rows = [
            self._make_row("RING", "ze złota próby 585", "14KT Gold",
                           "z diamentami", "Diamond Jewellery"),
            self._make_row("BRACELET", "ze złota próby 585", "14KT Gold",
                           "z diamentami", "Diamond Jewellery"),
        ]
        result = aggregate_packing_rows_to_invoice_positions(rows)
        assert len(result) == 1
        assert result[0]["quantity"] == 2.0
        assert result[0]["line_total"] == 200.0
        assert "Pierścionki" in result[0]["polish_customs_description"]
        assert "Bransoletki" in result[0]["polish_customs_description"]
        assert "ze złota próby 585" in result[0]["polish_customs_description"]

    def test_different_metals_split(self):
        rows = [
            self._make_row("RING", "ze złota próby 585", "14KT Gold",
                           "z diamentami", "Diamond Jewellery"),
            self._make_row("RING", "ze srebra próby 925", "925 Silver",
                           "z diamentami", "Diamond Jewellery"),
        ]
        result = aggregate_packing_rows_to_invoice_positions(rows)
        assert len(result) == 2

    def test_wysadzany_stone_extraction(self):
        """Rows with OLD "wysadzany" form still aggregate correctly."""
        rows = [
            self._make_row("PENDANT", "ze złota próby 585", "14KT Gold",
                           "wysadzany cyrkoniami", "CZ Stud Jewellery"),
            self._make_row("RING", "ze złota próby 585", "14KT Gold",
                           "wysadzany cyrkoniami", "CZ Stud Jewellery"),
        ]
        result = aggregate_packing_rows_to_invoice_positions(rows)
        assert len(result) == 1
        assert "wysadzany cyrkoniami" in result[0]["polish_customs_description"]

    def test_empty_input(self):
        assert aggregate_packing_rows_to_invoice_positions([]) == []


# ── 5. Import gate ──────────────────────────────────────────────────────────

class TestImportGate:

    def test_module_imports_without_error(self):
        """If this test runs, the import-time parity checks passed."""
        import app.services.customs_position_aggregator as m
        assert hasattr(m, "_PL_PLURAL")
        assert hasattr(m, "_PL_METAL_PATTERNS")
        assert hasattr(m, "_PL_STONE_PATTERNS")
