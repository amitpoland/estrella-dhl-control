"""AP payment→expense persistence, backfill, and local remaining knock-off."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.services.accounting_analytics import build_payables_analysis
from app.services.financial_reporting_db import (
    ApExpenseReportingRow,
    ArInvoiceReportingRow,
    set_sync_state,
    upsert_ap_expense,
    upsert_ar_invoice,
)
from app.services.wfirma_payment_db import (
    init_payment_db,
    insert_payment_snapshot,
    list_payments_as_of,
    payment_expense_link_coverage,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_projection(root: Path) -> None:
    """AR row required so local_projection_available() is True."""
    rep = root / "financial_reporting.sqlite"
    upsert_ar_invoice(
        rep,
        ArInvoiceReportingRow(
            invoice_id="AR1",
            contractor_id="C1",
            document_type="normal",
            issue_date="2026-01-01",
            due_date="2026-01-31",
            currency="USD",
            gross=Decimal("1.00"),
        ),
    )
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    set_sync_state(
        rep, "ar_invoices",
        last_full_sync_at=now,
        last_reconcile_at=now,
        row_count=1,
        status="ok",
    )
    set_sync_state(
        rep, "ap_expenses",
        last_full_sync_at=now,
        last_reconcile_at=now,
        row_count=1,
        status="ok",
    )


def _pay(
    db: Path,
    *,
    payment_id: str,
    contractor_id: str,
    expense_id: str,
    value: str,
    payment_date: str,
    invoice_id: str = "",
    converge: bool = False,
) -> bool:
    init_payment_db(db)
    return insert_payment_snapshot(
        db,
        payment_id=payment_id,
        contractor_id=contractor_id,
        invoice_id=invoice_id,
        expense_id=expense_id,
        payment_date=payment_date,
        value=value,
        value_pln=None,
        currency_label="",
        payment_method=None,
        payment_type=None,
        type_=None,
        notes=None,
        fetched_at=_now(),
        raw_json="{}",
        converge_expense_link=converge,
    )


def test_insert_persists_expense_relationship(tmp_path: Path):
    db = tmp_path / "payment_state.db"
    assert _pay(
        db, payment_id="P1", contractor_id="S1", expense_id="E1",
        value="25.00", payment_date="2026-03-20",
    ) is True
    rows = list_payments_as_of(db, "2026-08-17")
    assert rows[0]["expense_id"] == "E1"
    cov = payment_expense_link_coverage(db)
    assert cov == {
        "payments_total": 1,
        "with_expense_relationship": 1,
        "without_expense_relationship": 0,
    }


def test_sentinel_zero_is_unapplied(tmp_path: Path):
    db = tmp_path / "payment_state.db"
    _pay(
        db, payment_id="P1", contractor_id="S1", expense_id="0",
        value="25.00", payment_date="2026-03-20",
    )
    rows = list_payments_as_of(db, "2026-08-17")
    assert rows[0]["expense_id"] in ("", None)
    cov = payment_expense_link_coverage(db)
    assert cov["with_expense_relationship"] == 0
    assert cov["without_expense_relationship"] == 1


def test_converge_fills_existing_without_duplicate(tmp_path: Path):
    db = tmp_path / "payment_state.db"
    _pay(
        db, payment_id="P1", contractor_id="S1", expense_id="",
        value="25.00", payment_date="2026-03-20",
    )
    again = _pay(
        db, payment_id="P1", contractor_id="S9", expense_id="E1",
        value="99.00", payment_date="2099-01-01", converge=True,
    )
    assert again is False
    rows = list_payments_as_of(db, "2026-08-17")
    assert len(rows) == 1
    assert rows[0]["expense_id"] == "E1"
    assert rows[0]["contractor_id"] == "S1"
    assert rows[0]["value"] == "25.00"


def test_replay_without_converge_does_not_relink(tmp_path: Path):
    db = tmp_path / "payment_state.db"
    _pay(
        db, payment_id="P1", contractor_id="S1", expense_id="",
        value="25.00", payment_date="2026-03-20",
    )
    _pay(
        db, payment_id="P1", contractor_id="S1", expense_id="E1",
        value="25.00", payment_date="2026-03-20", converge=False,
    )
    rows = list_payments_as_of(db, "2026-08-17")
    assert rows[0]["expense_id"] in ("", None)


def _local_ap(tmp_path: Path, expenses, payments):
    _seed_projection(tmp_path)
    rep = tmp_path / "financial_reporting.sqlite"
    for e in expenses:
        upsert_ap_expense(rep, e)
    pay_db = tmp_path / "payment_state.db"
    for p in payments:
        _pay(pay_db, **p)
    return build_payables_analysis(
        date_from="2026-01-01",
        date_to="2026-08-17",
        as_of="2026-08-17",
        source="local",
        storage_root=tmp_path,
    )


def test_full_payment_reduces_local_ap(tmp_path: Path):
    body = _local_ap(
        tmp_path,
        [ApExpenseReportingRow(
            expense_id="E1", supplier_id="S1", supplier_name="Vendor",
            document_type="normal", document_number="FZ 1",
            issue_date="2026-04-01", due_date="2026-04-30",
            currency="USD", gross=Decimal("100.00"),
        )],
        [dict(payment_id="P1", contractor_id="S1", expense_id="E1",
              value="100.00", payment_date="2026-04-15")],
    )
    usd = next(s for s in body["currency_summaries"] if s["currency"] == "USD")
    assert Decimal(usd["gross_payable"]) == Decimal("0.00")


def test_partial_payment_reduces_local_ap(tmp_path: Path):
    body = _local_ap(
        tmp_path,
        [ApExpenseReportingRow(
            expense_id="E1", supplier_id="S1", supplier_name="Vendor",
            document_type="normal", issue_date="2026-04-01",
            due_date="2026-04-30", currency="EUR", gross=Decimal("200.00"),
        )],
        [dict(payment_id="P1", contractor_id="S1", expense_id="E1",
              value="50.00", payment_date="2026-04-10")],
    )
    eur = next(s for s in body["currency_summaries"] if s["currency"] == "EUR")
    assert Decimal(eur["gross_payable"]) == Decimal("150.00")


def test_multiple_payments_do_not_double_count(tmp_path: Path):
    body = _local_ap(
        tmp_path,
        [ApExpenseReportingRow(
            expense_id="E1", supplier_id="S1", supplier_name="Vendor",
            document_type="normal", issue_date="2026-04-01",
            due_date="2026-04-30", currency="USD", gross=Decimal("100.00"),
        )],
        [
            dict(payment_id="P1", contractor_id="S1", expense_id="E1",
                 value="30.00", payment_date="2026-04-10"),
            dict(payment_id="P2", contractor_id="S1", expense_id="E1",
                 value="20.00", payment_date="2026-04-11"),
        ],
    )
    usd = next(s for s in body["currency_summaries"] if s["currency"] == "USD")
    assert Decimal(usd["gross_payable"]) == Decimal("50.00")


def test_replayed_snapshot_does_not_double_knockoff(tmp_path: Path):
    db = tmp_path / "payment_state.db"
    _seed_projection(tmp_path)
    upsert_ap_expense(
        tmp_path / "financial_reporting.sqlite",
        ApExpenseReportingRow(
            expense_id="E1", supplier_id="S1", supplier_name="Vendor",
            document_type="normal", issue_date="2026-04-01",
            due_date="2026-04-30", currency="USD", gross=Decimal("100.00"),
        ),
    )
    kwargs = dict(
        payment_id="P1", contractor_id="S1", expense_id="E1",
        value="40.00", payment_date="2026-04-10",
    )
    assert _pay(db, **kwargs) is True
    assert _pay(db, converge=True, **kwargs) is False
    body = build_payables_analysis(
        date_from="2026-01-01", date_to="2026-08-17", as_of="2026-08-17",
        source="local", storage_root=tmp_path,
    )
    usd = next(s for s in body["currency_summaries"] if s["currency"] == "USD")
    assert Decimal(usd["gross_payable"]) == Decimal("60.00")


def test_payment_outside_activity_window_still_affects_as_of(tmp_path: Path):
    body = _local_ap(
        tmp_path,
        [ApExpenseReportingRow(
            expense_id="E1", supplier_id="S1", supplier_name="Vendor",
            document_type="normal", issue_date="2026-07-01",
            due_date="2026-07-31", currency="USD", gross=Decimal("100.00"),
        )],
        [dict(payment_id="P1", contractor_id="S1", expense_id="E1",
              value="25.00", payment_date="2025-12-01")],
    )
    usd = next(s for s in body["currency_summaries"] if s["currency"] == "USD")
    assert Decimal(usd["gross_payable"]) == Decimal("75.00")


def test_unapplied_payment_does_not_reduce_ap(tmp_path: Path):
    body = _local_ap(
        tmp_path,
        [ApExpenseReportingRow(
            expense_id="E1", supplier_id="S1", supplier_name="Vendor",
            document_type="normal", issue_date="2026-04-01",
            due_date="2026-04-30", currency="USD", gross=Decimal("100.00"),
        )],
        [dict(payment_id="P1", contractor_id="S1", expense_id="",
              value="100.00", payment_date="2026-04-15")],
    )
    usd = next(s for s in body["currency_summaries"] if s["currency"] == "USD")
    assert Decimal(usd["gross_payable"]) == Decimal("100.00")


def test_wrong_expense_is_not_used_for_other_document(tmp_path: Path):
    body = _local_ap(
        tmp_path,
        [
            ApExpenseReportingRow(
                expense_id="E1", supplier_id="S1", supplier_name="Vendor",
                document_type="normal", issue_date="2026-04-01",
                due_date="2026-04-30", currency="USD", gross=Decimal("100.00"),
            ),
            ApExpenseReportingRow(
                expense_id="E2", supplier_id="S1", supplier_name="Vendor",
                document_type="normal", issue_date="2026-04-02",
                due_date="2026-04-30", currency="USD", gross=Decimal("80.00"),
            ),
        ],
        [dict(payment_id="P1", contractor_id="S1", expense_id="E1",
              value="100.00", payment_date="2026-04-15")],
    )
    usd = next(s for s in body["currency_summaries"] if s["currency"] == "USD")
    # E1 fully paid, E2 still open
    assert Decimal(usd["gross_payable"]) == Decimal("80.00")


def test_supplier_aggregation_and_aging_invariant(tmp_path: Path):
    body = _local_ap(
        tmp_path,
        [
            ApExpenseReportingRow(
                expense_id="E1", supplier_id="S1", supplier_name="Alpha",
                document_type="normal", issue_date="2026-04-01",
                due_date="2026-04-30", currency="USD", gross=Decimal("100.00"),
            ),
            ApExpenseReportingRow(
                expense_id="E2", supplier_id="S2", supplier_name="Beta",
                document_type="normal", issue_date="2026-04-01",
                due_date="2026-04-30", currency="USD", gross=Decimal("50.00"),
            ),
        ],
        [
            dict(payment_id="P1", contractor_id="S1", expense_id="E1",
                 value="40.00", payment_date="2026-04-15"),
        ],
    )
    usd = next(s for s in body["currency_summaries"] if s["currency"] == "USD")
    assert Decimal(usd["gross_payable"]) == Decimal("110.00")
    suppliers = {s["contractor_id"]: s for s in body["suppliers"]}
    assert Decimal(suppliers["S1"]["gross_payable"]) == Decimal("60.00")
    assert Decimal(suppliers["S2"]["gross_payable"]) == Decimal("50.00")
    assert Decimal(usd["aging_plus_unavailable"]) == Decimal(usd["gross_payable"])
    assert usd["reconciliation_ok"] is True
