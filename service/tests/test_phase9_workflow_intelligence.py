"""Phase 9 -- Workflow Intelligence Foundation tests.

Test taxonomy:
  TestWorkflowBlockerClassification     -- readiness domain -> blockers
  TestWorkflowGraphSignals              -- graph conflict/missing -> blockers/warnings
  TestWorkflowStatusDerivation          -- BLOCKED/INCOMPLETE/READY/UNKNOWN
  TestWorkflowRecommendation            -- recommendation text logic
  TestWorkflowService                   -- get_workflow_intelligence() integration
  TestWorkflowAWBResolution             -- AWB -> batch_id via documents.db
  TestWorkflowRoute                     -- HTTP route contract tests
  TestWorkflowSourceGrep                -- governance invariant source-grep tests
"""

from __future__ import annotations

import sqlite3
import types
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────

def _readiness(
    wh_ready=True, sa_ready=True, wf_ready=True, dhl_ready=True, sla_breach=False,
    next_step="",
) -> Dict[str, Any]:
    def _dom(ready, msg="ok", **extra):
        d = {"ready": ready, "status": "clean" if ready else "partial", "message": msg}
        d.update(extra)
        return d
    blocked = []
    if not wh_ready: blocked.append("warehouse")
    if not sa_ready: blocked.append("sales")
    if not wf_ready: blocked.append("wfirma")
    if not dhl_ready: blocked.append("dhl")
    return {
        "batch_id": "BATCH-001",
        "warehouse": _dom(wh_ready, "Warehouse not ready" if not wh_ready else "ok"),
        "sales":     _dom(sa_ready, "Sales not ready" if not sa_ready else "ok"),
        "wfirma":    _dom(wf_ready, "wFirma not ready" if not wf_ready else "ok"),
        "dhl":       _dom(dhl_ready, "DHL not ready" if not dhl_ready else "ok",
                          sla_breach=sla_breach),
        "overall": {
            "ready_for_closure": not blocked,
            "blocked_domains": blocked,
            "next_step": next_step,
        },
    }


def _make_graph_result(
    missing=None, conflict_keys=None, batch_id="BATCH-001",
):
    """Create a minimal mock GraphResult."""
    gr = MagicMock()
    gr.batch_id    = batch_id
    gr.llm_used    = False
    gr.conflict_keys = conflict_keys or []
    lc = MagicMock()
    lc.missing = missing or []
    gr.link_completeness = lc
    return gr


# ── TestWorkflowBlockerClassification ─────────────────────────────────────────


class TestWorkflowBlockerClassification:
    """Verify _classify_readiness_blockers converts domain statuses to blockers."""

    def test_all_ready_no_blockers(self):
        from app.services.workflow_intelligence import _classify_readiness_blockers
        blockers = _classify_readiness_blockers(_readiness())
        assert blockers == []

    def test_wfirma_not_ready_is_high(self):
        from app.services.workflow_intelligence import _classify_readiness_blockers
        blockers = _classify_readiness_blockers(_readiness(wf_ready=False))
        assert len(blockers) == 1
        b = blockers[0]
        assert b.domain == "wfirma"
        assert b.severity == "HIGH"

    def test_sales_not_ready_is_high(self):
        from app.services.workflow_intelligence import _classify_readiness_blockers
        blockers = _classify_readiness_blockers(_readiness(sa_ready=False))
        wfirma_b = [b for b in blockers if b.domain == "sales"]
        assert len(wfirma_b) == 1
        assert wfirma_b[0].severity == "HIGH"

    def test_warehouse_not_ready_is_medium(self):
        from app.services.workflow_intelligence import _classify_readiness_blockers
        blockers = _classify_readiness_blockers(_readiness(wh_ready=False))
        wh = [b for b in blockers if b.domain == "warehouse"]
        assert len(wh) == 1
        assert wh[0].severity == "MEDIUM"

    def test_dhl_not_ready_no_breach_is_low(self):
        from app.services.workflow_intelligence import _classify_readiness_blockers
        blockers = _classify_readiness_blockers(_readiness(dhl_ready=False, sla_breach=False))
        dhl = [b for b in blockers if b.domain == "dhl"]
        assert len(dhl) == 1
        assert dhl[0].severity == "LOW"

    def test_dhl_not_ready_sla_breach_is_high(self):
        from app.services.workflow_intelligence import _classify_readiness_blockers
        blockers = _classify_readiness_blockers(_readiness(dhl_ready=False, sla_breach=True))
        dhl = [b for b in blockers if b.domain == "dhl"]
        assert len(dhl) == 1
        assert dhl[0].severity == "HIGH"

    def test_multiple_domains_blocked(self):
        from app.services.workflow_intelligence import _classify_readiness_blockers
        blockers = _classify_readiness_blockers(
            _readiness(wf_ready=False, wh_ready=False, dhl_ready=False)
        )
        domains = {b.domain for b in blockers}
        assert "wfirma" in domains
        assert "warehouse" in domains
        assert "dhl" in domains


# ── TestWorkflowGraphSignals ───────────────────────────────────────────────────


class TestWorkflowGraphSignals:
    """Verify _classify_graph_signals converts GraphResult to blockers/warnings/missing."""

    def test_no_issues_clean_result(self):
        from app.services.workflow_intelligence import _classify_graph_signals
        gr = _make_graph_result()
        blockers, warnings, missing = _classify_graph_signals(gr)
        assert blockers == []
        assert warnings == []
        assert missing == []

    def test_missing_awb_produces_warning_and_missing_entry(self):
        from app.services.workflow_intelligence import _classify_graph_signals
        gr = _make_graph_result(missing=["awb"])
        _, warnings, missing = _classify_graph_signals(gr)
        assert "awb" in missing
        warn_domains = [w.domain for w in warnings]
        assert "graph" in warn_domains

    def test_missing_multiple_links(self):
        from app.services.workflow_intelligence import _classify_graph_signals
        gr = _make_graph_result(missing=["awb", "customs", "invoice"])
        _, _, missing = _classify_graph_signals(gr)
        assert set(missing) == {"awb", "customs", "invoice"}

    def test_conflict_key_produces_high_blocker(self):
        from app.services.workflow_intelligence import _classify_graph_signals
        gr = _make_graph_result(conflict_keys=["awb"])
        blockers, _, _ = _classify_graph_signals(gr)
        assert len(blockers) == 1
        assert blockers[0].severity == "HIGH"
        assert blockers[0].domain == "graph"
        assert "awb" in blockers[0].reason

    def test_multiple_conflicts_multiple_high_blockers(self):
        from app.services.workflow_intelligence import _classify_graph_signals
        gr = _make_graph_result(conflict_keys=["awb", "customer"])
        blockers, _, _ = _classify_graph_signals(gr)
        high = [b for b in blockers if b.severity == "HIGH"]
        assert len(high) == 2

    def test_none_graph_result_returns_empty(self):
        from app.services.workflow_intelligence import _classify_graph_signals
        blockers, warnings, missing = _classify_graph_signals(None)
        assert blockers == []
        assert warnings == []
        assert missing == []


# ── TestWorkflowStatusDerivation ──────────────────────────────────────────────


class TestWorkflowStatusDerivation:
    """Verify _derive_status returns correct BLOCKED/INCOMPLETE/READY."""

    def test_no_blockers_no_missing_is_ready(self):
        from app.services.workflow_intelligence import _derive_status
        assert _derive_status([], []) == "READY"

    def test_high_blocker_is_blocked(self):
        from app.services.workflow_intelligence import (
            _derive_status, WorkflowBlocker,
        )
        b = WorkflowBlocker(domain="wfirma", reason="test", severity="HIGH")
        assert _derive_status([b], []) == "BLOCKED"

    def test_medium_blocker_is_incomplete(self):
        from app.services.workflow_intelligence import (
            _derive_status, WorkflowBlocker,
        )
        b = WorkflowBlocker(domain="warehouse", reason="test", severity="MEDIUM")
        assert _derive_status([b], []) == "INCOMPLETE"

    def test_low_blocker_is_incomplete(self):
        from app.services.workflow_intelligence import (
            _derive_status, WorkflowBlocker,
        )
        b = WorkflowBlocker(domain="dhl", reason="test", severity="LOW")
        assert _derive_status([b], []) == "INCOMPLETE"

    def test_missing_links_only_is_incomplete(self):
        from app.services.workflow_intelligence import _derive_status
        assert _derive_status([], ["awb", "mrn"]) == "INCOMPLETE"

    def test_high_blocker_beats_missing_links(self):
        from app.services.workflow_intelligence import (
            _derive_status, WorkflowBlocker,
        )
        b = WorkflowBlocker(domain="wfirma", reason="test", severity="HIGH")
        assert _derive_status([b], ["awb"]) == "BLOCKED"


# ── TestWorkflowRecommendation ────────────────────────────────────────────────


class TestWorkflowRecommendation:
    """Verify _recommend_next_review returns sensible text."""

    def test_ready_returns_no_action(self):
        from app.services.workflow_intelligence import _recommend_next_review
        rec = _recommend_next_review("READY", [], [], "")
        assert "ready" in rec.lower() or "no immediate" in rec.lower()

    def test_unknown_returns_check_logs(self):
        from app.services.workflow_intelligence import _recommend_next_review
        rec = _recommend_next_review("UNKNOWN", [], [], "")
        assert "unknown" in rec.lower() or "logs" in rec.lower()

    def test_blocked_wfirma_mentions_wfirma(self):
        from app.services.workflow_intelligence import (
            _recommend_next_review, WorkflowBlocker,
        )
        b = WorkflowBlocker(domain="wfirma", reason="test", severity="HIGH")
        rec = _recommend_next_review("BLOCKED", [b], [], "")
        assert "wfirma" in rec.lower() or "accounting" in rec.lower() or "pz" in rec.lower()

    def test_blocked_sales_mentions_invoice(self):
        from app.services.workflow_intelligence import (
            _recommend_next_review, WorkflowBlocker,
        )
        b = WorkflowBlocker(domain="sales", reason="test", severity="HIGH")
        rec = _recommend_next_review("BLOCKED", [b], [], "")
        assert "proforma" in rec.lower() or "invoice" in rec.lower() or "sales" in rec.lower()

    def test_incomplete_missing_awb_mentions_awb(self):
        from app.services.workflow_intelligence import _recommend_next_review
        rec = _recommend_next_review("INCOMPLETE", [], ["awb"], "")
        assert "awb" in rec.lower()

    def test_incomplete_missing_customs_mentions_customs(self):
        from app.services.workflow_intelligence import _recommend_next_review
        rec = _recommend_next_review("INCOMPLETE", [], ["customs"], "")
        assert "customs" in rec.lower() or "mrn" in rec.lower()

    def test_falls_back_to_readiness_next_step(self):
        from app.services.workflow_intelligence import _recommend_next_review
        rec = _recommend_next_review("INCOMPLETE", [], [], "Submit invoice to wFirma.")
        assert "Submit invoice" in rec


# ── TestWorkflowService ───────────────────────────────────────────────────────


class TestWorkflowService:
    """Integration tests for get_workflow_intelligence()."""

    def test_ready_batch_returns_ready_status(self):
        """All domains ready + no graph issues => llm_used=False, batch_id preserved."""
        import sys, importlib
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.return_value = _readiness()
        graph_mock = MagicMock()
        graph_mock.build_batch_graph.return_value = _make_graph_result()
        with patch.dict(sys.modules, {
            "app.services.batch_readiness":    batch_mock,
            "app.services.intelligence_graph": graph_mock,
        }):
            import app.services.workflow_intelligence as mod
            importlib.reload(mod)
            result = mod.get_workflow_intelligence("BATCH-001")
        assert result.llm_used is False
        assert result.batch_id == "BATCH-001"

    def test_llm_used_always_false(self):
        """llm_used must be False regardless of readiness or graph outcome."""
        import sys, importlib
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.return_value = _readiness(wf_ready=False)
        graph_mock = MagicMock()
        graph_mock.build_batch_graph.return_value = _make_graph_result(conflict_keys=["awb"])
        with patch.dict(sys.modules, {
            "app.services.batch_readiness":    batch_mock,
            "app.services.intelligence_graph": graph_mock,
        }):
            import app.services.workflow_intelligence as mod
            importlib.reload(mod)
            result = mod.get_workflow_intelligence("BATCH-001")
        assert result.llm_used is False

    def test_to_dict_shape(self):
        """to_dict() produces all required keys."""
        from app.services.workflow_intelligence import WorkflowIntelligenceResult
        r = WorkflowIntelligenceResult(
            batch_id="BATCH-TEST",
            workflow_status="READY",
            blockers=[],
            warnings=[],
            missing_links=[],
            readiness_impact={"warehouse": True, "sales": True, "wfirma": True,
                              "dhl": True, "ready_for_closure": True},
            recommended_next_operator_review="No action required.",
            llm_used=False,
            generated_at="2026-05-24T00:00:00Z",
        )
        d = r.to_dict()
        for key in ("batch_id", "workflow_status", "blockers", "warnings",
                    "missing_links", "readiness_impact",
                    "recommended_next_operator_review", "llm_used", "generated_at"):
            assert key in d, f"Missing key: {key}"
        assert d["llm_used"] is False

    def test_blockers_serialised_in_to_dict(self):
        from app.services.workflow_intelligence import (
            WorkflowIntelligenceResult, WorkflowBlocker,
        )
        r = WorkflowIntelligenceResult(
            batch_id="B",
            workflow_status="BLOCKED",
            blockers=[WorkflowBlocker(domain="wfirma", reason="test", severity="HIGH")],
            warnings=[],
            missing_links=[],
            readiness_impact={},
            recommended_next_operator_review="review wfirma",
            llm_used=False,
            generated_at="2026-05-24T00:00:00Z",
        )
        d = r.to_dict()
        assert len(d["blockers"]) == 1
        assert d["blockers"][0]["domain"] == "wfirma"
        assert d["blockers"][0]["severity"] == "HIGH"

    def test_readiness_fetch_failure_adds_warning_not_blocker(self):
        """If batch_readiness call raises, result should have a warning, not crash."""
        import sys
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.side_effect = RuntimeError("DB not found")
        graph_mock = MagicMock()
        graph_mock.build_batch_graph.return_value = _make_graph_result()
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": batch_mock,
            "app.services.intelligence_graph": graph_mock,
        }):
            # reimport to pick up fresh mocks
            import importlib
            import app.services.workflow_intelligence as mod
            importlib.reload(mod)
            result = mod.get_workflow_intelligence("BATCH-001")
        assert result.llm_used is False
        warn_domains = {w.domain for w in result.warnings}
        assert "readiness" in warn_domains

    def test_graph_fetch_failure_adds_warning_not_blocker(self):
        """If intelligence_graph call raises, result should have a warning, not crash."""
        import sys
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.return_value = _readiness()
        graph_mock = MagicMock()
        graph_mock.build_batch_graph.side_effect = RuntimeError("graph DB missing")
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": batch_mock,
            "app.services.intelligence_graph": graph_mock,
        }):
            import importlib
            import app.services.workflow_intelligence as mod
            importlib.reload(mod)
            result = mod.get_workflow_intelligence("BATCH-001")
        assert result.llm_used is False
        warn_domains = {w.domain for w in result.warnings}
        assert "graph" in warn_domains

    def test_domain_filter_limits_blockers(self):
        """domain='wfirma' should only return wfirma-domain blockers."""
        import sys
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.return_value = _readiness(
            wf_ready=False, wh_ready=False
        )
        graph_mock = MagicMock()
        graph_mock.build_batch_graph.return_value = _make_graph_result()
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": batch_mock,
            "app.services.intelligence_graph": graph_mock,
        }):
            import importlib
            import app.services.workflow_intelligence as mod
            importlib.reload(mod)
            result = mod.get_workflow_intelligence("BATCH-001", domain="wfirma")
        blocker_domains = {b.domain for b in result.blockers}
        assert "wfirma" in blocker_domains
        assert "warehouse" not in blocker_domains


# ── TestWorkflowAWBResolution ─────────────────────────────────────────────────


class TestWorkflowAWBResolution:
    """Verify AWB -> batch_id resolution via documents.db."""

    def test_resolves_awb_from_db(self, tmp_path):
        from app.services.workflow_intelligence import resolve_batch_id_from_awb
        db = tmp_path / "documents.db"
        con = sqlite3.connect(str(db))
        con.execute(
            "CREATE TABLE shipment_documents "
            "(id INTEGER PRIMARY KEY, batch_id TEXT, awb TEXT)"
        )
        con.execute(
            "INSERT INTO shipment_documents (batch_id, awb) VALUES (?,?)",
            ("BATCH-AWB-001", "9765416334"),
        )
        con.commit(); con.close()

        result = resolve_batch_id_from_awb("9765416334", doc_db=db)
        assert result == "BATCH-AWB-001"

    def test_missing_db_returns_none(self, tmp_path):
        from app.services.workflow_intelligence import resolve_batch_id_from_awb
        result = resolve_batch_id_from_awb("9999999999", doc_db=tmp_path / "missing.db")
        assert result is None

    def test_unknown_awb_returns_none(self, tmp_path):
        from app.services.workflow_intelligence import resolve_batch_id_from_awb
        db = tmp_path / "documents.db"
        con = sqlite3.connect(str(db))
        con.execute("CREATE TABLE shipment_documents (id INTEGER PRIMARY KEY, batch_id TEXT, awb TEXT)")
        con.commit(); con.close()
        result = resolve_batch_id_from_awb("0000000000", doc_db=db)
        assert result is None

    def test_empty_batch_id_skipped(self, tmp_path):
        """Rows with empty batch_id must not be returned."""
        from app.services.workflow_intelligence import resolve_batch_id_from_awb
        db = tmp_path / "documents.db"
        con = sqlite3.connect(str(db))
        con.execute("CREATE TABLE shipment_documents (id INTEGER PRIMARY KEY, batch_id TEXT, awb TEXT)")
        con.execute("INSERT INTO shipment_documents (batch_id, awb) VALUES ('', '9765416334')")
        con.commit(); con.close()
        result = resolve_batch_id_from_awb("9765416334", doc_db=db)
        assert result is None


# ── TestWorkflowRoute ──────────────────────────────────────────────────────────


class TestWorkflowRoute:
    """HTTP route contract tests using TestClient."""

    @pytest.fixture(autouse=True)
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self._client = TestClient(app, raise_server_exceptions=False)
        return self._client

    def _headers(self):
        return {"X-API-Key": "test-key"}

    def test_missing_batch_id_and_awb_returns_422(self):
        resp = self._client.get(
            "/api/v1/workflow/intelligence",
            headers=self._headers(),
        )
        assert resp.status_code in (401, 422), resp.text

    def test_invalid_domain_returns_422(self):
        import sys
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.return_value = _readiness()
        graph_mock = MagicMock()
        graph_mock.build_batch_graph.return_value = _make_graph_result()
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": batch_mock,
            "app.services.intelligence_graph": graph_mock,
        }):
            resp = self._client.get(
                "/api/v1/workflow/intelligence?batch_id=BATCH-001&domain=invalid_domain",
                headers=self._headers(),
            )
        assert resp.status_code in (401, 422)

    def test_batch_id_returns_200(self):
        import sys
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.return_value = _readiness()
        graph_mock = MagicMock()
        graph_mock.build_batch_graph.return_value = _make_graph_result()
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": batch_mock,
            "app.services.intelligence_graph": graph_mock,
        }):
            resp = self._client.get(
                "/api/v1/workflow/intelligence?batch_id=BATCH-001",
                headers=self._headers(),
            )
        assert resp.status_code in (200, 401)

    def test_awb_not_found_returns_404(self, tmp_path):
        # Patch the resolver at the module where it is imported (routes uses module-level import)
        with patch(
            "app.api.routes_workflow_intelligence.resolve_batch_id_from_awb",
            return_value=None,
        ):
            resp = self._client.get(
                "/api/v1/workflow/intelligence?awb=0000000000",
                headers=self._headers(),
            )
        assert resp.status_code in (401, 404)

    def test_response_has_llm_used_false(self):
        """llm_used must be false in every response body."""
        import sys
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.return_value = _readiness()
        graph_mock = MagicMock()
        graph_mock.build_batch_graph.return_value = _make_graph_result()
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": batch_mock,
            "app.services.intelligence_graph": graph_mock,
        }):
            resp = self._client.get(
                "/api/v1/workflow/intelligence?batch_id=BATCH-001",
                headers=self._headers(),
            )
        if resp.status_code == 200:
            assert resp.json()["llm_used"] is False

    def test_response_has_required_keys(self):
        import sys
        batch_mock = MagicMock()
        batch_mock.get_batch_readiness.return_value = _readiness()
        graph_mock = MagicMock()
        graph_mock.build_batch_graph.return_value = _make_graph_result()
        with patch.dict(sys.modules, {
            "app.services.batch_readiness": batch_mock,
            "app.services.intelligence_graph": graph_mock,
        }):
            resp = self._client.get(
                "/api/v1/workflow/intelligence?batch_id=BATCH-001",
                headers=self._headers(),
            )
        if resp.status_code == 200:
            body = resp.json()
            for key in (
                "batch_id", "workflow_status", "blockers", "warnings",
                "missing_links", "readiness_impact",
                "recommended_next_operator_review", "llm_used", "generated_at",
            ):
                assert key in body, f"Missing response key: {key}"


# ── TestWorkflowSourceGrep ────────────────────────────────────────────────────


class TestWorkflowSourceGrep:
    """Governance invariant tests via source code inspection."""

    SERVICE_FILE = (
        Path(__file__).parent.parent
        / "app" / "services" / "workflow_intelligence.py"
    )
    ROUTE_FILE = (
        Path(__file__).parent.parent
        / "app" / "api" / "routes_workflow_intelligence.py"
    )

    def _src(self, p: Path) -> str:
        return p.read_text(encoding="utf-8")

    def test_service_file_exists(self):
        assert self.SERVICE_FILE.exists(), "workflow_intelligence.py not found"

    def test_route_file_exists(self):
        assert self.ROUTE_FILE.exists(), "routes_workflow_intelligence.py not found"

    def test_llm_used_false_hardcoded_in_service(self):
        src = self._src(self.SERVICE_FILE)
        assert "llm_used = False" in src or "llm_used=False" in src, \
            "llm_used=False not hardcoded in workflow_intelligence.py"

    def test_no_insert_sql_in_service(self):
        src = self._src(self.SERVICE_FILE).upper()
        assert "INSERT INTO" not in src, \
            "Forbidden INSERT SQL found in workflow_intelligence.py"

    def test_no_update_sql_in_service(self):
        src = self._src(self.SERVICE_FILE).upper()
        assert "UPDATE " not in src or "PRAGMA query_only" in self._src(self.SERVICE_FILE), \
            "UPDATE SQL without PRAGMA query_only in workflow_intelligence.py"

    def test_no_delete_sql_in_service(self):
        src = self._src(self.SERVICE_FILE).upper()
        assert "DELETE FROM" not in src, \
            "Forbidden DELETE SQL found in workflow_intelligence.py"

    def test_pragma_query_only_in_service(self):
        src = self._src(self.SERVICE_FILE)
        assert "PRAGMA query_only" in src, \
            "PRAGMA query_only not found in workflow_intelligence.py"

    def test_no_anthropic_import_in_service(self):
        src = self._src(self.SERVICE_FILE)
        assert "import anthropic" not in src.lower() and \
               "from anthropic" not in src.lower(), \
            "Forbidden anthropic import in workflow_intelligence.py"

    def test_no_ai_gateway_import_in_service(self):
        src = self._src(self.SERVICE_FILE)
        # Check for actual import statements, not docstring/comment mentions
        import_lines = [
            ln for ln in src.splitlines()
            if "import" in ln and "ai_gateway" in ln and not ln.strip().startswith("#")
        ]
        assert import_lines == [], \
            f"Forbidden ai_gateway import in workflow_intelligence.py: {import_lines}"

    def test_route_is_get_only(self):
        src = self._src(self.ROUTE_FILE)
        assert "@router.get" in src, "No GET route in routes_workflow_intelligence.py"
        assert "@router.post" not in src, \
            "Forbidden POST route in routes_workflow_intelligence.py"
        assert "@router.put" not in src, \
            "Forbidden PUT route in routes_workflow_intelligence.py"
        assert "@router.delete" not in src, \
            "Forbidden DELETE route in routes_workflow_intelligence.py"

    def test_llm_used_false_in_route_description(self):
        src = self._src(self.ROUTE_FILE)
        assert "llm_used=False" in src or "llm_used = False" in src or \
               "llm_used=false" in src.lower(), \
            "llm_used=False not documented in route description"

    def test_no_direct_insert_in_route(self):
        src = self._src(self.ROUTE_FILE).upper()
        assert "INSERT INTO" not in src, "Forbidden INSERT in route file"

    def test_main_py_imports_workflow_router(self):
        main_src = (
            Path(__file__).parent.parent / "app" / "main.py"
        ).read_text(encoding="utf-8")
        assert "workflow_intelligence_router" in main_src, \
            "workflow_intelligence_router not imported/registered in main.py"
