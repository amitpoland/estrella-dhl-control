"""
test_dashboard_wfirma_design.py — Path B / Pass 11.

Contract for the wFirma page (WfirmaExportPage) design pass:
  - Live wFirma surface remains the ONLY real data source
  - Real endpoints preserved: /api/v1/wfirma/capabilities,
    /contractors/search, /goods/search, /customers, /customers/{id},
    /products, /products/{id}
  - Live KPI strip derives values from real state arrays (no fake counts)
  - Design-preview strip (Last full sync, Sync status breakdown, Sync
    drift, Sync errors + bulk re-sync/diagnostic/CSV export actions) is
    visually marked and disabled
  - Preview controls emit NO network calls and NO state changes
  - No mock customers, no mock products, no mock wFirma IDs, no mock
    capability statuses
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


# ── Live wFirma endpoints preserved ────────────────────────────────────────

def test_wfirma_component_present():
    assert "function WfirmaExportPage({ batches, onViewShipment })" in _src()


def test_wfirma_route_wired():
    src = _src()
    assert "page === 'wfirma_setup'" in src
    assert "<WfirmaExportPage" in src


def test_capabilities_endpoint_intact():
    assert "apiFetch('/api/v1/wfirma/capabilities')" in _src()


def test_contractors_search_endpoint_intact():
    src = _src()
    assert "apiFetch(`/api/v1/wfirma/contractors/search?${params}`)" in src


def test_goods_search_endpoint_intact():
    src = _src()
    assert "apiFetch(`/api/v1/wfirma/goods/search?${params}`)" in src


def test_customers_list_endpoint_intact():
    src = _src()
    assert "apiFetch(`/api/v1/wfirma/customers${qs}`)" in src


def test_products_list_endpoint_intact():
    src = _src()
    assert "apiFetch(`/api/v1/wfirma/products${qs}`)" in src


def test_customer_save_endpoint_intact():
    src = _src()
    # PUT /api/v1/wfirma/customers/{client_name}
    assert "/api/v1/wfirma/customers/${encodeURIComponent(editingCustomer.client_name.trim())}" in src


def test_product_save_endpoint_intact():
    src = _src()
    # PUT /api/v1/wfirma/products/{product_code}
    assert "/api/v1/wfirma/products/${encodeURIComponent(editingProduct.product_code.trim())}" in src


# ── Existing write guards preserved ────────────────────────────────────────

def test_customer_save_validation_intact():
    src = _src()
    assert "if (!editingCustomer || !editingCustomer.client_name?.trim())" in src
    assert "setModalError('Client name is required')" in src


def test_product_save_validation_intact():
    src = _src()
    assert "if (!editingProduct || !editingProduct.product_code?.trim())" in src
    assert "setModalError('Product code is required')" in src


def test_customer_save_uses_put_method():
    src = _src()
    # PUT method preserved (not POST — auto-create is forbidden per project rules)
    assert "method: 'PUT'" in src


# ── Live KPI strip uses real state ─────────────────────────────────────────

def test_wfirma_live_stats_strip_present():
    src = _src()
    assert 'data-testid="wfirma-live-stats"' in src
    assert 'data-testid={`wfirma-stat-${s.id}`}' in src
    for sid in ("'ready'", "'exported'", "'locked'", "'caps'"):
        assert f"id: {sid}" in src, f"Missing wFirma stat id: {sid}"


def test_kpi_ready_derives_from_real_array():
    src = _src()
    assert "ready:    ready.length" in src


def test_kpi_exported_derives_from_real_array():
    src = _src()
    assert "exported: exported.length" in src


def test_kpi_locked_derives_from_real_array():
    src = _src()
    assert "locked:   locked.length" in src


def test_kpi_caps_derives_from_real_capabilities():
    src = _src()
    # Caps count derives from real capabilities object — keys filtered by ===true
    assert "capabilities ? Object.keys(capabilities).filter(k => k !== 'error' && capabilities[k] === true).length : 0" in src


# ── Design preview strip present and marked ────────────────────────────────

def test_wfirma_preview_strip_present():
    assert 'data-testid="wfirma-design-preview"' in _src()


def test_wfirma_preview_has_pending_badge():
    assert 'data-testid="wfirma-preview-pending-badge"' in _src()


def test_wfirma_preview_widgets_present():
    src = _src()
    assert 'data-testid="wfirma-preview-widgets"' in src
    assert 'data-testid={`wfirma-preview-widget-${c.id}`}' in src
    for wid in ("'last_sync'", "'sync_status_break'", "'sync_drift'", "'sync_errors'"):
        assert f"id: {wid}" in src, f"Missing preview widget id: {wid}"


def test_wfirma_preview_actions_present():
    src = _src()
    assert 'data-testid="wfirma-preview-actions"' in src
    assert 'data-testid={`wfirma-preview-action-${b.id}`}' in src
    for aid in ("'bulk_resync'", "'run_diagnostic'", "'export_csv'"):
        assert f"id: {aid}" in src, f"Missing preview action id: {aid}"


# ── Preview controls disabled / non-executable ─────────────────────────────

def test_wfirma_preview_buttons_disabled():
    src = _src()
    block_start = src.index('data-testid="wfirma-design-preview"')
    block_end   = src.index('wFirma export &amp; mapping')
    block = src[block_start:block_end]
    assert block.count('disabled') >= 2
    assert 'aria-disabled="true"' in block
    assert "cursor: 'not-allowed'" in block


def test_wfirma_preview_no_onclick_no_fetch():
    src = _src()
    block_start = src.index('data-testid="wfirma-design-preview"')
    block_end   = src.index('wFirma export &amp; mapping')
    block = src[block_start:block_end]
    assert 'onClick' not in block, "Preview block must NOT have onClick"
    assert 'apiFetch' not in block, "Preview block must NOT call apiFetch"
    assert 'fetch(' not in block,   "Preview block must NOT call fetch()"
    assert 'dispatchEvent' not in block


def test_wfirma_preview_widgets_show_em_dash():
    src = _src()
    block_start = src.index('data-testid="wfirma-preview-widgets"')
    block_end   = src.index('data-testid="wfirma-preview-actions"')
    block = src[block_start:block_end]
    assert '>—</div>' in block


def test_wfirma_preview_pending_attribute_present():
    src = _src()
    block_start = src.index('data-testid="wfirma-design-preview"')
    block_end   = src.index('wFirma export &amp; mapping')
    block = src[block_start:block_end]
    assert block.count('data-pending="true"') >= 2


# ── Anti-fake: no mock customer / product / wFirma-id rows ─────────────────

def test_no_mock_customer_names():
    src = _src()
    # Design fixture customers
    for fake in (
        "Bijoux Maison Paris",
        "Goldhaus Berlin",
        "Atelier Lyon",
        "Joaillerie Geneva",
    ):
        assert fake not in src, f"Mock customer name leaked: {fake}"


def test_no_mock_wfirma_ids():
    src = _src()
    # Design fixture wFirma IDs
    for fake in (
        "WF-CUST-104",
        "WF-CUST-108",
        "WF-CUST-112",
        "WF-PROD-9921",
        "WF-PROD-9922",
        "WF-PROD-9931",
        "WF-PROD-9932",
    ):
        assert fake not in src, f"Mock wFirma id leaked: {fake}"


def test_no_mock_vat_ids():
    src = _src()
    for fake in (
        "FR12345678901",
        "DE987654321",
        "FR55667788990",
        "CHE112233445",
    ):
        assert fake not in src, f"Mock VAT id leaked: {fake}"


def test_no_mock_product_codes_introduced():
    src = _src()
    # The design's fixture product codes (EJL/26-27/015-N) are seed data
    # from a separate flow. They must not appear inside the wFirma block.
    block_start = src.index("function WfirmaExportPage")
    # Find a stable end marker — the next top-level function decl below
    rest = src[block_start:]
    block_end_idx = rest.find("\nfunction ", 200)
    block = rest[:block_end_idx] if block_end_idx > 0 else rest[:30000]
    for fake in (
        "EJL/26-27/015-1",
        "EJL/26-27/015-2",
        "Solitaire 1.0ct",
        "Halo bracelet",
        "Pavé pendant",
    ):
        assert fake not in block, f"Mock product code/name leaked into wFirma block: {fake}"


def test_no_mock_capability_pills():
    src = _src()
    block_start = src.index('data-testid="wfirma-design-preview"')
    block_end   = src.index('wFirma export &amp; mapping')
    block = src[block_start:block_end]
    # Design fixture capability labels — these strings should not appear
    # inside the preview block as hardcoded text.
    for fake in (
        "customers.read",
        "customers.write",
        "goods.read",
        "goods.write",
        "reservation.write",
    ):
        assert fake not in block, f"Mock capability label leaked into preview: {fake}"


def test_no_mock_blocking_reasons():
    src = _src()
    block_start = src.index('data-testid="wfirma-design-preview"')
    block_end   = src.index('wFirma export &amp; mapping')
    block = src[block_start:block_end]
    for fake in (
        "WFIRMA_WAREHOUSE_ID missing",
        "reservation.write scope not granted",
    ):
        assert fake not in block, f"Mock blocking reason leaked: {fake}"


# ── Anti-fake: no invented endpoints ───────────────────────────────────────

def test_no_invented_wfirma_endpoints():
    src = _src()
    for ep in (
        "/api/v1/wfirma/sync-all",
        "/api/v1/wfirma/sync-status",
        "/api/v1/wfirma/diagnostic",
        "/api/v1/wfirma/bulk-resync",
        "/api/v1/wfirma/last-sync",
        "/api/v1/wfirma/sync-errors",
        "/api/v1/wfirma/export-mapping",
    ):
        assert ep not in src, f"Invented wFirma endpoint leaked: {ep}"


# ── SectionLabel polish + page landmarks ───────────────────────────────────

def test_page_landmark_present():
    src = _src()
    assert 'data-testid="wfirma-page"' in src


def test_subtabs_landmark_present():
    src = _src()
    assert 'data-testid="wfirma-subtabs"' in src


def test_section_label_polish_applied():
    src = _src()
    assert "<SectionLabel>wFirma export &amp; mapping</SectionLabel>" in src


# ── Existing Export sub-tab content preserved ──────────────────────────────

def test_export_subtab_stats_row_intact():
    src = _src()
    # Existing 3-stat StatsRow remains on Export sub-tab
    assert "label: 'Ready for wFirma'" in src
    assert "label: 'Exported to wFirma'" in src
    assert "label: 'PZ Pending'" in src


def test_export_workflow_explainer_intact():
    src = _src()
    # The "How wFirma warehouse PZ works" explainer is the
    # operator-facing safety doc — must survive design polish
    assert "How wFirma warehouse PZ works" in src
    assert "Resolve Products" in src
    assert "Create wFirma PZ" in src


# ── Statement modal (Phase 10D — Ledgers) intact ──────────────────────────

def test_statement_modal_state_intact():
    src = _src()
    # The drawer state set by clicking Statement button on a customer row
    assert "setCustomerForStatement" in src


def test_statement_endpoints_intact():
    src = _src()
    # Real ledger endpoints — JSON and PDF
    assert "/api/v1/ledgers/clients/${encodeURIComponent(cid)}" in src
    assert "/statement.json" in src
    assert "/statement.pdf" in src


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
