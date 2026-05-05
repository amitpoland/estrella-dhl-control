"""
test_sales_to_wfirma_view.py — Read-only resolution view for sales→wFirma.

Covers the v_sales_to_wfirma view created in document_db.init_document_db()
and the query_sales_to_wfirma() helper.

Required coverage:
  1. matched design resolves wfirma_product_code
  2. unmatched design remains with NULL wfirma_product_code
  3. two sales rows mapping to same product_code aggregate qty correctly
  4. scoped by batch_id — same design in another batch does not leak
"""
from __future__ import annotations

import uuid

import pytest

from app.services import packing_db as pdb
from app.services import document_db as ddb


@pytest.fixture()
def db(tmp_path):
    # Order matters: packing first, so document_db's _connect() can ATTACH it.
    pdb.init_packing_db(tmp_path / "packing.db")
    ddb.init_document_db(tmp_path / "documents.db")
    return tmp_path


def _seed_purchase(batch_id: str, *, design_no: str, product_code: str,
                   pack_sr: float = 1.0, qty: float = 1.0) -> None:
    pdb.upsert_packing_lines([{
        "batch_id":              batch_id,
        "invoice_no":            "INV/X",
        "invoice_line_position": int(pack_sr),
        "product_code":          product_code,
        "design_no":             design_no,
        "bag_id":                "",
        "tray_id":               "",
        "item_type":             "RNG",
        "uom":                   "PCS",
        "quantity":              qty,
        "gross_weight":          0.0,
        "net_weight":            0.0,
        "metal":                 "",
        "karat":                 "",
        "stone_type":            "",
        "remarks":               "",
        "extracted_confidence":  1.0,
        "requires_manual_review": False,
        "pack_sr":               pack_sr,
        "unit_price":            100.0,
        "total_value":           100.0,
    }])


def _seed_sales_doc(batch_id: str, client_name: str, sales_doc_no: str) -> str:
    return ddb.store_sales_document(
        batch_id=batch_id,
        document_id=str(uuid.uuid4()),
        data={
            "client_name":  client_name,
            "client_ref":   "REF-1",
            "sales_doc_no": sales_doc_no,
        },
    )


def _seed_sales_lines(sales_document_id: str, batch_id: str,
                      client_name: str, lines: list) -> None:
    rows = [{
        "client_name":  client_name,
        "client_ref":   "REF-1",
        "product_code": ln["sku"],         # intake stores SKU as product_code
        "design_no":    ln["sku"],
        "bag_id":       "",
        "quantity":     ln["qty"],
        "remarks":      "",
    } for ln in lines]
    ddb.store_sales_packing_lines(sales_document_id, batch_id, rows)


# ── 1. Matched design resolves wfirma_product_code ──────────────────────────

def test_matched_design_resolves_product_code(db):
    B = "BATCH_VIEW_1"
    _seed_purchase(B, design_no="CSTR07576", product_code="EJL/26-27/100-1")
    sd = _seed_sales_doc(B, "ACME", "SO-1001")
    _seed_sales_lines(sd, B, "ACME", [{"sku": "CSTR07576", "qty": 2.0}])

    rows = ddb.query_sales_to_wfirma(B)
    assert len(rows) == 1
    r = rows[0]
    assert r["batch_id"]            == B
    assert r["client_name"]         == "ACME"
    assert r["sales_doc_no"]        == "SO-1001"
    assert r["sales_design_no"]     == "CSTR07576"
    assert r["wfirma_product_code"] == "EJL/26-27/100-1"
    assert r["purchase_design_no"]  == "CSTR07576"
    assert r["qty"]                 == 2.0


# ── 2. Unmatched design surfaces with NULL wfirma_product_code ──────────────

def test_unmatched_design_returns_null_product_code(db):
    B = "BATCH_VIEW_2"
    _seed_purchase(B, design_no="CSTR07576", product_code="EJL/26-27/100-1")
    sd = _seed_sales_doc(B, "ACME", "SO-2001")
    _seed_sales_lines(sd, B, "ACME", [{"sku": "GHOST_SKU", "qty": 1.0}])

    rows = ddb.query_sales_to_wfirma(B)
    assert len(rows) == 1
    r = rows[0]
    assert r["sales_design_no"]     == "GHOST_SKU"
    assert r["wfirma_product_code"] is None
    assert r["purchase_design_no"]  is None
    assert r["qty"]                 == 1.0


# ── 3. Two sales rows mapping to same product_code aggregate ────────────────

def test_two_sales_rows_aggregate_to_same_product_code(db):
    B = "BATCH_VIEW_3"
    # Two purchase rows share the same product_code via different design_nos
    # — but more realistically, two sales rows with the same SKU under one
    # sales document should aggregate. Test that case.
    _seed_purchase(B, design_no="CSTR07576", product_code="EJL/26-27/100-1")
    sd = _seed_sales_doc(B, "ACME", "SO-3001")
    _seed_sales_lines(sd, B, "ACME", [
        {"sku": "CSTR07576", "qty": 2.0},
        {"sku": "CSTR07576", "qty": 3.0},
    ])

    rows = ddb.query_sales_to_wfirma(B)
    assert len(rows) == 1
    r = rows[0]
    assert r["wfirma_product_code"] == "EJL/26-27/100-1"
    assert r["qty"]                 == 5.0


# ── 4. batch_id scoping — same design in another batch does not leak ────────

def test_view_scoped_by_batch_id(db):
    B1 = "BATCH_A"
    B2 = "BATCH_B"

    # Same design exists in both batches with different wfirma product_codes
    _seed_purchase(B1, design_no="CSTR07576", product_code="EJL/26-27/A-1")
    _seed_purchase(B2, design_no="CSTR07576", product_code="EJL/26-27/B-1")

    sd1 = _seed_sales_doc(B1, "ACME", "SO-A")
    sd2 = _seed_sales_doc(B2, "ACME", "SO-B")
    _seed_sales_lines(sd1, B1, "ACME", [{"sku": "CSTR07576", "qty": 1.0}])
    _seed_sales_lines(sd2, B2, "ACME", [{"sku": "CSTR07576", "qty": 9.0}])

    rows_a = ddb.query_sales_to_wfirma(B1)
    rows_b = ddb.query_sales_to_wfirma(B2)

    assert len(rows_a) == 1 and rows_a[0]["wfirma_product_code"] == "EJL/26-27/A-1"
    assert rows_a[0]["qty"] == 1.0
    assert len(rows_b) == 1 and rows_b[0]["wfirma_product_code"] == "EJL/26-27/B-1"
    assert rows_b[0]["qty"] == 9.0


# ── 5. Empty batch — empty list ─────────────────────────────────────────────

def test_empty_batch_returns_empty_list(db):
    assert ddb.query_sales_to_wfirma("NO_SUCH_BATCH") == []


# ── 6. Normalization: case + whitespace insensitive match ───────────────────

def test_match_is_case_and_whitespace_insensitive(db):
    B = "BATCH_NORM"
    _seed_purchase(B, design_no="CSTR07576", product_code="EJL/26-27/N-1")
    sd = _seed_sales_doc(B, "ACME", "SO-N")
    _seed_sales_lines(sd, B, "ACME", [{"sku": "  cstr07576  ", "qty": 1.0}])

    rows = ddb.query_sales_to_wfirma(B)
    assert rows[0]["wfirma_product_code"] == "EJL/26-27/N-1"
