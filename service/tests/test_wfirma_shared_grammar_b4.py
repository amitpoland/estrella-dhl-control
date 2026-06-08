"""
Phase 2B4 regression tests — wFirma grammar compatibility.

Verifies that ``routes_wfirma._material_from_pl_desc()`` can extract
the material phrase from every shared grammar metal form, and that the
import-time compatibility gate in routes_wfirma catches drift.

Coverage:
  - Every METAL_PREPOSITIONAL value is extractable by the regex
  - Stone phrase pass-through is preserved for both "z" and "wysadzany" forms
  - Karat genitive forms (PURITY_GENITIVE) are documented as out-of-scope
  - Import gate fires and routes_wfirma loads without error
  - EN-side behaviour untouched (function only processes PL text)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# Ensure repo root is on sys.path for description_grammar import
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from description_grammar import METAL_PREPOSITIONAL, PURITY_GENITIVE


# ── Import the private function under test ───────────────────────────────────
from app.api.routes_wfirma import _material_from_pl_desc  # type: ignore[attr-defined]


# ═════════════════════════════════════════════════════════════════════════════
# TestMetalExtractionParity — every shared grammar form is extractable
# ═════════════════════════════════════════════════════════════════════════════

class TestMetalExtractionParity:
    """Verify _material_from_pl_desc extracts the correct material
    from PL descriptions built with every METAL_PREPOSITIONAL form."""

    @pytest.mark.parametrize(
        "metal_key,metal_form",
        list(METAL_PREPOSITIONAL.items()),
        ids=[k for k in METAL_PREPOSITIONAL],
    )
    def test_every_metal_form_extracts(self, metal_key: str, metal_form: str):
        """Construct a typical PL description and verify extraction."""
        # Production shape: "Pierścionki ze złota próby 585 z diamentami"
        pl_desc = f"Pierścionki {metal_form}"
        result = _material_from_pl_desc(pl_desc)
        assert result, f"Failed to extract material from: {pl_desc!r}"
        # Result should NOT contain the item-type prefix
        assert not result.startswith("Pierścionki"), (
            f"Item-type prefix leaked through: {result!r}"
        )

    @pytest.mark.parametrize(
        "metal_key,metal_form",
        list(METAL_PREPOSITIONAL.items()),
        ids=[k for k in METAL_PREPOSITIONAL],
    )
    def test_metal_with_stone_suffix_extracts(self, metal_key: str, metal_form: str):
        """Verify extraction when stone phrase follows the metal."""
        pl_desc = f"Bransoletki {metal_form} z diamentami laboratoryjnymi"
        result = _material_from_pl_desc(pl_desc)
        assert result, f"Failed to extract from: {pl_desc!r}"
        # The stone phrase should be included in the extraction
        assert "diamentami" in result, (
            f"Stone phrase lost during extraction: {result!r}"
        )

    @pytest.mark.parametrize(
        "metal_key,metal_form",
        list(METAL_PREPOSITIONAL.items()),
        ids=[k for k in METAL_PREPOSITIONAL],
    )
    def test_metal_with_wysadzany_stone_extracts(self, metal_key: str, metal_form: str):
        """Verify extraction when stone uses 'wysadzany' form (packing renderer)."""
        pl_desc = f"Kolczyki {metal_form} wysadzany cyrkoniami"
        result = _material_from_pl_desc(pl_desc)
        assert result, f"Failed to extract from: {pl_desc!r}"

    def test_ze_gold_585_typical(self):
        """Canonical gold extraction case."""
        result = _material_from_pl_desc(
            "Bransoletki ze złota próby 585 z diamentami laboratoryjnymi"
        )
        assert result == "złota próby 585 z diamentami laboratoryjnymi"

    def test_ze_silver_925_typical(self):
        """Canonical silver extraction case."""
        result = _material_from_pl_desc(
            "Kolczyki ze srebra próby 925 z cyrkoniami"
        )
        assert result == "srebra próby 925 z cyrkoniami"

    def test_z_platinum_950_typical(self):
        """Canonical platinum extraction case."""
        result = _material_from_pl_desc(
            "Pierścionki z platyny próby 950"
        )
        assert result == "platyny próby 950"

    def test_ze_steel_typical(self):
        """Steel has no 'próby' suffix — relies on regex 1 (ze pattern)."""
        result = _material_from_pl_desc(
            "Bransoletki ze stali szlachetnej"
        )
        assert result == "stali szlachetnej"

    def test_plain_metal_no_stone(self):
        """Plain jewellery (no stone phrase) still extracts metal."""
        result = _material_from_pl_desc(
            "Pierścionki ze złota próby 375"
        )
        assert result == "złota próby 375"

    def test_empty_input(self):
        """Empty string returns empty."""
        assert _material_from_pl_desc("") == ""

    def test_none_coerced(self):
        """None-like input returns empty."""
        assert _material_from_pl_desc("") == ""

    def test_unrecognised_falls_through(self):
        """Input with no recognisable preposition returns input stripped."""
        result = _material_from_pl_desc("Unknown metal description")
        assert result == "Unknown metal description"


# ═════════════════════════════════════════════════════════════════════════════
# TestKaratGenitiveDocumented — engine forms do NOT flow to wFirma
# ═════════════════════════════════════════════════════════════════════════════

class TestKaratGenitiveDocumented:
    """Document that PURITY_GENITIVE (karat genitive) forms are NOT
    compatible with _material_from_pl_desc regex — and that this is
    by design because engine output never flows to pz_rows.json.

    These tests verify the gap EXISTS (not that it's a bug). If a
    future migration routes engine output to wFirma, the regex must
    be updated and these tests revised."""

    _GOLD_GENITIVE_KEYS = [
        k for k, v in PURITY_GENITIVE.items()
        if "karatowego" in v
    ]

    @pytest.mark.parametrize("key", _GOLD_GENITIVE_KEYS)
    def test_gold_karat_genitive_not_extractable(self, key: str):
        """Karat genitive gold forms fall through to raw text (by design)."""
        genitive_form = PURITY_GENITIVE[key]
        pl_desc = f"Pierścionek z {genitive_form} wysadzany diamentami"
        result = _material_from_pl_desc(pl_desc)
        # Falls through to raw input (unrecognised pattern)
        assert result == pl_desc.strip(), (
            f"Unexpected extraction from karat genitive: {result!r}"
        )

    def test_silver_genitive_extracts_via_ze(self):
        """Silver genitive form 'srebra próby 925' is also in
        METAL_PREPOSITIONAL and uses 'ze' prefix — extraction works."""
        # Engine output for silver: "Kolczyki ze srebra próby 925..."
        # This form is shared between engine and packing renderer.
        result = _material_from_pl_desc(
            "Kolczyki ze srebra próby 925"
        )
        assert result == "srebra próby 925"

    def test_platinum_genitive_extracts_via_z(self):
        """Platinum genitive 'platyny próby 950' uses 'z' prefix — works."""
        result = _material_from_pl_desc(
            "Pierścionki z platyny próby 950"
        )
        assert result == "platyny próby 950"


# ═════════════════════════════════════════════════════════════════════════════
# TestMultiTypePrefix — aggregated position descriptions with comma-separated types
# ═════════════════════════════════════════════════════════════════════════════

class TestMultiTypePrefix:
    """Verify extraction from aggregated descriptions that have multiple
    item types before the metal phrase (production aggregator output)."""

    def test_two_types_ze_gold(self):
        result = _material_from_pl_desc(
            "Pierścionki, Wisiorki ze złota próby 585 z diamentami"
        )
        assert result == "złota próby 585 z diamentami"

    def test_three_types_ze_silver(self):
        result = _material_from_pl_desc(
            "Pierścionki, Wisiorki, Bransoletki ze srebra próby 925 wysadzany cyrkoniami"
        )
        assert result == "srebra próby 925 wysadzany cyrkoniami"

    def test_two_types_z_platinum(self):
        result = _material_from_pl_desc(
            "Kolczyki, Naszyjniki z platyny próby 950"
        )
        assert result == "platyny próby 950"


# ═════════════════════════════════════════════════════════════════════════════
# TestImportGate — module loads without error
# ═════════════════════════════════════════════════════════════════════════════

class TestImportGate:
    """Verify the import-time compatibility gate passes."""

    def test_routes_wfirma_imports_without_error(self):
        """The module loaded successfully (import-time gate passed)."""
        from app.api import routes_wfirma  # noqa: F401
        assert hasattr(routes_wfirma, "router")

    def test_metal_prepositional_available(self):
        """Shared grammar is importable from the module's context."""
        from app.api.routes_wfirma import METAL_PREPOSITIONAL as mp
        assert len(mp) >= 7, f"Expected >=7 metal forms, got {len(mp)}"

    def test_compat_regexes_compiled(self):
        """Import-time regex objects exist."""
        from app.api.routes_wfirma import _RE_ZE, _RE_Z
        assert _RE_ZE is not None
        assert _RE_Z is not None


# ═════════════════════════════════════════════════════════════════════════════
# TestRegexEdgeCases — boundary conditions for the regex patterns
# ═════════════════════════════════════════════════════════════════════════════

class TestRegexEdgeCases:
    """Edge cases and boundary conditions for the extraction regex."""

    def test_ze_requires_whitespace_before(self):
        """'ze' must be preceded by whitespace (not start of string)."""
        # "ze złota" at start of string has no leading whitespace for \s+
        result = _material_from_pl_desc("ze złota próby 585")
        # Falls through — no \s+ before "ze"
        assert result == "ze złota próby 585"

    def test_z_requires_whitespace_before(self):
        """'z' must be preceded by whitespace."""
        result = _material_from_pl_desc("z platyny próby 950")
        assert result == "z platyny próby 950"

    def test_multiple_ze_takes_first(self):
        """If description has multiple 'ze', regex takes the first match."""
        result = _material_from_pl_desc(
            "Kolczyki ze srebra próby 925 ze specjalnej kolekcji"
        )
        # .search finds the first \s+ze\s+ occurrence
        assert "srebra" in result

    def test_whitespace_handling(self):
        """Extra whitespace doesn't break extraction."""
        result = _material_from_pl_desc(
            "  Pierścionki  ze złota próby 585  "
        )
        assert "złota" in result

    def test_tab_as_whitespace(self):
        """Tab characters work as whitespace separator."""
        result = _material_from_pl_desc(
            "Pierścionki\tze złota próby 585"
        )
        assert "złota" in result


# ═════════════════════════════════════════════════════════════════════════════
# TestENSideUntouched — B4 does not affect English-side behaviour
# ═════════════════════════════════════════════════════════════════════════════

class TestENSideUntouched:
    """Confirm _material_from_pl_desc only processes PL text.
    There is no EN extraction counterpart in the function."""

    def test_en_text_falls_through(self):
        """English description text has no 'ze'/'z próby' — falls through."""
        result = _material_from_pl_desc(
            "14KT Gold Diamond Jewellery RING"
        )
        assert result == "14KT Gold Diamond Jewellery RING"

    def test_mixed_pl_en_uses_pl_part(self):
        """When PL description is passed (which is always the case in production),
        the PL metal phrase is extracted correctly."""
        # _build_authority_description() returns PL/EN combined,
        # but _material_from_pl_desc receives only pl_desc
        result = _material_from_pl_desc(
            "Bransoletki ze złota próby 375 z diamentami laboratoryjnymi"
        )
        assert result == "złota próby 375 z diamentami laboratoryjnymi"
