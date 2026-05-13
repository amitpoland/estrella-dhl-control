"""
test_dashboard_admin_design.py — Path B / Pass 10.

Contract for the Settings / Admin page (AdminPage) design pass:
  - Live admin diagnostics surface remains the ONLY real data source
  - Real endpoints preserved: /api/v1/health, /api/v1/system/version,
    /api/v1/debug/health-full, /api/v1/debug/storage/health,
    /api/v1/admin/email-queue
  - Live KPI strip derives values from real state (no fake counts)
  - Design-preview strip (API config editor, Users & Roles, integration
    pills, audit log + save/invite/rotate-key actions) is visually marked
    and disabled
  - Preview controls emit NO network calls and NO state changes
  - No mock users, no mock health states, no mock email rows
  - No new write paths introduced
  - No invented endpoints
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


# ── Live admin endpoints preserved ─────────────────────────────────────────

def test_admin_page_component_present():
    assert "function AdminPage({ user })" in _src()


def test_admin_route_wired():
    src = _src()
    assert "page === 'admin'" in src
    assert "<AdminPage" in src


def test_health_endpoint_intact():
    assert "apiFetch('/api/v1/health')" in _src()


def test_version_endpoint_intact():
    assert "apiFetch('/api/v1/system/version')" in _src()


def test_health_full_endpoint_intact():
    assert "apiFetch('/api/v1/debug/health-full')" in _src()


def test_storage_health_endpoint_intact():
    assert "apiFetch('/api/v1/debug/storage/health')" in _src()


def test_email_queue_endpoint_intact():
    assert "apiFetch('/api/v1/admin/email-queue')" in _src()


# ── No new write paths added by this pass ──────────────────────────────────

def test_no_new_write_paths_in_admin_page():
    """The AdminPage body must not have gained any POST/PUT/DELETE/PATCH
    apiFetch calls in this design pass. AdminPage is read-only by design."""
    src = _src()
    block_start = src.index("function AdminPage({ user })")
    # End at the next top-level function declaration
    rest = src[block_start + len("function AdminPage({ user })"):]
    # Find next top-level "function " (some functions might appear inside as
    # named helpers; pick the first that's clearly outside — the diagnostics
    # / actions-v2 helpers come after). Use a marker that we know comes
    # after AdminPage.
    end_marker = "const ACTIONS_V2_SECTION_ORDER"
    block_end = src.index(end_marker, block_start)
    block = src[block_start:block_end]
    for method in ("method: 'POST'", "method: 'PUT'", "method: 'DELETE'", "method: 'PATCH'"):
        assert method not in block, f"AdminPage body must NOT contain {method!r}"


# ── Live KPI strip uses real state ─────────────────────────────────────────

def test_admin_live_stats_strip_present():
    src = _src()
    assert 'data-testid="admin-live-stats"' in src
    assert 'data-testid={`admin-stat-${s.id}`}' in src
    for sid in ("'api_status'", "'health_checks'", "'email_queue'", "'version'"):
        assert f"id: {sid}" in src, f"Missing admin stat id: {sid}"


def test_admin_kpi_api_status_derives_from_real_health_state():
    src = _src()
    # API Status value is ● Online iff `health` state truthy
    assert "value: health ? '● Online' : '○ Unknown'" in src


def test_admin_kpi_health_checks_derives_from_real_counts():
    src = _src()
    # Health checks value uses real healthPass / healthChecks.length
    assert "`${healthPass} / ${healthChecks.length}`" in src


def test_admin_kpi_email_queue_derives_from_real_queue_stats():
    src = _src()
    assert "queueStats ? `${queueStats.pending} / ${queueStats.total}` : '—'" in src


def test_admin_kpi_version_derives_from_real_commit():
    src = _src()
    # Version slice 0..7 of the real commit hash
    assert "version && !version.error && version.commit ? String(version.commit).slice(0, 7)" in src


# ── Design preview strip present and marked ────────────────────────────────

def test_admin_preview_strip_present():
    assert 'data-testid="admin-design-preview"' in _src()


def test_admin_preview_has_pending_badge():
    assert 'data-testid="admin-preview-pending-badge"' in _src()


def test_admin_preview_widgets_present():
    src = _src()
    assert 'data-testid="admin-preview-widgets"' in src
    assert 'data-testid={`admin-preview-widget-${c.id}`}' in src
    for wid in ("'api_config'", "'users_roles'", "'integration_pills'", "'audit_log'"):
        assert f"id: {wid}" in src, f"Missing preview widget id: {wid}"


def test_admin_preview_actions_present():
    src = _src()
    assert 'data-testid="admin-preview-actions"' in src
    assert 'data-testid={`admin-preview-action-${b.id}`}' in src
    for aid in ("'save_config'", "'invite_user'", "'rotate_key'"):
        assert f"id: {aid}" in src, f"Missing preview action id: {aid}"


# ── Preview controls disabled / non-executable ─────────────────────────────

def test_admin_preview_buttons_disabled():
    src = _src()
    block_start = src.index('data-testid="admin-design-preview"')
    block_end   = src.index('<SectionLabel>System diagnostics</SectionLabel>')
    block = src[block_start:block_end]
    assert block.count('disabled') >= 2
    assert 'aria-disabled="true"' in block
    assert "cursor: 'not-allowed'" in block


def test_admin_preview_no_onclick_no_fetch():
    src = _src()
    block_start = src.index('data-testid="admin-design-preview"')
    block_end   = src.index('<SectionLabel>System diagnostics</SectionLabel>')
    block = src[block_start:block_end]
    assert 'onClick' not in block, "Preview block must NOT have onClick"
    assert 'apiFetch' not in block, "Preview block must NOT call apiFetch"
    assert 'fetch(' not in block,   "Preview block must NOT call fetch()"
    assert 'dispatchEvent' not in block


def test_admin_preview_pending_attribute_present():
    src = _src()
    block_start = src.index('data-testid="admin-design-preview"')
    block_end   = src.index('<SectionLabel>System diagnostics</SectionLabel>')
    block = src[block_start:block_end]
    # Widgets + actions each use data-pending="true"
    assert block.count('data-pending="true"') >= 2


# ── Anti-fake: no mock users / mock health / mock email rows ──────────────

def test_no_mock_user_names_introduced():
    src = _src()
    # Design fixture user list
    for fake in (
        "Karolina",
        "Marek",
        "k.nowak@estrella.pl",
        "m.kowalski@estrella.pl",
        "admin@estrella.pl",
    ):
        assert fake not in src, f"Mock user leaked: {fake}"


def test_no_mock_role_labels():
    src = _src()
    # Design hardcoded role labels — should not appear in admin block
    block_start = src.index("function AdminPage({ user })")
    end_marker = "const ACTIONS_V2_SECTION_ORDER"
    block_end = src.index(end_marker, block_start)
    block = src[block_start:block_end]
    for fake in ("'Super User'", "'Accountant'", "'Logistics'"):
        assert fake not in block, f"Mock role label leaked: {fake}"


def test_no_mock_config_values():
    src = _src()
    # Design fixture values for API/DHL/wFirma
    for fake in (
        "'https://api.estrella-pz.pl/api/v1'",
        "'clearance@dhl.com.pl'",
        "'wf_••••••••••••••••'",
    ):
        assert fake not in src, f"Mock config value leaked: {fake}"


def test_no_mock_integration_status_pills():
    src = _src()
    block_start = src.index('data-testid="admin-design-preview"')
    block_end   = src.index('<SectionLabel>System diagnostics</SectionLabel>')
    block = src[block_start:block_end]
    # The design's hardcoded pills "● Online / ● Connected / ● Active / 27 Apr 2024, 14:32"
    for fake in ("'● Connected'", "27 Apr 2024, 14:32", "DHL Inbox Connector"):
        assert fake not in block, f"Mock integration pill leaked into preview: {fake}"


def test_no_mock_email_rows():
    src = _src()
    # Live email queue uses real status filter — no hardcoded email-row mocks
    # from the design (subjects, recipients).
    for fake in (
        "Pre-check notice — DHL",
        "AWB DHL-1234567890",
        "noreply@estrella.pl",
    ):
        assert fake not in src, f"Mock email-row mock leaked: {fake}"


# ── Anti-fake: no invented endpoints ───────────────────────────────────────

def test_no_invented_admin_endpoints():
    src = _src()
    for ep in (
        "/api/v1/admin/config",
        "/api/v1/admin/settings",
        "/api/v1/admin/users",
        "/api/v1/admin/users/invite",
        "/api/v1/admin/audit-log",
        "/api/v1/system/config",
        "/api/v1/system/rotate-key",
        "/api/v1/integrations/status",
    ):
        assert ep not in src, f"Invented admin endpoint leaked: {ep}"


# ── SectionLabel polish + page landmarks ───────────────────────────────────

def test_page_landmark_present():
    src = _src()
    assert 'data-testid="admin-page"' in src


def test_system_diagnostics_landmark_present():
    src = _src()
    assert 'data-testid="admin-system-diagnostics"' in src


def test_section_label_polish_applied():
    src = _src()
    assert "<SectionLabel>System diagnostics</SectionLabel>" in src


# ── Existing diagnostics cards still rendered ──────────────────────────────

def test_version_card_rendered():
    src = _src()
    assert "fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>Version</div>" in src


def test_health_full_12checks_card_rendered():
    src = _src()
    assert "Health (12 checks)" in src


def test_email_queue_state_machine_intact():
    src = _src()
    # The 3-bucket email queue derivation
    assert "emails.filter(e => e.status === 'pending').length" in src
    assert "emails.filter(e => e.status === 'sent').length" in src


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
