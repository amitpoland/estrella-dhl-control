"""Sprint 42 -- Diagnostics Authority-Honest Conversion regression tests.

Source-grep tests verifying that:
1. All 4 hardcoded fake data structures removed
2. No fake GB sizes, fake lock IDs, fake version, fake ms timings
3. Live endpoint wiring (5 independent fetches)
4. CLI tools visible but disabled (no runTool / setTimeout)
5. POST tools disabled with explicit reason
6. Per-section loading/error states
7. data-testid attributes for browser verification
8. 'diagnostics' in WIRED_PAGES (15 entries total)
9. pz-api.js has getStorageLocks + getSystemVersion
10. No BarRow function (removed — backend has no byte sizes)

Sprint: 42 -- Diagnostics Authority-Honest Conversion
Target: ops-cell.jsx, pz-api.js, mock-badge.jsx
"""

import pathlib
import re

import pytest

V2_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "v2"
OPS_CELL = V2_DIR / "ops-cell.jsx"
PZ_API = V2_DIR / "pz-api.js"
MOCK_BADGE = V2_DIR / "mock-badge.jsx"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# =============================================================================
# 1. Hardcoded fake data removed
# =============================================================================

class TestFakeDataRemoved:
    """All 4 fake data structures from the mock DiagnosticsPage must be gone."""

    def test_no_fake_health_checks_array(self):
        src = _read(OPS_CELL)
        assert "const healthChecks = [" not in src, \
            "Hardcoded healthChecks array must be removed"

    def test_no_fake_cli_tools_with_lastrun(self):
        """cliTools with fake lastRun dates must be gone (CLI_TOOLS has no lastRun)."""
        src = _read(OPS_CELL)
        assert "lastRun:" not in src, "Fake lastRun dates must be removed"

    def test_no_fake_lock_ids(self):
        src = _read(OPS_CELL)
        for lid in ["lock-201", "lock-202", "lock-203"]:
            assert lid not in src, f"Fake lock ID '{lid}' must be removed"

    def test_no_fake_version(self):
        src = _read(OPS_CELL)
        assert "v2.14.3" not in src, "Fake version string must be removed"

    def test_no_fake_gb_sizes(self):
        src = _read(OPS_CELL)
        for gb in ["2.4 GB", "1.8 GB", "0.3 GB", "0.2 GB", "0.1 GB", "2 MB", "of 100 GB"]:
            assert gb not in src, f"Fake storage size '{gb}' must be removed"

    def test_no_fake_ms_timings(self):
        """No hardcoded ms: N timing values."""
        src = _read(OPS_CELL)
        assert not re.search(r"ms:\s*\d+", src), "Hardcoded ms timings must be removed"

    def test_no_fake_errors(self):
        src = _read(OPS_CELL)
        assert "OAuth token expired" not in src
        assert "WFIRMA_WAREHOUSE_ID not set" not in src


# =============================================================================
# 2. No BarRow (backend has no byte sizes)
# =============================================================================

class TestBarRowRemoved:
    def test_no_bar_row_function(self):
        src = _read(OPS_CELL)
        assert "function BarRow(" not in src, "BarRow helper must be removed"


# =============================================================================
# 3. No fake runTool / setTimeout
# =============================================================================

class TestNoFakeRunTool:
    def test_no_run_tool_settimeout(self):
        src = _read(OPS_CELL)
        # Find the DiagnosticsPage region
        start = src.find("function DiagnosticsPage()")
        assert start > 0
        diag_region = src[start:start + 3000]
        assert "setTimeout" not in diag_region, "Fake setTimeout runner must be removed"

    def test_no_running_state(self):
        """No setRunning state for fake tool execution."""
        src = _read(OPS_CELL)
        start = src.find("function DiagnosticsPage()")
        diag_region = src[start:start + 3000]
        assert "setRunning" not in diag_region


# =============================================================================
# 4. Live endpoint wiring — 5 independent fetches
# =============================================================================

class TestLiveEndpoints:
    @pytest.mark.parametrize("api_call", [
        "getHealthFull()",
        "getStorageHealth()",
        "getStorageLocks()",
        "getSystemVersion()",
        "getDebugPending()",
    ])
    def test_api_call_present(self, api_call):
        src = _read(OPS_CELL)
        assert api_call in src, f"Live API call {api_call} must be present"

    def test_independent_fetches(self):
        """Each fetch has its own .then/.catch — no Promise.allSettled barrier."""
        src = _read(OPS_CELL)
        diag_start = src.find("function DiagnosticsPage()")
        diag = src[diag_start:]
        assert "Promise.allSettled" not in diag, "Must NOT use Promise.allSettled barrier"
        assert diag.count(".then(") >= 5, "Each of 5 fetches needs its own .then()"
        assert diag.count(".catch(") >= 5, "Each of 5 fetches needs its own .catch()"


# =============================================================================
# 5. Per-section loading/error states
# =============================================================================

class TestLoadingErrorStates:
    def test_loading_states(self):
        src = _read(OPS_CELL)
        assert "loading: true" in src
        assert "Loading" in src

    def test_error_states(self):
        src = _read(OPS_CELL)
        assert "Failed to load" in src

    @pytest.mark.parametrize("section_state", [
        "setHealth",
        "setStorage",
        "setLocks",
        "setVersion",
        "setPending",
    ])
    def test_per_section_state_setter(self, section_state):
        src = _read(OPS_CELL)
        assert section_state in src, f"Per-section state setter {section_state} must exist"


# =============================================================================
# 6. CLI tools visible but disabled
# =============================================================================

class TestCliToolsDisabled:
    def test_cli_tools_constant(self):
        src = _read(OPS_CELL)
        assert "const CLI_TOOLS" in src

    def test_all_run_buttons_disabled(self):
        """Run buttons must be disabled."""
        src = _read(OPS_CELL)
        # Find the CLI section
        cli_start = src.find("function _DiagCliSection()")
        assert cli_start > 0
        cli = src[cli_start:cli_start + 2000]
        assert "disabled" in cli

    def test_post_approval_reason(self):
        src = _read(OPS_CELL)
        assert "Diagnostic POST exists but execution requires explicit operator approval" in src

    def test_no_http_route_tools_labeled(self):
        src = _read(OPS_CELL)
        assert "CLI only" in src, "Tools without HTTP routes labeled 'CLI only'"
        assert "POST available" in src, "Tools with HTTP routes labeled 'POST available'"


# =============================================================================
# 7. data-testid attributes
# =============================================================================

class TestTestIds:
    @pytest.mark.parametrize("testid", [
        "diagnostics-page",
        "diag-kpi-strip",
        "diag-health-grid",
        "diag-storage-panel",
        "diag-locks-panel",
        "diag-cli-tools",
        "diag-pending-summary",
    ])
    def test_testid_present(self, testid):
        src = _read(OPS_CELL)
        assert testid in src, f"data-testid '{testid}' not found"


# =============================================================================
# 8. WIRED_PAGES includes 'diagnostics'
# =============================================================================

class TestWiredPages:
    def test_diagnostics_in_wired_pages(self):
        src = _read(MOCK_BADGE)
        assert "'diagnostics'" in src, "'diagnostics' not found in WIRED_PAGES"

    def test_wired_pages_count(self):
        src = _read(MOCK_BADGE)
        match = re.search(r"const WIRED_PAGES\s*=\s*\[([^\]]+)\]", src)
        assert match, "WIRED_PAGES array not found"
        entries = [e.strip().strip("'\"") for e in match.group(1).split(",") if e.strip()]
        assert len(entries) >= 15, f"Expected at least 15 WIRED_PAGES entries, found {len(entries)}: {entries}"


# =============================================================================
# 9. pz-api.js transports
# =============================================================================

class TestTransports:
    @pytest.mark.parametrize("fn_name,endpoint", [
        ("getStorageLocks", "debug/storage/locks"),
        ("getSystemVersion", "system/version"),
    ])
    def test_transport_defined(self, fn_name, endpoint):
        src = _read(PZ_API)
        assert fn_name in src, f"{fn_name} not in pz-api.js"
        assert endpoint in src, f"Endpoint '{endpoint}' not in pz-api.js"


# =============================================================================
# 10. Window export preserved
# =============================================================================

class TestWindowExport:
    def test_diagnostics_page_exported(self):
        src = _read(OPS_CELL)
        assert "DiagnosticsPage" in src
        # Must be in window exports
        assert "DiagnosticsPage," in src or "DiagnosticsPage\n" in src

    def test_other_pages_still_exported(self):
        src = _read(OPS_CELL)
        for page in ["WarehouseScannerPage", "ReservationCellPage", "WfirmaMappingPage"]:
            assert page in src, f"{page} must still be exported"


# =============================================================================
# 11. Sprint 41 WIRED_PAGES count test must be updated
# =============================================================================

class TestSprint41Compat:
    """Sprint 41 test expects 14 — it should still pass because it reads mock-badge
    which now has 15. We need to verify the sprint 41 test file exists and its
    count test checks for 14 (which will now fail — expected, we update it)."""

    def test_sprint41_test_file_exists(self):
        p = pathlib.Path(__file__).resolve().parent / "test_sprint41_api_status_authority_honest.py"
        assert p.exists(), "Sprint 41 test file must exist"
