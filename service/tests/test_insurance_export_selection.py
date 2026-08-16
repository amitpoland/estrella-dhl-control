"""Insurance Export Statement — declaration selection semantics.

Operator-specified cases: selection is ephemeral and IDs-only, the server
re-resolves every value; the FACTUAL REPORT totals never change with
selection, the DECLARATION totals do.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.services.insurance_export_statement as ies
from app.services.insurance_export_statement import (
    UnknownSelectionError,
    assemble_insurance_export_report,
    resolve_declaration_selection,
)
from app.services.insurance_fx_provider import InsuranceFxError

DB = Path("unused-proforma.db")
CDB = Path("unused-carrier.db")
PERIOD = ("2026-05-01", "2026-05-31")

# Operator-approved insurance INR rates (INR per 1 unit of currency) — the
# ONLY FX authority per the fail-closed insurance_fx_provider boundary
# (Blocker 1). Same canonical values used across the other insurance-export
# test files.
RATES = {"USD": "88.467460", "EUR": "99.382000", "GBP": "85.293000"}

PARENT_TAG_XML = (
    "<api><invoices><invoice>"
    "<invoicecorrection><invoice><id>101</id></invoice></invoicecorrection>"
    "</invoice></invoices></api>"
)


def _fact(inv_id, *, fullnumber, type_="normal", currency, brutto,
          contractor_id, contractor_name, date="2026-05-10"):
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


def _draft(draft_id, batch_id, client_name, currency, charges):
    return SimpleNamespace(
        id=draft_id,
        batch_id=batch_id,
        client_name=client_name,
        currency=currency,
        service_charges_json=json.dumps(charges),
    )


@pytest.fixture()
def fx(monkeypatch):
    """Standard 5-row fixture: 4 documents + 1 confirmed return adjustment.

    INR values (PLN_per_INR = 0.05):
      101 Alpha  USD 2600.00 -> 253016.94   (insured, premium 45.67 USD)
      102 Alpha  USD 1000.00 ->  97314.21   (no premium charged)
      103 Beta   EUR 2000.00 -> 218640.40   (personal pickup)
      104 Gamma  GBP  500.00 ->  46911.15   (needs review, no draft)
      201 Alpha  USD -500.00 -> -48657.10   (return, parent 101 confirmed)
    Documents 615882.70; grand with adjustment 567225.60.
    """
    state = SimpleNamespace(correction_xml={"201": PARENT_TAG_XML},
                            corr_fullnumber="KOR 1/2026")

    facts = [
        _fact("101", fullnumber="FV 1/2026", currency="USD", brutto="2600.00",
              contractor_id="C-1", contractor_name="Alpha Exports Ltd"),
        _fact("102", fullnumber="FV 2/2026", currency="USD", brutto="1000.00",
              contractor_id="C-1", contractor_name="Alpha Exports Ltd"),
        _fact("103", fullnumber="FV 3/2026", currency="EUR", brutto="2000.00",
              contractor_id="C-2", contractor_name="Beta Trading GmbH"),
        _fact("104", fullnumber="FV 4/2026", currency="GBP", brutto="500.00",
              contractor_id="C-3", contractor_name="Gamma Imports"),
    ]

    def _universe(df, dt, force=False):
        corr = _fact("201", fullnumber=state.corr_fullnumber,
                     type_="correction", currency="USD", brutto="-500.00",
                     contractor_id="C-1", contractor_name="Alpha Exports Ltd",
                     date="2026-05-20")
        return {"invoice_facts": list(facts) + [corr]}

    drafts = {
        "101": _draft(7, "BATCH-1", "Alpha Exports Ltd", "USD", []),
        "102": _draft(8, "BATCH-2", "Alpha Exports Ltd", "USD", []),
        "103": _draft(9, "BATCH-3", "Beta Trading GmbH", "EUR",
                      [{"charge_type": "freight",
                        "resolution": "customer_courier", "amount": 0}]),
        "201": _draft(10, "BATCH-9", "Alpha Exports Ltd", "USD", []),
    }
    # What each ISSUED document billed — the recovered-premium authority.
    # 101 billed 45.67 USD; 102/103 converged and billed nothing; 104 has no
    # entry at all, which is "not converged yet", not a zero.
    invoiced = {
        "101": [{"charge_type": "insurance", "amount": "45.67",
                 "currency": "USD", "resolution": "invoiced",
                 "conflict_state": ""}],
        "102": [{"charge_type": "insurance", "amount": "0",
                 "currency": "USD", "resolution": "invoiced",
                 "conflict_state": ""}],
        "103": [{"charge_type": "insurance", "amount": "0",
                 "currency": "EUR", "resolution": "invoiced",
                 "conflict_state": ""}],
    }
    shipments = {
        "BATCH-1": {"tracking_ref": "111", "mode": "dhl"},
        "BATCH-2": {"tracking_ref": "222", "mode": "dhl"},
        "BATCH-9": {"tracking_ref": "999", "mode": "dhl"},
    }

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

    def _fetch_xml(invoice_id):
        return state.correction_xml[str(invoice_id)]

    monkeypatch.setattr(ies, "load_ar_fact_universe", _universe)
    monkeypatch.setattr(ies, "get_draft_by_wfirma_invoice_id",
                        lambda db, i: drafts.get(str(i)))
    monkeypatch.setattr(ies, "get_document_charges",
                        lambda inv_id, path=None: invoiced.get(str(inv_id)))
    monkeypatch.setattr(ies, "_batch_client_count", lambda db, b: 1)
    monkeypatch.setattr(
        ies, "shipment_db",
        SimpleNamespace(
            get_shipment_for_draft=lambda cdb, b, c,
            allow_single_client_fallback=False: shipments.get(b)
        ),
    )
    monkeypatch.setattr(ies, "insurance_fx_provider",
                        SimpleNamespace(get_rate=_get_rate))
    monkeypatch.setattr(ies, "wfirma_client",
                        SimpleNamespace(fetch_invoice_xml=_fetch_xml))
    return state


def _select(doc_ids, adj_ids):
    return resolve_declaration_selection(
        PERIOD[0], PERIOD[1], doc_ids, adj_ids,
        db_path=DB, carrier_db_path=CDB,
    )


ALL_DOCS = ["101", "102", "103", "104"]


def test_all_selected_with_adjustment(fx):
    sel = _select(ALL_DOCS, ["201"])
    t = sel["declaration_totals"]
    assert t["sum_insured_inr_documents"] == "615882.70"
    assert t["sum_insured_inr_adjustments"] == "-48657.10"
    assert t["sum_insured_inr_grand"] == "567225.60"
    assert t["documents"] == 4
    assert t["adjustments"] == 1
    assert len(sel["selected_rows"]) == 4
    assert len(sel["selected_adjustments"]) == 1


def test_one_invoice_excluded(fx):
    sel = _select(["101", "103", "104"], ["201"])
    t = sel["declaration_totals"]
    assert t["sum_insured_inr_documents"] == "518568.49"
    assert t["sum_insured_inr_grand"] == "469911.39"


def test_pickup_invoice_excluded(fx):
    sel = _select(["101", "102", "104"], [])
    t = sel["declaration_totals"]
    assert t["sum_insured_inr_documents"] == "397242.30"
    assert t["sum_insured_inr_grand"] == "397242.30"
    assert t["adjustments"] == 0


def test_review_invoice_excluded(fx):
    sel = _select(["101", "102", "103"], ["201"])
    assert sel["declaration_totals"]["sum_insured_inr_documents"] == "568971.55"


def test_entire_customer_selected(fx):
    # Alpha only (101 + 102 + its return).
    sel = _select(["101", "102"], ["201"])
    t = sel["declaration_totals"]
    assert t["sum_insured_inr_documents"] == "350331.15"
    assert t["sum_insured_inr_grand"] == "301674.05"
    # Recovered premium follows the selected rows only, per currency.
    assert t["insurance_recovered"] == {"USD": "45.67"}


def test_partial_customer_selected(fx):
    sel = _select(["101"], [])
    assert sel["declaration_totals"]["sum_insured_inr_documents"] == "253016.94"


def test_return_excluded(fx):
    sel = _select(ALL_DOCS, [])
    t = sel["declaration_totals"]
    assert sel["selected_adjustments"] == []
    assert t["sum_insured_inr_adjustments"] == "0.00"
    assert t["sum_insured_inr_grand"] == t["sum_insured_inr_documents"] == "615882.70"


def test_report_totals_never_change_with_selection(fx):
    before = assemble_insurance_export_report(
        PERIOD[0], PERIOD[1], db_path=DB, carrier_db_path=CDB
    )["report_totals"]
    _select(["101"], [])
    _select(ALL_DOCS, ["201"])
    after = assemble_insurance_export_report(
        PERIOD[0], PERIOD[1], db_path=DB, carrier_db_path=CDB
    )["report_totals"]
    assert before == after
    # Blocker 4: correction "201" carries no evidenced correction_reason, so
    # it classifies as unknown/BLOCKED and is never counted in the FACTUAL
    # REPORT total automatically — regardless of what the operator later
    # selects into the declaration (that is a separate, explicit total; see
    # test_all_selected_with_adjustment). 615882.70 = documents only.
    assert after["sum_insured_inr_grand"] == "615882.70"
    assert after["sum_insured_inr_adjustments"] == "0.00"


def test_unknown_document_id_raises(fx):
    with pytest.raises(UnknownSelectionError) as ei:
        _select(["999"], [])
    assert ei.value.unknown == ["999"]


def test_document_id_is_not_a_valid_adjustment_id(fx):
    with pytest.raises(UnknownSelectionError) as ei:
        _select([], ["101"])
    assert "101" in ei.value.unknown


def test_selection_order_follows_report_order(fx):
    sel = _select(["104", "101", "103", "102"], [])
    assert [r["invoice_id"] for r in sel["selected_rows"]] == ALL_DOCS


def test_unconfirmed_adjustment_still_selectable(fx):
    # Number-pattern correlation → needs_review, unattached — but the
    # operator may still deliberately include it in the declaration.
    fx.correction_xml["201"] = (
        "<api><invoices><invoice><id>201</id></invoice></invoices></api>"
    )
    fx.corr_fullnumber = "KOR FV 1/2026"
    sel = _select(["101"], ["201"])
    assert len(sel["selected_adjustments"]) == 1
    adj = sel["selected_adjustments"][0]
    assert adj["parent_confirmed"] is False
    assert sel["declaration_totals"]["sum_insured_inr_adjustments"] == "-48657.10"
