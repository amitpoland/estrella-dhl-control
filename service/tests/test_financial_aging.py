"""test_financial_aging.py — canonical bucket boundaries + reconcile invariant."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.financial_aging import (
    AGING_BUCKETS,
    AGING_BUCKETS_WITH_UNAVAILABLE,
    buckets_reconcile,
    due_bucket,
    empty_buckets,
    open_total,
    overdue_total,
    sum_buckets,
)


@pytest.mark.parametrize(
    "days, expected",
    [
        (-5, "not_due"),
        (0, "not_due"),
        (1, "b_1_30"),
        (30, "b_1_30"),
        (31, "b_31_60"),
        (60, "b_31_60"),
        (61, "b_61_90"),
        (90, "b_61_90"),
        (91, "b_91_180"),
        (180, "b_91_180"),
        (181, "b_181_365"),
        (365, "b_181_365"),
        (366, "b_365_plus"),
        (900, "b_365_plus"),
    ],
)
def test_due_bucket_boundaries(days, expected):
    assert due_bucket(days) == expected


def test_seven_business_buckets_plus_unavailable():
    assert AGING_BUCKETS == (
        "not_due",
        "b_1_30",
        "b_31_60",
        "b_61_90",
        "b_91_180",
        "b_181_365",
        "b_365_plus",
    )
    assert AGING_BUCKETS_WITH_UNAVAILABLE[-1] == "due_date_unavailable"
    assert len(AGING_BUCKETS_WITH_UNAVAILABLE) == 8


def test_empty_and_sum_buckets():
    empty = empty_buckets()
    assert set(empty) == set(AGING_BUCKETS_WITH_UNAVAILABLE)
    assert all(v == Decimal("0") for v in empty.values())
    rows = [
        {**empty_buckets(), "b_1_30": Decimal("10"), "not_due": Decimal("5")},
        {**empty_buckets(), "b_365_plus": Decimal("3"), "due_date_unavailable": Decimal("2")},
    ]
    acc = sum_buckets(rows)
    assert acc["b_1_30"] == Decimal("10")
    assert acc["not_due"] == Decimal("5")
    assert acc["b_365_plus"] == Decimal("3")
    assert acc["due_date_unavailable"] == Decimal("2")


def test_overdue_excludes_not_due_and_unavailable():
    b = empty_buckets()
    b["not_due"] = Decimal("100")
    b["b_1_30"] = Decimal("10")
    b["b_365_plus"] = Decimal("5")
    b["due_date_unavailable"] = Decimal("7")
    assert overdue_total(b) == Decimal("15")
    assert open_total(b) == Decimal("122")


def test_buckets_reconcile_invariant():
    b = empty_buckets()
    b["not_due"] = Decimal("40.00")
    b["b_91_180"] = Decimal("60.00")
    assert buckets_reconcile(b, Decimal("100.00")) is True
    assert buckets_reconcile(b, Decimal("99.00")) is False
    assert buckets_reconcile(b, Decimal("100.005")) is True  # within 0.01
