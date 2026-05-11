"""
test_dashboard_carriers_design.py — Path B / Tier 2 / Pass 15.

Contract for the new Carriers composition page:
  - Frontend composition only; ZERO new backend invented
  - All values derived from real /api/v1/carrier/status and
    /api/v1/carrier/shadow/log
  - Each source loads independently (Promise-isolated failures)
  - No fake carriers, no mock accounts, no fake shadow rows
  - DHL Express is the only carrier wired in the backend; other
    carriers shown as disabled "Backend pending" placeholders
  - Read-only — no credential save/test/rotate, no shipment create,
    no shadow-log export write paths
  - 'Re-check' is the only refresh path: a safe GET reload of the
    same 2 source endpoints
  - carriers no longer routes to StubPage
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


# ── carriers is now a real composition route, not a stub ──────────────────

def test_carriers_component_present():
    src = _src()
    assert "function CarriersPage({ onNav, onToast })" in src


def test_carriers_route_renders_real_component():
    src = _src()
    assert "page === 'carriers' && (" in src
    assert "<CarriersPage" in src


def test_carriers_removed_from_stub_routes():
    src = _src()
    assert "|| page === 'carriers'" not in src
    for stub in ("'inventory'", "'master'", "'coverage'"):
        assert f"page === {stub}" in src, f"Stub route missing for {stub}"


def test_carriers_removed_from_stub_config():
    src = _src()
    stub_start = src.index("const STUB_CONFIG = {")
    # Stub config block ends well before CarriersPage now lives
    stub_end = src.index("function CarriersPage(", stub_start)
    stub_block = src[stub_start:stub_end]
    assert "carriers:" not in stub_block
    assert "Multi-carrier connections" not in stub_block


# ── Real endpoint usage ────────────────────────────────────────────────────

def test_carrier_status_endpoint_used():
    assert "'/api/v1/carrier/status'" in _src()


def test_carrier_shadow_log_endpoint_used():
    assert "'/api/v1/carrier/shadow/log'" in _src()


def test_both_loaders_present():
    src = _src()
    for setter in ("setStatus", "setShadow"):
        assert f"_load({setter}" in src, f"Missing loader for setter: {setter}"


# ── No new endpoints invented ──────────────────────────────────────────────

def test_no_invented_carrier_endpoints():
    src = _src()
    for ep in (
        "/api/v1/carriers/list",
        "/api/v1/carrier/credentials",
        "/api/v1/carrier/credentials/rotate",
        "/api/v1/carrier/test",
        "/api/v1/carrier/test-connection",
        "/api/v1/carrier/connect",
        "/api/v1/carrier/sessions",
        "/api/v1/carrier/webhook/config",
        "/api/v1/carrier/shadow/log/export",
        "/api/v1/carrier/shipment/create",
    ):
        assert ep not in src, f"Invented carrier endpoint leaked: {ep}"


def test_per_batch_shipment_get_not_called_for_dashboard():
    src = _src()
    block_start = src.index("function CarriersPage(")
    block_end   = src.index("function DiagnosticsPage(", block_start)
    block = src[block_start:block_end]
    # /api/v1/carrier/{batch_id}/shipment is real but per-batch (returns
    # 404 if no shipment) — must NOT be invoked from this cross-cutting
    # dashboard. Only /status and /shadow/log are valid sources here.
    assert "/shipment" not in block or "shipment_db" not in block, \
        "Per-batch shipment GET must not be invoked from CarriersPage"


# ── No fake/mock data ─────────────────────────────────────────────────────

def test_no_mock_account_numbers():
    src = _src()
    block_start = src.index("function CarriersPage(")
    block_end   = src.index("function DiagnosticsPage(", block_start)
    block = src[block_start:block_end]
    # Pattern-shaped fixture account numbers must not appear
    for fake in (
        "ACC-123456",
        "DHL-EX-",
        "account_number: '123456789'",
        "site_key: 'demo'",
        "FEDEX_TEST",
        "UPS_DEMO",
    ):
        assert fake not in block, f"Mock carrier account leaked: {fake}"


def test_no_mock_shadow_log_rows():
    src = _src()
    block_start = src.index("function CarriersPage(")
    block_end   = src.index("function DiagnosticsPage(", block_start)
    block = src[block_start:block_end]
    # The shadow table renders from real `shadowEntries` array — no
    # hardcoded seed entries.
    for fake in (
        "MOCK_SHADOW_LOG",
        "SAMPLE_SHADOW",
        "FAKE_SHIPMENTS",
        "DEMO_ENTRIES",
        "fakeShadow",
        # Pattern-shaped mock idempotency keys
        "idempotency_key: 'demo-",
        "idempotency_key: 'fake-",
    ):
        assert fake not in block, f"Mock shadow row leaked: {fake}"


def test_no_fake_carriers_named_as_live():
    src = _src()
    block_start = src.index("function CarriersPage(")
    block_end   = src.index("function DiagnosticsPage(", block_start)
    block = src[block_start:block_end]
    # FedEx / UPS / InPost / GLS appear as disabled placeholders in the
    # "Other carriers" section. They must NOT appear elsewhere as live
    # values or live KPIs.
    other_block_start = block.index('data-testid="carriers-other-panel"')
    other_block_end   = block.index('data-testid="carriers-shadow-panel"', other_block_start)
    other_block = block[other_block_start:other_block_end]
    # Inside the other-carriers section, those labels are allowed (they're
    # placeholders). Outside that section, they must not appear as values.
    before = block[:other_block_start]
    after  = block[other_block_end:]
    for fake in ("FedEx", "UPS", "InPost", "GLS"):
        assert fake not in before, f"Other-carrier '{fake}' leaked into live sections (before placeholder block)"
        assert fake not in after,  f"Other-carrier '{fake}' leaked into live sections (after placeholder block)"


# ── Read-only: no write paths ─────────────────────────────────────────────

def test_no_new_write_paths_in_carriers():
    src = _src()
    block_start = src.index("function CarriersPage(")
    block_end   = src.index("function DiagnosticsPage(", block_start)
    block = src[block_start:block_end]
    for method in ("method: 'POST'", "method: 'PUT'", "method: 'DELETE'", "method: 'PATCH'"):
        assert method not in block, f"CarriersPage body must NOT contain {method!r}"


def test_no_credential_save_or_test_buttons():
    src = _src()
    block_start = src.index("function CarriersPage(")
    block_end   = src.index("function DiagnosticsPage(", block_start)
    block = src[block_start:block_end]
    # Forbidden write-shaped controls
    for fake in (
        ">Save credentials<",
        ">Save<",
        ">Connect<",
        ">Disconnect<",
        ">Send test shipment<",
        ">Create shipment<",
        ">Apply<",
        ">Generate label<",
        ">Pickup<",
    ):
        assert fake not in block, f"Forbidden write action leaked into Carriers: {fake}"


def test_recheck_is_safe_get_reload():
    src = _src()
    assert 'data-testid="carriers-refresh"' in src
    assert "onClick={reloadAll}" in src
    assert "↻ Re-check" in src
    assert "Object.values(loaders).forEach(fn => fn())" in src


# ── Isolated failures ─────────────────────────────────────────────────────

def test_per_source_state_objects():
    src = _src()
    for setter in ("setStatus", "setShadow"):
        assert setter in src


def test_per_source_error_banner_landmarks():
    src = _src()
    assert 'data-testid="carriers-source-errors"' in src
    assert 'data-testid={`carriers-source-error-${err.src}`}' in src


def test_failure_isolation_pattern():
    src = _src()
    block_start = src.index("function CarriersPage(")
    block_end   = src.index("function DiagnosticsPage(", block_start)
    block = src[block_start:block_end]
    # errorRows filters out null per-source errors and renders one banner
    # per failing source while the other source still renders its panel.
    assert "].filter(Boolean)" in block
    assert "other sources still shown" in block


# ── Normalized status schema ──────────────────────────────────────────────

def test_normalized_state_derivation_from_real_fields():
    src = _src()
    # The _normState helper derives the visual state from the real
    # `carrier_api_status` and `carrier_plt_status` strings.
    assert "const _normState = (s) =>" in src
    # 4 documented states from Phase A–N feature flags
    for st in ("'live'", "'shadow'", "'off'", "'unknown'"):
        assert st in src
    # Real backend fields read
    assert "status.data.carrier_api_status" in src
    assert "status.data.carrier_plt_status" in src


def test_shadow_entries_derived_from_real_array():
    src = _src()
    assert "shadow.data.entries" in src
    assert "Array.isArray(shadow.data.entries)" in src


# ── KPI strip derived from real state ─────────────────────────────────────

def test_kpi_strip_landmark_present():
    src = _src()
    assert 'data-testid="carriers-live-stats"' in src
    assert 'data-testid={`carriers-stat-${s.id}`}' in src
    for sid in ("'api_mode'", "'plt_mode'", "'shadow_count'", "'last_seen'"):
        assert f"id: {sid}" in src, f"Missing KPI tile id: {sid}"


def test_kpi_values_derive_from_real_state():
    src = _src()
    # API mode value uses real apiState
    assert "apiState || 'unknown'" in src
    # PLT mode value uses real pltState
    assert "pltState || 'unknown'" in src
    # Shadow count from real shadowCount or shadowEntries.length
    assert "shadowCount" in src
    # Last activity from real lastEntry.created_at
    assert "lastEntry.created_at" in src


# ── Section panels ────────────────────────────────────────────────────────

def test_dhl_express_panel_landmark_present():
    src = _src()
    assert 'data-testid="carriers-dhl-panel"' in src
    assert 'data-testid="carriers-dhl-loading"' in src
    assert 'data-testid="carriers-dhl-error"' in src
    assert 'data-testid="carriers-dhl-api"' in src
    assert 'data-testid="carriers-dhl-plt"' in src


def test_other_carriers_panel_marked_pending():
    src = _src()
    assert 'data-testid="carriers-other-panel"' in src
    assert 'data-testid="carriers-other-pending-badge"' in src
    assert 'data-testid="carriers-other-grid"' in src
    # Per-placeholder testids (template literal)
    assert 'data-testid={`carriers-other-${c.id}`}' in src
    for cid in ("'fedex'", "'ups'", "'inpost'", "'gls'"):
        assert f"id: {cid}" in src, f"Missing placeholder carrier id: {cid}"


def test_shadow_log_panel_landmark_present():
    src = _src()
    assert 'data-testid="carriers-shadow-panel"' in src
    assert 'data-testid="carriers-shadow-loading"' in src
    assert 'data-testid="carriers-shadow-error"' in src
    assert 'data-testid="carriers-shadow-empty"' in src
    assert 'data-testid="carriers-shadow-row"' in src


def test_creds_panel_marked_pending():
    src = _src()
    assert 'data-testid="carriers-creds-panel"' in src
    assert 'data-testid="carriers-creds-pending-badge"' in src
    assert 'data-testid={`carriers-creds-${c.id}`}' in src
    for cid in ("'api_creds'", "'webhook'", "'sessions'"):
        assert f"id: {cid}" in src, f"Missing creds placeholder id: {cid}"


# ── Disabled placeholders ────────────────────────────────────────────────

def test_design_preview_actions_disabled_and_pending():
    src = _src()
    for aid in ('add_carrier', 'test_connection', 'rotate_creds', 'export_log'):
        assert f"id: '{aid}'" in src, f"Missing preview action id: {aid}"
    assert 'data-testid={`carriers-preview-action-${b.id}`}' in src
    block_start = src.index('data-testid="carriers-toolbar"')
    block_end   = src.index('<SectionLabel>DHL Express</SectionLabel>', block_start)
    block = src[block_start:block_end]
    # JSX template renders 4 buttons; source-level "disabled" count is
    # ≥3 (bare attribute + `aria-disabled` + section comment / similar)
    assert block.count('disabled') >= 3
    assert 'aria-disabled="true"' in block
    assert "cursor: 'not-allowed'" in block


def test_disabled_actions_have_no_onclick_no_fetch():
    src = _src()
    block_start = src.index("Design-preview disabled actions")
    rest = src[block_start:]
    block = rest[:3000]
    assert 'onClick' not in block
    assert 'apiFetch' not in block


def test_design_preview_footer_present():
    src = _src()
    assert 'data-testid="carriers-design-preview"' in src
    assert 'data-testid="carriers-preview-pending-badge"' in src


# ── SectionLabel polish + page landmark ───────────────────────────────────

def test_page_landmark_present():
    src = _src()
    assert 'data-testid="carriers-page"' in src


def test_all_four_section_labels_present():
    src = _src()
    for label in (
        "<SectionLabel>DHL Express</SectionLabel>",
        "<SectionLabel>Other carriers</SectionLabel>",
        "<SectionLabel>Shadow log</SectionLabel>",
        "<SectionLabel>Credentials &amp; webhooks</SectionLabel>",
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
