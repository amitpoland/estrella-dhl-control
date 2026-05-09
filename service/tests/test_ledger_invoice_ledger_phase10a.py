"""
test_ledger_invoice_ledger_phase10a.py — Phase 10A:
read-only wFirma invoice-ledger JSON endpoint.

Coverage (per task spec):
  1. invoices/find pagination across multiple pages.
  2. safety cap stops after 5000 invoices.
  3. Python-side date filter removes out-of-window invoices that wFirma
     silently returned.
  4. aggregator groups entries by currency.
  5. each entry contains exactly the seven proven fields.
  6. each entry does NOT contain payment_state, remaining, alreadypaid,
     due_date, paid_date, aging, or balance.
  7. unknown contractor returns 404.
  8. invalid date range returns 400.
  9. wFirma error returns 502.
 10. empty result returns empty per-currency map.
Plus:
  - fetch_invoices_for_contractor uses ONLY proven filters.
  - fetch_invoices_for_contractor rejects empty contractor_id and
    inverted date ranges.
  - The forbidden-key contract is pinned both at the aggregator level
    AND in the route-level JSON response.
  - Phase 10A.5 TODO is present in routes_ledgers.py.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import wfirma_client
from app.services.ledger_aggregator import (
    FORBIDDEN_ENTRY_FIELDS,
    LEDGER_ENTRY_FIELDS,
    aggregate_invoice_ledger,
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _auth_headers():
    return {"X-API-KEY": settings.api_key or "test-key"}


@pytest.fixture()
def client(tmp_path) -> TestClient:
    from app.main import app
    with patch.object(settings, "storage_root", tmp_path):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _invoice_xml(*,
                  invoice_id: str,
                  fullnumber: str = "",
                  type_:      str = "normal",
                  date:       str = "2026-04-15",
                  currency:   str = "EUR",
                  netto:      str = "100.00",
                  brutto:     str = "123.00") -> str:
    return (
        f"<invoice>"
          f"<id>{invoice_id}</id>"
          f"<fullnumber>{fullnumber}</fullnumber>"
          f"<type>{type_}</type>"
          f"<date>{date}</date>"
          f"<currency>{currency}</currency>"
          f"<netto>{netto}</netto>"
          f"<brutto>{brutto}</brutto>"
        f"</invoice>"
    )


def _envelope(invoices_xml: str = "", *, status: str = "OK") -> str:
    return (
        '<?xml version="1.0"?>'
        '<api>'
          f'<invoices>{invoices_xml}</invoices>'
          f'<status><code>{status}</code><description>{status}</description></status>'
        '</api>'
    )


def _make_pages(total: int, page_size: int = 200, currency: str = "EUR"):
    """Build a list of envelope strings, each with up to page_size invoices.
    Used to drive the paginator."""
    pages = []
    cursor = 0
    while cursor < total:
        chunk = min(page_size, total - cursor)
        invs  = "".join(
            _invoice_xml(invoice_id=str(cursor + i + 1),
                          fullnumber=f"FV {cursor + i + 1}/2026",
                          currency=currency)
            for i in range(chunk)
        )
        pages.append(_envelope(invs))
        cursor += chunk
    # Always append a final "empty" page so the loop's if-not-invoices
    # break is reachable when total is an exact multiple of page_size.
    pages.append(_envelope(""))
    return pages


def _paginator_stub(pages):
    """Yield each envelope in turn for successive _http_request calls."""
    iterator = iter(pages)
    def _fn(method, module, action, body=""):
        try:
            return 200, next(iterator)
        except StopIteration:
            return 200, _envelope("")
    return _fn


# ── 1. Pagination across multiple pages ────────────────────────────────────

def test_pagination_walks_multiple_pages(monkeypatch):
    pages = _make_pages(total=350, page_size=200)
    monkeypatch.setattr(wfirma_client, "_http_request",
                         _paginator_stub(pages))
    nodes = wfirma_client.fetch_invoices_for_contractor(
        "C-1", "2026-01-01", "2026-12-31",
    )
    assert len(nodes) == 350
    ids = {(n.findtext("id") or "") for n in nodes}
    assert "1"   in ids
    assert "200" in ids
    assert "350" in ids


def test_pagination_stops_when_page_smaller_than_limit(monkeypatch):
    """A short final page (< limit) is the natural termination signal —
    no extra empty-page round trip should be needed."""
    pages = _make_pages(total=50, page_size=200)
    calls = {"n": 0}
    def _stub(method, module, action, body=""):
        calls["n"] += 1
        return 200, pages[0] if calls["n"] == 1 else _envelope("")
    monkeypatch.setattr(wfirma_client, "_http_request", _stub)
    nodes = wfirma_client.fetch_invoices_for_contractor(
        "C-1", "2026-01-01", "2026-12-31",
    )
    assert len(nodes) == 50
    assert calls["n"] == 1


# ── 2. Safety cap at 5000 ──────────────────────────────────────────────────

def test_safety_cap_stops_at_5000(monkeypatch):
    """If wFirma keeps returning full pages, the loop must break at
    exactly 5000 rows. We simulate an infinite stream of 200-invoice
    pages and confirm the helper bails out."""
    def _full_page_factory():
        invs = "".join(
            _invoice_xml(invoice_id=str(i + 1),
                          fullnumber=f"FV {i + 1}/2026")
            for i in range(200)
        )
        return _envelope(invs)
    page = _full_page_factory()
    calls = {"n": 0}
    def _stub(method, module, action, body=""):
        calls["n"] += 1
        return 200, page
    monkeypatch.setattr(wfirma_client, "_http_request", _stub)
    nodes = wfirma_client.fetch_invoices_for_contractor(
        "C-1", "2026-01-01", "2026-12-31",
    )
    # Cap is 5000, so we get 5000 rows — 25 pages of 200.
    assert len(nodes) == 5000
    assert calls["n"] == 25


# ── 3. Python-side date filter ─────────────────────────────────────────────

def test_python_side_date_filter_removes_out_of_window(client, monkeypatch):
    """The route MUST re-filter Python-side because wFirma is known to
    silently ignore unsupported filter shapes."""
    inside  = _invoice_xml(invoice_id="1", date="2026-04-15", currency="EUR")
    after   = _invoice_xml(invoice_id="2", date="2026-12-31", currency="EUR")
    before  = _invoice_xml(invoice_id="3", date="2025-01-01", currency="EUR")
    pages   = [_envelope(inside + after + before), _envelope("")]
    monkeypatch.setattr(wfirma_client, "_http_request",
                         _paginator_stub(pages))
    monkeypatch.setattr(
        wfirma_client, "fetch_contractor_by_id",
        lambda cid: SimpleNamespace(ok=True, name="ACME",
                                      country="PL", nip="PL1"),
    )
    r = client.get(
        "/api/v1/ledgers/clients/C-1/invoice-ledger.json"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    eur_entries = body["entries_per_currency"]["EUR"]
    ids = {e["wfirma_doc_id"] for e in eur_entries}
    assert ids == {"1"}


def test_python_side_date_filter_keeps_dateless_entries(monkeypatch):
    """Dateless rows are kept — the aggregator decides what to do with
    them. Regression guard: a missing <date> must not crash."""
    from app.api import routes_ledgers as rl
    nodes = [
        ET.fromstring(_invoice_xml(invoice_id="1", date="2026-04-15")),
        ET.fromstring(_invoice_xml(invoice_id="2", date="")),
    ]
    out = rl._python_side_date_filter(nodes, "2026-04-01", "2026-05-01")
    ids = {n.findtext("id") for n in out}
    assert ids == {"1", "2"}


# ── 4. Aggregator groups by currency ──────────────────────────────────────

def test_aggregator_groups_by_currency():
    nodes = [
        ET.fromstring(_invoice_xml(invoice_id="1",  currency="EUR",
                                     date="2026-04-01", netto="100.00")),
        ET.fromstring(_invoice_xml(invoice_id="2",  currency="USD",
                                     date="2026-04-02", netto="50.00")),
        ET.fromstring(_invoice_xml(invoice_id="3",  currency="EUR",
                                     date="2026-04-03", netto="200.00")),
    ]
    out = aggregate_invoice_ledger(
        contractor_meta = {"wfirma_contractor_id": "C-1"},
        invoice_nodes   = nodes,
        period          = ("2026-04-01", "2026-04-30"),
    )
    assert out["currencies"] == ["EUR", "USD"]
    assert len(out["entries_per_currency"]["EUR"]) == 2
    assert len(out["entries_per_currency"]["USD"]) == 1
    assert out["totals_per_currency"]["EUR"]["invoiced_net"] == "300.00"
    assert out["totals_per_currency"]["USD"]["invoiced_net"] == "50.00"
    assert out["totals_per_currency"]["EUR"]["entry_count"] == 2


def test_aggregator_sorts_chronologically_per_currency():
    nodes = [
        ET.fromstring(_invoice_xml(invoice_id="3", date="2026-04-30",
                                     currency="EUR")),
        ET.fromstring(_invoice_xml(invoice_id="1", date="2026-04-01",
                                     currency="EUR")),
        ET.fromstring(_invoice_xml(invoice_id="2", date="2026-04-15",
                                     currency="EUR")),
    ]
    out = aggregate_invoice_ledger(
        contractor_meta = {"wfirma_contractor_id": "C-1"},
        invoice_nodes   = nodes,
        period          = ("2026-04-01", "2026-04-30"),
    )
    dates = [e["date"] for e in out["entries_per_currency"]["EUR"]]
    assert dates == ["2026-04-01", "2026-04-15", "2026-04-30"]


# ── 5. Entries contain exactly the 7 proven fields ────────────────────────

def test_entries_contain_exactly_seven_proven_fields():
    nodes = [
        ET.fromstring(_invoice_xml(invoice_id="1", currency="EUR",
                                     date="2026-04-15", netto="10.00",
                                     brutto="12.30")),
    ]
    out = aggregate_invoice_ledger(
        contractor_meta = {"wfirma_contractor_id": "C-1"},
        invoice_nodes   = nodes,
        period          = ("2026-04-01", "2026-04-30"),
    )
    e = out["entries_per_currency"]["EUR"][0]
    assert set(e.keys()) == set(LEDGER_ENTRY_FIELDS)
    # Pin each field's value source.
    assert e["wfirma_doc_id"] == "1"
    assert e["type"]          == "normal"
    assert e["currency"]      == "EUR"
    assert e["total_net"]     == "10.00"
    assert e["total_gross"]   == "12.30"


def test_aggregator_quantises_decimals_to_2dp():
    nodes = [
        ET.fromstring(_invoice_xml(invoice_id="1", currency="EUR",
                                     netto="10",   brutto="12.345")),
    ]
    out = aggregate_invoice_ledger(
        contractor_meta = {"wfirma_contractor_id": "C-1"},
        invoice_nodes   = nodes,
        period          = ("2026-04-01", "2026-04-30"),
    )
    e = out["entries_per_currency"]["EUR"][0]
    assert e["total_net"]   == "10.00"
    # Decimal.quantize defaults to ROUND_HALF_EVEN — 12.345 rounds to
    # 12.34 because 4 is even. Pinned so future rounding-mode changes
    # are intentional.
    assert e["total_gross"] == "12.34"


def test_aggregator_handles_missing_totals_safely():
    inv = (
        "<invoice><id>1</id><fullnumber>FV 1/2026</fullnumber>"
        "<type>normal</type><date>2026-04-15</date>"
        "<currency>EUR</currency></invoice>"
    )
    out = aggregate_invoice_ledger(
        contractor_meta = {"wfirma_contractor_id": "C-1"},
        invoice_nodes   = [ET.fromstring(inv)],
        period          = ("2026-04-01", "2026-04-30"),
    )
    e = out["entries_per_currency"]["EUR"][0]
    assert e["total_net"]   == "0.00"
    assert e["total_gross"] == "0.00"


# ── 6. Forbidden fields never leak ────────────────────────────────────────

@pytest.mark.parametrize("field", FORBIDDEN_ENTRY_FIELDS)
def test_entries_do_not_leak_payment_or_aging_fields(field):
    """Even if the source XML carries payment-state fields, the
    aggregator must NOT surface them. This is a regression guard
    against accidentally tipping into Phase-10B territory before the
    Phase-10A.5 live probe verifies the contracts."""
    inv = ET.fromstring(
        "<invoice>"
          "<id>1</id><fullnumber>FV 1/2026</fullnumber>"
          "<type>normal</type><date>2026-04-15</date>"
          "<currency>EUR</currency><netto>10</netto><brutto>12.30</brutto>"
          # Hostile-but-realistic extra fields wFirma might send.
          "<paymentstate>unpaid</paymentstate>"
          "<alreadypaid>0.00</alreadypaid>"
          "<remaining>12.30</remaining>"
          "<paymentdate>2026-05-15</paymentdate>"
          "<paid_date></paid_date>"
        "</invoice>"
    )
    out = aggregate_invoice_ledger(
        contractor_meta = {"wfirma_contractor_id": "C-1"},
        invoice_nodes   = [inv],
        period          = ("2026-04-01", "2026-04-30"),
    )
    e = out["entries_per_currency"]["EUR"][0]
    assert field not in e


def test_route_response_has_no_payment_or_aging_keys(client, monkeypatch):
    """End-to-end pin: the JSON response shape itself must not carry
    payment-state or aging keys at any level."""
    inv = (
        "<invoice>"
          "<id>1</id><fullnumber>FV 1/2026</fullnumber>"
          "<type>normal</type><date>2026-04-15</date>"
          "<currency>EUR</currency><netto>10</netto><brutto>12.30</brutto>"
          "<paymentstate>unpaid</paymentstate>"
          "<remaining>12.30</remaining>"
        "</invoice>"
    )
    pages = [_envelope(inv), _envelope("")]
    monkeypatch.setattr(wfirma_client, "_http_request",
                         _paginator_stub(pages))
    monkeypatch.setattr(
        wfirma_client, "fetch_contractor_by_id",
        lambda cid: SimpleNamespace(ok=True, name="ACME",
                                      country="PL", nip="PL1"),
    )
    r = client.get(
        "/api/v1/ledgers/clients/C-1/invoice-ledger.json"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    text = r.text
    # The response is small JSON; a top-level grep is enough.
    for forbidden in FORBIDDEN_ENTRY_FIELDS:
        assert forbidden not in text, (
            f"forbidden key {forbidden!r} leaked into response: {text}"
        )


# ── 7. Unknown contractor → 404 ───────────────────────────────────────────

def test_unknown_contractor_returns_404(client, monkeypatch):
    monkeypatch.setattr(
        wfirma_client, "fetch_contractor_by_id",
        lambda cid: SimpleNamespace(ok=False, error="not found"),
    )
    r = client.get(
        "/api/v1/ledgers/clients/MISSING/invoice-ledger.json"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "CONTRACTOR_NOT_FOUND"


# ── 8. Invalid date range → 400 ───────────────────────────────────────────

@pytest.mark.parametrize("qs", [
    "?from=&to=2026-05-01",
    "?from=2026-04-01&to=",
    "?from=not-a-date&to=2026-05-01",
    "?from=2026/04/01&to=2026-05-01",
    "?from=2026-04-01&to=2026/05/01",
    "?from=2026-05-01&to=2026-04-01",   # inverted
])
def test_invalid_date_range_returns_400(client, qs):
    r = client.get(
        "/api/v1/ledgers/clients/C-1/invoice-ledger.json" + qs,
        headers=_auth_headers(),
    )
    assert r.status_code == 400


def test_empty_contractor_id_returns_400(client):
    """Path-validation slash injection."""
    r = client.get(
        "/api/v1/ledgers/clients/.../invoice-ledger.json"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 400


# ── 9. wFirma error → 502 ─────────────────────────────────────────────────

def test_wfirma_fetch_failure_returns_502(client, monkeypatch):
    monkeypatch.setattr(
        wfirma_client, "fetch_contractor_by_id",
        lambda cid: SimpleNamespace(ok=True, name="ACME",
                                      country="PL", nip="PL1"),
    )
    def _boom(*a, **kw):
        raise RuntimeError("invoices/find HTTP 500: boom")
    monkeypatch.setattr(wfirma_client, "_http_request", _boom)
    r = client.get(
        "/api/v1/ledgers/clients/C-1/invoice-ledger.json"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail["code"] == "LEDGER_FETCH_FAILED"
    assert "boom" in detail["error"]


def test_preflight_failure_returns_502(client, monkeypatch):
    """Connection error during contractor preflight → 502, not 500."""
    def _boom(cid):
        raise ConnectionError("wFirma timeout")
    monkeypatch.setattr(wfirma_client, "fetch_contractor_by_id", _boom)
    r = client.get(
        "/api/v1/ledgers/clients/C-1/invoice-ledger.json"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "LEDGER_PREFLIGHT_FAILED"


# ── 10. Empty result returns empty per-currency map ───────────────────────

def test_empty_result_returns_empty_ledger(client, monkeypatch):
    monkeypatch.setattr(
        wfirma_client, "fetch_contractor_by_id",
        lambda cid: SimpleNamespace(ok=True, name="ACME",
                                      country="PL", nip="PL1"),
    )
    monkeypatch.setattr(wfirma_client, "_http_request",
                         _paginator_stub([_envelope("")]))
    r = client.get(
        "/api/v1/ledgers/clients/C-1/invoice-ledger.json"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currencies"]            == []
    assert body["entries_per_currency"]  == {}
    assert body["totals_per_currency"]   == {}
    assert body["contractor"]["wfirma_contractor_id"] == "C-1"
    assert body["period"] == {"from": "2026-04-01", "to": "2026-05-01"}


# ── fetch_invoices_for_contractor — defensive helper guards ───────────────

def test_helper_rejects_empty_contractor_id():
    with pytest.raises(ValueError):
        wfirma_client.fetch_invoices_for_contractor(
            "", "2026-01-01", "2026-12-31",
        )


def test_helper_rejects_inverted_date_range():
    with pytest.raises(ValueError):
        wfirma_client.fetch_invoices_for_contractor(
            "C-1", "2026-12-31", "2026-01-01",
        )


def test_helper_uses_only_proven_filters(monkeypatch):
    """Regression guard: the request body must contain
    contractor_id + type + date filters and NOTHING else."""
    captured = {}
    def _stub(method, module, action, body=""):
        captured["method"] = method
        captured["module"] = module
        captured["action"] = action
        captured["body"]   = body
        return 200, _envelope("")
    monkeypatch.setattr(wfirma_client, "_http_request", _stub)
    wfirma_client.fetch_invoices_for_contractor(
        "C-99", "2026-04-01", "2026-04-30",
    )
    body = captured["body"]
    # Must be a GET on invoices/find (matches snapshot tool pattern).
    assert captured["method"] == "GET"
    assert captured["module"] == "invoices"
    assert captured["action"] == "find"
    # Required fields are present.
    assert "<field>contractor_id</field>" in body
    assert "<value>C-99</value>"           in body
    assert "<field>type</field>"           in body
    assert "<field>date</field>"           in body
    assert "<value>2026-04-01</value>"     in body
    assert "<value>2026-04-30</value>"     in body
    # Forbidden filter fields are absent.
    for forbidden in ("paymentstate", "alreadypaid", "remaining",
                       "paymentdate", "paid_date", "id"):
        assert f"<field>{forbidden}</field>" not in body, (
            f"forbidden filter field {forbidden!r} leaked into request: "
            f"{body[:300]}"
        )


# ── Phase 10A.5 TODO must remain in routes_ledgers.py ─────────────────────

ROUTES_LEDGERS_PATH = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_ledgers.py"
)


def test_routes_ledgers_carries_phase10a5_todo():
    src = ROUTES_LEDGERS_PATH.read_text(encoding="utf-8")
    assert "Phase 10A.5" in src
    assert "payments/find" in src
    assert "alreadypaid"   in src
    assert "Statement"     in src   # docstring asserts this is NOT a Statement


def test_phase10a_endpoint_naming_preserved():
    """Phase 10A naming rule: the endpoint at the invoice-ledger path
    is and remains called 'invoice-ledger.json' — even after Phase 10B
    added a Statement of Account JSON at a separate URL and Phase 10C
    added a Statement PDF at a third URL.

    Contract evolution pinned:
      * ``invoice-ledger.json`` route still exists (Phase 10A).
      * ``statement.json``      route exists       (Phase 10B).
      * ``statement.pdf``       route exists       (Phase 10C).
    """
    src = ROUTES_LEDGERS_PATH.read_text(encoding="utf-8")
    assert '"/clients/{contractor_id}/invoice-ledger.json"' in src
    assert '"/clients/{contractor_id}/statement.json"'      in src
    assert '"/clients/{contractor_id}/statement.pdf"'       in src
