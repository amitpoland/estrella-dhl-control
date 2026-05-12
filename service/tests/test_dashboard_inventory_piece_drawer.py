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
    assert 'data-testid="inventory-piece-drawer-history-empty"' in body
    assert 'data-testid="inventory-piece-drawer-history"' in body


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


def test_no_write_methods_in_lookup_or_drawer_block():
    body = _inventory_body()
    lookup_start = body.index('data-testid="inventory-piece-lookup"')
    region = body[lookup_start:lookup_start + 6000]
    for method_str in ("'POST'", '"POST"', "'PUT'", '"PUT"',
                       "'PATCH'", '"PATCH"', "'DELETE'", '"DELETE"'):
        assert method_str not in region, (
            f"Forbidden write method in piece-drawer region: {method_str}"
        )


def test_disabled_action_buttons_unchanged():
    body = _inventory_body()
    assert "data-testid={`inventory-preview-action-${b.id}`}" in body
    for action_id in ("'move_stock'", "'sample_out'", "'sample_return'",
                      "'goods_return'", "'return_prod'"):
        assert f"id: {action_id}" in body
