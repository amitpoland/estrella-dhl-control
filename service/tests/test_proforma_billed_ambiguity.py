"""
test_proforma_billed_ambiguity.py — billed-line authority for design ambiguity.

AUDIT REPAIR THIS PINS (authority rules 4/5/6)
----------------------------------------------
The batch bridge (design_product_bridge.populate_from_packing) flags any
design_no that maps to >1 product_code across the WHOLE batch, collapsing
design_no globally and discarding the invoice context. The readiness gate used
that raw set verbatim, so a design was declared "ambiguous — clarify which line
to bill" even when:
  * no line on the draft bills that design (a pure batch artifact), or
  * the billed line already carries a definite product_code (the sales-packing /
    intake matcher already chose it).

`_reconcile_billed_ambiguity` makes the billed line's product_code the authority
(rule 6: product_code = invoice_no + line position is identity; rule 5: design_no
is descriptive). It NEVER guesses — it only validates an already-chosen code
against the batch's candidate set (rule 4: map against DB records).

Real scenario pinned below = SHIPMENT_9158478722 / EJL-26-27-299 (Draft #34):
PND/J4006R01513/JP02436 are batch-ambiguous but not billed; JR04929/J3806R00973
are billed and already carry a valid product_code.

Pure-function tests — no DB/app fixtures.
"""
from __future__ import annotations

from app.api.routes_proforma import _reconcile_billed_ambiguity


# Batch-level ambiguity exactly as design_product_bridge emits it for EJL-299.
EJL299_AMBIG = {
    "PND":         ["EJL/26-27/295-1", "EJL/26-27/299-3", "EJL/26-27/299-6"],
    "JR04929":     ["EJL/26-27/299-2", "EJL/26-27/299-9"],
    "J3806R00973": ["EJL/26-27/299-2", "EJL/26-27/299-8"],
    "J4006R01513": ["EJL/26-27/298-1", "EJL/26-27/298-2"],
    "JP02436":     ["EJL/26-27/291-1", "EJL/26-27/291-2"],
}


def _line(design, product_code=""):
    return {"design_no": design, "product_code": product_code}


# ── Rule 5/6: a billed line's product_code resolves the design ───────────────

def test_billed_line_with_valid_code_is_resolved_not_blocked():
    """design_no JR04929 is batch-ambiguous, but the billed line already carries
    EJL/26-27/299-2 (a valid candidate) → resolved, NOT a blocker."""
    lines = [_line("JR04929", "EJL/26-27/299-2")]
    r = _reconcile_billed_ambiguity({"JR04929": EJL299_AMBIG["JR04929"]}, lines)
    assert "JR04929" in r["resolved"]
    assert r["resolved"]["JR04929"] == ["EJL/26-27/299-2"]
    assert "JR04929" not in r["genuinely_ambiguous"]


def test_design_no_alone_without_product_code_still_blocks():
    """The core no-guessing guarantee: a billed line with only design_no and a
    BLANK product_code + multiple candidates stays genuinely ambiguous."""
    lines = [_line("JR04929", "")]
    r = _reconcile_billed_ambiguity({"JR04929": EJL299_AMBIG["JR04929"]}, lines)
    assert "JR04929" in r["genuinely_ambiguous"]
    assert r["genuinely_ambiguous"]["JR04929"] == sorted(EJL299_AMBIG["JR04929"])
    assert "JR04929" not in r["resolved"]


def test_off_candidate_product_code_is_not_silently_trusted():
    """A product_code that is NOT one of the batch candidates does not resolve
    the design — it keeps blocking (no silent trust of an unverifiable code)."""
    lines = [_line("JR04929", "EJL/26-27/999-9")]  # not in candidates
    r = _reconcile_billed_ambiguity({"JR04929": EJL299_AMBIG["JR04929"]}, lines)
    assert "JR04929" in r["genuinely_ambiguous"]
    assert "JR04929" not in r["resolved"]


# ── Not-billed designs are batch artifacts, not blockers ─────────────────────

def test_not_billed_design_is_downgraded_not_blocked():
    """PND is batch-ambiguous but no line on the draft bills it → not_billed,
    never a billing blocker."""
    lines = [_line("JR04929", "EJL/26-27/299-2")]  # bills JR04929 only
    r = _reconcile_billed_ambiguity({"PND": EJL299_AMBIG["PND"]}, lines)
    assert r["not_billed"] == ["PND"]
    assert "PND" not in r["genuinely_ambiguous"]
    assert "PND" not in r["resolved"]


# ── The full EJL-299 / Draft #34 picture ─────────────────────────────────────

def test_ejl299_draft34_scenario_collapses_to_zero_blockers():
    """Draft #34 bills JR04929 + J3806R00973 (both with valid codes); PND,
    J4006R01513, JP02436 are batch-only. Result: 0 genuine ambiguity blockers."""
    billed = [
        _line("JR04929", "EJL/26-27/299-2"),
        _line("J3806R00973", "EJL/26-27/299-8"),
        _line("CSTN00026", "EJL/26-27/299-1"),   # unrelated, not ambiguous
    ]
    r = _reconcile_billed_ambiguity(EJL299_AMBIG, billed)
    assert r["genuinely_ambiguous"] == {}, r["genuinely_ambiguous"]
    assert set(r["resolved"]) == {"JR04929", "J3806R00973"}
    assert set(r["not_billed"]) == {"PND", "J4006R01513", "JP02436"}


def test_one_genuine_plus_rest_resolved():
    """If one billed design lacks a code, ONLY it blocks; the resolved ones do not."""
    billed = [
        _line("JR04929", "EJL/26-27/299-2"),       # resolved
        _line("J3806R00973", ""),                  # genuinely ambiguous
    ]
    r = _reconcile_billed_ambiguity(EJL299_AMBIG, billed)
    assert set(r["genuinely_ambiguous"]) == {"J3806R00973"}
    assert "JR04929" in r["resolved"]


# ── Within-design multiplicity + normalization ───────────────────────────────

def test_multiple_billed_lines_same_design_all_resolved():
    """Two PND pieces, each pinned to a distinct valid code → resolved."""
    lines = [_line("PND", "EJL/26-27/299-3"), _line("PND", "EJL/26-27/299-6")]
    r = _reconcile_billed_ambiguity({"PND": EJL299_AMBIG["PND"]}, lines)
    assert "PND" in r["resolved"]
    assert r["resolved"]["PND"] == ["EJL/26-27/299-3", "EJL/26-27/299-6"]


def test_multiple_billed_lines_one_blank_blocks():
    """If one of several billed lines for a design lacks a code, the design blocks."""
    lines = [_line("PND", "EJL/26-27/299-3"), _line("PND", "")]
    r = _reconcile_billed_ambiguity({"PND": EJL299_AMBIG["PND"]}, lines)
    assert "PND" in r["genuinely_ambiguous"]


def test_case_and_whitespace_normalized():
    """design_no / product_code match is case- and whitespace-insensitive."""
    lines = [_line("  jr04929 ", " ejl/26-27/299-2 ")]
    r = _reconcile_billed_ambiguity({"JR04929": EJL299_AMBIG["JR04929"]}, lines)
    assert "JR04929" in r["resolved"]


def test_empty_inputs_are_safe():
    r = _reconcile_billed_ambiguity({}, [])
    assert r == {"genuinely_ambiguous": {}, "resolved": {}, "not_billed": []}
