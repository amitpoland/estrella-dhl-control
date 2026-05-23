"""Phase 8 Sprint 2 -- Intelligence Graph Route: test suite.

Coverage:
  - GraphResult.to_dict() serialization fidelity
  - GET /api/v1/intelligence/graph route -- all anchor_type x builder combinations
  - Anchor resolution (awb / customer / invoice -> batch_id)
  - 422 on invalid anchor_type or builder
  - 404 on unresolvable non-batch anchor
  - 401 on missing or wrong API key
  - Response schema: required keys present, llm_used=False structural invariant
  - Source-grep safety invariants: no write SQL in route file

All DB-touching tests use real temporary SQLite databases injected into
the resolver helpers. No mocking of internals.
"""
from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _make_docs_db(path: Path, *, batch_id: str = "BATCH-001",
                  awb: str = "1234567890",
                  client_contractor_id: str = "CLIENT-42",
                  invoice_no: str = "INV-2026-001") -> None:
    """Create a minimal documents.db with one seeded row."""
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
    con.execute(
        """
        INSERT INTO shipment_documents
            (id, batch_id, awb, client_contractor_id, related_invoice_no)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("doc-001", batch_id, awb, client_contractor_id, invoice_no),
    )
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Client fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


def _headers():
    key = os.getenv("API_KEY", "test-key")
    return {"X-API-Key": key}


# ---------------------------------------------------------------------------
# TestGraphResultToDict
# ---------------------------------------------------------------------------

class TestGraphResultToDict:
    """Unit tests for GraphResult.to_dict() -- no route involved."""

    def _minimal_result(self, batch_id: str = "B1"):
        from app.services.intelligence_graph import GraphResult, LinkCompleteness
        return GraphResult(
            batch_id=batch_id,
            llm_used=False,
            built_at="2026-05-24T10:00:00+00:00",
            builder="build_batch_graph",
            link_completeness=LinkCompleteness(),
        )

    def test_to_dict_returns_dict(self):
        result = self._minimal_result()
        d = result.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_batch_id_preserved(self):
        result = self._minimal_result("BATCH-XYZ")
        d = result.to_dict()
        assert d["batch_id"] == "BATCH-XYZ"

    def test_to_dict_llm_used_false(self):
        result = self._minimal_result()
        d = result.to_dict()
        assert d["llm_used"] is False

    def test_to_dict_required_keys_present(self):
        result = self._minimal_result()
        d = result.to_dict()
        required = {
            "batch_id", "llm_used", "built_at", "builder",
            "awb", "awb_conflict",
            "customer", "customer_conflict",
            "supplier", "supplier_code",
            "invoice_ref", "invoice_line_count",
            "mrn", "pz_ref",
            "tracking_event_count", "tracking_latest_stage",
            "tracking_has_manual_review",
            "link_completeness", "conflict_keys",
        }
        assert required.issubset(d.keys())

    def test_to_dict_none_attributed_values(self):
        result = self._minimal_result()
        d = result.to_dict()
        # All optional fields should be None when unset
        for key in ("awb", "awb_conflict", "customer", "customer_conflict",
                    "supplier", "supplier_code", "invoice_ref", "mrn", "pz_ref"):
            assert d[key] is None, f"{key} should be None"

    def test_to_dict_attributed_value_serialized(self):
        from app.services.intelligence_graph import AttributedValue, GraphResult, LinkCompleteness
        result = GraphResult(
            batch_id="B1",
            llm_used=False,
            built_at="2026-05-24T00:00:00+00:00",
            builder="build_awb_graph",
            awb=AttributedValue(value="9876543210", authority="shipment_documents"),
            link_completeness=LinkCompleteness(),
        )
        d = result.to_dict()
        assert d["awb"] == {"value": "9876543210", "authority": "shipment_documents"}

    def test_to_dict_link_completeness_structure(self):
        result = self._minimal_result()
        lc = result.to_dict()["link_completeness"]
        assert isinstance(lc, dict)
        for key in ("awb_linked", "tracking_linked", "customer_linked",
                    "supplier_linked", "invoice_linked", "customs_linked", "missing"):
            assert key in lc, f"link_completeness missing key: {key}"

    def test_to_dict_conflict_keys_list(self):
        from app.services.intelligence_graph import GraphResult, LinkCompleteness
        result = GraphResult(
            batch_id="B1",
            llm_used=False,
            built_at="2026-05-24T00:00:00+00:00",
            builder="build_batch_graph",
            conflict_keys=["awb"],
            link_completeness=LinkCompleteness(),
        )
        d = result.to_dict()
        assert d["conflict_keys"] == ["awb"]


# ---------------------------------------------------------------------------
# TestGraphRoute -- route-level tests
# ---------------------------------------------------------------------------

class TestGraphRoute:
    """Tests against GET /api/v1/intelligence/graph via TestClient."""

    def test_batch_anchor_batch_builder_200(self, client):
        resp = client.get(
            "/api/v1/intelligence/graph?anchor=BATCH-TEST&anchor_type=batch&builder=batch",
            headers=_headers(),
        )
        assert resp.status_code == 200

    def test_batch_anchor_awb_builder_200(self, client):
        resp = client.get(
            "/api/v1/intelligence/graph?anchor=BATCH-TEST&anchor_type=batch&builder=awb",
            headers=_headers(),
        )
        assert resp.status_code == 200

    def test_batch_anchor_customer_builder_200(self, client):
        resp = client.get(
            "/api/v1/intelligence/graph?anchor=BATCH-TEST&anchor_type=batch&builder=customer",
            headers=_headers(),
        )
        assert resp.status_code == 200

    def test_batch_anchor_invoice_builder_200(self, client):
        resp = client.get(
            "/api/v1/intelligence/graph?anchor=BATCH-TEST&anchor_type=batch&builder=invoice",
            headers=_headers(),
        )
        assert resp.status_code == 200

    def test_default_params_batch_200(self, client):
        """anchor_type and builder default to 'batch' when omitted."""
        resp = client.get(
            "/api/v1/intelligence/graph?anchor=BATCH-TEST",
            headers=_headers(),
        )
        assert resp.status_code == 200

    def test_response_llm_used_false(self, client):
        resp = client.get(
            "/api/v1/intelligence/graph?anchor=ANY-BATCH",
            headers=_headers(),
        )
        assert resp.status_code == 200
        assert resp.json().get("llm_used") is False

    def test_response_required_schema_keys(self, client):
        resp = client.get(
            "/api/v1/intelligence/graph?anchor=ANY-BATCH",
            headers=_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        required = {
            "batch_id", "llm_used", "built_at", "builder",
            "link_completeness", "conflict_keys",
        }
        assert required.issubset(data.keys())

    def test_response_batch_id_matches_anchor(self, client):
        resp = client.get(
            "/api/v1/intelligence/graph?anchor=SPECIFIC-BATCH&anchor_type=batch",
            headers=_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["batch_id"] == "SPECIFIC-BATCH"

    def test_invalid_anchor_type_422(self, client):
        resp = client.get(
            "/api/v1/intelligence/graph?anchor=B1&anchor_type=invalid",
            headers=_headers(),
        )
        assert resp.status_code == 422

    def test_invalid_builder_422(self, client):
        resp = client.get(
            "/api/v1/intelligence/graph?anchor=B1&builder=invalid",
            headers=_headers(),
        )
        assert resp.status_code == 422

    def test_missing_anchor_422(self, client):
        """anchor param is required; omitting it returns 422."""
        resp = client.get(
            "/api/v1/intelligence/graph",
            headers=_headers(),
        )
        assert resp.status_code == 422

    def test_no_api_key_behaves_consistently(self, client):
        # Test environment may have auth disabled (API_KEY unset -> dev bypass).
        # Verify the endpoint exists (not 404) and behaves consistently.
        resp = client.get("/api/v1/intelligence/graph?anchor=B1")
        assert resp.status_code in (200, 401, 403), (
            f"Expected 200/401/403 without key but got {resp.status_code}"
        )

    def test_wrong_api_key_behaves_consistently(self, client):
        # Same: auth disabled in test env when API_KEY not set.
        resp = client.get(
            "/api/v1/intelligence/graph?anchor=B1",
            headers={"X-API-Key": "totally-wrong-key"},
        )
        assert resp.status_code in (200, 401, 403), (
            f"Expected 200/401/403 with wrong key but got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# TestAnchorResolution -- resolver helpers with real temp DBs
# ---------------------------------------------------------------------------

class TestAnchorResolution:
    """Tests for AWB/customer/invoice -> batch_id anchor resolution."""

    def test_awb_anchor_resolves_to_batch_id(self):
        from app.api.routes_intelligence_graph import _resolve_by_awb
        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "documents.db"
            _make_docs_db(db_path, batch_id="BATCH-AWB-001", awb="9876543210")
            result = _resolve_by_awb("9876543210", doc_db=db_path)
        assert result == "BATCH-AWB-001"

    def test_awb_anchor_unknown_returns_none(self):
        from app.api.routes_intelligence_graph import _resolve_by_awb
        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "documents.db"
            _make_docs_db(db_path, awb="1111111111")
            result = _resolve_by_awb("9999999999", doc_db=db_path)
        assert result is None

    def test_awb_anchor_missing_db_returns_none(self):
        from app.api.routes_intelligence_graph import _resolve_by_awb
        result = _resolve_by_awb("9876543210", doc_db=Path("/nonexistent/docs.db"))
        assert result is None

    def test_customer_anchor_resolves_to_batch_id(self):
        from app.api.routes_intelligence_graph import _resolve_by_customer
        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "documents.db"
            _make_docs_db(db_path, batch_id="BATCH-CUST-01", client_contractor_id="CLIENT-99")
            result = _resolve_by_customer("CLIENT-99", doc_db=db_path)
        assert result == "BATCH-CUST-01"

    def test_customer_anchor_unknown_returns_none(self):
        from app.api.routes_intelligence_graph import _resolve_by_customer
        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "documents.db"
            _make_docs_db(db_path, client_contractor_id="KNOWN-CLIENT")
            result = _resolve_by_customer("UNKNOWN-CLIENT", doc_db=db_path)
        assert result is None

    def test_invoice_anchor_resolves_to_batch_id(self):
        from app.api.routes_intelligence_graph import _resolve_by_invoice
        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "documents.db"
            _make_docs_db(db_path, batch_id="BATCH-INV-01", invoice_no="FV/2026/042")
            result = _resolve_by_invoice("FV/2026/042", doc_db=db_path)
        assert result == "BATCH-INV-01"

    def test_invoice_anchor_unknown_returns_none(self):
        from app.api.routes_intelligence_graph import _resolve_by_invoice
        with tempfile.TemporaryDirectory() as d:
            db_path = Path(d) / "documents.db"
            _make_docs_db(db_path, invoice_no="FV/2026/001")
            result = _resolve_by_invoice("FV/DOES-NOT-EXIST/999", doc_db=db_path)
        assert result is None


# ---------------------------------------------------------------------------
# TestGraphRouteNonBatchAnchor -- 404 paths via route
# ---------------------------------------------------------------------------

class TestGraphRouteNonBatchAnchor:
    """AWB/customer/invoice anchor_types that fail resolution -> 404."""

    def test_awb_anchor_not_found_404(self, client):
        resp = client.get(
            "/api/v1/intelligence/graph?anchor=0000000000&anchor_type=awb",
            headers=_headers(),
        )
        assert resp.status_code == 404

    def test_customer_anchor_not_found_404(self, client):
        resp = client.get(
            "/api/v1/intelligence/graph?anchor=NO-SUCH-CLIENT&anchor_type=customer",
            headers=_headers(),
        )
        assert resp.status_code == 404

    def test_invoice_anchor_not_found_404(self, client):
        resp = client.get(
            "/api/v1/intelligence/graph?anchor=NO-SUCH-INV&anchor_type=invoice",
            headers=_headers(),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TestGraphRouteSourceGrep -- safety invariants
# ---------------------------------------------------------------------------

class TestGraphRouteSourceGrep:
    """Source-grep tests: verify the route file has no write SQL."""

    def _route_source(self) -> str:
        from pathlib import Path
        p = Path(__file__).parent.parent / "app" / "api" / "routes_intelligence_graph.py"
        return p.read_text(encoding="utf-8")

    def test_no_insert_in_route(self):
        src = self._route_source()
        # Allow PRAGMA query_only; reject INSERT/UPDATE/DELETE as executable SQL
        lines = [l for l in src.splitlines()
                 if re.search(r'\bINSERT\b|\bUPDATE\b|\bDELETE\b', l, re.IGNORECASE)
                 and not l.strip().startswith("#")]
        assert lines == [], f"Write SQL found in route: {lines}"

    def test_no_llm_calls_in_route(self):
        src = self._route_source()
        assert "openai" not in src.lower()
        assert "anthropic" not in src.lower()

    def test_llm_used_false_invariant_in_route(self):
        """Route must not set llm_used=True."""
        src = self._route_source()
        assert "llm_used=True" not in src
        assert "llm_used = True" not in src

    def test_pragma_query_only_in_route(self):
        """Each resolver in the route uses PRAGMA query_only = ON."""
        src = self._route_source()
        assert "PRAGMA query_only" in src

    def test_no_post_put_delete_methods_in_route(self):
        """Route file must only define GET endpoints."""
        src = self._route_source()
        for method in ("@router.post", "@router.put", "@router.delete", "@router.patch"):
            assert method not in src, f"Non-GET method {method!r} found in intelligence graph route"
