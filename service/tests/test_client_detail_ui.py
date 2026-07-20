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
# 3. V1 UI PARITY — six tabs, V1 order and V1 labels
# =============================================================================
#
# V1 is the visual authority (operator directive 2026-07-20). The reference is
# ClientKycModal in app/static/dashboard.html (FROZEN V1 page). These tests pin
# the parity contract: same tab ids, same order, same labels, same section
# headings, same header/footer chrome. Superseded the earlier 5-tab shape
# ('identity' / 'billing' / 'commercial' / 'sync'), which was a V2-only
# invention and is intentionally gone.

V1_TAB_IDS = ['basic', 'shipping', 'carriers', 'kyc', 'kuke', 'invoices']
V1_TAB_LABELS = ['Company / Basic', 'Shipping', 'Carriers',
                 'KYC / Compliance', 'KUKE & Credit', 'Invoices']


class TestV1TabParity:
    """Modal must expose the six V1 tabs, in V1 order, with V1 labels."""

    @pytest.mark.parametrize("tab_id", V1_TAB_IDS)
    def test_tab_id_present(self, tab_id):
        src = _read(CLIENT_DETAIL)
        assert f"'{tab_id}'" in src, f"V1 tab id '{tab_id}' must exist"

    @pytest.mark.parametrize("label", V1_TAB_LABELS)
    def test_tab_label_present(self, label):
        src = _read(CLIENT_DETAIL)
        assert label in src, f"V1 tab label '{label}' must exist"

    def test_tab_order_matches_v1(self):
        """_CD_TABS must list the six tabs in V1 order."""
        src = _read(CLIENT_DETAIL)
        block = src[src.index("const _CD_TABS"):src.index("];", src.index("const _CD_TABS"))]
        found = [t for t in V1_TAB_IDS if f"'{t}'" in block]
        positions = [block.index(f"'{t}'") for t in V1_TAB_IDS]
        assert found == V1_TAB_IDS, "all six V1 tabs must be in _CD_TABS"
        assert positions == sorted(positions), \
            "_CD_TABS order must match V1 (basic, shipping, carriers, kyc, kuke, invoices)"

    def test_every_tab_has_a_panel(self):
        src = _read(CLIENT_DETAIL)
        for tab_id in V1_TAB_IDS:
            assert f"tab === '{tab_id}'" in src, f"tab '{tab_id}' must render a panel"

    def test_no_v2_only_tab_ids_remain(self):
        """The pre-parity V2 tab ids must be gone."""
        src = _read(CLIENT_DETAIL)
        block = src[src.index("const _CD_TABS"):src.index("];", src.index("const _CD_TABS"))]
        for stale in ("'identity'", "'billing'", "'commercial'", "'sync'"):
            assert stale not in block, f"stale V2-only tab {stale} must not be in _CD_TABS"


class TestV1SectionParity:
    """V1 section headings must be reproduced verbatim."""

    @pytest.mark.parametrize("heading", [
        'Company / Identity', 'Billing address', 'Contact', 'VAT / Tax numbers', 'Notes',
        'Bill-to address (from Client Master)', 'Ship-to address',
        'Saved delivery addresses',
        # Was V1's 'Carrier accounts'. Operator ruling 2026-07-20 renamed this
        # section to 'DHL Express accounts' as part of the Carrier tab label
        # work; the newer ruling supersedes the V1 heading here.
        'DHL Express accounts',
        'KYC Status', 'KUKE Insurance', 'Credit',
        'Document defaults', 'Payment defaults',
    ])
    def test_section_heading_present(self, heading):
        src = _read(CLIENT_DETAIL)
        assert heading in src, f"V1 section heading '{heading}' must exist"


class TestV1ChromeParity:
    """Header, tab strip and footer must match V1 chrome."""

    def test_icon_close_not_text_close(self):
        """V1 closes with a ✕ icon. 'X Close' was the V2 regression."""
        src = _read(CLIENT_DETAIL)
        assert "X Close" not in src, "close control must be the V1 ✕ icon, not 'X Close'"
        assert "✕" in src, "V1 ✕ close icon must be present"

    def test_v1_modal_width(self):
        src = _read(CLIENT_DETAIL)
        assert "maxWidth: 760" in src, "V1 modal is maxWidth 760"

    def test_v1_tab_map_subtitle(self):
        src = _read(CLIENT_DETAIL)
        for part in ('Company', 'Shipping', 'Carriers', 'KYC', 'Credit', 'Invoices'):
            assert part in src
        assert "wFirma" in src, "header must show the wFirma contractor id"

    def test_v1_footer_buttons(self):
        """Footer is Cancel + Save (V1 wording, not 'Save to Customer Master')."""
        src = _read(CLIENT_DETAIL)
        footer = src[src.index("cd-cancel"):]
        assert ">Cancel<" in footer
        assert "Save to Customer Master" not in src, \
            "V1 footer button is labelled 'Save'"


class TestV1SubResourceParity:
    """V1 shipping-address + carrier-account CRUD must exist, via PzApi only."""

    @pytest.mark.parametrize("method", [
        "listShippingAddresses", "createShippingAddress",
        "updateShippingAddress", "deleteShippingAddress",
        "listCarrierAccounts", "createCarrierAccount",
        "updateCarrierAccount", "deleteCarrierAccount",
    ])
    def test_subresource_method_used(self, method):
        src = _read(CLIENT_DETAIL)
        assert f"PzApi.{method}" in src, f"PzApi.{method} must be used"

    @pytest.mark.parametrize("method", [
        "listShippingAddresses", "createShippingAddress",
        "updateShippingAddress", "deleteShippingAddress",
        "listCarrierAccounts", "createCarrierAccount",
        "updateCarrierAccount", "deleteCarrierAccount",
    ])
    def test_subresource_method_defined_in_api(self, method):
        """Transport lives in pz-api.js (Lesson F), not in the component."""
        src = _read(V2_DIR / "pz-api.js")
        assert f"{method}:" in src, f"pz-api.js must define {method}"

    def test_copy_billing_affordance(self):
        src = _read(CLIENT_DETAIL)
        assert "Copy billing address" in src


class TestCapabilityPreservation:
    """Lesson M — V2 capabilities with no V1 tab must survive the port."""

    @pytest.mark.parametrize("field", [
        "freight_fixed_amount_eur", "freight_fixed_amount_usd",
        "insurance_rate", "ship_to_contractor_id",
    ])
    def test_capability_field_still_rendered(self, field):
        src = _read(CLIENT_DETAIL)
        assert field in src, f"{field} must not be dropped by the parity port"

    def test_bank_account_not_rendered_as_input(self):
        """bank_account must NOT be an editable field until the backend is fixed.

        upsert_customer()'s payload dict in customer_master_db.py omits
        bank_account, so a PUT returns 200 and silently discards the value.
        V1 has no such field either, so parity and honesty agree here.
        Re-add the input only in the same change that fixes the payload dict.
        """
        src = _read(CLIENT_DETAIL)
        assert "inp('bank_account'" not in src, \
            "bank_account input must stay out until upsert_customer persists it"


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
        """Rendered as read-only metadata, never as an editable input.

        V1 parity: the id shows in the header subtitle and in the collapsed
        'Record metadata' block on Company / Basic. It must never be bound to
        a writable input via set('bill_to_contractor_id', ...).
        """
        src = _read(CLIENT_DETAIL)
        assert "bill_to_contractor_id" in src
        assert "cd-ro-contractor-id" in src, \
            "bill_to_contractor_id must render in the read-only metadata block"
        assert "set('bill_to_contractor_id'" not in src, \
            "bill_to_contractor_id must never be operator-editable"
        assert "inp('bill_to_contractor_id'" not in src, \
            "bill_to_contractor_id must never render as an editable input"


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
        for tab_id in V1_TAB_IDS:
            assert f"'{tab_id}'" in src, f"Tab ID {tab_id} must be defined"

    def test_confirm_dialog(self):
        src = _read(CLIENT_DETAIL)
        assert "cd-confirm-dialog" not in src

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
    """V1 parity: the footer button is labelled 'Save'.

    Was 'Save Changes' — a label that never actually shipped (the pre-parity
    V2 rendered 'Save to Customer Master', so this assertion was already
    failing on main). V1's ClientKycModal footer reads 'Save', with
    'Saving…' while in flight and 'No contractor ID' when unsaveable.
    """

    def test_save_label_matches_v1(self):
        src = _read(CLIENT_DETAIL)
        footer = src[src.index('data-testid="cd-save"'):]
        assert "'Save'" in footer, "V1 footer button label is 'Save'"
        assert "'Saving…'" in footer, "V1 in-flight label is 'Saving…'"
        assert "'No contractor ID'" in footer, \
            "V1 disables save with a 'No contractor ID' label"

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
# 12. Save is immediate — no confirm dialog (V1 parity)
# =============================================================================

class TestNoConfirmDialog:
    """Operator ruling 2026-07-20: Save writes immediately, exactly like V1.

    A Customer Master edit is not an irreversible financial operation;
    dirty-state, validation and save-error handling are the safeguards.
    Confirm dialogs are reserved for genuinely irreversible / financially
    consequential actions.
    """

    def test_no_confirm_dialog_component(self):
        src = _read(CLIENT_DETAIL)
        assert "_CdConfirmDialog" not in src
        assert "cd-confirm-dialog" not in src

    def test_no_confirm_state(self):
        src = _read(CLIENT_DETAIL)
        assert "showConfirm" not in src
        assert "setShowConfirm" not in src

    def test_save_button_saves_directly(self):
        """cd-save must invoke the save handler, not open a dialog."""
        src = _read(CLIENT_DETAIL)
        assert 'data-testid="cd-save" onClick={handleSave}' in src

    def test_changed_field_diff_still_computed(self):
        """Partial-PUT contract is unchanged — only changed fields are sent."""
        src = _read(CLIENT_DETAIL)
        assert "computeChanges" in src and "changedFields" in src


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
