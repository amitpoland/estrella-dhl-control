"""
test_inbox_composition_contracts.py — Tier-2 Inbox composition authority contracts.

Locks the invariants that preserve the Inbox as a pure composition/projection
layer and prevent future duplication between proposal generation, queue
orchestration, and operator execution surfaces.

Coverage:
  A. list_proposals response — can_approve / approve_blocked_reason projection
     (backend is the single authority; renderers consume, never re-derive)

  B. Partial composition failure isolation
     — one source unavailable must not prevent other sources from loading
     (tested via direct projector / service calls with bad storage root)

  C. dhl_followup_status_projector — graceful degradation when audit dir absent

  D. Inbox action registry invariants (source-grep tests on dashboard.html)
     — inboxActionsFor() must never produce an /api/v1/inbox/* endpoint
     — per-source failure strip must exist
     — financial checks must be blocked (no override button)

  E. No mutation side effects in inbox composition
     — inbox fetches must not write timeline events or modify audit files

  F. shipment-detail.html approve button authority contracts (source-grep)
     — approve button consumes backend can_approve; no local re-derivation
     — approve_blocked_reason used for disabled reason display
     — old client-side inference variables are absent
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY", "test-key")

_DASH   = _ROOT / "app" / "static" / "dashboard.html"
_DETAIL = _ROOT / "app" / "static" / "shipment-detail.html"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    from app.api import routes_action_proposals
    from app.services import action_email_builder
    for mod in (routes_action_proposals, action_email_builder):
        monkeypatch.setattr(mod, "_OUTPUTS", tmp_path / "outputs")


def _make_batch(
    root: Path,
    extra: Dict[str, Any] | None = None,
    batch_id: str | None = None,
) -> tuple[str, Path]:
    bid = batch_id or str(uuid.uuid4())[:8]
    bd = root / "outputs" / bid
    bd.mkdir(parents=True, exist_ok=True)
    audit: Dict[str, Any] = {
        "batch_id": bid,
        "awb": "1234567890",
        "status": "processing",
        "clearance_decision": {
            "total_value_usd": 800.0,
            "clearance_path": "dhl_self_clearance",
            "require_dsk": False,
        },
    }
    if extra:
        audit.update(extra)
    (bd / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return bid, bd


def _add_proposal(
    bd: Path,
    ptype: str = "dhl_followup",
    status: str = "pending_review",
    extra: Dict[str, Any] | None = None,
) -> str:
    pid = str(uuid.uuid4())
    audit = json.loads((bd / "audit.json").read_text(encoding="utf-8"))
    p: Dict[str, Any] = {
        "proposal_id":  pid,
        "type":         ptype,
        "batch_id":     audit["batch_id"],
        "status":       status,
        "reason":       "test",
        "confidence":   "medium",
        "draft":        {"to": "customs@dhl.com", "subject": "test", "body_text": "test"},
        "created_at":   "2026-05-28T10:00:00+00:00",
        "approved_by":  None,
        "approved_at":  None,
        "rejected_by":  None,
        "rejected_at":  None,
        "reject_reason": None,
        "email_id":     None,
        "queued_at":    None,
        "override_value_check": False,
        "validation_failure_reason": None,
    }
    if extra:
        p.update(extra)
    audit.setdefault("action_proposals", []).append(p)
    (bd / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return pid


# ═══════════════════════════════════════════════════════════════════════════════
# A. can_approve projection — backend is single authority
# ═══════════════════════════════════════════════════════════════════════════════

class TestCanApproveProjection:
    """
    list_proposals must annotate each proposal with can_approve + approve_blocked_reason.
    Renderers consume these fields; they must never re-derive readiness from raw audit.
    """

    def _fetch(self, tmp_path, batch_id):
        from app.api.routes_action_proposals import list_proposals
        return list_proposals(batch_id)

    def test_pz_not_ready_blocks_email_proposal(self, tmp_path):
        """Email proposal: can_approve=False when PZ not generated."""
        bid, bd = _make_batch(tmp_path)  # no pz_pdf_filename, no pz_generated_at
        _add_proposal(bd)
        result = self._fetch(tmp_path, bid)
        p = result["proposals"][0]
        assert p["can_approve"] is False
        assert "PZ not yet generated" in (p["approve_blocked_reason"] or "")

    def test_pz_ready_allows_email_proposal(self, tmp_path):
        """Email proposal: can_approve=True when PZ exists."""
        bid, bd = _make_batch(tmp_path, {"pz_pdf_filename": "PZ_test.pdf"})
        _add_proposal(bd)
        result = self._fetch(tmp_path, bid)
        p = result["proposals"][0]
        assert p["can_approve"] is True
        assert p["approve_blocked_reason"] is None

    def test_pz_generated_at_also_unlocks(self, tmp_path):
        """pz_generated_at is an accepted readiness signal alongside pz_pdf_filename."""
        bid, bd = _make_batch(tmp_path, {"pz_generated_at": "2026-05-28T00:00:00Z"})
        _add_proposal(bd)
        result = self._fetch(tmp_path, bid)
        assert result["proposals"][0]["can_approve"] is True

    def test_completed_batch_blocks_email_proposal(self, tmp_path):
        """Completed batch must block all email proposals regardless of PZ state."""
        bid, bd = _make_batch(tmp_path, {
            "pz_pdf_filename": "PZ_test.pdf",
            "status": "completed",
        })
        _add_proposal(bd)
        result = self._fetch(tmp_path, bid)
        p = result["proposals"][0]
        assert p["can_approve"] is False
        assert "completed" in (p["approve_blocked_reason"] or "").lower()

    def test_tracking_lookup_always_approvable(self, tmp_path):
        """tracking_lookup is a non-email type — approvable without PZ."""
        bid, bd = _make_batch(tmp_path)  # no PZ
        _add_proposal(bd, ptype="tracking_lookup")
        result = self._fetch(tmp_path, bid)
        p = result["proposals"][0]
        assert p["can_approve"] is True
        assert p["approve_blocked_reason"] is None

    def test_already_approved_is_not_approvable(self, tmp_path):
        """Approved proposal is terminal for the approve button."""
        bid, bd = _make_batch(tmp_path, {"pz_pdf_filename": "PZ.pdf"})
        _add_proposal(bd, status="approved")
        result = self._fetch(tmp_path, bid)
        p = result["proposals"][0]
        assert p["can_approve"] is False
        assert "approved" in (p["approve_blocked_reason"] or "").lower()

    def test_queued_proposal_not_approvable(self, tmp_path):
        """Queued proposal is in terminal state."""
        bid, bd = _make_batch(tmp_path, {"pz_pdf_filename": "PZ.pdf"})
        _add_proposal(bd, status="queued")
        result = self._fetch(tmp_path, bid)
        p = result["proposals"][0]
        assert p["can_approve"] is False

    def test_rejected_proposal_not_approvable(self, tmp_path):
        bid, bd = _make_batch(tmp_path, {"pz_pdf_filename": "PZ.pdf"})
        _add_proposal(bd, status="rejected")
        result = self._fetch(tmp_path, bid)
        p = result["proposals"][0]
        assert p["can_approve"] is False

    def test_empty_proposals_returns_empty_list(self, tmp_path):
        """Batch with no proposals returns empty list, not 404."""
        bid, bd = _make_batch(tmp_path)
        result = self._fetch(tmp_path, bid)
        assert result["proposals"] == []
        assert result["count"] == 0

    def test_multiple_proposals_each_annotated(self, tmp_path):
        """Every proposal in the list gets can_approve annotation."""
        bid, bd = _make_batch(tmp_path, {"pz_pdf_filename": "PZ.pdf"})
        _add_proposal(bd, ptype="dhl_followup")
        _add_proposal(bd, ptype="tracking_lookup")
        result = self._fetch(tmp_path, bid)
        assert len(result["proposals"]) == 2
        for p in result["proposals"]:
            assert "can_approve" in p
            assert "approve_blocked_reason" in p

    def test_original_proposal_fields_preserved(self, tmp_path):
        """Annotation must not drop original proposal fields."""
        bid, bd = _make_batch(tmp_path)
        _add_proposal(bd, ptype="dhl_followup")
        result = self._fetch(tmp_path, bid)
        p = result["proposals"][0]
        # Core fields must survive the annotation step
        for key in ("proposal_id", "type", "status", "reason", "draft", "created_at"):
            assert key in p, f"Original field '{key}' missing after annotation"


# ═══════════════════════════════════════════════════════════════════════════════
# B. Partial composition failure isolation
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompositionFailureIsolation:
    """
    Each inbox source must fail independently.
    A bad storage root for one projector must not prevent other sources from loading.
    """

    def test_projector_returns_empty_on_bad_storage(self, tmp_path, monkeypatch):
        """dhl_followup_status_projector gracefully returns zeros when storage missing."""
        from app.services.dhl_followup_status_projector import project_automation_status

        # Point settings.storage_root at a non-existent dir
        from app.core.config import settings
        monkeypatch.setattr(settings, "storage_root", tmp_path / "nonexistent")

        result = project_automation_status()
        # Must not raise; returns degraded-but-valid shape
        assert isinstance(result, dict)
        assert result["active_shipments"] == 0
        assert "generated_at" in result

    def test_projector_rows_returns_empty_on_bad_storage(self, tmp_path, monkeypatch):
        from app.services.dhl_followup_status_projector import project_shipment_rows
        from app.core.config import settings
        monkeypatch.setattr(settings, "storage_root", tmp_path / "nonexistent")

        rows = project_shipment_rows()
        assert rows == []

    def test_projector_survives_corrupt_audit(self, tmp_path, monkeypatch):
        """Corrupt audit.json in one batch must not break the projector for other batches."""
        from app.services.dhl_followup_status_projector import project_automation_status
        from app.core.config import settings
        monkeypatch.setattr(settings, "storage_root", tmp_path)

        # Create one valid batch and one corrupt batch
        good = tmp_path / "outputs" / "SHIPMENT_001"
        bad  = tmp_path / "outputs" / "SHIPMENT_002"
        good.mkdir(parents=True)
        bad.mkdir(parents=True)
        (good / "audit.json").write_text(
            json.dumps({"batch_id": "001", "awb": "111", "status": "processing"}),
            encoding="utf-8",
        )
        (bad / "audit.json").write_text("NOT JSON {{{{", encoding="utf-8")

        # Must not raise
        result = project_automation_status()
        assert isinstance(result, dict)

    def test_list_proposals_404_does_not_crash_caller(self, tmp_path):
        """list_proposals raises HTTP 404 for unknown batch; caller handles it."""
        from fastapi import HTTPException
        from app.api.routes_action_proposals import list_proposals

        with pytest.raises(HTTPException) as exc_info:
            list_proposals("NONEXISTENT_BATCH_ID")
        assert exc_info.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# C. DSK projector — graceful degradation
# ═══════════════════════════════════════════════════════════════════════════════

class TestDskProjectorDegradation:
    """DSK audit log endpoint must degrade gracefully, not explode."""

    def test_dsk_audit_log_missing_returns_empty(self, tmp_path, monkeypatch):
        """When dsk_audit_log.json doesn't exist, endpoint returns []."""
        import os as _os
        from app.api.routes_dsk import get_audit_log
        import importlib, asyncio

        # Temporarily point DSK output dir to tmp_path (no log file)
        import app.api.routes_dsk as dsk_mod
        monkeypatch.setattr(dsk_mod, "_DSK_OUTPUT_DIR", tmp_path)

        result = asyncio.run(get_audit_log())
        body = json.loads(result.body)
        assert body == []


# ═══════════════════════════════════════════════════════════════════════════════
# D. Inbox action registry — source-grep contracts on dashboard.html
# ═══════════════════════════════════════════════════════════════════════════════

def _dash() -> str:
    if not _DASH.exists():
        pytest.skip(f"dashboard.html not found: {_DASH}")
    return _DASH.read_text(encoding="utf-8")


class TestInboxActionRegistryInvariants:
    """Source-grep tests that lock key composition invariants in dashboard.html."""

    def test_no_invented_inbox_endpoints(self):
        """inboxActionsFor must never wire to a /api/v1/inbox/* URL (no new backend)."""
        src = _dash()
        assert "/api/v1/inbox/" not in src, (
            "Inbox action registry must only route to existing backend endpoints. "
            "Found /api/v1/inbox/ — new unified endpoint not approved."
        )

    def test_per_source_error_strip_present(self):
        """Independent failure isolation strip must exist for each source."""
        src = _dash()
        assert "inbox-source-error" in src, (
            "Per-source error strip (data-testid='inbox-source-error-*') must exist "
            "to isolate failures independently."
        )

    def test_forbidden_financial_checks_blocked(self):
        """Forbidden financial override checks must produce disabled_reason, not an action button."""
        src = _dash()
        for check in ("cif_match", "invoice_refs_match", "importer_match", "qty_match_by_type"):
            assert f"'{check}'" in src, f"Forbidden check '{check}' missing from client-side guard set"
        assert "disabled_reason" in src, "Forbidden checks must produce disabled_reason, not action button"

    def test_email_send_requires_confirmation(self):
        """Email send action must be gated by requires_confirmation=true."""
        src = _dash()
        # The email_queue send action must require confirmation (EXTERNAL SEND)
        assert "requires_confirmation: true" in src

    def test_no_auto_send_pattern(self):
        """
        Read-only preview actions may use requires_confirmation: false only when
        explicitly paired with read_only: true (no execute_endpoint fired).
        No write-capable action (with execute_endpoint) may set requires_confirmation: false.
        """
        src = _dash()
        # The only permitted requires_confirmation: false usage is the
        # dhl_followup.preview read-only action (read_only: true, no execute_endpoint).
        # It must be accompanied by read_only: true.
        assert "read_only: true" in src, (
            "Preview-only actions must carry read_only: true to suppress the confirm button."
        )
        # There must NOT be an action with both execute_endpoint and requires_confirmation: false
        # simultaneously on the same descriptor. We check that every confirmed-false block
        # also contains read_only (the coupling invariant).
        # Simple check: count occurrences; each requires_confirmation: false must be next
        # to read_only: true in the same descriptor block.
        import re
        # Extract each inboxActionsFor descriptor block (heuristic: between .push({...}))
        blocks = re.findall(r'actions\.push\(\{[^}]+?\}\)', src, re.DOTALL)
        for block in blocks:
            if "requires_confirmation: false" in block:
                assert "read_only: true" in block, (
                    "Found requires_confirmation: false on a descriptor block without "
                    "read_only: true — potential auto-send risk:\n" + block[:300]
                )

    def test_dhl_automation_bridge_not_full_surface(self):
        """V1 inbox must show DHL count + link only, not full automation surface."""
        src = _dash()
        # The refactored bridge card should exist
        assert "inbox-dhl-automation-card" in src
        # The full mode-management table must NOT be in dashboard.html inbox
        assert "inbox-dhl-mode-table" not in src, (
            "V1 inbox must not duplicate the full DHL automation surface. "
            "Lesson F: navigation bridge only."
        )

    def test_proposals_loaded_from_real_endpoint(self):
        """Inbox proposals source must call the real /api/v1/proposals endpoint."""
        src = _dash()
        assert "/api/v1/proposals" in src

    def test_email_queue_loaded_from_real_endpoint(self):
        """Inbox email source must call the real /api/v1/admin/email-queue endpoint."""
        src = _dash()
        assert "/api/v1/admin/email-queue" in src

    def test_dsk_loaded_from_real_endpoint(self):
        """DSK source must call /api/v1/dsk/audit-log."""
        src = _dash()
        assert "/api/v1/dsk/audit-log" in src

    def test_inbox_actions_for_handles_active_sources(self):
        """
        inboxActionsFor must handle the three action-bearing sources.
        DSK is intentionally read-only (no inline action, Open button only).
        """
        src = _dash()
        for source in ("proposals", "action_required", "email_queue"):
            assert f"row.source === '{source}'" in src, (
                f"inboxActionsFor must handle source '{source}'"
            )
        # DSK rows are composed at the row-normalization level but carry no inline action.
        # Verify DSK is handled as a row source (in the rows array, not in inboxActionsFor).
        assert "source:     'dsk'" in src or "source: 'dsk'" in src, (
            "DSK must appear as a row source in the inbox normalization block."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# E. No mutation side effects from inbox composition reads
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoMutationSideEffects:
    """
    Inbox composition reads must not write to audit files or timeline.
    list_proposals GET must not modify the audit.
    """

    def test_list_proposals_does_not_modify_audit(self, tmp_path):
        """GET list_proposals must not alter audit.json on disk."""
        bid, bd = _make_batch(tmp_path, {"pz_pdf_filename": "PZ.pdf"})
        _add_proposal(bd, ptype="dhl_followup")

        audit_path = bd / "audit.json"
        mtime_before = audit_path.stat().st_mtime

        from app.api.routes_action_proposals import list_proposals
        list_proposals(bid)

        mtime_after = audit_path.stat().st_mtime
        assert mtime_before == mtime_after, (
            "list_proposals must not modify audit.json. "
            "Inbox reads are composition-only — no side effects."
        )

    def test_list_proposals_does_not_add_timeline_event(self, tmp_path):
        """list_proposals must not append timeline events."""
        bid, bd = _make_batch(tmp_path)
        _add_proposal(bd)

        audit_before = json.loads((bd / "audit.json").read_text(encoding="utf-8"))
        tl_len_before = len(audit_before.get("timeline") or [])

        from app.api.routes_action_proposals import list_proposals
        list_proposals(bid)

        audit_after = json.loads((bd / "audit.json").read_text(encoding="utf-8"))
        tl_len_after = len(audit_after.get("timeline") or [])

        assert tl_len_before == tl_len_after, (
            "list_proposals must not append timeline events."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# F. shipment-detail.html approve button authority contracts
# ═══════════════════════════════════════════════════════════════════════════════

def _detail() -> str:
    if not _DETAIL.exists():
        pytest.skip(f"shipment-detail.html not found: {_DETAIL}")
    return _DETAIL.read_text(encoding="utf-8")


class TestShipmentDetailCanApproveContracts:
    """
    Source-grep tests locking the canApprove migration in shipment-detail.html.

    Invariants:
    - canApprove is read from p.can_approve (backend-projected field)
    - approveDisabledReason is read from p.approve_blocked_reason (backend-projected field)
    - Old client-side inference variables (proposalPzReady, proposalBatchClosed) are gone
    - Approve button testid present and gated by canApprove
    - Disabled-reason display testid present and fed by approveDisabledReason
    - No fallback to audit.pz_pdf_filename or audit.status in canApprove derivation
    """

    def test_can_approve_consumed_from_backend_field(self):
        """canApprove must be assigned from p.can_approve — the backend projection."""
        src = _detail()
        assert "p.can_approve" in src, (
            "shipment-detail.html must read canApprove from the backend-projected "
            "p.can_approve field. Client-side re-derivation is forbidden."
        )

    def test_approve_blocked_reason_consumed_from_backend_field(self):
        """approveDisabledReason must be assigned from p.approve_blocked_reason."""
        src = _detail()
        assert "p.approve_blocked_reason" in src, (
            "shipment-detail.html must read the disabled reason from the backend-projected "
            "p.approve_blocked_reason field."
        )

    def test_old_inference_variable_proposal_pz_ready_absent(self):
        """proposalPzReady (old client-side inference var) must not exist."""
        src = _detail()
        assert "proposalPzReady" not in src, (
            "proposalPzReady was the old client-side PZ-readiness inference variable. "
            "It must be absent — backend now projects can_approve."
        )

    def test_old_inference_variable_proposal_batch_closed_absent(self):
        """proposalBatchClosed (old client-side inference var) must not exist."""
        src = _detail()
        assert "proposalBatchClosed" not in src, (
            "proposalBatchClosed was the old client-side batch-closed inference variable. "
            "It must be absent — backend now projects can_approve."
        )

    def test_approve_button_testid_present(self):
        """Approve button must carry data-testid='proposal-approve-btn' for test targeting."""
        src = _detail()
        assert 'data-testid="proposal-approve-btn"' in src or \
               "data-testid='proposal-approve-btn'" in src, (
            "Approve button must have data-testid='proposal-approve-btn'."
        )

    def test_approve_button_gated_by_can_approve(self):
        """Approve button disabled prop must reference canApprove (from p.can_approve)."""
        src = _detail()
        # canApprove = p.can_approve, then used in disabled={busy || !canApprove}
        assert "!canApprove" in src or "canApprove" in src, (
            "Approve button must gate disabled on canApprove (derived from p.can_approve)."
        )
        # Specifically the disabled expression must use canApprove
        assert "disabled={busy || !canApprove}" in src or \
               "disabled={!canApprove" in src or \
               "disabled={busy||!canApprove" in src, (
            "Approve button disabled prop must use !canApprove."
        )

    def test_disabled_reason_testid_present(self):
        """Disabled-reason display must carry data-testid='proposal-approve-disabled-reason'."""
        src = _detail()
        assert "proposal-approve-disabled-reason" in src, (
            "Disabled reason display must have testid='proposal-approve-disabled-reason'."
        )

    def test_disabled_reason_uses_approve_disabled_reason_var(self):
        """The disabled-reason display must render approveDisabledReason (from backend)."""
        src = _detail()
        assert "approveDisabledReason" in src, (
            "Disabled reason display must render approveDisabledReason "
            "(derived from p.approve_blocked_reason)."
        )

    def test_no_raw_audit_pz_pdf_filename_in_can_approve_logic(self):
        """
        audit.pz_pdf_filename must not appear in any client-side canApprove calculation.
        Backend projects can_approve; the frontend must not re-check the raw field.
        """
        import re
        src = _detail()
        # Find lines that reference pz_pdf_filename near canApprove / proposalPz context
        # A simple heuristic: ensure the two identifiers don't coexist on the same line
        # in an assignment that produces canApprove.
        lines_with_pz_fname = [
            ln for ln in src.splitlines()
            if "pz_pdf_filename" in ln and
               any(kw in ln for kw in ("canApprove", "proposalPz", "can_approve ="))
        ]
        assert lines_with_pz_fname == [], (
            "Found line(s) combining pz_pdf_filename with canApprove derivation — "
            "backend must own PZ readiness; frontend must not re-derive:\n"
            + "\n".join(lines_with_pz_fname)
        )

    def test_no_raw_audit_status_in_can_approve_logic(self):
        """
        audit.status must not drive the approve button state client-side.
        batch-closed logic lives in backend _annotate_can_approve(); frontend must not repeat it.
        """
        import re
        src = _detail()
        lines = [
            ln for ln in src.splitlines()
            if "audit.status" in ln and
               any(kw in ln for kw in ("canApprove", "proposalBatch", "can_approve ="))
        ]
        assert lines == [], (
            "Found line(s) combining audit.status with canApprove derivation — "
            "batch-closed logic belongs in backend _annotate_can_approve():\n"
            + "\n".join(lines)
        )
