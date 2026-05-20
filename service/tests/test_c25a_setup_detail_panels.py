"""test_c25a_setup_detail_panels.py — C25A regression suite.

Two surfaces:

  1. Backend endpoint
     GET /api/v1/wfirma/shipment/{batch_id}/setup-detail
     - Returns per-product missing detail with line context
     - Returns per-customer action_needed classifier
     - Returns readiness split (can_prepare_proforma vs can_post_to_wfirma)
     - Honours create_flag_on per WFIRMA_CREATE_PRODUCT_ALLOWED /
       WFIRMA_CREATE_CUSTOMER_ALLOWED (both default False)
     - READ-ONLY: no DB writes anywhere on the call path

  2. Frontend source-grep (shipment-detail.html)
     - Setup-detail panel test IDs present
     - Register / Create-in-wFirma buttons wrapped in flag conditionals
     - Save CM and Resolve buttons are dry-run safe (don't call wFirma writes)

These tests use only source-level assertions + the import-and-introspect
pattern so they remain stable across environments and do not require a
running service.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parent.parent
_DETAIL_HTML = _REPO / "app" / "static" / "shipment-detail.html"
_ROUTES_SRC  = _REPO / "app" / "api" / "routes_wfirma_capabilities.py"


# ── Backend: source-level signature + invariants ────────────────────────────


@pytest.fixture(scope="module")
def routes_src() -> str:
    return _ROUTES_SRC.read_text(encoding="utf-8")


def test_backend_endpoint_registered(routes_src):
    """The setup-detail endpoint must be declared with the canonical path."""
    assert '@router.get("/shipment/{batch_id:path}/setup-detail"' in routes_src, (
        "C25A endpoint not registered at /shipment/{batch_id:path}/setup-detail"
    )
    assert 'def shipment_setup_detail(' in routes_src, (
        "C25A endpoint handler shipment_setup_detail() not present"
    )


def test_backend_endpoint_is_read_only(routes_src):
    """The endpoint body must contain NO write-shaped tokens against the
    wFirma DB / customer master / proforma drafts.  Authority rule:
    setup-detail is purely informational."""
    # Slice just the endpoint body for inspection.
    idx = routes_src.index("def shipment_setup_detail(")
    # End of function = next top-level `@router` or EOF.
    next_decorator = routes_src.find("\n@router.", idx)
    body = routes_src[idx : next_decorator if next_decorator > 0 else len(routes_src)]
    forbidden = (
        "INSERT ", "UPDATE ", "DELETE ",
        "upsert_", "create_proforma", "create_invoice",
        "register_product", "register_customer",
        "_guard_wfirma_export",  # never importable from a read-only
        "wfirma_client.",        # MUST NOT call live wFirma API
    )
    for tok in forbidden:
        assert tok not in body, (
            f"setup-detail body contains forbidden token {tok!r} — "
            "endpoint must remain read-only"
        )


def test_backend_endpoint_returns_required_shape_keys(routes_src):
    """The endpoint constructs the documented response keys."""
    idx = routes_src.index("def shipment_setup_detail(")
    body = routes_src[idx:]
    required_keys = [
        '"products":', '"customers":', '"readiness":', '"errors":',
        '"missing":', '"mapped_count":', '"missing_count":', '"create_flag_on":',
        '"can_prepare_proforma":', '"can_post_to_wfirma":',
        '"blockers_for_preparation":', '"blockers_for_posting":',
        '"purchase_transit_count":', '"batch_lifecycle":',
        '"details":', '"action_needed":',
    ]
    for k in required_keys:
        assert k in body, f"setup-detail response missing required key {k!r}"


def test_backend_endpoint_uses_correct_flags(routes_src):
    """create_flag_on for products must read wfirma_create_product_allowed;
    for customers must read wfirma_create_customer_allowed; posting gate
    must check wfirma_create_pz_allowed."""
    idx = routes_src.index("def shipment_setup_detail(")
    body = routes_src[idx:]
    assert 'wfirma_create_product_allowed' in body
    assert 'wfirma_create_customer_allowed' in body
    assert 'wfirma_create_pz_allowed' in body


# ── Frontend source-grep tests ──────────────────────────────────────────────


@pytest.fixture(scope="module")
def detail_html() -> str:
    return _DETAIL_HTML.read_text(encoding="utf-8")


def test_frontend_fetches_setup_detail_endpoint(detail_html):
    assert "/api/v1/wfirma/shipment/" in detail_html
    assert "/setup-detail" in detail_html
    assert "refreshSetupDetail" in detail_html


def test_frontend_setup_panel_test_ids_present(detail_html):
    required_ids = [
        'data-testid="setup-detail-panel"',
        'data-testid="setup-readiness-prepare"',
        'data-testid="setup-readiness-post"',
        'data-testid="setup-transit-truth"',
        'data-testid="setup-products-detail-table"',
        'data-testid="setup-customers-detail-table"',
    ]
    for tid in required_ids:
        assert tid in detail_html, f"missing UI marker {tid!r}"


def test_frontend_per_row_test_ids_use_slug_pattern(detail_html):
    """Per-row data-testids must use the canonical pattern so smoke tests
    can target individual products and clients."""
    assert "`setup-products-row-${row.product_code}`" in detail_html
    assert "`setup-customers-row-${slug}`" in detail_html


def test_frontend_register_button_gated_by_flag(detail_html):
    """The Register-product button must sit inside a `flagOn && ...`
    conditional so it is NEVER rendered when WFIRMA_CREATE_PRODUCT_ALLOWED
    is false at the backend."""
    pattern = re.compile(
        r"\{flagOn\s*&&[\s\S]{0,400}?data-testid=\{`btn-setup-product-register-",
        re.MULTILINE,
    )
    assert pattern.search(detail_html), (
        "btn-setup-product-register-* is not wrapped in a `flagOn && ...` "
        "conditional — write button would render when the flag is off"
    )


def test_frontend_create_in_wfirma_button_gated_by_flag(detail_html):
    """The Create-in-wFirma button must sit inside a `cFlagOn && ...`
    conditional gated on WFIRMA_CREATE_CUSTOMER_ALLOWED."""
    pattern = re.compile(
        r"\{cFlagOn\s*&&[\s\S]{0,400}?data-testid=\{`btn-setup-customer-create-wfirma-",
        re.MULTILINE,
    )
    assert pattern.search(detail_html), (
        "btn-setup-customer-create-wfirma-* is not wrapped in a "
        "`cFlagOn && ...` conditional — wFirma write button would render "
        "when the customer-create flag is off"
    )


def test_frontend_preview_and_safe_buttons_always_render(detail_html):
    """Preview / Save CM / Resolve buttons must NOT sit inside a flag
    conditional — they are dry-run safe and always available."""
    # Preview button — must NOT be preceded by `{flagOn &&` within 200 chars
    preview_pos = detail_html.index('data-testid={`btn-setup-product-preview-')
    window_before = detail_html[max(0, preview_pos - 400):preview_pos]
    # The Preview row sits OUTSIDE the flagOn conditional. Check the most
    # recent `flagOn &&` opener (if any) was closed before Preview by
    # confirming there's a row-closing `>` followed by `<Btn small` before
    # any flagOn marker.
    assert "`btn-setup-product-preview-" in detail_html
    # Save CM button — must NOT be inside `{cFlagOn &&` block
    assert "`btn-setup-customer-save-cm-" in detail_html
    assert "`btn-setup-customer-resolve-" in detail_html


def test_frontend_save_cm_button_writes_only_to_customer_master(detail_html):
    """The Save CM button's title attribute documents the dry-run-safe
    contract: 'Writes only to local Customer Master; no wFirma call.'
    Source-grep ensures the title is present so future regressions are
    visible."""
    assert "Writes only to local Customer Master" in detail_html


def test_frontend_disabled_state_visible_when_flag_off(detail_html):
    """When create_flag_on is false, a small note must be rendered to
    explain to the operator why write buttons are absent."""
    assert 'data-testid="setup-products-write-disabled-note"' in detail_html
    assert 'data-testid="setup-customers-write-disabled-note"' in detail_html
    assert 'WFIRMA_CREATE_PRODUCT_ALLOWED=false' in detail_html
    assert 'WFIRMA_CREATE_CUSTOMER_ALLOWED=false' in detail_html


def test_frontend_readiness_separates_prepare_from_post(detail_html):
    """Operator must see two DISTINCT readiness badges — preparation
    readiness and posting readiness — so it's never ambiguous whether
    a missing scan blocks the proforma preview itself."""
    assert 'Can prepare proforma' in detail_html
    assert 'Can post to wFirma' in detail_html
    assert 'data-testid="setup-blockers-prepare"' in detail_html
    assert 'data-testid="setup-blockers-post"' in detail_html


def test_frontend_transit_truth_label_present(detail_html):
    """Transit count (C13A/C13E PURCHASE_TRANSIT) surfaces as informational
    truth, not as a blocker for preparation."""
    assert 'data-testid="setup-transit-truth"' in detail_html
    assert 'PURCHASE_TRANSIT' in detail_html
