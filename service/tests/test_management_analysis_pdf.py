"""
test_management_analysis_pdf.py — Management Analysis PDF.

Parity rule: screen DTO == PDF DTO. The renderer takes the exact bodies
``management-analysis.json`` (AR) and ``payables-analysis.json`` (AP) return
and lays them out. It selects and formats; it never recomputes a balance and
never adds two currencies together.

Coverage:
   1. renderer returns %PDF- bytes
   2. every currency_summaries figure appears (AR + AP parity)
   3. no cross-currency grand total anywhere
   4. one page section per currency
   5. Receivables and Payables KPIs both present
   6. credits reported separately from the overdue buckets
   7. scope line: all_outstanding prints the floor; custom prints the period
   8. exposure tables render, and a bitten row cap is disclosed
   9. data-quality appendix present and restrained
  10. route returns application/pdf and calls both JSON builders
  11. route honours scope=all_outstanding with no dates
"""
from __future__ import annotations

import io
import re
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.core.config import settings
from app.services.statement_pdf_renderer import render_management_analysis_pdf


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


# ── Synthetic analytics bodies ────────────────────────────────────────────

def _ar(scope="all_outstanding", currencies=("EUR",)) -> dict:
    sums = {
        "EUR": {"currency": "EUR", "total_receivable": "4500.00", "overdue": "1500.00",
                 "not_due": "3000.00", "customer_credits": "200.00",
                 "customers_outstanding": 3, "oldest_overdue_days": 47,
                 "aging": {"not_due": "1500.00", "b_1_30": "1500.00", "b_31_90": "0.00",
                            "b_91_180": "0.00", "b_180_plus": "0.00",
                            "due_date_unavailable": "0.00"},
                 "reconciliation_ok": True},
        "USD": {"currency": "USD", "total_receivable": "800.00", "overdue": "0.00",
                 "not_due": "800.00", "customer_credits": "0.00",
                 "customers_outstanding": 1, "oldest_overdue_days": 0,
                 "aging": {"not_due": "800.00", "b_1_30": "0.00", "b_31_90": "0.00",
                            "b_91_180": "0.00", "b_180_plus": "0.00",
                            "due_date_unavailable": "0.00"},
                 "reconciliation_ok": True},
    }
    custs = [
        {"contractor_id": "C1", "customer_name": "Maison Lyon", "currency": "EUR",
         "outstanding": "3000.00", "overdue": "1500.00", "credit_balance": "200.00",
         "oldest_due_date": "2026-05-01", "open_invoice_count": 2,
         "not_due": "1500.00", "b_1_30": "1500.00", "b_31_90": "0.00",
         "b_91_180": "0.00", "b_180_plus": "0.00", "due_date_unavailable": "0.00"},
        {"contractor_id": "C2", "customer_name": "Bijoux SA", "currency": "USD",
         "outstanding": "800.00", "overdue": "0.00", "credit_balance": "0.00",
         "oldest_due_date": "2026-09-01", "open_invoice_count": 1,
         "not_due": "800.00", "b_1_30": "0.00", "b_31_90": "0.00",
         "b_91_180": "0.00", "b_180_plus": "0.00", "due_date_unavailable": "0.00"},
    ]
    return {
        "generated_at": "2026-08-10T09:00:00Z",
        "as_of": "2026-08-10",
        "period": {"from": "2020-01-01", "to": "2026-08-10"},
        "filters": {"scope": scope,
                     "outstanding_floor": "2020-01-01" if scope == "all_outstanding" else None},
        "source_health": {"ok": True},
        "currency_summaries": [sums[c] for c in currencies],
        "customers": [c for c in custs if c["currency"] in currencies],
        "due_date_coverage": {"open_coverage_pct": 98},
        "data_quality": {},
        "query_stats": {"per_customer_wfirma_calls": 0},
        "warnings": [],
    }


def _ap(currencies=("EUR",)) -> dict:
    sums = {
        "EUR": {"currency": "EUR", "gross_payable": "2200.00", "overdue": "700.00",
                 "not_due": "1500.00", "supplier_credits": "100.00",
                 "net_payable": "2100.00", "suppliers_outstanding": 2,
                 "aging": {"not_due": "1500.00", "b_1_30": "700.00", "b_31_90": "0.00",
                            "b_91_180": "0.00", "b_180_plus": "0.00",
                            "due_date_unavailable": "0.00"}},
        "USD": {"currency": "USD", "gross_payable": "300.00", "overdue": "0.00",
                 "not_due": "300.00", "supplier_credits": "0.00",
                 "net_payable": "300.00", "suppliers_outstanding": 1,
                 "aging": {"not_due": "300.00", "b_1_30": "0.00", "b_31_90": "0.00",
                            "b_91_180": "0.00", "b_180_plus": "0.00",
                            "due_date_unavailable": "0.00"}},
    }
    sups = [
        {"contractor_id": "S1", "supplier_name": "Gemstone Traders", "currency": "EUR",
         "gross_payable": "2200.00", "overdue": "700.00", "credit_balance": "100.00",
         "oldest_due_date": "2026-06-01", "open_expense_count": 2,
         "not_due": "1500.00", "b_1_30": "700.00", "b_31_90": "0.00",
         "b_91_180": "0.00", "b_180_plus": "0.00", "due_date_unavailable": "0.00"},
        {"contractor_id": "S2", "supplier_name": "Setter Co", "currency": "USD",
         "gross_payable": "300.00", "overdue": "0.00", "credit_balance": "0.00",
         "oldest_due_date": "2026-10-01", "open_expense_count": 1,
         "not_due": "300.00", "b_1_30": "0.00", "b_31_90": "0.00",
         "b_91_180": "0.00", "b_180_plus": "0.00", "due_date_unavailable": "0.00"},
    ]
    return {
        "generated_at": "2026-08-10T09:00:00Z",
        "as_of": "2026-08-10",
        "period": {"from": "2020-01-01", "to": "2026-08-10"},
        "filters": {"scope": "all_outstanding", "outstanding_floor": "2020-01-01"},
        "source_health": {"ok": True},
        "currency_summaries": [sums[c] for c in currencies],
        "suppliers": [s for s in sups if s["currency"] in currencies],
        "due_date_coverage": {"open_coverage_pct": 91},
        "data_quality": {},
        "query_stats": {"per_supplier_wfirma_calls": 0},
        "warnings": [],
    }


# ── 1-2. Renders + parity ─────────────────────────────────────────────────

def test_renderer_returns_pdf_magic_bytes():
    pdf = render_management_analysis_pdf(_ar(), _ap())
    assert isinstance(pdf, bytes) and pdf.startswith(b"%PDF-")


def test_every_currency_summary_figure_appears():
    ar, ap = _ar(currencies=("EUR", "USD")), _ap(currencies=("EUR", "USD"))
    t = _text(render_management_analysis_pdf(ar, ap))
    for s in ar["currency_summaries"]:
        for k in ("total_receivable", "overdue", "not_due", "customer_credits"):
            assert str(s[k]) in t, f"AR {s['currency']}.{k} missing from the PDF"
    for s in ap["currency_summaries"]:
        for k in ("gross_payable", "overdue", "not_due", "supplier_credits",
                   "net_payable"):
            assert str(s[k]) in t, f"AP {s['currency']}.{k} missing from the PDF"


def test_pdf_invents_no_figures():
    """Every money value on the page traces back to the analytics dicts.

    No allowance for renderer-side arithmetic: the currency-level aging
    subtotals are produced by the analytics layer and carried in
    ``currency_summaries[].aging``, so the PDF projects them like every other
    figure. A subtotal the JSON does not contain is a second calculation.
    """
    ar, ap = _ar(currencies=("EUR", "USD")), _ap(currencies=("EUR", "USD"))

    def collect(node, acc):
        if isinstance(node, dict):
            for v in node.values():
                collect(v, acc)
        elif isinstance(node, list):
            for v in node:
                collect(v, acc)
        else:
            acc.add(str(node))
        return acc

    known = collect(ar, set()) | collect(ap, set())
    printed = set(re.findall(r"\b\d+\.\d{2}\b", _text(render_management_analysis_pdf(ar, ap))))
    assert printed <= known, f"PDF invented figures: {sorted(printed - known)}"


def test_aging_row_is_the_summary_aging_not_a_renderer_sum():
    """Break the DTO's aging block and the page must follow it — proving the
    renderer reads the summary rather than re-adding the exposure rows."""
    ar, ap = _ar(), _ap()
    ar["currency_summaries"][0]["aging"]["b_31_90"] = "12345.67"
    t = _text(render_management_analysis_pdf(ar, ap))
    assert "12345.67" in t, (
        "the aging row must project currency_summaries[].aging — a renderer-side "
        "sum of the customer rows would silently ignore it"
    )


# ── 3-4. Currencies never combined ────────────────────────────────────────

def test_no_cross_currency_grand_total():
    ar, ap = _ar(currencies=("EUR", "USD")), _ap(currencies=("EUR", "USD"))
    t = _text(render_management_analysis_pdf(ar, ap))
    # 4500.00 EUR + 800.00 USD, and 2200.00 EUR + 300.00 USD.
    for consolidated in ("5300.00", "2500.00"):
        assert consolidated not in t, "currencies must never be FX-consolidated"
    for banned in ("Grand total", "GRAND TOTAL", "Total (all currencies)", "NBP"):
        assert banned not in t


def test_one_page_section_per_currency():
    one = _pages(render_management_analysis_pdf(_ar(), _ap()))
    two = _pages(render_management_analysis_pdf(
        _ar(currencies=("EUR", "USD")), _ap(currencies=("EUR", "USD"))))
    assert two > one, "each currency must start its own page section"


# ── 5-6. KPI blocks and credits ───────────────────────────────────────────

def test_receivables_and_payables_sections_present():
    t = _text(render_management_analysis_pdf(_ar(), _ap()))
    assert "Receivables" in t and "Payables" in t
    assert "Customer exposure" in t and "Supplier exposure" in t
    assert "Maison Lyon" in t and "Gemstone Traders" in t


def test_credits_reported_separately_from_overdue():
    t = _text(render_management_analysis_pdf(_ar(), _ap()))
    assert "Customer credits" in t and "Supplier credits" in t
    # Credits must not be folded into an overdue bucket: 1500 overdue + 200
    # credits would show as 1700.00 if they were combined.
    assert "1700.00" not in t


# ── 7. Scope line ─────────────────────────────────────────────────────────

def test_scope_line_prints_the_outstanding_floor():
    t = _text(render_management_analysis_pdf(_ar(scope="all_outstanding"), _ap()))
    assert "All outstanding since 2020-01-01" in t
    assert "2026-08-10" in t


def test_scope_line_prints_the_period_for_custom():
    ar = _ar(scope="custom_period")
    ar["period"] = {"from": "2026-07-01", "to": "2026-07-31"}
    t = _text(render_management_analysis_pdf(ar, _ap()))
    assert "2026-07-01" in t and "2026-07-31" in t
    assert "All outstanding since" not in t


# ── 8. Exposure cap is disclosed ──────────────────────────────────────────

def test_row_cap_is_disclosed_when_it_bites():
    ar = _ar()
    row = ar["customers"][0]
    ar["customers"] = [dict(row, contractor_id=f"C{i}", customer_name=f"Client {i}")
                       for i in range(60)]
    t = _text(render_management_analysis_pdf(ar, _ap()))
    assert "60" in t and "largest" in t.lower(), (
        "a truncated exposure table must say so — silence reads as 'this is everyone'"
    )


def test_row_cap_note_absent_when_it_does_not_bite():
    t = _text(render_management_analysis_pdf(_ar(), _ap()))
    assert "largest of" not in t.lower()


# ── 9. Appendix ───────────────────────────────────────────────────────────

def test_data_quality_appendix_present():
    t = _text(render_management_analysis_pdf(_ar(), _ap()))
    assert "Data quality" in t
    assert "98" in t and "91" in t


def test_non_dict_input_is_rejected():
    with pytest.raises(ValueError):
        render_management_analysis_pdf(_ar(), ["nope"])


# ── 10-11. Route contract ─────────────────────────────────────────────────

def test_route_returns_pdf_from_both_json_builders(client):
    with patch("app.api.routes_ledgers._build_management_analysis_dict",
               return_value=_ar()) as m_ar, \
         patch("app.api.routes_ledgers._build_payables_analysis_dict",
               return_value=_ap()) as m_ap:
        r = client.get("/api/v1/ledgers/management-analysis.pdf",
                       params={"scope": "all_outstanding"}, headers=_hdr())
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF-")
    assert m_ar.called and m_ap.called, (
        "the PDF must project both JSON authorities, not recompute either"
    )


def test_route_502_on_render_failure(client):
    with patch("app.api.routes_ledgers._build_management_analysis_dict",
               return_value=_ar()), \
         patch("app.api.routes_ledgers._build_payables_analysis_dict",
               return_value=_ap()), \
         patch("app.api.routes_ledgers.render_management_analysis_pdf",
               side_effect=RuntimeError("boom")):
        r = client.get("/api/v1/ledgers/management-analysis.pdf",
                       params={"scope": "all_outstanding"}, headers=_hdr())
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "MANAGEMENT_ANALYSIS_PDF_RENDER_FAILED"


def test_route_takes_the_same_parameters_as_the_json_route():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "app/api/routes_ledgers.py").read_text(encoding="utf-8")
    assert src.count("_build_management_analysis_dict(") >= 3
    assert src.count("_build_payables_analysis_dict(") >= 3
