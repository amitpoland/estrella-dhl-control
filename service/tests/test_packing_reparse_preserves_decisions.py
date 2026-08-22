"""test_packing_reparse_preserves_decisions.py — a reparse must not erase what
an operator decided.

The force-reparse path in routes_dhl_clearance used to open-code
``DELETE FROM packing_lines WHERE batch_id = ?`` against packing_db's file.
That delete bypassed packing_db's lock and every decision-preserving branch in
upsert_packing_lines, so one operator pressing "regenerate" silently erased the
product-review confirmations for the whole batch with no record that anything
was lost. replace_batch_packing_lines is the helper that comment asked for.

These tests were split out of the retired test_packing_allocation.py when the
cancelled packing-allocation authority was removed from main; the reparse
repair is independent of it and stays.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture()
def pdb(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services import packing_db as _pdb

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    _pdb.init_packing_db(tmp_path / "packing.db")
    return _pdb


def _reparse_rows(batch_id, doc_id, rows):
    """The shape routes_dhl_clearance hands to the replace helper."""
    return [{"packing_document_id": doc_id, "batch_id": batch_id,
             "invoice_no": "INV-1", "invoice_line_position": r["pos"],
             "design_no": r["design"], "quantity": r["qty"],
             "unit_price": 25.0, "item_type": "RING", "metal": "14KT",
             "pack_sr": r["sr"], "product_code": r.get("pc")} for r in rows]


def test_a_reparse_preserves_an_operator_product_confirmation(pdb):
    """The delete destroyed PR-2 product-review confirmations. Deliberately,
    upsert_packing_lines carries that pair across a re-extract; deleting first
    defeated it."""
    bid = "SHIPMENT_REPARSE_2"
    doc_id = pdb.upsert_packing_document(
        batch_id=bid, invoice_no="INV-1", source_file_path="p.xlsx",
        source_file_hash="h-reparse-2", extraction_status="ok")
    rows = _reparse_rows(bid, doc_id, [{"pos": 1, "design": "D-100",
                                        "qty": 10, "sr": 1, "pc": "PC-1"}])
    pdb.upsert_packing_lines(rows)
    pdb.confirm_product_review(bid, "PC-1", operator="jigar")

    pdb.replace_batch_packing_lines(bid, rows)

    after = pdb.get_packing_lines_for_batch(bid)[0]
    assert after["operator_review_status"] == "confirmed"
    assert after["operator_confirmed_by"] == "jigar"


def test_a_decision_whose_line_vanished_is_reported_not_silently_lost(pdb):
    """If the new parse no longer carries the line, the decision cannot be put
    back — the goods it described are not claimed by the source any more. That
    is reportable, not forgettable."""
    bid = "SHIPMENT_REPARSE_3"
    doc_id = pdb.upsert_packing_document(
        batch_id=bid, invoice_no="INV-1", source_file_path="p.xlsx",
        source_file_hash="h-reparse-3", extraction_status="ok")
    pdb.upsert_packing_lines(_reparse_rows(bid, doc_id, [
        {"pos": 1, "design": "D-100", "qty": 10, "sr": 1, "pc": "PC-1"},
        {"pos": 2, "design": "D-200", "qty": 5, "sr": 2, "pc": "PC-2"}]))
    pdb.confirm_product_review(bid, "PC-2", operator="jigar")

    # revised list drops the D-200/PC-2 line entirely
    out = pdb.replace_batch_packing_lines(bid, _reparse_rows(bid, doc_id, [
        {"pos": 1, "design": "D-100", "qty": 10, "sr": 1, "pc": "PC-1"}]))

    assert out["decisions_dropped"] == 1
    assert out["decisions_preserved"] == 0
    assert out["dropped"][0]["operator_review_status"] == "confirmed"


def test_the_clearance_reparse_no_longer_deletes_packing_lines_directly():
    """Source pin: the one-writer claim is about writes, but a DELETE erases
    the same columns. No module outside packing_db may delete packing_lines."""
    app_dir = _ROOT / "app"
    offenders = []
    for py in app_dir.rglob("*.py"):
        if py.name == "packing_db.py":
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        for n, line in enumerate(text.splitlines(), 1):
            if "DELETE FROM packing_lines" in line.upper().replace("  ", " "):
                offenders.append(f"{py.relative_to(_ROOT)}:{n}")
    assert offenders == [], f"packing_lines deleted outside packing_db: {offenders}"
