"""Ledger performance — bulk AR/AP, coalesce, cache Refresh, no N+1, no writes."""
from __future__ import annotations

import threading
import time
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.services import ledger_fact_universe as LFU
from app.services.ledger_aggregator import (
    aggregate_statement_from_facts,
    build_statement_index_by_contractor,
    remaining_after_payments,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    LFU.clear_fact_universe_cache()
    yield
    LFU.clear_fact_universe_cache()


def _inv(iid, cid="C1", ccy="USD", gross="100.00", date="2026-01-15"):
    return {
        "id": iid,
        "fullnumber": f"FV {iid}",
        "type": "normal",
        "date": date,
        "paymentdate": date,
        "currency": ccy,
        "netto": Decimal(gross),
        "brutto": Decimal(gross),
        "contractor_id": cid,
        "contractor_name": "Acme",
    }


def _pay(pid, invoice_id, value="40.00", cid="C1", date="2026-01-20"):
    return {
        "id": pid,
        "linked_invoice": invoice_id,
        "value": Decimal(value),
        "value_pln": Decimal("0"),
        "date": date,
        "currency_label": "",
        "currency": "",
        "contractor_id": cid,
    }


def test_statement_index_matches_from_facts_authority():
    invoices = [_inv("1", cid="A", gross="100.00"), _inv("2", cid="B", gross="50.00")]
    payments = [_pay("P1", "1", value="25.00", cid="A")]
    idx = build_statement_index_by_contractor(
        invoices, payments, statement_date="2026-02-01", period=("2026-01-01", "2026-12-31")
    )
    a = idx["A"]
    direct = aggregate_statement_from_facts(
        {"wfirma_contractor_id": "A"},
        [invoices[0]],
        [payments[0]],
        "2026-02-01",
        ("2026-01-01", "2026-12-31"),
    )
    assert a["totals_per_currency"]["USD"]["outstanding"] == direct["totals_per_currency"]["USD"]["outstanding"]
    assert a["totals_per_currency"]["USD"]["outstanding"] == "75.00"
    assert remaining_after_payments(Decimal("100.00"), Decimal("25.00")) == Decimal("75.00")


def test_ar_universe_coalesce_single_loader():
    calls = {"n": 0}
    barrier = threading.Barrier(3)

    def fake_inv(*a, **k):
        calls["n"] += 1
        time.sleep(0.05)
        return []

    def fake_pay(*a, **k):
        return []

    results = []

    def worker():
        barrier.wait()
        results.append(LFU.load_ar_fact_universe("2026-01-01", "2026-06-30"))

    with patch.object(LFU.wfirma_client, "fetch_invoices_for_period", side_effect=fake_inv), \
         patch.object(LFU.wfirma_client, "fetch_payments_for_period", side_effect=fake_pay):
        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert calls["n"] == 1
    assert sum(1 for r in results if r.get("coalesced")) >= 1
    assert any(not r.get("coalesced") for r in results)


def test_ar_universe_ttl_hit_and_refresh_bypass():
    calls = {"n": 0}

    def fake_inv(*a, **k):
        calls["n"] += 1
        return []

    with patch.object(LFU.wfirma_client, "fetch_invoices_for_period", side_effect=fake_inv), \
         patch.object(LFU.wfirma_client, "fetch_payments_for_period", return_value=[]):
        a = LFU.load_ar_fact_universe("2026-01-01", "2026-06-30")
        b = LFU.load_ar_fact_universe("2026-01-01", "2026-06-30")
        c = LFU.load_ar_fact_universe("2026-01-01", "2026-06-30", force=True)

    assert calls["n"] == 2
    assert a["cache_hit"] is False
    assert b["cache_hit"] is True
    assert c["cache_hit"] is False
    assert c.get("refresh") is None  # force path; flag is on route not payload


def test_ap_universe_zero_per_supplier_and_cache_key_isolated():
    with patch.object(LFU.wfirma_client, "fetch_expenses_for_period", return_value=[]) as fe, \
         patch.object(LFU.wfirma_client, "fetch_invoices_for_period", return_value=[]) as fi, \
         patch.object(LFU.wfirma_client, "fetch_payments_for_period", return_value=[]) as fp:
        ap = LFU.load_ap_fact_universe("2026-01-01", "2026-06-30")
        ar = LFU.load_ar_fact_universe("2026-01-01", "2026-06-30")

    assert ap["per_supplier_wfirma_calls"] == 0
    assert ar["per_customer_wfirma_calls"] == 0
    assert fe.call_count == 1
    assert fi.call_count == 1
    # AR and AP both need payments/find — separate keys, two payment loads
    assert fp.call_count == 2


def test_cache_hit_zeros_this_request_wfirma_wait():
    with patch.object(LFU.wfirma_client, "fetch_invoices_for_period", return_value=[]), \
         patch.object(LFU.wfirma_client, "fetch_payments_for_period", return_value=[]):
        a = LFU.load_ar_fact_universe("2026-07-01", "2026-08-10")
        b = LFU.load_ar_fact_universe("2026-07-01", "2026-08-10")
    assert a["cache_hit"] is False
    assert b["cache_hit"] is True
    assert b["wfirma_wait_ms"] == 0
    assert b["duration_ms"] == 0
    assert "cached_wfirma_wait_ms" in b


def test_paginate_stats_accumulate_wfirma_wait_ms():
    """Unit: paginator records per-page wait into stats (mocked HTTP)."""
    from app.services import wfirma_client as WC
    from xml.etree import ElementTree as ET

    nodes = [ET.fromstring(f"<invoice><id>{i}</id><date>2026-07-0{i}</date></invoice>") for i in (1, 2)]

    def fake_http(method, module, action, body=""):
        # one short page then stop
        xml = (
            '<?xml version="1.0"?><api><status><code>OK</code></status>'
            "<invoices>"
            + "".join(ET.tostring(n, encoding="unicode") for n in nodes)
            + "</invoices></api>"
        )
        return 200, xml

    stats: dict = {}
    with patch.object(WC, "_http_request", side_effect=fake_http):
        out = WC.fetch_invoices_for_period("2026-07-01", "2026-08-10", stats=stats)
    assert len(out) == 2
    assert int(stats.get("wfirma_wait_ms") or 0) >= 0
    assert stats.get("api_calls") == 1
    assert isinstance(stats.get("page_wait_ms"), list)
    assert len(stats["page_wait_ms"]) == 1


def test_fe_default_preset_is_quarter_not_ytd():
    from pathlib import Path
    hub = (Path(__file__).resolve().parent.parent / "app/static/v2/accounting-hub.jsx").read_text(
        encoding="utf-8"
    )
    # Cold-path defaults (Client + Supplier ledger tabs)
    assert "useState('quarter')" in hub
    assert "quarter default · YTD via Client Ledger" in hub
    ldg = (Path(__file__).resolve().parent.parent / "app/static/v2/ledgers-page.jsx").read_text(
        encoding="utf-8"
    )
    assert "calendar quarter" in ldg or "qStart" in ldg


def test_no_wfirma_write_verbs_in_fact_universe_module():
    src = open(LFU.__file__, encoding="utf-8").read()
    for banned in ("/add", "/edit", "/delete", "POST", "payments/add", "invoices/add", "expenses/add"):
        assert banned not in src


def test_accounting_hub_overview_no_longer_uses_limit_100_n_plus_one():
    from pathlib import Path
    hub = (Path(__file__).resolve().parent.parent / "app/static/v2/accounting-hub.jsx").read_text(
        encoding="utf-8"
    )
    assert "listClientBalances({ limit: 100 })" not in hub
    assert "getManagementAnalysis" in hub
    assert "AccountingOverviewKpis" in hub


def test_refresh_query_on_clients_forces_universe():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.config import settings
    from types import SimpleNamespace
    from app.api import routes_ledgers as R

    cust = SimpleNamespace(
        bill_to_contractor_id="9", bill_to_name="X",
        country="PL", nip="", default_currency="PLN",
    )
    with TestClient(app) as client, \
         patch.object(R, "_cm_list_customers", return_value=[cust]), \
         patch("app.services.ledger_fact_universe.load_ar_fact_universe") as load_ar, \
         patch("app.services.ledger_aggregator.build_statement_index_by_contractor",
               return_value={}):
        load_ar.return_value = {
            "invoice_facts": [], "payment_facts": [],
            "inv_stats": {}, "pay_stats": {}, "duration_ms": 1,
            "wfirma_wait_ms": 0, "ej_normalize_ms": 0, "ej_ms": 0,
            "cache_hit": False, "coalesced": False,
        }
        r = client.get(
            "/api/v1/ledgers/clients?refresh=1",
            headers={"X-API-KEY": settings.api_key or "test-key"},
        )
    assert r.status_code == 200
    assert load_ar.call_args.kwargs.get("force") is True
    assert r.json()["query_stats"]["refresh"] is True
