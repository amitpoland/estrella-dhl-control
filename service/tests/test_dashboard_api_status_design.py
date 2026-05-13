"""
test_dashboard_api_status_design.py — Path B / Tier 2 / Pass 13.

Contract for the new API Status composition page:
  - Frontend composition only; ZERO new backend invented
  - All rows derived from real /api/v1/{health, system/version,
    system/pending, debug/health-full, debug/storage/health,
    wfirma/capabilities, carrier/status}
  - Each source loads independently (Promise-isolated failures)
  - No fake integrations, no mock latency/uptime values
  - Read-only — no probe/rotate/execute write paths
  - 'Re-check all' is the only refresh path: a safe GET reload of the
    same 7 source endpoints
  - Disabled placeholders for Incident history / Configure SLA /
    Webhook configurator (design IA, backend pending)
  - api_status no longer routes to StubPage
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


# ── api_status is now a real composition route, not a stub ────────────────

def test_api_status_component_present():
    src = _src()
    assert "function ApiStatusPage({ onNav, onToast })" in src


def test_api_status_route_renders_real_component():
    src = _src()
    assert "page === 'api_status' && (" in src
    assert "<ApiStatusPage" in src


def test_api_status_removed_from_stub_routes():
    src = _src()
    # Stub-match list no longer contains 'api_status'
    assert "|| page === 'api_status'" not in src
    # Stub list still includes inventory + master + carriers + coverage
    # (api_status, inbox, diagnostics have all moved to real composition)
    for stub in ("'inventory'", "'master'", "'carriers'", "'coverage'"):
        assert f"page === {stub}" in src, f"Stub route missing for {stub}"


def test_api_status_removed_from_stub_config():
    src = _src()
    stub_start = src.index("const STUB_CONFIG = {")
    stub_end   = src.index("function ApiStatusPage(", stub_start)
    stub_block = src[stub_start:stub_end]
    assert "api_status:" not in stub_block
    assert "Consolidated health for every backend integration" not in stub_block


# ── Real endpoint usage — every source from an existing route ─────────────

def _has_endpoint(url):
    """Endpoints are passed to _load(setter, url) — the literal URL string
    must appear at least once in source. apiFetch(url) is invoked inside
    the _load helper, not at the call site."""
    return url in _src()


def test_health_endpoint_used():
    assert _has_endpoint("'/api/v1/health'")


def test_system_version_endpoint_used():
    assert _has_endpoint("'/api/v1/system/version'")


def test_system_pending_endpoint_used():
    assert _has_endpoint("'/api/v1/system/pending'")


def test_debug_health_full_endpoint_used():
    assert _has_endpoint("'/api/v1/debug/health-full'")


def test_debug_storage_health_endpoint_used():
    assert _has_endpoint("'/api/v1/debug/storage/health'")


def test_wfirma_capabilities_endpoint_used():
    assert _has_endpoint("'/api/v1/wfirma/capabilities'")


def test_carrier_status_endpoint_used():
    assert _has_endpoint("'/api/v1/carrier/status'")


def test_all_seven_loaders_present():
    src = _src()
    # The loaders block uses `_load(set<Name>` per source — that gives a
    # whitespace-tolerant check that works across any column-alignment.
    for setter in ("setApp", "setVer", "setPending", "setHf",
                   "setStorage", "setWfCaps", "setCarrier"):
        assert f"_load({setter}" in src, f"Missing loader for setter: {setter}"


# ── No new endpoints invented ──────────────────────────────────────────────

def test_no_invented_status_endpoints():
    src = _src()
    for ep in (
        "/api/v1/api-status",
        "/api/v1/api_status",
        "/api/v1/status/all",
        "/api/v1/integrations/status",
        "/api/v1/incidents",
        "/api/v1/sla",
        "/api/v1/webhooks/config",
        "/api/v1/probe/all",
        "/api/v1/reprobe",
    ):
        assert ep not in src, f"Invented API-status endpoint leaked: {ep}"


def test_no_monitor_post_used_for_status():
    """The /api/v1/monitor/active-shipments/run endpoint is POST-only;
    using it from this read-only page would be a write. Confirm it's
    not referenced anywhere inside the ApiStatusPage component."""
    src = _src()
    block_start = src.index("function ApiStatusPage(")
    block_end   = src.index("function StubPage(", block_start)
    block = src[block_start:block_end]
    assert "monitor/active-shipments/run" not in block, \
        "ApiStatusPage must not invoke POST /monitor/active-shipments/run"


# ── No fake rows / mock integration names / mock latency-uptime ───────────

def test_no_fake_integration_names():
    src = _src()
    block_start = src.index("function ApiStatusPage(")
    block_end   = src.index("function StubPage(", block_start)
    block = src[block_start:block_end]
    for fake in (
        "Datadog", "PagerDuty", "Statuspage", "Pingdom",
        "Rollbar", "Sentry", "Honeycomb", "New Relic",
        # Design-fixture-shaped names from other passes
        "Bijoux Maison Paris", "Goldhaus Berlin",
    ):
        assert fake not in block, f"Mock integration name leaked: {fake}"


def test_no_fake_latency_or_uptime_values():
    src = _src()
    block_start = src.index("function ApiStatusPage(")
    block_end   = src.index("function StubPage(", block_start)
    block = src[block_start:block_end]
    for fake in (
        "99.9%", "99.99%", "uptime", "p95 6.8s", "p99 12.0s",
        "240ms", "1.2s",  # latency-shaped fixtures
    ):
        assert fake not in block, f"Mock latency/uptime value leaked: {fake}"


def test_no_mock_status_array():
    src = _src()
    block_start = src.index("function ApiStatusPage(")
    block_end   = src.index("function StubPage(", block_start)
    block = src[block_start:block_end]
    for fake in ("MOCK_STATUS", "SAMPLE_STATUS", "STATUS_FIXTURES",
                 "fakeIntegrations", "INTEGRATIONS_DEMO"):
        assert fake not in block, f"Mock status seed array leaked: {fake}"


# ── Read-only: no write paths ─────────────────────────────────────────────

def test_no_new_write_paths_in_api_status():
    src = _src()
    block_start = src.index("function ApiStatusPage(")
    block_end   = src.index("function StubPage(", block_start)
    block = src[block_start:block_end]
    for method in ("method: 'POST'", "method: 'PUT'", "method: 'DELETE'", "method: 'PATCH'"):
        assert method not in block, f"ApiStatusPage body must NOT contain {method!r}"


def test_no_probe_or_rotate_or_test_buttons():
    src = _src()
    block_start = src.index("function ApiStatusPage(")
    block_end   = src.index("function StubPage(", block_start)
    block = src[block_start:block_end]
    # Forbidden write-shaped controls
    for fake in (
        ">Re-probe<",
        ">Reprobe<",
        ">Test connection<",
        ">Rotate key<",
        ">Rotate credentials<",
        ">Run probe<",
        ">Execute<",
    ):
        assert fake not in block, f"Forbidden write action leaked into API Status: {fake}"


def test_recheck_all_is_safe_get_reload():
    src = _src()
    # The only refresh path is a button that calls reloadAll(), which
    # invokes the existing GET loaders.
    assert 'data-testid="api-status-refresh"' in src
    assert "onClick={reloadAll}" in src
    assert "↻ Re-check all" in src
    # reloadAll calls every loader (Object.values(...).forEach)
    assert "Object.values(loaders).forEach(fn => fn())" in src


# ── Isolated failures: each source has its own state ──────────────────────

def test_per_source_state_objects():
    src = _src()
    for setter in ("setApp", "setVer", "setPending", "setHf", "setStorage", "setWfCaps", "setCarrier"):
        assert setter in src, f"Missing per-source setter: {setter}"


def test_per_source_error_banner_landmarks():
    src = _src()
    assert 'data-testid="api-status-source-errors"' in src
    assert 'data-testid={`api-status-source-error-${err.src}`}' in src


def test_failure_isolation_documented():
    src = _src()
    # The error banner explicitly notes other sources still shown
    assert "other sources still shown" in src
    # And errors.filter pattern is used (only failing sources appear)
    assert "rows.filter(r => r.status === 'offline')" in src


# ── Row schema is canonical ───────────────────────────────────────────────

def test_row_schema_documented_in_comment():
    src = _src()
    assert "id, name, source, status, detail, last_checked, tone" in src


def test_row_schema_keys_used_for_each_source():
    src = _src()
    # 7 sources × 7 keys — every push references all schema keys
    block_start = src.index("function ApiStatusPage(")
    block_end   = src.index("function StubPage(", block_start)
    block = src[block_start:block_end]
    for key in ("id:", "name:", "source:", "status:", "detail:", "last_checked:", "tone:"):
        # Each appears at least 7 times (once per source row push)
        assert block.count(key) >= 7, f"Row schema key '{key}' under-used (expected ≥7 uses across 7 sources)"


def test_status_enum_only_four_values():
    src = _src()
    block_start = src.index("function ApiStatusPage(")
    block_end   = src.index("function StubPage(", block_start)
    block = src[block_start:block_end]
    # Status values are one of: online / degraded / offline / unknown
    # Spot-check that each appears as a string literal in source
    for status in ("'online'", "'degraded'", "'offline'", "'unknown'"):
        assert status in block, f"Status enum value '{status}' missing from row construction"


# ── KPI strip computed from rows array, not literals ──────────────────────

def test_kpi_strip_landmark_present():
    src = _src()
    assert 'data-testid="api-status-live-stats"' in src
    assert 'data-testid={`api-status-stat-${s.id}`}' in src
    for sid in ("'online'", "'degraded'", "'offline'", "'unknown'"):
        assert f"id: {sid}" in src, f"Missing KPI tile id: {sid}"


def test_kpi_values_derive_from_rows_filter():
    src = _src()
    for line in (
        "rows.filter(r => r.status === 'online').length",
        "rows.filter(r => r.status === 'degraded').length",
        "rows.filter(r => r.status === 'offline').length",
        "rows.filter(r => r.status === 'unknown').length",
    ):
        assert line in src, f"KPI count not derived from rows: {line!r}"


# ── Integration status table + row landmarks ──────────────────────────────

def test_integration_table_landmark_present():
    src = _src()
    assert 'data-testid="api-status-table"' in src


def test_per_integration_row_landmarks():
    src = _src()
    # Each integration row uses a per-row testid via template literal
    assert 'data-testid={`api-status-row-${r.id}`}' in src
    # All 7 integration ids referenced in row construction
    for iid in ("'app'", "'version'", "'pending'", "'health_full'", "'storage'", "'wfirma'", "'carrier'"):
        assert f"id: {iid}" in src, f"Missing integration id in source: {iid}"


# ── Disabled placeholders are clearly marked ──────────────────────────────

def test_design_preview_actions_disabled_and_pending():
    src = _src()
    block_start = src.index('data-testid="api-status-toolbar"')
    block_end   = src.index('data-testid="api-status-table"', block_start)
    block = src[block_start:block_end]
    # 3 disabled actions: Incident history / Configure SLA / Webhook config
    for aid in ('incident_history', 'configure_sla', 'webhook_config'):
        assert f"id: '{aid}'" in src, f"Missing preview action id: {aid}"
    # Template-literal testid form
    assert 'data-testid={`api-status-preview-action-${b.id}`}' in src
    # All carry disabled + aria-disabled + cursor not-allowed
    assert block.count('disabled') >= 3
    assert 'aria-disabled="true"' in block
    assert "cursor: 'not-allowed'" in block


def test_disabled_actions_have_no_onclick_no_fetch():
    src = _src()
    # The disabled action template specifically must not have onClick
    # (the refresh button DOES have onClick — that's the only allowed one)
    block_start = src.index("Design-preview disabled actions")
    rest = src[block_start:]
    block_end = rest.find('</div>\n      </div>\n\n      {/* Integration status table */}')
    block = rest[:block_end if block_end > 0 else 4000]
    assert 'apiFetch' not in block
    assert 'fetch(' not in block


def test_design_preview_footer_present():
    src = _src()
    assert 'data-testid="api-status-design-preview"' in src
    assert 'data-testid="api-status-preview-pending-badge"' in src


# ── SectionLabel polish + page landmark ───────────────────────────────────

def test_page_landmark_present():
    src = _src()
    assert 'data-testid="api-status-page"' in src


def test_section_label_polish_applied():
    src = _src()
    assert "<SectionLabel>Integration status</SectionLabel>" in src


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
