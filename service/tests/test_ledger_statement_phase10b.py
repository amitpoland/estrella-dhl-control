"""
test_ledger_statement_phase10b.py — Phase 10B:
payments-driven Statement of Account JSON endpoint.

Coverage (per task spec):
  1. fetch_payments_for_contractor pagination across pages.
  2. fetch_payments_for_contractor 5000 safety cap.
  3. Python-side payment date filtering at the route level.
  4. Full payment → invoice contributes 0 to aging total.
  5. Partial payment → invoice contributes (brutto - paid) to aging.
  6. Overpayment → invoice contributes 0 + warning emitted; outstanding
     can go negative.
  7. Unmatched payment listed in unmatched_payments_per_currency.
  8. Cross-currency payment-vs-invoice mismatch listed as unmatched.
  9. Negative correction reduces totals.outstanding and contributes to
     totals.credited.
 10. Proforma emits proforma_treated_as_debit warning and appears as
     a debit entry.
 11. Multi-currency separation; no cross-currency arithmetic.
 12. Running balance tie-break — invoice before same-day payment.
 13. Aging bucket boundaries at 0/1/30/31/60/61/90/91 days.
 14. Aging method label is "invoice_age" on every block.
 15. Forbidden fields absent from JSON output.
 16. Route 404 unknown contractor.
 17. Route 400 bad dates / from > to / as_of < from.
 18. Route 502 wFirma error on invoices/find OR payments/find.
 19. Existing /invoice-ledger.json route unchanged.
 20. Wrapper guards — empty contractor, inverted date range, only
     proven filters.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import wfirma_client
from app.services.ledger_aggregator import (
    FORBIDDEN_ENTRY_FIELDS,
    aggregate_statement,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

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
          f"<contractor><id>C-1</id></contractor>"
        f"</invoice>"
    )


def _payment_xml(*,
                  payment_id: str,
                  invoice_id: str = "",
                  value:      str = "0.00",
                  value_pln:  str = "0.00",
                  date:       str = "2026-04-30",
                  currency:   str = "EUR") -> str:
    invoice_block = f"<invoice><id>{invoice_id}</id></invoice>" if invoice_id else ""
    return (
        f"<payment>"
          f"<id>{payment_id}</id>"
          f"{invoice_block}"
          f"<value>{value}</value>"
          f"<value_pln>{value_pln}</value_pln>"
          f"<date>{date}</date>"
          f"<currency_label>{currency}</currency_label>"
        f"</payment>"
    )


def _envelope_invoices(invoices_xml: str = "", *, status: str = "OK") -> str:
    return (
        '<?xml version="1.0"?>'
        '<api>'
          f'<invoices>{invoices_xml}</invoices>'
          f'<status><code>{status}</code><description>{status}</description></status>'
        '</api>'
    )


def _envelope_payments(payments_xml: str = "", *, status: str = "OK") -> str:
    return (
        '<?xml version="1.0"?>'
        '<api>'
          f'<payments>{payments_xml}</payments>'
          f'<status><code>{status}</code><description>{status}</description></status>'
        '</api>'
    )


def _two_endpoint_stub(invoices_pages, payments_pages):
    """Multi-endpoint paginator stub. Each call to ``_http_request``
    returns the next page from the matching module's queue.

    ``invoices_pages`` and ``payments_pages`` are lists of envelope
    strings. The stub always appends an empty terminator envelope so
    the loop's "less than page_size" early-exit fires."""
    inv_iter = iter(list(invoices_pages) + [_envelope_invoices("")])
    pay_iter = iter(list(payments_pages) + [_envelope_payments("")])
    def _fn(method, module, action, body=""):
        if module == "invoices":
            try:
                return 200, next(inv_iter)
            except StopIteration:
                return 200, _envelope_invoices("")
        if module == "payments":
            try:
                return 200, next(pay_iter)
            except StopIteration:
                return 200, _envelope_payments("")
        return 200, '<api><status><code>OK</code></status></api>'
    return _fn


def _stub_contractor_ok(monkeypatch):
    monkeypatch.setattr(
        wfirma_client, "fetch_contractor_by_id",
        lambda cid: SimpleNamespace(ok=True, name="ACME",
                                      country="PL", nip="PL1"),
    )


# ════════════════════════════════════════════════════════════════════════
#  fetch_payments_for_contractor — wrapper guards
# ════════════════════════════════════════════════════════════════════════

def test_payments_helper_rejects_empty_contractor():
    with pytest.raises(ValueError):
        wfirma_client.fetch_payments_for_contractor(
            "", "2026-01-01", "2026-12-31",
        )


def test_payments_helper_rejects_inverted_dates():
    with pytest.raises(ValueError):
        wfirma_client.fetch_payments_for_contractor(
            "C-1", "2026-12-31", "2026-01-01",
        )


def test_payments_helper_uses_only_proven_filters(monkeypatch):
    captured = {}
    def _stub(method, module, action, body=""):
        captured["method"] = method
        captured["module"] = module
        captured["action"] = action
        captured["body"]   = body
        return 200, _envelope_payments("")
    monkeypatch.setattr(wfirma_client, "_http_request", _stub)
    wfirma_client.fetch_payments_for_contractor(
        "C-99", "2026-04-01", "2026-04-30",
    )
    assert captured["method"] == "GET"
    assert captured["module"] == "payments"
    assert captured["action"] == "find"
    body = captured["body"]
    assert "<field>contractor_id</field>" in body
    assert "<value>C-99</value>"           in body
    assert "<field>date</field>"           in body
    assert "<value>2026-04-01</value>"     in body
    assert "<value>2026-04-30</value>"     in body
    # Only contractor_id + date filters — no payment-state guesses.
    for forbidden in ("paymentstate", "alreadypaid", "remaining",
                       "paymentdate", "paid_date", "id", "type"):
        assert f"<field>{forbidden}</field>" not in body, (
            f"forbidden filter field {forbidden!r} leaked into request"
        )


def test_payments_helper_paginates(monkeypatch):
    pages = []
    cursor = 0
    total = 350
    while cursor < total:
        chunk = min(200, total - cursor)
        payments = "".join(
            _payment_xml(payment_id=str(cursor + i + 1), invoice_id="X",
                          value="1.00", value_pln="1.00",
                          date="2026-04-15", currency="EUR")
            for i in range(chunk)
        )
        pages.append(_envelope_payments(payments))
        cursor += chunk
    pages.append(_envelope_payments(""))
    iterator = iter(pages)
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        lambda *a, **kw: (200, next(iterator)),
    )
    nodes = wfirma_client.fetch_payments_for_contractor(
        "C-1", "2026-01-01", "2026-12-31",
    )
    assert len(nodes) == 350


def test_payments_helper_safety_cap_at_5000(monkeypatch):
    full_page = _envelope_payments("".join(
        _payment_xml(payment_id=str(i + 1), invoice_id="X",
                      value="1.00", value_pln="1.00")
        for i in range(200)
    ))
    calls = {"n": 0}
    def _stub(method, module, action, body=""):
        calls["n"] += 1
        return 200, full_page
    monkeypatch.setattr(wfirma_client, "_http_request", _stub)
    nodes = wfirma_client.fetch_payments_for_contractor(
        "C-1", "2026-01-01", "2026-12-31",
    )
    assert len(nodes) == 5000
    assert calls["n"] == 25


def test_payments_helper_propagates_wfirma_error(monkeypatch):
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        lambda *a, **kw: (
            200,
            '<api><status><code>ERROR</code>'
            '<description>access denied</description></status></api>',
        ),
    )
    with pytest.raises(RuntimeError) as exc:
        wfirma_client.fetch_payments_for_contractor(
            "C-1", "2026-01-01", "2026-12-31",
        )
    assert "access denied" in str(exc.value)


# ════════════════════════════════════════════════════════════════════════
#  aggregate_statement — pure-data tests
# ════════════════════════════════════════════════════════════════════════

def _meta() -> dict:
    return {"wfirma_contractor_id": "C-1", "name": "ACME",
             "country": "PL",  "vat_id": "PL1"}


def _agg(invoice_xmls=(), payment_xmls=(), *,
          statement_date="2026-05-09",
          period=("2026-01-01", "2026-12-31")):
    inv_nodes = [ET.fromstring(x) for x in invoice_xmls]
    pay_nodes = [ET.fromstring(x) for x in payment_xmls]
    return aggregate_statement(
        contractor_meta = _meta(),
        invoice_nodes   = inv_nodes,
        payment_nodes   = pay_nodes,
        statement_date  = statement_date,
        period          = period,
    )


def test_full_payment_zeroes_aging():
    out = _agg(
        invoice_xmls=[
            _invoice_xml(invoice_id="1", brutto="100.00",
                          date="2026-04-01", currency="EUR")
        ],
        payment_xmls=[
            _payment_xml(payment_id="P1", invoice_id="1", value="100.00",
                          currency="EUR", date="2026-04-15")
        ],
    )
    assert out["totals_per_currency"]["EUR"]["received"]    == "100.00"
    assert out["totals_per_currency"]["EUR"]["outstanding"] == "0.00"
    assert out["aging_per_currency"]["EUR"]["total"]        == "0.00"
    assert out["aging_per_currency"]["EUR"]["1_30"]         == "0.00"


def test_partial_payment_leaves_remaining():
    out = _agg(
        invoice_xmls=[
            _invoice_xml(invoice_id="1", brutto="100.00",
                          date="2026-04-01", currency="EUR")
        ],
        payment_xmls=[
            _payment_xml(payment_id="P1", invoice_id="1", value="40.00",
                          currency="EUR", date="2026-04-15")
        ],
        statement_date="2026-05-09",
    )
    assert out["totals_per_currency"]["EUR"]["outstanding"] == "60.00"
    assert out["aging_per_currency"]["EUR"]["total"]        == "60.00"
    # 2026-04-01 → 2026-05-09 = 38 days → 31_60 bucket
    assert out["aging_per_currency"]["EUR"]["31_60"]        == "60.00"
    assert out["aging_per_currency"]["EUR"]["1_30"]         == "0.00"


def test_overpayment_clamps_aging_emits_warning():
    out = _agg(
        invoice_xmls=[
            _invoice_xml(invoice_id="1", brutto="100.00",
                          date="2026-04-01", currency="EUR")
        ],
        payment_xmls=[
            _payment_xml(payment_id="P1", invoice_id="1", value="150.00",
                          currency="EUR", date="2026-04-15")
        ],
    )
    # Aging for this invoice contributes 0 (already overpaid).
    assert out["aging_per_currency"]["EUR"]["total"] == "0.00"
    # But received and outstanding reflect the actual money flow.
    assert out["totals_per_currency"]["EUR"]["received"] == "150.00"
    # Outstanding goes negative — operator sees we owe customer money.
    assert Decimal_str_to_decimal(
        out["totals_per_currency"]["EUR"]["outstanding"]) < 0
    # Warning emitted with the overpaid amount.
    overpaid = [w for w in out["warnings"]
                 if w["event"] == "overpayment_on_invoice"]
    assert len(overpaid) == 1
    assert overpaid[0]["wfirma_doc_id"] == "1"
    assert overpaid[0]["overpaid_by"]   == "50.00"


# Tiny helper used by the over/under tests above.
def Decimal_str_to_decimal(s):
    from decimal import Decimal
    return Decimal(s)


def test_unmatched_payment_listed():
    out = _agg(
        invoice_xmls=[
            _invoice_xml(invoice_id="1", brutto="100.00",
                          date="2026-04-01", currency="EUR")
        ],
        payment_xmls=[
            # invoice_id empty → unmatched.
            _payment_xml(payment_id="P-UNM", invoice_id="", value="50.00",
                          currency="EUR", date="2026-04-20")
        ],
    )
    unm = out["unmatched_payments_per_currency"]["EUR"]
    assert len(unm) == 1
    assert unm[0]["wfirma_doc_id"] == "P-UNM"
    assert unm[0]["value"]         == "50.00"
    assert unm[0]["linked_invoice"] == ""
    # Warning emitted.
    assert any(w["event"] == "unmatched_payment" for w in out["warnings"])
    # Invoice still owes 100 because the payment didn't match it.
    assert out["aging_per_currency"]["EUR"]["total"] == "100.00"


def test_cross_currency_payment_listed_as_unmatched():
    """An EUR invoice paid via a USD payment must NOT reduce the EUR
    invoice's remaining. The payment lives in its own currency
    (USD) as an unmatched credit."""
    out = _agg(
        invoice_xmls=[
            _invoice_xml(invoice_id="1", brutto="100.00",
                          date="2026-04-01", currency="EUR")
        ],
        payment_xmls=[
            _payment_xml(payment_id="P1", invoice_id="1", value="120.00",
                          currency="USD", date="2026-04-15")
        ],
    )
    # EUR invoice still fully unpaid in aging.
    assert out["aging_per_currency"]["EUR"]["total"] == "100.00"
    # USD bucket exists with the unmatched payment.
    assert "USD" in out["unmatched_payments_per_currency"]
    usd_unm = out["unmatched_payments_per_currency"]["USD"]
    assert len(usd_unm) == 1
    assert usd_unm[0]["wfirma_doc_id"] == "P1"
    # Currency-mismatch warning.
    mw = [w for w in out["warnings"]
           if w["event"] == "currency_mismatch_with_invoice"]
    assert mw and mw[0]["wfirma_doc_id"] == "P1"


def test_negative_correction_credits_total():
    out = _agg(
        invoice_xmls=[
            _invoice_xml(invoice_id="1", type_="normal", brutto="200.00",
                          date="2026-04-01", currency="EUR"),
            _invoice_xml(invoice_id="2", type_="correction", brutto="-50.00",
                          date="2026-04-10", currency="EUR"),
        ],
    )
    totals = out["totals_per_currency"]["EUR"]
    # Invoice debit + correction credit on the books.
    assert totals["invoiced"] == "200.00"
    assert totals["credited"] == "50.00"
    assert totals["received"] == "0.00"
    assert totals["outstanding"] == "150.00"


def test_proforma_emits_warning_and_is_debit():
    out = _agg(
        invoice_xmls=[
            _invoice_xml(invoice_id="P-1", type_="proforma",
                          brutto="500.00", date="2026-04-01",
                          currency="EUR"),
        ],
    )
    proforma_warns = [w for w in out["warnings"]
                       if w["event"] == "proforma_treated_as_debit"]
    assert len(proforma_warns) == 1
    assert proforma_warns[0]["wfirma_doc_id"] == "P-1"
    e = out["entries_per_currency"]["EUR"][0]
    assert e["type"]   == "proforma"
    assert e["debit"]  == "500.00"
    assert e["credit"] == "0.00"


def test_multi_currency_separation():
    out = _agg(
        invoice_xmls=[
            _invoice_xml(invoice_id="1", brutto="100.00", currency="EUR"),
            _invoice_xml(invoice_id="2", brutto="80.00",  currency="USD"),
        ],
        payment_xmls=[
            _payment_xml(payment_id="P1", invoice_id="1", value="100.00",
                          currency="EUR"),
            _payment_xml(payment_id="P2", invoice_id="2", value="30.00",
                          currency="USD"),
        ],
    )
    assert sorted(out["currencies"]) == ["EUR", "USD"]
    assert out["totals_per_currency"]["EUR"]["outstanding"] == "0.00"
    assert out["totals_per_currency"]["USD"]["outstanding"] == "50.00"
    # Buckets are independent.
    assert out["aging_per_currency"]["EUR"]["total"] == "0.00"
    assert out["aging_per_currency"]["USD"]["total"] == "50.00"


def test_running_balance_tie_break_invoice_before_same_day_payment():
    """Two events on the same date: invoice debit must apply BEFORE
    the same-day payment credit so the running balance line reads
    correctly."""
    out = _agg(
        invoice_xmls=[
            _invoice_xml(invoice_id="1", brutto="100.00",
                          date="2026-04-15", currency="EUR"),
        ],
        payment_xmls=[
            _payment_xml(payment_id="P1", invoice_id="1", value="100.00",
                          currency="EUR", date="2026-04-15"),
        ],
    )
    rows = out["entries_per_currency"]["EUR"]
    assert rows[0]["type"] == "invoice"
    assert rows[1]["type"] == "payment"
    assert rows[0]["running_balance"] == "100.00"
    assert rows[1]["running_balance"] == "0.00"


@pytest.mark.parametrize("days_old, expected_bucket", [
    (-1,  "current"),
    (0,   "current"),
    (1,   "1_30"),
    (30,  "1_30"),
    (31,  "31_60"),
    (60,  "31_60"),
    (61,  "61_90"),
    (90,  "61_90"),
    (91,  "90_plus"),
    (365, "90_plus"),
])
def test_aging_bucket_boundaries(days_old, expected_bucket):
    statement_date = date(2026, 5, 9)
    inv_date       = statement_date - timedelta(days=days_old)
    out = _agg(
        invoice_xmls=[
            _invoice_xml(invoice_id="1", brutto="100.00",
                          date=inv_date.isoformat(), currency="EUR"),
        ],
        statement_date=statement_date.isoformat(),
    )
    bucket = out["aging_per_currency"]["EUR"]
    assert bucket[expected_bucket] == "100.00"
    # All other named buckets are zero.
    for b in ("current", "1_30", "31_60", "61_90", "90_plus"):
        if b != expected_bucket:
            assert bucket[b] == "0.00", (
                f"days_old={days_old} expected {expected_bucket}, "
                f"but {b} was non-zero: {bucket[b]}"
            )


def test_aging_method_label_is_invoice_age():
    out = _agg(
        invoice_xmls=[
            _invoice_xml(invoice_id="1", brutto="100.00",
                          date="2026-04-01", currency="EUR"),
            _invoice_xml(invoice_id="2", brutto="50.00",
                          date="2026-04-01", currency="USD"),
        ],
    )
    for ccy in ("EUR", "USD"):
        assert out["aging_per_currency"][ccy]["method"] == "invoice_age"


@pytest.mark.parametrize("forbidden_field", FORBIDDEN_ENTRY_FIELDS)
def test_forbidden_fields_absent_from_statement_entries(forbidden_field):
    """A hostile invoice / payment XML carrying every forbidden
    payment-state field must NOT see those fields surface on any
    entry, total, aging block, or unmatched-payment row."""
    inv = (
        "<invoice>"
          "<id>1</id><fullnumber>FV 1</fullnumber>"
          "<type>normal</type><date>2026-04-15</date>"
          "<currency>EUR</currency><netto>10</netto><brutto>100.00</brutto>"
          "<contractor><id>C-1</id></contractor>"
          # Hostile extras
          "<paymentstate>unpaid</paymentstate>"
          "<alreadypaid>0.00</alreadypaid>"
          "<remaining>100.00</remaining>"
          "<paymentdate>2026-05-15</paymentdate>"
          "<paid_date></paid_date>"
        "</invoice>"
    )
    pay = (
        "<payment>"
          "<id>P1</id><invoice><id>1</id></invoice>"
          "<value>50</value><value_pln>200</value_pln>"
          "<date>2026-04-20</date><currency_label>EUR</currency_label>"
          "<paymentstate>partial</paymentstate>"
          "<alreadypaid>50</alreadypaid>"
        "</payment>"
    )
    out = aggregate_statement(
        contractor_meta = _meta(),
        invoice_nodes   = [ET.fromstring(inv)],
        payment_nodes   = [ET.fromstring(pay)],
        statement_date  = "2026-05-09",
        period          = ("2026-01-01", "2026-12-31"),
    )
    # Recursively walk the aggregator output for the forbidden key.
    def _has_key(obj, key):
        if isinstance(obj, dict):
            if key in obj:
                return True
            return any(_has_key(v, key) for v in obj.values())
        if isinstance(obj, list):
            return any(_has_key(v, key) for v in obj)
        return False
    assert not _has_key(out, forbidden_field), (
        f"forbidden field {forbidden_field!r} leaked into Statement output"
    )


# ════════════════════════════════════════════════════════════════════════
#  HTTP — /statement.json route
# ════════════════════════════════════════════════════════════════════════

def test_route_404_unknown_contractor(client, monkeypatch):
    monkeypatch.setattr(
        wfirma_client, "fetch_contractor_by_id",
        lambda cid: SimpleNamespace(ok=False, error="not found"),
    )
    r = client.get(
        "/api/v1/ledgers/clients/MISSING/statement.json"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "CONTRACTOR_NOT_FOUND"


@pytest.mark.parametrize("qs", [
    "?from=&to=2026-05-01",
    "?from=2026-04-01&to=",
    "?from=not-a-date&to=2026-05-01",
    "?from=2026-05-01&to=2026-04-01",   # inverted
    "?from=2026-04-01&to=2026-05-01&as_of=2026-03-01",  # as_of < from
    "?from=2026-04-01&to=2026-05-01&as_of=not-a-date",
])
def test_route_400_bad_dates(client, qs):
    r = client.get(
        "/api/v1/ledgers/clients/C-1/statement.json" + qs,
        headers=_auth_headers(),
    )
    assert r.status_code == 400


def test_route_502_invoices_fetch_failure(client, monkeypatch):
    _stub_contractor_ok(monkeypatch)
    def _boom(method, module, action, body=""):
        if module == "invoices":
            return 500, "boom"
        return 200, _envelope_payments("")
    monkeypatch.setattr(wfirma_client, "_http_request", _boom)
    r = client.get(
        "/api/v1/ledgers/clients/C-1/statement.json"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "STATEMENT_INVOICE_FETCH_FAILED"


def test_route_502_payments_fetch_failure(client, monkeypatch):
    _stub_contractor_ok(monkeypatch)
    def _stub(method, module, action, body=""):
        if module == "invoices":
            return 200, _envelope_invoices("")
        if module == "payments":
            return 500, "boom"
        return 200, "<api/>"
    monkeypatch.setattr(wfirma_client, "_http_request", _stub)
    r = client.get(
        "/api/v1/ledgers/clients/C-1/statement.json"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "STATEMENT_PAYMENT_FETCH_FAILED"


def test_route_happy_path_default_as_of(client, monkeypatch):
    _stub_contractor_ok(monkeypatch)
    invoices = _envelope_invoices(_invoice_xml(
        invoice_id="1", fullnumber="FV 1/2026",
        date="2026-04-01", currency="EUR",
        netto="100.00", brutto="123.00",
    ))
    payments = _envelope_payments(_payment_xml(
        payment_id="P1", invoice_id="1", value="123.00",
        currency="EUR", date="2026-04-15",
    ))
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        _two_endpoint_stub([invoices], [payments]),
    )
    r = client.get(
        "/api/v1/ledgers/clients/C-1/statement.json"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currencies"] == ["EUR"]
    assert body["totals_per_currency"]["EUR"]["outstanding"] == "0.00"
    # generated_at defaults to today UTC; it is a YYYY-MM-DD string.
    assert len(body["generated_at"]) == 10
    # Aging method is invoice_age.
    assert body["aging_per_currency"]["EUR"]["method"] == "invoice_age"


def test_route_python_side_payment_date_filter(client, monkeypatch):
    """A payment that wFirma returned outside the requested window
    must be dropped at the route layer, never reaching the
    aggregator."""
    _stub_contractor_ok(monkeypatch)
    inside  = _payment_xml(payment_id="IN",  invoice_id="X",
                            value="10.00", date="2026-04-15",
                            currency="EUR")
    outside = _payment_xml(payment_id="OUT", invoice_id="X",
                            value="999.00", date="2025-01-01",
                            currency="EUR")
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        _two_endpoint_stub(
            [_envelope_invoices("")],
            [_envelope_payments(inside + outside)],
        ),
    )
    r = client.get(
        "/api/v1/ledgers/clients/C-1/statement.json"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    unm = r.json()["unmatched_payments_per_currency"].get("EUR", [])
    ids = {u["wfirma_doc_id"] for u in unm}
    # Outside-window payment dropped; inside-window unmatched payment kept.
    assert ids == {"IN"}


def test_route_response_carries_no_forbidden_keys(client, monkeypatch):
    _stub_contractor_ok(monkeypatch)
    inv = (
        "<invoice><id>1</id><fullnumber>FV 1</fullnumber>"
        "<type>normal</type><date>2026-04-15</date>"
        "<currency>EUR</currency><netto>10</netto><brutto>100.00</brutto>"
        "<contractor><id>C-1</id></contractor>"
        "<paymentstate>unpaid</paymentstate>"
        "<alreadypaid>0</alreadypaid><remaining>100</remaining>"
        "<paymentdate>2026-05-15</paymentdate>"
        "</invoice>"
    )
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        _two_endpoint_stub([_envelope_invoices(inv)], [_envelope_payments("")]),
    )
    r = client.get(
        "/api/v1/ledgers/clients/C-1/statement.json"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    text = r.text
    # Whole-response substring check is intentionally narrow: only the
    # wFirma-input field names the architecture doc forbids us from
    # surfacing. (FORBIDDEN_ENTRY_FIELDS includes ``aging`` /
    # ``balance``-style guards that legitimately appear as substrings
    # of Phase 10B's ``aging_per_currency`` / ``running_balance``
    # output keys; the per-entry recursive walk earlier in this file
    # is the right tool for those.)
    wfirma_native_forbidden = (
        "paymentstate", "paymentdate",
        "alreadypaid", "paid_date",
    )
    for forbidden in wfirma_native_forbidden:
        assert forbidden not in text, (
            f"forbidden wFirma-input key {forbidden!r} leaked into "
            "Statement response"
        )


# ════════════════════════════════════════════════════════════════════════
#  Existing /invoice-ledger.json route remains unchanged
# ════════════════════════════════════════════════════════════════════════

def test_invoice_ledger_route_still_works(client, monkeypatch):
    """Phase 10A endpoint must keep its existing contract — Phase 10B
    is a NEW route at a different path."""
    _stub_contractor_ok(monkeypatch)
    inv = _envelope_invoices(_invoice_xml(
        invoice_id="1", fullnumber="FV 1", date="2026-04-15",
        currency="EUR", netto="100", brutto="123.00",
    ))
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        _two_endpoint_stub([inv], [_envelope_payments("")]),
    )
    r = client.get(
        "/api/v1/ledgers/clients/C-1/invoice-ledger.json"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # The Phase 10A invoice-ledger does NOT carry payments / aging /
    # totals.outstanding — those belong to Phase 10B.
    assert "outstanding"            not in r.text
    assert "aging_per_currency"     not in body
    assert "unmatched_payments_per_currency" not in body
    # But it DOES carry the seven invoice-ledger fields.
    e = body["entries_per_currency"]["EUR"][0]
    assert "wfirma_doc_id" in e and "doc_number" in e


# ════════════════════════════════════════════════════════════════════════
#  Source-grep — Phase 10A.5 TODO + Statement naming
# ════════════════════════════════════════════════════════════════════════

ROUTES_LEDGERS_PATH = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_ledgers.py"
)


def test_routes_ledgers_keeps_phase10a5_todo():
    src = ROUTES_LEDGERS_PATH.read_text(encoding="utf-8")
    assert "Phase 10A.5" in src
    assert "due_date" in src.lower() or "due-date" in src.lower()


def test_statement_route_path_is_distinct():
    src = ROUTES_LEDGERS_PATH.read_text(encoding="utf-8")
    assert '/clients/{contractor_id}/statement.json' in src
    assert '/clients/{contractor_id}/invoice-ledger.json' in src
    # Phase 10A naming gate still holds for that route.
    assert 'invoice-ledger.json' in src
