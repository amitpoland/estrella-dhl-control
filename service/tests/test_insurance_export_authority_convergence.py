"""Two authority domains, ONE Insurance Export projection.

The statement consumes the India Official Reference FX Authority and the
CommercialChargeAuthority. They are separate domains and must stay separate:
neither may repair, mask, or stand in for the other, and the report may not
grow a second source for either.

Everything below runs the REAL provider boundary and the REAL FX authority
(offline: the archive transport is stubbed, the cache is a tmp dir) against the
REAL statement assembler, so the wiring itself is what is under test — not a
stub of it.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import app.services.insurance_export_statement as ies
from app.core.config import settings
from app.services import india_official_fx as fx
from app.services import insurance_fx_provider
from app.services.insurance_export_statement import (
    InsuranceRecommendation,
    InsuranceStatus,
    assemble_insurance_export_report,
)

DB = Path("unused-proforma.db")
CDB = Path("unused-carrier.db")
PERIOD = ("2026-08-01", "2026-08-31")

# Synthetic archive shape — test input, never an approved rate.
ARCHIVE_HTML = """
<table>
<tr><td><b>Date</b></td><td><b>USD (INR / 1 USD)</b></td>
    <td><b>EUR (INR / 1 EUR)</b></td></tr>
<tr><td>13/08/2026</td><td>95.0000</td><td>110.0000</td></tr>
</table>
"""


def _fact(inv_id="101", *, currency="USD", brutto="1000.00", date="2026-08-14"):
    return {"id": inv_id, "fullnumber": "WDT 153/2026", "type": "normal",
            "date": date, "paymentdate": "", "currency": currency,
            "netto": None, "brutto": brutto,
            "contractor_id": "C-1", "contractor_name": "Alpha Exports Ltd"}


def _invoiced(amount="56.98", currency="USD", conflict=""):
    return [{"charge_type": "insurance", "amount": amount, "currency": currency,
             "resolution": "invoiced", "conflict_state": conflict}]


class Wiring:
    """Real FX authority + real charge-authority shape; only the two edges of
    the system (wFirma reads, the charge record file) are stubbed."""

    def __init__(self, monkeypatch, tmp_path):
        self.facts = [_fact()]
        self.invoiced = {}
        # Linkage evidence (draft + shipment) is a THIRD, unrelated concern:
        # it decides the row's operator recommendation. Seeded here so the
        # tests below isolate the two authorities under test.
        self.drafts = {"101": SimpleNamespace(
            id=7, batch_id="BATCH-1", client_name="Alpha Exports Ltd",
            currency="USD", service_charges_json="[]")}
        monkeypatch.setattr(settings, "storage_root", tmp_path)
        monkeypatch.setattr(settings, "insurance_fx_provider", "india_official")
        monkeypatch.setattr(fx, "_fetch_window",
                            lambda start, end: fx._parse_archive(ARCHIVE_HTML))
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
        # The real boundary — NOT stubbed. This is the point of the file.
        monkeypatch.setattr(ies, "insurance_fx_provider", insurance_fx_provider)


@pytest.fixture
def w(monkeypatch, tmp_path):
    return Wiring(monkeypatch, tmp_path)


def _row(report):
    rows = [r for g in report["contractors"] for r in g["rows"]]
    assert len(rows) == 1
    return rows[0]


def _report():
    return assemble_insurance_export_report(PERIOD[0], PERIOD[1],
                                            db_path=DB, carrier_db_path=CDB)


# ── the two domains reach the one projection ─────────────────────────────────


def test_both_authorities_reach_the_same_row(w):
    w.invoiced["101"] = _invoiced()
    row = _row(_report())

    # FX domain: invoice 14/08 → publication 13/08 (date rule: never forward).
    assert row["fx_rate"] == "95.0000"
    # Provenance names the OFFICIAL publication it came from, not the
    # abstraction the statement consumes — FBIL/RBI semantics stay visible.
    assert row["fx_provenance"]["source"] == "rbi_reference_rate_archive"
    assert row["fx_provenance"]["effective_date"] == "2026-08-13"
    assert row["sum_insured_inr"] == "104500.00"        # 1000 x 1.10 x 95
    # Charge domain: what the ISSUED document billed.
    assert row["insurance_recovered"] == {"amount": "56.98", "currency": "USD",
                                          "resolution": "invoiced"}
    assert row["charge_authority_on_record"] is True
    assert row["status"] == InsuranceStatus.INCLUDED


def test_an_fx_gap_never_erases_the_recovered_premium(w):
    """FX failure is an FX-domain fact. The charge domain still answers."""
    w.facts = [_fact(currency="GBP")]                   # not in the archive
    w.invoiced["101"] = _invoiced(currency="GBP")
    row = _row(_report())

    assert row["fx_rate"] is None
    assert row["sum_insured_inr"] is None               # never a zero
    assert row["status"] == InsuranceStatus.NEEDS_REVIEW
    assert row["insurance_recovered"]["amount"] == "56.98"
    assert row["charge_authority_on_record"] is True


def test_an_unconverged_document_never_erases_the_fx_conversion(w):
    """And the mirror: no charge record is an unknown, not a zero premium."""
    row = _row(_report())

    assert row["fx_rate"] == "95.0000"
    assert row["insurance_recovered"] is None
    assert row["charge_authority_on_record"] is False
    report = _report()
    assert report["kpi"]["insurance_recovered_rows_without_authority"] == 1
    assert report["kpi"]["insurance_recovered"] == {}


def test_the_draft_is_never_a_second_source_for_the_premium(w):
    """Outcome 9: no report-time dual-source fallback survives.

    The draft carries a premium the issued document does not. The report must
    read the ISSUED document only — an intent is not a recovery.
    """
    import json

    w.drafts["101"] = SimpleNamespace(
        id=7, batch_id="BATCH-1", client_name="Alpha Exports Ltd", currency="USD",
        service_charges_json=json.dumps([{"charge_type": "insurance",
                                          "resolution": "manual_amount",
                                          "amount": 999.99, "currency": "USD"}]))
    row = _row(_report())

    assert row["insurance_recovered"] is None           # not 999.99
    assert row["charge_authority_on_record"] is False


def test_a_contradicted_premium_blocks_instead_of_publishing_either_value(w):
    w.invoiced["101"] = _invoiced(conflict="needs_manual_review")
    row = _row(_report())

    assert row["charge_conflict"] is True
    assert row["status"] == InsuranceStatus.NEEDS_REVIEW
    assert row["recommendation"] == InsuranceRecommendation.REVIEW
    assert "manual review" in row["recommendation_reason"].lower()
    # The FX domain is untouched by the charge-domain conflict.
    assert row["fx_rate"] == "95.0000"


def test_neither_authority_is_reimplemented_inside_the_statement(w):
    """No independent wFirma insurance lookup, no independent provider logic."""
    src = Path(ies.__file__).read_text(encoding="utf-8")
    for forbidden in ("nbp_rate_service", "invoices/find", "_parse_archive",
                      "rbi.org.in", "fbil.org.in"):
        assert forbidden not in src, forbidden
