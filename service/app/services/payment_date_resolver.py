# service/app/services/payment_date_resolver.py
"""
Payment due date computation with safety guard.

Rule: payment_due must never be earlier than invoice_date.
Base date for payment_days: max(sale_date, invoice_date).
"""
from datetime import date, timedelta
from typing import Optional


def compute_payment_due(
    invoice_date: date,
    sale_date: Optional[date] = None,
    payment_days: Optional[int] = None,
) -> date:
    """
    Compute payment due date.

    Base: max(sale_date, invoice_date) when sale_date is provided,
          invoice_date otherwise.

    This ensures payment_due >= invoice_date always.

    Examples:
        invoice_date=2026-06-28, sale_date=2026-06-25, days=0 → 2026-06-28
        invoice_date=2026-06-20, sale_date=2026-06-28, days=0 → 2026-06-28
        invoice_date=2026-06-28, sale_date=2026-06-25, days=14 → 2026-07-12
    """
    base = invoice_date
    if sale_date is not None:
        base = max(sale_date, invoice_date)
    days = payment_days if payment_days is not None else 0
    return base + timedelta(days=days)


def compute_payment_due_str(
    invoice_date_str: str,
    sale_date_str: Optional[str] = None,
    payment_days: Optional[int] = None,
) -> str:
    """String wrapper for use in route handlers."""
    inv = date.fromisoformat(invoice_date_str)
    sale = date.fromisoformat(sale_date_str) if sale_date_str else None
    return compute_payment_due(inv, sale, payment_days).isoformat()
