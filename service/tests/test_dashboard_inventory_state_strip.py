"""UI wiring tests for Phase 4.2 — Inventory state strip on BatchDetailPage.

Verifies dashboard.html fetches /api/v1/inventory/state/{batchId} and
renders a strip with honest empty / loading / error states.
"""
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


def _batch_detail_body() -> str:
    src = _src()
    start = src.index("function BatchDetailPage(")
    # bound to the next module-scope function
    end = src.index("function ", start + 25)
    return src[start:end]


def test_state_hooks_present():
    body = _batch_detail_body()
    assert "const [invState" in body
    assert "const [invStateLoading" in body
    assert "const [invStateError" in body


def test_apifetch_to_inventory_state_endpoint():
    body = _batch_detail_body()
    hits = (
        body.count("apiFetch(`/api/v1/inventory/state/${encodeURIComponent(batchId)}`)")
        + body.count("apiFetch('/api/v1/inventory/state/")
        + body.count('apiFetch("/api/v1/inventory/state/')
    )
    assert hits >= 1, (
        "Expected at least one apiFetch call to /api/v1/inventory/state/{batchId}"
    )


def test_loadInvState_called_in_mount_effect():
    body = _batch_detail_body()
    assert "loadInvState()" in body, (
        "loadInvState must be wired into the mount-time React.useEffect"
    )


def test_strip_testid_present():
    body = _batch_detail_body()
    assert 'data-testid="inventory-batch-state-strip"' in body


def test_strip_empty_state_testid_present():
    body = _batch_detail_body()
    assert 'data-testid="inventory-batch-state-empty"' in body


def test_strip_error_state_testid_present():
    body = _batch_detail_body()
    assert 'data-testid="inventory-batch-state-error"' in body


def test_strip_loading_state_present():
    body = _batch_detail_body()
    assert 'data-testid="inventory-batch-state-loading"' in body


def test_per_state_tile_testid_template():
    body = _batch_detail_body()
    assert "data-testid={`inventory-batch-state-tile-${stateName}`}" in body


def test_honest_em_dash_for_zero_count():
    body = _batch_detail_body()
    # Zero counts render em-dash + data-pending=true (matches the
    # honest-null pattern from Stage 2 tiles).
    assert "count === 0 ? 'true' : undefined" in body
    assert "count > 0 ? String(count) : '—'" in body


def test_no_write_methods_in_strip_block():
    body = _batch_detail_body()
    # apiFetch to /inventory/state is GET-only; ensure no POST/PUT/PATCH/DELETE
    # was added in this section.
    strip_start = body.index('data-testid="inventory-batch-state-strip"')
    # Scope: the strip JSX plus the loader callback declaration above.
    region = body[max(0, strip_start - 2000): strip_start + 3000]
    for method_str in ("'POST'", '"POST"', "'PUT'", '"PUT"',
                       "'PATCH'", '"PATCH"', "'DELETE'", '"DELETE"'):
        assert method_str not in region, (
            f"Forbidden write method in inventory-batch-state region: {method_str}"
        )
