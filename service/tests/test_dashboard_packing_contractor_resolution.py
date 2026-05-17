"""test_dashboard_packing_contractor_resolution.py — B0.X R3 UI contract.

Source-grep tests for the Contractor Resolution panel inserted into
BatchDetailPage. Confirms:
- panel + testids present
- panel inserted between Packing List card and Document Registry
- both client and supplier role cards rendered
- Resolve / Confirm / Open / Create-new buttons present with correct testids
- panel wires only the R2 API routes (no proforma / PZ / master writes)
- Create-new button is disabled
- legacy packing UI still renders
"""
from __future__ import annotations

from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DASH      = _REPO_ROOT / "service" / "app" / "static" / "dashboard.html"


def _src() -> str:
    if not _DASH.exists():
        pytest.skip("dashboard.html missing")
    return _DASH.read_text(encoding="utf-8", errors="replace")


# ── Panel presence + placement ────────────────────────────────────────────


def test_panel_testid_present():
    src = _src()
    assert 'data-testid="contractor-resolution-panel"' in src, \
        "Contractor resolution panel must render with the canonical testid"


def test_panel_inserted_between_packing_card_and_document_registry():
    """Panel anchor must sit between 'packing-list-card' and the Document
    Registry section."""
    src = _src()
    packing_idx = src.index('data-testid="packing-list-card"')
    registry_idx = src.index("Document Registry (per-batch, read-only)")
    panel_anchor = '<ContractorResolutionPanel'
    panel_idx = src.index(panel_anchor)
    assert packing_idx < panel_idx < registry_idx, \
        "ContractorResolutionPanel must be rendered AFTER the packing list card and BEFORE the Document Registry"


def test_client_and_supplier_role_cards_rendered():
    src = _src()
    assert 'data-testid={`contractor-resolution-${role}-card`}' in src, \
        "Role card template must use the testid pattern"
    # Both role props passed in the panel composer:
    assert 'role="client"' in src and 'role="supplier"' in src


def test_role_testids_use_canonical_set():
    """Every role-scoped testid in the new panel uses the
    contractor-resolution-{role}-* prefix."""
    src = _src()
    for suffix in (
        "card", "status", "tier", "loading", "error", "empty",
        "parsed-name", "matched", "override",
        "resolve-btn", "confirm-btn", "open-master-btn",
        "create-new-btn", "unresolved-warning",
    ):
        # Templated form (used inside the React component)
        templ = f'data-testid={{`contractor-resolution-${{role}}-{suffix}`}}'
        assert templ in src, f"role testid template missing: {suffix}"


# ── Routes wired (R2 only — no master writes, no proforma) ────────────────


def test_panel_calls_only_r2_routes():
    """The Contractor Resolution component must call only the R2 endpoints.
    Source-grep verifies the three URL literals are present in the
    component definition and no master-write URL is."""
    src = _src()
    start = src.index("function ContractorResolutionRoleCard(")
    end = src.index("function BatchDetailPage(")
    block = src[start: end]
    # Must call:
    assert "/contractor-resolution/${role}" in block or \
           "/contractor-resolution/" in block, \
        "panel must read /contractor-resolution/{role}"
    assert "/contractor-resolution`" in block or \
           "/contractor-resolution\"" in block or \
           "/contractor-resolution'" in block or \
           "contractor-resolution`," in block, \
        "panel must POST /contractor-resolution"
    assert "/contractor-resolution/confirm" in block, \
        "panel must POST /contractor-resolution/confirm"
    # Must NOT call:
    for forbidden in (
        "/api/v1/customer-master/",       # master CRUD
        "/api/v1/suppliers/",             # supplier CRUD
        "/api/v1/wfirma/",                # wFirma write surface
        "/api/v1/proforma/",
        "/api/v1/pz/",
        "/api/v1/dhl/",
        "/api/v1/finance/",
    ):
        assert forbidden not in block, \
            f"contractor-resolution component must not call {forbidden}"


def test_create_new_button_disabled():
    src = _src()
    start = src.index('data-testid={`contractor-resolution-${role}-create-new-btn`}')
    # Take ~600 chars from the testid forward — must contain `disabled` and
    # cursor not-allowed (visual cue for disabled state).
    block = src[start: start + 600]
    assert "disabled" in block, "Create-new button must be disabled"
    assert "not-allowed" in block, \
        "Create-new button must have not-allowed cursor (disabled visual)"


def test_create_new_button_carries_reason_in_title():
    src = _src()
    start = src.index('data-testid={`contractor-resolution-${role}-create-new-btn`}')
    block = src[start: start + 800]
    assert "Create-new path is disabled in R3" in block, \
        "Create-new button must explain why it is disabled (operator clarity)"


def test_unresolved_warning_blocks_proforma_pz():
    """When status=unresolved, the panel must render a visible warning so
    the operator knows proforma/PZ cannot consume the contractor yet."""
    src = _src()
    assert "Operator must pick a candidate" in src, \
        "unresolved warning copy must guide the operator"


def test_status_badge_present():
    src = _src()
    assert 'data-testid={`contractor-resolution-${role}-status`}' in src, \
        "status badge testid template required"
    # Each canonical status must have a colour-coded path in the resolution
    # panel's statusStyle helper. Locate it via the unique
    # `const statusStyle = (s) =>` signature (avoids colliding with the
    # WfReviewPanel's `const statusStyles = { ... }` constant).
    block_start = src.index("const statusStyle = (s) =>")
    block_end   = src.index("return map[s]", block_start)
    block = src[block_start: block_end]
    for s in ("auto", "unresolved", "confirmed", "overridden"):
        assert f"{s}:" in block, f"resolution-panel statusStyle missing colour for {s!r}"


def test_override_dropdown_uses_candidates_list():
    src = _src()
    # The select with the override testid is populated from verdict.candidates
    start = src.index('data-testid={`contractor-resolution-${role}-override`}')
    block = src[start: start + 1200]
    assert "verdict.candidates" in block, \
        "Override dropdown must enumerate verdict.candidates"


# ── Existing packing UI still renders ─────────────────────────────────────


def test_existing_packing_list_card_still_present():
    src = _src()
    assert 'data-testid="packing-list-card"'  in src
    assert 'data-testid="packing-list-upload-input"' in src
    assert 'data-testid="packing-list-empty-state"'  in src
    assert 'data-testid="packing-list-status"'       in src


def test_document_registry_still_present():
    src = _src()
    assert "Document Registry (per-batch, read-only)" in src
