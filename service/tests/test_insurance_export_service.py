"""Insurance Export Statement — service unit tests.

Covers row math + quantization, FX provenance and degradation, the
recommendation engine (evidence-based, never country-based), insurance
recovered read-verbatim semantics, correction correlation, grouping,
and error mapping.

Strategy: patch the five authority imports on the service module itself
(``insurance_export_statement`` imported them by name), keep
``resolve_commercial_charges`` REAL so the persisted-charge semantics are
exercised end-to-end.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.services.insurance_export_statement as ies
from app.services.insurance_export_statement import (
    InsuranceExportFetchError,
    InsuranceRecommendation,
    InsuranceStatus,
    UnknownSelectionError,
    assemble_insurance_export_report,
)
from app.services.nbp_rate_service import NbpRateError

DB = Path("unused-proforma.db")
CDB = Path("unused-carrier.db")

PERIOD = ("2026-05-01", "2026-05-31")


# ── Fixture harness ──────────────────────────────────────────────────────


def _fact(
    inv_id,
    *,
    fullnumber="FV 1/2026",
    type_="normal",
    date="2026-05-10",
    currency="USD",
    brutto="2600.00",
    contractor_id="C-1",
    contractor_name="Alpha Exports Ltd",
):
    return {
        "id": inv_id,
        "fullnumber": fullnumber,
        "type": type_,
        "date": date,
        "paymentdate": "",
        "currency": currency,
        "netto": None,
        "brutto": brutto,
        "contractor_id": contractor_id,
        "contractor_name": contractor_name,
    }


def _draft(
    draft_id=7,
    batch_id="BATCH-1",
    client_name="Alpha Exports Ltd",
    currency="USD",
    charges=None,
):
    return SimpleNamespace(
        id=draft_id,
        batch_id=batch_id,
        client_name=client_name,
        currency=currency,
        service_charges_json=json.dumps(charges if charges is not None else []),
    )


class Harness:
    """Stub the five authorities on the service module."""

    def __init__(self, monkeypatch):
        self.facts = []
        self.drafts = {}       # invoice_id (str) -> draft namespace
        self.shipments = {}    # batch_id -> shipment dict
        self.rates = {"INR": 0.05}   # ccy -> PLN-per-unit float | Exception
        self.correction_xml = {}     # invoice_id (str) -> xml text | Exception
        monkeypatch.setattr(
            ies,
            "load_ar_fact_universe",
            lambda df, dt, force=False: {"invoice_facts": list(self.facts)},
        )
        monkeypatch.setattr(
            ies,
            "get_draft_by_wfirma_invoice_id",
            lambda db, inv_id: self.drafts.get(str(inv_id)),
        )
        monkeypatch.setattr(ies, "_batch_client_count", lambda db, batch: 1)
        monkeypatch.setattr(
            ies,
            "shipment_db",
            SimpleNamespace(get_shipment_for_draft=self._get_shipment),
        )
        monkeypatch.setattr(
            ies,
            "nbp_rate_service",
            SimpleNamespace(fetch_rate=self._fetch_rate),
        )
        monkeypatch.setattr(
            ies,
            "wfirma_client",
            SimpleNamespace(fetch_invoice_xml=self._fetch_xml),
        )

    def _get_shipment(self, cdb, batch, client, allow_single_client_fallback=False):
        return self.shipments.get(batch)

    def _fetch_rate(self, currency, date):
        val = self.rates.get(currency)
        if val is None:
            raise NbpRateError(
                "unsupported_currency", "no NBP Table A rate for %s" % currency
            )
        if isinstance(val, Exception):
            raise val
        return {
            "rate": val,
            "source": "stub",
            "table_number": "090/A/NBP/2026",
            "table_date": "2026-05-09",
            "accounting_date": date,
            "currency": currency,
        }

    def _fetch_xml(self, invoice_id):
        val = self.correction_xml.get(str(invoice_id))
        if val is None:
            raise RuntimeError("unexpected fetch_invoice_xml(%s)" % invoice_id)
        if isinstance(val, Exception):
            raise val
        return val


@pytest.fixture()
def h(monkeypatch):
    return Harness(monkeypatch)


def _assemble():
    return assemble_insurance_export_report(
        PERIOD[0], PERIOD[1], db_path=DB, carrier_db_path=CDB
    )


def _all_rows(report):
    rows = []
    for grp in report["contractors"]:
        rows.extend(grp["rows"])
    return rows


def _only_row(report):
    rows = _all_rows(report)
    assert len(rows) == 1
    return rows[0]


INSURANCE_45_67 = {
    "charge_type": "insurance",
    "resolution": "manual_amount",
    "amount": 45.67,
    "currency": "USD",
}
AWB_SHIPMENT = {"tracking_ref": "1234567890", "mode": "dhl"}


# ── Row math + FX ────────────────────────────────────────────────────────


def test_row_math_quantization(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = 4.423373

    row = _only_row(_assemble())
    assert row["inv_cif"] == "2600.00"
    assert row["plus_10_pct"] == "260.00"
    assert row["sum_insured"] == "2860.00"
    assert row["fx_rate"] == "88.467460"
    assert row["sum_insured_inr"] == "253016.94"
    assert row["currency"] == "USD"
    assert row["status"] == InsuranceStatus.INCLUDED
    assert row["recommendation"] == InsuranceRecommendation.INCLUDE
    assert row["awb"] == "1234567890"


def test_fx_provenance_fields(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = 4.423373

    row = _only_row(_assemble())
    prov = row["fx_provenance"]
    assert prov["nbp_table_ccy"] == "090/A/NBP/2026"
    assert prov["nbp_table_inr"] == "090/A/NBP/2026"
    assert prov["nbp_date_used"] == "2026-05-09"
    assert row["fx_error"] is None


def test_pln_identity_leg_and_blank_currency(h):
    # Blank currency defaults to PLN; PLN leg is the NBP identity 1.0.
    h.facts = [_fact("101", currency="", brutto="100.00")]
    h.drafts["101"] = _draft(currency="PLN", charges=[INSURANCE_45_67])
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["PLN"] = 1.0

    row = _only_row(_assemble())
    assert row["currency"] == "PLN"
    assert row["fx_rate"] == "20.000000"      # 1.0 / 0.05
    assert row["sum_insured"] == "110.00"
    assert row["sum_insured_inr"] == "2200.00"


def test_fx_missing_degrades_row_never_raises(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = NbpRateError("upstream", "NBP api.nbp.pl unreachable")

    report = _assemble()
    row = _only_row(report)
    assert row["fx_rate"] is None
    assert row["sum_insured_inr"] is None
    assert row["fx_error"].startswith("upstream:")
    assert row["status"] == InsuranceStatus.NEEDS_REVIEW
    assert row["recommendation"] == InsuranceRecommendation.REVIEW
    # Degraded row is excluded from INR totals but counted as missing.
    assert report["report_totals"]["sum_insured_inr_documents"] == "0.00"
    assert report["report_totals"]["rows_without_inr"] == 1
    # CIF-side columns still render (only the INR leg is lost).
    assert row["sum_insured"] == "2860.00"


# ── Recommendation engine (evidence-based, never country-based) ─────────


def test_recommendation_no_country_based_pickup(h):
    # A Polish-named contractor with real shipment evidence must be
    # recommend_include — pickup exclusion is charge-evidence only.
    h.facts = [
        _fact(
            "101",
            contractor_id="C-PL",
            contractor_name="Polski Klient Sp. z o.o.",
        )
    ]
    h.drafts["101"] = _draft(client_name="Polski Klient Sp. z o.o.",
                             charges=[INSURANCE_45_67])
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = 4.423373

    row = _only_row(_assemble())
    assert row["recommendation"] == InsuranceRecommendation.INCLUDE
    assert row["status"] == InsuranceStatus.INCLUDED
    assert row["status"] != InsuranceStatus.PERSONAL_PICKUP


def test_pickup_excluded_on_customer_courier_freight(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(
        charges=[
            {"charge_type": "freight", "resolution": "customer_courier", "amount": 0}
        ]
    )
    h.rates["USD"] = 4.423373

    row = _only_row(_assemble())
    assert row["status"] == InsuranceStatus.PERSONAL_PICKUP
    assert row["recommendation"] == InsuranceRecommendation.EXCLUDE
    assert "customer courier" in row["recommendation_reason"]
    # Excluded-by-recommendation rows still carry their INR value — the
    # operator decides; totals math is selection-driven, not status-driven.
    assert row["sum_insured_inr"] is not None


def test_zero_value_document_is_cancellation(h):
    h.facts = [_fact("101", brutto="0.00")]
    h.drafts["101"] = _draft(
        charges=[
            {"charge_type": "freight", "resolution": "customer_courier", "amount": 0}
        ]
    )
    h.rates["USD"] = 4.423373

    row = _only_row(_assemble())
    # Cancellation wins even over pickup evidence.
    assert row["status"] == InsuranceStatus.CANCELLED
    assert row["recommendation"] == InsuranceRecommendation.EXCLUDE


def test_no_draft_needs_review(h):
    h.facts = [_fact("101")]
    h.rates["USD"] = 4.423373

    row = _only_row(_assemble())
    assert row["status"] == InsuranceStatus.NEEDS_REVIEW
    assert row["recommendation"] == InsuranceRecommendation.REVIEW
    assert row["recommendation_reason"] == "No proforma draft linked to this invoice"
    assert row["draft_id"] is None


def test_draft_without_shipment_needs_review(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.rates["USD"] = 4.423373

    row = _only_row(_assemble())
    assert row["shipment_found"] is False
    assert row["recommendation"] == InsuranceRecommendation.REVIEW
    assert row["recommendation_reason"] == "Draft linked but no shipment record found"


def test_shipment_without_awb_needs_review(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.shipments["BATCH-1"] = {"tracking_ref": "", "mode": "dhl"}
    h.rates["USD"] = 4.423373

    row = _only_row(_assemble())
    assert row["shipment_found"] is True
    assert row["awb"] in (None, "")
    assert row["recommendation"] == InsuranceRecommendation.REVIEW
    assert row["recommendation_reason"] == "Shipment record has no AWB"


def test_external_shipment_mode_recommends_include(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.shipments["BATCH-1"] = {"tracking_ref": "", "mode": "external"}
    h.rates["USD"] = 4.423373

    row = _only_row(_assemble())
    assert row["recommendation"] == InsuranceRecommendation.INCLUDE
    assert row["recommendation_reason"] == "External shipment recorded"
    assert row["status"] == InsuranceStatus.INCLUDED


# ── Insurance recovered — verbatim from charge authority ────────────────


def test_recovered_verbatim_manual_amount(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = 4.423373

    row = _only_row(_assemble())
    assert row["insurance_recovered"] == {
        "amount": "45.67",
        "currency": "USD",
        "resolution": "manual_amount",
    }
    assert row["status"] == InsuranceStatus.INCLUDED


def test_waived_insurance_is_no_premium_advisory(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(
        charges=[{"charge_type": "insurance", "resolution": "waived", "amount": 0}]
    )
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = 4.423373

    row = _only_row(_assemble())
    rec = row["insurance_recovered"]
    assert rec["resolution"] == "waived"
    assert rec["amount"] == "0.00"
    assert row["status"] == InsuranceStatus.NO_INSURANCE_CHARGED
    # Advisory only — the recommendation still follows shipment evidence.
    assert row["recommendation"] == InsuranceRecommendation.INCLUDE


def test_unresolved_insurance_is_no_premium(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(
        charges=[
            {"charge_type": "insurance", "resolution": "unresolved", "amount": 12.0}
        ]
    )
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = 4.423373

    row = _only_row(_assemble())
    assert row["insurance_recovered"]["resolution"] == "unresolved"
    assert row["status"] == InsuranceStatus.NO_INSURANCE_CHARGED


def test_recovered_totals_are_per_currency_never_summed(h):
    h.facts = [
        _fact("101"),
        _fact(
            "102",
            fullnumber="FV 2/2026",
            currency="EUR",
            brutto="1000.00",
            contractor_id="C-2",
            contractor_name="Beta Trading GmbH",
        ),
    ]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.drafts["102"] = _draft(
        draft_id=8,
        batch_id="BATCH-2",
        client_name="Beta Trading GmbH",
        currency="EUR",
        charges=[
            {
                "charge_type": "insurance",
                "resolution": "manual_amount",
                "amount": 30.0,
                "currency": "EUR",
            }
        ],
    )
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.shipments["BATCH-2"] = {"tracking_ref": "999", "mode": "dhl"}
    h.rates["USD"] = 4.423373
    h.rates["EUR"] = 4.9691

    report = _assemble()
    assert report["report_totals"]["insurance_recovered"] == {
        "EUR": "30.00",
        "USD": "45.67",
    }


# ── Correction correlation ───────────────────────────────────────────────


def _correction_fixture(h, *, xml=None, corr_fullnumber="KOR 1/2026"):
    h.facts = [
        _fact("101"),
        _fact(
            "201",
            fullnumber=corr_fullnumber,
            type_="correction",
            date="2026-05-20",
            brutto="-500.00",
        ),
    ]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.drafts["201"] = _draft(draft_id=9, batch_id="BATCH-9", charges=[])
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.shipments["BATCH-9"] = {"tracking_ref": "222", "mode": "dhl"}
    h.rates["USD"] = 4.423373
    if xml is not None:
        h.correction_xml["201"] = xml


def test_correction_parent_tag_confirmed_nests_as_return(h):
    _correction_fixture(
        h,
        xml=(
            "<api><invoices><invoice>"
            "<invoicecorrection><invoice><id>101</id></invoice></invoicecorrection>"
            "</invoice></invoices></api>"
        ),
    )
    report = _assemble()
    groups = report["contractors"]
    assert len(groups) == 1
    parent = groups[0]["rows"][0]
    assert parent["invoice_id"] == "101"
    assert len(parent["adjustments"]) == 1
    adj = parent["adjustments"][0]
    assert adj["parent_invoice_id"] == "101"
    assert adj["parent_confirmed"] is True
    assert adj["correlation_method"] == "parent_tag"
    assert adj["status"] == InsuranceStatus.RETURN
    assert adj["sum_insured_inr"] == "-48657.10"
    assert groups[0]["unattached_adjustments"] == []
    assert report["report_totals"]["adjustments"] == 1


def test_correction_number_pattern_is_needs_review_unattached(h):
    _correction_fixture(
        h,
        xml="<api><invoices><invoice><id>201</id></invoice></invoices></api>",
        corr_fullnumber="KOR FV 1/2026",
    )
    report = _assemble()
    grp = report["contractors"][0]
    assert grp["rows"][0]["adjustments"] == []
    assert len(grp["unattached_adjustments"]) == 1
    adj = grp["unattached_adjustments"][0]
    assert adj["correlation_method"] == "parent_inferred_by_number_pattern"
    assert adj["parent_confirmed"] is False
    assert adj["status"] == InsuranceStatus.NEEDS_REVIEW
    assert adj["recommendation"] == InsuranceRecommendation.REVIEW
    assert (
        adj["recommendation_reason"]
        == "Correction parent could not be confirmed (parent_inferred_by_number_pattern)"
    )


def test_correction_fetch_failure_degrades_that_row_only(h):
    _correction_fixture(h)
    h.correction_xml["201"] = RuntimeError("wFirma 500")

    report = _assemble()
    grp = report["contractors"][0]
    # Parent row is untouched.
    assert grp["rows"][0]["status"] == InsuranceStatus.INCLUDED
    adj = grp["unattached_adjustments"][0]
    assert adj["correlation_method"] == "fetch_failed"
    assert adj["correlation_error"] == "wFirma 500"
    assert adj["status"] == InsuranceStatus.NEEDS_REVIEW


# ── Grouping + totals ────────────────────────────────────────────────────


def test_groups_sorted_by_contractor_name(h):
    h.facts = [
        _fact("102", contractor_id="C-2", contractor_name="Zeta Ltd"),
        _fact("101", contractor_id="C-1", contractor_name="Alpha Exports Ltd"),
    ]
    h.rates["USD"] = 4.423373

    report = _assemble()
    names = [g["contractor_name"] for g in report["contractors"]]
    assert names == ["Alpha Exports Ltd", "Zeta Ltd"]
    # Group subtotals sum to the grand total.
    total = sum(
        Decimal(g["subtotals"]["sum_insured_inr"]) for g in report["contractors"]
    )
    assert str(total.quantize(Decimal("0.01"))) == report["report_totals"][
        "sum_insured_inr_grand"
    ]


# ── Error mapping ────────────────────────────────────────────────────────


def test_universe_failure_maps_to_fetch_error(h, monkeypatch):
    def _boom(df, dt, force=False):
        raise RuntimeError("wFirma unreachable")

    monkeypatch.setattr(ies, "load_ar_fact_universe", _boom)
    with pytest.raises(InsuranceExportFetchError):
        _assemble()


def test_universe_valueerror_also_maps_to_fetch_error(h, monkeypatch):
    # Regression: wfirma_client raises a plain ValueError when credentials
    # are not configured; it must map to the route's 502, never escape as
    # a 500. Date validation lives in the route (400), not here.
    def _bad(df, dt, force=False):
        raise ValueError(
            "wFirma API Key credentials not configured "
            "(WFIRMA_ACCESS_KEY / WFIRMA_SECRET_KEY / WFIRMA_APP_KEY)"
        )

    monkeypatch.setattr(ies, "load_ar_fact_universe", _bad)
    with pytest.raises(InsuranceExportFetchError):
        _assemble()


def test_unknown_selection_error_dedupes_and_sorts():
    exc = UnknownSelectionError(["b", "a", "b"])
    assert exc.unknown == ["a", "b"]
    assert "unknown selection ids" in str(exc)
