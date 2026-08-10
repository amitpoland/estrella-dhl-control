"""Fiscal AR excludes Proforma — Client Ledger + Management Analysis parity."""
from __future__ import annotations

from decimal import Decimal

from app.services.accounting_analytics import build_portfolio_from_facts
from app.services.ledger_aggregator import (
    aggregate_statement_from_facts,
    build_statement_index_by_contractor,
)
from app.services.ledger_fact_universe import FISCAL_AR_INVOICE_TYPES


def _inv(iid, *, typ="normal", gross="1000.00", cid="C1", ccy="USD", date="2026-04-01"):
    return {
        "id": iid,
        "fullnumber": f"DOC {iid}",
        "type": typ,
        "date": date,
        "paymentdate": date,
        "currency": ccy,
        "netto": Decimal(gross),
        "brutto": Decimal(gross),
        "contractor_id": cid,
        "contractor_name": "Acme",
    }


def _pay(pid, invoice_id, *, value="400.00", cid="C1", ccy="USD", date="2026-04-10"):
    return {
        "id": pid,
        "linked_invoice": invoice_id,
        "value": Decimal(value),
        "value_pln": Decimal("0"),
        "date": date,
        "currency_label": "",
        "currency": ccy,
        "contractor_id": cid,
    }


def test_fiscal_ar_invoice_types_constant():
    assert FISCAL_AR_INVOICE_TYPES == ("normal", "correction")
    assert "proforma" not in FISCAL_AR_INVOICE_TYPES


def test_fixture_invoice_proforma_payment_on_invoice():
    """Invoice 1000 + Proforma 500 + Payment 400 on Invoice → outstanding 600."""
    invoices = [
        _inv("I1", typ="normal", gross="1000.00"),
        _inv("PF1", typ="proforma", gross="500.00", date="2026-04-02"),
    ]
    payments = [_pay("P1", "I1", value="400.00")]
    period = ("2026-04-01", "2026-04-30")

    stmt = aggregate_statement_from_facts(
        {"wfirma_contractor_id": "C1", "name": "Acme"},
        invoices,
        payments,
        "2026-04-30",
        period,
    )
    t = stmt["totals_per_currency"]["USD"]
    assert t["invoiced"] == "1000.00"
    assert t["received"] == "400.00"
    assert t["outstanding"] == "600.00"

    ma = build_portfolio_from_facts(
        invoices,
        payments,
        as_of="2026-04-30",
        period=period,
    )
    assert ma["currency_summaries"][0]["invoices_represented"] == 1
    row = ma["customers"][0]
    assert row["invoice_count"] == 1
    assert Decimal(row["outstanding"]) == Decimal("600.00")

    idx = build_statement_index_by_contractor(
        invoices, payments, statement_date="2026-04-30", period=period
    )
    assert idx["C1"]["totals_per_currency"]["USD"]["outstanding"] == "600.00"
    assert idx["C1"]["totals_per_currency"]["USD"]["outstanding"] == t["outstanding"]
    assert Decimal(row["outstanding"]) == Decimal(t["outstanding"])


def test_fixture_payment_only_on_proforma_ignored():
    invoices = [
        _inv("I1", typ="normal", gross="1000.00"),
        _inv("PF1", typ="proforma", gross="500.00", date="2026-04-02"),
    ]
    payments = [_pay("P-PF", "PF1", value="200.00")]
    period = ("2026-04-01", "2026-04-30")

    stmt = aggregate_statement_from_facts(
        {"wfirma_contractor_id": "C1"},
        invoices,
        payments,
        "2026-04-30",
        period,
    )
    t = stmt["totals_per_currency"]["USD"]
    assert t["invoiced"] == "1000.00"
    assert t["received"] == "0.00"
    assert t["outstanding"] == "1000.00"

    ma = build_portfolio_from_facts(
        invoices, payments, as_of="2026-04-30", period=period
    )
    row = ma["customers"][0]
    assert row["invoice_count"] == 1
    assert Decimal(row["outstanding"]) == Decimal("1000.00")
    assert Decimal(row["outstanding"]) == Decimal(t["outstanding"])
