"""
tests/test_dashboard_route_audit.py

Unit tests for app/tools/dashboard_route_audit.py.

Each test exercises the pure-function layer (extract_frontend_calls, audit,
paths_compatible, find_match) — no filesystem access, no FastAPI import needed.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

_SERVICE = Path(__file__).resolve().parents[1]
if str(_SERVICE) not in sys.path:
    sys.path.insert(0, str(_SERVICE))

from app.tools.dashboard_route_audit import (
    BackendRoute,
    AuditResult,
    audit,
    extract_frontend_calls,
    find_match,
    paths_compatible,
)


# ── storage-root guard ────────────────────────────────────────────────────────
# Importing app.tools.dashboard_route_audit pulls in app.core.config which
# initialises settings.storage_root to the live path.  These tests are pure-
# function and never touch storage, but conftest._guard_storage_root checks
# settings after every test.
#
# Use a module-scoped patch via unittest.mock so it outlasts monkeypatch
# teardown (which would restore the live root before the conftest guard runs).

_tmp_storage_dir = tempfile.mkdtemp(prefix="audit_test_")


@pytest.fixture(autouse=True, scope="module")
def _patch_storage_root_module():
    from app.core.config import settings
    with patch.object(settings, "storage_root", Path(_tmp_storage_dir)):
        yield


# ── helpers ────────────────────────────────────────────────────────────────────

def _be(*routes: tuple) -> list[BackendRoute]:
    """Build a backend route list from (methods_list_or_str, path) tuples."""
    result = []
    for methods, path in routes:
        if isinstance(methods, str):
            methods = [methods]
        result.append(BackendRoute(methods=list(methods), path=path))
    return result


# ── paths_compatible ───────────────────────────────────────────────────────────

class TestPathsCompatible:
    def test_exact_static_match(self):
        assert paths_compatible("/api/v1/health", "/api/v1/health")

    def test_segment_count_mismatch(self):
        assert not paths_compatible("/api/v1/health", "/api/v1/health/check")

    def test_frontend_param_matches_literal(self):
        # Normalised frontend: ${batchId} → {param}
        assert paths_compatible("/api/v1/batches/{param}", "/api/v1/batches/{batch_id}")

    def test_backend_param_matches_literal(self):
        assert paths_compatible("/api/v1/batches/abc123", "/api/v1/batches/{batch_id}")

    def test_multi_param_segments(self):
        assert paths_compatible(
            "/api/v1/action-proposals/{param}/{param}",
            "/api/v1/action-proposals/{proposal_id}/approve",
        )

    def test_path_converter_prefix_match(self):
        assert paths_compatible("/dashboard/batches/xyz/files", "/dashboard/{path:path}")

    def test_literal_mismatch(self):
        # Two concrete (non-param) segments that differ → no match
        assert not paths_compatible("/api/v1/tracking/events", "/api/v1/tracking/timeline")

    def test_trailing_segment_differs(self):
        assert not paths_compatible("/api/v1/foo/bar", "/api/v1/foo/baz")


# ── extract_frontend_calls ─────────────────────────────────────────────────────

class TestExtractFrontendCalls:
    def test_static_apifetch_get(self):
        html = "apiFetch('/api/v1/health')"
        calls = extract_frontend_calls(html)
        assert len(calls) == 1
        assert calls[0].path == "/api/v1/health"
        assert calls[0].method == "GET"

    def test_apifetch_post_method(self):
        html = "apiFetch('/api/v1/upload/shipment', { method: 'POST' })"
        calls = extract_frontend_calls(html)
        assert len(calls) == 1
        assert calls[0].method == "POST"

    def test_apifetch_delete_method(self):
        html = "apiFetch(`/api/v1/batches/${id}`, { method: 'DELETE' })"
        calls = extract_frontend_calls(html)
        assert calls[0].method == "DELETE"

    def test_template_literal_normalised(self):
        html = "apiFetch(`/api/v1/tracking/${encodeURIComponent(batchId)}/timeline`)"
        calls = extract_frontend_calls(html)
        assert calls[0].path == "/api/v1/tracking/{param}/timeline"

    def test_query_string_stripped(self):
        html = "apiFetch(`/api/v1/dhl/scan-inbox?batch_id=${encodeURIComponent(batchId)}`)"
        calls = extract_frontend_calls(html)
        assert calls[0].path == "/api/v1/dhl/scan-inbox"

    def test_href_static(self):
        html = '<a href="/api/v1/tracking/events/export/download">Download</a>'
        calls = extract_frontend_calls(html)
        assert any(c.path == "/api/v1/tracking/events/export/download" for c in calls)

    def test_href_template_literal(self):
        html = 'href={`/api/v1/dhl/download/${encodeURIComponent(fn)}`}'
        calls = extract_frontend_calls(html)
        assert calls[0].path == "/api/v1/dhl/download/{param}"
        assert calls[0].method == "GET"

    def test_window_open(self):
        html = "window.open('/api/v1/tracking/events/export/download', '_blank')"
        calls = extract_frontend_calls(html)
        assert any(c.path == "/api/v1/tracking/events/export/download" for c in calls)

    def test_ignores_external_urls(self):
        html = "fetch('https://external.com/api/data')"
        calls = extract_frontend_calls(html)
        assert not calls

    def test_ignores_relative_nonapi_paths(self):
        # fetch('/auth/me') should still be captured (starts with /)
        html = "fetch('/auth/me', { credentials: 'include' })"
        calls = extract_frontend_calls(html)
        assert len(calls) == 1
        assert calls[0].path == "/auth/me"

    def test_fetch_without_leading_slash_ignored(self):
        html = "fetch('action.endpoint')"
        calls = extract_frontend_calls(html)
        assert not calls

    def test_multiple_calls_extracted(self):
        html = "apiFetch('/api/v1/health');\napiFetch('/api/v1/debug/health-full');"
        calls = extract_frontend_calls(html)
        paths = {c.path for c in calls}
        assert "/api/v1/health" in paths
        assert "/api/v1/debug/health-full" in paths


# ── find_match ─────────────────────────────────────────────────────────────────

class TestFindMatch:
    def test_exact_match(self):
        from app.tools.dashboard_route_audit import FrontendCall
        fc = FrontendCall("GET", "/api/v1/health", "/api/v1/health", 1)
        backend = _be(("GET", "/api/v1/health"))
        assert find_match(fc, backend) is not None

    def test_no_match(self):
        from app.tools.dashboard_route_audit import FrontendCall
        fc = FrontendCall("GET", "/api/v1/nonexistent", "/api/v1/nonexistent", 1)
        backend = _be(("GET", "/api/v1/health"))
        assert find_match(fc, backend) is None

    def test_dynamic_match(self):
        from app.tools.dashboard_route_audit import FrontendCall
        fc = FrontendCall("GET", "/api/v1/tracking/{param}/timeline",
                          "/api/v1/tracking/${batchId}/timeline", 10)
        backend = _be(("GET", "/api/v1/tracking/shipment/{batch_id}/timeline"),
                      ("GET", "/api/v1/tracking/{tracking_no}"))
        # {param}/timeline should match tracking/{tracking_no} — no, different segment count
        # Doesn't match tracking/shipment/... either (param vs shipment literal)
        assert find_match(fc, backend) is None  # correct: 3-seg vs 3-seg but "shipment" ≠ {param}? wait…
        # Actually /api/v1/tracking/{param}/timeline has segs: api,v1,tracking,{param},timeline
        # /api/v1/tracking/shipment/{batch_id}/timeline has segs: api,v1,tracking,shipment,{batch_id},timeline
        # count differs (5 vs 6) → no match. Correct stale detection.

    def test_method_mismatch_still_matches_path(self):
        from app.tools.dashboard_route_audit import FrontendCall
        fc = FrontendCall("GET", "/api/v1/upload/shipment", "/api/v1/upload/shipment", 5)
        backend = _be(("POST", "/api/v1/upload/shipment"))
        # Path matches; method differs but route exists
        assert find_match(fc, backend) is not None


# ── audit (integration of extract + match) ────────────────────────────────────

class TestAudit:
    def test_valid_static_route_is_ok(self):
        html = "apiFetch('/api/v1/health')"
        backend = _be(("GET", "/api/v1/health"))
        result = audit(html, backend)
        assert len(result.ok) == 1
        assert len(result.stale) == 0

    def test_missing_route_is_stale(self):
        html = "apiFetch('/api/v1/nonexistent')"
        backend = _be(("GET", "/api/v1/health"))
        result = audit(html, backend)
        assert len(result.stale) == 1
        assert result.stale[0].path == "/api/v1/nonexistent"

    def test_dynamic_template_route_resolves(self):
        html = "apiFetch(`/dashboard/batches/${encodeURIComponent(batchId)}`)"
        backend = _be(("GET", "/dashboard/batches/{batch_id}"))
        result = audit(html, backend)
        assert len(result.ok) == 1
        assert len(result.stale) == 0

    def test_post_method_detected_and_matched(self):
        html = "apiFetch(`/api/v1/upload/shipment/${encodeURIComponent(batchId)}/process`, { method: 'POST' })"
        backend = _be(("POST", "/api/v1/upload/shipment/{batch_id}/process"))
        result = audit(html, backend)
        assert len(result.ok) == 1
        assert result.ok[0][0].method == "POST"

    def test_external_url_ignored(self):
        html = "fetch('https://external.com/api/data')"
        backend = _be(("GET", "/api/v1/health"))
        result = audit(html, backend)
        assert len(result.ok) == 0
        assert len(result.stale) == 0

    def test_duplicate_calls_reported(self):
        # Two identical calls on separate lines — dedup sees 2 occurrences
        line1 = "apiFetch(`/api/v1/upload/shipment/${batchId}/wfirma/clipboard`, { method: 'POST' });"
        line2 = "apiFetch(`/api/v1/upload/shipment/${batchId}/wfirma/clipboard`, { method: 'POST' });"
        html = line1 + "\n" + line2
        backend = _be(("POST", "/api/v1/upload/shipment/{batch_id}/wfirma/clipboard"))
        result = audit(html, backend)
        assert len(result.duplicates) == 1
        method, path, count = result.duplicates[0]
        assert method == "POST"
        assert count == 2

    def test_stale_execute_endpoint(self):
        html = "apiFetch('/api/v1/execute/wfirma_create', { method: 'POST' })"
        backend = _be(("GET", "/api/v1/health"))   # /execute/* not mounted
        result = audit(html, backend)
        assert len(result.stale) == 1

    def test_mixed_ok_and_stale(self):
        html = "apiFetch('/api/v1/health');\n" \
               "apiFetch('/api/v1/ghost/endpoint');"
        backend = _be(("GET", "/api/v1/health"))
        result = audit(html, backend)
        ok_paths  = {fc.path for fc, _ in result.ok}
        bad_paths = {fc.path for fc in result.stale}
        assert "/api/v1/health" in ok_paths
        assert "/api/v1/ghost/endpoint" in bad_paths

    def test_deduplication_counts_once_in_ok(self):
        # Three identical calls — counted 3× in duplicates, but only 1 ok entry
        html = "apiFetch('/api/v1/health');\n" \
               "apiFetch('/api/v1/health');\n" \
               "apiFetch('/api/v1/health');"
        backend = _be(("GET", "/api/v1/health"))
        result = audit(html, backend)
        assert len(result.ok) == 1     # deduplicated
        assert result.duplicates[0][2] == 3

    def test_href_stale_download_route(self):
        html = '<a href="/api/v1/tracking/events/export/download">Download</a>'
        backend = _be(("GET", "/api/v1/health"))   # download route missing
        result = audit(html, backend)
        assert any(fc.path == "/api/v1/tracking/events/export/download"
                   for fc in result.stale)


# ── Normaliser: query-string template variables ────────────────────────────────

class TestNormaliseQueryStringVars:
    """
    ${qs} / ${params} appended directly to a path segment (no preceding /)
    are query-string fragments, not path segments.  They must be stripped,
    not converted to {param}.
    """

    def test_qs_var_at_segment_end_stripped(self):
        # /api/v1/wfirma/customers${qs}  →  /api/v1/wfirma/customers
        html = "apiFetch(`/api/v1/wfirma/customers${qs}`)"
        calls = extract_frontend_calls(html)
        assert len(calls) == 1
        assert calls[0].path == "/api/v1/wfirma/customers"

    def test_qs_var_does_not_create_fake_path_param(self):
        # Must NOT end with {param} — that would match wrong backend routes
        html = "apiFetch(`/api/v1/wfirma/products${qs}`)"
        calls = extract_frontend_calls(html)
        assert len(calls) == 1
        assert not calls[0].path.endswith("{param}")
        assert calls[0].path == "/api/v1/wfirma/products"

    def test_path_segment_var_still_becomes_param(self):
        # ${…} after "/" is a real path segment → must still become {param}
        html = "apiFetch(`/api/v1/wfirma/customers/${encodeURIComponent(name)}`, { method: 'PUT' })"
        calls = extract_frontend_calls(html)
        assert len(calls) == 1
        assert calls[0].path == "/api/v1/wfirma/customers/{param}"
        assert calls[0].method == "PUT"

    def test_mid_path_segment_var_becomes_param(self):
        html = "apiFetch(`/api/v1/tracking/${encodeURIComponent(batchId)}/timeline`)"
        calls = extract_frontend_calls(html)
        assert calls[0].path == "/api/v1/tracking/{param}/timeline"

    def test_qs_var_matches_correct_get_route_no_mismatch(self):
        # GET /customers (no {param}) must match the GET list route, not the PUT upsert route
        html = "apiFetch(`/api/v1/wfirma/customers${qs}`)"
        backend = _be(
            ("GET", "/api/v1/wfirma/customers"),
            (["PUT"], "/api/v1/wfirma/customers/{client_name}"),
        )
        result = audit(html, backend)
        assert len(result.stale) == 0
        assert len(result.ok) == 1
        matched_be = result.ok[0][1]
        # Must have matched the GET route, not the PUT one
        assert "GET" in matched_be.methods

    def test_href_get_matches_get_route_without_mismatch(self):
        # href always emits GET; if the backend is also GET, no method mismatch
        html = '<a href="/api/v1/tracking/events/export/download">Download</a>'
        backend = _be(("GET", "/api/v1/tracking/events/export/download"))
        result = audit(html, backend)
        assert len(result.stale) == 0
        assert len(result.ok) == 1
        fe, be = result.ok[0]
        assert fe.method == "GET"
        assert "GET" in be.methods   # no mismatch

    def test_post_apifetch_method_still_detected(self):
        # Confirm that explicit POST in apiFetch is not disturbed by normaliser changes
        html = "apiFetch(`/api/v1/wfirma/customers/${encodeURIComponent(n)}`, { method: 'PUT' })"
        calls = extract_frontend_calls(html)
        assert calls[0].method == "PUT"
        assert calls[0].path == "/api/v1/wfirma/customers/{param}"
