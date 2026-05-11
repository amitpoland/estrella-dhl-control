"""
test_dashboard_detail_design.py — Path B / Pass 3.

Contract for the Shipment Detail (BatchDetailPage) design pass:
  - All 9 DETAIL_TABS preserved
  - WorkflowStrip + Next-Action callout preserved
  - Pipeline Summary panel preserved (UI-3.4)
  - Sub-header polished with AWB / Importer / Lines / Doc No info-blocks
  - Real audit / inputs / totals fields bound (no mocks)
  - Importer/Lines fall back to muted em-dash, not fake values
  - No fake client names, fake PZ numbers, fake CIF figures introduced
  - Write/execute buttons unchanged and still guarded
"""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SVC_ROOT = _HERE.parent
_DASH = _SVC_ROOT / "app" / "static" / "dashboard.html"


def _src() -> str:
    if not _DASH.exists():
        import pytest
        pytest.skip(f"dashboard.html not found at {_DASH}")
    return _DASH.read_text(encoding="utf-8")


# ── All 9 DETAIL_TABS preserved (UI-3.5 baseline) ──────────────────────────

def test_detail_tabs_nine_preserved():
    src = _src()
    assert "const DETAIL_TABS = ['Overview', 'Documents', 'DHL / Customs', 'Warehouse', 'Sales', 'PZ / wFirma', 'Timeline', 'Intelligence', 'Proposals']" in src


def test_detail_tabs_map_renders():
    src = _src()
    # The sub-header still iterates DETAIL_TABS into per-tab buttons
    assert "DETAIL_TABS.map(tab => (" in src


# ── BatchDetailPage component still exists and is wired to real audit ──────

def test_batch_detail_page_component_present():
    src = _src()
    assert "function BatchDetailPage(" in src


def test_detail_audit_loaded_from_real_endpoint():
    src = _src()
    # Real load via apiFetch /dashboard/batches/{batch_id}
    assert "apiFetch(`/dashboard/batches/${encodeURIComponent(batchId)}`)" in src
    assert "setAudit(a)" in src


def test_detail_timeline_loaded_from_real_endpoint():
    src = _src()
    # Real timeline endpoint
    assert "apiFetch(`/api/v1/tracking/shipment/${encodeURIComponent(batchId)}/timeline`)" in src


# ── WorkflowStrip preserved ────────────────────────────────────────────────

def test_workflow_strip_present():
    src = _src()
    assert "const WORKFLOW_STAGES" in src
    assert "function WorkflowStrip(" in src
    assert "<WorkflowStrip audit={audit} />" in src


def test_workflow_strip_uses_real_audit_fields():
    src = _src()
    # The stage state derives from real audit.dhl_status/sad_status/pz_status
    assert "audit.dhl_status" in src
    assert "audit.sad_status" in src
    assert "audit.pz_status" in src


# ── Next-Action callout preserved and wires through real flags ─────────────

def test_next_action_callout_present():
    src = _src()
    assert "Next operator action callout" in src
    assert "Next Action" in src
    # The callout switches tabs via existing setActiveTab handler
    assert "setActiveTab(tab)" in src


# ── Pipeline Summary panel preserved (UI-3.4) ──────────────────────────────

def test_pipeline_summary_panel_preserved():
    src = _src()
    assert "pipeline-summary" in src


def test_pipeline_summary_sales_hint_binding_preserved():
    # UI-3.6 — sales_status_hint is passed through to the panel via salesHint
    src = _src()
    assert "salesHint" in src
    assert "sales_status_hint" in src


# ── Sub-header polish ───────────────────────────────────────────────────────

def test_detail_subheader_landmarks_present():
    src = _src()
    for tid in (
        'data-testid="detail-subheader"',
        'data-testid="detail-subheader-awb"',
        'data-testid="detail-subheader-importer"',
        'data-testid="detail-subheader-pieces"',
    ):
        assert tid in src, f"Missing sub-header landmark: {tid}"


def test_detail_subheader_doc_no_conditional():
    src = _src()
    # The Doc No info-block is rendered conditionally on real audit.doc_no
    assert "{audit.doc_no &&" in src
    assert 'data-testid="detail-subheader-doc-no"' in src


def test_detail_subheader_overlines_are_design_faithful():
    src = _src()
    # The labelled overlines use the design's letterspacing + uppercase
    # treatment that matches PanelCard / StatTile.
    assert "letterSpacing: '0.10em', textTransform: 'uppercase'" in src
    # AWB and Importer overline labels in the new sub-header
    assert ">AWB / Tracking<" in src
    assert ">Importer<" in src
    assert ">Lines<" in src


def test_detail_subheader_awb_uses_real_tracking_no():
    src = _src()
    # AWB block reads from the real trackingNo or batchId variables (not a mock)
    assert ">{trackingNo || batchId}<" in src


def test_detail_subheader_importer_uses_real_audit_fields():
    src = _src()
    # Importer fallback chain reads from audit.inputs / audit roots
    assert "inp.importer || inp.importer_name || audit.importer || audit.importer_name" in src


def test_detail_subheader_lines_uses_real_totals():
    src = _src()
    # Lines block reads totals.line_count or audit.line_count
    assert "t.line_count ?? audit.line_count" in src


def test_detail_subheader_missing_fields_show_em_dash():
    src = _src()
    # Both Importer and Lines have em-dash fallback (not a fake value)
    block_start = src.index('data-testid="detail-subheader-importer"')
    block_end   = src.index('data-testid="detail-subheader-pieces"')
    importer_block = src[block_start:block_end]
    assert "—" in importer_block, "Importer block must fall back to em-dash"


# ── No fake / mock values introduced ───────────────────────────────────────

def test_no_fake_importer_name_in_subheader():
    src = _src()
    # Design mock value "Estrella Jewels Sp. z o.o." must NOT be hardcoded
    block_start = src.index('data-testid="detail-subheader"')
    # Look forward until the tab map starts (after the badge)
    block_end = src.index("DETAIL_TABS.map(tab =>", block_start)
    block = src[block_start:block_end]
    assert "Estrella Jewels Sp. z o.o." not in block, \
        "Design mock importer name must not be hardcoded in sub-header"


def test_no_fake_pieces_count_in_subheader():
    src = _src()
    block_start = src.index('data-testid="detail-subheader-pieces"')
    block_end   = src.index("DETAIL_TABS.map(tab =>", block_start)
    block = src[block_start:block_end]
    # Design mock value `47` must not be hardcoded as a fallback
    assert "|| 47" not in block, "Design mock pieces count (47) must not appear"
    assert "?? 47"   not in block


def test_no_mock_pz_number_introduced():
    src = _src()
    # Design's hardcoded PZ/2024/001234 must not have leaked in via this pass
    assert "'PZ/2024/001234'" not in src
    assert '"PZ/2024/001234"' not in src


def test_no_mock_cif_in_detail_subheader():
    src = _src()
    # Design's fake "EUR 1,280" CIF must not have landed in our sub-header
    block_start = src.index('data-testid="detail-subheader"')
    block_end   = src.index("DETAIL_TABS.map(tab =>", block_start)
    block = src[block_start:block_end]
    assert "EUR 1,280" not in block
    assert "EUR 1,150" not in block


# ── Write / execute buttons unchanged + still guarded ──────────────────────

def test_recheck_still_guarded_by_confirm():
    src = _src()
    # Recheck button still calls window.confirm before write
    assert "window.confirm(`Recheck shipment" in src


def test_recheck_writes_to_real_endpoint():
    src = _src()
    # Recheck POSTs to the real /dashboard/batches/{id}/recheck endpoint
    assert "/dashboard/batches/" in src
    assert "method: 'POST'" in src
    assert "mode: 'all'" in src


def test_pz_create_still_requires_confirm():
    src = _src()
    # PzCreate / wFirma export flows are gated by confirm tokens
    assert "pzCreateConfirm" in src
    assert "setPzCreateConfirm" in src


# ── Tab content not gutted ─────────────────────────────────────────────────

def test_overview_tab_still_referenced():
    src = _src()
    # The Overview tab renders the existing overview content
    assert "activeTab === 'Overview'" in src


def test_documents_tab_still_referenced():
    src = _src()
    assert "activeTab === 'Documents'" in src


def test_dhl_customs_tab_still_referenced():
    src = _src()
    assert "activeTab === 'DHL / Customs'" in src


def test_warehouse_tab_still_referenced():
    src = _src()
    assert "activeTab === 'Warehouse'" in src


def test_sales_tab_still_referenced():
    src = _src()
    assert "activeTab === 'Sales'" in src


def test_pz_wfirma_tab_still_referenced():
    src = _src()
    assert "activeTab === 'PZ / wFirma'" in src


def test_timeline_tab_still_referenced():
    src = _src()
    assert "activeTab === 'Timeline'" in src


def test_intelligence_tab_still_referenced():
    src = _src()
    assert "activeTab === 'Intelligence'" in src


def test_proposals_tab_still_referenced():
    src = _src()
    assert "activeTab === 'Proposals'" in src


# ── Design components remain defined (used by Overview area + others) ──────

def test_design_components_present():
    src = _src()
    # These are the design helpers added in earlier passes; must not regress
    assert "function SectionLabel(" in src
    assert "function PanelCard(" in src
    assert "function StatTile(" in src


# ── No fake mock arrays leaked into detail page ────────────────────────────

def test_no_mock_arrays_in_dashboard_html():
    src = _src()
    for fake in ("MOCK_SHIPMENTS", "PIPELINE_SHIPMENTS", "SAMPLE_SHIPMENTS",
                 "fakeData", "FAKE_ROWS"):
        assert fake not in src
