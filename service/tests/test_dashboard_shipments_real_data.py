"""
test_dashboard_shipments_real_data.py — Source-grep contract for the
Shipments page (DashboardPage table view) after Path B / Pass 2.

Proves:
  - Shipments page binds to real `/dashboard/batches` data (no mocks)
  - UI-3 operational triptych cards preserved
  - Bucket filtering (UI-3.3) preserved
  - Open-shipment action still calls existing handler
  - Status / search filters preserved
  - NewShipmentModal still reachable from Shipments route
  - No fake FedEx/UPS/InPost test rows
  - Route `/shipments` still wired
  - New pagination is real (uses sorted-array length, real PAGE_SIZE)
"""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SVC_ROOT = _HERE.parent
_DASH = _SVC_ROOT / "app" / "static" / "dashboard.html"


def _src() -> str:
    if not _DASH.exists():
        import pytest
        pytest.skip(f"dashboard.html not found at {_DASH}")
    return _DASH.read_text(encoding="utf-8")


# ── DashboardPage component is present and is the /shipments render ─────────

def test_dashboard_page_component_present():
    assert "function DashboardPage({ onViewShipment, batches" in _src()


def test_shipments_route_renders_dashboard_page():
    src = _src()
    assert "page === 'shipments'" in src
    # The route renders DashboardPage with real batches array
    assert "<DashboardPage" in src
    assert "batches={batches}" in src
    assert "onReload={loadBatches}" in src


# ── Real backend bindings, no mocks ─────────────────────────────────────────

def test_no_mock_shipments_array():
    src = _src()
    assert "MOCK_SHIPMENTS" not in src


def test_no_mock_awbs():
    src = _src()
    # Design mock AWBs that must NOT leak into production
    for fake in (
        "DHL-1234567890",
        "DHL-9876543210",
        "FDX-0011223344",
        "DHL-5544332211",
        "DHL-6677889900",
        "OTH-1122334455",
        "FDX-9988776655",
        "PL12345678901234A",
        "PL98765432101234B",
    ):
        assert fake not in src, f"Mock AWB/MRN '{fake}' leaked into production"


def test_no_mock_shp_ids():
    src = _src()
    # Design mock IDs: SHP-001 ... SHP-007
    for n in range(1, 10):
        assert f"SHP-00{n}" not in src, f"Mock shipment id 'SHP-00{n}' leaked into production"


def test_filter_iterates_real_batches():
    src = _src()
    # Filter / sort all operate on the real batches prop
    assert "batches.filter(s => s.overall === filter)" in src
    assert "[...filtered].sort" in src


def test_summary_counts_derive_from_real_batches():
    src = _src()
    for line in (
        "total:        batches.length",
        "batches.filter(b => b.overall === 'Awaiting DHL').length",
        "batches.filter(b => b.overall === 'Awaiting SAD').length",
        "batches.filter(b => b.pzStatus === 'Ready for PZ').length",
        "batches.filter(b => b.overall === 'Action Required').length",
        "batches.filter(b => b.overall === 'Ready for Booking').length",
        "batches.reduce((s, b) => s + (b._raw && b._raw.duty",
        "batches.reduce((s, b) => s + (b._raw && b._raw.gross",
    ):
        assert line in src, f"Real batches binding missing: {line!r}"


# ── UI-3 operational triptych preserved ─────────────────────────────────────

def test_ui3_operational_cards_present():
    src = _src()
    for tid in (
        'data-testid="warehouse-operations-card"',
        'data-testid="sales-accounting-operations-card"',
        'data-testid="dhl-customs-operations-card"',
    ):
        assert tid in src, f"UI-3 operational card landmark missing: {tid}"


def test_ui3_bucket_filtering_preserved():
    src = _src()
    # UI-3.3 clickable bucket filter chip + clear button
    for tid in (
        'data-testid="op-filter-active-chip"',
        'data-testid="op-filter-active-label"',
        'data-testid="op-filter-clear-btn"',
    ):
        assert tid in src, f"UI-3.3 bucket filter landmark missing: {tid}"


def test_ui3_op_predicates_preserved():
    src = _src()
    assert "OP_PREDICATES" in src
    # Bucket toggle handler still wired
    assert "toggleOpFilter" in src
    assert "clearOpFilter" in src


# ── Open-shipment action still calls the existing handler ──────────────────

def test_open_shipment_calls_existing_handler():
    src = _src()
    # The AWB link and the View button both call onViewShipment(row)
    assert "onViewShipment(row)" in src
    # And the wiring is real (App component passes viewShipment which sets selectedBatch)
    assert "setSelectedBatch" in src


# ── Status / search filters preserved ───────────────────────────────────────

def test_status_filter_pills_present():
    src = _src()
    # Filter pills include all design statuses
    assert "const filters = ['all', 'Ready for PZ', 'Awaiting DHL', 'Awaiting SAD', 'Action Required', 'Ready for Booking', 'Exported']" in src


def test_view_mode_toggle_preserved():
    src = _src()
    # Active / Archived toggle (production-only, preserved)
    assert "viewMode === 'active'" in src
    assert "viewMode === 'archived'" in src


# ── NewShipmentModal still reachable ────────────────────────────────────────

def test_new_shipment_modal_reachable():
    src = _src()
    assert "NewShipmentModal" in src
    assert "setShowNewShipment(true)" in src


# ── No fake carrier expansion ───────────────────────────────────────────────

def test_no_fake_ups_or_tnt_introduced_by_this_pass():
    src = _src()
    # Pre-existing FedEx handling in app code is allowed (carrier dropdown,
    # badge colors, insights). What we want is for this pass to NOT have
    # introduced any mock UPS/TNT shipments or test-row carrier data.
    assert "UPS-1" not in src
    assert "TNT-" not in src
    # The design's mock InPost AWBs (e.g. INP-552448) must not leak
    assert "INP-552448" not in src
    assert "INP-552399" not in src


# ── Pagination: real, in-memory, frontend-only ─────────────────────────────

def test_pagination_footer_present():
    src = _src()
    for tid in (
        'data-testid="shipments-table-footer"',
        'data-testid="shipments-table-pagination"',
        'data-testid="shipments-table-prev"',
        'data-testid="shipments-table-next"',
        'data-testid="shipments-table-page-indicator"',
    ):
        assert tid in src, f"Pagination landmark missing: {tid}"


def test_pagination_uses_real_sorted_length():
    src = _src()
    # PAGE_SIZE is a real constant, totalPages derives from sorted.length
    assert "const PAGE_SIZE = 25" in src
    assert "Math.ceil(sorted.length / PAGE_SIZE)" in src
    # Page-reset effect fires on filter/sort change
    assert "React.useEffect(() => { setPage(1); }, [filter, opFilter, sortCol, sortDir, viewMode])" in src


def test_paginated_rows_used_in_table():
    src = _src()
    # The table maps over `paginated`, not `sorted` or a mock array
    assert "paginated.map(row =>" in src
    # And there's a real slice
    assert "sorted.slice(pageStart, pageEnd)" in src


def test_empty_state_is_honest():
    src = _src()
    # Empty state preserved + still references the bucket-filter clear link
    assert 'data-testid="active-table-empty-state"' in src
    assert 'data-testid="active-table-empty-op-filter-note"' in src


def test_count_label_shows_real_numbers():
    src = _src()
    # The footer count uses real sorted.length and pageStart/pageEnd, not mocks
    assert "{pageStart + 1}-{pageEnd} of {sorted.length}" in src
    # And honestly notes when filtered
    assert "sorted.length !== batches.length" in src


# ── DETAIL_TABS unchanged (UI-3.5 baseline preserved) ───────────────────────

def test_detail_tabs_unchanged():
    src = _src()
    assert "const DETAIL_TABS = ['Overview', 'Documents', 'DHL / Customs', 'Warehouse', 'Sales', 'PZ / Accounting', 'Timeline', 'Intelligence', 'Proposals']" in src
