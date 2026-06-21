"""
test_proforma_duplicate_product_code.py — duplicate / over-bill product_code guard.

AUTHORITY (rules 1-5, with the data-model correction surfaced during the audit)
-------------------------------------------------------------------------------
A ``product_code`` (invoice_no + line position) identifies one PURCHASE INVOICE
LINE — a lot that legitimately holds several pieces / design_no values. So a
product_code MAY appear on multiple draft lines; that is only a billing-integrity
failure when the TOTAL billed quantity exceeds the available packing quantity
(rule 2: the packing-line quantity is the split authority). An OVER-bill is the
double-bill risk and is the hard blocker (rule 4). Mere duplication WITHIN the
available quantity (a mixed lot — the norm for EJL/26-27/299) is legitimate and
must NOT block, or every real shipment would be wrongly blocked.

`_analyze_product_code_billing` classifies; it never auto-corrects/merges/picks
(rule 5). Pure-function tests — no DB/app fixtures.
"""
from __future__ import annotations

from app.api.routes_proforma import _analyze_product_code_billing


def _line(pc, design, qty, line_id=None):
    return {"product_code": pc, "design_no": design, "qty": qty, "line_id": line_id}


def _by_pc(entries):
    return {e["product_code"]: e for e in entries}


# ── unique product_codes pass ────────────────────────────────────────────────

def test_unique_product_codes_within_available_pass():
    lines = [_line("A-1", "D1", 1), _line("A-2", "D2", 1)]
    avail = {"A-1": 1, "A-2": 1}
    out = _analyze_product_code_billing(lines, avail)
    assert out == []                      # single-line, not over → nothing surfaced


# ── duplication WITHIN available is legitimate (mixed lot) — no block ─────────

def test_duplicate_same_pc_within_available_is_not_over_billed():
    """Two pieces of one invoice line, both available → surfaced, NOT over-billed."""
    lines = [_line("A-2", "JR04929", 1), _line("A-2", "JR05671", 1)]
    avail = {"A-2": 2}                    # lot has 2 pieces available
    e = _by_pc(_analyze_product_code_billing(lines, avail))["A-2"]
    assert e["over_billed"] is False
    assert e["billed_qty"] == 2 and e["available_qty"] == 2
    assert e["line_count"] == 2


def test_same_pc_different_design_within_available_not_blocked():
    """Different design_no under one product_code is the mixed-lot norm — allowed
    when within available quantity."""
    lines = [_line("A-2", "JR04929", 1), _line("A-2", "J3806R00973", 1)]
    avail = {"A-2": 2}
    e = _by_pc(_analyze_product_code_billing(lines, avail))["A-2"]
    assert e["over_billed"] is False
    assert e["design_nos"] == ["J3806R00973", "JR04929"]


# ── OVER-bill is the hard-blocker case (rule 4) ──────────────────────────────

def test_duplicate_same_pc_same_design_over_available_blocks():
    """Same product_code + same design billed twice but only 1 available → over."""
    lines = [_line("A-9", "JR04929", 1), _line("A-9", "JR04929", 1)]
    avail = {"A-9": 1}
    e = _by_pc(_analyze_product_code_billing(lines, avail))["A-9"]
    assert e["over_billed"] is True
    assert e["billed_qty"] == 2 and e["available_qty"] == 1


def test_duplicate_same_pc_different_design_over_available_blocks():
    lines = [_line("A-2", "JR04929", 1), _line("A-2", "J3806R00973", 1)]
    avail = {"A-2": 1}                    # lot only has 1 piece, but 2 billed
    e = _by_pc(_analyze_product_code_billing(lines, avail))["A-2"]
    assert e["over_billed"] is True


def test_single_line_quantity_exceeds_available_blocks():
    """Over-bill from one line with qty > available (not a duplicate, still over)."""
    lines = [_line("A-5", "D1", 5)]
    avail = {"A-5": 3}
    e = _by_pc(_analyze_product_code_billing(lines, avail))["A-5"]
    assert e["over_billed"] is True and e["billed_qty"] == 5 and e["available_qty"] == 3


def test_split_quantity_allowed_up_to_available_then_blocks_when_exceeded():
    """Split across lines is allowed only up to the available quantity (rule 2)."""
    avail = {"A-10": 3}
    ok = _by_pc(_analyze_product_code_billing(
        [_line("A-10", "D1", 1), _line("A-10", "D2", 2)], avail))["A-10"]
    assert ok["over_billed"] is False     # 3 billed == 3 available
    over = _by_pc(_analyze_product_code_billing(
        [_line("A-10", "D1", 2), _line("A-10", "D2", 2)], avail))["A-10"]
    assert over["over_billed"] is True    # 4 billed > 3 available


# ── evidence + hygiene ───────────────────────────────────────────────────────

def test_finding_carries_line_evidence():
    lines = [_line("A-2", "D1", 1, line_id="6"), _line("A-2", "D2", 1, line_id="7")]
    e = _by_pc(_analyze_product_code_billing(lines, {"A-2": 2}, {"A-2": "EJL/26-27/299"}))["A-2"]
    assert e["invoice_no"] == "EJL/26-27/299"
    assert {l["line_id"] for l in e["lines"]} == {"6", "7"}
    assert {l["idx"] for l in e["lines"]} == {0, 1}


def test_blank_product_code_ignored():
    out = _analyze_product_code_billing([_line("", "D1", 1), _line("", "D2", 1)], {})
    assert out == []


def test_overbilled_entries_listed_first():
    lines = [_line("OK-1", "D1", 1), _line("OK-1", "D2", 1),
             _line("BAD-1", "D3", 2), _line("BAD-1", "D4", 2)]
    out = _analyze_product_code_billing(lines, {"OK-1": 2, "BAD-1": 1})
    assert out[0]["product_code"] == "BAD-1" and out[0]["over_billed"] is True


# ── the real EJL/26-27/299 Draft #34 mixed lots — every lot within available ──

def test_ejl299_draft34_mixed_lots_no_over_bill():
    """The 5 duplicated product_codes on Draft #34 each bill exactly their
    available packing quantity → all surfaced, NONE over-billed → 0 blockers."""
    lines = (
        [_line("EJL/26-27/299-6", d, 1) for d in ("JP02298", "JP02890")] +
        [_line("EJL/26-27/299-9", d, 1) for d in ("JR04929", "JR04832", "JR04929")]
    )
    avail = {"EJL/26-27/299-6": 2, "EJL/26-27/299-9": 3}   # = available packing qty
    out = _analyze_product_code_billing(lines, avail)
    assert all(not e["over_billed"] for e in out)
    assert {e["product_code"] for e in out} == {"EJL/26-27/299-6", "EJL/26-27/299-9"}
