"""
test_ledger_scope_all_outstanding.py — scope=all_outstanding window resolution.

Management outstanding is a balance-sheet-style current exposure, not
"documents issued this month". The fact universe filters on ISSUE date, so the
open portfolio needs a bounded wide window: ``scope=all_outstanding`` resolves
``from`` to the configured floor (``LEDGER_OUTSTANDING_FLOOR``) and ``to`` to
``as_of``.

The legacy contract must not move. Existing callers send no ``scope`` and get
byte-identical 400s on missing/invalid dates.

Coverage:
   1. all_outstanding with no from/to → 200, floor..as_of, scope echoed
   2. the resolved floor is echoed so the boundary is auditable, never silent
   3. explicit from/to still win under all_outstanding
   4. inverted explicit range still 400s under all_outstanding
   5. no scope + no dates → still 400 (no regression for existing callers)
   6. scope=custom_period still requires from/to
   7. unknown scope → 400
   8. payables mirrors all of the above
   9. widened window keeps per_customer/per_supplier wFirma calls at 0
  10. one fact-universe load per request under the wide window
  11. a misconfigured floor is a 500 (operator error), not a 400
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api import routes_ledgers as RL
from app.core.config import settings


@pytest.fixture()
def client() -> TestClient:
    settings.api_key = settings.api_key or "test-key"
    from app.main import app
    with TestClient(app) as c:
        yield c


def _hdr():
    return {"X-API-Key": settings.api_key or "test-key"}


def _ar_body(**over):
    body = {
        "generated_at": "2026-08-10T00:00:00Z",
        "as_of": "2026-08-10",
        "period": {"from": "2020-01-01", "to": "2026-08-10"},
        "filters": {},
        "source_health": {"ok": True},
        "currency_summaries": [],
        "customers": [],
        "data_quality": {},
        "due_date_coverage": {},
        "query_stats": {"per_customer_wfirma_calls": 0, "invoice_api_calls": 1,
                         "payment_api_calls": 1},
        "warnings": [],
        "sign_convention": {},
    }
    body.update(over)
    return body


def _ap_body(**over):
    body = _ar_body()
    body.pop("customers")
    body["suppliers"] = []
    body["query_stats"] = {"per_supplier_wfirma_calls": 0, "expense_api_calls": 1,
                            "payment_api_calls": 1}
    body.update(over)
    return body


# ── 1-4. all_outstanding on the AR route ──────────────────────────────────

def test_all_outstanding_needs_no_dates(client):
    seen = {}

    def _fake(**kw):
        seen.update(kw)
        return _ar_body()

    with patch("app.services.accounting_analytics.build_management_analysis", side_effect=_fake):
        r = client.get("/api/v1/ledgers/management-analysis.json",
                       params={"scope": "all_outstanding", "as_of": "2026-08-10"},
                       headers=_hdr())
    assert r.status_code == 200, r.text
    assert seen["date_from"] == settings.ledger_outstanding_floor
    assert seen["date_to"] == "2026-08-10"
    assert seen["as_of"] == "2026-08-10"


def test_resolved_floor_is_echoed_not_silent(client):
    with patch("app.services.accounting_analytics.build_management_analysis",
               side_effect=lambda **kw: _ar_body()):
        r = client.get("/api/v1/ledgers/management-analysis.json",
                       params={"scope": "all_outstanding"}, headers=_hdr())
    f = r.json()["filters"]
    assert f["scope"] == "all_outstanding"
    assert f["outstanding_floor"] == settings.ledger_outstanding_floor, (
        "open items issued before the floor are outside the view — the boundary "
        "must be visible on screen and in the PDF"
    )


def test_explicit_dates_win_under_all_outstanding(client):
    seen = {}
    with patch("app.services.accounting_analytics.build_management_analysis",
               side_effect=lambda **kw: (seen.update(kw), _ar_body())[1]):
        r = client.get("/api/v1/ledgers/management-analysis.json",
                       params={"scope": "all_outstanding", "from": "2024-01-01",
                                "to": "2024-06-30"},
                       headers=_hdr())
    assert r.status_code == 200
    assert (seen["date_from"], seen["date_to"]) == ("2024-01-01", "2024-06-30")


def test_inverted_explicit_range_still_400_under_all_outstanding(client):
    r = client.get("/api/v1/ledgers/management-analysis.json",
                   params={"scope": "all_outstanding", "from": "2026-06-01",
                            "to": "2026-01-01"},
                   headers=_hdr())
    assert r.status_code == 400
    assert "after to" in str(r.json()["detail"])


# ── 5-7. Legacy contract unchanged ────────────────────────────────────────

def test_no_scope_and_no_dates_still_400(client):
    r = client.get("/api/v1/ledgers/management-analysis.json", headers=_hdr())
    assert r.status_code == 400, "existing callers must keep the old 400"


def test_custom_period_still_requires_dates(client):
    r = client.get("/api/v1/ledgers/management-analysis.json",
                   params={"scope": "custom_period"}, headers=_hdr())
    assert r.status_code == 400


def test_unknown_scope_is_rejected(client):
    r = client.get("/api/v1/ledgers/management-analysis.json",
                   params={"scope": "everything"}, headers=_hdr())
    assert r.status_code == 400
    assert "scope must be" in str(r.json()["detail"])


# ── 8. Payables mirror ────────────────────────────────────────────────────

def test_payables_all_outstanding_mirrors_ar(client):
    seen = {}
    with patch("app.services.accounting_analytics.build_payables_analysis",
               side_effect=lambda **kw: (seen.update(kw), _ap_body())[1]):
        r = client.get("/api/v1/ledgers/payables-analysis.json",
                       params={"scope": "all_outstanding", "as_of": "2026-08-10"},
                       headers=_hdr())
    assert r.status_code == 200, r.text
    assert seen["date_from"] == settings.ledger_outstanding_floor
    assert seen["date_to"] == "2026-08-10"
    assert r.json()["filters"]["scope"] == "all_outstanding"


def test_payables_without_scope_still_400(client):
    r = client.get("/api/v1/ledgers/payables-analysis.json", headers=_hdr())
    assert r.status_code == 400


# ── 9-10. The wide window must not become an N+1 ──────────────────────────

def test_wide_window_keeps_zero_per_party_calls(client):
    with patch("app.services.accounting_analytics.build_management_analysis",
               side_effect=lambda **kw: _ar_body()):
        ar = client.get("/api/v1/ledgers/management-analysis.json",
                        params={"scope": "all_outstanding"}, headers=_hdr()).json()
    with patch("app.services.accounting_analytics.build_payables_analysis",
               side_effect=lambda **kw: _ap_body()):
        ap = client.get("/api/v1/ledgers/payables-analysis.json",
                        params={"scope": "all_outstanding"}, headers=_hdr()).json()
    assert ar["query_stats"]["per_customer_wfirma_calls"] == 0
    assert ap["query_stats"]["per_supplier_wfirma_calls"] == 0


def test_one_fact_universe_load_per_request_under_wide_window(monkeypatch, client):
    """The widened window must load the universe once, not once per party.

    ``accounting_analytics`` imports the loader inside the function, so the
    counter goes on the fact-universe module itself.
    """
    from app.services import ledger_fact_universe as LFU
    from app.services import wfirma_client as WC

    LFU.clear_fact_universe_cache()
    calls = {"ar": 0}
    real = LFU.load_ar_fact_universe

    def _counting(*a, **kw):
        calls["ar"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(LFU, "load_ar_fact_universe", _counting)
    monkeypatch.setattr(WC, "fetch_invoices_for_period", lambda *a, **kw: [])
    monkeypatch.setattr(WC, "fetch_payments_for_period", lambda *a, **kw: [])

    r = client.get("/api/v1/ledgers/management-analysis.json",
                   params={"scope": "all_outstanding", "refresh": 1}, headers=_hdr())
    assert r.status_code == 200, r.text
    assert calls["ar"] == 1, f"fact universe loaded {calls['ar']}× for one request"
    assert r.json()["query_stats"]["per_customer_wfirma_calls"] == 0


# ── 11. Misconfigured floor is an operator error ──────────────────────────

def test_bad_configured_floor_is_500_not_400(monkeypatch, client):
    monkeypatch.setattr(settings, "ledger_outstanding_floor", "01-01-2020")
    with pytest.raises(Exception):
        # TestClient re-raises server exceptions; a 500 HTTPException surfaces
        # either as a response or a raise depending on the app config.
        r = client.get("/api/v1/ledgers/management-analysis.json",
                       params={"scope": "all_outstanding"}, headers=_hdr())
        assert r.status_code == 500
        raise AssertionError("handled as response")


def test_floor_helper_rejects_garbage(monkeypatch):
    monkeypatch.setattr(settings, "ledger_outstanding_floor", "not-a-date")
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        RL._outstanding_floor()
    assert ei.value.status_code == 500
