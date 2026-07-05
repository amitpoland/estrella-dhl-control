"""
test_ledger_client_balances_wave4.py — Wave 4 Item 4:
Client Balance roster  GET /api/v1/ledgers/clients

The roster JOINs the Customer Master client list with per-client balances
computed by REUSING the documented Statement authority (aggregate_statement).
These tests mock both sides — customer roster and _build_statement_dict — so
no live wFirma call and no real customer_master.sqlite is needed.

Coverage:
  Reducer (pure):
    1. single-currency statement -> open / overdue(invoice-age) / ytd / state
    2. clear balance (outstanding 0) -> state "clear"
    3. multi-currency -> open/overdue/ytd single fields None, currency "multi"
    4. _sum_ccy skips unparseable values
  Route:
    5. roster returns one row per customer, documented fields populated
    6. Backend-Pending columns are explicitly null + column_status disclosed
    7. per-client wFirma failure -> balance_available False (roster not failed)
    8. customer with no contractor id -> unavailable row, no fabricated figures
    9. from > to -> 400
   10. default window is year-to-date when from/to omitted
   11. pagination: start/limit slice the roster
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
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
            ccy: {"method": "invoice_age", "current": current,
                  "1_30": "200.00", "31_60": "0.00", "61_90": "0.00",
                  "90_plus": "300.00", "total": total},
        },
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
        "method": "invoice_age", "current": "50.00", "1_30": "0.00",
        "31_60": "0.00", "61_90": "0.00", "90_plus": "0.00", "total": "50.00"}
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


# ── 5-8  Route with mocked roster + statement ───────────────────────────────

def test_route_roster_populates_documented_fields(client):
    with patch.object(R, "_cm_list_customers", return_value=[_cust("101")]), \
         patch.object(R, "_build_statement_dict", return_value=_stmt_single()):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    row = body["rows"][0]
    assert row["contractor_id"] == "101"
    assert row["open"] == "600.00"
    assert row["overdue_invoice_age"] == "500.00"
    assert row["ytd_invoiced"] == "1000.00"


def test_route_backend_pending_columns_disclosed(client):
    with patch.object(R, "_cm_list_customers", return_value=[_cust("101")]), \
         patch.object(R, "_build_statement_dict", return_value=_stmt_single()):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    body = r.json()
    assert body["rows"][0]["last_30d"] is None
    assert body["rows"][0]["overdue_due_date"] is None
    cs = body["column_status"]
    assert cs["last_30d"].startswith("backend_pending")
    assert cs["overdue_due_date"].startswith("backend_pending")
    assert cs["open"] == "documented"


def test_route_per_client_failure_is_fault_isolated(client):
    with patch.object(R, "_cm_list_customers", return_value=[_cust("101"), _cust("102")]), \
         patch.object(R, "_build_statement_dict",
                      side_effect=[_stmt_single(),
                                   HTTPException(status_code=502, detail="wFirma down")]):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    assert r.status_code == 200          # roster NOT failed
    rows = r.json()["rows"]
    assert rows[0]["balance_available"] is True
    assert rows[1]["balance_available"] is False
    assert rows[1]["open"] is None
    assert "unavailable" in rows[1]["note"].lower()


def test_route_customer_without_contractor_id(client):
    with patch.object(R, "_cm_list_customers", return_value=[_cust("")]):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    row = r.json()["rows"][0]
    assert row["balance_available"] is False
    assert row["open"] is None
    assert "contractor id" in row["note"].lower()


# ── 9-11  Validation / window / pagination ──────────────────────────────────

def test_route_from_after_to_is_400(client):
    with patch.object(R, "_cm_list_customers", return_value=[]):
        r = client.get("/api/v1/ledgers/clients?from=2026-12-01&to=2026-01-01",
                       headers=_auth_headers())
    assert r.status_code == 400


def test_route_default_window_is_year_to_date(client):
    with patch.object(R, "_cm_list_customers", return_value=[]):
        r = client.get("/api/v1/ledgers/clients", headers=_auth_headers())
    period = r.json()["period"]
    assert period["from"].endswith("-01-01")
    assert period["from"][:4] == period["to"][:4]


def test_route_pagination_slices_roster(client):
    custs = [_cust(str(i)) for i in range(5)]
    with patch.object(R, "_cm_list_customers", return_value=custs), \
         patch.object(R, "_build_statement_dict", return_value=_stmt_single()):
        r = client.get("/api/v1/ledgers/clients?start=1&limit=2",
                       headers=_auth_headers())
    body = r.json()
    assert body["count"] == 2
    assert [row["contractor_id"] for row in body["rows"]] == ["1", "2"]
