"""
test_proforma_search_ui.py — M6 Prior Proforma Search: V2 UI tests.

PR 3 of 3: Source-grep tests verifying the search UI component,
transport function, script tag, navigation entry, data-testid
attributes, and read-only enforcement.

Sprint: M6 Prior Proforma Search (PR 3 — V2 UI)
Target: proforma-search.jsx, pz-api.js, index.html
"""
from __future__ import annotations

import pathlib

SERVICE_DIR = pathlib.Path(__file__).resolve().parent.parent
STATIC_V2 = SERVICE_DIR / "app" / "static" / "v2"
SEARCH_JSX = STATIC_V2 / "proforma-search.jsx"
PZ_API_JS = STATIC_V2 / "pz-api.js"
INDEX_HTML = STATIC_V2 / "index.html"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# =============================================================================
# 1. proforma-search.jsx exists and exports ProformaSearchPage
# =============================================================================


class TestComponentExists:
    """ProformaSearchPage component must exist."""

    def test_file_exists(self):
        assert SEARCH_JSX.exists(), "proforma-search.jsx must exist"

    def test_exports_component(self):
        src = _read(SEARCH_JSX)
        assert "window.ProformaSearchPage" in src, \
            "Must export ProformaSearchPage to window"

    def test_function_defined(self):
        src = _read(SEARCH_JSX)
        assert "function ProformaSearchPage(" in src


# =============================================================================
# 2. PzApi.searchProformaDrafts transport function exists
# =============================================================================


class TestTransportFunction:
    """PzApi must expose searchProformaDrafts."""

    def test_search_function_exists(self):
        src = _read(PZ_API_JS)
        assert "searchProformaDrafts" in src

    def test_calls_search_endpoint(self):
        src = _read(PZ_API_JS)
        assert "/proforma/search" in src

    def test_uses_get_method(self):
        """Must use _get (not _post, _postM, _put, _del)."""
        src = _read(PZ_API_JS)
        idx = src.find("searchProformaDrafts")
        assert idx > 0
        region = src[idx:idx + 300]
        assert "_get(" in region, "Must use _get (GET method)"
        assert "_post(" not in region
        assert "_postM(" not in region

    def test_builds_query_string(self):
        src = _read(PZ_API_JS)
        idx = src.find("searchProformaDrafts")
        region = src[idx:idx + 300]
        assert "URLSearchParams" in region, "Must build query string from params"


# =============================================================================
# 3. index.html includes the script tag
# =============================================================================


class TestScriptTag:
    """index.html must load proforma-search.jsx."""

    def test_script_tag_present(self):
        src = _read(INDEX_HTML)
        assert 'proforma-search.jsx' in src

    def test_loads_before_inline_jsx(self):
        """proforma-search.jsx must be loaded before proforma-list.jsx."""
        src = _read(INDEX_HTML)
        search_idx = src.find('proforma-search.jsx')
        list_idx = src.find('proforma-list.jsx')
        assert search_idx > 0
        assert list_idx > 0
        assert search_idx < list_idx, \
            "proforma-search.jsx must load before proforma-list.jsx"


# =============================================================================
# 4. Navigation entry point exists
# =============================================================================


class TestNavigation:
    """A navigation path to the search page must exist."""

    def test_page_route_exists(self):
        src = _read(INDEX_HTML)
        assert "proforma_search" in src, "proforma_search page route must exist"

    def test_search_page_renders(self):
        src = _read(INDEX_HTML)
        assert "ProformaSearchPage" in src, \
            "ProformaSearchPage component must be rendered in index.html"

    def test_search_all_drafts_button(self):
        """ProformaListPage or index.html must have a nav entry to search."""
        src = _read(INDEX_HTML)
        assert "Search All Drafts" in src or "proforma_search" in src


# =============================================================================
# 5. All 8 search filter inputs exist with data-testid
# =============================================================================


class TestSearchFilters:
    """All 8 approved search filter inputs must have data-testid."""

    def test_client_name_filter(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid="search-filter-client-name"' in src

    def test_batch_id_filter(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid="search-filter-batch-id"' in src

    def test_fullnumber_filter(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid="search-filter-fullnumber"' in src

    def test_wfirma_id_filter(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid="search-filter-wfirma-id"' in src

    def test_draft_state_filter(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid="search-filter-draft-state"' in src

    def test_currency_filter(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid="search-filter-currency"' in src

    def test_date_from_filter(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid="search-filter-date-from"' in src

    def test_date_to_filter(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid="search-filter-date-to"' in src


# =============================================================================
# 6. No amount-range filter
# =============================================================================


class TestNoAmountFilter:
    """Amount-range search is deferred — must not exist in UI."""

    def test_no_amount_input(self):
        src = _read(SEARCH_JSX)
        assert 'filter-amount' not in src.lower()

    def test_no_total_input(self):
        src = _read(SEARCH_JSX)
        assert 'filter-total' not in src.lower()


# =============================================================================
# 7. Results table columns exist
# =============================================================================


class TestResultsTable:
    """Results table must show the required columns."""

    def test_client_column(self):
        src = _read(SEARCH_JSX)
        assert "r.client_name" in src

    def test_batch_id_column(self):
        src = _read(SEARCH_JSX)
        assert "r.batch_id" in src

    def test_draft_state_column(self):
        src = _read(SEARCH_JSX)
        assert "r.draft_state" in src

    def test_currency_column(self):
        src = _read(SEARCH_JSX)
        assert "r.currency" in src

    def test_wfirma_proforma_id_column(self):
        src = _read(SEARCH_JSX)
        assert "r.wfirma_proforma_id" in src

    def test_wfirma_fullnumber_column(self):
        src = _read(SEARCH_JSX)
        assert "r.wfirma_proforma_fullnumber" in src

    def test_created_at_column(self):
        src = _read(SEARCH_JSX)
        assert "r.created_at" in src

    def test_updated_at_column(self):
        src = _read(SEARCH_JSX)
        assert "r.updated_at" in src


# =============================================================================
# 8. UI states exist (empty, loading, error, initial)
# =============================================================================


class TestUIStates:
    """Must include empty, loading, error, and initial states."""

    def test_loading_state(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid="proforma-search-loading"' in src

    def test_error_state(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid="proforma-search-error"' in src

    def test_empty_state(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid="proforma-search-empty"' in src

    def test_initial_state(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid="proforma-search-initial"' in src


# =============================================================================
# 9. Pagination controls exist
# =============================================================================


class TestPagination:
    """Pagination controls must exist with data-testid."""

    def test_pagination_container(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid="proforma-search-pagination"' in src

    def test_prev_button(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid="proforma-search-prev"' in src

    def test_next_button(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid="proforma-search-next"' in src


# =============================================================================
# 10. Read-only enforcement — no write operations in component
# =============================================================================


class TestReadOnly:
    """Search component must not contain any write operations."""

    def test_no_post_calls(self):
        src = _read(SEARCH_JSX)
        assert "_postM(" not in src
        assert "_post(" not in src
        assert 'method: "POST"' not in src

    def test_no_put_calls(self):
        src = _read(SEARCH_JSX)
        assert "_put(" not in src
        assert 'method: "PUT"' not in src

    def test_no_delete_calls(self):
        src = _read(SEARCH_JSX)
        assert "_del(" not in src
        assert 'method: "DELETE"' not in src

    def test_no_patch_calls(self):
        src = _read(SEARCH_JSX)
        assert "_patch(" not in src
        assert 'method: "PATCH"' not in src

    def test_no_wfirma_calls(self):
        src = _read(SEARCH_JSX)
        assert "wfirma" not in src.lower() or "wfirma_proforma" in src.lower()
        # wfirma_proforma_id / wfirma_proforma_fullnumber are display-only fields, OK

    def test_no_email_calls(self):
        src = _read(SEARCH_JSX)
        assert "sendEmail" not in src
        assert "queue_email" not in src
        assert "email_service" not in src


# =============================================================================
# 11. Authority notice label present
# =============================================================================


class TestAuthorityNotice:
    """The required read-only authority notice must be displayed."""

    def test_notice_text(self):
        src = _read(SEARCH_JSX)
        assert "Read-only search across local proforma drafts" in src

    def test_notice_wfirma_disclaimer(self):
        src = _read(SEARCH_JSX)
        assert "Does not query wFirma" in src

    def test_notice_no_mutate_disclaimer(self):
        src = _read(SEARCH_JSX)
        assert "does not mutate accounting records" in src

    def test_notice_testid(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid="proforma-search-authority-notice"' in src


# =============================================================================
# 12. Row click navigates to proforma list
# =============================================================================


class TestRowClick:
    """Clicking a result row should navigate to proforma list for that batch."""

    def test_row_has_onclick(self):
        src = _read(SEARCH_JSX)
        assert "handleRowClick" in src

    def test_row_uses_batch_id(self):
        src = _read(SEARCH_JSX)
        idx = src.find("handleRowClick")
        assert idx > 0
        body = src[idx:idx + 300]
        assert "batch_id" in body

    def test_row_has_testid(self):
        src = _read(SEARCH_JSX)
        assert 'data-testid={`proforma-search-row-' in src


# =============================================================================
# 13. Component calls PzApi.searchProformaDrafts
# =============================================================================


class TestComponentCallsApi:
    """ProformaSearchPage must call PzApi.searchProformaDrafts."""

    def test_calls_search_api(self):
        src = _read(SEARCH_JSX)
        assert "PzApi.searchProformaDrafts" in src

    def test_no_direct_fetch(self):
        """Must go through PzApi, not raw fetch."""
        src = _read(SEARCH_JSX)
        assert "fetch(" not in src
        assert "apiFetch(" not in src


# =============================================================================
# 14. No V1 file changes
# =============================================================================


class TestNoV1Changes:
    """V1 files must not be imported or modified by the search component."""

    def test_no_dashboard_html_reference(self):
        src = _read(SEARCH_JSX)
        assert "dashboard.html" not in src

    def test_no_shipment_detail_reference(self):
        src = _read(SEARCH_JSX)
        assert "shipment-detail.html" not in src


# =============================================================================
# 15. ProformaStatusChip exported from proforma-list.jsx
# =============================================================================


PROFORMA_LIST_JSX = STATIC_V2 / "proforma-list.jsx"


class TestStatusChipExported:
    """ProformaStatusChip must be exported to window from proforma-list.jsx."""

    def test_chip_exported_to_window(self):
        src = _read(PROFORMA_LIST_JSX)
        assert "ProformaStatusChip" in src
        # Must be exported via Object.assign(window, ...) or window.ProformaStatusChip
        assert ("ProformaStatusChip" in src.split("Object.assign(window")[-1]
                or "window.ProformaStatusChip" in src), \
            "ProformaStatusChip must be exported to window"

    def test_search_page_uses_chip(self):
        src = _read(SEARCH_JSX)
        assert "ProformaStatusChip" in src
