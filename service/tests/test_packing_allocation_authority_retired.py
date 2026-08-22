"""test_packing_allocation_authority_retired.py — the cancelled packing
allocation authority stays off main.

The operator cancelled the packing-allocation campaign, rejecting any
architecture that can block or condition the normal Purchase / Packing / Sales
/ Warehouse flow on an allocation confirmation. The implementation nevertheless
reached main as PR #1312 and would have deployed on the next release. It is
removed; this pin is what stops it coming back unnoticed.

Note the shape of the risk it guards. The allocation code was never wired to a
route or a page — but init_packing_db ALTERed the live packing_lines table with
eleven allocation columns plus an index on every service start, so shipping it
would have mutated production schema for an authority nobody approved.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# The four writer functions and the read-side rule of the cancelled authority.
_RETIRED_FUNCTIONS = (
    "set_allocation_suggestion", "confirm_allocation", "clear_allocation",
    "allocation_is_stale",
)

# Every column the cancelled migration added to packing_lines.
_RETIRED_COLUMNS = (
    "allocation_source", "suggested_customer_name", "suggested_customer_id",
    "allocated_customer_id", "allocation_confirmed_at", "allocation_confirmed_by",
    "allocation_source_revision", "allocation_strategy", "allocation_cleared_at",
    "allocation_cleared_by", "allocation_cleared_reason",
)


@pytest.fixture()
def pdb(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services import packing_db as _pdb

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    _pdb.init_packing_db(tmp_path / "packing.db")
    return _pdb


def test_packing_db_exposes_no_allocation_writer(pdb):
    present = [f for f in _RETIRED_FUNCTIONS if hasattr(pdb, f)]
    assert present == [], (
        "the cancelled packing-allocation authority is back in packing_db: "
        f"{present}"
    )


def test_init_does_not_migrate_allocation_columns_onto_packing_lines(pdb):
    """The one live effect the cancelled campaign would have had on production."""
    with sqlite3.connect(str(pdb._db_path)) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(packing_lines)")}
        idx = {r[1] for r in con.execute("PRAGMA index_list(packing_lines)")}
    back = sorted(cols & set(_RETIRED_COLUMNS))
    assert back == [], f"allocation columns migrated onto packing_lines: {back}"
    assert "idx_pl_allocated_customer" not in idx


def test_no_runtime_module_references_the_cancelled_authority():
    """Source pin across the whole deployed tree, not just packing_db."""
    needles = _RETIRED_FUNCTIONS + _RETIRED_COLUMNS
    offenders = []
    for py in (_ROOT / "app").rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        for n, line in enumerate(text.splitlines(), 1):
            for needle in needles:
                if needle in line:
                    offenders.append(f"{py.relative_to(_ROOT)}:{n}: {needle}")
    assert offenders == [], (
        "cancelled allocation authority referenced in runtime code:\n"
        + "\n".join(offenders)
    )


def test_normal_packing_flow_has_no_allocation_prerequisite(pdb):
    """The operator's actual requirement: parse, store, read back and reparse a
    batch without confirming an allocation anywhere, and without a stored row
    carrying allocation state."""
    bid = "SHIPMENT_NO_ALLOC"
    doc_id = pdb.upsert_packing_document(
        batch_id=bid, invoice_no="INV-1", source_file_path="p.xlsx",
        source_file_hash="h-no-alloc", extraction_status="ok")
    rows = [{
        "packing_document_id": doc_id, "batch_id": bid, "invoice_no": "INV-1",
        "invoice_line_position": 1, "design_no": "D-100", "quantity": 10,
        "unit_price": 25.0, "item_type": "RING", "metal": "14KT",
        "pack_sr": 1, "product_code": "PC-1",
    }]
    assert pdb.upsert_packing_lines(rows) == 1

    stored = pdb.get_packing_lines_for_batch(bid)
    assert len(stored) == 1
    leaked = sorted(set(stored[0].keys()) & set(_RETIRED_COLUMNS))
    assert leaked == [], f"allocation state on a normal packing line: {leaked}"

    # a reparse of the same batch still completes with no allocation concept
    out = pdb.replace_batch_packing_lines(bid, rows)
    assert out["stored"] == 1
    assert out["decisions_dropped"] == 0
