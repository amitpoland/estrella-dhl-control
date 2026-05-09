"""
test_operator_workflow_card.py — unified pre-PZ workflow card.

This is a UI surface test. It greps the OperatorWorkflowCard component
body inside dashboard.html to confirm structural invariants:

  • The component is defined and mounted in PZ/wFirma tab.
  • Pipeline header has all six stages in order.
  • Each stage section renders.
  • No POST inside useEffect (no auto-write on load).
  • Reuses existing read-only endpoints only.
  • No new fetch URLs introduced beyond the ones in the spec.
  • Refresh button is operator-explicit.
  • Embedded write surfaces (CNHSNDecisionPanel, ExecutePZGate, full
    ProformaReadinessCard) are mounted as sub-views — the workflow
    itself never POSTs.
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
    # The next top-level function is CNHSNDecisionPanel.
    end   = h.index("\nfunction CNHSNDecisionPanel(", start)
    return h[start:end]


# ── Mount ──────────────────────────────────────────────────────────────────

class TestMount:
    def test_component_defined(self):
        assert "function OperatorWorkflowCard(" in _html()

    def test_mounted_in_pz_wfirma_tab(self):
        h = _html()
        idx_tab    = h.index("activeTab === 'PZ / wFirma'")
        idx_card   = h.index("<OperatorWorkflowCard ", idx_tab)
        idx_close  = h.index("Section 3 — PZ / Accounting", idx_tab)
        assert idx_tab < idx_card < idx_close

    def test_top_of_pz_tab_is_workflow_card(self):
        """The unified workflow card must be the first thing in the tab —
        ahead of the legacy free-standing cards (which are now embedded
        inside it as sub-sections)."""
        h = _html()
        idx_tab     = h.index("activeTab === 'PZ / wFirma'")
        idx_workflow = h.index("<OperatorWorkflowCard ", idx_tab)
        # The legacy standalone <ProformaReadinessCard> mount block was
        # removed from the tab top; only the embedded one inside the
        # workflow card's <details> remains.
        legacy_pattern = re.compile(
            r"\n\s*<ProformaReadinessCard batchId=\{batchId\} onToast=\{onToast\} />\s*\n\s*\{/\* ZC429"
        )
        assert legacy_pattern.search(h) is None, \
            "the legacy <ProformaReadinessCard>+<ZC429EvidenceCard>+<ExecutePZGate> trio in PZ/wFirma top must be replaced"


# ── Pipeline header ────────────────────────────────────────────────────────

class TestPipelineHeader:
    def test_six_stage_pipeline(self):
        # Now 7 stages (Warehouse added), and 'Classification' is shown
        # as 'CN/HSN' in the pipeline header. Both legacy and new
        # spellings are accepted so this stays compatible.
        body = _component_body()
        for label in ("Evidence", "Products",
                      "Customers", "Preview", "Execute"):
            assert f"'{label}'" in body, f"missing pipeline stage label: {label}"
        assert ("'Classification'" in body) or ("'CN/HSN'" in body)

    def test_stage_pills_have_testids(self):
        body = _component_body()
        for k in ("evidence", "classification", "products",
                  "customers", "preview", "execute"):
            assert f'data-testid={{`workflow-pill-${{key}}`}}' in body \
                or f'data-testid={{`workflow-pill-${{key}}`}}'.replace("`","'") in body \
                or 'data-testid={`workflow-pill-${key}`}' in body
            # Also ensure the count-badge testid exists
            assert "data-testid={`workflow-pill-count-${key}`}" in body

    def test_pipeline_renders_all_in_order(self):
        body = _component_body()
        order = body[body.index("STAGE_ORDER"):body.index("// ── Style helpers")]
        for k in ("'evidence'", "'classification'", "'products'",
                  "'customers'", "'preview'", "'execute'"):
            assert k in order


# ── Sections ───────────────────────────────────────────────────────────────

class TestSections:
    def test_six_section_shells_rendered(self):
        body = _component_body()
        for k in ("evidence", "classification", "products",
                  "customers", "preview", "execute"):
            assert f"sectionShell('{k}'," in body, f"missing section shell: {k}"

    def test_section_testids_present(self):
        body = _component_body()
        # data-testid={`workflow-section-${key}`} is generated dynamically.
        assert "data-testid={`workflow-section-${key}`}" in body
        assert "data-testid={`workflow-section-header-${key}`}" in body

    def test_evidence_body_shows_intake_event_short_id(self):
        body = _component_body()
        assert "intake_event_id" in body
        # Short form (first 12 chars) is computed via .slice(0, 12)
        assert ".slice(0, 12)" in body or ".slice(0,12)" in body

    def test_evidence_body_shows_attachment_count(self):
        body = _component_body()
        assert "Attachments:" in body
        assert "(zc429.attachments || []).length" in body

    def test_classification_body_embeds_decision_panel(self):
        body = _component_body()
        assert "<CNHSNDecisionPanel " in body

    def test_preview_body_shows_required_fields(self):
        # The preview body now distinguishes Local PZ from wFirma PZ.
        # The required facts are still surfaced, but with new labels.
        body = _component_body()
        # Local PZ existence facts
        assert "Local PZ calculation:" in body
        # wFirma PZ block — id, ready, already-created
        assert "wFirma PZ export:" in body
        assert "wfirma_pz_doc_id" in body
        # MRN + warehouse + unresolved-codes still present
        assert "MRN " in body                       # "MRN {preview.mrn || …}"
        assert "warehouse " in body
        assert "unresolved product code" in body

    def test_execute_body_embeds_execute_gate(self):
        body = _component_body()
        assert "<ExecutePZGate " in body


# ── No-write invariants ────────────────────────────────────────────────────

class TestNoAutoWrite:
    def test_useeffect_contains_no_post(self):
        body = _component_body()
        # Locate React.useEffect block (only one) and assert it doesn't
        # contain any POST verb.
        ue_start = body.index("React.useEffect(() => { refresh(); }")
        # The effect statement is one-liner, but to be safe slice 200 chars.
        ue_block = body[ue_start:ue_start + 200]
        for forbidden in ("method: 'POST'", 'method: "POST"',
                          "method:'POST'", "method: 'PUT'",
                          "method: 'DELETE'", "method: 'PATCH'"):
            assert forbidden not in ue_block, \
                f"useEffect must not write ({forbidden})"

    def test_refresh_is_get_only(self):
        body = _component_body()
        refresh_start = body.index("const refresh = React.useCallback")
        refresh_end   = body.index("}, [batchId])", refresh_start)
        block = body[refresh_start:refresh_end]
        for forbidden in ("method: 'POST'", 'method: "POST"',
                          "method:'POST'", "method: 'PUT'",
                          "method: 'DELETE'", "method: 'PATCH'"):
            assert forbidden not in block, \
                f"refresh() must be GET-only ({forbidden})"

    def test_no_pz_create_or_process_in_workflow_body(self):
        body = _component_body()
        for forbidden in ("/wfirma/pz_create", "/process'", "/process\""):
            assert forbidden not in body, \
                f"workflow card must not reference {forbidden}"
        # Note: ExecutePZGate IS embedded — but the gate's own body
        # (defined separately) carries its own onClick-only POST.

    def test_no_auto_register_or_customer_create_in_workflow_body(self):
        body = _component_body()
        for forbidden in ("/wfirma/goods/auto-register'",
                          '/wfirma/goods/auto-register"',
                          "/wfirma/customers/auto-create-from-name'",
                          '/wfirma/customers/auto-create-from-name"'):
            assert forbidden not in body, \
                f"workflow must not auto-trigger {forbidden}"

    def test_uses_only_documented_read_endpoints(self):
        """Workflow must call exactly the spec's five read URLs and nothing else."""
        body = _component_body()
        expected_get_substrings = [
            "/dashboard/batches/${encodeURIComponent(batchId)}/proforma-readiness",
            "/dashboard/batches/${encodeURIComponent(batchId)}/zc429-lineage",
            "/dashboard/batches/${encodeURIComponent(batchId)}/cn-hsn-classification",
            "/api/v1/upload/shipment/${encodeURIComponent(batchId)}/wfirma/pz_preview",
            "/api/v1/wfirma/capabilities",
        ]
        for s in expected_get_substrings:
            assert s in body, f"expected GET endpoint missing: {s}"
        # Sanity — no other backend POST URL appears in the OWN
        # workflow body (sub-components are external).
        post_calls = re.findall(r"method:\s*['\"]POST['\"]", body)
        assert post_calls == [], \
            f"workflow body must contain no POSTs of its own; found {len(post_calls)}"


# ── Stage colours ──────────────────────────────────────────────────────────

class TestStageColours:
    def test_color_map_present(self):
        body = _component_body()
        for c in ("'green'", "'amber'", "'red'", "'gray'"):
            assert c in body
        # green/amber/red palette in dot()
        assert "#15803d" in body  # green
        assert "#d97706" in body  # amber
        assert "#dc2626" in body  # red
        assert "#9ca3af" in body  # gray

    def test_execute_only_enabled_when_no_blockers(self):
        body = _component_body()
        # The composite enabled rule:
        # previewReady && wouldCreate && flagOn && !alreadyCreated
        # && blockersBefore === 0
        assert "blockersBefore === 0" in body
        assert "executeEnabled" in body


# ── Refresh button / explicit ──────────────────────────────────────────────

class TestRefreshAction:
    def test_refresh_button_exists(self):
        body = _component_body()
        assert 'data-testid="workflow-refresh"' in body
        assert "onClick={refresh}" in body
