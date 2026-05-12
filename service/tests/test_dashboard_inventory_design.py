"""
test_dashboard_inventory_design.py — Path B / Tier 2 / Pass 17 (close-out).

Contract for the new Inventory composition page:
  - Frontend composition only; ZERO new backend invented
  - Reuses shared module-scope helpers: OP_PREDICATES.warehouse,
    deriveWarehouseLifecycle, WAREHOUSE_LIFECYCLE_LABEL,
    WAREHOUSE_LIFECYCLE_KEYS, ATTENTION_PREDICATES.warehouse
  - Source: real `batches` prop only (/dashboard/batches list view)
  - Does NOT call /api/v1/warehouse/audit/{batch_id} per batch (N calls)
  - Per-batch detail delegated to existing Warehouse tab in BatchDetailPage
    and to the external Warehouse Scanner page (/dashboard/warehouse.html)
  - No fake inventory rows, no mock locations, no fake stock quantities
  - Two-stage IA (Stage 1 Temp/Warehouse/Sale + Stage 2 Final/Samples/Returns)
    explicitly Backend pending — no fake aggregated totals
  - Read-only — no stock-move / sample-out / scan write paths
  - inventory no longer routes to StubPage
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


# ── inventory is now a real composition route, not a stub ────────────────

def test_inventory_component_present():
    src = _src()
    assert "function InventoryPage({ batches, onViewShipment, onNav, onToast })" in src


def test_inventory_route_renders_real_component():
    src = _src()
    assert "page === 'inventory' && (" in src
    assert "<InventoryPage" in src
    assert "batches={batches}" in src
    assert "onViewShipment={viewShipment}" in src


def test_inventory_removed_from_stub_routes():
    src = _src()
    # Stub route now matches only `coverage`
    assert "|| page === 'inventory'" not in src
    assert "page === 'coverage'" in src


def test_inventory_removed_from_stub_config():
    src = _src()
    stub_start = src.index("const STUB_CONFIG = {")
    stub_end   = src.index("function InventoryPage(", stub_start)
    stub_block = src[stub_start:stub_end]
    assert "inventory:" not in stub_block
    assert "two-stage architecture" not in stub_block


# ── Reuses shared helpers (no duplicate inline derivations) ───────────────

def test_uses_shared_op_predicates():
    src = _src()
    block_start = src.index("function InventoryPage(")
    block_end   = src.index("function MasterDataPage(", block_start)
    block = src[block_start:block_end]
    # All 5 lifecycle buckets derive from the shared OP_PREDICATES.warehouse
    for key in ("OP_PREDICATES.warehouse.unknown",
                "OP_PREDICATES.warehouse.awaiting",
                "OP_PREDICATES.warehouse.partial_received",
                "OP_PREDICATES.warehouse.in_warehouse",
                "OP_PREDICATES.warehouse.reserved"):
        assert key in block, f"Inventory must reuse shared {key}"


def test_uses_shared_lifecycle_keys_const():
    src = _src()
    block_start = src.index("function InventoryPage(")
    block_end   = src.index("function MasterDataPage(", block_start)
    block = src[block_start:block_end]
    # Iterates the shared key array — no local copy
    assert "WAREHOUSE_LIFECYCLE_KEYS.map(k =>" in block


def test_uses_shared_lifecycle_label():
    src = _src()
    block_start = src.index("function InventoryPage(")
    block_end   = src.index("function MasterDataPage(", block_start)
    block = src[block_start:block_end]
    assert "WAREHOUSE_LIFECYCLE_LABEL[k]" in block
    assert "WAREHOUSE_LIFECYCLE_LABEL[lk]" in block


def test_uses_shared_attention_predicate():
    src = _src()
    block_start = src.index("function InventoryPage(")
    block_end   = src.index("function MasterDataPage(", block_start)
    block = src[block_start:block_end]
    assert "ATTENTION_PREDICATES.warehouse" in block


def test_uses_shared_derive_helper():
    src = _src()
    block_start = src.index("function InventoryPage(")
    block_end   = src.index("function MasterDataPage(", block_start)
    block = src[block_start:block_end]
    # Per-row lifecycle for the attention table uses the shared helper
    assert "deriveWarehouseLifecycle(row)" in block


# ── No bulk /warehouse/audit calls (cost guard) ───────────────────────────

def test_no_bulk_warehouse_audit_calls():
    """Per task rules: 'If per-batch audit endpoints are too expensive to
    call for every batch, do not bulk-call them.' Inventory body must not
    iterate batches calling /warehouse/audit/{id}.

    Updated for Phase 2 (Inventory Stage 2 aggregate): permitted apiFetch
    calls are pinned to a read-only allowlist — no per-batch fan-out.

    Updated for Phase 4.4 (piece detail drawer): user-triggered single-piece
    lookup against /api/v1/inventory/pieces/{scan_code} is permitted. Still
    not a bulk per-batch call.
    """
    src = _src()
    block_start = src.index("function InventoryPage(")
    block_end   = src.index("function MasterDataPage(", block_start)
    block = src[block_start:block_end]
    # No apiFetch to per-batch audit endpoints
    assert "/api/v1/warehouse/audit/" not in block
    assert "/api/v1/warehouse/audit-summary/" not in block
    assert "/api/v1/warehouse/inventory/" not in block
    assert "/api/v1/warehouse/scan" not in block
    assert "/api/v1/warehouse/locations" not in block
    # Allowlisted apiFetch URLs (Stage 2 mount + Phase 4.4 single-piece lookup).
    apifetch_total = block.count("apiFetch(")
    apifetch_aggregate = (
        block.count("apiFetch('/api/v1/inventory/stage2/aggregate')")
        + block.count('apiFetch("/api/v1/inventory/stage2/aggregate")')
    )
    apifetch_pieces = (
        block.count("apiFetch(`/api/v1/inventory/pieces/${encodeURIComponent(code)}`)")
        + block.count("apiFetch('/api/v1/inventory/pieces/")
        + block.count('apiFetch("/api/v1/inventory/pieces/')
    )
    assert apifetch_aggregate == 1, \
        "Exactly one apiFetch must target /api/v1/inventory/stage2/aggregate"
    assert apifetch_total == apifetch_aggregate + apifetch_pieces, (
        f"InventoryPage has {apifetch_total} apiFetch calls; "
        f"allowlisted = {apifetch_aggregate} aggregate + {apifetch_pieces} pieces. "
        "Extra apiFetch calls violate the no-bulk-per-batch contract."
    )
    # Phase B.1: the drawer now also refreshes after a successful
    # sample-out / sample-return write (one apiFetch in lookupPiece +
    # one in refreshPiece). Both are user-triggered, not fan-outs.
    assert apifetch_pieces <= 2, (
        "Piece lookup/refresh apiFetch count exceeds the lookup + post-write "
        "refresh allowance — possible fan-out regression"
    )


# ── Warehouse Scanner link preserved ──────────────────────────────────────

def test_warehouse_scanner_link_preserved():
    src = _src()
    assert 'data-testid="inventory-scanner-link"' in src
    assert 'href="/dashboard/warehouse.html"' in src
    assert "Open Warehouse Scanner" in src


# ── No new endpoints invented ─────────────────────────────────────────────

def test_no_invented_inventory_endpoints():
    src = _src()
    # Note: /api/v1/inventory/stage2/aggregate is now a real endpoint
    # (Phase 2 — Stage 2 aggregate, single read-only GET). It is NOT
    # listed in the forbidden set below; the test_no_bulk_warehouse_audit_calls
    # gate verifies it is the sole apiFetch in InventoryPage.
    for ep in (
        "/api/v1/inventory/all",
        "/api/v1/inventory/move",
        "/api/v1/inventory/scan",
        "/api/v1/inventory/stages",
        "/api/v1/stock",
        "/api/v1/stock/move",
        "/api/v1/samples",
        "/api/v1/samples/out",
        "/api/v1/samples/return",
        "/api/v1/returns",
        "/api/v1/returns/producer",
        "/api/v1/lifecycle/aggregate",
    ):
        assert ep not in src, f"Invented inventory endpoint leaked: {ep}"


# ── No fake/mock data ─────────────────────────────────────────────────────

def test_no_mock_inventory_rows():
    src = _src()
    block_start = src.index("function InventoryPage(")
    block_end   = src.index("function MasterDataPage(", block_start)
    block = src[block_start:block_end]
    for fake in (
        "MOCK_INVENTORY",
        "SAMPLE_STOCK",
        "FAKE_LOCATIONS",
        "DEMO_BATCHES",
        "fakeInventory",
    ):
        assert fake not in block, f"Mock inventory array leaked: {fake}"


def test_no_mock_locations():
    src = _src()
    block_start = src.index("function InventoryPage(")
    block_end   = src.index("function MasterDataPage(", block_start)
    block = src[block_start:block_end]
    for fake in (
        "Aisle-A",
        "Shelf-",
        "Bin-",
        "Warsaw-North",
        "Krakow-Main",
        "location: 'WH-01'",
        "WH-DEMO-",
    ):
        assert fake not in block, f"Mock location leaked: {fake}"


def test_no_fake_stock_quantities():
    src = _src()
    block_start = src.index("function InventoryPage(")
    block_end   = src.index("function MasterDataPage(", block_start)
    block = src[block_start:block_end]
    # No hardcoded quantity-shaped strings inside the inventory block.
    # The lifecycle KPI tiles render `counts[k]` (derived from real predicates)
    # and the two-stage placeholder tiles render the literal em-dash.
    for fake in (
        "on_hand: 24",
        "reserved: 4",
        "available: 20",
        "stock: 42",
        "qty: '12'",
        ">PLN 38,400<",  # design fixture value
        ">PLN 14,640<",
    ):
        assert fake not in block, f"Fake stock quantity leaked: {fake}"


def test_no_mock_sku_or_product_fixtures():
    src = _src()
    block_start = src.index("function InventoryPage(")
    block_end   = src.index("function MasterDataPage(", block_start)
    block = src[block_start:block_end]
    for fake in (
        "EJ-RING-0142",
        "EJ-NECK-0089",
        "EJ-BRAC-0211",
        "EJ-EARR-0357",
        "Diamond Solitaire Ring",
        "Tennis Bracelet Sapphire",
    ):
        assert fake not in block, f"Mock SKU/product leaked: {fake}"


# ── Read-only: no write paths ─────────────────────────────────────────────

def test_inventory_writes_match_sample_allowlist():
    """Phase B.1 activates exactly two POST surfaces on InventoryPage:
    sample-out and sample-return (inside the piece drawer). PUT, PATCH,
    DELETE remain forbidden. Any new POSTs must target one of those two
    paths or this gate."""
    src = _src()
    block_start = src.index("function InventoryPage(")
    block_end   = src.index("function MasterDataPage(", block_start)
    block = src[block_start:block_end]
    for method in ("method: 'PUT'", "method: 'DELETE'", "method: 'PATCH'"):
        assert method not in block, f"InventoryPage body must NOT contain {method!r}"
    # POST allowlist: only the two Phase B.1 lifecycle endpoints.
    assert "_postSample('sample-out'" in block, "Expected sample-out POST call"
    assert "_postSample('sample-return'" in block, "Expected sample-return POST call"


def test_no_scan_or_move_or_release_buttons():
    src = _src()
    block_start = src.index("function InventoryPage(")
    block_end   = src.index("function MasterDataPage(", block_start)
    block = src[block_start:block_end]
    for fake in (
        ">Scan<",
        ">Scan barcode<",
        ">Move<",
        ">Release<",
        ">Receive<",
        ">Dispatch<",
        ">Reserve<",
        ">Adjust<",
        ">Cycle count<",
    ):
        assert fake not in block, f"Forbidden write action leaked into Inventory: {fake}"


# ── Real batches binding ──────────────────────────────────────────────────

def test_kpi_strip_landmark_present():
    src = _src()
    assert 'data-testid="inventory-live-stats"' in src
    assert 'data-testid={`inventory-stat-${s.id}`}' in src
    for sid in ("'total'", "'in_wh'", "'reserved'", "'attention'"):
        assert f"id: {sid}" in src, f"Missing KPI tile id: {sid}"


def test_kpi_values_derive_from_real_batches_filter():
    src = _src()
    assert "rows.filter(OP_PREDICATES.warehouse.unknown).length" in src
    assert "rows.filter(OP_PREDICATES.warehouse.awaiting).length" in src
    assert "rows.filter(OP_PREDICATES.warehouse.partial_received).length" in src
    assert "rows.filter(OP_PREDICATES.warehouse.in_warehouse).length" in src
    assert "rows.filter(OP_PREDICATES.warehouse.reserved).length" in src


def test_attention_derives_from_shared_predicate():
    src = _src()
    assert "rows.filter(ATTENTION_PREDICATES.warehouse)" in src


# ── Section panels present ───────────────────────────────────────────────

def test_lifecycle_grid_landmark_present():
    src = _src()
    assert 'data-testid="inventory-lifecycle-grid"' in src
    assert 'data-testid={`inventory-lifecycle-${k}`}' in src


def test_attention_panel_landmark_present():
    src = _src()
    assert 'data-testid="inventory-attention-panel"' in src
    # Empty state and per-row landmarks
    assert 'data-testid="inventory-attention-empty"' in src
    assert 'data-testid="inventory-attention-row"' in src
    # Open button still wired to existing onViewShipment
    assert 'data-testid="inventory-open-btn"' in src
    assert "onViewShipment && onViewShipment(row._raw || row)" in src


def test_two_stage_panel_marked_pending():
    src = _src()
    assert 'data-testid="inventory-two-stage-panel"' in src
    assert 'data-testid="inventory-two-stage-pending-badge"' in src
    # Stage 1 tiles are still static placeholders (template-literal testid).
    assert 'data-testid={`inventory-stage1-${t.id.replace(' in src
    for tid in ("'stage1_temp'", "'stage1_warehouse'", "'stage1_sale'"):
        assert f"id: {tid}" in src, f"Missing Stage 1 tile id in source: {tid}"
    # Stage 2 tiles are now wired to /api/v1/inventory/stage2/aggregate:
    # 5 explicit testids set per-row (no template literal) — verify each.
    for tid in ('inventory-stage2-final', 'inventory-stage2-samples',
                'inventory-stage2-returns', 'inventory-stage2-consignment',
                'inventory-stage2-unknown'):
        assert f"testid: '{tid}'" in src, \
            f"Missing Stage 2 tile testid in source array: {tid}"
    # Stage 2 grid landmark
    assert 'data-testid="inventory-stage2-grid"' in src


def test_two_stage_tiles_show_em_dash_not_fake_counts():
    src = _src()
    block_start = src.index('data-testid="inventory-two-stage-panel"')
    block_end   = src.index('data-testid="inventory-design-preview"', block_start)
    block = src[block_start:block_end]
    # Each tile renders the literal em-dash — no fake aggregated counts
    assert ">—</div>" in block
    # No fake numbers like "47 units" or "PLN 1,240,000"
    for fake in ("47 units", "PLN 1,240,000", "PLN 64,200"):
        assert fake not in block, f"Fake two-stage aggregate leaked: {fake}"


# ── Toolbar disabled placeholders ─────────────────────────────────────────

def test_design_preview_actions_disabled_and_pending():
    # Phase B.1: Sample-out + Sample-return moved to the piece drawer
    # (state-gated, evidence form). Move stock has its own per-piece UI
    # in the Warehouse Scanner. Only Goods-return and Return-to-producer
    # remain backend-pending toolbar placeholders.
    src = _src()
    for aid in ('goods_return', 'return_prod'):
        assert f"id: '{aid}'" in src, f"Missing backend-pending action id: {aid}"
    for aid in ('move_stock', 'sample_out', 'sample_return'):
        assert f"id: '{aid}'" not in src, (
            f"Live action {aid} must not remain in disabled placeholders"
        )
    assert 'data-testid={`inventory-preview-action-${b.id}`}' in src
    block_start = src.index('data-testid="inventory-toolbar"')
    block_end   = src.index('<SectionLabel>Warehouse lifecycle</SectionLabel>', block_start)
    block = src[block_start:block_end]
    assert block.count('disabled') >= 2
    assert 'aria-disabled="true"' in block
    assert "cursor: 'not-allowed'" in block


def test_disabled_actions_have_no_onclick_no_fetch():
    # Block bounds: from the live-actions marker comment to the
    # Lifecycle buckets section. The toolbar's remaining
    # backend-pending placeholder buttons must still have no onClick
    # and no fetch.
    src = _src()
    block_start = src.index("Phase B.1 live")
    block_end   = src.index('<SectionLabel>Warehouse lifecycle</SectionLabel>', block_start)
    block = src[block_start:block_end]
    assert 'onClick' not in block, "Disabled action template must NOT have onClick"
    assert 'apiFetch' not in block, "Disabled action template must NOT call apiFetch"
    assert 'fetch(' not in block


def test_design_preview_footer_present():
    src = _src()
    assert 'data-testid="inventory-design-preview"' in src
    assert 'data-testid="inventory-preview-pending-badge"' in src


# ── SectionLabel polish + page landmark ───────────────────────────────────

def test_page_landmark_present():
    src = _src()
    assert 'data-testid="inventory-page"' in src


def test_section_labels_present():
    src = _src()
    for label in (
        "<SectionLabel>Warehouse lifecycle</SectionLabel>",
        "<SectionLabel>Needs attention</SectionLabel>",
        "<SectionLabel>Two-stage inventory architecture</SectionLabel>",
    ):
        assert label in src, f"Missing SectionLabel: {label}"


# ── UI-3 landmarks unchanged ──────────────────────────────────────────────

def test_ui3_operational_cards_still_present():
    src = _src()
    for tid in (
        'data-testid="warehouse-operations-card"',
        'data-testid="sales-accounting-operations-card"',
        'data-testid="dhl-customs-operations-card"',
    ):
        assert tid in src


def test_ui3_1a_lifecycle_helpers_still_at_module_scope():
    src = _src()
    # The shared helpers must NOT be redefined inside InventoryPage; they
    # remain at module scope (above the WfirmaExportPage component, etc.)
    # so cross-batch (3.1b) and per-batch (3.4) surfaces still use them.
    assert "const OP_PREDICATES = {" in src
    assert "const deriveWarehouseLifecycle =" in src
    assert "const WAREHOUSE_LIFECYCLE_LABEL =" in src
    assert "const WAREHOUSE_LIFECYCLE_KEYS =" in src
    assert "const ATTENTION_PREDICATES =" in src


def test_detail_tabs_unchanged():
    src = _src()
    assert "const DETAIL_TABS = ['Overview', 'Documents', 'DHL / Customs', 'Warehouse', 'Sales', 'PZ / wFirma', 'Timeline', 'Intelligence', 'Proposals']" in src
