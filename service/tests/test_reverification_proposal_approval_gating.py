"""
test_reverification_proposal_approval_gating.py — Regression tests for proposal
approval gating of reverification (channel="ai_reverification") proposals.

Origin: AWB 9938632830 (2026-06-08). supplier_mismatch proposal was incorrectly
blocked by "PZ not yet generated" because _annotate_can_approve only exempted
tracking_lookup from the PZ gate. Reverification proposals are pre-PZ verification
steps that MUST be approvable before PZ exists.

Tests:
  1. Reverification proposals can be approved without PZ (all 10 types)
  2. Email proposals still require PZ (existing behavior preserved)
  3. Reverification proposals blocked when batch is completed
  4. Non-pending reverification proposals are blocked (status gate)
  5. tracking_lookup still exempt (existing behavior preserved)
  6. Reverification proposals without channel field fall to PZ gate (safety)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY", "test-key")


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _annotate(proposal: dict, audit: dict) -> dict:
    from app.api.routes_action_proposals import _annotate_can_approve
    return _annotate_can_approve(proposal, audit)


def _base_audit(*, pz_exists: bool = False, completed: bool = False) -> dict:
    a = {"batch_id": "TEST_BATCH", "status": "completed" if completed else "draft"}
    if pz_exists:
        a["pz_pdf_filename"] = "PZ_TEST.pdf"
        a["pz_generated_at"] = "2026-06-08T10:00:00Z"
    return a


def _reverification_proposal(ptype: str = "supplier_mismatch") -> dict:
    return {
        "proposal_id": "p_test_001",
        "type": ptype,
        "status": "pending_review",
        "channel": "ai_reverification",
        "approved_by": None,
    }


def _email_proposal(ptype: str = "dhl_followup") -> dict:
    return {
        "proposal_id": "p_test_002",
        "type": ptype,
        "status": "pending_review",
        "channel": "email",
        "approved_by": None,
    }


# ── All reverification types from rule_based_reverification.py + customs_desc_checker.py
REVERIFICATION_TYPES = [
    "supplier_mismatch",
    "client_mismatch",
    "product_design_mismatch",
    "missing_hs_code",
    "price_value_conflict",
    "sales_purchase_line_mismatch",
    "dhl_delivered_not_received",
    "product_not_synced_to_wfirma",
    "pz_proforma_invoice_ready_for_approval",
    "customs_description_mismatch",
]


# ── Test 1: Reverification proposals approvable without PZ ──────────────────

class TestReverificationBypassesPZGate:

    @pytest.mark.parametrize("ptype", REVERIFICATION_TYPES)
    def test_reverification_approvable_without_pz(self, ptype):
        """All reverification types are pre-PZ steps — must be approvable without PZ."""
        audit = _base_audit(pz_exists=False)
        proposal = _reverification_proposal(ptype)
        result = _annotate(proposal, audit)
        assert result["can_approve"] is True, (
            f"{ptype} blocked with reason: {result.get('approve_blocked_reason')}"
        )
        assert result["approve_blocked_reason"] is None

    @pytest.mark.parametrize("ptype", REVERIFICATION_TYPES)
    def test_reverification_also_approvable_with_pz(self, ptype):
        """Still approvable after PZ exists (rule 2b fires before rule 4)."""
        audit = _base_audit(pz_exists=True)
        proposal = _reverification_proposal(ptype)
        result = _annotate(proposal, audit)
        assert result["can_approve"] is True


# ── Test 2: Email proposals still require PZ ────────────────────────────────

class TestEmailProposalsStillGated:

    @pytest.mark.parametrize("ptype", [
        "dhl_followup", "agency_followup", "duty_payment_followup",
        "dhl_proactive_dispatch",
    ])
    def test_email_proposal_blocked_without_pz(self, ptype):
        """Email proposals must still require PZ — existing behavior preserved."""
        audit = _base_audit(pz_exists=False)
        proposal = _email_proposal(ptype)
        result = _annotate(proposal, audit)
        assert result["can_approve"] is False
        assert "PZ not yet generated" in result["approve_blocked_reason"]

    @pytest.mark.parametrize("ptype", [
        "dhl_followup", "agency_followup", "duty_payment_followup",
    ])
    def test_email_proposal_approvable_with_pz(self, ptype):
        """Email proposals approvable once PZ exists."""
        audit = _base_audit(pz_exists=True)
        proposal = _email_proposal(ptype)
        result = _annotate(proposal, audit)
        assert result["can_approve"] is True


# ── Test 3: Reverification blocked on completed batch ───────────────────────

class TestReverificationBlockedOnCompleted:

    def test_reverification_blocked_when_completed(self):
        """Rule 3 (completed) still applies to reverification proposals."""
        audit = _base_audit(completed=True)
        proposal = _reverification_proposal("supplier_mismatch")
        result = _annotate(proposal, audit)
        assert result["can_approve"] is False
        assert "completed" in result["approve_blocked_reason"].lower()


# ── Test 4: Non-pending reverification proposals blocked ────────────────────

class TestNonPendingReverificationBlocked:

    @pytest.mark.parametrize("status", ["approved", "rejected", "queued", "sent"])
    def test_non_pending_blocked(self, status):
        """Rule 1 (status gate) fires before channel check."""
        audit = _base_audit(pz_exists=False)
        proposal = _reverification_proposal("supplier_mismatch")
        proposal["status"] = status
        result = _annotate(proposal, audit)
        assert result["can_approve"] is False
        assert f"already {status}" in result["approve_blocked_reason"]


# ── Test 5: tracking_lookup still exempt ────────────────────────────────────

class TestTrackingLookupStillExempt:

    def test_tracking_lookup_approvable_without_pz(self):
        """Existing _NON_EMAIL_TYPES exemption still works."""
        audit = _base_audit(pz_exists=False)
        proposal = {
            "proposal_id": "p_track",
            "type": "tracking_lookup",
            "status": "pending_review",
            "approved_by": None,
        }
        result = _annotate(proposal, audit)
        assert result["can_approve"] is True


# ── Test 6: Missing channel field falls through to PZ gate ──────────────────

class TestMissingChannelSafety:

    def test_unknown_type_without_channel_still_gated(self):
        """Proposals without channel="ai_reverification" still require PZ."""
        audit = _base_audit(pz_exists=False)
        proposal = {
            "proposal_id": "p_mystery",
            "type": "supplier_mismatch",  # same type, but no channel field
            "status": "pending_review",
            "approved_by": None,
            # NOTE: no "channel" key — safety fallback
        }
        result = _annotate(proposal, audit)
        assert result["can_approve"] is False
        assert "PZ not yet generated" in result["approve_blocked_reason"]
