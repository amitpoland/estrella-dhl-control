"""
test_proforma_search_endpoint.py — M6 Prior Proforma Search: API endpoint tests.

PR 2 of 3: Verifies GET /api/v1/proforma/search endpoint contract,
filter passthrough, read-only enforcement, and response shape.

Authority: proforma_drafts table via search_drafts() from PR 1.
The endpoint is a thin read-only passthrough — no business logic,
no wFirma, no invoice ledger, no email, no mutation.

Sprint: M6 Prior Proforma Search (PR 2 — API Endpoint)
Target: routes_proforma.py (search_proforma_drafts endpoint)
"""
from __future__ import annotations

import pathlib

import pytest

SERVICE_DIR = pathlib.Path(__file__).resolve().parent.parent
APP_DIR = SERVICE_DIR / "app"
ROUTES_FILE = APP_DIR / "api" / "routes_proforma.py"


def _read_routes() -> str:
    return ROUTES_FILE.read_text(encoding="utf-8")


# =============================================================================
# 1. Endpoint exists with GET decorator
# =============================================================================


class TestEndpointExists:
    """GET /search endpoint must exist in routes_proforma.py."""

    def test_search_route_decorator(self):
        src = _read_routes()
        assert '@router.get("/search"' in src, \
            "Must have @router.get(\"/search\") decorator"

    def test_function_name(self):
        src = _read_routes()
        assert "def search_proforma_drafts(" in src, \
            "Endpoint function must be named search_proforma_drafts"

    def test_auth_dependency(self):
        """Endpoint must require API key authentication."""
        src = _read_routes()
        # Find the decorator line and check it has _auth
        idx = src.find('@router.get("/search"')
        assert idx > 0
        line = src[idx:idx + 200]
        assert "_auth" in line, "Endpoint must require API key auth"

    def test_returns_json_response(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        assert idx > 0
        region = src[idx:idx + 500]
        assert "JSONResponse" in region, "Must return JSONResponse"


# =============================================================================
# 2. Endpoint path is /search (mounted under /api/v1/proforma)
# =============================================================================


class TestEndpointPath:
    """Route must be /search under the /api/v1/proforma prefix."""

    def test_router_prefix(self):
        src = _read_routes()
        assert 'prefix="/api/v1/proforma"' in src, \
            "Router must have prefix /api/v1/proforma"

    def test_search_path(self):
        """Full path is GET /api/v1/proforma/search."""
        src = _read_routes()
        assert '@router.get("/search"' in src


# =============================================================================
# 3. Endpoint calls search_drafts()
# =============================================================================


class TestCallsSearchDrafts:
    """Endpoint must delegate to pildb.search_drafts()."""

    def test_calls_search_drafts(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        assert idx > 0
        # Get the function body (next 1500 chars covers it)
        body = src[idx:idx + 1500]
        assert "pildb.search_drafts(" in body, \
            "Must call pildb.search_drafts()"

    def test_passes_db_path(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 1500]
        assert "_proforma_db_path()" in body, \
            "Must pass _proforma_db_path() to search_drafts"

    def test_passes_filters(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 1500]
        assert "filters=filters" in body or "filters=" in body, \
            "Must pass filters dict to search_drafts"

    def test_passes_pagination(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 1500]
        assert "page=page" in body, "Must pass page parameter"
        assert "page_size=page_size" in body, "Must pass page_size parameter"


# =============================================================================
# 4. Endpoint returns results, total, page, page_size
# =============================================================================


class TestResponseShape:
    """Response must include results, total, page, page_size keys."""

    def test_returns_results_key(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 2500]
        assert '"results"' in body, "Response must include 'results' key"

    def test_returns_total_key(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 2500]
        assert '"total"' in body, "Response must include 'total' key"

    def test_returns_page_key(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 2500]
        assert '"page"' in body, "Response must include 'page' key"

    def test_returns_page_size_key(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 2500]
        assert '"page_size"' in body, "Response must include 'page_size' key"

    def test_returns_filters_key(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 2500]
        assert '"filters"' in body, "Response must include 'filters' key"

    def test_returns_ok_key(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 2500]
        assert '"ok"' in body, "Response must include 'ok' key"


# =============================================================================
# 5. Endpoint accepts all approved filters
# =============================================================================


class TestApprovedFilters:
    """All 8 approved search filters must be accepted as query params."""

    def test_client_name_param(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        signature = src[idx:idx + 600]
        assert "client_name:" in signature

    def test_batch_id_param(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        signature = src[idx:idx + 600]
        assert "batch_id:" in signature

    def test_wfirma_proforma_id_param(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        signature = src[idx:idx + 600]
        assert "wfirma_proforma_id:" in signature

    def test_wfirma_proforma_fullnumber_param(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        signature = src[idx:idx + 600]
        assert "wfirma_proforma_fullnumber:" in signature

    def test_draft_state_param(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        signature = src[idx:idx + 600]
        assert "draft_state:" in signature

    def test_currency_param(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        signature = src[idx:idx + 600]
        assert "currency:" in signature

    def test_date_from_param(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        signature = src[idx:idx + 600]
        assert "date_from:" in signature

    def test_date_to_param(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        signature = src[idx:idx + 600]
        assert "date_to:" in signature

    def test_page_param(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        signature = src[idx:idx + 600]
        assert "page:" in signature

    def test_page_size_param(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        signature = src[idx:idx + 600]
        assert "page_size:" in signature


# =============================================================================
# 6. Endpoint does NOT call wFirma
# =============================================================================


class TestNoWfirmaCalls:
    """Search endpoint must not call wFirma API or wfirma_client."""

    def test_no_wfirma_client_call(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 1500]
        assert "wfirma_client" not in body, \
            "Must not call wfirma_client"

    def test_no_wfdb_call(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 1500]
        assert "wfdb." not in body, "Must not call wfirma_db"


# =============================================================================
# 7. Endpoint does NOT call invoice ledger
# =============================================================================


class TestNoInvoiceLedger:
    """Search endpoint must not read from invoice ledger."""

    def test_no_invoice_ledger(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 1500]
        assert "invoice_ledger" not in body
        assert "invoice-ledger" not in body

    def test_no_proforma_invoice_links_table_direct(self):
        """Must not query proforma_invoice_links directly."""
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 1500]
        assert "proforma_invoice_links" not in body


# =============================================================================
# 8. Endpoint does NOT call queue_email
# =============================================================================


class TestNoEmail:
    """Search endpoint must not send or queue email."""

    def test_no_queue_email(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 1500]
        assert "queue_email" not in body
        assert "send_email" not in body
        assert "email_service" not in body


# =============================================================================
# 9. Endpoint does NOT mutate drafts
# =============================================================================


class TestNoMutation:
    """Search endpoint must be read-only — no INSERT/UPDATE/DELETE."""

    def test_no_update_draft(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 1500]
        assert "update_draft" not in body
        assert "approve_draft" not in body
        assert "cancel_draft" not in body

    def test_no_post_actions(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 1500]
        assert "start_post" not in body
        assert "mark_post" not in body

    def test_no_create_draft(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 1500]
        assert "auto_create_draft" not in body
        assert "clone_draft" not in body

    def test_no_convert(self):
        """Must not call conversion functions (word in docstring is OK)."""
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 2500]
        assert "convert_to_invoice" not in body
        assert "convert_draft" not in body
        assert "do_convert" not in body

    def test_is_get_method(self):
        """Must be GET, not POST/PUT/PATCH/DELETE."""
        src = _read_routes()
        # Find the decorator immediately before the function
        idx = src.find("def search_proforma_drafts(")
        region = src[max(0, idx - 200):idx]
        assert "@router.get(" in region, "Must be a GET endpoint"
        assert "@router.post(" not in region
        assert "@router.put(" not in region
        assert "@router.patch(" not in region
        assert "@router.delete(" not in region


# =============================================================================
# 10. Endpoint does NOT implement amount-range search
# =============================================================================


class TestNoAmountRangeSearch:
    """Amount-range search is deferred to Sprint 2."""

    def test_no_amount_filter(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        signature = src[idx:idx + 600]
        assert "amount" not in signature.lower(), \
            "Amount-range search is deferred to Sprint 2"

    def test_no_total_filter(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        signature = src[idx:idx + 600]
        # 'total' appears as response key but NOT as a filter param
        params_section = signature.split(") -> ")[0] if ") -> " in signature else signature
        # Check that total is not a query parameter name
        assert "total:" not in params_section or "total: " not in params_section

    def test_no_editable_lines_parsing(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 1500]
        assert "editable_lines_json" not in body, \
            "Must not parse editable_lines_json for amount filtering"

    def test_no_source_lines_parsing(self):
        src = _read_routes()
        idx = src.find("def search_proforma_drafts(")
        body = src[idx:idx + 1500]
        assert "source_lines_json" not in body, \
            "Must not parse source_lines_json for amount filtering"


# =============================================================================
# 11. Search result shape includes required fields
# =============================================================================


class TestSearchResultShape:
    """Each search result must include the required display fields."""

    def test_result_has_id(self):
        src = _read_routes()
        idx = src.find("def _draft_to_search_result(")
        assert idx > 0, "_draft_to_search_result helper must exist"
        body = src[idx:idx + 900]
        assert '"id"' in body

    def test_result_has_batch_id(self):
        src = _read_routes()
        idx = src.find("def _draft_to_search_result(")
        body = src[idx:idx + 900]
        assert '"batch_id"' in body

    def test_result_has_client_name(self):
        src = _read_routes()
        idx = src.find("def _draft_to_search_result(")
        body = src[idx:idx + 900]
        assert '"client_name"' in body

    def test_result_has_draft_state(self):
        src = _read_routes()
        idx = src.find("def _draft_to_search_result(")
        body = src[idx:idx + 900]
        assert '"draft_state"' in body

    def test_result_has_status(self):
        src = _read_routes()
        idx = src.find("def _draft_to_search_result(")
        body = src[idx:idx + 900]
        assert '"status"' in body

    def test_result_has_currency(self):
        src = _read_routes()
        idx = src.find("def _draft_to_search_result(")
        body = src[idx:idx + 900]
        assert '"currency"' in body

    def test_result_has_wfirma_proforma_id(self):
        src = _read_routes()
        idx = src.find("def _draft_to_search_result(")
        body = src[idx:idx + 900]
        assert '"wfirma_proforma_id"' in body

    def test_result_has_wfirma_proforma_fullnumber(self):
        src = _read_routes()
        idx = src.find("def _draft_to_search_result(")
        body = src[idx:idx + 900]
        assert '"wfirma_proforma_fullnumber"' in body

    def test_result_has_created_at(self):
        src = _read_routes()
        idx = src.find("def _draft_to_search_result(")
        body = src[idx:idx + 900]
        assert '"created_at"' in body

    def test_result_has_updated_at(self):
        src = _read_routes()
        idx = src.find("def _draft_to_search_result(")
        body = src[idx:idx + 900]
        assert '"updated_at"' in body

    def test_result_does_not_include_json_blobs(self):
        """Search results must be compact — no JSON blob fields."""
        src = _read_routes()
        idx = src.find("def _draft_to_search_result(")
        body = src[idx:idx + 900]
        assert "editable_lines_json" not in body
        assert "source_lines_json" not in body
        assert "buyer_override_json" not in body
        assert "service_charges_json" not in body
