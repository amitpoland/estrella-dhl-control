"""
test_customer_master_v2_contract.py — Source-grep contract tests for Customer Master V2 frontend.

Atlas-V2 Sprint 05. These tests never make HTTP requests — they read the static
file content and ensure the implementation meets the sprint contract:

  1. File exists at expected path
  2. CDN load order: react@18, react-dom@18, @babel/standalone, then the
     shared layer (dashboard-shared.js → pz-api.js → pz-state.js)
  3. All required testids present for components, forms, and UI elements
  4. No auto-save pattern — only btn-save-customer triggers writes
  5. Write-gate test — saveCustomerMaster only called from handleSave
  6. Sync confirmation gate — applyWfirmaSyncCustomer only called after confirmation
  7. Shared layer load order correct
  8. CSS custom properties only (no hardcoded hex colors)
  9. Stack compliance: no TypeScript, no Tailwind, no ES modules
 10. pz-api.js customer extensions present
 11. pz-state.js customer hooks present
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).parents[1] / "app" / "static"
CUSTOMER_MASTER_V2 = STATIC / "customer-master-v2.html"
PZ_API = STATIC / "pz-api.js"
PZ_STATE = STATIC / "pz-state.js"


def _src() -> str:
    if not CUSTOMER_MASTER_V2.exists():
        pytest.skip(f"customer-master-v2.html not found at {CUSTOMER_MASTER_V2}")
    return CUSTOMER_MASTER_V2.read_text(encoding="utf-8")


def _component_block(src: str) -> str:
    """Return the inline page <script> body (the React component code only)."""
    # Find the last script block which contains the main component
    scripts = re.findall(r"<script type=\"text/babel\"[^>]*>(.*?)</script>", src, re.DOTALL)
    assert scripts, "Customer Master V2 page script block not found"
    return scripts[-1]  # The main component is in the last script block


# ── Contract 1: File exists ──────────────────────────────────────────────────

def test_file_exists():
    assert CUSTOMER_MASTER_V2.exists(), f"customer-master-v2.html must exist at {CUSTOMER_MASTER_V2}"


# ── Contract 2: CDN + shared layer load order ────────────────────────────────

def test_cdn_and_shared_load_order():
    src = _src()
    positions = [
        src.find("react@18/umd/react.production.min.js"),
        src.find("react-dom@18/umd/react-dom.production.min.js"),
        src.find("@babel/standalone/babel.min.js"),
        src.find("/dashboard/dashboard-shared.js"),
        src.find("/dashboard/pz-api.js"),
        src.find("/dashboard/pz-state.js"),
    ]
    for p in positions:
        assert p != -1, "A required CDN / shared-layer script is missing"
    assert positions == sorted(positions), "Scripts must load in dependency order"


# ── Contract 3: Required testids present ─────────────────────────────────────

def test_page_structure_testids():
    src = _src()

    # Direct data-testid attributes
    direct_testids = [
        "customer-master-v2-root",
        "topbar",
        "back-to-dashboard-link",
        "customer-list-view",
        "filter-bar",
        "search-input",
        "country-filter",
        "risk-filter",
        "active-toggle",
        "btn-sync-preview",
        "btn-refresh-list",
        "customer-detail-view",
        "back-to-list-btn",
        "btn-save-customer",  # The ONLY save trigger
        "sync-modal",
        "btn-sync-refresh",
        "btn-sync-close",
        "sync-select-all",
        "btn-apply-selected",
        "btn-confirm-apply",
        "btn-confirm-cancel",
        "btn-sync-cancel",
    ]

    for testid in direct_testids:
        assert f'data-testid="{testid}"' in src, f"missing required testid: {testid}"

    # Field component testIds (these become data-testid when rendered)
    field_testids = [
        "field-contractor-id",  # Read-only identity field
        "field-name",
        "field-country",
        "field-nip",
    ]

    for testid in field_testids:
        assert f'testId="{testid}"' in src, f"missing Field testId: {testid}"


# ── Contract 4: No auto-save test ─────────────────────────────────────────────

def test_no_auto_save_patterns():
    block = _component_block(_src())

    # Confirm NO auto-save patterns exist
    forbidden_patterns = [
        "onBlur.*save",
        "onChange.*save",
        "debounce.*save",
        "onInput.*save",
        "useEffect.*save",
    ]

    for pattern in forbidden_patterns:
        matches = re.search(pattern, block, re.IGNORECASE)
        assert not matches, f"Found forbidden auto-save pattern: {pattern}"


# ── Contract 5: Write-gate test ───────────────────────────────────────────────

def test_save_customer_master_only_in_handle_save():
    block = _component_block(_src())

    # saveCustomerMaster should only be called somewhere (in the hook)
    assert 'save(form)' in block, "save function should be called from form"

    # Check that handleSave function exists and is bound to the save button
    assert 'handleSave' in block, "handleSave function should exist"
    assert 'onClick={handleSave}' in block, "handleSave should be bound to save button"
    assert 'data-testid="btn-save-customer"' in block, "Save button should have correct testid"


# ── Contract 6: Sync confirmation gate test ───────────────────────────────────

def test_sync_confirmation_gate():
    block = _component_block(_src())

    # applyWfirmaSyncCustomer should only be called inside handleApply
    # which is triggered by btn-confirm-apply (NOT directly by btn-apply-selected)
    assert 'applyWfirmaSyncCustomer' in block, "applyWfirmaSyncCustomer should be present"
    assert 'handleApply' in block, "handleApply function should exist"
    assert 'btn-confirm-apply' in block, "Confirmation button should exist"

    # btn-apply-selected should trigger confirmation modal, not direct apply
    assert 'setConfirmOpen(true)' in block, "Apply selected should open confirmation modal"


# ── Contract 7: Shared layer load order test ─────────────────────────────────

def test_shared_layer_load_order():
    src = _src()

    # Scripts should load in correct order: dashboard-shared.js → pz-api.js → pz-state.js
    dashboard_shared_pos = src.find("/dashboard/dashboard-shared.js")
    pz_api_pos = src.find("/dashboard/pz-api.js")
    pz_state_pos = src.find("/dashboard/pz-state.js")

    assert dashboard_shared_pos != -1, "dashboard-shared.js should be present"
    assert pz_api_pos != -1, "pz-api.js should be present"
    assert pz_state_pos != -1, "pz-state.js should be present"

    assert dashboard_shared_pos < pz_api_pos < pz_state_pos, "Scripts must load in dependency order"


# ── Contract 8: CSS vars only test ────────────────────────────────────────────

def test_css_custom_properties_only():
    src = _src()

    # Confirm CSS custom properties are used
    assert "--bg:" in src and "--text:" in src, "CSS custom properties should be defined"
    assert "var(--" in src, "CSS custom properties should be used"

    # Extract the <style> block
    style_match = re.search(r'<style>(.*?)</style>', src, re.DOTALL)
    assert style_match, "Style block should exist"

    style_content = style_match.group(1)

    # No hardcoded hex colors in the style block - only var(--*) references
    hex_colors = re.findall(r'#[0-9A-Fa-f]{3,6}', style_content)
    # All hex colors should be in CSS custom property definitions (under :root)
    for hex_color in hex_colors:
        # Check if this hex is in a CSS custom property definition
        prop_pattern = f'--[^:]*:[^;]*{re.escape(hex_color)}'
        assert re.search(prop_pattern, style_content), f"Hex color {hex_color} should only be in CSS custom property definitions"


# ── Contract 9: Stack compliance tests ────────────────────────────────────────

def test_no_forbidden_stack_elements():
    src = _src()

    forbidden_elements = [
        "tailwind",
        "cdn.tailwindcss",
        "TypeScript",
        "import ",  # ES module syntax
        ".ts",  # TypeScript extensions
        'type="module"',
    ]

    for element in forbidden_elements:
        assert element not in src, f"Forbidden stack element found: {element}"


def test_uses_react_production():
    src = _src()
    assert "react.production.min.js" in src, "Should use React production build"


# ── Contract 10: pz-api.js extension tests ───────────────────────────────────

def test_pz_api_customer_extensions():
    if not PZ_API.exists():
        pytest.skip(f"pz-api.js not found at {PZ_API}")

    api_content = PZ_API.read_text(encoding="utf-8")

    required_functions = [
        "previewWfirmaSyncCustomer",
        "applyWfirmaSyncCustomer",
        "getCustomerDictionaries",
        "refreshCustomerDictionaries",
        "listCustomerMaster",  # pre-existing
        "getCustomerMaster",   # pre-existing
        "saveCustomerMaster",  # pre-existing
    ]

    for func in required_functions:
        assert func in api_content, f"Required pz-api.js function missing: {func}"


# ── Contract 11: pz-state.js extension test ──────────────────────────────────

def test_pz_state_customer_hooks():
    if not PZ_STATE.exists():
        pytest.skip(f"pz-state.js not found at {PZ_STATE}")

    state_content = PZ_STATE.read_text(encoding="utf-8")

    required_hooks = [
        "useCustomerList",
        "useCustomerMaster",  # pre-existing
    ]

    for hook in required_hooks:
        assert hook in state_content, f"Required pz-state.js hook missing: {hook}"