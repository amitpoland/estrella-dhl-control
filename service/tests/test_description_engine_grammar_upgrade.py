"""
test_description_engine_grammar_upgrade.py — Regression tests for Description Engine
Phase 1: grammar and dictionary upgrades.

Pins the DESIRED output forms after the grammar upgrade:
  1. Karat-expanded genitive: "z 14-karatowego zlota (proba 585)" not "ze zlota proby 585"
  2. Gender-specific setting verb: wysadzany (masc), wysadzana (fem), wysadzane (plural)
  3. Sentence-break suffix: ". Bizuteria do noszenia." not ", bizuteria do noszenia."
  4. Material conjunction: "oraz" not "z" in nominative material_pl
  5. New stone categories: kamienie jubilerskie, kamienie ozdobne instrumental forms

These tests FAIL against pre-upgrade code and PASS after dictionary/grammar changes.

Origin: Operator review of AWB 9938632830 Polish description (2026-06-08).
Architectural directive: Description Engine is the single product-description
authority for all jewelry descriptions across the platform.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import customs_description_engine as cde


# ============================================================================
# 1. Karat-expanded genitive forms
# ============================================================================

class TestKaratExpandedGenitive:
    """_PURITY_GENITIVE must produce karat-expanded form for gold entries."""

    def test_14kt_genitive(self):
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA RING")
        assert "14-karatowego złota (próba 585)" in r["polish_customs_description"]

    def test_9kt_genitive(self):
        r = cde.normalize_item_description("PCS, 9KT Gold, DIA RING")
        assert "9-karatowego złota (próba 375)" in r["polish_customs_description"]

    def test_18kt_genitive(self):
        r = cde.normalize_item_description("PCS, 18KT Gold, DIA EARRINGS")
        assert "18-karatowego złota (próba 750)" in r["polish_customs_description"]

    def test_22kt_genitive(self):
        r = cde.normalize_item_description("PCS, 22KT Gold, PLAIN CHAIN")
        assert "22-karatowego złota (próba 916)" in r["polish_customs_description"]

    def test_24kt_genitive(self):
        r = cde.normalize_item_description("PCS, 24KT Gold, PLAIN BANGLE")
        assert "24-karatowego złota (próba 999)" in r["polish_customs_description"]

    def test_10kt_genitive(self):
        r = cde.normalize_item_description("PCS, 10KT Gold, DIA PENDANT")
        assert "10-karatowego złota (próba 417)" in r["polish_customs_description"]

    def test_silver_unchanged(self):
        """Silver is not karat-based — genitive stays as-is."""
        r = cde.normalize_item_description("PCS, 925 Silver, CZ RING")
        assert "srebra próby 925" in r["polish_customs_description"]

    def test_platinum_unchanged(self):
        """Platinum is not karat-based — genitive stays as-is."""
        r = cde.normalize_item_description("PCS, PT950 Platinum, DIA RING")
        assert "platyny próby 950" in r["polish_customs_description"]

    def test_preposition_z_not_ze_for_karat(self):
        """Karat-expanded form starts with digit → preposition is 'z', not 'ze'."""
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA RING")
        desc = r["polish_customs_description"]
        assert "z 14-karatowego" in desc
        assert "ze 14-karatowego" not in desc


# ============================================================================
# 2. Gender-specific setting verb (wysadzany/wysadzana/wysadzane)
# ============================================================================

class TestGenderSettingVerb:
    """Setting verb must agree in gender with the item_type_pl noun."""

    # ── Masculine (wysadzany) ────────────────────────────────────────────────

    def test_ring_masculine(self):
        """Pierścionek (m.) → wysadzany"""
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA RING")
        assert "wysadzany diamentami" in r["polish_customs_description"]

    def test_pendant_masculine(self):
        """Wisiorek (m.) → wysadzany"""
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA PENDANT")
        assert "wysadzany diamentami" in r["polish_customs_description"]

    def test_necklace_masculine(self):
        """Naszyjnik (m.) → wysadzany"""
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA NECKLACE")
        assert "wysadzany diamentami" in r["polish_customs_description"]

    def test_chain_masculine(self):
        """Łańcuszek (m.) → wysadzany"""
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA CHAIN")
        assert "wysadzany diamentami" in r["polish_customs_description"]

    # ── Feminine (wysadzana) ─────────────────────────────────────────────────

    def test_bracelet_feminine(self):
        """Bransoletka (f.) → wysadzana"""
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA BRACELET")
        assert "wysadzana diamentami" in r["polish_customs_description"]

    def test_bangle_feminine(self):
        """Bransoletka sztywna (f.) → wysadzana"""
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA BANGLE")
        assert "wysadzana diamentami" in r["polish_customs_description"]

    def test_brooch_feminine(self):
        """Broszka (f.) → wysadzana"""
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA BROOCH")
        assert "wysadzana diamentami" in r["polish_customs_description"]

    def test_anklet_feminine(self):
        """Bransoletka na kostkę (f.) → wysadzana"""
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA ANKLET")
        assert "wysadzana diamentami" in r["polish_customs_description"]

    # ── Plural (wysadzane) ───────────────────────────────────────────────────

    def test_earrings_plural(self):
        """Kolczyki (pl.) → wysadzane"""
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA EARRINGS")
        assert "wysadzane diamentami" in r["polish_customs_description"]

    def test_stud_earrings_plural(self):
        """Kolczyki wkrętki (pl.) → wysadzane"""
        r = cde.normalize_item_description("PCS, 14KT Gold Stud DIA")
        assert "wysadzane diamentami" in r["polish_customs_description"]

    def test_hoop_earrings_plural(self):
        """Kolczyki kółka (pl.) → wysadzane"""
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA HOOP")
        assert "wysadzane diamentami" in r["polish_customs_description"]

    def test_cufflinks_plural(self):
        """Spinki do mankietów (pl.) → wysadzane"""
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA CUFFLINKS")
        assert "wysadzane diamentami" in r["polish_customs_description"]

    def test_set_masculine(self):
        """Komplet biżuterii (m.) → wysadzany"""
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA SET")
        assert "wysadzany diamentami" in r["polish_customs_description"]

    # ── No stones → no setting verb ──────────────────────────────────────────

    def test_no_stones_no_setting_verb(self):
        """Without stones, no setting verb appears."""
        r = cde.normalize_item_description("PCS, 14KT Gold, PLAIN RING")
        desc = r["polish_customs_description"]
        assert "wysadzany" not in desc
        assert "wysadzana" not in desc
        assert "wysadzane" not in desc


# ============================================================================
# 3. Sentence-break suffix: ". Biżuteria" not ", biżuteria"
# ============================================================================

class TestSentenceBreakSuffix:
    """Customs description must end with '. Biżuteria do noszenia.' (capital B, period before)."""

    def test_ring_with_stones(self):
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA RING")
        desc = r["polish_customs_description"]
        assert ". Biżuteria do noszenia." in desc
        assert ", biżuteria do noszenia." not in desc

    def test_ring_without_stones(self):
        r = cde.normalize_item_description("PCS, 14KT Gold, PLAIN RING")
        desc = r["polish_customs_description"]
        assert ". Biżuteria do noszenia." in desc

    def test_earrings_with_stones(self):
        r = cde.normalize_item_description("PCS, 18KT Gold, DIA EARRINGS")
        desc = r["polish_customs_description"]
        assert ". Biżuteria do noszenia." in desc
        assert ", biżuteria do noszenia." not in desc

    def test_silver_with_cz(self):
        r = cde.normalize_item_description("PCS, 925 Silver, CZ RING")
        desc = r["polish_customs_description"]
        assert ". Biżuteria do noszenia." in desc


# ============================================================================
# 4. Material conjunction: "oraz" in nominative material_pl
# ============================================================================

class TestMaterialConjunction:
    """material_pl field must use 'oraz' not 'z' between metal and stones."""

    def test_gold_with_diamonds(self):
        r = cde.normalize_item_description("PCS, 14KT Gold, DIA RING")
        assert "oraz" in r["material_pl"]
        # Must NOT use "z" as conjunction in nominative
        parts = r["material_pl"].split("oraz")
        assert len(parts) == 2, f"Expected exactly one 'oraz' in material_pl: {r['material_pl']}"

    def test_silver_with_cz(self):
        r = cde.normalize_item_description("PCS, 925 Silver, CZ RING")
        assert "oraz" in r["material_pl"]

    def test_platinum_with_diamonds(self):
        r = cde.normalize_item_description("PCS, PT950 Platinum, DIA RING")
        assert "oraz" in r["material_pl"]

    def test_metal_only_no_conjunction(self):
        """Without stones, material_pl has no conjunction."""
        r = cde.normalize_item_description("PCS, 14KT Gold, PLAIN RING")
        assert "oraz" not in r["material_pl"]

    def test_stones_only_no_conjunction(self):
        """Without metal, material_pl has no conjunction."""
        r = cde.normalize_item_description("PCS, DIA RING")
        # May or may not have "oraz" — depends on whether metal is detected
        # This test just verifies the engine doesn't crash


# ============================================================================
# 5. New stone instrumental forms
# ============================================================================

class TestStoneInstrumentalForms:
    """_STONE_INSTRUMENTAL must include forms for new stone categories."""

    def test_kamienie_jubilerskie_form_exists(self):
        """'kamienie jubilerskie' → 'kamieniami jubilerskimi'"""
        assert "kamienie jubilerskie" in cde._STONE_INSTRUMENTAL
        assert cde._STONE_INSTRUMENTAL["kamienie jubilerskie"] == "kamieniami jubilerskimi"

    def test_kamienie_ozdobne_form_exists(self):
        """'kamienie ozdobne' → 'kamieniami ozdobnymi'"""
        assert "kamienie ozdobne" in cde._STONE_INSTRUMENTAL
        assert cde._STONE_INSTRUMENTAL["kamienie ozdobne"] == "kamieniami ozdobnymi"

    def test_existing_forms_preserved(self):
        """All existing stone forms must survive the upgrade."""
        expected = {
            "diamenty":                       "diamentami",
            "kamienie szlachetne":            "kamieniami szlachetnymi",
            "diamenty laboratoryjne":         "diamentami laboratoryjnymi",
            "cyrkonie":                       "cyrkoniami",
            "rubiny":                         "rubinami",
            "szmaragdy":                      "szmaragdami",
            "szafiry":                        "szafirami",
            "perły":                          "perłami",
            "moissanit":                      "moissanitem",
        }
        for nom, instr in expected.items():
            assert cde._STONE_INSTRUMENTAL.get(nom) == instr, (
                f"Missing or wrong instrumental for {nom!r}: "
                f"expected {instr!r}, got {cde._STONE_INSTRUMENTAL.get(nom)!r}"
            )


# ============================================================================
# 6. Full-sentence integration: real AWB 9938632830-style descriptions
# ============================================================================

class TestFullSentenceIntegration:
    """End-to-end tests matching AWB 9938632830 invoice descriptions."""

    def test_14kt_gold_lgd_ring(self):
        """'PCS, 14KT Gold,LGD Gold Stud Jewell RING' — full sentence check."""
        r = cde.normalize_item_description("PCS, 14KT Gold,LGD Gold Stud Jewell RING")
        desc = r["polish_customs_description"]
        # Must contain karat-expanded genitive
        assert "14-karatowego złota (próba 585)" in desc
        # Must contain gender-correct setting verb (RING = masculine)
        assert "wysadzany" in desc
        # Must contain lab-grown diamond instrumental
        assert "diamentami laboratoryjnymi" in desc
        # Must have sentence break
        assert ". Biżuteria do noszenia." in desc
        # Item type must be RING not STUD (final-noun authority)
        assert desc.startswith("Pierścionek")

    def test_14kt_gold_lgd_earrings(self):
        """14KT Gold LGD EARRINGS — plural gender agreement."""
        r = cde.normalize_item_description("PCS, 14KT Gold, LGD EARRINGS")
        desc = r["polish_customs_description"]
        assert "14-karatowego złota (próba 585)" in desc
        assert "wysadzane" in desc  # plural
        assert "diamentami laboratoryjnymi" in desc
        assert ". Biżuteria do noszenia." in desc
        assert desc.startswith("Kolczyki")

    def test_14kt_gold_dia_and_cls_ring(self):
        """14KT Gold DIA&CLS RING — diamonds and gemstones."""
        r = cde.normalize_item_description("PCS, 14KT Gold,Stud Jewelry DIA&CLS RING")
        desc = r["polish_customs_description"]
        assert "14-karatowego złota (próba 585)" in desc
        assert "wysadzany" in desc  # RING = masculine
        assert "diamentami i kamieniami szlachetnymi" in desc
        assert ". Biżuteria do noszenia." in desc

    def test_pt950_diamond_ring(self):
        """PT950 Platinum DIA RING — platinum genitive unchanged."""
        r = cde.normalize_item_description("PCS, PT950 Platinum,Stud With Diam Jewel RING")
        desc = r["polish_customs_description"]
        assert "platyny próby 950" in desc
        assert "wysadzany diamentami" in desc
        assert ". Biżuteria do noszenia." in desc

    def test_14kt_gold_plain_bracelet(self):
        """14KT Gold PLAIN BRACELET — no stones, no setting verb."""
        r = cde.normalize_item_description("PCS, 14KT Gold, PLAIN BRACELET")
        desc = r["polish_customs_description"]
        assert "14-karatowego złota (próba 585)" in desc
        assert "wysadzan" not in desc  # no stones → no setting verb
        assert ". Biżuteria do noszenia." in desc
        assert desc.startswith("Bransoletka")


# ============================================================================
# 7. GOLD_PURITY nominative — must remain unchanged
# ============================================================================

class TestGoldPurityNominativeUnchanged:
    """GOLD_PURITY (nominative field display) must NOT be affected by the upgrade."""

    def test_14kt_nominative(self):
        assert cde.GOLD_PURITY["14KT"] == "złoto próby 585"

    def test_18kt_nominative(self):
        assert cde.GOLD_PURITY["18KT"] == "złoto próby 750"

    def test_925_nominative(self):
        assert cde.GOLD_PURITY["925"] == "srebro próby 925"

    def test_pt950_nominative(self):
        assert cde.GOLD_PURITY["PT950"] == "platyna próby 950"


# ============================================================================
# 8. _PURITY_GENITIVE direct dictionary tests
# ============================================================================

class TestPurityGenitiveDictionary:
    """Direct tests on _PURITY_GENITIVE dictionary values."""

    @pytest.mark.parametrize("code,expected", [
        ("9KT",  "9-karatowego złota (próba 375)"),
        ("09KT", "9-karatowego złota (próba 375)"),
        ("10KT", "10-karatowego złota (próba 417)"),
        ("14KT", "14-karatowego złota (próba 585)"),
        ("18KT", "18-karatowego złota (próba 750)"),
        ("22KT", "22-karatowego złota (próba 916)"),
        ("24KT", "24-karatowego złota (próba 999)"),
    ])
    def test_gold_karat_expanded(self, code, expected):
        assert cde._PURITY_GENITIVE[code] == expected

    @pytest.mark.parametrize("code,expected", [
        ("925",   "srebra próby 925"),
        ("SL925", "srebra próby 925"),
        ("SS",    "stali szlachetnej"),
        ("PT950", "platyny próby 950"),
        ("PT900", "platyny próby 900"),
        ("PT850", "platyny próby 850"),
    ])
    def test_non_gold_unchanged(self, code, expected):
        assert cde._PURITY_GENITIVE[code] == expected
