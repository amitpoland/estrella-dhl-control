"""Governed re-extraction of already-persisted packing→invoice assignments.

These pin the *decision*, not the plumbing: `build_rematch_plan` is a pure
function, so every property below can be stated as data in, data out.

All fixtures are synthetic. The repository is public; no client name, real AWB,
real supplier invoice number, or real design number appears here.
"""
from __future__ import annotations

import pytest

from app.services.packing_rematch import build_rematch_plan

INV = "TEST/00-00/001"
DOC = "doc-synthetic-1"


def _line(pos, qty, price, code=None):
    return {
        "invoice_no": INV,
        "line_position": pos,
        "product_code": code or f"{INV}-{pos}",
        "quantity": qty,
        "unit_price": price,
        "total_value": qty * price,
    }


def _row(sr, pos, qty=1.0, price=10.0, *, code=None, strategy="type+qty",
         conf=0.80, review=False, status="", row_id=None, doc=DOC):
    return {
        "id": row_id or f"row-{sr}",
        "packing_document_id": doc,
        "pack_sr": sr,
        "invoice_no": INV,
        "invoice_line_position": pos,
        "product_code": code if code is not None else (f"{INV}-{pos}" if pos else None),
        "design_no": f"SYN{sr:03d}",
        "quantity": qty,
        "unit_price": price,
        "match_strategy": strategy,
        "extracted_confidence": conf,
        "requires_manual_review": review,
        "operator_review_status": status,
    }


# ── identity pairing ─────────────────────────────────────────────────────────

def test_rows_pair_on_document_and_serial_not_on_row_id():
    """A re-parsed row has no DB id, so identity must be (document, serial)."""
    stored = [_row(1, 1), _row(2, 2)]
    # Proposed rows carry no "id" at all — exactly what a re-parse produces.
    proposed = [
        {k: v for k, v in _row(2, 1).items() if k != "id"},
        {k: v for k, v in _row(1, 2).items() if k != "id"},
    ]
    plan = build_rematch_plan(stored, proposed, [_line(1, 1, 10.0), _line(2, 1, 10.0)])

    assert plan["counts"]["rows_changed"] == 2
    by_row = {c["row_id"]: c for c in plan["row_changes"]}
    assert by_row["row-1"]["new"]["invoice_line_position"] == 2
    assert by_row["row-2"]["new"]["invoice_line_position"] == 1


def test_identical_assignment_is_not_a_change():
    stored = [_row(1, 1), _row(2, 2)]
    proposed = [_row(1, 1), _row(2, 2)]
    plan = build_rematch_plan(stored, proposed, [_line(1, 1, 10.0), _line(2, 1, 10.0)])

    assert plan["row_changes"] == []
    assert plan["counts"]["rows_unchanged"] == 2
    assert plan["blocking"] is False


def test_row_changes_carry_both_sides_of_every_field_the_operator_reviews():
    stored = [_row(1, 1, strategy="type+qty", conf=0.80)]
    proposed = [_row(1, 2, strategy="type+qty+rate+metal", conf=0.95)]
    plan = build_rematch_plan(stored, proposed, [_line(1, 1, 10.0), _line(2, 1, 10.0)])

    ch = plan["row_changes"][0]
    assert ch["old"]["product_code"] == f"{INV}-1"
    assert ch["new"]["product_code"] == f"{INV}-2"
    assert ch["old"]["match_strategy"] == "type+qty"
    assert ch["new"]["match_strategy"] == "type+qty+rate+metal"
    assert ch["old"]["extracted_confidence"] == 0.80
    assert ch["new"]["extracted_confidence"] == 0.95
    assert ch["pack_sr"] == 1 and ch["packing_document_id"] == DOC


# ── blockers ─────────────────────────────────────────────────────────────────

def test_stored_row_the_reparse_does_not_cover_blocks():
    """A half-applied repair is worse than none."""
    stored = [_row(1, 1), _row(2, 2)]
    proposed = [_row(1, 2)]          # sr2 missing from the re-parse
    plan = build_rematch_plan(stored, proposed, [_line(1, 1, 10.0), _line(2, 1, 10.0)])

    assert plan["blocking"] is True
    codes = {b["code"] for b in plan["blockers"]}
    assert "stored_row_not_reparsed" in codes


def test_duplicate_stored_identity_blocks_rather_than_guessing():
    stored = [_row(1, 1, row_id="row-a"), _row(1, 2, row_id="row-b")]
    proposed = [_row(1, 1)]
    plan = build_rematch_plan(stored, proposed, [_line(1, 2, 10.0), _line(2, 1, 10.0)])

    assert plan["blocking"] is True
    assert "duplicate_stored_identity" in {b["code"] for b in plan["blockers"]}


def test_row_without_a_serial_blocks_on_both_sides():
    no_sr = _row(1, 1)
    no_sr["pack_sr"] = None
    no_sr.pop("line_position", None)
    plan = build_rematch_plan([no_sr], [], [_line(1, 1, 10.0)])
    assert "stored_row_without_identity" in {b["code"] for b in plan["blockers"]}

    prop_no_sr = _row(1, 1)
    prop_no_sr["pack_sr"] = None
    plan2 = build_rematch_plan([_row(1, 1)], [prop_no_sr], [_line(1, 1, 10.0)])
    assert "proposed_row_without_identity" in {b["code"] for b in plan2["blockers"]}


def test_plan_that_would_over_assign_an_invoice_line_is_refused():
    """The machine-checkable form of 'never increase availability synthetically'."""
    # Line 1 authorises 1 pc; the proposal puts two rows on it.
    stored = [_row(1, 1), _row(2, 2)]
    proposed = [_row(1, 1), _row(2, 1)]
    plan = build_rematch_plan(stored, proposed, [_line(1, 1, 10.0), _line(2, 1, 10.0)])

    assert plan["blocking"] is True
    over = [b for b in plan["blockers"] if b["code"] == "line_over_authority_after"]
    assert over and over[0]["product_code"] == f"{INV}-1"


def test_assignment_to_a_line_that_does_not_exist_blocks():
    stored = [_row(1, 1)]
    proposed = [_row(1, 9, code=f"{INV}-9")]
    plan = build_rematch_plan(stored, proposed, [_line(1, 1, 10.0)])

    assert plan["blocking"] is True
    assert "assignment_to_unknown_line" in {b["code"] for b in plan["blockers"]}


def test_row_moving_to_a_different_invoice_is_refused():
    stored = [_row(1, 1)]
    moved = _row(1, 1)
    moved["invoice_no"] = "TEST/00-00/002"
    plan = build_rematch_plan(stored, [moved], [_line(1, 1, 10.0)])

    assert plan["blocking"] is True
    assert "row_changed_invoice" in {b["code"] for b in plan["blockers"]}


def test_an_unmatched_row_becoming_matched_does_not_block():
    """The whole point of the repair: a NULL product_code row acquires its line."""
    orphan = _row(2, None, code=None, strategy=None, conf=0.0, review=True)
    stored = [_row(1, 1), orphan]
    proposed = [_row(1, 1), _row(2, 2, strategy="type+qty+rate+metal", conf=0.95)]
    plan = build_rematch_plan(stored, proposed, [_line(1, 1, 10.0), _line(2, 1, 10.0)])

    assert plan["blocking"] is False
    ch = [c for c in plan["row_changes"] if c["row_id"] == "row-2"][0]
    assert ch["old"]["product_code"] is None
    assert ch["new"]["product_code"] == f"{INV}-2"


def test_preexisting_over_line_the_plan_never_touches_is_advisory_not_blocker():
    """One bad line must not hold every unrelated correction hostage.

    Line 1 (authority 1) already carries two operator-confirmed rows — over
    authority BEFORE the plan, and only an operator ruling can release them.
    The plan itself proposes exactly one unrelated correction: the orphaned
    row-3 acquires line 2.  The write adds nothing to line 1 (before == after),
    so the violation is surfaced as an advisory and the plan is NOT blocking.
    """
    stored = [
        _row(1, 1, status="confirmed"),
        _row(2, 1, status="confirmed"),
        _row(3, None, code=None, strategy=None, conf=0.0, review=True),
    ]
    # Machine disagrees with row-2's pin (wants it on line 2's twin position);
    # both confirmed rows are preserved either way.  Row-3's fix is the only
    # write.
    proposed = [_row(1, 1), _row(2, 2), _row(3, 2, strategy="type+qty+rate+metal", conf=0.95)]
    plan = build_rematch_plan(
        stored, proposed, [_line(1, 1, 10.0), _line(2, 2, 10.0)])

    assert plan["blocking"] is False
    assert plan["blockers"] == []
    adv = [a for a in plan["advisories"]
           if a["code"] == "line_over_authority_preexisting"]
    assert len(adv) == 1
    assert adv[0]["product_code"] == f"{INV}-1"
    assert adv[0]["authority_qty"] == 1.0
    assert adv[0]["assigned_qty_before"] == 2.0
    assert adv[0]["assigned_qty_after"] == 2.0
    assert plan["counts"]["advisories"] == 1
    # The unrelated correction is still in the write set.
    ch = [c for c in plan["row_changes"] if c["row_id"] == "row-3"]
    assert ch and ch[0]["new"]["invoice_line_position"] == 2


def test_plan_that_adds_to_an_already_over_line_still_blocks():
    """Pre-existing over-ness is no licence: RAISING the line stays refused.

    Line 1 (authority 1) is already over with two stored rows; the proposal
    moves row-3 onto it as well (after 3 > before 2).  The write itself now
    increases the violation, so the blocker fires exactly as before.
    """
    stored = [_row(1, 1), _row(2, 1), _row(3, 2)]
    proposed = [_row(1, 1), _row(2, 1), _row(3, 1)]
    plan = build_rematch_plan(
        stored, proposed, [_line(1, 1, 10.0), _line(2, 1, 10.0)])

    assert plan["blocking"] is True
    over = [b for b in plan["blockers"] if b["code"] == "line_over_authority_after"]
    assert over and over[0]["product_code"] == f"{INV}-1"
    assert over[0]["before_qty"] == 2.0 and over[0]["proposed_qty"] == 3.0
    # And it is not double-reported as an advisory.
    assert all(a["product_code"] != f"{INV}-1" for a in plan["advisories"])


def test_plan_that_only_drains_an_over_line_is_advisory_and_proceeds():
    """Partial repair of an over line is an improvement, not a new violation.

    Line 1 (authority 1) holds three rows; the plan moves one away (3 → 2).
    Still over after, but strictly better — advisory, never a refusal of the
    very correction that reduces it.
    """
    stored = [_row(1, 1), _row(2, 1), _row(3, 1)]
    proposed = [_row(1, 1), _row(2, 1), _row(3, 3, strategy="type+qty+rate+metal", conf=0.95)]
    plan = build_rematch_plan(
        stored, proposed,
        [_line(1, 1, 10.0), _line(2, 1, 10.0), _line(3, 1, 10.0)])

    assert plan["blocking"] is False
    adv = [a for a in plan["advisories"]
           if a["code"] == "line_over_authority_preexisting"]
    assert len(adv) == 1
    assert adv[0]["assigned_qty_before"] == 3.0
    assert adv[0]["assigned_qty_after"] == 2.0
    assert {c["row_id"] for c in plan["row_changes"]} == {"row-3"}


# ── operator-confirmed rows ──────────────────────────────────────────────────

def test_operator_confirmed_row_is_preserved_not_rewritten():
    stored = [_row(1, 1, status="confirmed"), _row(2, 2)]
    proposed = [_row(1, 2), _row(2, 1)]
    plan = build_rematch_plan(stored, proposed, [_line(1, 1, 10.0), _line(2, 1, 10.0)])

    preserved_ids = {e["row_id"] for e in plan["operator_confirmed_preserved"]}
    assert preserved_ids == {"row-1"}
    assert "row-1" not in {c["row_id"] for c in plan["row_changes"]}


def test_projection_tallies_a_preserved_row_at_its_stored_assignment():
    """Otherwise the plan promises a reconciliation the write will not deliver.

    Row 1 is confirmed on line 1 and will not move.  If the projection credited
    it to line 2 (where the proposal wanted it) the "after" picture would show
    both lines balanced, while the actual write leaves line 1 double-assigned.
    """
    stored = [_row(1, 1, status="confirmed"), _row(2, 2)]
    # The proposal wants to swap them; only row-2 can actually move.
    proposed = [_row(1, 2), _row(2, 1)]
    plan = build_rematch_plan(stored, proposed, [_line(1, 1, 10.0), _line(2, 1, 10.0)])

    # Line 1 would then hold the confirmed row *and* row-2 → over authority.
    assert plan["blocking"] is True
    over = [b for b in plan["blockers"] if b["code"] == "line_over_authority_after"]
    assert over and over[0]["product_code"] == f"{INV}-1"


# ── invoice-line reconciliation ──────────────────────────────────────────────

def test_line_reconciliation_reports_authority_and_both_projections():
    stored = [_row(1, 1), _row(2, 1), _row(3, 1)]      # 3 rows piled on a 1-pc line
    proposed = [_row(1, 1), _row(2, 2), _row(3, 3)]
    lines = [_line(1, 1, 10.0), _line(2, 1, 10.0), _line(3, 1, 10.0)]
    plan = build_rematch_plan(stored, proposed, lines)

    by_code = {r["product_code"]: r for r in plan["line_reconciliation"]}
    assert by_code[f"{INV}-1"]["authority_qty"] == 1.0
    assert by_code[f"{INV}-1"]["before"]["assigned_qty"] == 3.0
    assert by_code[f"{INV}-1"]["after"]["assigned_qty"] == 1.0
    assert by_code[f"{INV}-1"]["before"]["qty_status"] == "over"
    assert by_code[f"{INV}-1"]["after"]["qty_status"] == "ok"
    # And the starved lines are filled.
    assert by_code[f"{INV}-2"]["before"]["assigned_qty"] == 0.0
    assert by_code[f"{INV}-2"]["after"]["qty_status"] == "ok"
    assert plan["counts"]["lines_over_before"] == 1
    assert plan["counts"]["lines_over_after"] == 0
    assert plan["blocking"] is False


# ── downstream sales impact ──────────────────────────────────────────────────

def _sale(code, qty):
    return {"product_code": code, "quantity": qty, "client_name": "SYNTHETIC CLIENT"}


def test_sales_over_bill_resolved_when_the_correct_line_is_restored():
    stored = [_row(1, 1), _row(2, 1)]                 # both on line 1
    proposed = [_row(1, 1), _row(2, 2)]
    lines = [_line(1, 1, 10.0), _line(2, 1, 10.0)]
    sales = [_sale(f"{INV}-1", 1.0), _sale(f"{INV}-2", 1.0)]
    plan = build_rematch_plan(stored, proposed, lines, sales)

    by_code = {s["product_code"]: s for s in plan["sales_impact"]}
    assert by_code[f"{INV}-2"]["verdict"] in {"over_bill_resolved", "ok"}
    assert plan["counts"]["over_bills_resolved"] >= 1
    assert plan["blocking"] is False


def test_revealing_a_concealed_over_bill_is_reported_and_does_not_block():
    """A wrong assignment can hide a real over-bill by crediting phantom pieces.

    Correcting it makes the true position visible so the fiscal gate can fire.
    Suppressing that would be the actual failure, so it must not block here.
    """
    # Line 2 authorises 2 pcs, and two stored rows sit on it, so a sale of 2
    # looks covered.
    stored = [_row(1, 2), _row(2, 2)]
    # The truth: only one of those rows belongs to line 2; the other is line 1's.
    proposed = [_row(1, 1), _row(2, 2)]
    lines = [_line(1, 1, 10.0), _line(2, 2, 10.0)]
    sales = [_sale(f"{INV}-2", 2.0)]
    plan = build_rematch_plan(stored, proposed, lines, sales)

    by_code = {s["product_code"]: s for s in plan["sales_impact"]}
    assert by_code[f"{INV}-2"]["verdict"] == "over_bill_revealed"
    assert plan["counts"]["over_bills_revealed"] == 1
    assert plan["blocking"] is False


def test_sales_availability_is_capped_by_invoice_authority_never_by_row_count():
    """Availability must come from the invoice, or the circularity returns."""
    stored = [_row(1, 1), _row(2, 1)]          # 2 rows carrying a 1-pc code
    proposed = [_row(1, 1), _row(2, 1)]
    lines = [_line(1, 1, 10.0)]
    sales = [_sale(f"{INV}-1", 2.0)]
    plan = build_rematch_plan(stored, proposed, lines, sales)

    impact = {s["product_code"]: s for s in plan["sales_impact"]}[f"{INV}-1"]
    assert impact["available_after"] == 1.0        # not 2.0
    assert impact["sales_qty"] == 2.0
    assert impact["verdict"] == "over_bill_persists"


# ── purity ───────────────────────────────────────────────────────────────────

def test_build_rematch_plan_does_not_mutate_its_inputs():
    stored = [_row(1, 1), _row(2, 2)]
    proposed = [_row(1, 2), _row(2, 1)]
    lines = [_line(1, 1, 10.0), _line(2, 1, 10.0)]
    sales = [_sale(f"{INV}-1", 1.0)]
    snap = (
        [dict(r) for r in stored], [dict(r) for r in proposed],
        [dict(l) for l in lines], [dict(s) for s in sales],
    )
    build_rematch_plan(stored, proposed, lines, sales)
    assert (stored, proposed, lines, sales) == snap


def test_plan_is_deterministic_and_independent_of_input_order():
    stored = [_row(i, i) for i in (1, 2, 3)]
    proposed = [_row(1, 3), _row(2, 1), _row(3, 2)]
    lines = [_line(1, 1, 10.0), _line(2, 1, 10.0), _line(3, 1, 10.0)]

    a = build_rematch_plan(stored, proposed, lines)
    b = build_rematch_plan(list(reversed(stored)), list(reversed(proposed)),
                           list(reversed(lines)))
    assert a == b


def test_empty_inputs_produce_an_empty_non_blocking_plan():
    plan = build_rematch_plan([], [], [])
    assert plan["row_changes"] == []
    assert plan["blocking"] is False
    assert plan["counts"]["rows_changed"] == 0


# -- blocker scope attribution (invoice-scoped apply support) -----------------

def test_every_blocker_carries_scope_invoices_and_authority_blocker_names_its_invoice():
    """Scope attribution is what lets the route apply one invoice while another
    is blocked; an over-authority blocker must name exactly its own invoice."""
    stored = [_row(1, 1), _row(2, 1), _row(3, 2)]
    proposed = [_row(1, 1), _row(2, 1), _row(3, 1)]
    plan = build_rematch_plan(
        stored, proposed, [_line(1, 1, 10.0), _line(2, 1, 10.0)])
    assert plan["blocking"] is True
    assert all("scope_invoices" in b for b in plan["blockers"])
    over = [b for b in plan["blockers"] if b["code"] == "line_over_authority_after"]
    assert over and all(b["scope_invoices"] == [INV] for b in over)


def test_row_changed_invoice_blocker_names_both_invoices():
    """Selecting EITHER involved invoice for a scoped apply must keep the veto."""
    other = "TEST/00-00/002"
    stored = [_row(1, 1)]
    moved = {k: v for k, v in _row(1, 1).items() if k != "id"}
    moved["invoice_no"] = other
    plan = build_rematch_plan(stored, [moved],
                              [_line(1, 1, 10.0)])
    blk = [b for b in plan["blockers"] if b["code"] == "row_changed_invoice"]
    assert blk and blk[0]["scope_invoices"] == sorted([INV, other])


def test_unattributable_blocker_scope_is_empty_meaning_global():
    """A stored row with no invoice at all cannot be attributed; the empty
    scope is the GLOBAL veto, never a silently narrowed one."""
    r = _row(1, 1)
    r["invoice_no"] = ""
    r.pop("pack_sr"); r["pack_sr"] = None; r["invoice_line_position"] = None
    r2 = dict(r); r2["line_position"] = None
    plan = build_rematch_plan([r2], [], [_line(1, 1, 10.0)])
    blk = [b for b in plan["blockers"] if b["code"] == "stored_row_without_identity"]
    assert blk and blk[0]["scope_invoices"] == []


def test_row_changes_carry_the_stored_invoice_no():
    """The write filter scopes on the STORED invoice - the one the write keeps."""
    stored = [_row(1, 2, price=5.0, code=f"{INV}-2")]
    proposed = [{k: v for k, v in
                 _row(1, 1, price=5.0, code=f"{INV}-1", strategy="type+qty+rate",
                      conf=0.95).items() if k != "id"}]
    plan = build_rematch_plan(stored, proposed,
                              [_line(1, 1, 5.0), _line(2, 1, 106.0)])
    assert plan["row_changes"] and all(
        c["invoice_no"] == INV for c in plan["row_changes"])
