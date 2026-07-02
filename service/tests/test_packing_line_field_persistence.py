"""
test_packing_line_field_persistence.py — client_po + invoice_no persistence.

Pins the 2026-07-02 silent-drop fix (PROJECT_STATE DECISIONS "client_po +
invoice_no silent-drop fix", scope evidence 2e05787e): both fields were
parsed by routes_packing (line dict :1434/:1443) but omitted from the
document_db sales_packing_lines INSERTs since inception.

Coverage required by the fix slice:
  1. parse -> persist -> readback for BOTH fields (real-shaped line dict,
     real document_db against a temp DB — no stubs, Lesson A)
  2. legacy-row default: a row inserted with the pre-fix 16-column INSERT
     reads back with client_po == '' and invoice_no == '' (never None/KeyError)
  3. drop-can't-return pin: BOTH sales_packing_lines INSERTs in
     document_db.py (store_ at ~:2013 and the replace_ copy at ~:2089) name
     both columns, and each INSERT's placeholder count equals its column count
  4. NULL-safety on the SELECT * readers (get_sales_packing_lines and
     get_sales_packing_lines_for_document)
  5. extractor alias pin: order_no -> client_po mapping survives
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from pathlib import Path

import pytest

from app.services import document_db as ddb

_DOC_DB_SRC = Path(ddb.__file__)


@pytest.fixture()
def db(tmp_path):
    ddb.init_document_db(tmp_path / "documents.db")
    return tmp_path / "documents.db"


def _line(n: int, **overrides) -> dict:
    """Real-shaped line dict — mirrors the routes_packing.py:1428-1445 record
    (the actual producer of these rows)."""
    rec = {
        "batch_id":          "BATCH_PO",
        "sales_document_id": "SDOC1",
        "client_name":       "Verhoeven BV",
        "client_ref":        "VER",
        "invoice_no":        f"EJL/26-27/300",
        "design_no":         f"D-{n:03}",
        "bag_id":            f"BAG-{n}",
        "product_code":      f"EJL/26-27/300-{n}",
        "quantity":          1.0,
        "unit_price":        12.5,
        "currency":          "EUR",
        "total_value":       12.5,
        "price_source":      "excel_symbol",
        "client_po":         f"PO-2026-{n:04}",
        "remarks":           "",
    }
    rec.update(overrides)
    return rec


# ── 1. parse → persist → readback (both fields, both write paths) ───────────

def test_store_persists_client_po_and_invoice_no(db):
    lines = [_line(1), _line(2)]
    inserted = ddb.store_sales_packing_lines("SDOC1", "BATCH_PO", lines)
    assert inserted == 2

    rows = ddb.get_sales_packing_lines("BATCH_PO")
    assert len(rows) == 2
    by_design = {r["design_no"]: r for r in rows}
    assert by_design["D-001"]["client_po"]  == "PO-2026-0001"
    assert by_design["D-002"]["client_po"]  == "PO-2026-0002"
    for r in rows:
        assert r["invoice_no"] == "EJL/26-27/300"


def test_replace_path_persists_both_fields_too(db):
    """replace_sales_packing_lines carries its OWN copy of the INSERT — the
    fix must cover both write paths (no Logic A / Logic B)."""
    ddb.store_sales_packing_lines("SDOC1", "BATCH_PO", [_line(1)])
    result = ddb.replace_sales_packing_lines(
        "SDOC1", "BATCH_PO",
        [_line(7, client_po="PO-REPLACED", invoice_no="EJL/26-27/301")],
    )
    assert isinstance(result, dict)

    rows = ddb.get_sales_packing_lines("BATCH_PO")
    assert len(rows) == 1
    assert rows[0]["client_po"]  == "PO-REPLACED"
    assert rows[0]["invoice_no"] == "EJL/26-27/301"


def test_missing_fields_default_to_empty_string(db):
    ln = _line(3)
    del ln["client_po"]
    del ln["invoice_no"]
    ddb.store_sales_packing_lines("SDOC1", "BATCH_PO", [ln])
    rows = ddb.get_sales_packing_lines("BATCH_PO")
    assert rows[0]["client_po"]  == ""
    assert rows[0]["invoice_no"] == ""


# ── 2 + 4. legacy rows read back '' via both SELECT * readers ───────────────

def test_legacy_rows_read_back_empty_never_none(db):
    """A row written by the PRE-FIX 16-column INSERT (the exact historical
    shape) must read back with '' for both new columns — the ALTER's
    DEFAULT '' backfills legacy data."""
    con = sqlite3.connect(str(db))
    con.execute(
        """INSERT INTO sales_packing_lines
           (id, batch_id, sales_document_id, client_name, client_ref,
            product_code, design_no, bag_id, quantity, remarks,
            unit_price, currency, total_value, price_source,
            client_contractor_id, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (str(uuid.uuid4()), "BATCH_LEGACY", "SDOC_L", "Old Client", "OLD",
         "EJL/25-26/001-1", "D-OLD", "", 1.0, "",
         0.0, "", 0.0, "", "", "2026-01-01T00:00:00+00:00"),
    )
    con.commit()
    con.close()

    rows = ddb.get_sales_packing_lines("BATCH_LEGACY")
    assert len(rows) == 1
    assert rows[0]["client_po"]  == ""   # not None, no KeyError
    assert rows[0]["invoice_no"] == ""

    doc_rows = ddb.get_sales_packing_lines_for_document("SDOC_L")
    assert doc_rows and doc_rows[0]["client_po"] == "" \
        and doc_rows[0]["invoice_no"] == ""


def test_alter_on_init_is_idempotent(db, tmp_path):
    # Re-init against the same file: the try/except OperationalError idiom
    # must swallow "duplicate column" — no raise, data intact.
    ddb.store_sales_packing_lines("SDOC1", "BATCH_PO", [_line(1)])
    ddb.init_document_db(tmp_path / "documents.db")
    rows = ddb.get_sales_packing_lines("BATCH_PO")
    assert rows and rows[0]["client_po"] == "PO-2026-0001"


# ── 3. drop-can't-return pin (source-grep, BOTH INSERTs) ─────────────────────

def test_both_inserts_carry_both_columns_with_matching_placeholders():
    src = _DOC_DB_SRC.read_text(encoding="utf-8", errors="replace")
    blocks = re.findall(
        r"INSERT INTO sales_packing_lines\s*\((.*?)\)\s*VALUES\s*\((.*?)\)",
        src, flags=re.DOTALL,
    )
    assert len(blocks) == 2, (
        f"expected exactly the two known sales_packing_lines INSERTs "
        f"(store_ + replace_), found {len(blocks)} — a new write path must "
        f"also persist client_po/invoice_no and be added to this pin"
    )
    for cols_raw, vals_raw in blocks:
        cols = [c.strip() for c in cols_raw.replace("\n", " ").split(",")]
        assert "client_po" in cols, "INSERT dropped client_po — silent-drop returned"
        assert "invoice_no" in cols, "INSERT dropped invoice_no — silent-drop returned"
        placeholders = vals_raw.count("?")
        assert placeholders == len(cols), (
            f"INSERT placeholder/column mismatch: {placeholders} vs {len(cols)}"
        )


def test_alter_tuple_registers_both_columns():
    src = _DOC_DB_SRC.read_text(encoding="utf-8", errors="replace")
    assert '("client_po",    "TEXT NOT NULL DEFAULT \'\'")' in src
    assert '("invoice_no",   "TEXT NOT NULL DEFAULT \'\'")' in src


# ── 5. extractor alias pin ───────────────────────────────────────────────────

def test_extractor_maps_order_no_alias_to_client_po():
    from app.services import invoice_packing_extractor as ipe
    src = Path(ipe.__file__).read_text(encoding="utf-8", errors="replace")
    assert '"client_po":   "client_po"' in src
    assert '"order_no":    "client_po"' in src, \
        "order_no → client_po alias must survive (parser feed for the fix)"
