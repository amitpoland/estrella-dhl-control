"""Enterprise ledger PRESENTATION contract.

Pins the presentation policy recorded in
``docs/accounting/EJ-FINANCIAL-BUSINESS-RULES.md``. Every assertion here is
about how a corrected financial fact is DISPLAYED. Nothing in this file
asserts, redefines, or exercises a financial authority: eligibility,
matching, ``remaining_after_payments``, opening/closing arithmetic, aging
buckets and FX all stay exactly where they are.

Fixtures are synthetic. No real counterparty, balance, or document number
appears in this file.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.financial_aging import AGING_BUCKETS_WITH_UNAVAILABLE
from app.services.ledger_aggregator import (
    AGING_BASIS_GROSS,
    FORBIDDEN_ENTRY_FIELDS,
    PRESENTATION_STATUS_APPLIED,
    PRESENTATION_STATUS_BF,
    PRESENTATION_STATUS_CONFLICT,
    PRESENTATION_STATUS_CREDIT,
    PRESENTATION_STATUS_DUE_UNAVAILABLE,
    PRESENTATION_STATUS_NOT_DUE,
    PRESENTATION_STATUS_OVERDUE,
    PRESENTATION_STATUS_SETTLED,
    PRESENTATION_STATUS_UNAPPLIED,
    _normalize_doc_link_id,
    _parse_expense_fact,
    _parse_invoice_fact,
    _parse_payment_fact,
    aggregate_statement_from_facts,
    aggregate_supplier_statement,
    classify_expense_lifecycle,
    derive_presentation_status,
    presentation_state,
    presentation_state_from_maps,
)
from app.services.local_fact_universe import (
    reporting_row_to_expense_fact,
    reporting_row_to_invoice_fact,
)

V2 = Path(__file__).resolve().parents[1] / "app" / "static" / "v2"


# ── fixture builders (synthetic) ──────────────────────────────────────────

def _inv(*, iid, date, brutto, currency="USD", type_="normal", fullnumber="",
         paymentdate=None, payment_state="", parent_id=""):
    due = date if paymentdate is None else paymentdate
    parent = f"<parent><id>{parent_id}</id></parent>" if parent_id else ""
    xml = (
        f"<invoice><id>{iid}</id><fullnumber>{fullnumber or iid}</fullnumber>"
        f"<type>{type_}</type><date>{date}</date>"
        f"<paymentdate>{due}</paymentdate>"
        f"<paymentstate>{payment_state}</paymentstate>"
        f"<currency>{currency}</currency>{parent}"
        f"<netto>{brutto}</netto><brutto>{brutto}</brutto></invoice>"
    )
    return _parse_invoice_fact(ET.fromstring(xml))


def _pay(*, pid, date, value, linked="", linked_expense="", currency=""):
    """A payment node in the shape production emits.

    wFirma carries BOTH link elements on every payment and populates at most
    one; ``linked`` is the receivable link, ``linked_expense`` the payable
    one. A fixture that sets the same id on both describes a document that
    cannot exist, and an earlier one did -- which is why the disclosure pins
    below build the two links separately.
    """
    inv = f"<invoice><id>{linked}</id></invoice>" if linked else ""
    exp = (f"<expense><id>{linked_expense}</id></expense>"
           if linked_expense else "")
    ccy = f"<currency>{currency}</currency>" if currency else ""
    xml = (
        f"<payment><id>{pid}</id><date>{date}</date>"
        f"<value>{value}</value>{ccy}{inv}{exp}</payment>"
    )
    return _parse_payment_fact(ET.fromstring(xml))


def _exp(*, eid, date, brutto, currency="EUR", fullnumber="", payment_date=None,
         correction="", draft="0", is_rejected="0"):
    due = date if payment_date is None else payment_date
    xml = (
        f"<expense><id>{eid}</id><fullnumber>{fullnumber or eid}</fullnumber>"
        f"<date>{date}</date><payment_date>{due}</payment_date>"
        f"<currency>{currency}</currency><correction>{correction}</correction>"
        f"<draft>{draft}</draft><is_rejected>{is_rejected}</is_rejected>"
        f"<netto>{brutto}</netto><brutto>{brutto}</brutto></expense>"
    )
    return _parse_expense_fact(ET.fromstring(xml))


def _meta(name="Synthetic Counterparty Sp. z o.o."):
    return {
        "wfirma_contractor_id": "9000001",
        "name": name,
        "country": "PL",
        "vat_id": "PL0000000000",
    }


def _rows(stmt, ccy):
    return stmt["entries_per_currency"][ccy]


# ── 1. Due date is a first-class, never-substituted column ────────────────

def test_due_date_is_carried_on_every_client_invoice_row():
    stmt = aggregate_statement_from_facts(
        _meta(),
        [_inv(iid="1", date="2026-01-05", paymentdate="2026-02-20",
              brutto="1000.00", fullnumber="INV 1/2026")],
        [], "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    row = [r for r in _rows(stmt, "USD") if r["type"] == "invoice"][0]
    assert row["due_date"] == "2026-02-20"
    # The issue date is never substituted for the due date.
    assert row["due_date"] != row["date"]


def test_missing_due_date_reads_unavailable_and_is_not_aged_either_way():
    stmt = aggregate_statement_from_facts(
        _meta(),
        [_inv(iid="1", date="2026-01-05", paymentdate="", brutto="300.00")],
        [], "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    row = [r for r in _rows(stmt, "USD") if r["type"] == "invoice"][0]
    assert row["due_date"] == ""
    assert row["presentation_status"] == PRESENTATION_STATUS_DUE_UNAVAILABLE
    pos = stmt["position_per_currency"]["USD"]
    assert pos["due_date_unavailable"] == "300.00"
    assert pos["overdue"] == "0.00"
    assert pos["not_due"] == "0.00"


def test_supplier_due_date_comes_from_payment_date_underscore():
    stmt = aggregate_supplier_statement(
        [_exp(eid="1", date="2026-01-05", payment_date="2026-03-01",
              brutto="500.00", fullnumber="EXP 1/2026")],
        [], contractor_meta=_meta(), period=("2026-01-01", "2026-01-31"),
        as_of="2026-01-31",
    )
    row = [r for r in _rows(stmt, "EUR") if r["type"] != "opening_balance"][0]
    assert row["due_date"] == "2026-03-01"


def test_payment_and_bf_rows_carry_no_due_date():
    stmt = aggregate_statement_from_facts(
        _meta(),
        [_inv(iid="1", date="2025-12-01", brutto="1000.00")],
        [_pay(pid="p1", date="2026-01-10", value="100.00", linked="1")],
        "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    rows = _rows(stmt, "USD")
    bf = [r for r in rows if r["type"] == "opening_balance"][0]
    pay = [r for r in rows if r["type"] == "payment"][0]
    assert bf["presentation_status"] == PRESENTATION_STATUS_BF
    assert not bf.get("due_date")
    assert not pay.get("due_date")
    assert pay["presentation_status"] == PRESENTATION_STATUS_APPLIED


# ── 2. Status Conflict — source claim never overrides economics ───────────

def test_source_paid_with_open_remaining_is_conflict_not_paid():
    assert derive_presentation_status(
        entry_type="invoice", remaining=Decimal("120.00"),
        due_date="2026-01-10", as_of="2026-01-31",
        source_payment_state="paid",
    ) == PRESENTATION_STATUS_CONFLICT


def test_conflict_is_suppressed_when_a_correction_explains_the_difference():
    assert derive_presentation_status(
        entry_type="invoice", remaining=Decimal("120.00"),
        due_date="2026-01-10", as_of="2026-01-31",
        source_payment_state="paid", has_explaining_correction=True,
    ) == PRESENTATION_STATUS_OVERDUE


def test_source_paid_with_zero_remaining_is_settled():
    assert derive_presentation_status(
        entry_type="invoice", remaining=Decimal("0"),
        due_date="2026-01-10", as_of="2026-01-31",
        source_payment_state="paid",
    ) == PRESENTATION_STATUS_SETTLED


def test_conflict_reaches_the_rendered_row():
    stmt = aggregate_statement_from_facts(
        _meta(),
        [_inv(iid="1", date="2026-01-05", paymentdate="2026-01-10",
              brutto="900.00", payment_state="paid")],
        [], "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    row = [r for r in _rows(stmt, "USD") if r["type"] == "invoice"][0]
    assert row["presentation_status"] == PRESENTATION_STATUS_CONFLICT


# ── 3. Credit / offset and the gross − credits = net identity ─────────────

def test_credit_note_row_reads_credit_offset():
    stmt = aggregate_statement_from_facts(
        _meta(),
        [
            _inv(iid="1", date="2026-01-05", paymentdate="2026-01-10",
                 brutto="1000.00", fullnumber="INV 1/2026"),
            _inv(iid="2", date="2026-01-20", brutto="-1000.00",
                 type_="correction", fullnumber="COR 1/2026"),
        ],
        [], "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    statuses = {r.get("presentation_status") for r in _rows(stmt, "USD")}
    assert PRESENTATION_STATUS_CREDIT in statuses


def test_gross_minus_credits_equals_net_and_offset_is_flagged():
    """The 'Net 0 beside Overdue 52,940' defect, in miniature.

    A fully credited but overdue document must publish the offsetting credit
    in the SAME position block as the gross overdue figure.
    """
    stmt = aggregate_statement_from_facts(
        _meta(),
        [
            _inv(iid="1", date="2025-01-05", paymentdate="2025-02-05",
                 brutto="52940.00", fullnumber="INV 1/2025",
                 payment_state="paid"),
            _inv(iid="2", date="2025-03-01", brutto="-52940.00",
                 type_="correction", fullnumber="COR 1/2025"),
        ],
        [], "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    pos = stmt["position_per_currency"]["USD"]
    gross = Decimal(pos["gross_exposure"])
    credits = Decimal(pos["customer_credits"])
    net = Decimal(pos["net_position"])
    assert gross - credits == net
    assert net == Decimal("0.00")
    assert gross > 0
    # The gross overdue figure is still published — it is not smoothed away.
    assert Decimal(pos["overdue"]) == gross
    assert pos["aging_basis"] == AGING_BASIS_GROSS
    assert pos["presentation_state"] == "offset"


def test_aging_basis_is_declared_on_every_statement():
    stmt = aggregate_statement_from_facts(
        _meta(), [_inv(iid="1", date="2026-01-05", brutto="10.00")], [],
        "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    assert stmt["aging_basis"] == AGING_BASIS_GROSS
    for block in stmt["position_per_currency"].values():
        assert block["aging_basis"] == AGING_BASIS_GROSS


def test_presentation_state_vocabulary():
    assert presentation_state("100", "0") == "open"
    assert presentation_state("100", "100") == "offset"
    assert presentation_state("0", "50") == "credit"
    assert presentation_state("0", "0") == "clear"


# ── 4. Multi-currency independence ────────────────────────────────────────

def test_currency_legs_are_independent_and_never_fx_summed():
    stmt = aggregate_statement_from_facts(
        _meta(),
        [
            _inv(iid="1", date="2026-01-05", paymentdate="2026-01-10",
                 brutto="600.00", currency="EUR", fullnumber="INV E/2026"),
            _inv(iid="2", date="2026-01-06", paymentdate="2026-01-10",
                 brutto="900.00", currency="USD", fullnumber="INV U/2026"),
            _inv(iid="3", date="2026-01-20", brutto="-900.00",
                 currency="USD", type_="correction", fullnumber="COR U/2026"),
        ],
        [], "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    assert stmt["currencies"] == ["EUR", "USD"]
    pos = stmt["position_per_currency"]
    assert Decimal(pos["EUR"]["net_position"]) == Decimal("600.00")
    assert Decimal(pos["USD"]["net_position"]) == Decimal("0.00")
    assert pos["EUR"]["presentation_state"] == "open"
    assert pos["USD"]["presentation_state"] == "offset"
    # No leg carries the other leg's money, and no combined figure exists.
    assert "multi" not in pos
    assert "multi" not in stmt["entries_per_currency"]
    # A fully offset USD leg does not clear the open EUR leg.
    assert stmt["presentation_state"] == "open"


def test_portfolio_rollup_is_the_most_open_leg():
    assert presentation_state_from_maps(
        {"EUR": Decimal("100"), "USD": Decimal("100")},
        {"EUR": Decimal("0"),   "USD": Decimal("100")},
    ) == "open"
    assert presentation_state_from_maps(
        {"EUR": Decimal("100"), "USD": Decimal("100")},
        {"EUR": Decimal("100"), "USD": Decimal("100")},
    ) == "offset"
    assert presentation_state_from_maps({}, {}) == "clear"


# ── 5. Opening / closing, and contiguous months ───────────────────────────

def test_opening_plus_debits_minus_credits_equals_closing():
    stmt = aggregate_statement_from_facts(
        _meta(),
        [
            _inv(iid="1", date="2025-12-15", brutto="1000.00"),
            _inv(iid="2", date="2026-01-10", brutto="500.00"),
        ],
        [
            _pay(pid="p1", date="2025-12-20", value="200.00", linked="1"),
            _pay(pid="p2", date="2026-01-15", value="100.00", linked="2"),
        ],
        "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    t = stmt["totals_per_currency"]["USD"]
    assert (
        Decimal(t["opening_balance"])
        + Decimal(t["period_debits"])
        - Decimal(t["period_credits"])
        == Decimal(t["closing_balance"])
    )


def test_previous_month_closing_equals_next_month_opening():
    invoices = [
        _inv(iid="1", date="2025-12-15", brutto="1000.00"),
        _inv(iid="2", date="2026-01-10", brutto="500.00"),
        _inv(iid="3", date="2026-02-04", brutto="250.00"),
    ]
    payments = [
        _pay(pid="p1", date="2025-12-20", value="200.00", linked="1"),
        _pay(pid="p2", date="2026-01-15", value="100.00", linked="2"),
    ]
    jan = aggregate_statement_from_facts(
        _meta(), invoices, payments, "2026-01-31", ("2026-01-01", "2026-01-31"))
    feb = aggregate_statement_from_facts(
        _meta(), invoices, payments, "2026-02-28", ("2026-02-01", "2026-02-28"))
    assert (
        jan["totals_per_currency"]["USD"]["closing_balance"]
        == feb["totals_per_currency"]["USD"]["opening_balance"]
    )


def test_position_is_not_the_same_question_as_closing_balance():
    """A period closing figure must never be substituted for the as-of
    position: they answer different questions and are separately published."""
    stmt = aggregate_statement_from_facts(
        _meta(),
        [_inv(iid="1", date="2025-06-01", paymentdate="2025-07-01",
              brutto="800.00")],
        [], "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    t = stmt["totals_per_currency"]["USD"]
    pos = stmt["position_per_currency"]["USD"]
    # Nothing moved inside January…
    assert Decimal(t["period_debits"]) == Decimal("0.00")
    # …yet the account is 800 open as of the as-of date.
    assert Decimal(pos["gross_exposure"]) == Decimal("800.00")
    assert Decimal(pos["overdue"]) == Decimal("800.00")


# ── 6. Old open items are never hidden ────────────────────────────────────

def test_genuinely_old_open_item_stays_in_the_position():
    stmt = aggregate_statement_from_facts(
        _meta(),
        [_inv(iid="1", date="2021-03-01", paymentdate="2021-04-01",
              brutto="4200.00", fullnumber="INV 1/2021")],
        [], "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    pos = stmt["position_per_currency"]["USD"]
    assert Decimal(pos["gross_exposure"]) == Decimal("4200.00")
    assert Decimal(pos["net_position"]) == Decimal("4200.00")
    aging = stmt["aging_per_currency"]["USD"]
    assert Decimal(aging["b_365_plus"]) == Decimal("4200.00")


# ── 7. Unapplied cash is reported, never netted ───────────────────────────

def test_unapplied_payment_is_reported_outside_the_running_balance():
    stmt = aggregate_statement_from_facts(
        _meta(),
        [_inv(iid="1", date="2026-01-05", brutto="500.00")],
        [_pay(pid="p9", date="2026-01-20", value="77.00", linked="",
              currency="USD")],
        "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    unapplied = stmt["unmatched_payments_per_currency"]["USD"]
    assert len(unapplied) == 1
    assert unapplied[0]["presentation_status"] == PRESENTATION_STATUS_UNAPPLIED
    # It has no due date and no reference to borrow from a document.
    assert unapplied[0]["due_date"] == ""
    assert unapplied[0]["reference"] == ""
    # …and it does not move the closing balance.
    t = stmt["totals_per_currency"]["USD"]
    assert Decimal(t["closing_balance"]) == Decimal("500.00")
    assert all(
        r["type"] != "payment" for r in _rows(stmt, "USD")
    )


# ── 8. Rejected AP documents are absent upstream, not filtered in the UI ──

def test_rejected_expense_is_classified_rejected_at_the_source_rule():
    assert classify_expense_lifecycle("0", "1") == "rejected"
    assert classify_expense_lifecycle("1", "0") == "draft"
    assert classify_expense_lifecycle("0", "0") == "booked"


def test_supplier_statement_publishes_lifecycle_so_the_ui_never_re_filters():
    stmt = aggregate_supplier_statement(
        [_exp(eid="1", date="2026-01-05", brutto="400.00",
              fullnumber="EXP 1/2026")],
        [], contractor_meta=_meta(), period=("2026-01-01", "2026-01-31"),
        as_of="2026-01-31",
    )
    pos = stmt["position_per_currency"]["EUR"]
    assert Decimal(pos["gross_exposure"]) - Decimal(pos["supplier_credits"]) \
        == Decimal(pos["net_position"])
    assert pos["aging_basis"] == AGING_BASIS_GROSS


# ── 9. Forbidden source fields never reach a rendered row ─────────────────

@pytest.mark.parametrize("build", ["client", "supplier"])
def test_no_forbidden_source_field_leaks_onto_an_entry(build):
    if build == "client":
        stmt = aggregate_statement_from_facts(
            _meta(),
            [_inv(iid="1", date="2026-01-05", brutto="100.00",
                  payment_state="paid")],
            [_pay(pid="p1", date="2026-01-20", value="40.00", linked="1")],
            "2026-01-31", ("2026-01-01", "2026-01-31"),
        )
    else:
        stmt = aggregate_supplier_statement(
            [_exp(eid="1", date="2026-01-05", brutto="100.00")],
            [_pay(pid="p1", date="2026-01-20", value="40.00", linked="1",
                  currency="EUR")],
            contractor_meta=_meta(), period=("2026-01-01", "2026-01-31"),
            as_of="2026-01-31",
        )
    leaks = []
    for ccy, rows in stmt["entries_per_currency"].items():
        for r in rows:
            leaks += [(ccy, f) for f in FORBIDDEN_ENTRY_FIELDS if f in r]
    assert leaks == []


# ── 10. Screen and PDF share ONE read model ───────────────────────────────

def test_pdf_renderer_holds_no_second_accounting_authority():
    src = (Path(__file__).resolve().parents[1] / "app" / "services"
           / "statement_pdf_renderer.py").read_text(encoding="utf-8")

    # The aggregators are the renderer's INPUT. Naming them in a docstring or
    # in a "this dict must come from X" error message is correct and expected;
    # *calling* or *importing* one would mean the PDF rebuilds the statement
    # instead of rendering it. So the assertion is about call sites.
    for builder in ("aggregate_statement", "aggregate_supplier_statement"):
        assert not re.search(r"%s\s*\(" % builder, src), (
            f"statement_pdf_renderer calls {builder!r} — the PDF must render "
            f"the dict the screen already read, never rebuild it"
        )
        assert not re.search(r"^\s*(?:from|import).*%s" % builder,
                             src, re.M), (
            f"statement_pdf_renderer imports {builder!r}"
        )

    # These are financial authorities outright. They may not appear at all —
    # not as a call, not as an import, not as a mention.
    for forbidden in (
        "remaining_after_payments", "match_payments_to_invoices",
        "match_payments_to_expenses", "classify_expense_lifecycle",
    ):
        assert forbidden not in src, (
            f"statement_pdf_renderer recomputes {forbidden!r} — the PDF must "
            f"render the same dict the screen reads, never rebuild it"
        )


def test_position_block_is_published_for_both_sides():
    """One position contract ⇒ one renderer can serve screen and PDF."""
    client = aggregate_statement_from_facts(
        _meta(), [_inv(iid="1", date="2026-01-05", brutto="100.00")], [],
        "2026-01-31", ("2026-01-01", "2026-01-31"))
    supplier = aggregate_supplier_statement(
        [_exp(eid="1", date="2026-01-05", brutto="100.00")], [],
        contractor_meta=_meta(), period=("2026-01-01", "2026-01-31"),
        as_of="2026-01-31")
    shared = {
        "gross_exposure", "credit_balance", "net_position", "overdue",
        "not_due", "due_date_unavailable", "aging_basis", "presentation_state",
    }
    for stmt in (client, supplier):
        assert stmt["position_per_currency"]
        for block in stmt["position_per_currency"].values():
            assert shared <= set(block)


# ── 11. The frontend is not a second accounting authority ─────────────────

_FINANCIAL_JSX_FIELDS = (
    "gross_exposure", "net_position", "credit_balance", "customer_credits",
    "supplier_credits", "opening_balance", "closing_balance", "period_debits",
    "period_credits", "running_balance", "outstanding", "net_payable",
)


def _js_code_only(line):
    """Return ``line`` with string content removed so a scan sees CODE only.

    A test id such as ``ldg-stmt-outstanding-${ccy}`` contains a hyphen next to
    a financial word and would otherwise read as subtraction. Quoted text is
    dropped entirely; inside a template literal the interpolations are kept,
    because ``${a - b}`` really is arithmetic.
    """
    out, i, n = [], 0, len(line)
    while i < n:
        ch = line[i]
        if ch in "'\"":
            i += 1
            while i < n and line[i] != ch:
                i += 2 if line[i] == "\\" else 1
            i += 1
        elif ch == "`":
            i += 1
            while i < n and line[i] != "`":
                if line[i] == "\\":
                    i += 2
                elif line[i] == "$" and i + 1 < n and line[i + 1] == "{":
                    depth, i = 1, i + 2
                    while i < n and depth:
                        if line[i] == "{":
                            depth += 1
                        elif line[i] == "}":
                            depth -= 1
                            if not depth:
                                break
                        out.append(line[i])
                        i += 1
                    i += 1
                else:
                    i += 1
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def test_no_arithmetic_on_financial_fields_in_the_ledger_jsx():
    """A financial field may be read and formatted, never combined."""
    pattern = re.compile(
        r"(?:%s)\s*(?:[-+*/]|\)\s*[-+*/])" % "|".join(_FINANCIAL_JSX_FIELDS)
    )
    offenders = []
    for name in ("ledgers-page.jsx", "accounting-hub.jsx"):
        src = (V2 / name).read_text(encoding="utf-8")
        for lineno, line in enumerate(src.splitlines(), 1):
            if pattern.search(_js_code_only(line)):
                offenders.append(f"{name}:{lineno}: {line.strip()}")
    assert offenders == [], (
        "financial arithmetic in JSX - the frontend must not become a second "
        "accounting authority:\n" + "\n".join(offenders)
    )


def test_ledger_jsx_never_reads_a_forbidden_source_field():
    """The ledger surface may not read a source lifecycle flag at all.

    Scope note: this pins ``ledgers-page.jsx`` — the ledger / statement read
    model, where a status is an economic claim and must arrive as
    ``presentation_status``. ``accounting-hub.jsx`` also renders the wFirma
    *document register* (``GET /api/v1/accounting/{type}``, "Loading from
    wFirma..."), which lists source documents with their own source flag in a
    column labelled "wFirma Payment". That is a mirror of the source, not an
    EJ economic position, and is deliberately outside this contract.
    """
    offenders = []
    src = (V2 / "ledgers-page.jsx").read_text(encoding="utf-8")
    for lineno, line in enumerate(src.splitlines(), 1):
        if line.lstrip().startswith("//"):
            continue
        for f in ("paymentstate", "alreadypaid", "payment_state"):
            if re.search(r"[.\[]\s*['\"]?%s\b" % f, line):
                offenders.append(f"ledgers-page.jsx:{lineno}: {line.strip()}")
    assert offenders == [], (
        "source lifecycle field read in the ledger UI - economic truth comes "
        "from presentation_status only:\n" + "\n".join(offenders)
    )


def test_source_payment_flag_is_labelled_as_a_source_fact_in_the_register():
    """Where the raw source flag IS shown, it is named as the source's."""
    src = (V2 / "accounting-hub.jsx").read_text(encoding="utf-8")
    assert "'wFirma Payment'" in src, (
        "the wFirma document register must label the source lifecycle column "
        "as the source's own flag, never as an EJ economic status"
    )


def test_multi_sentinel_is_never_rendered_as_a_currency():
    """``multi`` is a backend sentinel. Branching on it is fine; printing it
    to an operator is the defect."""
    offenders = []
    for name in ("ledgers-page.jsx", "accounting-hub.jsx"):
        src = (V2 / name).read_text(encoding="utf-8")
        for lineno, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            for m in re.finditer(r"""['"]multi['"]""", line):
                before = line[:m.start()].rstrip()
                # A comparison against the sentinel is correct usage.
                if before.endswith(("===", "!==", "==", "!=", "case")):
                    continue
                offenders.append(f"{name}:{lineno}: {stripped}")
    assert offenders == [], (
        "the 'multi' sentinel is displayed to the operator:\n"
        + "\n".join(offenders)
    )


# ── 12. Row status vocabulary is exactly the published one ────────────────

def test_row_status_vocabulary_is_closed():
    published = {
        PRESENTATION_STATUS_BF, PRESENTATION_STATUS_NOT_DUE,
        PRESENTATION_STATUS_OVERDUE, PRESENTATION_STATUS_SETTLED,
        PRESENTATION_STATUS_CREDIT, PRESENTATION_STATUS_APPLIED,
        PRESENTATION_STATUS_UNAPPLIED, PRESENTATION_STATUS_DUE_UNAVAILABLE,
        PRESENTATION_STATUS_CONFLICT,
    }
    stmt = aggregate_statement_from_facts(
        _meta(),
        [
            _inv(iid="1", date="2025-12-01", brutto="1000.00",
                 paymentdate="2025-12-31"),
            _inv(iid="2", date="2026-01-05", brutto="400.00",
                 paymentdate="2026-03-01"),
            _inv(iid="3", date="2026-01-06", brutto="200.00", paymentdate=""),
            _inv(iid="4", date="2026-01-07", brutto="-50.00",
                 type_="correction"),
        ],
        [_pay(pid="p1", date="2026-01-20", value="100.00", linked="2")],
        "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    seen = {r["presentation_status"] for r in _rows(stmt, "USD")
            if r.get("presentation_status")}
    assert seen <= published
    assert PRESENTATION_STATUS_BF in seen
    assert PRESENTATION_STATUS_NOT_DUE in seen
    assert PRESENTATION_STATUS_DUE_UNAVAILABLE in seen


# ── 13. The due-date-unavailable amount is presented, never dropped ──────
#
# An open amount whose due date is missing at source is neither overdue nor
# not-due. If a surface prints Overdue and Not Due but omits it, the split
# silently fails to add up to the gross figure standing beside it and the
# operator reads a smaller exposure than exists. These pin the *presentation*
# of a backend-emitted figure; nothing here derives it.

def test_aging_split_plus_unavailable_reconciles_to_gross():
    """Overdue + Not Due + No Due Date == Gross - the footnote identity."""
    stmt = aggregate_statement_from_facts(
        _meta(),
        [
            _inv(iid="1", date="2025-11-01", paymentdate="2025-12-01",
                 brutto="1000.00"),
            _inv(iid="2", date="2026-01-05", paymentdate="2026-03-01",
                 brutto="400.00"),
            _inv(iid="3", date="2026-01-06", paymentdate="", brutto="250.00"),
        ],
        [], "2026-01-31", ("2026-01-01", "2026-01-31"),
    )
    pos = stmt["position_per_currency"]["USD"]
    assert pos["overdue"] == "1000.00"
    assert pos["not_due"] == "400.00"
    assert pos["due_date_unavailable"] == "250.00"
    total = (Decimal(pos["overdue"]) + Decimal(pos["not_due"])
             + Decimal(pos["due_date_unavailable"]))
    assert total == Decimal(pos["gross_exposure"]) == Decimal("1650.00")


def test_supplier_aging_split_plus_unavailable_reconciles_to_gross():
    stmt = aggregate_supplier_statement(
        [
            _exp(eid="1", date="2025-11-01", payment_date="2025-12-01",
                 brutto="700.00"),
            _exp(eid="2", date="2026-01-06", payment_date="", brutto="300.00"),
        ],
        [], contractor_meta=_meta(), period=("2026-01-01", "2026-01-31"),
        as_of="2026-01-31",
    )
    pos = stmt["position_per_currency"]["EUR"]
    assert pos["due_date_unavailable"] == "300.00"
    total = (Decimal(pos["overdue"]) + Decimal(pos["not_due"])
             + Decimal(pos["due_date_unavailable"]))
    assert total == Decimal(pos["gross_exposure"]) == Decimal("1000.00")


def test_every_surface_that_shows_not_due_also_shows_no_due_date():
    """Source-grep pin: the .jsx is served verbatim, so grepping it IS the test."""
    src = (V2 / "ledgers-page.jsx").read_text(encoding="utf-8")
    for testid in ("ldg-client-duena-", "ldg-sup-duena-",
                   "ldg-client-leg-duena-"):
        assert testid in src, (
            testid + " missing - a surface prints Overdue and Not Due without "
            "the amount that is neither"
        )
    # The roster header must carry the column, not just the cell.
    assert src.count("'No Due Date'") >= 3, (
        "client roster, supplier roster and both MA bucket tables must each "
        "name the column in their header array"
    )
    # And the backend field must be what feeds it.
    assert "due_date_unavailable" in src


def test_roster_footnotes_state_the_full_identity():
    """The footnote may not promise a two-way split that does not add up."""
    src = (V2 / "ledgers-page.jsx").read_text(encoding="utf-8")
    for tail in (u"Overdue + Not Due + No Due Date = Gross AR",
                 u"Overdue + Not Due + No Due Date = Gross Payable"):
        assert tail in src, "footnote omits the No Due Date term: " + tail
    assert u"Overdue + Not Due = Gross" not in src, (
        "a footnote still claims the two-term identity"
    )


def test_per_leg_lines_do_not_print_the_currency_code_twice():
    """A leg line prints its own code, so it must format the amount alone."""
    src = (V2 / "ledgers-page.jsx").read_text(encoding="utf-8")
    assert "amount: (v) =>" in src, (
        "LDG_FMT.amount is the currency-free formatter the per-leg lines need"
    )
    assert "{LDG_FMT.amount(amt)}" in src
    assert "{ccy}</span>\n          {LDG_FMT.money(amt, ccy)}" not in src, (
        "per-leg line prints the code and then money() prints it again "
        "(the EUREUR defect)"
    )


def test_empty_roster_colspan_matches_the_header_width():
    """A stale colSpan leaves the empty-state cell short of the new column."""
    src = (V2 / "ledgers-page.jsx").read_text(encoding="utf-8")
    header = re.search(
        r"\{\[('Client',[^\]]*)\]\.map\(\(h\) =>", src)
    assert header, "client roster header array not found"
    width = len(re.findall(r"'[^']*'", header.group(1)))
    assert re.search(
        r"colSpan=\{%d\} data-testid=\"ldg-clients-empty\"" % width, src
    ), "ldg-clients-empty colSpan does not match the %d-column header" % width


# ── 14. The PDF prints the same aging identity as the screen ─────────
#
# The screen and the PDF read the same backend dict, but they are two renderers
# and either can silently omit a term. Wherever a surface prints Overdue and
# Not due beside a gross figure, it must also print the amount that is neither,
# or the reader is shown a split that does not add up to the number above it.

_PDF = Path(__file__).resolve().parents[1] / "app" / "services" / "statement_pdf_renderer.py"


def test_pdf_portfolio_cards_print_the_no_due_date_term():
    """The MA Receivables / Payables cards must not stop at Overdue + Not due."""
    src = _PDF.read_text(encoding="utf-8")
    for summary in ("ar_sum", "ap_sum"):
        assert (
            summary + '.get("due_date_unavailable")' in src
        ), (
            summary + " card prints Overdue and Not due beside a gross figure "
            "without the term that reconciles them"
        )
    assert src.count('"No due date"') >= 2, (
        "both portfolio cards must label the row"
    )


def test_pdf_per_counterparty_aging_card_keeps_the_term():
    """The statement aging card had this from the start; it must not regress."""
    src = _PDF.read_text(encoding="utf-8")
    assert 'aging.get("due_date_unavailable")' in src
    assert '"due date n/a"' in src or "'due date n/a'" in src


def test_pdf_and_screen_name_the_same_backend_field():
    """Neither renderer may invent its own key for the same figure."""
    pdf = _PDF.read_text(encoding="utf-8")
    jsx = (V2 / "ledgers-page.jsx").read_text(encoding="utf-8")
    assert "due_date_unavailable" in pdf and "due_date_unavailable" in jsx, (
        "one renderer has drifted onto a different field name"
    )


def test_pdf_renderer_does_no_aging_arithmetic():
    """The PDF is a renderer, not a second accounting authority.

    It may read and print the backend figures; it may not add, subtract or
    otherwise re-derive the aging split it displays.
    """
    src = _PDF.read_text(encoding="utf-8")
    for line in src.splitlines():
        if "due_date_unavailable" not in line:
            continue
        code = line.split("#")[0]
        for op in (" + ", " - ", " -= ", " += "):
            assert op not in code, (
                "PDF renderer performs arithmetic on due_date_unavailable: "
                + line.strip()
            )


# ── 15. The exposure tables locate the no-due-date amount ───────────
#
# A per-counterparty row that prints Gross beside Overdue and Credits invites
# the reader to infer that whatever is not overdue is not-due. For a document
# carrying no due date at all that inference is wrong, and the row gives no
# hint beyond an em dash in "Oldest due". The column makes the amount visible
# where the reader is actually looking.

def test_exposure_tables_carry_the_no_due_date_column():
    src = _PDF.read_text(encoding="utf-8")
    assert src.count('"No due date",') >= 2, (
        "customer and supplier exposure tables must both name the column"
    )
    assert src.count('r.get("due_date_unavailable") or "0.00"') >= 2, (
        "both exposure row builders must read the backend field"
    )


def test_exposure_column_widths_still_fit_the_frame():
    """A4 less 15mm margins each side leaves 180mm; a wider table clips."""
    src = _PDF.read_text(encoding="utf-8")
    widths = re.findall(
        r"\[46 \* mm(?:, \d+ \* mm)+\]", src)
    assert widths, "exposure column-width list not found"
    for w in widths:
        total = sum(int(n) for n in re.findall(r"(\d+) \* mm", w))
        assert total <= 180, (
            "exposure table is %dmm wide, frame is 180mm" % total
        )


# -- 16. The gross caption and the activity/position split ----------------
#
# Both were found by looking at rendered pages, not at JSON. An aging card
# prints a GROSS split: a fully offset supplier -- gross 2000.00
# against credits 2000.00, net payable 0.00 -- and its card read "91-180
# 2000.00 / Total 2000.00" with nothing on the card saying that figure is
# before credits. Separately, the supplier statement held ACTIVITY (opening,
# period debits, period credits, closing) and POSITION (gross, credits,
# payments applied, outstanding, net payable) under one heading, and because
# closing balance equals net payable in both fixtures the conflation was
# invisible in the numbers themselves.

_MIDDOT = chr(0xB7)
_GROSS_CAPTION = "gross " + _MIDDOT + " before credits"


def _rendered_text(pdf_bytes):
    from io import BytesIO

    from pypdf import PdfReader

    return chr(10).join(
        (p.extract_text() or "") for p in PdfReader(BytesIO(pdf_bytes)).pages
    )


def _one_invoice_ar():
    return aggregate_statement_from_facts(
        _meta(),
        [_inv(iid="1", date="2025-11-05", paymentdate="2025-12-05",
              brutto="900.00", fullnumber="INV 5/2025")],
        [], "2026-01-31", ("2026-01-01", "2026-01-31"),
    )


def _one_expense_ap():
    """AP statement whose CLOSING and NET POSITION deliberately differ.

    `as_of` sits a month past the period end, so the February expense counts
    towards the position but not towards the January closing balance. Any
    test that substitutes one figure for the other therefore has to fail.
    """
    return aggregate_supplier_statement(
        [_exp(eid="1", date="2026-01-05", brutto="1000.00",
              fullnumber="EXP 1/2026"),
         _exp(eid="2", date="2026-02-10", brutto="400.00",
              fullnumber="EXP 2/2026")],
        [], contractor_meta=_meta(),
        period=("2026-01-01", "2026-01-31"), as_of="2026-02-28",
    )


def test_every_aging_surface_says_the_split_is_before_credits():
    """Client statement, supplier statement, management grid -- all three.

    This was a count of the caption in the renderer source until the two
    per-currency builders were consolidated into one. Counting copies of a
    caption measures how many renderers exist, not what a reader sees, so it
    went red for the RIGHT change. The invariant that actually matters is
    that the caption reaches every RENDERED surface -- asserted here on real
    aggregator output rather than a hand-written dict.
    """
    from app.services.statement_pdf_renderer import (
        render_management_analysis_pdf,
        render_statement_pdf,
        render_supplier_statement_pdf,
    )

    # The management grid reads the ANALYTICS bodies, not statement dicts;
    # its own fixtures are reused so there is one shape authority per surface.
    from test_management_analysis_pdf import _ap as _ma_ap, _ar as _ma_ar

    ar, ap = _one_invoice_ar(), _one_expense_ap()
    ma_ar, ma_ap = _ma_ar(), _ma_ap()
    assert ar["currencies"] and ap["currencies"], "fixture must not be empty"
    assert ma_ar["currency_summaries"] and ma_ap["currency_summaries"], (
        "an empty grid would pass vacuously"
    )

    surfaces = {
        "client statement":   render_statement_pdf(ar),
        "supplier statement": render_supplier_statement_pdf(ap),
        "management grid":    render_management_analysis_pdf(ma_ar, ma_ap),
    }
    for name, pdf in surfaces.items():
        assert _GROSS_CAPTION in _rendered_text(pdf), (
            "aging is a gross split; the %s must say so where it is read"
            % name
        )


def test_supplier_statement_separates_activity_from_position():
    src = _PDF.read_text(encoding="utf-8")
    assert '_kv_card("Period activity"' in src, "period movement needs its own card"
    assert '_kv_card("Position"' in src, "as-of position needs its own card"
    assert '"Period statement"' not in src, (
        "the mixed activity/position card must not come back"
    )


def test_activity_card_holds_no_position_figure():
    """Opening and closing answer a different question than net payable."""
    src = _PDF.read_text(encoding="utf-8")
    start = src.index('_kv_card("Period activity"')
    end = src.index('_kv_card("Position"', start)
    block = src[start:end]
    for key in ("gross_payable", "net_payable", "supplier_credits",
                "payments_applied", "outstanding"):
        assert key not in block, (
            "%s is a position figure, not period movement" % key
        )


def test_position_card_is_dated_and_names_the_credit_relationship():
    src = _PDF.read_text(encoding="utf-8")
    assert "gross less credits " + _MIDDOT + " as of %s" in src, (
        "position is as-of a date and is gross net of credits; say both"
    )


def test_kv_card_takes_a_subtitle():
    src = _PDF.read_text(encoding="utf-8")
    assert 'subtitle: str = ""' in src, "_kv_card must accept a subtitle"
    assert "if subtitle:" in src, "and must render it beneath the title"


def test_closing_balance_never_falls_back_to_a_position_figure():
    """A period figure may only fall back to another period figure.

    Supplier `net_payable` and `outstanding` are both as-of position
    (ledger_aggregator.py:1043-1045); printing either under "Closing
    balance" looks entirely correct while answering another question.
    Client `outstanding` is the aggregator's own alias for the closing
    itself (:1583), so reading it substitutes nothing.
    """
    src = _PDF.read_text(encoding="utf-8")
    assert 'totals.get("closing_balance") or totals.get("net_payable")' \
        not in src, "net payable is a position figure, not a period one"

    # The per-currency section is now ONE shared builder serving both sides
    # (`_supplier_currency_flowables` is gone), so the window is anchored
    # on the surviving authority instead of the retired copy.
    start = src.index("def _currency_section_flowables")
    end = src.index("def _empty_notice_flowables", start)
    assert 'totals.get("closing_balance") or totals.get(' \
        not in src[start:end], (
            "on the supplier statement every alternative to closing balance "
            "is a position figure"
        )

    # Behavioural half: a supplier whose closing balance and net payable
    # differ must print the CLOSING figure under "Closing balance". A
    # substitution reads as entirely correct in the source, so the figure
    # itself is checked on rendered output.
    from app.services.statement_pdf_renderer import render_supplier_statement_pdf

    ap = _one_expense_ap()
    ccy = ap["currencies"][0]
    totals = ap["totals_per_currency"][ccy]
    position = ap["position_per_currency"][ccy]
    assert Decimal(totals["closing_balance"]) != Decimal(position["net_position"]), (
        "fixture must make the two figures differ, else the test is vacuous"
    )
    text = _rendered_text(render_supplier_statement_pdf(ap))
    window = text[text.index("Closing balance"):][:80]
    assert totals["closing_balance"] in window, (
        "closing balance must print the period figure, not a position one"
    )


# ---------------------------------------------------------------------------
# The no-link sentinel, pinned with PRODUCTION-SHAPED rows
#
# financial_reporting.sqlite stores ``correction_of_id = '0'`` for "no parent"
# on the overwhelming majority of rows, where the review fixture stores ``''``.
# That single character is why fixture-based acceptance was blind to this
# class: ``'0'`` is truthy, so an unnormalised local fact claims a parent that
# does not exist. Every pin below therefore feeds ``'0'`` deliberately.
# ---------------------------------------------------------------------------

_NO_PARENT_SENTINELS = (None, "", "  ", "0")


@pytest.mark.parametrize("sentinel", _NO_PARENT_SENTINELS)
def test_local_facts_treat_the_zero_sentinel_as_no_parent(sentinel):
    """None / "" / "0" all mean no parent, on both local converters."""
    inv = reporting_row_to_invoice_fact(
        {"invoice_id": "800100", "invoice_number": "FV/1", "currency": "EUR",
         "net": "100.00", "gross": "123.00", "issue_date": "2026-07-01",
         "due_date": "2026-07-31", "document_type": "normal",
         "correction_of_id": sentinel}
    )
    assert inv["correction_of_id"] == ""

    exp = reporting_row_to_expense_fact(
        {"expense_id": "900100", "document_number": "EXP/1", "currency": "EUR",
         "net": "100.00", "gross": "123.00", "issue_date": "2026-07-01",
         "due_date": "2026-07-31", "document_type": "normal",
         "document_status": "booked", "correction_of_id": sentinel}
    )
    assert exp["correction_of_id"] == ""
    assert exp["parent_id"] == ""
    assert exp["correction"] == "0", (
        "a row with no parent is not a correction; '0' is truthy, so deriving "
        "this flag from the raw column marks almost every AP row corrected"
    )


def test_local_facts_keep_a_real_parent_link():
    """Normalising the sentinel must not erase genuine correction linkage."""
    inv = reporting_row_to_invoice_fact(
        {"invoice_id": "800101", "invoice_number": "FVK/1", "currency": "EUR",
         "net": "-30.00", "gross": "-36.90", "issue_date": "2026-07-20",
         "due_date": "2026-08-19", "document_type": "correction",
         "correction_of_id": "800100"}
    )
    assert inv["correction_of_id"] == "800100"

    exp = reporting_row_to_expense_fact(
        {"expense_id": "900101", "document_number": "EXP/2", "currency": "EUR",
         "net": "-20.00", "gross": "-24.60", "issue_date": "2026-07-10",
         "due_date": "2026-07-31", "document_type": "correction",
         "document_status": "booked", "correction_of_id": "900100"}
    )
    assert exp["correction_of_id"] == "900100"
    assert exp["parent_id"] == "900100"
    assert exp["correction"] == "1"


def test_local_and_live_agree_on_the_sentinel():
    """One rule, one implementation - the local adapter defers to the live one."""
    for sentinel in _NO_PARENT_SENTINELS:
        assert _normalize_doc_link_id(sentinel) == ""
        assert reporting_row_to_invoice_fact(
            {"correction_of_id": sentinel})["correction_of_id"] == ""
    assert _normalize_doc_link_id("800100") == "800100"


@pytest.mark.parametrize("sentinel", ["", "0"])
def test_no_parent_row_renders_a_blank_reference_on_both_sides(sentinel):
    """The Reference column must never print the sentinel as a document id.

    Rendered by ``ledgers-page.jsx`` as ``{e.reference || '-'}``, so a literal
    ``"0"`` reaches the operator as a document reference. Refusing to hide it
    in the renderer is the point: the repair belongs in the fact adapter.
    """
    exp = reporting_row_to_expense_fact(
        {"expense_id": "900100", "document_number": "EXP/1",
         "supplier_id": "950001", "supplier_name": "Synthetic Supplier BV",
         "currency": "EUR", "net": "100.00", "gross": "123.00",
         "issue_date": "2026-07-01", "due_date": "2026-07-31",
         "document_type": "normal", "document_status": "booked",
         "correction_of_id": sentinel}
    )
    ap = aggregate_supplier_statement(
        [exp], [],
        contractor_meta={"id": "950001", "name": "Synthetic Supplier BV"},
        period=("2026-07-01", "2026-08-18"), as_of="2026-08-18",
    )
    assert [e["reference"] for e in ap["entries_per_currency"]["EUR"]] == [""]

    inv = reporting_row_to_invoice_fact(
        {"invoice_id": "800100", "invoice_number": "FV/1",
         "contractor_id": "940001", "contractor_name": "Synthetic Client BV",
         "currency": "EUR", "net": "200.00", "gross": "246.00",
         "issue_date": "2026-07-01", "due_date": "2026-07-31",
         "document_type": "normal", "correction_of_id": sentinel}
    )
    ar = aggregate_statement_from_facts(
        {"wfirma_contractor_id": "940001", "name": "Synthetic Client BV"},
        [inv], [], "2026-08-18", ("2026-07-01", "2026-08-18"),
    )
    assert [e["reference"] for e in ar["entries_per_currency"]["EUR"]] == [""]


def test_the_sentinel_moves_no_money():
    """The repair is presentation-only: no monetary leaf may move.

    Same economic facts, only the stored no-parent sentinel differs. Every
    total, aging bucket, opening, closing and running balance must be
    byte-identical between the two runs; if one moves, an accounting authority
    is reading the correction linkage and the change is no longer cosmetic.
    """
    def money(body):
        out = {}

        def walk(o, path=""):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k not in ("reference", "correction"):
                        walk(v, "{}.{}".format(path, k))
            elif isinstance(o, (list, tuple)):
                for i, v in enumerate(o):
                    walk(v, "{}[{}]".format(path, i))
            elif isinstance(o, (int, float, Decimal)) and not isinstance(o, bool):
                out[path] = str(o)
            elif isinstance(o, str) and o.strip() and o.replace(
                    "-", "").replace(".", "").isdigit():
                out[path] = o

        walk(body)
        return out

    def rows(sentinel):
        return [
            {"expense_id": "900100", "document_number": "EXP/1",
             "supplier_id": "950001", "supplier_name": "Synthetic Supplier BV",
             "currency": "EUR", "net": "1000.00", "gross": "1230.00",
             "issue_date": "2026-07-02", "due_date": "2026-07-31",
             "document_type": "normal", "document_status": "booked",
             "correction_of_id": sentinel},
            {"expense_id": "900101", "document_number": "EXP/2",
             "supplier_id": "950001", "supplier_name": "Synthetic Supplier BV",
             "currency": "EUR", "net": "-200.00", "gross": "-246.00",
             "issue_date": "2026-07-10", "due_date": "2026-07-31",
             "document_type": "correction", "document_status": "booked",
             "correction_of_id": "900100"},
            {"expense_id": "900102", "document_number": "EXP/3",
             "supplier_id": "950001", "supplier_name": "Synthetic Supplier BV",
             "currency": "USD", "net": "500.00", "gross": "500.00",
             "issue_date": "2026-07-15", "due_date": "",
             "document_type": "normal", "document_status": "booked",
             "correction_of_id": sentinel},
        ]

    def run(sentinel):
        return aggregate_supplier_statement(
            [reporting_row_to_expense_fact(r) for r in rows(sentinel)], [],
            contractor_meta={"id": "950001", "name": "Synthetic Supplier BV"},
            period=("2026-07-01", "2026-08-18"), as_of="2026-08-18",
        )

    assert money(run("0")) == money(run("")), (
        "a no-parent sentinel changed a monetary figure - the correction "
        "linkage is feeding an accounting authority, not just presentation"
    )


# ── aging total: ONE meaning across both statements ───────────────────────
# Measured divergence on identical facts: the supplier statement reported an
# aging total of 10104.00 and the client statement 9366.00. Both were
# internally consistent; they simply defined "total" differently, so the
# client aging column printed a total 738.00 short of its own gross exposure
# and no reader could tell whether the total was wrong or a lane excluded.
# financial_aging settles it -- "invariant sum(buckets) == open balance", and
# due_date_unavailable is "included in open-balance reconciliation".

def _undated_mix_ar():
    """Overdue + not-yet-due + one document with no due date at all."""
    return aggregate_statement_from_facts(
        _meta(),
        [_inv(iid="6001", date="2026-07-02", paymentdate="2026-07-10",
              brutto="4200.00", currency="EUR", fullnumber="FV 1"),
         _inv(iid="6002", date="2026-07-08", paymentdate="2026-08-22",
              brutto="1230.00", currency="EUR", fullnumber="FV 2"),
         _inv(iid="6003", date="2026-07-19", paymentdate="",
              brutto="738.00", currency="EUR", fullnumber="FV 3")],
        [], "2026-07-31", ("2026-07-01", "2026-07-31"),
    )


def _undated_mix_ap():
    return aggregate_supplier_statement(
        [_exp(eid="6001", date="2026-07-02", payment_date="2026-07-10",
              brutto="4200.00", fullnumber="EXP 1"),
         _exp(eid="6002", date="2026-07-08", payment_date="2026-08-22",
              brutto="1230.00", fullnumber="EXP 2"),
         _exp(eid="6003", date="2026-07-19", payment_date="",
              brutto="738.00", fullnumber="EXP 3")],
        [], contractor_meta=_meta(),
        period=("2026-07-01", "2026-07-31"), as_of="2026-07-31",
    )


@pytest.mark.parametrize("build,side", [(_undated_mix_ar, "client"),
                                        (_undated_mix_ap, "supplier")])
def test_aging_column_sums_to_its_own_printed_total(build, side):
    stmt = build()
    aging = stmt["aging_per_currency"]["EUR"]
    # Non-vacuous: the undated lane must actually carry money, or this test
    # would pass on a fact set that never exercises the divergence.
    assert Decimal(aging["due_date_unavailable"]) == Decimal("738.00"), aging
    lanes = sum(
        (Decimal(str(aging.get(k) or "0")) for k in AGING_BUCKETS_WITH_UNAVAILABLE),
        Decimal("0"),
    )
    assert lanes == Decimal(aging["total"]), (
        f"{side} aging column does not sum to its own total: "
        f"lanes={lanes} total={aging['total']}"
    )


@pytest.mark.parametrize("build,side", [(_undated_mix_ar, "client"),
                                        (_undated_mix_ap, "supplier")])
def test_aging_total_equals_gross_exposure(build, side):
    """The aging block and the position block describe the same money."""
    stmt = build()
    assert (Decimal(stmt["aging_per_currency"]["EUR"]["total"])
            == Decimal(stmt["position_per_currency"]["EUR"]["gross_exposure"])
            == Decimal("6168.00")), side


def test_both_statements_define_the_aging_total_the_same_way():
    """One product, one meaning of 'total' -- on identical facts."""
    ar = _undated_mix_ar()["aging_per_currency"]["EUR"]
    ap = _undated_mix_ap()["aging_per_currency"]["EUR"]
    for key in AGING_BUCKETS_WITH_UNAVAILABLE + ("total",):
        assert Decimal(str(ar[key])) == Decimal(str(ap[key])), (
            f"client and supplier disagree on aging '{key}': "
            f"{ar[key]} vs {ap[key]}"
        )


# ── 14. Unapplied cash is disclosed once, on the side that owns it ────────
#
# Measured defect (2026-08-19): the AP bucketing loop dropped its own orphan
# and currency-mismatched payments as "already in warnings", so cash paid to a
# supplier appeared on no supplier document; the AR loop had no mirror of AP's
# guard, so that same supplier-side cash was simultaneously reported to the
# customer as unapplied CLIENT money. One payment, two statements, two
# different stories -- and the one the supplier reads was the one missing it.
# No arithmetic is involved: unapplied cash never touched a running balance,
# a matched total or a bucket sum, before the fix or after it.

def _expense_linked_payment_facts():
    """One expense, and cash against an expense id that is not in the window."""
    return (
        [_exp(eid="6001", date="2026-03-04", brutto="1000.00",
              currency="EUR", payment_date="2026-03-18")],
        [
            # settles the expense in the window -> matched on AP, silent on AR
            _pay(pid="8001", date="2026-03-20", value="1000.00",
                 linked_expense="6001", currency="EUR"),
            # names an expense nobody can resolve -> disclosed on AP only
            _pay(pid="8003", date="2026-03-21", value="310.00",
                 linked_expense="9099", currency="EUR"),
        ],
    )


def _ap_of(expenses, payments):
    return aggregate_supplier_statement(
        expenses, payments, contractor_meta=_meta(),
        period=("2026-03-01", "2026-03-31"), as_of="2026-03-31",
    )


def _ar_of(payments):
    return aggregate_statement_from_facts(
        _meta(),
        [_inv(iid="1", date="2026-03-05", brutto="500.00", currency="EUR")],
        payments, "2026-03-31", ("2026-03-01", "2026-03-31"),
    )


def test_supplier_side_cash_is_never_reported_as_unapplied_client_money():
    expenses, payments = _expense_linked_payment_facts()
    ar = _ar_of(payments)
    disclosed = [
        p["wfirma_doc_id"]
        for rows in (ar["unmatched_payments_per_currency"] or {}).values()
        for p in rows
    ]
    assert disclosed == [], (
        "an expense-linked payment is the supplier statement's to disclose; "
        "listing it here tells the customer we hold money of theirs that we "
        "do not: %s" % disclosed
    )


def test_supplier_statement_discloses_its_own_unapplied_cash():
    expenses, payments = _expense_linked_payment_facts()
    ap = _ap_of(expenses, payments)
    rows = (ap["unmatched_payments_per_currency"] or {}).get("EUR") or []
    assert [r["wfirma_doc_id"] for r in rows] == ["8003"], (
        "cash paid to this supplier that resolved to no expense must still "
        "appear on the supplier's own statement, not only in warnings"
    )
    assert rows[0]["linked_expense"] == "9099", (
        "disclose the link it names, so the gap is reconcilable"
    )
    assert Decimal(rows[0]["value"]) == Decimal("310.00")


def test_one_payment_is_disclosed_on_exactly_one_side():
    expenses, payments = _expense_linked_payment_facts()
    ar, ap = _ar_of(payments), _ap_of(expenses, payments)

    def ids(stmt):
        return {p["wfirma_doc_id"]
                for rows in (stmt["unmatched_payments_per_currency"] or {}).values()
                for p in rows}

    assert not (ids(ar) & ids(ap)), "a payment disclosed twice is two claims"


def test_unapplied_disclosure_moves_no_money():
    """The fix is a disclosure fix; the balances must be untouched by it."""
    expenses, payments = _expense_linked_payment_facts()
    ap = _ap_of(expenses, payments)
    t = ap["totals_per_currency"]["EUR"]
    pos = ap["position_per_currency"]["EUR"]
    # 1000.00 expense, fully settled inside the window by payment 8001.
    assert Decimal(t["period_debits"]) == Decimal("1000.00")
    assert Decimal(t["closing_balance"]) == Decimal("0.00")
    assert Decimal(pos["gross_exposure"]) == Decimal("0.00")
    # 8003 is disclosed BESIDE the ledger, never inside it. The matched
    # payment 8001 is a ledger row and always was -- an applied payment is
    # part of the running balance; unapplied cash is precisely the cash that
    # is not.
    ids = [r["wfirma_doc_id"] for r in ap["entries_per_currency"]["EUR"]]
    assert ids == ["6001", "8001"], ids


def test_unapplied_rows_name_themselves_but_ledger_rows_never_do():
    """The two halves of one rule, asserted on the rendered pages.

    An unapplied payment has no document, so the disclosure prints the only
    handle it has -- otherwise the statement announces a hole without
    saying which payment made it. A LEDGER row does have a document, and is
    identified by that and nothing else: a matched payment whose
    `doc_number` is empty prints an em dash, not a wFirma object id.

    Measured: the supplier ledger printed `PAY-8001` in its Document column
    when both tables shared one key set (test_supplier_statement_pdf.py::
    test_internal_metadata_never_reaches_the_page). The tables want
    opposite rules, so they read different key sets, and this holds both
    ends of that at once.
    """
    from app.services.statement_pdf_renderer import (
        render_statement_pdf, render_supplier_statement_pdf,
    )

    expenses, payments = _expense_linked_payment_facts()
    ap = _ap_of(expenses, payments)
    assert [r["wfirma_doc_id"]
            for rows in ap["unmatched_payments_per_currency"].values()
            for r in rows] == ["8003"], "fixture must carry unapplied cash"
    assert [e["wfirma_doc_id"] for e in ap["entries_per_currency"]["EUR"]
            if e["type"] == "payment"] == ["8001"], (
        "and a MATCHED payment in the ledger, which is the row that leaked"
    )
    ap_text = _rendered_text(render_supplier_statement_pdf(ap))
    assert "8003" in ap_text, "the unapplied payment must name itself"
    assert "8001" not in ap_text, (
        "a wFirma object id has no business on a supplier-facing ledger row"
    )

    # AR: the same disclosure, the same fallback, the same page.
    ar = _paginating_ar(3)
    assert [r["wfirma_doc_id"]
            for rows in ar["unmatched_payments_per_currency"].values()
            for r in rows] == ["7777"], "fixture must carry unapplied cash"
    assert "7777" in _rendered_text(render_statement_pdf(ar))


# ── 15. The monthly statement is the balance-forward product ──────────────
#
# `soa` and `monthly` carried byte-identical config, so `document=monthly`
# rendered the SOA with one word changed -- one document wearing two names.
# The distinction pinned here is the one accountancy draws: an SOA is an
# open-item statement as of a date; a monthly statement is period-closed and
# balance-forward for a named calendar month. Presentation only: the flag
# selects wording, never arithmetic.

def test_only_the_monthly_product_is_period_closed():
    from app.services.statement_pdf_renderer import _DOC_CFG
    closed = {k for k, v in _DOC_CFG.items() if v["period_close"]}
    assert closed == {"monthly"}, (
        "period-close is what makes the monthly product distinct from the "
        "SOA; spreading it further would blur them again: %s" % closed
    )


def test_the_month_is_named_only_when_the_period_is_that_whole_month():
    from app.services.statement_pdf_renderer import statement_title
    whole = {"period": {"from": "2026-07-01", "to": "2026-07-31"}}
    part = {"period": {"from": "2026-07-12", "to": "2026-07-31"}}
    quarter = {"period": {"from": "2026-07-01", "to": "2026-09-30"}}
    assert statement_title("ar", "monthly", whole).endswith("July 2026")
    for stmt, why in ((part, "part month"), (quarter, "quarter")):
        title = statement_title("ar", "monthly", stmt)
        assert "July" not in title, (
            "naming a month asserts which window the figures cover (%s)" % why
        )
    # …and the open-item product never borrows the month.
    assert "July" not in statement_title("ar", "soa", whole)


def test_a_monthly_statement_over_a_part_month_says_so_on_its_face():
    from app.services.statement_pdf_renderer import (
        _period_integrity_flowables, _styles,
    )
    styles = _styles()
    part = {"period": {"from": "2026-07-12", "to": "2026-07-31"}}
    whole = {"period": {"from": "2026-07-01", "to": "2026-07-31"}}
    notice = _period_integrity_flowables(part, styles, document="monthly")
    assert notice, "a part-month monthly statement must disclose its window"
    text = " ".join(getattr(f, "text", "") for f in notice)
    assert "2026-07-12" in text and "2026-07-31" in text
    assert "not a single whole calendar month" in text
    # Never fires where it would be noise: whole month, or another product.
    assert _period_integrity_flowables(whole, styles, document="monthly") == []
    assert _period_integrity_flowables(part, styles, document="soa") == []


def test_the_balance_forward_chain_is_labelled_as_a_chain():
    """opening + debits - credits = closing, readable without a manual."""
    from app.services.statement_pdf_renderer import _activity_rows
    totals = {"opening_balance": "100.00", "period_debits": "50.00",
              "period_credits": "20.00", "closing_balance": "130.00",
              "entry_count": 3}
    labels = [k for k, _ in _activity_rows(totals, period_close=True)]
    assert labels[:4] == ["Opening balance", "+ Period debits",
                          "- Period credits", "= Closing balance"]
    # The operators are labels; the SOA keeps the plain wording.
    plain = [k for k, _ in _activity_rows(totals)]
    assert plain[:4] == ["Opening balance", "Period debits",
                         "Period credits", "Closing balance"]
    values = dict(_activity_rows(totals, period_close=True))
    assert values["= Closing balance"] == "130.00", (
        "the renderer prints the aggregator's closing balance; re-deriving "
        "it here would be a second accounting engine"
    )


# ── 16. One document system: no stranded headings, one vocabulary ─────────
#
# Two presentation defects measured on rendered pages (2026-08-19), both in
# the ONE shared renderer and so fixed once, at it:
#
#   (a) "Unapplied payments" printed as the last line of a page, its table
#       overleaf -- seen on the client monthly and again on the supplier
#       monthly. A heading with nothing under it reads as a section with
#       nothing IN it, and this section's subject is cash the counterparty
#       paid that we could not apply to a document. `_titled_grid` puts a
#       `CondPageBreak` ahead of every heading that owns a table, so the
#       heading is only printed where the head of its table can follow.
#   (b) The client statement headed that block "Unmatched payments" while
#       the supplier statement -- same renderer, same block, same meaning --
#       headed it "Unapplied payments". A counterparty who receives both
#       reasonably asks whether two words describe two different facts.
#
# The JSON key `unmatched_payments_per_currency` and the warning event
# `unmatched_payment` deliberately keep their own names: they are the data
# authority's, and the data-quality panel labels the event with the event's
# word so a reader can cross-reference it. Only the captions are shared.

# Every guarded table starts with a "Date" column. The page footers carry
# "Due date" (lower-case d) and no other, so capital-D "Date" on a page is
# evidence that a table head actually printed there.
_TABLE_HEAD_MARK = "Date"


def _pages(pdf_bytes):
    from io import BytesIO

    from pypdf import PdfReader

    return [(p.extract_text() or "")
            for p in PdfReader(BytesIO(pdf_bytes)).pages]


def _paginating_ar(rows):
    """`rows` invoices in one currency, plus cash that resolves to nothing."""
    invoices = [
        _inv(iid=str(3000 + i), date="2026-03-%02d" % (i % 28 + 1),
             brutto="100.00", currency="EUR",
             fullnumber="FV %d/2026" % (i + 1))
        for i in range(rows)
    ]
    # Names an invoice id nothing in the window resolves -> disclosed beside
    # the ledger, which is the block whose heading was being stranded.
    unapplied = [_pay(pid="7777", date="2026-03-20", value="250.00",
                      linked="9099", currency="EUR")]
    return aggregate_statement_from_facts(
        _meta(), invoices, unapplied, "2026-03-31",
        ("2026-03-01", "2026-03-31"),
    )


def _guarded_headings():
    from app.services.statement_pdf_renderer import _SIDE_CFG

    return ["Ledger"] + sorted(
        {cfg["unmatched_title"] for cfg in _SIDE_CFG.values()}
    )


def test_a_section_heading_never_ends_a_page_without_its_table():
    """Swept across a page boundary, not sampled at one convenient length.

    A single fixture passes or fails on where its ledger happens to break,
    which is luck, not coverage. The row count is swept instead, so the
    unapplied heading is walked through the foot of a page inside the run.
    The range is not arbitrary: with the guard disabled, this fixture
    strands the heading at 52 and 53 ledger rows (measured 2026-08-19; it
    strands again at 97-98, one page further on). A sweep that misses those
    lengths is a test that cannot fail, so the range brackets them.
    """
    from app.services.statement_pdf_renderer import render_statement_pdf

    headings = _guarded_headings()
    saw_a_second_page = False
    saw_the_unapplied_block = False

    for rows in range(48, 58):
        pages = _pages(render_statement_pdf(_paginating_ar(rows)))
        saw_a_second_page = saw_a_second_page or len(pages) > 1
        for n, text in enumerate(pages, start=1):
            for heading in headings:
                at = text.find(heading)
                if at < 0:
                    continue
                if heading != "Ledger":
                    saw_the_unapplied_block = True
                assert _TABLE_HEAD_MARK in text[at + len(heading):], (
                    "%d rows, page %d: '%s' printed with no table under it. "
                    "A heading alone at a page break claims a section with "
                    "nothing in it -- here, about money."
                    % (rows, n, heading)
                )

    assert saw_a_second_page, "a one-page sweep cannot strand anything"
    assert saw_the_unapplied_block, (
        "the block that was measured stranded must be in the sweep"
    )


def test_the_heading_guard_reserves_a_foothold_rather_than_moving_the_table():
    """`CondPageBreak`, not `KeepTogether` -- the difference is load-bearing.

    A long ledger must still split across pages and repeat its column header
    (`repeatRows=1`). `KeepTogether` would try to relocate the whole table,
    and degrades to no protection at all once it outgrows the frame.
    """
    from reportlab.platypus import CondPageBreak

    from reportlab.lib.units import mm

    from app.services.statement_pdf_renderer import (
        _SECTION_FOOTHOLD, _titled_grid,
    )

    title, table = object(), object()
    out = _titled_grid(title, table)
    assert isinstance(out[0], CondPageBreak), (
        "the guard is a conditional break placed BEFORE the heading"
    )
    assert out[1:] == [title, table], "and it moves neither of them"
    assert 0 < _SECTION_FOOTHOLD < 40 * mm, (
        "a foothold is a heading plus a first row; reserving more would "
        "start pushing whole sections to the next page for no reason"
    )


def test_both_statements_use_one_word_for_cash_we_could_not_apply():
    from app.services.statement_pdf_renderer import _SIDE_CFG

    titles = {side: cfg["unmatched_title"] for side, cfg in _SIDE_CFG.items()}
    types = {side: cfg["unmatched_type"] for side, cfg in _SIDE_CFG.items()}
    assert len(set(titles.values())) == 1, (
        "one document system, one caption for one fact: %s" % titles
    )
    assert len(set(types.values())) == 1, "and one row type: %s" % types


def test_the_shared_caption_reaches_both_rendered_documents():
    """Source agreement is not proof; both PDFs must print the same word."""
    from app.services.statement_pdf_renderer import (
        _SIDE_CFG, render_statement_pdf, render_supplier_statement_pdf,
    )

    caption = _SIDE_CFG["ar"]["unmatched_title"]
    ar = _paginating_ar(3)
    expenses, payments = _expense_linked_payment_facts()
    ap = _ap_of(expenses, payments)
    assert (ar["unmatched_payments_per_currency"]
            and ap["unmatched_payments_per_currency"]), (
        "both fixtures must actually carry unapplied cash, else vacuous"
    )
    for name, pdf in (("client", render_statement_pdf(ar)),
                      ("supplier", render_supplier_statement_pdf(ap))):
        assert caption in _rendered_text(pdf), (
            "the %s statement must print '%s'" % (name, caption)
        )


def test_the_data_authority_keeps_its_own_names():
    """The caption was unified; the API and the warning event were not.

    Renaming `unmatched_payments_per_currency` to match a caption would
    break every consumer for no reader's benefit, and the data-quality
    panel labels the warning with the warning's own word so an operator can
    cross-reference it against the event stream.
    """
    ar = _paginating_ar(3)
    assert "unmatched_payments_per_currency" in ar, (
        "the JSON key is the data authority's name and does not follow "
        "presentation vocabulary"
    )
    labels = (V2 / "ledgers-page.jsx").read_text(encoding="utf-8")
    assert "unmatched_payment:" in labels, (
        "the data-quality panel must still label the event by its own name"
    )


# -- 17. A confirmation discloses the cash it does not deduct --------------
#
# Measured on the rendered pages (2026-08-19): one flag gated both the
# ledger and the unapplied-payments block, so the `confirmation` product --
# the ONE document whose purpose is "do you agree you owe this" -- was the
# one document that did not mention the payment we were holding unapplied.
# Their books show the payment; ours show a position that excludes it;
# nothing on the page connected the two. That is a NOT AGREED tick caused by
# our own document. The gates are now separate: no ledger on a confirmation,
# but unapplied cash is disclosed on every product, with a sentence saying
# it is disclosed and not deducted so the two numbers reconcile.


def _confirmation_of(stmt, side):
    from app.services.statement_pdf_renderer import (
        render_statement_pdf, render_supplier_statement_pdf,
    )

    render = (render_statement_pdf if side == "ar"
              else render_supplier_statement_pdf)
    return _rendered_text(render(stmt, document="confirmation"))


def test_the_confirmation_discloses_unapplied_cash_and_still_has_no_ledger():
    """Both halves: the disclosure appears, the ledger does not.

    Asserting only the disclosure would pass a confirmation that had simply
    grown a full ledger -- which is the other half of what this document is
    not. A confirmation asks about one number; a document listing takes the
    reader's eye off it.
    """
    from app.services.statement_pdf_renderer import _SIDE_CFG

    ar = _paginating_ar(3)
    expenses, payments = _expense_linked_payment_facts()
    ap = _ap_of(expenses, payments)
    assert (ar["unmatched_payments_per_currency"]
            and ap["unmatched_payments_per_currency"]), (
        "both fixtures must carry unapplied cash, else this is vacuous"
    )

    for side, stmt, ident in (("ar", ar, "7777"), ("ap", ap, "8003")):
        text = _confirmation_of(stmt, side)
        assert _SIDE_CFG[side]["unmatched_title"] in text, (
            "%s confirmation must disclose cash we could not apply" % side
        )
        assert ident in text, (
            "%s confirmation must name the payment, not just its existence"
            % side
        )
        assert _SIDE_CFG[side]["unapplied_sentence"] in " ".join(text.split()), (
            "%s confirmation must say the cash is disclosed, NOT deducted -- "
            "otherwise the reader cannot reconcile our position against "
            "their own ledger" % side
        )
        assert "Ledger" not in text, (
            "%s confirmation must not carry a document listing" % side
        )


def test_the_sentence_is_absent_when_there_is_no_unapplied_cash():
    """A standing paragraph about cash we do not hold is noise on a form.

    It also weakens the disclosure: a sentence that prints on every
    confirmation stops being read by the time it matters.
    """
    from app.services.statement_pdf_renderer import _SIDE_CFG

    clean = _paginating_ar(3)
    clean["unmatched_payments_per_currency"] = {}
    text = _confirmation_of(clean, "ar")
    assert _SIDE_CFG["ar"]["unapplied_sentence"] not in " ".join(text.split())
    assert "AGREED" in text, "the confirmation itself must still render"


# ── One unmatched-payment rule, applied by BOTH consumers ──────────────────
# The AR portfolio matcher counted every payment without a linked_invoice as an
# unmatched AR receipt, including supplier-side cash linked to an EXPENSE. That
# reported 2,049 phantom unapplied receipts on Management Analysis (production,
# 2026-08-20) while the AP side raised 3 warnings and customer statements none.
# The statement path already skipped supplier cash; these tests pin that the
# portfolio path now applies the SAME rule, and that money is untouched.

def test_supplier_cash_is_not_an_unmatched_ar_receipt():
    """A payment linked to an expense belongs to AP, never to AR."""
    from app.services.ledger_aggregator import match_payments_to_invoices

    out = match_payments_to_invoices(
        [_inv(iid="1", date="2026-01-05", brutto="100.00")],
        [_pay(pid="p-sup", date="2026-01-10", value="100.00",
              linked_expense="55")],
    )
    events = [w.get("event") for w in out["warnings"]]
    assert "unmatched_payment" not in events, (
        "supplier-side cash was counted as an unmatched AR receipt: %s" % events
    )
    assert not out["unmatched_payments"]


def test_genuinely_unlinked_cash_is_still_reported_unmatched():
    """The guard must not silence real unapplied AR receipts."""
    from app.services.ledger_aggregator import match_payments_to_invoices

    out = match_payments_to_invoices(
        [_inv(iid="1", date="2026-01-05", brutto="100.00")],
        [_pay(pid="p-orphan", date="2026-01-10", value="100.00")],
    )
    assert [w.get("event") for w in out["warnings"]] == ["unmatched_payment"]
    assert [p["id"] for p in out["unmatched_payments"]] == ["p-orphan"]


def test_the_guard_changes_no_money():
    """Only the counter moves: paid_against_invoice is identical either way."""
    from app.services.ledger_aggregator import match_payments_to_invoices

    inv = [_inv(iid="1", date="2026-01-05", brutto="100.00")]
    p_ar = _pay(pid="p1", date="2026-01-10", value="40.00", linked="1")
    p_sup = _pay(pid="p2", date="2026-01-10", value="99.00", linked_expense="55")
    without = match_payments_to_invoices(inv, [p_ar])
    withsup = match_payments_to_invoices(inv, [p_ar, p_sup])
    assert without["paid_against_invoice"] == withsup["paid_against_invoice"], (
        "supplier cash must not alter AR settlement"
    )


def test_both_consumers_share_one_rule():
    """Structural pin: the expense-link skip exists in BOTH payment loops."""
    import inspect

    from app.services import ledger_aggregator as la

    portfolio = inspect.getsource(la.match_payments_to_invoices)
    statement = inspect.getsource(la.aggregate_statement_from_facts)
    for name, src in (("portfolio", portfolio), ("statement", statement)):
        assert "linked_expense" in src, (
            "%s consumer lost the canonical supplier-cash rule" % name
        )


def test_ap_offset_status_is_judged_against_the_suppliers_own_gross():
    """offset_status must read gross_payable, not the leaked loop variable.

    ``gross`` stays bound by the ``for exp in expense_facts`` loop, so reading
    it in the supplier loop judged every supplier against the brutto of the
    last expense that loop kept. Supplier A owes 9,900 net against a 100
    credit -- partially_offset -- but the leaked 50 made it fully_offset, and
    since offset_status is the primary sort key it then ranked BELOW a
    supplier owing 50.
    """
    from app.services.accounting_analytics import (
        build_payables_portfolio_from_facts,
    )

    def _exp(eid, cid, brutto):
        return {"id": eid, "contractor_id": cid, "contractor_name": cid,
                "currency": "USD", "brutto": Decimal(brutto),
                "date": "2026-01-10", "payment_date": "2026-02-10"}

    # S-B's +50 is the last expense kept, so 50 is what leaked.
    facts = [_exp("e1", "S-A", "10000"), _exp("e2", "S-A", "-100"),
             _exp("e3", "S-B", "50")]
    out = build_payables_portfolio_from_facts(
        facts, [], as_of="2026-08-20", period=("2020-01-01", "2026-08-20"))

    by_id = {s["contractor_id"]: s for s in out["suppliers"]}
    assert by_id["S-A"]["net_payable"] == "9900.00"
    assert by_id["S-A"]["offset_status"] == "partially_offset", (
        "a supplier owing 9,900 against a 100 credit is not fully offset"
    )
    assert by_id["S-B"]["offset_status"] == "actionable"
    # Ranking consequence: offset_status is the PRIMARY sort key, so the
    # mislabel did not merely print a wrong flag -- it dropped a 9,900
    # creditor into the bottom (fully_offset) tier. Pin the tier itself.
    assert by_id["S-A"]["offset_status"] != "fully_offset"
