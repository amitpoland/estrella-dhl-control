"""tests/test_c16a_lapis_ux_truth.py — C16A

Lapis Proforma / Sales / Inventory UX truth redesign.

Changes verified:
  1.  Location column uses 'In transit' for transit rows (not blank '—')
  2.  Summary qty counter uses PURCHASE_TRANSIT count expression (not raw missing_scan)
  3.  Customer Master datalist wired to primary link-packing panel
  4.  Customer Master datalist wired to main link-packing panel
  5.  OperatorWorkflowCard loads customer-master endpoint
  6.  customersBody shows CM fields (pay, series, terms, ship-to)
  7.  Stale 'contact your admin' text removed from customersBody
  8.  C15A features still present (customer-flag-off, contractor tooltip, unassigned highlight)
  9.  C14A features still present (transit banner, orphan CTA, qty reconciliation)
  10. C13E zero-write guarantee unchanged
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
_HTML = (_ROOT / "service" / "app" / "static" / "shipment-detail.html").read_text(
    encoding="utf-8"
)


# ── 1. Location column fix ────────────────────────────────────────────────────

def test_location_column_shows_in_transit_for_transit_rows():
    """C16A: Location cell must render 'In transit' when isTransit, not r.current_location."""
    assert "isTransit ? 'In transit' : (r.current_location || '—')" in _HTML, \
        "Location column must use isTransit guard"


def test_location_column_does_not_show_blank_for_transit():
    """C16A: The old unconditional r.current_location expression must be gone from the sales table."""
    # The specific sales-table location cell pattern must now be conditional
    # (the old `{r.current_location || '—'}` standalone cell no longer exists
    # in the per-client group rows block)
    sales_table_idx = _HTML.index("isTransit ? 'In transit' : (r.current_location || '—')")
    # Verify it's near the sales status badge
    ctx = _HTML[sales_table_idx - 50: sales_table_idx + 200]
    assert "statusBadge" in ctx or "warehouse_status" in ctx, \
        "Location fix must be in the sales table row, adjacent to statusBadge"


# ── 2. Summary qty counter uses PURCHASE_TRANSIT ──────────────────────────────

def test_summary_counter_uses_purchase_transit_for_transit():
    """C16A: isTransit summary counter must read invState.counts.PURCHASE_TRANSIT."""
    assert "invState.counts.PURCHASE_TRANSIT" in _HTML
    # Verify the counter expression is in the summary card area
    idx = _HTML.index("invState.counts.PURCHASE_TRANSIT")
    ctx = _HTML[idx - 200: idx + 300]
    assert "isTransit" in ctx, \
        "PURCHASE_TRANSIT reference must be guarded by isTransit"
    assert "summary.missing_scan" in ctx, \
        "Fallback to summary.missing_scan must be preserved for non-transit"


def test_summary_counter_preserves_non_transit_path():
    """C16A: non-transit path still uses summary.missing_scan."""
    # Both branches must exist in the same expression
    idx = _HTML.index("invState.counts.PURCHASE_TRANSIT")
    ctx = _HTML[idx - 300: idx + 400]
    assert "summary.missing_scan" in ctx, \
        "summary.missing_scan fallback must be preserved"


# ── 3+4. Customer Master datalist in link-packing panels ─────────────────────

def test_primary_link_panel_has_cm_datalist():
    """C16A: primary link-packing panel client input must be wired to a CM datalist."""
    assert "cm-clients-${doc.id}" in _HTML, \
        "Primary panel must have datalist id cm-clients-${doc.id}"


def test_main_link_panel_has_cm_datalist():
    """C16A: main link-packing panel client input must be wired to a CM datalist."""
    assert "cm-clients-main-${doc.id}" in _HTML, \
        "Main panel must have datalist id cm-clients-main-${doc.id}"


def test_primary_panel_input_uses_list_attribute():
    """C16A: primary panel input must reference the CM datalist via list attribute."""
    # The datalist id and the input list= attribute both embed the same key string
    count = _HTML.count("cm-clients-${doc.id}")
    assert count >= 2, \
        f"Expected cm-clients-${{doc.id}} in both datalist id and input list=, found {count} occurrences"


def test_main_panel_input_uses_list_attribute():
    """C16A: main panel input must reference the CM datalist via list attribute."""
    count = _HTML.count("cm-clients-main-${doc.id}")
    assert count >= 2, \
        f"Expected cm-clients-main-${{doc.id}} in both datalist id and input list=, found {count} occurrences"


def test_datalist_populated_from_clientlist():
    """C16A: datalist options must come from clientList state, not hardcoded."""
    assert "clientList.map" in _HTML, \
        "CM datalist must be populated via clientList.map"


# ── 5. OperatorWorkflowCard loads customer-master ────────────────────────────

def test_operator_workflow_card_loads_customer_master():
    """C16A: OperatorWorkflowCard must fetch /api/v1/customer-master/ on refresh."""
    idx = _HTML.index("function OperatorWorkflowCard")
    # Find the refresh function within the component
    end = _HTML.index("function CNHSNDecisionPanel")
    component_src = _HTML[idx:end]
    assert "/api/v1/customer-master/" in component_src, \
        "OperatorWorkflowCard must load customer-master endpoint"


def test_operator_workflow_card_has_cm_state():
    """C16A: OperatorWorkflowCard must declare cm state variable."""
    idx = _HTML.index("function OperatorWorkflowCard")
    end = _HTML.index("function CNHSNDecisionPanel")
    component_src = _HTML[idx:end]
    assert "setCm" in component_src, \
        "OperatorWorkflowCard must have setCm state setter"
    assert "const [cm, setCm]" in component_src, \
        "OperatorWorkflowCard must declare [cm, setCm] state"


# ── 6. customersBody shows CM fields ─────────────────────────────────────────

def test_customers_body_shows_payment_method():
    """C16A: customersBody must display preferred_payment_method from CM."""
    idx = _HTML.index("workflow-customers-body")
    ctx = _HTML[idx: idx + 1500]
    assert "preferred_payment_method" in ctx, \
        "customersBody must render preferred_payment_method"


def test_customers_body_shows_proforma_series():
    """C16A: customersBody must display preferred_proforma_series_id from CM."""
    idx = _HTML.index("workflow-customers-body")
    ctx = _HTML[idx: idx + 3000]
    assert "preferred_proforma_series_id" in ctx, \
        "customersBody must render preferred_proforma_series_id"


def test_customers_body_shows_invoice_series():
    """C16A: customersBody must display preferred_invoice_series_id from CM."""
    idx = _HTML.index("workflow-customers-body")
    ctx = _HTML[idx: idx + 3000]
    assert "preferred_invoice_series_id" in ctx, \
        "customersBody must render preferred_invoice_series_id"


def test_customers_body_shows_payment_terms():
    """C16A: customersBody must display payment_terms_days from CM."""
    idx = _HTML.index("workflow-customers-body")
    ctx = _HTML[idx: idx + 3000]
    assert "payment_terms_days" in ctx, \
        "customersBody must render payment_terms_days"


def test_customers_body_shows_ship_to():
    """C16A: customersBody must conditionally display ship_to_name from CM."""
    idx = _HTML.index("workflow-customers-body")
    ctx = _HTML[idx: idx + 3000]
    assert "ship_to_name" in ctx, \
        "customersBody must render ship_to_name"


def test_customers_body_cm_row_has_testid():
    """C16A: CM data rows must have testid for test targeting."""
    assert "workflow-cm-row-" in _HTML, \
        "CM rows must have data-testid='workflow-cm-row-{i}'"


# ── 7. Stale 'contact your admin' text removed ───────────────────────────────

def test_stale_contact_admin_text_removed_from_customers_body():
    """C16A: 'contact your admin' must not appear in the customersBody IIFE."""
    idx = _HTML.index("workflow-customers-body")
    # Search forward from the testid to find the end of the customersBody IIFE
    ctx = _HTML[idx: idx + 2000]
    assert "contact your admin" not in ctx, \
        "customersBody must not say 'contact your admin' — replaced with wFirma instruction"


def test_wfirma_instruction_in_customers_body():
    """C16A: customersBody missing-customer warning must name wFirma Contractors path."""
    idx = _HTML.index("workflow-customers-body")
    ctx = _HTML[idx: idx + 2000]
    assert "wFirma" in ctx or "Contractors" in ctx, \
        "customersBody must guide operator to wFirma Contractors for missing customers"


# ── 8. C15A features still present ───────────────────────────────────────────

def test_c15a_customer_flag_off_still_present():
    assert 'data-testid="customer-flag-off"' in _HTML


def test_c15a_contractor_create_new_tooltip_still_present():
    assert "contractor-resolution-${role}-create-new-btn" in _HTML


def test_c15a_link_packing_unassigned_primary_still_present():
    assert "link-packing-doc-unassigned-${doc.id}" in _HTML


def test_c15a_link_packing_unassigned_main_still_present():
    assert "link-packing-doc-unassigned-main-${doc.id}" in _HTML


def test_c15a_needs_client_badge_primary_still_present():
    assert "link-packing-doc-needs-client-${doc.id}" in _HTML


def test_c15a_needs_client_badge_main_still_present():
    assert "link-packing-doc-needs-client-main-${doc.id}" in _HTML


def test_c15a_amber_background_still_present():
    count = _HTML.count("isUnassigned ? 'var(--badge-amber-bg)'")
    assert count >= 2, f"Expected amber highlight in ≥2 panel instances, found {count}"


# ── 9. C14A features still present ───────────────────────────────────────────

def test_c14a_transit_context_banner_present():
    assert 'data-testid="sales-transit-context-banner"' in _HTML


def test_c14a_orphan_assignment_cta_present():
    assert 'data-testid="orphan-assignment-cta"' in _HTML


def test_c14a_qty_reconciliation_present():
    assert 'data-testid="sales-qty-reconciliation"' in _HTML


def test_c14a_proforma_not_linked_panel_present():
    assert "proforma-not-linked-panel-" in _HTML


def test_c14a_pending_arrival_badge_present():
    assert "Pending arrival" in _HTML


# ── 10. C13E zero-write guarantee unchanged ───────────────────────────────────

def test_c13e_zero_write_guarantee_unchanged():
    """C16A changes must not have touched inventory_state_engine.py."""
    import inspect
    from app.services import inventory_state_engine as ise
    src = inspect.getsource(ise.derive_purchase_transit_projection)
    for forbidden in ("INSERT", "UPDATE INVENTORY", "DELETE FROM",
                      "transition(", "upsert_"):
        assert forbidden not in src, \
            f"Zero-write guarantee violated: {forbidden!r} found in projector"
    assert "_coerce_qty" in src, "C13E _coerce_qty helper must still be present"
