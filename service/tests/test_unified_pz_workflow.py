"""
test_unified_pz_workflow.py — single-source-of-truth PZ/wFirma tab.

Verifies that:
  • The unified workflow card renders all 7 stages in order.
  • Evidence shows SAD/MRN and ZC429 lineage as two separate facts.
  • CN/HSN accepted state renders the compact green summary, not the
    big warning panel.
  • Warehouse stage uses /api/v1/batch/{id}/readiness as the source.
  • Preview distinguishes local PZ calculation from wFirma PZ export.
  • Execute disabled when pz_preview returns 422 or when any blocker
    remains.
  • Legacy Section 3 + reservation preview are wrapped in <details>
    so they cannot contradict the unified view.
  • No POST inside useEffect; no auto-trigger of pz_create / process /
    auto-register / auto-create-from-name.
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


# ── Single source of truth in PZ/wFirma tab ────────────────────────────────

class TestSingleSource:
    def test_workflow_card_at_top_of_pz_tab(self):
        h = _html()
        idx_tab      = h.index("activeTab === 'PZ / wFirma'")
        idx_workflow = h.index("<OperatorWorkflowCard ", idx_tab)
        idx_legacy   = h.index('data-testid="legacy-pz-details"', idx_tab)
        assert idx_tab < idx_workflow < idx_legacy

    def test_legacy_section3_and_reservation_wrapped_in_details(self):
        h = _html()
        # Both legacy panels must live inside <details> nodes.
        assert 'data-testid="legacy-pz-details"' in h
        assert 'data-testid="legacy-reservation-details"' in h
        # Each must have a <summary> that names them as legacy.
        assert 'data-testid="legacy-pz-summary"' in h
        assert 'data-testid="legacy-reservation-summary"' in h
        # The summary copy explains they're not the canonical surface.
        assert "Advanced / legacy reservation" in h


# ── Pipeline header ────────────────────────────────────────────────────────

class TestPipelineHeader:
    def test_seven_stage_pipeline(self):
        body = _component_body()
        for label in ("Evidence", "CN/HSN", "Products", "Customers",
                      "Warehouse", "Preview", "Execute"):
            assert f"'{label}'" in body, f"missing pipeline label: {label}"

    def test_warehouse_stage_added(self):
        body = _component_body()
        assert "['warehouse'," in body
        assert "['warehouse',      'Warehouse']" in body


# ── Evidence (split) ───────────────────────────────────────────────────────

class TestEvidenceSplit:
    def test_evidence_shows_two_facts(self):
        body = _component_body()
        assert 'data-testid="workflow-evidence-sad"' in body
        assert 'data-testid="workflow-evidence-zc"'  in body
        assert "SAD / MRN present:" in body
        assert "ZC429 lineage present:" in body

    def test_amber_note_when_sad_only(self):
        body = _component_body()
        assert 'data-testid="workflow-evidence-amber-note"' in body
        assert "Legacy SAD/MRN present" in body
        assert "DHL ZC429 email attachments not yet ingested" in body

    def test_evidence_color_logic(self):
        body = _component_body()
        # green only when both facts hold
        assert "(sadPresent && zcPresent) ? 'green'" in body


# ── Classification compact ─────────────────────────────────────────────────

class TestClassificationCompact:
    def test_accepted_renders_compact(self):
        body = _component_body()
        assert 'data-testid="workflow-classification-accepted"' in body
        # Only renders compact summary when decision.approved
        assert "if (dec && dec.approved)" in body

    def test_falls_back_to_full_panel_when_not_accepted(self):
        body = _component_body()
        assert "<CNHSNDecisionPanel " in body


# ── Customer source unification ────────────────────────────────────────────

class TestCustomerSource:
    def test_customer_pulled_from_proforma_readiness_only(self):
        body = _component_body()
        # The 'customers' branch must use proforma.customers — not a
        # separate reservation-preview source.
        assert "proforma && proforma.customers" in body
        # And the workflow card must not call any reservation-preview
        # endpoint of its own.
        for forbidden in ("/wfirma/reservations/preview",
                          "wfirma_reservation_preview",
                          "/api/v1/wfirma/reservations"):
            assert forbidden not in body, \
                f"workflow must not consult legacy reservation preview ({forbidden})"


# ── Warehouse stage ────────────────────────────────────────────────────────

class TestWarehouseStage:
    def test_warehouse_section_present(self):
        body = _component_body()
        assert 'data-testid="workflow-warehouse-body"' in body
        assert 'data-testid="workflow-warehouse-line"' in body
        assert 'data-testid="workflow-sales-line"' in body

    def test_warehouse_uses_batch_readiness_endpoint(self):
        body = _component_body()
        assert "/api/v1/batch/${encodeURIComponent(batchId)}/readiness" in body

    def test_warehouse_blocker_message_surfaced(self):
        body = _component_body()
        assert "wh.message" in body or "wh && wh.message" in body
        assert "sales.message" in body or "sales && sales.message" in body


# ── Preview / local-vs-wFirma split ────────────────────────────────────────

class TestPreviewSplit:
    def test_local_pz_distinct_from_wfirma_pz(self):
        body = _component_body()
        assert "Local PZ calculation:" in body
        assert "wFirma PZ export:" in body
        assert 'data-testid="workflow-preview-local"'  in body
        assert 'data-testid="workflow-preview-wfirma"' in body

    def test_local_pz_exists_uses_batch_detail_files_pdf(self):
        body = _component_body()
        assert "batchDet.files" in body
        assert "batchDet.files.pdf" in body
        assert "batchDet.files.pdf.exists" in body

    def test_preview_guard_message_rendered_when_422(self):
        body = _component_body()
        assert 'data-testid="workflow-preview-guard"' in body
        assert "preview.detail" in body
        # Distinct label when guard blocks the preview
        assert "wFirma PZ preview blocked" in body


# ── Execute gating ─────────────────────────────────────────────────────────

class TestExecuteGate:
    def test_execute_requires_no_blockers(self):
        body = _component_body()
        # The composite enabled rule includes blockersBefore === 0
        assert "blockersBefore === 0" in body
        # SAD presence is required
        assert "(!sadPresent ? 1 : 0)" in body
        # Warehouse readiness counts as a blocker
        assert "(!whReady ? 1 : 0)" in body

    def test_execute_disabled_when_preview_errored(self):
        """When preview.detail (HTTP 422) is present, executeEnabled is
        false because previewReady is false."""
        body = _component_body()
        # previewReady is computed from preview.ready only — when
        # preview.detail exists, preview.ready is undefined → false.
        assert "const previewReady   = !!(preview && preview.ready);" in body
        assert "executeEnabled = previewReady" in body


# ── No-write invariants ────────────────────────────────────────────────────

class TestNoAutoWrite:
    def test_useeffect_contains_no_post(self):
        body = _component_body()
        ue_start = body.index("React.useEffect(() => { refresh(); }")
        ue_block = body[ue_start:ue_start + 200]
        for forbidden in ("method: 'POST'", 'method: "POST"',
                          "method: 'PUT'", "method: 'DELETE'", "method: 'PATCH'"):
            assert forbidden not in ue_block

    def test_no_pz_create_or_process_in_workflow_body(self):
        body = _component_body()
        for forbidden in ("/wfirma/pz_create", "/process'", "/process\""):
            assert forbidden not in body, \
                f"workflow must not reference {forbidden}"

    def test_no_auto_register_or_auto_create_in_workflow_body(self):
        body = _component_body()
        for forbidden in ("/wfirma/goods/auto-register'",
                          '/wfirma/goods/auto-register"',
                          "/wfirma/customers/auto-create-from-name'",
                          '/wfirma/customers/auto-create-from-name"'):
            assert forbidden not in body

    def test_only_documented_read_endpoints(self):
        body = _component_body()
        expected = [
            "/dashboard/batches/${encodeURIComponent(batchId)}/proforma-readiness",
            "/dashboard/batches/${encodeURIComponent(batchId)}/zc429-lineage",
            "/dashboard/batches/${encodeURIComponent(batchId)}/cn-hsn-classification",
            "/api/v1/upload/shipment/${encodeURIComponent(batchId)}/wfirma/pz_preview",
            "/api/v1/wfirma/capabilities",
            "/api/v1/batch/${encodeURIComponent(batchId)}/readiness",
            "/dashboard/batches/${encodeURIComponent(batchId)}",
        ]
        for s in expected:
            assert s in body, f"expected GET endpoint missing: {s}"
        post_calls = re.findall(r"method:\s*['\"]POST['\"]", body)
        assert post_calls == [], \
            f"workflow must contain no own POST calls; found {post_calls}"


# ── Sections rendered ──────────────────────────────────────────────────────

class TestSectionsRendered:
    def test_seven_section_shells(self):
        body = _component_body()
        for k in ("evidence", "classification", "products",
                  "customers", "warehouse", "preview", "execute"):
            assert f"sectionShell('{k}'," in body

    def test_next_required_actions_block_present(self):
        body = _component_body()
        assert 'data-testid="workflow-next-actions"' in body
        assert "Next required actions" in body
