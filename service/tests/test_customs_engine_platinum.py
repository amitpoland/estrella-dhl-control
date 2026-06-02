"""
test_customs_engine_platinum.py
================================
Regression tests for platinum (PT950/PT900/PT850) purity resolution in
customs_description_engine.normalize_item_description().

Root cause fixed (2026-06-02):
  GOLD_PURITY and _PURITY_GENITIVE lacked platinum entries.
  Invoice descriptions containing "PT950 Platinum" fell through to
  material_pl = "metal szlachetny" — a forbidden placeholder that caused
  the 422 polish_desc_forbidden_tokens guard to fire for AWB 8400636576.

These tests pin the fix so any regression re-introduces a test failure
BEFORE the batch reaches the customs guard.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

# Engine lives at repo root (one level above service/).
# conftest.py already adds the root to sys.path, but we make it explicit
# here so this test file is self-contained when run in isolation.
_REPO_ROOT = Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import customs_description_engine as cde  # noqa: E402  (after sys.path setup)

FORBIDDEN = "metal szlachetny"


def _norm(description: str, item_type: str = "ring") -> dict:
    """Thin wrapper around normalize_item_description."""
    return cde.normalize_item_description(description, item_type=item_type,
                                          hsn_from_invoice="")


# ── platinum material_pl (nominative) ────────────────────────────────────────

class TestPlatinumMaterialPl:
    """material_pl must NOT be the forbidden placeholder for any platinum input."""

    @pytest.mark.parametrize("description,expected_material", [
        # Exact invoice lines from AWB 8400636576 (the failing batch)
        ("PCS, PT950 Platinum,Plain Jewel RING",
         "platyna próby 950"),
        ("PCS, PT950 Platinum,Stud With Diam Jewel RING",
         "platyna próby 950"),
        # Variant purities
        ("PT900 Platinum Ring",   "platyna próby 900"),
        ("PT850 Platinum Ring",   "platyna próby 850"),
        # Generic "Platinum" when no numeric purity is stated
        ("Platinum Ring",         "platyna"),
        ("PLATINUM JEWELLERY",    "platyna"),
    ])
    def test_material_pl_resolved(self, description, expected_material):
        result = _norm(description)
        assert result.get("material_pl") == expected_material, (
            f"Expected material_pl={expected_material!r} for {description!r}, "
            f"got {result.get('material_pl')!r}"
        )

    @pytest.mark.parametrize("description", [
        "PCS, PT950 Platinum,Plain Jewel RING",
        "PCS, PT950 Platinum,Stud With Diam Jewel RING",
        "PT900 Platinum Ring",
        "PT850 Platinum Ring",
        "Platinum Ring",
    ])
    def test_no_forbidden_placeholder(self, description):
        result = _norm(description)
        assert FORBIDDEN not in (result.get("material_pl") or ""), (
            f"Forbidden placeholder found in material_pl for {description!r}: "
            f"{result.get('material_pl')!r}"
        )


# ── platinum polish_customs_description ──────────────────────────────────────

class TestPlatinumPolishDescription:
    """polish_customs_description must contain the correct genitive form."""

    @pytest.mark.parametrize("description,expected_genitive", [
        ("PCS, PT950 Platinum,Plain Jewel RING", "platyny próby 950"),
        ("PT900 Platinum Ring",                  "platyny próby 900"),
        ("PT850 Platinum Ring",                  "platyny próby 850"),
        ("Platinum Ring",                        "platyny"),
    ])
    def test_genitive_in_customs_description(self, description, expected_genitive):
        result = _norm(description)
        desc_pl = result.get("polish_customs_description") or ""
        assert expected_genitive in desc_pl, (
            f"Expected genitive {expected_genitive!r} in polish_customs_description "
            f"for {description!r}, got: {desc_pl!r}"
        )

    def test_pt950_plain_ring_full_sentence(self):
        """Exact sentence form for the failing AWB's plain platinum ring."""
        result = _norm("PCS, PT950 Platinum,Plain Jewel RING", item_type="ring")
        desc_pl = result.get("polish_customs_description") or ""
        # Must contain item type + genitive purity — no forbidden placeholder
        assert "platyny próby 950" in desc_pl, f"Missing purity in: {desc_pl!r}"
        assert FORBIDDEN not in desc_pl, f"Forbidden placeholder in: {desc_pl!r}"


# ── gold still works after the edit ──────────────────────────────────────────

class TestGoldUnaffected:
    """Existing gold/silver rows must be unaffected by the platinum addition."""

    @pytest.mark.parametrize("description,expected_material", [
        ("PCS, 18KT Gold,Plain Jewellery PENDANT", "złoto próby 750"),
        ("PCS, 14KT Gold,LGD Gold Stud Jewell RING", "złoto próby 585 z diamenty laboratoryjne"),
        ("925 Silver Ring",                          "srebro próby 925"),
    ])
    def test_gold_silver_unchanged(self, description, expected_material):
        result = _norm(description)
        assert result.get("material_pl") == expected_material, (
            f"Gold/silver regression: expected {expected_material!r}, "
            f"got {result.get('material_pl')!r}"
        )

    @pytest.mark.parametrize("description", [
        "PCS, 18KT Gold,Plain Jewellery PENDANT",
        "PCS, 14KT Gold,LGD Gold Stud Jewell RING",
        "14KT Gold Diamond Ring",
    ])
    def test_gold_no_forbidden_placeholder(self, description):
        result = _norm(description)
        assert FORBIDDEN not in (result.get("material_pl") or ""), (
            f"Gold row got forbidden placeholder: {description!r}"
        )


# ── GOLD_PURITY dict contains platinum entries ────────────────────────────────

class TestDictContainsPlatinum:
    """Directly assert the dicts carry the new entries (catches a typo in keys)."""

    def test_gold_purity_has_pt950(self):
        assert "PT950" in cde.GOLD_PURITY
        assert cde.GOLD_PURITY["PT950"] == "platyna próby 950"

    def test_gold_purity_has_pt900(self):
        assert "PT900" in cde.GOLD_PURITY
        assert cde.GOLD_PURITY["PT900"] == "platyna próby 900"

    def test_gold_purity_has_pt850(self):
        assert "PT850" in cde.GOLD_PURITY
        assert cde.GOLD_PURITY["PT850"] == "platyna próby 850"

    def test_gold_purity_has_platinum_fallback(self):
        assert "PLATINUM" in cde.GOLD_PURITY
        assert cde.GOLD_PURITY["PLATINUM"] == "platyna"

    def test_purity_genitive_has_pt950(self):
        assert "PT950" in cde._PURITY_GENITIVE
        assert cde._PURITY_GENITIVE["PT950"] == "platyny próby 950"

    def test_purity_genitive_has_pt900(self):
        assert "PT900" in cde._PURITY_GENITIVE
        assert cde._PURITY_GENITIVE["PT900"] == "platyny próby 900"

    def test_purity_genitive_has_pt850(self):
        assert "PT850" in cde._PURITY_GENITIVE
        assert cde._PURITY_GENITIVE["PT850"] == "platyny próby 850"

    def test_purity_genitive_has_platinum_fallback(self):
        assert "PLATINUM" in cde._PURITY_GENITIVE
        assert cde._PURITY_GENITIVE["PLATINUM"] == "platyny"

    def test_pt950_before_platinum_in_dict_order(self):
        """PT950 must precede PLATINUM so PT950 wins the first-match scan."""
        keys = list(cde.GOLD_PURITY.keys())
        assert keys.index("PT950") < keys.index("PLATINUM"), (
            "PT950 must be inserted before PLATINUM in GOLD_PURITY "
            "or the first-match scan returns the generic form instead of próby 950"
        )
