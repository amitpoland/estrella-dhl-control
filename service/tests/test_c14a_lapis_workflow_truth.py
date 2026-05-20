"""tests/test_c14a_lapis_workflow_truth.py — C14A

Source-grep tests verifying the Lapis Commercial Workflow Truth Correction:

C14A contract:
  - View Proforma 404 (PROFORMA_NOT_LINKED) → informational panel, no silent failure
  - Transit is an inventory/location concept, not a Sales line status
  - Per-line status for missing scans shows 'Pending arrival' (amber), not 'In transit' (blue)
  - Transit context banner added above per-client groups when isTransit
  - Quantity reconciliation note in transit banner (transit pieces vs invoice units)
  - Orphan assignment CTA at bottom of Sales section
  - No backend files touched
  - No write gates weakened
  - No fake ready state introduced
"""
from __future__ import annotations

from pathlib import Path

import pytest

_HERE     = Path(__file__).resolve()
_SVC_ROOT = _HERE.parent.parent
_DETAIL   = _SVC_ROOT / "app" / "static" / "shipment-detail.html"


def _detail() -> str:
    if not _DETAIL.exists():
        pytest.skip("shipment-detail.html not found")
    return _DETAIL.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════
# CLASS 1: View Proforma graceful 404 handling
# ══════════════════════════════════════════════════════════

class TestC14AViewProformaGraceful:
    # NOTE: C27.1 deleted the legacy reservation IIFE that hosted the
    # "No linked proforma yet" panel and the `proDoc.data` document
    # renderer. State-layer handlers (loadProformaDocument,
    # PROFORMA_NOT_LINKED detection at lines ~2530-2540) remain intact;
    # the JSX surface that consumed them was inside the deleted block.
    # Individual JSX-surface tests are skipped below; state-layer tests
    # remain active.

    def test_proforma_not_linked_error_stored_in_state(self):
        """loadProformaDocument must detect PROFORMA_NOT_LINKED and store
        error:'not_linked' in state instead of a silent toast-only failure."""
        src = _detail()
        assert "error: isNotLinked ? 'not_linked'" in src, (
            "PROFORMA_NOT_LINKED must store error:'not_linked' in proformaDocState"
        )

    def test_proforma_not_linked_suppresses_toast(self):
        """When error is PROFORMA_NOT_LINKED, the error toast must be
        suppressed — this is a normal empty state, not a failure."""
        src = _detail()
        assert "if (!isNotLinked) onToast" in src, (
            "PROFORMA_NOT_LINKED must not trigger an error toast"
        )

    @pytest.mark.skip(reason="C27.1 deleted the JSX surface — see class docstring")
    def test_proforma_not_linked_panel_testid(self):
        """A panel with data-testid must render when proDoc.error==='not_linked'."""
        src = _detail()
        assert 'data-testid={`proforma-not-linked-panel-${d.client_name}`}' in src or \
               'proforma-not-linked-panel' in src, (
            "proforma-not-linked-panel testid must exist"
        )

    @pytest.mark.skip(reason="C27.1 deleted the JSX surface — see class docstring")
    def test_proforma_not_linked_panel_shown_when_error_not_linked(self):
        """The panel must be conditional on proDoc.error === 'not_linked'."""
        src = _detail()
        assert "proDoc.error === 'not_linked'" in src, (
            "panel must be conditional on proDoc.error === 'not_linked'"
        )

    @pytest.mark.skip(reason="C27.1 deleted the JSX surface — see class docstring")
    def test_proforma_not_linked_panel_mentions_draft_preview(self):
        """The not-linked panel must tell operator to use draft preview above."""
        src = _detail()
        idx = src.find("No linked proforma yet")
        assert idx != -1, "panel must say 'No linked proforma yet'"
        snippet = src[idx : idx + 300]
        assert "draft" in snippet.lower() or "preview" in snippet.lower(), (
            "not-linked panel must reference draft preview as next step"
        )

    @pytest.mark.skip(reason="C27.1 deleted the JSX surface — see class docstring")
    def test_proforma_not_linked_panel_is_read_only(self):
        """Not-linked panel must be informational only — no submit, no onClick action."""
        src = _detail()
        idx = src.find("No linked proforma yet")
        assert idx != -1
        snippet = src[idx : idx + 400]
        assert "apiFetch" not in snippet, "not-linked panel must not make API calls"
        assert "method: 'POST'" not in snippet, "not-linked panel must not POST"

    @pytest.mark.skip(reason="C27.1 deleted the JSX surface — see class docstring")
    def test_proforma_document_panel_still_renders_for_linked(self):
        """When proDoc.data is present (proforma IS linked), the full document
        panel must still render — graceful 404 path must not break the happy path."""
        src = _detail()
        assert "if (!proDoc.data) return null" in src or \
               "const pd = proDoc.data" in src, (
            "full proforma document panel render path must still exist"
        )


# ══════════════════════════════════════════════════════════
# CLASS 2: Transit as inventory location, not Sales status
# ══════════════════════════════════════════════════════════

@pytest.mark.skip(reason=(
    "C27.1 deleted the Sales Linkage block including the "
    "sales-transit-context-banner surface. Transit lifecycle is now a "
    "Warehouse-tab concern; equivalent surface will be pinned by a "
    "Warehouse-tab test when C27.3 relocates the transit tables."
))
class TestC14ATransitLocationSemantics:
    def test_transit_context_banner_testid(self):
        """A transit context banner with testid must exist in the Sales tab."""
        src = _detail()
        assert 'data-testid="sales-transit-context-banner"' in src, (
            "sales-transit-context-banner testid must exist"
        )

    def test_transit_context_banner_conditional_on_is_transit(self):
        """Transit context banner must only render when isTransit is true."""
        src = _detail()
        idx = src.find('data-testid="sales-transit-context-banner"')
        assert idx != -1
        prefix = src[max(0, idx - 200) : idx]
        assert "isTransit" in prefix, (
            "transit context banner must be conditional on isTransit"
        )

    def test_transit_context_banner_says_inventory_location(self):
        """Banner must explicitly say 'Inventory location' to distinguish
        inventory/location concept from Sales status."""
        src = _detail()
        assert "Inventory location" in src and "In transit" in src, (
            "transit banner must frame transit as an inventory location concept"
        )

    def test_per_line_remap_absent(self):
        """C14A removes the C13D per-line missing_scan→in_transit remap.
        The inline ternary remap must not exist in the Sales tab statusBadge."""
        src = _detail()
        assert "isTransit && s === 'missing_scan'" not in src and \
               "isTransit && s==='missing_scan'" not in src, (
            "per-line missing_scan→in_transit remap must be absent (C14A removed it)"
        )

    def test_missing_scan_shows_pending_arrival(self):
        """missing_scan status in the Sales tab STATUS_BADGE must show
        'Pending arrival' label — accurate for transit batches without
        confusing inventory location with sales state."""
        src = _detail()
        assert "Pending arrival" in src, (
            "missing_scan in STATUS_BADGE must use 'Pending arrival' label"
        )

    def test_pending_arrival_is_amber_not_red(self):
        """'Pending arrival' for missing_scan must use amber styling,
        not red — red implies an error; amber implies expected waiting state."""
        src = _detail()
        idx = src.find("missing_scan:")
        assert idx != -1
        snippet = src[idx : idx + 200]
        assert "amber" in snippet, (
            "missing_scan (Pending arrival) must use amber color, not red"
        )
        assert "badge-red" not in snippet, (
            "missing_scan must not use red badge in Sales tab STATUS_BADGE"
        )

    def test_summary_counter_label_still_uses_is_transit(self):
        """Summary counter label (In transit: vs Missing scan:) must still
        use isTransit — this is acceptable context, not per-line status."""
        src = _detail()
        assert "isTransit ? 'In transit:'" in src or \
               "isTransit?'In transit:'" in src, (
            "summary counter label must still switch to 'In transit:' when isTransit"
        )


# ══════════════════════════════════════════════════════════
# CLASS 3: Quantity reconciliation display
# ══════════════════════════════════════════════════════════

@pytest.mark.skip(reason=(
    "C27.1 superseded C14A: Sales Linkage block (including the transit "
    "context banner and sales-qty-reconciliation note) was removed from "
    "the Pro Forma surface. The data still exists at the backend; future "
    "Warehouse-tab relocation will pin equivalent surfaces. Test class "
    "preserved as history marker — see test_c27_1_proforma_surface_deletions.py."
))
class TestC14AQtyReconciliation:
    def test_qty_reconciliation_testid(self):
        """Quantity reconciliation note must have a stable data-testid."""
        src = _detail()
        assert 'data-testid="sales-qty-reconciliation"' in src, (
            "sales-qty-reconciliation testid must exist"
        )

    def test_qty_reconciliation_shows_transit_pieces(self):
        """Reconciliation must display the PURCHASE_TRANSIT count as
        'Transit pieces'."""
        src = _detail()
        idx = src.find('data-testid="sales-qty-reconciliation"')
        assert idx != -1
        snippet = src[idx : idx + 400]
        assert "Transit pieces" in snippet or "transit pieces" in snippet, (
            "reconciliation must label the transit piece count"
        )

    def test_qty_reconciliation_reads_purchase_transit_count(self):
        """Reconciliation must read from invState.counts.PURCHASE_TRANSIT."""
        src = _detail()
        idx = src.find('data-testid="sales-qty-reconciliation"')
        assert idx != -1
        # Look back far enough to capture the enclosing IIFE
        block = src[max(0, idx - 600) : idx + 600]
        assert "PURCHASE_TRANSIT" in block, (
            "reconciliation must read from invState.counts.PURCHASE_TRANSIT"
        )

    def test_qty_reconciliation_inside_transit_banner(self):
        """Reconciliation note must be nested inside the transit context
        banner so it only appears when isTransit."""
        src = _detail()
        banner_idx = src.find('data-testid="sales-transit-context-banner"')
        recon_idx  = src.find('data-testid="sales-qty-reconciliation"')
        assert banner_idx != -1 and recon_idx != -1
        assert recon_idx > banner_idx, (
            "reconciliation must appear after the transit banner opening tag"
        )
        assert recon_idx - banner_idx < 2000, (
            "reconciliation must be inside the transit banner block"
        )

    def test_qty_reconciliation_mentions_prs_pairs(self):
        """Reconciliation note must mention PRS/pair counting as a likely
        source of invoice vs packing quantity differences."""
        src = _detail()
        idx = src.find('data-testid="sales-qty-reconciliation"')
        assert idx != -1
        snippet = src[idx : idx + 800]
        assert "PRS" in snippet or "pair" in snippet.lower(), (
            "reconciliation must note PRS/pair counting as a possible difference source"
        )


# ══════════════════════════════════════════════════════════
# CLASS 4: Orphan assignment CTA
# ══════════════════════════════════════════════════════════

@pytest.mark.skip(reason=(
    "C27.1 superseded C14A: orphan-assignment-cta was inside the deleted "
    "Sales Linkage block. The empty-state link-packing flow (when no "
    "drafts exist) still surfaces the action — see "
    "test_c27_1_proforma_surface_deletions.py::test_link_packing_button_preserved_in_empty_state."
))
class TestC14AOrphanAssignmentCta:
    def test_orphan_cta_testid(self):
        """Orphan assignment CTA must have a stable data-testid."""
        src = _detail()
        assert 'data-testid="orphan-assignment-cta"' in src, (
            "orphan-assignment-cta testid must exist"
        )

    def test_orphan_cta_references_link_panel(self):
        """CTA must reference the 'Link packing files as client sales' action."""
        src = _detail()
        idx = src.find('data-testid="orphan-assignment-cta"')
        assert idx != -1
        snippet = src[idx : idx + 400]
        assert "Link packing files" in snippet, (
            "orphan CTA must reference the Link packing files panel"
        )

    def test_orphan_cta_is_informational_only(self):
        """Orphan CTA must be purely informational — no button, no API call."""
        src = _detail()
        idx = src.find('data-testid="orphan-assignment-cta"')
        assert idx != -1
        snippet = src[idx : idx + 400]
        assert "apiFetch" not in snippet, "orphan CTA must not make API calls"
        assert "<Btn" not in snippet, "orphan CTA must not contain a button"
        assert "onClick" not in snippet, "orphan CTA must not bind onClick"

    def test_orphan_cta_in_bottom_card(self):
        """Orphan CTA must appear in the bottom card of the Sales section,
        after the per-client groups."""
        src = _detail()
        groups_idx = src.find("Per-client groups")
        cta_idx    = src.find('data-testid="orphan-assignment-cta"')
        assert groups_idx != -1 and cta_idx != -1
        assert cta_idx > groups_idx, (
            "orphan CTA must appear after per-client groups comment"
        )


# ══════════════════════════════════════════════════════════
# CLASS 5: Safety invariants — no forbidden mutations
# ══════════════════════════════════════════════════════════

class TestC14ASafetyInvariants:
    def test_no_wfirma_write_flag_touched(self):
        """C14A must not introduce WFIRMA_CREATE_PZ_ALLOWED references."""
        src = _detail()
        assert "WFIRMA_CREATE_PZ_ALLOWED" not in src, (
            "shipment-detail.html must not reference WFIRMA_CREATE_PZ_ALLOWED"
        )

    def test_no_fake_ready_state(self):
        """cleanGate must still check stuck/invalid/orphans even after C14A."""
        src = _detail()
        idx = src.find("const cleanGate")
        snippet = src[idx : idx + 250]
        assert "stuck.length" in snippet
        assert "invalid.length" in snippet
        assert "orphans.length" in snippet

    @pytest.mark.skip(reason=(
        "C27.1 superseded C14A: sales-linkage-blocking-reasons was inside "
        "the deleted Sales Linkage block. Invoice-gate blocker visibility "
        "is now owned by /proforma-readiness blockers_for_posting (C26 "
        "canonical reader)."
    ))
    def test_gate_blockers_preserved(self):
        """Sales linkage blocking reasons display must still be present —
        C14A must not remove existing blocker visibility."""
        src = _detail()
        assert 'data-testid="sales-linkage-blocking-reasons"' in src, (
            "sales-linkage-blocking-reasons block must remain"
        )
        assert "ready_for_invoice: false" in src or "ready_for_invoice:" in src, (
            "invoice gate flag must remain visible"
        )

    def test_transit_note_unchanged(self):
        """The Warehouse tab transit note (from C13D) must still be present."""
        src = _detail()
        assert 'data-testid="warehouse-transit-note"' in src, (
            "warehouse-transit-note must not be removed by C14A"
        )

    def test_braces_balanced(self):
        """shipment-detail.html must have balanced braces after C14A edits."""
        src = _detail()
        opens  = src.count("{")
        closes = src.count("}")
        assert opens == closes, f"unbalanced braces: {{={opens} }}={closes}"
