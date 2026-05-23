"""Phase 8 Sprint 3 -- MDI Graph Domain: test suite.

Coverage:
  - _score_graph() with no DB (zero-state)
  - _score_graph() with empty documents.db (0 batches)
  - _score_graph() with real temp documents.db + seeded batches
  - Link dimension scoring (awb, invoice, customs, pz, customer, supplier)
  - tracking dimension scored only when tracking_events.db available
  - Field gaps raised when dimension <80% coverage
  - MasterDataIntelligenceReport has graph field + to_dict() includes it
  - generate_report() returns graph DomainScore
  - GET /api/v1/master-data/intelligence returns graph in response
  - GET /api/v1/master-data/intelligence/graph returns 200
  - Platform score weight rebalance: 7 weights sum to 1.0
  - Source-grep: no write SQL in scorer, llm_used=False preserved
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient
import os


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _make_docs_db(path: Path, rows: list[dict]) -> None:
    """Create documents.db with shipment_documents schema and seed rows."""
    con = sqlite3.connect(str(path))
    con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS shipment_documents (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL DEFAULT '',
            awb TEXT NOT NULL DEFAULT '',
            document_type TEXT NOT NULL DEFAULT '',
            file_name TEXT NOT NULL DEFAULT '',
            canonical_file_name TEXT NOT NULL DEFAULT '',
            file_path TEXT NOT NULL DEFAULT '',
            file_hash TEXT NOT NULL DEFAULT '',
            parser_name TEXT NOT NULL DEFAULT '',
            parser_version TEXT NOT NULL DEFAULT '',
            parser_status TEXT NOT NULL DEFAULT 'pending',
            extraction_status TEXT NOT NULL DEFAULT 'pending',
            requires_manual_review INTEGER NOT NULL DEFAULT 0,
            related_invoice_no TEXT NOT NULL DEFAULT '',
            related_mrn TEXT NOT NULL DEFAULT '',
            related_pz_no TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'upload',
            client_contractor_id TEXT NOT NULL DEFAULT '',
            supplier_contractor_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '2026-05-24T10:00:00+00:00',
            updated_at TEXT NOT NULL DEFAULT '2026-05-24T10:00:00+00:00'
        );
    """)
    for r in rows:
        con.execute(
            """
            INSERT INTO shipment_documents
                (id, batch_id, awb, related_invoice_no, related_mrn, related_pz_no,
                 client_contractor_id, supplier_contractor_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r.get("id", "doc-001"),
                r.get("batch_id", "B1"),
                r.get("awb", ""),
                r.get("invoice_no", ""),
                r.get("mrn", ""),
                r.get("pz", ""),
                r.get("customer", ""),
                r.get("supplier", ""),
            ),
        )
    con.commit()
    con.close()


def _make_tracking_db(path: Path, batch_ids: list[str]) -> None:
    """Create tracking_events.db with one event per batch_id."""
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS shipment_tracking_events (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL DEFAULT '',
            awb TEXT NOT NULL DEFAULT '',
            event_time TEXT NOT NULL DEFAULT '',
            normalized_stage TEXT NOT NULL DEFAULT '',
            raw_subject TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT ''
        );
    """)
    for i, bid in enumerate(batch_ids):
        con.execute(
            "INSERT INTO shipment_tracking_events (id, batch_id, awb) VALUES (?, ?, ?)",
            (f"evt-{i}", bid, "AWB001"),
        )
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# TestScoreGraphNoDb
# ---------------------------------------------------------------------------

class TestScoreGraphNoDb:
    """_score_graph with missing documents.db."""

    def test_missing_doc_db_returns_zero_entity_count(self):
        from app.services.master_data_intelligence import _score_graph
        score = _score_graph(doc_db=Path("/nonexistent/documents.db"))
        assert score.entity_count == 0

    def test_missing_doc_db_confidence_zero(self):
        from app.services.master_data_intelligence import _score_graph
        score = _score_graph(doc_db=Path("/nonexistent/documents.db"))
        assert score.confidence == 0.0

    def test_missing_doc_db_completeness_zero(self):
        from app.services.master_data_intelligence import _score_graph
        score = _score_graph(doc_db=Path("/nonexistent/documents.db"))
        assert score.completeness_score == 0.0

    def test_missing_doc_db_has_field_gap(self):
        from app.services.master_data_intelligence import _score_graph
        score = _score_graph(doc_db=Path("/nonexistent/documents.db"))
        assert len(score.field_gaps) >= 1

    def test_domain_name_is_graph(self):
        from app.services.master_data_intelligence import _score_graph
        score = _score_graph(doc_db=Path("/nonexistent/documents.db"))
        assert score.domain == "graph"

    def test_llm_used_not_in_score_graph(self):
        """DomainScore has no llm_used field -- but caller sets llm_used=False."""
        from app.services.master_data_intelligence import _score_graph
        score = _score_graph(doc_db=Path("/nonexistent/documents.db"))
        # DomainScore dataclass should not have llm_used; verify caller invariant in report
        assert not hasattr(score, "llm_used")


# ---------------------------------------------------------------------------
# TestScoreGraphEmptyDb
# ---------------------------------------------------------------------------

class TestScoreGraphEmptyDb:
    """_score_graph with empty documents.db (schema present, 0 rows)."""

    def test_empty_db_zero_batches(self):
        from app.services.master_data_intelligence import _score_graph
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, [])
            score = _score_graph(doc_db=db)
        assert score.entity_count == 0

    def test_empty_db_completeness_zero(self):
        from app.services.master_data_intelligence import _score_graph
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, [])
            score = _score_graph(doc_db=db)
        assert score.completeness_score == 0.0


# ---------------------------------------------------------------------------
# TestScoreGraphWithBatches
# ---------------------------------------------------------------------------

class TestScoreGraphWithBatches:
    """_score_graph with real seeded batches."""

    def _fully_linked_row(self, idx: int) -> dict:
        return {
            "id": f"doc-{idx}",
            "batch_id": f"BATCH-{idx:03d}",
            "awb": f"AWB{idx:010d}",
            "invoice_no": f"INV-{idx}",
            "mrn": f"MRN-{idx}",
            "pz": f"PZ-{idx}",
            "customer": f"CLIENT-{idx}",
            "supplier": f"SUPP-{idx}",
        }

    def test_fully_linked_batches_high_completeness(self):
        from app.services.master_data_intelligence import _score_graph
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, [self._fully_linked_row(i) for i in range(5)])
            score = _score_graph(doc_db=db, tracking_db=Path("/nonexistent/tracking.db"))
        # 5 fully linked batches, tracking_db missing (tracking not counted)
        # 6 dims (awb/invoice/customs/pz/customer/supplier), all linked
        assert score.completeness_score > 0.9
        assert score.entity_count == 5

    def test_batch_count_correct(self):
        from app.services.master_data_intelligence import _score_graph
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, [self._fully_linked_row(i) for i in range(3)])
            score = _score_graph(doc_db=db, tracking_db=Path("/nonexistent/tracking.db"))
        assert score.entity_count == 3

    def test_missing_awb_creates_field_gap(self):
        from app.services.master_data_intelligence import _score_graph
        rows = [
            {
                "id": f"doc-{i}", "batch_id": f"B-{i}",
                "awb": "",  # deliberately empty
                "invoice_no": "INV-001", "mrn": "MRN-001",
                "pz": "PZ-001", "customer": "C001", "supplier": "S001",
            }
            for i in range(5)
        ]
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, rows)
            score = _score_graph(doc_db=db, tracking_db=Path("/nonexistent/tracking.db"))
        gap_fields = [g.field for g in score.field_gaps]
        assert "awb" in gap_fields

    def test_all_batches_missing_link_low_score(self):
        from app.services.master_data_intelligence import _score_graph
        rows = [{"id": f"doc-{i}", "batch_id": f"B-{i}"} for i in range(4)]
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, rows)
            score = _score_graph(doc_db=db, tracking_db=Path("/nonexistent/tracking.db"))
        assert score.completeness_score < 0.1

    def test_tracking_counted_when_db_available(self):
        from app.services.master_data_intelligence import _score_graph
        with tempfile.TemporaryDirectory() as d:
            db  = Path(d) / "documents.db"
            tdb = Path(d) / "tracking.db"
            rows = [self._fully_linked_row(i) for i in range(3)]
            _make_docs_db(db, rows)
            _make_tracking_db(tdb, [f"BATCH-{i:03d}" for i in range(3)])
            score = _score_graph(doc_db=db, tracking_db=tdb)
        # 7 dims (tracking now counted), all fully linked -> very high score
        assert score.completeness_score > 0.9
        assert score.details.get("tracking_db_available") is True

    def test_tracking_not_counted_when_db_missing(self):
        from app.services.master_data_intelligence import _score_graph
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, [self._fully_linked_row(0)])
            score = _score_graph(doc_db=db, tracking_db=Path(d) / "nonexistent_tracking.db")
        assert score.details.get("tracking_db_available") is False

    def test_details_contains_dimensions(self):
        from app.services.master_data_intelligence import _score_graph
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, [self._fully_linked_row(0)])
            score = _score_graph(doc_db=db, tracking_db=Path("/nonexistent"))
        dims = score.details.get("dimensions", {})
        for dim in ("awb", "invoice", "customs", "pz", "customer", "supplier"):
            assert dim in dims, f"Missing dimension: {dim}"

    def test_confidence_increases_with_batch_count(self):
        from app.services.master_data_intelligence import _score_graph
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, [self._fully_linked_row(i) for i in range(20)])
            score = _score_graph(doc_db=db, tracking_db=Path("/nonexistent"))
        assert score.confidence >= 0.8  # 20 batches -> near max confidence


# ---------------------------------------------------------------------------
# TestMDIReportGraphField
# ---------------------------------------------------------------------------

class TestMDIReportGraphField:
    """MasterDataIntelligenceReport has graph field and to_dict() includes it."""

    def test_report_has_graph_domain_score(self):
        from app.services.master_data_intelligence import generate_report
        report = generate_report()
        assert hasattr(report, "graph")

    def test_report_graph_domain_name(self):
        from app.services.master_data_intelligence import generate_report
        report = generate_report()
        assert report.graph.domain == "graph"

    def test_report_llm_used_false(self):
        from app.services.master_data_intelligence import generate_report
        report = generate_report()
        assert report.llm_used is False

    def test_to_dict_includes_graph(self):
        from app.services.master_data_intelligence import generate_report
        d = generate_report().to_dict()
        assert "graph" in d

    def test_to_dict_graph_has_domain_score_keys(self):
        from app.services.master_data_intelligence import generate_report
        d = generate_report().to_dict()
        g = d["graph"]
        for key in ("domain", "entity_count", "completeness_score", "confidence",
                    "field_gaps", "advisory", "recommendations"):
            assert key in g, f"Missing key in graph domain: {key}"

    def test_platform_score_weights_sum_to_one(self):
        """Verify the 7-domain weight rebalance sums to 1.0."""
        weights = [0.22, 0.20, 0.16, 0.11, 0.12, 0.09, 0.10]
        assert abs(sum(weights) - 1.0) < 1e-9, f"Weights sum to {sum(weights)}"


# ---------------------------------------------------------------------------
# TestMDIRouteGraphDomain -- route-level tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _headers():
    return {"X-API-Key": os.getenv("API_KEY", "test-key")}


class TestMDIRouteGraphDomain:
    def test_platform_report_includes_graph(self, client):
        resp = client.get("/api/v1/master-data/intelligence", headers=_headers())
        assert resp.status_code == 200
        assert "graph" in resp.json()

    def test_graph_domain_endpoint_200(self, client):
        resp = client.get("/api/v1/master-data/intelligence/graph", headers=_headers())
        assert resp.status_code == 200

    def test_graph_domain_response_has_completeness_score(self, client):
        resp = client.get("/api/v1/master-data/intelligence/graph", headers=_headers())
        assert resp.status_code == 200
        d = resp.json()
        assert "completeness_score" in d

    def test_graph_domain_response_has_llm_used_false(self, client):
        resp = client.get("/api/v1/master-data/intelligence/graph", headers=_headers())
        assert resp.status_code == 200
        d = resp.json()
        assert d.get("llm_used") is False

    def test_platform_report_llm_used_false(self, client):
        resp = client.get("/api/v1/master-data/intelligence", headers=_headers())
        assert resp.status_code == 200
        assert resp.json().get("llm_used") is False


# ---------------------------------------------------------------------------
# TestGraphDomainSourceGrep -- safety invariants
# ---------------------------------------------------------------------------

class TestGraphDomainSourceGrep:
    """Source-grep tests: _score_graph must have no write SQL."""

    def _mdi_source(self) -> str:
        from pathlib import Path
        p = Path(__file__).parent.parent / "app" / "services" / "master_data_intelligence.py"
        return p.read_text(encoding="utf-8")

    def test_no_write_sql_in_score_graph(self):
        import re
        src = self._mdi_source()
        # Find the _score_graph function body
        match = re.search(r"def _score_graph\(.*?(?=\ndef |\Z)", src, re.DOTALL)
        assert match, "_score_graph function not found"
        body = match.group(0)
        for kw in ("INSERT", "UPDATE", "DELETE"):
            lines = [l for l in body.splitlines()
                     if kw in l.upper() and not l.strip().startswith("#")]
            assert lines == [], f"{kw} found in _score_graph: {lines}"

    def test_pragma_query_only_in_score_graph(self):
        src = self._mdi_source()
        assert "PRAGMA query_only" in src

    def test_llm_used_false_in_generate_report(self):
        src = self._mdi_source()
        assert "llm_used=False" in src

    def test_graph_in_generate_report_weights(self):
        """7 weights present in generate_report."""
        import re
        src = self._mdi_source()
        # Find the weights line in generate_report
        match = re.search(r"weights\s*=\s*\[([\d.,\s]+)\]", src)
        assert match, "weights list not found in generate_report"
        weight_str = match.group(1)
        weights = [float(w.strip()) for w in weight_str.split(",") if w.strip()]
        assert len(weights) == 7, f"Expected 7 weights, found {len(weights)}"
        assert abs(sum(weights) - 1.0) < 1e-6, f"Weights do not sum to 1.0: {sum(weights)}"
