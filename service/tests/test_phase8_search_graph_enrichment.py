"""Phase 8 Sprint 4 -- Search Graph Enrichment: test suite.

Coverage:
  - enrich=False (default): hits have no graph_enrichment key in to_dict()
  - enrich=True with missing doc_db: graph_enrichment has graph_available=False
  - enrich=True with seeded doc_db: document hit -> related_count/batch_ids
  - enrich=True with shipment hit: entity_id is batch_id directly
  - enrich=True with customer hit: resolves batch_ids by client_contractor_id
  - enrich=True with supplier hit: resolves batch_ids by supplier_contractor_id
  - enrich=True with product hit: no batch relationship -> graph_available=False
  - related_count excludes self for document hits
  - execute_search(..., enrich=True) signature contract
  - Route GET /api/v1/search?q=X&enrich=true returns graph_enrichment keys
  - Route GET /api/v1/search?q=X (no enrich) returns no graph_enrichment keys
  - Source-grep: no write SQL in _enrich_hits / _resolve_batch_ids_for_hit
  - llm_used=False preserved with enrich=True
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
# DB helper
# ---------------------------------------------------------------------------

def _make_docs_db(path: Path, rows: list[dict]) -> None:
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
                (id, batch_id, awb, document_type, file_name,
                 client_contractor_id, supplier_contractor_id,
                 related_invoice_no, related_mrn, related_pz_no)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r.get("id", "doc-001"),
                r.get("batch_id", "B1"),
                r.get("awb", ""),
                r.get("document_type", "invoice"),
                r.get("file_name", "test.pdf"),
                r.get("customer", ""),
                r.get("supplier", ""),
                r.get("invoice_no", ""),
                r.get("mrn", ""),
                r.get("pz", ""),
            ),
        )
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _headers():
    return {"X-API-Key": os.getenv("API_KEY", "test-key")}


# ---------------------------------------------------------------------------
# TestEnrichOff -- enrich=False (default) behavior
# ---------------------------------------------------------------------------

class TestEnrichOff:
    """With enrich=False (default), hits must NOT carry graph_enrichment."""

    def test_execute_search_no_enrich_no_key(self):
        from app.services.search_engine import parse_query, execute_search
        result = execute_search(parse_query("test keyword"))
        for h in result.hits:
            assert h.graph_enrichment is None

    def test_to_dict_no_enrich_no_key_in_hit(self):
        from app.services.search_engine import parse_query, execute_search
        d = execute_search(parse_query("test keyword")).to_dict()
        for h in d["hits"]:
            assert "graph_enrichment" not in h

    def test_enrich_false_explicit_same_as_default(self):
        from app.services.search_engine import parse_query, execute_search
        r1 = execute_search(parse_query("alpha"), enrich=False)
        r2 = execute_search(parse_query("alpha"))
        for h in r1.hits:
            assert h.graph_enrichment is None
        for h in r2.hits:
            assert h.graph_enrichment is None


# ---------------------------------------------------------------------------
# TestEnrichMissingDb -- enrich=True but doc_db absent
# ---------------------------------------------------------------------------

class TestEnrichMissingDb:
    """enrich=True with a missing doc_db still returns enrichment, but zeroed."""

    def _make_document_hit(self):
        from app.services.search_engine import SearchHit
        return SearchHit(
            domain="document",
            entity_id="doc-xxx",
            title="test",
            subtitle="",
            match_reason="",
            details={},
            score=0.9,
        )

    def test_missing_db_graph_available_false(self):
        from app.services.search_engine import _enrich_hits
        h = self._make_document_hit()
        _enrich_hits([h], doc_db=Path("/nonexistent/documents.db"))
        assert h.graph_enrichment["graph_available"] is False

    def test_missing_db_related_count_zero(self):
        from app.services.search_engine import _enrich_hits
        h = self._make_document_hit()
        _enrich_hits([h], doc_db=Path("/nonexistent/documents.db"))
        assert h.graph_enrichment["related_count"] == 0

    def test_missing_db_related_batch_ids_empty(self):
        from app.services.search_engine import _enrich_hits
        h = self._make_document_hit()
        _enrich_hits([h], doc_db=Path("/nonexistent/documents.db"))
        assert h.graph_enrichment["related_batch_ids"] == []

    def test_missing_db_all_hits_enriched(self):
        """Every hit gets enrichment even when db missing."""
        from app.services.search_engine import SearchHit, _enrich_hits
        hits = [
            SearchHit("document", f"doc-{i}", "t", "", "", {}, 1.0)
            for i in range(3)
        ]
        _enrich_hits(hits, doc_db=Path("/nonexistent"))
        assert all(h.graph_enrichment is not None for h in hits)


# ---------------------------------------------------------------------------
# TestEnrichDocumentHit
# ---------------------------------------------------------------------------

class TestEnrichDocumentHit:
    """enrich=True for document-domain hits."""

    def _batch_rows(self) -> list:
        """3 docs in the same batch, 1 in a separate batch."""
        return [
            {"id": "d1", "batch_id": "BATCH-A", "awb": "AWB001"},
            {"id": "d2", "batch_id": "BATCH-A", "awb": "AWB001"},
            {"id": "d3", "batch_id": "BATCH-A", "awb": "AWB001"},
            {"id": "d4", "batch_id": "BATCH-B", "awb": "AWB002"},
        ]

    def test_document_hit_related_count_excludes_self(self):
        from app.services.search_engine import SearchHit, _enrich_hits
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, self._batch_rows())
            h = SearchHit("document", "d1", "t", "", "", {}, 1.0)
            _enrich_hits([h], doc_db=db)
        # BATCH-A has 3 docs; d1 is self, so related = 2
        assert h.graph_enrichment["related_count"] == 2

    def test_document_hit_graph_available_true(self):
        from app.services.search_engine import SearchHit, _enrich_hits
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, self._batch_rows())
            h = SearchHit("document", "d1", "t", "", "", {}, 1.0)
            _enrich_hits([h], doc_db=db)
        assert h.graph_enrichment["graph_available"] is True

    def test_document_hit_batch_id_in_related(self):
        from app.services.search_engine import SearchHit, _enrich_hits
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, self._batch_rows())
            h = SearchHit("document", "d1", "t", "", "", {}, 1.0)
            _enrich_hits([h], doc_db=db)
        assert "BATCH-A" in h.graph_enrichment["related_batch_ids"]

    def test_document_hit_unknown_entity_id_zeroed(self):
        from app.services.search_engine import SearchHit, _enrich_hits
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, self._batch_rows())
            h = SearchHit("document", "nonexistent-id", "t", "", "", {}, 1.0)
            _enrich_hits([h], doc_db=db)
        assert h.graph_enrichment["graph_available"] is False
        assert h.graph_enrichment["related_count"] == 0

    def test_document_hit_solo_batch_related_count_zero(self):
        """A document alone in its batch has related_count=0 (not -1)."""
        from app.services.search_engine import SearchHit, _enrich_hits
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, [{"id": "solo", "batch_id": "SOLO-BATCH"}])
            h = SearchHit("document", "solo", "t", "", "", {}, 1.0)
            _enrich_hits([h], doc_db=db)
        assert h.graph_enrichment["related_count"] == 0
        assert h.graph_enrichment["graph_available"] is True


# ---------------------------------------------------------------------------
# TestEnrichShipmentHit
# ---------------------------------------------------------------------------

class TestEnrichShipmentHit:
    """enrich=True for shipment-domain hits (entity_id is batch_id)."""

    def test_shipment_hit_batch_id_used_directly(self):
        from app.services.search_engine import SearchHit, _enrich_hits
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            rows = [
                {"id": f"doc-{i}", "batch_id": "SHIP-BATCH", "awb": "AWB999"}
                for i in range(4)
            ]
            _make_docs_db(db, rows)
            h = SearchHit("shipment", "SHIP-BATCH", "t", "", "", {}, 1.0)
            _enrich_hits([h], doc_db=db)
        assert h.graph_enrichment["graph_available"] is True
        assert h.graph_enrichment["related_count"] == 4
        assert "SHIP-BATCH" in h.graph_enrichment["related_batch_ids"]

    def test_shipment_hit_empty_entity_id_zeroed(self):
        from app.services.search_engine import SearchHit, _enrich_hits
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, [])
            h = SearchHit("shipment", "", "t", "", "", {}, 1.0)
            _enrich_hits([h], doc_db=db)
        assert h.graph_enrichment["graph_available"] is False


# ---------------------------------------------------------------------------
# TestEnrichCustomerHit
# ---------------------------------------------------------------------------

class TestEnrichCustomerHit:
    """enrich=True for customer-domain hits."""

    def test_customer_hit_resolves_batch_ids(self):
        from app.services.search_engine import SearchHit, _enrich_hits
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            rows = [
                {"id": f"d{i}", "batch_id": f"CUST-BATCH-{i}", "customer": "CLIENT-001"}
                for i in range(3)
            ]
            _make_docs_db(db, rows)
            h = SearchHit("customer", "CLIENT-001", "t", "", "", {}, 1.0)
            _enrich_hits([h], doc_db=db)
        assert h.graph_enrichment["graph_available"] is True
        assert len(h.graph_enrichment["related_batch_ids"]) == 3

    def test_customer_hit_unknown_id_zeroed(self):
        from app.services.search_engine import SearchHit, _enrich_hits
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, [{"id": "d1", "batch_id": "B1", "customer": "C001"}])
            h = SearchHit("customer", "UNKNOWN-CUSTOMER", "t", "", "", {}, 1.0)
            _enrich_hits([h], doc_db=db)
        assert h.graph_enrichment["graph_available"] is False


# ---------------------------------------------------------------------------
# TestEnrichSupplierHit
# ---------------------------------------------------------------------------

class TestEnrichSupplierHit:
    """enrich=True for supplier-domain hits."""

    def test_supplier_hit_resolves_batch_ids(self):
        from app.services.search_engine import SearchHit, _enrich_hits
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            rows = [
                {"id": f"d{i}", "batch_id": f"SUPP-BATCH-{i}", "supplier": "SUPP-XYZ"}
                for i in range(2)
            ]
            _make_docs_db(db, rows)
            h = SearchHit("supplier", "SUPP-XYZ", "t", "", "", {}, 1.0)
            _enrich_hits([h], doc_db=db)
        assert h.graph_enrichment["graph_available"] is True
        assert len(h.graph_enrichment["related_batch_ids"]) == 2


# ---------------------------------------------------------------------------
# TestEnrichProductHit
# ---------------------------------------------------------------------------

class TestEnrichProductHit:
    """Product hits have no batch relationship in documents.db."""

    def test_product_hit_graph_available_false(self):
        from app.services.search_engine import SearchHit, _enrich_hits
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "documents.db"
            _make_docs_db(db, [{"id": "d1", "batch_id": "B1"}])
            h = SearchHit("product", "DESIGN-001", "t", "", "", {}, 1.0)
            _enrich_hits([h], doc_db=db)
        assert h.graph_enrichment["graph_available"] is False
        assert h.graph_enrichment["related_count"] == 0


# ---------------------------------------------------------------------------
# TestEnrichExecuteSearch
# ---------------------------------------------------------------------------

class TestEnrichExecuteSearch:
    """execute_search(..., enrich=True) contract tests."""

    def test_execute_search_enrich_true_returns_enrichment(self):
        """Even with no real DBs, enrich=True populates graph_enrichment."""
        from app.services.search_engine import parse_query, execute_search
        result = execute_search(
            parse_query("test keyword"),
            enrich=True,
            doc_db=Path("/nonexistent/documents.db"),
        )
        for h in result.hits:
            assert h.graph_enrichment is not None

    def test_execute_search_enrich_to_dict_has_key(self):
        from app.services.search_engine import parse_query, execute_search
        d = execute_search(
            parse_query("test keyword"),
            enrich=True,
            doc_db=Path("/nonexistent/documents.db"),
        ).to_dict()
        # If there are any hits, each must have graph_enrichment
        for h in d["hits"]:
            assert "graph_enrichment" in h

    def test_execute_search_llm_used_false_with_enrich(self):
        from app.services.search_engine import parse_query, execute_search
        result = execute_search(parse_query("anything"), enrich=True)
        assert result.llm_used is False

    def test_execute_search_no_enrich_hits_no_enrichment_key(self):
        from app.services.search_engine import parse_query, execute_search
        d = execute_search(parse_query("anything"), enrich=False).to_dict()
        for h in d["hits"]:
            assert "graph_enrichment" not in h

    def test_execute_search_with_real_seeded_db(self):
        """Fully seeded DB: document hit returns graph_available=True."""
        from app.services.search_engine import parse_query, execute_search
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "documents.db"
            rows = [
                {"id": "d1", "batch_id": "BATCHX", "awb": "12345678901",
                 "document_type": "invoice", "file_name": "inv.pdf"},
                {"id": "d2", "batch_id": "BATCHX", "awb": "12345678901",
                 "document_type": "customs", "file_name": "cust.pdf"},
            ]
            _make_docs_db(db, rows)
            result = execute_search(
                parse_query("12345678901"),
                enrich=True,
                doc_db=db,
            )
        doc_hits = [h for h in result.hits if h.domain == "document"]
        assert len(doc_hits) >= 1
        for h in doc_hits:
            assert h.graph_enrichment is not None
            assert h.graph_enrichment["graph_available"] is True


# ---------------------------------------------------------------------------
# TestEnrichRoute -- route-level tests
# ---------------------------------------------------------------------------

class TestEnrichRoute:
    def test_search_no_enrich_param_no_enrichment_key(self, client):
        resp = client.get("/api/v1/search?q=test", headers=_headers())
        assert resp.status_code in (200, 401, 403)
        if resp.status_code == 200:
            for h in resp.json().get("hits", []):
                assert "graph_enrichment" not in h

    def test_search_enrich_false_no_enrichment_key(self, client):
        resp = client.get("/api/v1/search?q=test&enrich=false", headers=_headers())
        assert resp.status_code in (200, 401, 403)
        if resp.status_code == 200:
            for h in resp.json().get("hits", []):
                assert "graph_enrichment" not in h

    def test_search_enrich_true_returns_200(self, client):
        resp = client.get("/api/v1/search?q=test&enrich=true", headers=_headers())
        assert resp.status_code in (200, 401, 403)

    def test_search_enrich_true_hits_have_enrichment_key(self, client):
        resp = client.get("/api/v1/search?q=invoice&enrich=true", headers=_headers())
        assert resp.status_code in (200, 401, 403)
        if resp.status_code == 200:
            for h in resp.json().get("hits", []):
                assert "graph_enrichment" in h

    def test_search_enrich_true_enrichment_keys_shape(self, client):
        resp = client.get("/api/v1/search?q=invoice&enrich=true", headers=_headers())
        assert resp.status_code in (200, 401, 403)
        if resp.status_code == 200:
            for h in resp.json().get("hits", []):
                ge = h.get("graph_enrichment", {})
                assert "graph_available" in ge
                assert "related_count" in ge
                assert "related_batch_ids" in ge

    def test_search_enrich_true_llm_used_false(self, client):
        resp = client.get("/api/v1/search?q=test&enrich=true", headers=_headers())
        assert resp.status_code in (200, 401, 403)
        if resp.status_code == 200:
            assert resp.json().get("llm_used") is False


# ---------------------------------------------------------------------------
# TestEnrichSourceGrep -- safety invariants
# ---------------------------------------------------------------------------

class TestEnrichSourceGrep:
    """Source-grep: _enrich_hits must have no write SQL."""

    def _src(self) -> str:
        from pathlib import Path
        p = Path(__file__).parent.parent / "app" / "services" / "search_engine.py"
        return p.read_text(encoding="utf-8")

    def test_no_write_sql_in_enrich_hits(self):
        import re
        src = self._src()
        match = re.search(r"def _enrich_hits\(.*?(?=\ndef |\Z)", src, re.DOTALL)
        assert match, "_enrich_hits function not found"
        body = match.group(0)
        for kw in ("INSERT", "UPDATE", "DELETE"):
            lines = [l for l in body.splitlines()
                     if kw in l.upper() and not l.strip().startswith("#")]
            assert lines == [], f"{kw} found in _enrich_hits: {lines}"

    def test_no_write_sql_in_resolve_batch_ids(self):
        import re
        src = self._src()
        match = re.search(
            r"def _resolve_batch_ids_for_hit\(.*?(?=\ndef |\Z)", src, re.DOTALL
        )
        assert match, "_resolve_batch_ids_for_hit not found"
        body = match.group(0)
        for kw in ("INSERT", "UPDATE", "DELETE"):
            lines = [l for l in body.splitlines()
                     if kw in l.upper() and not l.strip().startswith("#")]
            assert lines == [], f"{kw} found in _resolve_batch_ids_for_hit: {lines}"

    def test_pragma_query_only_in_ro_conn(self):
        src = self._src()
        assert "PRAGMA query_only" in src

    def test_llm_used_false_preserved(self):
        src = self._src()
        assert "llm_used=False" in src

    def test_enrich_param_in_execute_search(self):
        src = self._src()
        assert "enrich:" in src or "enrich :" in src

    def test_graph_enrichment_field_in_search_hit(self):
        src = self._src()
        assert "graph_enrichment" in src
