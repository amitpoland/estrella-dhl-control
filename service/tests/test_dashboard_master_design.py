"""
test_dashboard_master_design.py — Path B / Tier 2 / Pass 16.

Contract for the new Master Data composition page:
  - Frontend composition only; ZERO new backend invented
  - All entity rows derived from real /auth/users, /api/v1/wfirma/customers,
    /api/v1/wfirma/products
  - Each source loads independently (Promise-isolated failures)
  - No fake entities, no mock suppliers/designs/HS codes/FX rates/roles
  - Read-only — no create/edit/delete/write actions
  - Search is purely client-side over loaded real rows
  - Pending entity types (Suppliers / Designs / HS codes / FX rates / Roles)
    rendered as disabled "Backend pending" placeholders
  - master no longer routes to StubPage
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


# ── master is now a real composition route, not a stub ───────────────────

def test_master_component_present():
    src = _src()
    assert "function MasterDataPage({ onNav, onToast })" in src


def test_master_route_renders_real_component():
    src = _src()
    assert "page === 'master' && (" in src
    assert "<MasterDataPage" in src


def test_master_removed_from_stub_routes():
    src = _src()
    assert "|| page === 'master'" not in src
    for stub in ("'inventory'", "'coverage'"):
        assert f"page === {stub}" in src, f"Stub route missing for {stub}"


def test_master_removed_from_stub_config():
    src = _src()
    stub_start = src.index("const STUB_CONFIG = {")
    stub_end   = src.index("function MasterDataPage(", stub_start)
    stub_block = src[stub_start:stub_end]
    assert "master:" not in stub_block
    assert "clients, suppliers, products, designs" not in stub_block


# ── Real endpoint usage ────────────────────────────────────────────────────

def test_users_endpoint_used():
    assert "apiFetch('/auth/users')" in _src()


def test_customers_endpoint_used():
    assert "apiFetch('/api/v1/wfirma/customers')" in _src()


def test_products_endpoint_used():
    assert "apiFetch('/api/v1/wfirma/products')" in _src()


def test_three_loaders_present():
    src = _src()
    for fn in ("loadUsers", "loadCustomers", "loadProducts"):
        assert f"const {fn} = React.useCallback" in src, f"Missing loader: {fn}"


# ── No new endpoints invented ──────────────────────────────────────────────

def test_no_invented_master_endpoints():
    src = _src()
    for ep in (
        "/api/v1/master",
        "/api/v1/master/users",
        "/api/v1/master/customers",
        "/api/v1/master/products",
        "/api/v1/master/suppliers",
        "/api/v1/master/designs",
        "/api/v1/master/hs-codes",
        "/api/v1/master/fx-rates",
        "/api/v1/master/roles",
        "/api/v1/suppliers",
        "/api/v1/designs",
        "/api/v1/hs-codes",
        "/api/v1/fx-rates",
        "/api/v1/roles",
    ):
        assert ep not in src, f"Invented master-data endpoint leaked: {ep}"


# ── No fake/mock entity rows ──────────────────────────────────────────────

def test_no_mock_user_fixtures():
    src = _src()
    block_start = src.index("function MasterDataPage(")
    block_end   = src.index("function CarriersPage(", block_start)
    block = src[block_start:block_end]
    for fake in (
        "MOCK_USERS",
        "SAMPLE_USERS",
        "FAKE_USERS",
        "demo@estrella.pl",
        "admin@estrella.pl",
        "Karolina Nowak",
        "Marek Kowalski",
    ):
        assert fake not in block, f"Mock user fixture leaked: {fake}"


def test_no_mock_customer_fixtures():
    src = _src()
    block_start = src.index("function MasterDataPage(")
    block_end   = src.index("function CarriersPage(", block_start)
    block = src[block_start:block_end]
    for fake in (
        "MOCK_CUSTOMERS",
        "SAMPLE_CUSTOMERS",
        "Bijoux Maison Paris",
        "Goldhaus Berlin",
        "Atelier Lyon",
        "WF-CUST-104",
        "WF-CUST-108",
    ):
        assert fake not in block, f"Mock customer fixture leaked: {fake}"


def test_no_mock_product_fixtures():
    src = _src()
    block_start = src.index("function MasterDataPage(")
    block_end   = src.index("function CarriersPage(", block_start)
    block = src[block_start:block_end]
    for fake in (
        "MOCK_PRODUCTS",
        "EJL/26-27/015-1",
        "Solitaire 1.0ct",
        "WF-PROD-9921",
        "Halo bracelet",
    ):
        assert fake not in block, f"Mock product fixture leaked: {fake}"


def test_no_mock_supplier_or_design_or_hs_or_fx():
    src = _src()
    block_start = src.index("function MasterDataPage(")
    block_end   = src.index("function CarriersPage(", block_start)
    block = src[block_start:block_end]
    # All these entity types are explicitly Backend pending — no rows.
    for fake in (
        "MOCK_SUPPLIERS",
        "SAMPLE_DESIGNS",
        "HS_FIXTURES",
        "FX_DEMO",
        # Pattern shapes
        "'71131900'",       # HS code fixture
        "'4.2650 PLN'",     # FX rate fixture
        "Tiffany supplier",
    ):
        assert fake not in block, f"Mock pending-entity fixture leaked: {fake}"


# ── Read-only: no create/edit/delete write paths ──────────────────────────

def test_no_new_write_paths_in_master():
    src = _src()
    block_start = src.index("function MasterDataPage(")
    block_end   = src.index("function CarriersPage(", block_start)
    block = src[block_start:block_end]
    for method in ("method: 'POST'", "method: 'PUT'", "method: 'DELETE'", "method: 'PATCH'"):
        assert method not in block, f"MasterDataPage body must NOT contain {method!r}"


def test_no_create_edit_delete_buttons():
    src = _src()
    block_start = src.index("function MasterDataPage(")
    block_end   = src.index("function CarriersPage(", block_start)
    block = src[block_start:block_end]
    for fake in (
        ">+ New<",
        ">Add user<",
        ">Add customer<",
        ">Add product<",
        ">Invite<",
        ">Approve<",
        ">Edit<",
        ">Delete<",
        ">Save<",
        ">Import<",
    ):
        assert fake not in block, f"Forbidden write action leaked into Master Data: {fake}"


def test_search_is_client_side_only():
    src = _src()
    # The search input updates only local `query` state — no apiFetch
    # triggered on input change.
    assert 'data-testid="master-search"' in src
    assert "onChange={e => setQuery(e.target.value)}" in src
    # The filter is .filter() over loaded items, not a server query
    for line in (
        "(users.items     || []).filter(r => _match(r, query))",
        "(customers.items || []).filter(r => _match(r, query))",
        "(products.items  || []).filter(r => _match(r, query))",
    ):
        assert line in src, f"Client-side filter missing: {line!r}"


def test_recheck_is_safe_get_reload():
    src = _src()
    assert 'data-testid="master-refresh"' in src
    assert "onClick={reloadAll}" in src
    assert "↻ Re-check" in src
    # reloadAll invokes only the 3 GET loaders
    assert "loadUsers(); loadCustomers(); loadProducts();" in src


# ── Isolated failures ─────────────────────────────────────────────────────

def test_per_source_state_objects():
    src = _src()
    for setter in ("setUsers", "setCustomers", "setProducts"):
        assert setter in src, f"Missing per-source setter: {setter}"


def test_per_source_error_banner_landmarks():
    src = _src()
    assert 'data-testid="master-source-errors"' in src
    assert 'data-testid={`master-source-error-${err.src}`}' in src


def test_failure_isolation_pattern():
    src = _src()
    block_start = src.index("function MasterDataPage(")
    block_end   = src.index("function CarriersPage(", block_start)
    block = src[block_start:block_end]
    # Per-source errors filter pattern + "other sources still shown"
    assert "].filter(Boolean)" in block
    assert "other sources still shown" in block


# ── KPI strip derived from real source counts ────────────────────────────

def test_kpi_strip_landmark_present():
    src = _src()
    assert 'data-testid="master-live-stats"' in src
    assert 'data-testid={`master-stat-${s.id}`}' in src
    for sid in ("'users'", "'customers'", "'products'", "'pending'"):
        assert f"id: {sid}" in src, f"Missing KPI tile id: {sid}"


def test_kpi_values_derive_from_real_arrays():
    src = _src()
    assert "(users.items     || []).length" in src
    assert "(customers.items || []).length" in src
    assert "(products.items  || []).length" in src


# ── Tab strip — 3 live + 5 pending ────────────────────────────────────────

def test_tabs_landmark_present():
    src = _src()
    assert 'data-testid="master-tabs"' in src
    assert 'data-testid={`master-tab-${t.id}`}' in src
    # All 8 ids defined
    for tid in ("'users'", "'customers'", "'products'", "'suppliers'", "'designs'", "'hs_codes'", "'fx_rates'", "'roles'"):
        assert f"id: {tid}" in src, f"Missing tab id: {tid}"


def test_three_tabs_marked_live():
    src = _src()
    # Live entity tabs explicitly set live: true
    for tid in ("'users'", "'customers'", "'products'"):
        # Just verify the entity-tab dict has live: true keyed to id
        pattern = f"id: {tid},"
        assert pattern in src
    # Live tabs use enabled style (not the disabled stub treatment)
    assert 'data-live="true"' in src


def test_five_tabs_marked_pending():
    src = _src()
    # The pending tabs use the disabled template with data-pending="true"
    # — and the data structure has live: false for them
    for line in (
        "id: 'suppliers', label: 'Suppliers',",
        "id: 'designs',   label: 'Designs',",
        "id: 'hs_codes',  label: 'HS codes',",
        "id: 'fx_rates',  label: 'FX rates',",
        "id: 'roles',     label: 'Roles',",
    ):
        assert line in src, f"Missing pending tab definition: {line!r}"


# ── Live entity panels ────────────────────────────────────────────────────

def test_users_panel_landmarks_present():
    src = _src()
    assert 'data-testid="master-users-panel"' in src
    for tid in ('master-users-loading', 'master-users-error',
                'master-users-empty',   'master-users-row'):
        assert f'data-testid="{tid}"' in src, f"Missing users panel landmark: {tid}"


def test_customers_panel_landmarks_present():
    src = _src()
    assert 'data-testid="master-customers-panel"' in src
    for tid in ('master-customers-loading', 'master-customers-error',
                'master-customers-empty',   'master-customers-row'):
        assert f'data-testid="{tid}"' in src, f"Missing customers panel landmark: {tid}"


def test_products_panel_landmarks_present():
    src = _src()
    assert 'data-testid="master-products-panel"' in src
    for tid in ('master-products-loading', 'master-products-error',
                'master-products-empty',   'master-products-row'):
        assert f'data-testid="{tid}"' in src, f"Missing products panel landmark: {tid}"


def test_users_table_uses_real_fields():
    src = _src()
    # Read directly from _safe_user keys: full_name, email, role, etc.
    for field in ("u.full_name", "u.email", "u.role", "u.is_approved",
                  "u.is_active", "u.approval_status", "u.created_at", "u.last_login"):
        assert field in src, f"Users table must use real field: {field}"


def test_customers_table_uses_real_fields():
    src = _src()
    for field in ("c.client_name", "c.wfirma_customer_id", "c.vat_id",
                  "c.country", "c.match_status"):
        assert field in src, f"Customers table must use real field: {field}"


def test_products_table_uses_real_fields():
    src = _src()
    for field in ("p.product_code", "p.wfirma_product_id", "p.product_name_pl",
                  "p.unit", "p.vat_rate", "p.sync_status"):
        assert field in src, f"Products table must use real field: {field}"


# ── Pending entity types panel ────────────────────────────────────────────

def test_pending_entity_panel_present():
    src = _src()
    assert 'data-testid="master-pending-panel"' in src
    assert 'data-testid="master-pending-badge"' in src
    assert 'data-testid="master-pending-grid"' in src
    assert 'data-testid={`master-pending-${t.id}`}' in src
    for tid in ("'suppliers'", "'designs'", "'hs_codes'", "'fx_rates'", "'roles'"):
        assert f"id: {tid}" in src, f"Missing pending placeholder id: {tid}"


def test_pending_entities_show_em_dash():
    src = _src()
    block_start = src.index('data-testid="master-pending-panel"')
    block_end   = src.index('data-testid="master-design-preview"', block_start)
    block = src[block_start:block_end]
    # Each placeholder tile renders an em-dash value (no fake counts)
    assert '>—</div>' in block


# ── Design preview footer ─────────────────────────────────────────────────

def test_design_preview_footer_present():
    src = _src()
    assert 'data-testid="master-design-preview"' in src
    assert 'data-testid="master-preview-pending-badge"' in src


# ── SectionLabel polish + page landmark ───────────────────────────────────

def test_page_landmark_present():
    src = _src()
    assert 'data-testid="master-page"' in src


def test_section_labels_present():
    src = _src()
    assert "<SectionLabel>Entity browser</SectionLabel>" in src
    assert "Other entity types</SectionLabel>" in src


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
