"""
test_packing_autoresolve_position_key.py — the REPLACEMENT deterministic
packing product_code resolver, keyed on the EXACT invoice-line position
(``packing_lines.invoice_line_position == active invoice_lines.line_position``),
NOT pack_sr order.

Context: the earlier pack_sr-sequence resolver was rejected after production
validation proved pack_sr order is independent of invoice-line order (45.7% of
multi-row invoices reversed; codes EJL/26-27/390, /207, /297 would have been
mis-stamped). These pins prove the position-key planner:
  * assigns only on an exact, unique, quantity-consistent, non-conflicting key,
  * refuses (→ manual) on missing position, duplicate/inactive/blank line,
    quantity mismatch, cross-invoice design conflict, and mixed valid/invalid,
  * never uses pack_sr / row order,
  * never overwrites an assigned row, and is invoice-atomic + idempotent.

Pure function — packing rows and invoice lines are injected; no DB.
"""
from __future__ import annotations

from app.services import product_authority_resolver as par


def _p(rid, design, code, qty, pos, sr=None, inv="EJL/26-27/380"):
    """packing_lines row (product_code blank == unassigned)."""
    return {"id": rid, "design_no": design, "product_code": code, "quantity": qty,
            "invoice_line_position": pos, "pack_sr": sr, "invoice_no": inv}


def _i(code, qty, pos, inv="EJL/26-27/380", active=1):
    """active invoice_lines row (the product_code mint)."""
    return {"product_code": code, "quantity": qty, "line_position": pos,
            "invoice_no": inv, "active": active}


def _plan(pack, inv):
    return par.plan_position_key_assignments("B", packing_rows=pack, invoice_lines=inv)


def _codes_by_design(plan):
    return {a["design_no"]: a["product_code"] for a in plan["assignments"]}


# ── exact position match assigns correctly ───────────────────────────────────

def test_exact_position_match_assigns():
    pack = [_p("r1", "JR07550", None, 1.0, 1), _p("r2", "JR08385", None, 1.0, 2)]
    inv  = [_i("EJL/26-27/380-1", 1.0, 1), _i("EJL/26-27/380-2", 1.0, 2)]
    plan = _plan(pack, inv)
    assert plan["status"] == "deterministic"
    assert _codes_by_design(plan) == {"JR07550": "EJL/26-27/380-1",
                                      "JR08385": "EJL/26-27/380-2"}
    assert all(a["expected_count"] == 1 for a in plan["assignments"])
    assert plan["refusals"] == []


def test_reversed_pack_sr_does_not_change_result():
    # pack_sr is REVERSED vs position; the planner must ignore pack_sr entirely
    # and key purely on invoice_line_position.
    pack = [_p("r1", "JR07550", None, 1.0, 1, sr=2.0),
            _p("r2", "JR08385", None, 1.0, 2, sr=1.0)]
    inv  = [_i("EJL/26-27/380-1", 1.0, 1), _i("EJL/26-27/380-2", 1.0, 2)]
    assert _codes_by_design(_plan(pack, inv)) == {
        "JR07550": "EJL/26-27/380-1", "JR08385": "EJL/26-27/380-2"}


# ── refusals: everything non-exact falls through to manual ───────────────────

def test_missing_position_refuses_the_380_defect():
    # The original defect: design-only packing with NULL invoice_line_position →
    # no deterministic key → NO assignment → manual UI still required.
    pack = [_p("r1", "JR07550", None, 1.0, None), _p("r2", "JR08385", None, 1.0, None)]
    inv  = [_i("EJL/26-27/380-1", 1.0, 1), _i("EJL/26-27/380-2", 1.0, 2)]
    plan = _plan(pack, inv)
    assert plan["assignments"] == [] and plan["status"] == "none"
    assert any("no invoice_line_position" in r["reason"] for r in plan["refusals"])


def test_duplicate_invoice_position_refuses():
    pack = [_p("r1", "JR07550", None, 1.0, 1)]
    inv  = [_i("EJL/26-27/380-1", 1.0, 1), _i("EJL/26-27/380-9", 1.0, 1)]  # two @ pos1
    plan = _plan(pack, inv)
    assert plan["assignments"] == []
    assert any("duplicate active invoice line" in r["reason"] for r in plan["refusals"])


def test_missing_invoice_line_refuses():
    pack = [_p("r1", "JR07550", None, 1.0, 3)]
    inv  = [_i("EJL/26-27/380-1", 1.0, 1)]                                  # no pos3
    plan = _plan(pack, inv)
    assert plan["assignments"] == []
    assert any("no active invoice line at position 3" in r["reason"] for r in plan["refusals"])


def test_inactive_invoice_line_refuses():
    pack = [_p("r1", "JR07550", None, 1.0, 1)]
    inv  = [_i("EJL/26-27/380-1", 1.0, 1, active=0)]                        # superseded
    plan = _plan(pack, inv)
    assert plan["assignments"] == []
    assert any("no active invoice line" in r["reason"] for r in plan["refusals"])


def test_blank_invoice_code_refuses():
    pack = [_p("r1", "JR07550", None, 1.0, 1)]
    inv  = [_i("", 1.0, 1)]                                                 # blank code
    plan = _plan(pack, inv)
    assert plan["assignments"] == []
    assert any("blank product_code" in r["reason"] for r in plan["refusals"])


def test_quantity_mismatch_refuses():
    pack = [_p("r1", "JR07550", None, 1.0, 1)]
    inv  = [_i("EJL/26-27/380-1", 2.0, 1)]                                  # 1 pc vs qty 2
    plan = _plan(pack, inv)
    assert plan["assignments"] == []
    assert any("quantity mismatch" in r["reason"] for r in plan["refusals"])


def test_existing_product_code_never_overwritten():
    # r1 already assigned; only r2 (blank) is a candidate. r1 must not appear.
    pack = [_p("r1", "JR07550", "EJL/26-27/380-1", 1.0, 1),
            _p("r2", "JR08385", None, 1.0, 2)]
    inv  = [_i("EJL/26-27/380-1", 1.0, 1), _i("EJL/26-27/380-2", 1.0, 2)]
    plan = _plan(pack, inv)
    assert _codes_by_design(plan) == {"JR08385": "EJL/26-27/380-2"}
    row_ids = {r["row_id"] for a in plan["assignments"] for r in a["rows"]}
    assert "r1" not in row_ids


def test_mixed_valid_and_invalid_rows_cause_zero_writes_for_that_invoice():
    # One row of the invoice has no position → the WHOLE invoice group refuses
    # (never a partial invoice assignment), even though the other row matches.
    pack = [_p("r1", "JR07550", None, 1.0, 1),
            _p("r2", "JR08385", None, 1.0, None)]
    inv  = [_i("EJL/26-27/380-1", 1.0, 1), _i("EJL/26-27/380-2", 1.0, 2)]
    plan = _plan(pack, inv)
    assert plan["assignments"] == [] and plan["status"] == "none"


def test_idempotent_when_all_assigned():
    pack = [_p("r1", "JR07550", "EJL/26-27/380-1", 1.0, 1),
            _p("r2", "JR08385", "EJL/26-27/380-2", 1.0, 2)]
    inv  = [_i("EJL/26-27/380-1", 1.0, 1), _i("EJL/26-27/380-2", 1.0, 2)]
    plan = _plan(pack, inv)
    assert plan["assignments"] == [] and plan["refusals"] == []


def test_genuine_over_bill_not_masked():
    # Nothing is unassigned; a real over-bill (billed > available) is unaffected
    # by the planner — it produces no assignment, so the over-bill gate stays.
    pack = [_p("r1", "JR07550", "EJL/26-27/380-1", 1.0, 1)]
    inv  = [_i("EJL/26-27/380-1", 1.0, 1)]
    plan = _plan(pack, inv)
    assert plan["assignments"] == []


# ── mixed-lot: one invoice line = many pieces of one design, quantities sum ──

def test_mixed_lot_same_design_multiple_pieces_assigns_when_qty_accounts():
    # position 2 invoice qty 3; three packing rows qty 1 each, same design → sum
    # 3 == 3 → assign all three to 380-2 with expected_count 3.
    pack = [_p("r1", "JR07550", None, 1.0, 1),
            _p("r2", "JRLOT", None, 1.0, 2),
            _p("r3", "JRLOT", None, 1.0, 2),
            _p("r4", "JRLOT", None, 1.0, 2)]
    inv  = [_i("EJL/26-27/380-1", 1.0, 1), _i("EJL/26-27/380-2", 3.0, 2)]
    plan = _plan(pack, inv)
    by = {a["design_no"]: a for a in plan["assignments"]}
    assert by["JRLOT"]["product_code"] == "EJL/26-27/380-2"
    assert by["JRLOT"]["expected_count"] == 3
    assert by["JR07550"]["product_code"] == "EJL/26-27/380-1"


def test_mixed_lot_quantity_shortfall_refuses():
    # invoice qty 3 but only 2 packing pieces present at that position → the
    # packing does not account for the line → refuse (manual).
    pack = [_p("r2", "JRLOT", None, 1.0, 2), _p("r3", "JRLOT", None, 1.0, 2)]
    inv  = [_i("EJL/26-27/380-2", 3.0, 2)]
    plan = _plan(pack, inv)
    assert plan["assignments"] == []
    assert any("quantity mismatch" in r["reason"] for r in plan["refusals"])


# ── design-keyed writer safety: a design spanning invoices/codes is blocked ──

def test_design_spanning_two_codes_across_invoices_is_blocked():
    # Same design appears unassigned in two invoices resolving to DIFFERENT codes.
    # The design-keyed, batch-wide writer cannot express that → block BOTH
    # (fall to manual), never stamp one code across both.
    pack = [_p("r1", "JRDUP", None, 1.0, 1, inv="EJL/26-27/380"),
            _p("r2", "JRDUP", None, 1.0, 1, inv="EJL/26-27/381")]
    inv  = [_i("EJL/26-27/380-1", 1.0, 1, inv="EJL/26-27/380"),
            _i("EJL/26-27/381-1", 1.0, 1, inv="EJL/26-27/381")]
    plan = _plan(pack, inv)
    assert plan["assignments"] == []


def test_multi_invoice_only_clean_ones_resolve():
    # invoice 380 is a clean 1×1; invoice 381 has a NULL-position row → 380
    # resolves, 381 refuses, and their designs are disjoint so no cross-block.
    pack = [_p("r1", "JR07550", None, 1.0, 1, inv="EJL/26-27/380"),
            _p("r2", "JRA", None, 1.0, 1, inv="EJL/26-27/381"),
            _p("r3", "JRB", None, 1.0, None, inv="EJL/26-27/381")]
    inv  = [_i("EJL/26-27/380-1", 1.0, 1, inv="EJL/26-27/380"),
            _i("EJL/26-27/381-1", 1.0, 1, inv="EJL/26-27/381"),
            _i("EJL/26-27/381-2", 1.0, 2, inv="EJL/26-27/381")]
    plan = _plan(pack, inv)
    assert _codes_by_design(plan) == {"JR07550": "EJL/26-27/380-1"}
    assert any(r["invoice_no"] == "EJL/26-27/381" for r in plan["refusals"])


# ── historical mismatch shapes cannot be MIS-assigned by the replacement ─────

def test_historical_390_207_297_assigned_by_position_not_sequence():
    # These invoices are exactly where pack_sr order reversed vs line_position.
    # Keyed on position, each piece gets its TRUE code — the sequence resolver
    # would have rotated/swapped them.
    # EJL/26-27/390: pack_sr 1..4 but positions 4,1,2,3 (rotation).
    pack390 = [_p("a", "CSTR05189", None, 1.0, 4, sr=1.0, inv="EJL/26-27/390"),
               _p("b", "CSTR08070", None, 1.0, 1, sr=2.0, inv="EJL/26-27/390"),
               _p("c", "CSTR08076", None, 1.0, 2, sr=3.0, inv="EJL/26-27/390"),
               _p("d", "CSTR08087", None, 1.0, 3, sr=4.0, inv="EJL/26-27/390")]
    inv390 = [_i(f"EJL/26-27/390-{k}", 1.0, k, inv="EJL/26-27/390") for k in (1, 2, 3, 4)]
    got = _codes_by_design(_plan(pack390, inv390))
    assert got == {"CSTR05189": "EJL/26-27/390-4",   # position 4 → -4 (TRUE)
                   "CSTR08070": "EJL/26-27/390-1",
                   "CSTR08076": "EJL/26-27/390-2",
                   "CSTR08087": "EJL/26-27/390-3"}

    # EJL/26-27/297: pack_sr 1,2 but positions 2,1 (swap); variant designs.
    pack297 = [_p("x", "J4506P00551-A", None, 1.0, 2, sr=1.0, inv="EJL/26-27/297"),
               _p("y", "J4506P00551-S", None, 1.0, 1, sr=2.0, inv="EJL/26-27/297")]
    inv297 = [_i("EJL/26-27/297-1", 1.0, 1, inv="EJL/26-27/297"),
              _i("EJL/26-27/297-2", 1.0, 2, inv="EJL/26-27/297")]
    got297 = _codes_by_design(_plan(pack297, inv297))
    assert got297 == {"J4506P00551-A": "EJL/26-27/297-2",   # position 2 → -2 (TRUE)
                      "J4506P00551-S": "EJL/26-27/297-1"}


def test_read_failure_returns_empty_plan_not_crash():
    # A None batch with no injected rows → empty plan, never raises.
    plan = par.plan_position_key_assignments("")
    assert plan["assignments"] == [] and plan["status"] == "none"
