"""
test_ledger_client_balances_wave4.py — Client Balance roster

Authority: Customer Master identity × Management Analysis portfolio
(``build_management_analysis`` → ``build_portfolio_from_facts``).

Default ``source=local`` — zero portfolio-wide wFirma calls.
``source=live`` / ``refresh=1`` = explicit reconciliation path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.api import routes_ledgers as R


def _auth_headers():
    return {"X-API-KEY": settings.api_key or "test-key"}


def _cust(cid, name="Acme", country="US", nip="123", ccy="USD"):
    return SimpleNamespace(
        bill_to_contractor_id=cid, bill_to_name=name,
        country=country, nip=nip, default_currency=ccy,
    )


def _stmt_single(outstanding="600.00", invoiced="1000.00",
                 current="100.00", total="600.00", ccy="USD"):
    return {
        "totals_per_currency": {
            ccy: {"invoiced": invoiced, "credited": "0.00",
                  "received": "400.00", "outstanding": outstanding,
                  "entry_count": 3},
        },
        "aging_per_currency": {
            ccy: {"method": "invoice_age", "not_due": current,
                  "b_1_30": "200.00", "b_31_60": "0.00", "b_61_90": "0.00",
                  "b_91_180": "0.00", "b_181_365": "0.00",
                  "b_365_plus": "300.00", "total": total},
        },
    }


def _port_customer(
    cid="101",
    name="Acme",
    ccy="USD",
    outstanding="600.00",
    overdue="500.00",
    not_due="100.00",
    credit="0.00",
    gross="1000.00",
    oldest="2026-01-01",
    open_inv=2,
):
    return {
        "contractor_id": cid,
        "customer_name": name,
        "currency": ccy,
        "outstanding": outstanding,
        "overdue": overdue,
        "not_due": not_due,
        "credit_balance": credit,
        "gross_invoiced": gross,
        "oldest_due_date": oldest,
        "open_invoice_count": open_inv,
        "invoice_count": open_inv,
    }


def _portfolio(customers=None, source="local"):
    return {
        "customers": customers if customers is not None else [_port_customer()],
        "currency_summaries": [],
        "query_stats": {
            "source": source,
            "invoice_api_calls": 0 if source == "local" else 4,
            "payment_api_calls": 0 if source == "local" else 16,
            "invoices_normalized": 10,
            "payments_normalized": 20,
            "wfirma_wait_ms": 0 if source == "local" else 1200,
            "ej_normalize_ms": 5,
            "ej_ms": 14,
            "ej_aggregate_ms": 9,
            "per_customer_wfirma_calls": 0,
            "cache_hit": False,
            "coalesced": False,
        },
        "source": source,
        "freshness": "fresh" if source == "local" else "live",
        "reconciliation_status": "verified" if source == "local" else "live_wfirma",
    }


@pytest.fixture()
def client() -> TestClient:
    from app.main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Legacy statement reducer (kept for compatibility) ───────────────────────

def test_reducer_single_currency_maps_documented_fields():
    row = R._roster_row_from_statement("USD", _stmt_single())
    assert row["balance_available"] is True
    assert row["open"] == "600.00"
    assert row["overdue_invoice_age"] == "500.00"
    assert row["overdue_due_date"] == "500.00"  # legacy reducer mirrors aged
    assert row["ytd_invoiced"] == "1000.00"
    assert row["last_30d"] is None
    assert row["currency"] == "USD"
    assert row["state"] == "outstanding"


def test_reducer_clear_balance_state():
    row = R._roster_row_from_statement(
        "USD", _stmt_single(outstanding="0.00", total="0.00", current="0.00"))
    assert row["state"] == "clear"


def test_reducer_multi_currency_single_fields_none():
    stmt = _stmt_single(ccy="USD")
    stmt["totals_per_currency"]["EUR"] = {
        "invoiced": "50.00", "credited": "0.00", "received": "0.00",
        "outstanding": "50.00", "entry_count": 1}
    stmt["aging_per_currency"]["EUR"] = {
        "method": "invoice_age", "not_due": "50.00", "b_1_30": "0.00",
        "b_31_60": "0.00", "b_61_90": "0.00", "b_91_180": "0.00",
        "b_181_365": "0.00", "b_365_plus": "0.00", "total": "50.00"}
    row = R._roster_row_from_statement("USD", stmt)
    assert row["open"] is None
    assert row["overdue_invoice_age"] is None
    assert row["ytd_invoiced"] is None
    assert row["currency"] == "multi"
    assert set(row["currencies"]) == {"USD", "EUR"}
    assert row["open_by_currency"]["EUR"] == "50.00"
    assert row["state"] == "outstanding"


def test_sum_ccy_skips_bad_values():
    from decimal import Decimal
    assert R._sum_ccy({"USD": "10.00", "EUR": "bad", "PLN": "5"}) == Decimal("15")


def test_portfolio_group_maps_due_date_overdue():
    row = R._roster_row_from_portfolio_group(
        "USD",
        [_port_customer(outstanding="600.00", overdue="500.00", not_due="100.00")],
    )
    assert row["open"] == "600.00"
    assert row["overdue_due_date"] == "500.00"
    assert row["overdue_invoice_age"] == "500.00"
    assert row["not_due"] == "100.00"
    assert row["ytd_invoiced"] == "1000.00"
    assert row["state"] == "outstanding"


def test_portfolio_group_multi_currency():
    row = R._roster_row_from_portfolio_group(
        "USD",
        [
            _port_customer(ccy="USD", outstanding="100.00", overdue="40.00"),
            _port_customer(ccy="EUR", outstanding="50.00", overdue="0.00",
                           not_due="50.00", gross="50.00"),
        ],
    )
    assert row["currency"] == "multi"
    assert row["open"] is None
    assert row["open_by_currency"]["EUR"] == "50.00"
    assert row["overdue_due_date_by_currency"]["USD"] == "40.00"


# ── Route — local portfolio authority ───────────────────────────────────────

def test_route_roster_populates_documented_fields(client):
    with patch.object(R, "_cm_list_customers", return_value=[_cust("101")]), \
         patch("app.services.accounting_analytics.build_management_analysis",
               return_value=_portfolio()):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["source"] == "local"
    row = body["rows"][0]
    assert row["contractor_id"] == "101"
    assert row["open"] == "600.00"
    assert row["overdue_due_date"] == "500.00"
    assert row["overdue_invoice_age"] == "500.00"
    assert row["ytd_invoiced"] == "1000.00"
    assert body["query_stats"]["per_customer_wfirma_calls"] == 0
    assert body["query_stats"]["invoice_api_calls"] == 0
    assert body["query_stats"]["payment_api_calls"] == 0


def test_route_due_date_columns_documented(client):
    with patch.object(R, "_cm_list_customers", return_value=[_cust("101")]), \
         patch("app.services.accounting_analytics.build_management_analysis",
               return_value=_portfolio()):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    body = r.json()
    assert body["rows"][0]["last_30d"] is None
    assert body["rows"][0]["overdue_due_date"] == "500.00"
    cs = body["column_status"]
    assert cs["last_30d"].startswith("backend_pending")
    assert "due-date" in cs["overdue_due_date"]
    assert "portfolio" in cs["open"]


def test_route_local_unavailable_is_503(client):
    from app.services.accounting_analytics import LocalProjectionUnavailable

    with patch.object(R, "_cm_list_customers", return_value=[_cust("101")]), \
         patch("app.services.accounting_analytics.build_management_analysis",
               side_effect=LocalProjectionUnavailable("empty projection")):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "LOCAL_PROJECTION_UNAVAILABLE"


def test_route_portfolio_failure_is_502(client):
    with patch.object(R, "_cm_list_customers", return_value=[_cust("101")]), \
         patch("app.services.accounting_analytics.build_management_analysis",
               side_effect=RuntimeError("boom")):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    assert r.status_code == 502


def test_route_customer_without_contractor_id(client):
    with patch.object(R, "_cm_list_customers", return_value=[_cust("")]), \
         patch("app.services.accounting_analytics.build_management_analysis",
               return_value=_portfolio(customers=[])):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    row = r.json()["rows"][0]
    assert row["balance_available"] is False
    assert row["open"] is None
    assert "contractor id" in row["note"].lower()


def test_route_orphan_portfolio_contractor_included(client):
    """Financial exposure without Customer Master must not be hidden."""
    with patch.object(R, "_cm_list_customers", return_value=[]), \
         patch("app.services.accounting_analytics.build_management_analysis",
               return_value=_portfolio(customers=[
                   _port_customer(cid="999", name="Orphan Co"),
               ])):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    body = r.json()
    assert body["count"] == 1
    assert body["rows"][0]["contractor_id"] == "999"
    assert body["rows"][0]["identity_note"] == "financial_fact_without_customer_master"
    assert body["rows"][0]["open"] == "600.00"


def test_route_from_after_to_is_400(client):
    with patch.object(R, "_cm_list_customers", return_value=[]):
        r = client.get(
            "/api/v1/ledgers/clients?scope=activity&from=2026-12-01&to=2026-01-01",
            headers=_auth_headers(),
        )
    assert r.status_code == 400


def test_route_default_window_is_all_outstanding(client):
    with patch.object(R, "_cm_list_customers", return_value=[]), \
         patch("app.services.accounting_analytics.build_management_analysis",
               return_value=_portfolio(customers=[])), \
         patch.object(R, "_outstanding_floor", return_value="2020-01-01"):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    period = r.json()["period"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert period["scope"] == "all_outstanding"
    assert period["from"] == "2020-01-01"
    assert period["to"] == today
    assert period["as_of"] == today


def test_route_query_stats_local_zero_wfirma(client):
    with patch.object(R, "_cm_list_customers", return_value=[]), \
         patch("app.services.accounting_analytics.build_management_analysis",
               return_value=_portfolio(customers=[])) as build:
        r = client.get("/api/v1/ledgers/clients?from=2026-07-01&to=2026-08-10",
                       headers=_auth_headers())
    qs = r.json()["query_stats"]
    assert qs["invoice_api_calls"] == 0
    assert qs["payment_api_calls"] == 0
    assert qs["per_customer_wfirma_calls"] == 0
    assert isinstance(qs.get("ej_aggregate_ms"), int)
    assert build.call_count == 1
    assert build.call_args.kwargs.get("source") == "local"


def test_route_pagination_slices_roster(client):
    custs = [_cust(str(i)) for i in range(5)]
    customers = [
        _port_customer(cid=str(i), outstanding=f"{(5 - i) * 100}.00",
                       overdue=f"{(5 - i) * 50}.00")
        for i in range(5)
    ]
    with patch.object(R, "_cm_list_customers", return_value=custs), \
         patch("app.services.accounting_analytics.build_management_analysis",
               return_value=_portfolio(customers=customers)):
        r = client.get("/api/v1/ledgers/clients?start=1&limit=2",
                       headers=_auth_headers())
    body = r.json()
    assert body["count"] == 2
    assert body["total"] == 5


def test_roster_open_equals_portfolio_outstanding_per_contractor(client):
    """Client Balance Open must copy MA outstanding — no second formula."""
    customers = [
        _port_customer(cid="101", outstanding="10.00", overdue="4.00"),
        _port_customer(cid="101", ccy="EUR", outstanding="20.00", overdue="0.00",
                       not_due="20.00", gross="20.00"),
        _port_customer(cid="102", outstanding="7.50", overdue="7.50"),
    ]
    with patch.object(R, "_cm_list_customers", return_value=[_cust("101"), _cust("102")]), \
         patch("app.services.accounting_analytics.build_management_analysis",
               return_value=_portfolio(customers=customers)):
        r = client.get("/api/v1/ledgers/clients?limit=20", headers=_auth_headers())
    rows = {x["contractor_id"]: x for x in r.json()["rows"]}
    assert rows["101"]["currency"] == "multi"
    assert rows["101"]["open_by_currency"]["USD"] == "10.00"
    assert rows["101"]["open_by_currency"]["EUR"] == "20.00"
    assert rows["102"]["open"] == "7.50"
    assert rows["102"]["overdue_due_date"] == "7.50"


def test_route_zero_per_customer_wfirma_calls(client):
    with patch.object(R, "_cm_list_customers", return_value=[_cust("101"), _cust("102")]), \
         patch("app.services.accounting_analytics.build_management_analysis",
               return_value=_portfolio(customers=[
                   _port_customer(cid="101"),
                   _port_customer(cid="102"),
               ])) as build:
        r = client.get("/api/v1/ledgers/clients?limit=15", headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["query_stats"]["per_customer_wfirma_calls"] == 0
    assert build.call_count == 1
