"""test_financial_reporting_db.py — upsert + as_of list helpers."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.services.financial_reporting_db import (
    ApExpenseReportingRow,
    ArInvoiceReportingRow,
    count_ap,
    count_ar,
    get_sync_state,
    list_ap_expenses_as_of,
    list_ar_invoices_as_of,
    set_sync_state,
    upsert_ap_expense,
    upsert_ar_invoice,
)


def test_upsert_ar_and_list_as_of(tmp_path: Path):
    db = tmp_path / "fr.sqlite"
    upsert_ar_invoice(
        db,
        ArInvoiceReportingRow(
            invoice_id="I1",
            contractor_id="C1",
            document_type="normal",
            invoice_number="WDT 1/2026",
            issue_date="2026-03-01",
            due_date="2026-03-31",
            currency="EUR",
            net=Decimal("100.00"),
            gross=Decimal("100.00"),
        ),
    )
    upsert_ar_invoice(
        db,
        ArInvoiceReportingRow(
            invoice_id="I2",
            contractor_id="C1",
            document_type="normal",
            issue_date="2026-08-01",
            due_date="2026-08-31",
            currency="EUR",
            gross=Decimal("50.00"),
        ),
    )
    # Proforma must be upsertable but excluded from fiscal as_of list defaults.
    upsert_ar_invoice(
        db,
        ArInvoiceReportingRow(
            invoice_id="P1",
            contractor_id="C1",
            document_type="proforma",
            issue_date="2026-02-01",
            currency="EUR",
            gross=Decimal("999.00"),
        ),
    )
    assert count_ar(db) == 3
    rows = list_ar_invoices_as_of(db, as_of="2026-06-30")
    ids = {r["invoice_id"] for r in rows}
    assert ids == {"I1"}
    assert all(r["document_type"] != "proforma" for r in rows)

    # Upsert updates in place
    upsert_ar_invoice(
        db,
        ArInvoiceReportingRow(
            invoice_id="I1",
            contractor_id="C1",
            document_type="normal",
            invoice_number="WDT 1/2026-R",
            issue_date="2026-03-01",
            due_date="2026-04-15",
            currency="EUR",
            gross=Decimal("110.00"),
        ),
    )
    again = list_ar_invoices_as_of(db, as_of="2026-06-30")
    assert len(again) == 1
    assert again[0]["invoice_number"] == "WDT 1/2026-R"
    assert again[0]["gross"] == "110.00"


def test_upsert_ap_and_sync_state(tmp_path: Path):
    db = tmp_path / "fr.sqlite"
    upsert_ap_expense(
        db,
        ApExpenseReportingRow(
            expense_id="E1",
            supplier_id="S1",
            document_number="FZ 1",
            issue_date="2026-01-10",
            due_date="2026-02-10",
            currency="USD",
            gross=Decimal("200.00"),
        ),
    )
    assert count_ap(db) == 1
    rows = list_ap_expenses_as_of(db, as_of="2026-01-31")
    assert len(rows) == 1
    assert rows[0]["expense_id"] == "E1"

    set_sync_state(
        db,
        "ar_invoices",
        last_incremental_at="2026-08-17T00:00:00+00:00",
        row_count=0,
        status="ok",
    )
    st = get_sync_state(db, "ar_invoices")
    assert st is not None
    assert st["status"] == "ok"
    assert st["stream"] == "ar_invoices"
