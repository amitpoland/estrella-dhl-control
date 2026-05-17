"""test_phase2b_shipment_detail_pruned.py — Phase 2B prunes unused
cross-batch code from shipment-detail.html and adds a static loading
shell inside <div id="root">.

Asserts:
  - file size dropped below 1 MB
  - line count dropped below 14,000
  - loading-shell testid present inside root div
  - pruned symbols (legacy App, cross-batch pages, dead constants)
    are NOT declared anymore
  - critical retained components (BDP, AddDocumentModal,
    WorkflowStrip, etc.) still declared
  - all 9 detail tabs still present
  - critical testids still present
  - dashboard.html and dashboard-shared.js NOT touched by this PR
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
SDET   = STATIC / "shipment-detail.html"
DASH   = STATIC / "dashboard.html"
SHARED = STATIC / "dashboard-shared.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── Size & shape ────────────────────────────────────────────────────────

def test_shipment_detail_html_under_one_megabyte():
    size = SDET.stat().st_size
    assert size < 1_000_000, (
        f"shipment-detail.html still {size:,} bytes — Phase 2B target "
        f"was < 1,000,000 bytes (was 1,608,816 pre-prune)"
    )


def test_shipment_detail_html_under_fourteen_thousand_lines():
    line_count = _read(SDET).count("\n")
    assert line_count < 14_000, (
        f"shipment-detail.html still {line_count:,} lines — Phase 2B "
        f"target was < 14,000 (was 26,102 pre-prune)"
    )


# ── Loading shell ───────────────────────────────────────────────────────

def test_loading_shell_testid_present():
    src = _read(SDET)
    assert 'data-testid="shipment-detail-loading-shell"' in src


def test_loading_shell_inside_root_div():
    """Shell must live inside <div id="root"> so React's first render
    replaces it automatically (zero JS unmount)."""
    src = _read(SDET)
    root_idx  = src.index('id="root"')
    shell_idx = src.index('shipment-detail-loading-shell')
    main_script_idx = src.index('<script type="text/babel"', root_idx)
    assert root_idx < shell_idx < main_script_idx, (
        "loading shell must live inside <div id='root'> before the "
        "main Babel script block"
    )


def test_loading_shell_has_visible_text():
    src = _read(SDET)
    assert "Loading shipment detail" in src


# ── Pruned components absent ────────────────────────────────────────────

_PRUNED_COMPONENTS = (
    # Legacy router
    "App", "transformBatch",
    # Cross-batch pages
    "MasterDataPage", "ClientKycModal", "DashboardPage", "InventoryPage",
    "WfirmaExportPage", "IntelligencePage", "AdminPage", "NewShipmentModal",
    "NewShipmentDocumentSlot", "ReportsPage", "CustomerStatementDrawer",
    "AiBridgePage", "LearningPage", "AdminUsersPage", "InboxPage",
    "DiagnosticsPage", "CarriersPage", "ApiStatusPage", "CoverageMatrixPage",
    "FinancePostingBreakdownPanel", "PzAccountingPage",
    "CustomsDocumentsPage", "DhlClearancePage", "DashboardKanban",
    "KanbanCard", "KanbanLane", "CompactKpi", "StackedBarChart",
    "BarChart", "AnalyticsCard", "StubPage", "PageHeader",
    "StatsRow",
)


@pytest.mark.parametrize("sym", _PRUNED_COMPONENTS)
def test_pruned_component_not_declared(sym):
    src = _read(SDET)
    assert not re.search(rf"^function\s+{re.escape(sym)}\s*\(", src,
                         re.MULTILINE), (
        f"pruned component {sym!r} still declared in shipment-detail.html"
    )


_PRUNED_CONSTANTS = (
    "STUB_CONFIG", "INBOX_SOURCE_META", "KANBAN_LANES",
    "QUICK_FLOWS", "ADMIN_USERS_ROLES", "STATUS_HINT_MAP",
)


@pytest.mark.parametrize("name", _PRUNED_CONSTANTS)
def test_pruned_constant_not_declared(name):
    src = _read(SDET)
    assert not re.search(rf"^const\s+{re.escape(name)}\s*[=({{]", src,
                         re.MULTILINE), (
        f"pruned constant {name!r} still declared"
    )


# ── Critical retained components present ────────────────────────────────

_RETAINED_COMPONENTS = (
    "BatchDetailPage", "ShipmentDetailApp", "AddDocumentModal",
    "WorkflowStrip", "BatchControlCenter", "ContractorResolutionPanel",
    "ProformaDraftPanel", "DhlActionCard", "OperatorWorkflowCard",
    "ExecutePZGate", "ProformaReadinessCard",
)


@pytest.mark.parametrize("sym", _RETAINED_COMPONENTS)
def test_critical_retained_component_present(sym):
    src = _read(SDET)
    assert re.search(rf"^function\s+{re.escape(sym)}\s*\(", src,
                     re.MULTILINE), (
        f"critical retained component {sym!r} missing — pruning regression"
    )


def test_shipment_detail_app_is_react_root():
    """ShipmentDetailApp must still be the entry point after pruning."""
    src = _read(SDET)
    assert "root.render(<ShipmentDetailApp />)" in src


def test_all_nine_detail_tabs_present():
    src = _read(SDET)
    for tab in ("Overview", "Documents", "DHL / Customs", "Warehouse",
                "Sales", "PZ / Accounting", "Timeline",
                "Intelligence", "Proposals"):
        assert f"'{tab}'" in src, f"tab {tab!r} missing after prune"


def test_critical_testids_preserved():
    src = _read(SDET)
    for tid in (
        "packing-list-status",
        "packing-list-row-fallback",
        "packing-list-row-parsed",
        "packing-list-row-side-purchase",
        "packing-list-row-side-sales",
        "lane-readiness-sales",
        "lane-readiness-purchase",
        "detail-subheader-importer",
    ):
        assert f'"{tid}"' in src or f"'{tid}'" in src, (
            f"testid {tid!r} missing after prune"
        )


# ── Sister files unchanged ──────────────────────────────────────────────

def test_dashboard_html_phase_2b_invariants():
    """dashboard.html must not be functionally modified by Phase 2B.
    Check key markers from prior phases are still present."""
    src = _read(DASH)
    assert "function buildShipmentDetailUrl(" in src
    assert "/dashboard/shipment-detail.html?id=" in src
    # BatchDetailPage already moved to shipment-detail.html in Phase 2.
    assert "function BatchDetailPage(" not in src


def test_dashboard_shared_js_phase_2b_invariants():
    src = _read(SHARED)
    for sym in ("Sidebar", "EstrellaMark", "SubTabStrip",
                "apiFetch", "fmtPLN", "Badge", "Card", "Btn",
                "Sel", "Toast", "SessionBanner"):
        assert sym in src, f"{sym!r} missing from dashboard-shared.js"
    # No BatchDetailPage leakage into shared.
    assert "function BatchDetailPage(" not in src
    assert "function ShipmentDetailApp(" not in src
