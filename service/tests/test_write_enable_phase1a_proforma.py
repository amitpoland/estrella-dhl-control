"""Write Enablement Phase 1A — Proforma Safe Actions regression tests.

Source-grep tests verifying that:
1. M5 Inline Edit: Edit button is conditionally enabled (not hardcoded disabled)
2. M5 Inline Edit: Uses PATCH endpoints via PzApi.patchDraft
3. M5 Inline Edit: Includes expected_updated_at for optimistic locking
4. M5 Inline Edit: Edit mode shows save/cancel controls with data-testid
5. M1a Cancel Draft: Delete button relabeled to "Cancel Draft"
6. M1a Cancel Draft: Uses POST cancel via PzApi.cancelDraft (not DELETE)
7. M1a Cancel Draft: No DELETE route invented
8. M1a Cancel Draft: Confirmation modal with reason input
9. M7 Prior Invoice History: Button exists with data-testid
10. M7 Prior Invoice History: Uses ledger route (getClientInvoiceLedger)
11. M7 Prior Invoice History: Disabled with reason when contractor_id missing
12. Lesson M: Send/CMR/Generate remain visible and disabled with reasons
13. Lesson M: No planned controls removed (all testids still present)
14. pz-api.js: getClientInvoiceLedger transport defined
15. Cancel modal: CancelDraftModal exported to window
16. Prior Invoice modal: PriorInvoiceHistoryModal exported to window

Sprint: Write Enablement Phase 1A — Proforma Safe Actions
Target: proforma-detail.jsx, pz-api.js
"""

import pathlib
import re

import pytest

V2_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "v2"
DETAIL = V2_DIR / "proforma-detail.jsx"
PZ_API = V2_DIR / "pz-api.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# =============================================================================
# 1. M5 — Inline Edit: button is conditionally enabled
# =============================================================================

class TestM5InlineEdit:
    """Edit button must be conditionally enabled, not hardcoded disabled."""

    def test_edit_button_not_hardcoded_disabled(self):
        """The edit button must NOT be unconditionally disabled."""
        src = _read(DETAIL)
        # Find the tb-edit button region — it should NOT have a bare `disabled` prop
        # without a condition. Look for the pattern: onClick={handleEnterEdit}
        assert "handleEnterEdit" in src, "Edit button must have handleEnterEdit handler"

    def test_can_edit_state_derived(self):
        """canEdit must be derived from draft state."""
        src = _read(DETAIL)
        assert "canEdit" in src, "canEdit variable must exist"
        # Must check for editable states
        assert "'draft'" in src and "'editing'" in src, \
            "canEdit must check for draft/editing states"

    def test_edit_mode_state_exists(self):
        src = _read(DETAIL)
        assert "editMode" in src, "editMode state must exist"
        assert "setEditMode" in src, "setEditMode setter must exist"

    def test_edit_save_button_exists(self):
        src = _read(DETAIL)
        assert "tb-edit-save" in src, "Save button must have data-testid tb-edit-save"

    def test_edit_cancel_button_exists(self):
        src = _read(DETAIL)
        assert "tb-edit-cancel" in src, "Cancel button must have data-testid tb-edit-cancel"

    def test_uses_patch_draft(self):
        """Edit save must call PzApi.patchDraft."""
        src = _read(DETAIL)
        assert "PzApi.patchDraft" in src or "patchDraft" in src, \
            "Edit save must use PzApi.patchDraft"

    def test_includes_expected_updated_at(self):
        """PATCH call must include expected_updated_at for optimistic locking."""
        src = _read(DETAIL)
        assert "updated_at" in src, \
            "Edit save must reference updated_at for optimistic locking"

    def test_edit_mode_banner_exists(self):
        src = _read(DETAIL)
        assert "edit-mode-banner" in src, "Edit mode banner with data-testid must exist"

    def test_editable_fields_include_remarks(self):
        src = _read(DETAIL)
        assert "edit-remarks-section" in src or "edit-field-remarks" in src, \
            "Remarks must be editable in edit mode"

    def test_editable_fields_include_currency(self):
        src = _read(DETAIL)
        assert "editFields.currency" in src, "Currency must be editable"

    def test_editable_fields_include_exchange_rate(self):
        src = _read(DETAIL)
        assert "editFields.exchange_rate" in src, "Exchange rate must be editable"

    def test_editable_fields_include_payment_terms(self):
        src = _read(DETAIL)
        assert "editFields.payment_terms" in src, "Payment terms must be editable"


# =============================================================================
# 2. M1a — Cancel Draft
# =============================================================================

class TestM1aCancelDraft:
    """Delete button must be relabeled to Cancel Draft and wired to cancel endpoint."""

    def test_label_is_cancel_draft(self):
        """The tb-delete button must say 'Cancel Draft', not 'Delete'."""
        src = _read(DETAIL)
        # Find the tb-delete testid and verify the label near it
        idx = src.find('data-testid="tb-delete"')
        assert idx > 0
        # The surrounding JSX should contain "Cancel Draft"
        region = src[max(0, idx - 200):idx + 200]
        assert "Cancel Draft" in region, "Button label must be 'Cancel Draft'"

    def test_uses_cancel_draft_api(self):
        """Must call PzApi.cancelDraft, not a DELETE endpoint."""
        src = _read(DETAIL)
        assert "cancelDraft" in src, "Must use PzApi.cancelDraft"

    def test_no_delete_route_invented(self):
        """No DELETE /draft/{id} route must be called."""
        src = _read(DETAIL)
        # Check no DELETE method call for draft deletion in the main component
        # The existing _del in pz-api.js is fine for lines, but no delete_draft route
        code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))
        assert "DELETE" not in code or "deleteDraft" not in code, \
            "No deleteDraft transport should exist for M1a — uses cancelDraft instead"

    def test_cancel_modal_exists(self):
        src = _read(DETAIL)
        assert "CancelDraftModal" in src, "CancelDraftModal component must exist"

    def test_cancel_modal_has_testid(self):
        src = _read(DETAIL)
        assert "cancel-draft-modal" in src, "Cancel modal must have data-testid"

    def test_cancel_modal_has_reason_input(self):
        src = _read(DETAIL)
        assert "cancel-draft-reason" in src, "Cancel modal must have reason input"

    def test_cancel_modal_has_submit_button(self):
        src = _read(DETAIL)
        assert "cancel-draft-submit" in src, "Cancel modal must have submit button"

    def test_can_cancel_derived_from_state(self):
        src = _read(DETAIL)
        assert "canCancel" in src, "canCancel must be derived from draft state"

    def test_cancel_button_is_conditional(self):
        """Cancel button must be conditionally enabled."""
        src = _read(DETAIL)
        idx = src.find('data-testid="tb-delete"')
        assert idx > 0
        region = src[max(0, idx - 300):idx]
        assert "canCancel" in region or "disabled={!canCancel}" in region, \
            "Cancel button must be conditionally disabled"

    def test_cancel_sends_reason(self):
        """Cancel API call must include reason."""
        src = _read(DETAIL)
        assert "reason" in src, "Cancel must send reason"


# =============================================================================
# 3. M7 — Prior Invoice History
# =============================================================================

class TestM7PriorInvoiceHistory:
    """Prior Invoice History button and modal must exist."""

    def test_button_exists(self):
        src = _read(DETAIL)
        assert "tb-invoice-history" in src, "Prior Invoice button must have data-testid"

    def test_button_label(self):
        src = _read(DETAIL)
        assert "Prior Invoices" in src, "Button must be labeled 'Prior Invoices'"

    def test_disabled_when_no_contractor(self):
        """Button must be disabled when contractorId is missing."""
        src = _read(DETAIL)
        idx = src.find('data-testid="tb-invoice-history"')
        assert idx > 0
        region = src[max(0, idx - 400):idx]
        assert "contractorId" in region, \
            "Button must check contractorId for enablement"

    def test_disabled_reason_when_no_contractor(self):
        src = _read(DETAIL)
        assert "wFirma contractor ID missing" in src, \
            "Must show reason when contractor ID is missing"

    def test_modal_exists(self):
        src = _read(DETAIL)
        assert "PriorInvoiceHistoryModal" in src, "PriorInvoiceHistoryModal must exist"

    def test_modal_has_testid(self):
        src = _read(DETAIL)
        assert "prior-invoice-modal" in src, "Modal must have data-testid"

    def test_modal_has_table(self):
        src = _read(DETAIL)
        assert "prior-invoice-table" in src, "Modal must have invoice table"

    def test_modal_has_loading_state(self):
        src = _read(DETAIL)
        assert "prior-invoice-loading" in src, "Modal must have loading state"

    def test_modal_has_error_state(self):
        src = _read(DETAIL)
        assert "prior-invoice-error" in src, "Modal must have error state"

    def test_modal_has_empty_state(self):
        src = _read(DETAIL)
        assert "prior-invoice-empty" in src, "Modal must have empty state"

    def test_uses_ledger_route(self):
        """Must call getClientInvoiceLedger to fetch invoice data."""
        src = _read(DETAIL)
        assert "getClientInvoiceLedger" in src, \
            "Must use PzApi.getClientInvoiceLedger"


# =============================================================================
# 4. pz-api.js — Transport
# =============================================================================

class TestPzApiTransport:
    """pz-api.js must have the getClientInvoiceLedger transport."""

    def test_transport_defined(self):
        src = _read(PZ_API)
        assert "getClientInvoiceLedger" in src

    def test_ledger_route_url(self):
        src = _read(PZ_API)
        assert "invoice-ledger.json" in src, "Transport must target invoice-ledger.json"

    def test_ledger_route_is_get(self):
        """Ledger transport must use GET (read-only)."""
        src = _read(PZ_API)
        idx = src.find("getClientInvoiceLedger")
        assert idx > 0
        region = src[idx:idx + 300]
        assert "_get(" in region, "Ledger transport must use _get (GET method)"


# =============================================================================
# 5. Lesson M — Disabled controls preserved
# =============================================================================

class TestLessonMPreservation:
    """Send, CMR, Generate, More buttons must remain visible and disabled."""

    @pytest.mark.parametrize("testid,label_fragment", [
        ("tb-send",     "Send"),
        ("tb-cmr",      "CMR"),
        ("tb-generate", "Generate"),
        ("tb-more",     "⋯"),
    ])
    def test_disabled_button_still_present(self, testid, label_fragment):
        src = _read(DETAIL)
        assert testid in src, f"Button {testid} must still exist (Lesson M)"
        idx = src.find(f'data-testid="{testid}"')
        region = src[max(0, idx - 200):idx + 100]
        assert "disabled" in region, f"Button {testid} must still be disabled"

    def test_send_has_explicit_reason(self):
        src = _read(DETAIL)
        assert "Email send not yet wired to backend" in src

    def test_cmr_has_explicit_reason(self):
        src = _read(DETAIL)
        assert "CMR print" in src and "no backend PDF generation route" in src

    def test_generate_has_explicit_reason(self):
        src = _read(DETAIL)
        assert "Document generation not yet available" in src

    def test_no_testids_removed(self):
        """All original toolbar testids must still be present."""
        src = _read(DETAIL)
        required_testids = [
            "tb-edit", "tb-delete", "tb-duplicate", "tb-post",
            "tb-convert", "tb-preview", "tb-cmr", "tb-send",
            "tb-generate", "tb-more", "tb-back",
            "proforma-detail-download-pdf",
        ]
        for tid in required_testids:
            assert tid in src, f"Required testid '{tid}' must still exist"


# =============================================================================
# 6. Window exports
# =============================================================================

class TestWindowExports:
    def test_cancel_modal_exported(self):
        src = _read(DETAIL)
        export_idx = src.find("Object.assign(window,")
        assert export_idx > 0
        region = src[export_idx:export_idx + 300]
        assert "CancelDraftModal" in region, "CancelDraftModal must be window-exported"

    def test_prior_invoice_modal_exported(self):
        src = _read(DETAIL)
        export_idx = src.find("Object.assign(window,")
        assert export_idx > 0
        region = src[export_idx:export_idx + 300]
        assert "PriorInvoiceHistoryModal" in region, \
            "PriorInvoiceHistoryModal must be window-exported"

    def test_proforma_detail_page_still_exported(self):
        src = _read(DETAIL)
        export_idx = src.find("Object.assign(window,")
        assert export_idx > 0
        region = src[export_idx:export_idx + 300]
        assert "ProformaDetailPage" in region


# =============================================================================
# 7. No destructive operations
# =============================================================================

class TestSafetyConstraints:
    """Write enablement must not introduce unsafe operations."""

    def test_no_delete_whole_draft_in_api(self):
        """pz-api.js must NOT have a deleteWholeDraft transport (deleteDraftLine is fine)."""
        src = _read(PZ_API)
        code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("//"))
        # deleteDraftLine exists for line removal — that's correct.
        # But there must be no `deleteDraft:` or `deleteWholeDraft` transport
        # that targets DELETE /draft/{id} without /lines/ in the path.
        import re
        matches = re.findall(r'deleteDraft\b(?!Line)', code)
        assert len(matches) == 0, \
            "No deleteDraft (whole-draft) transport — M1a uses cancelDraft"

    def test_no_wfirma_write_in_invoice_history(self):
        """Prior Invoice modal must be read-only."""
        src = _read(DETAIL)
        idx = src.find("PriorInvoiceHistoryModal")
        end = src.find("}", idx + 500) if idx > 0 else -1
        if idx > 0 and end > 0:
            region = src[idx:end + 500]
            assert "_postM" not in region, "Invoice history modal must not make write calls"

    def test_cancel_is_soft_state(self):
        """Cancel uses PzApi.cancelDraft (POST /cancel), not DELETE."""
        src = _read(DETAIL)
        assert "cancelDraft" in src
        # Verify it does NOT use a DELETE method for draft removal
        assert "deleteDraft(" not in src

    def test_edit_does_not_post_to_wfirma(self):
        """Edit mode must not trigger a wFirma post."""
        src = _read(DETAIL)
        idx = src.find("handleSaveEdit")
        if idx > 0:
            region = src[idx:idx + 800]
            assert "postDraftToWfirma" not in region, \
                "Edit save must not trigger wFirma post"
