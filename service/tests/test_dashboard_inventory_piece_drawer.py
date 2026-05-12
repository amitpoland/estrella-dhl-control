"""UI wiring tests for Phase 4.4 — Piece detail drawer on InventoryPage."""
from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_PATH = (
    Path(__file__).resolve().parent.parent / "app" / "static" / "dashboard.html"
)


def _src() -> str:
    if not DASHBOARD_PATH.exists():
        pytest.skip(f"dashboard.html not found at {DASHBOARD_PATH}")
    return DASHBOARD_PATH.read_text(encoding="utf-8")


def _inventory_body() -> str:
    src = _src()
    start = src.index("function InventoryPage(")
    end = src.index("function MasterDataPage(", start)
    return src[start:end]


def test_state_hooks_present():
    body = _inventory_body()
    assert "const [pieceLookupCode," in body
    assert "const [pieceDetail," in body
    assert "const [pieceDetailLoading," in body
    assert "const [pieceDetailError," in body
    assert "const [drawerOpen," in body


def test_apifetch_to_pieces_endpoint():
    body = _inventory_body()
    hits = (
        body.count("apiFetch(`/api/v1/inventory/pieces/${encodeURIComponent(code)}`)")
        + body.count("apiFetch('/api/v1/inventory/pieces/")
        + body.count('apiFetch("/api/v1/inventory/pieces/')
    )
    assert hits >= 1, "Expected an apiFetch call to /api/v1/inventory/pieces/{...}"


def test_lookup_input_and_button_present():
    body = _inventory_body()
    assert 'data-testid="inventory-piece-lookup-input"' in body
    assert 'data-testid="inventory-piece-lookup-btn"' in body


def test_enter_key_triggers_lookup():
    body = _inventory_body()
    assert "e.key === 'Enter'" in body


def test_drawer_testids_present():
    body = _inventory_body()
    assert 'data-testid="inventory-piece-drawer"' in body
    assert 'data-testid="inventory-piece-drawer-close"' in body
    assert 'data-testid="inventory-piece-drawer-loading"' in body
    assert 'data-testid="inventory-piece-drawer-error"' in body
    assert 'data-testid="inventory-piece-drawer-empty"' in body
    assert 'data-testid="inventory-piece-drawer-found"' in body
    # Phase B.2 — unified timeline replaced the legacy History section.
    assert 'data-testid="inventory-piece-drawer-timeline-empty"' in body
    assert 'data-testid="inventory-piece-drawer-timeline"' in body
    assert 'data-testid="inventory-piece-drawer-timeline-row"' in body


def test_drawer_renders_timeline_kinds():
    """Drawer must branch on `kind` (lifecycle / movement / sample) to
    pick the row icon. Source-grep the discriminator literals."""
    body = _inventory_body()
    assert "ev.kind === 'lifecycle'" in body
    assert "ev.kind === 'movement'" in body
    # sample-out vs sample-return is distinguished by detail.direction.
    assert "ev.detail.direction === 'return'" in body


def test_drawer_renders_location_chip():
    """Location chip below the lifecycle pill — sourced from
    pieceDetail.location.current_location."""
    body = _inventory_body()
    assert 'data-testid="inventory-piece-location-chip"' in body
    assert "pieceDetail.location" in body
    assert "current_location" in body


def test_drawer_renders_limitations_chip():
    """When backend reports degraded sources, drawer renders them
    inline above the timeline."""
    body = _inventory_body()
    assert 'data-testid="inventory-piece-drawer-timeline-limitations"' in body
    assert "pieceDetail.limitations" in body


def test_drawer_renders_sample_recipient_inline():
    """Sample-out timeline rows must surface recipient_client_name +
    expected_return_date inline (operator-requested visibility)."""
    body = _inventory_body()
    assert "ev.detail.recipient_client_name" in body
    assert "ev.detail.expected_return_date" in body


def test_drawer_only_renders_when_open():
    body = _inventory_body()
    # JSX guard pattern: `{drawerOpen && (`
    assert "{drawerOpen && (" in body


def test_empty_state_uses_found_false():
    body = _inventory_body()
    assert "pieceDetail.found === false" in body


def test_found_state_uses_found_true():
    body = _inventory_body()
    assert "pieceDetail.found === true" in body


def test_close_handler_resets_drawer():
    body = _inventory_body()
    # closeDrawer must clear state (setDrawerOpen(false))
    assert "setDrawerOpen(false)" in body
    assert "const closeDrawer" in body


def test_drawer_writes_match_sample_allowlist():
    """The piece drawer became a controlled write surface with Phase B.1.

    Lookup itself stays GET-only. The drawer's action panel adds exactly
    two write paths — POST sample-out and POST sample-return — and
    nothing else. PUT/PATCH/DELETE remain forbidden anywhere on the
    InventoryPage (which contains the drawer)."""
    body = _inventory_body()
    for method_str in ("'PUT'", '"PUT"', "'PATCH'", '"PATCH"',
                       "'DELETE'", '"DELETE"'):
        assert method_str not in body, (
            f"Forbidden write method in InventoryPage / drawer: {method_str}"
        )
    # POST is allowed but only against the two Phase B.1 paths.
    assert "_postSample('sample-out'" in body, "Expected sample-out POST call"
    assert "_postSample('sample-return'" in body, "Expected sample-return POST call"


def test_disabled_action_buttons_post_sample_activation():
    """Sample-out + Sample-return moved from toolbar placeholders into
    the piece drawer. Move stock has its own per-piece UI in the
    Warehouse Scanner. Goods-return + Return-to-producer remain
    backend-pending placeholders in the toolbar."""
    body = _inventory_body()
    assert "data-testid={`inventory-preview-action-${b.id}`}" in body
    # Remaining backend-pending placeholders.
    for action_id in ("'goods_return'", "'return_prod'"):
        assert f"id: {action_id}" in body
    # Now-live actions must NOT appear as disabled placeholders.
    for action_id in ("'sample_out'", "'sample_return'", "'move_stock'"):
        assert f"id: {action_id}" not in body, (
            f"Live action {action_id} must not remain in the disabled "
            f"placeholder array"
        )
