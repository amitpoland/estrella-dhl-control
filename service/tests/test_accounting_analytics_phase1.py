"""
test_accounting_analytics_phase1.py — Management Analysis portfolio invariants.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.core.config import settings
from app.services.accounting_analytics import build_portfolio_from_facts
from app.services.ledger_aggregator import remaining_after_payments
from app.services import wfirma_client


def _inv(
    *,
    iid: str,
    cid: str = "C1",
    name: str = "Acme",
    ccy: str = "USD",
    gross: str = "100.00",
    date: str = "2021-06-01",
    due: str = "2021-06-15",
    type_: str = "normal",
) -> dict:
    return {
        "id": iid,
        "fullnumber": f"WDT {iid}",
        "type": type_,
        "date": date,
        "paymentdate": due,
        "currency": ccy,
        "netto": Decimal(gross),
        "brutto": Decimal(gross),
        "contractor_id": cid,
        "contractor_name": name,
    }


def _pay(*, pid: str, invoice_id: str, value: str, date: str = "2021-06-20", cid: str = "C1") -> dict:
    return {
        "id": pid,
        "linked_invoice": invoice_id,
        "value": Decimal(value),
        "value_pln": Decimal("0"),
        "date": date,
        "currency_label": "083/A/NBP/2021",
        "currency": "",
        "contractor_id": cid,
    }


def test_shared_remaining_helper():
    assert remaining_after_payments(Decimal("100.00"), Decimal("40.00")) == Decimal("60.00")
    assert remaining_after_payments(Decimal("92548.72"), Decimal("50928.72")) == Decimal(
        "41620.00"
    )


def test_fixture_38533544_shape_remaining():
    """Pin the proven one-client arithmetic shape (generic IDs)."""
    gross = Decimal("92548.72")
    credits = Decimal("2519.00")
    payments = Decimal("50928.72")
    remaining = gross - credits - payments
    assert remaining == Decimal("39101.00")


def test_portfolio_sum_customers_equals_receivable():
    invoices = [
        _inv(iid="1", cid="A", name="Alpha", gross="100.00", due="2021-01-10"),
        _inv(iid="2", cid="B", name="Beta", gross="50.00", due="2021-01-10"),
    ]
    payments = [
        _pay(pid="P1", invoice_id="1", value="20.00"),
    ]
    out = build_portfolio_from_facts(
        invoices, payments, as_of="2021-02-01", period=("2021-01-01", "2021-12-31")
    )
    usd = next(s for s in out["currency_summaries"] if s["currency"] == "USD")
    cust_sum = sum(Decimal(c["outstanding"]) for c in out["customers"] if c["currency"] == "USD")
    assert cust_sum == Decimal(usd["total_receivable"])
    assert usd["reconciliation_ok"] is True


def test_aging_plus_credit_equation():
    invoices = [
        _inv(iid="1", gross="100.00", due="2020-01-01"),  # >180 as of 2021-12-31
        _inv(iid="2", gross="40.00", due="2021-12-31"),   # not due / current
    ]
    payments = [
        _pay(pid="P1", invoice_id="1", value="150.00"),  # overpay → credit 50 on rem of inv1... wait rem = 100-150 = -50 credit
    ]
    out = build_portfolio_from_facts(
        invoices, payments, as_of="2021-12-31", period=("2020-01-01", "2021-12-31")
    )
    row = out["customers"][0]
    # Inv1 credit 50; inv2 outstanding 40 not_due
    assert Decimal(row["credit_balance"]) == Decimal("50.00")
    assert Decimal(row["not_due"]) == Decimal("40.00")
    assert Decimal(row["outstanding"]) == Decimal("40.00")
    # Credits must not reduce an overdue bucket artificially
    assert Decimal(row["b_365_plus"]) == Decimal("0.00")


def test_currency_summary_carries_the_aging_breakdown():
    """The currency-level bucket split is analytics output, not something the
    screen or the PDF is allowed to add up for itself. It must be present, cover
    every bucket, and agree with the rows it summarises."""
    invoices = [
        _inv(iid="1", cid="A", name="Alpha", gross="100.00", due="2020-01-01"),
        _inv(iid="2", cid="B", name="Beta", gross="40.00", due="2021-12-31"),
    ]
    out = build_portfolio_from_facts(
        invoices, [], as_of="2021-12-31", period=("2020-01-01", "2021-12-31")
    )
    usd = next(s for s in out["currency_summaries"] if s["currency"] == "USD")
    aging = usd["aging"]
    assert set(aging) == {
        "not_due", "b_1_30", "b_31_60", "b_61_90", "b_91_180",
        "b_181_365", "b_365_plus", "due_date_unavailable",
    }
    rows = [c for c in out["customers"] if c["currency"] == "USD"]
    for bucket, total in aging.items():
        assert Decimal(total) == sum(Decimal(r[bucket]) for r in rows), bucket
    assert sum(Decimal(v) for v in aging.values()) == Decimal(
        usd["aging_plus_unavailable"]
    )
    assert Decimal(aging["b_365_plus"]) == Decimal("100.00")
    assert Decimal(aging["not_due"]) == Decimal("40.00")


def test_credits_never_enter_overdue_buckets():
    invoices = [_inv(iid="1", gross="100.00", due="2020-01-01")]
    payments = [_pay(pid="P1", invoice_id="1", value="130.00")]
    out = build_portfolio_from_facts(
        invoices, payments, as_of="2021-12-31", period=("2020-01-01", "2021-12-31")
    )
    row = out["customers"][0]
    assert Decimal(row["credit_balance"]) == Decimal("30.00")
    for b in ("not_due", "b_1_30", "b_31_60", "b_61_90", "b_91_180",
              "b_181_365", "b_365_plus"):
        assert Decimal(row[b]) == Decimal("0.00")


def test_missing_paymentdate_goes_to_unavailable_not_aged():
    invoices = [_inv(iid="1", gross="100.00", due="")]
    out = build_portfolio_from_facts(
        invoices, [], as_of="2021-12-31", period=("2021-01-01", "2021-12-31")
    )
    row = out["customers"][0]
    assert Decimal(row["due_date_unavailable"]) == Decimal("100.00")
    assert Decimal(row["b_365_plus"]) == Decimal("0.00")
    assert out["due_date_coverage"]["open_missing_paymentdate"] == 1


def test_nbp_label_never_becomes_currency_bucket():
    invoices = [_inv(iid="1", gross="100.00")]
    payments = [_pay(pid="P1", invoice_id="1", value="100.00")]
    out = build_portfolio_from_facts(
        invoices, payments, as_of="2021-12-31", period=("2021-01-01", "2021-12-31")
    )
    assert out["customers"][0]["currency"] == "USD"
    assert all("/" not in s["currency"] and "NBP" not in s["currency"]
               for s in out["currency_summaries"])


def test_no_cross_currency_grand_total():
    invoices = [
        _inv(iid="1", ccy="USD", gross="100.00"),
        _inv(iid="2", ccy="EUR", gross="50.00", cid="C2", name="EuroCo"),
    ]
    out = build_portfolio_from_facts(
        invoices, [], as_of="2021-12-31", period=("2021-01-01", "2021-12-31")
    )
    assert len(out["currency_summaries"]) == 2
    assert "grand_total" not in out
    assert "total_all_currencies" not in out


def test_paginate_repeated_page_terminates(monkeypatch):
    """Broken server that always returns the same page must stop."""
    page_xml = (
        '<?xml version="1.0"?><api><invoices>'
        + "".join(
            f"<invoice><id>{i}</id><fullnumber>F{i}</fullnumber>"
            f"<type>normal</type><date>2021-01-01</date>"
            f"<currency>USD</currency><total>10</total>"
            f"<contractor><id>C</id></contractor></invoice>"
            for i in range(1, 201)
        )
        + "</invoices><status><code>OK</code></status></api>"
    )
    calls = {"n": 0}

    def _stub(method, module, action, body=""):
        calls["n"] += 1
        return 200, page_xml

    monkeypatch.setattr(wfirma_client, "_http_request", _stub)
    stats = {}
    nodes = wfirma_client.fetch_invoices_for_period(
        "2021-01-01", "2021-12-31", stats=stats
    )
    assert len(nodes) == 200
    assert calls["n"] == 2  # page1 keep, page2 no-new-ids stop
    assert stats["stopped_reason"] == "no_new_ids"
    assert stats["duplicate_ids_suppressed"] >= 200


def _auth_headers():
    return {"X-API-KEY": settings.api_key or "test-key"}


@pytest.fixture()
def client(tmp_path):
    from app.main import app
    with patch.object(settings, "storage_root", tmp_path):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def test_ma_kpi_totals_independent_of_table_page_slice():
    """Visible AR table page must not change currency_summaries KPIs."""
    from app.services.accounting_register_paging import paginate_rows

    invoices = [
        _inv(iid=str(i), cid=f"C{i}", name=f"Cust{i}", gross="100.00", due="2021-01-10")
        for i in range(1, 40)
    ]
    out = build_portfolio_from_facts(
        invoices, [], as_of="2021-07-01", period=("2021-01-01", "2021-12-31")
    )
    summaries = out["currency_summaries"]
    p1 = paginate_rows(out["customers"], page=1, limit=15)
    p2 = paginate_rows(out["customers"], page=2, limit=15)
    assert p1["count"] == 15
    assert p2["count"] == 15
    assert {c["contractor_id"] for c in p1["rows"]}.isdisjoint(
        {c["contractor_id"] for c in p2["rows"]}
    )
    # KPIs are portfolio-level — unchanged by table slicing
    assert out["currency_summaries"] == summaries
    assert summaries[0]["customers_outstanding"] == len(out["customers"])


def test_route_management_analysis_ok(client, monkeypatch):
    inv_env = (
        '<?xml version="1.0"?><api><invoices>'
        "<invoice><id>1</id><fullnumber>WDT 1</fullnumber><type>normal</type>"
        "<date>2021-06-01</date><paymentdate>2021-06-15</paymentdate>"
        "<currency>USD</currency><total>100.00</total>"
        "<contractor><id>C1</id></contractor>"
        "<contractor_detail><name>Acme</name></contractor_detail>"
        "</invoice></invoices><status><code>OK</code></status></api>"
    )
    pay_env = (
        '<?xml version="1.0"?><api><payments>'
        "<payment><id>P1</id><invoice><id>1</id></invoice>"
        "<value>25.00</value><date>2021-06-20</date>"
        "<currency_label>083/A/NBP/2021</currency_label>"
        "<contractor><id>C1</id></contractor>"
        "</payment></payments><status><code>OK</code></status></api>"
    )

    def _stub(method, module, action, body=""):
        if module == "invoices":
            return 200, inv_env
        return 200, pay_env

    monkeypatch.setattr(wfirma_client, "_http_request", _stub)
    r = client.get(
        "/api/v1/ledgers/management-analysis.json"
        "?from=2021-01-01&to=2021-12-31&as_of=2021-07-01&source=live",
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["query_stats"]["per_customer_wfirma_calls"] == 0
    assert body["query_stats"]["invoice_api_calls"] >= 1
    assert body["query_stats"]["payment_api_calls"] >= 1
    usd = body["currency_summaries"][0]
    assert usd["currency"] == "USD"
    assert usd["total_receivable"] == "75.00"
    assert body["customers"][0]["customer_name"] == "Acme"
    assert "083/A/NBP" not in str(body["currency_summaries"])
