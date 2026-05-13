"""
test_workflow_ux_consolidation.py — UX consolidation (ux/proforma-workflow-consolidation).

Source-grep tests for the Section A / Section B restructure of OperatorWorkflowCard
introduced in the ux/proforma-workflow-consolidation task.

Coverage:
  • Two parallel sections (A + B) present with correct testids
  • Independence note banner rendered before both sections
  • ProformaDraftPanel lives in Section A (above the PZ pipeline)
  • ProformaReadinessCard collapsed inside a <details> in Section A
  • sectionGroupHeader helper defined within the component
  • ExecutePZGate debug block wrapped in collapsible <details>
  • Human-readable reason strings in ExecutePZGate (no raw env-flag names)
  • Human-readable product / customer flag text (no raw env-flag names)
  • Section B contains the pipeline and all 7 sectionShell calls
"""
from __future__ import annotations

import re
from pathlib import Path

DASHBOARD_HTML = (Path(__file__).resolve().parents[1]
                  / "app" / "static" / "dashboard.html")


def _html() -> str:
    return DASHBOARD_HTML.read_text(encoding="utf-8")


def _component_body() -> str:
    h = _html()
    start = h.index("function OperatorWorkflowCard(")
    end   = h.index("\nfunction CNHSNDecisionPanel(", start)
    return h[start:end]


def _execute_gate_body() -> str:
    h = _html()
    start = h.index("function ExecutePZGate(")
    end   = h.index("\nfunction ", start + 50)
    return h[start:end]


# ── Independence note ──────────────────────────────────────────────────────

class TestIndependenceNote:
    def test_independence_note_present(self):
        """Operator-facing banner stating the two workflows are independent."""
        body = _component_body()
        assert 'data-testid="workflow-independence-note"' in body, \
            "independence note banner must be present in OperatorWorkflowCard"

    def test_independence_note_before_section_a(self):
        """Note must appear BEFORE Section A."""
        body = _component_body()
        idx_note    = body.index('data-testid="workflow-independence-note"')
        idx_section = body.index('data-testid="workflow-section-a"')
        assert idx_note < idx_section, \
            "independence note must appear before workflow-section-a"

    def test_independence_note_copy_mentions_parallel(self):
        """Banner text must make it clear these are parallel, not sequential."""
        body = _component_body()
        idx = body.index('data-testid="workflow-independence-note"')
        window = body[idx:idx + 400]
        assert "parallel" in window.lower() or "independent" in window.lower(), \
            "independence note must mention parallel or independent workflows"


# ── Section A ─────────────────────────────────────────────────────────────

class TestSectionA:
    def test_section_a_wrapper_present(self):
        body = _component_body()
        assert 'data-testid="workflow-section-a"' in body

    def test_section_a_header_label(self):
        """Section A group header must identify it as the Proforma section."""
        body = _component_body()
        idx = body.index('data-testid="workflow-section-a"')
        window = body[idx:idx + 400]
        assert "Proforma" in window, \
            "Section A header must reference Proforma"

    def test_proforma_draft_panel_inside_section_a(self):
        """ProformaDraftPanel must be mounted inside Section A."""
        body = _component_body()
        idx_a     = body.index('data-testid="workflow-section-a"')
        idx_panel = body.index('<ProformaDraftPanel batchId={batchId}', idx_a)
        # Must come before Section B
        idx_b     = body.index('data-testid="workflow-section-b"')
        assert idx_a < idx_panel < idx_b, \
            "ProformaDraftPanel must be inside Section A (before Section B)"

    def test_proforma_draft_panel_before_pipeline(self):
        """ProformaDraftPanel now precedes the PZ pipeline in the DOM."""
        body = _component_body()
        idx_panel    = body.index('<ProformaDraftPanel batchId={batchId}')
        idx_pipeline = body.index('data-testid="workflow-pipeline"')
        assert idx_panel < idx_pipeline, \
            "ProformaDraftPanel must appear before the PZ pipeline bar"

    def test_proforma_readiness_card_in_details_toggle(self):
        """ProformaReadinessCard must be wrapped in a collapsible <details>."""
        body = _component_body()
        idx_toggle = body.index('data-testid="workflow-details-toggle"')
        # ProformaReadinessCard must appear after the toggle
        idx_card   = body.index('<ProformaReadinessCard batchId={batchId}', idx_toggle)
        # And before Section B
        idx_b      = body.index('data-testid="workflow-section-b"')
        assert idx_toggle < idx_card < idx_b, \
            "ProformaReadinessCard must be inside the workflow-details-toggle <details>"

    def test_details_toggle_is_details_element(self):
        """workflow-details-toggle must be a <details> HTML element (collapsed by default)."""
        body = _component_body()
        idx = body.index('data-testid="workflow-details-toggle"')
        # Walk backwards up to 40 chars to find the opening tag
        before = body[max(0, idx - 40):idx]
        assert "<details" in before, \
            "workflow-details-toggle must be on a <details> element (collapsible)"


# ── Section B ─────────────────────────────────────────────────────────────

class TestSectionB:
    def test_section_b_wrapper_present(self):
        body = _component_body()
        assert 'data-testid="workflow-section-b"' in body

    def test_section_b_header_label(self):
        """Section B group header must identify it as PZ Generation / Customs."""
        body = _component_body()
        idx = body.index('data-testid="workflow-section-b"')
        window = body[idx:idx + 400]
        assert "PZ" in window, \
            "Section B header must reference PZ"

    def test_pipeline_inside_section_b(self):
        """The stage pipeline bar must live inside Section B."""
        body = _component_body()
        idx_b        = body.index('data-testid="workflow-section-b"')
        idx_pipeline = body.index('data-testid="workflow-pipeline"', idx_b)
        assert idx_b < idx_pipeline, \
            "workflow-pipeline must be inside Section B"

    def test_all_seven_section_shells_inside_section_b(self):
        """All 7 accordion section shells must appear inside Section B."""
        body = _component_body()
        idx_b = body.index('data-testid="workflow-section-b"')
        b_body = body[idx_b:]
        for k in ("evidence", "classification", "products",
                  "customers", "warehouse", "preview", "execute"):
            assert f"sectionShell('{k}'," in b_body, \
                f"sectionShell('{k}',...) must appear inside Section B"


# ── sectionGroupHeader helper ──────────────────────────────────────────────

class TestSectionGroupHeader:
    def test_helper_defined_in_component(self):
        """sectionGroupHeader must be defined inside OperatorWorkflowCard."""
        body = _component_body()
        assert "const sectionGroupHeader" in body, \
            "sectionGroupHeader helper must be defined in OperatorWorkflowCard"

    def test_helper_accepts_color_param(self):
        """Helper must accept a color parameter to distinguish A vs B styling."""
        body = _component_body()
        idx = body.index("const sectionGroupHeader")
        window = body[idx:idx + 200]
        assert "color" in window, \
            "sectionGroupHeader must accept a color parameter"

    def test_helper_used_for_both_sections(self):
        """sectionGroupHeader must be called for both Section A and B."""
        body = _component_body()
        calls = re.findall(r"sectionGroupHeader\(", body)
        assert len(calls) >= 2, \
            f"sectionGroupHeader must be called at least twice (found {len(calls)})"


# ── ExecutePZGate human-readable reasons ──────────────────────────────────

class TestExecutePZGateReasons:
    def test_no_raw_env_flag_name_in_reasons(self):
        """ExecutePZGate must NOT expose raw env-flag names to operators."""
        gate = _execute_gate_body()
        forbidden = [
            "WFIRMA_CREATE_PZ_ALLOWED",
            "pz_preview.ready=false",
            "would_create_pz=false",
        ]
        for f in forbidden:
            assert f not in gate, \
                f"ExecutePZGate must not expose raw technical string '{f}' in reasons"

    def test_human_readable_flag_off_reason(self):
        """Admin-setting reason must be human-readable."""
        gate = _execute_gate_body()
        assert "disabled (admin" in gate or "not enabled (admin" in gate, \
            "flag-off reason must say 'disabled (admin setting)' or similar"

    def test_human_readable_preview_not_ready_reason(self):
        """Preview-not-ready reason must guide operator to fix issues in earlier steps."""
        gate = _execute_gate_body()
        assert "resolve" in gate.lower() or "steps" in gate.lower(), \
            "preview-not-ready reason must guide operator to resolve issues"

    def test_debug_block_is_collapsible_details(self):
        """Execute PZ debug state block must be wrapped in <details> (hidden by default)."""
        gate = _execute_gate_body()
        idx_summary = gate.index('data-testid="execute-pz-summary"')
        before = gate[max(0, idx_summary - 40):idx_summary]
        assert "<details" in before, \
            "execute-pz-summary must be on a <details> element so debug info is hidden by default"

    def test_debug_block_has_summary_label(self):
        """Debug <details> must have a <summary> label so operators know it's debug info."""
        gate = _execute_gate_body()
        idx = gate.index('data-testid="execute-pz-summary"')
        window = gate[idx:idx + 300]
        assert "<summary" in window, \
            "execute-pz-summary <details> must contain a <summary> element"
        assert "debug" in window.lower() or "technical" in window.lower(), \
            "<summary> label must say 'debug' or 'technical'"


# ── Human-readable products / customers flag text ─────────────────────────

class TestHumanReadableFlagText:
    def test_products_body_no_raw_flag_name(self):
        """Products section must not show WFIRMA_CREATE_PRODUCT_ALLOWED verbatim."""
        body = _component_body()
        assert "WFIRMA_CREATE_PRODUCT_ALLOWED" not in body, \
            "WFIRMA_CREATE_PRODUCT_ALLOWED must not appear in the component (use human text)"

    def test_customers_body_no_raw_flag_name(self):
        """Customers section must not show WFIRMA_CREATE_CUSTOMER_ALLOWED verbatim."""
        body = _component_body()
        assert "WFIRMA_CREATE_CUSTOMER_ALLOWED" not in body, \
            "WFIRMA_CREATE_CUSTOMER_ALLOWED must not appear in the component (use human text)"

    def test_products_admin_contact_text(self):
        """When auto-register is off, message should suggest contacting admin."""
        body = _component_body()
        assert "contact your admin" in body, \
            "When product auto-register is off, message must say 'contact your admin'"

    def test_customers_admin_contact_text(self):
        """When auto-create is off, message should suggest contacting admin."""
        body = _component_body()
        # The customers body shares the 'contact your admin' text
        count = body.count("contact your admin")
        assert count >= 2, \
            f"'contact your admin' must appear for both products and customers (found {count})"


# ── DOM ordering invariant: Section A before Section B ────────────────────

class TestDomOrder:
    def test_section_a_before_section_b(self):
        body = _component_body()
        idx_a = body.index('data-testid="workflow-section-a"')
        idx_b = body.index('data-testid="workflow-section-b"')
        assert idx_a < idx_b, \
            "Section A (Proforma) must appear before Section B (PZ) in the DOM"

    def test_independence_note_before_section_b(self):
        body = _component_body()
        idx_note = body.index('data-testid="workflow-independence-note"')
        idx_b    = body.index('data-testid="workflow-section-b"')
        assert idx_note < idx_b, \
            "independence note must appear before Section B"


# ── Phase 3: STAGE_ORDER display label normalization ─────────────────────────

class TestStageOrderLabels:
    def test_evidence_label_renamed_to_customs_docs(self):
        """Evidence stage now shows 'Customs docs' to non-technical operators."""
        body = _component_body()
        assert "'Customs docs'" in body, \
            "evidence stage display label must be 'Customs docs'"
        assert "'Evidence'" not in body, \
            "old 'Evidence' display label must be replaced"

    def test_classification_label_normalized(self):
        """Classification stage no longer shows raw 'CN/HSN' abbreviation."""
        body = _component_body()
        assert "'Classification'" in body, \
            "classification stage display label must be 'Classification'"

    def test_preview_label_renamed_to_review(self):
        """Preview stage now shows 'Review' to match operator language."""
        body = _component_body()
        assert "'Review'" in body, \
            "preview stage display label must be 'Review'"
        assert "'Preview'" not in body, \
            "old 'Preview' display label must be replaced"

    def test_execute_label_renamed_to_post(self):
        """Execute stage now shows 'Post' to match accounting terminology."""
        body = _component_body()
        assert "'Post'" in body, \
            "execute stage display label must be 'Post'"
        assert "'Execute'" not in body, \
            "old 'Execute' display label must be replaced"

    def test_stage_keys_unchanged(self):
        """STAGE_ORDER keys (first elements) must not change — they are test-locked."""
        body = _component_body()
        for key in ("'evidence'", "'classification'", "'products'",
                    "'customers'", "'warehouse'", "'preview'", "'execute'"):
            assert key in body, f"STAGE_ORDER key {key} must not be renamed"


# ── Phase 3: ExecutePZGate hierarchy (reasons before status chip) ─────────────

class TestExecutePZGateHierarchy:
    def test_reasons_appear_before_status_chip(self):
        """Blocked reasons must appear ABOVE the status chip so operator sees
        what to fix before seeing the 'Blocked' label."""
        gate = _execute_gate_body()
        idx_reasons = gate.index('data-testid="execute-pz-reasons"')
        idx_chip    = gate.index('data-testid="execute-pz-status-chip"')
        assert idx_reasons < idx_chip, \
            "execute-pz-reasons must appear before execute-pz-status-chip"

    def test_whats_needed_header_present(self):
        """Reason chip block must have a 'What's needed:' header label."""
        gate = _execute_gate_body()
        assert "What's needed:" in gate, \
            "execute-pz-reasons block must contain \"What's needed:\" header"

    def test_status_chip_ready_to_post(self):
        """Enabled status chip must say 'Ready to post' (not 'Ready to execute')."""
        gate = _execute_gate_body()
        assert "Ready to post" in gate, \
            "enabled status chip must say 'Ready to post'"
        assert "Ready to execute" not in gate, \
            "old 'Ready to execute' label must be replaced"

    def test_status_chip_blocked_label(self):
        """Locked status chip must say 'Blocked — resolve items above'."""
        gate = _execute_gate_body()
        assert "Blocked — resolve items above" in gate, \
            "locked chip must say 'Blocked — resolve items above'"
        assert "'Locked'" not in gate, \
            "bare 'Locked' chip label must be replaced"

    def test_gate_heading_updated(self):
        """Gate heading must say 'Create goods receipt in wFirma'."""
        gate = _execute_gate_body()
        assert "Create goods receipt in wFirma" in gate, \
            "gate heading must say 'Create goods receipt in wFirma'"

    def test_refresh_button_label_simplified(self):
        """Refresh button must say 'Refresh', not 'Refresh preview'."""
        gate = _execute_gate_body()
        assert ">Refresh<" in gate or "Refresh\n" in gate or ">Refresh<" in gate, \
            "refresh button text must be 'Refresh'"
        assert "Refresh preview" not in gate, \
            "old 'Refresh preview' button text must be replaced"

    def test_execute_button_label_updated(self):
        """Execute button must say 'Create goods receipt in wFirma'."""
        gate = _execute_gate_body()
        assert "Create goods receipt in wFirma" in gate, \
            "execute button must say 'Create goods receipt in wFirma'"
        assert "'Execute PZ in wFirma'" not in gate and '"Execute PZ in wFirma"' not in gate, \
            "old 'Execute PZ in wFirma' button text must be replaced"


# ── Phase 2B: Section B completion banner ────────────────────────────────────

class TestCompletionBanner:
    def test_completion_banner_present_in_section_b(self):
        """Section B must contain a completion banner triggered when all stages are green."""
        body = _component_body()
        idx_b = body.index('data-testid="workflow-section-b"')
        b_body = body[idx_b:]
        assert 'data-testid="workflow-completion-banner"' in b_body, \
            "workflow-completion-banner must be present inside Section B"

    def test_completion_banner_before_pipeline(self):
        """Completion banner must appear before the pipeline bar."""
        body = _component_body()
        idx_banner   = body.index('data-testid="workflow-completion-banner"')
        idx_pipeline = body.index('data-testid="workflow-pipeline"')
        assert idx_banner < idx_pipeline, \
            "workflow-completion-banner must appear before workflow-pipeline"

    def test_completion_banner_copy(self):
        """Banner copy must mention 'accounting' to map to operator vocabulary."""
        body = _component_body()
        idx = body.index('data-testid="workflow-completion-banner"')
        window = body[idx:idx + 300]
        assert "accounting" in window.lower(), \
            "completion banner must reference 'accounting'"

    def test_completion_banner_checks_all_seven_stages(self):
        """allStagesDone predicate must reference all 7 stage keys."""
        body = _component_body()
        for stage in ("evidence", "classification", "products",
                      "customers", "warehouse", "preview", "execute"):
            assert f"stages.{stage}.color" in body, \
                f"completion banner must check stages.{stage}.color"


# ── Phase 3: ProformaDraftPanel language normalization ───────────────────────

def _proforma_draft_panel_body() -> str:
    h = _html()
    start = h.index("function ProformaDraftPanel(")
    end   = h.index("\nfunction ", start + 50)
    return h[start:end]


class TestProformaDraftPanelLanguage:
    def test_empty_state_updated(self):
        """Empty state must not reference 'sales packing intake'."""
        body = _proforma_draft_panel_body()
        assert "No proforma drafts yet" in body, \
            "empty state must say 'No proforma drafts yet'"
        assert "sales packing intake" not in body, \
            "old 'sales packing intake' empty state message must be replaced"

    def test_state_chip_labels_map_defined(self):
        """Human-readable state chip label map must be defined."""
        h = _html()
        assert "_DRAFT_STATE_LABELS" in h, \
            "_DRAFT_STATE_LABELS map must be defined"

    def test_post_failed_chip_label(self):
        """post_failed state chip must show 'Send failed'."""
        h = _html()
        assert "Send failed" in h, \
            "post_failed chip must label as 'Send failed'"

    def test_posted_chip_label(self):
        """posted state chip must show 'Sent to accounting'."""
        h = _html()
        assert "Sent to accounting" in h, \
            "posted chip must label as 'Sent to accounting'"

    def test_posting_chip_label(self):
        """posting state chip must show 'Sending…'."""
        h = _html()
        assert "Sending…" in h or "Sending..." in h or "Sending…" in h, \
            "posting chip must label as 'Sending…'"

    def test_post_button_label_updated(self):
        """Post button must say 'Send to accounting' not '⚠ Post to wFirma'."""
        body = _proforma_draft_panel_body()
        assert "Send to accounting" in body, \
            "post button must say 'Send to accounting (wFirma)'"
        assert "⚠ Post to wFirma" not in body, \
            "old '⚠ Post to wFirma' button label must be replaced"

    def test_reset_button_label_updated(self):
        """Reset button visible label must say 'Reload items from warehouse data'."""
        h = _html()
        # Button testid btn-draft-reset must carry the new operator-facing label.
        idx = h.find('data-testid="btn-draft-reset"')
        assert idx > 0, "btn-draft-reset must exist"
        # Search forward for the button label text
        window = h[idx:idx + 200]
        assert "Reload items from warehouse data" in window, \
            "btn-draft-reset visible label must say 'Reload items from warehouse data'"


# ── Phase 3: Section header language ─────────────────────────────────────────

class TestSectionHeaderLanguage:
    def test_classification_section_header(self):
        """Classification section must say 'Tariff classification'."""
        body = _component_body()
        assert "'2. Tariff classification'" in body or "2. Tariff classification" in body, \
            "section 2 header must say 'Tariff classification'"

    def test_products_section_header(self):
        """Products section must say 'Products registered in accounting'."""
        body = _component_body()
        assert "Products registered in accounting" in body, \
            "section 3 header must say 'Products registered in accounting'"

    def test_customers_section_header(self):
        """Customers section must say 'Customers matched to orders'."""
        body = _component_body()
        assert "Customers matched to orders" in body, \
            "section 4 header must say 'Customers matched to orders'"

    def test_preview_section_header(self):
        """Preview section must say 'Goods receipt ready to post'."""
        body = _component_body()
        assert "Goods receipt ready to post" in body, \
            "section 6 header must say 'Goods receipt ready to post'"

    def test_execute_section_header(self):
        """Execute section must say 'Create goods receipt in wFirma'."""
        body = _component_body()
        assert "Create goods receipt in wFirma" in body, \
            "section 7 header must say 'Create goods receipt in wFirma'"
