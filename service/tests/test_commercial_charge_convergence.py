"""The charge-record store and the convergence capability.

Two things are pinned here, because both are how the recovered-premium gap
comes back:

  * the record store must never overwrite a stored amount, and must keep
    "never converged" (None) distinct from "converged, billed nothing" (0.00);
  * the capability must never write without the operator's gate, must never
    record an amount it could not attribute by canonical service identity, and
    must be idempotent.

wFirma is stubbed throughout — no test here performs a network read.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal

import pytest

from app.services import commercial_charge_convergence as ccc
from app.services import commercial_charge_record_db as record_db

INSURANCE_ID = "13102217"


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    return tmp_path / "commercial_charges.db"


def _doc(invoice_id="101", number="WDT 153/2026", date="2026-08-04",
         currency="EUR", dtype="normal"):
    return {"invoice_id": invoice_id, "number": number, "date": date,
            "type": dtype, "currency": currency}


def _invoice_xml(invoice_id="101", number="WDT 153/2026", date="2026-08-04",
                 currency="EUR", contractor_id="900", lines=()):
    """One wFirma invoice element. ``lines`` = (name, good_id, netto) tuples."""
    content = "".join(
        "<invoicecontent><name>%s</name><good><id>%s</id></good>"
        "<netto>%s</netto></invoicecontent>" % (n, g, v) for n, g, v in lines
    )
    return ET.fromstring(
        "<invoice><id>%s</id><fullnumber>%s</fullnumber><date>%s</date>"
        "<currency>%s</currency><contractor_id>%s</contractor_id><type>normal</type>"
        "<invoicecontents>%s</invoicecontents></invoice>"
        % (invoice_id, number, date, currency, contractor_id, content)
    )


@pytest.fixture
def wfirma(monkeypatch):
    """Stub the wFirma read. ``wfirma.invoices`` is what the API 'holds'."""
    class Stub:
        def __init__(self):
            self.invoices = []
            self.calls = []

        def fetch(self, invoice_type, page_size=200):
            self.calls.append(invoice_type)
            return self.invoices if invoice_type == "normal" else []

    stub = Stub()
    monkeypatch.setattr(ccc, "fetch_invoices", stub.fetch)
    monkeypatch.setattr(ccc, "insurance_service_id",
                        lambda cid, master_db, cache: INSURANCE_ID)
    return stub


@pytest.fixture
def armed(monkeypatch):
    monkeypatch.setattr(ccc.settings, "commercial_charge_convergence_apply_enabled",
                        True, raising=False)


# ── the record store ─────────────────────────────────────────────────────────


def test_never_converged_is_none_not_empty(db):
    """The distinction the whole repair rests on."""
    assert record_db.get_document_charges("101", path=db) is None


def test_billed_nothing_is_a_recorded_zero(db):
    record_db.capture_document(_doc(), {"insurance": {"amount": Decimal("0")}}, path=db)
    rows = record_db.get_document_charges("101", path=db)
    assert rows is not None and rows[0]["amount"] == "0"
    assert rows[0]["resolution"] == "invoiced"


def test_recapture_of_the_same_evidence_is_a_no_op(db):
    charges = {"insurance": {"amount": Decimal("56.98"), "good_id": INSURANCE_ID}}
    first = record_db.capture_document(_doc(), charges, path=db)
    second = record_db.capture_document(_doc(), charges, path=db)
    assert first["actions"]["insurance"] == "inserted"
    assert second["actions"]["insurance"] == "unchanged"
    assert second["conflicts"] == []


def test_contradiction_keeps_the_stored_value_and_flags_review(db):
    record_db.capture_document(_doc(), {"insurance": {"amount": Decimal("56.98")}},
                               path=db)
    result = record_db.capture_document(
        _doc(), {"insurance": {"amount": Decimal("99.00")}}, path=db)

    assert result["actions"]["insurance"] == "conflict"
    stored = record_db.get_document_charges("101", path=db)[0]
    assert stored["amount"] == "56.98"          # never overwritten
    assert stored["conflict_state"] == record_db.CONFLICT_NEEDS_REVIEW
    conflicts = record_db.list_conflicts(path=db)
    assert len(conflicts) == 1 and conflicts[0]["conflict_note"]


def test_a_charge_type_not_passed_is_not_asserted_as_zero(db):
    """Omission means "could not attribute" — the store must not invent a 0."""
    record_db.capture_document(_doc(), {"insurance": {"amount": Decimal("10")}},
                               path=db)
    types = {r["charge_type"] for r in record_db.get_document_charges("101", path=db)}
    assert types == {"insurance"}


def test_dry_capture_computes_the_decision_and_writes_nothing(db):
    result = record_db.capture_document(
        _doc(), {"insurance": {"amount": Decimal("56.98")}}, path=db, apply=False)
    assert result["actions"]["insurance"] == "inserted"
    assert record_db.get_document_charges("101", path=db) is None


# ── run status ───────────────────────────────────────────────────────────────


def test_status_of_a_capability_that_never_ran_is_not_an_error(db):
    status = record_db.get_run_status(path=db)
    assert status["last_started_at"] is None
    assert status["running"] is False
    assert status["errors"] == 0


def test_cooldown_measures_from_the_start_so_a_dead_run_unblocks(db):
    record_db.mark_run_started("2026-08-01", "2026-08-31", "scheduler", path=db)
    # never completed — a run that died
    assert record_db.is_run_due(3600, path=db) is False
    import time as _t
    assert record_db.is_run_due(3600, now=_t.time() + 7200, path=db) is True


# ── the capability ───────────────────────────────────────────────────────────


def test_apply_without_the_gate_is_refused_never_downgraded(db, wfirma):
    wfirma.invoices = [_invoice_xml(lines=[("Insurance", INSURANCE_ID, "56.98")])]
    with pytest.raises(ccc.ChargeConvergenceWriteDenied):
        ccc.run_charge_convergence(date_from="2026-08-01", date_to="2026-08-31",
                                   apply=True, record_path=db)
    assert record_db.get_document_charges("101", path=db) is None


def test_dry_run_needs_no_gate_and_writes_nothing(db, wfirma):
    wfirma.invoices = [_invoice_xml(lines=[("Insurance", INSURANCE_ID, "56.98")])]
    summary = ccc.run_charge_convergence(date_from="2026-08-01", date_to="2026-08-31",
                                         record_path=db)
    assert summary["mode"] == "dry_run"
    assert summary["processed"] == 1 and summary["created"] == 1
    assert summary["billed_insurance_by_currency"] == {"EUR": "56.98"}
    assert record_db.get_document_charges("101", path=db) is None
    assert record_db.get_run_status(path=db)["last_started_at"] is None


def test_apply_records_the_billed_premium_and_is_idempotent(db, wfirma, armed):
    wfirma.invoices = [_invoice_xml(lines=[("Insurance", INSURANCE_ID, "56.98")])]
    first = ccc.run_charge_convergence(date_from="2026-08-01", date_to="2026-08-31",
                                       apply=True, record_path=db)
    second = ccc.run_charge_convergence(date_from="2026-08-01", date_to="2026-08-31",
                                        apply=True, record_path=db)

    assert first["created"] == 1 and first["skipped"] == 0
    assert second["created"] == 0 and second["skipped"] == 1
    assert record_db.get_document_charges("101", path=db)[0]["amount"] == "56.98"
    status = record_db.get_run_status(path=db)
    assert status["last_completed_at"] and status["running"] is False


def test_unattributed_insurance_line_is_reported_never_recorded(db, wfirma, armed):
    """It reads like insurance but carries a good_id we do not own."""
    wfirma.invoices = [_invoice_xml(lines=[("Ubezpieczenie", "99999999", "42.00")])]
    summary = ccc.run_charge_convergence(date_from="2026-08-01", date_to="2026-08-31",
                                         apply=True, record_path=db)

    assert summary["unattributed"] == 1
    assert summary["billed_insurance_by_currency"] == {}
    # The document IS on record — as a proven zero, which is the honest reading:
    # by canonical identity this document billed no insurance.
    assert record_db.get_document_charges("101", path=db)[0]["amount"] == "0"


def test_documents_outside_the_window_are_not_touched(db, wfirma, armed):
    wfirma.invoices = [
        _invoice_xml(invoice_id="101", date="2026-08-04",
                     lines=[("Insurance", INSURANCE_ID, "56.98")]),
        _invoice_xml(invoice_id="102", date="2026-07-04",
                     lines=[("Insurance", INSURANCE_ID, "10.00")]),
    ]
    summary = ccc.run_charge_convergence(date_from="2026-08-01", date_to="2026-08-31",
                                         apply=True, record_path=db)
    assert summary["processed"] == 1
    assert record_db.get_document_charges("102", path=db) is None


def test_multiple_insurance_lines_are_summed(db, wfirma):
    wfirma.invoices = [_invoice_xml(lines=[("Insurance", INSURANCE_ID, "40.00"),
                                           ("Insurance", INSURANCE_ID, "16.98")])]
    summary = ccc.run_charge_convergence(date_from="2026-08-01", date_to="2026-08-31",
                                         record_path=db)
    assert summary["billed_insurance_by_currency"] == {"EUR": "56.98"}


def test_a_conflict_is_surfaced_by_the_run(db, wfirma, armed):
    wfirma.invoices = [_invoice_xml(lines=[("Insurance", INSURANCE_ID, "56.98")])]
    ccc.run_charge_convergence(date_from="2026-08-01", date_to="2026-08-31",
                               apply=True, record_path=db)
    wfirma.invoices = [_invoice_xml(lines=[("Insurance", INSURANCE_ID, "99.00")])]
    summary = ccc.run_charge_convergence(date_from="2026-08-01", date_to="2026-08-31",
                                         apply=True, record_path=db)

    assert summary["conflicts"] == 1
    assert record_db.get_document_charges("101", path=db)[0]["amount"] == "56.98"


def test_scheduler_tick_does_nothing_while_the_gate_is_disarmed(db, wfirma, monkeypatch):
    monkeypatch.setattr(ccc.settings, "commercial_charge_convergence_apply_enabled",
                        False, raising=False)
    wfirma.invoices = [_invoice_xml(lines=[("Insurance", INSURANCE_ID, "56.98")])]
    assert ccc.run_scheduler_tick() is None
    assert wfirma.calls == []           # not even a read


def test_run_failure_carries_what_was_measured(db, wfirma, armed, monkeypatch):
    def boom(invoice_type, page_size=200):
        raise ConnectionError("invoices/find HTTP 503")

    monkeypatch.setattr(ccc, "fetch_invoices", boom)
    with pytest.raises(ccc.ChargeConvergenceError) as exc:
        ccc.run_charge_convergence(date_from="2026-08-01", date_to="2026-08-31",
                                   apply=True, record_path=db)
    assert exc.value.summary["errors"] == 1
    status = record_db.get_run_status(path=db)
    assert status["errors"] == 1 and "503" in status["last_error"]
