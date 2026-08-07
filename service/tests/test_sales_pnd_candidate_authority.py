"""Sales PND candidate authority: candidates come from invoice_lines, never
from packing rows.

The defect class: ``supplier_candidates`` were built from ``packing_lines``,
whose ``product_code`` is itself the OUTPUT of the packing→invoice matcher. A
purchase-side mis-assignment therefore corrupted the sales candidate set (and a
NULL packing code tripped the "supplier candidate missing product_code" refusal
outright) — circular truth. ``build_supplier_candidates`` severs it: identity,
price and item type come from the invoice authority; packing rows corroborate
(design_no) but never define or veto a candidate.

Includes the hard over-allocation regression: purchase authority qty 1 vs sales
demand 2 must be REFUSED — never duplicated, never invented.

All fixtures synthetic — the repository is public.
"""
from __future__ import annotations

from app.services.sales_pnd_disambiguator import (
    build_supplier_candidates,
    disambiguate_pnd,
)

INV = "TEST/00-00/001"


def _il(pos, desc, qty=1.0, rate=10.0):
    return {
        "invoice_no": INV, "line_position": pos, "product_code": f"{INV}-{pos}",
        "description": desc, "quantity": qty, "rate_usd": rate,
        "unit_price": rate, "total_value": qty * rate,
    }


def _pl(sr, pos, design="SYN", item_type="PENDANT", code="__default__"):
    return {
        "pack_sr": sr, "invoice_no": INV,
        "invoice_line_position": pos, "item_type": item_type,
        "design_no": design,
        "product_code": (f"{INV}-{pos}" if code == "__default__" else code),
    }


def _sale(price, qty=1.0):
    return {"design_no": "PND", "unit_price": price, "quantity": qty,
            "invoice_no": INV, "product_code": ""}


# ── Candidate construction: authority, not packing ───────────────────────────

def test_candidates_come_from_invoice_lines_not_packing_assignment():
    """A wrong or NULL packing assignment must not corrupt the candidate set."""
    lines = [
        _il(1, "PCS, SL925 SILVER Plain Jewellery PENDANT", rate=5.0),
        _il(2, "PCS, 14KT Gold Studded PENDANT", rate=106.0),
        _il(3, "PCS, 18KT Gold LGD RING", rate=200.0),
    ]
    # Packing is maximally broken: the silver pendant row is orphaned (NULL)
    # and the gold pendant row was stolen onto the ring line.
    packing = [
        _pl(1, None, design="SYN-A", code=None),
        _pl(2, 3, design="SYN-B", code=f"{INV}-3"),
    ]
    cands = build_supplier_candidates(lines, packing, invoice_no=INV)

    codes = sorted(c["product_code"] for c in cands)
    assert codes == [f"{INV}-1", f"{INV}-2"]          # both pendant LINES, no ring
    by_code = {c["product_code"]: c for c in cands}
    assert by_code[f"{INV}-1"]["unit_price"] == 5.0    # price from the line itself
    assert by_code[f"{INV}-2"]["unit_price"] == 106.0
    assert all(c["authority_qty"] == 1.0 for c in cands)


def test_aggregate_packing_rows_do_not_inflate_the_candidate_count():
    """One invoice line = one candidate, however many packing rows sit on it."""
    lines = [_il(1, "PCS, 14KT Gold PENDANT", qty=3.0, rate=50.0)]
    packing = [_pl(sr, 1) for sr in (1, 2, 3)]        # N:1 aggregate assignment
    cands = build_supplier_candidates(lines, packing, invoice_no=INV)
    assert len(cands) == 1
    assert cands[0]["authority_qty"] == 3.0


def test_packing_corroborates_design_no_but_cannot_veto_a_candidate():
    lines = [_il(1, "PCS, 14KT Gold PENDANT", rate=50.0)]
    with_packing = build_supplier_candidates(
        lines, [_pl(1, 1, design="SYN-D")], invoice_no=INV)
    without_packing = build_supplier_candidates(lines, [], invoice_no=INV)

    assert with_packing[0]["design_no"] == "SYN-D"
    assert without_packing[0]["design_no"] == ""
    # Same candidate either way — packing evidence never decides existence.
    assert with_packing[0]["product_code"] == without_packing[0]["product_code"]
    assert len(with_packing) == len(without_packing) == 1


def test_candidates_are_scoped_to_the_requested_invoice():
    lines = [
        _il(1, "PCS, 14KT PENDANT", rate=50.0),
        {**_il(2, "PCS, 925 PENDANT", rate=5.0),
         "invoice_no": "TEST/00-00/002", "product_code": "TEST/00-00/002-2"},
    ]
    cands = build_supplier_candidates(lines, [], invoice_no=INV)
    assert [c["product_code"] for c in cands] == [f"{INV}-1"]


# ── The removed coupling, end to end ─────────────────────────────────────────

def test_resolver_fires_even_when_purchase_packing_is_null():
    """The exact incident: a NULL purchase assignment used to poison the sales
    candidate set. With invoice-sourced candidates the resolver still fires."""
    lines = [
        _il(1, "PCS, SL925 SILVER Plain PENDANT", rate=4.0),
        _il(2, "PCS, 14KT Gold PENDANT", rate=36.0),
    ]
    packing = [_pl(1, None, code=None), _pl(2, None, code=None)]  # all orphaned
    cands = build_supplier_candidates(lines, packing, invoice_no=INV)

    sales = [_sale(5.13), _sale(51.30)]
    out, summary = disambiguate_pnd(sales, cands, invoice_no=INV)

    assert summary["applied"] is True
    assert out[0]["product_code"] == f"{INV}-1"       # cheap → cheap
    assert out[1]["product_code"] == f"{INV}-2"
    assert all(r["pnd_mapping_source"] == "price_tiebreak" for r in out)


# ── Hard over-allocation regression ──────────────────────────────────────────

def test_authority_one_sales_demand_two_rows_is_refused_not_duplicated():
    """Purchase authority qty 1, sales demand 2 PND rows → block, don't invent.

    One pendant line exists; two sales PND rows want codes. The count gate must
    refuse — the same code must never be stamped onto both rows, and no second
    candidate may be invented.
    """
    lines = [_il(1, "PCS, 14KT Gold PENDANT", qty=1.0, rate=50.0)]
    cands = build_supplier_candidates(lines, [], invoice_no=INV)
    sales = [_sale(60.0), _sale(70.0)]

    out, summary = disambiguate_pnd(sales, cands, invoice_no=INV)

    assert summary["applied"] is False
    assert "count mismatch" in summary["reason"]
    assert all(not r.get("product_code") for r in out)   # nothing stamped


def test_sales_row_quantity_exceeding_line_authority_is_refused():
    """Even with matching counts, a single sales row demanding more pieces than
    the invoice line authorises must be refused, not paired."""
    lines = [_il(1, "PCS, 14KT Gold PENDANT", qty=1.0, rate=50.0)]
    cands = build_supplier_candidates(lines, [], invoice_no=INV)
    sales = [_sale(60.0, qty=2.0)]                     # demand 2 vs authority 1

    out, summary = disambiguate_pnd(sales, cands, invoice_no=INV)

    assert summary["applied"] is False
    assert "exceeds invoice authority" in summary["reason"]
    assert not out[0].get("product_code")


def test_refusal_leaves_no_half_applied_pairing():
    """If any pair fails a gate, NO row may keep a stamped code."""
    lines = [
        _il(1, "PCS, 925 PENDANT", qty=1.0, rate=5.0),
        _il(2, "PCS, 14KT PENDANT", qty=1.0, rate=50.0),
    ]
    cands = build_supplier_candidates(lines, [], invoice_no=INV)
    # First (cheap) pair is fine; second demands 3 pcs against authority 1.
    sales = [_sale(6.0, qty=1.0), _sale(60.0, qty=3.0)]

    out, summary = disambiguate_pnd(sales, cands, invoice_no=INV)

    assert summary["applied"] is False
    assert all(not r.get("product_code") for r in out)
    assert all("pnd_mapping_source" not in r for r in out)


def test_candidates_without_authority_qty_keep_legacy_behaviour():
    """Hand-built candidates (existing tests, manual tooling) omit
    authority_qty — the gate must not fire on absent evidence."""
    cands = [{"product_code": f"{INV}-1", "unit_price": 50.0,
              "item_type": "PENDANT", "design_no": ""}]
    sales = [_sale(60.0, qty=5.0)]
    out, summary = disambiguate_pnd(sales, cands, invoice_no=INV)
    assert summary["applied"] is True
    assert out[0]["product_code"] == f"{INV}-1"
