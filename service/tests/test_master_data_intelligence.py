"""Phase 4 — Master Data Intelligence Foundation tests.

Covers:
  - Advisory-only output contract (no writes, no LLM)
  - Customer scoring logic
  - Product/Design scoring logic
  - Finishing scoring logic
  - Supplier scoring logic
  - Readiness cross-domain logic
  - Duplicate detection
  - Empty-DB graceful handling
  - Platform score calculation
  - API endpoint structure
  - Source-grep: no forbidden operations
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# ── Minimal stubs ─────────────────────────────────────────────────────────────

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _perfect_customer(idx: int = 1) -> _Customer:
    return _Customer(
        bill_to_contractor_id=str(100 + idx),
        bill_to_name=f"Client {idx} Sp. z o.o.",
        country="PL",
        nip=f"12345678{idx:02d}",
        vat_eu_number=f"PL12345678{idx:02d}",
        vat_eu_valid=True,
        default_currency="EUR",
        vat_mode=222,
        bill_to_street="ul. Testowa 1",
        bill_to_city="Warsaw",
        bill_to_postal_code="00-001",
        bill_to_email=f"client{idx}@example.com",
        preferred_payment_method="transfer",
        short_code=f"CLT{idx:03d}",
        client_type="client",
        kyc_status="approved",
    )


def _perfect_design(code: str = "D001") -> _Design:
    return _Design(
        design_code=code,
        display_name=f"Ring {code}",
        product_ref=f"WF-{code}",
        design_family="rings",
        collection="spring2026",
        metal="gold",
        stone_summary="diamond 0.5ct",
        hs_code="71131910",
        unit="szt",
        notes="tested",
    )


def _perfect_supplier(idx: int = 1) -> _Supplier:
    return _Supplier(
        supplier_code=f"SUPP{idx:03d}",
        name=f"Supplier {idx} GmbH",
        country="IN",
        wfirma_id=str(200 + idx),
        vat_id=f"IN123456789{idx}",
        eori=f"IN{idx:010d}",
        contact_email=f"supp{idx}@example.com",
        address="123 Supplier Street",
        contact_phone="+1234567890",
        bank_account="PL61109010140000071219812874",
    )


# ── Import shortcuts ──────────────────────────────────────────────────────────

from app.services.master_data_intelligence import (
    _score_customers,
    _score_products,
    _score_finishing,
    _score_suppliers,
    _score_readiness,
    generate_report,
    MasterDataIntelligenceReport,
    DomainScore,
)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Advisory-only contract
# ══════════════════════════════════════════════════════════════════════════════

def test_report_llm_used_is_false():
    with patch("app.services.master_data_intelligence.list_customers", return_value=[]):
        with patch("app.services.master_data_intelligence.list_designs", return_value=[]):
            with patch("app.services.master_data_intelligence.list_product_local", return_value=[]):
                with patch("app.services.master_data_intelligence.list_suppliers", return_value=[]):
                    with patch("app.services.master_data_intelligence.cm_init"):
                        with patch("app.services.master_data_intelligence.md_init"):
                            with patch("app.services.master_data_intelligence.supp_init"):
                                report = generate_report()
    assert report.llm_used is False


def test_report_advisory_class_is_R():
    with patch("app.services.master_data_intelligence.list_customers", return_value=[]):
        with patch("app.services.master_data_intelligence.list_designs", return_value=[]):
            with patch("app.services.master_data_intelligence.list_product_local", return_value=[]):
                with patch("app.services.master_data_intelligence.list_suppliers", return_value=[]):
                    with patch("app.services.master_data_intelligence.cm_init"):
                        with patch("app.services.master_data_intelligence.md_init"):
                            with patch("app.services.master_data_intelligence.supp_init"):
                                report = generate_report()
    assert report.advisory_class == "R"


def test_report_has_all_five_domains():
    with patch("app.services.master_data_intelligence.list_customers", return_value=[]):
        with patch("app.services.master_data_intelligence.list_designs", return_value=[]):
            with patch("app.services.master_data_intelligence.list_product_local", return_value=[]):
                with patch("app.services.master_data_intelligence.list_suppliers", return_value=[]):
                    with patch("app.services.master_data_intelligence.cm_init"):
                        with patch("app.services.master_data_intelligence.md_init"):
                            with patch("app.services.master_data_intelligence.supp_init"):
                                report = generate_report()
    d = report.to_dict()
    for domain in ("customer", "product", "finishing", "supplier", "readiness"):
        assert domain in d, f"missing domain {domain}"
        assert "completeness_score" in d[domain]
        assert "confidence" in d[domain]
        assert "advisory" in d[domain]
        assert "recommendations" in d[domain]


def test_report_to_dict_never_has_write_keys():
    """Output dict must never contain keys implying mutation."""
    with patch("app.services.master_data_intelligence.list_customers", return_value=[_perfect_customer()]):
        with patch("app.services.master_data_intelligence.list_designs", return_value=[_perfect_design()]):
            with patch("app.services.master_data_intelligence.list_product_local", return_value=[]):
                with patch("app.services.master_data_intelligence.list_suppliers", return_value=[_perfect_supplier()]):
                    with patch("app.services.master_data_intelligence.cm_init"):
                        with patch("app.services.master_data_intelligence.md_init"):
                            with patch("app.services.master_data_intelligence.supp_init"):
                                report = generate_report()
    d_str = str(report.to_dict())
    forbidden_keys = ("write", "modify", "execute", "correct", "approve", "create", "delete",
                      "INSERT", "UPDATE", "DELETE", "upsert")
    for key in forbidden_keys:
        assert key not in d_str, f"forbidden key '{key}' found in report output"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Empty-DB graceful handling
# ══════════════════════════════════════════════════════════════════════════════

def test_customer_score_empty_db():
    score = _score_customers([])
    assert score.entity_count == 0
    assert score.completeness_score == 0.0
    assert score.confidence == 0.0
    assert isinstance(score.advisory, str)
    assert len(score.advisory) > 0


def test_product_score_empty_db():
    score = _score_products([])
    assert score.entity_count == 0
    assert isinstance(score.recommendations, list)


def test_supplier_score_empty_db():
    score = _score_suppliers([])
    assert score.entity_count == 0
    assert isinstance(score.duplicate_clusters, list)


def test_readiness_score_empty_db():
    cs = _score_customers([])
    ps = _score_products([])
    ss = _score_suppliers([])
    rs = _score_readiness([], [], [], cs, ps, ss)
    assert rs.entity_count == 0
    assert isinstance(rs.blockers if hasattr(rs, "blockers") else rs.details.get("blockers", []), list)


# ══════════════════════════════════════════════════════════════════════════════
# 3. Customer scoring
# ══════════════════════════════════════════════════════════════════════════════

def test_perfect_customer_scores_near_1():
    score = _score_customers([_perfect_customer()])
    assert score.completeness_score > 0.95
    assert score.entity_count == 1


def test_customer_missing_nip_lowers_score():
    c = _perfect_customer()
    c.nip = None
    score = _score_customers([c])
    assert score.completeness_score < 0.95


def test_customer_missing_critical_fields_lower_confidence():
    c = _Customer(bill_to_contractor_id="1", bill_to_name="Test", country="PL")
    score = _score_customers([c])
    assert score.confidence < 0.8


def test_customer_field_gaps_listed_for_missing_fields():
    c = _Customer(bill_to_contractor_id="1", bill_to_name="Test", country="PL")
    score = _score_customers([c])
    gap_fields = {g.field for g in score.field_gaps}
    assert "nip" in gap_fields
    assert "default_currency" in gap_fields
    assert "vat_mode" in gap_fields


def test_customer_critical_gaps_sorted_first():
    c = _Customer(bill_to_contractor_id="1", bill_to_name="Test", country="PL")
    score = _score_customers([c])
    severities = [g.severity for g in score.field_gaps]
    # First gap must be critical
    assert severities[0] == "critical"


def test_customer_recommendations_not_empty_when_gaps_exist():
    c = _Customer(bill_to_contractor_id="1", bill_to_name="Test", country="PL")
    score = _score_customers([c])
    assert len(score.recommendations) > 0


# ══════════════════════════════════════════════════════════════════════════════
# 4. Customer duplicate detection
# ══════════════════════════════════════════════════════════════════════════════

def test_customer_duplicate_detected_by_nip():
    c1 = _perfect_customer(1)
    c1.nip = "1234567890"
    c2 = _perfect_customer(2)
    c2.nip = "1234567890"
    score = _score_customers([c1, c2])
    assert len(score.duplicate_clusters) >= 1
    nip_dups = [d for d in score.duplicate_clusters if d.key.startswith("nip:")]
    assert len(nip_dups) == 1
    assert nip_dups[0].probability >= 0.9


def test_customer_no_duplicate_when_nips_differ():
    c1 = _perfect_customer(1)
    c1.nip = "1111111111"
    c2 = _perfect_customer(2)
    c2.nip = "2222222222"
    score = _score_customers([c1, c2])
    nip_dups = [d for d in score.duplicate_clusters if d.key.startswith("nip:")]
    assert len(nip_dups) == 0


def test_customer_duplicate_by_normalized_name():
    c1 = _perfect_customer(1)
    c1.bill_to_name = "Acme Sp. z o.o."
    c1.nip = "1111111111"
    c2 = _perfect_customer(2)
    c2.bill_to_name = "Acme Sp z o.o."
    c2.nip = "2222222222"
    score = _score_customers([c1, c2])
    name_dups = [d for d in score.duplicate_clusters if d.key.startswith("name:")]
    assert len(name_dups) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# 5. Product scoring
# ══════════════════════════════════════════════════════════════════════════════

def test_perfect_design_scores_near_1():
    score = _score_products([_perfect_design()])
    assert score.completeness_score > 0.90


def test_design_missing_hs_code_lowers_score():
    d = _perfect_design()
    d.hs_code = None
    score = _score_products([d])
    assert score.completeness_score < 0.90


def test_design_malformed_hs_code_flagged():
    d = _perfect_design()
    d.hs_code = "ABCDEF"  # non-numeric
    score = _score_products([d])
    assert score.details.get("invalid_hs_code_count", 0) >= 1


def test_design_valid_hs_code_not_flagged():
    d = _perfect_design()
    d.hs_code = "71131910"
    score = _score_products([d])
    assert score.details.get("invalid_hs_code_count", 0) == 0


def test_product_entity_count_correct():
    designs = [_perfect_design(f"D{i:03d}") for i in range(7)]
    score = _score_products(designs)
    assert score.entity_count == 7


# ══════════════════════════════════════════════════════════════════════════════
# 6. Finishing scoring
# ══════════════════════════════════════════════════════════════════════════════

def test_perfect_finishing_scores_near_1():
    d = _perfect_design()
    score = _score_finishing([d])
    assert score.completeness_score > 0.95


def test_finishing_missing_metal_drops_score_significantly():
    d = _perfect_design()
    d.metal = None
    score = _score_finishing([d])
    assert score.completeness_score < 0.65


def test_finishing_non_standard_metal_flagged():
    d = _perfect_design()
    d.metal = "unobtanium"
    score = _score_finishing([d])
    assert score.details.get("non_standard_metal_count", 0) >= 1


def test_finishing_known_metal_not_flagged():
    for metal in ("gold", "silver", "platinum", "Gold"):
        d = _perfect_design()
        d.metal = metal
        score = _score_finishing([d])
        assert score.details.get("non_standard_metal_count", 0) == 0, f"false positive for {metal}"


def test_finishing_missing_stone_generates_recommendation():
    d = _perfect_design()
    d.stone_summary = None
    score = _score_finishing([d])
    assert any("stone_summary" in r for r in score.recommendations)


# ══════════════════════════════════════════════════════════════════════════════
# 7. Supplier scoring
# ══════════════════════════════════════════════════════════════════════════════

def test_perfect_supplier_scores_near_1():
    score = _score_suppliers([_perfect_supplier()])
    assert score.completeness_score > 0.90


def test_supplier_missing_wfirma_id_lowers_score():
    s = _perfect_supplier()
    s.wfirma_id = None
    score = _score_suppliers([s])
    assert score.completeness_score < 0.90
    assert score.details.get("missing_wfirma_id_count", 0) == 1


def test_supplier_duplicate_by_vat_id():
    s1 = _perfect_supplier(1)
    s1.vat_id = "IN99999999"
    s2 = _perfect_supplier(2)
    s2.vat_id = "IN99999999"
    score = _score_suppliers([s1, s2])
    vat_dups = [d for d in score.duplicate_clusters if d.key.startswith("vat:")]
    assert len(vat_dups) >= 1
    assert vat_dups[0].probability >= 0.9


def test_supplier_no_duplicate_when_vat_ids_differ():
    s1 = _perfect_supplier(1)
    s1.vat_id = "IN11111111"
    s2 = _perfect_supplier(2)
    s2.vat_id = "IN22222222"
    score = _score_suppliers([s1, s2])
    vat_dups = [d for d in score.duplicate_clusters if d.key.startswith("vat:")]
    assert len(vat_dups) == 0


# ══════════════════════════════════════════════════════════════════════════════
# 8. Readiness cross-domain logic
# ══════════════════════════════════════════════════════════════════════════════

def test_readiness_detects_missing_currency():
    c = _Customer(bill_to_contractor_id="1", bill_to_name="Test", country="PL")
    cs = _score_customers([c])
    ps = _score_products([])
    ss = _score_suppliers([])
    rs = _score_readiness([c], [], [], cs, ps, ss)
    blockers = rs.details.get("blockers", [])
    assert any(b["blocker"] == "missing_default_currency" for b in blockers)


def test_readiness_detects_missing_hs_code():
    d = _perfect_design()
    d.hs_code = None
    cs = _score_customers([])
    ps = _score_products([d])
    ss = _score_suppliers([])
    rs = _score_readiness([], [d], [], cs, ps, ss)
    blockers = rs.details.get("blockers", [])
    assert any(b["blocker"] == "missing_hs_code" for b in blockers)


def test_readiness_no_blockers_when_data_complete():
    c = _perfect_customer()
    d = _perfect_design()
    s = _perfect_supplier()
    cs = _score_customers([c])
    ps = _score_products([d])
    ss = _score_suppliers([s])
    rs = _score_readiness([c], [d], [s], cs, ps, ss)
    assert rs.details.get("blocker_count", 99) == 0


def test_readiness_missing_supplier_wfirma_id_is_blocker():
    s = _perfect_supplier()
    s.wfirma_id = None
    cs = _score_customers([])
    ps = _score_products([])
    ss = _score_suppliers([s])
    rs = _score_readiness([], [], [s], cs, ps, ss)
    blockers = rs.details.get("blockers", [])
    assert any(b["blocker"] == "missing_wfirma_id" for b in blockers)


# ══════════════════════════════════════════════════════════════════════════════
# 9. Platform score calculation
# ══════════════════════════════════════════════════════════════════════════════

def test_platform_score_between_0_and_1():
    with patch("app.services.master_data_intelligence.list_customers", return_value=[_perfect_customer()]):
        with patch("app.services.master_data_intelligence.list_designs", return_value=[_perfect_design()]):
            with patch("app.services.master_data_intelligence.list_product_local", return_value=[]):
                with patch("app.services.master_data_intelligence.list_suppliers", return_value=[_perfect_supplier()]):
                    with patch("app.services.master_data_intelligence.cm_init"):
                        with patch("app.services.master_data_intelligence.md_init"):
                            with patch("app.services.master_data_intelligence.supp_init"):
                                report = generate_report()
    assert 0.0 <= report.platform_score <= 1.0


def test_platform_score_higher_with_complete_data():
    with patch("app.services.master_data_intelligence.list_customers",
               return_value=[_perfect_customer()]):
        with patch("app.services.master_data_intelligence.list_designs",
                   return_value=[_perfect_design()]):
            with patch("app.services.master_data_intelligence.list_product_local", return_value=[]):
                with patch("app.services.master_data_intelligence.list_suppliers",
                           return_value=[_perfect_supplier()]):
                    with patch("app.services.master_data_intelligence.cm_init"):
                        with patch("app.services.master_data_intelligence.md_init"):
                            with patch("app.services.master_data_intelligence.supp_init"):
                                full_report = generate_report()

    with patch("app.services.master_data_intelligence.list_customers", return_value=[]):
        with patch("app.services.master_data_intelligence.list_designs", return_value=[]):
            with patch("app.services.master_data_intelligence.list_product_local", return_value=[]):
                with patch("app.services.master_data_intelligence.list_suppliers", return_value=[]):
                    with patch("app.services.master_data_intelligence.cm_init"):
                        with patch("app.services.master_data_intelligence.md_init"):
                            with patch("app.services.master_data_intelligence.supp_init"):
                                empty_report = generate_report()

    assert full_report.platform_score > empty_report.platform_score


def test_top_recommendations_is_list():
    with patch("app.services.master_data_intelligence.list_customers", return_value=[]):
        with patch("app.services.master_data_intelligence.list_designs", return_value=[]):
            with patch("app.services.master_data_intelligence.list_product_local", return_value=[]):
                with patch("app.services.master_data_intelligence.list_suppliers", return_value=[]):
                    with patch("app.services.master_data_intelligence.cm_init"):
                        with patch("app.services.master_data_intelligence.md_init"):
                            with patch("app.services.master_data_intelligence.supp_init"):
                                report = generate_report()
    assert isinstance(report.top_recommendations, list)


# ══════════════════════════════════════════════════════════════════════════════
# 10. Source-grep: no forbidden operations
# ══════════════════════════════════════════════════════════════════════════════

def _read_source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_service_has_no_write_db_calls():
    src = _read_source("app/services/master_data_intelligence.py")
    for forbidden in ("conn.execute(\"INSERT", "conn.execute(\"UPDATE", "conn.execute(\"DELETE",
                      "upsert_customer", "upsert_design", "upsert_supplier",
                      "create_supplier", "delete_"):
        assert forbidden not in src, f"forbidden write pattern found: {forbidden!r}"


def test_service_has_no_llm_calls():
    src = _read_source("app/services/master_data_intelligence.py")
    assert "anthropic" not in src
    assert "ai_gateway" not in src
    assert "openai" not in src


def test_service_llm_used_false_is_hardcoded():
    src = _read_source("app/services/master_data_intelligence.py")
    assert "llm_used=False" in src
    assert "llm_used=True" not in src


def test_router_has_no_post_put_delete_routes():
    src = _read_source("app/api/routes_mdi.py")
    assert "@router.post" not in src
    assert "@router.put" not in src
    assert "@router.delete" not in src
    assert "@router.patch" not in src


def test_router_advisory_class_R_in_output():
    src = _read_source("app/api/routes_mdi.py")
    # Router returns advisory_class from the report (which is "R")
    assert "advisory_class" in src


def test_service_read_functions_only():
    src = _read_source("app/services/master_data_intelligence.py")
    # Must use list_ and get_ functions (read), not upsert/create/delete
    assert "list_customers" in src
    assert "list_designs" in src
    assert "list_suppliers" in src


def test_report_generated_at_is_iso_timestamp():
    import re as _re
    with patch("app.services.master_data_intelligence.list_customers", return_value=[]):
        with patch("app.services.master_data_intelligence.list_designs", return_value=[]):
            with patch("app.services.master_data_intelligence.list_product_local", return_value=[]):
                with patch("app.services.master_data_intelligence.list_suppliers", return_value=[]):
                    with patch("app.services.master_data_intelligence.cm_init"):
                        with patch("app.services.master_data_intelligence.md_init"):
                            with patch("app.services.master_data_intelligence.supp_init"):
                                report = generate_report()
    assert _re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", report.generated_at)
