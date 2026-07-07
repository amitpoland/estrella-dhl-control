"""test_sales_persistence_authority.py — Package 1.

Pins the single canonical sales-packing persistence authority
(document_db.persist_sales_from_packing): intake, re-ingest, and reprocess all
route through it, producing identical, idempotent, non-duplicated
sales_packing_lines keyed to a DETERMINISTIC sales_document_id (== the sales
packing shipment_documents.id) — never the legacy random UUID that caused the
intake-vs-reprocess duplication.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.services import document_db as ddb

B = "SHIPMENT_SALESUNIFY_2026"


def _rows():
    # One faithful parser row: distinct client_po / remarks / invoice_no so the
    # separate-column pin is meaningful, plus full variant identity.
    return [{
        "product_code": "EJL/1-1", "design_no": "D1", "quantity": 2,
        "unit_price": 10.0, "total_value": 20.0, "currency": "eur",
        "price_source": "excel_symbol",
        "client_po": "PO-9", "remarks": "handle with care", "invoice_no": "INV/1",
        "item_type": "RING", "karat": "14KT", "metal": "14KT/W", "metal_color": "W",
        "quality_string": "RD75", "stone_type": "", "size": "18-C",
        "diamond_weight": 0.035, "color_weight": 0.0,
    }]


@pytest.fixture
def db(tmp_path):
    ddb.init_document_db(tmp_path / "documents.db")
    doc_id = ddb.register_document(
        batch_id=B, document_type="sales_packing_list", file_name="sales.xlsx")
    return tmp_path / "documents.db", doc_id


def _lines(dbp, doc_id):
    con = sqlite3.connect(str(dbp)); con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM sales_packing_lines WHERE sales_document_id=? "
        "ORDER BY product_code", (doc_id,))]
    con.close(); return rows


def _doc_counts(dbp, doc_id):
    con = sqlite3.connect(str(dbp))
    n_id = con.execute("SELECT COUNT(*) FROM sales_documents WHERE id=?", (doc_id,)).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM sales_documents WHERE batch_id=?", (B,)).fetchone()[0]
    con.close(); return n_id, total


# ── 6. no random sales_document_id authority remains ─────────────────────────
def test_deterministic_sales_document_id_no_random_uuid(db):
    dbp, doc_id = db
    ddb.persist_sales_from_packing(B, doc_id, _rows(), client_name="MDS")
    n_id, total = _doc_counts(dbp, doc_id)
    assert n_id == 1 and total == 1, "sales_documents id must equal the doc_id (deterministic), exactly one row"
    assert _lines(dbp, doc_id)[0]["sales_document_id"] == doc_id


# ── 4. client_po / remarks / invoice_no preserved separately ─────────────────
def test_client_po_remarks_invoice_no_kept_separate(db):
    dbp, doc_id = db
    ddb.persist_sales_from_packing(B, doc_id, _rows(), client_name="MDS")
    ln = _lines(dbp, doc_id)[0]
    assert ln["client_po"] == "PO-9"
    assert ln["remarks"] == "handle with care"      # NOT collapsed with client_po
    assert ln["invoice_no"] == "INV/1"              # NOT dropped
    assert "PO-9" not in (ln["remarks"] or "")
    # variant identity forwarded (reprocess previously omitted these)
    assert ln["karat"] == "14KT" and ln["metal_color"] == "W" and ln["size"] == "18-C"


# ── 1. intake output == reprocess output ─────────────────────────────────────
def test_intake_output_equals_reprocess_output(db):
    dbp, doc_id = db
    ddb.persist_sales_from_packing(B, doc_id, _rows(), client_name="MDS")   # intake
    a = _lines(dbp, doc_id)
    ddb.persist_sales_from_packing(B, doc_id, _rows(), client_name="MDS")   # reprocess (same doc_id)
    b = _lines(dbp, doc_id)
    strip = lambda rows: [{k: v for k, v in r.items() if k not in ("id", "created_at")} for r in rows]
    assert strip(a) == strip(b)


# ── 2 + 5. intake -> reprocess idempotent, no duplicate ──────────────────────
def test_intake_then_reprocess_idempotent_no_duplicate(db):
    dbp, doc_id = db
    ddb.persist_sales_from_packing(B, doc_id, _rows(), client_name="MDS")   # intake
    ddb.persist_sales_from_packing(B, doc_id, _rows(), client_name="MDS")   # reprocess
    assert len(_lines(dbp, doc_id)) == len(_rows())    # exactly one row set — no duplicate


# ── 3. reprocess -> reprocess idempotent ─────────────────────────────────────
def test_reprocess_reprocess_idempotent(db):
    dbp, doc_id = db
    for _ in range(3):
        ddb.persist_sales_from_packing(B, doc_id, _rows(), client_name="MDS")
    assert len(_lines(dbp, doc_id)) == len(_rows())


# ── source-grep pins: single writer / no legacy line writer ──────────────────
_API = Path(__file__).resolve().parent.parent / "app" / "api"


def _src(name):
    return (_API / name).read_text(encoding="utf-8")


def test_no_store_sales_packing_lines_caller_remains():
    for f in ("routes_intake.py", "routes_packing.py"):
        assert "store_sales_packing_lines(" not in _src(f), (
            f"{f} still calls store_sales_packing_lines — sales-packing persistence "
            f"must route through persist_sales_from_packing")


def test_sales_packing_flows_use_canonical_authority():
    assert "persist_sales_from_packing(" in _src("routes_intake.py")
    assert "persist_sales_from_packing(" in _src("routes_packing.py")
