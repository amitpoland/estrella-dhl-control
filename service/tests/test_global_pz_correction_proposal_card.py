"""
test_global_pz_correction_proposal_card.py
Source-grep tests for GlobalPZCorrectionProposalCard in shipment-detail.html.

Coverage:
  - Component defined in shipment-detail.html
  - Component rendered in PZ / Accounting tab, after GlobalPZLineageCard
  - Proposal endpoint path is GET (correction-proposal)
  - Execution endpoint path is POST (correction-execute)
  - data-testid attributes present for all key UI elements
  - "No wFirma mutation" label present (no direct wFirma calls)
  - Action buttons are enabled with onClick handlers (not statically disabled)
  - Inline confirmation modal present (data-testid="global-pz-correction-confirm-modal")
  - Reason input field present (data-testid="global-pz-correction-reason-input")
  - Confirm/cancel buttons present
  - Execution disabled while executing (reason.trim() guard)
  - CANCEL_AND_RECREATE is filtered from options (never rendered)
  - Non-global suppression: is_global_supplier gate present, returns null
  - 404 → return null silently
  - No wFirma import or mutation call within component body
  - No pz_create or pz_cancel call within component body
  - KEEP_CURRENT affirmative notice present
  - Stats fields (current_pz_line_count, authority_row_count, lineage_link_count)
  - Risk level rendered per option
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
    tab_start    = src.find("activeTab === 'PZ / Accounting'")
    lineage_idx  = src.find("<GlobalPZLineageCard", tab_start)
    proposal_idx = src.find("<GlobalPZCorrectionProposalCard", tab_start)
    assert lineage_idx > 0,  "GlobalPZLineageCard JSX not found in PZ/Accounting tab"
    assert proposal_idx > 0, "GlobalPZCorrectionProposalCard JSX not found in PZ/Accounting tab"
    assert proposal_idx > lineage_idx, (
        "GlobalPZCorrectionProposalCard must appear after GlobalPZLineageCard in the tab"
    )


# ── 3. Endpoint paths ─────────────────────────────────────────────────────────

def test_correction_proposal_endpoint_path():
    body = _card_body()
    assert "/correction-proposal" in body, (
        "Component must fetch /api/v1/pz/lineage/{batchId}/correction-proposal"
    )


def test_correction_execute_endpoint_path():
    body = _card_body()
    assert "/correction-execute" in body, (
        "Component must POST to /api/v1/pz/lineage/{batchId}/correction-execute"
    )


def test_correction_execute_uses_post_method():
    """Execution fetch must use POST method."""
    body = _card_body()
    exec_idx = body.find("/correction-execute")
    assert exec_idx > 0, "correction-execute endpoint not found"
    # Inspect the window around the execute fetch call
    window = body[max(0, exec_idx - 300): exec_idx + 100]
    assert "POST" in window, (
        "Fetch to correction-execute must use method: 'POST'"
    )


def test_correction_proposal_fetch_is_get():
    """Proposal fetch must NOT use POST (default GET is correct)."""
    body = _card_body()
    proposal_idx = body.find("/correction-proposal")
    assert proposal_idx > 0
    window = body[max(0, proposal_idx - 200): proposal_idx + 200]
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


def test_correction_proposal_confirm_modal_testid():
    body = _card_body()
    assert 'data-testid="global-pz-correction-confirm-modal"' in body, (
        "Inline confirmation panel must have data-testid='global-pz-correction-confirm-modal'"
    )


def test_correction_proposal_reason_input_testid():
    body = _card_body()
    assert 'data-testid="global-pz-correction-reason-input"' in body, (
        "Reason textarea must have data-testid='global-pz-correction-reason-input'"
    )


def test_correction_proposal_confirm_btn_testid():
    body = _card_body()
    assert 'data-testid="global-pz-correction-confirm-btn"' in body, (
        "Confirm execution button must have data-testid='global-pz-correction-confirm-btn'"
    )


def test_correction_proposal_cancel_btn_testid():
    body = _card_body()
    assert 'data-testid="global-pz-correction-cancel-btn"' in body, (
        "Cancel button must have data-testid='global-pz-correction-cancel-btn'"
    )


def test_correction_proposal_result_testid():
    body = _card_body()
    assert 'data-testid="global-pz-correction-result"' in body, (
        "Execution result banner must have data-testid='global-pz-correction-result'"
    )


# ── 5. No wFirma mutation label ───────────────────────────────────────────────

def test_correction_proposal_no_wfirma_mutation_label():
    body = _card_body()
    assert "No wFirma mutation" in body, (
        "Component must display 'No wFirma mutation' label"
    )


def test_correction_proposal_local_staging_label():
    body = _card_body()
    assert "local staging only" in body or "local pz_rows" in body, (
        "Component must clarify that execution targets local staging only"
    )


# ── 6. Buttons are enabled with onClick handlers ──────────────────────────────

def test_correction_proposal_buttons_have_onclick():
    """Action buttons must have onClick handlers (not statically disabled)."""
    body = _card_body()
    assert "onClick={() => setConfirmOpt" in body, (
        "Option buttons must have onClick handlers that open confirmation"
    )


def test_correction_proposal_confirm_btn_calls_handleExecute():
    body = _card_body()
    assert "onClick={handleExecute}" in body, (
        "Confirm execution button must call handleExecute"
    )


def test_correction_proposal_executing_guard():
    """Confirm button must be disabled while executing."""
    body = _card_body()
    assert "executing" in body, (
        "Component must track executing state to prevent double-submit"
    )
    assert "reason.trim()" in body, (
        "Confirm button must be disabled when reason is empty"
    )


# ── 7. CANCEL_AND_RECREATE is hidden ─────────────────────────────────────────

def test_correction_proposal_cancel_and_recreate_filtered():
    """CANCEL_AND_RECREATE must be filtered out of the rendered option list."""
    body = _card_body()
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

    The UI label 'No wFirma mutation' contains 'wFirma' — intentional documentation.
    We check for actual API call patterns only.
    """
    body = _card_body()
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


# ── 13. Execution result display ─────────────────────────────────────────────

def test_correction_proposal_already_executed_message():
    body = _card_body()
    assert "already_executed" in body, (
        "Component must handle already_executed flag in execution result"
    )
    assert "Already executed" in body, (
        "Component must display 'Already executed' message when result.already_executed"
    )


def test_correction_proposal_result_shows_line_counts():
    body = _card_body()
    assert "pre_line_count" in body and "post_line_count" in body, (
        "Execution result must show pre_line_count and post_line_count"
    )


# ── 14. Confirmation panel content ───────────────────────────────────────────

def test_correction_proposal_confirm_explains_no_wfirma():
    body = _card_body()
    # Confirmation panel must warn operator about no wFirma calls
    assert "No wFirma calls" in body or "no wFirma" in body.lower(), (
        "Confirmation panel must clarify no wFirma calls are made"
    )


def test_correction_proposal_confirm_explains_backup():
    body = _card_body()
    assert "backup" in body.lower(), (
        "Confirmation panel must mention automatic backup"
    )
