"""
test_statement_pdf_phase10c.py — Phase 10C:
Statement of Account PDF renderer + endpoint.

Coverage (per task spec):
   1. renderer returns %PDF- bytes
   2. PDF text includes "Statement of Account"
   3. PDF text includes contractor name and period
   4. PDF text includes aging method "Invoice age"
   5. multi-currency sections render separately
   6. unmatched payments render only when present
   7. warnings render only when present
   8. forbidden fields are not rendered
   9. empty statement renders cleanly
  10. negative outstanding renders
  11. long ledger creates multi-page PDF
  12. route returns application/pdf
  13. route filename is sanitized
  14. route 404 unknown contractor
  15. route 400 bad dates
  16. route 502 wFirma fetch failure
  17. route 502 render failure
  18. statement.json route still works
  19. invoice-ledger.json route still works
  20. Phase 1–10B regression sweep — full suite separately
"""
from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.core.config import settings
from app.services import wfirma_client
from app.services.statement_pdf_renderer import render_statement_pdf


# ── Fixtures ──────────────────────────────────────────────────────────────

def _auth_headers():
    return {"X-API-KEY": settings.api_key or "test-key"}


@pytest.fixture()
def client(tmp_path) -> TestClient:
    from app.main import app
    with patch.object(settings, "storage_root", tmp_path):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _stub_contractor_ok(monkeypatch, *, name="ACME", country="PL", nip="PL1"):
    monkeypatch.setattr(
        wfirma_client, "fetch_contractor_by_id",
        lambda cid: SimpleNamespace(ok=True, name=name,
                                      country=country, nip=nip),
    )


def _envelope_invoices(invoices_xml: str = "") -> str:
    return (
        '<?xml version="1.0"?>'
        '<api>'
          f'<invoices>{invoices_xml}</invoices>'
          '<status><code>OK</code><description>OK</description></status>'
        '</api>'
    )


def _envelope_payments(payments_xml: str = "") -> str:
    return (
        '<?xml version="1.0"?>'
        '<api>'
          f'<payments>{payments_xml}</payments>'
          '<status><code>OK</code><description>OK</description></status>'
        '</api>'
    )


def _two_endpoint_stub(invoices_pages, payments_pages):
    inv_iter = iter(list(invoices_pages) + [_envelope_invoices("")])
    pay_iter = iter(list(payments_pages) + [_envelope_payments("")])
    def _fn(method, module, action, body=""):
        if module == "invoices":
            try:    return 200, next(inv_iter)
            except StopIteration: return 200, _envelope_invoices("")
        if module == "payments":
            try:    return 200, next(pay_iter)
            except StopIteration: return 200, _envelope_payments("")
        return 200, '<api><status><code>OK</code></status></api>'
    return _fn


def _read_pdf_text(pdf_bytes: bytes) -> str:
    """Concatenated text from every page of the PDF."""
    r = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((p.extract_text() or "") for p in r.pages)


def _read_pdf_pages(pdf_bytes: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


# ── Synthetic statement fixtures ──────────────────────────────────────────

def _empty_statement() -> dict:
    return {
        "contractor": {
            "wfirma_contractor_id": "C-1",
            "name":     "TestCo",
            "country":  "PL",
            "vat_id":   "PL1234567890",
        },
        "generated_at": "2026-05-09",
        "period":       {"from": "2026-04-01", "to": "2026-05-01"},
        "currencies":   [],
        "entries_per_currency":          {},
        "totals_per_currency":           {},
        "aging_per_currency":            {},
        "unmatched_payments_per_currency": {},
        "warnings":     [],
    }


def _one_currency_statement(*, outstanding="500.00") -> dict:
    return {
        "contractor": {
            "wfirma_contractor_id": "C-1",
            "name":     "Maison Aurélie",
            "country":  "FR",
            "vat_id":   "FR12345678901",
        },
        "generated_at": "2026-05-09",
        "period":       {"from": "2026-04-01", "to": "2026-05-01"},
        "currencies":   ["EUR"],
        "entries_per_currency": {
            "EUR": [
                {"type": "invoice", "wfirma_doc_id": "INV-9001",
                 "doc_number": "FV 92/2026", "date": "2026-04-12",
                 "currency": "EUR", "debit": "1500.00", "credit": "0.00",
                 "running_balance": "1500.00"},
                {"type": "payment", "wfirma_doc_id": "PAY-3001",
                 "doc_number": "", "linked_invoice": "INV-9001",
                 "date": "2026-04-30", "currency": "EUR",
                 "debit": "0.00", "credit": "1000.00",
                 "running_balance": "500.00"},
            ],
        },
        "totals_per_currency": {
            "EUR": {"invoiced": "1500.00", "credited": "0.00",
                     "received": "1000.00", "outstanding": outstanding,
                     "entry_count": 2},
        },
        "aging_per_currency": {
            "EUR": {"method": "invoice_age",
                     "current": "0.00", "1_30": "500.00",
                     "31_60": "0.00", "61_90": "0.00",
                     "90_plus": "0.00", "total": "500.00"},
        },
        "unmatched_payments_per_currency": {},
        "warnings": [],
    }


# ════════════════════════════════════════════════════════════════════════
#  Renderer — pure-data tests
# ════════════════════════════════════════════════════════════════════════

# 1
def test_renderer_returns_pdf_magic_bytes():
    pdf = render_statement_pdf(_empty_statement())
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF-")


# 2
def test_pdf_text_includes_statement_of_account():
    pdf = render_statement_pdf(_one_currency_statement())
    text = _read_pdf_text(pdf)
    assert "Statement of Account" in text


# 3
def test_pdf_text_includes_contractor_name_and_period():
    stmt = _one_currency_statement()
    pdf  = render_statement_pdf(stmt)
    text = _read_pdf_text(pdf)
    assert "Maison Aur" in text   # accented name; "é" may not survive every extractor
    assert "2026-04-01" in text
    assert "2026-05-01" in text
    assert "FR12345678901" in text


# 4
def test_pdf_text_includes_invoice_age_label():
    pdf = render_statement_pdf(_one_currency_statement())
    text = _read_pdf_text(pdf)
    # The label appears in the metadata strip, the per-currency aging
    # card subtitle, AND the footer (drawn via canvas — pypdf may not
    # always extract canvas drawString text on all builds; we accept
    # ≥ 1 occurrence as the contract).
    assert "Invoice age" in text


def test_pdf_does_not_imply_due_date_aging():
    """Phase 10C MUST NOT show due-date aging until a real-id probe
    verifies <paymentdate>. The label 'Due date' must not appear."""
    pdf = render_statement_pdf(_one_currency_statement())
    text = _read_pdf_text(pdf)
    assert "Due date" not in text


# 5
def test_multi_currency_sections_render_separately():
    stmt = _one_currency_statement()
    stmt["currencies"] = ["EUR", "USD"]
    stmt["entries_per_currency"]["USD"] = [
        {"type": "invoice", "wfirma_doc_id": "USD-1",
         "doc_number": "USD/INV/1", "date": "2026-04-20",
         "currency": "USD", "debit": "200.00", "credit": "0.00",
         "running_balance": "200.00"},
    ]
    stmt["totals_per_currency"]["USD"] = {
        "invoiced": "200.00", "credited": "0.00",
        "received": "0.00", "outstanding": "200.00", "entry_count": 1,
    }
    stmt["aging_per_currency"]["USD"] = {
        "method": "invoice_age",
        "current": "0.00", "1_30": "200.00",
        "31_60": "0.00", "61_90": "0.00", "90_plus": "0.00",
        "total": "200.00",
    }
    pdf  = render_statement_pdf(stmt)
    text = _read_pdf_text(pdf)
    assert "Currency · EUR" in text
    assert "Currency · USD" in text
    # Each currency carries its own outstanding total.
    assert "500.00" in text
    assert "200.00" in text


# 6
def test_unmatched_payments_render_only_when_present():
    no_unm = _one_currency_statement()
    pdf_a  = render_statement_pdf(no_unm)
    text_a = _read_pdf_text(pdf_a)
    assert "Unmatched payments" not in text_a

    with_unm = _one_currency_statement()
    with_unm["unmatched_payments_per_currency"]["EUR"] = [{
        "wfirma_doc_id":  "P-UNM",
        "value":          "50.00",
        "currency":       "EUR",
        "date":           "2026-04-25",
        "linked_invoice": "",
    }]
    pdf_b  = render_statement_pdf(with_unm)
    text_b = _read_pdf_text(pdf_b)
    assert "Unmatched payments" in text_b
    assert "P-UNM" in text_b


# 7
def test_warnings_render_only_when_present():
    no_warn = _one_currency_statement()
    pdf_a   = render_statement_pdf(no_warn)
    text_a  = _read_pdf_text(pdf_a)
    assert "Warnings" not in text_a

    with_warn = _one_currency_statement()
    with_warn["warnings"] = [
        {"event": "overpayment_on_invoice", "wfirma_doc_id": "INV-9001",
         "overpaid_by": "50.00"},
        {"event": "proforma_treated_as_debit", "wfirma_doc_id": "P-1"},
    ]
    pdf_b  = render_statement_pdf(with_warn)
    text_b = _read_pdf_text(pdf_b)
    assert "Warnings" in text_b
    assert "overpayment_on_invoice"    in text_b
    assert "proforma_treated_as_debit" in text_b


# 8
@pytest.mark.parametrize("forbidden", [
    "paymentstate", "paymentdate", "alreadypaid", "remaining", "paid_date",
])
def test_forbidden_fields_are_not_rendered(forbidden):
    """Even if a hostile dict carries forbidden wFirma-input keys, the
    renderer must not surface them anywhere in the PDF text."""
    stmt = _one_currency_statement()
    # Inject the forbidden key at every plausible location.
    stmt["contractor"][forbidden] = "POISONED-CONTRACTOR-VALUE-XYZ"
    stmt[forbidden]                = "POISONED-TOPLEVEL-VALUE-XYZ"
    stmt["totals_per_currency"]["EUR"][forbidden] = "POISONED-TOTAL-XYZ"
    stmt["aging_per_currency"]["EUR"][forbidden]  = "POISONED-AGING-XYZ"
    for e in stmt["entries_per_currency"]["EUR"]:
        e[forbidden] = "POISONED-ENTRY-XYZ"
    stmt["warnings"] = [{"event": forbidden, forbidden: "POISONED-WARN-XYZ"}]
    stmt["unmatched_payments_per_currency"]["EUR"] = [{
        "wfirma_doc_id":  "P-UNM",
        "value":          "10.00",
        "currency":       "EUR",
        "date":           "2026-04-25",
        "linked_invoice": "",
        forbidden:        "POISONED-UNM-XYZ",
    }]
    pdf  = render_statement_pdf(stmt)
    text = _read_pdf_text(pdf)
    assert "POISONED" not in text, (
        f"forbidden key {forbidden!r} leaked a value into the PDF"
    )


# 9
def test_empty_statement_renders_cleanly():
    pdf  = render_statement_pdf(_empty_statement())
    assert pdf.startswith(b"%PDF-")
    text = _read_pdf_text(pdf)
    assert "Statement of Account" in text
    assert "TestCo" in text
    # Empty notice surfaces (no per-currency block, but the customer
    # block + meta strip + an "no activity" notice).
    assert "No invoices or payments" in text


# 10
def test_negative_outstanding_renders():
    """Overpayment ⇒ outstanding negative. The renderer must accept
    the negative string without crashing AND surface it in the PDF."""
    stmt = _one_currency_statement(outstanding="-50.00")
    pdf  = render_statement_pdf(stmt)
    text = _read_pdf_text(pdf)
    assert "-50.00" in text


# 11
def test_long_ledger_creates_multi_page_pdf():
    """A 200-entry ledger must flow across pages without crashing,
    and the PDF must contain more than one page."""
    stmt = _one_currency_statement()
    big_entries = []
    for i in range(200):
        big_entries.append({
            "type": "invoice",
            "wfirma_doc_id":   f"INV-{i:04d}",
            "doc_number":      f"FV {i+1}/2026",
            "date":            "2026-04-15",
            "currency":        "EUR",
            "debit":           "10.00",
            "credit":          "0.00",
            "running_balance": f"{(i+1)*10}.00",
        })
    stmt["entries_per_currency"]["EUR"] = big_entries
    stmt["totals_per_currency"]["EUR"] = {
        "invoiced": "2000.00", "credited": "0.00",
        "received": "0.00", "outstanding": "2000.00",
        "entry_count": 200,
    }
    pdf = render_statement_pdf(stmt)
    assert pdf.startswith(b"%PDF-")
    assert _read_pdf_pages(pdf) >= 2


def test_ledger_table_header_repeats_on_each_page():
    """`repeatRows=1` ensures the ledger column headers print on
    every page. The header text must appear at least twice in a
    multi-page PDF."""
    stmt = _one_currency_statement()
    big_entries = []
    for i in range(200):
        big_entries.append({
            "type": "invoice",
            "wfirma_doc_id":   f"INV-{i:04d}",
            "doc_number":      f"FV {i+1}",
            "date":            "2026-04-15",
            "currency":        "EUR",
            "debit":           "10.00",
            "credit":          "0.00",
            "running_balance": f"{(i+1)*10}.00",
        })
    stmt["entries_per_currency"]["EUR"] = big_entries
    pdf  = render_statement_pdf(stmt)
    text = _read_pdf_text(pdf)
    # "Balance" header appears at least twice when ledger table spans
    # 2+ pages thanks to repeatRows.
    assert text.count("Balance") >= 2


def test_renderer_rejects_non_dict():
    with pytest.raises(ValueError):
        render_statement_pdf("not-a-dict")  # type: ignore[arg-type]


def test_renderer_runtime_error_on_build_failure(monkeypatch):
    """If reportlab build raises, the renderer wraps it in
    RuntimeError so the route can convert to 502."""
    from reportlab.platypus import SimpleDocTemplate as _SDT
    real_build = _SDT.build

    def _explode(self, *a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(_SDT, "build", _explode)
    with pytest.raises(RuntimeError) as exc:
        render_statement_pdf(_empty_statement())
    assert "reportlab build failed" in str(exc.value)


# ════════════════════════════════════════════════════════════════════════
#  Route — GET /api/v1/ledgers/clients/{id}/statement.pdf
# ════════════════════════════════════════════════════════════════════════

# 12, happy path
def test_route_returns_application_pdf(client, monkeypatch):
    _stub_contractor_ok(monkeypatch, name="ACME")
    inv = _envelope_invoices(
        "<invoice>"
          "<id>1</id><fullnumber>FV 1/2026</fullnumber>"
          "<type>normal</type><date>2026-04-15</date>"
          "<currency>EUR</currency><netto>100</netto><brutto>123.00</brutto>"
          "<contractor><id>C-1</id></contractor>"
        "</invoice>"
    )
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        _two_endpoint_stub([inv], [_envelope_payments("")]),
    )
    r = client.get(
        "/api/v1/ledgers/clients/C-1/statement.pdf"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF-")


# 12b — Lesson G: the statement PDF is a regenerable download carrying
# live per-customer financial data (linked from the V2 Client Ledger
# page). A browser-cached copy would show a stale balance, so the route
# MUST send the full no-store header triplet.
def test_route_sets_no_store_cache_headers(client, monkeypatch):
    _stub_contractor_ok(monkeypatch, name="ACME")
    inv = _envelope_invoices(
        "<invoice>"
          "<id>1</id><fullnumber>FV 1/2026</fullnumber>"
          "<type>normal</type><date>2026-04-15</date>"
          "<currency>EUR</currency><netto>100</netto><brutto>123.00</brutto>"
          "<contractor><id>C-1</id></contractor>"
        "</invoice>"
    )
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        _two_endpoint_stub([inv], [_envelope_payments("")]),
    )
    r = client.get(
        "/api/v1/ledgers/clients/C-1/statement.pdf"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("cache-control") == \
        "no-store, no-cache, must-revalidate, max-age=0"
    assert r.headers.get("pragma")  == "no-cache"
    assert r.headers.get("expires") == "0"


# 13
def test_route_filename_is_sanitised(client, monkeypatch):
    _stub_contractor_ok(monkeypatch)
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        _two_endpoint_stub([_envelope_invoices("")], [_envelope_payments("")]),
    )
    r = client.get(
        "/api/v1/ledgers/clients/C-9001/statement.pdf"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert "statement-C-9001-2026-04-01-2026-05-01.pdf" in cd
    assert 'inline' in cd


# 14
def test_route_404_unknown_contractor(client, monkeypatch):
    monkeypatch.setattr(
        wfirma_client, "fetch_contractor_by_id",
        lambda cid: SimpleNamespace(ok=False, error="not found"),
    )
    r = client.get(
        "/api/v1/ledgers/clients/MISSING/statement.pdf"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "CONTRACTOR_NOT_FOUND"


# 15
@pytest.mark.parametrize("qs", [
    "?from=&to=2026-05-01",
    "?from=2026-04-01&to=",
    "?from=not-a-date&to=2026-05-01",
    "?from=2026-05-01&to=2026-04-01",
    "?from=2026-04-01&to=2026-05-01&as_of=2026-03-01",
    "?from=2026-04-01&to=2026-05-01&as_of=not-a-date",
])
def test_route_400_bad_dates(client, qs):
    r = client.get(
        "/api/v1/ledgers/clients/C-1/statement.pdf" + qs,
        headers=_auth_headers(),
    )
    assert r.status_code == 400


# 16
def test_route_502_invoices_fetch_failure(client, monkeypatch):
    _stub_contractor_ok(monkeypatch)
    def _stub(method, module, action, body=""):
        if module == "invoices": return 500, "boom"
        return 200, _envelope_payments("")
    monkeypatch.setattr(wfirma_client, "_http_request", _stub)
    r = client.get(
        "/api/v1/ledgers/clients/C-1/statement.pdf"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "STATEMENT_INVOICE_FETCH_FAILED"


def test_route_502_payments_fetch_failure(client, monkeypatch):
    _stub_contractor_ok(monkeypatch)
    def _stub(method, module, action, body=""):
        if module == "invoices": return 200, _envelope_invoices("")
        if module == "payments": return 500, "boom"
        return 200, "<api/>"
    monkeypatch.setattr(wfirma_client, "_http_request", _stub)
    r = client.get(
        "/api/v1/ledgers/clients/C-1/statement.pdf"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "STATEMENT_PAYMENT_FETCH_FAILED"


# 17
def test_route_502_render_failure(client, monkeypatch):
    """If the renderer raises after a successful fetch, the route
    must convert to 502 STATEMENT_PDF_RENDER_FAILED."""
    _stub_contractor_ok(monkeypatch)
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        _two_endpoint_stub([_envelope_invoices("")], [_envelope_payments("")]),
    )
    # Patch the renderer at its import site inside routes_ledgers.
    from app.api import routes_ledgers as rl
    def _boom(stmt):
        raise RuntimeError("fake render boom")
    monkeypatch.setattr(rl, "render_statement_pdf", _boom)
    r = client.get(
        "/api/v1/ledgers/clients/C-1/statement.pdf"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "STATEMENT_PDF_RENDER_FAILED"
    assert "fake render boom" in r.json()["detail"]["error"]


# 18
def test_statement_json_route_still_works(client, monkeypatch):
    """Phase 10B JSON endpoint must keep working after the Phase 10C
    refactor extracted ``_build_statement_dict``."""
    _stub_contractor_ok(monkeypatch)
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        _two_endpoint_stub([_envelope_invoices("")], [_envelope_payments("")]),
    )
    r = client.get(
        "/api/v1/ledgers/clients/C-1/statement.json"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["contractor"]["wfirma_contractor_id"] == "C-1"
    assert body["aging_per_currency"]                 == {}


# 19
def test_invoice_ledger_route_still_works(client, monkeypatch):
    _stub_contractor_ok(monkeypatch)
    inv = _envelope_invoices(
        "<invoice><id>1</id><fullnumber>FV 1</fullnumber>"
        "<type>normal</type><date>2026-04-15</date>"
        "<currency>EUR</currency><netto>100</netto><brutto>123.00</brutto>"
        "<contractor><id>C-1</id></contractor></invoice>"
    )
    monkeypatch.setattr(
        wfirma_client, "_http_request",
        _two_endpoint_stub([inv], [_envelope_payments("")]),
    )
    r = client.get(
        "/api/v1/ledgers/clients/C-1/invoice-ledger.json"
        "?from=2026-04-01&to=2026-05-01",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert "outstanding" not in r.text
    assert "aging_per_currency" not in body


# Source-grep wiring ---------------------------------------------------

ROUTES_LEDGERS_PATH = (
    Path(__file__).resolve().parent.parent
    / "app" / "api" / "routes_ledgers.py"
)


def test_routes_ledgers_has_statement_pdf_route():
    src = ROUTES_LEDGERS_PATH.read_text(encoding="utf-8")
    assert '/clients/{contractor_id}/statement.pdf' in src
    assert '/clients/{contractor_id}/statement.json' in src
    assert '/clients/{contractor_id}/invoice-ledger.json' in src


def test_routes_ledgers_uses_shared_builder():
    """Refactoring rule: both /statement.json and /statement.pdf must
    call the shared ``_build_statement_dict`` helper. This catches a
    future regression where the PDF path duplicates fetch logic."""
    src = ROUTES_LEDGERS_PATH.read_text(encoding="utf-8")
    assert src.count("_build_statement_dict(") >= 2


def test_routes_ledgers_pdf_declares_no_store_headers():
    """Lesson G source pin: the statement.pdf download must carry the
    full no-store header triplet. Guards against the constant being
    dropped or the merge into the Response headers being removed."""
    src = ROUTES_LEDGERS_PATH.read_text(encoding="utf-8")
    assert "no-store, no-cache, must-revalidate, max-age=0" in src
    assert '"Pragma":' in src
    assert '"Expires":' in src
    # The triplet must actually be merged into the PDF Response, not
    # merely defined and left unused.
    assert "**_NO_STORE_HEADERS" in src
