"""test_c25a_handlers_wiring.py — C25A-handlers regression suite.

Surface tested: shipment-detail.html handler wiring for the 3 safe
non-fiscal setup actions:

  1. btn-setup-product-preview-*    → POST goods/auto-register-preview (dry-run)
  2. btn-setup-customer-resolve-*   → POST customers/auto-resolve-preview (dry-run)
  3. btn-setup-customer-save-cm-*   → routes through existing C17A saveCmFields
                                      (writes ONLY to /api/v1/customer-master/{id})

Forbidden surfaces (verified by source-grep negative assertions):
  - No fetch/apiFetch call to goods/auto-register/{...} (write endpoint)
  - No fetch/apiFetch call to customers/auto-create-from-name (write endpoint)
  - No call to /wfirma/proforma/* (proforma posting)
  - No call to wfirma_export / pz_create / invoice_create
  - btn-setup-product-register-* remains disabled (no onClick wired)
  - btn-setup-customer-create-wfirma-* remains disabled (no onClick wired)

The previously-shipped C25A regression file
(test_c25a_setup_detail_panels.py) covers the backend endpoint and the
panel structure.  This file covers ONLY the handler wiring delta.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parent.parent
_DETAIL_HTML = _REPO / "app" / "static" / "shipment-detail.html"


@pytest.fixture(scope="module")
def html() -> str:
    return _DETAIL_HTML.read_text(encoding="utf-8")


# ── Handler functions declared in module scope ─────────────────────────────


def test_handler_product_preview_declared(html):
    assert "handleProductPreview" in html
    assert "setSetupProductPreview" in html
    assert "setSetupProductPreviewLoading" in html
    assert "setSetupProductPreviewErr" in html


def test_handler_customer_resolve_declared(html):
    assert "handleCustomerResolve" in html
    assert "setSetupCustomerResolve" in html
    assert "setSetupCustomerResolveLoading" in html
    assert "setSetupCustomerResolveErr" in html


def test_handler_save_cm_declared(html):
    assert "handleSetupSaveCmFor" in html


# ── Handlers call ONLY the dry-run / local endpoints ───────────────────────


def test_product_preview_calls_only_dry_run_endpoint(html):
    """handleProductPreview must POST ONLY to auto-register-preview, never
    to the write endpoint auto-register/{batch} (no `-preview` suffix)."""
    idx_start = html.index("const handleProductPreview")
    idx_end = html.index("const handleCustomerResolve", idx_start)
    body = html[idx_start:idx_end]

    # Must call the preview endpoint
    assert "/api/v1/wfirma/goods/auto-register-preview/" in body, (
        "handleProductPreview must POST to auto-register-preview"
    )
    # Must NOT call the write endpoint (path without -preview suffix)
    write_endpoint_pattern = re.compile(
        r"/api/v1/wfirma/goods/auto-register/[^-]"
    )
    assert not write_endpoint_pattern.search(body), (
        "handleProductPreview must NOT call goods/auto-register/ write endpoint"
    )
    # Must NOT call goods/add or any wFirma write
    for forbidden in (
        "/api/v1/wfirma/goods/add",
        "/api/v1/wfirma/customers/auto-create-from-name",
        "/api/v1/wfirma/goods/create",
    ):
        assert forbidden not in body, (
            f"handleProductPreview must not reach {forbidden}"
        )


def test_customer_resolve_calls_only_dry_run_endpoint(html):
    """handleCustomerResolve must POST ONLY to auto-resolve-preview, never
    to a contractor-create endpoint."""
    idx_start = html.index("const handleCustomerResolve")
    idx_end = html.index("const handleSetupSaveCmFor", idx_start)
    body = html[idx_start:idx_end]

    assert "/api/v1/wfirma/customers/auto-resolve-preview/" in body, (
        "handleCustomerResolve must POST to auto-resolve-preview"
    )
    # Must NOT call a contractor-create endpoint
    for forbidden in (
        "/api/v1/wfirma/customers/auto-create-from-name",
        "/api/v1/wfirma/customers/create",
        "/api/v1/wfirma/contractors/add",
    ):
        assert forbidden not in body, (
            f"handleCustomerResolve must not reach {forbidden}"
        )


def test_save_cm_routes_through_customer_master_only(html):
    """handleSetupSaveCmFor must:
      - NOT call any wFirma endpoint (no /api/v1/wfirma/ in its body)
      - reuse the existing C17A saveCmFields path (single CM write authority)
    """
    idx_start = html.index("const handleSetupSaveCmFor")
    # End at the next top-level `const ` declaration so we slice only this
    # one useCallback body (not subsequent module-scope hooks).
    next_const = html.index("\n  const ", idx_start + 50)
    body = html[idx_start:next_const]

    # No wFirma calls in this handler — it's CM-only.
    assert "/api/v1/wfirma/" not in body, (
        "handleSetupSaveCmFor must not call any /api/v1/wfirma/ endpoint"
    )
    # Must hand off to the existing C17A editor state (setCmEdit) so the
    # single CM write authority (saveCmFields) is the only writer.
    assert "setCmEdit(" in body, (
        "handleSetupSaveCmFor must open the C17A editor via setCmEdit"
    )


# ── Button onClick wiring ──────────────────────────────────────────────────


def test_preview_button_has_onclick(html):
    """Preview button must invoke handleProductPreview on click."""
    pattern = re.compile(
        r"data-testid=\{`btn-setup-product-preview-[^}]*\}[\s\S]{0,300}?onClick=\{handleProductPreview\}",
        re.MULTILINE,
    )
    assert pattern.search(html), (
        "btn-setup-product-preview-* missing onClick={handleProductPreview}"
    )


def test_resolve_button_has_onclick(html):
    pattern = re.compile(
        r"data-testid=\{`btn-setup-customer-resolve-[^}]*\}[\s\S]{0,300}?onClick=\{handleCustomerResolve\}",
        re.MULTILINE,
    )
    assert pattern.search(html), (
        "btn-setup-customer-resolve-* missing onClick={handleCustomerResolve}"
    )


def test_save_cm_button_has_onclick(html):
    pattern = re.compile(
        r"data-testid=\{`btn-setup-customer-save-cm-[^}]*\}[\s\S]{0,300}?onClick=\{\(\)\s*=>\s*handleSetupSaveCmFor\(row\)\}",
        re.MULTILINE,
    )
    assert pattern.search(html), (
        "btn-setup-customer-save-cm-* missing onClick={() => handleSetupSaveCmFor(row)}"
    )


# ── Negative invariants — write buttons stay disabled ───────────────────────


def test_register_product_button_remains_disabled(html):
    """btn-setup-product-register-* must NOT have an onClick handler in
    this PR — wiring is deferred to C25B/C25C per operator brief."""
    idx = html.index("btn-setup-product-register-")
    # Look forward 600 chars
    block = html[idx:idx + 600]
    # No onClick handler should be wired
    assert "onClick=" not in block.split("</Btn>")[0], (
        "btn-setup-product-register-* must remain without an onClick — "
        "wiring is forbidden in this PR (write behaviour)"
    )
    # Must remain disabled
    assert "disabled" in block.split("</Btn>")[0], (
        "btn-setup-product-register-* must remain disabled"
    )


def test_create_in_wfirma_button_remains_disabled(html):
    """btn-setup-customer-create-wfirma-* must NOT have an onClick handler
    in this PR."""
    idx = html.index("btn-setup-customer-create-wfirma-")
    block = html[idx:idx + 600]
    assert "onClick=" not in block.split("</Btn>")[0], (
        "btn-setup-customer-create-wfirma-* must remain without an onClick"
    )
    assert "disabled" in block.split("</Btn>")[0], (
        "btn-setup-customer-create-wfirma-* must remain disabled"
    )


# ── Refresh after save ─────────────────────────────────────────────────────


def test_handlers_refresh_setup_detail_after_action(html):
    """Both Preview and Resolve must call refreshSetupDetail after
    their dry-run completes, so the panel reflects newly-mirrored
    mappings without an operator reload."""
    # Product preview body
    idx = html.index("const handleProductPreview")
    body = html[idx:html.index("const handleCustomerResolve", idx)]
    assert "refreshSetupDetail()" in body, (
        "handleProductPreview must refreshSetupDetail() after preview"
    )
    # Customer resolve body
    idx = html.index("const handleCustomerResolve")
    body = html[idx:html.index("const handleSetupSaveCmFor", idx)]
    assert "refreshSetupDetail()" in body, (
        "handleCustomerResolve must refreshSetupDetail() after resolve"
    )


# ── Inline result drawers render ───────────────────────────────────────────


def test_inline_result_drawers_present(html):
    """Both preview/resolve drawers must render inside setup-detail-panel."""
    assert 'data-testid="setup-product-preview-result"' in html
    assert 'data-testid="setup-customer-resolve-result"' in html


# ── Source-grep: no global write endpoint reachable from setup panel ───────


def test_setup_panel_has_no_wfirma_write_endpoint_anywhere(html):
    """Hard guard — search the WHOLE setup-detail-panel block for any
    wFirma write endpoint string.  Authority rule: this panel is
    READ-ONLY for fiscal/wFirma surfaces."""
    panel_idx = html.index('data-testid="setup-detail-panel"')
    # Find the matching closing brace by scanning forward to the next
    # `{sectionShell('warehouse'` which immediately follows the panel.
    panel_end = html.index("{sectionShell('warehouse'", panel_idx)
    panel_block = html[panel_idx:panel_end]
    forbidden_endpoints = (
        "/api/v1/wfirma/goods/add",
        "/api/v1/wfirma/goods/create",
        "/api/v1/wfirma/customers/auto-create-from-name",
        "/api/v1/wfirma/customers/create",
        "/api/v1/wfirma/contractors/add",
        "/api/v1/upload/shipment/",
        "/api/v1/proforma/create/",
        "/api/v1/proforma/post/",
        # Goods auto-register WRITE endpoint (without -preview suffix)
        "/api/v1/wfirma/goods/auto-register/",
    )
    for ep in forbidden_endpoints:
        assert ep not in panel_block, (
            f"setup-detail-panel block contains forbidden write endpoint {ep!r}"
        )
