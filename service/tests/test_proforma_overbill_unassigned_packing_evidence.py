"""
test_proforma_overbill_unassigned_packing_evidence.py

Regression for the "available 0" over-bill blocker hiding real packing pieces
that exist for a product_code's DESIGN but were never assigned a product_code.

Reproduces (synthetic identifiers) SHIPMENT_8341809162 invoice-380: two packing
pieces exist (designs JR07550 / JR08385, qty 1 each) but their product_code is
NULL, so the resolver skipped them and reported available 0 for the billed codes
EJL/26-27/380-1 / -2 — presenting no evidence for why two pieces exist yet both
availability totals are zero.

The fix is READ-ONLY and EVIDENCE-ONLY:
  * available quantity is NEVER invented (the NULL-product_code pieces are not
    counted as available) — the over-bill gate is preserved;
  * the over-bill result carries ``unassigned_packing`` evidence naming the
    design(s) and piece counts so the operator can repair via product-code
    assignment (a separate, approval-gated writer path).

Injection is via the resolver's canonical ``packing_rows=`` entry point (the
authoritative read shape), so these pins do not depend on packing_db seeding.
"""
from __future__ import annotations

from app.services.product_authority_resolver import (
    resolve_batch_product_authority,
    analyze_product_code_billing,
)


def _snap(rows):
    return resolve_batch_product_authority("BATCH_T", packing_rows=rows)


# ── Assigned packing behaves exactly as before ───────────────────────────────

def test_assigned_two_codes_each_available_one():
    rows = [
        {"design_no": "D1", "product_code": "P-1", "quantity": 1.0, "invoice_no": "INV"},
        {"design_no": "D2", "product_code": "P-2", "quantity": 1.0, "invoice_no": "INV"},
    ]
    s = _snap(rows)
    assert s["available_by_product_code"] == {"P-1": 1.0, "P-2": 1.0}
    assert s["unassigned_by_design"] == {}


def test_billed_one_one_against_available_one_one_no_overbill():
    rows = [
        {"design_no": "D1", "product_code": "P-1", "quantity": 1.0, "invoice_no": "INV"},
        {"design_no": "D2", "product_code": "P-2", "quantity": 1.0, "invoice_no": "INV"},
    ]
    s = _snap(rows)
    draft = [
        {"product_code": "P-1", "design_no": "D1", "qty": 1.0, "line_id": "L1"},
        {"product_code": "P-2", "design_no": "D2", "qty": 1.0, "line_id": "L2"},
    ]
    out = analyze_product_code_billing(draft, s["available_by_product_code"],
                                       s["invoice_by_product_code"], s["unassigned_by_design"])
    # 1/1 each, single line each → no entry at all (not >1 line, not over)
    assert out == []


def test_genuine_overbill_still_blocks_without_unassigned_evidence():
    # billed 2, available 1, fully assigned → over-bill fires with the ORIGINAL
    # message path (no unassigned_packing evidence).
    rows = [{"design_no": "D1", "product_code": "P-1", "quantity": 1.0, "invoice_no": "INV"}]
    s = _snap(rows)
    draft = [
        {"product_code": "P-1", "design_no": "D1", "qty": 1.0, "line_id": "L1"},
        {"product_code": "P-1", "design_no": "D1", "qty": 1.0, "line_id": "L2"},
    ]
    out = analyze_product_code_billing(draft, s["available_by_product_code"],
                                       s["invoice_by_product_code"], s["unassigned_by_design"])
    e = {x["product_code"]: x for x in out}["P-1"]
    assert e["billed_qty"] == 2.0 and e["available_qty"] == 1.0 and e["over_billed"] is True
    assert "unassigned_packing" not in e   # genuine over-bill, not an assignment gap


# ── The fix: design-present, product_code-NULL packing pieces ─────────────────

def test_unassigned_packing_not_counted_as_available():
    rows = [
        {"design_no": "JR07550", "product_code": None, "quantity": 1.0, "invoice_no": "INV-380"},
        {"design_no": "JR08385", "product_code": None, "quantity": 1.0, "invoice_no": "INV-380"},
    ]
    s = _snap(rows)
    # availability is NOT invented from the unassigned pieces
    assert s["available_by_product_code"] == {}
    # but they ARE captured as evidence
    assert s["unassigned_by_design"] == {
        "JR07550": {"quantity": 1.0, "count": 1, "invoice_no": "INV-380"},
        "JR08385": {"quantity": 1.0, "count": 1, "invoice_no": "INV-380"},
    }


def test_shipment_8341809162_380_reproduction():
    # Exact defect: two design-only pieces, draft bills 380-1/380-2.
    rows = [
        {"design_no": "JR07550", "product_code": None, "quantity": 1.0, "invoice_no": "EJL/26-27/380"},
        {"design_no": "JR08385", "product_code": None, "quantity": 1.0, "invoice_no": "EJL/26-27/380"},
    ]
    s = _snap(rows)
    draft = [
        {"product_code": "EJL/26-27/380-1", "design_no": "JR07550", "qty": 1.0, "line_id": "L1"},
        {"product_code": "EJL/26-27/380-2", "design_no": "JR08385", "qty": 1.0, "line_id": "L2"},
    ]
    out = analyze_product_code_billing(draft, s["available_by_product_code"],
                                       s["invoice_by_product_code"], s["unassigned_by_design"])
    by = {x["product_code"]: x for x in out}
    for code, design in (("EJL/26-27/380-1", "JR07550"), ("EJL/26-27/380-2", "JR08385")):
        e = by[code]
        # GATE PRESERVED: availability stays 0, over-bill still fires
        assert e["available_qty"] == 0.0
        assert e["over_billed"] is True
        # EVIDENCE surfaced: the real unassigned piece for this code's design
        assert e["unassigned_packing"] == [
            {"design_no": design, "quantity": 1.0, "count": 1, "invoice_no": "EJL/26-27/380"}
        ]


def test_availability_never_invented_from_piece_count():
    # Two design-only pieces must NEVER be split/credited to the two billed codes
    # merely because two codes and two pieces exist.
    rows = [
        {"design_no": "JR07550", "product_code": None, "quantity": 1.0, "invoice_no": "INV"},
        {"design_no": "JR08385", "product_code": None, "quantity": 1.0, "invoice_no": "INV"},
    ]
    s = _snap(rows)
    draft = [
        {"product_code": "P-1", "design_no": "JR07550", "qty": 1.0},
        {"product_code": "P-2", "design_no": "JR08385", "qty": 1.0},
    ]
    out = analyze_product_code_billing(draft, s["available_by_product_code"],
                                       s["invoice_by_product_code"], s["unassigned_by_design"])
    assert all(e["available_qty"] == 0.0 and e["over_billed"] for e in out)


def test_mixed_assigned_and_unassigned_same_batch():
    # 378 assigned (product_code present) + 380 unassigned (design-only) coexist.
    rows = [
        {"design_no": "JR07152", "product_code": "EJL/26-27/378-1", "quantity": 1.0, "invoice_no": "EJL/26-27/378"},
        {"design_no": "JR07550", "product_code": None,              "quantity": 1.0, "invoice_no": "EJL/26-27/380"},
    ]
    s = _snap(rows)
    assert s["available_by_product_code"] == {"EJL/26-27/378-1": 1.0}
    assert "JR07550" in s["unassigned_by_design"] and "JR07152" not in s["unassigned_by_design"]


def test_product_code_stripped_match_preserved():
    # existing strip-normalization: trailing space on the draft line still matches.
    rows = [{"design_no": "D1", "product_code": "P-1", "quantity": 2.0, "invoice_no": "INV"}]
    s = _snap(rows)
    draft = [{"product_code": " P-1 ", "design_no": "D1", "qty": 1.0}]
    out = analyze_product_code_billing(draft, s["available_by_product_code"],
                                       s["invoice_by_product_code"], s["unassigned_by_design"])
    # billed 1 <= available 2, single line → no blocker
    assert out == []


def test_zero_quantity_unassigned_row_produces_no_false_evidence():
    # a design-only row with quantity 0 must not be surfaced as a real piece.
    rows = [{"design_no": "JR07550", "product_code": None, "quantity": 0.0, "invoice_no": "INV"}]
    s = _snap(rows)
    draft = [{"product_code": "P-1", "design_no": "JR07550", "qty": 1.0}]
    out = analyze_product_code_billing(draft, s["available_by_product_code"],
                                       s["invoice_by_product_code"], s["unassigned_by_design"])
    e = {x["product_code"]: x for x in out}["P-1"]
    assert e["over_billed"] is True
    assert "unassigned_packing" not in e   # qty 0 → not a real piece, no false evidence
