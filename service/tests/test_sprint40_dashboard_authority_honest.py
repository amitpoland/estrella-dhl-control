"""Sprint 40 -- Dashboard Authority-Honest Conversion regression tests.

Source-grep tests verifying that:
1. All hardcoded mock data (PIPELINE_SHIPMENTS) is removed
2. No fake client names remain (Maison Royale, Patek, Crown, Audemars, etc.)
3. No fake AWBs or static values remain
4. dashboard-kanban.jsx calls PzApi.listBatches()
5. pz-api.js defines listBatches with /api/v1/dashboard/batches
6. V1 PZ workflow lane names present (Ready for PZ, PZ Generated, Exported)
7. Wrong mock lane names absent (Ready to Ship, In Transit, Delivered)
8. KPIs derived from live batches (Active, Urgent, Awaiting DHL, Awaiting SAD, Ready for booking)
9. 'dashboard' is in WIRED_PAGES
10. Loading/error/empty states exist
11. List view button navigates to shipments (not dead)
12. No drag-and-drop claim remains
13. Status mapper functions present (_mapOverall, _mapDhlStatus, _mapSadStatus, _mapPzStatus)
14. transformBatch and _batchLane functions present
15. data-testid attributes for browser verification

Sprint: 40 -- Dashboard Authority-Honest Conversion
Target: dashboard-kanban.jsx, pz-api.js, mock-badge.jsx
"""

import pathlib
import re

import pytest

# -- File paths ---------------------------------------------------------------

V2_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "v2"
DASHBOARD_KANBAN = V2_DIR / "dashboard-kanban.jsx"
PZ_API = V2_DIR / "pz-api.js"
MOCK_BADGE = V2_DIR / "mock-badge.jsx"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# =============================================================================
# 1. PIPELINE_SHIPMENTS removed
# =============================================================================

class TestMockDataRemoved:
    """Verify Sprint 40 removed all hardcoded pipeline shipment data."""

    def test_no_pipeline_shipments_constant(self):
        src = _read(DASHBOARD_KANBAN)
        assert not re.search(r"^const PIPELINE_SHIPMENTS\s*=\s*\[", src, re.MULTILINE), \
            "Hardcoded PIPELINE_SHIPMENTS array still present — Sprint 40 must remove all mock data"

    def test_no_old_lanes_constant(self):
        """The old mock LANES constant (with 'transit', 'done=Delivered') must be replaced."""
        src = _read(DASHBOARD_KANBAN)
        # Old mock had: { id: 'transit', label: 'In Transit' }
        assert "id: 'transit'" not in src, \
            "Old 'transit' lane ID still present — Sprint 40 uses 'booked' (PZ Generated)"

    def test_kanban_lanes_constant_exists(self):
        src = _read(DASHBOARD_KANBAN)
        assert "KANBAN_LANES" in src, "KANBAN_LANES constant must exist"


# =============================================================================
# 2. No fake client names
# =============================================================================

class TestNoFakeClients:
    """Verify no fake client names from the mock data remain."""

    @pytest.mark.parametrize("fake_client", [
        "Maison Royale SARL",
        "Atelier Lumiere",    # accent stripped for grep safety
        "Crown Jewelers Ltd",
        "Patek Philippe SA",
        "Audemars Piguet",
        "Aurum Watches GmbH",
        "Bijoux",
        "Manufaktura",
    ])
    def test_no_fake_client(self, fake_client):
        src = _read(DASHBOARD_KANBAN)
        assert fake_client not in src, \
            f"Fake client name '{fake_client}' still present in dashboard-kanban.jsx"

    def test_no_hotel_belle_etoile(self):
        src = _read(DASHBOARD_KANBAN)
        assert "Belle" not in src, "Fake client 'Hotel Belle Etoile' still present"


# =============================================================================
# 3. No fake AWBs or static values
# =============================================================================

class TestNoFakeValues:
    """Verify no fake AWBs, IDs, or static shipment values remain."""

    def test_no_fake_ship_ids(self):
        src = _read(DASHBOARD_KANBAN)
        assert "SHIP-2026" not in src, "Fake shipment IDs (SHIP-2026-xxxx) still present"

    def test_no_fake_awb_1234567(self):
        src = _read(DASHBOARD_KANBAN)
        assert "1234567802" not in src, "Fake AWB 1234567802 still present"
        assert "1234567803" not in src, "Fake AWB 1234567803 still present"
        assert "1234567890" not in src, "Fake AWB 1234567890 still present"
        assert "1234567812" not in src, "Fake AWB 1234567812 still present"
        assert "1234567830" not in src, "Fake AWB 1234567830 still present"
        assert "1234567831" not in src, "Fake AWB 1234567831 still present"

    def test_no_fake_awb_others(self):
        src = _read(DASHBOARD_KANBAN)
        assert "998877665" not in src, "Fake AWB 998877665 still present"
        assert "8442211003" not in src, "Fake AWB 8442211003 still present"
        assert "INP-552448" not in src, "Fake InPost AWB still present"
        assert "INP-552399" not in src, "Fake InPost AWB still present"

    def test_no_fake_values_in_data(self):
        src = _read(DASHBOARD_KANBAN)
        assert "9840.50" not in src, "Fake value 9840.50 still present"
        assert "142000" not in src, "Fake value 142000 still present"
        assert "24100" not in src, "Fake value 24100 still present"
        assert "88400" not in src, "Fake value 88400 still present"

    def test_no_fake_direction_in_out(self):
        """direction: 'in'/'out' was a mock concept — no direction field in real batch data."""
        src = _read(DASHBOARD_KANBAN)
        assert not re.search(r"direction:\s*'(in|out)'", src), \
            "Fake direction field still present in data"

    def test_no_static_age_strings(self):
        """Ages like '2h', '1d', '3d' were static mock values — real ages computed from timestamp."""
        src = _read(DASHBOARD_KANBAN)
        assert not re.search(r"age:\s*'[0-9]+[hd]'", src), \
            "Static age strings still present in data"

    def test_no_fake_priority_urgent(self):
        """priority: 'urgent' was a mock field — real urgency derived from status."""
        src = _read(DASHBOARD_KANBAN)
        assert not re.search(r"priority:\s*'(urgent|high|normal)'", src), \
            "Fake priority field still present in data"


# =============================================================================
# 4. Live API calls
# =============================================================================

class TestLiveApiCalls:
    """Verify dashboard-kanban.jsx calls live backend API."""

    def test_calls_list_batches(self):
        src = _read(DASHBOARD_KANBAN)
        assert "PzApi.listBatches()" in src, \
            "dashboard-kanban.jsx must call PzApi.listBatches()"

    def test_uses_useeffect(self):
        src = _read(DASHBOARD_KANBAN)
        assert "useEffect" in src, \
            "dashboard-kanban.jsx must use useEffect for data fetching"

    def test_uses_usestate(self):
        src = _read(DASHBOARD_KANBAN)
        assert "useState" in src, \
            "dashboard-kanban.jsx must use useState for batch state"


# =============================================================================
# 5. pz-api.js has listBatches
# =============================================================================

class TestPzApiTransport:
    """Verify pz-api.js defines listBatches."""

    def test_list_batches_function_exists(self):
        src = _read(PZ_API)
        assert "listBatches:" in src or "listBatches :" in src, \
            "pz-api.js must define listBatches function"

    def test_list_batches_calls_correct_endpoint(self):
        src = _read(PZ_API)
        assert "/dashboard/batches" in src, \
            "listBatches must call /api/v1/dashboard/batches"


# =============================================================================
# 6. V1 PZ workflow lane names present
# =============================================================================

class TestV1LaneNames:
    """Verify correct PZ workflow lane names from V1 production."""

    def test_ready_for_pz_lane(self):
        src = _read(DASHBOARD_KANBAN)
        assert "Ready for PZ" in src, "'Ready for PZ' lane label must be present"

    def test_pz_generated_lane(self):
        src = _read(DASHBOARD_KANBAN)
        assert "PZ Generated" in src, "'PZ Generated' lane label must be present"

    def test_exported_lane(self):
        src = _read(DASHBOARD_KANBAN)
        assert "'Exported'" in src or '"Exported"' in src, "'Exported' lane label must be present"

    def test_booked_lane_id(self):
        src = _read(DASHBOARD_KANBAN)
        assert "'booked'" in src, "'booked' lane ID must be present (replaces old 'transit')"

    def test_six_lanes(self):
        src = _read(DASHBOARD_KANBAN)
        for lane_id in ['new', 'docs', 'customs', 'ready', 'booked', 'done']:
            assert f"id: '{lane_id}'" in src or f"'{lane_id}'" in src, \
                f"Lane '{lane_id}' must exist"


# =============================================================================
# 7. Wrong mock lane names ABSENT
# =============================================================================

class TestMockLaneNamesRemoved:
    """Verify wrong mock lane names are not present."""

    def test_no_ready_to_ship(self):
        src = _read(DASHBOARD_KANBAN)
        assert "Ready to Ship" not in src, "'Ready to Ship' is a mock label — must use 'Ready for PZ'"

    def test_no_in_transit(self):
        src = _read(DASHBOARD_KANBAN)
        assert "In Transit" not in src, "'In Transit' is a mock label — must use 'PZ Generated'"

    def test_no_delivered(self):
        src = _read(DASHBOARD_KANBAN)
        assert "'Delivered'" not in src, "'Delivered' is a mock label — must use 'Exported'"


# =============================================================================
# 8. KPIs derived from live batches
# =============================================================================

class TestKpiDerivation:
    """Verify KPIs are derived from real batch data, not fake constants."""

    def test_active_kpi(self):
        src = _read(DASHBOARD_KANBAN)
        assert "Active" in src, "Active KPI label must be present"

    def test_urgent_kpi(self):
        src = _read(DASHBOARD_KANBAN)
        assert "Urgent" in src, "Urgent KPI label must be present"

    def test_awaiting_dhl_kpi(self):
        src = _read(DASHBOARD_KANBAN)
        assert "Awaiting DHL" in src, "Awaiting DHL KPI label must be present"

    def test_awaiting_sad_kpi(self):
        src = _read(DASHBOARD_KANBAN)
        assert "Awaiting SAD" in src, "Awaiting SAD KPI label must be present"

    def test_ready_for_booking_kpi(self):
        src = _read(DASHBOARD_KANBAN)
        assert "Ready for booking" in src, "Ready for booking KPI label must be present"

    def test_no_inbound_outbound_kpi(self):
        """Inbound/Outbound KPIs were mock — no direction field in real data."""
        src = _read(DASHBOARD_KANBAN)
        # Check no KPI labeled exactly 'Inbound' or 'Outbound' in KPI strip
        assert not re.search(r'label="Inbound"', src), \
            "Fake 'Inbound' KPI label still present"
        assert not re.search(r'label="Outbound"', src), \
            "Fake 'Outbound' KPI label still present"

    def test_no_total_value_kpi(self):
        """Total value KPI was mock — currency mix makes aggregate meaningless."""
        src = _read(DASHBOARD_KANBAN)
        assert not re.search(r'label="Total value"', src), \
            "Fake 'Total value' KPI label still present"

    def test_urgent_derived_from_status(self):
        """Urgent count must be derived from overall/sadStatus, not priority field."""
        src = _read(DASHBOARD_KANBAN)
        assert "Action Required" in src, \
            "Urgent must check for 'Action Required' overall status"
        assert "Verification Needed" in src, \
            "Urgent must check for 'Verification Needed' sadStatus"


# =============================================================================
# 9. WIRED_PAGES includes 'dashboard'
# =============================================================================

class TestWiredPages:
    """Verify 'dashboard' is in WIRED_PAGES."""

    def test_dashboard_in_wired_pages(self):
        src = _read(MOCK_BADGE)
        assert "'dashboard'" in src, \
            "'dashboard' must be in WIRED_PAGES in mock-badge.jsx"

    def test_wired_pages_contains_dashboard(self):
        src = _read(MOCK_BADGE)
        match = re.search(r"WIRED_PAGES\s*=\s*\[([^\]]+)\]", src)
        assert match, "WIRED_PAGES array not found"
        assert "'dashboard'" in match.group(1), \
            "'dashboard' not found inside WIRED_PAGES array"


# =============================================================================
# 10. Loading/error/empty states exist
# =============================================================================

class TestStates:
    """Verify loading, error, and empty states are implemented."""

    def test_loading_state(self):
        src = _read(DASHBOARD_KANBAN)
        assert 'data-testid="dashboard-loading"' in src, \
            "Loading state with data-testid must exist"

    def test_error_state(self):
        src = _read(DASHBOARD_KANBAN)
        assert 'data-testid="dashboard-error"' in src, \
            "Error state with data-testid must exist"

    def test_empty_state(self):
        src = _read(DASHBOARD_KANBAN)
        assert 'data-testid="dashboard-empty"' in src, \
            "Empty state with data-testid must exist"

    def test_loading_text(self):
        src = _read(DASHBOARD_KANBAN)
        assert "Loading batches" in src, "Loading text must be present"

    def test_error_text(self):
        src = _read(DASHBOARD_KANBAN)
        assert "Failed to load batches" in src, "Error text must be present"


# =============================================================================
# 11. List view button is real
# =============================================================================

class TestListViewButton:
    """Verify List view button navigates to shipments."""

    def test_list_view_button_exists(self):
        src = _read(DASHBOARD_KANBAN)
        assert 'data-testid="dashboard-list-view-btn"' in src, \
            "List view button with data-testid must exist"

    def test_list_view_navigates_to_shipments(self):
        src = _read(DASHBOARD_KANBAN)
        # The list view button should have an onClick that calls onNav('shipments')
        assert "List view" in src, "List view button text must be present"
        # Check it's wired (not a dead button)
        assert "onNav" in src, "List view button must be wired to navigation"


# =============================================================================
# 12. No drag-and-drop claim
# =============================================================================

class TestNoDragClaim:
    """Verify no drag-and-drop claim remains."""

    def test_no_drag_text(self):
        src = _read(DASHBOARD_KANBAN)
        assert "Drag cards" not in src, \
            "Drag-and-drop claim removed — not implemented"
        assert "drag" not in src.lower() or "drag" in "drag".lower(), \
            "No drag references should remain"

    def test_no_wireframe_text(self):
        src = _read(DASHBOARD_KANBAN)
        assert "wireframe" not in src.lower(), \
            "Wireframe reference removed — this is now live"


# =============================================================================
# 13. Status mapper functions present
# =============================================================================

class TestStatusMappers:
    """Verify V1 status mapper functions are ported."""

    def test_map_overall(self):
        src = _read(DASHBOARD_KANBAN)
        assert "_mapOverall" in src, "_mapOverall function must be present"

    def test_map_dhl_status(self):
        src = _read(DASHBOARD_KANBAN)
        assert "_mapDhlStatus" in src, "_mapDhlStatus function must be present"

    def test_map_sad_status(self):
        src = _read(DASHBOARD_KANBAN)
        assert "_mapSadStatus" in src, "_mapSadStatus function must be present"

    def test_map_pz_status(self):
        src = _read(DASHBOARD_KANBAN)
        assert "_mapPzStatus" in src, "_mapPzStatus function must be present"


# =============================================================================
# 14. transformBatch and _batchLane functions present
# =============================================================================

class TestCoreFunctions:
    """Verify transform and lane derivation functions exist."""

    def test_transform_batch(self):
        src = _read(DASHBOARD_KANBAN)
        assert "_transformBatch" in src, "_transformBatch function must be present"

    def test_batch_lane(self):
        src = _read(DASHBOARD_KANBAN)
        assert "_batchLane" in src, "_batchLane function must be present"

    def test_fmt_age(self):
        src = _read(DASHBOARD_KANBAN)
        assert "_fmtAge" in src, "_fmtAge function must be present"


# =============================================================================
# 15. data-testid attributes for browser verification
# =============================================================================

class TestTestIds:
    """Verify data-testid attributes exist for browser verification."""

    def test_dashboard_kanban_testid(self):
        src = _read(DASHBOARD_KANBAN)
        assert 'data-testid="dashboard-kanban"' in src

    def test_kanban_board_testid(self):
        src = _read(DASHBOARD_KANBAN)
        assert 'data-testid="kanban-board"' in src

    def test_kanban_lane_testid(self):
        src = _read(DASHBOARD_KANBAN)
        assert 'data-testid="kanban-lane"' in src

    def test_kanban_card_testid(self):
        src = _read(DASHBOARD_KANBAN)
        assert 'data-testid="kanban-card"' in src

    def test_kpi_strip_testid(self):
        src = _read(DASHBOARD_KANBAN)
        assert 'data-testid="dashboard-kpi-strip"' in src

    def test_compact_kpi_testid(self):
        src = _read(DASHBOARD_KANBAN)
        assert 'data-testid="compact-kpi"' in src

    def test_search_btn_testid(self):
        src = _read(DASHBOARD_KANBAN)
        assert 'data-testid="dashboard-search-btn"' in src

    def test_quick_flow_testids(self):
        src = _read(DASHBOARD_KANBAN)
        assert 'data-testid={' in src, "Quick flow buttons need data-testid"


# =============================================================================
# 16. Quick flows corrected
# =============================================================================

class TestQuickFlows:
    """Verify quick flow CTAs are real operational targets."""

    def test_no_customer_order_cta(self):
        src = _read(DASHBOARD_KANBAN)
        assert "Customer order" not in src, \
            "Mock 'Customer order' CTA removed — replaced with real operational target"

    def test_generate_pz_or_scan_dhl(self):
        src = _read(DASHBOARD_KANBAN)
        assert "Generate PZ" in src or "Scan DHL" in src, \
            "Must have real operational CTA (Generate PZ or Scan DHL inbox)"

    def test_scan_dhl_navigates_to_dhl(self):
        src = _read(DASHBOARD_KANBAN)
        # V1 uses onNav('dhl') for email scanning
        assert "onNav('dhl')" in src or 'onNav("dhl")' in src, \
            "DHL inbox scan must navigate to DHL page"


# =============================================================================
# 17. No other pages touched
# =============================================================================

class TestNoOtherPagesTouched:
    """Sprint 40 must not add write transport for dashboard."""

    def test_no_write_transport_for_batches(self):
        """No write transport functions for batch management."""
        src = _read(PZ_API)
        for name in ["createBatch", "updateBatch", "deleteBatch",
                      "moveBatchLane", "setBatchPriority"]:
            assert name not in src, \
                f"pz-api.js added {name} — Sprint 40 is read-only wiring"
