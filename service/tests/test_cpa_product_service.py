"""Tests for cpa_product_service — CPA Phase 1 service boundary.

Covers:
  - upsert_product_master_from_packing: happy path, blank-code skip, per-row error capture
  - authority_snapshot: delegation to resolver (via injected packing_rows)
  - is_billed_product_code_valid: delegation
  - reconcile_billed: delegation
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from app.services.cpa_product_service import (
    authority_snapshot,
    is_billed_product_code_valid,
    reconcile_billed,
    upsert_product_master_from_packing,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_reservation_db(tmp_path: Path) -> Path:
    """Minimal reservation DB with product_master table."""
    db = tmp_path / "reservation.db"
    with sqlite3.connect(str(db)) as con:
        con.execute("""
            CREATE TABLE product_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_code TEXT NOT NULL UNIQUE,
                design_no TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                metal TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                source_invoice_no TEXT NOT NULL DEFAULT '',
                source_batch_id TEXT NOT NULL DEFAULT '',
                item_type TEXT NOT NULL DEFAULT '',
                hsn_code TEXT NOT NULL DEFAULT '',
                unit_price_ref REAL NOT NULL DEFAULT 0.0,
                currency_ref TEXT NOT NULL DEFAULT '',
                confidence TEXT NOT NULL DEFAULT 'high',
                source_document_id TEXT NOT NULL DEFAULT '',
                last_seen_batch_id TEXT NOT NULL DEFAULT '',
                supplier_id TEXT NOT NULL DEFAULT '',
                supplier_product_code TEXT NOT NULL DEFAULT '',
                normalized_design_attributes TEXT NOT NULL DEFAULT '',
                is_globally_unique INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
    return db


def _row(product_code: str, design_no: str = "D001", metal: str = "gold",
         invoice_no: str = "INV/001") -> Dict[str, Any]:
    return {
        "product_code": product_code,
        "design_no":    design_no,
        "metal":        metal,
        "item_type":    "ring",
        "invoice_no":   invoice_no,
    }


# ── upsert_product_master_from_packing ────────────────────────────────────────

def test_upsert_happy_path(tmp_path):
    db = _make_reservation_db(tmp_path)
    rows = [_row("EJL/26-27/001-1"), _row("EJL/26-27/001-2", design_no="D002")]

    with patch("app.services.cpa_product_service.audit_safe", return_value=1):
        result = upsert_product_master_from_packing(db, "BATCH-001", rows)

    assert result["upserted_count"] == 2
    assert result["skipped_count"] == 0
    assert result["error_count"] == 0
    assert "EJL/26-27/001-1" in result["upserted"]
    assert "EJL/26-27/001-2" in result["upserted"]


def test_upsert_skips_blank_product_code(tmp_path):
    db = _make_reservation_db(tmp_path)
    rows = [
        _row("EJL/26-27/001-1"),
        {"product_code": "", "design_no": "MYSTERY", "metal": "gold", "invoice_no": "INV/001"},
        {"product_code": None, "design_no": "ALSO_BLANK", "metal": "", "invoice_no": ""},
    ]

    with patch("app.services.cpa_product_service.audit_safe", return_value=1):
        result = upsert_product_master_from_packing(db, "BATCH-002", rows)

    assert result["upserted_count"] == 1
    assert result["skipped_count"] == 2
    assert "MYSTERY" in result["skipped"]
    assert "ALSO_BLANK" in result["skipped"]


def test_upsert_captures_per_row_error_without_aborting(tmp_path):
    db = _make_reservation_db(tmp_path)
    rows = [_row("EJL/26-27/001-1"), _row("EJL/26-27/001-2")]

    def _boom(db_path, product_code, **kwargs):
        if product_code == "EJL/26-27/001-2":
            raise RuntimeError("simulated DB error")
        # call the real function for the first row
        from app.services.reservation_db import upsert_product_master as _real
        return _real(db_path, product_code=product_code, design_no=kwargs.get("design_no", ""), **{k: v for k, v in kwargs.items() if k != "design_no"})

    with patch("app.services.cpa_product_service.upsert_product_master", side_effect=_boom), \
         patch("app.services.cpa_product_service.audit_safe", return_value=1):
        result = upsert_product_master_from_packing(db, "BATCH-003", rows)

    assert result["upserted_count"] == 1
    assert result["error_count"] == 1
    assert "EJL/26-27/001-2" in result["errors"]
    assert "simulated DB error" in result["errors"]["EJL/26-27/001-2"]


def test_upsert_idempotent(tmp_path):
    """Running twice with same data must not create duplicate rows."""
    db = _make_reservation_db(tmp_path)
    rows = [_row("EJL/26-27/001-1")]

    with patch("app.services.cpa_product_service.audit_safe", return_value=1):
        r1 = upsert_product_master_from_packing(db, "BATCH-001", rows)
        r2 = upsert_product_master_from_packing(db, "BATCH-001", rows)

    assert r1["upserted_count"] == 1
    assert r2["upserted_count"] == 1

    with sqlite3.connect(str(db)) as con:
        count = con.execute(
            "SELECT COUNT(*) FROM product_master WHERE product_code=?",
            ("EJL/26-27/001-1",),
        ).fetchone()[0]
    assert count == 1


def test_upsert_empty_rows_returns_zeroes(tmp_path):
    db = _make_reservation_db(tmp_path)
    with patch("app.services.cpa_product_service.audit_safe", return_value=1):
        result = upsert_product_master_from_packing(db, "BATCH-000", [])
    assert result == {
        "batch_id":       "BATCH-000",
        "upserted":       [],
        "upserted_count": 0,
        "skipped":        [],
        "skipped_count":  0,
        "errors":         {},
        "error_count":    0,
    }


# ── authority_snapshot ────────────────────────────────────────────────────────

def test_authority_snapshot_delegates_to_resolver():
    packing_rows = [
        {"design_no": "D001", "product_code": "EJL/26-27/001-1",
         "quantity": 2, "invoice_no": "INV/001", "invoice_line_position": 1},
    ]
    snap = authority_snapshot("BATCH-001", packing_rows=packing_rows)
    assert snap["batch_id"] == "BATCH-001"
    assert "EJL/26-27/001-1" in snap["product_codes"]
    assert snap["authority_available"] is True


def test_authority_snapshot_empty_batch():
    snap = authority_snapshot("BATCH-EMPTY", packing_rows=[])
    assert snap["product_codes"] == set()
    assert snap["rows_scanned"] == 0


# ── is_billed_product_code_valid ──────────────────────────────────────────────

def test_is_billed_valid_true():
    rows = [{"design_no": "D001", "product_code": "EJL/001-1",
             "quantity": 1, "invoice_no": "INV/001", "invoice_line_position": 1}]
    assert is_billed_product_code_valid("B1", "EJL/001-1", packing_rows=rows) is True


def test_is_billed_valid_false_unknown_code():
    rows = [{"design_no": "D001", "product_code": "EJL/001-1",
             "quantity": 1, "invoice_no": "INV/001", "invoice_line_position": 1}]
    assert is_billed_product_code_valid("B1", "GHOST/999", packing_rows=rows) is False


# ── reconcile_billed ──────────────────────────────────────────────────────────

def test_reconcile_billed_over_bill():
    rows = [{"design_no": "D001", "product_code": "EJL/001-1",
             "quantity": 1, "invoice_no": "INV/001", "invoice_line_position": 1}]
    draft = [{"design_no": "D001", "product_code": "EJL/001-1", "qty": 5}]
    result = reconcile_billed("B1", draft, packing_rows=rows)
    assert "duplicates" in result
    over = [d for d in result["duplicates"] if d["over_billed"]]
    assert len(over) == 1
    assert over[0]["product_code"] == "EJL/001-1"


def test_reconcile_billed_clean():
    rows = [{"design_no": "D001", "product_code": "EJL/001-1",
             "quantity": 3, "invoice_no": "INV/001", "invoice_line_position": 1}]
    draft = [{"design_no": "D001", "product_code": "EJL/001-1", "qty": 2}]
    result = reconcile_billed("B1", draft, packing_rows=rows)
    assert result["duplicates"] == []
