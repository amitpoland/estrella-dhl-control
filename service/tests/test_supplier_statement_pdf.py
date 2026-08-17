"""
test_supplier_statement_pdf.py — Supplier Ledger statement PDF.

Parity rule: screen DTO == PDF DTO. The PDF is a projection of the exact dict
``/suppliers/{id}/statement.json`` returns; it performs no accounting
arithmetic. Parity is structural (one ``_build_supplier_statement_dict``
called by both routes) and asserted numerically below.

Business-facing: no wFirma ids, no raw metadata, no operator warnings, no NBP
or FX labels.

Coverage:
   1. renderer returns %PDF- bytes
   2. supplier name, address and tax id render
   3. selected period renders
   4. per-currency totals render, and equal the JSON totals (parity)
   5. aging summary renders with the AP bucket labels
   6. multi-currency renders separate sections; no cross-currency total
   7. wFirma ids / metadata / warnings never reach the page
   8. both routes call the one builder (structural parity)
   9. empty statement renders cleanly
  10. long ledger paginates
  11. route returns application/pdf with a sanitized filename
  12. route 400 on bad dates, 502 on render failure
"""
from __future__ import annotations

import io
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.core.config import settings
from app.services.statement_pdf_renderer import render_supplier_statement_pdf


def _text(pdf: bytes) -> str:
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages)


def _pages(pdf: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf)).pages)


@pytest.fixture()
def client() -> TestClient:
    settings.api_key = settings.api_key or "test-key"
    from app.main import app
    with TestClient(app) as c:
        yield c


def _hdr():
    return {"X-API-Key": settings.api_key or "test-key"}


# ── Synthetic statement (shape of aggregate_supplier_statement) ───────────

def _stmt(*, currencies=("EUR",), warnings=None) -> dict:
    entries = {
        "EUR": [
            {"type": "expense", "wfirma_doc_id": "EXP-7001", "doc_number": "FZ 14/2026",
             "date": "2026-04-03", "due_date": "2026-05-03", "currency": "EUR",
             "debit": "1000.00", "credit": "0.00", "running_balance": "1000.00"},
            {"type": "payment", "wfirma_doc_id": "PAY-8001", "doc_number": "",
             "linked_expense": "EXP-7001", "date": "2026-04-20", "currency": "EUR",
             "debit": "0.00", "credit": "900.00", "running_balance": "100.00"},
        ],
        "USD": [
            {"type": "expense", "wfirma_doc_id": "EXP-7002", "doc_number": "FZ 15/2026",
             "date": "2026-04-05", "due_date": "2026-06-05", "currency": "USD",
             "debit": "60.00", "credit": "0.00", "running_balance": "60.00"},
        ],
    }
    totals = {
        "EUR": {"gross_payable": "1000.00", "supplier_credits": "0.00",
                 "payments_applied": "900.00", "outstanding": "100.00",
                 "net_payable": "100.00", "entry_count": 2},
        "USD": {"gross_payable": "60.00", "supplier_credits": "0.00",
                 "payments_applied": "0.00", "outstanding": "60.00",
                 "net_payable": "60.00", "entry_count": 1},
    }
    aging = {
        "EUR": {"not_due": "0.00", "b_1_30": "100.00", "b_31_60": "0.00",
                 "b_91_180": "0.00", "b_365_plus": "0.00",
                 "due_date_unavailable": "0.00", "total": "100.00",
                 "method": "due_date"},
        "USD": {"not_due": "60.00", "b_1_30": "0.00", "b_31_60": "0.00",
                 "b_91_180": "0.00", "b_365_plus": "0.00",
                 "due_date_unavailable": "0.00", "total": "60.00",
                 "method": "due_date"},
    }
    ccys = list(currencies)
    return {
        "contractor": {
            "wfirma_contractor_id": "S-42",
            "name": "Gemstone Traders GmbH",
            "country": "DE",
            "vat_id": "DE811234567",
            "street": "Hauptstrasse 12",
            "city": "Idar-Oberstein",
            "postal_code": "55743",
        },
        "generated_at": "2026-08-10",
        "period": {"from": "2026-04-01", "to": "2026-06-30"},
        "as_of": "2026-08-10",
        "currencies": ccys,
        "entries_per_currency": {c: entries[c] for c in ccys},
        "totals_per_currency": {c: totals[c] for c in ccys},
        "aging_per_currency": {c: aging[c] for c in ccys},
        "warnings": list(warnings or []),
        "query_stats": {"per_supplier_wfirma_calls": 0, "expense_api_calls": 1,
                         "note": "shared AP fact universe + Python contractor filter"},
    }


# ── 1-3. Renders, identity, period ────────────────────────────────────────

def test_renderer_returns_pdf_magic_bytes():
    pdf = render_supplier_statement_pdf(_stmt())
    assert isinstance(pdf, bytes) and pdf.startswith(b"%PDF-")


def test_supplier_identity_and_address_render():
    t = _text(render_supplier_statement_pdf(_stmt()))
    assert "Gemstone Traders" in t
    assert "Hauptstrasse 12" in t
    assert "Idar-Oberstein" in t
    assert "DE811234567" in t
    assert "Supplier" in t


def test_period_renders():
    t = _text(render_supplier_statement_pdf(_stmt()))
    assert "2026-04-01" in t and "2026-06-30" in t


# ── 4. Parity ─────────────────────────────────────────────────────────────

def test_every_total_in_the_pdf_equals_the_statement_dict():
    stmt = _stmt(currencies=("EUR", "USD"))
    t = _text(render_supplier_statement_pdf(stmt))
    for ccy, tot in stmt["totals_per_currency"].items():
        assert ccy in t
        for key in ("gross_payable", "supplier_credits", "payments_applied",
                     "outstanding", "net_payable"):
            assert str(tot[key]) in t, f"{ccy}.{key}={tot[key]} missing from the PDF"


def test_pdf_prints_no_figure_the_statement_does_not_contain():
    """No invented money: every 2-dp number on the page comes from the dict."""
    import re
    stmt = _stmt(currencies=("EUR", "USD"))
    known = set()
    for tot in stmt["totals_per_currency"].values():
        known |= {str(v) for v in tot.values()}
    for ag in stmt["aging_per_currency"].values():
        known |= {str(v) for v in ag.values()}
    for rows in stmt["entries_per_currency"].values():
        for e in rows:
            known |= {e["debit"], e["credit"], e["running_balance"]}
    t = _text(render_supplier_statement_pdf(stmt))
    printed = set(re.findall(r"\b\d+\.\d{2}\b", t))
    assert printed <= known, f"PDF invented figures: {sorted(printed - known)}"


# ── 5. Aging ──────────────────────────────────────────────────────────────

def test_aging_summary_uses_the_ap_buckets():
    t = _text(render_supplier_statement_pdf(_stmt()))
    assert "Aging" in t
    for label in ("Not due", "1–30", "31–60", "61–90", "91–180", "181–365", "365+"):
        assert label in t, f"AP bucket {label!r} missing"


def test_aging_total_matches_outstanding():
    stmt = _stmt()
    assert (Decimal(stmt["aging_per_currency"]["EUR"]["total"])
            == Decimal(stmt["totals_per_currency"]["EUR"]["outstanding"])), (
        "fixture invariant: aging must reconcile to outstanding"
    )
    t = _text(render_supplier_statement_pdf(stmt))
    assert "100.00" in t


# ── 6. Currencies stay separate ───────────────────────────────────────────

def test_multi_currency_sections_separate_with_no_grand_total():
    stmt = _stmt(currencies=("EUR", "USD"))
    t = _text(render_supplier_statement_pdf(stmt))
    assert "EUR" in t and "USD" in t
    # 100.00 + 60.00 must never appear as a consolidated figure.
    assert "160.00" not in t, "currencies must never be FX-consolidated"
    for banned in ("Grand total", "GRAND TOTAL", "Total (all currencies)"):
        assert banned not in t


# ── 7. Nothing internal leaks ─────────────────────────────────────────────

def test_internal_metadata_never_reaches_the_page():
    stmt = _stmt(warnings=["expense EXP-7001 has no due date"])
    t = _text(render_supplier_statement_pdf(stmt))
    for banned in ("EXP-7001", "PAY-8001", "S-42", "wfirma", "wFirma", "NBP",
                    "query_stats", "linked_expense", "has no due date"):
        assert banned not in t, f"business PDF leaked {banned!r}"


# ── 8. Structural parity ──────────────────────────────────────────────────

def test_json_and_pdf_routes_share_one_builder():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "app/api/routes_ledgers.py").read_text(encoding="utf-8")
    assert src.count("_build_supplier_statement_dict(") >= 3, (
        "both routes must call the single builder (1 def + 2 call sites)"
    )
    assert src.count("aggregate_supplier_statement(") == 1, (
        "aggregation must happen once — the PDF must not re-aggregate"
    )


# ── 9-10. Edge shapes ─────────────────────────────────────────────────────

def test_empty_statement_renders_cleanly():
    stmt = _stmt()
    stmt.update(currencies=[], entries_per_currency={},
                totals_per_currency={}, aging_per_currency={})
    pdf = render_supplier_statement_pdf(stmt)
    assert pdf.startswith(b"%PDF-")
    assert "No expenses or payments" in _text(pdf)


def test_long_ledger_paginates():
    stmt = _stmt()
    row = stmt["entries_per_currency"]["EUR"][0]
    stmt["entries_per_currency"]["EUR"] = [dict(row, doc_number=f"FZ {i}/2026")
                                            for i in range(120)]
    assert _pages(render_supplier_statement_pdf(stmt)) > 1


def test_non_dict_input_is_rejected():
    with pytest.raises(ValueError):
        render_supplier_statement_pdf(["not", "a", "dict"])


# ── 11-12. Route contract ─────────────────────────────────────────────────

def test_route_returns_pdf_with_sanitized_filename(client):
    with patch("app.api.routes_ledgers._build_supplier_statement_dict",
               return_value=_stmt()):
        r = client.get("/api/v1/ledgers/suppliers/S-42/statement.pdf",
                       params={"from": "2026-04-01", "to": "2026-06-30"},
                       headers=_hdr())
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF-")
    assert "no-store" in r.headers["cache-control"]
    assert ".." not in r.headers["content-disposition"]


def test_route_400_on_bad_dates(client):
    r = client.get("/api/v1/ledgers/suppliers/S-42/statement.pdf",
                   params={"from": "not-a-date", "to": "2026-06-30"},
                   headers=_hdr())
    assert r.status_code == 400, "validation must not be masked as 502"


def test_route_502_on_render_failure(client):
    with patch("app.api.routes_ledgers._build_supplier_statement_dict",
               return_value=_stmt()), \
         patch("app.api.routes_ledgers.render_supplier_statement_pdf",
               side_effect=RuntimeError("boom")):
        r = client.get("/api/v1/ledgers/suppliers/S-42/statement.pdf",
                       params={"from": "2026-04-01", "to": "2026-06-30"},
                       headers=_hdr())
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "SUPPLIER_STATEMENT_PDF_RENDER_FAILED"


def test_json_route_still_works(client):
    with patch("app.api.routes_ledgers._build_supplier_statement_dict",
               return_value=_stmt()):
        r = client.get("/api/v1/ledgers/suppliers/S-42/statement.json",
                       params={"from": "2026-04-01", "to": "2026-06-30"},
                       headers=_hdr())
    assert r.status_code == 200
    assert r.json()["totals_per_currency"]["EUR"]["outstanding"] == "100.00"
