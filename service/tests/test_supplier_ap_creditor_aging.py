"""
test_supplier_ap_creditor_aging.py — Supplier AP fact + portfolio invariants.
"""
from __future__ import annotations

from decimal import Decimal
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.core.config import settings
from app.services.accounting_analytics import (
    build_payables_portfolio_from_facts,
    build_portfolio_from_facts,
)
from app.services.ledger_aggregator import (
    _normalize_doc_link_id,
    _parse_payment_fact,
    aggregate_supplier_statement,
    match_payments_to_expenses,
    remaining_after_payments,
)
from app.services import wfirma_client


def _exp(
    *,
    eid: str,
    cid: str = "S1",
    name: str = "SupplierCo",
    ccy: str = "USD",
    gross: str = "100.00",
    date: str = "2021-06-01",
    due: str = "2021-06-15",
    type_: str = "invoice",
    correction: str = "0",
) -> dict:
    return {
        "id": eid,
        "fullnumber": f"EXP {eid}",
        "type": type_,
        "date": date,
        "payment_date": due,
        "currency": ccy,
        "netto": Decimal(gross),
        "brutto": Decimal(gross),
        "contractor_id": cid,
        "contractor_name": name,
        "paymentstate": "",
        "correction": correction,
        "parent_id": "",
    }


def _pay(
    *,
    pid: str,
    expense_id: str = "",
    invoice_id: str = "",
    value: str = "10.00",
    date: str = "2021-06-20",
    cid: str = "S1",
) -> dict:
    return {
        "id": pid,
        "linked_invoice": invoice_id,
        "linked_expense": expense_id,
        "value": Decimal(value),
        "value_pln": Decimal("0"),
        "date": date,
        "currency_label": "083/A/NBP/2021",
        "currency": "",
        "contractor_id": cid,
    }


def test_normalize_doc_link_sentinel_zero():
    assert _normalize_doc_link_id("0") == ""
    assert _normalize_doc_link_id("") == ""
    assert _normalize_doc_link_id(None) == ""
    assert _normalize_doc_link_id("37267250") == "37267250"


def test_parse_payment_fact_ignores_zero_sentinels():
    xml = (
        "<payment><id>1</id><invoice><id>0</id></invoice>"
        "<expense><id>0</id></expense><value>10</value>"
        "<date>2021-01-01</date><currency_label>083/A/NBP/2021</currency_label>"
        "<contractor><id>C</id></contractor></payment>"
    )
    fact = _parse_payment_fact(ET.fromstring(xml))
    assert fact["linked_invoice"] == ""
    assert fact["linked_expense"] == ""
    assert fact["currency"] == ""
    assert "NBP" in fact["currency_label"]


def test_parse_payment_fact_keeps_genuine_expense_link():
    xml = (
        "<payment><id>2</id><invoice><id>0</id></invoice>"
        "<expense><id>37267250</id></expense><value>67</value>"
        "<date>2021-01-01</date><contractor><id>C</id></contractor></payment>"
    )
    fact = _parse_payment_fact(ET.fromstring(xml))
    assert fact["linked_invoice"] == ""
    assert fact["linked_expense"] == "37267250"


def test_expense_id_zero_ignored_in_match():
    expenses = [_exp(eid="E1", gross="100.00")]
    payments = [_pay(pid="P1", expense_id="0", value="100.00")]
    m = match_payments_to_expenses(expenses, payments)
    assert m["paid_against_expense"] == {}
    assert "P1" not in m["matched_payment_ids"]


def test_invoice_id_zero_does_not_block_expense_link():
    expenses = [_exp(eid="E1", gross="100.00")]
    payments = [_pay(pid="P1", expense_id="E1", invoice_id="0", value="40.00")]
    m = match_payments_to_expenses(expenses, payments)
    assert m["paid_against_expense"]["E1"] == Decimal("40.00")


def test_cross_contractor_expense_link_applies_with_warning_not_refusal():
    """wFirma expense/id is authoritative; contractor mismatch is advisory only."""
    expenses = [_exp(eid="E1", cid="S1", gross="100.00")]
    payments = [_pay(pid="P1", expense_id="E1", cid="S2", value="40.00")]
    m = match_payments_to_expenses(expenses, payments)
    assert m["paid_against_expense"]["E1"] == Decimal("40.00")
    assert "P1" in m["matched_payment_ids"]
    events = {w["event"] for w in m["warnings"]}
    assert "payment_expense_contractor_mismatch" in events


def test_negative_correction_is_credit_not_aged():
    expenses = [
        _exp(eid="CN1", gross="-3368.48", due="2022-03-30", correction="1"),
        _exp(eid="E1", gross="10000.00", due="2020-01-01"),
    ]
    out = build_payables_portfolio_from_facts(
        expenses, [], as_of="2026-08-09", period=("2020-01-01", "2026-12-31")
    )
    row = out["suppliers"][0]
    assert Decimal(row["credit_balance"]) == Decimal("3368.48")
    assert Decimal(row["gross_payable"]) == Decimal("10000.00")
    assert Decimal(row["b_365_plus"]) == Decimal("10000.00")
    assert Decimal(row["net_payable"]) == Decimal("6631.52")


def test_partial_and_multiple_payments():
    expenses = [_exp(eid="E1", gross="100.00")]
    payments = [
        _pay(pid="P1", expense_id="E1", value="30.00"),
        _pay(pid="P2", expense_id="E1", value="20.00"),
    ]
    out = build_payables_portfolio_from_facts(
        expenses, payments, as_of="2021-07-01", period=("2021-01-01", "2021-12-31")
    )
    row = out["suppliers"][0]
    assert Decimal(row["gross_payable"]) == Decimal("50.00")


def test_due_date_buckets_payment_date_basis():
    expenses = [
        _exp(eid="1", gross="10.00", due="2021-12-31"),  # not due as of 2021-12-31
        _exp(eid="2", gross="20.00", due="2021-12-01"),  # 30 days → 1-30
        _exp(eid="3", gross="30.00", due="2021-11-01"),  # 60 days → 31-60
        _exp(eid="4", gross="40.00", due="2021-08-01"),  # 152 days → 91-180
        _exp(eid="5", gross="50.00", due="2020-01-01"),  # >365 → 365+
    ]
    out = build_payables_portfolio_from_facts(
        expenses, [], as_of="2021-12-31", period=("2020-01-01", "2021-12-31")
    )
    row = out["suppliers"][0]
    assert Decimal(row["not_due"]) == Decimal("10.00")
    assert Decimal(row["b_1_30"]) == Decimal("20.00")
    assert Decimal(row["b_31_60"]) == Decimal("30.00")
    assert Decimal(row["b_91_180"]) == Decimal("40.00")
    assert Decimal(row["b_365_plus"]) == Decimal("50.00")
    usd = out["currency_summaries"][0]
    assert usd["reconciliation_ok"] is True
    assert Decimal(usd["gross_payable"]) == Decimal("150.00")


def test_per_currency_separation_no_grand_total():
    expenses = [
        _exp(eid="1", ccy="USD", gross="100.00"),
        _exp(eid="2", ccy="EUR", gross="50.00", cid="S2", name="EuroSup"),
    ]
    out = build_payables_portfolio_from_facts(
        expenses, [], as_of="2021-12-31", period=("2021-01-01", "2021-12-31")
    )
    assert len(out["currency_summaries"]) == 2
    assert "grand_total" not in out


def test_proven_supplier_shape_generic_ids():
    """Pin the scoped v3 arithmetic shape without hardcoding production IDs."""
    # 3 positive expenses + 1 credit note; payments partial
    expenses = [
        _exp(eid="E1", gross="1000.00", due="2020-01-01"),
        _exp(eid="E2", gross="500.00", due="2021-06-01"),
        _exp(eid="CN", gross="-100.00", due="2021-06-01", correction="1"),
    ]
    payments = [
        _pay(pid="P1", expense_id="E1", value="400.00"),
        _pay(pid="P2", expense_id="E2", value="500.00"),
    ]
    # remaining: E1=600 aged >180, E2=0, CN credit 100
    out = build_payables_portfolio_from_facts(
        expenses, payments, as_of="2026-08-09", period=("2020-01-01", "2026-12-31")
    )
    row = out["suppliers"][0]
    assert Decimal(row["gross_payable"]) == Decimal("600.00")
    assert Decimal(row["credit_balance"]) == Decimal("100.00")
    assert Decimal(row["net_payable"]) == Decimal("500.00")
    usd = out["currency_summaries"][0]
    assert usd["reconciliation_ok"] is True

    # Shape analogous to live proof: credits 7787.13 / outstanding 656662.63
    credits = Decimal("7787.13")
    outstanding = Decimal("656662.63")
    assert remaining_after_payments(
        Decimal("3567977.34") - credits, Decimal("2911314.71")
    ) == Decimal("648875.50")
    assert outstanding - credits == Decimal("648875.50")


def test_supplier_statement_uses_same_remaining():
    expenses = [_exp(eid="E1", gross="100.00")]
    payments = [_pay(pid="P1", expense_id="E1", value="40.00")]
    stmt = aggregate_supplier_statement(
        expenses, payments,
        contractor_meta={"wfirma_contractor_id": "S1", "name": "SupplierCo"},
        period=("2021-01-01", "2021-12-31"),
        as_of="2021-12-31",
    )
    usd = stmt["totals_per_currency"]["USD"]
    assert Decimal(usd["outstanding"]) == Decimal("60.00")
    assert Decimal(usd["net_payable"]) == Decimal("60.00")
    assert any(e["type"] == "payment" for e in stmt["entries_per_currency"]["USD"])
    assert Decimal(usd["opening_balance"]) == Decimal("0.00")
    assert Decimal(usd["closing_balance"]) == Decimal("60.00")
    opening = Decimal(usd["opening_balance"])
    assert opening + Decimal(usd["period_debits"]) - Decimal(usd["period_credits"]) == Decimal(usd["closing_balance"])


def test_supplier_statement_opening_closing_and_contiguous():
    """Tally identity on AP: opening + period_debits - period_credits = closing.

    Knock-off remains payment/expense/id via match_payments_to_expenses.
    """
    prior = [_exp(eid="E0", gross="100.00", date="2020-06-01", due="2020-07-01")]
    prior_pay = [_pay(pid="P0", expense_id="E0", value="20.00", date="2020-07-01")]
    period_exp = [_exp(eid="E1", gross="50.00", date="2021-06-01", due="2021-07-01")]
    facts_e = prior + period_exp
    facts_p = prior_pay
    jan = aggregate_supplier_statement(
        facts_e, facts_p,
        contractor_meta={"wfirma_contractor_id": "S1", "name": "SupplierCo"},
        period=("2021-01-01", "2021-12-31"),
        as_of="2021-12-31",
    )
    usd = jan["totals_per_currency"]["USD"]
    opening = Decimal(usd["opening_balance"])
    closing = Decimal(usd["closing_balance"])
    assert opening == Decimal("80.00")
    assert Decimal(usd["period_debits"]) == Decimal("50.00")
    assert Decimal(usd["period_credits"]) == Decimal("0.00")
    assert closing == Decimal("130.00")
    assert opening + Decimal(usd["period_debits"]) - Decimal(usd["period_credits"]) == closing
    assert Decimal(usd["net_payable"]) == closing
    assert Decimal(usd["outstanding"]) == Decimal("130.00")
    entries = jan["entries_per_currency"]["USD"]
    assert entries[0]["type"] == "opening_balance"
    assert any(e.get("is_opening_balance") for e in entries)

    # Previous closing == next opening (contiguous years).
    next_stmt = aggregate_supplier_statement(
        facts_e, facts_p,
        contractor_meta={"wfirma_contractor_id": "S1", "name": "SupplierCo"},
        period=("2022-01-01", "2022-12-31"),
        as_of="2022-12-31",
    )
    assert next_stmt["totals_per_currency"]["USD"]["opening_balance"] == usd["closing_balance"]


def test_supplier_statement_does_not_invent_second_match_path():
    import inspect
    from app.services import ledger_aggregator as la
    src = inspect.getsource(la.aggregate_supplier_statement)
    assert "match_payments_to_expenses(" in src
    assert "match_payments_to_invoices(" not in src
    assert src.count("remaining_after_payments(") >= 1


def test_duplicate_payment_id_does_not_double_count():
    expenses = [_exp(eid="E1", gross="100.00")]
    payments = [
        _pay(pid="P1", expense_id="E1", value="40.00"),
        _pay(pid="P1", expense_id="E1", value="40.00"),
    ]
    m = match_payments_to_expenses(expenses, payments)
    assert m["paid_against_expense"]["E1"] == Decimal("40.00")
    assert "duplicate_payment_id_ignored" in {w["event"] for w in m["warnings"]}


def test_ar_phase1_unchanged_by_ap_payment_fact_key():
    """Receivables portfolio still reconciles when payment facts include linked_expense."""
    invoices = [{
        "id": "I1",
        "fullnumber": "WDT 1",
        "type": "normal",
        "date": "2021-06-01",
        "paymentdate": "2021-06-15",
        "currency": "USD",
        "netto": Decimal("100"),
        "brutto": Decimal("100"),
        "contractor_id": "C1",
        "contractor_name": "Acme",
    }]
    payments = [_pay(pid="P1", invoice_id="I1", expense_id="", value="25.00", cid="C1")]
    out = build_portfolio_from_facts(
        invoices, payments, as_of="2021-07-01", period=("2021-01-01", "2021-12-31")
    )
    assert Decimal(out["customers"][0]["outstanding"]) == Decimal("75.00")
    assert out["currency_summaries"][0]["reconciliation_ok"] is True


def test_paginate_expenses_repeated_page_terminates(monkeypatch):
    page_xml = (
        '<?xml version="1.0"?><api><expenses>'
        + "".join(
            f"<expense><id>{i}</id><fullnumber>F{i}</fullnumber>"
            f"<type>invoice</type><date>2021-01-01</date>"
            f"<payment_date>2021-01-15</payment_date>"
            f"<currency>USD</currency><brutto>10</brutto>"
            f"<contractor><id>C</id></contractor>"
            f"<correction>0</correction></expense>"
            for i in range(1, 201)
        )
        + "</expenses><status><code>OK</code></status></api>"
    )
    calls = {"n": 0}

    def _stub(method, module, action, body=""):
        calls["n"] += 1
        return 200, page_xml

    monkeypatch.setattr(wfirma_client, "_http_request", _stub)
    stats = {}
    nodes = wfirma_client.fetch_expenses_for_period(
        "2021-01-01", "2021-12-31", stats=stats
    )
    assert len(nodes) == 200
    assert stats["stopped_reason"] == "no_new_ids"
    assert calls["n"] == 2  # page1 + repeated page2 stop


def test_ma_ap_kpi_totals_independent_of_table_page_slice():
    """Visible AP table page must not change currency_summaries KPIs."""
    from app.services.accounting_register_paging import paginate_rows

    expenses = [
        _exp(eid=str(i), cid=f"S{i}", name=f"Sup{i}", gross="100.00", due="2021-01-10")
        for i in range(1, 40)
    ]
    out = build_payables_portfolio_from_facts(
        expenses, [], as_of="2021-07-01", period=("2021-01-01", "2021-12-31")
    )
    summaries = out["currency_summaries"]
    p1 = paginate_rows(out["suppliers"], page=1, limit=15)
    p2 = paginate_rows(out["suppliers"], page=2, limit=15)
    assert p1["count"] == 15
    assert p2["count"] == 15
    assert {s["contractor_id"] for s in p1["rows"]}.isdisjoint(
        {s["contractor_id"] for s in p2["rows"]}
    )
    assert out["currency_summaries"] == summaries
    assert summaries[0]["suppliers_outstanding"] == len(out["suppliers"])


def test_payables_route_zero_per_supplier_calls(monkeypatch):
    settings.api_key = settings.api_key or "test-key"
    from app.main import app

    def _fake_payables(**kwargs):
        return {
            "generated_at": "2026-08-09T00:00:00Z",
            "as_of": "2026-08-09",
            "period": {"from": "2020-01-01", "to": "2026-12-31"},
            "filters": {},
            "source_health": {"ok": True},
            "currency_summaries": [],
            "suppliers": [],
            "data_quality": {},
            "due_date_coverage": {},
            "query_stats": {
                "expense_api_calls": 11,
                "payment_api_calls": 16,
                "per_supplier_wfirma_calls": 0,
            },
            "warnings": [],
            "sign_convention": {},
        }

    with patch(
        "app.services.accounting_analytics.build_payables_analysis",
        side_effect=_fake_payables,
    ):
        client = TestClient(app)
        r = client.get(
            "/api/v1/ledgers/payables-analysis.json",
            params={"from": "2020-01-01", "to": "2026-12-31"},
            headers={"X-API-Key": settings.api_key},
        )
    assert r.status_code == 200
    assert r.json()["query_stats"]["per_supplier_wfirma_calls"] == 0
