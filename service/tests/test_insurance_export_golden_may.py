"""Insurance Export Statement — golden May-style fixture.

Exercises the REAL ``load_ar_fact_universe`` pipeline (wFirma XML envelopes
via a stubbed ``_http_request``) end-to-end through
``assemble_insurance_export_report`` and pins the four contractor-group INR
subtotals plus the 646,849.80 grand total.

FX legs are stubbed operator-approved insurance rates (the ONLY FX authority
per the fail-closed ``insurance_fx_provider`` boundary — Blocker 1). Rates are
chosen to match the terminating cross-rates the old NBP-hub fixture used, so
each group total still lands exactly after 0.01-quantization.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import app.services.insurance_export_statement as ies
import app.services.wfirma_client as wfirma_client
from app.services.insurance_export_statement import (
    assemble_insurance_export_report,
)
from app.services.insurance_fx_provider import InsuranceFxError
from app.services.ledger_fact_universe import clear_fact_universe_cache

DB = Path("unused-proforma.db")
CDB = Path("unused-carrier.db")

# Operator-approved insurance INR rates (INR per 1 unit of currency).
RATES = {
    "USD": "88.467460",
    "EUR": "99.382000",
    "GBP": "85.293000",
    "CHF": "83.660466",
}

EXPECTED_SUBTOTALS = {
    "Alpha Exports Ltd": "253016.94",   # USD 2600.00
    "Beta Trading GmbH": "273300.50",   # EUR 2500.00
    "Gamma Imports": "46911.15",        # GBP  500.00
    "Delta Watch Co": "73621.21",       # CHF  800.00
}
EXPECTED_GRAND = "646849.80"


def _invoice_xml(inv_id, fullnumber, currency, brutto, c_id, c_name):
    return (
        "<invoice>"
        "<id>%s</id>"
        "<fullnumber>%s</fullnumber>"
        "<type>normal</type>"
        "<date>2026-05-12</date>"
        "<currency>%s</currency>"
        "<netto>%s</netto>"
        "<brutto>%s</brutto>"
        "<contractor><id>%s</id><name>%s</name></contractor>"
        "</invoice>"
    ) % (inv_id, fullnumber, currency, brutto, brutto, c_id, c_name)


def _envelope(invoices_xml=""):
    return (
        '<?xml version="1.0"?>'
        "<api>"
        "<invoices>%s</invoices>"
        "<status><code>OK</code><description>OK</description></status>"
        "</api>"
    ) % invoices_xml


def _paginator_stub(pages):
    iterator = iter(pages)

    def _fn(method, module, action, body=""):
        try:
            return 200, next(iterator)
        except StopIteration:
            return 200, _envelope("")

    return _fn


@pytest.fixture(autouse=True)
def _fresh_universe_cache():
    clear_fact_universe_cache()
    yield
    clear_fact_universe_cache()


@pytest.fixture()
def golden(monkeypatch):
    invoices = "".join(
        [
            _invoice_xml("1", "FV 1/2026", "USD", "2600.00", "C-1",
                         "Alpha Exports Ltd"),
            _invoice_xml("2", "FV 2/2026", "EUR", "2500.00", "C-2",
                         "Beta Trading GmbH"),
            _invoice_xml("3", "FV 3/2026", "GBP", "500.00", "C-3",
                         "Gamma Imports"),
            _invoice_xml("4", "FV 4/2026", "CHF", "800.00", "C-4",
                         "Delta Watch Co"),
        ]
    )
    monkeypatch.setattr(
        wfirma_client, "_http_request", _paginator_stub([_envelope(invoices)])
    )
    # No drafts linked — rows degrade to needs_review advisories but keep
    # full INR math (the golden check is the arithmetic, not the linkage).
    monkeypatch.setattr(ies, "get_draft_by_wfirma_invoice_id", lambda db, i: None)

    def _get_rate(currency, invoice_date):
        val = RATES.get(currency)
        if val is None:
            raise InsuranceFxError("no operator-approved rate for %s" % currency)
        return {
            "requested_date": invoice_date,
            "effective_date": invoice_date,
            "currency": currency,
            "rate": val,
            "source": "operator_fixed",
        }

    monkeypatch.setattr(
        ies, "insurance_fx_provider", SimpleNamespace(get_rate=_get_rate)
    )
    return None


def _assemble():
    return assemble_insurance_export_report(
        "2026-05-01", "2026-05-31", db_path=DB, carrier_db_path=CDB
    )


def test_golden_group_subtotals_and_grand_total(golden):
    report = _assemble()

    by_name = {
        g["contractor_name"]: g["subtotals"] for g in report["contractors"]
    }
    assert set(by_name) == set(EXPECTED_SUBTOTALS)
    for name, expected in EXPECTED_SUBTOTALS.items():
        assert by_name[name]["sum_insured_inr"] == expected, name
        assert by_name[name]["documents"] == 1
        assert by_name[name]["adjustments"] == 0

    totals = report["report_totals"]
    assert totals["sum_insured_inr_documents"] == EXPECTED_GRAND
    assert totals["sum_insured_inr_adjustments"] == "0.00"
    assert totals["sum_insured_inr_grand"] == EXPECTED_GRAND
    assert totals["documents"] == 4
    assert totals["adjustments"] == 0
    assert totals["rows_without_inr"] == 0


def test_golden_group_order_and_kpi(golden):
    report = _assemble()
    names = [g["contractor_name"] for g in report["contractors"]]
    assert names == [
        "Alpha Exports Ltd",
        "Beta Trading GmbH",
        "Delta Watch Co",
        "Gamma Imports",
    ]
    kpi = report["kpi"]
    assert kpi["invoices"] == 4
    assert kpi["adjustments"] == 0
    assert kpi["gross_insured_inr"] == EXPECTED_GRAND
    assert kpi["net_insured_inr"] == EXPECTED_GRAND
    # No drafts in the golden fixture → every row is a review advisory.
    assert kpi["needs_review"] == 4
    assert report["period"] == {"from": "2026-05-01", "to": "2026-05-31"}


def test_golden_row_math_sample(golden):
    report = _assemble()
    alpha = [
        g for g in report["contractors"]
        if g["contractor_name"] == "Alpha Exports Ltd"
    ][0]
    row = alpha["rows"][0]
    assert row["inv_cif"] == "2600.00"
    assert row["plus_10_pct"] == "260.00"
    assert row["sum_insured"] == "2860.00"
    assert row["fx_rate"] == "88.467460"
    assert row["sum_insured_inr"] == "253016.94"
    assert row["fx_provenance"]["source"] == "operator_fixed"
