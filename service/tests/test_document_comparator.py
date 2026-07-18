"""test_document_comparator.py — Campaign-2 A1.

Direct unit tests for the pure comparison authority
``services.document_comparator.compare_invoice_plan``, extracted from
``routes_proforma._verify_created_invoice``.

Two things are pinned here:
  1. The comparator reproduces the exact verify-after-create matrix, ordering,
     and byte-identical messages (so the creation gate is unchanged).
  2. Unlike the raising gate, the comparator COLLECTS all gaps (report mode) and
     classifies each (severity / resolution_policy / evidence_quality).

Behavioural gate coverage lives in test_invoice_verify_after_create.py; this
file exercises the comparator directly and proves gate↔comparator parity.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.document_comparator import (
    compare_invoice_plan,
    ReconciliationResult,
    Gap,
    SEVERITY_CRITICAL,
    POLICY_BLOCKED,
    EQ_EXACT,
)
from app.services.proforma_to_invoice import FinalInvoicePlan, LineItem
from app.api.routes_proforma import _verify_created_invoice


# ── builders ──────────────────────────────────────────────────────────────────

def _line(name="RING", good_id="42", unit_count="1.0000",
          price="306.00", vat_code_id="228") -> LineItem:
    return LineItem(
        name=name, good_id=good_id, unit="szt.",
        unit_count=unit_count, price=price, vat_code_id=vat_code_id,
    )


def _plan(*, contractor_id="9001", currency="EUR", total="306.00",
          receiver_id="", lines=None) -> FinalInvoicePlan:
    return FinalInvoicePlan(
        type="normal",
        contractor_id=contractor_id,
        currency=currency,
        price_currency_exchange=None,
        paymentmethod="przelew",
        paymentdate="2026-05-15",
        date="2026-06-08",
        description="Invoice",
        series_id="15827921",
        company_account_id="194483",
        translation_language_id=None,
        contractor_receiver_id=(receiver_id or None),
        contents=lines if lines is not None else [_line()],
        source_proforma_id="467236963",
        source_proforma_number="PROF 92/2026",
        expected_total=Decimal(total),
    )


def _actual_xml(*, inv_id="500001", inv_type="normal", contractor_id="9001",
                currency="EUR", total="306.00", receiver_id="",
                lines=None) -> str:
    lines = lines if lines is not None else [dict(
        name="RING", good_id="42", unit_count="1.0000",
        price="306.00", vat_code_id="228")]
    rcv = (f"<contractor_receiver><id>{receiver_id}</id></contractor_receiver>"
           if receiver_id else "")
    body = ""
    for lo in lines:
        body += (
            "<invoicecontent>"
            f"<name>{lo['name']}</name>"
            f"<good><id>{lo['good_id']}</id></good>"
            "<unit>szt.</unit>"
            f"<unit_count>{lo['unit_count']}</unit_count>"
            f"<price>{lo['price']}</price>"
            f"<vat_code><id>{lo['vat_code_id']}</id></vat_code>"
            "</invoicecontent>"
        )
    return (
        "<api><invoices><invoice>"
        f"<id>{inv_id}</id><type>{inv_type}</type>"
        f"<currency>{currency}</currency><total>{total}</total>"
        f"<contractor><id>{contractor_id}</id></contractor>{rcv}"
        f"<invoicecontents>{body}</invoicecontents>"
        "</invoice></invoices></api>"
    )


# ── happy path ────────────────────────────────────────────────────────────────

def test_matching_invoice_yields_no_gaps():
    res = compare_invoice_plan(_plan(), _actual_xml())
    assert isinstance(res, ReconciliationResult)
    assert res.gaps == []
    assert res.has_blocking_gaps is False
    assert res.first_blocking_gap() is None


# ── each single-difference branch, message byte-identical ────────────────────

def test_no_invoice_element():
    res = compare_invoice_plan(_plan(), "<api><invoices></invoices></api>")
    assert len(res.gaps) == 1
    assert res.gaps[0].message == (
        "verify-after-create: fetched invoice "
        "but no <invoice> element in response"
    )


def test_empty_id():
    res = compare_invoice_plan(_plan(), _actual_xml(inv_id=""))
    assert res.first_blocking_gap().message == (
        "verify-after-create: fetched invoice has empty <id>"
    )


def test_wrong_type():
    res = compare_invoice_plan(_plan(), _actual_xml(inv_type="proforma"))
    g = res.first_blocking_gap()
    assert g.field == "type"
    assert "expected type='normal' or 'vat'" in g.message


def test_contractor_mismatch():
    res = compare_invoice_plan(_plan(), _actual_xml(contractor_id="9999"))
    assert res.first_blocking_gap().message == (
        "verify-after-create: contractor mismatch — "
        "expected='9001' got='9999'"
    )


def test_line_count_mismatch():
    res = compare_invoice_plan(_plan(), _actual_xml(lines=[]))
    assert "line count mismatch" in res.first_blocking_gap().message


@pytest.mark.parametrize("field,val,token", [
    ("name", "WRONG", "name:"),
    ("good_id", "999", "good_id:"),
    ("unit_count", "5.0000", "unit_count:"),
    ("price", "1.00", "price:"),
    ("vat_code_id", "111", "vat_code_id:"),
])
def test_per_line_field_mismatch(field, val, token):
    lo = dict(name="RING", good_id="42", unit_count="1.0000",
              price="306.00", vat_code_id="228")
    lo[field] = val
    res = compare_invoice_plan(_plan(), _actual_xml(lines=[lo]))
    msg = res.first_blocking_gap().message
    assert "line 1 field mismatch" in msg
    assert token in msg


def test_currency_mismatch():
    res = compare_invoice_plan(_plan(), _actual_xml(currency="USD"))
    assert "currency mismatch" in res.first_blocking_gap().message


def test_currency_absent_is_not_a_gap():
    # conditional check: an actual with no <currency> must NOT produce a gap
    xml = _actual_xml().replace("<currency>EUR</currency>", "")
    res = compare_invoice_plan(_plan(), xml)
    assert res.gaps == []


def test_total_beyond_tolerance():
    res = compare_invoice_plan(_plan(total="306.00"), _actual_xml(total="306.10"))
    assert "total mismatch" in res.first_blocking_gap().message


def test_total_within_tolerance_is_not_a_gap():
    res = compare_invoice_plan(_plan(total="306.00"), _actual_xml(total="306.01"))
    assert res.gaps == []


def test_receiver_mismatch():
    res = compare_invoice_plan(
        _plan(receiver_id="99990004"), _actual_xml(receiver_id=""))
    assert "contractor_receiver mismatch" in res.first_blocking_gap().message


def test_receiver_not_expected_is_not_a_gap():
    res = compare_invoice_plan(_plan(receiver_id=""), _actual_xml(receiver_id=""))
    assert res.gaps == []


# ── report mode: ALL gaps collected, in matrix order ─────────────────────────

def test_report_collects_multiple_gaps_in_order():
    res = compare_invoice_plan(
        _plan(contractor_id="9001", currency="EUR", total="306.00"),
        _actual_xml(contractor_id="9999", currency="USD", total="400.00"),
    )
    fields = [g.field for g in res.gaps]
    # contractor precedes currency precedes total (matrix order preserved)
    assert fields.index("contractor_id") < fields.index("currency")
    assert fields.index("currency") < fields.index("total")
    assert res.has_blocking_gaps is True


# ── classification ───────────────────────────────────────────────────────────

def test_every_verify_gap_is_critical_blocked_exact():
    res = compare_invoice_plan(_plan(), _actual_xml(contractor_id="9999"))
    for g in res.gaps:
        assert g.severity == SEVERITY_CRITICAL
        assert g.resolution_policy == POLICY_BLOCKED
        assert g.evidence_quality == EQ_EXACT


# ── gate ↔ comparator parity ─────────────────────────────────────────────────

@pytest.mark.parametrize("kwargs", [
    dict(inv_type="proforma"),
    dict(contractor_id="9999"),
    dict(currency="USD"),
    dict(total="306.10"),
    dict(lines=[]),
])
def test_gate_raises_first_blocking_gap_message(kwargs):
    plan = _plan()
    xml = _actual_xml(**kwargs)
    expected_msg = compare_invoice_plan(plan, xml).first_blocking_gap().message
    with pytest.raises(RuntimeError) as ei:
        _verify_created_invoice(plan, xml)
    assert str(ei.value) == expected_msg


def test_gate_passes_when_no_blocking_gap():
    # returns None, raises nothing
    assert _verify_created_invoice(_plan(), _actual_xml()) is None
