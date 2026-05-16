"""
test_dashboard_master_design.py — source-grep contract for the Master Data module.

Pass 16 → Pass 17: updated for sidebar/modal architecture.

Covers:
  MasterDataPage
    - sidebar layout with ENTITIES array (4 live + 9 pending)
    - KPI strip derived from real source counts
    - search is client-side only
    - 4 real loaders (users, customers, products, customer_master)
    - live entity panels: users, clients (wFirma), products, customer master
    - pending entity panel (structure preview only, no fake data)
    - design-preview footer with accurate pending label
    - page landmark, route wiring, no stub regression
    - only allowed write: PUT /api/v1/customer-master/ (inline CM edit)
    - no DELETE / PATCH / POST in MasterDataPage body
    - no mock / fake entity fixtures
    - no invented endpoints

  ClientKycModal
    - component present, defined before MasterDataPage
    - 6-tab KYC editor (KYC_TABS array)
    - 3 wired tabs: basic, shipping, kuke
    - 3 backend-pending tabs: carriers, kyc, invoices
    - Company/Basic: bill_to_name, country, nip, vat_eu_number, currency, notes
    - Shipping: use_alternate checkbox + full ship-to address fields
    - KUKE & Credit: kuke_approved, kuke_limit, kuke_currency, kuke_expiry,
                     credit_limit, credit_currency, risk_status
    - Carriers / KYC / Invoices: pending panels, Save disabled
    - Save calls PUT /api/v1/customer-master/{contractorId} only
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


def _master_block(src: str) -> str:
    """Block from function MasterDataPage( to function CarriersPage(."""
    start = src.index("function MasterDataPage(")
    end   = src.index("function CarriersPage(", start)
    return src[start:end]


def _kyc_block(src: str) -> str:
    """Block from function ClientKycModal( to function MasterDataPage(."""
    start = src.index("function ClientKycModal(")
    end   = src.index("function MasterDataPage(", start)
    return src[start:end]


# ══════════════════════════════════════════════════════════════════════════════
# Route + component wiring (unchanged from Pass 16)
# ══════════════════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════════════════
# Real endpoint usage (unchanged)
# ══════════════════════════════════════════════════════════════════════════════

def test_users_endpoint_used():
    assert "apiFetch('/auth/users')" in _src()


def test_customers_endpoint_used():
    assert "apiFetch('/api/v1/wfirma/customers')" in _src()


def test_products_endpoint_used():
    assert "apiFetch('/api/v1/wfirma/products')" in _src()


def test_customer_master_endpoint_used():
    assert "apiFetch('/api/v1/customer-master/')" in _src()


def test_four_loaders_present():
    src = _src()
    for fn in ("loadUsers", "loadCustomers", "loadProducts", "loadCustomerMaster"):
        assert f"const {fn} = React.useCallback" in src, f"Missing loader: {fn}"


# ══════════════════════════════════════════════════════════════════════════════
# No invented endpoints
# ══════════════════════════════════════════════════════════════════════════════

def test_no_invented_master_endpoints():
    """Forbidden endpoints — these are NOT real backend routes; UI must not
    reference them. Any entity moved to live status must also have its forbidden
    line removed from this list (B4 suppliers, B5 hs-codes/units/product-local)."""
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
        # NOTE removed in B4: /api/v1/suppliers
        # NOTE removed in B5: /api/v1/hs-codes
        # NOTE removed in B8: /api/v1/fx-rates (reference-only, NOT a PZ override)
        # NOTE removed in B-MD2 (MDOC): /api/v1/designs (Designs master now live)
        "/api/v1/roles",
    ):
        assert ep not in src, f"Invented master-data endpoint leaked: {ep}"


# ══════════════════════════════════════════════════════════════════════════════
# No fake / mock entity rows
# ══════════════════════════════════════════════════════════════════════════════

def test_no_mock_user_fixtures():
    src = _src()
    block = _master_block(src)
    for fake in (
        "MOCK_USERS", "SAMPLE_USERS", "FAKE_USERS",
        "demo@estrella.pl", "admin@estrella.pl",
        "Karolina Nowak", "Marek Kowalski",
    ):
        assert fake not in block, f"Mock user fixture leaked: {fake}"


def test_no_mock_customer_fixtures():
    src = _src()
    block = _master_block(src)
    for fake in (
        "MOCK_CUSTOMERS", "SAMPLE_CUSTOMERS",
        "Bijoux Maison Paris", "Goldhaus Berlin", "Atelier Lyon",
        "WF-CUST-104", "WF-CUST-108",
    ):
        assert fake not in block, f"Mock customer fixture leaked: {fake}"


def test_no_mock_product_fixtures():
    src = _src()
    block = _master_block(src)
    for fake in (
        "MOCK_PRODUCTS", "EJL/26-27/015-1",
        "Solitaire 1.0ct", "WF-PROD-9921", "Halo bracelet",
    ):
        assert fake not in block, f"Mock product fixture leaked: {fake}"


def test_no_mock_supplier_or_design_or_hs_or_fx():
    src = _src()
    block = _master_block(src)
    for fake in (
        "MOCK_SUPPLIERS", "SAMPLE_DESIGNS", "HS_FIXTURES", "FX_DEMO",
        "'71131900'", "'4.2650 PLN'", "Tiffany supplier",
    ):
        assert fake not in block, f"Mock pending-entity fixture leaked: {fake}"


# ══════════════════════════════════════════════════════════════════════════════
# Write safety — MasterDataPage block
# ══════════════════════════════════════════════════════════════════════════════

def test_only_allowed_writes_in_master():
    """PATCH is never allowed. POST/DELETE/PUT are only allowed for explicitly
    wired master-data entities. After B5 the allow-list is:
    - customer-master         PUT
    - /api/v1/suppliers/      POST/PUT/DELETE  (B4)
    - /api/v1/hs-codes/       PUT/DELETE       (B5; upsert via PUT)
    - /api/v1/units/          PUT/DELETE       (B5)
    - /api/v1/product-local/  PUT/DELETE       (B5)
    """
    src = _src()
    block = _master_block(src)
    assert "method: 'PATCH'" not in block, \
        "MasterDataPage body must NOT contain method: 'PATCH'"
    import re
    posts = re.findall(r"apiFetch\(([^,]+),\s*\{\s*method:\s*'POST'", block)
    dels  = re.findall(r"apiFetch\(([^,]+),\s*\{\s*method:\s*'DELETE'", block)
    allowed_writes = (
        '/api/v1/suppliers',
        '/api/v1/hs-codes',
        '/api/v1/units',
        '/api/v1/product-local',
        '/api/v1/incoterms',
        '/api/v1/vat-config',
        '/api/v1/fx-rates',
        '/api/v1/carriers-config',
        '/api/v1/designs',   # B-MD2 (MDOC-2026-05): Designs master live
        '/api/v1/wfirma/capabilities/customers/sync',  # B0 (MDOC-cache): Customer Master sync surface (bulk + per-row apply); local cache write only
    )
    # b5Save / b5Delete are generic helpers that accept a basePath parameter;
    # their call sites (b5Save('/api/v1/hs-codes', ...) etc.) carry the literal
    # allowed-paths string. So allow `basePath` as a helper-parameter passthrough.
    HELPER_PASSTHROUGH = ('basePath',)
    for ep in posts + dels:
        if any(p in ep for p in HELPER_PASSTHROUGH):
            continue
        assert any(a in ep for a in allowed_writes), \
            f"POST/DELETE to non-allow-listed endpoint in MasterDataPage: {ep}"
    # Cross-check: every helper invocation must reference one of the allowed paths
    import re as _re
    helper_calls = _re.findall(r"b5(?:Save|Delete)\('([^']+)'", block)
    for call_path in helper_calls:
        assert any(a in call_path for a in allowed_writes), \
            f"b5 helper invoked with non-allow-listed path: {call_path}"
    # The legacy CM inline edit PUT must remain
    assert "method: 'PUT'" in block, "Customer Master inline edit PUT must be present"
    assert "customer-master" in block, "PUT must target /api/v1/customer-master/"


def test_no_dangerous_destructive_buttons_in_master():
    """Destructive identity actions (Approve user, Reject user, Deactivate user)
    must never appear in MasterDataPage. Per-row Delete on suppliers is allowed
    via the × icon and 'master-suppliers-btn-delete-*' testid, not via a
    spelled-out >Delete< label."""
    src = _src()
    block = _master_block(src)
    for forbidden in (">Approve<", ">Reject<", ">Deactivate<", ">Suspend<",
                      ">Delete user<", ">Delete client<"):
        assert forbidden not in block, f"Destructive identity action leaked: {forbidden}"


# ══════════════════════════════════════════════════════════════════════════════
# Search — client-side only (updated for new filter whitespace)
# ══════════════════════════════════════════════════════════════════════════════

def test_search_is_client_side_only():
    src = _src()
    assert 'data-testid="master-search"' in src
    assert "onChange={e => setQuery(e.target.value)}" in src
    # All three entity arrays are filtered client-side with _match()
    for arr in ("users.items", "customers.items", "products.items"):
        assert f"({arr}" in src, f"Missing client-side filter for {arr}"
    assert ".filter(r => _match(r, query))" in src, "Client-side _match filter missing"


def test_recheck_is_safe_get_reload():
    src = _src()
    assert 'data-testid="master-refresh"' in src
    assert "onClick={reloadAll}" in src
    assert "↻ Re-check" in src
    assert "loadUsers(); loadCustomers(); loadProducts();" in src


# ══════════════════════════════════════════════════════════════════════════════
# Isolated failures
# ══════════════════════════════════════════════════════════════════════════════

def test_per_source_state_objects():
    src = _src()
    for setter in ("setUsers", "setCustomers", "setProducts", "setCustMaster"):
        assert setter in src, f"Missing per-source setter: {setter}"


def test_per_source_error_banner_landmarks():
    """Error banner uses concat syntax (not backtick template literal)."""
    src = _src()
    assert 'data-testid="master-source-errors"' in src
    assert "data-testid={'master-source-error-' + err.src}" in src


def test_failure_isolation_pattern():
    src = _src()
    block = _master_block(src)
    assert "].filter(Boolean)" in block
    assert "other sources still shown" in block


# ══════════════════════════════════════════════════════════════════════════════
# KPI strip
# ══════════════════════════════════════════════════════════════════════════════

def test_kpi_strip_landmark_present():
    """KPI strip uses concat testid syntax (not backtick template literal)."""
    src = _src()
    assert 'data-testid="master-live-stats"' in src
    assert "data-testid={'master-stat-' + s.id}" in src
    for sid in ("'users'", "'customers'", "'products'", "'pending'"):
        assert f"id: {sid}" in src, f"Missing KPI tile id: {sid}"


def test_kpi_values_derive_from_real_arrays():
    src = _src()
    assert "(users.items" in src and "|| []).length" in src
    assert "(customers.items" in src
    assert "(products.items" in src


# ══════════════════════════════════════════════════════════════════════════════
# Sidebar navigation (replaces old tab strip)
# ══════════════════════════════════════════════════════════════════════════════

def test_sidebar_navigation_present():
    """Sidebar uses concat testid (not backtick template literal)."""
    src = _src()
    assert "data-testid={'master-sidebar-' + e.id}" in src


def test_four_live_entities_in_sidebar():
    src = _src()
    for eid in ("'clients'", "'users'", "'products'", "'customer_master'"):
        assert f"id: {eid}" in src, f"Missing live entity id: {eid}"
    assert "live: true" in src, "live: true must be set on live entities"


def test_remaining_entity_ids_present():
    """B-MD2 (MDOC-2026-05): designs is now live (B-MD2a/b); roles is now a
    read-only explainer panel (B-MD2c). Both ids must still appear in the
    sidebar entries.
    """
    src = _src()
    for eid in ("'designs'", "'roles'"):
        assert f"id: {eid}" in src, f"Missing entity id: {eid}"
    # Roles remains live: false (it has no list/count; it's a read-only explainer).
    idx = src.index("id: 'roles'")
    snippet = src[idx:idx + 120]
    assert "live: false" in snippet, (
        "Roles entity remains live: false (read-only explainer panel only)"
    )


def test_suppliers_entity_is_live():
    """Suppliers is now live (B4): id present with live: true and a count field."""
    src = _src()
    idx = src.index("id: 'suppliers'")
    snippet = src[idx:idx + 220]
    assert "live: true" in snippet
    assert "suppliers.items" in snippet or "suppliers.error" in snippet


def test_b5_entities_are_live():
    """B5 entities — hs_codes, units, product_local — must be live: true with
    a real count source."""
    src = _src()
    for eid, state_var in (("'hs_codes'", "hsCodes"),
                            ("'units'", "units"),
                            ("'product_local'", "pl")):
        idx = src.index("id: " + eid)
        snippet = src[idx:idx + 260]
        assert "live: true" in snippet, f"{eid} must be live: true (B5)"
        assert (state_var + ".items") in snippet or (state_var + ".error") in snippet, \
            f"{eid} sidebar entry must derive from state ({state_var})"


def test_b5_panel_testids_present():
    src = _src()
    for tid in ('master-hs-codes-panel', 'master-units-panel',
                'master-product-local-panel',
                'master-hs-btn-new', 'master-units-btn-new', 'master-pl-btn-new',
                'master-hs-btn-save', 'master-units-btn-save', 'master-pl-btn-save'):
        assert f'data-testid="{tid}"' in src, f"B5 missing testid: {tid}"


def test_b7_entities_are_live():
    src = _src()
    for eid, state_var in (("'incoterms'", "incoterms"),
                            ("'vat_config'", "vatCfg")):
        idx = src.index("id: " + eid)
        snippet = src[idx:idx + 260]
        assert "live: true" in snippet, f"{eid} must be live: true (B7)"
        assert (state_var + ".items") in snippet or (state_var + ".error") in snippet, \
            f"{eid} sidebar entry must derive from state ({state_var})"


def test_b7_panel_testids_present():
    src = _src()
    for tid in ('master-incoterms-panel', 'master-vat-config-panel',
                'master-incoterms-btn-new', 'master-vat-btn-new',
                'master-incoterms-btn-save', 'master-vat-btn-save'):
        assert f'data-testid="{tid}"' in src, f"B7 missing testid: {tid}"


def test_b7_vat_read_only_disclaimer_present():
    """VAT Config panel must explicitly state it does NOT override wFirma
    invoice VAT codes. Guards against future drift toward write integration."""
    src = _src()
    block = _master_block(src)
    assert "wFirma invoice VAT codes are not overridden" in block or \
           "does NOT override wFirma" in block, \
        "VAT Config panel must carry a read-only disclaimer"


def test_b8_fx_is_live_and_reference_only():
    """B8: FX rates entity is live: true but the panel must carry the
    reference-only disclaimer."""
    src = _src()
    idx = src.index("id: 'fx_rates'")
    snippet = src[idx:idx + 260]
    assert "live: true" in snippet, "fx_rates must be live: true (B8)"
    assert "fxRates.items" in snippet or "fxRates.error" in snippet
    # Disclaimer in the panel body
    block = _master_block(src)
    assert ("NEVER read by the calculation engine" in block or
            "PZ engine uses NBP live, NOT this table" in block), \
        "FX panel must carry the reference-only disclaimer"


def test_b8_fx_panel_testids_present():
    src = _src()
    for tid in ('master-fx-rates-panel', 'master-fx-btn-new',
                'master-fx-btn-save', 'master-fx-btn-cancel'):
        assert f'data-testid="{tid}"' in src, f"B8 missing testid: {tid}"


def test_b9_carriers_config_is_live():
    """B9: carriers_config entity is live: true."""
    src = _src()
    idx = src.index("id: 'carriers_config'")
    snippet = src[idx:idx + 260]
    assert "live: true" in snippet, "carriers_config must be live: true (B9)"
    assert "carriersCfg.items" in snippet or "carriersCfg.error" in snippet


def test_b9_carriers_config_panel_testids_present():
    src = _src()
    for tid in ('master-carriers-config-panel', 'master-carcfg-btn-new',
                'master-carcfg-btn-save', 'master-carcfg-btn-cancel',
                'master-carcfg-input-code'):
        assert f'data-testid="{tid}"' in src, f"B9 missing testid: {tid}"


def test_b9_carriers_config_credentials_disclaimer_present():
    """Carriers Config panel must explicitly state credentials stay in .env."""
    src = _src()
    block = _master_block(src)
    assert ".env" in block, "Carriers Config panel must reference .env (credentials stay there)"
    assert "credentials" in block.lower() or "non-secret" in block.lower(), \
        "Carriers Config panel must carry a non-secret disclaimer"


def test_b9_carriers_config_does_not_touch_runtime():
    """The B9 carriers_config table must NOT be wired into the carrier runtime
    subsystem. Guarded via source-grep of the routes module."""
    from app.api import routes_master_data as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("routes_carrier_actions", "routes_carrier_shadow",
                      "routes_carrier_webhook", "from .routes_carrier_",
                      "from ..api.routes_carrier_"):
        assert forbidden not in src, \
            f"routes_master_data must not import carrier runtime: {forbidden}"


# ══════════════════════════════════════════════════════════════════════════════
# Live entity panels
# ══════════════════════════════════════════════════════════════════════════════

def test_users_panel_landmarks_present():
    src = _src()
    assert 'data-testid="master-users-panel"' in src
    for tid in ('master-users-loading', 'master-users-error',
                'master-users-empty', 'master-users-row'):
        assert f'data-testid="{tid}"' in src, f"Missing users panel landmark: {tid}"


def test_clients_panel_landmarks_present():
    """Clients panel shows wFirma contractors and opens KYC modal on Edit."""
    src = _src()
    assert 'data-testid="master-clients-panel"' in src
    for tid in ('master-customers-loading', 'master-customers-error',
                'master-customers-empty', 'master-customers-row'):
        assert f'data-testid="{tid}"' in src, f"Missing clients panel landmark: {tid}"
    assert 'data-testid="master-clients-btn-kyc"' in src, \
        "KYC edit button testid must be present on clients panel"


def test_products_panel_landmarks_present():
    src = _src()
    assert 'data-testid="master-products-panel"' in src
    for tid in ('master-products-loading', 'master-products-error',
                'master-products-empty', 'master-products-row'):
        assert f'data-testid="{tid}"' in src, f"Missing products panel landmark: {tid}"


def test_customer_master_panel_present():
    src = _src()
    assert 'data-testid="master-customer-master-panel"' in src
    for tid in ('master-cm-loading', 'master-cm-error',
                'master-cm-empty', 'master-cm-row'):
        assert f'data-testid="{tid}"' in src, f"Missing CM panel landmark: {tid}"


def test_users_table_uses_real_fields():
    src = _src()
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


# ══════════════════════════════════════════════════════════════════════════════
# Pending entity panel (compatibility layer — hidden, for testid coverage)
# ══════════════════════════════════════════════════════════════════════════════

def test_pending_entity_panel_present():
    """Pending-grid container anchors must still exist for test compatibility,
    even when (B-MD2 MDOC) all previously-pending entities have been
    converted to live (designs) or read-only explainer (roles).
    """
    src = _src()
    assert 'data-testid="master-pending-panel"' in src
    assert 'data-testid="master-pending-badge"' in src
    assert 'data-testid="master-pending-grid"' in src


def test_pending_tiles_have_data_pending_flag():
    """B-MD2 (MDOC-2026-05): the pending grid is empty by design — all
    previously-pending entities have been converted to live (designs) or
    read-only explainer (roles). Either zero pending tiles OR each tile
    carries data-pending='true'.
    """
    src = _src()
    block_start = src.index('data-testid="master-pending-panel"')
    block_end   = src.index('data-testid="master-design-preview"', block_start)
    block = src[block_start:block_end]
    # If any pending tile is rendered, it must carry data-pending="true".
    if "master-pending-" in block.replace("master-pending-panel", "").replace(
        "master-pending-grid", "").replace("master-pending-badge", ""):
        assert 'data-pending="true"' in block, (
            "If pending tiles exist they must carry data-pending='true'"
        )
    # Otherwise (zero pending tiles) the test passes — that's the B-MD2 state.


# ══════════════════════════════════════════════════════════════════════════════
# Design preview footer
# ══════════════════════════════════════════════════════════════════════════════

def test_design_preview_footer_present():
    src = _src()
    assert 'data-testid="master-design-preview"' in src
    assert 'data-testid="master-preview-pending-badge"' in src


def test_footer_accurately_lists_live_and_pending():
    """B-MD3 (MDOC-2026-05): footer narrative updated. All Master Data entities
    are now either live (including Designs) or surfaced as a read-only explainer
    (Roles). The legacy "backend pending" footer phrase was removed in B-MD3 —
    if the dashboard still claimed "backend pending" for an entity that is in
    fact live, the operator would be misled.
    """
    src = _src()
    # B-MD3: footer must list the full live set including Designs.
    assert "Clients" in src and "Users" in src
    assert "Designs are live" in src, (
        "Footer must list Designs as live (B-MD2 made Designs live; B-MD3 "
        "updates the footer narrative)"
    )
    assert "FX Rates (reference)" in src
    assert "Incoterms" in src
    assert "HS Codes" in src
    assert "Suppliers" in src
    assert "VAT Config" in src
    assert "Carriers Config" in src
    # B-MD3: footer must explicitly position Roles as a read-only explainer
    # (NOT as "backend pending" any more).
    assert "Roles is a read-only explainer" in src, (
        "Footer must position Roles as a read-only explainer panel"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Page landmark + UI-3 cards + DETAIL_TABS
# ══════════════════════════════════════════════════════════════════════════════

def test_page_landmark_present():
    assert 'data-testid="master-page"' in _src()


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


# ══════════════════════════════════════════════════════════════════════════════
# ClientKycModal — component presence and structure
# ══════════════════════════════════════════════════════════════════════════════

def test_client_kyc_modal_component_present():
    src = _src()
    assert "function ClientKycModal({" in src, "ClientKycModal function must be defined"


def test_client_kyc_modal_defined_before_master_data_page():
    src = _src()
    modal_pos = src.index("function ClientKycModal(")
    mdp_pos   = src.index("function MasterDataPage(")
    assert modal_pos < mdp_pos, \
        "ClientKycModal must be defined before MasterDataPage"


def test_client_kyc_modal_landmark():
    assert 'data-testid="client-kyc-modal"' in _src()


def test_kyc_tabs_array_defined():
    src = _src()
    assert "const KYC_TABS = [" in src, "KYC_TABS array must be defined"


def test_kyc_six_tabs_defined():
    src = _src()
    for tab_id in ("'basic'", "'shipping'", "'carriers'", "'kyc'", "'kuke'", "'invoices'"):
        assert f"id: {tab_id}" in src, f"Missing KYC tab id: {tab_id}"


def test_kyc_tab_labels_correct():
    src = _src()
    for label in (
        "label: 'Company / Basic'",
        "label: 'Shipping'",
        "label: 'Carriers'",
        "label: 'KYC / Compliance'",
        "label: 'KUKE & Credit'",
        "label: 'Invoices'",
    ):
        assert label in src, f"Missing KYC tab label: {label}"


def test_kyc_no_tabs_marked_pending():
    """B2 (MasterData-2.2): all 6 KYC tabs are now wired — no `pending: true` flag
    remains on KYC_TABS entries. Save button is active across every tab."""
    src = _src()
    # No KYC_TABS entry may carry pending: true now
    assert "label: 'KYC / Compliance', pending: true" not in src, \
        "KYC / Compliance tab must no longer be backend-pending (B2 wired it)"
    assert "label: 'Invoices',          pending: true" not in src, \
        "Invoices tab must no longer be backend-pending (B2 wired it)"
    assert "label: 'Carriers',         pending: true" not in src, \
        "Carriers tab must no longer be backend-pending"
    # Each tab definition is present
    for tab_label in ("'Company / Basic'", "'Shipping'", "'Carriers'",
                      "'KYC / Compliance'", "'KUKE & Credit'", "'Invoices'"):
        assert tab_label in src, f"Missing KYC tab label: {tab_label}"


def test_kyc_tab_testid_pattern():
    assert "data-testid={'kyc-tab-' + t.id}" in _src()


def test_kyc_panel_testids_present():
    src = _src()
    for panel_id in ('kyc-panel-basic', 'kyc-panel-shipping', 'kyc-panel-carriers',
                     'kyc-panel-kyc', 'kyc-panel-kuke', 'kyc-panel-invoices'):
        assert f'data-testid="{panel_id}"' in src, f"Missing panel testid: {panel_id}"


# ══════════════════════════════════════════════════════════════════════════════
# ClientKycModal — Company / Basic tab (wired)
# ══════════════════════════════════════════════════════════════════════════════

def test_kyc_basic_tab_field_testids():
    src = _src()
    for tid in (
        'kyc-basic-bill-to-name',
        'kyc-basic-country',
        'kyc-basic-currency',
        'kyc-basic-nip',
        'kyc-basic-vat-eu',
        'kyc-basic-notes',
    ):
        assert f'data-testid="{tid}"' in src, f"Missing basic tab testid: {tid}"


def test_kyc_basic_fields_wired_to_form_state():
    src = _src()
    block = _kyc_block(src)
    # bill_to_name, country, default_currency, nip, vat_eu_number, notes
    for field in ("bill_to_name", "country", "default_currency", "nip", "vat_eu_number"):
        assert field in block, f"Basic tab field not wired: {field}"


# ══════════════════════════════════════════════════════════════════════════════
# ClientKycModal — Shipping tab (wired)
# ══════════════════════════════════════════════════════════════════════════════

def test_kyc_shipping_tab_field_testids():
    src = _src()
    for tid in (
        'kyc-shipping-use-alternate',
        'kyc-shipping-name',
        'kyc-shipping-person',
        'kyc-shipping-street',
        'kyc-shipping-city',
        'kyc-shipping-zip',
        'kyc-shipping-country',
        'kyc-shipping-phone',
        'kyc-shipping-email',
    ):
        assert f'data-testid="{tid}"' in src, f"Missing shipping tab testid: {tid}"


def test_kyc_shipping_fields_wired_to_form_state():
    src = _src()
    block = _kyc_block(src)
    for field in (
        "ship_to_use_alternate", "ship_to_name", "ship_to_person",
        "ship_to_street", "ship_to_city", "ship_to_zip",
        "ship_to_country", "ship_to_phone", "ship_to_email",
    ):
        assert field in block, f"Shipping tab field not wired: {field}"


# ══════════════════════════════════════════════════════════════════════════════
# ClientKycModal — Carriers tab (MasterData-1: now live)
# ══════════════════════════════════════════════════════════════════════════════

def test_kyc_carriers_tab_live():
    """Carriers tab is now live (MasterData-1). Panel must be present with real UI."""
    src = _src()
    block = _kyc_block(src)
    assert 'data-testid="kyc-panel-carriers"' in src
    # Carriers is now live — Save disabled message must NOT appear for carriers tab
    # (it still appears for kyc/invoices, just not in the carriers panel itself)
    assert 'data-testid="kyc-carriers-add-btn"' in src, \
        "Carriers tab must have an Add account button (live MasterData-1)"
    assert 'data-testid="kyc-carriers-list"' in src, \
        "Carriers tab must have a carrier accounts list"


def test_kyc_carriers_tab_form_testids():
    src = _src()
    for tid in (
        'kyc-carriers-add-btn',
        'kyc-carriers-list',
        'kyc-carriers-form-carrier',
        'kyc-carriers-form-account-number',
        'kyc-carriers-form-save',
    ):
        assert f'data-testid="{tid}"' in src, f"Missing carriers tab testid: {tid}"


# ══════════════════════════════════════════════════════════════════════════════
# ClientKycModal — KYC / Compliance tab (backend pending)
# ══════════════════════════════════════════════════════════════════════════════

def test_kyc_compliance_tab_live():
    """B2: KYC/Compliance tab body renders the bound form fields; Save is active.
    No invented endpoint — the existing PUT /customer-master/ writes these columns."""
    src = _src()
    block = _kyc_block(src)
    assert 'data-testid="kyc-panel-kyc"' in src
    # The "Save disabled" message must no longer appear anywhere in the KYC modal
    assert "Save disabled for this tab" not in block, \
        "KYC modal must not show 'Save disabled' — all tabs are wired in B2"
    # Compliance field testids must be present
    for tid in ('kyc-pep-check-result', 'kyc-compliance-notes'):
        assert f'data-testid="{tid}"' in src, f"Missing KYC compliance testid: {tid}"


def test_kyc_compliance_tab_no_live_write():
    src = _src()
    block = _kyc_block(src)
    # No POST or custom endpoint invented for KYC compliance
    assert "/api/v1/kyc" not in block, "No KYC-specific endpoint may be invented"
    assert "/api/v1/aml" not in block, "No AML-specific endpoint may be invented"


# ══════════════════════════════════════════════════════════════════════════════
# ClientKycModal — KUKE & Credit tab (wired)
# ══════════════════════════════════════════════════════════════════════════════

def test_kyc_kuke_tab_field_testids():
    src = _src()
    for tid in (
        'kyc-kuke-approved',
        'kyc-kuke-limit',
        'kyc-kuke-currency',
        'kyc-kuke-expiry',
        'kyc-credit-limit',
        'kyc-credit-currency',
        'kyc-risk-status',
    ):
        assert f'data-testid="{tid}"' in src, f"Missing KUKE/Credit testid: {tid}"


def test_kyc_kuke_fields_wired_to_form_state():
    src = _src()
    block = _kyc_block(src)
    for field in (
        "kuke_approved", "kuke_limit", "kuke_currency",
        "kuke_expiry_date", "credit_limit", "credit_currency", "risk_status",
    ):
        assert field in block, f"KUKE/Credit field not wired: {field}"


# ══════════════════════════════════════════════════════════════════════════════
# ClientKycModal — Invoices tab (backend pending)
# ══════════════════════════════════════════════════════════════════════════════

def test_kyc_invoices_tab_live():
    """B2: Invoices tab body renders bound form for wFirma defaults
    (proforma/invoice series, VAT mode, language, payment terms, currency).
    Save uses the existing PUT /customer-master/ — no new endpoint invented."""
    src = _src()
    assert 'data-testid="kyc-panel-invoices"' in src
    for tid in (
        'kyc-invoices-proforma-series',
        'kyc-invoices-invoice-series',
        'kyc-invoices-vat-mode',
        'kyc-invoices-language-id',
        'kyc-invoices-payment-terms',
        'kyc-invoices-currency',
    ):
        assert f'data-testid="{tid}"' in src, f"Missing invoices tab testid: {tid}"


def test_kyc_invoices_fields_wired_to_form_state():
    src = _src()
    block = _kyc_block(src)
    for field in (
        "preferred_proforma_series_id", "preferred_invoice_series_id",
        "vat_mode", "default_language_id",
        "payment_terms_days", "default_currency",
    ):
        assert field in block, f"Invoices tab field not wired: {field}"


def test_cm_open_profile_button_present():
    """B2: CM-tab row offers an 'Open full profile' button that opens ClientKycModal."""
    src = _src()
    assert 'data-testid="master-cm-btn-open-profile"' in src, \
        "Open-profile button must be present on CM-tab row"
    block = _master_block(src)
    assert "Open full profile" in block, \
        "Open-profile button label must be present in MasterDataPage"
    assert "setKycModal" in block, "Open-profile button must trigger setKycModal"


def test_kyc_invoices_tab_no_invented_endpoint():
    src = _src()
    block = _kyc_block(src)
    assert "/api/v1/invoices" not in block, \
        "No invoices endpoint may be invented in KYC modal"


# ══════════════════════════════════════════════════════════════════════════════
# ClientKycModal — Save wiring
# ══════════════════════════════════════════════════════════════════════════════

def test_kyc_save_button_testid():
    assert 'data-testid="kyc-btn-save"' in _src()


def test_kyc_save_calls_customer_master_put():
    src = _src()
    block = _kyc_block(src)
    assert "apiFetch('/api/v1/customer-master/' + contractorId" in block, \
        "KYC save must PUT to /api/v1/customer-master/{contractorId}"
    assert "method: 'PUT'" in block, "KYC save must use PUT method"


def test_kyc_no_patch_and_sub_resource_only_writes():
    """PATCH is never allowed. POST/DELETE are only allowed for sub-resource routes
    (shipping-addresses and carrier-accounts). No direct customer-master POST/DELETE."""
    src = _src()
    block = _kyc_block(src)
    assert "method: 'PATCH'" not in block, \
        "ClientKycModal must not contain method: 'PATCH'"
    # Sub-resource POST/DELETE are allowed (shipping-addresses, carrier-accounts)
    # but customer-master itself must never be POST/DELETE'd
    assert "method: 'POST', body: JSON.stringify(payload)" not in block, \
        "customer-master must not be POST'd directly in ClientKycModal"
    assert "shipping-addresses" in block or "carrier-accounts" in block, \
        "ClientKycModal sub-resource routes must be present"


def test_kyc_save_error_testid():
    assert 'data-testid="kyc-save-error"' in _src()


# ══════════════════════════════════════════════════════════════════════════════
# Customer Master panel
# ══════════════════════════════════════════════════════════════════════════════

def test_customer_master_panel_testid():
    assert 'data-testid="master-customer-master-panel"' in _src()


def test_customer_master_panel_shows_freight_and_insurance():
    src = _src()
    # The CM panel subtitle mentions freight / insurance / credit
    assert "Freight / insurance / credit config per contractor" in src


def test_customer_master_legacy_edit_testids_preserved():
    """Legacy inline-edit testids from PR #94 must remain for test compatibility."""
    src = _src()
    for tid in (
        'master-cm-btn-save', 'master-cm-btn-cancel',
        'master-cm-save-error', 'master-cm-edit-form',
        'cm-edit-freight-service-id', 'cm-edit-freight-eur', 'cm-edit-freight-usd',
        'cm-edit-freight-label-pl', 'cm-edit-freight-label-en',
        'cm-edit-insurance-service-id', 'cm-edit-insurance-rate',
        'cm-edit-insurance-min-eur', 'cm-edit-insurance-min-usd',
        'cm-edit-insurance-label-pl', 'cm-edit-insurance-label-en',
        'cm-edit-insurance-enabled',
    ):
        assert f'data-testid="{tid}"' in src, f"Legacy CM testid must be preserved: {tid}"


# ══════════════════════════════════════════════════════════════════════════════
# FX Rates panel (pending, design preview)
# ══════════════════════════════════════════════════════════════════════════════

def test_fx_rates_entity_in_sidebar():
    assert "id: 'fx_rates'" in _src()


def test_fx_rates_entity_is_live_b8():
    """B8 promoted fx_rates from pending to live (reference-only mode)."""
    src = _src()
    idx = src.index("id: 'fx_rates'")
    snippet = src[idx:idx + 220]
    assert "live: true" in snippet, "fx_rates is live (B8 reference-only)"


def test_fx_rates_no_longer_in_pending_grid():
    """B8: fx_rates moved out of the pending grid."""
    src = _src()
    block_start = src.index('data-testid="master-pending-panel"')
    block_end   = src.index('data-testid="master-design-preview"', block_start)
    block = src[block_start:block_end]
    assert "'fx_rates'" not in block, "fx_rates should NOT appear in pending grid (B8)"


# ══════════════════════════════════════════════════════════════════════════════
# Designs panel (pending, design preview)
# ══════════════════════════════════════════════════════════════════════════════

def test_designs_entity_in_sidebar():
    assert "id: 'designs'" in _src()


def test_designs_entity_is_live():
    """B-MD2 (MDOC-2026-05): Designs moved from pending to live.
    Marker: `live: true` near the `id: 'designs'` entry.
    """
    src = _src()
    idx = src.index("id: 'designs'")
    snippet = src[idx:idx + 220]
    assert "live: true" in snippet, (
        "Designs entity must have live: true after B-MD2"
    )


def test_designs_panel_exists():
    """B-MD2: master-designs-panel testid renders when activeEntity === 'designs'."""
    src = _src()
    assert 'data-testid="master-designs-panel"' in src
    assert "activeEntity === 'designs'" in src
    assert 'data-testid="master-designs-btn-new"' in src
    assert 'data-testid="master-designs-btn-save"' in src
    assert 'data-testid="master-designs-btn-cancel"' in src


def test_designs_uses_b5_helpers():
    """B-MD2: Designs writes flow through b5Save / b5Delete (no inline POST/PUT)."""
    src = _src()
    assert "b5Save('/api/v1/designs', 'design_code'" in src, (
        "Designs Save must use b5Save helper with basePath /api/v1/designs"
    )
    assert "b5Delete('/api/v1/designs'," in src, (
        "Designs Delete must use b5Delete helper with basePath /api/v1/designs"
    )


# ══════════════════════════════════════════════════════════════════════════════
# B10 (MDC-090) — wFirma sync visibility on Clients table
# ══════════════════════════════════════════════════════════════════════════════

def test_clients_table_has_sync_column():
    """Clients table renders a Sync column derived from match_status returned
    by GET /api/v1/wfirma/customers. Read-only; no new endpoint."""
    src = _src()
    block = _master_block(src)
    assert "'Sync'" in block, "Sync column header missing from Clients table"
    assert 'data-testid="master-customers-sync"' in src, \
        "master-customers-sync testid must be present"
    # Derivation must reference match_status from the wFirma capabilities payload
    assert "match_status" in block, \
        "Clients sync column must derive from match_status field"
    # No new endpoint may be invented
    for ep in ("/api/v1/sync/customers", "/api/v1/wfirma/sync", "/api/v1/master/sync"):
        assert ep not in src, f"Invented sync endpoint leaked: {ep}"


def test_clients_sync_chip_states_present():
    """The Sync chip must visibly represent matched, pending, not_found, error."""
    src = _src()
    block = _master_block(src)
    for label in ("synced", "pending", "not found", "error"):
        assert label in block.lower(), f"Sync chip must mention state {label!r}"
