"""tests/test_c18a_unified_proforma_truth.py — C18A

Unified Proforma Builder Truth: 5 root-cause fixes verified.

Changes verified:
  1. ship_to_postal_code used for ship-to ZIP (was c.ship_to_zip — wrong field)
  2. isTransit handles non-synthetic PURCHASE_TRANSIT batches (both occurrences)
  3. AI intelligence panel / button hidden from operator workflow
  4. JSON (debug) button hidden from operator view
  5. Empty-lines hint present and actionable
  6. All C17A markers still present (regression guard)
  7. All C16A markers still present (regression guard)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent.parent
_HTML = (_ROOT / "service" / "app" / "static" / "shipment-detail.html").read_text(
    encoding="utf-8"
)


# ── 1. ship_to_postal_code fix ────────────────────────────────────────────────

def test_ship_to_zip_uses_postal_code_field():
    """C18A: ship-to ZIP must read c.ship_to_postal_code not c.ship_to_zip."""
    assert "c.ship_to_postal_code" in _HTML, \
        "onApplyCustomerDefaults must use c.ship_to_postal_code for ship-to ZIP"


def test_ship_to_zip_old_wrong_field_gone():
    """C18A: c.ship_to_zip (wrong CM field) must not appear outside comments."""
    # Allow it inside comments but not as actual code
    # Find all non-comment occurrences
    non_comment_uses = [
        line for line in _HTML.split('\n')
        if 'c.ship_to_zip' in line and not line.strip().startswith('//')
        and not line.strip().startswith('*')
        and '// C18A:' not in line  # allow inline migration comment
    ]
    assert not non_comment_uses, \
        f"c.ship_to_zip appears as active code: {non_comment_uses[:3]}"


def test_ship_to_cascade_has_postal_fallback():
    """C18A: ship-to ZIP cascade must include bill_to_postal_code fallback."""
    # Ensure the full fallback chain is present
    assert "c.ship_to_postal_code || c.bill_to_postal_code" in _HTML, \
        "Ship-to ZIP must fall back to bill_to_postal_code"


# ── 2. isTransit detection fix ────────────────────────────────────────────────

def test_is_transit_handles_non_synthetic_purchase_transit():
    """C18A: isTransit must fire when ALL pieces are PURCHASE_TRANSIT (synthetic=false)."""
    # The new guard: invState.total === invState.counts.PURCHASE_TRANSIT
    assert "invState.total === ((invState.counts || {}).PURCHASE_TRANSIT || 0)" in _HTML, \
        "isTransit must handle non-synthetic PURCHASE_TRANSIT (total === PURCHASE_TRANSIT)"


def test_is_transit_fix_applied_twice():
    """C18A: isTransit fix must be applied at both render locations."""
    count = _HTML.count(
        "invState.total === ((invState.counts || {}).PURCHASE_TRANSIT || 0)"
    )
    assert count >= 2, \
        f"isTransit fix must appear at both Sales-tab and inventory-card locations; found {count}"


def test_is_transit_still_handles_synthetic_true():
    """C18A: synthetic=true path still works (backward compat)."""
    assert "invState.synthetic === true" in _HTML, \
        "Original synthetic=true check must still be present"


# ── 3. AI intelligence panel hidden ──────────────────────────────────────────

def test_ai_intelligence_button_hidden():
    """C18A: AI intelligence button must be hidden from operator flow (wrapped in {false &&})."""
    # btn-draft-intelligence must either not exist or be inside a {false && ...} guard
    idx = _HTML.find('data-testid="btn-draft-intelligence"')
    if idx == -1:
        return  # fully removed — also fine
    # Must be inside a {false && ...} block
    context = _HTML[max(0, idx - 200): idx + 50]
    assert '{false &&' in context, \
        "btn-draft-intelligence must be wrapped in {false && ...} to hide it"


def test_ai_intelligence_panel_not_prominent():
    """C18A: draft-intelligence-panel must remain in DOM but never visible (button hidden)."""
    # The panel itself can remain (no test should fail just because it's still in DOM),
    # but the toggle button must be hidden. Confirmed by test above.
    # Just check panel testid still exists so C18A didn't accidentally break HTML structure.
    assert 'data-testid="draft-intelligence-panel"' in _HTML, \
        "draft-intelligence-panel testid must remain in HTML"


# ── 4. JSON (debug) button hidden ────────────────────────────────────────────

def test_json_debug_button_hidden():
    """C18A: JSON (debug) button must be hidden from operator view."""
    # Both occurrences should be gone or in false-guarded blocks
    idx1 = _HTML.find('btn-draft-preview-json"')
    idx2 = _HTML.find('btn-draft-preview-json-approved"')
    # btn-draft-preview-json (editable state): should be hidden
    if idx1 != -1:
        ctx = _HTML[max(0, idx1 - 200): idx1 + 50]
        assert '{false &&' in ctx or 'JSON (debug)' not in _HTML[idx1: idx1 + 200], \
            "btn-draft-preview-json must be hidden (wrapped in {false &&})"
    # btn-draft-preview-json-approved: should be removed entirely
    assert idx2 == -1, \
        "btn-draft-preview-json-approved should be removed from the approved-state block"


def test_json_debug_label_not_shown_to_operator():
    """C18A: 'JSON (debug)' text must not appear as visible button label."""
    # It may appear inside a {false && ...} block (inert) but must not be in
    # an operator-reachable button outside such a guard.
    occurrences = [(m.start(), m.end()) for m in re.finditer(r'JSON \(debug\)', _HTML)]
    for start, end in occurrences:
        context_before = _HTML[max(0, start - 400): start]
        assert '{false &&' in context_before, \
            f"'JSON (debug)' appears outside a {{false && ...}} guard at offset {start}"


# ── 5. Empty-lines hint ───────────────────────────────────────────────────────

def test_empty_lines_hint_present():
    """C18A: empty editable_lines must show actionable hint, not silent '(no lines)'."""
    assert 'data-testid="draft-lines-empty-hint"' in _HTML, \
        "draft-lines-empty-hint testid must be present for empty-lines state"


def test_empty_lines_hint_mentions_reload():
    """C18A: empty-lines hint must direct operator to 'Reload items from warehouse data'."""
    idx = _HTML.index('draft-lines-empty-hint')
    ctx = _HTML[idx: idx + 1200]
    assert "Reload items from warehouse data" in ctx, \
        "Empty-lines hint must mention the Reload action button"


def test_empty_lines_hint_mentions_link_packing():
    """C18A: empty-lines hint must mention link-packing-as-sales as prerequisite."""
    idx = _HTML.index('draft-lines-empty-hint')
    ctx = _HTML[idx: idx + 1200]
    assert "Link packing as sales" in ctx or "link-packing" in ctx.lower(), \
        "Empty-lines hint must guide operator to link packing first if not done"


def test_old_no_lines_silent_removed():
    """C18A: silent '(no lines)' placeholder must be replaced by the hint."""
    # The bare "(no lines)" string should no longer appear in that context
    # (it was inside the empty-lines check block)
    assert "(no lines)" not in _HTML, \
        "Silent '(no lines)' placeholder must be replaced by the actionable hint"


# ── 6. C17A regression guard ─────────────────────────────────────────────────

def test_c17a_cm_card_testid_present():
    assert "workflow-cm-card-" in _HTML

def test_c17a_btn_cm_edit_present():
    assert "btn-cm-edit-" in _HTML

def test_c17a_btn_cm_save_present():
    assert "btn-cm-save-" in _HTML

def test_c17a_save_cm_fields_callback_present():
    assert "saveCmFields" in _HTML

def test_c17a_saves_to_cm_only_note_present():
    assert "Saves to Customer Master only" in _HTML


# ── 7. C16A regression guard ─────────────────────────────────────────────────

def test_c16a_location_uses_is_transit_guard():
    assert "isTransit ? 'In transit' : (r.current_location" in _HTML

def test_c16a_purchase_transit_count_expression():
    assert "invState.counts.PURCHASE_TRANSIT" in _HTML

def test_c16a_workflow_cm_card_testid():
    assert "workflow-cm-card-" in _HTML


# ── 8. C14A/C15A regression guard ────────────────────────────────────────────

def test_c14a_sales_transit_banner_present():
    assert 'data-testid="sales-transit-context-banner"' in _HTML

def test_c15a_customer_flag_off_present():
    assert 'data-testid="customer-flag-off"' in _HTML
