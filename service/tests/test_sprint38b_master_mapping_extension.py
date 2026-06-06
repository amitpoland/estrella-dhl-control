"""Sprint 38b — Master Data Mapping Extension regression tests.

Source-grep tests verifying that:
1. Mapping/status columns are added for 7 focus entities
2. Missing backend reasons are visible (not faked)
3. No wFirma authority replaces local master authority
4. No write routes are called from mapping columns
5. No fake usage counts
6. wFirma sync buttons exist with correct disabled/pending states
7. MappingInfoBanner renders per-entity status
8. Column definitions include new mapping fields

Sprint: 38b — Master Data Mapping Extension
Target:  master-page.jsx (MasterPage + MappingInfoBanner), pz-api.js (no new transport)
"""

import pathlib
import re

import pytest

# ── File paths ──────────────────────────────────────────────────────────

V2_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "v2"
MASTER_PAGE = V2_DIR / "master-page.jsx"
PZ_API = V2_DIR / "pz-api.js"


# ── Helper ──────────────────────────────────────────────────────────────

def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════
# 1. Mapping columns exist in ENTITY_COLUMNS
# ═══════════════════════════════════════════════════════════════════════

class TestMappingColumnsExist:
    """Verify Sprint 38b added mapping/status columns to focus entities."""

    def test_clients_wfirma_id_column(self):
        src = _read(MASTER_PAGE)
        assert "bill_to_contractor_id" in src
        assert "'wFirma ID'" in src or '"wFirma ID"' in src

    def test_clients_last_sync_column(self):
        src = _read(MASTER_PAGE)
        # clients section should have last_wfirma_sync_at
        assert re.search(r"clients:.*?last_wfirma_sync_at", src, re.DOTALL)

    def test_suppliers_wfirma_id_column(self):
        src = _read(MASTER_PAGE)
        # suppliers section should have wfirma_id
        assert re.search(r"suppliers:.*?wfirma_id", src, re.DOTALL)

    def test_suppliers_last_sync_column(self):
        src = _read(MASTER_PAGE)
        assert re.search(r"suppliers:.*?last_wfirma_sync_at", src, re.DOTALL)

    def test_carriers_api_type_column(self):
        src = _read(MASTER_PAGE)
        assert re.search(r"carriers:.*?api_type", src, re.DOTALL)

    def test_incoterms_insurance_column(self):
        src = _read(MASTER_PAGE)
        assert re.search(r"incoterms:.*?insurance_included", src, re.DOTALL)

    def test_incoterms_customs_column(self):
        src = _read(MASTER_PAGE)
        assert re.search(r"incoterms:.*?customs_included", src, re.DOTALL)


# ═══════════════════════════════════════════════════════════════════════
# 2. Mapping column type markers
# ═══════════════════════════════════════════════════════════════════════

class TestMappingColumnTypes:
    """Verify mapping and timestamp column type markers exist."""

    def test_mapping_true_marker(self):
        src = _read(MASTER_PAGE)
        assert "mapping: true" in src, "No mapping: true column marker found"

    def test_timestamp_true_marker(self):
        src = _read(MASTER_PAGE)
        assert "timestamp: true" in src, "No timestamp: true column marker found"

    def test_render_cell_function(self):
        src = _read(MASTER_PAGE)
        assert "_renderCell" in src, "_renderCell function not found"

    def test_not_mapped_badge(self):
        src = _read(MASTER_PAGE)
        assert "not mapped" in src, "'not mapped' badge text not found"


# ═══════════════════════════════════════════════════════════════════════
# 3. MAPPING_INFO constant exists with per-entity metadata
# ═══════════════════════════════════════════════════════════════════════

class TestMappingInfo:
    """Verify MAPPING_INFO declares available/pending status per entity."""

    def test_mapping_info_constant_exists(self):
        src = _read(MASTER_PAGE)
        assert "MAPPING_INFO" in src

    def test_mapping_info_has_clients(self):
        src = _read(MASTER_PAGE)
        assert re.search(r"MAPPING_INFO\s*=\s*\{[\s\S]*?clients:", src)

    def test_mapping_info_has_suppliers(self):
        src = _read(MASTER_PAGE)
        assert re.search(r"MAPPING_INFO\s*=\s*\{[\s\S]*?suppliers:", src)

    def test_mapping_info_has_products(self):
        src = _read(MASTER_PAGE)
        assert re.search(r"MAPPING_INFO\s*=\s*\{[\s\S]*?products:", src)

    def test_mapping_info_has_vat(self):
        src = _read(MASTER_PAGE)
        assert re.search(r"MAPPING_INFO\s*=\s*\{[\s\S]*?vat:", src)

    def test_mapping_info_has_carriers(self):
        src = _read(MASTER_PAGE)
        assert re.search(r"MAPPING_INFO\s*=\s*\{[\s\S]*?carriers:", src)

    def test_mapping_info_has_incoterms(self):
        src = _read(MASTER_PAGE)
        assert re.search(r"MAPPING_INFO\s*=\s*\{[\s\S]*?incoterms:", src)

    def test_mapping_info_has_units(self):
        src = _read(MASTER_PAGE)
        assert re.search(r"MAPPING_INFO\s*=\s*\{[\s\S]*?units:", src)


# ═══════════════════════════════════════════════════════════════════════
# 4. MappingInfoBanner component exists
# ═══════════════════════════════════════════════════════════════════════

class TestMappingInfoBanner:
    """Verify MappingInfoBanner renders per-entity mapping status."""

    def test_component_defined(self):
        src = _read(MASTER_PAGE)
        assert "function MappingInfoBanner" in src

    def test_testid_pattern(self):
        src = _read(MASTER_PAGE)
        assert "mapping-info-" in src, "data-testid pattern for mapping-info-{entity} not found"

    def test_pending_testid_pattern(self):
        src = _read(MASTER_PAGE)
        assert "mapping-pending-" in src, "data-testid pattern for mapping-pending not found"

    def test_rendered_in_page(self):
        src = _read(MASTER_PAGE)
        assert "<MappingInfoBanner" in src, "MappingInfoBanner not rendered in MasterPage"

    def test_exported(self):
        src = _read(MASTER_PAGE)
        assert "MappingInfoBanner" in src
        # Check window export
        assert re.search(r"Object\.assign\(window.*?MappingInfoBanner", src)


# ═══════════════════════════════════════════════════════════════════════
# 5. wFirma sync buttons exist with correct states
# ═══════════════════════════════════════════════════════════════════════

class TestWfirmaSyncButtons:
    """Verify sync buttons for clients, suppliers (endpoint exists), and VAT (pending)."""

    def test_clients_suppliers_sync_button_testid(self):
        """Sync button for clients/suppliers uses template: 'btn-wfirma-sync-' + entity."""
        src = _read(MASTER_PAGE)
        assert "btn-wfirma-sync-" in src

    def test_vat_sync_button_testid(self):
        src = _read(MASTER_PAGE)
        assert "btn-wfirma-sync-vat" in src

    def test_vat_sync_disabled_reason(self):
        src = _read(MASTER_PAGE)
        assert "wFirma VAT sync endpoint missing" in src

    def test_sync_section_testids(self):
        """Sync sections for clients/suppliers use template, VAT is literal."""
        src = _read(MASTER_PAGE)
        assert "wfirma-sync-section-" in src
        assert "wfirma-sync-section-vat" in src

    def test_clients_suppliers_sync_conditional(self):
        """Sync section renders for clients OR suppliers."""
        src = _read(MASTER_PAGE)
        assert re.search(r"entity\s*===\s*'clients'.*?entity\s*===\s*'suppliers'", src, re.DOTALL)


# ═══════════════════════════════════════════════════════════════════════
# 6. No fake usage counts
# ═══════════════════════════════════════════════════════════════════════

class TestNoFakeUsageCounts:
    """Verify no hardcoded usage counts or fake statistics."""

    def test_no_usage_count_literal(self):
        src = _read(MASTER_PAGE)
        # Should NOT contain patterns like "used in 5 packing lists"
        assert not re.search(r"used in \d+ ", src, re.IGNORECASE), \
            "Found hardcoded usage count — Sprint 38b must not fake usage data"

    def test_no_fake_shipment_count(self):
        src = _read(MASTER_PAGE)
        assert not re.search(r"\d+ shipment", src, re.IGNORECASE), \
            "Found hardcoded shipment count"

    def test_no_fake_proforma_count(self):
        src = _read(MASTER_PAGE)
        assert not re.search(r"\d+ proforma", src, re.IGNORECASE), \
            "Found hardcoded proforma count"


# ═══════════════════════════════════════════════════════════════════════
# 7. Authority separation preserved
# ═══════════════════════════════════════════════════════════════════════

class TestAuthoritySeparation:
    """Verify Sprint 38b does NOT replace local master with wFirma authority."""

    def test_clients_still_use_customer_master_api(self):
        """Client Master tab must still use PzApi.listCustomerMaster, not getWfirmaCustomers."""
        src = _read(MASTER_PAGE)
        assert "PzApi.listCustomerMaster()" in src
        # Must NOT use getWfirmaCustomers in the _entityApi for clients
        clients_section = re.search(r"case 'clients':.*?;", src)
        assert clients_section, "clients case not found in _entityApi"
        assert "getWfirmaCustomers" not in clients_section.group()

    def test_products_still_use_product_local_api(self):
        """Product tab must still use PzApi.listProductLocal, not getWfirmaProducts."""
        src = _read(MASTER_PAGE)
        assert "PzApi.listProductLocal()" in src
        products_section = re.search(r"case 'products':.*?;", src)
        assert products_section, "products case not found in _entityApi"
        assert "getWfirmaProducts" not in products_section.group()

    def test_suppliers_still_use_suppliers_api(self):
        src = _read(MASTER_PAGE)
        assert "PzApi.listSuppliers()" in src

    def test_no_wfirma_customers_import(self):
        """master-page.jsx must not call getWfirmaCustomers anywhere."""
        src = _read(MASTER_PAGE)
        assert "getWfirmaCustomers" not in src, \
            "master-page.jsx must not call getWfirmaCustomers — Client Master uses /customer-master/"

    def test_no_wfirma_products_import(self):
        """master-page.jsx must not call getWfirmaProducts anywhere."""
        src = _read(MASTER_PAGE)
        assert "getWfirmaProducts" not in src, \
            "master-page.jsx must not call getWfirmaProducts — Product Local uses /product-local/"


# ═══════════════════════════════════════════════════════════════════════
# 8. No write routes called
# ═══════════════════════════════════════════════════════════════════════

class TestNoWriteRoutes:
    """Sprint 38b is read-only. No new write/mutation calls."""

    def test_no_post_calls(self):
        """master-page.jsx must not contain any PzApi POST/PUT/DELETE calls."""
        src = _read(MASTER_PAGE)
        # Exclude comments
        lines = [l for l in src.splitlines() if not l.strip().startswith("//")]
        code = "\n".join(lines)
        for method in ["updateCustomerMaster", "applyCustomerMasterSync",
                       "upsertHsCode", "upsertUnit", "upsertProductLocal",
                       "upsertIncoterm", "upsertCarrierConfig", "createVatConfig",
                       "updateVatConfig"]:
            assert method not in code, \
                f"master-page.jsx calls write method {method} — Sprint 38b is read-only"


# ═══════════════════════════════════════════════════════════════════════
# 9. Backend pending reasons are visible (not silently hidden)
# ═══════════════════════════════════════════════════════════════════════

class TestBackendPendingReasons:
    """Verify missing backend status is explicitly declared, not hidden."""

    def test_pending_keyword_in_mapping_info(self):
        src = _read(MASTER_PAGE)
        # MAPPING_INFO must contain 'pending' items for entities with missing endpoints
        assert re.search(r"pending:.*?\[", src, re.DOTALL)

    def test_backend_pending_text_visible(self):
        src = _read(MASTER_PAGE)
        assert "Backend pending" in src, "No 'Backend pending' text found in mapping info"

    def test_no_endpoint_text_visible(self):
        src = _read(MASTER_PAGE)
        assert "no endpoint" in src.lower(), "No 'no endpoint' text found in mapping info"


# ═══════════════════════════════════════════════════════════════════════
# 10. Sprint 38 base functionality preserved
# ═══════════════════════════════════════════════════════════════════════

class TestSprint38BasePreserved:
    """Verify Sprint 38 functionality still intact after 38b additions."""

    def test_entity_types_count(self):
        src = _read(MASTER_PAGE)
        entity_ids = re.findall(r"id:\s*'(\w+)'", src.split("ENTITY_TYPES")[1].split("];")[0])
        assert len(entity_ids) == 12, f"Expected 12 entity types, got {len(entity_ids)}"

    def test_write_disabled_reason_constant(self):
        src = _read(MASTER_PAGE)
        assert "WRITE_DISABLED_REASON" in src

    def test_static_roles_preserved(self):
        src = _read(MASTER_PAGE)
        assert "STATIC_ROLES" in src

    def test_role_matrix_preserved(self):
        src = _read(MASTER_PAGE)
        assert "ROLE_MATRIX" in src

    def test_entity_api_function_preserved(self):
        src = _read(MASTER_PAGE)
        assert "_entityApi" in src

    def test_no_seed_data(self):
        """No SEED constants — all data from backend (Sprint 38 invariant)."""
        src = _read(MASTER_PAGE)
        assert "SEED_" not in src, "SEED_ data found — violates Sprint 38 live authority"

    def test_mapping_info_exported(self):
        src = _read(MASTER_PAGE)
        assert re.search(r"Object\.assign\(window.*?MAPPING_INFO", src)


# ═══════════════════════════════════════════════════════════════════════
# 11. pz-api.js has no new write transport functions
# ═══════════════════════════════════════════════════════════════════════

class TestNoNewTransport:
    """Sprint 38b should NOT add new transport functions — mapping uses existing data."""

    def test_no_mapping_usage_endpoint(self):
        """No new usage-count or mapping-status transport function should exist."""
        src = _read(PZ_API)
        for name in ["listClientUsage", "listSupplierUsage", "listProductUsage",
                      "listIncotermUsage", "listUnitUsage", "listCarrierUsage"]:
            assert name not in src, f"pz-api.js added {name} — Sprint 38b uses existing fields only"
