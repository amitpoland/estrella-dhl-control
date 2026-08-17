"""test_wfirma_payment_db_as_of.py — expense_id column + list_payments_as_of."""
from __future__ import annotations

from pathlib import Path

from app.services.wfirma_payment_db import (
    init_payment_db,
    insert_payment_snapshot,
    list_payments_as_of,
)


def test_list_payments_as_of_and_expense_id_column(tmp_path: Path):
    db = tmp_path / "pay.db"
    init_payment_db(db)
    # Existing INSERT path still works (expense_id additive, not required).
    assert insert_payment_snapshot(
        db,
        payment_id="P1",
        contractor_id="C1",
        invoice_id="I1",
        payment_date="2026-03-01",
        value="10.00",
        value_pln="40.00",
        currency_label="",
        payment_method=None,
        payment_type=None,
        type_=None,
        notes=None,
        fetched_at="2026-08-17T00:00:00+00:00",
        raw_json="{}",
    )
    assert insert_payment_snapshot(
        db,
        payment_id="P2",
        contractor_id="C1",
        invoice_id="I1",
        payment_date="2026-08-01",
        value="5.00",
        value_pln="20.00",
        currency_label="",
        payment_method=None,
        payment_type=None,
        type_=None,
        notes=None,
        fetched_at="2026-08-17T00:00:00+00:00",
        raw_json="{}",
    )
    rows = list_payments_as_of(db, "2026-06-30")
    ids = {r["payment_id"] for r in rows}
    assert ids == {"P1"}
    assert "expense_id" in rows[0]

    filtered = list_payments_as_of(db, "2026-12-31", invoice_ids=["I1"])
    assert {r["payment_id"] for r in filtered} == {"P1", "P2"}

    empty = list_payments_as_of(db, "2026-12-31", invoice_ids=["NOPE"])
    assert empty == []


def test_insert_persists_expense_id_and_as_of_includes_old_payment(tmp_path: Path):
    db = tmp_path / "pay.db"
    init_payment_db(db)
    assert insert_payment_snapshot(
        db,
        payment_id="P_OLD",
        contractor_id="C1",
        invoice_id="",
        expense_id="E9",
        payment_date="2025-01-01",
        value="12.00",
        value_pln=None,
        currency_label="",
        payment_method=None,
        payment_type=None,
        type_=None,
        notes=None,
        fetched_at="2026-08-17T00:00:00+00:00",
        raw_json="{}",
    )
    rows = list_payments_as_of(db, "2026-08-17")
    assert rows[0]["payment_id"] == "P_OLD"
    assert rows[0]["expense_id"] == "E9"
