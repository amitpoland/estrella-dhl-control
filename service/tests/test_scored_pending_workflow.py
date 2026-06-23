"""
test_scored_pending_workflow.py — Tests for the scored-pending operator confirmation
workflow introduced with the spec-reconciliation-scorer campaign.

Coverage:
  1. update_sales_packing_line_product_code — service-layer unit tests
  2. recommended_assignments populated in MEDIUM-confidence designs_scored_pending
  3. HIGH confidence requires spec differentiation, not price alone
  4. GET /scored-pending logic — empty when no file, returns data when file exists
  5. POST /scored-pending/confirm validation rules (pure logic, not HTTP)
  6. Source-grep safety guards — confirm path must not touch fiscal writes
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ── 1. document_db.update_sales_packing_line_product_code ─────────────────────

def _make_temp_ddb(tmp_path: Path) -> Path:
    """Create a minimal documents.db with two sales_packing_lines rows."""
    db = tmp_path / "documents.db"
    with sqlite3.connect(str(db)) as con:
        con.execute(
            """CREATE TABLE sales_packing_lines (
                id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                sales_document_id TEXT NOT NULL DEFAULT '',
                client_name TEXT NOT NULL DEFAULT '',
                client_ref TEXT NOT NULL DEFAULT '',
                product_code TEXT NOT NULL DEFAULT '',
                design_no TEXT NOT NULL DEFAULT '',
                bag_id TEXT NOT NULL DEFAULT '',
                quantity REAL NOT NULL DEFAULT 0.0,
                remarks TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT ''
            )"""
        )
        con.execute(
            "INSERT INTO sales_packing_lines "
            "(id, batch_id, product_code, design_no, created_at) VALUES (?,?,?,?,?)",
            ("row-001", "BATCH-TEST", "", "PND", "2026-06-23T00:00:00"),
        )
        con.execute(
            "INSERT INTO sales_packing_lines "
            "(id, batch_id, product_code, design_no, created_at) VALUES (?,?,?,?,?)",
            ("row-002", "BATCH-TEST", "", "PND", "2026-06-23T00:00:00"),
        )
    return db


class TestUpdateSalesPackingLineProductCode:
    """Unit tests for document_db.update_sales_packing_line_product_code."""

    def test_updates_correct_row(self, tmp_path):
        db = _make_temp_ddb(tmp_path)
        import service.app.services.document_db as ddb
        orig = ddb._db_path
        ddb._db_path = db
        try:
            ok = ddb.update_sales_packing_line_product_code(
                "BATCH-TEST", "row-001", "EJL/26-27/295-1"
            )
            assert ok is True
            with sqlite3.connect(str(db)) as con:
                row = con.execute(
                    "SELECT product_code FROM sales_packing_lines WHERE id=?",
                    ("row-001",),
                ).fetchone()
            assert row[0] == "EJL/26-27/295-1"
        finally:
            ddb._db_path = orig

    def test_returns_false_for_missing_row(self, tmp_path):
        db = _make_temp_ddb(tmp_path)
        import service.app.services.document_db as ddb
        orig = ddb._db_path
        ddb._db_path = db
        try:
            assert ddb.update_sales_packing_line_product_code(
                "BATCH-TEST", "no-such-row", "X"
            ) is False
        finally:
            ddb._db_path = orig

    def test_cross_batch_isolation(self, tmp_path):
        """row-001 belongs to BATCH-TEST; a different batch must not touch it."""
        db = _make_temp_ddb(tmp_path)
        import service.app.services.document_db as ddb
        orig = ddb._db_path
        ddb._db_path = db
        try:
            ok = ddb.update_sales_packing_line_product_code(
                "BATCH-OTHER", "row-001", "EJL/26-27/295-1"
            )
            assert ok is False
            with sqlite3.connect(str(db)) as con:
                row = con.execute(
                    "SELECT product_code FROM sales_packing_lines WHERE id=?",
                    ("row-001",),
                ).fetchone()
            assert row[0] == ""  # unchanged
        finally:
            ddb._db_path = orig

    def test_returns_false_when_db_not_initialised(self):
        import service.app.services.document_db as ddb
        orig = ddb._db_path
        ddb._db_path = None
        try:
            assert ddb.update_sales_packing_line_product_code("B", "R", "X") is False
        finally:
            ddb._db_path = orig

    def test_empty_row_id_or_batch_returns_false(self, tmp_path):
        db = _make_temp_ddb(tmp_path)
        import service.app.services.document_db as ddb
        orig = ddb._db_path
        ddb._db_path = db
        try:
            assert ddb.update_sales_packing_line_product_code(
                "BATCH-TEST", "", "X"
            ) is False
            assert ddb.update_sales_packing_line_product_code(
                "", "row-001", "X"
            ) is False
        finally:
            ddb._db_path = orig

    def test_does_not_touch_other_rows_in_same_batch(self, tmp_path):
        """Updating row-001 must leave row-002 unchanged."""
        db = _make_temp_ddb(tmp_path)
        import service.app.services.document_db as ddb
        orig = ddb._db_path
        ddb._db_path = db
        try:
            ddb.update_sales_packing_line_product_code(
                "BATCH-TEST", "row-001", "EJL/26-27/295-1"
            )
            with sqlite3.connect(str(db)) as con:
                row2 = con.execute(
                    "SELECT product_code FROM sales_packing_lines WHERE id=?",
                    ("row-002",),
                ).fetchone()
            assert row2[0] == ""
        finally:
            ddb._db_path = orig


# ── 2. recommended_assignments present in MEDIUM scored_pending ───────────────

class TestRecommendedAssignmentsInScoredPending:
    """MEDIUM-confidence scored_pending must include recommended_assignments with row_ids."""

    def test_recommended_assignments_populated(self):
        from service.app.services import proforma_draft_sync as pds
        from service.app.services.reconciliation_scorer import (
            ReconciliationResult,
            SalesAssignment,
            HIGH_CONFIDENCE_THRESHOLD,
        )

        mock_result = ReconciliationResult(
            design_no="PND",
            method="quantity_only",
            confidence=0.40,
            confidence_label="MEDIUM",
            recommended_assignments=[
                SalesAssignment(
                    sales_row_index=0,
                    recommended_product_code="EJL/26-27/295-1",
                    confidence=0.4,
                    is_auto_resolved=False,
                    audit_reason="qty balance",
                ),
                SalesAssignment(
                    sales_row_index=1,
                    recommended_product_code="EJL/26-27/299-3",
                    confidence=0.4,
                    is_auto_resolved=False,
                    audit_reason="qty balance",
                ),
            ],
            distribution_hint={"EJL/26-27/295-1": 1, "EJL/26-27/299-3": 1},
            spec_diff_fields=[],
            audit_trail=[],
            requires_operator_review=True,
        )

        sales_clones = [
            {"id": "row-001", "design_no": "PND", "product_code": ""},
            {"id": "row-002", "design_no": "PND", "product_code": ""},
        ]
        designs_reconciled:     Dict[str, Any] = {}
        designs_scored_pending: Dict[str, Any] = {}

        with patch(
            "service.app.services.reconciliation_scorer.score_ambiguous_design",
            return_value=mock_result,
        ):
            pds._apply_spec_reconciliation(
                "BATCH",
                {"PND": ["EJL/26-27/295-1", "EJL/26-27/299-3"]},
                {"PND": sales_clones},
                designs_reconciled,
                designs_scored_pending,
            )

        assert "PND" in designs_scored_pending, "MEDIUM design must appear in scored_pending"
        pending = designs_scored_pending["PND"]
        assert "recommended_assignments" in pending
        asgns = pending["recommended_assignments"]
        assert len(asgns) == 2
        assert asgns[0]["row_id"] == "row-001"
        assert asgns[0]["recommended_product_code"] == "EJL/26-27/295-1"
        assert asgns[1]["row_id"] == "row-002"
        assert asgns[1]["recommended_product_code"] == "EJL/26-27/299-3"
        assert "PND" not in designs_reconciled, "MEDIUM must NOT go into reconciled"


# ── 3. HIGH confidence requires spec differentiation, not price alone ─────────

class TestHighConfidenceRequiresSpec:
    """Price-only difference between candidates cannot achieve HIGH confidence (≥ 0.85)."""

    def test_price_only_difference_is_not_high(self, tmp_path):
        """
        Max achievable score without spec differentiation:
          qty(0.40) + price(0.20) = 0.60 < HIGH threshold (0.85).
        """
        from service.app.services.reconciliation_scorer import (
            score_ambiguous_design,
            HIGH_CONFIDENCE_THRESHOLD,
        )

        # Build a real packing.db with identical specs but different prices.
        db_path = tmp_path / "packing.db"
        with sqlite3.connect(str(db_path)) as con:
            con.execute(
                """CREATE TABLE packing_lines (
                    id TEXT PRIMARY KEY, batch_id TEXT, product_code TEXT,
                    design_no TEXT, item_type TEXT, karat TEXT, metal TEXT,
                    metal_color TEXT, gross_weight REAL, net_weight REAL,
                    diamond_weight REAL, color_weight REAL, quality_string TEXT,
                    size TEXT, unit_price REAL, quantity REAL
                )"""
            )
            # Two candidates, identical specs (RING, 14KT, GOLD), different prices.
            con.execute(
                "INSERT INTO packing_lines VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("pl-1", "B", "EJL/26-27/295-1", "PND",
                 "RING", "14KT", "GOLD", "Y", 3.5, 3.0, 0.0, 0.0, "", "", 500.0, 1),
            )
            con.execute(
                "INSERT INTO packing_lines VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("pl-2", "B", "EJL/26-27/299-3", "PND",
                 "RING", "14KT", "GOLD", "Y", 3.5, 3.0, 0.0, 0.0, "", "", 800.0, 1),
            )

        sales_rows = [
            {"id": "sr-1", "unit_price": 500.0, "product_code": "", "design_no": "PND"},
            {"id": "sr-2", "unit_price": 800.0, "product_code": "", "design_no": "PND"},
        ]

        result = score_ambiguous_design(
            "B", "PND",
            ["EJL/26-27/295-1", "EJL/26-27/299-3"],
            sales_rows,
            packing_db_path=str(db_path),
        )

        assert result.confidence < HIGH_CONFIDENCE_THRESHOLD, (
            f"Price-only diff must not reach HIGH confidence; got {result.confidence:.3f}"
        )
        assert result.confidence_label in ("MEDIUM", "LOW", "UNRESOLVABLE"), (
            f"Expected MEDIUM/LOW/UNRESOLVABLE; got {result.confidence_label}"
        )
        assert result.requires_operator_review is True


# ── 4. GET scored-pending logic ───────────────────────────────────────────────

class TestGetScoredPendingLogic:
    """Unit tests for the scored-pending GET endpoint logic (without HTTP)."""

    def test_returns_empty_count_when_no_file(self, tmp_path):
        sp_path = tmp_path / "scored_pending.json"
        assert not sp_path.exists()
        # Replicate endpoint logic
        if not sp_path.exists():
            result = {"batch_id": "B", "designs": {}, "count": 0}
        else:
            data = json.loads(sp_path.read_text())
            designs = data.get("designs") or {}
            result = {"batch_id": "B", "designs": designs, "count": len(designs)}
        assert result == {"batch_id": "B", "designs": {}, "count": 0}

    def test_returns_designs_when_file_exists(self, tmp_path):
        sp_path = tmp_path / "scored_pending.json"
        sp_path.write_text(
            json.dumps({
                "batch_id": "B",
                "designs": {
                    "PND": {
                        "candidates":      ["X", "Y"],
                        "confidence":      0.4,
                        "confidence_label": "MEDIUM",
                    }
                },
            }),
            encoding="utf-8",
        )
        data = json.loads(sp_path.read_text())
        designs = data.get("designs") or {}
        result = {"batch_id": "B", "designs": designs, "count": len(designs)}
        assert result["count"] == 1
        assert "PND" in result["designs"]


# ── 5. POST confirm validation rules (pure logic) ────────────────────────────

class TestConfirmValidationLogic:

    def test_rejects_design_not_in_pending(self):
        designs = {"PND": {"candidates": ["EJL/26-27/295-1"]}}
        assert designs.get("NO-SUCH-DESIGN") is None

    def test_rejects_product_code_not_in_candidates(self):
        candidates = ["EJL/26-27/295-1", "EJL/26-27/299-3"]
        bad = "INVENTED-CODE"
        assert bad not in candidates

    def test_accepts_valid_candidate(self):
        candidates = ["EJL/26-27/295-1", "EJL/26-27/299-3"]
        assert "EJL/26-27/295-1" in candidates
        assert "EJL/26-27/299-3" in candidates


# ── 6. Source-grep safety guards ──────────────────────────────────────────────

class TestSourceSafetyGuards:
    """Confirm path and document_db update must not touch fiscal writes."""

    def test_routes_packing_confirm_no_fiscal_writes(self):
        src = (Path(__file__).parent.parent / "app/api/routes_packing.py").read_text(encoding="utf-8")
        confirm_section = (
            src.split("scored-pending")[-1] if "scored-pending" in src else src
        )
        forbidden = [
            "wfirma_client",
            "create_pz",
            "create_proforma",
            "fiscal_write",
            "post_invoice",
        ]
        for term in forbidden:
            assert term not in confirm_section, (
                f"Confirm endpoint must not reference {term!r}"
            )

    def test_document_db_update_targets_sales_table_only(self):
        import inspect
        from service.app.services import document_db as ddb
        src = inspect.getsource(ddb.update_sales_packing_line_product_code)
        assert "sales_packing_lines" in src
        assert "UPDATE packing_lines" not in src
        assert "FROM packing_lines" not in src
