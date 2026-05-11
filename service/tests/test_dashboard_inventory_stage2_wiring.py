"""UI wiring tests — Inventory Stage 2 fetches /api/v1/inventory/stage2/aggregate."""
from __future__ import annotations

import re
from pathlib import Path

DASHBOARD_PATH = Path(__file__).resolve().parent.parent / "app" / "static" / "dashboard.html"


def _src() -> str:
    if not DASHBOARD_PATH.exists():
        import pytest
        pytest.skip(f"dashboard.html not found at {DASHBOARD_PATH}")
    return DASHBOARD_PATH.read_text(encoding="utf-8")


def _inventory_page_body() -> str:
    """Extract the InventoryPage function body for scoped scans."""
    src = _src()
    # InventoryPage runs from its declaration until the next module-scope
    # function/comment header. Bound on the next component header for
    # tight scope.
    start = src.index("function InventoryPage(")
    end = src.index("function MasterDataPage(", start)
    return src[start:end]


def _coverage_page_body() -> str:
    src = _src()
    start = src.index("function CoverageMatrixPage()")
    end = src.index("function InventoryPage(", start)
    return src[start:end]


def test_inventory_stage2_fetches_aggregate_endpoint():
    body = _inventory_page_body()
    # Exactly one apiFetch call to the endpoint (anchored on the apiFetch
    # form — comments referencing the URL are fine but must not be the
    # only occurrence).
    apifetch_hits = (
        body.count("apiFetch('/api/v1/inventory/stage2/aggregate')")
        + body.count('apiFetch("/api/v1/inventory/stage2/aggregate")')
    )
    assert apifetch_hits == 1, \
        f"Expected exactly 1 apiFetch call to /api/v1/inventory/stage2/aggregate, got {apifetch_hits}"


def test_stage2_state_hooks_present():
    body = _inventory_page_body()
    assert "stage2Data" in body
    assert "stage2Loading" in body
    assert "stage2Error" in body
    assert "React.useState" in body
    assert "React.useEffect" in body


def test_stage2_tile_values_come_from_response():
    body = _inventory_page_body()
    # Tile values must read from stage2Data?.stage2?.[tile.key]
    assert "stage2Data?.stage2?.[tile.key]" in body


def test_null_count_renders_em_dash_and_data_pending():
    body = _inventory_page_body()
    # Conditional ladder: isPending = count === null || count === undefined
    assert "count === null" in body
    assert "count === undefined" in body
    assert "data-pending={isPending ? 'true' : undefined}" in body


def test_int_count_renders_count_string():
    body = _inventory_page_body()
    assert "String(count)" in body


def test_loading_state_renders_ellipsis():
    body = _inventory_page_body()
    assert "stage2Loading ? '…'" in body or 'stage2Loading ? "…"' in body


def test_error_state_chip_present_and_isolated():
    body = _inventory_page_body()
    assert 'data-testid="inventory-stage2-error"' in body
    # The page-level landmark must still exist regardless of stage2Error state
    assert 'data-testid="inventory-page"' in _src()


def test_disabled_action_buttons_unchanged():
    # The 5 disabled action button testids are rendered from a JSX
    # template literal: `data-testid={`inventory-preview-action-${b.id}`}`.
    # Source-grep checks the template form + the per-id source array.
    body = _inventory_page_body()
    assert "data-testid={`inventory-preview-action-${b.id}`}" in body, \
        "Disabled-action testid template missing from InventoryPage"
    for action_id in ("'move_stock'", "'sample_out'", "'sample_return'",
                      "'goods_return'", "'return_prod'"):
        assert f"id: {action_id}" in body, \
            f"Disabled action id missing from source: {action_id}"
    # Each button template still carries disabled + cursor: not-allowed
    actions_block_start = body.index("Design-preview disabled actions")
    actions_block_end = body.index("Lifecycle buckets", actions_block_start)
    actions_block = body[actions_block_start:actions_block_end]
    assert "disabled" in actions_block
    assert 'aria-disabled="true"' in actions_block
    assert "cursor: 'not-allowed'" in actions_block


def test_no_new_write_methods_in_inventory_page():
    body = _inventory_page_body()
    for method_str in ("'POST'", "'PUT'", "'PATCH'", "'DELETE'",
                       '"POST"', '"PUT"', '"PATCH"', '"DELETE"'):
        assert method_str not in body, \
            f"Forbidden write method in InventoryPage: {method_str}"


def test_basis_surfaced_as_tooltip():
    body = _inventory_page_body()
    assert "title={basis || tile.hint}" in body


def test_limitations_array_surfaced_in_ui():
    body = _inventory_page_body()
    assert 'data-testid="inventory-stage2-limitations"' in body
    assert "stage2Data?.limitations?.length > 0" in body
    assert "stage2Data.limitations.map" in body


def test_coverage_matrix_inventory_row_updated():
    body = _coverage_page_body()
    inv_row = re.search(
        r"route:\s*'inventory'[^}]+\}",
        body, re.DOTALL,
    )
    assert inv_row, "Inventory MATRIX row not found in CoverageMatrixPage"
    text = inv_row.group(0)
    # Updated row references final_stock being live
    assert "final_stock" in text
    # And still marks samples/returns/consignment as pending
    assert "samples" in text and "returns" in text and "consignment" in text
    # And references the new endpoint in real_source
    assert "stage2/aggregate" in text
