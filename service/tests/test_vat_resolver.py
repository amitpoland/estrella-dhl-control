"""
test_vat_resolver.py — unit tests for the wFirma vat_code resolver.

Coverage:
  - Polish domestic → 222 (23%)
  - EU + confirmed valid VAT-EU → 228 (WDT)
  - Non-EU → 229 (EXP)
  - EU + invalid/unknown VAT-EU → ManualReviewRequired
  - Missing/blank country → ManualReviewRequired
  - Country-code normalisation (case + whitespace)
  - Northern Ireland (XI) is NOT auto-EU
  - Constants are pinned to what wFirma actually returned
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from app.models.vat_resolver import (   # noqa: E402
    CustomerForVAT,
    EU_COUNTRIES,
    ManualReviewRequired,
    VAT_CODE_EXP,
    VAT_CODE_PL_23,
    VAT_CODE_WDT,
    pick_vat_code,
)


# ── Constants pinned ──────────────────────────────────────────────────────────

def test_constants_match_live_wfirma_ids():
    """These are LOCKED to what wFirma's vat_codes/find returned on 2026-05-03."""
    assert VAT_CODE_PL_23 == 222
    assert VAT_CODE_WDT   == 228
    assert VAT_CODE_EXP   == 229


def test_eu_countries_set_size_is_27():
    """EU has 27 members post-Brexit. UK is NOT in the set."""
    assert len(EU_COUNTRIES) == 27
    assert "GB" not in EU_COUNTRIES
    assert "UK" not in EU_COUNTRIES
    # Spot-check key members
    for c in ("DE", "FR", "IT", "ES", "PL", "NL", "PT", "RO", "SE", "FI"):
        assert c in EU_COUNTRIES


def test_xi_northern_ireland_not_auto_eu():
    """XI (NI Protocol) requires accountant sign-off before auto-treatment."""
    assert "XI" not in EU_COUNTRIES


# ── Polish domestic ──────────────────────────────────────────────────────────

def test_polish_customer_returns_222():
    c = CustomerForVAT(country="PL")
    assert pick_vat_code(c) == 222


def test_polish_customer_vat_eu_field_is_irrelevant():
    """For a Polish customer the vat_eu_valid flag is ignored."""
    for v in (True, False, None):
        c = CustomerForVAT(country="PL", vat_eu_valid=v)
        assert pick_vat_code(c) == 222


def test_polish_country_lowercase_normalises():
    c = CustomerForVAT(country="pl")
    assert pick_vat_code(c) == 222


def test_polish_country_with_whitespace_normalises():
    c = CustomerForVAT(country="  PL  ")
    assert pick_vat_code(c) == 222


# ── EU with valid VAT-EU → WDT ────────────────────────────────────────────────

@pytest.mark.parametrize("country", ["DE", "FR", "IT", "ES", "NL", "BE", "AT",
                                       "SE", "FI", "DK", "IE", "PT", "GR", "RO"])
def test_eu_customer_with_valid_vat_eu_returns_wdt(country):
    c = CustomerForVAT(country=country, vat_eu_valid=True, vat_eu_number=f"{country}123456789")
    assert pick_vat_code(c) == 228


def test_eu_customer_lowercase_country_normalises_to_wdt():
    c = CustomerForVAT(country="de", vat_eu_valid=True)
    assert pick_vat_code(c) == 228


# ── EU without valid VAT-EU → ManualReviewRequired ───────────────────────────

@pytest.mark.parametrize("vat_eu_valid", [False, None])
def test_eu_customer_without_valid_vat_eu_blocks(vat_eu_valid):
    c = CustomerForVAT(country="DE", vat_eu_valid=vat_eu_valid)
    with pytest.raises(ManualReviewRequired) as exc_info:
        pick_vat_code(c)
    assert "DE" in str(exc_info.value)
    assert "manual review" in str(exc_info.value).lower()


def test_eu_customer_with_vat_number_but_unverified_blocks():
    """Number present but vat_eu_valid not yet True → still block."""
    c = CustomerForVAT(country="FR", vat_eu_valid=None, vat_eu_number="FR12345678901")
    with pytest.raises(ManualReviewRequired):
        pick_vat_code(c)


def test_manual_review_carries_diagnostic_info():
    c = CustomerForVAT(country="DE", vat_eu_valid=False)
    with pytest.raises(ManualReviewRequired) as exc_info:
        pick_vat_code(c)
    assert exc_info.value.customer_country == "DE"
    assert exc_info.value.vat_eu_valid is False


# ── Non-EU → EXP ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("country", ["IN", "US", "GB", "CH", "NO", "AE", "JP",
                                       "AU", "CA", "SG", "BR", "IL", "TR"])
def test_non_eu_customer_returns_exp(country):
    """Non-EU customers (incl. UK, Switzerland, Norway) → 229 EXP regardless of vat_eu_valid."""
    for v in (True, False, None):
        c = CustomerForVAT(country=country, vat_eu_valid=v)
        assert pick_vat_code(c) == 229, f"{country} with vat_eu_valid={v}"


def test_uk_explicitly_not_eu_returns_exp():
    """Brexit guard: GB must NOT be treated as EU."""
    c = CustomerForVAT(country="GB", vat_eu_valid=True)
    assert pick_vat_code(c) == 229


def test_switzerland_explicitly_not_eu():
    c = CustomerForVAT(country="CH", vat_eu_valid=True)
    assert pick_vat_code(c) == 229


def test_norway_explicitly_not_eu():
    c = CustomerForVAT(country="NO", vat_eu_valid=True)
    assert pick_vat_code(c) == 229


def test_xi_falls_through_to_exp_until_explicit_eu_treatment():
    """XI is not in EU set → currently treated as non-EU (export). Accountant-sign-off needed
    before changing this. Test locks current behaviour."""
    c = CustomerForVAT(country="XI", vat_eu_valid=True)
    assert pick_vat_code(c) == 229


# ── Missing / invalid country ────────────────────────────────────────────────

def test_missing_country_blocks():
    c = CustomerForVAT(country=None)
    with pytest.raises(ManualReviewRequired) as exc_info:
        pick_vat_code(c)
    assert "country" in str(exc_info.value).lower()


def test_blank_country_blocks():
    c = CustomerForVAT(country="   ")
    with pytest.raises(ManualReviewRequired):
        pick_vat_code(c)


def test_empty_string_country_blocks():
    c = CustomerForVAT(country="")
    with pytest.raises(ManualReviewRequired):
        pick_vat_code(c)


# ── No silent fallback ────────────────────────────────────────────────────────

def test_resolver_never_silently_picks_pl_for_eu_invalid():
    """Critical liability guard: an EU customer without VAT-EU MUST NOT
    silently fall through to 23% PL — that would under/over-collect VAT
    depending on the case. Always raise."""
    c = CustomerForVAT(country="DE", vat_eu_valid=False)
    with pytest.raises(ManualReviewRequired):
        pick_vat_code(c)


def test_resolver_never_silently_picks_exp_for_eu_invalid():
    """Same guard, opposite direction: must not silently fall to EXP either."""
    c = CustomerForVAT(country="IT", vat_eu_valid=None)
    with pytest.raises(ManualReviewRequired):
        pick_vat_code(c)


# ── Pure function: no side effects ───────────────────────────────────────────

def test_resolver_is_pure_no_side_effects():
    """Same input, same output. Many calls must not change state."""
    c = CustomerForVAT(country="PL")
    results = [pick_vat_code(c) for _ in range(10)]
    assert all(r == 222 for r in results)
