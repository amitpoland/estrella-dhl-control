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


def test_disabled_action_buttons_post_sample_activation():
    # The toolbar placeholder array is rendered from a JSX template
    # literal: `data-testid={`inventory-preview-action-${b.id}`}`. With
    # Phase B.1 (Sample-out live) and Move stock live, only Goods-return
    # and Return-to-producer remain backend-pending toolbar placeholders.
    body = _inventory_page_body()
    assert "data-testid={`inventory-preview-action-${b.id}`}" in body, \
        "Disabled-action testid template missing from InventoryPage"
    for action_id in ("'goods_return'", "'return_prod'"):
        assert f"id: {action_id}" in body, \
            f"Backend-pending action id missing from source: {action_id}"
    for action_id in ("'sample_out'", "'sample_return'", "'move_stock'"):
        assert f"id: {action_id}" not in body, \
            f"Live action {action_id} must not remain in disabled placeholders"
    # Remaining placeholders still carry disabled + cursor: not-allowed.
    actions_block_start = body.index("Phase B.1 live")
    actions_block_end = body.index("Lifecycle buckets", actions_block_start)
    actions_block = body[actions_block_start:actions_block_end]
    assert "disabled" in actions_block
    assert 'aria-disabled="true"' in actions_block
    assert "cursor: 'not-allowed'" in actions_block


def test_inventory_page_writes_match_sample_allowlist():
    """Phase B.1 activates exactly two POST surfaces on InventoryPage:
    sample-out and sample-return, both inside the piece drawer.
    PUT/PATCH/DELETE remain forbidden. Both endpoint templates must
    be present and a single POST helper feeds them."""
    body = _inventory_page_body()
    for method_str in ("'PUT'", '"PUT"', "'PATCH'", '"PATCH"',
                       "'DELETE'", '"DELETE"'):
        assert method_str not in body, \
            f"Forbidden write method in InventoryPage: {method_str}"
    # The two allowlisted POST targets appear via template literals
    # rendered by the shared `_postSample` helper.
    assert "_postSample('sample-out'" in body, "sample-out POST call missing"
    assert "_postSample('sample-return'" in body, "sample-return POST call missing"
    # POST method markers are bounded — there should be exactly the
    # one POST helper call (`_postSample` issues a single fetch() with
    # method:'POST'). If this count grows, it means a new mutation
    # surface was introduced and the contract needs explicit review.
    post_count = body.count("method: 'POST'")
    assert post_count == 1, (
        f"Expected exactly one POST helper in InventoryPage "
        f"(_postSample); found {post_count}"
    )


def test_basis_surfaced_as_tooltip():
    body = _inventory_page_body()
    assert "title={basis || tile.hint}" in body


def test_limitations_array_surfaced_in_ui():
    body = _inventory_page_body()
    assert 'data-testid="inventory-stage2-limitations"' in body
    assert "stage2Data?.limitations?.length > 0" in body
    assert "stage2Data.limitations.map" in body


def test_stale_sample_out_limitation_is_rewritten_in_ui():
    """Phase B.1 added SAMPLE_OUT to inventory_state_engine.STATES, so
    the aggregator's hard-coded "SAMPLE_OUT not in
    inventory_state_engine.STATES" limitation is now factually false.
    The dashboard must rewrite that exact line at render time until the
    aggregator copy is updated server-side."""
    body = _inventory_page_body()
    # The stale phrase must still be matched (so we can rewrite it)
    # but only inside the rewrite guard — i.e. as a string literal in
    # an indexOf check, not as the displayed text.
    assert "SAMPLE_OUT not in inventory_state_engine.STATES" in body, (
        "Rewrite guard must reference the exact stale phrase to match it"
    )
    # The corrected message must be present.
    assert "Stage 2 aggregator has not yet been updated to count" in body
    # And the testid that flags a rewritten row must be present, so
    # operators can grep for it in DevTools when triaging Stage 2 copy.
    assert 'inventory-stage2-limitation-samples-corrected' in body


def test_samples_tile_hint_no_longer_claims_backend_pending_lifecycle():
    """Samples tile hint must reflect: SAMPLE_OUT lifecycle is live;
    only the aggregator-derived count is still pending."""
    body = _inventory_page_body()
    samples_line_idx = body.index("testid: 'inventory-stage2-samples'")
    samples_line_end = body.index("\n", samples_line_idx)
    line = body[samples_line_idx:samples_line_end]
    # Must NOT contain the stale "released to client for review"
    # without acknowledging the lifecycle is live.
    assert "SAMPLE_OUT lifecycle live" in line, \
        "Samples tile hint must reference SAMPLE_OUT being live"
    assert "aggregator count pending" in line, \
        "Samples tile hint must say aggregator count is still pending"


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
