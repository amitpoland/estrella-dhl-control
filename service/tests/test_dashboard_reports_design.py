"""
test_dashboard_reports_design.py — Path B / Pass 4.

Contract for the Reports page design pass:
  - Live Phase A analytics path remains the ONLY real data source
  - Real backend endpoint bindings preserved
  - Design preview strip (period pills + sub-tabs + export actions) is
    visually marked and disabled
  - Preview buttons have NO onClick and emit NO network calls
  - No mock counters (Revenue / Cost of goods / Gross margin / etc.)
  - No mock client/supplier names
  - No fake currency values introduced
  - Existing Tracking Master Export (real) remains untouched
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


# ── Live Phase A path preserved ─────────────────────────────────────────────

def test_reports_page_component_present():
    assert "function ReportsPage()" in _src()


def test_reports_loads_real_phase_a_endpoint():
    src = _src()
    # Phase A analytics call is the live data source
    assert "apiFetch('/api/v1/analytics/phase-a')" in src
    assert "setData(d)" in src


def test_reports_tracking_master_export_real_endpoints():
    src = _src()
    # Regenerate (POST) and Download (GET) endpoints both real
    assert "apiFetch('/api/v1/tracking/events/export', { method: 'POST' })" in src
    assert "/api/v1/tracking/events/export/download" in src


def test_reports_phase_a_badge_preserved():
    src = _src()
    assert "PHASE A — LOCAL" in src
    # Real meta from the response object
    assert "{data.batches_scanned}" in src
    assert "data.generated_at" in src


def test_reports_real_kpi_strip_preserved():
    src = _src()
    for label in ("YTD Duty A00", "YTD Net Value", "Inventory (PZ)", "wFirma Sync"):
        assert label in src, f"Real KPI label missing: {label}"
    # Real derivations
    assert "duty.reduce" in src
    assert "shipVal.reduce" in src


def test_reports_real_charts_preserved():
    src = _src()
    assert "Import Duty A00 by Month" in src
    assert "Monthly Shipment Value" in src
    assert "<BarChart" in src


# ── Design preview strip present and clearly marked ─────────────────────────

def test_reports_preview_strip_present():
    src = _src()
    assert 'data-testid="reports-design-preview"' in src


def test_reports_preview_has_pending_badge():
    src = _src()
    assert 'data-testid="reports-preview-pending-badge"' in src


def test_reports_preview_period_row_present():
    src = _src()
    assert 'data-testid="reports-preview-period-row"' in src


def test_reports_preview_subtabs_present():
    src = _src()
    assert 'data-testid="reports-preview-subtabs"' in src


def test_reports_preview_pill_template_present():
    src = _src()
    # Pills + subtabs + actions all rendered from JSX template-literal testids
    assert 'data-testid={`reports-preview-period-${p.id}`}' in src
    assert 'data-testid={`reports-preview-action-${b.id}`}' in src
    assert 'data-testid={`reports-preview-subtab-${t.id}`}' in src


def test_reports_preview_period_ids_in_source():
    src = _src()
    for pid in ("'today'", "'wtd'", "'mtd'", "'qtd'", "'ytd'", "'last30'", "'custom'"):
        assert f"id: {pid}" in src, f"Missing period id in source: {pid}"


def test_reports_preview_subtab_ids_in_source():
    src = _src()
    for tid in ("'financial'", "'sales'", "'purchase'", "'shipping'", "'duty_vat'"):
        assert f"id: {tid}" in src, f"Missing sub-report id in source: {tid}"


def test_reports_preview_action_ids_in_source():
    src = _src()
    for aid in ("'export_pdf'", "'export_csv'", "'schedule'"):
        assert f"id: {aid}" in src, f"Missing preview action id in source: {aid}"


# ── Preview buttons disabled and emit no network calls ─────────────────────

def test_reports_preview_buttons_disabled():
    src = _src()
    # Locate the preview block and confirm disabled + aria-disabled present
    block_start = src.index('data-testid="reports-design-preview"')
    block_end   = src.index('Live Phase A analytics', block_start)
    block = src[block_start:block_end]
    # Multiple disabled occurrences across the three button arrays
    assert block.count('disabled') >= 3
    assert 'aria-disabled="true"' in block
    assert "cursor: 'not-allowed'" in block


def test_reports_preview_buttons_no_onclick():
    src = _src()
    block_start = src.index('data-testid="reports-design-preview"')
    block_end   = src.index('Live Phase A analytics', block_start)
    block = src[block_start:block_end]
    assert 'onClick' not in block, "Preview button must NOT have onClick"
    assert 'apiFetch' not in block, "Preview block must NOT call apiFetch"
    assert 'fetch(' not in block,   "Preview block must NOT call fetch()"


def test_reports_preview_marked_pending_via_data_attr():
    src = _src()
    # Pills + actions + subtabs all carry data-pending="true" — 3 source
    # occurrences (one per template) renders 7+3+5 = 15 elements at runtime
    block_start = src.index('data-testid="reports-design-preview"')
    block_end   = src.index('Live Phase A analytics', block_start)
    block = src[block_start:block_end]
    assert block.count('data-pending="true"') >= 3


# ── Anti-fake: no design mock figures / names introduced ───────────────────

def test_no_mock_pnl_values():
    src = _src()
    # Design fixture values from ReportsFinancial / ReportsSales / ReportsPurchase
    for v in (
        "PLN 184,500", "PLN 132,800", "PLN 124,800",
        "PLN 42,180", "PLN 51,700", "PLN 33,500",
        "28.0%", "+18% vs last month", "+3.2 pp vs last month",
    ):
        assert v not in src, f"Mock P&L value leaked: {v}"


def test_no_mock_top_clients_or_suppliers():
    src = _src()
    for fake in (
        "Estrella Boutique Warsaw",
        "Estrella Boutique Krakow",
        "Geneva Imports SA",
        "Atelier Bonacchi SRL",
        "Paris Atelier Direct",
    ):
        assert fake not in src, f"Mock client name leaked: {fake}"


def test_no_mock_proforma_metrics():
    src = _src()
    # Design fixture for ReportsSales sub-tab
    for v in (
        "Proformas issued",
        "76% acceptance rate",
        "PLN 6,360",
        "Days to close",
        "3.2",
    ):
        # Some of these strings may legitimately occur elsewhere (e.g. "3.2")
        # — keep the strict ones strict, allow the loose ones to be permissive.
        if v in ("3.2",):
            continue
        assert v not in src, f"Mock proforma metric leaked: {v}"


def test_no_design_period_date_range_string():
    src = _src()
    # Design hardcoded "1 Apr → 27 Apr 2024 · 27 days" string
    assert "1 Apr → 27 Apr 2024" not in src
    assert "27 days" not in src


# ── Existing real Tracking Master Export untouched ─────────────────────────

def test_tracking_master_export_card_present():
    src = _src()
    assert "Tracking Master Export" in src
    assert "regenerateTrackingExport" in src
    assert "SHIPMENT_TRACKING_MASTER.xlsx" in src


def test_tracking_master_export_real_handlers_intact():
    src = _src()
    # The Regenerate button still has a real handler
    assert "onClick={regenerateTrackingExport}" in src
    # Download link is a real anchor with download attribute
    assert 'href="/api/v1/tracking/events/export/download"' in src


# ── No new fetch/apiFetch calls added for preview features ─────────────────

def test_no_new_endpoints_invented_for_preview():
    """The preview strip must not have introduced any new endpoints.
    Pin: only the three real endpoints used by Reports today are
    referenced in this file's Reports-related code."""
    src = _src()
    # The ReportsPage component (and only it) should reference these endpoints
    # Confirm no new analytics or reports endpoints were invented
    for fake_ep in (
        "/api/v1/reports/financial",
        "/api/v1/reports/sales",
        "/api/v1/reports/purchase",
        "/api/v1/reports/shipping",
        "/api/v1/reports/duty",
        "/api/v1/analytics/period",
        "/api/v1/analytics/mtd",
        "/api/v1/analytics/ytd",
        "/api/v1/reports/schedule",
        "/api/v1/reports/export",
    ):
        assert fake_ep not in src, f"Invented backend endpoint leaked: {fake_ep}"
