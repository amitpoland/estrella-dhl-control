"""Canonical financial aging buckets — single authority for AR/AP/MIS.

Approved buckets (per currency; invariant sum(buckets) == open balance):

  not_due | b_1_30 | b_31_60 | b_61_90 | b_91_180 | b_181_365 | b_365_plus

``due_date_unavailable`` is a data-quality lane for open amounts that cannot
be aged; it is included in open-balance reconciliation but is NOT one of the
seven business aging buckets.

This module must remain pure (no I/O). Consumers: accounting_analytics,
ledger_aggregator statement aging, CFO MIS, statement PDF.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, Iterable, Mapping

# Business aging buckets (ordered).
AGING_BUCKETS: tuple = (
    "not_due",
    "b_1_30",
    "b_31_60",
    "b_61_90",
    "b_91_180",
    "b_181_365",
    "b_365_plus",
)

# Extended set used in portfolio/summary payloads.
AGING_BUCKETS_WITH_UNAVAILABLE: tuple = AGING_BUCKETS + ("due_date_unavailable",)

AGING_LABELS: Dict[str, str] = {
    "not_due": "Not Due",
    "b_1_30": "1–30",
    "b_31_60": "31–60",
    "b_61_90": "61–90",
    "b_91_180": "91–180",
    "b_181_365": "181–365",
    "b_365_plus": "365+",
    "due_date_unavailable": "due n/a",
}


def due_bucket(days_overdue: int) -> str:
    """Map days-overdue (as_of − due_date) to a canonical bucket key.

    days_overdue <= 0 → not_due.
    """
    if days_overdue <= 0:
        return "not_due"
    if days_overdue <= 30:
        return "b_1_30"
    if days_overdue <= 60:
        return "b_31_60"
    if days_overdue <= 90:
        return "b_61_90"
    if days_overdue <= 180:
        return "b_91_180"
    if days_overdue <= 365:
        return "b_181_365"
    return "b_365_plus"


def empty_buckets(*, include_unavailable: bool = True) -> Dict[str, Decimal]:
    keys = AGING_BUCKETS_WITH_UNAVAILABLE if include_unavailable else AGING_BUCKETS
    return {b: Decimal("0") for b in keys}


def sum_buckets(
    rows: Iterable[Mapping[str, object]],
    *,
    include_unavailable: bool = True,
) -> Dict[str, Decimal]:
    keys = AGING_BUCKETS_WITH_UNAVAILABLE if include_unavailable else AGING_BUCKETS
    acc = {b: Decimal("0") for b in keys}
    for r in rows:
        for b in keys:
            v = r.get(b)
            if v is None:
                continue
            acc[b] += Decimal(str(v))
    return acc


def overdue_total(buckets: Mapping[str, object]) -> Decimal:
    """Sum of all positive overdue buckets (excludes not_due + unavailable)."""
    total = Decimal("0")
    for b in AGING_BUCKETS:
        if b == "not_due":
            continue
        v = buckets.get(b)
        if v is not None:
            total += Decimal(str(v))
    return total


def open_total(buckets: Mapping[str, object], *, include_unavailable: bool = True) -> Decimal:
    """Sum of aging lanes that constitute open receivable/payable."""
    keys = AGING_BUCKETS_WITH_UNAVAILABLE if include_unavailable else AGING_BUCKETS
    total = Decimal("0")
    for b in keys:
        v = buckets.get(b)
        if v is not None:
            total += Decimal(str(v))
    return total


def buckets_reconcile(
    buckets: Mapping[str, object],
    expected_open: object,
    *,
    include_unavailable: bool = True,
    tol: Decimal = Decimal("0.01"),
) -> bool:
    """True when sum(buckets) == expected_open within tol (per-currency)."""
    got = open_total(buckets, include_unavailable=include_unavailable)
    exp = Decimal(str(expected_open or 0))
    return abs(got - exp) <= tol
