"""
test_ledger_client_balances_wave4.py — Wave 4 Item 4:
Client Balance roster  GET /api/v1/ledgers/clients

The roster JOINs the Customer Master client list with per-client balances
computed by REUSING the documented Statement authority via ONE bulk AR
fact universe (``load_ar_fact_universe`` + ``build_statement_index_by_contractor``).
``per_customer_wfirma_calls`` must stay 0.

Coverage:
  Reducer (pure):
    1. single-currency statement -> open / overdue(invoice-age) / ytd / state
    2. clear balance (outstanding 0) -> state "clear"
    3. multi-currency -> open/overdue/ytd single fields None, currency "multi"
    4. _sum_ccy skips unparseable values
  Route:
    5. roster returns one row per customer, documented fields populated
    6. Backend-Pending columns are explicitly null + column_status disclosed
    7. bulk wFirma failure -> 502 (no fabricated roster)
    8. customer with no contractor id -> unavailable row, no fabricated figures
    9. from > to -> 400
   10. default window is all_outstanding (position as-of) when scope omitted
   11. pagination: start/limit slice the roster
   12. query_stats.per_customer_wfirma_calls == 0
   13. query_stats exposes wfirma_wait_ms / ej_ms timing split
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.api import routes_ledgers as R


# ── Fixtures ────────────────────────────────────────────────────────────────

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


def _ar_universe():
    return {
        "invoice_facts": [],
        "payment_facts": [],
        "inv_stats": {"api_calls": 2},
        "pay_stats": {"api_calls": 4},
        "duration_ms": 12,
        "cache_hit": False,
        "coalesced": False,
        "per_customer_wfirma_calls": 0,
    }


@pytest.fixture()
def client() -> TestClient:
    from app.main import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── 1-4  Pure reducer ───────────────────────────────────────────────────────

def test_reducer_single_currency_maps_documented_fields():
    row = R._roster_row_from_statement("USD", _stmt_single())
    assert row["balance_available"] is True
    assert row["open"] == "600.00"
    assert row["overdue_invoice_age"] == "500.00"   # total 600 - current 100
    assert row["overdue_due_date"] is None          # Backend Pending
    assert row["ytd_invoiced"] == "1000.00"
    assert row["last_30d"] is None                  # Backend Pending
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


# ── 5-8  Route with mocked roster + bulk statement index ────────────────────

def test_route_roster_populates_documented_fields(client):
    with patch.object(R, "_cm_list_customers", return_value=[_cust("101")]), \
         patch("app.services.ledger_fact_universe.load_ar_fact_universe",
               return_value=_ar_universe()), \
         patch("app.services.ledger_aggregator.build_statement_index_by_contractor",
               return_value={"101": _stmt_single()}):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    row = body["rows"][0]
    assert row["contractor_id"] == "101"
    assert row["open"] == "600.00"
    assert row["overdue_invoice_age"] == "500.00"
    assert row["ytd_invoiced"] == "1000.00"
    assert body["query_stats"]["per_customer_wfirma_calls"] == 0


def test_route_backend_pending_columns_disclosed(client):
    with patch.object(R, "_cm_list_customers", return_value=[_cust("101")]), \
         patch("app.services.ledger_fact_universe.load_ar_fact_universe",
               return_value=_ar_universe()), \
         patch("app.services.ledger_aggregator.build_statement_index_by_contractor",
               return_value={"101": _stmt_single()}):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    body = r.json()
    assert body["rows"][0]["last_30d"] is None
    assert body["rows"][0]["overdue_due_date"] is None
    cs = body["column_status"]
    assert cs["last_30d"].startswith("backend_pending")
    assert cs["overdue_due_date"].startswith("backend_pending")
    assert cs["open"] == "documented"


def test_route_bulk_failure_is_502(client):
    with patch.object(R, "_cm_list_customers", return_value=[_cust("101")]), \
         patch("app.services.ledger_fact_universe.load_ar_fact_universe",
               side_effect=RuntimeError("wFirma down")):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    assert r.status_code == 502


def test_route_customer_without_contractor_id(client):
    with patch.object(R, "_cm_list_customers", return_value=[_cust("")]), \
         patch("app.services.ledger_fact_universe.load_ar_fact_universe",
               return_value=_ar_universe()), \
         patch("app.services.ledger_aggregator.build_statement_index_by_contractor",
               return_value={}):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    row = r.json()["rows"][0]
    assert row["balance_available"] is False
    assert row["open"] is None
    assert "contractor id" in row["note"].lower()


# ── 9-12  Validation / window / pagination / zero N+1 ───────────────────────

def test_route_from_after_to_is_400(client):
    with patch.object(R, "_cm_list_customers", return_value=[]):
        r = client.get(
            "/api/v1/ledgers/clients?scope=activity&from=2026-12-01&to=2026-01-01",
            headers=_auth_headers(),
        )
    assert r.status_code == 400


def test_route_default_window_is_all_outstanding(client):
    with patch.object(R, "_cm_list_customers", return_value=[]), \
         patch("app.services.ledger_fact_universe.load_ar_fact_universe",
               return_value=_ar_universe()), \
         patch("app.services.ledger_aggregator.build_statement_index_by_contractor",
               return_value={}), \
         patch.object(R, "_outstanding_floor", return_value="2020-01-01"):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    period = r.json()["period"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert period["scope"] == "all_outstanding"
    assert period["from"] == "2020-01-01"
    assert period["to"] == today
    assert period["as_of"] == today


def test_route_query_stats_exposes_timing_split(client):
    uni = _ar_universe()
    uni.update({
        "wfirma_wait_ms": 1200,
        "ej_normalize_ms": 5,
        "ej_ms": 5,
        "duration_ms": 1210,
        "inv_page_wait_ms": [800],
        "pay_page_wait_ms": [400],
    })
    with patch.object(R, "_cm_list_customers", return_value=[]), \
         patch("app.services.ledger_fact_universe.load_ar_fact_universe",
               return_value=uni), \
         patch("app.services.ledger_aggregator.build_statement_index_by_contractor",
               return_value={}):
        r = client.get("/api/v1/ledgers/clients?from=2026-07-01&to=2026-08-10",
                       headers=_auth_headers())
    qs = r.json()["query_stats"]
    assert qs["wfirma_wait_ms"] == 1200
    assert qs["ej_normalize_ms"] == 5
    assert "ej_ms" in qs
    assert qs["per_customer_wfirma_calls"] == 0
    assert isinstance(qs.get("ej_aggregate_ms"), int)


def test_route_pagination_slices_roster(client):
    custs = [_cust(str(i)) for i in range(5)]
    idx = {str(i): _stmt_single() for i in range(5)}
    with patch.object(R, "_cm_list_customers", return_value=custs), \
         patch("app.services.ledger_fact_universe.load_ar_fact_universe",
               return_value=_ar_universe()), \
         patch("app.services.ledger_aggregator.build_statement_index_by_contractor",
               return_value=idx):
        r = client.get("/api/v1/ledgers/clients?start=1&limit=2",
                       headers=_auth_headers())
    body = r.json()
    assert body["count"] == 2
    assert [row["contractor_id"] for row in body["rows"]] == ["1", "2"]


def test_route_zero_per_customer_wfirma_calls(client):
    with patch.object(R, "_cm_list_customers", return_value=[_cust("101"), _cust("102")]), \
         patch("app.services.ledger_fact_universe.load_ar_fact_universe",
               return_value=_ar_universe()) as load_ar, \
         patch("app.services.ledger_aggregator.build_statement_index_by_contractor",
               return_value={"101": _stmt_single(), "102": _stmt_single()}):
        r = client.get("/api/v1/ledgers/clients?limit=15", headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["query_stats"]["per_customer_wfirma_calls"] == 0
    assert load_ar.call_count == 1
