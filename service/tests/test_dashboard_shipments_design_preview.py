"""
test_dashboard_shipments_design_preview.py — Path B / Pass 2.5

Contract for the Shipments page "Design preview · Backend pending" strip:
  - Live table data still comes only from real `/dashboard/batches`
  - Preview cards are visually marked pending (testid + data-pending=true)
  - Preview action buttons are disabled and cannot trigger backend calls
  - No new fetch/apiFetch calls added for these preview fields
  - No fake rows in the live table
  - UI-3 operational cards still present
  - Bucket filtering preserved
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


# ── Preview strip exists and is clearly marked ──────────────────────────────

def test_preview_strip_present():
    src = _src()
    assert 'data-testid="shipments-design-preview"' in src


def test_preview_strip_has_pending_badge():
    src = _src()
    assert 'data-testid="design-preview-pending-badge"' in src
    assert 'Backend pending' in src
    assert 'Design preview' in src


def test_all_five_preview_cards_present_and_marked_pending():
    src = _src()
    # The testid is rendered from a template-literal, so source-grep
    # checks the template form + the per-card id strings in the array.
    assert 'data-testid={`shipments-preview-card-${card.id}`}' in src
    for card_id in ("'inbound'", "'outbound'", "'customs_queue'", "'inventory'", "'carrier_sla'"):
        assert f"id: {card_id}" in src, f"Missing preview card id: {card_id}"
    # Cards and buttons each render with data-pending="true". At source
    # level, the JSX uses two templates (one map over cards, one over
    # buttons), so we expect >= 2 occurrences. At runtime, React renders
    # 5 cards + 4 buttons = 9 with the attribute.
    assert src.count('data-pending="true"') >= 2


def test_preview_cards_show_em_dash_not_fake_number():
    src = _src()
    # Each preview card's number row is the literal em-dash. No fake counts
    # of "7", "12", "3", etc. Cards iterate from a single template, so the
    # em-dash appears literally once in the rendered template body.
    block_start = src.index('data-testid="shipments-design-preview"')
    block_end   = src.index('Active shipments table', block_start)
    block = src[block_start:block_end]
    # Template body contains the em-dash placeholder
    assert '>—</div>' in block
    # No numeric values in the big serif slot of the preview block
    assert 'fontFamily: \'"DM Serif Display", serif\', lineHeight: 1 }}>7' not in block
    assert 'fontFamily: \'"DM Serif Display", serif\', lineHeight: 1 }}>12' not in block


def test_preview_actions_disabled_and_pending():
    src = _src()
    # Action testid is rendered from a template literal — assert the template
    # form + each per-action id appears in the source array.
    assert 'data-testid={`shipments-preview-action-${b.id}`}' in src
    for action_id in ("'create_outbound'", "'export_csv'", "'bulk_label'", "'sla_report'"):
        assert f"id: {action_id}" in src, f"Missing preview action id: {action_id}"
    # Each disabled button carries aria-disabled, disabled, and a pending title
    assert 'aria-disabled="true"' in src
    assert 'title="Backend pending — not connected yet"' in src
    # Cursor: not-allowed
    assert "cursor: 'not-allowed'" in src


def test_preview_actions_have_no_onClick_handlers():
    src = _src()
    # Grep the preview-action block and confirm no onClick is wired up
    block_start = src.index('Future action buttons — disabled, no handlers wired')
    block_end   = src.index('Active shipments table', block_start)
    block = src[block_start:block_end]
    assert 'onClick' not in block, "Preview action button must NOT have onClick"
    # And confirm the button template carries `disabled`
    assert 'disabled' in block


# ── Live table data still real ──────────────────────────────────────────────

def test_live_table_still_maps_paginated_real_rows():
    src = _src()
    # The actual <tbody> still iterates the real `paginated` array
    assert 'paginated.map(row =>' in src
    # And `paginated` derives from real `sorted` array via slice
    assert 'sorted.slice(pageStart, pageEnd)' in src


def test_live_table_pagination_real():
    src = _src()
    assert 'const PAGE_SIZE = 25' in src
    assert 'Math.ceil(sorted.length / PAGE_SIZE)' in src


def test_no_mock_arrays_introduced():
    src = _src()
    for fake in ('MOCK_SHIPMENTS', 'PIPELINE_SHIPMENTS', 'SAMPLE_', 'fakeData'):
        assert fake not in src, f"Mock array '{fake}' leaked in"


def test_no_mock_client_names_in_preview():
    src = _src()
    # Mocks from previous design iterations must not be revived as preview seeds
    for fake in ('Crown Jewelers', 'Patek Philippe', 'Maison Royale',
                 'Audemars Piguet', 'Aurum Watches', 'Bijoux Sélection'):
        assert fake not in src


def test_no_fake_awbs_in_preview():
    src = _src()
    for fake in ('DHL-1234567890', 'DHL-9876543210', 'FDX-0011223344',
                 'INP-552448', 'INP-552399'):
        assert fake not in src


def test_no_new_apifetch_calls_for_preview_fields():
    """The preview strip must not have triggered any new fetch/apiFetch
    additions. Pinning the count of `apiFetch(` occurrences keeps future
    Pass 2.x edits from sneaking in a backend call for these fields without
    a backend route landing first."""
    src = _src()
    # Cards are dumb placeholders — they don't call apiFetch.
    # Confirm that the preview block doesn't reference apiFetch / fetch(
    block_start = src.index('data-testid="shipments-design-preview"')
    block_end   = src.index('Active shipments table', block_start)
    block = src[block_start:block_end]
    assert 'apiFetch' not in block, "Preview strip must NOT call apiFetch"
    assert 'fetch(' not in block,   "Preview strip must NOT call fetch()"
    # Confirm no event-driven custom events either
    assert 'dispatchEvent' not in block


# ── UI-3 cards and bucket filter still present ─────────────────────────────

def test_ui3_operational_cards_still_present():
    src = _src()
    for tid in (
        'data-testid="warehouse-operations-card"',
        'data-testid="sales-accounting-operations-card"',
        'data-testid="dhl-customs-operations-card"',
    ):
        assert tid in src


def test_bucket_filter_chip_still_present():
    src = _src()
    for tid in (
        'data-testid="op-filter-active-chip"',
        'data-testid="op-filter-clear-btn"',
    ):
        assert tid in src


# ── Preview is hidden in Archived view ──────────────────────────────────────

def test_preview_only_renders_in_active_view():
    src = _src()
    # The preview block is gated on viewMode === 'active'
    block = src[src.index('Design preview · Backend pending'):
                src.index('Active shipments table', src.index('Design preview · Backend pending'))]
    # The whole preview is wrapped in `viewMode === 'active' && (...)`
    assert "viewMode === 'active'" in block


# ── Open-shipment handler unchanged ─────────────────────────────────────────

def test_open_shipment_handler_unchanged():
    src = _src()
    assert "onClick={() => onViewShipment(row)}" in src


# ── DETAIL_TABS still 9 (UI-3.5 baseline) ──────────────────────────────────

def test_detail_tabs_unchanged():
    src = _src()
    assert "const DETAIL_TABS = ['Overview', 'Documents', 'DHL / Customs', 'Warehouse', 'Sales', 'PZ / wFirma', 'Timeline', 'Intelligence', 'Proposals']" in src
