"""
test_customer_intelligence.py — Unit tests for customer_intelligence module.

Tests use mock connectors only — no live network calls.

Phase 0 test inventory (read-only report):
  1. valid VIES result marks advisory clear (vat_eu_valid proposed True)
  2. invalid VIES result marks export risk (CRITICAL risk finding)
  3. unavailable VIES result stays advisory only (INFO risk, no CM update proposed)
  4. expired KUKE produces CRITICAL finding
  5. no Customer Master write occurs (safety contract)
  6. every finding has source and confidence set

Phase 1 test inventory (VIES validation action + KUKE guard):
  10. valid VIES clears D3 advisory (sets vat_eu_valid=True in DB)
  11. invalid VIES sets vat_eu_valid=False in DB
  12. unavailable VIES does not modify Customer Master
  13. validation timestamp is written for valid/invalid, absent for unavailable
  14. ViesValidationAction fields are fully populated
  15. manual recheck: second call with different result updates CM again
  16. kuke_is_currently_active — True when approved + not expired
  17. kuke_is_currently_active — False when expired (critical stale-approval scenario)
  18. kuke_is_currently_active — False when kuke_approved=False
  19. get_kuke_risk returns CRITICAL when approved+expired
  20. get_kuke_risk returns None when approved+active
  21. wfirma_client d3_vies_blocked=True when vat_eu_valid=False (EU customer)
  22. wfirma_client d3_vies_blocked=False when vat_eu_valid=None (advisory only)
  23. wfirma_client d3_vies_blocked=False when vat_eu_valid=True (clear)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

# ─── Path bootstrap ────────────────────────────────────────────────────────────
_svc = Path(__file__).resolve().parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))

from app.services.customer_intelligence import (
    CRITICAL,
    WARNING,
    INFO,
    CLEAR,
    VERIFIED,
    UNAVAILABLE,
    CAN_AUTOMATE,
    MANUAL_REQUIRED,
    MockViesConnector,
    PlaceholderEoriConnector,
    ViesResult,
    run_intelligence_check,
)


# ─── CustomerMaster stub ──────────────────────────────────────────────────────

@dataclass
class _CustomerMasterStub:
    """Minimal stub matching the CustomerMaster interface.

    Only fields read by customer_intelligence.py are listed here.
    All optional fields default to None to keep tests tight.
    """
    bill_to_contractor_id: str = "104677702"
    bill_to_name: str           = "Verhoeven Joaillier"
    country: str                = "FR"
    nip: Optional[str]          = "FR90333134013"
    vat_eu_number: Optional[str] = "FR90333134013"
    vat_eu_valid: Optional[bool] = None
    vat_eu_validated_at: Optional[str] = None
    eori: Optional[str]         = None
    kuke_approved: Optional[bool] = None
    kuke_expiry_date: Optional[str] = None
    kuke_limit: Optional[Decimal] = None
    kuke_currency: Optional[str] = None
    kuke_policy_number: Optional[str] = None
    kuke_self_retention_pct: Optional[Decimal] = None
    kyc_status: Optional[str]   = "approved"
    kyc_approved_on: Optional[str] = "2026-05-18"
    kyc_expiry: Optional[str]   = "2027-04-13"
    aml_risk_rating: Optional[str] = "low"
    pep_check_result: Optional[str] = "clear"
    compliance_notes: Optional[str] = None
    beneficial_owner: Optional[str] = None
    owner_id_type: Optional[str] = "passport"
    owner_id_number: Optional[str] = None
    risk_status: Optional[str]  = "low"
    credit_limit: Optional[Decimal] = Decimal("100000")
    credit_currency: Optional[str] = "PLN"
    default_currency: Optional[str] = "EUR"
    payment_terms_days: Optional[int] = 7
    bill_to_street: Optional[str]  = "37, Place Jean Bart"
    bill_to_city: Optional[str]    = "Dunkerque"
    bill_to_postal_code: Optional[str] = "59140"
    bill_to_email: Optional[str]   = "axel@verhoeven-joaillier.com"
    bill_to_phone: Optional[str]   = "33624090393"
    client_type: Optional[str]     = "Buyer"
    industry: Optional[str]        = "Jewelry retail"
    short_code: Optional[str]      = None
    regon: Optional[str]           = None


_BASE_DATE = date(2026, 6, 26)  # fixed check_date for all tests


def _base_cm(**overrides):
    return _CustomerMasterStub(**overrides)


# ─── Test 1: valid VIES clears the advisory ───────────────────────────────────

class TestViesValid:
    def test_valid_vies_proposes_vat_eu_valid_true(self):
        vies = MockViesConnector(ViesResult(
            status="valid",
            name="VERHOEVEN JOAILLIER",
            address="37 PLACE JEAN BART 59140 DUNKERQUE",
            validated_at="2026-06-26",
        ))
        cm = _base_cm()
        report = run_intelligence_check(
            cm, vies_connector=vies, check_date=_BASE_DATE
        )

        # A proposal to set vat_eu_valid=True should exist
        vat_proposals = [p for p in report.proposed_cm if p.field == "vat_eu_valid"]
        assert vat_proposals, "Expected a proposal for vat_eu_valid"
        assert vat_proposals[0].suggested_value is True
        assert vat_proposals[0].action_type == CAN_AUTOMATE

        # The VIES finding should be VERIFIED status
        vies_verified = [f for f in report.vies if f.field == "vat_eu_number" and f.status == VERIFIED]
        assert vies_verified, "Expected a VERIFIED finding for vat_eu_number"

        # No CRITICAL risk from VIES
        critical_risks = [r for r in report.risks if r.level == CRITICAL and "VIES" in r.code]
        assert not critical_risks, f"Unexpected CRITICAL VIES risk: {critical_risks}"

    def test_valid_vies_note_mentions_wdt(self):
        vies = MockViesConnector(ViesResult(status="valid", name="Test"))
        report = run_intelligence_check(
            _base_cm(), vies_connector=vies, check_date=_BASE_DATE
        )
        wdt_findings = [f for f in report.vies if f.note and "WDT" in f.note]
        assert wdt_findings, "Expected at least one VIES finding mentioning WDT"


# ─── Test 2: invalid VIES marks export risk ───────────────────────────────────

class TestViesInvalid:
    def test_invalid_vies_produces_critical_risk(self):
        vies = MockViesConnector(ViesResult(
            status="invalid",
            validated_at="2026-06-26",
        ))
        cm = _base_cm()
        report = run_intelligence_check(
            cm, vies_connector=vies, check_date=_BASE_DATE
        )

        critical = [r for r in report.risks if r.code == "VIES_INVALID"]
        assert critical, "Expected VIES_INVALID critical risk finding"
        assert critical[0].level == CRITICAL

    def test_invalid_vies_proposes_vat_eu_valid_false_as_manual(self):
        vies = MockViesConnector(ViesResult(status="invalid"))
        report = run_intelligence_check(
            _base_cm(), vies_connector=vies, check_date=_BASE_DATE
        )
        vat_proposals = [p for p in report.proposed_cm if p.field == "vat_eu_valid"]
        assert vat_proposals, "Expected proposal for vat_eu_valid when VIES invalid"
        assert vat_proposals[0].suggested_value is False
        # Must be MANUAL_REQUIRED — tax consequences require human confirmation
        assert vat_proposals[0].action_type == MANUAL_REQUIRED

    def test_invalid_vies_finding_is_verified_status(self):
        vies = MockViesConnector(ViesResult(status="invalid"))
        report = run_intelligence_check(
            _base_cm(), vies_connector=vies, check_date=_BASE_DATE
        )
        # VIES confirmed the invalidity — that itself is a verified fact
        invalid_finding = [f for f in report.vies if f.field == "vat_eu_number" and f.status == VERIFIED]
        assert invalid_finding, "Expected VERIFIED finding even when VIES returns invalid"


# ─── Test 3: unavailable VIES stays advisory only ─────────────────────────────

class TestViesUnavailable:
    def test_unavailable_vies_produces_info_risk_not_critical(self):
        vies = MockViesConnector(ViesResult(status="unavailable"))
        report = run_intelligence_check(
            _base_cm(), vies_connector=vies, check_date=_BASE_DATE
        )

        vies_risks = [r for r in report.risks if "VIES" in r.code]
        assert vies_risks, "Expected at least one VIES risk finding"
        # Must NOT be CRITICAL — service unavailability is advisory
        critical_vies = [r for r in vies_risks if r.level == CRITICAL]
        assert not critical_vies, (
            f"VIES unavailable should not produce CRITICAL: {critical_vies}"
        )
        # Should be INFO
        info_vies = [r for r in vies_risks if r.level == INFO]
        assert info_vies, "Expected INFO-level risk when VIES unavailable"

    def test_unavailable_vies_does_not_propose_cm_update(self):
        vies = MockViesConnector(ViesResult(status="unavailable"))
        report = run_intelligence_check(
            _base_cm(), vies_connector=vies, check_date=_BASE_DATE
        )
        vat_proposals = [p for p in report.proposed_cm if p.field == "vat_eu_valid"]
        # No proposal to change vat_eu_valid when we couldn't confirm either way
        assert not vat_proposals, (
            "Should not propose vat_eu_valid change when VIES is unavailable"
        )

    def test_unavailable_vies_finding_status_is_unavailable(self):
        vies = MockViesConnector(ViesResult(status="unavailable"))
        report = run_intelligence_check(
            _base_cm(), vies_connector=vies, check_date=_BASE_DATE
        )
        unavail = [f for f in report.vies if f.status == UNAVAILABLE]
        assert unavail, "Expected at least one UNAVAILABLE finding for unreachable VIES"


# ─── Test 4: expired KUKE produces CRITICAL finding ──────────────────────────

class TestKukeExpired:
    def test_expired_kuke_produces_critical(self):
        vies = MockViesConnector(ViesResult(status="unavailable"))
        cm = _base_cm(
            kuke_approved=True,
            kuke_expiry_date="2026-05-18",   # 39 days before check_date 2026-06-26
            kuke_limit=Decimal("50000"),
            kuke_currency="PLN",
            kuke_policy_number="POL-2025-001",
        )
        report = run_intelligence_check(
            cm, vies_connector=vies, check_date=_BASE_DATE
        )

        expired_risks = [r for r in report.risks if r.code == "KUKE_EXPIRED"]
        assert expired_risks, "Expected KUKE_EXPIRED risk finding"
        assert expired_risks[0].level == CRITICAL

    def test_expired_kuke_proposes_approved_false(self):
        vies = MockViesConnector(ViesResult(status="unavailable"))
        cm = _base_cm(
            kuke_approved=True,
            kuke_expiry_date="2026-05-18",
            kuke_limit=Decimal("50000"),
            kuke_currency="PLN",
        )
        report = run_intelligence_check(
            cm, vies_connector=vies, check_date=_BASE_DATE
        )

        proposals = [p for p in report.proposed_cm if p.field == "kuke_approved"]
        assert proposals, "Expected proposal to set kuke_approved=False after expiry"
        assert proposals[0].suggested_value is False
        assert proposals[0].action_type == MANUAL_REQUIRED

    def test_active_kuke_produces_no_expired_risk(self):
        """Expiry 90 days in the future → no KUKE_EXPIRED or KUKE_EXPIRING_SOON."""
        vies = MockViesConnector(ViesResult(status="unavailable"))
        cm = _base_cm(
            kuke_approved=True,
            kuke_expiry_date="2026-09-24",   # 90 days after check_date
            kuke_limit=Decimal("50000"),
            kuke_currency="PLN",
        )
        report = run_intelligence_check(
            cm, vies_connector=vies, check_date=_BASE_DATE
        )
        bad_risks = [r for r in report.risks
                     if r.code in ("KUKE_EXPIRED", "KUKE_EXPIRING_SOON")]
        assert not bad_risks, f"Unexpected KUKE risk for future expiry: {bad_risks}"


# ─── Test 5: no Customer Master write ─────────────────────────────────────────

class TestNoCustomerMasterWrite:
    """Safety contract: run_intelligence_check() must not write to any DB."""

    def test_report_does_not_call_any_write_function(self, monkeypatch):
        """
        Monkeypatch the two write paths from customer_master_db.
        Both must remain uncalled.
        """
        called = []

        try:
            from app.services import customer_master_db
            monkeypatch.setattr(
                customer_master_db,
                "upsert_customer",
                lambda *a, **kw: called.append("upsert_customer") or 0,
            )
            monkeypatch.setattr(
                customer_master_db,
                "upsert_identity_only",
                lambda *a, **kw: called.append("upsert_identity_only") or {},
            )
        except (ImportError, AttributeError):
            # If the module cannot be imported in test context, the safety
            # constraint is still met — customer_intelligence never imports it.
            pass

        vies = MockViesConnector(ViesResult(status="valid", name="Test"))
        run_intelligence_check(
            _base_cm(kuke_approved=True, kuke_expiry_date="2026-05-18",
                     kuke_limit=Decimal("50000"), kuke_currency="PLN"),
            vies_connector=vies,
            check_date=_BASE_DATE,
        )

        assert not called, f"Write functions were called: {called}"

    def test_customer_master_stub_is_unchanged_after_check(self):
        vies = MockViesConnector(ViesResult(status="valid", name="Test"))
        cm = _base_cm()
        original_vat_valid = cm.vat_eu_valid
        original_contractor_id = cm.bill_to_contractor_id

        run_intelligence_check(cm, vies_connector=vies, check_date=_BASE_DATE)

        assert cm.vat_eu_valid == original_vat_valid, "cm.vat_eu_valid was mutated"
        assert cm.bill_to_contractor_id == original_contractor_id, "cm.bill_to_contractor_id was mutated"


# ─── Test 6: every finding has source and confidence ─────────────────────────

class TestFindingMetadata:
    def _all_findings(self, report):
        return (
            report.baseline
            + report.vies
            + report.eori
            + report.kuke
            + report.kyc_aml
            + report.registry
        )

    def test_all_findings_have_source(self):
        vies = MockViesConnector(ViesResult(status="valid", name="Test"))
        report = run_intelligence_check(
            _base_cm(), vies_connector=vies, check_date=_BASE_DATE
        )
        for f in self._all_findings(report):
            assert f.source, (
                f"Finding field={f.field!r} has empty source"
            )

    def test_all_findings_have_confidence(self):
        vies = MockViesConnector(ViesResult(status="valid", name="Test"))
        report = run_intelligence_check(
            _base_cm(), vies_connector=vies, check_date=_BASE_DATE
        )
        valid_confidence = {"high", "medium", "low", "none"}
        for f in self._all_findings(report):
            assert f.confidence in valid_confidence, (
                f"Finding field={f.field!r} has invalid confidence={f.confidence!r}"
            )

    def test_all_proposed_updates_have_source_and_confidence(self):
        vies = MockViesConnector(ViesResult(status="valid", name="Test"))
        report = run_intelligence_check(
            _base_cm(), vies_connector=vies, check_date=_BASE_DATE
        )
        all_proposals = report.proposed_cm + report.proposed_intel
        assert all_proposals, "Expected at least some proposals"
        for p in all_proposals:
            assert p.source, f"Proposal field={p.field!r} has empty source"
            assert p.confidence, f"Proposal field={p.field!r} has empty confidence"
            assert p.action_type, f"Proposal field={p.field!r} has empty action_type"

    def test_all_risk_findings_have_code_level_description_action(self):
        vies = MockViesConnector(ViesResult(status="invalid"))
        cm = _base_cm(
            kuke_approved=True,
            kuke_expiry_date="2026-05-18",
            kuke_limit=Decimal("50000"),
            kuke_currency="PLN",
        )
        report = run_intelligence_check(cm, vies_connector=vies, check_date=_BASE_DATE)
        for rf in report.risks:
            assert rf.code, f"RiskFinding missing code: {rf}"
            assert rf.level in ("critical", "warning", "info", "clear"), (
                f"RiskFinding invalid level: {rf.level!r}"
            )
            assert rf.description, f"RiskFinding missing description: {rf.code}"
            assert rf.recommended_action, f"RiskFinding missing recommended_action: {rf.code}"


# ─── Test 7: KUKE not set → no KUKE section risk ─────────────────────────────

class TestKukeAbsent:
    def test_kuke_not_approved_no_expired_risk(self):
        vies = MockViesConnector(ViesResult(status="unavailable"))
        cm = _base_cm(kuke_approved=False)
        report = run_intelligence_check(cm, vies_connector=vies, check_date=_BASE_DATE)
        kuke_risks = [r for r in report.risks if "KUKE" in r.code]
        assert not kuke_risks, f"Unexpected KUKE risk when not approved: {kuke_risks}"

    def test_kuke_none_produces_no_risk(self):
        vies = MockViesConnector(ViesResult(status="unavailable"))
        cm = _base_cm(kuke_approved=None)
        report = run_intelligence_check(cm, vies_connector=vies, check_date=_BASE_DATE)
        kuke_risks = [r for r in report.risks if "KUKE_EXPIRED" in r.code]
        assert not kuke_risks


# ─── Test 8: EORI missing → warning ─────────────────────────────────────────

class TestEoriMissing:
    def test_missing_eori_produces_warning(self):
        vies = MockViesConnector(ViesResult(status="unavailable"))
        cm = _base_cm(eori=None)
        report = run_intelligence_check(cm, vies_connector=vies, check_date=_BASE_DATE)
        eori_risks = [r for r in report.risks if r.code == "EORI_MISSING"]
        assert eori_risks, "Expected EORI_MISSING warning"
        assert eori_risks[0].level == WARNING

    def test_missing_eori_produces_manual_required_proposal(self):
        vies = MockViesConnector(ViesResult(status="unavailable"))
        report = run_intelligence_check(
            _base_cm(eori=None), vies_connector=vies, check_date=_BASE_DATE
        )
        eori_proposals = [p for p in report.proposed_intel if "eori" in p.field.lower()]
        assert eori_proposals, "Expected EORI proposal in proposed_intel"


# ─── Test 9: render_markdown produces non-empty output ───────────────────────

class TestMarkdownRenderer:
    def test_render_produces_markdown_with_all_sections(self):
        from app.services.customer_intelligence import render_markdown

        vies = MockViesConnector(ViesResult(status="valid", name="Test"))
        report = run_intelligence_check(
            _base_cm(), vies_connector=vies, check_date=_BASE_DATE
        )
        md = render_markdown(report)
        assert "Customer Intelligence Report" in md
        assert "Section 1" in md
        assert "Section 2" in md
        assert "Section 4" in md   # KUKE
        assert "Section 9" in md   # Risk Summary
        assert "Verhoeven Joaillier" in md

    def test_render_includes_contractor_id(self):
        from app.services.customer_intelligence import render_markdown

        vies = MockViesConnector(ViesResult(status="unavailable"))
        report = run_intelligence_check(
            _base_cm(), vies_connector=vies, check_date=_BASE_DATE
        )
        md = render_markdown(report)
        assert "104677702" in md


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 tests — VIES validation action + KUKE guard
# ─────────────────────────────────────────────────────────────────────────────

def _make_cm_db(tmp_path: Path, cm_stub=None) -> Path:
    """Write a customer_master SQLite DB using the real schema (init_db)."""
    from app.services.customer_master_db import init_db, upsert_customer, CustomerMaster
    from decimal import Decimal as D

    cm = cm_stub or _base_cm()
    db = tmp_path / "customer_master.sqlite"
    init_db(db)

    # Build a real CustomerMaster from the stub fields we care about.
    # Most fields default to None / empty which is fine for tests.
    real_cm = CustomerMaster(
        bill_to_contractor_id=cm.bill_to_contractor_id,
        bill_to_name=cm.bill_to_name,
        country=cm.country,
        nip=cm.nip or "",
        vat_eu_number=cm.vat_eu_number,
        vat_eu_valid=cm.vat_eu_valid,
        vat_eu_validated_at=cm.vat_eu_validated_at,
        kuke_approved=cm.kuke_approved,
        kuke_expiry_date=cm.kuke_expiry_date,
        kuke_limit=D(str(cm.kuke_limit)) if cm.kuke_limit else None,
        kuke_currency=cm.kuke_currency,
        risk_status=cm.risk_status,
        default_currency=cm.default_currency or "EUR",
    )
    upsert_customer(db, real_cm)
    return db


class TestViesValidationAction:
    """Phase 1: validate_customer_vat() writes to a real SQLite DB."""

    def test_valid_vies_sets_vat_eu_valid_true_in_db(self, tmp_path):
        from app.services.customer_intelligence import validate_customer_vat
        from app.services.customer_master_db import get_customer

        db = _make_cm_db(tmp_path, _base_cm(vat_eu_valid=None))
        vies = MockViesConnector(ViesResult(
            status="valid", name="VERHOEVEN JOAILLIER", address="59140 DUNKERQUE"
        ))

        action = validate_customer_vat(db, "104677702", vies_connector=vies,
                                       today=_BASE_DATE)

        assert action.vies_status == "valid"
        assert action.vat_eu_valid is True
        assert action.cm_updated is True
        assert action.d3_cleared is True
        assert action.d3_blocked is False

        # Verify the DB was actually updated
        cm = get_customer(db, "104677702")
        assert cm.vat_eu_valid is True
        assert cm.vat_eu_validated_at == _BASE_DATE.isoformat()

    def test_invalid_vies_sets_vat_eu_valid_false_in_db(self, tmp_path):
        from app.services.customer_intelligence import validate_customer_vat
        from app.services.customer_master_db import get_customer

        db = _make_cm_db(tmp_path, _base_cm(vat_eu_valid=None))
        vies = MockViesConnector(ViesResult(status="invalid"))

        action = validate_customer_vat(db, "104677702", vies_connector=vies,
                                       today=_BASE_DATE)

        assert action.vies_status == "invalid"
        assert action.vat_eu_valid is False
        assert action.cm_updated is True
        assert action.d3_cleared is False
        assert action.d3_blocked is True

        cm = get_customer(db, "104677702")
        assert cm.vat_eu_valid is False
        assert cm.vat_eu_validated_at == _BASE_DATE.isoformat()

    def test_unavailable_vies_does_not_modify_customer_master(self, tmp_path):
        from app.services.customer_intelligence import validate_customer_vat
        from app.services.customer_master_db import get_customer

        db = _make_cm_db(tmp_path, _base_cm(vat_eu_valid=None))
        vies = MockViesConnector(ViesResult(status="unavailable"))

        action = validate_customer_vat(db, "104677702", vies_connector=vies,
                                       today=_BASE_DATE)

        assert action.vies_status == "unavailable"
        assert action.vat_eu_valid is None
        assert action.cm_updated is False
        assert action.d3_cleared is False
        assert action.d3_blocked is False

        # CM must be unchanged
        cm = get_customer(db, "104677702")
        assert cm.vat_eu_valid is None
        assert cm.vat_eu_validated_at is None

    def test_timestamp_written_for_valid_not_for_unavailable(self, tmp_path):
        from app.services.customer_intelligence import validate_customer_vat

        db_valid = _make_cm_db(tmp_path / "valid", _base_cm())
        (tmp_path / "valid").mkdir(parents=True, exist_ok=True)
        db_valid = _make_cm_db(tmp_path, _base_cm())

        action_valid = validate_customer_vat(
            db_valid, "104677702",
            vies_connector=MockViesConnector(ViesResult(status="valid")),
            today=_BASE_DATE,
        )
        assert action_valid.validated_at == _BASE_DATE.isoformat()

    def test_timestamp_absent_for_unavailable(self, tmp_path):
        from app.services.customer_intelligence import validate_customer_vat

        db = _make_cm_db(tmp_path, _base_cm())
        action = validate_customer_vat(
            db, "104677702",
            vies_connector=MockViesConnector(ViesResult(status="unavailable")),
            today=_BASE_DATE,
        )
        assert action.validated_at is None

    def test_action_fields_fully_populated_on_valid(self, tmp_path):
        from app.services.customer_intelligence import validate_customer_vat

        db = _make_cm_db(tmp_path, _base_cm())
        vies = MockViesConnector(ViesResult(
            status="valid", name="Test SA", address="1 Rue Test"
        ))
        action = validate_customer_vat(db, "104677702", vies_connector=vies,
                                       today=_BASE_DATE)

        assert action.contractor_id == "104677702"
        assert action.vat_number == "FR90333134013"
        assert action.source == "EC VIES REST API"
        assert action.raw_name == "Test SA"
        assert action.raw_address == "1 Rue Test"
        assert action.advisory         # non-empty
        assert "D3" in action.advisory or "proforma" in action.advisory.lower()

    def test_manual_recheck_updates_cached_value(self, tmp_path):
        """Second call with different result must overwrite the first."""
        from app.services.customer_intelligence import validate_customer_vat
        from app.services.customer_master_db import get_customer

        db = _make_cm_db(tmp_path, _base_cm(vat_eu_valid=True,
                                             vat_eu_validated_at="2026-01-01"))

        # Simulate a re-check that now returns invalid (e.g., VAT deregistered)
        action = validate_customer_vat(
            db, "104677702",
            vies_connector=MockViesConnector(ViesResult(status="invalid")),
            today=_BASE_DATE,
        )
        assert action.vat_eu_valid is False

        cm = get_customer(db, "104677702")
        assert cm.vat_eu_valid is False
        assert cm.vat_eu_validated_at == _BASE_DATE.isoformat()

    def test_no_vat_number_returns_not_applicable(self, tmp_path):
        from app.services.customer_intelligence import validate_customer_vat

        db = _make_cm_db(tmp_path, _base_cm(vat_eu_number=None))
        action = validate_customer_vat(
            db, "104677702",
            vies_connector=MockViesConnector(ViesResult(status="valid")),
            today=_BASE_DATE,
        )
        assert action.vies_status == "not_applicable"
        assert action.cm_updated is False

    def test_no_network_calls_in_unit_tests(self, tmp_path):
        """All VIES calls go through the mock — no real HTTP."""
        from app.services.customer_intelligence import validate_customer_vat, PlaceholderViesConnector

        db = _make_cm_db(tmp_path, _base_cm())
        # PlaceholderViesConnector returns 'unavailable' and never calls a URL
        action = validate_customer_vat(
            db, "104677702",
            vies_connector=PlaceholderViesConnector(),
            today=_BASE_DATE,
        )
        # PlaceholderViesConnector → unavailable → no write
        assert action.vies_status == "unavailable"
        assert action.cm_updated is False


class TestKukeGuard:
    """Phase 1: kuke_is_currently_active() and get_kuke_risk() — pure functions."""

    def test_kuke_active_when_approved_and_not_expired(self):
        from app.services.customer_intelligence import kuke_is_currently_active

        cm = _base_cm(
            kuke_approved=True,
            kuke_expiry_date="2026-09-30",  # well after _BASE_DATE 2026-06-26
        )
        assert kuke_is_currently_active(cm, today=_BASE_DATE) is True

    def test_kuke_not_active_when_expired(self):
        """Critical stale-approval scenario: approved=True but expiry in the past."""
        from app.services.customer_intelligence import kuke_is_currently_active

        cm = _base_cm(
            kuke_approved=True,
            kuke_expiry_date="2026-05-18",  # 39 days before _BASE_DATE
        )
        assert kuke_is_currently_active(cm, today=_BASE_DATE) is False

    def test_kuke_not_active_when_not_approved(self):
        from app.services.customer_intelligence import kuke_is_currently_active

        cm = _base_cm(kuke_approved=False, kuke_expiry_date="2026-09-30")
        assert kuke_is_currently_active(cm, today=_BASE_DATE) is False

    def test_kuke_not_active_when_no_expiry_date(self):
        from app.services.customer_intelligence import kuke_is_currently_active

        cm = _base_cm(kuke_approved=True, kuke_expiry_date=None)
        assert kuke_is_currently_active(cm, today=_BASE_DATE) is False

    def test_get_kuke_risk_critical_when_expired(self):
        from app.services.customer_intelligence import get_kuke_risk

        cm = _base_cm(
            kuke_approved=True,
            kuke_expiry_date="2026-05-18",
        )
        risk = get_kuke_risk(cm, today=_BASE_DATE)
        assert risk is not None
        assert risk.code == "KUKE_EXPIRED"
        assert risk.level == "critical"
        assert "39" in risk.description or "day" in risk.description

    def test_get_kuke_risk_none_when_active(self):
        from app.services.customer_intelligence import get_kuke_risk

        cm = _base_cm(
            kuke_approved=True,
            kuke_expiry_date="2026-09-30",
        )
        risk = get_kuke_risk(cm, today=_BASE_DATE)
        assert risk is None

    def test_get_kuke_risk_none_when_not_approved(self):
        from app.services.customer_intelligence import get_kuke_risk

        cm = _base_cm(kuke_approved=False)
        assert get_kuke_risk(cm, today=_BASE_DATE) is None

    def test_get_kuke_risk_warning_when_expiring_soon(self):
        from app.services.customer_intelligence import get_kuke_risk

        # Expiry 10 days from check date (within 30-day warn window)
        cm = _base_cm(
            kuke_approved=True,
            kuke_expiry_date="2026-07-06",  # 10 days after _BASE_DATE 2026-06-26
        )
        risk = get_kuke_risk(cm, today=_BASE_DATE)
        assert risk is not None
        assert risk.code == "KUKE_EXPIRING_SOON"
        assert risk.level == "warning"


class TestD3ViesBlocked:
    """Phase 1: wfirma_client.resolve_vat_context_from_master() d3_vies_blocked key."""

    def _resolve(self, country, vat_eu_number, vat_eu_valid, vat_mode=None):
        from app.services import wfirma_client

        class _FakeCm:
            pass

        cm = _FakeCm()
        cm.vat_mode = vat_mode
        cm.country = country
        cm.vat_eu_number = vat_eu_number
        cm.vat_eu_valid = vat_eu_valid
        return wfirma_client.resolve_vat_context_from_master(cm)

    def test_d3_blocked_true_when_vat_eu_valid_false_eu_customer(self):
        result = self._resolve("FR", "FR90333134013", False)
        assert result.get("d3_vies_blocked") is True

    def test_d3_blocked_false_when_vat_eu_valid_none_advisory_only(self):
        result = self._resolve("FR", "FR90333134013", None)
        assert result.get("d3_vies_blocked") is False
        assert result.get("d3_vies_warning") is True   # advisory still fires

    def test_d3_blocked_false_when_vat_eu_valid_true_clear(self):
        result = self._resolve("FR", "FR90333134013", True)
        assert result.get("d3_vies_blocked") is False
        assert result.get("d3_vies_warning") is False  # D3 is clear

    def test_d3_blocked_absent_for_domestic_customer(self):
        result = self._resolve("PL", None, None)
        # PL domestic — d3_vies_blocked key may be missing or False
        assert not result.get("d3_vies_blocked")

    def test_d3_blocked_absent_when_vat_mode_override(self):
        # vat_mode=228 → operator override branch, d3_vies_blocked not set / False
        result = self._resolve("FR", "FR90333134013", False, vat_mode=228)
        assert not result.get("d3_vies_blocked")
