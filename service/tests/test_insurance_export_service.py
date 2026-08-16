"""Insurance Export Statement — service unit tests.

Covers row math + quantization, FX provenance and degradation, the
recommendation engine (evidence-based, never country-based), insurance
recovered read-verbatim semantics, correction correlation, grouping,
and error mapping.

Strategy: patch the authority imports on the service module itself
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
    CorrectionReason,
    InsuranceEffect,
    InsuranceExportFetchError,
    InsuranceRecommendation,
    InsuranceStatus,
    UnknownSelectionError,
    assemble_insurance_export_report,
    classify_correction,
)
from app.services.insurance_fx_provider import InsuranceFxError

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
        self.invoiced = {}     # invoice_id (str) -> issued-document charge rows
        self.shipments = {}    # batch_id -> shipment dict
        self.rates = {}   # ccy -> operator-approved INR-per-unit str/float | Exception
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
        monkeypatch.setattr(
            ies,
            "get_document_charges",
            lambda inv_id, path=None: self.invoiced.get(str(inv_id)),
        )
        monkeypatch.setattr(ies, "_batch_client_count", lambda db, batch: 1)
        monkeypatch.setattr(
            ies,
            "shipment_db",
            SimpleNamespace(get_shipment_for_draft=self._get_shipment),
        )
        monkeypatch.setattr(
            ies,
            "insurance_fx_provider",
            SimpleNamespace(get_rate=self._get_rate),
        )
        monkeypatch.setattr(
            ies,
            "wfirma_client",
            SimpleNamespace(fetch_invoice_xml=self._fetch_xml),
        )

    def _get_shipment(self, cdb, batch, client, allow_single_client_fallback=False):
        return self.shipments.get(batch)

    def _get_rate(self, currency, invoice_date):
        val = self.rates.get(currency)
        if val is None:
            raise InsuranceFxError("no operator-approved rate for %s" % currency)
        if isinstance(val, Exception):
            raise val
        return {
            "requested_date": invoice_date,
            "effective_date": invoice_date,
            "currency": currency,
            "rate": val,
            "source": "operator_fixed",
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


def _invoiced(amount="45.67", currency="USD", conflict=""):
    """What the ISSUED document billed — the recovered-premium authority.

    Shaped exactly like ``commercial_charge_record_db.get_document_charges``.
    A converged document that billed nothing carries an explicit ``0.00`` row;
    an UNCONVERGED document has no entry at all (``None``), which is an
    unknown, not a zero.
    """
    return [
        {
            "charge_type": "insurance",
            "amount": amount,
            "currency": currency,
            "resolution": "invoiced",
            "conflict_state": conflict,
        }
    ]


# ── Row math + FX ────────────────────────────────────────────────────────


def test_row_math_quantization(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.invoiced["101"] = _invoiced()
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = "88.467460"

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


def test_wdt89_precision_never_double_rounds(h):
    """Blocker 2: CIF x 1.10 must never be quantized before the FX multiply.

    WDT 89/2026, CIF 723.55 USD: raw chain 723.55 x 1.10 x 92.50 =
    73621.2125 -> quantized once, at serialization, to 73621.21. Rounding
    the +10% leg to 2dp FIRST (795.91) and then multiplying by FX gives
    795.91 x 92.50 = 73621.675 -> 73621.68 — the wrong, double-rounded
    value this test pins against. The display-only plus_10_pct/sum_insured
    strings are still shown rounded (72.36 / 795.91); only the INR leg must
    carry the raw, unrounded intermediate value forward.
    """
    h.facts = [_fact("89", brutto="723.55")]
    h.drafts["89"] = _draft(charges=[INSURANCE_45_67])
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = "92.500000"

    row = _only_row(_assemble())
    assert row["inv_cif"] == "723.55"
    assert row["plus_10_pct"] == "72.36"
    assert row["sum_insured"] == "795.91"
    assert row["sum_insured_inr"] == "73621.21"
    assert row["sum_insured_inr"] != "73621.68"


def test_fx_provenance_fields(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = "88.467460"

    row = _only_row(_assemble())
    prov = row["fx_provenance"]
    assert prov["source"] == "operator_fixed"
    assert prov["requested_date"] == "2026-05-10"
    assert prov["effective_date"] == "2026-05-10"
    assert row["fx_error"] is None


def test_blank_currency_defaults_to_pln(h):
    h.facts = [_fact("101", currency="", brutto="100.00")]
    h.drafts["101"] = _draft(currency="PLN", charges=[INSURANCE_45_67])
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["PLN"] = "20.000000"

    row = _only_row(_assemble())
    assert row["currency"] == "PLN"
    assert row["fx_rate"] == "20.000000"
    assert row["sum_insured"] == "110.00"
    assert row["sum_insured_inr"] == "2200.00"


def test_fx_missing_degrades_row_never_raises(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = InsuranceFxError("upstream: insurance FX provider unreachable")

    report = _assemble()
    row = _only_row(report)
    assert row["fx_rate"] is None
    assert row["sum_insured_inr"] is None
    # The taxonomy kind prefixes the message so the row discloses WHY the
    # rate is missing; a missing rate is never rendered as zero.
    assert row["fx_error"] == "provider_error: upstream: insurance FX provider unreachable"
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
    h.invoiced["101"] = _invoiced()
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = "88.467460"

    row = _only_row(_assemble())
    assert row["recommendation"] == InsuranceRecommendation.INCLUDE
    assert row["status"] == InsuranceStatus.INCLUDED
    assert row["status"] != InsuranceStatus.CUSTOMER_TRANSPORT


def test_pickup_excluded_on_customer_courier_freight(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(
        charges=[
            {"charge_type": "freight", "resolution": "customer_courier", "amount": 0}
        ]
    )
    h.rates["USD"] = "88.467460"

    row = _only_row(_assemble())
    assert row["status"] == InsuranceStatus.CUSTOMER_TRANSPORT
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
    h.rates["USD"] = "88.467460"

    row = _only_row(_assemble())
    # Cancellation wins even over pickup evidence.
    assert row["status"] == InsuranceStatus.CANCELLED
    assert row["recommendation"] == InsuranceRecommendation.EXCLUDE


def test_no_draft_needs_review(h):
    h.facts = [_fact("101")]
    h.rates["USD"] = "88.467460"

    row = _only_row(_assemble())
    assert row["status"] == InsuranceStatus.NEEDS_REVIEW
    assert row["recommendation"] == InsuranceRecommendation.REVIEW
    assert row["recommendation_reason"] == "No proforma draft linked to this invoice"
    assert row["draft_id"] is None


def test_draft_without_shipment_needs_review(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.rates["USD"] = "88.467460"

    row = _only_row(_assemble())
    assert row["shipment_found"] is False
    assert row["recommendation"] == InsuranceRecommendation.REVIEW
    assert row["recommendation_reason"] == "Draft linked but no shipment record found"


def test_shipment_without_awb_needs_review(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.shipments["BATCH-1"] = {"tracking_ref": "", "mode": "dhl"}
    h.rates["USD"] = "88.467460"

    row = _only_row(_assemble())
    assert row["shipment_found"] is True
    assert row["awb"] in (None, "")
    assert row["recommendation"] == InsuranceRecommendation.REVIEW
    assert row["recommendation_reason"] == "Shipment record has no AWB"


def test_external_shipment_mode_recommends_include(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.invoiced["101"] = _invoiced()
    h.shipments["BATCH-1"] = {"tracking_ref": "", "mode": "external"}
    h.rates["USD"] = "88.467460"

    row = _only_row(_assemble())
    assert row["recommendation"] == InsuranceRecommendation.INCLUDE
    assert row["recommendation_reason"] == "External shipment recorded"
    assert row["status"] == InsuranceStatus.INCLUDED


# ── Insurance recovered — verbatim from charge authority ────────────────


def test_recovered_verbatim_from_the_issued_document(h):
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.invoiced["101"] = _invoiced()
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = "88.467460"

    row = _only_row(_assemble())
    assert row["insurance_recovered"] == {
        "amount": "45.67",
        "currency": "USD",
        "resolution": "invoiced",
    }
    assert row["status"] == InsuranceStatus.INCLUDED


def test_draft_intent_never_becomes_a_recovery(h):
    """Census class B2 (WDT 155/2026) in miniature.

    The draft snapshot carries a premium the issued document never billed.
    The published recovery is what the DOCUMENT billed — 10.00 — and the
    362.39 of pre-issue intent must not appear anywhere in the row.
    """
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(
        charges=[
            {
                "charge_type": "insurance",
                "resolution": "calculated",
                "amount": 362.39,
                "currency": "USD",
            }
        ]
    )
    h.invoiced["101"] = _invoiced(amount="10.00")
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = "88.467460"

    report = _assemble()
    row = _only_row(report)
    assert row["insurance_recovered"]["amount"] == "10.00"
    assert report["report_totals"]["insurance_recovered"] == {"USD": "10.00"}


def test_document_that_billed_nothing_is_a_proven_zero(h):
    """Converged, insurance line absent: an answered 0.00, not an unknown."""
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.invoiced["101"] = _invoiced(amount="0.00")
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = "88.467460"

    report = _assemble()
    row = _only_row(report)
    assert row["insurance_recovered"]["amount"] == "0.00"
    assert row["status"] == InsuranceStatus.NO_INSURANCE_CHARGED
    assert row["charge_authority_on_record"] is True
    assert report["report_totals"]["insurance_recovered_rows_without_authority"] == 0
    # Advisory only — the recommendation still follows shipment evidence.
    assert row["recommendation"] == InsuranceRecommendation.INCLUDE


def test_contradicted_record_is_needs_review_never_published(h):
    """Census classes B1/B2: a conflict is an operator decision, not a total."""
    h.facts = [_fact("101")]
    h.invoiced["101"] = _invoiced(amount="45.67", conflict="needs_manual_review")
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = "88.467460"

    row = _only_row(_assemble())
    assert row["charge_conflict"] is True
    assert row["status"] == InsuranceStatus.NEEDS_REVIEW
    assert row["recommendation"] == InsuranceRecommendation.REVIEW
    assert "manual review" in row["recommendation_reason"]


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
    )
    h.invoiced["101"] = _invoiced()
    h.invoiced["102"] = _invoiced(amount="30.00", currency="EUR")
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.shipments["BATCH-2"] = {"tracking_ref": "999", "mode": "dhl"}
    h.rates["USD"] = "88.467460"
    h.rates["EUR"] = "99.382000"

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
    h.invoiced["101"] = _invoiced()
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.shipments["BATCH-9"] = {"tracking_ref": "222", "mode": "dhl"}
    h.rates["USD"] = "88.467460"
    if xml is not None:
        h.correction_xml["201"] = xml


def test_correction_parent_tag_confirmed_nests_as_return(h):
    # Blocker 4: parent-tag CORRELATION (which invoice this correction
    # belongs to) is independent of REASON classification (why it was
    # issued). A confirmed parent link does not, by itself, justify an
    # automatic reduction of the insured total — the repository has no
    # evidence source for the reason, so it stays unknown/BLOCKED and the
    # row surfaces as needs_review until an operator supplies the reason.
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
    assert adj["status"] == InsuranceStatus.NEEDS_REVIEW
    assert adj["recommendation"] == InsuranceRecommendation.REVIEW
    assert adj["correction_reason"] == CorrectionReason.UNKNOWN
    assert adj["insurance_effect"] == InsuranceEffect.BLOCKED
    assert adj["sum_insured_inr"] == "-48657.10"
    assert groups[0]["unattached_adjustments"] == []
    assert report["report_totals"]["adjustments"] == 1
    # Fail-closed: an unresolved-reason correction never reduces the
    # automatic FACTUAL REPORT total.
    assert report["report_totals"]["sum_insured_inr_adjustments"] == "0.00"


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
    h.rates["USD"] = "88.467460"

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


# ── Blocker 4: classify_correction() pinned reason -> effect mapping ───────
#
# The repository has no evidence source for WHY a correction was issued, so
# assembly always calls classify_correction(None, ...) today and every row
# lands on UNKNOWN/BLOCKED (see test_correction_parent_tag_confirmed_nests_as_return
# above). These five tests pin the classifier itself — the mapping an
# operator-supplied reason resolves to once a reason evidence source exists —
# so the vocabulary in CorrectionReason/InsuranceEffect stays load-bearing
# and never silently drifts back to "any correction -> RETURN".


def test_genuine_partial_return_is_a_negative_adjustment():
    reason, effect = classify_correction(
        CorrectionReason.PHYSICAL_RETURN_PARTIAL, Decimal("-500.00")
    )
    assert reason == CorrectionReason.PHYSICAL_RETURN_PARTIAL
    assert effect == InsuranceEffect.PARTIAL_REVERSE


def test_commercial_discount_never_reduces_insurance():
    reason, effect = classify_correction(
        CorrectionReason.COMMERCIAL_DISCOUNT, Decimal("-200.00")
    )
    assert reason == CorrectionReason.COMMERCIAL_DISCOUNT
    assert effect == InsuranceEffect.NO_EFFECT


def test_damage_claim_credit_never_reduces_insurance():
    reason, effect = classify_correction(
        CorrectionReason.CLAIM_DAMAGE, Decimal("-150.00")
    )
    assert reason == CorrectionReason.CLAIM_DAMAGE
    assert effect == InsuranceEffect.NO_EFFECT

    reason, effect = classify_correction(
        CorrectionReason.CLAIM_SHORTAGE, Decimal("-90.00")
    )
    assert reason == CorrectionReason.CLAIM_SHORTAGE
    assert effect == InsuranceEffect.NO_EFFECT


def test_cancelled_before_dispatch_is_a_full_reversal():
    reason, effect = classify_correction(
        CorrectionReason.CANCELLED_BEFORE_DISPATCH, Decimal("-2600.00")
    )
    assert reason == CorrectionReason.CANCELLED_BEFORE_DISPATCH
    assert effect == InsuranceEffect.FULL_REVERSE


def test_unknown_reason_is_blocked_and_needs_review():
    # No reason supplied at all — today's real assembly-layer call shape.
    reason, effect = classify_correction(None, Decimal("-500.00"))
    assert reason == CorrectionReason.UNKNOWN
    assert effect == InsuranceEffect.BLOCKED

    # Explicit "unknown" and unrecognized vocabulary both fail closed too.
    reason, effect = classify_correction("unknown", Decimal("-500.00"))
    assert reason == CorrectionReason.UNKNOWN
    assert effect == InsuranceEffect.BLOCKED

    reason, effect = classify_correction("some_future_reason_code", Decimal("-500.00"))
    assert reason == CorrectionReason.UNKNOWN
    assert effect == InsuranceEffect.BLOCKED


# ── Recovered-total authority disclosure (Slice 3) ───────────────────────
#
# _sum_recovered skips any row whose premium it cannot read, so the total
# alone is indistinguishable from a complete one. These pin the count that
# discloses the gap, and — just as important — pin that a row the charge
# authority DID answer for is never counted as a gap.


def test_recovered_total_discloses_rows_without_a_charge_record(h):
    h.facts = [
        _fact("101"),
        _fact("102", fullnumber="FV 2/2026", brutto="1000.00"),
    ]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.invoiced["101"] = _invoiced()
    # 102: never converged — the authority holds no record of what it billed
    # (census class A, 512 of 764 documents). An unknown, never a zero.
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = "88.467460"

    report = _assemble()
    totals = report["report_totals"]
    assert totals["insurance_recovered"] == {"USD": "45.67"}
    assert totals["insurance_recovered_rows_without_authority"] == 1
    # The KPI carries it too — the tile is where the operator reads the total.
    assert report["kpi"]["insurance_recovered_rows_without_authority"] == 1
    by_id = {r["invoice_id"]: r for r in _all_rows(report)}
    assert by_id["101"]["charge_authority_on_record"] is True
    assert by_id["102"]["charge_authority_on_record"] is False


def test_unconverged_document_is_an_unknown_not_a_zero(h):
    """A linked draft is not a charge record — the premium stays unknown."""
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[INSURANCE_45_67])
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = "88.467460"

    report = _assemble()
    row = _only_row(report)
    assert row["insurance_recovered"] is None
    assert row["charge_authority_on_record"] is False
    assert report["report_totals"]["insurance_recovered_rows_without_authority"] == 1


def test_record_without_an_insurance_row_is_a_gap_not_a_proven_zero(h):
    """Captured freight, insurance unattributed: still an unanswered premium.

    ``capture_document`` records only the charge types the caller could
    attribute with certainty, so a record can exist while insurance is
    genuinely unknown. That must read as a gap — asserting a zero here would
    be the wrong-in-our-favour error (Lesson Q rule 6).
    """
    h.facts = [_fact("101")]
    h.drafts["101"] = _draft(charges=[])
    h.invoiced["101"] = [
        {
            "charge_type": "freight",
            "amount": "85.00",
            "currency": "USD",
            "resolution": "invoiced",
            "conflict_state": "",
        }
    ]
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = "88.467460"

    report = _assemble()
    row = _only_row(report)
    assert row["insurance_recovered"] is None
    assert row["status"] == InsuranceStatus.NO_INSURANCE_CHARGED
    assert row["charge_authority_on_record"] is False
    assert report["report_totals"]["insurance_recovered_rows_without_authority"] == 1


def test_contractor_subtotals_disclose_the_gap_too(h):
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
    h.invoiced["101"] = _invoiced()
    h.shipments["BATCH-1"] = AWB_SHIPMENT
    h.rates["USD"] = "88.467460"
    h.rates["EUR"] = "95.000000"

    subs = {
        g["contractor_id"]: g["subtotals"] for g in _assemble()["contractors"]
    }
    assert subs["C-1"]["insurance_recovered_rows_without_authority"] == 0
    assert subs["C-2"]["insurance_recovered_rows_without_authority"] == 1
