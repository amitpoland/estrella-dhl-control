"""
test_dashboard_diagnostics_design.py — Path B / Tier 2 / Pass 14.

Contract for the new Diagnostics composition page:
  - Frontend composition only; ZERO new backend invented
  - All rows / values derived from real /api/v1/debug/* and
    /api/v1/system/version endpoints
  - Each source loads independently (Promise-isolated failures)
  - No fake diagnostics rows, no mock lock IDs, no fake worker/job rows
  - Read-only — no repair / unlock / probe / execute write paths
  - 'Re-check' is the only refresh path: a safe GET reload of the same
    5 source endpoints
  - Disabled placeholders for Force-unlock / Clear quarantine /
    Export diagnostics / Run all probes (design IA, backend pending)
  - diagnostics no longer routes to StubPage
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


# ── diagnostics is now a real composition route, not a stub ───────────────

def test_diagnostics_component_present():
    src = _src()
    assert "function DiagnosticsPage({ onNav, onToast })" in src


def test_diagnostics_route_renders_real_component():
    src = _src()
    assert "page === 'diagnostics' && (" in src
    assert "<DiagnosticsPage" in src


def test_diagnostics_removed_from_stub_routes():
    src = _src()
    assert "|| page === 'diagnostics'" not in src
    for stub in ("'inventory'", "'master'", "'carriers'", "'coverage'"):
        assert f"page === {stub}" in src, f"Stub route missing for {stub}"


def test_diagnostics_removed_from_stub_config():
    src = _src()
    stub_start = src.index("const STUB_CONFIG = {")
    stub_end   = src.index("function DiagnosticsPage(", stub_start)
    stub_block = src[stub_start:stub_end]
    assert "diagnostics:" not in stub_block
    assert "System Diagnostics" not in stub_block
    assert "CLI diagnostic tools" not in stub_block


# ── Real endpoint usage — every source from an existing route ─────────────

def test_health_full_endpoint_used():
    assert "'/api/v1/debug/health-full'" in _src()


def test_storage_health_endpoint_used():
    assert "'/api/v1/debug/storage/health'" in _src()


def test_storage_locks_endpoint_used():
    assert "'/api/v1/debug/storage/locks'" in _src()


def test_debug_pending_endpoint_used():
    assert "'/api/v1/debug/pending'" in _src()


def test_system_version_endpoint_used():
    assert "'/api/v1/system/version'" in _src()


def test_all_five_loaders_present():
    src = _src()
    for setter in ("setHf", "setStorage", "setLocks", "setPend", "setVer"):
        assert f"_load({setter}" in src, f"Missing loader for setter: {setter}"


# ── No new endpoints invented ──────────────────────────────────────────────

def test_no_invented_diagnostics_endpoints():
    src = _src()
    for ep in (
        "/api/v1/diagnostics",
        "/api/v1/diagnostics/all",
        "/api/v1/diagnostics/run",
        "/api/v1/diagnostics/export",
        "/api/v1/debug/unlock",
        "/api/v1/debug/force-release",
        "/api/v1/debug/clear-quarantine",
        "/api/v1/debug/run-all",
        "/api/v1/system/repair",
    ):
        assert ep not in src, f"Invented diagnostics endpoint leaked: {ep}"


def test_no_monitor_post_used_for_diagnostics():
    src = _src()
    block_start = src.index("function DiagnosticsPage(")
    block_end   = src.index("function ApiStatusPage(", block_start)
    block = src[block_start:block_end]
    assert "monitor/active-shipments/run" not in block, \
        "DiagnosticsPage must not invoke POST /monitor/active-shipments/run"


# ── No fake / mock data ────────────────────────────────────────────────────

def test_no_mock_lock_ids():
    src = _src()
    block_start = src.index("function DiagnosticsPage(")
    block_end   = src.index("function ApiStatusPage(", block_start)
    block = src[block_start:block_end]
    # Common fixture shapes that must not appear
    for fake in (
        "SHIPMENT_AUTO_2024",
        "batch-stuck-001",
        "lock-stale-",
        "PID 12345",
        "actively_held: 3",  # any hardcoded count
    ):
        assert fake not in block, f"Mock lock fixture leaked: {fake}"


def test_no_mock_diagnostics_array():
    src = _src()
    block_start = src.index("function DiagnosticsPage(")
    block_end   = src.index("function ApiStatusPage(", block_start)
    block = src[block_start:block_end]
    for fake in ("MOCK_DIAGNOSTICS", "SAMPLE_LOCKS", "FAKE_CHECKS",
                 "fakeWorkers", "DEMO_WORKERS"):
        assert fake not in block, f"Mock diagnostics seed array leaked: {fake}"


def test_no_fake_health_check_messages():
    src = _src()
    block_start = src.index("function DiagnosticsPage(")
    block_end   = src.index("function ApiStatusPage(", block_start)
    block = src[block_start:block_end]
    # Check names rendered are derived from real keys (k.replace(/^\d+_/, ...))
    # not from a hardcoded list. Verify the regex-based derivation is present.
    assert "/^\\d+_/" in block, "Health-check derivation must use the real key regex"
    assert "c.key.replace(/^\\d+_/, '').replace(/_/g, ' ')" in block


def test_no_fake_worker_or_session_counts():
    src = _src()
    block_start = src.index("function DiagnosticsPage(")
    block_end   = src.index("function ApiStatusPage(", block_start)
    block = src[block_start:block_end]
    # The pending panel reads counts via fallback chain over real fields
    assert "pdActive.active_count" in block
    assert "pdActive.sessions" in block
    assert "pend.data && !pend.error && pend.data.summary" in block


# ── Read-only: no write paths ─────────────────────────────────────────────

def test_no_new_write_paths_in_diagnostics():
    src = _src()
    block_start = src.index("function DiagnosticsPage(")
    block_end   = src.index("function ApiStatusPage(", block_start)
    block = src[block_start:block_end]
    for method in ("method: 'POST'", "method: 'PUT'", "method: 'DELETE'", "method: 'PATCH'"):
        assert method not in block, f"DiagnosticsPage body must NOT contain {method!r}"


def test_no_repair_or_unlock_or_execute_buttons():
    src = _src()
    block_start = src.index("function DiagnosticsPage(")
    block_end   = src.index("function ApiStatusPage(", block_start)
    block = src[block_start:block_end]
    for fake in (
        ">Unlock<",
        ">Force unlock<",
        ">Repair<",
        ">Fix<",
        ">Release lock<",
        ">Execute<",
        ">Run probe<",
        ">Reset<",
    ):
        assert fake not in block, f"Forbidden write action leaked into Diagnostics: {fake}"


def test_recheck_is_safe_get_reload():
    src = _src()
    assert 'data-testid="diagnostics-refresh"' in src
    assert "onClick={reloadAll}" in src
    assert "↻ Re-check" in src
    # reloadAll calls every loader via Object.values
    assert "Object.values(loaders).forEach(fn => fn())" in src


# ── Isolated failures ─────────────────────────────────────────────────────

def test_per_source_state_objects():
    src = _src()
    for setter in ("setHf", "setStorage", "setLocks", "setPend", "setVer"):
        assert setter in src, f"Missing per-source setter: {setter}"


def test_per_source_error_banner_landmarks():
    src = _src()
    assert 'data-testid="diagnostics-source-errors"' in src
    assert 'data-testid={`diagnostics-source-error-${err.src}`}' in src


def test_failure_isolation_pattern():
    src = _src()
    # The sourceState array + .filter(s => s.state.error) pattern only
    # surfaces failing sources while the rest still render.
    block_start = src.index("function DiagnosticsPage(")
    block_end   = src.index("function ApiStatusPage(", block_start)
    block = src[block_start:block_end]
    assert "const sourceState =" in block
    assert "sourceState.filter(s => s.state.error)" in block
    assert "other sources still shown" in block


# ── KPI strip is computed, not literal ────────────────────────────────────

def test_kpi_strip_landmark_present():
    src = _src()
    assert 'data-testid="diagnostics-live-stats"' in src
    assert 'data-testid={`diagnostics-stat-${s.id}`}' in src
    for sid in ("'health_pass'", "'storage_ok'", "'locks_held'", "'pending'"):
        assert f"id: {sid}" in src, f"Missing KPI tile id: {sid}"


def test_kpi_values_derive_from_real_state():
    src = _src()
    # Health-pass derives from real hf data and computed hfPass/hfChecks
    assert "`${hfPass}/${hfChecks.length || 0}`" in src
    # Storage uses real stOk = storage.data.ok
    assert "storage.data ? storage.data.ok : null" in src
    # Locks count from real locks.data.actively_held
    assert "locks.data.actively_held || 0" in src
    # Pending count from real pdActiveCount / pdChatCount
    assert "pdActiveCount" in src
    assert "pdChatCount" in src


# ── Section panels present ───────────────────────────────────────────────

def test_health_panel_landmark_present():
    src = _src()
    assert 'data-testid="diagnostics-health-panel"' in src
    # Loading / error / empty / row landmarks
    assert 'data-testid="diagnostics-health-loading"' in src
    assert 'data-testid="diagnostics-health-error"' in src
    assert 'data-testid="diagnostics-health-empty"' in src
    assert 'data-testid="diagnostics-health-row"' in src


def test_storage_panel_landmark_present():
    src = _src()
    assert 'data-testid="diagnostics-storage-panel"' in src
    assert 'data-testid="diagnostics-storage-loading"' in src
    assert 'data-testid="diagnostics-storage-error"' in src


def test_locks_panel_landmark_present():
    src = _src()
    assert 'data-testid="diagnostics-locks-panel"' in src
    assert 'data-testid="diagnostics-locks-loading"' in src
    assert 'data-testid="diagnostics-locks-error"' in src
    assert 'data-testid="diagnostics-locks-empty"' in src
    assert 'data-testid="diagnostics-lock-row"' in src


def test_pending_panel_landmark_present():
    src = _src()
    assert 'data-testid="diagnostics-pending-panel"' in src
    assert 'data-testid="diagnostics-pending-loading"' in src
    assert 'data-testid="diagnostics-pending-error"' in src
    assert 'data-testid="diagnostics-pending-sessions"' in src
    assert 'data-testid="diagnostics-pending-chats"' in src


def test_version_panel_landmark_present():
    src = _src()
    assert 'data-testid="diagnostics-version-panel"' in src
    assert 'data-testid="diagnostics-version-loading"' in src
    assert 'data-testid="diagnostics-version-error"' in src
    assert 'data-testid="diagnostics-version-commit"' in src
    assert 'data-testid="diagnostics-version-deployed"' in src


# ── Disabled placeholders ────────────────────────────────────────────────

def test_design_preview_actions_disabled_and_pending():
    src = _src()
    # 4 disabled actions
    for aid in ('force_unlock', 'clear_quarantine', 'export_report', 'run_all_probes'):
        assert f"id: '{aid}'" in src, f"Missing preview action id: {aid}"
    # Template-literal testid form
    assert 'data-testid={`diagnostics-preview-action-${b.id}`}' in src
    block_start = src.index('data-testid="diagnostics-toolbar"')
    block_end   = src.index('<SectionLabel>Subsystem health</SectionLabel>', block_start)
    block = src[block_start:block_end]
    # JSX uses a single template rendering 4 buttons via .map(); at source
    # level, `disabled` appears as the bare attribute + inside `aria-disabled`
    # + in the section comment ("Design-preview disabled actions"). Expect ≥3.
    assert block.count('disabled') >= 3
    assert 'aria-disabled="true"' in block
    assert "cursor: 'not-allowed'" in block


def test_disabled_actions_have_no_onclick_no_fetch():
    src = _src()
    block_start = src.index("Design-preview disabled actions")
    rest = src[block_start:]
    # Take a bounded window so we don't accidentally include the
    # diagnostics-table block (which has onClick on the refresh button).
    block = rest[:3500]
    assert 'onClick' not in block, "Disabled action template must NOT have onClick"
    assert 'apiFetch' not in block, "Disabled action template must NOT call apiFetch"


def test_design_preview_footer_present():
    src = _src()
    assert 'data-testid="diagnostics-design-preview"' in src
    assert 'data-testid="diagnostics-preview-pending-badge"' in src


# ── SectionLabel polish + page landmark ───────────────────────────────────

def test_page_landmark_present():
    src = _src()
    assert 'data-testid="diagnostics-page"' in src


def test_all_five_section_labels_present():
    src = _src()
    for label in (
        "<SectionLabel>Subsystem health</SectionLabel>",
        "<SectionLabel>Storage health</SectionLabel>",
        "<SectionLabel>Storage locks</SectionLabel>",
        "<SectionLabel>Pending work</SectionLabel>",
        "<SectionLabel>Build version</SectionLabel>",
    ):
        assert label in src, f"Missing SectionLabel: {label}"


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
    assert "const DETAIL_TABS = ['Overview', 'Documents', 'DHL / Customs', 'Warehouse', 'Sales', 'PZ / wFirma', 'Timeline', 'Intelligence', 'Proposals']" in src
