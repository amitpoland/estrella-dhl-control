"""Sprint 43 -- Coverage Map Authority-Honest Conversion regression tests.

Source-grep tests verifying that:
1. All 46 hardcoded COVERAGE_ROWS removed
2. No fake status categories (active/partial/backend/future as coverage status)
3. No fake "Wireframe rules in effect" footer
4. Live OpenAPI fetch wired (getOpenApiSpec)
5. _parseOpenApiPaths + _deriveModule helpers present
6. Loading/error states
7. data-testid attributes for browser verification
8. 'coverage' in WIRED_PAGES (17 entries = 100%, including proforma_search)
9. pz-api.js has getOpenApiSpec transport
10. CoverageMapPage exported to window
11. Method badge colors use CSS custom properties
12. Filter controls (search, method, module)

Sprint: 43 -- Coverage Map Authority-Honest Conversion
Target: wireframe-update.jsx, pz-api.js, mock-badge.jsx, index.html, components.jsx
"""

import pathlib
import re

import pytest

V2_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "v2"
WIREFRAME = V2_DIR / "wireframe-update.jsx"
PZ_API = V2_DIR / "pz-api.js"
MOCK_BADGE = V2_DIR / "mock-badge.jsx"
INDEX_HTML = V2_DIR / "index.html"
COMPONENTS = V2_DIR / "components.jsx"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# =============================================================================
# 1. Hardcoded COVERAGE_ROWS removed
# =============================================================================

class TestFakeDataRemoved:
    """All 46 hardcoded COVERAGE_ROWS entries must be gone."""

    def test_no_coverage_rows_array(self):
        src = _read(WIREFRAME)
        assert "const COVERAGE_ROWS = [" not in src, \
            "Hardcoded COVERAGE_ROWS array must be removed"

    def test_no_fake_fedex_clearance(self):
        """FedEx clearance was a fake 'future' entry."""
        src = _read(WIREFRAME)
        code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))
        assert "fedex/clearance" not in code, "Fake FedEx clearance route must be removed"

    def test_no_fake_kuke_entry(self):
        src = _read(WIREFRAME)
        code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))
        assert "KUKE" not in code, "Fake KUKE entry must be removed"

    def test_no_fake_reports_entries(self):
        src = _read(WIREFRAME)
        code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))
        assert "reports/financial" not in code
        assert "reports/sales" not in code
        assert "reports/purchase" not in code

    def test_no_single_source_of_truth_note(self):
        """The fake 'Single source of truth' notes column entry must be gone."""
        src = _read(WIREFRAME)
        code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))
        assert "Single source of truth" not in code

    def test_no_wireframe_rules_footer_in_coverage(self):
        """The old wireframe footer must not appear in the CoverageMapPage region."""
        src = _read(WIREFRAME)
        start = src.find("function CoverageMapPage()")
        assert start > 0
        region = src[start:start + 5000]
        assert "Wireframe rules in effect" not in region

    def test_no_source_wfirma_badge(self):
        """Fake 'Source · wFirma' notes must be gone from coverage."""
        src = _read(WIREFRAME)
        # Find the CoverageMapPage region only
        start = src.find("function CoverageMapPage()")
        assert start > 0
        region = src[start:start + 5000]
        assert "Source · wFirma" not in region


# =============================================================================
# 2. No fake status categories in coverage page
# =============================================================================

class TestNoFakeStatusCategories:
    """The old active/partial/backend/future status tiles must be gone."""

    def test_no_status_tiles(self):
        src = _read(WIREFRAME)
        start = src.find("function CoverageMapPage()")
        assert start > 0
        region = src[start:start + 5000]
        assert "Wired & shipping" not in region
        assert "UI live · backend gaps" not in region
        assert "Backend pending" not in region
        assert "Planned · not scoped" not in region

    def test_no_old_coverage_matrix_function(self):
        """Original CoverageMatrix function body must be replaced."""
        src = _read(WIREFRAME)
        # The old function had COVERAGE_ROWS.filter — that pattern must be gone
        assert "COVERAGE_ROWS.filter" not in src


# =============================================================================
# 3. Live OpenAPI fetch
# =============================================================================

class TestLiveOpenApiFetch:
    """CoverageMapPage must fetch from /openapi.json via PzApi."""

    def test_get_openapi_spec_called(self):
        src = _read(WIREFRAME)
        assert "getOpenApiSpec()" in src, "Must call PzApi.getOpenApiSpec()"

    def test_uses_useeffect(self):
        src = _read(WIREFRAME)
        start = src.find("function CoverageMapPage()")
        region = src[start:start + 3000]
        assert "useEffect" in region

    def test_parse_openapi_paths_present(self):
        src = _read(WIREFRAME)
        assert "_parseOpenApiPaths" in src

    def test_derive_module_present(self):
        src = _read(WIREFRAME)
        assert "_deriveModule" in src


# =============================================================================
# 4. Loading and error states
# =============================================================================

class TestLoadingErrorStates:
    def test_loading_state(self):
        src = _read(WIREFRAME)
        assert "coverage-loading" in src
        assert "Loading" in src

    def test_error_state(self):
        src = _read(WIREFRAME)
        assert "coverage-error" in src
        assert "Failed to load" in src

    def test_spec_state_management(self):
        src = _read(WIREFRAME)
        assert "setSpec" in src


# =============================================================================
# 5. data-testid attributes
# =============================================================================

class TestTestIds:
    @pytest.mark.parametrize("testid", [
        "coverage-map-page",
        "coverage-kpi-strip",
        "coverage-filters",
        "coverage-search",
        "coverage-method-filter",
        "coverage-module-filter",
        "coverage-route-table",
    ])
    def test_testid_present(self, testid):
        src = _read(WIREFRAME)
        assert testid in src, f"data-testid '{testid}' not found"


# =============================================================================
# 6. WIRED_PAGES includes 'coverage' + 'proforma_search' + 'detail' (18/18 = 100%)
#    'detail' = the Shipment Detail drill-down (page==='detail'), wired read-only
#    to GET /api/v1/dashboard/batches/{batch_id}. See test_c03_shipment_detail_v2_ux.py.
# =============================================================================

class TestWiredPages:
    def test_coverage_in_wired_pages(self):
        src = _read(MOCK_BADGE)
        assert "'coverage'" in src, "'coverage' not found in WIRED_PAGES"

    def test_wired_pages_count_18(self):
        # B×7-1 (2026-07-02, PROJECT_STATE DECISIONS "slice B×7-1"): 'move_location'
        # (built as 'move_stock', renamed per operator decision (i)) promoted as
        # the 19th wired page — count pin updated 18 -> 19 in the same commit as
        # the promotion, per the DECISIONS entry's pin-update rule.
        src = _read(MOCK_BADGE)
        match = re.search(r"const WIRED_PAGES\s*=\s*\[([^\]]+)\]", src)
        assert match, "WIRED_PAGES array not found"
        entries = [e.strip().strip("'\"") for e in match.group(1).split(",") if e.strip()]
        assert len(entries) == 19, f"Expected 19 WIRED_PAGES entries (100%), found {len(entries)}: {entries}"

    def test_all_18_slugs_present(self):
        """Every V2 page slug must be in WIRED_PAGES."""
        src = _read(MOCK_BADGE)
        for slug in ['proforma', 'proforma_search', 'inbox', 'inventory', 'dhl',
                     'shipments', 'automation', 'intelligence', 'documents',
                     'proforma_detail', 'wfirma_setup', 'master', 'carriers',
                     'dashboard', 'api_status', 'diagnostics', 'coverage', 'detail']:
            assert f"'{slug}'" in src, f"Slug '{slug}' not in WIRED_PAGES"


# =============================================================================
# 7. pz-api.js transport
# =============================================================================

class TestTransport:
    def test_get_openapi_spec_defined(self):
        src = _read(PZ_API)
        assert "getOpenApiSpec" in src

    def test_openapi_json_endpoint(self):
        src = _read(PZ_API)
        assert "/openapi.json" in src


# =============================================================================
# 8. Window export
# =============================================================================

class TestWindowExport:
    def test_coverage_map_page_exported(self):
        src = _read(WIREFRAME)
        assert "CoverageMapPage" in src
        # Must be in window exports
        exports_start = src.find("Object.assign(window,")
        assert exports_start > 0
        exports_region = src[exports_start:exports_start + 300]
        assert "CoverageMapPage" in exports_region

    def test_backward_compat_alias(self):
        """CoverageMatrix alias must exist for index.html backward compat."""
        src = _read(WIREFRAME)
        assert "CoverageMatrix = CoverageMapPage" in src or "CoverageMatrix" in src


# =============================================================================
# 9. Method badge uses CSS custom properties
# =============================================================================

class TestCssCustomProperties:
    def test_method_color_uses_css_vars(self):
        src = _read(WIREFRAME)
        assert "var(--badge-green" in src
        assert "var(--badge-amber" in src
        assert "var(--badge-red" in src

    def test_no_hardcoded_method_colors(self):
        """Method badges must not use hardcoded hex — only CSS vars."""
        src = _read(WIREFRAME)
        start = src.find("function _methodColor(")
        assert start > 0
        region = src[start:start + 500]
        assert "#" not in region, "No hardcoded hex colors in _methodColor"


# =============================================================================
# 10. Filter controls
# =============================================================================

class TestFilterControls:
    def test_method_filter_state(self):
        src = _read(WIREFRAME)
        assert "methodFilter" in src

    def test_module_filter_state(self):
        src = _read(WIREFRAME)
        assert "moduleFilter" in src

    def test_search_input(self):
        src = _read(WIREFRAME)
        start = src.find("function CoverageMapPage()")
        region = src[start:start + 5000]
        assert "placeholder" in region
        assert "Search" in region or "search" in region


# =============================================================================
# 11. index.html updated
# =============================================================================

class TestIndexHtml:
    def test_uses_coverage_map_page(self):
        src = _read(INDEX_HTML)
        assert "CoverageMapPage" in src, "index.html must reference CoverageMapPage"

    def test_authority_subtitle(self):
        src = _read(INDEX_HTML)
        assert "OpenAPI" in src or "openapi" in src, "Subtitle must reference OpenAPI authority"

    def test_no_wireframe_subtitle(self):
        src = _read(INDEX_HTML)
        assert "wireframe coverage" not in src, "Old wireframe subtitle must be gone"


# =============================================================================
# 12. components.jsx nav label
# =============================================================================

class TestNavLabel:
    def test_coverage_map_label(self):
        src = _read(COMPONENTS)
        assert "'Coverage Map'" in src or '"Coverage Map"' in src, \
            "Nav label should say 'Coverage Map' not 'Coverage Matrix'"


# =============================================================================
# 13. Sprint 42 WIRED_PAGES test compat
# =============================================================================

class TestSprint42Compat:
    def test_sprint42_test_file_exists(self):
        p = pathlib.Path(__file__).resolve().parent / "test_sprint42_diagnostics_authority_honest.py"
        assert p.exists(), "Sprint 42 test file must exist"
