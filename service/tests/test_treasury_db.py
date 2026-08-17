"""Unit tests for treasury_db — additive balances + immutable close history."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.services.treasury_db import (
    BalanceSnapshot,
    init_db,
    insert_balance_snapshot,
    insert_daily_close,
    latest_balances_as_of,
)


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    p = tmp_path / "treasury.sqlite"
    init_db(p)
    return p


def test_insert_and_latest_balance(db: Path):
    insert_balance_snapshot(
        db,
        BalanceSnapshot(
            effective_date="2026-08-15",
            account_location="mBank PLN",
            currency="PLN",
            closing_balance=Decimal("1000.00"),
            source="MANUAL",
            operator="tester",
        ),
    )
    insert_balance_snapshot(
        db,
        BalanceSnapshot(
            effective_date="2026-08-16",
            account_location="mBank PLN",
            currency="PLN",
            closing_balance=Decimal("1100.50"),
            source="MANUAL",
            operator="tester",
        ),
    )
    rows = latest_balances_as_of(db, "2026-08-16")
    assert len(rows) == 1
    assert rows[0]["closing_balance"] == "1100.50"
    assert rows[0]["effective_date"] == "2026-08-16"

    as_of_15 = latest_balances_as_of(db, "2026-08-15")
    assert as_of_15[0]["closing_balance"] == "1000.00"


def test_correction_does_not_overwrite(db: Path):
    first = insert_balance_snapshot(
        db,
        BalanceSnapshot(
            effective_date="2026-08-16",
            account_location="Cash EUR",
            currency="EUR",
            closing_balance=Decimal("50.00"),
            source="MANUAL",
        ),
    )
    insert_balance_snapshot(
        db,
        BalanceSnapshot(
            effective_date="2026-08-16",
            account_location="Cash EUR",
            currency="EUR",
            closing_balance=Decimal("55.00"),
            source="MANUAL",
            correction_of_id=first,
            reference_note="count correction",
        ),
    )
    rows = latest_balances_as_of(db, "2026-08-16")
    assert len(rows) == 1
    assert rows[0]["closing_balance"] == "55.00"
    assert rows[0]["correction_of_id"] == first


def test_daily_close_statuses(db: Path):
    cid = insert_daily_close(
        db,
        close_date="2026-08-16",
        status="INCOMPLETE",
        bank_balances_ok=True,
    )
    assert cid > 0
    with pytest.raises(ValueError):
        insert_daily_close(db, close_date="2026-08-16", status="BOGUS")
