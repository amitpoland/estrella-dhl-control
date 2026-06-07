"""
test_client_detail_ui.py — Source-grep tests for Client Detail UI.

Step 3 of Customer Master Address Authority migration.

Authority: Customer Master is PRIMARY for client identity, email, address.
  bill_to_* = invoice / billing authority
  ship_to_* = DHL delivery / shipping authority
  Shape B (ship_to_contractor_id) = wFirma receiver, NOT DHL delivery

Scope:
  - Verifies client-detail.jsx exists and exports ClientDetailModal
  - Verifies correct API usage (getCustomerMaster, saveCustomerMaster)
  - Verifies 5 tabs exist
  - Verifies ship_to_use_alternate toggle
  - Verifies read-only bill_to_contractor_id
  - Verifies no DHL/proforma logic leaks
  - Verifies Edit button in master-page.jsx
  - Verifies script tag in index.html
  - Verifies data-testid coverage

Sprint: Customer Master Client Detail UI (Step 3)
Target: client-detail.jsx, master-page.jsx, index.html
"""
from __future__ import annotations

import pathlib

import pytest

SERVICE_DIR = pathlib.Path(__file__).resolve().parent.parent
APP_DIR = SERVICE_DIR / "app"
V2_DIR = APP_DIR / "static" / "v2"
CLIENT_DETAIL = V2_DIR / "client-detail.jsx"
MASTER_PAGE = V2_DIR / "master-page.jsx"
INDEX_HTML = V2_DIR / "index.html"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# =============================================================================
# 1. File exists and exports ClientDetailModal
# =============================================================================

class TestClientDetailFileExists:
    """client-detail.jsx must exist and export ClientDetailModal."""

    def test_file_exists(self):
        assert CLIENT_DETAIL.exists(), "client-detail.jsx must exist"

    def test_exports_client_detail_modal(self):
        src = _read(CLIENT_DETAIL)
        assert "ClientDetailModal" in src
        assert "Object.assign(window" in src
        assert "ClientDetailModal" in src.split("Object.assign(window")[1]

    def test_is_a_function_component(self):
        src = _read(CLIENT_DETAIL)
        assert "function ClientDetailModal(" in src


# =============================================================================
# 2. Uses correct API functions (transport layer)
# =============================================================================

class TestCorrectApiUsage:
    """Must use PzApi.getCustomerMaster and PzApi.saveCustomerMaster."""

    def test_uses_get_customer_master(self):
        src = _read(CLIENT_DETAIL)
        assert "PzApi.getCustomerMaster" in src, \
            "Must load record via PzApi.getCustomerMaster"

    def test_uses_save_customer_master(self):
        src = _read(CLIENT_DETAIL)
        assert "PzApi.saveCustomerMaster" in src, \
            "Must save via PzApi.saveCustomerMaster (partial PUT)"

    def test_does_not_call_list_customer_master(self):
        """Modal loads ONE record, must not list all."""
        src = _read(CLIENT_DETAIL)
        assert "PzApi.listCustomerMaster" not in src

    def test_does_not_define_own_fetch(self):
        """Must not bypass PzApi transport layer."""
        src = _read(CLIENT_DETAIL)
        # Filter comments
        code_lines = [ln for ln in src.splitlines()
                      if not ln.strip().startswith("//")
                      and not ln.strip().startswith("*")]
        code = "\n".join(code_lines)
        assert "fetch(" not in code, \
            "Must use PzApi, not raw fetch"


# =============================================================================
# 3. Five tabs exist
# =============================================================================

class TestFiveTabsExist:
    """Modal must have 5 tabs matching the spec."""

    def test_identity_tab(self):
        src = _read(CLIENT_DETAIL)
        assert "'identity'" in src or '"identity"' in src

    def test_billing_tab(self):
        src = _read(CLIENT_DETAIL)
        assert "'billing'" in src or '"billing"' in src

    def test_shipping_tab(self):
        src = _read(CLIENT_DETAIL)
        assert "'shipping'" in src or '"shipping"' in src

    def test_commercial_tab(self):
        src = _read(CLIENT_DETAIL)
        assert "'commercial'" in src or '"commercial"' in src

    def test_sync_tab(self):
        src = _read(CLIENT_DETAIL)
        assert "'sync'" in src or '"sync"' in src

    def test_tab_labels_present(self):
        src = _read(CLIENT_DETAIL)
        for label in ['Identity', 'Billing Address', 'Shipping Address',
                       'Commercial Defaults', 'Sync & Authority']:
            assert label in src, f"Tab label '{label}' must exist"


# =============================================================================
# 4. ship_to_use_alternate toggle
# =============================================================================

class TestShipToToggle:
    """Toggle controls ship-to field visibility."""

    def test_toggle_field_exists(self):
        src = _read(CLIENT_DETAIL)
        assert "ship_to_use_alternate" in src

    def test_toggle_is_checkbox(self):
        src = _read(CLIENT_DETAIL)
        assert 'cd-ship_to_use_alternate' in src

    def test_shipto_fields_section(self):
        """Ship-to fields must be conditionally rendered."""
        src = _read(CLIENT_DETAIL)
        assert "cd-shipto-fields" in src

    def test_toggle_label_text(self):
        """Toggle must explain what it does."""
        src = _read(CLIENT_DETAIL)
        assert "Different delivery address" in src or "delivery address" in src.lower()


# =============================================================================
# 5. bill_to_contractor_id is read-only
# =============================================================================

class TestBillToContractorReadOnly:
    """bill_to_contractor_id must be read-only (system-managed)."""

    def test_contractor_id_is_readonly(self):
        src = _read(CLIENT_DETAIL)
        # The sync tab renders it as read-only metadata
        assert "bill_to_contractor_id" in src
        # Must appear in the read-only sync tab section
        idx = src.find("tab === 'sync'")
        assert idx > 0
        sync_section = src[idx:idx + 2000]
        assert "bill_to_contractor_id" in sync_section, \
            "bill_to_contractor_id must be in Sync & Authority tab (read-only)"


# =============================================================================
# 6. ship_to_contractor_id labeled correctly
# =============================================================================

class TestShipToContractorLabel:
    """ship_to_contractor_id must be labeled as wFirma Receiver."""

    def test_wfirma_receiver_label(self):
        src = _read(CLIENT_DETAIL)
        assert "wFirma Receiver" in src

    def test_not_affect_dhl_note(self):
        """Must state that it does NOT affect DHL delivery."""
        src = _read(CLIENT_DETAIL)
        assert "NOT affect DHL" in src or "not affect DHL" in src.lower() or \
               "Does NOT affect DHL" in src


# =============================================================================
# 7. No DHL / proforma / email-send logic
# =============================================================================

class TestNoDomainLeaks:
    """Client Detail UI must not contain DHL, proforma, or email-send logic."""

    def test_no_dhl_api(self):
        src = _read(CLIENT_DETAIL)
        code_lines = [ln for ln in src.splitlines()
                      if not ln.strip().startswith("//")
                      and not ln.strip().startswith("*")]
        code = "\n".join(code_lines)
        assert "PzApi.dhl" not in code.lower()
        assert "routes_dhl" not in code

    def test_no_proforma_logic(self):
        src = _read(CLIENT_DETAIL)
        code_lines = [ln for ln in src.splitlines()
                      if not ln.strip().startswith("//")
                      and not ln.strip().startswith("*")]
        code = "\n".join(code_lines)
        # preferred_proforma_series_id is a legitimate Customer Master field,
        # not proforma logic. Check for actual proforma API calls instead.
        assert "PzApi.proforma" not in code.lower()
        assert "routes_proforma" not in code
        assert "proforma_draft" not in code.lower()

    def test_no_email_send(self):
        src = _read(CLIENT_DETAIL)
        code_lines = [ln for ln in src.splitlines()
                      if not ln.strip().startswith("//")
                      and not ln.strip().startswith("*")]
        code = "\n".join(code_lines)
        assert "queue_email" not in code
        assert "send_email" not in code
        assert "email_service" not in code


# =============================================================================
# 8. Edit button in master-page.jsx (clients entity only)
# =============================================================================

class TestEditButtonInMasterPage:
    """master-page.jsx must have an Edit button for clients entity."""

    def test_edit_button_exists(self):
        src = _read(MASTER_PAGE)
        assert "btn-edit-record" in src

    def test_edit_button_clients_only(self):
        """Edit button must be conditional on entity === 'clients'."""
        src = _read(MASTER_PAGE)
        # Find the edit button region
        idx = src.find("btn-edit-record")
        assert idx > 0
        region = src[max(0, idx - 300):idx + 100]
        assert "entity === 'clients'" in region, \
            "Edit button must only appear for clients entity"

    def test_edit_record_state(self):
        """master-page.jsx must have editRecord state."""
        src = _read(MASTER_PAGE)
        assert "editRecord" in src
        assert "setEditRecord" in src

    def test_client_detail_modal_rendered(self):
        """master-page.jsx must render ClientDetailModal."""
        src = _read(MASTER_PAGE)
        assert "ClientDetailModal" in src


# =============================================================================
# 9. Script tag in index.html
# =============================================================================

class TestScriptTagInIndex:
    """client-detail.jsx must be loaded before master-page.jsx."""

    def test_script_tag_exists(self):
        src = _read(INDEX_HTML)
        assert 'client-detail.jsx' in src

    def test_loaded_before_master_page(self):
        """client-detail.jsx must appear before master-page.jsx."""
        src = _read(INDEX_HTML)
        cd_pos = src.find('client-detail.jsx')
        mp_pos = src.find('master-page.jsx')
        assert cd_pos > 0
        assert mp_pos > 0
        assert cd_pos < mp_pos, \
            "client-detail.jsx must be loaded before master-page.jsx"


# =============================================================================
# 10. data-testid coverage
# =============================================================================

class TestDataTestIds:
    """Critical interactive elements must have data-testid."""

    def test_modal_container(self):
        src = _read(CLIENT_DETAIL)
        assert "client-detail-modal" in src

    def test_save_button(self):
        src = _read(CLIENT_DETAIL)
        assert "cd-save" in src

    def test_cancel_button(self):
        src = _read(CLIENT_DETAIL)
        assert "cd-cancel" in src

    def test_close_button(self):
        src = _read(CLIENT_DETAIL)
        assert "cd-close" in src

    def test_tab_buttons(self):
        src = _read(CLIENT_DETAIL)
        # Tab testids are built dynamically: 'cd-tab-' + t.id
        # Verify the pattern exists and all tab IDs are defined
        assert "'cd-tab-'" in src or '"cd-tab-"' in src, \
            "Tab buttons must use cd-tab- prefix for data-testid"
        for tab_id in ['identity', 'billing', 'shipping', 'commercial', 'sync']:
            assert f"'{tab_id}'" in src or f'"{tab_id}"' in src, \
                f"Tab ID {tab_id} must be defined"

    def test_confirm_dialog(self):
        src = _read(CLIENT_DETAIL)
        assert "cd-confirm-dialog" in src

    def test_loading_state(self):
        src = _read(CLIENT_DETAIL)
        assert "cd-loading" in src

    def test_error_state(self):
        src = _read(CLIENT_DETAIL)
        assert "cd-error" in src


# =============================================================================
# 11. Save button says "Save Changes"
# =============================================================================

class TestSaveButtonLabel:
    """Save button must say 'Save Changes', not just 'Save'."""

    def test_save_changes_label(self):
        src = _read(CLIENT_DETAIL)
        assert "Save Changes" in src

    def test_no_auto_save(self):
        """Must NOT auto-save on field change."""
        src = _read(CLIENT_DETAIL)
        # onChange handlers should only call set() or toggleBool(), not save
        code_lines = [ln for ln in src.splitlines()
                      if "onChange" in ln]
        for line in code_lines:
            assert "saveCustomerMaster" not in line, \
                "onChange must not trigger save — explicit Save button required"


# =============================================================================
# 12. Confirm dialog before save
# =============================================================================

class TestConfirmDialog:
    """Must show a confirm dialog before saving."""

    def test_confirm_before_save(self):
        src = _read(CLIENT_DETAIL)
        assert "showConfirm" in src
        assert "setShowConfirm" in src

    def test_confirm_shows_changed_fields(self):
        """Confirm dialog must display the changed fields."""
        src = _read(CLIENT_DETAIL)
        assert "computeChanges" in src or "changedFields" in src

    def test_confirm_has_cancel(self):
        src = _read(CLIENT_DETAIL)
        assert "cd-confirm-cancel" in src

    def test_confirm_has_save(self):
        src = _read(CLIENT_DETAIL)
        assert "cd-confirm-save" in src


# =============================================================================
# 13. Validation error display
# =============================================================================

class TestValidationErrors:
    """Backend validation errors must be displayed."""

    def test_validation_errors_state(self):
        src = _read(CLIENT_DETAIL)
        assert "validationErrors" in src
        assert "setValidationErrors" in src

    def test_validation_errors_rendered(self):
        src = _read(CLIENT_DETAIL)
        assert "cd-validation-errors" in src

    def test_save_error_rendered(self):
        src = _read(CLIENT_DETAIL)
        assert "cd-save-error" in src


# =============================================================================
# 14. Partial PUT — sends only changed fields
# =============================================================================

class TestPartialPut:
    """Frontend must send only changed fields (partial PUT)."""

    def test_computes_changed_fields(self):
        src = _read(CLIENT_DETAIL)
        assert "computeChanges" in src

    def test_compares_against_original(self):
        """Must compare form state against original loaded record."""
        src = _read(CLIENT_DETAIL)
        idx = src.find("computeChanges")
        assert idx > 0
        region = src[idx:idx + 600]
        assert "original" in region, \
            "Must compare against original record to detect changes"

    def test_sends_changed_only_to_save(self):
        """saveCustomerMaster must receive changedFields, not full form."""
        src = _read(CLIENT_DETAIL)
        # Skip comment occurrences — find the call inside a function body
        code_lines = [ln for ln in src.splitlines()
                      if not ln.strip().startswith("//")]
        code = "\n".join(code_lines)
        idx = code.find("PzApi.saveCustomerMaster(")
        assert idx > 0, "Must call PzApi.saveCustomerMaster()"
        region = code[idx:idx + 150]
        assert "changedFields" in region, \
            "Must pass changedFields to saveCustomerMaster, not full form"
