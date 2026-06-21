"""
test_product_authority_resolver.py — the canonical product-identity resolver.

Phase 0–2 consolidation: one resolver replaces the three duplicated
``SELECT DISTINCT design_no, product_code`` derivations. These tests pin the
canonical behaviour AND prove equivalence with the historical per-site logic, so
the repoint of design_product_bridge / proforma_draft_sync / sales_packing_matcher
is behaviour-preserving. Pure-function tests — packing rows are injected, no DB.
"""
from __future__ import annotations

from app.services import product_authority_resolver as par


def _row(design, product_code, qty=1, invoice="EJL/26-27/299", pos=None):
    return {"design_no": design, "product_code": product_code,
            "quantity": qty, "invoice_no": invoice, "invoice_line_position": pos}


# Real EJL/26-27/299 shape: 299-2 is a mixed lot (many designs share one code);
# a NULL-product_code row exists (must NOT inflate candidates — rule 8).
EJL299_ROWS = (
    [_row(d, "EJL/26-27/299-2") for d in
        ["JR04929", "JR05671", "JR05671", "JR05318", "J3806R00973", "JR06077"]] +
    [_row(d, "EJL/26-27/299-9") for d in ["JR04929", "JR04832", "JR04929"]] +
    [_row("PND", None), _row("PND", "")] +             # null/blank → excluded
    [_row("", "EJL/26-27/299-3")]                       # blank design → excluded
)


# ── reference: the historical SELECT DISTINCT + strip + skip-blank logic ──────

def _old_design_distinct(rows):
    distinct = set()
    for r in rows:
        distinct.add((r.get("design_no"), r.get("product_code")))
    out = {}
    for d_raw, p_raw in distinct:
        d = str(d_raw or "").strip()
        p = str(p_raw or "").strip()
        if not d or not p:
            continue
        out.setdefault(d, set()).add(p)
    return {d: sorted(ps) for d, ps in out.items()}


# ── snapshot / read functions ────────────────────────────────────────────────

def test_snapshot_shape_and_keys():
    snap = par.resolve_batch_product_authority("B", packing_rows=EJL299_ROWS)
    assert set(snap) == {
        "batch_id", "design_to_product_codes", "available_by_product_code",
        "invoice_by_product_code", "product_codes", "rows_scanned", "rows_skipped",
    }


def test_design_to_codes_strips_sorts_and_excludes_null_blank():
    d2c = par.design_to_product_codes("B", packing_rows=EJL299_ROWS)
    # null/blank product_code rows excluded (rule 8); blank design excluded
    assert "PND" not in d2c
    assert "" not in d2c
    # mixed lot: JR04929 appears under both 299-2 and 299-9 → sorted union
    assert d2c["JR04929"] == ["EJL/26-27/299-2", "EJL/26-27/299-9"]
    assert d2c["J3806R00973"] == ["EJL/26-27/299-2"]
    # keys are case-preserved (stripped), not upper-cased
    assert all(k == k.strip() for k in d2c)


def test_available_quantity_sums_per_product_code():
    avail = par.available_quantity_by_product_code("B", packing_rows=EJL299_ROWS)
    # 299-2: 6 design rows × qty1 = 6 ; 299-9: 3 rows × qty1 = 3 ; 299-3: 1
    assert avail["EJL/26-27/299-2"] == 6
    assert avail["EJL/26-27/299-9"] == 3
    assert avail["EJL/26-27/299-3"] == 1
    # null/blank product_code contributes nothing
    assert "" not in avail and None not in avail


def test_invoice_by_product_code_first_wins():
    rows = [_row("D1", "C1", invoice="INV-A"), _row("D2", "C1", invoice="INV-B")]
    snap = par.resolve_batch_product_authority("B", packing_rows=rows)
    assert snap["invoice_by_product_code"]["C1"] == "INV-A"


def test_rows_scanned_and_skipped_accounting():
    snap = par.resolve_batch_product_authority("B", packing_rows=EJL299_ROWS)
    # distinct non-blank (design, code) pairs
    expected_pairs = {(r["design_no"], r["product_code"]) for r in EJL299_ROWS
                      if str(r["design_no"] or "").strip() and str(r["product_code"] or "").strip()}
    assert snap["rows_scanned"] == len(expected_pairs)
    assert snap["rows_skipped"] >= 1   # the null/blank/blank-design rows


# ── validate_billed_product_code (rules 5 / 7) ───────────────────────────────

def test_validate_membership_rule5():
    assert par.validate_billed_product_code("B", "EJL/26-27/299-2", packing_rows=EJL299_ROWS) is True
    assert par.validate_billed_product_code("B", "EJL/26-27/999-9", packing_rows=EJL299_ROWS) is False
    assert par.validate_billed_product_code("B", "", packing_rows=EJL299_ROWS) is False


def test_validate_with_design_context_rule7():
    # 299-2 IS a candidate for J3806R00973 …
    assert par.validate_billed_product_code(
        "B", "EJL/26-27/299-2", "J3806R00973", packing_rows=EJL299_ROWS) is True
    # … but 299-9 is NOT a candidate for J3806R00973
    assert par.validate_billed_product_code(
        "B", "EJL/26-27/299-9", "J3806R00973", packing_rows=EJL299_ROWS) is False


# ── EQUIVALENCE with the historical per-site logic ───────────────────────────

def test_equivalence_with_old_distinct_logic():
    for rows in (
        EJL299_ROWS,
        [_row("a", "X"), _row("A", "X")],                 # case variants stay separate keys
        [_row("D", None), _row("D", "")],                 # all-null design drops out
        [_row("D1", "C1"), _row("D1", "C2"), _row("D1", "C1")],  # dup pair dedup
        [],
    ):
        assert par.design_to_product_codes("B", packing_rows=rows) == _old_design_distinct(rows)


def test_matcher_renormalization_merges_case_variants():
    # The resolver returns case-preserved keys; the sales matcher re-keys with
    # _norm and MERGES — emulate that adapter and confirm the merge.
    rows = [_row("abc", "C1"), _row("ABC", "C2")]
    raw = par.design_to_product_codes("B", packing_rows=rows)
    merged = {}
    for d, codes in raw.items():
        merged.setdefault(d.strip().upper(), set()).update(codes)
    assert merged == {"ABC": {"C1", "C2"}}


# ── combined reconcile (#684 + #686) on the Draft #34 shape ───────────────────

def test_reconcile_billed_lines_no_over_bill_on_mixed_lot():
    # Bill the exact pieces present (within available) → no over-bill, ambiguity
    # resolved by the billed product_code.
    draft = [
        {"design_no": "JR04929", "product_code": "EJL/26-27/299-9", "qty": 1, "line_id": "1"},
        {"design_no": "JR04832", "product_code": "EJL/26-27/299-9", "qty": 1, "line_id": "2"},
        {"design_no": "JR04929", "product_code": "EJL/26-27/299-9", "qty": 1, "line_id": "3"},
    ]
    out = par.reconcile_billed_lines(
        "B", draft,
        ambiguous_design_codes={"JR04929": ["EJL/26-27/299-2", "EJL/26-27/299-9"]},
        packing_rows=EJL299_ROWS)
    assert out["ambiguity"]["genuinely_ambiguous"] == {}      # billed code validates
    overs = [d for d in out["duplicates"] if d["over_billed"]]
    assert overs == []                                         # 3 billed ≤ 3 available
    assert out["available_by_product_code"]["EJL/26-27/299-9"] == 3


def test_reconcile_billed_lines_flags_over_bill():
    draft = [
        {"design_no": "D", "product_code": "EJL/26-27/299-9", "qty": 2, "line_id": "1"},
        {"design_no": "D", "product_code": "EJL/26-27/299-9", "qty": 2, "line_id": "2"},
    ]
    out = par.reconcile_billed_lines("B", draft, packing_rows=EJL299_ROWS)
    overs = [d for d in out["duplicates"] if d["over_billed"]]
    assert len(overs) == 1 and overs[0]["product_code"] == "EJL/26-27/299-9"  # 4 > 3


# ── #684 safety preserved through the re-home ────────────────────────────────

def test_design_no_alone_still_blocks():
    out = par.reconcile_billed_ambiguity(
        {"JR04929": ["EJL/26-27/299-2", "EJL/26-27/299-9"]},
        [{"design_no": "JR04929", "product_code": ""}])   # no product_code
    assert "JR04929" in out["genuinely_ambiguous"]


def test_off_candidate_code_still_blocks():
    out = par.reconcile_billed_ambiguity(
        {"JR04929": ["EJL/26-27/299-2", "EJL/26-27/299-9"]},
        [{"design_no": "JR04929", "product_code": "EJL/26-27/999-9"}])
    assert "JR04929" in out["genuinely_ambiguous"]
