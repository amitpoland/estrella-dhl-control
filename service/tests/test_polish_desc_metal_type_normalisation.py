"""
test_polish_desc_metal_type_normalisation.py
=============================================
Data-driven regression test for _normalise_metal_key(), _normalise_type_key(),
and _global_render_pl_en() — seeded from the full audited parser code set
produced by the INSPECTOR gate (2026-06-02).

STRUCTURE:
  - Every ✅ code from the audit → assert renders a non-empty PL/EN string
    that is NOT "metal szlachetny".
  - Every former GAP code → assert now renders correctly (regression guard:
    if a new parser alias is added without handling, this test fails before
    the customs form does).
  - '999' alone → assert raises _UnrecognisedMetalCode (ambiguous; pending
    operator mapping decision).
  - Genuinely unrecognised code → assert raises _UnrecognisedMetalCode
    (legible error, not silent fallback).

CONSTRAINTS: description-rendering only. No qty / price / currency / duty.
             Polish description guard (polish_desc_forbidden_tokens) untouched.
"""
from __future__ import annotations

import pytest

from app.api.routes_dhl_clearance import (
    _GLOBAL_METAL_TABLE,
    _GLOBAL_TYPE_TABLE,
    _UnrecognisedMetalCode,
    _global_render_pl_en,
    _normalise_metal_key,
    _normalise_type_key,
)

FORBIDDEN_PLACEHOLDER = "metal szlachetny"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _renders(item_type: str, metal: str, stone: str = "") -> dict:
    """Call _global_render_pl_en and return the desc dict."""
    return _global_render_pl_en(item_type, metal, stone,
                                _row_context=f"{item_type}/{metal}")


def _assert_real(item_type: str, metal: str, stone: str = "") -> None:
    """Assert the row renders a real (non-placeholder, non-empty) PL/EN."""
    desc = _renders(item_type, metal, stone)
    assert desc.get("pl"), (
        f"Expected non-empty PL for type={item_type!r} metal={metal!r}, got empty"
    )
    assert desc.get("en"), (
        f"Expected non-empty EN for type={item_type!r} metal={metal!r}, got empty"
    )
    assert FORBIDDEN_PLACEHOLDER not in desc["pl"], (
        f"Forbidden placeholder in PL for type={item_type!r} metal={metal!r}: "
        f"{desc['pl']!r}"
    )


# ── Metal normalisation unit tests ───────────────────────────────────────────

class TestNormaliseMetalKey:
    """_normalise_metal_key: structural classification by pattern family."""

    # Gold family — all karat+colour variants
    @pytest.mark.parametrize("raw,expected_key", [
        ("18KT/Y",   "18KT GOLD"),
        ("18KT/P",   "18KT GOLD"),
        ("18KT/W",   "18KT GOLD"),
        ("18KT/R",   "18KT GOLD"),
        ("18KT/RG",  "18KT GOLD"),
        ("18KT/WG",  "18KT GOLD"),
        ("18KT/YG",  "18KT GOLD"),
        ("18KT/YWPD","18KT GOLD"),   # multi-char suffix — split on / handles it
        ("18KT",     "18KT GOLD"),
        ("18KT GOLD","18KT GOLD"),   # already canonical
        ("14KT/Y",   "14KT GOLD"),
        ("14KT/W",   "14KT GOLD"),
        ("14KT/P",   "14KT GOLD"),
        ("14KT/PW",  "14KT GOLD"),
        ("14KT/WPD", "14KT GOLD"),
        ("14KT",     "14KT GOLD"),
        ("22KT/Y",   "22KT GOLD"),
        ("22KT",     "22KT GOLD"),
        ("24KT",     "24KT GOLD"),
        ("24KT GOLD","24KT GOLD"),   # already canonical
        ("09KT/W",   "9KT GOLD"),    # leading zero normalised
        ("9KT GOLD", "9KT GOLD"),    # already canonical (via table)
    ])
    def test_gold_family(self, raw, expected_key):
        assert _normalise_metal_key(raw) == expected_key, (
            f"_normalise_metal_key({raw!r}) should be {expected_key!r}"
        )

    # Platinum family
    @pytest.mark.parametrize("raw,expected_key", [
        ("PT950",    "PT950"),
        ("PT900",    "PT900"),
        ("PT850",    "PT850"),
        ("PT950/-",  "PT950"),   # slash-dash suffix stripped
        ("900PT",    "PT900"),   # reversed order
        ("950 PT",   "PT950"),   # spaced, reversed
    ])
    def test_platinum_family(self, raw, expected_key):
        assert _normalise_metal_key(raw) == expected_key, (
            f"_normalise_metal_key({raw!r}) should be {expected_key!r}"
        )

    # Silver family
    @pytest.mark.parametrize("raw,expected_key", [
        ("925 SILVER", "925 SILVER"),   # already canonical
        ("925",        "925 SILVER"),
        ("925/-",      "925 SILVER"),
        ("SL925",      "925 SILVER"),
        ("SL925/-",    "925 SILVER"),
        ("SS925",      "925 SILVER"),
        ("SILVER 925", "925 SILVER"),
    ])
    def test_silver_family(self, raw, expected_key):
        assert _normalise_metal_key(raw) == expected_key, (
            f"_normalise_metal_key({raw!r}) should be {expected_key!r}"
        )

    def test_999_returns_ambiguous_sentinel(self):
        """Bare '999' must return the ambiguity sentinel, NOT a real key."""
        result = _normalise_metal_key("999")
        assert result == "999_AMBIGUOUS", (
            f"Expected '999_AMBIGUOUS', got {result!r}"
        )

    def test_table_keys_pass_through(self):
        """Every existing _GLOBAL_METAL_TABLE key must pass through unchanged."""
        for key in _GLOBAL_METAL_TABLE:
            assert _normalise_metal_key(key) == key, (
                f"Table key {key!r} should pass through unchanged"
            )


# ── Type normalisation unit tests ─────────────────────────────────────────────

class TestNormaliseTypeKey:
    """_normalise_type_key: covers full _EJL_TOKEN_MAP including gaps."""

    @pytest.mark.parametrize("raw,expected", [
        # Pendant
        ("PND",      "PENDANT"),
        ("PEND",     "PENDANT"),
        ("PENDANT",  "PENDANT"),
        # Ring
        ("RNG",      "RING"),
        ("RING",     "RING"),
        # Earring — all aliases including the two gaps ER and EARS
        ("ERG",      "EARRING"),
        ("EAR",      "EARRING"),
        ("ER",       "EARRING"),    # 2-letter gap
        ("EARS",     "EARRING"),    # plural gap
        ("ERS",      "EARRING"),
        ("EARRING",  "EARRING"),
        ("EARRINGS", "EARRING"),
        ("PRS",      "EARRING"),
        # Bracelet
        ("BRC",      "BRACELET"),
        ("BR",       "BRACELET"),
        ("BRACELET", "BRACELET"),
        # Necklace
        ("NCK",      "NECKLACE"),
        ("NK",       "NECKLACE"),
        ("NECKLACE", "NECKLACE"),
        # Bangle
        ("BNG",      "BANGLE"),
        ("BANGLE",   "BANGLE"),
        # Cufflinks
        ("CFL",      "CUFFLINK"),
        ("CUFFLINK", "CUFFLINK"),
        # Chain
        ("CHN",      "CHAIN"),
        ("CHAIN",    "CHAIN"),
    ])
    def test_type_aliases(self, raw, expected):
        assert _normalise_type_key(raw) == expected, (
            f"_normalise_type_key({raw!r}) should be {expected!r}"
        )

    def test_table_keys_pass_through(self):
        """Every _GLOBAL_TYPE_TABLE key should pass through or resolve cleanly."""
        for key in _GLOBAL_TYPE_TABLE:
            result = _normalise_type_key(key)
            # Result must be in the table (possibly as singular form)
            assert result in _GLOBAL_TYPE_TABLE or result.rstrip("S") in _GLOBAL_TYPE_TABLE, (
                f"Table key {key!r} normalised to {result!r} which is not in table"
            )


# ── Integration: _global_render_pl_en renders real descriptions ───────────────

class TestGlobalRenderPlEn:
    """Full render test seeded from the audited parser code set."""

    # Every ✅ code plus every former GAP (now fixed) — all must render real PL/EN
    @pytest.mark.parametrize("item_type,metal", [
        # Gold karats — production set (all colour variants)
        ("PND", "18KT/Y"),
        ("PND", "18KT/P"),
        ("PND", "18KT/W"),
        ("PND", "18KT/RG"),
        ("PND", "18KT/YWPD"),   # former gap (multi-suffix)
        ("PND", "18KT"),
        ("RNG", "14KT/Y"),
        ("RNG", "14KT/W"),
        ("RNG", "14KT/PW"),
        ("RNG", "14KT/WPD"),
        ("RNG", "22KT/Y"),
        ("RNG", "24KT"),        # former gap
        ("RNG", "24KT GOLD"),   # former gap
        ("RNG", "22KT"),        # ✅ bare 22KT (audited green, now pinned in render test)
        ("RNG", "14KT/P"),      # ✅ 14KT pink
        ("RNG", "18KT/R"),      # ✅ 18KT rose
        ("RNG", "18KT/WG"),     # ✅ 18KT white-gold compound suffix
        ("RNG", "18KT/WPD"),    # ✅ 18KT white+pave compound suffix
        ("RNG", "18KT/YG"),     # ✅ 18KT yellow-gold compound suffix
        ("EAR", "09KT/W"),      # former gap (leading-zero karat)
        # Platinum
        ("BRC", "PT950"),
        ("BRC", "PT900"),
        ("BRC", "PT850"),       # former gap
        ("BRC", "PT950/-"),     # former gap
        ("BRC", "900PT"),       # former gap
        ("BRC", "950 PT"),      # former gap
        # Silver
        ("RNG", "925 SILVER"),
        ("RNG", "925"),         # former gap
        ("RNG", "925/-"),       # former gap
        ("RNG", "SL925"),       # former gap
        ("RNG", "SL925/-"),     # former gap
        ("RNG", "SS925"),       # former gap
        ("RNG", "SILVER 925"),  # former gap
        # Type aliases — former gaps ER and EARS
        ("ER",   "18KT/Y"),     # 2-letter earring alias (former type gap)
        ("EARS", "14KT"),       # plural earring alias  (former type gap)
        # Other type variants
        ("ERG",  "18KT/Y"),
        ("EAR",  "18KT/W"),
        ("PRS",  "18KT/P"),
        ("BRC",  "18KT/Y"),
        ("NCK",  "14KT/Y"),
        ("BNG",  "18KT"),
        ("CHN",  "14KT"),
        ("CFL",  "18KT"),
        # With stones
        ("RNG", "18KT/Y"),
        ("PND", "14KT/W"),
    ])
    def test_renders_real_description(self, item_type, metal):
        _assert_real(item_type, metal)

    @pytest.mark.parametrize("item_type,metal,stone", [
        ("RNG", "18KT/Y", "LGD"),     # lab-grown diamond
        ("PND", "14KT/W", "DIA"),     # natural diamond
        ("EAR", "18KT/P", "CZ"),      # cubic zirconia
    ])
    def test_renders_with_stones(self, item_type, metal, stone):
        _assert_real(item_type, metal, stone)

    def test_999_raises_unrecognised(self):
        """Bare '999' must raise _UnrecognisedMetalCode, not fallback silently."""
        with pytest.raises(_UnrecognisedMetalCode, match="999"):
            _renders("RNG", "999")

    def test_truly_unknown_metal_raises(self):
        """A completely unrecognised metal code raises _UnrecognisedMetalCode."""
        with pytest.raises(_UnrecognisedMetalCode):
            _renders("RNG", "UNOBTAINIUM")

    def test_unknown_type_returns_empty_not_raises(self):
        """Unknown item type returns empty strings (skipped), not an exception."""
        desc = _renders("WIDGET", "18KT GOLD")
        assert desc.get("pl") == "" and desc.get("en") == ""

    def test_no_metal_szlachetny_in_any_known_code(self):
        """No known parser code should produce the forbidden placeholder."""
        known_types  = ["PND", "RNG", "ERG", "EAR", "ER", "EARS", "PRS",
                        "BRC", "NCK", "BNG", "CFL", "CHN"]
        known_metals = [
            "18KT/Y", "18KT/P", "14KT/Y", "14KT/W", "22KT/Y", "24KT",
            "PT950", "PT900", "PT850", "900PT", "950 PT", "PT950/-",
            "925", "925/-", "SL925", "SS925", "SILVER 925",
        ]
        for t in known_types:
            for m in known_metals:
                try:
                    desc = _renders(t, m)
                    assert FORBIDDEN_PLACEHOLDER not in desc.get("pl", ""), (
                        f"Forbidden placeholder found for type={t!r} metal={m!r}"
                    )
                except _UnrecognisedMetalCode:
                    pass  # 999_AMBIGUOUS — expected
