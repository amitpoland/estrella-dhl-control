# service/tests/test_payment_date_guard.py
"""
Tests for payment due date safety guard.
payment_due must never be earlier than invoice_date unless audited.
These MUST FAIL before Task 7 fix is applied.
Run: cd service && pytest tests/test_payment_date_guard.py -v
"""
import pytest
from datetime import date


def test_payment_due_not_before_invoice_date():
    """
    Given: invoice_date=2026-06-28, sale_date=2026-06-25, payment_days=0
    When: payment_due is computed
    Then: payment_due must be >= invoice_date (i.e. 2026-06-28)
    Proves Bug 2 from OMARA / FV 12/2026 incident.
    """
    from app.services.payment_date_resolver import compute_payment_due

    result = compute_payment_due(
        invoice_date=date(2026, 6, 28),
        sale_date=date(2026, 6, 25),
        payment_days=0,
    )
    assert result >= date(2026, 6, 28), (
        f"payment_due {result} must not be earlier than invoice_date 2026-06-28"
    )


def test_payment_due_zero_days_equals_invoice_date():
    """
    Given: payment_days=0, sale_date < invoice_date
    When: payment_due is computed
    Then: payment_due == invoice_date (clamped to invoice_date)
    """
    from app.services.payment_date_resolver import compute_payment_due

    result = compute_payment_due(
        invoice_date=date(2026, 6, 28),
        sale_date=date(2026, 6, 25),
        payment_days=0,
    )
    assert result == date(2026, 6, 28)


def test_payment_due_positive_days_base_clamped():
    """
    Given: invoice_date=2026-06-28, sale_date=2026-06-20, payment_days=14
    When: payment_due is computed
    Then: base = max(sale_date, invoice_date) = invoice_date
          payment_due = 2026-06-28 + 14 = 2026-07-12
    """
    from app.services.payment_date_resolver import compute_payment_due

    result = compute_payment_due(
        invoice_date=date(2026, 6, 28),
        sale_date=date(2026, 6, 20),
        payment_days=14,
    )
    assert result == date(2026, 7, 12), (
        f"expected 2026-07-12 (invoice_date + 14), got {result}"
    )


def test_payment_due_normal_terms():
    """
    Given: invoice_date=2026-06-28, sale_date=2026-06-28, payment_days=14
    When: payment_due is computed
    Then: payment_due = 2026-07-12
    """
    from app.services.payment_date_resolver import compute_payment_due

    result = compute_payment_due(
        invoice_date=date(2026, 6, 28),
        sale_date=date(2026, 6, 28),
        payment_days=14,
    )
    assert result == date(2026, 7, 12)


def test_payment_due_sale_after_invoice():
    """
    Given: invoice_date=2026-06-20, sale_date=2026-06-28, payment_days=0
    When: payment_due is computed
    Then: base = max(sale_date, invoice_date) = sale_date = 2026-06-28
          payment_due = 2026-06-28
    """
    from app.services.payment_date_resolver import compute_payment_due

    result = compute_payment_due(
        invoice_date=date(2026, 6, 20),
        sale_date=date(2026, 6, 28),
        payment_days=0,
    )
    assert result == date(2026, 6, 28)
