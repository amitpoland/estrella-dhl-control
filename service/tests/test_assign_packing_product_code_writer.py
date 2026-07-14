"""test_assign_packing_product_code_writer.py

Writer-level pins for
``packing_db.assign_product_code_to_unassigned_design`` — the canonical
single-purpose product_code stamp behind the operator-confirmation repair of the
unassigned-packing over-bill defect (Part 2 of SHIPMENT_8341809162
EJL/26-27/380-1 / -2, designs JR07550 / JR08385 that arrived design-only).

The writer MUST:
  * stamp ONLY rows whose product_code is NULL/'' for the matching design+batch;
  * never touch an already-assigned row, never invent rows, never change qty;
  * recompute scan_code so barcode identity stays consistent;
  * enforce ``expected_count`` (TOCTOU guard) — no partial stamp;
  * be idempotent (a second call finds 0 unassigned → assigned 0);
  * make the pieces countable by the availability authority afterwards.
"""
from __future__ import annotations

import pytest

from app.services import packing_db as pdb
from app.services.product_authority_resolver import resolve_batch_product_authority

BATCH = "BATCH_ASSIGN_W"


def _row(design_no, pos, product_code=None, qty=1.0, invoice="EJL/26-27/380"):
    return {
        "batch_id": BATCH, "invoice_no": invoice, "invoice_line_position": pos,
        "product_code": product_code, "design_no": design_no,
        "bag_id": "", "tray_id": "", "item_type": "RNG", "uom": "PCS",
        "quantity": qty, "gross_weight": 0.0, "net_weight": 0.0,
        "metal": "", "karat": "", "stone_type": "", "remarks": "",
        "extracted_confidence": 1.0, "requires_manual_review": False,
        "pack_sr": float(pos), "unit_price": 50.0, "total_value": 50.0,
    }


@pytest.fixture()
def db(tmp_path):
    pdb.init_packing_db(tmp_path / "packing.db")
    yield pdb


def _rows(design):
    return [r for r in pdb.get_packing_lines_for_batch(BATCH)
            if (r.get("design_no") or "").strip() == design]


# ── core stamp ────────────────────────────────────────────────────────────────

def test_stamps_only_unassigned_matching_design(db):
    pdb.upsert_packing_lines([_row("JR07550", 1), _row("JR08385", 2)])
    res = pdb.assign_product_code_to_unassigned_design(
        BATCH, "JR07550", "EJL/26-27/380-1")
    assert res["assigned"] == 1 and res["matched"] == 1
    # only JR07550 rows now carry the code; JR08385 untouched
    assert [r["product_code"] for r in _rows("JR07550")] == ["EJL/26-27/380-1"]
    assert [r["product_code"] for r in _rows("JR08385")] == [None]


def test_quantity_is_never_changed(db):
    pdb.upsert_packing_lines([_row("JR07550", 1, qty=1.0)])
    pdb.assign_product_code_to_unassigned_design(BATCH, "JR07550", "EJL/26-27/380-1")
    assert _rows("JR07550")[0]["quantity"] == 1.0


def test_does_not_restamp_already_assigned_row(db):
    # design already fully assigned to a code → nothing to stamp, no overwrite.
    pdb.upsert_packing_lines([_row("JR07550", 1, product_code="EJL/26-27/380-9")])
    res = pdb.assign_product_code_to_unassigned_design(
        BATCH, "JR07550", "EJL/26-27/380-1")
    assert res["assigned"] == 0 and res["matched"] == 0
    assert res["already_assigned_to"] == ["EJL/26-27/380-9"]
    # the existing assignment is untouched — never overwritten
    assert [r["product_code"] for r in _rows("JR07550")] == ["EJL/26-27/380-9"]


def test_mixed_assigned_and_unassigned_only_blank_stamped(db):
    pdb.upsert_packing_lines([
        _row("JR07550", 1, product_code=None),
        _row("JR07550", 2, product_code="EJL/26-27/380-1"),
    ])
    res = pdb.assign_product_code_to_unassigned_design(
        BATCH, "JR07550", "EJL/26-27/380-1")
    assert res["assigned"] == 1
    assert sorted(r["product_code"] for r in _rows("JR07550")) == [
        "EJL/26-27/380-1", "EJL/26-27/380-1"]


# ── count guard / idempotency ─────────────────────────────────────────────────

def test_expected_count_mismatch_refuses_no_partial_stamp(db):
    pdb.upsert_packing_lines([_row("JR07550", 1), _row("JR07550", 2)])
    with pytest.raises(ValueError):
        pdb.assign_product_code_to_unassigned_design(
            BATCH, "JR07550", "EJL/26-27/380-1", expected_count=1)  # actual 2
    # nothing stamped — all-or-nothing
    assert [r["product_code"] for r in _rows("JR07550")] == [None, None]


def test_expected_count_match_stamps_all(db):
    pdb.upsert_packing_lines([_row("JR07550", 1), _row("JR07550", 2)])
    res = pdb.assign_product_code_to_unassigned_design(
        BATCH, "JR07550", "EJL/26-27/380-1", expected_count=2)
    assert res["assigned"] == 2


def test_idempotent_second_call_returns_zero(db):
    pdb.upsert_packing_lines([_row("JR07550", 1)])
    pdb.assign_product_code_to_unassigned_design(BATCH, "JR07550", "EJL/26-27/380-1")
    again = pdb.assign_product_code_to_unassigned_design(
        BATCH, "JR07550", "EJL/26-27/380-1")
    assert again["assigned"] == 0 and again["matched"] == 0
    assert again["already_assigned_to"] == ["EJL/26-27/380-1"]


# ── identity / validation ─────────────────────────────────────────────────────

def test_recomputes_scan_code(db):
    pdb.upsert_packing_lines([_row("JR07550", 1)])
    pdb.assign_product_code_to_unassigned_design(BATCH, "JR07550", "EJL/26-27/380-1")
    sc = _rows("JR07550")[0]["scan_code"]
    assert sc and sc.startswith("EJL/26-27/380-1") and "JR07550" in sc


def test_requires_all_fields(db):
    for args in ((BATCH, "", "P"), (BATCH, "D", ""), ("", "D", "P")):
        with pytest.raises(ValueError):
            pdb.assign_product_code_to_unassigned_design(*args)


def test_trimmed_design_match(db):
    pdb.upsert_packing_lines([_row(" JR07550 ", 1)])
    res = pdb.assign_product_code_to_unassigned_design(
        BATCH, "JR07550", "EJL/26-27/380-1")
    assert res["assigned"] == 1


# ── availability authority sees the pieces afterwards ─────────────────────────

def test_availability_becomes_countable_after_assign(db):
    pdb.upsert_packing_lines([_row("JR07550", 1), _row("JR08385", 2)])
    before = resolve_batch_product_authority(BATCH)
    assert before["available_by_product_code"] == {}
    assert "JR07550" in before["unassigned_by_design"]

    pdb.assign_product_code_to_unassigned_design(BATCH, "JR07550", "EJL/26-27/380-1")

    after = resolve_batch_product_authority(BATCH)
    # the stamped piece is now TRUE available quantity (not invented — it was a
    # real received piece all along); the other design stays unassigned evidence.
    assert after["available_by_product_code"] == {"EJL/26-27/380-1": 1.0}
    assert "JR07550" not in after["unassigned_by_design"]
    assert "JR08385" in after["unassigned_by_design"]
