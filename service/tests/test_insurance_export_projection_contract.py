"""Insurance Export — the whole-report projection contract.

The presentation pins in ``test_insurance_export_presentation.py`` prove one
row behaves. This file proves the *report* behaves: every row, every group,
every total, over a multi-currency universe that includes the two shapes that
actually broke in production —

* a PLN row, whose USD-bridge cross rate carries 26 fractional digits (the
  value that leaked into the web table and the PDF), and
* rows that reach ``needs_review`` through different branches, which is where
  a reason-less chip could reappear.

Everything below runs the REAL FX boundary and the REAL assembler; only the
two edges (wFirma reads, the charge-record file) are stubbed, following
``test_insurance_export_authority_convergence.py``.

The four contracts, all of which a future refactor must keep:

1. ``needs_review`` implies a reason. Always. On documents and on corrections.
2. Every rated row carries ``fx_rate_display`` at exactly 4 fractional digits,
   and it is a *view* of ``fx_rate`` — never the other way round.
3. No INR value in the report is derivable from the display rate.
4. Row INR sums == contractor subtotals == report totals == KPI. Four ways of
   printing one number, never four numbers.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.services.insurance_export_statement as ies
from app.core.config import settings
from app.services import india_official_fx, insurance_fx_provider, nbp_rate_service
from app.services.insurance_export_statement import (
    InsuranceStatus,
    assemble_insurance_export_report,
)

DB = Path("unused-proforma.db")
CDB = Path("unused-carrier.db")
PERIOD = ("2026-08-01", "2026-08-31")

# Synthetic upstream quotes — test input, never an approved production rate.
INR_PER_USD = Decimal("87.500000")
INR_PER_EUR = Decimal("101.250000")
PLN_PER_USD = Decimal("3.6421")          # NBP bridge leg
# 87.500000 / 3.6421 does not terminate -> the long Decimal the operator saw.
INR_PER_PLN = INR_PER_USD / PLN_PER_USD


def _fact(inv_id, fullnumber, *, currency="USD", brutto="1000.00",
          doc_type="normal", contractor_id="C-1",
          contractor_name="Alpha Exports Ltd", date="2026-08-14"):
    return {"id": inv_id, "fullnumber": fullnumber, "type": doc_type,
            "date": date, "paymentdate": "", "currency": currency,
            "netto": None, "brutto": brutto,
            "contractor_id": contractor_id, "contractor_name": contractor_name}


def _invoiced(amount, currency):
    return [{"charge_type": "insurance", "amount": amount, "currency": currency,
             "resolution": "invoiced", "conflict_state": ""}]


def _draft(currency="USD"):
    return SimpleNamespace(id=7, batch_id="BATCH-1",
                           client_name="Alpha Exports Ltd",
                           currency=currency, service_charges_json="[]")


class Universe:
    """A period wide enough to exercise every branch that reaches a total.

    Contractor C-1 (Alpha): USD invoice with a recorded premium, EUR invoice
    with a proven 0.00, PLN invoice with a recorded premium and the long
    cross rate, plus a correction against the USD invoice.
    Contractor C-2 (Beta): USD invoice with NO charge record (unknown, not
    zero) and no draft link, and a GBP invoice the FX authority cannot rate.
    """

    def __init__(self, monkeypatch, tmp_path):
        self.facts = [
            _fact("101", "WDT 153/2026", brutto="1000.00"),
            _fact("102", "WDT 154/2026", currency="EUR", brutto="2000.00"),
            _fact("103", "WDT 155/2026", currency="PLN", brutto="5000.00"),
            _fact("201", "KOR 201/2026", brutto="-200.00", doc_type="correction"),
            _fact("301", "WDT 156/2026", brutto="3000.00",
                  contractor_id="C-2", contractor_name="Beta Trading GmbH"),
            _fact("302", "WDT 157/2026", currency="GBP", brutto="4000.00",
                  contractor_id="C-2", contractor_name="Beta Trading GmbH"),
        ]
        self.invoiced = {
            "101": _invoiced("56.98", "USD"),
            "102": _invoiced("0.00", "EUR"),      # proven zero, not unknown
            "103": _invoiced("41.20", "PLN"),
            "201": _invoiced("0.00", "USD"),
            "302": _invoiced("12.00", "GBP"),
        }                                          # 301: no record at all
        self.drafts = {"101": _draft(), "102": _draft("EUR"),
                       "103": _draft("PLN"), "201": _draft(),
                       "302": _draft("GBP")}       # 301: unlinked -> review

        monkeypatch.setattr(settings, "storage_root", tmp_path)
        monkeypatch.setattr(settings, "insurance_fx_provider", "india_official")
        monkeypatch.setattr(insurance_fx_provider, "_NBP_USD_MEMO", {},
                            raising=False)
        monkeypatch.setattr(india_official_fx, "resolve_for_invoice_date",
                            self._india)
        monkeypatch.setattr(nbp_rate_service, "fetch_rate", self._nbp)
        monkeypatch.setattr(ies, "load_ar_fact_universe",
                            lambda df, dt, force=False: {"invoice_facts": list(self.facts)})
        monkeypatch.setattr(ies, "get_draft_by_wfirma_invoice_id",
                            lambda db, i: self.drafts.get(str(i)))
        monkeypatch.setattr(ies, "get_document_charges",
                            lambda i, path=None: self.invoiced.get(str(i)))
        monkeypatch.setattr(ies, "_batch_client_count", lambda db, b: 1)
        monkeypatch.setattr(ies, "shipment_db", SimpleNamespace(
            get_shipment_for_draft=lambda *a, **k: {"tracking_ref": "111",
                                                    "mode": "dhl"}))
        # The real provider boundary — the point of the file.
        monkeypatch.setattr(ies, "insurance_fx_provider", insurance_fx_provider)

    @staticmethod
    def _india(currency, invoice_date):
        rate = {"USD": INR_PER_USD, "EUR": INR_PER_EUR}.get(currency)
        if rate is None:
            raise insurance_fx_provider.InsuranceFxError(
                "no official quote for %s" % currency)
        return {"currency": currency, "rate": rate,
                "requested_date": "2026-08-13", "effective_date": "2026-08-13",
                "staleness_days": 1, "quote_unit": 1, "rate_as_published": rate,
                "source": "rbi_reference_rate_archive"}

    @staticmethod
    def _nbp(currency, accounting_date):
        return {"rate": float(PLN_PER_USD), "source": "NBP",
                "table_number": "153/A/NBP/2026", "table_date": "2026-08-13",
                "accounting_date": accounting_date, "currency": currency}


@pytest.fixture
def report(monkeypatch, tmp_path):
    Universe(monkeypatch, tmp_path)
    return assemble_insurance_export_report(PERIOD[0], PERIOD[1],
                                            db_path=DB, carrier_db_path=CDB)


def _all_rows(report):
    """Every row that can carry a status or a number, in one list."""
    out = []
    for grp in report["contractors"]:
        for row in grp["rows"]:
            out.append(row)
            out.extend(row["adjustments"])
        out.extend(grp["unattached_adjustments"])
    return out


def _d(value):
    return Decimal(value)


def test_the_universe_actually_exercises_every_branch(report):
    """Guard on the fixture itself: a contract proved over an empty or
    single-shape report proves nothing."""
    rows = _all_rows(report)
    assert len(rows) == 6
    assert {r["currency"] for r in rows} == {"USD", "EUR", "PLN", "GBP"}
    assert any(r["status"] == InsuranceStatus.NEEDS_REVIEW for r in rows)
    assert any(r["status"] == InsuranceStatus.INCLUDED for r in rows)
    assert any(r["fx_rate"] is None for r in rows)          # the GBP gap
    assert any(r["charge_authority_on_record"] is False for r in rows)


# ── 1. needs_review implies a reason, everywhere ─────────────────────────────


def test_no_row_anywhere_reaches_needs_review_without_a_reason(report):
    """The defect the operator saw: a bare 'Needs review' chip.

    It is a report-wide contract, not a row-level one — corrections reach the
    state through a different branch than invoices do.
    """
    for row in _all_rows(report):
        if row["status"] != InsuranceStatus.NEEDS_REVIEW:
            continue
        reason = row.get("recommendation_reason")
        assert reason and reason.strip(), (
            "%s is needs_review with no reason" % row["fullnumber"])


def test_the_kpi_review_count_matches_the_rows_carrying_reasons(report):
    """A review counted in the KPI but not visible on a row is a hidden
    blocker; the two must be the same population."""
    reviewed = [r for r in _all_rows(report)
                if r["status"] == InsuranceStatus.NEEDS_REVIEW]
    assert report["kpi"]["needs_review"] == len(reviewed)
    assert all(r["recommendation_reason"] for r in reviewed)


# ── 2 + 3. the display rate is a view, never an input ────────────────────────


def test_every_rated_row_carries_a_four_decimal_display_rate(report):
    for row in _all_rows(report):
        if row["fx_rate"] is None:
            assert row["fx_rate_display"] is None
            continue
        shown = row["fx_rate_display"]
        assert shown is not None, row["fullnumber"]
        assert len(shown.split(".")[1]) == 4, shown
        assert _d(shown) == _d(row["fx_rate"]).quantize(ies.FX_DISPLAY_EXP)


def test_the_pln_row_still_proves_the_two_precisions_differ(report):
    """Without a rate that does not terminate, contract 3 below is vacuous."""
    pln = [r for r in _all_rows(report) if r["currency"] == "PLN"][0]
    assert len(pln["fx_rate"].split(".")[1]) > 4
    assert _d(pln["fx_rate"]) != _d(pln["fx_rate_display"])
    assert pln["fx_rate_display"] == str(INR_PER_PLN.quantize(ies.FX_DISPLAY_EXP))


def test_no_inr_value_in_the_report_is_derivable_from_the_display_rate(report):
    """Every INR figure comes from the full rate. On the PLN row the two
    products differ, so this is a real discriminator and not a tautology."""
    discriminated = False
    for row in _all_rows(report):
        if row["fx_rate"] is None:
            assert row["sum_insured_inr"] is None      # a gap, never a zero
            continue
        base = _d(row["sum_insured"])
        from_full = ies._money(base * _d(row["fx_rate"]))
        from_display = ies._money(base * _d(row["fx_rate_display"]))
        assert row["sum_insured_inr"] == from_full, row["fullnumber"]
        discriminated = discriminated or from_full != from_display
    assert discriminated, "no row distinguishes the two precisions"


# ── 4. one number, printed four ways ─────────────────────────────────────────


def test_group_subtotals_sum_to_the_report_totals_and_the_kpi(report):
    """Rows -> contractor subtotal -> report total -> KPI.

    Contractor grouping partitions every row exactly once (an adjustment sits
    under its parent's group or, unattached, under its own), so the sums must
    be identical at all four levels. A future grouping change that drops or
    double-counts a row fails here.
    """
    groups = report["contractors"]
    totals = report["report_totals"]
    kpi = report["kpi"]

    docs_from_rows = sum(
        (_d(r["sum_insured_inr"]) for g in groups for r in g["rows"]
         if r["sum_insured_inr"]), Decimal("0"))
    docs_from_groups = sum(
        (_d(g["subtotals"]["sum_insured_inr_documents"]) for g in groups),
        Decimal("0"))

    assert docs_from_rows == docs_from_groups
    assert str(docs_from_groups) == totals["sum_insured_inr_documents"]
    assert kpi["gross_insured_inr"] == totals["sum_insured_inr_documents"]

    adj_from_groups = sum(
        (_d(g["subtotals"]["sum_insured_inr_adjustments"]) for g in groups),
        Decimal("0"))
    assert str(adj_from_groups) == totals["sum_insured_inr_adjustments"]

    grand_from_groups = sum(
        (_d(g["subtotals"]["sum_insured_inr"]) for g in groups), Decimal("0"))
    assert str(grand_from_groups) == totals["sum_insured_inr_grand"]
    assert kpi["net_insured_inr"] == totals["sum_insured_inr_grand"]


def test_a_missing_rate_is_disclosed_and_never_folded_in_as_zero(report):
    """The GBP row cannot be converted. It must be COUNTED as missing, not
    quietly contribute 0.00 to a total that then looks complete."""
    assert report["report_totals"]["rows_without_inr"] == 1
    unrated = [r for r in _all_rows(report) if r["sum_insured_inr"] is None]
    assert len(unrated) == 1
    assert unrated[0]["currency"] == "GBP"
    assert unrated[0]["status"] == InsuranceStatus.NEEDS_REVIEW


def test_rows_without_authority_counts_exactly_the_unconverged_rows(report):
    """A recorded 0.00 is an answer; no record at all is a question. Only the
    second may be counted, or the recovered total silently understates."""
    unconverged = [r for r in _all_rows(report)
                   if not r["charge_authority_on_record"]]
    assert [r["fullnumber"] for r in unconverged] == ["WDT 156/2026"]
    assert report["kpi"]["insurance_recovered_rows_without_authority"] == 1
    assert sum(g["subtotals"]["insurance_recovered_rows_without_authority"]
               for g in report["contractors"]) == 1


def test_the_recovered_total_is_per_currency_and_never_summed_across(report):
    """Recovered premiums are billed in the document's own currency; adding
    EUR to USD would invent a number no document supports."""
    recovered = report["kpi"]["insurance_recovered"]
    assert recovered == {"EUR": "0.00", "GBP": "12.00", "PLN": "41.20",
                         "USD": "56.98"}
