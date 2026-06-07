"""Sprint 41 -- API Status Authority-Honest Conversion regression tests.

Source-grep tests verifying that:
1. All 4 hardcoded mock arrays are removed (API_INTEGRATIONS, API_ENDPOINT_REGISTRY,
   RECENT_ERRORS, INCIDENTS)
2. No fake carrier names remain (FedEx, UPS, GLS, InPost, DPD)
3. No fake latency/P95/call-count/incident metrics remain
4. SUBSYSTEMS array maps 12 real endpoints
5. pz-api.js defines all 9 transport functions for status endpoints
6. _deriveStatus handles all 12 subsystem IDs
7. Real KPIs present (Systems Online, Emails Pending, DHL Scanner, Follow-up Queue,
   Bot Errors, Active Carriers)
8. Wrong mock KPIs absent (Open Incidents, P95 Latency, Calls 24h, Success %)
9. 5 tabs present (Integration Health, Guardian Diagnostic, DHL Operations,
   Recent Errors, Bot Activity)
10. 'api_status' is in WIRED_PAGES
11. Per-card loading/error/empty states exist (no page-level failure)
12. data-testid attributes for browser verification
13. Independent per-subsystem fetching (not Promise.allSettled as a barrier)
14. STATE_STYLES map and StateChip component present
15. HealthFullDetail, RecentErrorsPanel, BotActivityPanel, DhlOpsSummary present

Sprint: 41 -- API Status Authority-Honest Conversion
Target: api-status-page.jsx, pz-api.js, mock-badge.jsx
"""

import pathlib
import re

import pytest

# -- File paths ---------------------------------------------------------------

V2_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "v2"
API_STATUS = V2_DIR / "api-status-page.jsx"
PZ_API = V2_DIR / "pz-api.js"
MOCK_BADGE = V2_DIR / "mock-badge.jsx"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# =============================================================================
# 1. All 4 mock arrays removed
# =============================================================================

class TestMockDataRemoved:
    """Verify Sprint 41 removed all hardcoded mock arrays."""

    @pytest.mark.parametrize("mock_array", [
        "API_INTEGRATIONS",
        "API_ENDPOINT_REGISTRY",
        "RECENT_ERRORS",
        "INCIDENTS",
    ])
    def test_no_mock_arrays(self, mock_array):
        src = _read(API_STATUS)
        assert not re.search(rf"^const {mock_array}\s*=\s*\[", src, re.MULTILINE), \
            f"Hardcoded {mock_array} array still present — Sprint 41 must remove all mock data"

    def test_no_mock_endpoint_count(self):
        """The old mock had 30 fake endpoint entries — no const declaration should remain."""
        src = _read(API_STATUS)
        assert not re.search(r"^const API_ENDPOINT_REGISTRY\s*=", src, re.MULTILINE), \
            "API_ENDPOINT_REGISTRY constant must not appear (comments are OK)"


# =============================================================================
# 2. No fake carrier names
# =============================================================================

class TestNoFakeCarriers:
    """Verify no fake carrier names from the mock data remain."""

    @pytest.mark.parametrize("fake_carrier", [
        "FedEx",
        "UPS",
        "GLS",
        "InPost",
        "DPD",
        "USPS",
        "Royal Mail",
    ])
    def test_no_fake_carrier(self, fake_carrier):
        """Fake carrier names must not appear in non-comment code."""
        src = _read(API_STATUS)
        # Strip comment lines so header notes about deleted data don't trigger false positives
        code_lines = [ln for ln in src.splitlines() if not ln.strip().startswith("//")]
        code = "\n".join(code_lines)
        assert fake_carrier not in code, \
            f"Fake carrier '{fake_carrier}' found in non-comment code — Sprint 41 only renders DHL (real carrier)"


# =============================================================================
# 3. No fake metrics
# =============================================================================

class TestNoFakeMetrics:
    """Verify fake KPI metrics from the mock are gone."""

    @pytest.mark.parametrize("fake_metric", [
        "P95 Latency",
        "Calls 24h",
        "Success %",
        "Open Incidents",
        "99.9%",
        "45ms",
        "12,847",
    ])
    def test_no_fake_metric(self, fake_metric):
        src = _read(API_STATUS)
        assert fake_metric not in src, \
            f"Fake metric '{fake_metric}' found — Sprint 41 uses real KPIs only"


# =============================================================================
# 4. SUBSYSTEMS array maps 12 real endpoints
# =============================================================================

class TestSubsystemsArray:
    """Verify SUBSYSTEMS constant defines all 12 subsystems."""

    def test_subsystems_constant_exists(self):
        src = _read(API_STATUS)
        assert "const SUBSYSTEMS" in src, "SUBSYSTEMS constant must exist"

    @pytest.mark.parametrize("subsystem_id", [
        "pz-engine",
        "health-full",
        "storage",
        "dhl-scanner",
        "dhl-ops",
        "dhl-followup",
        "carrier-gate",
        "carrier-config",
        "wfirma",
        "email-queue",
        "intelligence",
        "bot-pipeline",
    ])
    def test_subsystem_defined(self, subsystem_id):
        src = _read(API_STATUS)
        assert f"id: '{subsystem_id}'" in src, \
            f"Subsystem '{subsystem_id}' not found in SUBSYSTEMS array"

    def test_subsystem_count(self):
        """Exactly 12 subsystem entries (no more, no less)."""
        src = _read(API_STATUS)
        count = len(re.findall(r"\{\s*id:\s*'[^']+',\s*name:", src))
        assert count == 12, f"Expected 12 subsystems, found {count}"


# =============================================================================
# 5. pz-api.js transport functions
# =============================================================================

class TestTransportFunctions:
    """Verify pz-api.js defines all 9 transport functions for status endpoints."""

    @pytest.mark.parametrize("fn_name,endpoint_fragment", [
        ("getHealthFull", "debug/health-full"),
        ("getDebugPending", "debug/pending"),
        ("getStorageHealth", "debug/storage/health"),
        ("getPzHealth", "pz/health"),
        ("getDhlAutoScanStatus", "dhl/auto-scan-status"),
        ("getDhlDailySummary", "dhl/daily-summary"),
        ("getDhlFollowupStatus", "dhl/followup-automation/status"),
        ("getEmailQueue", "admin/email-queue"),
        ("getIntelligenceStatus", "intelligence/status"),
    ])
    def test_transport_function_defined(self, fn_name, endpoint_fragment):
        src = _read(PZ_API)
        assert fn_name in src, f"Transport function {fn_name} not found in pz-api.js"
        assert endpoint_fragment in src, f"Endpoint fragment '{endpoint_fragment}' not found in pz-api.js"


# =============================================================================
# 6. _deriveStatus handles all 12 subsystem IDs
# =============================================================================

class TestDeriveStatus:
    """Verify _deriveStatus switch covers all 12 subsystems."""

    def test_derive_status_function_exists(self):
        src = _read(API_STATUS)
        assert "function _deriveStatus" in src, "_deriveStatus function must exist"

    @pytest.mark.parametrize("case_label", [
        "case 'pz-engine'",
        "case 'health-full'",
        "case 'storage'",
        "case 'dhl-scanner'",
        "case 'dhl-ops'",
        "case 'dhl-followup'",
        "case 'carrier-gate'",
        "case 'carrier-config'",
        "case 'wfirma'",
        "case 'email-queue'",
        "case 'intelligence'",
        "case 'bot-pipeline'",
    ])
    def test_derive_status_case(self, case_label):
        src = _read(API_STATUS)
        assert case_label in src, f"_deriveStatus missing switch case for {case_label}"


# =============================================================================
# 7. Real KPIs present
# =============================================================================

class TestRealKpis:
    """Verify the 6 real KPIs are rendered."""

    @pytest.mark.parametrize("kpi_label", [
        "Systems Online",
        "Emails Pending",
        "DHL Scanner",
        "Follow-up Queue",
        "Bot Errors",
        "Active Carriers",
    ])
    def test_kpi_present(self, kpi_label):
        src = _read(API_STATUS)
        assert kpi_label in src, f"Real KPI '{kpi_label}' not found in page"


# =============================================================================
# 8. Wrong mock KPIs absent
# =============================================================================

class TestNoMockKpis:
    """Verify old mock KPIs are gone."""

    @pytest.mark.parametrize("bad_kpi", [
        "API Uptime",
        "Total Endpoints",
        "Active Integrations",
    ])
    def test_no_mock_kpi(self, bad_kpi):
        src = _read(API_STATUS)
        assert bad_kpi not in src, f"Mock KPI '{bad_kpi}' still present — remove"


# =============================================================================
# 9. Tab structure
# =============================================================================

class TestTabStructure:
    """Verify the 5 correct tabs are present."""

    @pytest.mark.parametrize("tab_label", [
        "Integration Health",
        "Guardian Diagnostic",
        "DHL Operations",
        "Recent Errors",
        "Bot Activity",
    ])
    def test_tab_present(self, tab_label):
        src = _read(API_STATUS)
        assert tab_label in src, f"Tab '{tab_label}' not found"

    @pytest.mark.parametrize("bad_tab", [
        "Endpoint Registry",
        "API Gateway",
        "Incident History",
    ])
    def test_no_mock_tab(self, bad_tab):
        src = _read(API_STATUS)
        assert bad_tab not in src, f"Mock tab '{bad_tab}' still present"

    def test_tab_testid_pattern(self):
        """Tab buttons use template literal data-testid={`tab-${t.id}`}."""
        src = _read(API_STATUS)
        assert "tab-${t.id}" in src or "tab-${" in src, \
            "Tab buttons must use data-testid template with tab IDs"

    @pytest.mark.parametrize("tab_id", [
        "overview",
        "guardian",
        "dhl-ops",
        "errors",
        "bot",
    ])
    def test_tab_id_defined(self, tab_id):
        """Each tab ID must be defined in the tabs array."""
        src = _read(API_STATUS)
        assert f"id: '{tab_id}'" in src, f"Tab ID '{tab_id}' not found in tabs definition"


# =============================================================================
# 10. WIRED_PAGES includes 'api_status'
# =============================================================================

class TestWiredPages:
    """Verify 'api_status' is in WIRED_PAGES."""

    def test_api_status_in_wired_pages(self):
        src = _read(MOCK_BADGE)
        assert "'api_status'" in src, "'api_status' not found in WIRED_PAGES"

    def test_wired_pages_count(self):
        """After Sprint 41, WIRED_PAGES should have at least 14 entries (Sprint 42+ adds more)."""
        src = _read(MOCK_BADGE)
        match = re.search(r"const WIRED_PAGES\s*=\s*\[([^\]]+)\]", src)
        assert match, "WIRED_PAGES array not found"
        entries = [e.strip().strip("'\"") for e in match.group(1).split(",") if e.strip()]
        assert len(entries) >= 14, f"Expected at least 14 WIRED_PAGES entries, found {len(entries)}: {entries}"


# =============================================================================
# 11. Per-card loading/error/empty states
# =============================================================================

class TestLoadingErrorStates:
    """Verify per-subsystem loading and error state handling."""

    def test_loading_state(self):
        src = _read(API_STATUS)
        assert "loading" in src, "Loading state must be handled"
        assert "Fetching" in src or "Loading" in src, "Loading message must be shown to user"

    def test_error_state_per_card(self):
        src = _read(API_STATUS)
        assert "fetch_error" in src, "fetch_error state for per-card errors must exist"
        assert "Failed to load" in src, "Error message per card must exist"

    def test_no_page_level_failure_blanket(self):
        """No single error should blank all subsystems."""
        src = _read(API_STATUS)
        # Each subsystem is fetched independently
        assert "SUBSYSTEMS.forEach" in src, "Subsystems must be fetched independently (forEach loop)"
        # There must NOT be a Promise.allSettled call in executable code
        code_lines = [ln for ln in src.splitlines() if not ln.strip().startswith("//")]
        code = "\n".join(code_lines)
        assert "Promise.allSettled" not in code, \
            "Must NOT use Promise.allSettled as barrier — each subsystem fetches independently"


# =============================================================================
# 12. data-testid attributes
# =============================================================================

class TestTestIds:
    """Verify data-testid attributes for browser verification."""

    @pytest.mark.parametrize("testid", [
        "api-status-page",
        "api-kpi-strip",
        "health-full-detail",
        "recent-errors-panel",
        "recent-errors-empty",
        "bot-activity-panel",
        "dhl-ops-summary",
        "tab-content-overview",
        "tab-content-guardian",
        "tab-content-dhl-ops",
        "tab-content-errors",
        "tab-content-bot",
    ])
    def test_testid_present(self, testid):
        src = _read(API_STATUS)
        assert testid in src, f"data-testid '{testid}' not found"


# =============================================================================
# 13. Independent per-subsystem fetching
# =============================================================================

class TestIndependentFetching:
    """Verify each subsystem fetches independently."""

    def test_foreach_pattern(self):
        """Each subsystem's fetch fires in its own .then/.catch chain."""
        src = _read(API_STATUS)
        assert "SUBSYSTEMS.forEach" in src, "Must use forEach for independent fetches"
        assert ".then(" in src, "Each fetch must have .then() handler"
        assert ".catch(" in src, "Each fetch must have .catch() handler"

    def test_per_subsystem_state(self):
        """Results stored per subsystem ID, not as a single all-or-nothing."""
        src = _read(API_STATUS)
        # setResults updates one key at a time
        assert "setResults(prev => ({" in src or "setResults(prev =>" in src, \
            "Must update per-subsystem in results state"


# =============================================================================
# 14. STATE_STYLES and StateChip
# =============================================================================

class TestStateChip:
    """Verify STATE_STYLES map and StateChip component."""

    def test_state_styles_exists(self):
        src = _read(API_STATUS)
        assert "STATE_STYLES" in src, "STATE_STYLES constant must exist"

    @pytest.mark.parametrize("state_key", [
        "healthy", "degraded", "error", "offline", "unknown", "loading", "fetch_error",
    ])
    def test_state_key(self, state_key):
        src = _read(API_STATUS)
        assert f"{state_key}:" in src or f"'{state_key}'" in src, \
            f"State '{state_key}' not found in STATE_STYLES"

    def test_state_chip_component(self):
        src = _read(API_STATUS)
        assert "function StateChip" in src, "StateChip component must exist"


# =============================================================================
# 15. Sub-panel components
# =============================================================================

class TestSubPanels:
    """Verify all sub-panel components exist."""

    @pytest.mark.parametrize("component", [
        "HealthFullDetail",
        "RecentErrorsPanel",
        "BotActivityPanel",
        "DhlOpsSummary",
        "SubsystemCard",
        "_MiniKpi",
    ])
    def test_component_exists(self, component):
        src = _read(API_STATUS)
        assert f"function {component}" in src, f"Component '{component}' not defined"


# =============================================================================
# 16. CSS custom properties (no hardcoded hex)
# =============================================================================

class TestCssCustomProperties:
    """Verify CSS custom properties are used, not hardcoded hex."""

    def test_uses_css_vars(self):
        src = _read(API_STATUS)
        assert "var(--" in src, "Must use CSS custom properties"

    def test_uses_badge_vars(self):
        src = _read(API_STATUS)
        assert "var(--badge-green" in src, "Must use badge-green CSS variables"
        assert "var(--badge-red" in src, "Must use badge-red CSS variables"
        assert "var(--badge-yellow" in src, "Must use badge-yellow CSS variables"


# =============================================================================
# 17. Window export
# =============================================================================

class TestWindowExport:
    """Verify the component is exported to window."""

    def test_window_export(self):
        src = _read(API_STATUS)
        assert "window.ApiStatusPage = ApiStatusPage" in src, \
            "ApiStatusPage must be exported to window"
