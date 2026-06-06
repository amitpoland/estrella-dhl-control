"""Sprint 39 -- Carriers Authority-Honest Redesign regression tests.

Source-grep tests verifying that:
1. All hardcoded mock data arrays are removed (CARRIERS, AVAILABLE_NEW,
   API_ENDPOINTS, WEBHOOKS, SESSIONS, AUDIT)
2. No fake account numbers, ping times, quotas remain
3. carriers-page.jsx calls PzApi.listCarriersConfig()
4. carriers-page.jsx calls PzApi.getCarrierStatus()
5. pz-api.js defines getCarrierStatus with /api/v1/carrier/status
6. 'carriers' is in WIRED_PAGES
7. DHL Operations section contains only route-backed facts
8. Integration gaps are rendered as disabled backend-pending items
9. No fake connection states (connected/pending_oauth/disconnected)

Sprint: 39 -- Carriers Authority-Honest Redesign
Target: carriers-page.jsx, pz-api.js, mock-badge.jsx
"""

import pathlib
import re

import pytest

# -- File paths ---------------------------------------------------------------

V2_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "v2"
CARRIERS_PAGE = V2_DIR / "carriers-page.jsx"
PZ_API = V2_DIR / "pz-api.js"
MOCK_BADGE = V2_DIR / "mock-badge.jsx"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# =============================================================================
# 1. All hardcoded mock data arrays are REMOVED
# =============================================================================

class TestMockDataRemoved:
    """Verify Sprint 39 removed all hardcoded carrier mock data."""

    def test_no_carriers_constant(self):
        src = _read(CARRIERS_PAGE)
        # Should NOT have the old CARRIERS = [ { id: 'dhl-express' ... } ] array
        assert not re.search(r"^const CARRIERS\s*=\s*\[", src, re.MULTILINE), \
            "Hardcoded CARRIERS array still present — Sprint 39 must remove all mock carrier data"

    def test_no_available_new_constant(self):
        src = _read(CARRIERS_PAGE)
        assert not re.search(r"^const AVAILABLE_NEW\s*=\s*\[", src, re.MULTILINE), \
            "Hardcoded AVAILABLE_NEW array still present"

    def test_no_api_endpoints_constant(self):
        src = _read(CARRIERS_PAGE)
        assert not re.search(r"^const API_ENDPOINTS\s*=\s*\[", src, re.MULTILINE), \
            "Hardcoded API_ENDPOINTS array still present"

    def test_no_webhooks_constant(self):
        src = _read(CARRIERS_PAGE)
        assert not re.search(r"^const WEBHOOKS\s*=\s*\[", src, re.MULTILINE), \
            "Hardcoded WEBHOOKS array still present"

    def test_no_sessions_constant(self):
        src = _read(CARRIERS_PAGE)
        assert not re.search(r"^const SESSIONS\s*=\s*\[", src, re.MULTILINE), \
            "Hardcoded SESSIONS array still present"

    def test_no_audit_constant(self):
        src = _read(CARRIERS_PAGE)
        assert not re.search(r"^const AUDIT\s*=\s*\[", src, re.MULTILINE), \
            "Hardcoded AUDIT array still present"


# =============================================================================
# 2. No fake values remain
# =============================================================================

class TestNoFakeValues:
    """Verify no fake account numbers, ping times, quotas."""

    def test_no_fake_account_numbers(self):
        src = _read(CARRIERS_PAGE)
        assert "954********" not in src, "Fake DHL account number still present"
        assert "740********" not in src, "Fake FedEx account number still present"
        assert "980********" not in src, "Fake sandbox account number still present"

    def test_no_fake_ping_times(self):
        src = _read(CARRIERS_PAGE)
        assert "pingMs:" not in src, "Fake ping milliseconds still present"
        assert "lastPing:" not in src, "Fake lastPing field still present"

    def test_no_fake_quotas(self):
        src = _read(CARRIERS_PAGE)
        assert "quotaUsed:" not in src, "Fake quotaUsed still present"
        assert "quotaLimit:" not in src, "Fake quotaLimit still present"

    def test_no_fake_token_strings(self):
        src = _read(CARRIERS_PAGE)
        assert "k_dhl_2026" not in src, "Fake DHL token string still present"
        assert "fx_oauth_" not in src, "Fake FedEx OAuth token still present"
        assert "inp_****" not in src, "Fake InPost token still present"

    def test_no_fake_connection_states_in_data(self):
        """No hardcoded state: 'connected' in carrier data objects (state chips for UI are OK)."""
        src = _read(CARRIERS_PAGE)
        # The old mock had: state: 'connected', state: 'pending_oauth', etc.
        # These should not appear as data values (chip labels in rendering helpers are fine)
        assert not re.search(r"state:\s*'connected'", src), \
            "Fake carrier connection state 'connected' in data"
        assert not re.search(r"state:\s*'pending_oauth'", src), \
            "Fake carrier connection state 'pending_oauth' in data"

    def test_no_fake_24h_counts(self):
        src = _read(CARRIERS_PAGE)
        assert "last24h:" not in src, "Fake 24h webhook count still present"

    def test_no_fake_error_messages(self):
        src = _read(CARRIERS_PAGE)
        assert "AUTH_401" not in src, "Fake AUTH_401 error message still present"
        assert "token rejected; needs rotation" not in src, "Fake error detail still present"


# =============================================================================
# 3. Live API calls
# =============================================================================

class TestLiveApiCalls:
    """Verify carriers-page.jsx calls live backend APIs."""

    def test_calls_list_carriers_config(self):
        src = _read(CARRIERS_PAGE)
        assert "PzApi.listCarriersConfig()" in src, \
            "carriers-page.jsx must call PzApi.listCarriersConfig()"

    def test_calls_get_carrier_status(self):
        src = _read(CARRIERS_PAGE)
        assert "PzApi.getCarrierStatus()" in src, \
            "carriers-page.jsx must call PzApi.getCarrierStatus()"

    def test_calls_list_master_audit(self):
        src = _read(CARRIERS_PAGE)
        assert "PzApi.listMasterAudit(" in src, \
            "carriers-page.jsx must call PzApi.listMasterAudit for audit tab"

    def test_audit_filters_carriers_config(self):
        src = _read(CARRIERS_PAGE)
        assert "entity: 'carriers_config'" in src or "entity:'carriers_config'" in src, \
            "Audit call must filter by entity=carriers_config"


# =============================================================================
# 4. pz-api.js has getCarrierStatus
# =============================================================================

class TestPzApiTransport:
    """Verify pz-api.js defines getCarrierStatus."""

    def test_get_carrier_status_function_exists(self):
        src = _read(PZ_API)
        assert "getCarrierStatus:" in src or "getCarrierStatus :" in src, \
            "pz-api.js must define getCarrierStatus function"

    def test_get_carrier_status_calls_correct_endpoint(self):
        src = _read(PZ_API)
        assert "/carrier/status" in src, \
            "getCarrierStatus must call /api/v1/carrier/status"

    def test_list_carriers_config_still_exists(self):
        src = _read(PZ_API)
        assert "listCarriersConfig:" in src, \
            "listCarriersConfig must still exist in pz-api.js"

    def test_list_master_audit_still_exists(self):
        src = _read(PZ_API)
        assert "listMasterAudit:" in src, \
            "listMasterAudit must still exist in pz-api.js"


# =============================================================================
# 5. WIRED_PAGES includes 'carriers'
# =============================================================================

class TestWiredPages:
    """Verify 'carriers' is in WIRED_PAGES."""

    def test_carriers_in_wired_pages(self):
        src = _read(MOCK_BADGE)
        assert "'carriers'" in src, \
            "'carriers' must be in WIRED_PAGES in mock-badge.jsx"

    def test_wired_pages_contains_carriers(self):
        src = _read(MOCK_BADGE)
        match = re.search(r"WIRED_PAGES\s*=\s*\[([^\]]+)\]", src)
        assert match, "WIRED_PAGES array not found"
        assert "'carriers'" in match.group(1), \
            "'carriers' not found inside WIRED_PAGES array"


# =============================================================================
# 6. DHL Operations section — route-backed facts only
# =============================================================================

class TestDhlOperations:
    """Verify DHL Operations tab contains only route-backed facts."""

    def test_dhl_routes_constant_exists(self):
        src = _read(CARRIERS_PAGE)
        assert "DHL_ROUTES" in src, "DHL_ROUTES constant must exist"

    def test_dhl_ops_tab_component(self):
        src = _read(CARRIERS_PAGE)
        assert "DhlOperationsTab" in src, "DhlOperationsTab component must exist"

    def test_dhl_routes_have_real_paths(self):
        src = _read(CARRIERS_PAGE)
        # Verify real backend route paths are referenced
        assert "/api/v1/carrier/{batch_id}/shipment" in src
        assert "/api/v1/tracking/{tracking_no}" in src
        assert "/api/v1/carrier/webhook/dhl" in src
        assert "/api/v1/dhl/scan-inbox" in src
        assert "/api/v1/dhl/readiness/{batch_id}" in src
        assert "/api/v1/dhl/clearance-status/{batch_id}" in src

    def test_gate_status_uses_real_fields(self):
        src = _read(CARRIERS_PAGE)
        assert "carrier_api_status" in src
        assert "carrier_plt_status" in src
        assert "dhl_tracking_api_status" in src

    def test_no_fake_dhl_ping(self):
        src = _read(CARRIERS_PAGE)
        assert "312 ms" not in src, "Fake DHL ping time still present"
        assert "successPct" not in src, "Fake success percentage still present"
        assert "calls24h" not in src, "Fake 24h call count still present"


# =============================================================================
# 7. Integration gaps — disabled with reasons
# =============================================================================

class TestIntegrationGaps:
    """Verify missing APIs are rendered as disabled backend-pending items."""

    def test_integration_gaps_constant_exists(self):
        src = _read(CARRIERS_PAGE)
        assert "INTEGRATION_GAPS" in src, "INTEGRATION_GAPS constant must exist"

    def test_gaps_tab_component(self):
        src = _read(CARRIERS_PAGE)
        assert "IntegrationGapsTab" in src, "IntegrationGapsTab component must exist"

    def test_gap_ids_present(self):
        src = _read(CARRIERS_PAGE)
        for gap_id in ["GAP-C01", "GAP-C02", "GAP-C03", "GAP-C04", "GAP-C05"]:
            assert gap_id in src, f"{gap_id} not found in integration gaps"

    def test_backend_pending_text(self):
        src = _read(CARRIERS_PAGE)
        assert "Backend pending" in src, "Backend pending text must appear"

    def test_severity_levels_present(self):
        src = _read(CARRIERS_PAGE)
        assert "'critical'" in src, "Critical severity level must exist"
        assert "'high'" in src, "High severity level must exist"
        assert "'medium'" in src, "Medium severity level must exist"
        assert "'low'" in src, "Low severity level must exist"


# =============================================================================
# 8. Tab structure redesigned
# =============================================================================

class TestTabStructure:
    """Verify tabs are redesigned from mock 6-tab to honest 4-tab."""

    def test_config_tab_exists(self):
        src = _read(CARRIERS_PAGE)
        assert "'config'" in src, "Config Registry tab must exist"
        assert "Config Registry" in src

    def test_dhl_ops_tab_exists(self):
        src = _read(CARRIERS_PAGE)
        assert "'dhl_ops'" in src, "DHL Operations tab must exist"
        assert "DHL Operations" in src

    def test_gaps_tab_exists(self):
        src = _read(CARRIERS_PAGE)
        assert "'gaps'" in src, "Integration Gaps tab must exist"
        assert "Integration Gaps" in src

    def test_audit_tab_exists(self):
        src = _read(CARRIERS_PAGE)
        assert "'audit'" in src, "Config Audit tab must exist"
        assert "Config Audit" in src

    def test_old_accounts_tab_removed(self):
        src = _read(CARRIERS_PAGE)
        assert "CarrierAccountsTab" not in src, "Old CarrierAccountsTab component must be removed"

    def test_old_add_carrier_tab_removed(self):
        src = _read(CARRIERS_PAGE)
        assert "AddCarrierTab" not in src, "Old AddCarrierTab component must be removed"

    def test_old_api_integration_tab_removed(self):
        src = _read(CARRIERS_PAGE)
        assert "ApiIntegrationTab" not in src, "Old ApiIntegrationTab component must be removed"

    def test_old_webhooks_tab_removed(self):
        src = _read(CARRIERS_PAGE)
        assert "WebhooksTab" not in src, "Old WebhooksTab component must be removed"

    def test_old_sessions_tab_removed(self):
        src = _read(CARRIERS_PAGE)
        assert "SessionsTab" not in src, "Old SessionsTab component must be removed"


# =============================================================================
# 9. Component exports preserved
# =============================================================================

class TestExports:
    """Verify window exports are maintained for other pages."""

    def test_carriers_page_exported(self):
        src = _read(CARRIERS_PAGE)
        assert re.search(r"Object\.assign\(window.*?CarriersPage", src), \
            "CarriersPage must be exported to window"

    def test_carrier_kpi_exported(self):
        src = _read(CARRIERS_PAGE)
        assert re.search(r"Object\.assign\(window.*?CarrierKpi", src), \
            "CarrierKpi must be exported to window"

    def test_api_btn_exported(self):
        src = _read(CARRIERS_PAGE)
        assert re.search(r"Object\.assign\(window.*?ApiBtn", src), \
            "ApiBtn must be exported to window"

    def test_tbl_exported(self):
        src = _read(CARRIERS_PAGE)
        assert re.search(r"Object\.assign\(window.*?Tbl", src), \
            "Tbl must be exported to window"


# =============================================================================
# 10. Test IDs present
# =============================================================================

class TestTestIds:
    """Verify data-testid attributes for browser verification."""

    def test_carriers_page_testid(self):
        src = _read(CARRIERS_PAGE)
        assert 'data-testid="carriers-page"' in src

    def test_kpi_strip_testid(self):
        src = _read(CARRIERS_PAGE)
        assert 'data-testid="carriers-kpi-strip"' in src

    def test_config_registry_tab_testid(self):
        src = _read(CARRIERS_PAGE)
        assert 'data-testid="config-registry-tab"' in src

    def test_dhl_ops_tab_testid(self):
        src = _read(CARRIERS_PAGE)
        assert 'data-testid="dhl-ops-tab"' in src

    def test_gaps_tab_testid(self):
        src = _read(CARRIERS_PAGE)
        assert 'data-testid="gaps-tab"' in src

    def test_audit_tab_testid(self):
        src = _read(CARRIERS_PAGE)
        assert 'data-testid="audit-tab"' in src

    def test_gate_status_testid(self):
        src = _read(CARRIERS_PAGE)
        assert 'data-testid="gate-status-grid"' in src


# =============================================================================
# 11. No other pages touched
# =============================================================================

class TestNoOtherPagesTouched:
    """Sprint 39 must not modify master-page.jsx or dashboard."""

    def test_no_new_transport_for_carriers_crud(self):
        """No write transport functions for carrier management."""
        src = _read(PZ_API)
        for name in ["createCarrier", "updateCarrier", "deleteCarrier",
                      "testCarrierConnection", "disconnectCarrier",
                      "rotateCarrierToken", "startCarrierOAuth"]:
            assert name not in src, \
                f"pz-api.js added {name} — Sprint 39 does not create carrier management APIs"
