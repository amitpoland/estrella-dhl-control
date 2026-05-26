"""
test_inbox_approval_cockpit.py — Inbox-as-Approval-Cockpit contract.

Locks the conversion of the Inbox from a passive list into the operator
approval surface. Each row that has a corresponding existing backend
action must render inline buttons that POST to the existing endpoint
(no new backend invented).

Coverage:
  - inboxActionsFor() exists and is exported into the InboxPage scope
  - Each source has the expected action descriptors (proposals,
    cn_match, exporter_match, email_queue)
  - Forbidden financial checks render disabled with reason
  - Approve / Reject buttons render inline with data-testid
  - Confirm modal exists with preview, reason field, idempotency guards
  - Old "Send / approve / reject actions remain on each item's
    existing detail page" disclaimer was removed
  - Endpoints used are the real existing ones (regression: never
    invent /api/v1/inbox/* or similar)
"""
from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DASH = _HERE.parent / "app" / "static" / "dashboard.html"


def _src() -> str:
    if not _DASH.exists():
        import pytest
        pytest.skip(f"dashboard.html not found at {_DASH}")
    return _DASH.read_text(encoding="utf-8")


# ── Mapping function present ─────────────────────────────────────────────────

def test_inbox_actions_for_function_present():
    src = _src()
    assert "function inboxActionsFor(row, raw)" in src


def test_forbidden_override_set_present():
    src = _src()
    # Mirror of batch_state_normalizer.FORBIDDEN_OVERRIDE_TYPES on the frontend
    for check in ("cif_match", "invoice_refs_match", "importer_match", "qty_match_by_type"):
        assert f"'{check}'" in src, f"Forbidden check '{check}' must be in client-side set"


# ── Proposals: approve + reject wired to /api/v1/proposals/{id} ──────────────

def test_proposal_approve_endpoint_used():
    src = _src()
    # Real backend: POST /api/v1/proposals/{id}/approve
    assert "/api/v1/proposals/${encodeURIComponent(pid)}/approve" in src


def test_proposal_reject_endpoint_used():
    src = _src()
    assert "/api/v1/proposals/${encodeURIComponent(pid)}/reject" in src


# ── cn_match: 3-way decision (real backend in routes_dashboard.py) ───────────

def test_cn_decision_accept_sad_wired():
    src = _src()
    assert "/cn-decision/accept-sad" in src


def test_cn_decision_escalate_agent_wired():
    src = _src()
    assert "/cn-decision/escalate-agent" in src


# ── exporter_match: operator-override (real backend) ─────────────────────────

def test_exporter_match_override_wired():
    src = _src()
    assert "/operator-override" in src
    # Body must declare the check name explicitly
    assert "check: 'exporter_match'" in src


# ── Email queue: send via existing admin endpoint ────────────────────────────

def test_email_send_smtp_wired():
    src = _src()
    assert "/api/v1/admin/email-queue/${encodeURIComponent(eid)}/send" in src
    # Method body sets smtp explicitly
    assert "method: 'smtp'" in src


# ── No invented endpoints (regression guard) ─────────────────────────────────

def test_no_invented_inbox_endpoints():
    src = _src()
    # The whole point of this work: do NOT invent /api/v1/inbox/* —
    # reuse existing routes.
    for bad in (
        "/api/v1/inbox/approve",
        "/api/v1/inbox/execute",
        "/api/v1/inbox/preview",
        "/api/v1/cockpit/",
    ):
        assert bad not in src, f"Invented endpoint detected: {bad}"


# ── Inline buttons + modal data-testids ──────────────────────────────────────

def test_inline_action_button_template_present():
    src = _src()
    # Template renders <button data-testid={`inbox-action-${act.id}`} ...>
    assert "data-testid={`inbox-action-${act.id}`}" in src
    # And disabled variant carries a separate testid
    assert "data-testid={`inbox-action-disabled-${act.id}`}" in src


def test_approval_modal_present():
    src = _src()
    assert 'data-testid="inbox-approval-modal"' in src
    assert 'data-testid="inbox-approval-confirm"' in src
    assert 'data-testid="inbox-approval-cancel"' in src
    assert 'data-testid="inbox-approval-reason"' in src


def test_approval_modal_shows_risk_level():
    src = _src()
    assert 'data-testid="inbox-approval-risk"' in src


# ── Idempotency: in-flight latch + completed set ─────────────────────────────

def test_idempotency_latches_present():
    src = _src()
    assert "inflightRef" in src
    assert "completedRef" in src


def test_double_click_guard_blocks_resubmit():
    src = _src()
    # The guard logic must reject if either set contains the latchKey
    assert "completedRef.current.has(latchKey)" in src
    assert "inflightRef.current.has(latchKey)" in src


# ── Old misleading disclaimer removed ────────────────────────────────────────

def test_pending_disclaimer_no_longer_claims_actions_are_detail_only():
    src = _src()
    # The pre-cockpit message claimed approve/send/reject lived only on
    # detail pages. That sentence is the architectural defect this task
    # exists to remove.
    assert "Send / approve / reject actions remain on each item" not in src
    assert "no shortcuts from this list" not in src


def test_design_preview_strip_now_describes_only_bulk_ops():
    src = _src()
    # We keep the strip (Mark-read / Snooze / Bulk-apply genuinely have no
    # backend) but the wording must scope it to BULK only — per-row actions
    # are explicitly described as wired.
    assert "Bulk ops pending" in src or "Bulk-apply-rule" in src
    assert "Per-row Approve / Reject / Send are wired" in src


# ── Risk-level vocabulary present ────────────────────────────────────────────

def test_risk_levels_declared():
    src = _src()
    for level in ("'high'", "'medium'", "'low'"):
        assert f"risk_level: {level}" in src, f"Missing risk_level {level} in action descriptors"


# ── Reason validation thresholds match backend (regression) ──────────────────

def test_exporter_override_reason_min_20_chars():
    src = _src()
    # Backend route_dashboard.add_operator_override requires >= 20 chars
    assert "min_reason_len: 20" in src


def test_cn_decision_reason_min_present():
    src = _src()
    # CN decisions enforce a default reason via backend; UI requires >= 10
    assert "min_reason_len: 10" in src


# ── Single-authority mode model (2026-05-26 consolidation) ──────────────────

def test_dhl_followup_preview_is_read_only_get():
    """Preview action must be a read-only GET against the canonical guard
    endpoint — never the prior /auto/run POST that PR #372 added."""
    src = _src()
    # Read-only preview wired
    assert "/api/v1/dhl-followup/${encodeURIComponent(batchId)}/auto/preview" in src
    # The OLD POST /auto/run endpoint is removed entirely
    assert "/auto/run" not in src, "Auto/run endpoint must be removed — single-authority"


def test_dhl_followup_preview_descriptor_is_read_only():
    src = _src()
    assert "id: 'dhl_followup.preview'" in src
    block_start = src.index("id: 'dhl_followup.preview'")
    block_end   = src.index("});", block_start)
    block = src[block_start:block_end]
    assert "read_only: true" in block
    # Read-only previews carry no execute_endpoint
    assert "execute_endpoint:" not in block


def test_dhl_followup_mode_toggle_actions_wired():
    """Inbox surfaces explicit Enable/Disable auto buttons (mode-aware)."""
    src = _src()
    # Both directions exist and POST to the new /mode endpoint
    assert "id: 'dhl_followup.set_automatic'" in src
    assert "id: 'dhl_followup.set_manual'" in src
    assert "/api/v1/dhl-followup/${encodeURIComponent(batchId)}/mode" in src
    # Bodies are explicit and minimal — no force_sla, no hidden auto-send
    assert "mode: 'automatic'" in src
    assert "mode: 'manual'" in src


def test_dhl_followup_manual_send_uses_existing_send_now_endpoint():
    """Manual send must call the existing /send-now route — not a new path."""
    src = _src()
    assert "id: 'dhl_followup.send_now'" in src
    # The existing operator-explicit endpoint is the canonical manual path
    assert "/api/v1/dhl-followup/${encodeURIComponent(batchId)}/send-now" in src
    block_start = src.index("id: 'dhl_followup.send_now'")
    block_end   = src.index("});", block_start)
    block = src[block_start:block_end]
    # Carries approved_by per existing send-now contract
    assert "approved_by: 'operator_inbox'" in block
    # High-risk because external email
    assert "risk_level: 'high'" in block


def test_dhl_followup_substantive_reply_stays_disabled():
    src = _src()
    # Substantive customs reply must NOT auto-send (operator on detail page)
    assert "id: 'dhl_reply.detail_only'" in src
    assert "Auto-reply forbidden" in src
    assert "disabled: true" in src


def test_no_agency_auto_action_in_inbox():
    """Agency auto-send is forbidden — no inbox action for it."""
    src = _src()
    block_start = src.index("function inboxActionsFor(row, raw)")
    block_end   = src.index("// ══════════", block_start + 50)
    block = src[block_start:block_end]
    for forbidden in (
        "agency.auto_send",
        "agency_advance.send",
        "/api/v1/dhl-followup/agency",
    ):
        assert forbidden not in block, f"Forbidden agency auto-send leaked: {forbidden}"


def test_no_redundant_auto_engine_referenced():
    """The deleted PR #372 engine must not be referenced anywhere in the UI."""
    src = _src()
    for ghost in (
        "/auto/run",
        "dhl_auto_followup_enabled",          # deleted flag
        "force_sla",                          # deleted bypass
        "dhl_followup_auto_sent",             # deleted event name
        "dhl_followup_auto_suppressed",       # deleted event name
    ):
        assert ghost not in src, f"Reference to deleted engine surface: {ghost}"
