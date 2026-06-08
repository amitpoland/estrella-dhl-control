"""
Phase 2C regression tests — packing renderer grammar parity.

Verifies that the packing renderer's local PL dictionaries
(_GLOBAL_TYPE_TABLE, _GLOBAL_METAL_TABLE) are consistent with the
shared grammar authority in description_grammar.py.

Coverage:
  - Every PL value in _GLOBAL_TYPE_TABLE exists in ITEM_TYPE_PL
  - Every PL value in _GLOBAL_METAL_TABLE exists in METAL_PREPOSITIONAL
  - EN-side values are untouched (renderer owns EN rendering)
  - Stone vocabulary is documented (inline rendering, not dict-driven)
  - Import gate fires and module loads without error
  - Rendering pipeline output matches expected grammar forms
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure repo root is on sys.path for description_grammar import
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from description_grammar import ITEM_TYPE_PL, METAL_PREPOSITIONAL

# Import the renderer's tables and function
from app.api.routes_dhl_clearance import (
    _GLOBAL_TYPE_TABLE,
    _GLOBAL_METAL_TABLE,
    _global_render_pl_en,
    _normalise_type_key,
    _normalise_metal_key,
    _KARAT_FINENESS,
)


# ═════════════════════════════════════════════════════════════════════════════
# TestTypePLParity — every renderer PL type matches shared grammar
# ═════════════════════════════════════════════════════════════════════════════

class TestTypePLParity:
    """Verify PL values in _GLOBAL_TYPE_TABLE match ITEM_TYPE_PL."""

    def test_all_pl_values_in_shared_grammar(self):
        """Every renderer PL type value must exist in ITEM_TYPE_PL."""
        shared_values = set(ITEM_TYPE_PL.values())
        for key, info in _GLOBAL_TYPE_TABLE.items():
            assert info["pl"] in shared_values, (
                f"_GLOBAL_TYPE_TABLE[{key!r}]['pl'] = {info['pl']!r} "
                f"not in ITEM_TYPE_PL values"
            )

    @pytest.mark.parametrize(
        "type_key",
        list(_GLOBAL_TYPE_TABLE.keys()),
    )
    def test_each_type_pl_value_matches(self, type_key: str):
        """Each renderer type's PL value is in the shared grammar."""
        pl_val = _GLOBAL_TYPE_TABLE[type_key]["pl"]
        assert pl_val in ITEM_TYPE_PL.values(), (
            f"PL value {pl_val!r} for type {type_key!r} not in shared grammar"
        )

    def test_shared_grammar_is_superset(self):
        """Shared grammar has MORE types than the renderer (BROOCH, SET, etc.)."""
        renderer_pl = {v["pl"] for v in _GLOBAL_TYPE_TABLE.values()}
        shared_pl = set(ITEM_TYPE_PL.values())
        # Shared must be a superset
        assert renderer_pl.issubset(shared_pl)
        # Shared has more entries (renderer doesn't handle all types)
        assert len(shared_pl) > len(renderer_pl)

    def test_en_values_untouched(self):
        """EN values in _GLOBAL_TYPE_TABLE are renderer-owned, not shared."""
        # Just verify they exist and are non-empty
        for key, info in _GLOBAL_TYPE_TABLE.items():
            assert info["en"], f"_GLOBAL_TYPE_TABLE[{key!r}]['en'] is empty"
            assert info["label"], f"_GLOBAL_TYPE_TABLE[{key!r}]['label'] is empty"

    def test_renderer_type_count(self):
        """Renderer has exactly the expected type keys."""
        expected_keys = {
            "RING", "PENDANT", "EARRING", "EARRINGS", "BRACELET",
            "BANGLE", "NECKLACE", "CHAIN", "CUFFLINK", "CUFFLINKS",
        }
        assert set(_GLOBAL_TYPE_TABLE.keys()) == expected_keys


# ═════════════════════════════════════════════════════════════════════════════
# TestMetalPLParity — every renderer PL metal matches shared grammar
# ═════════════════════════════════════════════════════════════════════════════

class TestMetalPLParity:
    """Verify PL values in _GLOBAL_METAL_TABLE match METAL_PREPOSITIONAL."""

    def test_all_pl_values_in_shared_grammar(self):
        """Every renderer PL metal value must exist in METAL_PREPOSITIONAL."""
        shared_values = set(METAL_PREPOSITIONAL.values())
        for key, info in _GLOBAL_METAL_TABLE.items():
            assert info["pl"] in shared_values, (
                f"_GLOBAL_METAL_TABLE[{key!r}]['pl'] = {info['pl']!r} "
                f"not in METAL_PREPOSITIONAL values"
            )

    @pytest.mark.parametrize(
        "metal_key",
        list(_GLOBAL_METAL_TABLE.keys()),
    )
    def test_each_metal_pl_value_matches(self, metal_key: str):
        """Each renderer metal's PL value is in the shared grammar."""
        pl_val = _GLOBAL_METAL_TABLE[metal_key]["pl"]
        assert pl_val in METAL_PREPOSITIONAL.values(), (
            f"PL value {pl_val!r} for metal {metal_key!r} not in shared grammar"
        )

    def test_gold_forms_use_ze_prefix(self):
        """All gold entries use 'ze złota próby NNN' form."""
        gold_keys = [k for k in _GLOBAL_METAL_TABLE if "GOLD" in k]
        assert len(gold_keys) >= 5, "Expected at least 5 gold entries"
        for k in gold_keys:
            pl = _GLOBAL_METAL_TABLE[k]["pl"]
            assert pl.startswith("ze złota próby"), (
                f"Gold entry {k!r} PL = {pl!r} doesn't start with 'ze złota próby'"
            )

    def test_silver_form(self):
        """Silver uses 'ze srebra próby 925' form."""
        assert _GLOBAL_METAL_TABLE["925 SILVER"]["pl"] == "ze srebra próby 925"

    def test_platinum_forms_use_z_prefix(self):
        """Platinum entries use 'z platyny próby NNN' form."""
        pt_keys = [k for k in _GLOBAL_METAL_TABLE if k.startswith("PT")]
        assert len(pt_keys) >= 3, "Expected at least 3 platinum entries"
        for k in pt_keys:
            pl = _GLOBAL_METAL_TABLE[k]["pl"]
            assert pl.startswith("z platyny próby"), (
                f"Platinum entry {k!r} PL = {pl!r} doesn't start with 'z platyny próby'"
            )

    def test_en_values_untouched(self):
        """EN values are renderer-owned."""
        for key, info in _GLOBAL_METAL_TABLE.items():
            assert info["en"], f"_GLOBAL_METAL_TABLE[{key!r}]['en'] is empty"

    def test_alias_consistency(self):
        """'9 GOLD' and '9KT GOLD' produce the same PL value."""
        assert _GLOBAL_METAL_TABLE["9 GOLD"]["pl"] == _GLOBAL_METAL_TABLE["9KT GOLD"]["pl"]


# ═════════════════════════════════════════════════════════════════════════════
# TestRenderPipelineSmoke — verify rendering output uses shared grammar forms
# ═════════════════════════════════════════════════════════════════════════════

class TestRenderPipelineSmoke:
    """Smoke tests verifying that _global_render_pl_en produces
    descriptions using the shared grammar forms."""

    def test_gold_ring_plain(self):
        """14KT gold ring, no stones."""
        result = _global_render_pl_en("RING", "14KT", "")
        assert result["pl"] == "Pierścionek ze złota próby 585"
        assert "14KT Gold" in result["en"]
        assert result["item_type_pl"] == "Pierścionek"

    def test_silver_earring_cz(self):
        """925 silver earring with CZ stones."""
        result = _global_render_pl_en("EARRING", "925", "CZ")
        assert result["pl"] == "Kolczyki ze srebra próby 925 wysadzany cyrkoniami"
        assert "925 Silver" in result["en"]

    def test_platinum_pendant_diamond(self):
        """PT950 platinum pendant with diamonds."""
        result = _global_render_pl_en("PENDANT", "PT950", "DIA")
        assert result["pl"] == "Wisiorek z platyny próby 950 z diamentami"
        assert "PT950 Platinum" in result["en"]

    def test_gold_bracelet_lgd(self):
        """18KT gold bracelet with lab-grown diamonds."""
        result = _global_render_pl_en("BRACELET", "18KT", "LGD")
        assert result["pl"] == "Bransoletka ze złota próby 750 z diamentami laboratoryjnymi"

    def test_silver_bangle_colour_cz(self):
        """925 silver bangle with CZ and colour stones."""
        result = _global_render_pl_en("BANGLE", "925", "CZ CLS")
        assert result["pl"] == "Bransoletka sztywna ze srebra próby 925 wysadzany cyrkoniami i kamieniami kolorowymi"

    def test_unknown_type_returns_empty(self):
        """Unknown item type returns empty strings."""
        result = _global_render_pl_en("TIARA", "14KT", "DIA")
        assert result["pl"] == ""
        assert result["en"] == ""

    def test_colour_suffix_metal_normalises(self):
        """18KT/Y (yellow gold variant) normalises to 18KT GOLD."""
        result = _global_render_pl_en("RING", "18KT/Y", "")
        assert result["pl"] == "Pierścionek ze złota próby 750"

    def test_pt900_platinum_chain(self):
        """PT900 platinum chain."""
        result = _global_render_pl_en("CHAIN", "PT900", "")
        assert result["pl"] == "Łańcuszek z platyny próby 900"

    def test_9kt_gold_cufflink(self):
        """9KT gold cufflinks."""
        result = _global_render_pl_en("CUFFLINK", "9KT", "")
        assert result["pl"] == "Spinki do mankietów ze złota próby 375"


# ═════════════════════════════════════════════════════════════════════════════
# TestNormalisers — key normalisation functions
# ═════════════════════════════════════════════════════════════════════════════

class TestNormalisers:
    """Verify key normalisation functions work correctly."""

    def test_type_aliases(self):
        """Common packing-list type aliases normalise correctly."""
        assert _normalise_type_key("PND") == "PENDANT"
        assert _normalise_type_key("RNG") == "RING"
        assert _normalise_type_key("ERG") == "EARRING"
        assert _normalise_type_key("BRC") == "BRACELET"
        assert _normalise_type_key("NCK") == "NECKLACE"

    def test_metal_colour_suffix_stripped(self):
        """Metal colour suffixes are stripped by _normalise_metal_key."""
        assert _normalise_metal_key("18KT/Y") == "18KT GOLD"
        assert _normalise_metal_key("18KT/P") == "18KT GOLD"
        assert _normalise_metal_key("18KT/RG") == "18KT GOLD"
        assert _normalise_metal_key("925/-") == "925 SILVER"

    def test_karat_fineness_not_arithmetic(self):
        """Fineness values are table lookups, not karat÷24×1000."""
        assert _KARAT_FINENESS[14] == 585  # not 583
        assert _KARAT_FINENESS[22] == 916  # not 917


# ═════════════════════════════════════════════════════════════════════════════
# TestStoneVocabularyDocumented — stone rendering is inline, not dict-driven
# ═════════════════════════════════════════════════════════════════════════════

class TestStoneVocabularyDocumented:
    """Document the stone vocabulary forms used by the packing renderer.

    The packing renderer uses inline regex matching (not dictionary
    lookups) for stones.  These tests document the exact forms produced,
    which the aggregator's _PL_STONE_PATTERNS must match."""

    _STONE_FORMS = [
        ("LGD", "z diamentami laboratoryjnymi"),
        ("DIA CZ", "wysadzany diamentami i cyrkoniami"),
        ("CZ CLS", "wysadzany cyrkoniami i kamieniami kolorowymi"),
        ("CZ", "wysadzany cyrkoniami"),
        ("DIA", "z diamentami"),
        ("CLS", "wysadzany kamieniami kolorowymi"),
    ]

    @pytest.mark.parametrize(
        "stone_text,expected_pl_suffix",
        _STONE_FORMS,
        ids=[s[0] for s in _STONE_FORMS],
    )
    def test_stone_form_in_output(self, stone_text: str, expected_pl_suffix: str):
        """Verify each stone vocabulary form appears in rendered output."""
        result = _global_render_pl_en("RING", "14KT", stone_text)
        assert expected_pl_suffix in result["pl"], (
            f"Expected {expected_pl_suffix!r} in PL output: {result['pl']!r}"
        )

    def test_plain_no_stone_suffix(self):
        """Plain jewellery (no stone) has no stone suffix."""
        result = _global_render_pl_en("RING", "14KT", "")
        assert result["pl"] == "Pierścionek ze złota próby 585"
        assert "Plain Jewellery" in result["en"]

    def test_wysadzany_forms_count(self):
        """4 stone types use 'wysadzany' form (CZ, DIA+CZ, CZ+CLS, CLS)."""
        wysadzany_forms = [
            f for _, f in self._STONE_FORMS if "wysadzany" in f
        ]
        assert len(wysadzany_forms) == 4

    def test_z_prefix_forms_count(self):
        """2 stone types use 'z' prefix form (LGD, DIA)."""
        z_forms = [
            f for _, f in self._STONE_FORMS
            if f.startswith("z ") and "wysadzany" not in f
        ]
        assert len(z_forms) == 2


# ═════════════════════════════════════════════════════════════════════════════
# TestImportGate — module loads without error
# ═════════════════════════════════════════════════════════════════════════════

class TestImportGate:
    """Verify the import-time parity gates pass."""

    def test_routes_dhl_clearance_imports_without_error(self):
        """Module loaded successfully (parity gates passed)."""
        from app.api import routes_dhl_clearance  # noqa: F401
        assert hasattr(routes_dhl_clearance, "router")

    def test_shared_grammar_available(self):
        """Shared grammar is importable from module context."""
        from app.api.routes_dhl_clearance import ITEM_TYPE_PL as itp
        from app.api.routes_dhl_clearance import METAL_PREPOSITIONAL as mp
        assert len(itp) >= 10
        assert len(mp) >= 7
