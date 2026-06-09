"""
test_sales_linkage_physical_only.py

Regression tests for the get_sales_packing_lines(physical_only=True) fix and
the sales_linkage.get_sales_linkage scan-count deduplication.

Bug (2026-06-09):
  AWB 9938632830 has 146 physical goods lines.  The sales-price import
  (import-sales-prices) inserted 146 additional rows with
  price_source='excel_symbol', bringing the total in sales_packing_lines
  to 292.  sales_linkage.get_sales_linkage called
  ddb.get_sales_packing_lines() without filtering and received 292 rows.
  batch_readiness then reported 292/292 not-scanned (instead of 146/146),
  blocking readiness with a doubled missing count.

Fix:
  1. document_db.get_sales_packing_lines gains a physical_only kwarg
     (default=False for backward compatibility with proforma callers).
  2. sales_linkage.get_sales_linkage passes physical_only=True so it
     receives only the packing_xlsx_value rows (one per physical item).

References:
  - document_db.py get_sales_packing_lines (physical_only parameter)
  - sales_linkage.py get_sales_linkage (physical_only=True call site)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

_svc = Path(__file__).parent.parent
if str(_svc) not in sys.path:
    sys.path.insert(0, str(_svc))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_line(design_no: str, product_code: str, price_source: str,
               client_ref: str = "", unit_price: float = 100.0,
               currency: str = "USD") -> Dict[str, Any]:
    return {
        "id":                 None,
        "batch_id":           "BATCH_TEST",
        "sales_document_id":  "SDOC_001",
        "client_name":        "UAB TOMAS GOLD",
        "client_ref":         client_ref,
        "product_code":       product_code,
        "design_no":          design_no,
        "bag_id":             None,
        "quantity":           1.0,
        "remarks":            None,
        "created_at":         "2026-06-09T12:00:00",
        "unit_price":         unit_price,
        "currency":           currency,
        "total_value":        unit_price,
        "price_source":       price_source,
    }


def _seed_dual_source_batch(db_path: Path, batch_id: str, n_items: int = 5):
    """Insert n_items * 2 rows: one packing_xlsx_value + one excel_symbol each."""
    from app.services import document_db as ddb
    ddb.init_document_db(db_path)
    import sqlite3
    con = sqlite3.connect(db_path)
    try:
        for i in range(n_items):
            dn = f"JR0000-0.{i:02d}"
            pc_cost = f"EJL/BATCH-{i}"
            # packing_xlsx_value row: has client_ref, USD cost price
            con.execute(
                "INSERT INTO sales_packing_lines "
                "(batch_id, sales_document_id, client_name, client_ref, "
                " product_code, design_no, quantity, unit_price, currency, "
                " total_value, price_source, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (batch_id, "SDOC_001", "UAB TOMAS GOLD", f"EJL/26-27/{i:03d}",
                 pc_cost, dn, 1.0, 100.0, "USD", 100.0,
                 "packing_xlsx_value", "2026-06-09T10:00:00"),
            )
            # excel_symbol row: same design_no, empty client_ref, EUR sales price
            con.execute(
                "INSERT INTO sales_packing_lines "
                "(batch_id, sales_document_id, client_name, client_ref, "
                " product_code, design_no, quantity, unit_price, currency, "
                " total_value, price_source, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (batch_id, "SDOC_001", "UAB TOMAS GOLD", "",
                 pc_cost, dn, 1.0, 120.0, "EUR", 120.0,
                 "excel_symbol", "2026-06-09T11:00:00"),
            )
        con.commit()
    finally:
        con.close()


# ── Tests: document_db.get_sales_packing_lines ────────────────────────────────

class TestGetSalesPackingLinesPhysicalOnly:

    BATCH = "TEST_PHYSICAL_ONLY_01"

    @pytest.fixture(autouse=True)
    def _db(self, tmp_path):
        from app.services import document_db as ddb
        ddb.init_document_db(tmp_path / "documents.db")
        _seed_dual_source_batch(tmp_path / "documents.db", self.BATCH, n_items=5)
        yield ddb

    def test_default_returns_all_rows(self, _db):
        """Default (physical_only=False) returns both price sources: 10 rows for 5 items."""
        rows = _db.get_sales_packing_lines(self.BATCH)
        assert len(rows) == 10, f"Expected 10 (5 × 2 sources), got {len(rows)}"

    def test_physical_only_true_returns_packing_xlsx_value_only(self, _db):
        """physical_only=True returns only packing_xlsx_value rows: 5 rows."""
        rows = _db.get_sales_packing_lines(self.BATCH, physical_only=True)
        assert len(rows) == 5, f"Expected 5 physical rows, got {len(rows)}"
        assert all(r["price_source"] == "packing_xlsx_value" for r in rows)

    def test_physical_only_false_includes_excel_symbol(self, _db):
        """physical_only=False includes excel_symbol rows."""
        rows = _db.get_sales_packing_lines(self.BATCH, physical_only=False)
        sources = {r["price_source"] for r in rows}
        assert "packing_xlsx_value" in sources
        assert "excel_symbol" in sources

    def test_empty_batch_returns_empty_list(self, _db):
        """No rows for an unknown batch_id."""
        rows = _db.get_sales_packing_lines("NONEXISTENT_BATCH", physical_only=True)
        assert rows == []

    def test_physical_only_true_currency_is_usd(self, _db):
        """packing_xlsx_value rows carry USD (cost currency), not EUR."""
        rows = _db.get_sales_packing_lines(self.BATCH, physical_only=True)
        currencies = {r["currency"] for r in rows}
        assert currencies == {"USD"}

    def test_default_includes_eur_rows(self, _db):
        """Default (all rows) includes EUR excel_symbol rows."""
        rows = _db.get_sales_packing_lines(self.BATCH)
        currencies = {r["currency"] for r in rows}
        assert "EUR" in currencies


# ── Tests: sales_linkage calls physical_only=True ─────────────────────────────

class TestSalesLinkageCallsPhysicalOnly:

    def test_get_sales_linkage_passes_physical_only_true(self, tmp_path):
        """sales_linkage.get_sales_linkage must call ddb.get_sales_packing_lines
        with physical_only=True to avoid double-counting the scan set."""
        from app.services import sales_linkage as sl
        from app.services import document_db as ddb
        from app.services import packing_db as pdb
        from app.services import warehouse_db as wdb

        # Initialize all three DBs so _ready() returns True
        ddb.init_document_db(tmp_path / "documents.db")
        pdb.init_packing_db(tmp_path / "packing.db")
        wdb.init_warehouse_db(tmp_path / "warehouse.db")

        captured_kwargs: dict = {}

        def _mock_get_sales_packing_lines(batch_id, **kwargs):
            captured_kwargs.update(kwargs)
            return []  # empty → get_sales_linkage returns early after this

        with patch.object(ddb, "get_sales_packing_lines",
                          side_effect=_mock_get_sales_packing_lines):
            sl.get_sales_linkage("ANY_BATCH")

        assert captured_kwargs.get("physical_only") is True, (
            f"sales_linkage must call get_sales_packing_lines(physical_only=True); "
            f"got kwargs={captured_kwargs}"
        )

    def test_scan_count_uses_physical_items_not_doubled(self, tmp_path):
        """When 10 physical items × 2 price sources exist (20 rows total),
        the scan set must be 10 (physical items), NOT 20.

        get_sales_linkage returns {"summary": {"total": N, ...}}.
        With physical_only=True, N must equal the number of physical items.
        """
        from app.services import sales_linkage as sl
        from app.services import document_db as ddb
        from app.services import packing_db as pdb
        from app.services import warehouse_db as wdb

        batch_id = "SCAN_COUNT_TEST"

        # Initialize all three DBs (required by sales_linkage._ready())
        doc_db_path = tmp_path / "documents.db"
        pck_db_path = tmp_path / "packing.db"
        wh_db_path  = tmp_path / "warehouse.db"
        ddb.init_document_db(doc_db_path)
        pdb.init_packing_db(pck_db_path)
        wdb.init_warehouse_db(wh_db_path)

        # Insert 10 items × 2 price sources = 20 rows
        _seed_dual_source_batch(doc_db_path, batch_id, n_items=10)

        result = sl.get_sales_linkage(batch_id)

        # With physical_only=True, items list has 10 entries (not 20)
        assert result.get("batch_id") == batch_id
        total = result["summary"]["total"]
        assert total == 10, (
            f"Expected summary.total=10 (physical items, not doubled by "
            f"price sources), got {total}"
        )

    def test_source_has_physical_only_kwarg(self):
        """Source check: get_sales_packing_lines call in sales_linkage.py
        must include physical_only=True to prevent scan doubling."""
        import app.services.sales_linkage as sl_module
        src = Path(sl_module.__file__.replace(".pyc", ".py")).read_text(
            encoding="utf-8")
        assert "physical_only=True" in src, (
            "sales_linkage.py must call get_sales_packing_lines(physical_only=True) "
            "to prevent doubling the scan count"
        )
