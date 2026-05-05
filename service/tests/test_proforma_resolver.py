"""
test_proforma_resolver.py — unit tests for the proforma resolver.

NEVER hits wFirma. fetch_contractor_terms() is exercised against a
patched _http_request, so no network is required.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest


def _ensure_path() -> None:
    here = Path(__file__).resolve()
    service_dir = here.parents[1]
    repo_root   = here.parents[2]
    for p in (str(service_dir), str(repo_root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_path()

from app.models.vat_resolver import CustomerForVAT, ManualReviewRequired   # noqa: E402
from app.models.proforma_resolver import (                                  # noqa: E402
    BANK_ACCOUNT_BY_CURRENCY,
    COMPANY_ACCOUNT_BY_CURRENCY,
    DEFAULT_LANGUAGE_ID,
    ContractorTerms,
    ProformaResolution,
    ProformaResolutionBlocked,
    fetch_contractor_terms,
    resolve_proforma,
)


# ── Constants pinned ─────────────────────────────────────────────────────────

def test_company_account_map_locked_to_live_ids():
    assert COMPANY_ACCOUNT_BY_CURRENCY == {
        "PLN": "180686",
        "USD": "169589",
        "EUR": "194483",
    }


def test_bank_account_alias_points_to_same_map():
    """Backward-compat alias must equal the canonical map."""
    assert BANK_ACCOUNT_BY_CURRENCY is COMPANY_ACCOUNT_BY_CURRENCY


def test_default_language_id_is_1():
    assert DEFAULT_LANGUAGE_ID == "1"


# ── Bank account selection ──────────────────────────────────────────────────

@pytest.mark.parametrize("currency,expected_account", [
    ("PLN", "180686"),
    ("USD", "169589"),
    ("EUR", "194483"),
])
def test_bank_account_resolves_by_currency(currency, expected_account):
    res = resolve_proforma(
        customer       = CustomerForVAT(country="PL"),
        currency       = currency,
        contractor     = ContractorTerms("X", "transfer", 7),
        document_date  = date(2026, 5, 3),
    )
    assert res.company_account_id == expected_account
    assert res.bank_account_id    == expected_account   # alias still works


def test_currency_lowercase_normalises():
    res = resolve_proforma(
        customer       = CustomerForVAT(country="PL"),
        currency       = "pln",
        contractor     = ContractorTerms("X", "transfer", 7),
        document_date  = date(2026, 5, 3),
    )
    assert res.company_account_id == "180686"


def test_unknown_currency_blocks():
    with pytest.raises(ProformaResolutionBlocked) as exc:
        resolve_proforma(
            customer       = CustomerForVAT(country="PL"),
            currency       = "JPY",
            contractor     = ContractorTerms("X", "transfer", 7),
            document_date  = date(2026, 5, 3),
        )
    assert "JPY" in str(exc.value)


# ── VAT routing ──────────────────────────────────────────────────────────────

def test_vat_pl_customer():
    res = resolve_proforma(
        customer       = CustomerForVAT(country="PL"),
        currency       = "PLN",
        contractor     = ContractorTerms("X", "transfer", 14),
        document_date  = date(2026, 5, 3),
    )
    assert res.vat_code_id == 222


def test_vat_eu_with_valid_vat_eu():
    res = resolve_proforma(
        customer       = CustomerForVAT(country="DE", vat_eu_valid=True),
        currency       = "EUR",
        contractor     = ContractorTerms("X", "transfer", 14),
        document_date  = date(2026, 5, 3),
    )
    assert res.vat_code_id == 228


def test_vat_non_eu():
    res = resolve_proforma(
        customer       = CustomerForVAT(country="IN"),
        currency       = "USD",
        contractor     = ContractorTerms("X", "transfer", 30),
        document_date  = date(2026, 5, 3),
    )
    assert res.vat_code_id == 229


def test_vat_eu_unverified_raises():
    """Ambiguous EU case bubbles up from vat_resolver."""
    with pytest.raises(ManualReviewRequired):
        resolve_proforma(
            customer       = CustomerForVAT(country="DE", vat_eu_valid=False),
            currency       = "EUR",
            contractor     = ContractorTerms("X", "transfer", 14),
            document_date  = date(2026, 5, 3),
        )


# ── Language map ─────────────────────────────────────────────────────────────

def test_language_defaults_to_id_1_when_no_map():
    res = resolve_proforma(
        customer       = CustomerForVAT(country="DE", vat_eu_valid=True),
        currency       = "EUR",
        contractor     = ContractorTerms("X", "transfer", 14),
        document_date  = date(2026, 5, 3),
    )
    assert res.language_id == "1"


def test_language_uses_operator_supplied_map():
    lang_map = {"PL": 1, "EN": 2, "DE": 3, "FR": 4}
    res = resolve_proforma(
        customer       = CustomerForVAT(country="DE", vat_eu_valid=True),
        currency       = "EUR",
        contractor     = ContractorTerms("X", "transfer", 14),
        document_date  = date(2026, 5, 3),
        lang_map       = lang_map,
    )
    assert res.language_id == "3"


def test_language_country_not_in_map_falls_back_to_default():
    lang_map = {"PL": 1, "DE": 3}
    res = resolve_proforma(
        customer       = CustomerForVAT(country="JP"),
        currency       = "USD",
        contractor     = ContractorTerms("X", "transfer", 14),
        document_date  = date(2026, 5, 3),
        lang_map       = lang_map,
    )
    assert res.language_id == "1"


def test_language_country_lowercase_normalises():
    lang_map = {"DE": 3}
    res = resolve_proforma(
        customer       = CustomerForVAT(country="de", vat_eu_valid=True),
        currency       = "EUR",
        contractor     = ContractorTerms("X", "transfer", 14),
        document_date  = date(2026, 5, 3),
        lang_map       = lang_map,
    )
    assert res.language_id == "3"


# ── default_language_id override (operator config) ───────────────────────────

def test_default_language_id_default_kwarg_value():
    """No override → falls back to module DEFAULT_LANGUAGE_ID = '1'."""
    res = resolve_proforma(
        customer       = CustomerForVAT(country="JP"),
        currency       = "USD",
        contractor     = ContractorTerms("X", "transfer", 14),
        document_date  = date(2026, 5, 3),
    )
    assert res.language_id == DEFAULT_LANGUAGE_ID == "1"


def test_default_language_id_override_takes_effect_when_country_missing_from_map():
    res = resolve_proforma(
        customer            = CustomerForVAT(country="JP"),
        currency            = "USD",
        contractor          = ContractorTerms("X", "transfer", 14),
        document_date       = date(2026, 5, 3),
        lang_map            = {"PL": 1, "DE": 3},
        default_language_id = "2",      # operator says "fallback to English (id=2)"
    )
    assert res.language_id == "2"


def test_default_language_id_override_accepts_int_or_str():
    """Operator config might serialise as int from JSON; resolver should coerce."""
    res = resolve_proforma(
        customer            = CustomerForVAT(country="JP"),
        currency            = "USD",
        contractor          = ContractorTerms("X", "transfer", 14),
        document_date       = date(2026, 5, 3),
        default_language_id = 2,        # int rather than str
    )
    assert res.language_id == "2"


def test_lang_map_beats_default_language_id():
    res = resolve_proforma(
        customer            = CustomerForVAT(country="DE", vat_eu_valid=True),
        currency            = "EUR",
        contractor          = ContractorTerms("X", "transfer", 14),
        document_date       = date(2026, 5, 3),
        lang_map            = {"DE": 3},
        default_language_id = "99",     # would be used only if DE was not mapped
    )
    assert res.language_id == "3"


@pytest.mark.parametrize("blank_value", ["", "  ", None])
def test_blank_default_language_id_blocks_when_country_not_in_map(blank_value):
    """Operator passes blank/None default → resolver MUST block (no silent guess)."""
    with pytest.raises(ProformaResolutionBlocked) as exc:
        resolve_proforma(
            customer            = CustomerForVAT(country="JP"),
            currency            = "USD",
            contractor          = ContractorTerms("X", "transfer", 14),
            document_date       = date(2026, 5, 3),
            lang_map            = {"PL": 1},
            default_language_id = blank_value,
        )
    assert "language not resolvable" in str(exc.value).lower()
    assert exc.value.details.get("country") == "JP"


def test_blank_default_language_id_okay_when_country_is_in_map():
    """If lang_map covers the country, blank default is irrelevant — no block."""
    res = resolve_proforma(
        customer            = CustomerForVAT(country="DE", vat_eu_valid=True),
        currency            = "EUR",
        contractor          = ContractorTerms("X", "transfer", 14),
        document_date       = date(2026, 5, 3),
        lang_map            = {"DE": 3},
        default_language_id = "",       # blank, but DE is in map → OK
    )
    assert res.language_id == "3"


def test_blank_country_with_blank_default_blocks():
    """Customer country missing AND default blank → block."""
    with pytest.raises(ProformaResolutionBlocked):
        resolve_proforma(
            customer            = CustomerForVAT(country="PL"),
            currency            = "PLN",
            contractor          = ContractorTerms("X", "transfer", 14),
            document_date       = date(2026, 5, 3),
            lang_map            = {},
            default_language_id = None,
        )


# ── Payment terms — contractor profile drives ──────────────────────────────

def test_uses_contractor_payment_method_and_days():
    res = resolve_proforma(
        customer       = CustomerForVAT(country="PL"),
        currency       = "PLN",
        contractor     = ContractorTerms("38582303", "transfer", 14),
        document_date  = date(2026, 5, 3),
    )
    assert res.payment_method == "transfer"
    assert res.payment_days   == 14
    assert res.payment_date   == date(2026, 5, 17)   # +14 days


def test_payment_method_missing_blocks():
    with pytest.raises(ProformaResolutionBlocked) as exc:
        resolve_proforma(
            customer       = CustomerForVAT(country="PL"),
            currency       = "PLN",
            contractor     = ContractorTerms("X", payment_method=None, payment_days=7),
            document_date  = date(2026, 5, 3),
        )
    assert "payment_method" in str(exc.value)
    assert "no fallback" in str(exc.value)


def test_payment_days_missing_blocks():
    with pytest.raises(ProformaResolutionBlocked) as exc:
        resolve_proforma(
            customer       = CustomerForVAT(country="PL"),
            currency       = "PLN",
            contractor     = ContractorTerms("X", "transfer", payment_days=None),
            document_date  = date(2026, 5, 3),
        )
    assert "payment_days" in str(exc.value)


def test_payment_days_zero_blocks():
    with pytest.raises(ProformaResolutionBlocked):
        resolve_proforma(
            customer       = CustomerForVAT(country="PL"),
            currency       = "PLN",
            contractor     = ContractorTerms("X", "transfer", payment_days=0),
            document_date  = date(2026, 5, 3),
        )


def test_payment_method_fallback_used_only_when_supplied():
    res = resolve_proforma(
        customer                 = CustomerForVAT(country="PL"),
        currency                 = "PLN",
        contractor               = ContractorTerms("X", payment_method=None, payment_days=7),
        document_date            = date(2026, 5, 3),
        fallback_payment_method  = "transfer",
    )
    assert res.payment_method == "transfer"


def test_payment_days_fallback_used_only_when_supplied():
    res = resolve_proforma(
        customer               = CustomerForVAT(country="PL"),
        currency               = "PLN",
        contractor             = ContractorTerms("X", "transfer", payment_days=None),
        document_date          = date(2026, 5, 3),
        fallback_payment_days  = 7,
    )
    assert res.payment_days == 7
    assert res.payment_date == date(2026, 5, 10)


def test_contractor_value_overrides_fallback():
    """Contractor profile beats fallback — explicit data wins."""
    res = resolve_proforma(
        customer                 = CustomerForVAT(country="PL"),
        currency                 = "PLN",
        contractor               = ContractorTerms("X", "card", 21),
        document_date            = date(2026, 5, 3),
        fallback_payment_method  = "transfer",
        fallback_payment_days    = 7,
    )
    assert res.payment_method == "card"
    assert res.payment_days   == 21


def test_negative_fallback_days_blocks():
    with pytest.raises(ProformaResolutionBlocked):
        resolve_proforma(
            customer               = CustomerForVAT(country="PL"),
            currency               = "PLN",
            contractor             = ContractorTerms("X", "transfer", payment_days=None),
            document_date          = date(2026, 5, 3),
            fallback_payment_days  = -3,
        )


# ── End-to-end full resolution ───────────────────────────────────────────────

def test_full_resolution_pl_customer_pln():
    res = resolve_proforma(
        customer       = CustomerForVAT(country="PL"),
        currency       = "PLN",
        contractor     = ContractorTerms("38582303", "transfer", 14),
        document_date  = date(2026, 5, 3),
    )
    assert res.to_dict() == {
        "vat_code_id":         222,
        "language_id":         "1",
        "company_account_id":  "180686",
        "payment_method":      "transfer",
        "payment_days":        14,
        "payment_date":        "2026-05-17",
    }


def test_full_resolution_german_b2b_eur():
    res = resolve_proforma(
        customer       = CustomerForVAT(country="DE", vat_eu_valid=True),
        currency       = "EUR",
        contractor     = ContractorTerms("99999999", "transfer", 30),
        document_date  = date(2026, 5, 3),
        lang_map       = {"DE": 3},
    )
    assert res.vat_code_id     == 228
    assert res.language_id     == "3"
    assert res.company_account_id == "194483"
    assert res.payment_method  == "transfer"
    assert res.payment_days    == 30
    assert res.payment_date    == date(2026, 6, 2)


def test_full_resolution_us_customer_usd():
    res = resolve_proforma(
        customer       = CustomerForVAT(country="US"),
        currency       = "USD",
        contractor     = ContractorTerms("88888888", "transfer", 60),
        document_date  = date(2026, 5, 3),
    )
    assert res.vat_code_id     == 229     # EXP 0%
    assert res.company_account_id == "169589"
    assert res.payment_date    == date(2026, 7, 2)


# ── Pure function: no side effects ───────────────────────────────────────────

def test_resolver_is_pure_no_side_effects():
    args = dict(
        customer       = CustomerForVAT(country="PL"),
        currency       = "PLN",
        contractor     = ContractorTerms("X", "transfer", 14),
        document_date  = date(2026, 5, 3),
    )
    a = resolve_proforma(**args)
    b = resolve_proforma(**args)
    c = resolve_proforma(**args)
    assert a == b == c


# ── fetch_contractor_terms — mocked HTTP, no live wFirma ────────────────────

def _fake_contractor_xml(payment_method: str = "transfer", payment_days: str = "7"):
    return f"""<?xml version="1.0"?>
<api>
  <contractors>
    <contractor>
      <id>38582303</id>
      <name>Test contractor</name>
      <payment_method>{payment_method}</payment_method>
      <payment_days>{payment_days}</payment_days>
    </contractor>
  </contractors>
  <status><code>OK</code></status>
</api>"""


def test_fetch_contractor_terms_parses_payment_fields():
    from app.services import wfirma_client as wfc

    def fake_http(method, module, action, body=""):
        return 200, _fake_contractor_xml("transfer", "14")

    with patch.object(wfc, "_http_request", side_effect=fake_http):
        terms = fetch_contractor_terms("38582303")
    assert terms.contractor_id  == "38582303"
    assert terms.payment_method == "transfer"
    assert terms.payment_days   == 14


def test_fetch_contractor_terms_handles_empty_fields():
    from app.services import wfirma_client as wfc

    def fake_http(method, module, action, body=""):
        return 200, _fake_contractor_xml("", "")

    with patch.object(wfc, "_http_request", side_effect=fake_http):
        terms = fetch_contractor_terms("X")
    assert terms.payment_method is None
    assert terms.payment_days   is None


def test_fetch_contractor_terms_raises_on_unknown_id():
    from app.services import wfirma_client as wfc

    body = """<?xml version="1.0"?><api><contractors></contractors><status><code>OK</code></status></api>"""

    def fake_http(method, module, action, body_xml=""):
        return 200, body

    with patch.object(wfc, "_http_request", side_effect=fake_http):
        with pytest.raises(ValueError, match="not found"):
            fetch_contractor_terms("9999999")


def test_fetch_contractor_terms_raises_on_http_error():
    from app.services import wfirma_client as wfc

    def fake_http(method, module, action, body=""):
        return 500, "<server error>"

    with patch.object(wfc, "_http_request", side_effect=fake_http):
        with pytest.raises(ConnectionError, match="HTTP 500"):
            fetch_contractor_terms("X")


def test_fetch_contractor_terms_no_live_http_call_in_tests():
    """Sanity: the fetcher uses _http_request which we patched. If a future
    code change introduces a direct requests call, this test catches it."""
    from app.services import wfirma_client as wfc
    calls = []

    def fake_http(method, module, action, body=""):
        calls.append((method, module, action))
        return 200, _fake_contractor_xml()

    with patch.object(wfc, "_http_request", side_effect=fake_http):
        fetch_contractor_terms("38582303")
    assert calls == [("GET", "contractors", "find")]


# ── Block exception carries diagnostic details ──────────────────────────────

def test_block_exception_carries_details():
    try:
        resolve_proforma(
            customer       = CustomerForVAT(country="PL"),
            currency       = "PLN",
            contractor     = ContractorTerms("CUST_42", "transfer", payment_days=None),
            document_date  = date(2026, 5, 3),
        )
    except ProformaResolutionBlocked as e:
        assert e.details.get("contractor_id") == "CUST_42"
    else:
        pytest.fail("expected block")
