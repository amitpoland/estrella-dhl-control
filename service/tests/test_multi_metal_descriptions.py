"""
test_multi_metal_descriptions.py — material-component semantics.

Governing invariant (campaign "repair product-description authority"):

    Normalization may improve language.
    It may NEVER remove a material component present in the source.

Two independent single-metal parsers used to keep exactly ONE metal per row
and silently discard the rest:

  * commercial path — pz_import_processor.normalize_family() / get_karat()
    returned one family + one purity token, so
    "18KT Gold,LGD Stud PT950 Com" rendered as platinum-only.
  * customs path — customs_description_engine.normalize_item_description()
    scanned GOLD_PURITY with a first-match-wins ``break``; the dict is
    ordered gold → silver → steel → platinum, so gold always won and
    "SILVER Plain 10kt Gold Com" rendered as gold-only.

Both now consume ONE shared parser — description_grammar.parse_material_components().

Everything here is written against GENERIC strings.  No draft id, no
invoice number, no product code is asserted anywhere: the defect is a
workflow class, not four bad rows (Lesson I).
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
import pz_import_processor as pz

# The real consumer's set — the one that decides whether a row raises an
# operator proposal (customs_desc_checker.py:171).  Imported, never copied.
from app.services.customs_desc_checker import FORBIDDEN_MATERIAL_PL


# ═══════════════════════════════════════════════════════════════════════════
# Fixture corpus — nine material classes
# ═══════════════════════════════════════════════════════════════════════════
#
# Raw strings follow real supplier grammar (comma-jammed, mixed case,
# "Com" = combination) but carry no real invoice identity.

RAW_GOLD_ONLY      = "PCS, 18KT Gold,LGD Gold Stud Jewell RING"
RAW_SILVER_925     = "PCS, SL925 Silver Plain Jewell RING"
RAW_SILVER_BARE    = "PCS, SILVER Plain Jewell RING"
RAW_PLATINUM_ONLY  = "PCS, PT950 Plain Jewell RING"
RAW_GOLD_PLATINUM  = "PCS, 18KT Gold,LGD Stud PT950 Com Jewell RING"
RAW_SILVER_GOLD    = "PCS, SILVER Plain 10kt Gold Com Jewell RING"
RAW_LGD_GOLD       = "PCS, 09KT Gold,LGD Gold Stud Jewell RING"
RAW_LGD_MIXED      = "PCS, 14KT Gold,LGD Stud SL925 Com Jewell BRACELET"
RAW_NATURAL_DIA    = "PCS, 14KT Gold NAT DIA Stud Jewell RING"
RAW_AMBIGUOUS      = "PCS, Fancy Jewell RING"
RAW_TWO_METALS_NO_COM = "PCS, 18KT Gold PT950 Stud Jewell RING"

ALL_RAW = [
    RAW_GOLD_ONLY, RAW_SILVER_925, RAW_SILVER_BARE, RAW_PLATINUM_ONLY,
    RAW_GOLD_PLATINUM, RAW_SILVER_GOLD, RAW_LGD_GOLD, RAW_LGD_MIXED,
    RAW_NATURAL_DIA,
]


def _keys(raw: str) -> list[str]:
    return [c.purity_key for c in dg.parse_material_components(raw).components]


# ═══════════════════════════════════════════════════════════════════════════
# 1. The shared parser — component identification
# ═══════════════════════════════════════════════════════════════════════════

class TestParseMaterialComponents:

    def test_single_gold(self):
        p = dg.parse_material_components(RAW_GOLD_ONLY)
        assert [c.purity_key for c in p.components] == ["18KT"]
        assert p.construction == "single"
        assert p.description_review_required is False

    def test_single_silver_with_purity(self):
        p = dg.parse_material_components(RAW_SILVER_925)
        assert [c.purity_key for c in p.components] == ["SL925"]
        assert p.components[0].has_purity is True

    def test_bare_silver_carries_no_purity(self):
        """SILVER alone is a metal word. It is NOT evidence of próba 925."""
        p = dg.parse_material_components(RAW_SILVER_BARE)
        assert [c.purity_key for c in p.components] == ["SILVER"]
        assert p.components[0].has_purity is False
        assert "925" not in p.components[0].purity_nominative_pl
        assert "925" not in p.components[0].purity_genitive_pl

    def test_single_platinum(self):
        assert _keys(RAW_PLATINUM_ONLY) == ["PT950"]

    def test_gold_plus_platinum_keeps_both_in_source_order(self):
        p = dg.parse_material_components(RAW_GOLD_PLATINUM)
        assert [c.purity_key for c in p.components] == ["18KT", "PT950"]
        assert p.construction == "combination"
        assert p.description_review_required is False

    def test_silver_plus_gold_keeps_both_in_source_order(self):
        p = dg.parse_material_components(RAW_SILVER_GOLD)
        assert [c.purity_key for c in p.components] == ["SILVER", "10KT"]
        assert p.construction == "combination"

    def test_lgd_gold(self):
        p = dg.parse_material_components(RAW_LGD_GOLD)
        assert [c.purity_key for c in p.components] == ["09KT"]
        assert p.natural_or_lab == "lab_grown"

    def test_lgd_mixed_metal(self):
        p = dg.parse_material_components(RAW_LGD_MIXED)
        assert [c.purity_key for c in p.components] == ["14KT", "SL925"]
        assert p.construction == "combination"
        assert p.natural_or_lab == "lab_grown"

    def test_natural_diamond_plus_metal(self):
        p = dg.parse_material_components(RAW_NATURAL_DIA)
        assert [c.purity_key for c in p.components] == ["14KT"]
        assert p.natural_or_lab == "natural"

    def test_unrecognized_material_is_surfaced_not_guessed(self):
        p = dg.parse_material_components(RAW_AMBIGUOUS)
        assert p.components == []
        assert p.description_review_required is True
        assert p.review_reason == "no_material_recognized"

    def test_two_metals_without_combination_marker_is_ambiguous(self):
        """Surface the ambiguity — but still keep BOTH metals."""
        p = dg.parse_material_components(RAW_TWO_METALS_NO_COM)
        assert [c.purity_key for c in p.components] == ["18KT", "PT950"]
        assert p.description_review_required is True
        assert p.review_reason == "multiple_materials_without_combination_marker"

    def test_duplicate_purity_spelling_is_deduped(self):
        """9KT and 09KT are the same próba — one component, not two."""
        p = dg.parse_material_components("PCS, 09KT Gold 9KT Gold Jewell RING")
        assert len(p.components) == 1

    def test_longest_token_wins(self):
        """SL925 must beat the bare 925 substring; PT950 must not read as 950."""
        assert _keys("PCS, SL925 Plain Jewell RING") == ["SL925"]
        assert _keys("PCS, PT950 Plain Jewell RING") == ["PT950"]


# ═══════════════════════════════════════════════════════════════════════════
# 2. The completeness invariant
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckMaterialCompleteness:

    @pytest.mark.parametrize("raw", ALL_RAW)
    def test_generated_pair_is_complete(self, raw):
        meta = pz.build_item_meta(raw, "RING")
        ok, reason = dg.check_material_completeness(
            meta["parsed_material"],
            pz.build_pl_name(meta),
            pz.build_en_name(meta),
        )
        assert ok is True, reason

    def test_truncated_description_fails_the_invariant(self):
        parsed = dg.parse_material_components(RAW_GOLD_PLATINUM)
        ok, reason = dg.check_material_completeness(
            parsed,
            "pierścionek ze złota próby 18 karatów",      # platinum dropped
            "Lab Grown Diamond Studded 18KT Gold Jewellery RING",
        )
        assert ok is False
        assert "platin" in reason.lower() or "platyn" in reason.lower()

    def test_empty_description_fails_the_invariant(self):
        parsed = dg.parse_material_components(RAW_SILVER_GOLD)
        ok, _ = dg.check_material_completeness(parsed, "", "")
        assert ok is False

    def test_no_recognized_material_cannot_fail_completeness(self):
        """Nothing was recognized, so nothing can be lost — review flag covers it."""
        parsed = dg.parse_material_components(RAW_AMBIGUOUS)
        ok, _ = dg.check_material_completeness(parsed, "pierścionek", "Jewellery RING")
        assert ok is True


# ═══════════════════════════════════════════════════════════════════════════
# 3. Commercial renderer — pz_import_processor
# ═══════════════════════════════════════════════════════════════════════════

class TestCommercialSingleMetalIsByteStable:
    """Single-metal output must not move — golden rows depend on it."""

    def test_gold_lgd_en(self):
        meta = pz.build_item_meta(RAW_GOLD_ONLY, "RING")
        assert pz.build_en_name(meta) == "Lab Grown Diamond Studded 18KT Gold Jewellery RING"

    def test_gold_lgd_pl(self):
        meta = pz.build_item_meta(RAW_GOLD_ONLY, "RING")
        assert pz.build_pl_name(meta) == (
            "pierścionek ze złota próby 18 karatów z diamentami hodowanymi laboratoryjnie"
        )

    def test_silver_sl925_en(self):
        meta = pz.build_item_meta(RAW_SILVER_925, "RING")
        assert pz.build_en_name(meta) == "Silver SL925 Jewellery RING"

    def test_silver_sl925_pl(self):
        meta = pz.build_item_meta(RAW_SILVER_925, "RING")
        assert pz.build_pl_name(meta) == "pierścionek srebrny próby 925"

    def test_platinum_plain_en(self):
        meta = pz.build_item_meta(RAW_PLATINUM_ONLY, "RING")
        assert pz.build_en_name(meta) == "Plain PT950 Platinum Jewellery RING"

    def test_platinum_plain_pl(self):
        meta = pz.build_item_meta(RAW_PLATINUM_ONLY, "RING")
        assert pz.build_pl_name(meta) == "pierścionek z platyny próby 950"

    def test_natural_diamond_gold(self):
        meta = pz.build_item_meta(RAW_NATURAL_DIA, "RING")
        assert pz.build_en_name(meta) == "Diamond Studded 14KT Gold Jewellery RING"
        assert pz.build_pl_name(meta) == (
            "pierścionek ze złota próby 14 karatów wysadzany diamentami"
        )


class TestCommercialBareSilverInventsNothing:
    """The source said SILVER. It did not say 925."""

    def test_pl_has_no_invented_purity(self):
        meta = pz.build_item_meta(RAW_SILVER_BARE, "RING")
        pl = pz.build_pl_name(meta)
        assert "925" not in pl
        assert "srebr" in pl

    def test_en_has_no_invented_purity(self):
        meta = pz.build_item_meta(RAW_SILVER_BARE, "RING")
        en = pz.build_en_name(meta)
        assert "925" not in en
        assert "SL925" not in en
        assert "Silver" in en


class TestCommercialCombination:

    def test_gold_platinum_en_keeps_both(self):
        meta = pz.build_item_meta(RAW_GOLD_PLATINUM, "RING")
        assert pz.build_en_name(meta) == (
            "Lab Grown Diamond Studded 18KT Gold & PT950 Platinum Jewellery RING"
        )

    def test_gold_platinum_pl_keeps_both(self):
        meta = pz.build_item_meta(RAW_GOLD_PLATINUM, "RING")
        assert pz.build_pl_name(meta) == (
            "pierścionek ze złota próby 18 karatów i z platyny próby 950 "
            "z diamentami hodowanymi laboratoryjnie"
        )

    def test_silver_gold_en_keeps_both(self):
        meta = pz.build_item_meta(RAW_SILVER_GOLD, "RING")
        en = pz.build_en_name(meta)
        assert "Silver" in en and "10KT Gold" in en
        assert "925" not in en

    def test_silver_gold_pl_keeps_both(self):
        meta = pz.build_item_meta(RAW_SILVER_GOLD, "RING")
        pl = pz.build_pl_name(meta)
        assert "srebr" in pl and "złot" in pl
        assert "925" not in pl

    def test_combination_family_is_not_collapsed_to_silver(self):
        """The old silver-override forced family='Silver Plain' and erased gold."""
        meta = pz.build_item_meta(RAW_SILVER_GOLD, "RING")
        assert meta["family"] != "Silver Plain"

    def test_lgd_mixed_metal_keeps_both(self):
        meta = pz.build_item_meta(RAW_LGD_MIXED, "BRACELET")
        pl = pz.build_pl_name(meta)
        en = pz.build_en_name(meta)
        assert "złot" in pl and "srebr" in pl
        assert "14KT Gold" in en and "Silver" in en


class TestReviewFlagReachesTheItem:

    def test_unrecognized_material_flags_review(self):
        meta = pz.build_item_meta(RAW_AMBIGUOUS, "RING")
        assert meta["description_review_required"] is True

    def test_recognized_single_metal_does_not_flag_review(self):
        meta = pz.build_item_meta(RAW_GOLD_ONLY, "RING")
        assert meta["description_review_required"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 4. Cross-line contamination
# ═══════════════════════════════════════════════════════════════════════════

class TestNoCrossLineContamination:
    """Parsing one line must not change what another line renders."""

    def test_alternating_parse_is_stable(self):
        a1 = pz.build_pl_name(pz.build_item_meta(RAW_GOLD_ONLY, "RING"))
        b1 = pz.build_pl_name(pz.build_item_meta(RAW_GOLD_PLATINUM, "RING"))
        a2 = pz.build_pl_name(pz.build_item_meta(RAW_GOLD_ONLY, "RING"))
        b2 = pz.build_pl_name(pz.build_item_meta(RAW_GOLD_PLATINUM, "RING"))
        assert a1 == a2
        assert b1 == b2
        assert a1 != b1

    def test_parsed_material_is_not_shared_between_items(self):
        m1 = pz.build_item_meta(RAW_GOLD_ONLY, "RING")
        m2 = pz.build_item_meta(RAW_GOLD_PLATINUM, "RING")
        assert m1["parsed_material"] is not m2["parsed_material"]
        assert m1["parsed_material"].components is not m2["parsed_material"].components

    def test_batch_order_does_not_matter(self):
        forward = [pz.build_en_name(pz.build_item_meta(r, "RING")) for r in ALL_RAW]
        backward = [pz.build_en_name(pz.build_item_meta(r, "RING")) for r in reversed(ALL_RAW)]
        assert forward == list(reversed(backward))


# ═══════════════════════════════════════════════════════════════════════════
# 5. Customs renderer — customs_description_engine
# ═══════════════════════════════════════════════════════════════════════════

class TestCustomsSingleMetalIsByteStable:

    def test_gold_lgd_customs_description(self):
        out = cde.normalize_item_description(RAW_GOLD_ONLY)
        assert out["gold_purity_raw"] == "18KT"
        assert out["gold_purity_pl"] == "złoto próby 750"
        assert out["polish_customs_description"] == (
            "Pierścionek z 18-karatowego złota (próba 750) "
            "wysadzany diamentami laboratoryjnymi. Biżuteria do noszenia."
        )

    def test_platinum_customs_description(self):
        out = cde.normalize_item_description(RAW_PLATINUM_ONLY)
        assert out["gold_purity_raw"] == "PT950"
        assert out["gold_purity_pl"] == "platyna próby 950"


class TestCustomsCombination:

    def test_gold_platinum_keeps_both_metals(self):
        out = cde.normalize_item_description(RAW_GOLD_PLATINUM)
        assert out["material_components"] == ["18KT", "PT950"]
        assert out["construction"] == "combination"
        assert "złot" in out["gold_purity_pl"] and "platyn" in out["gold_purity_pl"]

    def test_gold_platinum_polish_customs_description(self):
        out = cde.normalize_item_description(RAW_GOLD_PLATINUM)
        assert out["polish_customs_description"] == (
            "Pierścionek z 18-karatowego złota (próba 750) i z platyny próby 950 "
            "wysadzany diamentami laboratoryjnymi. Biżuteria do noszenia."
        )

    def test_silver_gold_keeps_both_metals(self):
        """GOLD_PURITY is ordered gold-first — silver used to vanish here."""
        out = cde.normalize_item_description(RAW_SILVER_GOLD)
        assert out["material_components"] == ["SILVER", "10KT"]
        assert "srebr" in out["polish_customs_description"]
        assert "złot" in out["polish_customs_description"]

    def test_silver_gold_invents_no_purity(self):
        out = cde.normalize_item_description(RAW_SILVER_GOLD)
        assert "925" not in out["polish_customs_description"]
        assert "925" not in out["material_pl"]

    def test_product_description_pl_keeps_both_metals(self):
        out = cde.normalize_item_description(RAW_GOLD_PLATINUM)
        assert "złot" in out["product_description_pl"]
        assert "platyn" in out["product_description_pl"]

    def test_product_description_en_keeps_both_metals(self):
        out = cde.normalize_item_description(RAW_GOLD_PLATINUM)
        assert "18KT Gold" in out["product_description_en"]
        assert "Platinum" in out["product_description_en"]

    def test_short_description_keeps_both_metals(self):
        out = cde.normalize_item_description(RAW_GOLD_PLATINUM)
        assert "Au750" in out["short_description"]
        assert "Pt950" in out["short_description"]

    def test_review_flag_is_exposed(self):
        assert cde.normalize_item_description(RAW_AMBIGUOUS)["description_review_required"] is True
        assert cde.normalize_item_description(RAW_GOLD_ONLY)["description_review_required"] is False

    def test_resolver_facts_still_win_over_the_parser(self):
        """When the resolver has a DB hit the engine must not re-parse metal."""
        out = cde.normalize_item_description(
            RAW_GOLD_PLATINUM,
            resolved_facts={
                "canonical_metal": "platinum",
                "material_pl": "platyna próby 950",
                "purity_gen": "platyny próby 950",
            },
        )
        assert out["gold_purity_pl"] == "platyna próby 950"


# ═══════════════════════════════════════════════════════════════════════════
# 6. Cross-path agreement — the "PZ and Proforma disagree" hard-HOLD
# ═══════════════════════════════════════════════════════════════════════════

class TestCommercialAndCustomsAgreeOnMaterials:

    @pytest.mark.parametrize("raw", ALL_RAW)
    def test_same_metal_set_on_both_paths(self, raw):
        commercial = [c.purity_key for c in dg.parse_material_components(raw).components]
        customs = cde.normalize_item_description(raw)["material_components"]
        assert commercial == customs

    @pytest.mark.parametrize("raw", ALL_RAW)
    def test_customs_output_satisfies_the_invariant(self, raw):
        """A rendered customs row states every material the source states.

        Two branches, and no third one.  Either the engine renders the row —
        and then EVERY recognized material must appear, which is the whole
        point of this campaign — or it declares the row unresolved by emitting
        a `material_pl` from `customs_desc_checker.FORBIDDEN_MATERIAL_PL`,
        which is what raises the operator proposal at
        `customs_desc_checker.py:171`.  Declared non-resolution is not silent
        loss; it is the "surface review rather than manufacture a description"
        rule.  The customs register always states a fineness, so a row whose
        only material carries none (bare "SILVER") takes the second branch
        rather than acquiring a próba it never stated.
        """
        parsed = dg.parse_material_components(raw)
        out = cde.normalize_item_description(raw)

        if (out.get("material_pl") or "").strip() in FORBIDDEN_MATERIAL_PL:
            # Unresolved is allowed, but it must be unresolved *loudly*: no
            # metal may be named in the rendered text either.
            rendered = (out["product_description_pl"] + " "
                        + out["product_description_en"]).lower()
            for c in parsed.components:
                assert not (c.pl_stem and c.pl_stem in rendered), (
                    f"{raw!r} is flagged unresolved yet still names "
                    f"{c.purity_key} in the rendered description"
                )
            return

        ok, reason = dg.check_material_completeness(
            parsed, out["product_description_pl"], out["product_description_en"]
        )
        assert ok is True, reason
