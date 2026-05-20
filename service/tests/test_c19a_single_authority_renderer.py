"""tests/test_c19a_single_authority_renderer.py — C19A

Single-Authority Renderer Cleanup: intelligence infrastructure deleted,
visibility panel kept, single ProformaDraftPanel function, C14A–C18A
regression guard.

C18A hid the AI intelligence button with {false && ...}.
C19A deletes the entire intelligence infrastructure from ProformaDraftPanel.

Groups tested:
  1. Intelligence renderer fully deleted (NOT just hidden)
  2. Visibility panel (live operator tool) still present
  3. Single draft renderer (one ProformaDraftPanel)
  4. Customer Master authority (no stale 30/30 isTransit)
  5. Technical diagnostics collapsed (not authoritative)
  6. C14A–C18A regression guard
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
_HTML = (_ROOT / "service" / "app" / "static" / "shipment-detail.html").read_text(
    encoding="utf-8"
)

# Pre-compute ProformaDraftPanel source boundary once for panel-scoped tests.
# ProformaDraftPanel is defined AFTER ProformaReadinessCard in the file.
# We find the next top-level function definition after ProformaDraftPanel to
# delimit the panel source.
_PANEL_START = _HTML.index("function ProformaDraftPanel")
_NEXT_FUNC_MATCHES = [
    m.start() for m in re.finditer(r"\nfunction [A-Z]", _HTML)
    if m.start() > _PANEL_START
]
_PANEL_END = _NEXT_FUNC_MATCHES[0] if _NEXT_FUNC_MATCHES else len(_HTML)
_PANEL_SRC = _HTML[_PANEL_START:_PANEL_END]


# ── Group 1 — Intelligence renderer fully deleted (NOT just hidden) ───────────

def test_intelligence_panel_fully_deleted():
    """C19A: draft-intelligence-panel must be fully deleted, not just hidden."""
    assert 'data-testid="draft-intelligence-panel"' not in _HTML
    assert 'draft-intelligence-panel' not in _HTML


def test_intelligence_button_fully_deleted():
    """C19A: btn-draft-intelligence must be fully deleted from DOM."""
    assert 'btn-draft-intelligence' not in _HTML


def test_load_intelligence_callback_deleted():
    """C19A: loadIntelligence callback must not exist in ProformaDraftPanel."""
    assert 'loadIntelligence' not in _PANEL_SRC


def test_intel_open_state_deleted():
    """C19A: intelOpen state variable must not exist."""
    assert 'intelOpen' not in _HTML


def test_intelligence_state_deleted():
    """C19A: intelligence state variable in ProformaDraftPanel must not exist."""
    # 'intelligence' may appear in comments for email_intelligence_cache (different system)
    # but the state-variable pattern must not exist in ProformaDraftPanel
    assert 'setIntelligence' not in _PANEL_SRC, \
        "setIntelligence must not exist in ProformaDraftPanel"
    assert 'intelOpen' not in _PANEL_SRC, \
        "intelOpen must not exist in ProformaDraftPanel"


def test_draft_anomaly_row_deleted():
    """C19A: draft-anomaly-row testid must be fully deleted."""
    assert 'draft-anomaly-row' not in _HTML


def test_draft_suggestion_row_deleted():
    """C19A: draft-suggestion-row testid must be fully deleted."""
    assert 'draft-suggestion-row' not in _HTML


# ── Group 2 — Visibility panel (live tool) still present ─────────────────────

def test_visibility_panel_still_present():
    """C19A: draft-visibility-panel must remain (it is a live operator tool)."""
    assert 'data-testid="draft-visibility-panel"' in _HTML


def test_visibility_button_still_present():
    """C19A: btn-draft-visibility must remain."""
    assert 'data-testid="btn-draft-visibility"' in _HTML


def test_load_visibility_callback_still_present():
    """C19A: loadVisibility callback must remain in ProformaDraftPanel."""
    assert 'loadVisibility' in _PANEL_SRC


# ── Group 3 — Single draft renderer (one ProformaDraftPanel) ─────────────────

def test_only_one_proforma_draft_panel_function():
    """C19A: exactly one function ProformaDraftPanel definition."""
    count = _HTML.count('function ProformaDraftPanel')
    assert count == 1, f"Expected 1 ProformaDraftPanel definition, found {count}"


def test_draft_lines_table_appears_once():
    """C19A: draft-lines-table must appear exactly once (single renderer)."""
    count = _HTML.count('data-testid="draft-lines-table"')
    assert count == 1, f"Expected 1 draft-lines-table, found {count}"


# ── Group 4 — Customer Master authority (no stale 30/30) ─────────────────────

def test_is_transit_handles_non_synthetic_purchase_transit():
    """C19A regression: isTransit fix from C18A still present."""
    assert "invState.total === ((invState.counts || {}).PURCHASE_TRANSIT || 0)" in _HTML


def test_is_transit_fix_at_both_locations():
    """C19A regression: isTransit fix must appear at both render locations."""
    count = _HTML.count("invState.total === ((invState.counts || {}).PURCHASE_TRANSIT || 0)")
    assert count >= 2, f"isTransit fix must appear at both locations; found {count}"


def test_ship_to_postal_code_used_not_ship_to_zip():
    """C19A regression: CM field ship_to_postal_code used (not wrong ship_to_zip)."""
    assert "c.ship_to_postal_code" in _HTML
    non_comment_uses = [
        line for line in _HTML.split('\n')
        if 'c.ship_to_zip' in line
        and not line.strip().startswith('//')
        and not line.strip().startswith('*')
        and '// C18A:' not in line
    ]
    assert not non_comment_uses, \
        f"c.ship_to_zip must not appear as active code: {non_comment_uses[:3]}"


# ── Group 5 — Technical diagnostics collapsed (not authoritative) ─────────────

def test_legacy_pz_details_collapsed():
    """C19A: legacy-pz-details must be in a <details> element (collapsed by default)."""
    assert 'data-testid="legacy-pz-details"' in _HTML
    idx = _HTML.index('legacy-pz-details')
    ctx = _HTML[max(0, idx - 50): idx + 10]
    assert '<details' in ctx, "legacy-pz-details must be inside a <details> element"


def test_legacy_reservation_details_collapsed():
    """C19A: legacy-reservation-details must be in a <details> element."""
    assert 'data-testid="legacy-reservation-details"' in _HTML
    idx = _HTML.index('legacy-reservation-details')
    ctx = _HTML[max(0, idx - 50): idx + 10]
    assert '<details' in ctx


def test_empty_lines_hint_still_present():
    """C19A regression: draft-lines-empty-hint from C18A still present."""
    assert 'data-testid="draft-lines-empty-hint"' in _HTML


# ── Group 6 — C14A–C18A regression guard ─────────────────────────────────────

def test_c18a_ship_to_postal_code_present():
    assert "c.ship_to_postal_code" in _HTML


def test_c17a_cm_card_testid_present():
    assert "workflow-cm-card-" in _HTML


def test_c17a_saves_to_cm_only_note_present():
    assert "Saves to Customer Master only" in _HTML


def test_c16a_location_uses_is_transit_guard():
    assert "isTransit ? 'In transit' : (r.current_location" in _HTML


def test_c16a_purchase_transit_count_expression():
    assert "invState.counts.PURCHASE_TRANSIT" in _HTML


def test_c14a_sales_transit_banner_present():
    assert 'data-testid="sales-transit-context-banner"' in _HTML


def test_c15a_customer_flag_off_present():
    assert 'data-testid="customer-flag-off"' in _HTML
