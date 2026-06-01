"""
test_remediation_b6_dual_valuation.py — Integration tests for B6.

Verifies the dual-valuation endpoint is registered and returns both values.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


class TestDualValuationEndpointRegistered:
    def test_endpoint_in_routes_source(self):
        src = (Path(__file__).parent.parent / "app" / "api" / "routes_proforma.py"
               ).read_text(encoding="utf-8")
        assert "dual-valuation" in src
        assert "resolve_dual_values" in src
        assert "get_dual_valuation" in src

    def test_ui_panel_in_html(self):
        src = (Path(__file__).parent.parent / "app" / "static" / "proforma-detail-v2.html"
               ).read_text(encoding="utf-8")
        assert "DualValuationPanel" in src
        assert "dual-valuation-panel" in src
        assert "purchase basis" in src.lower() or "Purchase basis" in src


class TestDualValuationResolver:
    def test_resolver_returns_both_bases(self, tmp_path):
        from app.services.dual_valuation import resolve_dual_values, summarize
        # Seed documents.db
        db = tmp_path / "documents.db"
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE invoice_lines (
                id TEXT PRIMARY KEY DEFAULT (hex(randomblob(4))),
                document_id TEXT DEFAULT '', batch_id TEXT NOT NULL DEFAULT '',
                invoice_no TEXT DEFAULT '', line_position INTEGER DEFAULT 1,
                product_code TEXT DEFAULT '', description TEXT DEFAULT '',
                quantity REAL DEFAULT 0, unit_price REAL DEFAULT 0,
                total_value REAL DEFAULT 0, currency TEXT DEFAULT '',
                hs_code TEXT DEFAULT '', gross_weight REAL DEFAULT 0,
                net_weight REAL DEFAULT 0, rate_usd REAL DEFAULT 0,
                amount_usd REAL DEFAULT 0, hsn_code TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE sales_packing_lines (
                id TEXT PRIMARY KEY DEFAULT (hex(randomblob(4))),
                sales_document_id TEXT DEFAULT '', batch_id TEXT DEFAULT '',
                client_name TEXT DEFAULT '', client_ref TEXT DEFAULT '',
                design_no TEXT DEFAULT '', product_code TEXT DEFAULT '',
                quantity REAL DEFAULT 0, unit_price REAL DEFAULT 0,
                total_value REAL DEFAULT 0, currency TEXT DEFAULT '',
                price_source TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE packing_lines (
                id TEXT PRIMARY KEY DEFAULT (hex(randomblob(4))),
                packing_document_id TEXT DEFAULT '', batch_id TEXT DEFAULT '',
                invoice_no TEXT DEFAULT '', product_code TEXT DEFAULT '',
                design_no TEXT DEFAULT '', quantity REAL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute(
            "INSERT INTO invoice_lines (batch_id, product_code, quantity, unit_price, total_value, currency, amount_usd) VALUES (?,?,?,?,?,?,?)",
            ("B1", "PC-1", 5.0, 100.0, 500.0, "USD", 500.0)
        )
        conn.commit()
        conn.close()

        from app.core.config import settings
        import sys
        import unittest.mock as mock
        with mock.patch.object(settings, "storage_root", tmp_path):
            result = resolve_dual_values("B1", tmp_path)
            s = summarize(result)

        assert s["batch_id"] == "B1"
        assert s["purchase_total_usd"] > 0, "purchase basis should be non-zero"
        assert "purchase_source" in s
        assert "sales_total" in s
        # JSON-serialisable
        json.dumps(s)
