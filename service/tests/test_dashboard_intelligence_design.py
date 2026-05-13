"""
test_dashboard_intelligence_design.py — Path B / Pass 9.

Contract for the Intelligence page (IntelligencePage) design pass:
  - Live intelligence surface remains the ONLY real data source
  - Real /api/v1/intelligence endpoints preserved (suggestions, status,
    insights, refresh, build)
  - Existing risk summary cards + 5 tabs + refresh/rebuild/build actions
    untouched
  - Design-preview strip (severity trend / supplier risk / trigger
    history / auto-quarantine) is visually marked and disabled
  - Preview tiles emit NO network calls and NO state changes
  - No mock risk scores, no mock supplier names, no mock trigger history
  - No invented intelligence endpoints
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


# ── Live intelligence endpoints preserved ──────────────────────────────────

def test_intelligence_page_component_present():
    assert "function IntelligencePage({ onToast })" in _src()


def test_intelligence_route_wired():
    src = _src()
    assert "page === 'intelligence'" in src
    assert "<IntelligencePage" in src


def test_suggestions_endpoint_intact():
    src = _src()
    assert "apiFetch(`/api/v1/intelligence/suggestions?include_low=${low}`)" in src


def test_status_endpoint_intact():
    src = _src()
    assert "apiFetch('/api/v1/intelligence/status')" in src


def test_insights_endpoint_intact():
    src = _src()
    assert "apiFetch('/api/v1/intelligence/insights')" in src


def test_refresh_endpoint_intact():
    src = _src()
    # POST /api/v1/intelligence/refresh — config rebuild
    assert "apiFetch('/api/v1/intelligence/refresh', { method: 'POST' })" in src


def test_build_endpoint_intact():
    src = _src()
    # POST /api/v1/intelligence/build — knowledge base build
    assert "apiFetch('/api/v1/intelligence/build', { method: 'POST' })" in src


# ── Action handlers + guards preserved ─────────────────────────────────────

def test_refresh_button_state_guard_intact():
    src = _src()
    # Rebuild Config button is disabled while refreshing
    assert "disabled={refreshing}" in src
    # Real handler reference
    assert "const handleRefreshConfig = async () =>" in src


def test_build_button_state_guard_intact():
    src = _src()
    # Build button is disabled while building
    assert "disabled={building}" in src
    assert "const handleBuildMaster = async () =>" in src


def test_include_low_toggle_intact():
    src = _src()
    # Show LOW toggle still wired
    assert "Show LOW severity" in src
    assert "onChange={handleToggleLow}" in src


# ── Risk summary preserves real counts ─────────────────────────────────────

def test_risk_summary_derives_from_real_warnings():
    src = _src()
    # HIGH/MEDIUM counts come from warnItems array, not literals
    assert "warnItems.filter(w => w.severity === 'HIGH').length" in src
    assert "warnItems.filter(w => w.severity === 'MEDIUM').length" in src
    # Trigger count from real array
    assert "{trigItems.length}" in src


def test_risk_summary_mode_card_preserved():
    src = _src()
    # The "Suggest-only" guarantee card is a real invariant — must survive
    assert "Suggest-only — read-only" in src
    assert "No writes. No emails sent." in src


# ── Tabs preserved ─────────────────────────────────────────────────────────

def test_all_five_tabs_present():
    src = _src()
    # 5 tabs: warnings, triggers, batches, insights, config
    for key in ("'warnings'", "'triggers'", "'batches'", "'insights'", "'config'"):
        assert f"key:{key}" in src or f"key: {key}" in src, f"Missing tab key: {key}"


def test_tabs_landmark_present():
    src = _src()
    assert 'data-testid="intelligence-tabs"' in src


# ── Page landmark + SectionLabel polish ───────────────────────────────────

def test_page_landmark_present():
    src = _src()
    assert 'data-testid="intelligence-page"' in src


def test_status_bar_landmark_present():
    src = _src()
    assert 'data-testid="intelligence-status-bar"' in src


def test_section_label_polish_applied():
    src = _src()
    assert "<SectionLabel>Engine status</SectionLabel>" in src
    assert "<SectionLabel>Intelligence streams</SectionLabel>" in src


# ── Design preview strip present and marked ────────────────────────────────

def test_intelligence_preview_strip_present():
    assert 'data-testid="intelligence-design-preview"' in _src()


def test_intelligence_preview_has_pending_badge():
    assert 'data-testid="intelligence-preview-pending-badge"' in _src()


def test_intelligence_preview_widgets_present():
    src = _src()
    assert 'data-testid="intelligence-preview-widgets"' in src
    assert 'data-testid={`intelligence-preview-widget-${c.id}`}' in src
    for wid in ("'severity_trend'", "'supplier_risk'", "'trigger_history'", "'auto_quarantine'"):
        assert f"id: {wid}" in src, f"Missing preview widget id: {wid}"


# ── Preview controls non-executable ────────────────────────────────────────

def test_preview_block_no_onclick_no_fetch():
    src = _src()
    block_start = src.index('data-testid="intelligence-design-preview"')
    block_end   = src.index('<SectionLabel>Engine status</SectionLabel>')
    block = src[block_start:block_end]
    assert 'onClick' not in block, "Preview block must NOT have onClick"
    assert 'apiFetch' not in block, "Preview block must NOT call apiFetch"
    assert 'fetch(' not in block,   "Preview block must NOT call fetch()"
    assert 'dispatchEvent' not in block


def test_preview_widgets_carry_pending_attribute():
    src = _src()
    block_start = src.index('data-testid="intelligence-design-preview"')
    block_end   = src.index('<SectionLabel>Engine status</SectionLabel>')
    block = src[block_start:block_end]
    # Single template per map, source-level count is 1
    assert 'data-pending="true"' in block


def test_preview_widgets_show_em_dash_not_fake_number():
    src = _src()
    block_start = src.index('data-testid="intelligence-preview-widgets"')
    block_end   = src.index('<SectionLabel>Engine status</SectionLabel>')
    block = src[block_start:block_end]
    assert '>—</div>' in block


# ── Anti-fake: no mock risk scores, supplier names, or trigger history ────

def test_no_mock_supplier_names_in_intelligence():
    src = _src()
    block_start = src.index('data-testid="intelligence-design-preview"')
    block_end   = src.index('<SectionLabel>Engine status</SectionLabel>')
    block = src[block_start:block_end]
    for fake in (
        "Patek Philippe SA",
        "Crown Jewelers Ltd",
        "Audemars Piguet",
        "Maison Royale SARL",
        "Estrella Boutique Warsaw",
    ):
        assert fake not in block, f"Mock supplier leaked into Intelligence preview: {fake}"


def test_no_mock_risk_scores():
    src = _src()
    block_start = src.index('data-testid="intelligence-design-preview"')
    block_end   = src.index('<SectionLabel>Engine status</SectionLabel>')
    block = src[block_start:block_end]
    # No fake severity counts or percentages baked into the preview
    for fake in ("7 HIGH", "12 MEDIUM", "94%", "0.82", "0.94"):
        assert fake not in block, f"Mock risk score leaked: {fake}"


def test_no_mock_trigger_history():
    src = _src()
    block_start = src.index('data-testid="intelligence-design-preview"')
    block_end   = src.index('<SectionLabel>Engine status</SectionLabel>')
    block = src[block_start:block_end]
    # Trigger-history widget shows em-dash only; no fixture rows
    for fake in ("accepted by", "dismissed by", "auto-fired", "operator:"):
        assert fake not in block, f"Mock trigger-history phrase leaked: {fake}"


# ── Anti-fake: no invented endpoints ───────────────────────────────────────

def test_no_invented_intelligence_endpoints():
    src = _src()
    for ep in (
        "/api/v1/intelligence/trend",
        "/api/v1/intelligence/history",
        "/api/v1/intelligence/quarantine",
        "/api/v1/intelligence/suppliers/risk",
        "/api/v1/intelligence/triggers/history",
        "/api/v1/intelligence/severity-trend",
        "/api/v1/intelligence/series",
    ):
        assert ep not in src, f"Invented intelligence endpoint leaked: {ep}"


# ── UI-3 + DETAIL_TABS unchanged ───────────────────────────────────────────

def test_ui3_operational_cards_still_present():
    src = _src()
    for tid in (
        'data-testid="warehouse-operations-card"',
        'data-testid="sales-accounting-operations-card"',
        'data-testid="dhl-customs-operations-card"',
    ):
        assert tid in src


def test_detail_tabs_unchanged():
    src = _src()
    assert "const DETAIL_TABS = ['Overview', 'Documents', 'DHL / Customs', 'Warehouse', 'Sales', 'PZ / Accounting', 'Timeline', 'Intelligence', 'Proposals']" in src
