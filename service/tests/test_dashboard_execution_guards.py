"""
test_dashboard_execution_guards.py — Source-grep tests for execution guards
on write actions in the dashboard.

Three guarded actions:
  1. wFirma create reservation  — disabled when document not ready or batch blocked
  2. Closure evaluate           — disabled when PZ not generated or batch completed
  3. Action proposal approve    — disabled when PZ missing or batch completed

Pattern: read dashboard.html as text + assert structural markers.
No JSX execution.
"""
from __future__ import annotations

import re
from pathlib import Path

DASHBOARD = Path(
    "/Users/amitgupta/Downloads/CLI/service/app/static/dashboard.html"
)


def _src() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# wFirma create guard
# ─────────────────────────────────────────────────────────────────────────────

def test_wfirma_create_btn_testid():
    """data-testid='wfirma-create-btn' must be present on the Create Reservation button."""
    src = _src()
    assert (
        'data-testid="wfirma-create-btn"' in src
        or "data-testid='wfirma-create-btn'" in src
    ), "wfirma-create-btn testid not found"


def test_wfirma_create_disabled_reason_testid():
    """data-testid='wfirma-create-disabled-reason' must be present for the disable reason."""
    src = _src()
    assert (
        'data-testid="wfirma-create-disabled-reason"' in src
        or "data-testid='wfirma-create-disabled-reason'" in src
    ), "wfirma-create-disabled-reason testid not found"


def test_wfirma_create_btn_disabled_prop():
    """Create Reservation button must use a computed disabled value (not always false)."""
    src = _src()
    idx = src.find('data-testid="wfirma-create-btn"')
    if idx == -1:
        idx = src.find("data-testid='wfirma-create-btn'")
    assert idx != -1
    # Grab surrounding context — the disabled= attribute must appear nearby
    snippet = src[max(0, idx - 200):idx + 400]
    assert "disabled={isDisabled}" in snippet or "disabled={" in snippet, (
        "Create Reservation button must bind disabled to a computed variable"
    )


def test_wfirma_create_has_batch_level_gate():
    """wFirma create must check batchReadiness.wfirma.status === 'blocked'."""
    src = _src()
    assert "batchWfirmaBlocked" in src, (
        "Batch-level wFirma blocked check (batchWfirmaBlocked) not found"
    )
    assert "batchReadiness.wfirma" in src and "status === 'blocked'" in src, (
        "batchReadiness.wfirma.status === 'blocked' check not found"
    )


def test_wfirma_create_does_not_call_api_when_disabled():
    """Create Reservation button must NOT POST when disabled — onClick only opens modal."""
    src = _src()
    idx = src.find('data-testid="wfirma-create-btn"')
    if idx == -1:
        idx = src.find("data-testid='wfirma-create-btn'")
    assert idx != -1
    snippet = src[max(0, idx - 300):idx + 500]
    # The button must open a confirmation modal (setCreateConfirm), not call apiFetch directly
    assert "setCreateConfirm" in snippet, (
        "Create Reservation button must open confirmation modal, not POST directly"
    )
    # Direct POST must NOT be in the button's onClick
    assert "apiFetch" not in snippet.split("onClick")[1].split(">")[0], (
        "apiFetch must not be in button's onClick — must go through confirm modal"
    )


def test_wfirma_create_disabled_reason_shown_when_not_can_create():
    """Disabled reason must be rendered when canCreate is false."""
    src = _src()
    # The reason is inside a conditional that checks !canCreate
    assert "!canCreate" in src, "canCreate check not found in wFirma section"
    assert "wfirma-create-disabled-reason" in src, (
        "Disabled reason element must be present for !canCreate state"
    )


# ─────────────────────────────────────────────────────────────────────────────
# wFirma confirmation modal guard
# ─────────────────────────────────────────────────────────────────────────────

def test_wfirma_confirm_modal_testid():
    """data-testid='wfirma-confirm-modal' must be present on the confirmation modal."""
    src = _src()
    assert (
        'data-testid="wfirma-confirm-modal"' in src
        or "data-testid='wfirma-confirm-modal'" in src
    ), "wfirma-confirm-modal testid not found"


def test_wfirma_confirm_submit_btn_testid():
    """data-testid='wfirma-confirm-submit-btn' must be present on the Confirm & Create button."""
    src = _src()
    assert (
        'data-testid="wfirma-confirm-submit-btn"' in src
        or "data-testid='wfirma-confirm-submit-btn'" in src
    ), "wfirma-confirm-submit-btn testid not found"


def test_wfirma_confirm_modal_has_cancel():
    """Confirmation modal must have a Cancel button."""
    src = _src()
    idx = src.find('data-testid="wfirma-confirm-modal"')
    if idx == -1:
        idx = src.find("data-testid='wfirma-confirm-modal'")
    assert idx != -1
    # Expand window: modal content + buttons span ~1800 chars from the testid div
    snippet = src[idx:idx + 2000]
    assert "Cancel" in snippet, "Cancel button not found in wFirma confirmation modal"


def test_wfirma_confirm_modal_shows_client_name():
    """Confirmation modal must display client name for operator review."""
    src = _src()
    idx = src.find('data-testid="wfirma-confirm-modal"')
    if idx == -1:
        idx = src.find("data-testid='wfirma-confirm-modal'")
    assert idx != -1
    snippet = src[idx:idx + 800]
    assert "client_name" in snippet or "Client" in snippet, (
        "Confirmation modal must show client name"
    )


def test_wfirma_modal_only_shown_via_createconfirm():
    """wFirma modal must only render when createConfirm is set — not always visible."""
    src = _src()
    assert "createConfirm &&" in src or "{createConfirm &&" in src, (
        "wFirma confirmation modal must be guarded by createConfirm state"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Closure evaluate guard
# ─────────────────────────────────────────────────────────────────────────────

def test_closure_eval_btn_testid():
    """data-testid='closure-eval-btn' must be present."""
    src = _src()
    assert (
        'data-testid="closure-eval-btn"' in src
        or "data-testid='closure-eval-btn'" in src
    ), "closure-eval-btn testid not found"


def test_closure_eval_disabled_reason_testid():
    """data-testid='closure-eval-disabled-reason' must be present."""
    src = _src()
    assert (
        'data-testid="closure-eval-disabled-reason"' in src
        or "data-testid='closure-eval-disabled-reason'" in src
    ), "closure-eval-disabled-reason testid not found"


def test_closure_eval_btn_disabled_when_pz_missing():
    """Closure eval button must be disabled when PZ not generated."""
    src = _src()
    # pzGenerated must be computed from audit
    assert "pzGenerated" in src, "pzGenerated variable not found"
    assert "pz_pdf_filename" in src or "pz_generated_at" in src, (
        "PZ generation detection (pz_pdf_filename or pz_generated_at) not found"
    )
    # The button disabled attribute must reference pzGenerated
    idx = src.find('data-testid="closure-eval-btn"')
    if idx == -1:
        idx = src.find("data-testid='closure-eval-btn'")
    assert idx != -1
    snippet = src[max(0, idx - 100):idx + 400]
    assert "closureEvalDisabled" in snippet or "pzGenerated" in snippet, (
        "closure-eval-btn disabled must reference pzGenerated or closureEvalDisabled"
    )


def test_closure_eval_disabled_when_already_completed():
    """Closure eval button must be disabled when batch is already completed."""
    src = _src()
    assert "batchCompletedStatus" in src, (
        "batchCompletedStatus variable not found in closure eval guard"
    )
    assert "audit.status === 'completed'" in src or 'audit.status === "completed"' in src, (
        "audit.status === 'completed' check not found"
    )


def test_closure_eval_disabled_reason_shown():
    """Disabled reason element must be rendered conditionally, not always."""
    src = _src()
    assert "closureEvalDisabledReason" in src, (
        "closureEvalDisabledReason variable not found"
    )
    # Must be shown conditionally
    assert "closureEvalDisabledReason &&" in src or "&& closureEvalDisabledReason" in src, (
        "closureEvalDisabledReason must be rendered conditionally"
    )


def test_closure_eval_pz_reason_text():
    """PZ not generated reason text must be present in dashboard source."""
    src = _src()
    assert "PZ document must be generated first" in src, (
        "Disabled reason text for missing PZ not found"
    )


def test_closure_eval_completed_reason_text():
    """Batch completed reason text must be present in dashboard source."""
    src = _src()
    assert "already completed" in src.lower() or "Shipment already completed" in src, (
        "Disabled reason text for completed batch not found"
    )


def test_closure_eval_is_read_only():
    """Closure eval card must call /check not /evaluate (read-only endpoint)."""
    src = _src()
    idx = src.find("closure-eval-card")
    snippet = src[idx:idx + 8000]
    assert "/check" in snippet, "/check not found in closure eval card"
    assert "/evaluate" not in snippet, (
        "closure eval card must not call /evaluate — that endpoint writes audit"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Proposal approve guard
# ─────────────────────────────────────────────────────────────────────────────

def test_proposal_approve_btn_testid():
    """data-testid='proposal-approve-btn' must be present on the Approve button."""
    src = _src()
    assert (
        'data-testid="proposal-approve-btn"' in src
        or "data-testid='proposal-approve-btn'" in src
    ), "proposal-approve-btn testid not found"


def test_proposal_approve_disabled_reason_testid():
    """data-testid='proposal-approve-disabled-reason' must be present."""
    src = _src()
    assert (
        'data-testid="proposal-approve-disabled-reason"' in src
        or "data-testid='proposal-approve-disabled-reason'" in src
    ), "proposal-approve-disabled-reason testid not found"


def test_proposal_approve_btn_disabled_prop():
    """Approve button must reference canApprove in its disabled attribute."""
    src = _src()
    idx = src.find('data-testid="proposal-approve-btn"')
    if idx == -1:
        idx = src.find("data-testid='proposal-approve-btn'")
    assert idx != -1
    snippet = src[max(0, idx - 50):idx + 300]
    assert "canApprove" in snippet, (
        "proposal-approve-btn disabled must reference canApprove"
    )
    assert "disabled={" in snippet, (
        "proposal-approve-btn must have a disabled binding"
    )


def test_proposal_approve_canApprove_checks_pz():
    """canApprove computation must check proposalPzReady."""
    src = _src()
    assert "proposalPzReady" in src, "proposalPzReady variable not found"
    assert "canApprove" in src, "canApprove variable not found"


def test_proposal_approve_canApprove_checks_batch_closed():
    """canApprove computation must check proposalBatchClosed."""
    src = _src()
    assert "proposalBatchClosed" in src, "proposalBatchClosed variable not found"


def test_proposal_approve_disabled_reason_pz_text():
    """Approve disabled reason must mention PZ not generated."""
    src = _src()
    assert "PZ not yet generated" in src, (
        "Approve disabled reason for missing PZ not found"
    )


def test_proposal_approve_disabled_reason_completed_text():
    """Approve disabled reason must mention batch completed."""
    src = _src()
    assert "already completed" in src.lower(), (
        "Approve disabled reason for completed batch not found"
    )


def test_proposal_approve_reason_shown_conditionally():
    """Disabled reason must only appear when approveDisabledReason is truthy."""
    src = _src()
    assert "approveDisabledReason" in src, (
        "approveDisabledReason variable not found"
    )
    assert "approveDisabledReason &&" in src or "{approveDisabledReason &&" in src, (
        "approveDisabledReason must be rendered conditionally"
    )


def test_proposal_approve_no_post_when_disabled():
    """When canApprove is false, the disabled attribute prevents onClick from firing.

    The guard pattern is: disabled={busy || !canApprove}
    The onClick still contains proposalAction — the browser's disabled prevents execution.
    This test verifies the guard is on the disabled attribute, not on onClick removal.
    """
    src = _src()
    idx = src.find('data-testid="proposal-approve-btn"')
    if idx == -1:
        idx = src.find("data-testid='proposal-approve-btn'")
    assert idx != -1
    # Grab the full element including onClick handler
    snippet = src[max(0, idx - 80):idx + 600]
    # disabled must reference !canApprove
    assert "!canApprove" in snippet, (
        "canApprove guard must appear in disabled attribute of approve button"
    )
    # proposalAction must be reachable inside the button (disabled attr prevents it, not removal)
    assert "proposalAction" in snippet, (
        "proposalAction call must be inside button's onClick — disabled attribute blocks execution"
    )


def test_tracking_lookup_not_blocked_by_pz_guard():
    """Tracking lookup proposals must not be blocked by the PZ readiness guard."""
    src = _src()
    # isTrackingLookup exempts from canApprove — tracking doesn't need PZ
    assert "isTrackingLookup" in src, "isTrackingLookup not found"
    assert "isTrackingLookup || (" in src or "isTrackingLookup||(proposalPzReady" in src.replace(" ", ""), (
        "canApprove must exempt isTrackingLookup proposals from PZ check"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3.6: decision engine visual integration (advisory only — never gates)
# ─────────────────────────────────────────────────────────────────────────────

def test_wfirma_create_btn_has_primary_action_outline():
    """wFirma create button must apply a green outline when wfirmaPrimary is true."""
    src = _src()
    idx = src.find('data-testid="wfirma-create-btn"')
    if idx == -1:
        idx = src.find("data-testid='wfirma-create-btn'")
    assert idx != -1
    snippet = src[max(0, idx - 200):idx + 600]
    assert "wfirmaPrimary" in snippet, (
        "wfirmaPrimary must be referenced in the wfirma-create-btn style"
    )
    assert "badge-green-border" in snippet, (
        "wfirma create button must use badge-green-border for primary action outline"
    )


def test_wfirma_create_primary_outline_only_when_not_disabled():
    """The green outline must only apply when the button is not disabled."""
    src = _src()
    idx = src.find('data-testid="wfirma-create-btn"')
    if idx == -1:
        idx = src.find("data-testid='wfirma-create-btn'")
    assert idx != -1
    snippet = src[max(0, idx - 200):idx + 600]
    # Must check !isDisabled to avoid green ring on a disabled button
    assert "!isDisabled" in snippet, (
        "wfirma-create-btn primary outline must be gated on !isDisabled"
    )


def test_proposal_card_has_primary_action_indicator():
    """Proposal card must apply a green outline when proposalIsPrimary and isPending."""
    src = _src()
    assert "proposalIsPrimary" in src, "proposalIsPrimary not found in dashboard"
    assert "topProposalId && topProposalId === p.proposal_id" in src, (
        "proposalIsPrimary must match by proposal_id against topProposalId"
    )
    # The Card outline must reference proposalIsPrimary
    idx = src.find("proposalIsPrimary && isPending")
    assert idx != -1, (
        "proposal Card outline must be gated on proposalIsPrimary && isPending"
    )


def test_decision_integration_does_not_change_disabled_logic():
    """Decision advisory must never affect disabled attribute — guards are unchanged."""
    src = _src()
    # canCreate must NOT reference decisionData or wfirmaPrimary in its computation
    idx = src.find("const isDisabled = ")
    assert idx != -1
    snippet = src[idx:idx + 200]
    assert "decisionData" not in snippet, (
        "isDisabled must not reference decisionData — decision is advisory only"
    )
    assert "wfirmaPrimary" not in snippet, (
        "isDisabled must not reference wfirmaPrimary — decision does not gate execution"
    )


def test_decision_integration_does_not_change_can_approve():
    """canApprove computation must NOT reference decisionData."""
    src = _src()
    idx = src.find("const canApprove = ")
    assert idx != -1
    snippet = src[idx:idx + 200]
    assert "decisionData" not in snippet, (
        "canApprove must not reference decisionData — decision is advisory only"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Structural integrity
# ─────────────────────────────────────────────────────────────────────────────

def test_brace_balance():
    """Curly braces in the JS/JSX portion must be balanced."""
    content = DASHBOARD.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
    jsx = max(scripts, key=len)
    opens  = jsx.count("{")
    closes = jsx.count("}")
    assert opens == closes, f"Unbalanced braces: {{ {opens}  }} {closes}"


def test_paren_balance():
    """Parentheses in the JS/JSX portion must be balanced."""
    content = DASHBOARD.read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
    jsx = max(scripts, key=len)
    opens  = jsx.count("(")
    closes = jsx.count(")")
    assert opens == closes, f"Unbalanced parens: ( {opens}  ) {closes}"


# ─────────────────────────────────────────────────────────────────────────────
# DHL reply — execution-engine routing
# ─────────────────────────────────────────────────────────────────────────────
#
# The "Queue Reply to DHL" button must route through the execution engine
# (POST /api/v1/execute/dhl_send_reply) and must NOT call the old direct route
# (POST /api/v1/dhl/send-reply/{batchId}).
#
# All tests are source-grep only — no JSX execution.
# ─────────────────────────────────────────────────────────────────────────────

_DHL_EXEC_URL = "/api/v1/execute/dhl_send_reply"
_DHL_OLD_URL  = "/api/v1/dhl/send-reply/"


def _dhl_handler_snippet(src: str) -> str:
    """Return the full onClick handler body around the execution-engine URL.

    Window: 300 chars before the URL (catches disabled/busy guard on the Btn)
    through 1800 chars after (captures success, skipped, blocked, catch, finally).
    """
    idx = src.find(_DHL_EXEC_URL)
    assert idx != -1, f"{_DHL_EXEC_URL!r} not found in dashboard — routing not wired"
    return src[max(0, idx - 300): idx + 1800]


def test_dhl_reply_old_direct_route_absent():
    """Dashboard must not contain the old direct /api/v1/dhl/send-reply/ path."""
    src = _src()
    assert _DHL_OLD_URL not in src, (
        f"Old direct DHL reply route {_DHL_OLD_URL!r} still present — must be removed"
    )


def test_dhl_reply_execution_engine_url_present():
    """Dashboard must call POST /api/v1/execute/dhl_send_reply."""
    src = _src()
    assert _DHL_EXEC_URL in src, (
        f"Execution-engine DHL reply route {_DHL_EXEC_URL!r} not found in dashboard"
    )


def test_dhl_reply_body_includes_batch_id():
    """Request body must include batch_id: batchId."""
    src = _src()
    snippet = _dhl_handler_snippet(src)
    assert "batch_id: batchId" in snippet, (
        "DHL reply POST body must include 'batch_id: batchId'"
    )


def test_dhl_reply_body_includes_empty_payload():
    """Request body must include payload: {}."""
    src = _src()
    snippet = _dhl_handler_snippet(src)
    assert "payload: {}" in snippet, (
        "DHL reply POST body must include 'payload: {}'"
    )


def test_dhl_reply_success_refreshes_dhl_readiness():
    """Success branch must call loadDhlReadiness() to update DHL state chip."""
    src = _src()
    snippet = _dhl_handler_snippet(src)
    assert "loadDhlReadiness()" in snippet, (
        "DHL reply success branch must call loadDhlReadiness()"
    )


def test_dhl_reply_success_refreshes_batch_readiness():
    """Success branch must call loadBatchReadiness() to update readiness panel."""
    src = _src()
    snippet = _dhl_handler_snippet(src)
    assert "loadBatchReadiness()" in snippet, (
        "DHL reply success branch must call loadBatchReadiness()"
    )


def test_dhl_reply_success_refreshes_decision():
    """Success branch must call loadDecision() to update decision widget."""
    src = _src()
    snippet = _dhl_handler_snippet(src)
    assert "loadDecision()" in snippet, (
        "DHL reply success branch must call loadDecision()"
    )


def test_dhl_reply_refresh_calls_use_promise_all():
    """All three refresh calls must be batched in Promise.all — not sequential awaits."""
    src = _src()
    snippet = _dhl_handler_snippet(src)
    assert "Promise.all(" in snippet, (
        "DHL reply refresh calls must use Promise.all — not sequential awaits"
    )
    # All three loaders must appear inside the same Promise.all block.
    # Grab just the Promise.all(...) call to verify they're co-located.
    pa_idx = snippet.find("Promise.all(")
    assert pa_idx != -1
    pa_snippet = snippet[pa_idx: pa_idx + 200]
    assert "loadDhlReadiness()" in pa_snippet,  "loadDhlReadiness() missing from Promise.all"
    assert "loadBatchReadiness()" in pa_snippet, "loadBatchReadiness() missing from Promise.all"
    assert "loadDecision()" in pa_snippet,       "loadDecision() missing from Promise.all"


def test_dhl_reply_skipped_branch_handled():
    """Skipped branch (d.status === 'skipped') must be explicitly handled."""
    src = _src()
    snippet = _dhl_handler_snippet(src)
    assert "d.status === 'skipped'" in snippet or 'd.status === "skipped"' in snippet, (
        "DHL reply handler must handle the skipped branch (d.status === 'skipped')"
    )


def test_dhl_reply_blocked_branch_handled():
    """Blocked/error branch (!d.ok) must be explicitly handled with a reason toast."""
    src = _src()
    snippet = _dhl_handler_snippet(src)
    assert "!d.ok" in snippet, (
        "DHL reply handler must handle the blocked branch (!d.ok)"
    )
    assert "d.reason" in snippet or "d.error" in snippet, (
        "Blocked branch must extract reason from d.reason or d.error"
    )


def test_dhl_reply_catch_branch_handled():
    """catch(e) branch must show an error toast — apiFetch exceptions must not be swallowed."""
    src = _src()
    snippet = _dhl_handler_snippet(src)
    assert "catch (e)" in snippet or "catch(e)" in snippet, (
        "DHL reply handler must have a catch branch for apiFetch exceptions"
    )
    assert "e.message" in snippet, (
        "catch branch must surface e.message in error toast"
    )


def test_dhl_reply_busy_guard_present():
    """sendReply busy state must gate the button (disabled={!!busy.sendReply})."""
    src = _src()
    snippet = _dhl_handler_snippet(src)
    assert "busy.sendReply" in snippet, (
        "DHL reply button must use busy.sendReply to prevent double-submission"
    )


def test_dhl_reply_finally_releases_busy():
    """finally block must always release busy.sendReply — even on failure."""
    src = _src()
    snippet = _dhl_handler_snippet(src)
    assert "finally" in snippet, (
        "DHL reply handler must have a finally block to release busy state"
    )
    finally_idx = snippet.find("finally")
    finally_snippet = snippet[finally_idx: finally_idx + 150]
    assert "setBusyKey" in finally_snippet and "sendReply" in finally_snippet, (
        "finally block must call setBusyKey('sendReply', false)"
    )


# ── Service Invoice Receipt card tests ────────────────────────────────────────

_SVC_INVOICE_UPLOAD_URL = "/api/v1/service-invoices/"
_SVC_INVOICE_CARD_ANCHOR = "svc-invoice-dhl-status"


def _svc_invoice_snippet(src: str) -> str:
    """Window anchored on the DHL status badge testid (first element in the card).
    500 chars before + 5600 chars after covers the full card including upload handler."""
    idx = src.find(_SVC_INVOICE_CARD_ANCHOR)
    assert idx != -1, (
        f"{_SVC_INVOICE_CARD_ANCHOR!r} not found in dashboard — service invoice card not wired"
    )
    return src[max(0, idx - 500): idx + 5600]


def test_svc_invoice_card_present_in_pz_wfirma_tab():
    """Service Invoices card must be present in the PZ / wFirma tab block."""
    src = _src()
    # Card must appear after the 'PZ / wFirma' tab guard
    pz_tab_idx = src.find("activeTab === 'PZ / wFirma'")
    assert pz_tab_idx != -1, "PZ / wFirma tab guard not found"
    region = src[pz_tab_idx:]
    assert "Service Invoices" in region, (
        "Service Invoices card title not found in PZ / wFirma tab block"
    )


def test_svc_invoice_dhl_status_testid_present():
    """DHL invoice status element must carry data-testid for test selection."""
    src = _src()
    assert 'data-testid="svc-invoice-dhl-status"' in src, (
        "DHL invoice status element missing data-testid='svc-invoice-dhl-status'"
    )


def test_svc_invoice_agency_status_testid_present():
    """Agency invoice status element must carry data-testid for test selection."""
    src = _src()
    assert 'data-testid="svc-invoice-agency-status"' in src, (
        "Agency invoice status element missing data-testid='svc-invoice-agency-status'"
    )


def test_svc_invoice_status_reads_dhl_invoice_received():
    """Status badge must render from audit.dhl_invoice_received."""
    src = _src()
    snippet = _svc_invoice_snippet(src)
    assert "audit.dhl_invoice_received" in snippet, (
        "Service invoice card must reference audit.dhl_invoice_received for DHL status"
    )


def test_svc_invoice_status_reads_agency_invoice_received():
    """Status badge must render from audit.agency_invoice_received."""
    src = _src()
    snippet = _svc_invoice_snippet(src)
    assert "audit.agency_invoice_received" in snippet, (
        "Service invoice card must reference audit.agency_invoice_received for agency status"
    )


def test_svc_invoice_file_input_testid_present():
    """Hidden file input must carry data-testid for test targeting."""
    src = _src()
    assert 'data-testid="svc-invoice-file-input"' in src, (
        "Service invoice file input missing data-testid='svc-invoice-file-input'"
    )


def test_svc_invoice_file_input_accepts_correct_extensions():
    """File input must accept the same extensions as the backend validator."""
    src = _src()
    snippet = _svc_invoice_snippet(src)
    assert '.pdf' in snippet and '.xml' in snippet and '.jpg' in snippet, (
        "Service invoice file input must accept .pdf, .xml, .jpg (and other allowed extensions)"
    )


def test_svc_invoice_file_input_is_multiple():
    """File input must allow multiple file selection."""
    src = _src()
    snippet = _svc_invoice_snippet(src)
    assert "multiple" in snippet, (
        "Service invoice file input must have 'multiple' attribute"
    )


def test_svc_invoice_upload_url_correct():
    """Upload must POST to /api/v1/service-invoices/{batchId}/upload."""
    src = _src()
    snippet = _svc_invoice_snippet(src)
    assert _SVC_INVOICE_UPLOAD_URL in snippet, (
        f"Service invoice upload must POST to {_SVC_INVOICE_UPLOAD_URL!r}"
    )
    assert "/upload" in snippet, (
        "Upload endpoint must end with /upload (not /received)"
    )


def test_svc_invoice_formdata_appends_files():
    """FormData must append files under the 'files' key."""
    src = _src()
    snippet = _svc_invoice_snippet(src)
    assert "fd.append('files'" in snippet or 'fd.append("files"' in snippet, (
        "Service invoice upload must append files as 'files' in FormData"
    )


def test_svc_invoice_formdata_appends_source_operator():
    """FormData must append source=operator (matches backend default)."""
    src = _src()
    snippet = _svc_invoice_snippet(src)
    assert ("fd.append('source'" in snippet or 'fd.append("source"' in snippet), (
        "Service invoice upload must append 'source' to FormData"
    )
    assert "'operator'" in snippet or '"operator"' in snippet, (
        "Source value must be 'operator'"
    )


def test_svc_invoice_success_refreshes_load():
    """After successful upload, load() must be called to refresh audit state."""
    src = _src()
    snippet = _svc_invoice_snippet(src)
    assert "load()" in snippet, (
        "Service invoice upload success must call load() to refresh audit data"
    )


def test_svc_invoice_success_refreshes_batch_readiness():
    """After successful upload, loadBatchReadiness() must be called."""
    src = _src()
    snippet = _svc_invoice_snippet(src)
    assert "loadBatchReadiness()" in snippet, (
        "Service invoice upload success must call loadBatchReadiness()"
    )


def test_svc_invoice_success_refreshes_decision():
    """After successful upload, loadDecision() must be called."""
    src = _src()
    snippet = _svc_invoice_snippet(src)
    assert "loadDecision()" in snippet, (
        "Service invoice upload success must call loadDecision()"
    )


def test_svc_invoice_refresh_calls_use_promise_all():
    """load(), loadBatchReadiness(), loadDecision() must fire in parallel via Promise.all."""
    src = _src()
    snippet = _svc_invoice_snippet(src)
    pa_idx = snippet.find("Promise.all(")
    assert pa_idx != -1, "Service invoice upload success must use Promise.all for parallel refresh"
    pa_snippet = snippet[pa_idx: pa_idx + 200]
    assert "load()" in pa_snippet,             "load() missing from Promise.all"
    assert "loadBatchReadiness()" in pa_snippet, "loadBatchReadiness() missing from Promise.all"
    assert "loadDecision()" in pa_snippet,       "loadDecision() missing from Promise.all"


def test_svc_invoice_catch_branch_handled():
    """catch(ex) must be present — upload errors must not be swallowed."""
    src = _src()
    snippet = _svc_invoice_snippet(src)
    assert "catch (ex)" in snippet or "catch(ex)" in snippet, (
        "Service invoice upload handler must have a catch branch"
    )


def test_svc_invoice_busy_state_gates_input():
    """svcInvoiceBusy must be used to disable the file input during upload."""
    src = _src()
    snippet = _svc_invoice_snippet(src)
    assert "svcInvoiceBusy" in snippet, (
        "Service invoice file input must be gated by svcInvoiceBusy"
    )
    assert "disabled={svcInvoiceBusy}" in snippet, (
        "File input must set disabled={svcInvoiceBusy}"
    )


def test_svc_invoice_finally_resets_ref():
    """finally block must reset the file input ref to allow re-upload of same file."""
    src = _src()
    snippet = _svc_invoice_snippet(src)
    assert "finally" in snippet, "Service invoice upload must have a finally block"
    finally_idx = snippet.find("finally")
    finally_snippet = snippet[finally_idx: finally_idx + 200]
    assert "svcInvoiceRef.current" in finally_snippet, (
        "finally block must reset svcInvoiceRef.current so the same file can be re-uploaded"
    )


def test_svc_invoice_success_testid_present():
    """Success result div must carry data-testid for test targeting."""
    src = _src()
    assert 'data-testid="svc-invoice-upload-success"' in src, (
        "Service invoice upload success element missing data-testid='svc-invoice-upload-success'"
    )


def test_svc_invoice_error_testid_present():
    """Error result div must carry data-testid for test targeting."""
    src = _src()
    assert 'data-testid="svc-invoice-upload-error"' in src, (
        "Service invoice upload error element missing data-testid='svc-invoice-upload-error'"
    )


def test_svc_invoice_existing_list_reads_service_invoices():
    """File list must render from audit.service_invoices array."""
    src = _src()
    snippet = _svc_invoice_snippet(src)
    assert "audit.service_invoices" in snippet, (
        "Service invoice card must render existing files from audit.service_invoices"
    )


def test_svc_invoice_state_vars_declared():
    """React state vars (svcInvoiceBusy, svcInvoiceResult, svcInvoiceError) must be declared."""
    src = _src()
    assert "svcInvoiceBusy" in src,   "svcInvoiceBusy state not declared"
    assert "svcInvoiceResult" in src, "svcInvoiceResult state not declared"
    assert "svcInvoiceError" in src,  "svcInvoiceError state not declared"
    assert "svcInvoiceRef" in src,    "svcInvoiceRef ref not declared"


# ─────────────────────────────────────────────────────────────────────────────
# wFirma create — execution-engine routing
#
# The Create Reservation button must route through the execution engine
# (POST /api/v1/execute/wfirma_create) and must NOT call the old direct route
# (POST /api/v1/wfirma/reservations/create or similar).
#
# All tests are source-grep only — no JSX execution.
# ─────────────────────────────────────────────────────────────────────────────

_WFIRMA_EXEC_URL  = "/api/v1/execute/wfirma_create"
_WFIRMA_OLD_URL   = "/api/v1/wfirma/reservations/create"


def _wfirma_handler_snippet(src: str) -> str:
    """Return the full submitReservation handler body.

    Window: 200 chars before the execute URL (catches the apiFetch open)
    through 1800 chars after (captures success, skipped, blocked, catch, finally).
    """
    idx = src.find(_WFIRMA_EXEC_URL)
    assert idx != -1, f"{_WFIRMA_EXEC_URL!r} not found in dashboard — wFirma routing not wired"
    return src[max(0, idx - 200): idx + 1800]


def test_wfirma_create_old_direct_route_absent():
    """Dashboard must not contain the old direct wFirma reservations create path."""
    src = _src()
    assert _WFIRMA_OLD_URL not in src, (
        f"Old direct wFirma create route {_WFIRMA_OLD_URL!r} still present — must be removed"
    )


def test_wfirma_create_execution_engine_url_present():
    """Dashboard must call POST /api/v1/execute/wfirma_create."""
    src = _src()
    assert _WFIRMA_EXEC_URL in src, (
        f"Execution-engine wFirma create route {_WFIRMA_EXEC_URL!r} not found in dashboard"
    )


def test_wfirma_create_body_includes_batch_id():
    """Request body must include batch_id: batchId."""
    src = _src()
    snippet = _wfirma_handler_snippet(src)
    assert "batch_id: batchId" in snippet, (
        "wFirma create POST body must include 'batch_id: batchId'"
    )


def test_wfirma_create_body_includes_payload_client_name():
    """Request body must include payload: { client_name: clientName }."""
    src = _src()
    snippet = _wfirma_handler_snippet(src)
    assert "payload: { client_name: clientName }" in snippet or \
           "payload:{client_name:clientName}" in snippet.replace(" ", ""), (
        "wFirma create POST body must include 'payload: { client_name: clientName }'"
    )


def test_wfirma_create_skipped_branch_handled():
    """Skipped branch (d.status === 'skipped') must be explicitly handled."""
    src = _src()
    snippet = _wfirma_handler_snippet(src)
    assert "d.status === 'skipped'" in snippet or 'd.status === "skipped"' in snippet, (
        "wFirma create handler must handle the skipped branch (d.status === 'skipped')"
    )


def test_wfirma_create_blocked_branch_handled():
    """Blocked/error branch (!d.ok) must be explicitly handled with a reason toast."""
    src = _src()
    snippet = _wfirma_handler_snippet(src)
    assert "!d.ok" in snippet, (
        "wFirma create handler must handle the blocked branch (!d.ok)"
    )
    assert "d.reason" in snippet or "d.error" in snippet, (
        "Blocked branch must extract reason from d.reason or d.error"
    )


def test_wfirma_create_catch_branch_handled():
    """catch(e) branch must show an error toast — apiFetch exceptions must not be swallowed."""
    src = _src()
    snippet = _wfirma_handler_snippet(src)
    assert "catch (e)" in snippet or "catch(e)" in snippet, (
        "wFirma create handler must have a catch branch for apiFetch exceptions"
    )
    assert "e.message" in snippet, (
        "catch branch must surface e.message in error toast"
    )


def test_wfirma_create_success_refreshes_reservation_preview():
    """Success branch must call loadReservationPreview() to update wFirma preview panel."""
    src = _src()
    snippet = _wfirma_handler_snippet(src)
    assert "loadReservationPreview()" in snippet, (
        "wFirma create success branch must call loadReservationPreview()"
    )


def test_wfirma_create_success_refreshes_batch_readiness():
    """Success branch must call loadBatchReadiness() to update readiness panel."""
    src = _src()
    snippet = _wfirma_handler_snippet(src)
    assert "loadBatchReadiness()" in snippet, (
        "wFirma create success branch must call loadBatchReadiness()"
    )


def test_wfirma_create_success_refreshes_decision():
    """Success branch must call loadDecision() to update decision widget."""
    src = _src()
    snippet = _wfirma_handler_snippet(src)
    assert "loadDecision()" in snippet, (
        "wFirma create success branch must call loadDecision()"
    )


def test_wfirma_create_refresh_calls_use_promise_all():
    """All three refresh calls must be batched in Promise.all — not sequential awaits."""
    src = _src()
    snippet = _wfirma_handler_snippet(src)
    assert "Promise.all(" in snippet, (
        "wFirma create refresh calls must use Promise.all — not sequential awaits"
    )
    pa_idx = snippet.find("Promise.all(")
    assert pa_idx != -1
    pa_snippet = snippet[pa_idx: pa_idx + 200]
    assert "loadReservationPreview()" in pa_snippet, "loadReservationPreview() missing from Promise.all"
    assert "loadBatchReadiness()" in pa_snippet,     "loadBatchReadiness() missing from Promise.all"
    assert "loadDecision()" in pa_snippet,           "loadDecision() missing from Promise.all"


def test_wfirma_create_skipped_also_refreshes():
    """Skipped branch must also refresh preview + readiness + decision (idempotent re-sync)."""
    src = _src()
    snippet = _wfirma_handler_snippet(src)
    # Find the skipped branch
    skipped_idx = snippet.find("d.status === 'skipped'")
    if skipped_idx == -1:
        skipped_idx = snippet.find('d.status === "skipped"')
    assert skipped_idx != -1
    # The Promise.all must appear after the skipped branch within the handler
    after_skipped = snippet[skipped_idx:]
    assert "Promise.all(" in after_skipped, (
        "Skipped branch must also call Promise.all([loadReservationPreview, loadBatchReadiness, loadDecision])"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Closure confirm — execution-engine routing
#
# The Confirm Closure button must route through the execution engine
# (POST /api/v1/execute/closure_confirm) and must NOT use the old write path
# (POST /api/v1/closure/{id}/evaluate).
#
# The existing read-only check button (GET /check) must be untouched.
# All tests are source-grep only — no JSX execution.
# ─────────────────────────────────────────────────────────────────────────────

_CLOSURE_EXEC_URL  = "/api/v1/execute/closure_confirm"
_CLOSURE_EVAL_URL  = "/closure/"          # old write evaluate path prefix
_CLOSURE_CHECK_URL = "/check"             # read-only — must remain


def _closure_confirm_snippet(src: str) -> str:
    """Return handler body anchored on the execute URL.

    300 chars before (catches disabled/busy guard on the Btn)
    through 2000 chars after (captures ok, skipped, blocked, catch, finally, Promise.all).
    """
    idx = src.find(_CLOSURE_EXEC_URL)
    assert idx != -1, (
        f"{_CLOSURE_EXEC_URL!r} not found in dashboard — closure confirm routing not wired"
    )
    return src[max(0, idx - 300): idx + 2000]


def test_closure_confirm_execution_engine_url_present():
    """Dashboard must call POST /api/v1/execute/closure_confirm."""
    src = _src()
    assert _CLOSURE_EXEC_URL in src, (
        f"Execution-engine closure confirm route {_CLOSURE_EXEC_URL!r} not found in dashboard"
    )


def test_closure_confirm_old_evaluate_route_absent():
    """POST /closure/.../evaluate must not be called — it writes audit directly."""
    src = _src()
    # The check button uses GET /closure/.../check — that is fine.
    # We want to ensure /evaluate (the write endpoint) is not called anywhere.
    assert "/evaluate" not in src, (
        "Old /closure/.../evaluate write route found in dashboard — must not be used"
    )


def test_closure_check_read_only_btn_still_present():
    """Read-only check button (GET /check) must still be present and unchanged."""
    src = _src()
    assert _CLOSURE_CHECK_URL in src, (
        "Read-only /check endpoint missing — evaluate button was accidentally removed"
    )
    assert 'data-testid="closure-eval-btn"' in src or \
           "data-testid='closure-eval-btn'" in src, (
        "closure-eval-btn testid missing — read-only evaluate button was removed"
    )


def test_closure_confirm_btn_testid():
    """data-testid='closure-confirm-btn' must be present."""
    src = _src()
    assert 'data-testid="closure-confirm-btn"' in src or \
           "data-testid='closure-confirm-btn'" in src, (
        "closure-confirm-btn testid not found"
    )


def test_closure_confirm_body_includes_batch_id():
    """Request body must include batch_id: batchId."""
    src = _src()
    snippet = _closure_confirm_snippet(src)
    assert "batch_id: batchId" in snippet, (
        "closure_confirm POST body must include 'batch_id: batchId'"
    )


def test_closure_confirm_body_includes_empty_payload():
    """Request body must include payload: {}."""
    src = _src()
    snippet = _closure_confirm_snippet(src)
    assert "payload: {}" in snippet, (
        "closure_confirm POST body must include 'payload: {}'"
    )


def test_closure_confirm_skipped_branch_handled():
    """Skipped branch (status === 'skipped') must be explicitly handled."""
    src = _src()
    snippet = _closure_confirm_snippet(src)
    assert "skipped" in snippet, (
        "closure_confirm handler must handle the skipped branch"
    )


def test_closure_confirm_blocked_branch_handled():
    """Blocked/error branch (!d.ok) must be handled with reason extraction."""
    src = _src()
    snippet = _closure_confirm_snippet(src)
    assert "!d.ok" in snippet or "d.ok" in snippet, (
        "closure_confirm handler must check d.ok"
    )
    assert "d.reason" in snippet or "d.error" in snippet, (
        "Blocked branch must extract reason from d.reason or d.error"
    )


def test_closure_confirm_catch_branch_handled():
    """catch(e) branch must surface e.message — apiFetch exceptions must not be swallowed."""
    src = _src()
    snippet = _closure_confirm_snippet(src)
    assert "catch (e)" in snippet or "catch(e)" in snippet, (
        "closure_confirm handler must have a catch branch"
    )
    assert "e.message" in snippet, (
        "catch branch must surface e.message in error handling"
    )


def test_closure_confirm_success_refreshes_load():
    """Success branch must call load() to reload audit data."""
    src = _src()
    snippet = _closure_confirm_snippet(src)
    assert "load()" in snippet, (
        "closure_confirm success branch must call load() to refresh audit"
    )


def test_closure_confirm_success_refreshes_batch_readiness():
    """Success branch must call loadBatchReadiness()."""
    src = _src()
    snippet = _closure_confirm_snippet(src)
    assert "loadBatchReadiness()" in snippet, (
        "closure_confirm success branch must call loadBatchReadiness()"
    )


def test_closure_confirm_success_refreshes_decision():
    """Success branch must call loadDecision()."""
    src = _src()
    snippet = _closure_confirm_snippet(src)
    assert "loadDecision()" in snippet, (
        "closure_confirm success branch must call loadDecision()"
    )


def test_closure_confirm_refresh_uses_promise_all():
    """Refresh calls must be batched in Promise.all."""
    src = _src()
    snippet = _closure_confirm_snippet(src)
    assert "Promise.all(" in snippet, (
        "closure_confirm refresh calls must use Promise.all — not sequential awaits"
    )
    pa_idx = snippet.find("Promise.all(")
    assert pa_idx != -1
    pa_snippet = snippet[pa_idx: pa_idx + 200]
    assert "load()" in pa_snippet,            "load() missing from Promise.all"
    assert "loadBatchReadiness()" in pa_snippet, "loadBatchReadiness() missing from Promise.all"
    assert "loadDecision()" in pa_snippet,    "loadDecision() missing from Promise.all"


def test_closure_confirm_btn_disabled_when_guard_fails():
    """Confirm button must be disabled when closureEvalDisabled is true."""
    src = _src()
    idx = src.find('data-testid="closure-confirm-btn"')
    if idx == -1:
        idx = src.find("data-testid='closure-confirm-btn'")
    assert idx != -1
    snippet = src[max(0, idx - 50): idx + 400]
    assert "closureEvalDisabled" in snippet, (
        "closure-confirm-btn must reference closureEvalDisabled in its disabled prop"
    )
    assert "disabled={" in snippet, (
        "closure-confirm-btn must have a disabled binding"
    )


def test_closure_confirm_btn_disabled_when_not_ready():
    """Confirm button must also be disabled when closureCheck is not ready."""
    src = _src()
    idx = src.find('data-testid="closure-confirm-btn"')
    if idx == -1:
        idx = src.find("data-testid='closure-confirm-btn'")
    assert idx != -1
    snippet = src[max(0, idx - 50): idx + 400]
    # Must check closureCheck.ready
    assert "closureCheck" in snippet and "ready" in snippet, (
        "closure-confirm-btn disabled must check closureCheck.ready"
    )


def test_closure_confirm_busy_guard_present():
    """closureConfirmBusy must gate the confirm button to prevent double-submit."""
    src = _src()
    snippet = _closure_confirm_snippet(src)
    assert "closureConfirmBusy" in snippet, (
        "closure-confirm-btn must use closureConfirmBusy to prevent double-submission"
    )


def test_closure_confirm_finally_releases_busy():
    """finally block must always release closureConfirmBusy."""
    src = _src()
    snippet = _closure_confirm_snippet(src)
    assert "finally" in snippet, (
        "closure_confirm handler must have a finally block"
    )
    finally_idx = snippet.find("finally")
    finally_snippet = snippet[finally_idx: finally_idx + 150]
    assert "setClosureConfirmBusy(false)" in finally_snippet, (
        "finally block must call setClosureConfirmBusy(false)"
    )
