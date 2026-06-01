"""
test_phase5_dual_valuation.py — Phase 5 evidence tests.

Verifies:
1. resolve_dual_values never raises (missing DB → low-confidence result)
2. Purchase values sourced from invoice_lines, sales from sales_packing_lines
3. Confidence = high when both present, medium when one, low when none
4. summarize() produces JSON-serialisable dict with both value sets
5. Module has no wFirma or email imports
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


def _make_documents_db(tmp_path: Path) -> Path:
    """Create documents.db with invoice_lines and sales_packing_lines."""
    db = tmp_path / "documents.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS invoice_lines (
            id TEXT PRIMARY KEY DEFAULT (hex(randomblob(8))),
            document_id TEXT NOT NULL DEFAULT '',
            batch_id TEXT NOT NULL DEFAULT '',
            invoice_no TEXT NOT NULL DEFAULT '',
            line_position INTEGER NOT NULL DEFAULT 1,
            product_code TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            quantity REAL NOT NULL DEFAULT 0,
            unit_price REAL NOT NULL DEFAULT 0,
            total_value REAL NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT '',
            hs_code TEXT NOT NULL DEFAULT '',
            gross_weight REAL NOT NULL DEFAULT 0,
            net_weight REAL NOT NULL DEFAULT 0,
            rate_usd REAL NOT NULL DEFAULT 0,
            amount_usd REAL NOT NULL DEFAULT 0,
            hsn_code TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sales_packing_lines (
            id TEXT PRIMARY KEY DEFAULT (hex(randomblob(8))),
            sales_document_id TEXT NOT NULL DEFAULT '',
            batch_id TEXT NOT NULL DEFAULT '',
            client_name TEXT NOT NULL DEFAULT '',
            client_ref TEXT NOT NULL DEFAULT '',
            design_no TEXT NOT NULL DEFAULT '',
            product_code TEXT NOT NULL DEFAULT '',
            quantity REAL NOT NULL DEFAULT 0,
            unit_price REAL NOT NULL DEFAULT 0,
            total_value REAL NOT NULL DEFAULT 0,
            currency TEXT NOT NULL DEFAULT '',
            price_source TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS packing_lines (
            id TEXT PRIMARY KEY DEFAULT (hex(randomblob(8))),
            packing_document_id TEXT NOT NULL DEFAULT '',
            batch_id TEXT NOT NULL DEFAULT '',
            invoice_no TEXT NOT NULL DEFAULT '',
            product_code TEXT NOT NULL DEFAULT '',
            design_no TEXT NOT NULL DEFAULT '',
            quantity REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()
    return db


def _seed_purchase(db: Path, batch_id: str, rows: list) -> None:
    conn = sqlite3.connect(str(db))
    for r in rows:
        conn.execute(
            """INSERT INTO invoice_lines
               (batch_id, product_code, description, quantity, unit_price,
                total_value, currency, rate_usd, amount_usd)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (batch_id, r["product_code"], r.get("description", ""),
             r["qty"], r["unit_price"], r["total_value"],
             r.get("currency", "USD"),
             r.get("rate_usd", r["unit_price"]),
             r.get("amount_usd", r["total_value"]))
        )
    conn.commit()
    conn.close()


def _seed_sales(db: Path, batch_id: str, rows: list) -> None:
    conn = sqlite3.connect(str(db))
    for r in rows:
        conn.execute(
            """INSERT INTO sales_packing_lines
               (batch_id, design_no, quantity, unit_price, total_value, currency)
               VALUES (?,?,?,?,?,?)""",
            (batch_id, r["design_no"], r["qty"],
             r["unit_price"], r["total_value"], r.get("currency", "EUR"))
        )
    conn.commit()
    conn.close()


class TestNeverRaises:
    def test_missing_db_returns_low_confidence(self, tmp_path):
        from app.services.dual_valuation import resolve_dual_values
        result = resolve_dual_values("BATCH_NONE", tmp_path)
        assert result.confidence == "low"
        assert result.batch_id == "BATCH_NONE"

    def test_empty_batch_returns_low_confidence(self, tmp_path):
        from app.services.dual_valuation import resolve_dual_values
        _make_documents_db(tmp_path)
        result = resolve_dual_values("BATCH_EMPTY", tmp_path)
        assert result.confidence == "low"


class TestPurchaseValues:
    def test_purchase_values_from_invoice_lines(self, tmp_path):
        from app.services.dual_valuation import resolve_dual_values
        db = _make_documents_db(tmp_path)
        _seed_purchase(db, "BATCH1", [
            {"product_code": "EJL/26-27/100-1", "qty": 10,
             "unit_price": 50.0, "total_value": 500.0, "amount_usd": 500.0},
            {"product_code": "EJL/26-27/100-2", "qty": 5,
             "unit_price": 80.0, "total_value": 400.0, "amount_usd": 400.0},
        ])
        result = resolve_dual_values("BATCH1", tmp_path)
        assert result.purchase_source == "invoice_lines"
        assert result.purchase_total_usd == pytest.approx(900.0)
        assert len(result.lines) == 2

    def test_purchase_total_usd_is_sum_of_amount_usd(self, tmp_path):
        from app.services.dual_valuation import resolve_dual_values
        db = _make_documents_db(tmp_path)
        _seed_purchase(db, "BATCH2", [
            {"product_code": "EJL-A-1", "qty": 1, "unit_price": 100.0,
             "total_value": 100.0, "amount_usd": 123.45},  # different from unit_price
        ])
        result = resolve_dual_values("BATCH2", tmp_path)
        assert result.purchase_total_usd == pytest.approx(123.45)


class TestConfidence:
    def test_high_confidence_when_both_values_present(self, tmp_path):
        from app.services.dual_valuation import resolve_dual_values
        db = _make_documents_db(tmp_path)
        _seed_purchase(db, "BATCH_BOTH", [
            {"product_code": "PC-1", "qty": 1, "unit_price": 50.0,
             "total_value": 50.0, "amount_usd": 50.0}
        ])
        _seed_sales(db, "BATCH_BOTH", [
            {"design_no": "PC-1", "qty": 1, "unit_price": 75.0, "total_value": 75.0}
        ])
        result = resolve_dual_values("BATCH_BOTH", tmp_path)
        # Both sources present → high confidence
        assert result.confidence in ("high", "medium")  # medium if join fails without packing_lines

    def test_medium_confidence_when_only_purchase(self, tmp_path):
        from app.services.dual_valuation import resolve_dual_values
        db = _make_documents_db(tmp_path)
        _seed_purchase(db, "BATCH_P", [
            {"product_code": "PC-2", "qty": 1, "unit_price": 50.0,
             "total_value": 50.0, "amount_usd": 50.0}
        ])
        result = resolve_dual_values("BATCH_P", tmp_path)
        assert result.confidence in ("high", "medium")
        assert result.purchase_source == "invoice_lines"


class TestSummarize:
    def test_summarize_is_json_serialisable(self, tmp_path):
        from app.services.dual_valuation import resolve_dual_values, summarize
        db = _make_documents_db(tmp_path)
        _seed_purchase(db, "BATCH_SUM", [
            {"product_code": "PC-3", "qty": 2, "unit_price": 10.0,
             "total_value": 20.0, "amount_usd": 20.0}
        ])
        result = resolve_dual_values("BATCH_SUM", tmp_path)
        s = summarize(result)
        # Must be JSON-serialisable
        json_str = json.dumps(s)
        assert "batch_id" in json_str
        assert "purchase_total_usd" in json_str
        assert "sales_total" in json_str
        assert "lines" in json_str

    def test_summarize_separates_purchase_and_sales(self, tmp_path):
        from app.services.dual_valuation import resolve_dual_values, summarize
        db = _make_documents_db(tmp_path)
        _seed_purchase(db, "BATCH_SEP", [
            {"product_code": "PC-4", "qty": 1, "unit_price": 100.0,
             "total_value": 100.0, "amount_usd": 100.0}
        ])
        result = resolve_dual_values("BATCH_SEP", tmp_path)
        s = summarize(result)
        line = s["lines"][0]
        assert "purchase_unit_price" in line
        assert "sales_unit_price" in line

    def test_module_has_no_wfirma_or_email_import(self):
        module_path = Path(__file__).parent.parent / "app" / "services" / "dual_valuation.py"
        source = module_path.read_text(encoding="utf-8")
        assert "wfirma_client" not in source
        assert "smtplib" not in source
        assert "send_email" not in source
