"""
Slice 4 + Slice 5 — structural source-grep tests for proforma-detail.jsx.

These tests check the JSX source for:
  - Slice 4: three QA warning affordances wired to existing edit fields (no new save path)
  - Slice 5: ProformaReadinessPanel dedup guard so blockers already rendered by
             ProformaBlockerPanel are not repeated
  - No editable origin input on proforma lines (wrong authority — Lesson N)
  - No new backend call / no NBP-fetch method invented in PzApi
"""

import pathlib
import re
import pytest

JSX = pathlib.Path(__file__).parent.parent / "app" / "static" / "v2" / "proforma-detail.jsx"

def src() -> str:
    return JSX.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Slice 4 — QA warning testids exist and are wired correctly
# ─────────────────────────────────────────────────────────────────────────────

class TestSlice4WarningAffordances:
    """All three warn-fix testids exist and use only the existing edit path."""

    def test_warn_fix_fx_rate_testid_exists(self):
        """warn-fix-fx-rate button exists in the JSX source."""
        assert 'data-testid="warn-fix-fx-rate"' in src(), (
            "Expected data-testid=\"warn-fix-fx-rate\" in proforma-detail.jsx"
        )

    def test_warn_fix_issue_date_testid_exists(self):
        """warn-fix-issue-date button exists in the JSX source."""
        assert 'data-testid="warn-fix-issue-date"' in src(), (
            "Expected data-testid=\"warn-fix-issue-date\" in proforma-detail.jsx"
        )

    def test_warn_origin_authority_testid_exists(self):
        """warn-origin-authority advisory div exists in the JSX source."""
        assert 'data-testid="warn-origin-authority"' in src(), (
            "Expected data-testid=\"warn-origin-authority\" in proforma-detail.jsx"
        )

    def test_warn_fix_fx_rate_wired_to_no_fx_rate_code(self):
        """warn-fix-fx-rate is rendered only when w.code === 'NO_FX_RATE'."""
        text = src()
        # The testid must appear inside a NO_FX_RATE guard
        pattern = re.compile(
            r"NO_FX_RATE.*?warn-fix-fx-rate|warn-fix-fx-rate.*?NO_FX_RATE",
            re.DOTALL,
        )
        # Find occurrence window: look for the testid within 300 chars of NO_FX_RATE guard
        idx_code = text.find("w.code === 'NO_FX_RATE'")
        idx_tid = text.find('warn-fix-fx-rate')
        assert idx_code != -1, "w.code === 'NO_FX_RATE' guard not found"
        assert idx_tid != -1, "warn-fix-fx-rate testid not found"
        # The testid must appear within 500 chars after the guard
        assert 0 < (idx_tid - idx_code) < 500, (
            "warn-fix-fx-rate testid must be within 500 chars after NO_FX_RATE guard; "
            f"gap is {idx_tid - idx_code}"
        )

    def test_warn_fix_issue_date_wired_to_no_issue_date_code(self):
        """warn-fix-issue-date is rendered only when w.code === 'NO_ISSUE_DATE'."""
        text = src()
        idx_code = text.find("w.code === 'NO_ISSUE_DATE'")
        idx_tid = text.find('warn-fix-issue-date')
        assert idx_code != -1, "w.code === 'NO_ISSUE_DATE' guard not found"
        assert idx_tid != -1, "warn-fix-issue-date testid not found"
        assert 0 < (idx_tid - idx_code) < 500, (
            "warn-fix-issue-date testid must be within 500 chars after NO_ISSUE_DATE guard; "
            f"gap is {idx_tid - idx_code}"
        )

    def test_warn_fix_buttons_call_onEditRequest_not_a_new_save_path(self):
        """Both fix buttons call onEditRequest() — no new save API call invented."""
        text = src()
        # Both buttons must call onEditRequest (the existing enter-edit-mode callback)
        # and must NOT call a new backend method
        assert text.count("onEditRequest()") >= 2, (
            "Expected at least 2 onEditRequest() calls (one per fix button)"
        )
        # Guard: no new nbp/fx-fetch method should have been added to PzApi
        pz_api_block_match = re.search(
            r"window\.PzApi\s*=\s*\{(.+?)\}\s*;",
            text,
            re.DOTALL,
        )
        if pz_api_block_match:
            api_block = pz_api_block_match.group(1)
            # No fetchNbp / fetchFxRate / getNbpRate style method
            assert not re.search(r"fetchNbp|fetchFxRate|getNbpRate|nbpFetch", api_block, re.IGNORECASE), (
                "A new NBP/FX fetch method was added to PzApi — not allowed (Slice 4 is display-only)"
            )

    def test_warn_fix_fx_rate_uses_existing_edit_exchange_rate_field(self):
        """The edit-exchange-rate testid exists so warn-fix-fx-rate has a target."""
        assert 'data-testid="edit-exchange-rate"' in src(), (
            "data-testid=\"edit-exchange-rate\" must exist on the exchange-rate edit field "
            "so warn-fix-fx-rate has a target to navigate to"
        )

    def test_warn_fix_issue_date_uses_existing_edit_pt_invoice_date_field(self):
        """The edit-pt-invoice-date testid exists so warn-fix-issue-date has a target."""
        assert 'data-testid="edit-pt-invoice-date"' in src(), (
            "data-testid=\"edit-pt-invoice-date\" must already exist (pre-slice) "
            "for warn-fix-issue-date to point to"
        )

    def test_onEditRequest_wired_in_parent_preview_call(self):
        """The parent's ProformaPreviewModal call includes onEditRequest."""
        text = src()
        # The onEditRequest prop must be passed to ProformaPreviewModal
        assert "onEditRequest={() =>" in text or "onEditRequest={" in text, (
            "onEditRequest must be passed to ProformaPreviewModal in the parent render"
        )
        # The handler must call handleEnterEdit (the existing enter-edit-mode function)
        assert "handleEnterEdit()" in text, (
            "onEditRequest handler must call handleEnterEdit() — no new edit-mode path"
        )

    def test_no_editable_origin_input_on_proforma_lines(self):
        """No per-line origin editor exists on the proforma detail (wrong authority)."""
        text = src()
        # No input/select with 'origin' in name/id adjacent to a line-level context
        # — specifically no testid like 'edit-line-origin' or 'line-origin-input'
        bad_patterns = [
            r'data-testid="edit-line-origin"',
            r'data-testid="line-origin-input"',
            r'data-testid="origin-edit-',
            r'onEditField\(\'origin\'',
            r"onEditField\('line_origin",
        ]
        for pat in bad_patterns:
            assert not re.search(pat, text), (
                f"Forbidden per-line origin editor pattern found: {pat!r} — "
                "origin authority is Product Master (Lesson N)"
            )

    def test_missing_origin_advisory_points_to_product_master(self):
        """warn-origin-authority advisory points to /v2/master?entity=products."""
        text = src()
        idx = text.find('data-testid="warn-origin-authority"')
        assert idx != -1, "warn-origin-authority div not found"
        # Within 400 chars of the testid there should be the product master link
        window = text[idx:idx + 400]
        assert "/v2/master" in window, (
            "warn-origin-authority must contain a link to /v2/master (Product Master)"
        )
        assert "Product Master" in window or "product_local.origin_country" in window, (
            "warn-origin-authority must mention Product Master or product_local.origin_country"
        )

    def test_no_new_nbp_api_method_invented(self):
        """No new PzApi method for NBP/FX fetch was introduced."""
        text = src()
        # Search for any method definition containing nbp or fx in its name
        # in the PzApi object literal
        assert not re.search(
            r"(fetchNbp|fetchFxRate|getNbpRate|nbpFetch|fetchExchangeRate)\s*[:=]\s*(function|\(|\s*async)",
            text,
            re.IGNORECASE,
        ), (
            "A new NBP/FX-fetch method was invented in PzApi — forbidden (no backend for this exists)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Slice 5 — blocker dedup guard in ProformaReadinessPanel
# ─────────────────────────────────────────────────────────────────────────────

class TestSlice5BlockerDedup:
    """ProformaReadinessPanel suppresses blockers already shown by ProformaBlockerPanel."""

    def test_dedup_container_testid_exists(self):
        """readiness-panel-blockers-deduped testid wraps the filtered blocker list."""
        assert 'data-testid="readiness-panel-blockers-deduped"' in src(), (
            "Expected data-testid=\"readiness-panel-blockers-deduped\" in "
            "ProformaReadinessPanel — required for test assertion of single-render"
        )

    def test_blockerPanelReasons_computed_in_parent(self):
        """blockerPanelReasons is computed (useMemo) from approveBlockers + postBlockers in parent."""
        text = src()
        # Look for the useMemo definition specifically (not just the first mention)
        idx = text.find("const blockerPanelReasons = React.useMemo")
        assert idx != -1, (
            "const blockerPanelReasons = React.useMemo(...) must exist in the parent "
            "(ProformaDetailPage)"
        )
        # Within 400 chars of the useMemo definition, must reference approveBlockers and postBlockers
        window = text[idx:idx + 400]
        assert "approveBlockers" in window, (
            "blockerPanelReasons useMemo must reference approveBlockers"
        )
        assert "postBlockers" in window, (
            "blockerPanelReasons useMemo must reference postBlockers"
        )

    def test_blockerPanelReasons_passed_to_readiness_panel(self):
        """blockerPanelReasons is passed as a prop to ProformaReadinessPanel."""
        text = src()
        assert "blockerPanelReasons={blockerPanelReasons}" in text, (
            "blockerPanelReasons must be passed as a JSX prop to ProformaReadinessPanel"
        )

    def test_readiness_panel_accepts_blockerPanelReasons_prop(self):
        """ProformaReadinessPanel destructures blockerPanelReasons from its props."""
        text = src()
        # The function signature must include blockerPanelReasons
        fn_match = re.search(
            r"function ProformaReadinessPanel\s*\(\s*\{(.+?)\}\s*\)",
            text,
            re.DOTALL,
        )
        assert fn_match, "ProformaReadinessPanel function signature not found"
        sig = fn_match.group(1)
        assert "blockerPanelReasons" in sig, (
            "ProformaReadinessPanel must destructure blockerPanelReasons from its props"
        )

    def test_readiness_panel_filters_with_shownAbove(self):
        """ProformaReadinessPanel filters blockers using _shownAbove (the dedup guard)."""
        text = src()
        assert "_shownAbove" in text, (
            "_shownAbove local variable must exist in ProformaReadinessPanel for dedup filter"
        )
        # The filter must be applied on readinessPost.blockers
        assert ".filter(b => !_shownAbove.has(b.reason))" in text, (
            "readinessPost.blockers must be filtered with .filter(b => !_shownAbove.has(b.reason))"
        )

    def test_readiness_panel_uses_Set_for_shownAbove(self):
        """_shownAbove is derived as a Set from blockerPanelReasons."""
        text = src()
        assert "instanceof Set" in text, (
            "_shownAbove must check instanceof Set for safe fallback "
            "(in case blockerPanelReasons is undefined)"
        )

    def test_no_blocker_removed_from_gate_evaluation(self):
        """Gating variables (postBlocked, approveBlocked) are unchanged by the dedup."""
        text = src()
        # postBlockers / approveBlockers must NOT be filtered
        # Check that postBlockers and approveBlockers are still derived directly from readiness
        assert "const approveBlockers = (readinessApprove && readinessApprove.blockers) || [];" in text
        assert "const postBlockers    = (readinessPost    && readinessPost.blockers)    || [];" in text
        # Gate variables still use the unfiltered lists
        assert "const approveBlocked  = !!(readinessApprove && readinessApprove.ready === false);" in text
        assert "const postBlocked     = !!(readinessPost    && readinessPost.ready    === false);" in text

    def test_blocker_count_header_unchanged_in_readiness_panel(self):
        """The 'N blocking reason(s)' count in ProformaReadinessPanel header is NOT filtered."""
        text = src()
        # The count line must still reference readinessPost.blockers (full list), not a filtered version
        assert "(readinessPost.blockers || []).length} blocking reason" in text, (
            "Header blocker count must reference readinessPost.blockers (backend authority), "
            "not the filtered list — count represents what the backend reports"
        )

    def test_product_mapping_resolver_rendered_exactly_once(self):
        """ProductMappingResolver is rendered exactly once (not duplicated by dedup changes)."""
        text = src()
        count = text.count("<ProductMappingResolver")
        assert count == 1, (
            f"ProductMappingResolver must appear exactly once in the source; found {count}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Warn-fix action honesty — the edit-link is only active when the draft is
# editable (canEdit), so an "active" button never silently no-ops.
# Root cause fixed: handleEnterEdit() returns early when !canEdit, which made
# the warn-fix buttons appear clickable but do nothing during the transient
# canEdit-false window (post-apply reload) or on non-editable drafts.
# Fix: pass onEditRequest only when canEdit; the buttons already guard on
# `onEditRequest &&`, so they self-suppress (warning still shows as text).
# ─────────────────────────────────────────────────────────────────────────────

class TestWarnFixCanEditGating:
    """The Preview warn-fix edit-links are gated on canEdit (honest + deterministic)."""

    def test_onEditRequest_passed_only_when_canEdit(self):
        """ProformaPreviewModal receives onEditRequest only when canEdit is true."""
        text = src()
        assert "onEditRequest={canEdit ?" in text, (
            "onEditRequest must be gated on canEdit so the warn-fix buttons never "
            "render as active when the draft is not editable"
        )
        # The false branch must yield undefined (which the buttons' `onEditRequest &&`
        # guard treats as 'no active link').
        assert re.search(r"onEditRequest=\{canEdit \?[\s\S]{0,200}\}\s*:\s*undefined\}", text), (
            "When canEdit is false, onEditRequest must be undefined so the buttons self-suppress"
        )

    def test_warn_fix_buttons_guard_on_onEditRequest(self):
        """Both warn-fix buttons only render when onEditRequest is truthy."""
        text = src()
        assert "w.code === 'NO_FX_RATE' && onEditRequest &&" in text, (
            "NO_FX_RATE warn-fix button must guard on onEditRequest (absent when canEdit false)"
        )
        assert "w.code === 'NO_ISSUE_DATE' && onEditRequest &&" in text, (
            "NO_ISSUE_DATE warn-fix button must guard on onEditRequest (absent when canEdit false)"
        )

    def test_warn_fix_click_uses_existing_edit_request_not_a_writer(self):
        """warn-fix onClick invokes onClose()+onEditRequest() — no PzApi write/patch call."""
        text = src()
        # The button onClick must be the established edit-request handoff, not a new write.
        assert text.count("onClick={() => { onClose(); onEditRequest(); }}") >= 2, (
            "Both warn-fix buttons must invoke onClose()+onEditRequest() (existing edit path)"
        )
        # onEditRequest itself must call handleEnterEdit (existing edit mode), not a writer.
        assert re.search(
            r"onEditRequest=\{canEdit \?[\s\S]{0,200}handleEnterEdit\(\);[\s\S]{0,40}\}\s*:\s*undefined\}",
            text,
        ), "onEditRequest must call the existing handleEnterEdit, not create a new writer"
        # Negative: the warn-fix buttons must not call an apply/patch/save writer directly.
        for bad in ("applyCustomerCommercial", "patchDraft", "addServiceCharge", "apply-customer-commercial"):
            assert f"onClick={{() => {{ onClose(); {bad}" not in text, (
                f"warn-fix onClick must not call a writer ({bad})"
            )


# ─────────────────────────────────────────────────────────────────────────────
# VAT/WDT applicability — a derived (non-stored) VAT hint is advisory-only:
# rendered for context but never given a selection checkbox and never submitted.
# ─────────────────────────────────────────────────────────────────────────────

class TestVatWdtAdvisoryRendering:
    """Frontend honours the backend `applicable:false` contract (no checkbox)."""

    def test_initial_checked_skips_non_applicable(self):
        text = src()
        assert "if (f.applicable === false) return;" in text, (
            "_initialChecked must never default-select a non-applicable (advisory) field"
        )

    def test_row_checkbox_gated_on_applicable(self):
        text = src()
        assert "!!applyKey && f.applicable !== false && (f.source === 'suggested' || f.source === 'conflict')" in text, (
            "the row 'applicable' flag must exclude fields the backend marks applicable:false"
        )

    def test_advisory_source_badge_exists(self):
        text = src()
        assert "advisory:" in text and "resolved at posting" in text.lower(), (
            "an 'advisory' source badge must exist so a derived VAT hint reads as advisory, not 'suggested'"
        )
