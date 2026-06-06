"""Sprint 37 — wFirma Mapping page wiring regression tests.

Source-grep tests verifying that WfirmaMappingPage uses live API calls
instead of hardcoded mock data.

Sprint: 37 — wFirma Mapping (MOCK -> authority-backed)
Target:  ops-cell.jsx -> WfirmaMappingPage
"""

import pathlib
import re

import pytest

# ── File paths ──────────────────────────────────────────────────────────

V2_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "v2"
OPS_CELL = V2_DIR / "ops-cell.jsx"
PZ_API = V2_DIR / "pz-api.js"
MOCK_BADGE = V2_DIR / "mock-badge.jsx"


# ── Helper ──────────────────────────────────────────────────────────────

def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_wfirma_page() -> str:
    """Extract just the WfirmaMappingPage function from ops-cell.jsx."""
    src = _read(OPS_CELL)
    start = src.index("function WfirmaMappingPage")
    # Find the next top-level function declaration after WfirmaMappingPage
    rest = src[start + 30:]
    # CapPill is the next function after WfirmaMappingPage
    end_marker = rest.find("\nfunction CapPill")
    if end_marker < 0:
        end_marker = rest.find("\nfunction ")
    if end_marker > 0:
        return src[start:start + 30 + end_marker]
    return src[start:]


# ── Source existence ────────────────────────────────────────────────────

class TestFileExistence:
    def test_ops_cell_exists(self):
        assert OPS_CELL.exists(), f"ops-cell.jsx not found at {OPS_CELL}"

    def test_pz_api_exists(self):
        assert PZ_API.exists(), f"pz-api.js not found at {PZ_API}"

    def test_mock_badge_exists(self):
        assert MOCK_BADGE.exists(), f"mock-badge.jsx not found at {MOCK_BADGE}"


# ── No hardcoded mock data ─────────────────────────────────────────────

class TestNoHardcodedMockData:
    """WfirmaMappingPage must NOT contain hardcoded customer/product arrays."""

    def test_no_hardcoded_customer_array(self):
        src = _read(OPS_CELL)
        # Match patterns like: const customers = [ { name: 'Bijoux ...
        # but NOT: const [customers, setCustomers] = React.useState
        assert not re.search(
            r"const\s+customers\s*=\s*\[", src
        ), "Hardcoded customers array found in ops-cell.jsx"

    def test_no_hardcoded_product_array(self):
        src = _read(OPS_CELL)
        assert not re.search(
            r"const\s+products\s*=\s*\[", src
        ), "Hardcoded products array found in ops-cell.jsx"

    def test_no_bijoux_maison_in_wfirma_page(self):
        src = _read_wfirma_page()
        assert "Bijoux Maison" not in src, "Mock customer name 'Bijoux Maison' in WfirmaMappingPage"

    def test_no_goldhaus_berlin_in_wfirma_page(self):
        src = _read_wfirma_page()
        assert "Goldhaus Berlin" not in src, "Mock customer name 'Goldhaus Berlin' in WfirmaMappingPage"

    def test_no_mock_product_codes_in_wfirma_page(self):
        src = _read_wfirma_page()
        assert "WF-PROD-99" not in src, "Mock wFirma product IDs (WF-PROD-99xx) in WfirmaMappingPage"

    def test_no_mock_customer_ids_in_wfirma_page(self):
        src = _read_wfirma_page()
        assert "WF-CUST-1" not in src, "Mock wFirma customer IDs (WF-CUST-1xx) in WfirmaMappingPage"


# ── Live API wiring ────────────────────────────────────────────────────

class TestLiveApiWiring:
    """WfirmaMappingPage must call real PzApi endpoints."""

    def test_calls_get_wfirma_capabilities(self):
        src = _read(OPS_CELL)
        assert "PzApi.getWfirmaCapabilities" in src, \
            "WfirmaMappingPage does not call PzApi.getWfirmaCapabilities"

    def test_calls_get_wfirma_customers(self):
        src = _read(OPS_CELL)
        assert "PzApi.getWfirmaCustomers" in src, \
            "WfirmaMappingPage does not call PzApi.getWfirmaCustomers"

    def test_calls_get_wfirma_products(self):
        src = _read(OPS_CELL)
        assert "PzApi.getWfirmaProducts" in src, \
            "WfirmaMappingPage does not call PzApi.getWfirmaProducts"

    def test_uses_react_use_effect(self):
        src = _read(OPS_CELL)
        # Should have useEffect for data loading
        assert "React.useEffect" in src, \
            "WfirmaMappingPage should use React.useEffect for API calls"

    def test_uses_react_use_state(self):
        src = _read(OPS_CELL)
        assert "React.useState" in src, \
            "WfirmaMappingPage should use React.useState for state management"


# ── pz-api.js transport functions ──────────────────────────────────────

class TestPzApiTransportFunctions:
    """pz-api.js must expose the wFirma mapping transport functions."""

    def test_get_wfirma_capabilities_in_pz_api(self):
        src = _read(PZ_API)
        assert "getWfirmaCapabilities" in src, \
            "pz-api.js missing getWfirmaCapabilities function"

    def test_get_wfirma_customers_in_pz_api(self):
        src = _read(PZ_API)
        assert "getWfirmaCustomers" in src, \
            "pz-api.js missing getWfirmaCustomers function"

    def test_get_wfirma_products_in_pz_api(self):
        src = _read(PZ_API)
        assert "getWfirmaProducts" in src, \
            "pz-api.js missing getWfirmaProducts function"

    def test_search_wfirma_contractors_in_pz_api(self):
        src = _read(PZ_API)
        assert "searchWfirmaContractors" in src, \
            "pz-api.js missing searchWfirmaContractors function"

    def test_search_wfirma_goods_in_pz_api(self):
        src = _read(PZ_API)
        assert "searchWfirmaGoods" in src, \
            "pz-api.js missing searchWfirmaGoods function"

    def test_capabilities_endpoint_path(self):
        src = _read(PZ_API)
        assert "/wfirma/capabilities" in src, \
            "pz-api.js missing /wfirma/capabilities endpoint path"

    def test_customers_endpoint_path(self):
        src = _read(PZ_API)
        assert "/wfirma/customers" in src, \
            "pz-api.js missing /wfirma/customers endpoint path"

    def test_products_endpoint_path(self):
        src = _read(PZ_API)
        assert "/wfirma/products" in src, \
            "pz-api.js missing /wfirma/products endpoint path"


# ── WIRED_PAGES includes wfirma_setup ──────────────────────────────────

class TestWiredPages:
    """mock-badge.jsx WIRED_PAGES must include wfirma_setup."""

    def test_wfirma_setup_in_wired_pages(self):
        src = _read(MOCK_BADGE)
        assert "'wfirma_setup'" in src, \
            "mock-badge.jsx WIRED_PAGES does not include 'wfirma_setup'"

    def test_wired_pages_has_10_entries(self):
        src = _read(MOCK_BADGE)
        match = re.search(r"WIRED_PAGES\s*=\s*\[([^\]]+)\]", src)
        assert match, "Could not find WIRED_PAGES array"
        entries = [e.strip().strip("'\"") for e in match.group(1).split(",") if e.strip()]
        assert len(entries) >= 10, \
            f"WIRED_PAGES should have at least 10 entries, found {len(entries)}: {entries}"


# ── Authority-honest UI: disabled write buttons ────────────────────────

class TestAuthorityHonestUI:
    """Write buttons must be disabled with reason, not auto-save."""

    def test_no_auto_save_in_wfirma_page(self):
        src = _read(OPS_CELL)
        # The WfirmaMappingPage should NOT contain auto-save patterns
        # (checking within the function scope is enough — search for autoSave, auto_save)
        wfirma_section = src[src.index("function WfirmaMappingPage"):]
        next_fn = wfirma_section.find("\nfunction ", 10)
        if next_fn > 0:
            wfirma_section = wfirma_section[:next_fn]
        assert "autoSave" not in wfirma_section.lower(), \
            "WfirmaMappingPage should not contain autoSave logic"

    def test_data_testid_present(self):
        src = _read(OPS_CELL)
        assert 'data-testid="wfirma-mapping-page"' in src, \
            "WfirmaMappingPage missing data-testid for test/browser verification"

    def test_customers_table_testid(self):
        src = _read(OPS_CELL)
        assert 'data-testid="wfirma-customers-table"' in src, \
            "Customers table missing data-testid"

    def test_products_table_testid(self):
        src = _read(OPS_CELL)
        assert 'data-testid="wfirma-products-table"' in src, \
            "Products table missing data-testid"

    def test_filter_input_testid(self):
        src = _read(OPS_CELL)
        assert 'data-testid="wfirma-filter"' in src, \
            "Filter input missing data-testid"


# ── No forbidden endpoints consumed ───────────────────────────────────

class TestNoForbiddenEndpoints:
    """WfirmaMappingPage must NOT consume write-heavy forbidden endpoints."""

    def test_no_auto_register_endpoint(self):
        src = _read(OPS_CELL)
        assert "auto-register" not in src, \
            "WfirmaMappingPage must not reference auto-register endpoint"

    def test_no_create_from_product_code(self):
        src = _read(OPS_CELL)
        assert "create-from-product-code" not in src, \
            "WfirmaMappingPage must not reference create-from-product-code endpoint"

    def test_no_auto_create_from_name(self):
        src = _read(OPS_CELL)
        assert "auto-create-from-name" not in src, \
            "WfirmaMappingPage must not reference auto-create-from-name endpoint"


# ── Empty state rendering ─────────────────────────────────────────────

class TestEmptyStateRendering:
    """Page must handle zero results gracefully."""

    def test_empty_customers_message(self):
        src = _read(OPS_CELL)
        assert "No customer mappings registered" in src, \
            "Missing empty-state message for zero customers"

    def test_empty_products_message(self):
        src = _read(OPS_CELL)
        assert "No product mappings registered" in src, \
            "Missing empty-state message for zero products"

    def test_loading_state(self):
        src = _read(OPS_CELL)
        assert "Loading wFirma mapping data" in src, \
            "Missing loading state indicator"
