"""
test_proforma_conflict_detector.py — ADR-029 PR-1 pure-detector unit tests.

Covers each of the four implemented validators with a positive AND a negative
case, plus the vocabulary-translation edge for V5 (draft stores "23"/"WDT"/"EXP"
code strings; the resolver returns 222/228/229 numeric ids).

The detector is pure (no DB, no wFirma), so these tests build a lightweight
fake CustomerMaster via SimpleNamespace — only the attributes the detectors read
are populated, which also pins exactly which fields the contract depends on.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services.proforma_conflict_detector import (
    detect_conflicts,
    parse_service_charges,
    IMPLEMENTED_CONFLICT_TYPES,
)
from app.models.vat_resolver import CustomerForVAT


def _customer(**kw):
    """Fake CustomerMaster with detector-relevant fields defaulted to inert."""
    base = dict(
        default_currency=None,
        country="PL",
        vat_eu_valid=None,
        freight_mode=None,
        freight_fixed_amount_eur=None,
        freight_fixed_amount_usd=None,
        insurance_enabled=True,
        insurance_mode=None,
        insurance_fixed_amount_eur=None,
        insurance_fixed_amount_usd=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _types(detections):
    return {d.conflict_type for d in detections}


# ── V3 currency_vs_customer_default ──────────────────────────────────────────

def test_v3_currency_mismatch_emits_warning():
    cust = _customer(default_currency="EUR")
    out = detect_conflicts(proforma_id="1", currency="USD", customer=cust)
    v3 = [d for d in out if d.conflict_type == "currency_vs_customer_default"]
    assert len(v3) == 1
    assert v3[0].severity == "warning"
    assert v3[0].current_value == "USD"
    assert v3[0].master_value == "EUR"
    assert v3[0].authority_owner == "Customer Service"


def test_v3_currency_match_no_conflict():
    cust = _customer(default_currency="EUR")
    out = detect_conflicts(proforma_id="1", currency="EUR", customer=cust)
    assert "currency_vs_customer_default" not in _types(out)


def test_v3_no_customer_default_silent():
    cust = _customer(default_currency=None)
    out = detect_conflicts(proforma_id="1", currency="EUR", customer=cust)
    assert "currency_vs_customer_default" not in _types(out)


# ── V4 bank_account_currency_unsupported ─────────────────────────────────────

@pytest.mark.parametrize("cur", ["PLN", "USD", "EUR"])
def test_v4_supported_currency_no_conflict(cur):
    out = detect_conflicts(proforma_id="1", currency=cur, customer=None)
    assert "bank_account_currency_unsupported" not in _types(out)


def test_v4_unsupported_currency_emits_error():
    out = detect_conflicts(proforma_id="1", currency="GBP", customer=None)
    v4 = [d for d in out if d.conflict_type == "bank_account_currency_unsupported"]
    assert len(v4) == 1
    assert v4[0].severity == "error"
    assert v4[0].current_value == "GBP"


def test_v4_missing_currency_emits_error():
    out = detect_conflicts(proforma_id="1", currency=None, customer=None)
    v4 = [d for d in out if d.conflict_type == "bank_account_currency_unsupported"]
    assert len(v4) == 1
    assert v4[0].severity == "error"
    assert v4[0].current_value is None


# ── V5 customer_vat_eu_changed ───────────────────────────────────────────────

def test_v5_pl_draft_matches_master_no_conflict():
    # PL master resolves to "23"; draft already holds "23" → no drift.
    ctx = CustomerForVAT(country="PL", vat_eu_valid=None)
    out = detect_conflicts(proforma_id="1", currency="PLN", vat_code="23",
                           vat_context=ctx)
    assert "customer_vat_eu_changed" not in _types(out)


def test_v5_drift_emits_warning():
    # Master is non-EU export → resolver returns 229 → "EXP"; draft holds "23".
    ctx = CustomerForVAT(country="US", vat_eu_valid=None)
    out = detect_conflicts(proforma_id="1", currency="USD", vat_code="23",
                           vat_context=ctx)
    v5 = [d for d in out if d.conflict_type == "customer_vat_eu_changed"]
    assert len(v5) == 1
    assert v5[0].severity == "warning"
    assert v5[0].current_value == "23"
    assert v5[0].master_value == "EXP"


def test_v5_manual_review_emits_error():
    # EU customer with no confirmed VAT-EU number → ManualReviewRequired → error.
    ctx = CustomerForVAT(country="DE", vat_eu_valid=None)
    out = detect_conflicts(proforma_id="1", currency="EUR", vat_code="WDT",
                           vat_context=ctx)
    v5 = [d for d in out if d.conflict_type == "customer_vat_eu_changed"]
    assert len(v5) == 1
    assert v5[0].severity == "error"
    assert v5[0].master_value == "manual_review_required"


def test_v5_wdt_match_no_conflict():
    # EU customer WITH confirmed VAT → resolver returns 228 → "WDT"; draft "WDT".
    ctx = CustomerForVAT(country="DE", vat_eu_valid=True)
    out = detect_conflicts(proforma_id="1", currency="EUR", vat_code="WDT",
                           vat_context=ctx)
    assert "customer_vat_eu_changed" not in _types(out)


def test_v5_lowercase_draft_code_normalised():
    ctx = CustomerForVAT(country="DE", vat_eu_valid=True)
    out = detect_conflicts(proforma_id="1", currency="EUR", vat_code="wdt",
                           vat_context=ctx)
    assert "customer_vat_eu_changed" not in _types(out)


def test_v5_no_context_silent():
    out = detect_conflicts(proforma_id="1", currency="EUR", vat_code="23",
                           vat_context=None)
    assert "customer_vat_eu_changed" not in _types(out)


def test_v5_empty_draft_code_advises_master():
    ctx = CustomerForVAT(country="PL", vat_eu_valid=None)
    out = detect_conflicts(proforma_id="1", currency="PLN", vat_code=None,
                           vat_context=ctx)
    v5 = [d for d in out if d.conflict_type == "customer_vat_eu_changed"]
    assert len(v5) == 1
    assert v5[0].severity == "warning"
    assert v5[0].current_value is None
    assert v5[0].master_value == "23"


# ── V8 service_charge_defaults_changed ───────────────────────────────────────

def test_v8_freight_drift_emits_warning():
    cust = _customer(freight_mode="fixed", freight_fixed_amount_eur="50")
    charges = [{"charge_type": "freight", "amount": 75, "currency": "EUR"}]
    out = detect_conflicts(proforma_id="1", currency="EUR",
                           service_charges=charges, customer=cust)
    v8 = [d for d in out if d.conflict_type == "service_charge_defaults_changed"]
    assert len(v8) == 1
    assert v8[0].severity == "warning"
    assert v8[0].field_affected == "service_charge.freight"
    assert v8[0].current_value == "75"
    assert v8[0].master_value == "50"


def test_v8_freight_match_no_conflict():
    cust = _customer(freight_mode="fixed", freight_fixed_amount_eur="50")
    charges = [{"charge_type": "freight", "amount": 50, "currency": "EUR"}]
    out = detect_conflicts(proforma_id="1", currency="EUR",
                           service_charges=charges, customer=cust)
    assert "service_charge_defaults_changed" not in _types(out)


def test_v8_non_fixed_mode_silent():
    cust = _customer(freight_mode="variable", freight_fixed_amount_eur="50")
    charges = [{"charge_type": "freight", "amount": 75, "currency": "EUR"}]
    out = detect_conflicts(proforma_id="1", currency="EUR",
                           service_charges=charges, customer=cust)
    assert "service_charge_defaults_changed" not in _types(out)


def test_v8_pln_currency_silent_no_column():
    # PLN has no *_fixed_amount_* column → V8 cannot compare → silent.
    cust = _customer(freight_mode="fixed", freight_fixed_amount_eur="50")
    charges = [{"charge_type": "freight", "amount": 75, "currency": "PLN"}]
    out = detect_conflicts(proforma_id="1", currency="PLN",
                           service_charges=charges, customer=cust)
    assert "service_charge_defaults_changed" not in _types(out)


def test_v8_missing_charge_against_fixed_default_emits_warning():
    cust = _customer(freight_mode="fixed", freight_fixed_amount_usd="40")
    out = detect_conflicts(proforma_id="1", currency="USD",
                           service_charges=[], customer=cust)
    v8 = [d for d in out if d.conflict_type == "service_charge_defaults_changed"]
    assert len(v8) == 1
    assert v8[0].current_value is None
    assert v8[0].master_value == "40"


def test_v8_insurance_disabled_silent():
    cust = _customer(insurance_enabled=False, insurance_mode="fixed",
                     insurance_fixed_amount_eur="30")
    charges = [{"charge_type": "insurance", "amount": 99, "currency": "EUR"}]
    out = detect_conflicts(proforma_id="1", currency="EUR",
                           service_charges=charges, customer=cust)
    assert "service_charge_defaults_changed" not in _types(out)


# ── parse_service_charges robustness ─────────────────────────────────────────

def test_parse_service_charges_accepts_json_string():
    raw = json.dumps([{"charge_type": "freight", "amount": 10, "currency": "EUR"}])
    parsed = parse_service_charges(raw)
    assert parsed == [{"charge_type": "freight", "amount": 10, "currency": "EUR"}]


def test_parse_service_charges_bad_input_returns_empty():
    assert parse_service_charges("not json") == []
    assert parse_service_charges(None) == []
    assert parse_service_charges("{}") == []  # object, not list


# ── No-customer / clean-draft baseline ───────────────────────────────────────

def test_clean_eur_draft_no_customer_only_currency_ok():
    # EUR is supported; no customer → no V3/V5/V8; no V4. Empty result.
    out = detect_conflicts(proforma_id="1", currency="EUR", customer=None)
    assert out == []


def test_implemented_set_is_the_four_pr1_validators():
    assert IMPLEMENTED_CONFLICT_TYPES == {
        "currency_vs_customer_default",
        "bank_account_currency_unsupported",
        "customer_vat_eu_changed",
        "service_charge_defaults_changed",
    }


# ── ADR-029/ADR-022 divergence-vs-temporal governance marker ─────────────────

def test_divergence_findings_carry_semantic_marker():
    """The three master-comparison divergence checks (V3/V5/V8) must each carry
    evidence["semantic"] so reviewers / UI never read 'current draft != current
    master' as temporal drift."""
    # V3 — currency vs customer default.
    v3 = [d for d in detect_conflicts(
              proforma_id="1", currency="USD",
              customer=_customer(default_currency="EUR"))
          if d.conflict_type == "currency_vs_customer_default"]
    assert v3, "expected a currency divergence finding"
    assert v3[0].evidence.get("semantic") == "divergence_not_temporal_drift"
    assert "pr2_todo" in v3[0].evidence

    # V5 — customer VAT-EU resolution vs draft code.
    v5 = [d for d in detect_conflicts(
              proforma_id="1", currency="USD", vat_code="23",
              vat_context=CustomerForVAT(country="US", vat_eu_valid=None))
          if d.conflict_type == "customer_vat_eu_changed"]
    assert v5, "expected a VAT divergence finding"
    assert v5[0].evidence.get("semantic") == "divergence_not_temporal_drift"
    assert "pr2_todo" in v5[0].evidence

    # V8 — service-charge default vs draft amount.
    v8 = [d for d in detect_conflicts(
              proforma_id="1", currency="EUR",
              service_charges=[{"charge_type": "freight", "amount": 75, "currency": "EUR"}],
              customer=_customer(freight_mode="fixed", freight_fixed_amount_eur="50"))
          if d.conflict_type == "service_charge_defaults_changed"]
    assert v8, "expected a service-charge divergence finding"
    assert v8[0].evidence.get("semantic") == "divergence_not_temporal_drift"
    assert "pr2_todo" in v8[0].evidence


def test_v4_static_eligibility_carries_no_divergence_marker():
    """V4 bank_account_currency_unsupported is a STATIC eligibility error, not a
    master comparison — it must NOT carry the divergence/temporal marker (pins the
    intentional distinction the detector docstring declares)."""
    v4 = [d for d in detect_conflicts(proforma_id="1", currency="GBP", customer=None)
          if d.conflict_type == "bank_account_currency_unsupported"]
    assert v4, "expected a bank-account eligibility finding"
    assert v4[0].evidence.get("semantic") is None
    assert "pr2_todo" not in v4[0].evidence
