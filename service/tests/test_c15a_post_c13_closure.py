"""tests/test_c15a_post_c13_closure.py — C15A

Post-C13 master closure: operator friction reduction.

Changes verified:
  1.  customer-flag-off message is actionable (wFirma instruction)
  2.  contractor create-new button label mentions wFirma
  3.  contractor create-new tooltip is actionable
  4.  link-packing unassigned badge testid present (both panel instances)
  5.  ProformaDraftPanel empty subtitle is accurate
  6.  validate_deploy_*.sh is in .gitignore
  7.  No fake-readiness strings introduced
  8.  No write tokens added to shipment-detail.html read-only surfaces
  9.  C14A features still present (PROFORMA_NOT_LINKED, transit banner, orphan CTA)
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
_GITIGNORE = (_ROOT / ".gitignore").read_text(encoding="utf-8")


# ── 1. customer-flag-off message is actionable ────────────────────────────────

def test_customer_flag_off_contains_wfirma_instruction():
    """C15A: message must point operator to wFirma, not just say 'contact admin'."""
    idx = _HTML.index('data-testid="customer-flag-off"')
    snippet = _HTML[idx: idx + 400]
    assert "wFirma" in snippet, "customer-flag-off must mention wFirma"
    assert "Contractors" in snippet or "contractor" in snippet.lower(), \
        "customer-flag-off must mention Contractors"
    assert "Action required" in snippet, \
        "customer-flag-off must have 'Action required' label"


def test_customer_flag_off_does_not_say_contact_admin():
    """Old text 'contact your admin' must be gone."""
    idx = _HTML.index('data-testid="customer-flag-off"')
    snippet = _HTML[idx: idx + 400]
    assert "contact your admin" not in snippet, \
        "customer-flag-off must not say 'contact your admin'"


# ── 2+3. contractor create-new button ────────────────────────────────────────

def test_contractor_create_new_button_label_mentions_wfirma():
    """C15A: disabled button label must hint operator to create in wFirma first."""
    idx = _HTML.index("contractor-resolution-${role}-create-new-btn")
    snippet = _HTML[idx: idx + 300]
    assert "wFirma" in snippet, \
        "create-new button label must mention wFirma"


def test_contractor_create_new_tooltip_is_actionable():
    """C15A: tooltip must tell operator to use wFirma Contractors menu."""
    idx = _HTML.index("contractor-resolution-${role}-create-new-btn")
    snippet = _HTML[idx: idx + 400]
    assert "Contractors menu" in snippet or "Contractors" in snippet, \
        "create-new tooltip must mention Contractors menu"
    assert "Resolve" in snippet, \
        "create-new tooltip must mention Resolve step"


# ── 4. unassigned highlight testids present ───────────────────────────────────

def test_link_packing_unassigned_testid_present_primary_panel():
    """C15A: primary link-packing panel must emit 'Needs client' badge testid."""
    assert "link-packing-doc-needs-client-${doc.id}" in _HTML, \
        "primary panel must have 'Needs client' badge testid"


def test_link_packing_unassigned_testid_present_main_panel():
    """C15A: main link-packing panel must also emit 'Needs client' badge testid."""
    assert "link-packing-doc-needs-client-main-${doc.id}" in _HTML, \
        "main panel must have 'Needs client' badge testid"


def test_link_packing_unassigned_row_testid_primary_panel():
    """C15A: primary panel row testid switches to 'unassigned' when no name."""
    assert "link-packing-doc-unassigned-${doc.id}" in _HTML


def test_link_packing_unassigned_row_testid_main_panel():
    """C15A: main panel row testid switches to 'unassigned-main' when no name."""
    assert "link-packing-doc-unassigned-main-${doc.id}" in _HTML


def test_link_packing_unassigned_uses_amber_background():
    """C15A: amber highlight must reference the badge-amber-bg CSS variable."""
    # Both panel instances should use the amber background for unassigned rows
    count = _HTML.count("isUnassigned ? 'var(--badge-amber-bg)'")
    assert count >= 2, \
        f"expected amber highlight in ≥2 panel instances, found {count}"


# ── 5. ProformaDraftPanel empty subtitle ─────────────────────────────────────

def test_proforma_draft_panel_empty_subtitle_is_accurate():
    """C15A: empty subtitle must not say 'once packing data is uploaded' when
    data may already be present but not linked."""
    assert "they'll appear once packing data is uploaded" not in _HTML, \
        "Outdated subtitle still present — update to mention link path"


def test_proforma_draft_panel_empty_subtitle_mentions_link_button():
    """C15A: new subtitle must point to the link button as the next action."""
    idx = _HTML.index("proforma-draft-panel-empty")
    snippet = _HTML[idx: idx + 500]
    assert "link" in snippet.lower(), \
        "empty subtitle must mention the link path"


# ── 6. .gitignore covers validate_deploy scripts ─────────────────────────────

def test_gitignore_covers_validate_deploy_scripts():
    """C15A: validate_deploy_*.sh must be in .gitignore."""
    assert "validate_deploy_*.sh" in _GITIGNORE, \
        ".gitignore must exclude validate_deploy_*.sh"


# ── 7. No fake-readiness strings introduced ───────────────────────────────────

def test_no_fake_readiness_introduced():
    """C15A: none of the new change areas should introduce fake-ready strings."""
    forbidden = [
        "ready_for_invoice: true",   # must remain gated
        "WFIRMA_WRITE=true",         # must remain off
        "auto_pz_enabled",
    ]
    for tok in forbidden:
        assert tok not in _HTML, f"Forbidden fake-readiness token found: {tok!r}"


# ── 8. No write tokens in new unassigned-highlight logic ─────────────────────

def test_no_write_tokens_in_unassigned_highlight_logic():
    """C15A: the isUnassigned expression must not trigger any write."""
    # Find all occurrences of isUnassigned in the source and check surrounding
    # context for write-shaped API calls.
    for match in re.finditer(r"isUnassigned", _HTML):
        ctx = _HTML[match.start(): match.start() + 200]
        assert "apiFetch" not in ctx, \
            "isUnassigned expression must not trigger an API call"
        assert "onClick" not in ctx.split("isUnassigned")[1][:100], \
            "isUnassigned must not attach an onClick handler"


# ── 9. C14A features still present ───────────────────────────────────────────

def test_c14a_proforma_not_linked_panel_present():
    assert "proforma-not-linked-panel-" in _HTML


def test_c14a_sales_transit_context_banner_present():
    assert 'data-testid="sales-transit-context-banner"' in _HTML


def test_c14a_orphan_assignment_cta_present():
    assert 'data-testid="orphan-assignment-cta"' in _HTML


def test_c14a_sales_qty_reconciliation_present():
    assert 'data-testid="sales-qty-reconciliation"' in _HTML


def test_c14a_pending_arrival_badge_present():
    assert "Pending arrival" in _HTML


# ── 10. C13E zero-write guarantee unchanged ───────────────────────────────────

def test_c13e_zero_write_guarantee_unchanged():
    """C15A changes must not have touched inventory_state_engine.py."""
    import inspect
    from app.services import inventory_state_engine as ise
    src = inspect.getsource(ise.derive_purchase_transit_projection)
    for forbidden in ("INSERT", "UPDATE INVENTORY", "DELETE FROM",
                      "transition(", "upsert_"):
        assert forbidden not in src, \
            f"Zero-write guarantee violated: {forbidden!r} found in projector"
    assert "_coerce_qty" in src, "C13E _coerce_qty helper must still be present"
