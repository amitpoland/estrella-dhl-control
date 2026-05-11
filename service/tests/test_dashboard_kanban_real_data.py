"""
test_dashboard_kanban_real_data.py — Source-grep tests proving the Dashboard
Kanban landing page binds to real backend `batches`, contains no mock /
sample data, preserves UI-3 landmarks, and keeps NewShipmentModal reachable.

Path B / Pass 1: Dashboard page visual alignment with Estrella Atlas design
while preserving all backend wiring. These tests are the contract that
future edits must not regress.
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


# ── DashboardKanban component is present and is the landing render ──────────

def test_kanban_component_present():
    assert "function DashboardKanban(" in _src()


def test_kanban_is_dashboard_landing():
    src = _src()
    # The dashboard route renders the Kanban (not the legacy DashboardPage)
    assert "page === 'dashboard'" in src
    assert "<DashboardKanban" in src


def test_kanban_takes_real_batches_prop():
    src = _src()
    # The render block passes the real `batches` array (not a literal)
    assert "<DashboardKanban" in src
    # The component signature reads from props
    assert "function DashboardKanban({ batches" in src
    assert "(batches || []).map(transformBatch)" in src


# ── Lane derivation is from real batch fields (no hardcoded array) ──────────

def test_lanes_derived_from_real_status_fields():
    src = _src()
    # The lane-classifier function reads real backend status fields
    assert "function _batchLane(b)" in src
    for field in ("b.pzStatus", "b.sadStatus", "b.dhlStatus", "b.overall"):
        assert field in src


def test_no_pipeline_shipments_mock_array():
    src = _src()
    assert "PIPELINE_SHIPMENTS" not in src


def test_no_mock_markers():
    src = _src()
    for marker in ("MOCK_SHIPMENTS", "SAMPLE_SHIPMENTS", "fakeData", "FAKE_ROWS"):
        assert marker not in src


def test_no_mock_client_names():
    src = _src()
    # The design's mock data referenced these client names — none should land
    for fake in (
        "Maison Royale SARL",
        "Atelier Lumière",
        "Crown Jewelers Ltd",
        "Patek Philippe SA",
        "Audemars Piguet",
        "Aurum Watches GmbH",
        "Hôtel Belle Étoile",
        "Bijoux Sélection",
        "Manufaktura Złota",
    ):
        assert fake not in src, f"Mock client name '{fake}' leaked into production"


def test_no_hardcoded_ship_ids():
    src = _src()
    # The design's mock data used SHIP-2026-NNNN ids; production uses real batch_ids
    assert "SHIP-2026-0" not in src


# ── Quick-start CTAs wire to real navigation, not synthetic flows ───────────

def test_quick_flows_present():
    assert "const QUICK_FLOWS" in _src()


def test_quick_flow_outbound_opens_new_shipment_modal():
    src = _src()
    # The 'outbound' button must call onNewShipment which opens NewShipmentModal
    assert "onNewShipment && onNewShipment()" in src
    # NewShipmentModal is reachable from the App (state hook)
    assert "setShowNewShipment(true)" in src
    assert "NewShipmentModal" in src


# ── KPI strip values come from real batch state ─────────────────────────────

def test_kpis_derive_from_real_batches():
    src = _src()
    # The active/urgent/awaiting* counters all derive from `rows` / `active`
    assert "const rows = (batches || []).map(transformBatch)" in src
    assert "const active = rows" in src
    assert "urgentCount" in src
    # KPI labels exist
    for label in ("Active", "Urgent", "Awaiting DHL", "Awaiting SAD", "Ready for booking"):
        assert label in src


# ── Kanban card binds to real batch fields ──────────────────────────────────

def test_kanban_card_uses_real_batch_fields():
    src = _src()
    # The card reads from the transformed batch object
    assert 'data-testid="kanban-card"' in src
    assert "function KanbanCard({ batch, onClick })" in src
    # Real fields, not mock fields
    for field in ("batch.batch_id", "batch.carrier", "batch.timestamp", "batch.doc_no", "batch.net"):
        assert field in src


def test_kanban_card_no_fake_action_button():
    src = _src()
    # Card is a click-to-open-detail surface, not a write surface
    # Confirm the card click handler routes through viewShipment (real detail page)
    assert "onCardClick={(b) => onViewShipment(b._raw || b)" in src


# ── UI-3 landmarks survive ──────────────────────────────────────────────────

def test_ui3_landmarks_preserved():
    src = _src()
    for testid in (
        "warehouse-operations-card",
        "sales-accounting-operations-card",
        "dhl-customs-operations-card",
        "op-filter-active-chip",
        "active-table-empty-state",
    ):
        assert testid in src, f"UI-3 landmark '{testid}' missing"


def test_pipeline_summary_panel_preserved():
    src = _src()
    # UI-3.4 Pipeline Summary panel is rendered on the batch detail page
    assert "pipeline-summary" in src


def test_sales_status_hint_binding_preserved():
    # UI-3.6 — backend passes `sales_status_hint`; dashboard reads it.
    src = _src()
    assert "sales_status_hint" in src
    assert "salesHint" in src


# ── All 9 DETAIL_TABS still defined (UI-3.5 Windows baseline) ───────────────

def test_detail_tabs_unchanged():
    src = _src()
    assert "const DETAIL_TABS = ['Overview', 'Documents', 'DHL / Customs', 'Warehouse', 'Sales', 'PZ / wFirma', 'Timeline', 'Intelligence', 'Proposals']" in src


# ── Routes still resolve for every sidebar item ─────────────────────────────

def test_sidebar_routes_resolve():
    src = _src()
    # Every sidebar leaf in the new IA must still render something in App
    for route in (
        "page === 'dashboard'",
        "page === 'shipments'",
        "page === 'documents'",
        "page === 'accounting'",
        "page === 'reports'",
        "page === 'admin'",
        "page === 'automation'",
        "page === 'wfirma_setup'",
    ):
        assert route in src, f"Route render missing for {route}"


def test_stubs_clearly_marked():
    src = _src()
    # Stub pages render a pending badge — not a fake working module
    assert "Design IA · Backend pending" in src
    assert "function StubPage" in src
    # And include Inbox / Inventory / Master / Carriers etc. in stub-config
    for stub_id in ("inbox", "inventory", "master", "carriers", "api_status", "diagnostics", "coverage"):
        assert stub_id in src


# ── ROUTE_REDIRECTS preserves legacy slugs ──────────────────────────────────

def test_route_redirects_preserved():
    src = _src()
    assert "const ROUTE_REDIRECTS" in src
    # Critical legacy slugs that external bookmarks / emails may still use
    for legacy in ("'pz':", "'customs':", "'wfirma':", "'ai_bridge':", "'learning':"):
        assert legacy in src, f"ROUTE_REDIRECT for {legacy} missing"
