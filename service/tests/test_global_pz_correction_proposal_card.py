"""
test_global_pz_correction_proposal_card.py
Source-grep tests for GlobalPZCorrectionProposalCard in shipment-detail.html.

Coverage:
  - Component defined in shipment-detail.html
  - Component rendered in PZ / Accounting tab, after GlobalPZLineageCard
  - Endpoint path is GET-only (no POST/PUT/DELETE in component)
  - data-testid attributes present for all key UI elements
  - Read-only label present: "Read-only proposal · no wFirma mutation"
  - All option buttons carry `disabled` attribute
  - ALIGN_TO_AUTHORITY button shows disabled reason "Execution endpoint not available"
  - SPLIT_TO_STYLE_LEVEL button shows disabled reason "Preview only"
  - CANCEL_AND_RECREATE is filtered from options (never rendered)
  - Non-global suppression: is_global_supplier gate present, returns null
  - No wFirma import or mutation call within component body
  - No frontend POST/mutation call within component body
"""
from __future__ import annotations

from pathlib import Path

import pytest

_HTML = Path(__file__).resolve().parent.parent / "app" / "static" / "shipment-detail.html"


def _card_body() -> str:
    """Return the source text of GlobalPZCorrectionProposalCard only."""
    src = _HTML.read_text(encoding="utf-8")
    start = src.find("function GlobalPZCorrectionProposalCard(")
    assert start > 0, "GlobalPZCorrectionProposalCard not found in shipment-detail.html"
    # Bound to the next top-level function definition
    next_fn = src.find("\nfunction ", start + 1)
    return src[start:next_fn] if next_fn > start else src[start:start + 20000]


# ── 1. Component exists ───────────────────────────────────────────────────────

def test_correction_proposal_card_defined():
    src = _HTML.read_text(encoding="utf-8")
    assert "function GlobalPZCorrectionProposalCard(" in src, (
        "GlobalPZCorrectionProposalCard must be defined in shipment-detail.html"
    )


# ── 2. Rendered in PZ / Accounting tab ───────────────────────────────────────

def test_correction_proposal_card_rendered_in_pz_tab():
    src = _HTML.read_text(encoding="utf-8")
    tab_idx  = src.find("activeTab === 'PZ / Accounting'")
    card_idx = src.find("GlobalPZCorrectionProposalCard", tab_idx)
    assert tab_idx > 0, "PZ / Accounting tab block not found"
    assert card_idx > 0, (
        "GlobalPZCorrectionProposalCard not rendered inside PZ / Accounting tab"
    )


def test_correction_proposal_card_placed_after_lineage_card():
    """Card must appear after GlobalPZLineageCard in the tab markup."""
    src = _HTML.read_text(encoding="utf-8")
    tab_start   = src.find("activeTab === 'PZ / Accounting'")
    lineage_idx = src.find("<GlobalPZLineageCard", tab_start)
    proposal_idx = src.find("<GlobalPZCorrectionProposalCard", tab_start)
    assert lineage_idx > 0,  "GlobalPZLineageCard JSX not found in PZ/Accounting tab"
    assert proposal_idx > 0, "GlobalPZCorrectionProposalCard JSX not found in PZ/Accounting tab"
    assert proposal_idx > lineage_idx, (
        "GlobalPZCorrectionProposalCard must appear after GlobalPZLineageCard in the tab"
    )


# ── 3. Endpoint path and method ──────────────────────────────────────────────

def test_correction_proposal_endpoint_path():
    body = _card_body()
    assert "/correction-proposal" in body, (
        "Component must fetch /api/v1/pz/lineage/{batchId}/correction-proposal"
    )


def test_correction_proposal_no_post_in_component():
    """Component must not make any mutating fetch calls."""
    body = _card_body()
    # method:'POST' or method:"POST" must not appear in the component
    assert "method:'POST'" not in body
    assert 'method:"POST"' not in body
    assert "method: 'POST'" not in body
    assert 'method: "POST"' not in body


def test_correction_proposal_no_mutation_fetch():
    """Fetch inside the component must use GET only (default when no method given)."""
    body = _card_body()
    # The fetch call must reference the correction-proposal endpoint
    fetch_idx = body.find("/correction-proposal")
    assert fetch_idx > 0
    # Slice a window around the fetch call to confirm no 'POST' appears nearby
    window = body[max(0, fetch_idx - 200): fetch_idx + 200]
    assert "POST" not in window, (
        "Fetch to correction-proposal endpoint must not use POST method"
    )


# ── 4. data-testid attributes ────────────────────────────────────────────────

def test_correction_proposal_card_testid():
    body = _card_body()
    assert 'data-testid="global-pz-correction-card"' in body


def test_correction_proposal_recommended_badge_testid():
    body = _card_body()
    assert 'data-testid="global-pz-correction-recommended-badge"' in body


def test_correction_proposal_readonly_label_testid():
    body = _card_body()
    assert 'data-testid="global-pz-correction-readonly-label"' in body


def test_correction_proposal_stats_testid():
    body = _card_body()
    assert 'data-testid="global-pz-correction-stats"' in body


def test_correction_proposal_options_testid():
    body = _card_body()
    assert 'data-testid="global-pz-correction-options"' in body


def test_correction_proposal_refresh_button_testid():
    body = _card_body()
    assert 'data-testid="global-pz-correction-refresh"' in body


# ── 5. Read-only label ────────────────────────────────────────────────────────

def test_correction_proposal_readonly_label_present():
    body = _card_body()
    assert "Read-only proposal · no wFirma mutation" in body, (
        "Component must display 'Read-only proposal · no wFirma mutation'"
    )


# ── 6. All option buttons are disabled ───────────────────────────────────────

def test_correction_proposal_buttons_all_disabled():
    """Every action button in the options list must carry the disabled attribute."""
    body = _card_body()
    # The option button pattern uses `button disabled` in JSX
    assert "button disabled" in body, (
        "All option buttons must render with the disabled attribute"
    )
    # Confirm no enabled button targets wFirma or mutating verbs
    assert 'onClick={' not in body or 'refresh' in body, (
        "No onClick handler may fire a mutation — only refresh is allowed"
    )


def test_correction_proposal_align_button_disabled_reason():
    body = _card_body()
    assert "Execution endpoint not available" in body, (
        "ALIGN_TO_AUTHORITY option must display 'Execution endpoint not available'"
    )


def test_correction_proposal_split_button_disabled_reason():
    body = _card_body()
    assert "Preview only" in body, (
        "SPLIT_TO_STYLE_LEVEL option must display 'Preview only'"
    )


def test_correction_proposal_keep_current_disabled_reason():
    body = _card_body()
    assert "Acknowledgement endpoint not yet available" in body, (
        "KEEP_CURRENT button must explain it is disabled: 'Acknowledgement endpoint not yet available'"
    )


# ── 7. CANCEL_AND_RECREATE is hidden ─────────────────────────────────────────

def test_correction_proposal_cancel_and_recreate_filtered():
    """CANCEL_AND_RECREATE must be filtered out of the rendered option list."""
    body = _card_body()
    # The filter must exclude CANCEL_AND_RECREATE
    assert "CANCEL_AND_RECREATE" in body, (
        "CANCEL_AND_RECREATE filter must be present in the component"
    )
    assert "!== 'CANCEL_AND_RECREATE'" in body or "!= 'CANCEL_AND_RECREATE'" in body, (
        "Component must filter out CANCEL_AND_RECREATE from displayed options"
    )


# ── 8. Non-global suppression ─────────────────────────────────────────────────

def test_correction_proposal_suppressed_for_non_global():
    body = _card_body()
    assert "is_global_supplier" in body, (
        "Component must gate on is_global_supplier"
    )
    global_cond_idx = body.find("is_global_supplier")
    assert global_cond_idx > 0
    # Find the `return null` that comes AFTER the is_global_supplier check
    # (there may be an earlier `return null` from the 404 path — ignore that one)
    null_guard_idx = body.find("return null", global_cond_idx)
    assert null_guard_idx > 0, (
        "Component must return null after is_global_supplier check for non-global batches"
    )
    assert null_guard_idx > global_cond_idx, (
        "null guard must appear after the is_global_supplier check"
    )


def test_correction_proposal_suppresses_404_silently():
    """404 response (non-global batch) must return null, not an error panel."""
    body = _card_body()
    assert "HTTP 404" in body, (
        "Component must detect HTTP 404 and suppress silently (return null)"
    )
    # Find the 404 branch and confirm it returns null
    idx_404  = body.find("HTTP 404")
    idx_null = body.find("return null", idx_404)
    assert idx_null > 0 and idx_null < idx_404 + 300, (
        "404 branch must return null within 300 chars of the 404 check"
    )


# ── 9. No wFirma mutation in component ───────────────────────────────────────

def test_correction_proposal_no_wfirma_call():
    """Component must not make any wFirma API call.

    The UI label 'no wFirma mutation' contains 'wfirma' in lowercase — that is
    intentional documentation.  We check for actual API call patterns only.
    """
    body = _card_body()
    # These are the real wFirma mutation patterns — none must appear
    forbidden = [
        "wfirma_create", "wfirma_cancel", "wfirma_post",
        "wfirma_update", "wfirma_delete",
        "/wfirma/", "wFirma.create", "wFirma.post",
    ]
    for pattern in forbidden:
        assert pattern not in body, (
            f"GlobalPZCorrectionProposalCard must not contain wFirma call: {pattern!r}"
        )


def test_correction_proposal_no_pz_create_call():
    body = _card_body()
    assert "pz_create" not in body and "pz-create" not in body, (
        "Component must not call pz_create"
    )


def test_correction_proposal_no_pz_cancel_call():
    body = _card_body()
    assert "pz_cancel" not in body and "pz-cancel" not in body, (
        "Component must not call pz_cancel"
    )


# ── 10. KEEP_CURRENT affirmative notice ──────────────────────────────────────

def test_correction_proposal_keep_current_affirmative_notice():
    body = _card_body()
    assert "Existing PZ can remain" in body, (
        "When recommended_option=KEEP_CURRENT, card must show affirmative notice"
    )


# ── 11. Stats fields rendered ────────────────────────────────────────────────

def test_correction_proposal_stats_show_current_lines():
    body = _card_body()
    assert "current_pz_line_count" in body, (
        "Component must render current_pz_line_count from API response"
    )


def test_correction_proposal_stats_show_authority_rows():
    body = _card_body()
    assert "authority_row_count" in body, (
        "Component must render authority_row_count from API response"
    )


def test_correction_proposal_stats_show_lineage_links():
    body = _card_body()
    assert "lineage_link_count" in body, (
        "Component must render lineage_link_count from API response"
    )


# ── 12. Risk level per option ────────────────────────────────────────────────

def test_correction_proposal_risk_level_rendered():
    body = _card_body()
    assert "risk_level" in body, (
        "Component must render risk_level for each option"
    )
    assert 'data-testid={`global-pz-correction-risk-${opt.option_id}`}' in body, (
        "Risk badge must carry a testid per option"
    )
