"""test_state_propagation_audit.py — Frontend stale-state fixes.

Asserts that BatchDetailPage's centralised refreshAll dispatcher exists
and is wired into both Add Document and Reparse-all paths; that the
importer header reads customs_declaration as a fallback; that
WorkflowStrip derives status from customs_declaration + timeline
instead of bare audit.dhl_status/sad_status/pz_status; that Goods
Movement Timeline lives in the Timeline tab; that EmailEvidenceTimeline
is no longer rendered on Overview; that SelfclearanceStatePill is
gated to Path-A shipments.
"""
from __future__ import annotations

import re
from pathlib import Path


DASH = (Path(__file__).resolve().parents[1] / "app" / "static"
        / "dashboard.html").read_text(encoding="utf-8")
STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"


# ── refreshAll helper ────────────────────────────────────────────────────

def test_refresh_all_helper_exists():
    assert "const refreshAll = React.useCallback(" in DASH


def test_refresh_all_references_required_loaders():
    start = DASH.index("const refreshAll = React.useCallback(")
    body = DASH[start:start + 2000]
    for fn in ("load", "loadDocRegistry", "loadPackingInfo",
               "loadLaneReadiness", "loadDhlReadiness",
               "loadBatchReadiness", "loadSalesLinkage",
               "loadReservationPreview", "loadPzPreview",
               "loadWarehouseAudit"):
        assert fn in body, f"refreshAll must reference {fn!r}"


# ── Callsite wiring ──────────────────────────────────────────────────────

def test_add_document_uploaded_calls_refresh_all():
    idx = DASH.index("<AddDocumentModal")
    block = DASH[idx:idx + 1200]
    assert ("refreshAll('add_document')" in block
            or 'refreshAll("add_document")' in block), (
        "AddDocumentModal onUploaded must call refreshAll('add_document')"
    )


def test_reparse_all_success_calls_refresh_all():
    idx = DASH.index("setReparseSummary(`Reparse complete:")
    block = DASH[idx:idx + 600]
    assert ("refreshAll('reparse')" in block
            or 'refreshAll("reparse")' in block), (
        "Reparse-all success must call refreshAll('reparse')"
    )


# ── Importer fallback (Fix 4) ────────────────────────────────────────────

def test_importer_header_falls_back_to_customs_declaration():
    idx = DASH.index('data-testid="detail-subheader-importer"')
    block = DASH[idx:idx + 1200]
    assert "customs_declaration" in block, (
        "importer header must fall back to audit.customs_declaration.importer_name"
    )
    assert "importer_name" in block


# ── WorkflowStrip derivation (Fix 5) ─────────────────────────────────────

def test_workflow_strip_derives_from_customs_declaration_and_timeline():
    fn_start = DASH.index("function WorkflowStrip(")
    # Find the end of WorkflowStrip — next top-level `function ` declaration.
    fn_end = DASH.index("\nfunction ", fn_start + 30)
    body = DASH[fn_start:fn_end]
    assert "customs_declaration" in body, (
        "WorkflowStrip must read audit.customs_declaration to derive SAD state"
    )
    assert "timeline" in body, (
        "WorkflowStrip must read audit.timeline to derive DHL/PZ state"
    )
    # Confirm at least one canonical event constant appears in derivation.
    assert ("dhl_email_received" in body
            or "dsk_transfer_sent"   in body
            or "pz_generated"        in body), (
        "WorkflowStrip derivation must reference at least one canonical "
        "EV_* event from core/timeline.py"
    )


# ── Goods Movement Timeline relocation (Fix 6) ───────────────────────────

def test_goods_movement_timeline_in_timeline_tab():
    timeline_block_start = DASH.index("{activeTab === 'Timeline' && (")
    # Next sibling block: another activeTab === '...' branch.
    next_tab = DASH.find("activeTab === '", timeline_block_start + 50)
    timeline_block = DASH[timeline_block_start:next_tab]
    assert "Goods Movement Timeline" in timeline_block, (
        "Goods Movement Timeline JSX must live inside Timeline tab block"
    )


def test_goods_movement_timeline_not_in_warehouse_tab():
    warehouse_block_start = DASH.index("activeTab === 'Warehouse'")
    next_tab = DASH.find("\n        {activeTab === '", warehouse_block_start + 50)
    if next_tab < 0:
        next_tab = warehouse_block_start + 60000
    warehouse_block = DASH[warehouse_block_start:next_tab]
    # The label must NOT appear inside the Warehouse tab body.
    assert "Goods Movement Timeline" not in warehouse_block, (
        "Goods Movement Timeline must be removed from Warehouse tab"
    )


# ── EmailEvidenceTimeline removed from Overview (Fix 7) ──────────────────

def test_email_evidence_timeline_not_in_overview():
    pat = re.compile(r"activeTab === 'Overview'\s*&&\s*\(?\s*<EmailEvidenceTimeline")
    assert not pat.search(DASH), (
        "EmailEvidenceTimeline must not be rendered on Overview"
    )


# ── SelfclearanceStatePill gating (Fix 8) ────────────────────────────────

def test_selfclearance_pill_gated_on_in_scope():
    fn_start = DASH.index("function SelfclearanceStatePill(")
    fn_end   = DASH.index("\nfunction ", fn_start + 30)
    body     = DASH[fn_start:fn_end]
    # Acceptable forms:
    #   parent gate:    selfclearanceInScope && <SelfclearanceStatePill ...>
    #   internal gate:  data.in_scope === false  OR  !data.in_scope
    parent_gated = "selfclearanceInScope && <SelfclearanceStatePill" in DASH
    internal_gated = (
        "data.in_scope === false" in body
        or "!data.in_scope" in body
    )
    assert parent_gated or internal_gated, (
        "SelfclearanceStatePill must hide when shipment is not Path-A"
    )


# ── Boundaries: nothing else moved ──────────────────────────────────────

def test_all_nine_detail_tabs_still_present():
    for tab in ("Overview", "Documents", "DHL / Customs", "Warehouse",
                "Sales", "PZ / Accounting", "Timeline",
                "Intelligence", "Proposals"):
        assert f"'{tab}'" in DASH, f"tab {tab!r} missing"


def test_no_backend_url_changes():
    for url in (
        "/api/v1/packing/", "/api/v1/dhl/readiness/",
        "/api/v1/sales/linkage/",
        "/api/v1/shipment/", "/dashboard/batches",
    ):
        assert url in DASH, (
            f"expected URL {url!r} missing — backend route accidentally changed"
        )


def test_shipment_detail_html_not_created():
    assert not (STATIC_DIR / "shipment-detail.html").exists()


def test_batch_detail_page_still_in_dashboard():
    assert "function BatchDetailPage(" in DASH


def test_sidebar_moved_to_shared_after_phase_1b():
    """Phase 1B lifted Sidebar into dashboard-shared.js."""
    hits = re.findall(r"\bfunction\s+Sidebar\b\s*\(", DASH)
    assert len(hits) == 0, "Sidebar must live in dashboard-shared.js after Phase 1B"


def test_route_helper_unchanged():
    """Phase 0 helper survives."""
    assert "function buildShipmentDetailUrl(" in DASH
    assert "window.EstrellaRoutes" in DASH
