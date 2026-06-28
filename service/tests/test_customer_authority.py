# service/tests/test_customer_authority.py
"""
Tests proving Customer Master is the single authority for customer data.
Tests MUST FAIL until customer_authority.py is created (Task 9).
Run: cd service && pytest tests/test_customer_authority.py -v
"""
import pytest
from unittest.mock import MagicMock


def _make_cm(
    billing_name="OMARA s.r.o",
    billing_street="Test 1",
    billing_city="Prague",
    billing_postal="10000",
    billing_country="CZ",
    vat_id="CZ12345678",
    payment_method="transfer",
    payment_days=30,
    preferred_invoice_series_id="15827921",
    currency="EUR",
):
    cm = MagicMock()
    cm.name = billing_name
    cm.billing_name = billing_name
    cm.billing_street = billing_street
    cm.billing_city = billing_city
    cm.billing_postal_code = billing_postal
    cm.billing_country = billing_country
    cm.vat_id = vat_id
    cm.payment_method = payment_method
    cm.payment_terms_days = payment_days
    cm.preferred_invoice_series_id = preferred_invoice_series_id
    cm.currency = currency
    return cm


def test_proforma_uses_customer_master_billing_address():
    """
    Given: Customer Master has billing_street='Test Street 99'
    When: resolve_customer_for_proforma() is called
    Then: billing_street == 'Test Street 99'
    And:  authority == 'customer_master' (not wFirma)
    """
    from app.services.customer_authority import resolve_customer_for_proforma

    cm = _make_cm(billing_street="Test Street 99")
    result = resolve_customer_for_proforma(cm)
    assert result["billing_street"] == "Test Street 99"
    assert result["authority"] == "customer_master"


def test_commercial_defaults_from_customer_master():
    """
    Given: Customer Master has payment_terms_days=14
    When: resolve_customer_commercial_defaults() is called
    Then: payment_terms_days == 14
    And:  authority == 'customer_master'
    """
    from app.services.customer_authority import resolve_customer_commercial_defaults

    cm = _make_cm(payment_days=14)
    result = resolve_customer_commercial_defaults(cm)
    assert result["payment_terms_days"] == 14
    assert result["authority"] == "customer_master"


def test_wfirma_contractor_not_primary_source():
    """
    Given: Customer Master has payment_terms_days=30
    When: resolve_customer_commercial_defaults() is called
    Then: returns Customer Master values (authority='customer_master')
    Not wFirma contractor values.
    """
    from app.services.customer_authority import resolve_customer_commercial_defaults

    cm = _make_cm(payment_days=30)
    result = resolve_customer_commercial_defaults(cm)
    assert result["payment_terms_days"] == 30
    assert result["authority"] == "customer_master"


def test_wdt_context_overrides_to_wdt_series():
    """
    Given: VAT context is WDT, Customer Master preferred series is FV
    When: resolve_customer_commercial_defaults() is called with vat_context='wdt'
    Then: invoice_series_id is the WDT series (not the customer's FV preference)
    """
    from app.services.customer_authority import resolve_customer_commercial_defaults

    FV_SERIES = "15827088"
    WDT_SERIES = "15827921"
    cm = _make_cm(preferred_invoice_series_id=FV_SERIES)
    result = resolve_customer_commercial_defaults(
        cm, vat_context="wdt", wdt_series_id=WDT_SERIES
    )
    assert result["invoice_series_id"] == WDT_SERIES
    assert result["invoice_series_source"] == "vat_context_wdt"
