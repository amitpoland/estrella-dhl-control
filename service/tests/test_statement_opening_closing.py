"""Tally-style Client Ledger statement: opening / period / closing.

Pins the single ``aggregate_statement_from_facts`` authority — no second
calculation path. Screen and PDF both consume this model via
``_build_statement_dict``.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.services.ledger_aggregator import (
    aggregate_statement_from_facts,
    _parse_invoice_fact,
    _parse_payment_fact,
)
import xml.etree.ElementTree as ET


def _inv(*, iid, date, brutto, currency="USD", type_="normal", fullnumber="", paymentdate=""):
    xml = (
        f"<invoice><id>{iid}</id><fullnumber>{fullnumber or iid}</fullnumber>"
        f"<type>{type_}</type><date>{date}</date>"
        f"<paymentdate>{paymentdate or date}</paymentdate>"
        f"<currency>{currency}</currency>"
        f"<netto>{brutto}</netto><brutto>{brutto}</brutto></invoice>"
    )
    return _parse_invoice_fact(ET.fromstring(xml))


def _pay(*, pid, date, value, linked, currency=""):
    inv = f"<invoice><id>{linked}</id></invoice>" if linked else ""
    ccy = f"<currency>{currency}</currency>" if currency else ""
    xml = (
        f"<payment><id>{pid}</id><date>{date}</date>"
        f"<value>{value}</value>{ccy}{inv}</payment>"
    )
    return _parse_payment_fact(ET.fromstring(xml))


def _meta():
    return {
        "wfirma_contractor_id": "1",
        "name": "Diamond Point B.V.",
        "country": "NL",
        "vat_id": "NL123",
    }


def test_nonzero_opening_balance_and_closing_invariant():
    facts_inv = [
        _inv(iid="10", date="2025-12-15", brutto="1000.00", fullnumber="WDT 100/2025"),
        _inv(iid="20", date="2026-01-10", brutto="500.00", fullnumber="WDT 10/2026"),
    ]
    facts_pay = [
        _pay(pid="p1", date="2025-12-20", value="200.00", linked="10"),
        _pay(pid="p2", date="2026-01-15", value="100.00", linked="20"),
    ]
    stmt = aggregate_statement_from_facts(
        _meta(), facts_inv, facts_pay, "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    t = stmt["totals_per_currency"]["USD"]
    assert t["opening_balance"] == "800.00"  # 1000 - 200
    assert t["period_debits"] == "500.00"
    assert Decimal(t["period_credits"]) == Decimal("100.00")
    assert t["closing_balance"] == "1200.00"
    opening = Decimal(t["opening_balance"])
    closing = Decimal(t["closing_balance"])
    assert opening + Decimal(t["period_debits"]) - Decimal(t["period_credits"]) == closing
    entries = stmt["entries_per_currency"]["USD"]
    assert entries[0]["type"] == "opening_balance"
    assert entries[0]["doc_number"] == "OPENING BALANCE / B/F"
    assert entries[0]["running_balance"] == "800.00"
    # First period movement continues from opening
    period_rows = [e for e in entries if not e.get("is_opening_balance")]
    assert period_rows[0]["running_balance"] == "1300.00"  # 800 + 500


def test_zero_opening_when_no_prior_activity():
    facts_inv = [_inv(iid="20", date="2026-01-10", brutto="500.00")]
    stmt = aggregate_statement_from_facts(
        _meta(), facts_inv, [], "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    t = stmt["totals_per_currency"]["USD"]
    assert t["opening_balance"] == "0.00"
    assert t["closing_balance"] == "500.00"
    entries = stmt["entries_per_currency"]["USD"]
    assert all(e.get("type") != "opening_balance" for e in entries)


def test_previous_closing_equals_next_opening():
    facts_inv = [
        _inv(iid="10", date="2025-12-15", brutto="1000.00"),
        _inv(iid="20", date="2026-01-10", brutto="500.00"),
    ]
    facts_pay = [
        _pay(pid="p1", date="2025-12-20", value="200.00", linked="10"),
    ]
    dec = aggregate_statement_from_facts(
        _meta(), facts_inv, facts_pay, "2025-12-31", ("2025-12-01", "2025-12-31"),
    )
    jan = aggregate_statement_from_facts(
        _meta(), facts_inv, facts_pay, "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    assert (
        dec["totals_per_currency"]["USD"]["closing_balance"]
        == jan["totals_per_currency"]["USD"]["opening_balance"]
    )


def test_credit_note_appears_once_as_credit():
    facts_inv = [
        _inv(iid="10", date="2026-01-05", brutto="1000.00"),
        _inv(iid="11", date="2026-01-08", brutto="-100.00", type_="correction", fullnumber="CN 1/2026"),
    ]
    stmt = aggregate_statement_from_facts(
        _meta(), facts_inv, [], "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    entries = [e for e in stmt["entries_per_currency"]["USD"] if e.get("type") == "correction"]
    assert len(entries) == 1
    assert entries[0]["credit"] == "100.00"
    assert entries[0]["debit"] == "0.00"
    t = stmt["totals_per_currency"]["USD"]
    assert t["credited"] == "100.00"
    assert t["closing_balance"] == "900.00"
    assert entries[0]["status"] == "Issued"
    # Aging excludes credit notes — total can diverge from closing
    aging_total = Decimal(stmt["aging_per_currency"]["USD"]["total"])
    assert aging_total == Decimal("1000.00")
    assert aging_total != Decimal(t["closing_balance"])


def test_partial_payment_and_payment_outside_period_in_opening():
    facts_inv = [
        _inv(iid="10", date="2025-11-01", brutto="1000.00"),
    ]
    facts_pay = [
        _pay(pid="p1", date="2025-11-15", value="400.00", linked="10"),  # opening
        _pay(pid="p2", date="2026-02-10", value="100.00", linked="10"),  # period
    ]
    stmt = aggregate_statement_from_facts(
        _meta(), facts_inv, facts_pay, "2026-02-28", ("2026-02-01", "2026-02-28"),
    )
    t = stmt["totals_per_currency"]["USD"]
    assert t["opening_balance"] == "600.00"
    assert t["period_credits"] == "100.00"
    assert t["closing_balance"] == "500.00"
    pays = [e for e in stmt["entries_per_currency"]["USD"] if e.get("type") == "payment"]
    assert len(pays) == 1
    assert pays[0]["credit"] == "100.00"


def test_running_balance_continuous_from_opening():
    facts_inv = [
        _inv(iid="10", date="2025-12-01", brutto="100.00"),
        _inv(iid="20", date="2026-01-05", brutto="50.00"),
        _inv(iid="21", date="2026-01-10", brutto="25.00"),
    ]
    stmt = aggregate_statement_from_facts(
        _meta(), facts_inv, [], "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    rows = stmt["entries_per_currency"]["USD"]
    bals = [Decimal(e["running_balance"]) for e in rows]
    assert bals[0] == Decimal("100.00")  # B/F
    assert bals[1] == Decimal("150.00")
    assert bals[2] == Decimal("175.00")


def test_multi_currency_separation():
    facts_inv = [
        _inv(iid="10", date="2025-12-01", brutto="100.00", currency="USD"),
        _inv(iid="20", date="2026-01-05", brutto="50.00", currency="EUR"),
    ]
    stmt = aggregate_statement_from_facts(
        _meta(), facts_inv, [], "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    assert "USD" in stmt["totals_per_currency"]
    assert "EUR" in stmt["totals_per_currency"]
    assert stmt["totals_per_currency"]["USD"]["closing_balance"] == "100.00"
    assert stmt["totals_per_currency"]["EUR"]["closing_balance"] == "50.00"


def test_statement_model_flags_and_ui_labels_in_source():
    ldg = (
        Path(__file__).resolve().parent.parent / "app/static/v2/ledgers-page.jsx"
    ).read_text(encoding="utf-8")
    assert "OPENING BALANCE / B/F" in (
        Path(__file__).resolve().parent.parent
        / "app/services/ledger_aggregator.py"
    ).read_text(encoding="utf-8")
    assert "Closing balance as of" in ldg
    assert "ldg-stmt-closing-" in ldg
    assert "ldg-position-vs-activity-note" in ldg
    assert "id: 'unapplied'" in ldg
    assert "Opening → period movements → Closing" in ldg


def test_pdf_uses_closing_balance_label():
    src = (
        Path(__file__).resolve().parent.parent
        / "app/services/statement_pdf_renderer.py"
    ).read_text(encoding="utf-8")
    assert "Closing balance" in src
    assert "Opening balance" in src


def test_routes_load_from_history_floor():
    src = (
        Path(__file__).resolve().parent.parent / "app/api/routes_ledgers.py"
    ).read_text(encoding="utf-8")
    assert "load_ar_fact_universe(floor, dt)" in src
    assert "STATEMENT_HISTORY_FLOOR" in src
    assert "history_floor" in src
