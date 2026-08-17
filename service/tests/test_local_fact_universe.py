"""Local AR/AP fact universe — CFO default path (no live waterfall)."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.financial_reporting_db import (
    ApExpenseReportingRow,
    ArInvoiceReportingRow,
    set_sync_state,
    upsert_ap_expense,
    upsert_ar_invoice,
)
from app.services.local_fact_universe import (
    load_ap_fact_universe_local,
    load_ar_fact_universe_local,
    local_projection_available,
)
from app.services.wfirma_payment_db import init_payment_db, insert_payment_snapshot
from app.services.accounting_analytics import (
    LocalProjectionUnavailable,
    build_management_analysis,
    build_payables_analysis,
)


def _seed_ar(root: Path) -> Path:
    rep = root / "financial_reporting.sqlite"
    upsert_ar_invoice(
        rep,
        ArInvoiceReportingRow(
            invoice_id="100",
            contractor_id="C1",
            contractor_name="Acme",
            document_type="normal",
            invoice_number="WDT 1/2026",
            issue_date="2026-03-01",
            due_date="2026-03-15",
            currency="USD",
            net=Decimal("100.00"),
            gross=Decimal("100.00"),
        ),
    )
    upsert_ar_invoice(
        rep,
        ArInvoiceReportingRow(
            invoice_id="101",
            contractor_id="C1",
            contractor_name="Acme",
            document_type="normal",
            invoice_number="WDT 2/2026",
            issue_date="2026-07-01",
            due_date="2026-08-01",
            currency="USD",
            gross=Decimal("50.00"),
        ),
    )
    # Outside activity window when from=2026-06-01
    upsert_ar_invoice(
        rep,
        ArInvoiceReportingRow(
            invoice_id="99",
            contractor_id="C2",
            document_type="normal",
            issue_date="2025-01-01",
            due_date="2025-02-01",
            currency="EUR",
            gross=Decimal("10.00"),
        ),
    )
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    set_sync_state(
        rep, "ar_invoices",
        last_full_sync_at=now,
        last_reconcile_at=now,
        row_count=3,
        status="ok",
    )
    return rep


def _seed_payments(root: Path) -> Path:
    pay = root / "payment_state.db"
    init_payment_db(pay)
    insert_payment_snapshot(
        pay,
        payment_id="P1",
        contractor_id="C1",
        invoice_id="100",
        payment_date="2026-03-20",
        value="25.00",
        value_pln=None,
        currency_label="083/A/NBP/2026",
        payment_method=None,
        payment_type=None,
        type_=None,
        notes=None,
        fetched_at="2026-08-17T00:00:00+00:00",
        raw_json="{}",
    )
    return pay


def test_local_projection_available(tmp_path: Path):
    ok, reason = local_projection_available(tmp_path)
    assert ok is False
    assert "missing" in reason or "empty" in reason
    _seed_ar(tmp_path)
    ok2, reason2 = local_projection_available(tmp_path)
    assert ok2 is True
    assert "ar_rows=" in reason2


def test_load_ar_local_filters_activity_and_exposes_provenance(tmp_path: Path):
    _seed_ar(tmp_path)
    _seed_payments(tmp_path)
    uni = load_ar_fact_universe_local(
        tmp_path, "2026-06-01", "2026-08-17", types=("normal", "correction"),
    )
    ids = {f["id"] for f in uni["invoice_facts"]}
    assert ids == {"101"}  # 100 and 99 outside activity window
    assert uni["source"] == "local"
    assert uni["provenance"]["source"] == "local"
    assert uni["provenance"]["freshness"] in ("fresh", "stale", "unknown")
    assert uni["inv_stats"]["api_calls"] == 0
    assert uni["pay_stats"]["api_calls"] == 0
    # POSITION payments: P1 still loaded even though invoice 100 filtered out
    assert any(p["id"] == "P1" for p in uni["payment_facts"])


def test_build_management_analysis_local_zero_api(tmp_path: Path):
    _seed_ar(tmp_path)
    _seed_payments(tmp_path)
    body = build_management_analysis(
        date_from="2026-01-01",
        date_to="2026-08-17",
        as_of="2026-08-17",
        source="local",
        storage_root=tmp_path,
    )
    assert body["source"] == "local"
    assert body["query_stats"]["invoice_api_calls"] == 0
    assert body["query_stats"]["payment_api_calls"] == 0
    assert body["as_of"] == "2026-08-17"
    assert body["freshness"] in ("fresh", "stale", "unknown", "empty")
    assert body["reconciliation_status"]
    usd = next(s for s in body["currency_summaries"] if s["currency"] == "USD")
    # 100 - 25 + 50 = 125 outstanding USD
    assert Decimal(usd["total_receivable"]) == Decimal("125.00")


def test_local_empty_raises(tmp_path: Path):
    with pytest.raises(LocalProjectionUnavailable):
        build_management_analysis(
            date_from="2026-01-01",
            date_to="2026-08-17",
            source="local",
            storage_root=tmp_path,
        )


def test_stale_not_labeled_fresh(tmp_path: Path):
    rep = _seed_ar(tmp_path)
    old = (datetime.now(timezone.utc) - timedelta(hours=48)).replace(
        microsecond=0
    ).isoformat()
    set_sync_state(
        rep, "ar_invoices",
        last_full_sync_at=old,
        last_reconcile_at=old,
        row_count=3,
        status="ok",
    )
    body = build_management_analysis(
        date_from="2026-01-01",
        date_to="2026-08-17",
        source="local",
        storage_root=tmp_path,
    )
    assert body["freshness"] == "stale"
    assert body["freshness"] != "fresh"


def test_build_payables_local(tmp_path: Path):
    _seed_ar(tmp_path)  # ensures projection available gate
    rep = tmp_path / "financial_reporting.sqlite"
    upsert_ap_expense(
        rep,
        ApExpenseReportingRow(
            expense_id="E1",
            supplier_id="S1",
            supplier_name="Vendor",
            document_type="normal",
            document_number="FZ 1",
            issue_date="2026-04-01",
            due_date="2026-04-30",
            currency="EUR",
            gross=Decimal("200.00"),
        ),
    )
    body = build_payables_analysis(
        date_from="2026-01-01",
        date_to="2026-08-17",
        as_of="2026-08-17",
        source="local",
        storage_root=tmp_path,
    )
    assert body["source"] == "local"
    assert body["query_stats"]["expense_api_calls"] == 0
    eur = next(s for s in body["currency_summaries"] if s["currency"] == "EUR")
    assert Decimal(eur["gross_payable"]) == Decimal("200.00")
