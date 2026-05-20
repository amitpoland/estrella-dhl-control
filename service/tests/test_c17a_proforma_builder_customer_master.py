"""tests/test_c17a_proforma_builder_customer_master.py — C17A

Source-grep tests verifying the Proforma Builder Customer Master Mirror redesign.

C17A contract:
  - customersBody renders per-client CARDS (workflow-cm-card-{i}) not rows
  - Each card shows buyer/bill-to block (bill_to_name, bill_to_nip, bill_to_street/city)
  - Each card shows ship-to block (ship_to_name when different)
  - Each card shows payment block (preferred_payment_method, payment_terms_days, default_currency)
  - Each card shows document settings block (preferred_proforma_series_id, preferred_invoice_series_id)
  - Each card has an inline edit form (btn-cm-edit-{cid})
  - Edit form has Save and Cancel buttons (btn-cm-save-{cid}, btn-cm-cancel-{cid})
  - Edit form saves via PUT /api/v1/customer-master/{contractorId}
  - saveCmFields uses PUT method (not POST, not PATCH)
  - Technical wFirma mapping collapsed in <details> per card
  - ProformaCustomerCard: business header (Buyer label + client name) is prominent
  - ProformaCustomerCard: wFirma technical fields inside collapsed <details>
  - ProformaCustomerCard: unmatched state shown as contextual warning, not technical grid row
  - OperatorWorkflowCard has cmEdit, cmSaving, cmSavedMsg state
  - OperatorWorkflowCard has saveCmFields callback
  - Safety: no wFirma write flag touched, no PZ creation, no fiscal gate bypass
  - Safety: save note says 'No PZ' or equivalent
  - Braces balanced in shipment-detail.html
"""
from __future__ import annotations

from pathlib import Path

import pytest

_HERE     = Path(__file__).resolve()
_SVC_ROOT = _HERE.parent.parent
_DETAIL   = _SVC_ROOT / "app" / "static" / "shipment-detail.html"


def _src() -> str:
    if not _DETAIL.exists():
        pytest.skip("shipment-detail.html not found")
    return _DETAIL.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════
# CLASS 1: Per-client card redesign in customersBody
# ══════════════════════════════════════════════════════════

class TestC17ACustomersBodyCards:
    def test_cm_card_testid_present(self):
        """C17A: Per-client cards must use workflow-cm-card-{i} testid."""
        src = _src()
        assert "workflow-cm-card-" in src, (
            "customersBody must render cards with data-testid='workflow-cm-card-{i}'"
        )

    def test_bill_to_nip_in_customers_body(self):
        """C17A: Buyer block must include bill_to_nip (VAT)."""
        src = _src()
        idx = src.find("workflow-customers-body")
        assert idx != -1
        ctx = src[idx: idx + 10000]
        assert "bill_to_nip" in ctx, "customersBody must show bill_to_nip (VAT/NIP)"

    def test_bill_to_street_in_customers_body(self):
        """C17A: Buyer block must include bill_to_street (address)."""
        src = _src()
        idx = src.find("workflow-customers-body")
        assert idx != -1
        ctx = src[idx: idx + 10000]
        assert "bill_to_street" in ctx, "customersBody must show bill_to_street"

    def test_bill_to_city_in_customers_body(self):
        """C17A: Buyer block must include bill_to_city."""
        src = _src()
        idx = src.find("workflow-customers-body")
        assert idx != -1
        ctx = src[idx: idx + 10000]
        assert "bill_to_city" in ctx, "customersBody must show bill_to_city"

    def test_ship_to_block_in_customers_body(self):
        """C17A: Ship-to block must be rendered (conditional on shipDiffers)."""
        src = _src()
        idx = src.find("workflow-customers-body")
        assert idx != -1
        ctx = src[idx: idx + 10000]
        assert "Ship-to" in ctx or "ship_to_name" in ctx, (
            "customersBody must render ship-to block"
        )

    def test_wfirma_mapping_in_details_element(self):
        """C17A: Technical wFirma mapping must be inside a <details> element per card."""
        src = _src()
        idx = src.find("workflow-customers-body")
        assert idx != -1
        ctx = src[idx: idx + 10000]
        assert "<details" in ctx, "wFirma mapping must be inside <details> (collapsed)"
        assert "wFirma mapping details" in ctx, (
            "details summary must say 'wFirma mapping details'"
        )

    def test_status_badge_on_card(self):
        """C17A: Each card must show a status badge (mapped/ambiguous/missing)."""
        src = _src()
        idx = src.find("workflow-customers-body")
        assert idx != -1
        ctx = src[idx: idx + 10000]
        assert "statusBg" in ctx or "statusColor" in ctx or "'mapped'" in ctx, (
            "cards must render a status badge"
        )

    def test_client_name_in_card_header(self):
        """C17A: Card header must render d.client_name prominently."""
        src = _src()
        idx = src.find("workflow-customers-body")
        assert idx != -1
        ctx = src[idx: idx + 10000]
        assert "d.client_name" in ctx, "card header must render d.client_name"

    def test_all_details_iterated_not_just_resolved(self):
        """C17A: allDetails must include ALL clients, not just resolved ones."""
        src = _src()
        idx = src.find("workflow-customers-body")
        assert idx != -1
        ctx = src[idx: idx + 10000]
        assert "allDetails.map" in ctx, (
            "customersBody must iterate allDetails (all clients, not just resolved)"
        )
        # Old resolvedDetails-only filter must not be the sole path
        # (allDetails replaces it for card rendering)
        assert "allDetails" in ctx

    def test_missing_client_shows_no_cm_record_note(self):
        """C17A: If no CM record found for a client, show informational note."""
        src = _src()
        idx = src.find("workflow-customers-body")
        assert idx != -1
        ctx = src[idx: idx + 10000]
        assert "No Customer Master record" in ctx, (
            "missing CM record must show 'No Customer Master record' note"
        )


# ══════════════════════════════════════════════════════════
# CLASS 2: Inline edit form
# ══════════════════════════════════════════════════════════

class TestC17AInlineEditForm:
    def test_edit_button_testid_present(self):
        """C17A: Edit button must have btn-cm-edit-{cid} testid."""
        src = _src()
        assert "btn-cm-edit-" in src, (
            "edit button must have data-testid='btn-cm-edit-{cid}'"
        )

    def test_save_button_testid_present(self):
        """C17A: Save button must have btn-cm-save-{cid} testid."""
        src = _src()
        assert "btn-cm-save-" in src, (
            "save button must have data-testid='btn-cm-save-{cid}'"
        )

    def test_cancel_button_testid_present(self):
        """C17A: Cancel button must have btn-cm-cancel-{cid} testid."""
        src = _src()
        assert "btn-cm-cancel-" in src, (
            "cancel button must have data-testid='btn-cm-cancel-{cid}'"
        )

    def test_edit_form_testid_present(self):
        """C17A: Edit form container must have cm-edit-form-{cid} testid."""
        src = _src()
        assert "cm-edit-form-" in src, (
            "edit form must have data-testid='cm-edit-form-{cid}'"
        )

    def test_save_uses_put_method(self):
        """C17A: saveCmFields must use PUT method (not POST, not PATCH)."""
        src = _src()
        idx = src.find("saveCmFields")
        assert idx != -1
        body = src[idx: idx + 600]
        assert "method: 'PUT'" in body, "saveCmFields must use PUT method"

    def test_save_targets_customer_master_endpoint(self):
        """C17A: saveCmFields must call /api/v1/customer-master/{contractorId}."""
        src = _src()
        idx = src.find("saveCmFields")
        assert idx != -1
        body = src[idx: idx + 600]
        assert "/api/v1/customer-master/" in body, (
            "saveCmFields must PUT to /api/v1/customer-master/{contractorId}"
        )

    def test_edit_form_has_payment_method_select(self):
        """C17A: Edit form must include a payment method dropdown with 'transfer' option."""
        src = _src()
        # The CmEditForm helper is defined inside the customersBody IIFE,
        # before the return statement — search from the IIFE declaration.
        idx = src.find("const customersBody = (() => {")
        assert idx != -1
        ctx = src[idx: idx + 20000]
        assert "value=\"transfer\"" in ctx or "value='transfer'" in ctx, (
            "payment method dropdown must include 'transfer' option"
        )

    def test_edit_form_has_proforma_series_field(self):
        """C17A: Edit form must include proforma series ID field."""
        src = _src()
        assert "preferred_proforma_series_id" in src, (
            "edit form must have preferred_proforma_series_id field"
        )

    def test_edit_form_has_invoice_series_field(self):
        """C17A: Edit form must include invoice series ID field."""
        src = _src()
        assert "preferred_invoice_series_id" in src, (
            "edit form must have preferred_invoice_series_id field"
        )

    def test_edit_form_has_bill_to_fields(self):
        """C17A: Edit form must include bill-to address fields."""
        src = _src()
        # Check all bill_to fields are in the form
        for field in ['bill_to_name', 'bill_to_nip', 'bill_to_street',
                      'bill_to_city', 'bill_to_postal_code', 'bill_to_country']:
            assert field in src, f"edit form must have {field} field"

    def test_edit_form_has_ship_to_fields(self):
        """C17A: Edit form must include ship-to fields."""
        src = _src()
        assert "ship_to_name" in src
        assert "ship_to_street" in src
        assert "ship_to_city" in src

    def test_save_calls_refresh_on_success(self):
        """C17A: saveCmFields must call refresh() after a successful save."""
        src = _src()
        idx = src.find("const saveCmFields = React.useCallback")
        assert idx != -1
        body = src[idx: idx + 1200]
        assert "refresh()" in body, "saveCmFields must call refresh() on success"

    def test_save_clears_edit_state_on_success(self):
        """C17A: saveCmFields must call setCmEdit(null) on success."""
        src = _src()
        idx = src.find("const saveCmFields = React.useCallback")
        assert idx != -1
        body = src[idx: idx + 1200]
        assert "setCmEdit(null)" in body, "saveCmFields must clear edit state on success"


# ══════════════════════════════════════════════════════════
# CLASS 3: OperatorWorkflowCard state additions
# ══════════════════════════════════════════════════════════

class TestC17AOperatorWorkflowCardState:
    def _component(self, src: str) -> str:
        idx = src.find("function OperatorWorkflowCard")
        end = src.find("function CNHSNDecisionPanel")
        return src[idx:end]

    def test_cm_edit_state_declared(self):
        """C17A: OperatorWorkflowCard must declare cmEdit state."""
        src = _src()
        comp = self._component(src)
        assert "cmEdit" in comp and "setCmEdit" in comp, (
            "OperatorWorkflowCard must declare [cmEdit, setCmEdit] state"
        )

    def test_cm_saving_state_declared(self):
        """C17A: OperatorWorkflowCard must declare cmSaving state."""
        src = _src()
        comp = self._component(src)
        assert "cmSaving" in comp and "setCmSaving" in comp, (
            "OperatorWorkflowCard must declare [cmSaving, setCmSaving] state"
        )

    def test_cm_saved_msg_state_declared(self):
        """C17A: OperatorWorkflowCard must declare cmSavedMsg state."""
        src = _src()
        comp = self._component(src)
        assert "cmSavedMsg" in comp and "setCmSavedMsg" in comp, (
            "OperatorWorkflowCard must declare [cmSavedMsg, setCmSavedMsg] state"
        )

    def test_save_cm_fields_callback_declared(self):
        """C17A: OperatorWorkflowCard must declare saveCmFields callback."""
        src = _src()
        comp = self._component(src)
        assert "saveCmFields" in comp, (
            "OperatorWorkflowCard must declare saveCmFields callback"
        )

    def test_save_cm_fields_uses_useCallback(self):
        """C17A: saveCmFields must be wrapped in useCallback for stability."""
        src = _src()
        idx = src.find("saveCmFields")
        assert idx != -1
        ctx = src[idx: idx + 30]
        # Check the declaration form
        decl_idx = src.find("const saveCmFields = React.useCallback")
        assert decl_idx != -1, "saveCmFields must be React.useCallback"


# ══════════════════════════════════════════════════════════
# CLASS 4: ProformaCustomerCard redesign
# ══════════════════════════════════════════════════════════

class TestC17AProformaCustomerCard:
    def _card_src(self, src: str) -> str:
        idx = src.find("function ProformaCustomerCard")
        assert idx != -1
        return src[idx: idx + 6000]

    def test_buyer_label_prominent(self):
        """C17A: ProformaCustomerCard must show 'Buyer' label (not 'Customer mapping')."""
        src = _src()
        card = self._card_src(src)
        assert "Buyer" in card, (
            "ProformaCustomerCard header must say 'Buyer' not 'Customer mapping'"
        )

    def test_customer_mapping_heading_removed(self):
        """C17A: The old 'Customer mapping' section heading must be removed."""
        src = _src()
        card = self._card_src(src)
        assert "Customer mapping" not in card, (
            "Old 'Customer mapping' heading must be replaced by business layout"
        )

    def test_technical_fields_in_details_element(self):
        """C17A: wFirma ID and match strategy must be inside <details> (collapsed)."""
        src = _src()
        card = self._card_src(src)
        assert "<details>" in card or "<details " in card, (
            "technical fields must be inside <details> collapsed block"
        )

    def test_wfirma_id_testid_preserved(self):
        """C17A: draft-customer-wfirma-id testid must still exist for compatibility."""
        src = _src()
        assert 'data-testid="draft-customer-wfirma-id"' in src, (
            "draft-customer-wfirma-id testid must be preserved in collapsed details"
        )

    def test_match_strategy_testid_preserved(self):
        """C17A: draft-customer-match-strategy testid must still exist."""
        src = _src()
        assert 'data-testid="draft-customer-match-strategy"' in src, (
            "draft-customer-match-strategy testid must be preserved"
        )

    def test_unmatched_shown_as_warning_block(self):
        """C17A: Unmatched state must show contextual warning, not just a grid row."""
        src = _src()
        card = self._card_src(src)
        assert "!matched" in card, "unmatched state must be shown"
        # The warning must be a standalone block, not hidden in a grid
        assert "badge-red-bg" in card or "badge-amber-bg" in card, (
            "unmatched warning must use a colored background block"
        )

    def test_remap_button_still_present(self):
        """C17A: 'Open Customer Master' button must still be present."""
        src = _src()
        assert 'data-testid="btn-draft-customer-remap"' in src, (
            "remap button must still exist"
        )

    def test_draft_customer_card_testid_preserved(self):
        """C17A: draft-customer-card testid must still exist."""
        src = _src()
        assert 'data-testid="draft-customer-card"' in src, (
            "draft-customer-card testid must be preserved"
        )


# ══════════════════════════════════════════════════════════
# CLASS 5: Safety invariants — no forbidden writes
# ══════════════════════════════════════════════════════════

class TestC17ASafetyInvariants:
    def test_save_note_warns_no_pz_or_wfirma_write(self):
        """C17A: Edit form must display safety note about no PZ/invoice/wFirma write."""
        src = _src()
        idx = src.find("cm-edit-form-")
        assert idx != -1
        # Find the safety note in the form area
        form_area = src[max(0, idx - 500): idx + 5000]
        assert "No PZ" in form_area or "no PZ" in form_area or \
               "no wFirma write" in form_area or "No wFirma" in form_area or \
               "Customer Master only" in form_area, (
            "edit form must display safety note about no PZ/wFirma write"
        )

    def test_save_does_not_reference_wfirma_create_pz(self):
        """C17A: saveCmFields must not reference any PZ creation path."""
        src = _src()
        idx = src.find("saveCmFields")
        assert idx != -1
        body = src[idx: idx + 800]
        assert "create_pz" not in body.lower() and "pz_preview" not in body, (
            "saveCmFields must not touch any PZ creation endpoint"
        )

    def test_save_only_calls_customer_master_put(self):
        """C17A: saveCmFields must only write to /api/v1/customer-master/."""
        src = _src()
        idx = src.find("const saveCmFields = React.useCallback")
        assert idx != -1
        body = src[idx: idx + 800]
        # Should contain customer-master PUT
        assert "/api/v1/customer-master/" in body, "must PUT to customer-master"
        # Must NOT reference wfirma/upload/pz or other write paths
        forbidden = ["/api/v1/wfirma/", "/api/v1/upload/", "/pz/process"]
        for path in forbidden:
            assert path not in body, f"saveCmFields must not reference {path}"

    def test_no_new_wfirma_flags(self):
        """C17A: must not add any new WFIRMA_CREATE or WFIRMA_POST flags."""
        src = _src()
        # Count occurrences before C17A — they should not have increased
        assert "WFIRMA_CREATE_PZ_ALLOWED" not in src[src.find("function OperatorWorkflowCard"):
                                                       src.find("function CNHSNDecisionPanel")], (
            "OperatorWorkflowCard must not reference WFIRMA_CREATE_PZ_ALLOWED"
        )

    def test_braces_balanced(self):
        """C17A: shipment-detail.html must have balanced braces after C17A edits."""
        src = _src()
        opens  = src.count("{")
        closes = src.count("}")
        assert opens == closes, f"unbalanced braces: {{={opens} }}={closes}"
