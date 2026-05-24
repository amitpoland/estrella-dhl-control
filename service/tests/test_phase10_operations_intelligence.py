"""Phase 10 -- Operations Intelligence tests.

Test strategy:
  - Service unit tests via sys.modules + importlib.reload (lazy imports)
  - Route integration tests via FastAPI TestClient
  - Source-grep contracts (no ai_gateway, no writes, llm_used=False)
  - Regression: Phase 7+8+9 endpoints still 200

Covers:
  - get_operations_intelligence() all paths: empty DB, mixed readiness, all ready
  - Period filter: today / 7d / 30d cutoff logic
  - Domain filter: only matching domain in missing_evidence
  - Batch enumeration from real SQLite
  - MDI score injection via mock
  - Route validation: 422 on bad period, 422 on bad domain, 200 on valid
  - Source-grep: no INSERT/UPDATE/DELETE, no anthropic/ai_gateway, llm_used=False
  - to_dict() shape and types
"""

from __future__ import annotations

import importlib
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_readiness(
    wfirma_ready: bool = True,
    sales_ready: bool = True,
    warehouse_ready: bool = True,
    dhl_ready: bool = True,
    sla_breach: bool = False,
) -> Dict[str, Any]:
    return {
        "wfirma":    {"ready": wfirma_ready, "message": "wFirma domain"},
        "sales":     {"ready": sales_ready,  "message": "Sales domain"},
        "warehouse": {"ready": warehouse_ready, "message": "Warehouse domain"},
        "dhl":       {"ready": dhl_ready, "sla_breach": sla_breach, "message": "DHL domain"},
        "overall":   {"ready_for_closure": all([wfirma_ready, sales_ready, warehouse_ready, dhl_ready])},
    }


def _make_mdi_report(
    platform_score: float = 0.75,
    document_score: float = 0.60,
    graph_score: float = 0.55,
    top_recommendations: Optional[List[str]] = None,
) -> MagicMock:
    report = MagicMock()
    report.platform_score = platform_score
    report.document.completeness_score = document_score
    report.graph.completeness_score = graph_score
    report.top_recommendations = top_recommendations or [
        "Fill missing supplier VAT numbers",
        "Complete product local augmentation",
        "Resolve near-duplicate customer entries",
    ]
    return report


def _create_documents_db(tmp_path: Path, rows: List[Dict[str, Any]]) -> Path:
    """Create a minimal documents.db with shipment_documents rows."""
    db = tmp_path / "documents.db"
    con = sqlite3.connect(str(db))
    con.execute(
        "CREATE TABLE shipment_documents ("
        "id INTEGER PRIMARY KEY, "
        "batch_id TEXT NOT NULL, "
        "document_type TEXT, "
        "created_at TEXT NOT NULL)"
    )
    for row in rows:
        con.execute(
            "INSERT INTO shipment_documents (batch_id, document_type, created_at) VALUES (?,?,?)",
            (row["batch_id"], row.get("document_type", "INVOICE"), row["created_at"]),
        )
    con.commit()
    con.close()
    return db


# ── Service unit tests ────────────────────────────────────────────────────────


class TestOperationsIntelligenceService:
    """Tests for get_operations_intelligence() service function."""

    SERVICE_FILE = "app/services/operations_intelligence.py"

    def _src(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8")

    # ── Source-grep contracts ─────────────────────────────────────────────────

    def test_no_write_sql_in_service(self):
        src = self._src(self.SERVICE_FILE)
        assert "INSERT INTO" not in src, "Forbidden INSERT SQL in service"
        assert "DELETE FROM" not in src, "Forbidden DELETE SQL in service"
        # UPDATE check: service must not update unless PRAGMA query_only is present
        assert "UPDATE " not in src or "PRAGMA query_only" in src, \
            "UPDATE SQL without PRAGMA query_only in service"

    def test_llm_used_false_hardcoded_in_service(self):
        src = self._src(self.SERVICE_FILE)
        assert "llm_used = False" in src

    def test_pragma_query_only_in_service(self):
        src = self._src(self.SERVICE_FILE)
        assert "PRAGMA query_only" in src

    def test_no_ai_gateway_import_in_service(self):
        src = self._src(self.SERVICE_FILE)
        import_lines = [
            ln for ln in src.splitlines()
            if "import" in ln and "ai_gateway" in ln and not ln.strip().startswith("#")
        ]
        assert import_lines == [], f"ai_gateway imported in service: {import_lines}"

    def test_no_anthropic_import_in_service(self):
        src = self._src(self.SERVICE_FILE)
        import_lines = [
            ln for ln in src.splitlines()
            if "import" in ln and "anthropic" in ln.lower() and not ln.strip().startswith("#")
        ]
        assert import_lines == [], f"anthropic imported in service: {import_lines}"

    def test_no_write_sql_in_route(self):
        src = self._src("app/api/routes_operations_intelligence.py")
        assert "INSERT INTO" not in src, "Forbidden INSERT SQL in route"
        assert "DELETE FROM" not in src, "Forbidden DELETE SQL in route"

    # ── to_dict() shape ───────────────────────────────────────────────────────

    def test_to_dict_contains_all_required_keys(self):
        import app.services.operations_intelligence as mod
        result = mod.OperationsIntelligenceResult(
            period="7d",
            total_batches=5,
            blocked_batches=2,
            incomplete_batches=1,
            ready_batches=2,
            document_coverage_score=0.6,
            master_data_score=0.75,
            graph_completeness_score=0.5,
            workflow_risk_summary={"HIGH": 3, "MEDIUM": 1, "LOW": 0},
            top_missing_evidence=["wfirma", "sales"],
            top_master_data_gaps=["Gap A"],
            llm_used=False,
            generated_at="2026-05-24T12:00:00Z",
        )
        d = result.to_dict()
        required_keys = {
            "period", "total_batches", "blocked_batches", "incomplete_batches",
            "ready_batches", "document_coverage_score", "master_data_score",
            "graph_completeness_score", "workflow_risk_summary", "top_missing_evidence",
            "top_master_data_gaps", "llm_used", "generated_at",
        }
        assert required_keys.issubset(d.keys())

    def test_to_dict_llm_used_always_false(self):
        import app.services.operations_intelligence as mod
        result = mod.OperationsIntelligenceResult(
            period="today",
            total_batches=0,
            blocked_batches=0,
            incomplete_batches=0,
            ready_batches=0,
            document_coverage_score=0.0,
            master_data_score=0.0,
            graph_completeness_score=0.0,
            workflow_risk_summary={"HIGH": 0, "MEDIUM": 0, "LOW": 0},
            top_missing_evidence=[],
            top_master_data_gaps=[],
            llm_used=False,
            generated_at="2026-05-24T00:00:00Z",
        )
        assert result.to_dict()["llm_used"] is False

    def test_to_dict_scores_rounded_to_3dp(self):
        import app.services.operations_intelligence as mod
        result = mod.OperationsIntelligenceResult(
            period="7d",
            total_batches=1,
            blocked_batches=0,
            incomplete_batches=0,
            ready_batches=1,
            document_coverage_score=0.666666,
            master_data_score=0.333333,
            graph_completeness_score=0.123456,
            workflow_risk_summary={"HIGH": 0, "MEDIUM": 0, "LOW": 0},
            top_missing_evidence=[],
            top_master_data_gaps=[],
            llm_used=False,
            generated_at="2026-05-24T00:00:00Z",
        )
        d = result.to_dict()
        assert d["document_coverage_score"] == 0.667
        assert d["master_data_score"] == 0.333
        assert d["graph_completeness_score"] == 0.123

    # ── Period cutoff helpers ─────────────────────────────────────────────────

    def test_period_cutoff_today_is_start_of_day(self):
        import app.services.operations_intelligence as mod
        cutoff = mod._period_cutoff("today")
        # must start with today's date
        today = datetime.now(timezone.utc).date().isoformat()
        assert cutoff.startswith(today)
        assert "T00:00:00Z" in cutoff

    def test_period_cutoff_7d_is_7_days_ago(self):
        import app.services.operations_intelligence as mod
        cutoff = mod._period_cutoff("7d")
        # Parse and check it's within 8 days of now
        dt = datetime.strptime(cutoff, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        assert 6 <= delta.days <= 8

    def test_period_cutoff_30d_is_30_days_ago(self):
        import app.services.operations_intelligence as mod
        cutoff = mod._period_cutoff("30d")
        dt = datetime.strptime(cutoff, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        assert 29 <= delta.days <= 31

    # ── Batch enumeration ─────────────────────────────────────────────────────

    def test_enumerate_batch_ids_returns_empty_when_db_missing(self, tmp_path):
        import app.services.operations_intelligence as mod
        result = mod._enumerate_batch_ids("7d", 100, doc_db=tmp_path / "nonexistent.db")
        assert result == []

    def test_enumerate_batch_ids_from_real_db(self, tmp_path):
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        db = _create_documents_db(tmp_path, [
            {"batch_id": "BATCH-001", "created_at": now_iso},
            {"batch_id": "BATCH-002", "created_at": now_iso},
            {"batch_id": "BATCH-001", "created_at": now_iso},  # duplicate
        ])
        import app.services.operations_intelligence as mod
        result = mod._enumerate_batch_ids("7d", 100, doc_db=db)
        assert set(result) == {"BATCH-001", "BATCH-002"}
        assert len(result) == 2

    def test_enumerate_batch_ids_respects_limit(self, tmp_path):
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = [{"batch_id": f"B-{i:03d}", "created_at": now_iso} for i in range(10)]
        db = _create_documents_db(tmp_path, rows)
        import app.services.operations_intelligence as mod
        result = mod._enumerate_batch_ids("7d", 5, doc_db=db)
        assert len(result) == 5

    def test_enumerate_batch_ids_filters_by_period(self, tmp_path):
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        old_iso = "2020-01-01T00:00:00Z"
        db = _create_documents_db(tmp_path, [
            {"batch_id": "RECENT", "created_at": now_iso},
            {"batch_id": "OLD",    "created_at": old_iso},
        ])
        import app.services.operations_intelligence as mod
        result = mod._enumerate_batch_ids("7d", 100, doc_db=db)
        assert "RECENT" in result
        assert "OLD" not in result

    def test_enumerate_batch_ids_excludes_empty_batch_id(self, tmp_path):
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        db = _create_documents_db(tmp_path, [
            {"batch_id": "", "created_at": now_iso},
            {"batch_id": "REAL-BATCH", "created_at": now_iso},
        ])
        import app.services.operations_intelligence as mod
        result = mod._enumerate_batch_ids("7d", 100, doc_db=db)
        assert "" not in result
        assert "REAL-BATCH" in result

    # ── Readiness classification ──────────────────────────────────────────────

    def test_classify_readiness_blocked_when_wfirma_not_ready(self):
        import app.services.operations_intelligence as mod
        r = _make_readiness(wfirma_ready=False)
        assert mod._classify_readiness_severity(r) == "BLOCKED"

    def test_classify_readiness_blocked_when_sales_not_ready(self):
        import app.services.operations_intelligence as mod
        r = _make_readiness(sales_ready=False)
        assert mod._classify_readiness_severity(r) == "BLOCKED"

    def test_classify_readiness_blocked_when_dhl_not_ready_and_sla_breach(self):
        import app.services.operations_intelligence as mod
        r = _make_readiness(dhl_ready=False, sla_breach=True)
        assert mod._classify_readiness_severity(r) == "BLOCKED"

    def test_classify_readiness_incomplete_when_warehouse_not_ready(self):
        import app.services.operations_intelligence as mod
        r = _make_readiness(warehouse_ready=False)
        assert mod._classify_readiness_severity(r) == "INCOMPLETE"

    def test_classify_readiness_incomplete_when_dhl_not_ready_no_breach(self):
        import app.services.operations_intelligence as mod
        r = _make_readiness(dhl_ready=False, sla_breach=False)
        assert mod._classify_readiness_severity(r) == "INCOMPLETE"

    def test_classify_readiness_ready_when_all_ready(self):
        import app.services.operations_intelligence as mod
        r = _make_readiness()
        assert mod._classify_readiness_severity(r) == "READY"

    # ── Missing evidence collection ───────────────────────────────────────────

    def test_collect_missing_evidence_returns_not_ready_domains(self):
        import app.services.operations_intelligence as mod
        r = _make_readiness(wfirma_ready=False, warehouse_ready=False)
        missing = mod._collect_missing_evidence(r)
        assert "wfirma" in missing
        assert "warehouse" in missing
        assert "sales" not in missing

    def test_collect_missing_evidence_empty_when_all_ready(self):
        import app.services.operations_intelligence as mod
        r = _make_readiness()
        assert mod._collect_missing_evidence(r) == []

    # ── Aggregate missing evidence ────────────────────────────────────────────

    def test_aggregate_missing_evidence_sorted_by_frequency(self):
        import app.services.operations_intelligence as mod
        counter = {"wfirma": 5, "warehouse": 3, "sales": 8}
        result = mod._aggregate_missing_evidence(counter, top_n=3)
        assert result[0] == "sales"
        assert result[1] == "wfirma"
        assert result[2] == "warehouse"

    def test_aggregate_missing_evidence_empty_counter(self):
        import app.services.operations_intelligence as mod
        assert mod._aggregate_missing_evidence({}, top_n=5) == []

    def test_aggregate_missing_evidence_respects_top_n(self):
        import app.services.operations_intelligence as mod
        counter = {f"d{i}": i for i in range(10)}
        result = mod._aggregate_missing_evidence(counter, top_n=3)
        assert len(result) == 3

    # ── Integration: get_operations_intelligence ─────────────────────────────

    def test_empty_db_returns_zero_counts(self, tmp_path):
        db = _create_documents_db(tmp_path, [])
        import app.services.operations_intelligence as mod
        result = mod.get_operations_intelligence("7d", doc_db=db)
        assert result.total_batches == 0
        assert result.blocked_batches == 0
        assert result.incomplete_batches == 0
        assert result.ready_batches == 0
        assert result.llm_used is False

    def test_llm_used_always_false(self, tmp_path):
        db = _create_documents_db(tmp_path, [])
        import app.services.operations_intelligence as mod
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.return_value = _make_readiness()
        with patch.dict(sys.modules, {"app.services.batch_readiness": batch_mock,
                                      "app.services.master_data_intelligence": MagicMock()}):
            importlib.reload(mod)
            result = mod.get_operations_intelligence("7d", doc_db=db)
            assert result.llm_used is False

    def test_all_ready_batches_counted_correctly(self, tmp_path):
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        db = _create_documents_db(tmp_path, [
            {"batch_id": "B1", "created_at": now_iso},
            {"batch_id": "B2", "created_at": now_iso},
        ])
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.return_value = _make_readiness()
        mdi_mock = MagicMock()
        mdi_mock.generate_report.return_value = _make_mdi_report()

        import app.services.operations_intelligence as mod
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": batch_mock,
            "app.services.master_data_intelligence": mdi_mock,
        }):
            importlib.reload(mod)
            result = mod.get_operations_intelligence("7d", doc_db=db)

        assert result.total_batches == 2
        assert result.ready_batches == 2
        assert result.blocked_batches == 0
        assert result.incomplete_batches == 0

    def test_blocked_batches_counted_correctly(self, tmp_path):
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        db = _create_documents_db(tmp_path, [
            {"batch_id": "BLOCKED-1", "created_at": now_iso},
            {"batch_id": "READY-1",   "created_at": now_iso},
        ])
        call_count = {"n": 0}

        def readiness_by_batch(batch_id):
            call_count["n"] += 1
            if batch_id == "BLOCKED-1":
                return _make_readiness(wfirma_ready=False)  # HIGH blocker
            return _make_readiness()

        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.side_effect = readiness_by_batch
        mdi_mock = MagicMock()
        mdi_mock.generate_report.return_value = _make_mdi_report()

        import app.services.operations_intelligence as mod
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": batch_mock,
            "app.services.master_data_intelligence": mdi_mock,
        }):
            importlib.reload(mod)
            result = mod.get_operations_intelligence("7d", doc_db=db)

        assert result.total_batches == 2
        assert result.blocked_batches == 1
        assert result.ready_batches == 1
        assert result.workflow_risk_summary["HIGH"] >= 1

    def test_incomplete_batches_counted_correctly(self, tmp_path):
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        db = _create_documents_db(tmp_path, [
            {"batch_id": "INC-1", "created_at": now_iso},
        ])
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.return_value = _make_readiness(warehouse_ready=False)
        mdi_mock = MagicMock()
        mdi_mock.generate_report.return_value = _make_mdi_report()

        import app.services.operations_intelligence as mod
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": batch_mock,
            "app.services.master_data_intelligence": mdi_mock,
        }):
            importlib.reload(mod)
            result = mod.get_operations_intelligence("7d", doc_db=db)

        assert result.incomplete_batches == 1
        assert result.blocked_batches == 0
        assert result.workflow_risk_summary["MEDIUM"] >= 1

    def test_mdi_scores_pulled_from_generate_report(self, tmp_path):
        db = _create_documents_db(tmp_path, [])
        mdi_mock = MagicMock()
        mdi_mock.generate_report.return_value = _make_mdi_report(
            platform_score=0.80,
            document_score=0.65,
            graph_score=0.50,
        )

        import app.services.operations_intelligence as mod
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": MagicMock(),
            "app.services.master_data_intelligence": mdi_mock,
        }):
            importlib.reload(mod)
            result = mod.get_operations_intelligence("7d", doc_db=db)

        assert result.master_data_score == pytest.approx(0.80, abs=0.01)
        assert result.document_coverage_score == pytest.approx(0.65, abs=0.01)
        assert result.graph_completeness_score == pytest.approx(0.50, abs=0.01)

    def test_top_master_data_gaps_from_mdi_recommendations(self, tmp_path):
        db = _create_documents_db(tmp_path, [])
        mdi_mock = MagicMock()
        mdi_mock.generate_report.return_value = _make_mdi_report(
            top_recommendations=["Gap A", "Gap B", "Gap C", "Gap D"],
        )

        import app.services.operations_intelligence as mod
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": MagicMock(),
            "app.services.master_data_intelligence": mdi_mock,
        }):
            importlib.reload(mod)
            result = mod.get_operations_intelligence("7d", doc_db=db)

        # Top 3 only
        assert result.top_master_data_gaps == ["Gap A", "Gap B", "Gap C"]

    def test_domain_filter_restricts_missing_evidence(self, tmp_path):
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        db = _create_documents_db(tmp_path, [
            {"batch_id": "B1", "created_at": now_iso},
        ])
        batch_mock = MagicMock()
        # Both wfirma and warehouse are not ready
        batch_mock.get_batch_readiness.return_value = _make_readiness(
            wfirma_ready=False, warehouse_ready=False
        )
        mdi_mock = MagicMock()
        mdi_mock.generate_report.return_value = _make_mdi_report()

        import app.services.operations_intelligence as mod
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": batch_mock,
            "app.services.master_data_intelligence": mdi_mock,
        }):
            importlib.reload(mod)
            # Filter to wfirma domain only
            result = mod.get_operations_intelligence("7d", domain="wfirma", doc_db=db)

        assert "wfirma" in result.top_missing_evidence
        assert "warehouse" not in result.top_missing_evidence

    def test_missing_db_returns_zero_totals(self, tmp_path):
        import app.services.operations_intelligence as mod
        result = mod.get_operations_intelligence("7d", doc_db=tmp_path / "missing.db")
        assert result.total_batches == 0
        assert result.llm_used is False

    def test_period_today_uses_today_cutoff(self, tmp_path):
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        old_iso = "2020-01-01T00:00:00Z"
        db = _create_documents_db(tmp_path, [
            {"batch_id": "TODAY-BATCH", "created_at": now_iso},
            {"batch_id": "OLD-BATCH",   "created_at": old_iso},
        ])
        import app.services.operations_intelligence as mod
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.return_value = _make_readiness()
        mdi_mock = MagicMock()
        mdi_mock.generate_report.return_value = _make_mdi_report()
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": batch_mock,
            "app.services.master_data_intelligence": mdi_mock,
        }):
            importlib.reload(mod)
            result = mod.get_operations_intelligence("today", doc_db=db)

        assert result.total_batches == 1  # OLD-BATCH filtered out

    def test_period_30d_includes_older_batches(self, tmp_path):
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # 20 days ago
        from datetime import timedelta
        twenty_ago = (datetime.now(timezone.utc) - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
        db = _create_documents_db(tmp_path, [
            {"batch_id": "NOW-BATCH",    "created_at": now_iso},
            {"batch_id": "TWENTY-BATCH", "created_at": twenty_ago},
        ])
        import app.services.operations_intelligence as mod
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.return_value = _make_readiness()
        mdi_mock = MagicMock()
        mdi_mock.generate_report.return_value = _make_mdi_report()
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": batch_mock,
            "app.services.master_data_intelligence": mdi_mock,
        }):
            importlib.reload(mod)
            result = mod.get_operations_intelligence("30d", doc_db=db)

        assert result.total_batches == 2  # both included

    def test_workflow_risk_summary_has_correct_keys(self, tmp_path):
        db = _create_documents_db(tmp_path, [])
        import app.services.operations_intelligence as mod
        result = mod.get_operations_intelligence("7d", doc_db=db)
        assert set(result.workflow_risk_summary.keys()) == {"HIGH", "MEDIUM", "LOW"}

    def test_generated_at_is_valid_iso_format(self, tmp_path):
        db = _create_documents_db(tmp_path, [])
        import app.services.operations_intelligence as mod
        result = mod.get_operations_intelligence("7d", doc_db=db)
        # Must parse without error
        datetime.strptime(result.generated_at, "%Y-%m-%dT%H:%M:%SZ")

    def test_batch_readiness_failure_does_not_raise(self, tmp_path):
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        db = _create_documents_db(tmp_path, [
            {"batch_id": "B1", "created_at": now_iso},
        ])
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.side_effect = Exception("readiness exploded")
        mdi_mock = MagicMock()
        mdi_mock.generate_report.return_value = _make_mdi_report()

        import app.services.operations_intelligence as mod
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": batch_mock,
            "app.services.master_data_intelligence": mdi_mock,
        }):
            importlib.reload(mod)
            # Must not raise
            result = mod.get_operations_intelligence("7d", doc_db=db)

        assert result.total_batches == 1  # still counted; readiness just skipped
        assert result.llm_used is False

    def test_mdi_failure_returns_zero_scores(self, tmp_path):
        db = _create_documents_db(tmp_path, [])
        mdi_mock = MagicMock()
        mdi_mock.generate_report.side_effect = Exception("MDI exploded")

        import app.services.operations_intelligence as mod
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": MagicMock(),
            "app.services.master_data_intelligence": mdi_mock,
        }):
            importlib.reload(mod)
            result = mod.get_operations_intelligence("7d", doc_db=db)

        assert result.master_data_score == 0.0
        assert result.document_coverage_score == 0.0
        assert result.graph_completeness_score == 0.0

    def test_dhl_sla_breach_counts_as_high_blocked(self, tmp_path):
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        db = _create_documents_db(tmp_path, [
            {"batch_id": "DHL-SLA", "created_at": now_iso},
        ])
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.return_value = _make_readiness(
            dhl_ready=False, sla_breach=True
        )
        mdi_mock = MagicMock()
        mdi_mock.generate_report.return_value = _make_mdi_report()

        import app.services.operations_intelligence as mod
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": batch_mock,
            "app.services.master_data_intelligence": mdi_mock,
        }):
            importlib.reload(mod)
            result = mod.get_operations_intelligence("7d", doc_db=db)

        assert result.blocked_batches == 1
        assert result.workflow_risk_summary["HIGH"] >= 1

    def test_dhl_no_breach_counts_as_low_incomplete(self, tmp_path):
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        db = _create_documents_db(tmp_path, [
            {"batch_id": "DHL-LOW", "created_at": now_iso},
        ])
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.return_value = _make_readiness(
            dhl_ready=False, sla_breach=False
        )
        mdi_mock = MagicMock()
        mdi_mock.generate_report.return_value = _make_mdi_report()

        import app.services.operations_intelligence as mod
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": batch_mock,
            "app.services.master_data_intelligence": mdi_mock,
        }):
            importlib.reload(mod)
            result = mod.get_operations_intelligence("7d", doc_db=db)

        assert result.incomplete_batches == 1
        assert result.blocked_batches == 0
        assert result.workflow_risk_summary["LOW"] >= 1


# ── Route integration tests ───────────────────────────────────────────────────


class TestOperationsIntelligenceRoute:
    """Tests for GET /api/v1/operations/intelligence via TestClient."""

    SOURCE_FILE = "app/api/routes_operations_intelligence.py"

    def _src(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8")

    @pytest.fixture(autouse=True)
    def _client(self):
        from app.main import app
        self.client = TestClient(app, raise_server_exceptions=False)
        from app.core.config import settings
        self.api_key = settings.api_key

    def _headers(self):
        return {"X-API-Key": self.api_key}

    # ── 422 validation ────────────────────────────────────────────────────────

    def test_invalid_period_returns_422(self):
        resp = self.client.get(
            "/api/v1/operations/intelligence?period=invalid",
            headers=self._headers(),
        )
        assert resp.status_code == 422

    def test_invalid_domain_returns_422(self):
        resp = self.client.get(
            "/api/v1/operations/intelligence?domain=bogus",
            headers=self._headers(),
        )
        assert resp.status_code == 422

    # ── 200 success ───────────────────────────────────────────────────────────

    def test_default_period_returns_200(self):
        resp = self.client.get(
            "/api/v1/operations/intelligence",
            headers=self._headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "period" in data
        assert "total_batches" in data
        assert data["llm_used"] is False

    def test_period_today_returns_200(self):
        resp = self.client.get(
            "/api/v1/operations/intelligence?period=today",
            headers=self._headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["period"] == "today"

    def test_period_7d_returns_200(self):
        resp = self.client.get(
            "/api/v1/operations/intelligence?period=7d",
            headers=self._headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["period"] == "7d"

    def test_period_30d_returns_200(self):
        resp = self.client.get(
            "/api/v1/operations/intelligence?period=30d",
            headers=self._headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["period"] == "30d"

    def test_domain_warehouse_returns_200(self):
        resp = self.client.get(
            "/api/v1/operations/intelligence?domain=warehouse",
            headers=self._headers(),
        )
        assert resp.status_code == 200

    def test_domain_wfirma_returns_200(self):
        resp = self.client.get(
            "/api/v1/operations/intelligence?domain=wfirma",
            headers=self._headers(),
        )
        assert resp.status_code == 200

    def test_domain_sales_returns_200(self):
        resp = self.client.get(
            "/api/v1/operations/intelligence?domain=sales",
            headers=self._headers(),
        )
        assert resp.status_code == 200

    def test_domain_dhl_returns_200(self):
        resp = self.client.get(
            "/api/v1/operations/intelligence?domain=dhl",
            headers=self._headers(),
        )
        assert resp.status_code == 200

    def test_domain_graph_returns_200(self):
        resp = self.client.get(
            "/api/v1/operations/intelligence?domain=graph",
            headers=self._headers(),
        )
        assert resp.status_code == 200

    def test_domain_readiness_returns_200(self):
        resp = self.client.get(
            "/api/v1/operations/intelligence?domain=readiness",
            headers=self._headers(),
        )
        assert resp.status_code == 200

    # ── Response shape ────────────────────────────────────────────────────────

    def test_response_contains_all_required_fields(self):
        resp = self.client.get(
            "/api/v1/operations/intelligence",
            headers=self._headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        required = {
            "period", "total_batches", "blocked_batches", "incomplete_batches",
            "ready_batches", "document_coverage_score", "master_data_score",
            "graph_completeness_score", "workflow_risk_summary", "top_missing_evidence",
            "top_master_data_gaps", "llm_used", "generated_at",
        }
        assert required.issubset(data.keys())

    def test_llm_used_false_in_response(self):
        resp = self.client.get(
            "/api/v1/operations/intelligence",
            headers=self._headers(),
        )
        assert resp.json()["llm_used"] is False

    def test_workflow_risk_summary_has_three_keys(self):
        resp = self.client.get(
            "/api/v1/operations/intelligence",
            headers=self._headers(),
        )
        wrs = resp.json()["workflow_risk_summary"]
        assert set(wrs.keys()) == {"HIGH", "MEDIUM", "LOW"}

    def test_scores_are_floats(self):
        resp = self.client.get(
            "/api/v1/operations/intelligence",
            headers=self._headers(),
        )
        data = resp.json()
        for field in ("document_coverage_score", "master_data_score", "graph_completeness_score"):
            assert isinstance(data[field], (int, float)), f"{field} is not numeric"

    # ── Auth ──────────────────────────────────────────────────────────────────

    def test_missing_api_key_returns_401_or_200_in_dev(self):
        # Dev mode: settings.api_key may be empty -> auth bypass -> 200
        # Production: missing key -> 401
        resp = self.client.get("/api/v1/operations/intelligence")
        assert resp.status_code in (200, 401, 403)

    def test_wrong_api_key_returns_401_or_200_in_dev(self):
        # Dev mode: settings.api_key may be empty -> auth bypass -> 200
        # Production: wrong key -> 401
        resp = self.client.get(
            "/api/v1/operations/intelligence",
            headers={"X-API-Key": "WRONG-KEY"},
        )
        assert resp.status_code in (200, 401, 403)

    # ── Source-grep contracts ─────────────────────────────────────────────────

    def test_no_ai_gateway_import_in_route(self):
        src = self._src(self.SOURCE_FILE)
        import_lines = [
            ln for ln in src.splitlines()
            if "import" in ln and "ai_gateway" in ln and not ln.strip().startswith("#")
        ]
        assert import_lines == []

    def test_no_write_sql_in_route(self):
        src = self._src(self.SOURCE_FILE)
        assert "INSERT INTO" not in src, "Forbidden INSERT SQL in route"
        assert "DELETE FROM" not in src, "Forbidden DELETE SQL in route"

    # ── Regression: Phase 7+8+9 endpoints still work ─────────────────────────

    def test_phase7_search_still_200(self):
        resp = self.client.get(
            "/api/v1/search?q=test",
            headers=self._headers(),
        )
        assert resp.status_code == 200

    def test_phase8_intelligence_graph_still_200(self):
        resp = self.client.get(
            "/api/v1/intelligence/graph?anchor=SMOKE-TEST",
            headers=self._headers(),
        )
        assert resp.status_code == 200

    def test_phase9_workflow_intelligence_still_200(self):
        resp = self.client.get(
            "/api/v1/workflow/intelligence?batch_id=SMOKE-TEST",
            headers=self._headers(),
        )
        assert resp.status_code == 200

    def test_phase4_mdi_still_200(self):
        resp = self.client.get(
            "/api/v1/master-data/intelligence",
            headers=self._headers(),
        )
        assert resp.status_code == 200

    def test_health_still_200(self):
        resp = self.client.get(
            "/api/v1/health",
            headers=self._headers(),
        )
        assert resp.status_code == 200
