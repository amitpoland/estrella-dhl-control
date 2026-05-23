"""Phase 5 — Product / Finishing Intelligence tests.

Covers:
  - _desc_quality(): none / poor / ok / good classification
  - _design_near_duplicates(): cluster detection, generic token stripping
  - _metal_stone_compat_warnings(): silver+high-value stone advisory, gold=no-warn
  - ProductLocal coverage percentage in _score_products()
  - Finishing domain: stone_keyword_coverage_count + compat_warnings in details
  - generate_report() end-to-end with product_locals patch
  - Phase 4 regression: existing scoring contracts still hold
  - Source-grep: no INSERT/UPDATE/DELETE, no LLM/Anthropic calls
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from app.services.master_data_intelligence import (
    _desc_quality,
    _design_near_duplicates,
    _metal_stone_compat_warnings,
    _score_products,
    _score_finishing,
    generate_report,
    DomainScore,
    DuplicateCluster,
)


# ── Stubs (reuse shapes from Phase 4 tests) ───────────────────────────────────

@dataclass
class _Design:
    design_code: str
    display_name: Optional[str] = None
    product_ref: Optional[str] = None
    design_family: Optional[str] = None
    collection: Optional[str] = None
    metal: Optional[str] = None
    stone_summary: Optional[str] = None
    hs_code: Optional[str] = None
    unit: Optional[str] = None
    active: bool = True
    notes: Optional[str] = None


@dataclass
class _ProductLocal:
    product_code: str
    hs_code_override: Optional[str] = None
    unit_override: Optional[str] = None
    design_code_link: Optional[str] = None
    notes: Optional[str] = None
    origin_country: Optional[str] = None


@dataclass
class _Customer:
    bill_to_contractor_id: str
    bill_to_name: str
    country: str
    nip: Optional[str] = None
    vat_eu_number: Optional[str] = None
    vat_eu_valid: Optional[bool] = None
    vat_eu_validated_at: Optional[str] = None
    default_currency: Optional[str] = None
    vat_mode: Optional[int] = None
    bill_to_street: Optional[str] = None
    bill_to_city: Optional[str] = None
    bill_to_postal_code: Optional[str] = None
    bill_to_email: Optional[str] = None
    preferred_payment_method: Optional[str] = None
    short_code: Optional[str] = None
    client_type: Optional[str] = None
    kyc_status: Optional[str] = None
    id: Optional[int] = None


@dataclass
class _Supplier:
    supplier_code: str
    name: str
    country: str
    wfirma_id: Optional[str] = None
    vat_id: Optional[str] = None
    eori: Optional[str] = None
    contact_email: Optional[str] = None
    address: Optional[str] = None
    contact_phone: Optional[str] = None
    bank_account: Optional[str] = None
    id: Optional[int] = None


def _perfect_design(code: str = "D001") -> _Design:
    return _Design(
        design_code=code,
        display_name=f"Gold Diamond Ring {code}",
        product_ref=f"WF-{code}",
        design_family="rings",
        collection="spring2026",
        metal="gold",
        stone_summary="diamond 0.5ct",
        hs_code="71131910",
        unit="szt",
        notes="tested",
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. _desc_quality()
# ══════════════════════════════════════════════════════════════════════════════

class TestDescQuality:
    def test_none_returns_none(self):
        assert _desc_quality(None) == "none"

    def test_empty_string_returns_none(self):
        assert _desc_quality("") == "none"

    def test_whitespace_only_returns_none(self):
        assert _desc_quality("   ") == "none"

    def test_very_short_returns_poor(self):
        assert _desc_quality("Rng") == "poor"  # 3 chars < 5

    def test_exactly_4_chars_returns_poor(self):
        assert _desc_quality("Ring") == "poor"  # 4 chars < 5

    def test_plain_word_no_material_returns_ok(self):
        # 8 chars, no material word → ok
        assert _desc_quality("Pendant") == "ok"

    def test_material_plus_length_returns_good(self):
        # ≥10 chars and contains a material word
        assert _desc_quality("Gold Diamond Ring") == "good"

    def test_silver_pearl_bracelet_returns_good(self):
        assert _desc_quality("Silver Pearl Bracelet") == "good"

    def test_long_but_no_material_returns_ok(self):
        # ≥10 chars but no material word
        assert _desc_quality("Beautiful Necklace Set") == "ok"

    def test_material_word_short_text_returns_poor_or_ok(self):
        # "Gold" is 4 chars → poor (len < 5)
        assert _desc_quality("Gold") == "poor"
        # "Gold rng" is 8 chars, has material, but only 8 < 10 → ok (not good)
        assert _desc_quality("Gold rng") == "ok"

    def test_platinum_long_description_returns_good(self):
        assert _desc_quality("Platinum Solitaire Ring 18K") == "good"


# ══════════════════════════════════════════════════════════════════════════════
# 2. _design_near_duplicates()
# ══════════════════════════════════════════════════════════════════════════════

class TestDesignNearDuplicates:
    def test_empty_list_returns_no_clusters(self):
        assert _design_near_duplicates([]) == []

    def test_single_design_no_cluster(self):
        d = _Design("D001", display_name="Ruby Ring Gold")
        assert _design_near_duplicates([d]) == []

    def test_two_identical_names_form_cluster(self):
        d1 = _Design("D001", display_name="Ruby Gold Ring")
        d2 = _Design("D002", display_name="Ruby Gold Ring")
        clusters = _design_near_duplicates([d1, d2])
        assert len(clusters) == 1
        assert set(clusters[0].entity_keys) == {"D001", "D002"}
        assert clusters[0].probability == 0.80

    def test_generic_tokens_stripped_before_clustering(self):
        # Both have "ring" stripped → same key → cluster
        d1 = _Design("D001", display_name="Gold Diamond Ring")
        d2 = _Design("D002", display_name="Diamond Gold Ring")
        clusters = _design_near_duplicates([d1, d2])
        # After stripping "ring" generic token and normalizing, both reduce to same key
        assert len(clusters) == 1

    def test_different_meaningful_names_no_cluster(self):
        d1 = _Design("D001", display_name="Ruby Gold Pendant")
        d2 = _Design("D002", display_name="Emerald Silver Bracelet")
        clusters = _design_near_duplicates([d1, d2])
        assert len(clusters) == 0

    def test_cluster_key_starts_with_name_prefix(self):
        d1 = _Design("D001", display_name="Gold Sapphire Ring")
        d2 = _Design("D002", display_name="Gold Sapphire Ring")
        clusters = _design_near_duplicates([d1, d2])
        assert len(clusters) == 1
        assert clusters[0].key.startswith("name:")

    def test_three_designs_same_name_one_cluster(self):
        designs = [
            _Design(f"D{i:03d}", display_name="Diamond Gold Bracelet")
            for i in range(3)
        ]
        clusters = _design_near_duplicates(designs)
        assert len(clusters) == 1
        assert len(clusters[0].entity_keys) == 3

    def test_designs_without_display_name_skipped(self):
        d1 = _Design("D001", display_name=None)
        d2 = _Design("D002", display_name="")
        assert _design_near_duplicates([d1, d2]) == []


# ══════════════════════════════════════════════════════════════════════════════
# 3. _metal_stone_compat_warnings()
# ══════════════════════════════════════════════════════════════════════════════

class TestMetalStoneCompatWarnings:
    def test_silver_diamond_produces_warning(self):
        d = _Design("D001", metal="Silver", stone_summary="diamond 0.3ct")
        warnings = _metal_stone_compat_warnings([d])
        assert len(warnings) == 1
        assert warnings[0]["design_code"] == "D001"
        assert "diamond" in warnings[0]["matched_advisory_stones"]
        assert "silver" in warnings[0]["advisory"].lower()

    def test_gold_diamond_no_warning(self):
        d = _Design("D001", metal="Gold", stone_summary="diamond 0.5ct")
        warnings = _metal_stone_compat_warnings([d])
        assert len(warnings) == 0

    def test_gold_ruby_no_warning(self):
        d = _Design("D001", metal="gold 18k", stone_summary="ruby 1.0ct")
        warnings = _metal_stone_compat_warnings([d])
        assert len(warnings) == 0

    def test_platinum_sapphire_no_warning(self):
        d = _Design("D001", metal="Platinum", stone_summary="sapphire 0.8ct")
        warnings = _metal_stone_compat_warnings([d])
        assert len(warnings) == 0

    def test_silver_ruby_produces_warning(self):
        d = _Design("D001", metal="silver", stone_summary="ruby 0.5ct")
        warnings = _metal_stone_compat_warnings([d])
        assert len(warnings) == 1
        assert "ruby" in warnings[0]["matched_advisory_stones"]

    def test_silver_pearl_no_warning(self):
        # Pearl is not in _SILVER_ADVISORY_STONES
        d = _Design("D001", metal="silver", stone_summary="freshwater pearl")
        warnings = _metal_stone_compat_warnings([d])
        assert len(warnings) == 0

    def test_srebro_diamond_produces_warning(self):
        # Polish: srebro = silver
        d = _Design("D001", metal="Srebro 925", stone_summary="diamond 0.1ct")
        warnings = _metal_stone_compat_warnings([d])
        assert len(warnings) == 1

    def test_no_metal_no_warning(self):
        d = _Design("D001", metal=None, stone_summary="diamond 0.5ct")
        assert _metal_stone_compat_warnings([d]) == []

    def test_no_stone_no_warning(self):
        d = _Design("D001", metal="silver", stone_summary=None)
        assert _metal_stone_compat_warnings([d]) == []

    def test_empty_list_returns_empty(self):
        assert _metal_stone_compat_warnings([]) == []

    def test_multiple_designs_only_flagged_items_returned(self):
        designs = [
            _Design("D001", metal="silver", stone_summary="diamond 0.1ct"),   # warn
            _Design("D002", metal="gold", stone_summary="emerald 0.3ct"),      # no warn
            _Design("D003", metal="silver", stone_summary="emerald 0.5ct"),    # warn
        ]
        warnings = _metal_stone_compat_warnings(designs)
        assert len(warnings) == 2
        flagged = {w["design_code"] for w in warnings}
        assert flagged == {"D001", "D003"}


# ══════════════════════════════════════════════════════════════════════════════
# 4. _score_products() — ProductLocal coverage
# ══════════════════════════════════════════════════════════════════════════════

class TestProductLocalCoverage:
    def test_zero_coverage_when_no_product_locals(self):
        designs = [_perfect_design(f"D{i:03d}") for i in range(4)]
        score = _score_products(designs, product_locals=[])
        assert score.details["product_local_coverage_pct"] == 0.0
        assert score.details["product_local_linked_count"] == 0

    def test_zero_coverage_when_product_locals_none(self):
        designs = [_perfect_design(f"D{i:03d}") for i in range(3)]
        score = _score_products(designs, product_locals=None)
        assert score.details["product_local_coverage_pct"] == 0.0

    def test_partial_coverage_via_product_ref(self):
        # D001 has product_ref="WF-D001"; ProductLocal has product_code="WF-D001"
        d1 = _perfect_design("D001")  # product_ref = "WF-D001"
        d2 = _perfect_design("D002")  # product_ref = "WF-D002" — not in product_locals
        pl = _ProductLocal(product_code="WF-D001")
        score = _score_products([d1, d2], product_locals=[pl])
        assert score.details["product_local_linked_count"] == 1
        assert score.details["product_local_coverage_pct"] == 50.0

    def test_full_coverage_when_all_linked(self):
        designs = [_perfect_design(f"D{i:03d}") for i in range(3)]
        # product_refs are "WF-D000", "WF-D001", "WF-D002"
        product_locals = [_ProductLocal(product_code=f"WF-D{i:03d}") for i in range(3)]
        score = _score_products(designs, product_locals=product_locals)
        assert score.details["product_local_linked_count"] == 3
        assert score.details["product_local_coverage_pct"] == 100.0

    def test_coverage_recommendation_when_below_50_pct(self):
        # Only 1 of 4 linked → 25% → below 50% threshold
        d1 = _perfect_design("D001")
        d2 = _perfect_design("D002")
        d3 = _perfect_design("D003")
        d4 = _perfect_design("D004")
        pl = _ProductLocal(product_code="WF-D001")
        score = _score_products([d1, d2, d3, d4], product_locals=[pl])
        assert any("product_local" in r or "ProductLocal" in r for r in score.recommendations)

    def test_no_coverage_rec_when_no_product_locals_provided(self):
        # If product_locals is empty, the rec for coverage should not fire
        # (there's nothing to link to — recommendation only fires when product_locals exist)
        designs = [_perfect_design(f"D{i:03d}") for i in range(4)]
        score = _score_products(designs, product_locals=[])
        # Rec fires only when product_locals is non-empty
        product_local_recs = [r for r in score.recommendations if "ProductLocal" in r or "product_local" in r]
        assert len(product_local_recs) == 0


# ══════════════════════════════════════════════════════════════════════════════
# 5. _score_products() — description quality breakdown
# ══════════════════════════════════════════════════════════════════════════════

class TestDescriptionQualityBreakdown:
    def test_description_quality_dict_present_in_details(self):
        score = _score_products([_perfect_design()])
        assert "description_quality" in score.details
        dq = score.details["description_quality"]
        assert set(dq.keys()) == {"none", "poor", "ok", "good"}

    def test_all_good_designs_count_correctly(self):
        # "Gold Diamond Ring D001" → good (≥10 chars, has material)
        designs = [_perfect_design(f"D{i:03d}") for i in range(5)]
        score = _score_products(designs)
        dq = score.details["description_quality"]
        assert dq["good"] == 5
        assert dq["none"] == 0
        assert dq["poor"] == 0

    def test_missing_display_name_counted_as_none(self):
        d = _perfect_design("D001")
        d.display_name = None
        score = _score_products([d])
        dq = score.details["description_quality"]
        assert dq["none"] == 1

    def test_poor_quality_recommendation_fires(self):
        d = _perfect_design("D001")
        d.display_name = "Rng"  # 3 chars → poor
        score = _score_products([d])
        assert any("display" in r.lower() or "description" in r.lower() or "short" in r.lower()
                   for r in score.recommendations)


# ══════════════════════════════════════════════════════════════════════════════
# 6. _score_finishing() — Phase 5 additions
# ══════════════════════════════════════════════════════════════════════════════

class TestFinishingPhase5:
    def test_compat_warnings_in_details(self):
        d = _Design("D001", metal="silver", stone_summary="diamond 0.3ct",
                    unit="szt")
        score = _score_finishing([d])
        assert "metal_stone_compat_warnings" in score.details
        warnings = score.details["metal_stone_compat_warnings"]
        assert len(warnings) == 1
        assert warnings[0]["design_code"] == "D001"

    def test_no_compat_warnings_for_gold_diamond(self):
        d = _perfect_design("D001")  # gold + diamond
        score = _score_finishing([d])
        assert score.details["metal_stone_compat_warnings"] == []

    def test_compat_warnings_added_to_recommendations(self):
        d = _Design("D001", metal="Silver", stone_summary="emerald 0.5ct",
                    unit="szt")
        score = _score_finishing([d])
        assert any("combination" in r.lower() or "unusual" in r.lower() or "metal" in r.lower()
                   for r in score.recommendations)

    def test_stone_keyword_coverage_count_in_details(self):
        d1 = _perfect_design("D001")  # stone_summary has "diamond" → counted
        d2 = _Design("D002", metal="gold", stone_summary=None, unit="szt")  # no stone
        score = _score_finishing([d1, d2])
        assert "stone_keyword_coverage_count" in score.details
        assert score.details["stone_keyword_coverage_count"] == 1

    def test_stone_keyword_zero_when_no_stone_summaries(self):
        d1 = _Design("D001", metal="gold", unit="szt")
        d2 = _Design("D002", metal="silver", unit="szt")
        score = _score_finishing([d1, d2])
        assert score.details["stone_keyword_coverage_count"] == 0

    def test_stone_keyword_counted_for_various_stones(self):
        designs = [
            _Design("D001", metal="gold", stone_summary="pearl set", unit="szt"),
            _Design("D002", metal="silver", stone_summary="amethyst 1.2ct", unit="szt"),
            _Design("D003", metal="gold", unit="szt"),  # no stone
        ]
        score = _score_finishing(designs)
        assert score.details["stone_keyword_coverage_count"] == 2

    def test_compat_warning_advisory_appears_in_domain_advisory_text(self):
        d = _Design("D001", metal="Silver 925", stone_summary="sapphire 0.5ct",
                    unit="szt")
        score = _score_finishing([d])
        assert "1 compatibility advisory flag" in score.advisory


# ══════════════════════════════════════════════════════════════════════════════
# 7. generate_report() end-to-end with product_locals
# ══════════════════════════════════════════════════════════════════════════════

def _make_generate_report_patches(
    customers=None, designs=None, product_locals=None, suppliers=None
):
    """Context-manager helper — yields the fully patched generate_report context."""
    from contextlib import ExitStack
    from unittest.mock import patch as _patch

    customers = customers or []
    designs = designs or []
    product_locals = product_locals or []
    suppliers = suppliers or []

    stack = ExitStack()
    stack.enter_context(_patch(
        "app.services.master_data_intelligence.list_customers",
        return_value=customers,
    ))
    stack.enter_context(_patch(
        "app.services.master_data_intelligence.list_designs",
        return_value=designs,
    ))
    stack.enter_context(_patch(
        "app.services.master_data_intelligence.list_product_local",
        return_value=product_locals,
    ))
    stack.enter_context(_patch(
        "app.services.master_data_intelligence.list_suppliers",
        return_value=suppliers,
    ))
    stack.enter_context(_patch("app.services.master_data_intelligence.cm_init"))
    stack.enter_context(_patch("app.services.master_data_intelligence.md_init"))
    stack.enter_context(_patch("app.services.master_data_intelligence.supp_init"))
    return stack


def test_generate_report_product_local_coverage_flows_to_report():
    d1 = _perfect_design("D001")
    d2 = _perfect_design("D002")
    pl = _ProductLocal(product_code="WF-D001")

    with _make_generate_report_patches(designs=[d1, d2], product_locals=[pl]) as _:
        report = generate_report()

    product_details = report.product.details
    assert product_details["product_local_linked_count"] == 1
    assert product_details["product_local_coverage_pct"] == 50.0


def test_generate_report_finishing_compat_warnings_flow():
    d = _Design("D001", metal="Silver 925", stone_summary="emerald 0.5ct",
                hs_code="71131910", unit="szt", display_name="Silver Emerald Ring")
    with _make_generate_report_patches(designs=[d]) as _:
        report = generate_report()

    finishing_details = report.finishing.details
    assert len(finishing_details["metal_stone_compat_warnings"]) == 1


def test_generate_report_description_quality_in_product_domain():
    designs = [
        _Design("D001", display_name=None, hs_code="71131910", unit="szt"),  # none
        _Design("D002", display_name="Ring", hs_code="71131910", unit="szt"),  # poor
        _Design("D003", display_name="Gold Diamond Ring", hs_code="71131910", unit="szt"),  # good
    ]
    with _make_generate_report_patches(designs=designs) as _:
        report = generate_report()

    dq = report.product.details["description_quality"]
    assert dq["none"] == 1
    assert dq["poor"] == 1
    assert dq["good"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# 8. Phase 4 regression — existing scoring contracts preserved
# ══════════════════════════════════════════════════════════════════════════════

class TestPhase4Regression:
    """Verify Phase 5 additions don't break Phase 4 contracts."""

    def test_product_completeness_score_still_near_1_for_perfect_design(self):
        score = _score_products([_perfect_design()])
        assert score.completeness_score > 0.90, (
            f"Phase 4 regression: expected > 0.90, got {score.completeness_score}"
        )

    def test_finishing_completeness_still_near_1_for_gold_diamond(self):
        score = _score_finishing([_perfect_design()])
        assert score.completeness_score > 0.95, (
            f"Phase 4 regression: expected > 0.95, got {score.completeness_score}"
        )

    def test_product_missing_hs_code_still_flagged(self):
        d = _perfect_design()
        d.hs_code = None
        score = _score_products([d])
        assert score.details["missing_hs_code_count"] == 1

    def test_product_malformed_hs_still_flagged(self):
        d = _perfect_design()
        d.hs_code = "ABCDEF"
        score = _score_products([d])
        assert score.details["invalid_hs_code_count"] >= 1

    def test_finishing_non_standard_metal_still_flagged(self):
        d = _perfect_design()
        d.metal = "unobtanium"
        score = _score_finishing([d])
        assert score.details["non_standard_metal_count"] >= 1

    def test_finishing_missing_metal_still_drops_score(self):
        d = _perfect_design()
        d.metal = None
        score = _score_finishing([d])
        assert score.completeness_score < 0.65

    def test_report_llm_used_still_false(self):
        with _make_generate_report_patches() as _:
            report = generate_report()
        assert report.llm_used is False

    def test_report_advisory_class_still_R(self):
        with _make_generate_report_patches() as _:
            report = generate_report()
        assert report.advisory_class == "R"

    def test_product_entity_count_unchanged(self):
        designs = [_perfect_design(f"D{i:03d}") for i in range(5)]
        score = _score_products(designs)
        assert score.entity_count == 5

    def test_near_duplicate_clusters_in_duplicate_clusters_field(self):
        d1 = _Design("D001", display_name="Gold Diamond Ring")
        d2 = _Design("D002", display_name="Diamond Gold Ring")
        score = _score_products([d1, d2])
        # Both reduce to same normalized key → should produce a cluster
        assert len(score.duplicate_clusters) >= 1
        assert isinstance(score.duplicate_clusters[0], DuplicateCluster)


# ══════════════════════════════════════════════════════════════════════════════
# 9. Source-grep: no forbidden operations
# ══════════════════════════════════════════════════════════════════════════════

def _read_source() -> str:
    return Path("app/services/master_data_intelligence.py").read_text(encoding="utf-8")


def test_phase5_no_insert_update_delete():
    src = _read_source()
    for forbidden in (
        "conn.execute(\"INSERT",
        "conn.execute(\"UPDATE",
        "conn.execute(\"DELETE",
        ".execute(\"INSERT",
        ".execute(\"UPDATE",
        ".execute(\"DELETE",
    ):
        assert forbidden not in src, f"forbidden SQL write found: {forbidden!r}"


def test_phase5_no_anthropic_import():
    src = _read_source()
    assert "anthropic" not in src, "Anthropic import found in MDI service"
    assert "import anthropic" not in src


def test_phase5_no_ai_gateway_call():
    src = _read_source()
    assert "ai_gateway" not in src, "ai_gateway found in MDI service"


def test_phase5_no_openai_import():
    src = _read_source()
    assert "openai" not in src, "OpenAI import found in MDI service"


def test_phase5_llm_used_false_hardcoded():
    src = _read_source()
    assert "llm_used=False" in src
    assert "llm_used=True" not in src


def test_phase5_list_product_local_in_source():
    """Phase 5: list_product_local must be imported and used."""
    src = _read_source()
    assert "list_product_local" in src


def test_phase5_desc_quality_helper_in_source():
    src = _read_source()
    assert "_desc_quality" in src


def test_phase5_metal_stone_compat_in_source():
    src = _read_source()
    assert "_metal_stone_compat_warnings" in src
