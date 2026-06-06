"""Sprint 38 — Master Data page read-authority wiring regression tests.

Source-grep tests verifying that MasterPage uses live PzApi calls
instead of hardcoded SEED data, and that write buttons are disabled
with explicit reasons.

Sprint: 38 — Master Data Read Authority Conversion
Target:  master-page.jsx (MasterPage), pz-api.js (transport), mock-badge.jsx
"""

import pathlib
import re

import pytest

# ── File paths ──────────────────────────────────────────────────────────

V2_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "v2"
MASTER_PAGE = V2_DIR / "master-page.jsx"
PZ_API = V2_DIR / "pz-api.js"
MOCK_BADGE = V2_DIR / "mock-badge.jsx"


# ── Helper ──────────────────────────────────────────────────────────────

def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════
# 1. File existence
# ═══════════════════════════════════════════════════════════════════════

class TestFileExistence:
    def test_master_page_exists(self):
        assert MASTER_PAGE.exists(), f"master-page.jsx not found at {MASTER_PAGE}"

    def test_pz_api_exists(self):
        assert PZ_API.exists(), f"pz-api.js not found at {PZ_API}"

    def test_mock_badge_exists(self):
        assert MOCK_BADGE.exists(), f"mock-badge.jsx not found at {MOCK_BADGE}"


# ═══════════════════════════════════════════════════════════════════════
# 2. No hardcoded SEED data — the core authority assertion
# ═══════════════════════════════════════════════════════════════════════

class TestNoSeedData:
    """MasterPage must NOT contain any hardcoded entity records."""

    def test_no_seed_constant(self):
        src = _read(MASTER_PAGE)
        assert "const SEED" not in src, "Hardcoded SEED constant still present in master-page.jsx"

    def test_no_estrella_jewels_mock(self):
        src = _read(MASTER_PAGE)
        assert "Estrella Jewels Sp." not in src, "Mock client 'Estrella Jewels Sp.' in master-page.jsx"

    def test_no_atelier_bonacchi_mock(self):
        src = _read(MASTER_PAGE)
        assert "Atelier Bonacchi" not in src, "Mock client 'Atelier Bonacchi' in master-page.jsx"

    def test_no_geneva_imports_mock(self):
        src = _read(MASTER_PAGE)
        assert "Geneva Imports" not in src, "Mock client 'Geneva Imports' in master-page.jsx"

    def test_no_bonacchi_atelier_mock(self):
        src = _read(MASTER_PAGE)
        assert "Bonacchi Atelier" not in src, "Mock supplier 'Bonacchi Atelier' in master-page.jsx"

    def test_no_maison_de_vicenza_mock(self):
        src = _read(MASTER_PAGE)
        assert "Maison de Vicenza" not in src, "Mock supplier 'Maison de Vicenza' in master-page.jsx"

    def test_no_antwerp_stones_mock(self):
        src = _read(MASTER_PAGE)
        assert "Antwerp Stones" not in src, "Mock supplier 'Antwerp Stones' in master-page.jsx"

    def test_no_gold_pendant_mock(self):
        src = _read(MASTER_PAGE)
        assert "Gold pendant" not in src, "Mock product 'Gold pendant' in master-page.jsx"

    def test_no_gold_ring_mock(self):
        src = _read(MASTER_PAGE)
        assert "Gold ring" not in src, "Mock product 'Gold ring' in master-page.jsx"

    def test_no_silver_bracelet_mock(self):
        src = _read(MASTER_PAGE)
        assert "Silver bracelet" not in src, "Mock product 'Silver bracelet' in master-page.jsx"

    def test_no_anna_kowalska_mock(self):
        src = _read(MASTER_PAGE)
        assert "Anna Kowalska" not in src, "Mock user 'Anna Kowalska' in master-page.jsx"

    def test_no_tomek_wisniewski_mock(self):
        src = _read(MASTER_PAGE)
        assert "Tomek" not in src, "Mock user 'Tomek' in master-page.jsx"

    def test_no_maria_nowak_mock(self):
        src = _read(MASTER_PAGE)
        assert "Maria Nowak" not in src, "Mock user 'Maria Nowak' in master-page.jsx"

    def test_no_hardcoded_vat_ids(self):
        src = _read(MASTER_PAGE)
        assert "PL5252312345" not in src, "Mock VAT ID in master-page.jsx"

    def test_no_hardcoded_wfirma_ids(self):
        src = _read(MASTER_PAGE)
        assert "WF-2210" not in src, "Mock wFirma ID in master-page.jsx"

    def test_no_wisior_zloty(self):
        src = _read(MASTER_PAGE)
        assert "Wisior" not in src, "Mock Polish product description in master-page.jsx"

    def test_no_mock_rate_values(self):
        src = _read(MASTER_PAGE)
        assert "4.3128" not in src, "Mock FX rate in master-page.jsx"

    def test_no_seed_setdata(self):
        src = _read(MASTER_PAGE)
        assert "setData(SEED)" not in src and "useState(SEED)" not in src, \
            "State initialized from SEED in master-page.jsx"

    def test_no_entity_fields_constant(self):
        """ENTITY_FIELDS was the old mock form schema — must be removed."""
        src = _read(MASTER_PAGE)
        assert "const ENTITY_FIELDS" not in src, \
            "Old ENTITY_FIELDS constant still present in master-page.jsx"


# ═══════════════════════════════════════════════════════════════════════
# 3. Live API wiring — PzApi calls present
# ═══════════════════════════════════════════════════════════════════════

class TestLiveApiWiring:
    """MasterPage must call real PzApi endpoints for each entity."""

    def test_calls_list_customer_master(self):
        src = _read(MASTER_PAGE)
        assert "PzApi.listCustomerMaster" in src, \
            "MasterPage does not call PzApi.listCustomerMaster"

    def test_calls_list_suppliers(self):
        src = _read(MASTER_PAGE)
        assert "PzApi.listSuppliers" in src, \
            "MasterPage does not call PzApi.listSuppliers"

    def test_calls_list_product_local(self):
        src = _read(MASTER_PAGE)
        assert "PzApi.listProductLocal" in src, \
            "MasterPage does not call PzApi.listProductLocal"

    def test_calls_list_designs(self):
        src = _read(MASTER_PAGE)
        assert "PzApi.listDesigns" in src, \
            "MasterPage does not call PzApi.listDesigns"

    def test_calls_list_hs_codes(self):
        src = _read(MASTER_PAGE)
        assert "PzApi.listHsCodes" in src, \
            "MasterPage does not call PzApi.listHsCodes"

    def test_calls_list_fx_rates(self):
        src = _read(MASTER_PAGE)
        assert "PzApi.listFxRates" in src, \
            "MasterPage does not call PzApi.listFxRates"

    def test_calls_list_vat_config(self):
        src = _read(MASTER_PAGE)
        assert "PzApi.listVatConfig" in src, \
            "MasterPage does not call PzApi.listVatConfig"

    def test_calls_list_incoterms(self):
        src = _read(MASTER_PAGE)
        assert "PzApi.listIncoterms" in src, \
            "MasterPage does not call PzApi.listIncoterms"

    def test_calls_list_units(self):
        src = _read(MASTER_PAGE)
        assert "PzApi.listUnits" in src, \
            "MasterPage does not call PzApi.listUnits"

    def test_calls_list_carriers_config(self):
        src = _read(MASTER_PAGE)
        assert "PzApi.listCarriersConfig" in src, \
            "MasterPage does not call PzApi.listCarriersConfig"

    def test_calls_list_users(self):
        src = _read(MASTER_PAGE)
        assert "PzApi.listUsers" in src, \
            "MasterPage does not call PzApi.listUsers"

    def test_uses_react_use_effect(self):
        src = _read(MASTER_PAGE)
        assert "React.useEffect" in src, \
            "MasterPage should use React.useEffect for data loading"

    def test_uses_react_use_state(self):
        src = _read(MASTER_PAGE)
        assert "React.useState" in src, \
            "MasterPage should use React.useState for state management"


# ═══════════════════════════════════════════════════════════════════════
# 4. pz-api.js transport functions
# ═══════════════════════════════════════════════════════════════════════

class TestPzApiTransportFunctions:
    """pz-api.js must expose all master data list functions."""

    def test_list_suppliers_in_pz_api(self):
        src = _read(PZ_API)
        assert "listSuppliers" in src, "pz-api.js missing listSuppliers function"

    def test_list_product_local_in_pz_api(self):
        src = _read(PZ_API)
        assert "listProductLocal" in src, "pz-api.js missing listProductLocal function"

    def test_list_designs_in_pz_api(self):
        src = _read(PZ_API)
        assert "listDesigns" in src, "pz-api.js missing listDesigns function"

    def test_list_hs_codes_in_pz_api(self):
        src = _read(PZ_API)
        assert "listHsCodes" in src, "pz-api.js missing listHsCodes function"

    def test_list_fx_rates_in_pz_api(self):
        src = _read(PZ_API)
        assert "listFxRates" in src, "pz-api.js missing listFxRates function"

    def test_list_vat_config_in_pz_api(self):
        src = _read(PZ_API)
        assert "listVatConfig" in src, "pz-api.js missing listVatConfig function"

    def test_list_incoterms_in_pz_api(self):
        src = _read(PZ_API)
        assert "listIncoterms" in src, "pz-api.js missing listIncoterms function"

    def test_list_units_in_pz_api(self):
        src = _read(PZ_API)
        assert "listUnits" in src, "pz-api.js missing listUnits function"

    def test_list_carriers_config_in_pz_api(self):
        src = _read(PZ_API)
        assert "listCarriersConfig" in src, "pz-api.js missing listCarriersConfig function"

    def test_list_users_in_pz_api(self):
        src = _read(PZ_API)
        assert "listUsers" in src, "pz-api.js missing listUsers function"

    def test_list_customer_master_already_exists(self):
        src = _read(PZ_API)
        assert "listCustomerMaster" in src, "pz-api.js missing listCustomerMaster function"

    # Endpoint paths
    def test_suppliers_endpoint_path(self):
        src = _read(PZ_API)
        assert "/suppliers" in src, "pz-api.js missing /suppliers endpoint path"

    def test_product_local_endpoint_path(self):
        src = _read(PZ_API)
        assert "/product-local" in src, "pz-api.js missing /product-local endpoint path"

    def test_designs_endpoint_path(self):
        src = _read(PZ_API)
        assert "/designs" in src, "pz-api.js missing /designs endpoint path"

    def test_hs_codes_endpoint_path(self):
        src = _read(PZ_API)
        assert "/hs-codes" in src, "pz-api.js missing /hs-codes endpoint path"

    def test_fx_rates_endpoint_path(self):
        src = _read(PZ_API)
        assert "/fx-rates" in src, "pz-api.js missing /fx-rates endpoint path"

    def test_vat_config_endpoint_path(self):
        src = _read(PZ_API)
        assert "/vat-config" in src, "pz-api.js missing /vat-config endpoint path"

    def test_incoterms_endpoint_path(self):
        src = _read(PZ_API)
        assert "/incoterms" in src, "pz-api.js missing /incoterms endpoint path"

    def test_units_endpoint_path(self):
        src = _read(PZ_API)
        assert "/units" in src, "pz-api.js missing /units endpoint path"

    def test_carriers_config_endpoint_path(self):
        src = _read(PZ_API)
        assert "/carriers-config" in src, "pz-api.js missing /carriers-config endpoint path"

    def test_auth_users_endpoint_path(self):
        src = _read(PZ_API)
        assert "/auth/users" in src, "pz-api.js missing /auth/users endpoint path"


# ═══════════════════════════════════════════════════════════════════════
# 5. WIRED_PAGES includes 'master'
# ═══════════════════════════════════════════════════════════════════════

class TestWiredPages:
    """mock-badge.jsx WIRED_PAGES must include 'master'."""

    def test_master_in_wired_pages(self):
        src = _read(MOCK_BADGE)
        assert "'master'" in src, \
            "mock-badge.jsx WIRED_PAGES does not include 'master'"

    def test_wired_pages_has_11_entries(self):
        src = _read(MOCK_BADGE)
        match = re.search(r"WIRED_PAGES\s*=\s*\[([^\]]+)\]", src)
        assert match, "Could not find WIRED_PAGES array"
        entries = [e.strip().strip("'\"") for e in match.group(1).split(",") if e.strip()]
        assert len(entries) >= 11, \
            f"WIRED_PAGES should have at least 11 entries, found {len(entries)}: {entries}"


# ═══════════════════════════════════════════════════════════════════════
# 6. Authority-honest UI: disabled write buttons with reasons
# ═══════════════════════════════════════════════════════════════════════

class TestAuthorityHonestUI:
    """Write buttons must be visible but disabled with explicit reasons."""

    def test_write_disabled_reason_present(self):
        src = _read(MASTER_PAGE)
        assert "Write operations not yet wired" in src, \
            "Missing generic write-disabled reason message"

    def test_roles_disabled_reason_present(self):
        src = _read(MASTER_PAGE)
        assert "No backend endpoint for role management" in src, \
            "Missing roles-specific disabled reason"

    def test_users_write_disabled_reason_present(self):
        src = _read(MASTER_PAGE)
        assert "User write operations require admin endpoints" in src, \
            "Missing users-specific write-disabled reason"

    def test_new_button_disabled(self):
        src = _read(MASTER_PAGE)
        # The + New button should have disabled attribute
        assert 'data-testid="btn-new-record"' in src, \
            "New record button missing data-testid"
        # Check that disabled is unconditionally set
        new_btn_match = re.search(r'data-testid="btn-new-record"', src)
        assert new_btn_match, "btn-new-record testid not found"
        # Find the surrounding Btn and check for disabled
        region = src[max(0, new_btn_match.start() - 200):new_btn_match.end() + 50]
        assert "disabled" in region, "New record button is not disabled"

    def test_export_csv_disabled(self):
        src = _read(MASTER_PAGE)
        assert 'data-testid="btn-export-csv"' in src, \
            "Export CSV button missing data-testid"

    def test_import_csv_disabled(self):
        src = _read(MASTER_PAGE)
        assert 'data-testid="btn-import-csv"' in src, \
            "Import CSV button missing data-testid"

    def test_no_handle_save_local_mutation(self):
        """handleSave was local state mutation — must be removed."""
        src = _read(MASTER_PAGE)
        assert "handleSave" not in src, \
            "Local handleSave mutation still present in master-page.jsx"

    def test_no_handle_delete_local_mutation(self):
        """handleDelete was local state mutation — must be removed."""
        src = _read(MASTER_PAGE)
        assert "handleDelete" not in src, \
            "Local handleDelete mutation still present in master-page.jsx"

    def test_no_creating_state(self):
        """Creating state was for the create modal — must be removed."""
        src = _read(MASTER_PAGE)
        assert "setCreating" not in src, \
            "Create modal state (setCreating) still present in master-page.jsx"

    def test_no_editing_state(self):
        """Editing state was for the edit modal — must be removed."""
        src = _read(MASTER_PAGE)
        assert "setEditing" not in src, \
            "Edit modal state (setEditing) still present in master-page.jsx"

    def test_no_record_modal(self):
        """RecordModal was for create/edit — should be removed in read-only sprint."""
        src = _read(MASTER_PAGE)
        assert "function RecordModal" not in src, \
            "RecordModal component still present in master-page.jsx"


# ═══════════════════════════════════════════════════════════════════════
# 7. Data-testid coverage for browser verification
# ═══════════════════════════════════════════════════════════════════════

class TestDataTestIds:
    """All interactive elements must have data-testid."""

    def test_master_data_page_testid(self):
        src = _read(MASTER_PAGE)
        assert 'data-testid="master-data-page"' in src, \
            "MasterPage root missing data-testid"

    def test_entity_tab_testid(self):
        src = _read(MASTER_PAGE)
        assert 'data-testid={\'entity-tab-\'' in src or \
               "data-testid={'entity-tab-'" in src, \
            "Entity tab buttons missing data-testid pattern"

    def test_record_count_testid(self):
        src = _read(MASTER_PAGE)
        assert 'data-testid="record-count"' in src, \
            "Record count display missing data-testid"

    def test_search_input_testid(self):
        src = _read(MASTER_PAGE)
        assert 'data-testid="master-search"' in src, \
            "Search input missing data-testid"

    def test_loading_state_testid(self):
        src = _read(MASTER_PAGE)
        assert 'data-testid="loading-state"' in src, \
            "Loading state missing data-testid"

    def test_error_state_testid(self):
        src = _read(MASTER_PAGE)
        assert 'data-testid="error-state"' in src, \
            "Error state missing data-testid"

    def test_empty_state_testid(self):
        src = _read(MASTER_PAGE)
        assert 'data-testid="empty-state"' in src, \
            "Empty state missing data-testid"

    def test_table_testid_pattern(self):
        src = _read(MASTER_PAGE)
        assert "data-testid={'table-'" in src or \
               'data-testid={\'table-\'' in src, \
            "Data table missing data-testid pattern"

    def test_reload_button_testid(self):
        src = _read(MASTER_PAGE)
        assert 'data-testid="btn-reload"' in src, \
            "Reload button missing data-testid"

    def test_roles_info_banner_testid(self):
        src = _read(MASTER_PAGE)
        assert 'data-testid="roles-info-banner"' in src, \
            "Roles info banner missing data-testid"

    def test_users_info_banner_testid(self):
        src = _read(MASTER_PAGE)
        assert 'data-testid="users-info-banner"' in src, \
            "Users info banner missing data-testid"


# ═══════════════════════════════════════════════════════════════════════
# 8. Column definitions match backend response fields
# ═══════════════════════════════════════════════════════════════════════

class TestColumnDefinitions:
    """ENTITY_COLUMNS must use real backend field names, not mock field names."""

    def test_entity_columns_constant_exists(self):
        src = _read(MASTER_PAGE)
        assert "ENTITY_COLUMNS" in src, \
            "ENTITY_COLUMNS constant missing from master-page.jsx"

    def test_clients_uses_bill_to_name(self):
        src = _read(MASTER_PAGE)
        assert "bill_to_name" in src, \
            "Clients columns should use 'bill_to_name' from backend, not 'name'"

    def test_suppliers_uses_supplier_code(self):
        src = _read(MASTER_PAGE)
        assert "supplier_code" in src, \
            "Suppliers columns should use 'supplier_code' from backend"

    def test_products_uses_product_code(self):
        src = _read(MASTER_PAGE)
        assert "product_code" in src, \
            "Products columns should use 'product_code' from backend"

    def test_designs_uses_design_code(self):
        src = _read(MASTER_PAGE)
        assert "design_code" in src, \
            "Designs columns should use 'design_code' from backend"

    def test_hs_uses_hs_code(self):
        src = _read(MASTER_PAGE)
        assert "hs_code" in src, \
            "HS columns should use 'hs_code' from backend"

    def test_hs_uses_duty_rate_pct(self):
        src = _read(MASTER_PAGE)
        assert "duty_rate_pct" in src, \
            "HS columns should use 'duty_rate_pct' from backend"

    def test_fx_uses_from_currency(self):
        src = _read(MASTER_PAGE)
        assert "from_currency" in src, \
            "FX columns should use 'from_currency' from backend"

    def test_vat_uses_rate_pct(self):
        src = _read(MASTER_PAGE)
        assert "rate_pct" in src, \
            "VAT columns should use 'rate_pct' from backend"

    def test_carriers_uses_carrier_code(self):
        src = _read(MASTER_PAGE)
        assert "carrier_code" in src, \
            "Carriers columns should use 'carrier_code' from backend"

    def test_users_uses_full_name(self):
        src = _read(MASTER_PAGE)
        assert "full_name" in src, \
            "Users columns should use 'full_name' from backend"

    def test_users_uses_approval_status(self):
        src = _read(MASTER_PAGE)
        assert "approval_status" in src, \
            "Users columns should use 'approval_status' from backend"


# ═══════════════════════════════════════════════════════════════════════
# 9. Loading and error states
# ═══════════════════════════════════════════════════════════════════════

class TestLoadingErrorStates:
    """Page must handle loading and error states gracefully."""

    def test_loading_text_present(self):
        src = _read(MASTER_PAGE)
        assert "Loading" in src, \
            "Missing loading state text"

    def test_failed_to_load_text_present(self):
        src = _read(MASTER_PAGE)
        assert "Failed to load" in src, \
            "Missing error state text"

    def test_retry_button_present(self):
        src = _read(MASTER_PAGE)
        assert "Retry" in src, \
            "Missing retry button for error state"

    def test_reload_button_present(self):
        src = _read(MASTER_PAGE)
        assert "handleReload" in src, \
            "Missing reload handler"


# ═══════════════════════════════════════════════════════════════════════
# 10. Static roles data
# ═══════════════════════════════════════════════════════════════════════

class TestStaticRoles:
    """Roles tab uses static system data, not an API call."""

    def test_static_roles_constant_exists(self):
        src = _read(MASTER_PAGE)
        assert "STATIC_ROLES" in src, \
            "STATIC_ROLES constant missing from master-page.jsx"

    def test_roles_has_admin(self):
        src = _read(MASTER_PAGE)
        # STATIC_ROLES should contain admin role
        roles_section = src[src.index("STATIC_ROLES"):]
        end = roles_section.index("];")
        assert "'admin'" in roles_section[:end] or '"admin"' in roles_section[:end], \
            "STATIC_ROLES missing 'admin' role"

    def test_roles_has_viewer(self):
        src = _read(MASTER_PAGE)
        roles_section = src[src.index("STATIC_ROLES"):]
        end = roles_section.index("];")
        assert "'viewer'" in roles_section[:end] or '"viewer"' in roles_section[:end], \
            "STATIC_ROLES missing 'viewer' role"

    def test_roles_info_banner(self):
        src = _read(MASTER_PAGE)
        assert "Roles are system-defined" in src, \
            "Missing roles info banner text"


# ═══════════════════════════════════════════════════════════════════════
# 11. No forbidden patterns
# ═══════════════════════════════════════════════════════════════════════

class TestNoForbiddenPatterns:
    """MasterPage must not contain auto-save, auto-fetch on mount, or mock remnants."""

    def test_no_auto_save(self):
        src = _read(MASTER_PAGE)
        assert "autoSave" not in src.lower(), \
            "MasterPage should not contain autoSave logic"

    def test_no_confirm_dialog(self):
        """confirm() was used for delete — writes are disabled, no need."""
        src = _read(MASTER_PAGE)
        # Exclude the word 'confirm_token' which is in PzApi comments
        confirm_calls = [m for m in re.finditer(r'\bconfirm\s*\(', src)]
        assert len(confirm_calls) == 0, \
            "confirm() dialog still present — delete is disabled"

    def test_no_client_kyc_modal(self):
        """ClientKycModal was for client create/edit — writes are disabled."""
        src = _read(MASTER_PAGE)
        assert "ClientKycModal" not in src, \
            "ClientKycModal reference still present in master-page.jsx"

    def test_exports_entity_columns(self):
        """ENTITY_COLUMNS should be exported for external use."""
        src = _read(MASTER_PAGE)
        assert "ENTITY_COLUMNS" in src, \
            "ENTITY_COLUMNS not exported from master-page.jsx"
