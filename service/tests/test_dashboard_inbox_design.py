"""
test_dashboard_inbox_design.py — Path B / Tier 2 / Pass 12.

Contract for the new Inbox composition page:
  - Frontend composition only; ZERO new backend invented
  - All rows derived from real /api/v1/admin/email-queue,
    /api/v1/proposals, /api/v1/dsk/audit-log, or /dashboard/batches
  - Each source loads independently (Promise-isolated failures)
  - No fake inbox rows, no mock subjects, no mock client names
  - Read-only first pass — no send / approve / execute buttons
  - Stub pending placeholders for Mark-read / Snooze / Bulk-rule
  - Inbox no longer routes to StubPage
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


# ── Inbox is now a real composition route, not a stub ──────────────────────

def test_inbox_component_present():
    src = _src()
    assert "function InboxPage({ batches, onViewShipment, onNav, onToast })" in src


def test_inbox_route_renders_real_component():
    src = _src()
    # Inbox is rendered via <InboxPage> with real batches prop
    assert "page === 'inbox' && (" in src
    assert "<InboxPage" in src
    assert "batches={batches}" in src
    assert "onViewShipment={viewShipment}" in src


def test_inbox_removed_from_stub_routes():
    src = _src()
    # The stub-page match list no longer includes 'inbox'
    assert "page === 'inbox' || page === 'inventory'" not in src
    # Stub list still includes inventory + master + carriers +
    # diagnostics + coverage (api_status was removed in a later pass)
    for stub in ("'inventory'", "'master'", "'carriers'", "'diagnostics'", "'coverage'"):
        assert f"page === {stub}" in src, f"Stub route missing for {stub}"


def test_inbox_removed_from_stub_config():
    src = _src()
    # STUB_CONFIG no longer has an inbox: entry; the heading "Unified
    # Inbox" must not appear in the stub config block.
    assert "STUB_CONFIG" in src  # the const itself remains
    stub_start = src.index("const STUB_CONFIG = {")
    stub_end   = src.index("function StubPage(", stub_start)
    stub_block = src[stub_start:stub_end]
    assert "inbox:" not in stub_block
    assert "Unified Inbox" not in stub_block


# ── Real endpoint usage — every source comes from an existing route ───────

def test_email_queue_endpoint_used():
    src = _src()
    assert "apiFetch('/api/v1/admin/email-queue')" in src


def test_proposals_endpoint_used():
    src = _src()
    # GET /api/v1/proposals?status=pending — real
    assert "apiFetch('/api/v1/proposals?status=pending')" in src


def test_dsk_audit_log_endpoint_used():
    src = _src()
    assert "apiFetch('/api/v1/dsk/audit-log')" in src


def test_batches_real_source_used():
    src = _src()
    # The action_required source iterates the real `batches` prop
    assert "(batches || []).forEach(b =>" in src


# ── No new endpoints invented ──────────────────────────────────────────────

def test_no_invented_inbox_endpoints():
    src = _src()
    for ep in (
        "/api/v1/inbox",
        "/api/v1/inbox/all",
        "/api/v1/inbox/unified",
        "/api/v1/admin/inbox",
        "/api/v1/notifications",
        "/api/v1/operator/queue",
        "/api/v1/inbox/snooze",
        "/api/v1/inbox/mark-read",
    ):
        assert ep not in src, f"Invented Inbox endpoint leaked: {ep}"


# ── No fake rows / mock subjects / mock client names ──────────────────────

def test_no_mock_email_subjects():
    src = _src()
    # Inbox component body bounded; mock subjects from design must not appear
    block_start = src.index("function InboxPage(")
    block_end   = src.index("function StubPage(", block_start)
    block = src[block_start:block_end]
    for fake in (
        "Pre-check notice — DHL",
        "DHL clearance complete",
        "Customs reply required",
        "AWB DHL-1234567890",
        "AWB FedEx-",
        "Subject: Re:",
    ):
        assert fake not in block, f"Mock email subject leaked into Inbox: {fake}"


def test_no_mock_client_names_in_inbox():
    src = _src()
    block_start = src.index("function InboxPage(")
    block_end   = src.index("function StubPage(", block_start)
    block = src[block_start:block_end]
    for fake in (
        "Maison Royale SARL",
        "Atelier Lumière",
        "Crown Jewelers Ltd",
        "Patek Philippe SA",
        "Audemars Piguet",
        "Aurum Watches GmbH",
        "Hôtel Belle Étoile",
        "Bijoux Sélection",
        "Bijoux Maison Paris",
        "Goldhaus Berlin",
    ):
        assert fake not in block, f"Mock client name leaked into Inbox: {fake}"


def test_no_mock_inbox_rows_array():
    src = _src()
    block_start = src.index("function InboxPage(")
    block_end   = src.index("function StubPage(", block_start)
    block = src[block_start:block_end]
    # No literal seed arrays — every row is built from a source endpoint
    for fake in ("MOCK_INBOX", "SAMPLE_INBOX", "fakeInboxRows", "INBOX_FIXTURES"):
        assert fake not in block, f"Mock inbox seed array leaked: {fake}"


# ── Read-only first pass — no send/approve/execute write paths ────────────

def test_no_new_write_paths_in_inbox():
    """The Inbox composition must be read-only. No POST/PUT/DELETE/PATCH
    calls anywhere in the InboxPage body."""
    src = _src()
    block_start = src.index("function InboxPage(")
    block_end   = src.index("function StubPage(", block_start)
    block = src[block_start:block_end]
    for method in ("method: 'POST'", "method: 'PUT'", "method: 'DELETE'", "method: 'PATCH'"):
        assert method not in block, f"InboxPage body must NOT contain {method!r}"


def test_no_send_approve_reject_buttons_in_inbox():
    src = _src()
    block_start = src.index("function InboxPage(")
    block_end   = src.index("function StubPage(", block_start)
    block = src[block_start:block_end]
    # Buttons like "Send", "Approve", "Reject", "Execute" must not appear
    # as functional controls inside the inbox table. The only enabled
    # action is "Open" → routes to existing detail page.
    for fake in (
        ">Send<",
        ">Approve<",
        ">Reject<",
        ">Execute<",
        ">Apply<",
        ">Run<",
    ):
        assert fake not in block, f"Forbidden write-action button leaked into Inbox: {fake}"


# ── Isolated failures: each source has its own loading/error state ────────

def test_per_source_state_objects():
    src = _src()
    # Each source has independent state shape: { loading, error, items, ... }
    for state in ("setEmails", "setProposals", "setDsk"):
        assert state in src, f"Missing per-source setter: {state}"
    # Each load callback exists separately
    for fn in ("loadEmails", "loadProposals", "loadDsk"):
        assert f"const {fn} = React.useCallback" in src, f"Missing per-source loader: {fn}"


def test_per_source_error_banner_landmarks():
    src = _src()
    assert 'data-testid="inbox-source-errors"' in src
    # Template-literal testid for per-source error pill
    assert 'data-testid={`inbox-source-error-${err.src}`}' in src


def test_failure_does_not_block_other_sources():
    src = _src()
    # The errors array filters out null per-source errors and renders
    # them as separate banners. Other sources still render their rows
    # via the unified `rows` array.
    assert "].filter(Boolean)" in src
    # The "other sources still shown" hint is part of the banner
    assert "other sources still shown" in src


# ── Normalized row schema ──────────────────────────────────────────────────

def test_row_schema_documented_in_comment():
    src = _src()
    # The schema comment lists the canonical keys
    assert "id, source, severity, title, batch_id, awb, timestamp, reason, open_target" in src


def test_row_schema_used_for_each_source():
    src = _src()
    # All 4 sources push rows with the same schema. Keys that are always
    # spelled with explicit `key:` form (no shorthand) must appear ≥4×.
    for key in ("source:", "title:", "batch_id:", "timestamp:", "reason:", "open_target:"):
        assert src.count(key) >= 4, f"Row schema key '{key}' not used across all 4 sources"
    # `severity` uses ES6 shorthand binding in one source (proposals).
    # Combined occurrences of `severity:` + shorthand `severity,` must
    # cover all 4 sources.
    sev_total = src.count('severity:') + src.count('      severity,')
    assert sev_total >= 4, f"severity key not used across all 4 sources (counted {sev_total})"


# ── KPI strip is computed from rows, not literals ─────────────────────────

def test_kpi_strip_landmark_present():
    src = _src()
    assert 'data-testid="inbox-live-stats"' in src
    assert 'data-testid={`inbox-stat-${s.id}`}' in src
    for sid in ("'total'", "'emails'", "'proposals'", "'action_required'", "'dsk'"):
        assert f"id: {sid}" in src, f"Missing KPI tile id: {sid}"


def test_kpi_values_derive_from_rows_array():
    src = _src()
    # Every KPI value is rows.length or rows.filter(...) — no fake counts
    assert "value: rows.length" in src
    assert "value: rows.filter(r => r.source === 'email_queue').length" in src
    assert "value: rows.filter(r => r.source === 'proposals').length" in src
    assert "value: rows.filter(r => r.source === 'action_required').length" in src
    assert "value: rows.filter(r => r.source === 'dsk').length" in src


# ── Filter pills + unified table + empty state ────────────────────────────

def test_source_filter_pills_present():
    src = _src()
    assert 'data-testid="inbox-toolbar"' in src
    assert 'data-testid={`inbox-filter-${f.id}`}' in src
    for fid in ("'all'", "'email_queue'", "'proposals'", "'action_required'", "'dsk'"):
        assert f"id: {fid}" in src, f"Missing filter pill id: {fid}"


def test_unified_table_landmark_present():
    src = _src()
    assert 'data-testid="inbox-table"' in src


def test_loading_and_empty_states_present():
    src = _src()
    assert 'data-testid="inbox-loading"' in src
    assert 'data-testid="inbox-empty-state"' in src


def test_per_row_open_navigates_to_existing_handler():
    src = _src()
    # The Open button calls onViewShipment with the row's open_target.id
    assert 'data-testid="inbox-open-btn"' in src
    assert "onViewShipment && onViewShipment" in src


# ── Disabled placeholders are clearly marked ──────────────────────────────

def test_disabled_actions_are_marked_pending():
    src = _src()
    # The 3 design-preview action buttons (Mark all read / Snooze / Bulk
    # apply rule) carry data-pending="true", disabled, aria-disabled
    block_start = src.index('data-testid="inbox-toolbar"')
    block_end   = src.index('data-testid="inbox-table"', block_start)
    block = src[block_start:block_end]
    for aid in ('mark_read', 'snooze', 'bulk_apply'):
        assert f'data-testid={{`inbox-preview-action-${{b.id}}`}}' in src
        assert f"id: '{aid}'" in src
    assert block.count('disabled') >= 3
    assert 'aria-disabled="true"' in block
    assert "cursor: 'not-allowed'" in block


def test_disabled_actions_have_no_onclick_no_fetch():
    src = _src()
    block_start = src.index('data-testid="inbox-toolbar"')
    block_end   = src.index('data-testid="inbox-table"', block_start)
    block = src[block_start:block_end]
    # The disabled buttons in the toolbar must NOT have onClick or fetch.
    # The "Refresh" button DOES have onClick (real reload) — so we check
    # specifically that the disabled action template doesn't have onClick.
    # Find the disabled-action block specifically.
    disabled_block_start = block.index("Design-preview disabled actions")
    disabled_block = block[disabled_block_start:]
    assert 'onClick' not in disabled_block, "Disabled action template must NOT have onClick"
    assert 'apiFetch' not in disabled_block, "Disabled action template must NOT call apiFetch"


def test_design_preview_footer_strip_present():
    src = _src()
    assert 'data-testid="inbox-design-preview"' in src
    assert 'data-testid="inbox-preview-pending-badge"' in src


# ── SectionLabel polish + page landmark ───────────────────────────────────

def test_page_landmark_present():
    src = _src()
    assert 'data-testid="inbox-page"' in src


def test_section_label_polish_applied():
    src = _src()
    assert "<SectionLabel>Unified queue</SectionLabel>" in src


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
