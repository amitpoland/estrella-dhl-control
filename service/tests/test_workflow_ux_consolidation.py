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
