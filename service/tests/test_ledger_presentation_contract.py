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


def _pay(*, pid, date, value, linked="", currency=""):
    inv = f"<invoice><id>{linked}</id></invoice>" if linked else ""
    ccy = f"<currency>{currency}</currency>" if currency else ""
    xml = (
        f"<payment><id>{pid}</id><date>{date}</date>"
        f"<value>{value}</value>{ccy}{inv}</payment>"
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
# prints a GROSS split: Orion Casting Works is fully offset -- gross 2000.00
# against credits 2000.00, net payable 0.00 -- and its card read "91-180
# 2000.00 / Total 2000.00" with nothing on the card saying that figure is
# before credits. Separately, the supplier statement held ACTIVITY (opening,
# period debits, period credits, closing) and POSITION (gross, credits,
# payments applied, outstanding, net payable) under one heading, and because
# closing balance equals net payable in both fixtures the conflation was
# invisible in the numbers themselves.

_MIDDOT = chr(0xB7)
_GROSS_CAPTION = "gross " + _MIDDOT + " before credits"


def test_every_aging_surface_says_the_split_is_before_credits():
    """Supplier card, client card, management grid -- all three."""
    src = _PDF.read_text(encoding="utf-8")
    assert src.count(_GROSS_CAPTION) >= 3, (
        "aging is a gross split; each surface must say so where it is read"
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

    start = src.index("def _supplier_currency_flowables")
    end = src.index("def render_supplier_statement_pdf", start)
    assert 'totals.get("closing_balance") or totals.get(' \
        not in src[start:end], (
            "on the supplier statement every alternative to closing balance "
            "is a position figure"
        )
