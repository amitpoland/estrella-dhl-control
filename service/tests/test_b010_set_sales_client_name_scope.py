"""B-010: set_sales_client_name multi-client non-clobber pin.

When old_client_name is supplied, only lines matching that name are renamed.
A second distinct client_name on the same sales_document must be left intact.

Run: python -m pytest tests/test_b010_set_sales_client_name_scope.py -q
"""
from __future__ import annotations

import sqlite3
import uuid

import pytest

from app.services import document_db as ddb


@pytest.fixture()
def docdb(tmp_path):
    ddb.init_document_db(tmp_path / "documents.db")
    return tmp_path


def _line(client_name: str, product_code: str) -> dict:
    return {
        "client_name": client_name,
        "product_code": product_code,
        "design_no": product_code,
        "qty": 1,
        "unit_price": 10.0,
        "currency": "PLN",
    }


def _line_names(db_dir, sales_document_id: str) -> dict:
    with sqlite3.connect(str(db_dir / "documents.db")) as con:
        rows = con.execute(
            "SELECT product_code, client_name FROM sales_packing_lines "
            "WHERE sales_document_id=? ORDER BY product_code",
            (sales_document_id,),
        ).fetchall()
    return {pc: name for pc, name in rows}


def test_scoped_rename_leaves_other_client_lines(docdb):
    B = "B010_MULTI"
    doc_id = str(uuid.uuid4())
    sd = ddb.store_sales_document(
        B, doc_id,
        {"client_name": "Alpha Co", "document_type": "sales_packing_list"},
    )
    ddb.store_sales_packing_lines(
        sd, B,
        [
            _line("Alpha Co", "PC-A1"),
            _line("Alpha Co", "PC-A2"),
            _line("Beta Ltd", "PC-B1"),
        ],
    )

    n = ddb.set_sales_client_name(
        B, sd, "ALPHA CANONICAL", old_client_name="Alpha Co",
    )
    assert n == 2

    by_pc = _line_names(docdb, sd)
    assert by_pc["PC-A1"] == "ALPHA CANONICAL"
    assert by_pc["PC-A2"] == "ALPHA CANONICAL"
    assert by_pc["PC-B1"] == "Beta Ltd"  # must not be clobbered


def test_unscoped_rename_updates_all_lines(docdb):
    B = "B010_ALL"
    doc_id = str(uuid.uuid4())
    sd = ddb.store_sales_document(
        B, doc_id,
        {"client_name": "Only", "document_type": "sales_packing_list"},
    )
    ddb.store_sales_packing_lines(
        sd, B, [_line("Only", "PC-1"), _line("Only", "PC-2")],
    )
    n = ddb.set_sales_client_name(B, sd, "CANON")
    assert n == 2
    assert set(_line_names(docdb, sd).values()) == {"CANON"}
