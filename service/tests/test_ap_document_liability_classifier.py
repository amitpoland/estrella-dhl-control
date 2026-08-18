"""AP document lifecycle classification — rejected inbox drafts are not liabilities.

Origin
------
A supplier account showed a large multi-currency payable that could never
settle. Every underlying expense carried ``<draft>2</draft>``,
``<is_rejected>1</is_rejected>``, ``<parser>ubl21</parser>`` and a
``contractor_detail`` naming our own legal entity: they were our own outbound
sales invoices auto-parsed back into the wFirma expense inbox by the UBL 2.1
e-invoice reader and then REJECTED by wFirma. Zero payments existed against
the account and none ever could, so the balance would have sat open forever.

Root cause — neither AP ingestion path read the source lifecycle flags:
  * ``map_expense_node`` hardcoded ``open_relevant=True`` and read a
    ``<status>`` tag the expenses module never emits (NULL on every row).
  * ``_parse_expense_fact`` dropped ``<draft>`` / ``<is_rejected>`` entirely.

The prior AP truth gate passed with zero blockers because every comparison was
LIVE wFirma vs LOCAL projection — both built from the same unfiltered
universe. A mirror compared against itself always agrees.

Authority under test
--------------------
``ledger_aggregator.classify_expense_lifecycle`` — the ONE rule. Both the live
universe and the local projection mapper consume it; neither may re-implement.

Fixtures here are synthetic (public repo). Real supplier identifiers, document
numbers and balances stay in the local investigation evidence.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from app.services.ledger_aggregator import (
    EXPENSE_CLASS_BOOKED,
    EXPENSE_CLASS_DRAFT,
    EXPENSE_CLASS_REJECTED,
    _parse_expense_fact,
    classify_expense_lifecycle,
)
from app.services.local_fact_universe import reporting_row_to_expense_fact
from app.tools.sync_financial_reporting import map_expense_node


def _expense_xml(
    expense_id: str = "900000001",
    *,
    draft: str = "0",
    is_rejected: str = "",
    parser: str = "",
    supplier_id: str = "10000001",
    number: str = "SELF 001/2026",
    currency: str = "EUR",
    brutto: str = "1000.00",
) -> ET.Element:
    return ET.fromstring(
        "<expense>"
        f"<id>{expense_id}</id>"
        f"<fullnumber>{number}</fullnumber>"
        "<type>invoice</type>"
        "<date>2026-06-29</date>"
        "<payment_date>2026-07-06</payment_date>"
        f"<currency>{currency}</currency>"
        f"<netto>{brutto}</netto>"
        f"<brutto>{brutto}</brutto>"
        f"<remaining>{brutto}</remaining>"
        "<alreadypaid>0.00</alreadypaid>"
        "<paymentstate>unpaid</paymentstate>"
        f"<draft>{draft}</draft>"
        f"<is_rejected>{is_rejected}</is_rejected>"
        f"<parser>{parser}</parser>"
        f"<contractor><id>{supplier_id}</id></contractor>"
        "<contractor_detail><name>Example Supplier Sp. z o.o.</name></contractor_detail>"
        "</expense>"
    )


# --- the rule itself -------------------------------------------------------

def test_rejected_flag_wins_over_any_draft_value():
    assert classify_expense_lifecycle("2", "1") == EXPENSE_CLASS_REJECTED
    assert classify_expense_lifecycle("0", "1") == EXPENSE_CLASS_REJECTED
    assert classify_expense_lifecycle("", "1") == EXPENSE_CLASS_REJECTED


def test_nonzero_draft_without_rejection_is_draft_not_rejected():
    """A real supplier document sitting unbooked in the inbox: draft, no rejection.

    These stay in the universe — demoting them to rejected would understate
    genuine payables.
    """
    assert classify_expense_lifecycle("1", "") == EXPENSE_CLASS_DRAFT
    assert classify_expense_lifecycle("1", "0") == EXPENSE_CLASS_DRAFT


def test_booked_expense_is_the_default():
    assert classify_expense_lifecycle("0", "") == EXPENSE_CLASS_BOOKED
    assert classify_expense_lifecycle("", "") == EXPENSE_CLASS_BOOKED
    assert classify_expense_lifecycle("0", "0") == EXPENSE_CLASS_BOOKED


# --- live universe path ----------------------------------------------------

def test_live_expense_fact_carries_lifecycle():
    booked = _parse_expense_fact(_expense_xml())
    assert booked["lifecycle"] == EXPENSE_CLASS_BOOKED

    rejected = _parse_expense_fact(
        _expense_xml(draft="2", is_rejected="1", parser="ubl21")
    )
    assert rejected["lifecycle"] == EXPENSE_CLASS_REJECTED
    # brutto still parsed — the fact is complete, only its class differs.
    assert str(rejected["brutto"]) == "1000.00"


def test_live_universe_drops_rejected_and_counts_the_exclusion(monkeypatch):
    """Self-billing mirrors must never reach a live AP consumer."""
    from app.services import ledger_fact_universe as lfu

    mirrors = [
        _expense_xml("900000001", draft="2", is_rejected="1", parser="ubl21",
                     number="SELF 001/2026", currency="USD", brutto="100.00"),
        _expense_xml("900000002", draft="2", is_rejected="1", parser="ubl21",
                     number="SELF 002/2026", currency="EUR", brutto="2000.00"),
        _expense_xml("900000003", draft="2", is_rejected="1", parser="ubl21",
                     number="SELF 003/2026", currency="EUR", brutto="3000.00"),
    ]
    genuine = _expense_xml("900000009", draft="0", supplier_id="10000002",
                           number="INV 500/2026", currency="USD",
                           brutto="5000.00")

    monkeypatch.setattr(
        lfu.wfirma_client, "fetch_expenses_for_period",
        lambda df, dt, stats=None: list(mirrors) + [genuine],
    )
    monkeypatch.setattr(
        lfu.wfirma_client, "fetch_payments_for_period",
        lambda df, dt, stats=None: [],
    )
    lfu.clear_fact_universe_cache()

    uni = lfu.load_ap_fact_universe("2026-06-01", "2026-08-18", force=True)

    ids = [f["id"] for f in uni["expense_facts"]]
    assert ids == ["900000009"]
    assert uni["excluded_rejected_count"] == 3
    lfu.clear_fact_universe_cache()


# --- local projection path -------------------------------------------------

def test_mapper_marks_rejected_row_not_open_relevant():
    row = map_expense_node(_expense_xml(draft="2", is_rejected="1", parser="ubl21"))
    assert row.open_relevant is False
    assert row.document_status == EXPENSE_CLASS_REJECTED


def test_mapper_keeps_draft_and_booked_rows_open_relevant():
    draft_row = map_expense_node(_expense_xml(draft="1"))
    assert draft_row.open_relevant is True
    assert draft_row.document_status == EXPENSE_CLASS_DRAFT

    booked_row = map_expense_node(_expense_xml())
    assert booked_row.open_relevant is True
    assert booked_row.document_status == EXPENSE_CLASS_BOOKED


def test_mapper_no_longer_reads_the_absent_status_tag():
    """Regression: <status> is an AR tag. Reading it left AP status NULL on every
    production row, so the classification column was dead."""
    node = _expense_xml(draft="2", is_rejected="1")
    node.append(ET.fromstring("<status>whatever</status>"))
    assert map_expense_node(node).document_status == EXPENSE_CLASS_REJECTED


def test_local_row_to_fact_matches_live_fact_shape():
    node = _expense_xml(draft="2", is_rejected="1", parser="ubl21")
    live = _parse_expense_fact(node)
    mapped = map_expense_node(node)
    local = reporting_row_to_expense_fact(
        {
            "expense_id": mapped.expense_id,
            "document_number": mapped.document_number,
            "document_type": mapped.document_type,
            "issue_date": mapped.issue_date,
            "due_date": mapped.due_date,
            "currency": mapped.currency,
            "net": str(mapped.net),
            "gross": str(mapped.gross),
            "supplier_id": mapped.supplier_id,
            "supplier_name": mapped.supplier_name,
            "correction_of_id": mapped.correction_of_id,
            "document_status": mapped.document_status,
        }
    )
    assert local["lifecycle"] == live["lifecycle"] == EXPENSE_CLASS_REJECTED
    assert local["brutto"] == live["brutto"]


def test_pre_classifier_rows_read_as_booked():
    """Rows synced before this landed carry document_status NULL. They must read
    as booked — the same assumption list_ap_expenses_as_of already made."""
    fact = reporting_row_to_expense_fact(
        {"expense_id": "1", "gross": "10.00", "document_status": None}
    )
    assert fact["lifecycle"] == EXPENSE_CLASS_BOOKED
