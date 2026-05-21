"""test_c27_1_proforma_surface_deletions.py — C27.1.

Pins the C27.1 surface deletions from the Pro Forma area of
shipment-detail.html:

1. Sales Linkage block (header + summary + per-client transit tables)
2. Advanced / legacy reservation preview (entire <details> block + the
   wFirma Reservation Preview standalone inside it)
3. Link / re-link packing files as client sales (post-draft surface)

These deletions remove mixed-authority surfaces from the Pro Forma
renderer. The data sources still exist on the backend; future Screen B
drilldown (C27.4) and Warehouse-tab relocation (C27.3) consume them
from their proper domain pages, not stacked inside the proforma editor.

Real-builder regression test per Lesson A: scans the actual deployed
shipment-detail.html for the absence of the removed surface markers.
"""
from __future__ import annotations

from pathlib import Path

import pytest


_HTML_PATH = (
    Path(__file__).resolve().parent.parent
    / "app" / "static" / "shipment-detail.html"
)


@pytest.fixture(scope="module")
def html_src() -> str:
    return _HTML_PATH.read_text(encoding="utf-8")


# ── Block 1: Sales Linkage surface removed ────────────────────────────────


def test_sales_linkage_header_removed(html_src):
    """The 🛒 Sales Linkage header div must not exist as a rendered
    surface inside the Pro Forma area. A passing reference inside an
    unrelated tooltip comment (informational, not a rendered surface)
    is allowed."""
    # The actual rendered surface had a unique combination — heading + handler
    assert ">🛒 Sales Linkage</div>" not in html_src, (
        "🛒 Sales Linkage rendered surface still present in shipment-detail.html"
    )


def test_linkage_summary_card_removed(html_src):
    """The Linkage Summary card with Total/Ready/Pending/Not ready/In transit
    must be removed."""
    assert ">Linkage Summary</div>" not in html_src, (
        "Linkage Summary surface still present"
    )


def test_sales_linkage_blocked_flag_testid_removed(html_src):
    """The test-id sales-linkage-blocked-flag belonged only to the
    Sales Linkage surface."""
    assert "sales-linkage-blocked-flag" not in html_src, (
        "Sales Linkage blocked-flag test-id still present"
    )


def test_sales_linkage_ready_flag_testid_removed(html_src):
    assert "sales-linkage-ready-flag" not in html_src, (
        "Sales Linkage ready-flag test-id still present"
    )


def test_sales_linkage_blocking_reasons_testid_removed(html_src):
    assert "sales-linkage-blocking-reasons" not in html_src, (
        "Sales Linkage blocking-reasons test-id still present"
    )


def test_per_client_transit_tables_removed_from_proforma(html_src):
    """The per-client transit tables (PRODUCT CODE / DESIGN / QTY /
    SCAN CODES / LOCATION / STATUS columns) were rendered inside the
    Sales Linkage block. Asserting they are absent from the static file
    is sufficient because the only rendering path was through that
    block."""
    # The column header sequence was unique to those tables
    assert "Scan codes" not in html_src or html_src.count("Scan codes") == 0, (
        "Per-client transit table column headers still present in DOM"
    )


# ── Block 2: Advanced / legacy reservation preview removed ────────────────


def test_legacy_reservation_details_testid_removed(html_src):
    assert "legacy-reservation-details" not in html_src, (
        "legacy-reservation-details test-id still present"
    )


def test_legacy_reservation_summary_testid_removed(html_src):
    assert "legacy-reservation-summary" not in html_src, (
        "legacy-reservation-summary test-id still present"
    )


def test_wfirma_reservation_preview_surface_removed(html_src):
    """The standalone '↗ wFirma Reservation Preview' header lived inside
    the legacy reservation block; its removal is verified by absence of
    that exact header string."""
    assert "↗ wFirma Reservation Preview" not in html_src, (
        "↗ wFirma Reservation Preview rendered surface still present"
    )


def test_advanced_legacy_reservation_label_removed(html_src):
    """The summary label 'Advanced / legacy reservation preview' marked
    the entry point to the deleted block."""
    assert "Advanced / legacy reservation preview" not in html_src, (
        "Advanced / legacy reservation preview surface still present"
    )


# ── Block 3: Link / re-link packing files (post-draft surface) removed ────


def test_link_packing_section_main_removed(html_src):
    """The link-packing-section-main surface (shown when drafts exist)
    is a pre-draft repair flow that must not survive into the post-draft
    era. The empty-state version inside ProformaDraftPanel (when
    drafts.length === 0) is preserved because it remains valid before
    drafts are created."""
    assert "link-packing-section-main" not in html_src, (
        "link-packing-section-main surface still present"
    )


def test_btn_link_packing_as_sales_main_removed(html_src):
    assert "btn-link-packing-as-sales-main" not in html_src, (
        "btn-link-packing-as-sales-main button still present"
    )


def test_btn_link_packing_submit_main_removed(html_src):
    assert "btn-link-packing-submit-main" not in html_src, (
        "btn-link-packing-submit-main button still present"
    )


def test_btn_link_packing_cancel_main_removed(html_src):
    assert "btn-link-packing-cancel-main" not in html_src, (
        "btn-link-packing-cancel-main button still present"
    )


def test_link_packing_button_preserved_in_empty_state(html_src):
    """The pre-draft repair flow MUST remain available in
    ProformaDraftPanel's empty state (when no drafts exist yet).
    Confirms we did not over-delete."""
    assert "btn-link-packing-as-sales" in html_src, (
        "btn-link-packing-as-sales (empty-state version) was over-deleted"
    )
    assert 'data-testid="proforma-draft-panel-empty"' in html_src, (
        "proforma-draft-panel empty state was over-deleted"
    )


# ── Replacement markers present (positive confirmation) ───────────────────


def test_c27_1_replacement_comments_present(html_src):
    """Verify the C27.1 deletion markers are in place — these document
    the removal so future maintainers know where the blocks went."""
    assert "C27.1: Sales Linkage block removed from Pro Forma surface" in html_src
    assert "C27.1: Advanced/legacy reservation IIFE removed" in html_src
    assert "C27.1: Link / re-link packing files (legacy pre-draft repair flow)" in html_src


# ── Authority chain: C25A / C26 still intact ──────────────────────────────


def test_proforma_draft_panel_still_mounted(html_src):
    """ProformaDraftPanel mount must remain — it is the canonical draft
    list surface (Screen A precursor)."""
    assert 'data-testid="sales-tab-proforma-draft-panel"' in html_src, (
        "Canonical proforma-draft-panel mount missing"
    )
    assert "<ProformaDraftPanel batchId={batchId}" in html_src, (
        "ProformaDraftPanel component invocation missing"
    )


def test_setup_detail_panel_still_present(html_src):
    """C25A setup-detail panel must not be disturbed by C27.1."""
    assert "setup-detail-panel" in html_src or "shipment_setup_detail" in html_src or \
           "OperatorWorkflowCard" in html_src, (
        "C25A setup-detail surface markers missing — C27.1 over-deleted"
    )


def test_unified_workflow_card_still_present(html_src):
    """The unified workflow card was the canonical replacement that made
    the legacy reservation block obsolete. It must remain."""
    assert "<OperatorWorkflowCard batchId={batchId}" in html_src, (
        "OperatorWorkflowCard mount missing — C27.1 over-deleted"
    )
