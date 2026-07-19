"""Regression: _safe_float must not read a decimal comma as a thousands separator.

Before this fix both packing normalisers ran str.replace(",", "") unconditionally,
so "1234,56" became 123456.0 — a silent 100x overstatement on a money column.
The "1,554" -> 1554.0 grouped-thousands contract (EJL packing lists) must survive.
"""

import pytest

from app.services.invoice_packing_extractor import _safe_float
from app.services.global_packing_parser import _safe_float as _global_safe_float


CASES = [
    # grouped thousands - existing contract, must not regress
    ("1,554", 1554.0),
    ("$ 1,554", 1554.0),
    ("1,234,567", 1234567.0),
    ("USD 1,554.00", 1554.0),
    # decimal comma - the bug
    ("1234,56", 1234.56),
    ("1,5", 1.5),
    ("0,75", 0.75),
    ("12,3456", 12.3456),
    # european grouped + decimal comma
    ("1.234,56", 1234.56),
    ("1 234,56", 1234.56),
    (" 1.234.567,89", 1234567.89),
    # plain / currency-prefixed - unchanged
    ("$ 993", 993.0),
    ("  993 ", 993.0),
    ("EUR 12.50", 12.5),
    ("3.420", 3.420),
    (1554, 1554.0),
    (12.5, 12.5),
    # non-numeric and empty - never raise, always 0.0
    ("ite 1", 0.0),
    ("Total", 0.0),
    ("", 0.0),
    (None, 0.0),
    ([], 0.0),
]


@pytest.mark.parametrize("raw,expected", CASES)
def test_safe_float(raw, expected):
    assert _safe_float(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw,expected", CASES)
def test_global_parser_agrees(raw, expected):
    """global_packing_parser delegates - both parsers must normalise identically."""
    assert _global_safe_float(raw) == pytest.approx(expected)
