"""Client Statement on the LOCAL financial fact authority.

Phase 10B built the statement on a live wFirma read. The Supplier Ledger had
already converged onto the local financial projection, so the receivable side
was the only statement still holding a second read model. These tests pin the
converged behaviour:

  1. ``source=local`` (the default) reads the projection and makes NO wFirma
     call at all -- not for the facts, and not for the contractor preflight.
  2. No projection is a 503, never a silently empty statement.
  3. A contractor that neither Customer Master nor the projection knows is a
     404, exactly as the live preflight returns -- a typo must not render a
     clean zero statement.
  4. ``source=live`` still works, so the convergence added a default, it did
     not remove a capability.
  5. ``document=`` selects one of the four statement products on the PDF
     route and is validated, not passed through.

The arithmetic is NOT re-asserted here; ``aggregate_statement_from_facts`` is
the one formula and Phase 10B already pins it. What is asserted is which
authority filled it.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings

CID = "9000123"
BASE = "/api/v1/ledgers/clients/%s/statement" % CID
PERIOD = "from=2026-01-01&to=2026-01-31&as_of=2026-01-31"


def _auth():
    return {"X-API-KEY": settings.api_key or "test-key"}


@pytest.fixture()
def client(tmp_path) -> TestClient:
    from app.main import app
    with patch.object(settings, "storage_root", tmp_path):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _invoice_fact(**kw):
    fact = {
        "id": "5001",
        "fullnumber": "FV 5/2026",
        "type": "normal",
        "date": "2026-01-09",
        "paymentdate": "2026-02-08",
        "currency": "EUR",
        "netto": Decimal("1000.00"),
        "brutto": Decimal("1230.00"),
        "contractor_id": CID,
        "contractor_name": "Synthetic Counterparty Sp. z o.o.",
        "payment_state": "",
        "correction_of_id": "",
    }
    fact.update(kw)
    return fact


def _universe(invoice_facts=None, payment_facts=None):
    return {
        "kind": "ar",
        "invoice_facts": invoice_facts if invoice_facts is not None
        else [_invoice_fact()],
        "payment_facts": payment_facts or [],
        "cache_hit": False,
        "duration_ms": 3,
        "source": "local",
        "provenance": {
            "source": "local",
            "freshness": "projection",
            "reconciliation_status": "projection_ok",
        },
    }


def _local(ok=True, reason="ar_rows=1", universe=None):
    """Patch the local projection pair the route imports at call time."""
    return (
        patch("app.services.local_fact_universe.local_projection_available",
              return_value=(ok, reason)),
        patch("app.services.local_fact_universe.load_ar_fact_universe_local",
              return_value=universe if universe is not None else _universe()),
    )


def _no_wfirma():
    """Any wFirma reach-out on the local path is a failure, not a fallback."""
    def _boom(*a, **kw):
        raise AssertionError("local statement must not call wFirma")
    return (
        patch("app.api.routes_ledgers._cmd_lookup_contractor", side_effect=_boom),
        patch("app.services.ledger_fact_universe.load_ar_fact_universe", side_effect=_boom),
    )


# -- 1. default source is local, and it is genuinely offline ---------------

def test_statement_defaults_to_the_local_projection_and_never_calls_wfirma(client):
    avail, load = _local()
    lookup, live = _no_wfirma()
    with avail, load, lookup, live:
        r = client.get("%s.json?%s" % (BASE, PERIOD), headers=_auth())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "local"
    assert body["reconciliation_status"] == "projection_ok"
    assert body["freshness"]["source"] == "projection"
    # Non-vacuous: the projection invoice actually reached the statement.
    assert body["currencies"] == ["EUR"]
    rows = body["entries_per_currency"]["EUR"]
    assert any(e.get("doc_number") == "FV 5/2026" for e in rows), rows


def test_explicit_source_live_still_reads_wfirma(client):
    """Convergence changed the default, it did not delete the live path."""
    rcv = type("R", (), {"ok": True, "name": "Live Name", "country": "PL",
                         "nip": "PL0000000000"})()
    with patch("app.api.routes_ledgers._cmd_lookup_contractor",
               return_value=rcv) as lookup, \
         patch("app.services.ledger_fact_universe.load_ar_fact_universe",
               return_value=_universe()) as uni:
        r = client.get("%s.json?%s&source=live" % (BASE, PERIOD), headers=_auth())
    assert r.status_code == 200, r.text
    assert lookup.called and uni.called
    assert r.json()["source"] == "wfirma"


def test_refresh_forces_the_live_read_even_when_source_says_local(client):
    rcv = type("R", (), {"ok": True, "name": "", "country": "", "nip": ""})()
    with patch("app.api.routes_ledgers._cmd_lookup_contractor", return_value=rcv), \
         patch("app.services.ledger_fact_universe.load_ar_fact_universe",
               return_value=_universe()) as uni:
        r = client.get("%s.json?%s&source=local&refresh=1" % (BASE, PERIOD),
                       headers=_auth())
    assert r.status_code == 200, r.text
    assert uni.called, "refresh=1 must reach wFirma"
    assert r.json()["source"] == "wfirma"


# -- 2. missing projection is loud ----------------------------------------

def test_missing_projection_is_503_not_an_empty_statement(client):
    avail, load = _local(ok=False, reason="ar_rows=0")
    lookup, live = _no_wfirma()
    with avail, load, lookup, live:
        r = client.get("%s.json?%s" % (BASE, PERIOD), headers=_auth())
    assert r.status_code == 503, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "LOCAL_PROJECTION_UNAVAILABLE"
    # The operator must be told the way out, not just the failure.
    assert "source=live" in detail["hint"]


# -- 3. unknown contractor is 404 on the local path too --------------------

def test_unknown_contractor_is_404_on_the_local_path(client):
    """No master record and no receivable = not a customer, not a zero one."""
    avail, load = _local(universe=_universe(invoice_facts=[]))
    lookup, live = _no_wfirma()
    with avail, load, lookup, live:
        r = client.get("%s.json?%s" % (BASE, PERIOD), headers=_auth())
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["code"] == "CONTRACTOR_NOT_FOUND"


def test_known_contractor_with_no_period_activity_is_still_200(client):
    """A real customer who simply did not trade in January gets a statement.

    This is the other half of the 404 above: the gate must key on "unknown",
    never on "quiet", or every dormant account would 404.
    """
    cust = type("C", (), {"bill_to_name": "Dormant Client SARL",
                          "bill_to_country": "FR", "vat_eu_number": "FR123",
                          "bill_to_street": "", "bill_to_city": "",
                          "bill_to_postal_code": "", "bill_to_email": "",
                          "bill_to_phone": ""})()
    avail, load = _local(universe=_universe(invoice_facts=[]))
    lookup, live = _no_wfirma()
    with avail, load, lookup, live, \
         patch("app.services.customer_master_db.get_customer", return_value=cust):
        r = client.get("%s.json?%s" % (BASE, PERIOD), headers=_auth())
    assert r.status_code == 200, r.text
    assert r.json()["contractor"]["name"] == "Dormant Client SARL"


# -- 4. the four statement products on the PDF route ----------------------

@pytest.mark.parametrize("document,stem", [
    ("soa",          "statement"),
    ("monthly",      "monthly-statement"),
    ("ledger",       "ledger"),
    ("confirmation", "balance-confirmation"),
])
def test_pdf_route_renders_each_statement_product(client, document, stem):
    avail, load = _local()
    lookup, live = _no_wfirma()
    with avail, load, lookup, live:
        r = client.get("%s.pdf?%s&document=%s" % (BASE, PERIOD, document),
                       headers=_auth())
    assert r.status_code == 200, r.text[:400]
    assert r.content[:4] == b"%PDF"
    assert "%s-%s" % (stem, CID) in r.headers["content-disposition"]
    # Lesson G: a regenerable artefact must never be cached.
    assert "no-store" in r.headers["cache-control"]


def test_pdf_route_rejects_an_unknown_document_name(client):
    avail, load = _local()
    lookup, live = _no_wfirma()
    with avail, load, lookup, live:
        r = client.get("%s.pdf?%s&document=invoice" % (BASE, PERIOD),
                       headers=_auth())
    assert r.status_code == 400, r.text[:300]
    assert "confirmation" in r.json()["detail"]
