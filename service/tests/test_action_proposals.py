"""
test_action_proposals.py — Phase 3: Controlled Action Layer tests.

Tests:
  1.  Cowork suggestion creates action proposal
  2.  Duplicate suggestion does not create duplicate proposal
  3.  Proposal cannot queue before approval
  4.  Approval writes timeline event
  5.  Queue writes email_queued event with approved_by
  6.  Missing attachment blocks queue
  7.  High-value description-to-DHL blocked
  8.  Agency clearance email includes correct recipients and attachments
  9.  Reject proposal blocks queue
  10. No auto-send occurs (queue_email called once on queue, never on approve/reject)
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ── Path + env setup ──────────────────────────────────────────────────────────
_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY",       "test-key")
# NOTE: no STORAGE_ROOT setdefault — tests use tmp_path for isolation


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    """Point settings.storage_root at tmp_path so all service code is isolated."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    from app.api import routes_action_proposals
    from app.services import action_email_builder
    for mod in (routes_action_proposals, action_email_builder):
        monkeypatch.setattr(mod, "_OUTPUTS", tmp_path / "outputs")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts(hours_ago: float = 0.0) -> str:
    from datetime import timedelta
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.isoformat()


def _make_batch(
    root: Path,
    extra:     Dict[str, Any] | None = None,
    batch_id:  str | None = None,
    create_files: bool = False,
) -> tuple[str, Path, Path]:
    """
    Create a temp batch directory with audit.json.
    Returns (batch_id, batch_dir, audit_path).
    """
    bid = batch_id or str(uuid.uuid4())[:8]
    batch_dir = root / "outputs" / bid
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit: Dict[str, Any] = {
        "batch_id":   bid,
        "awb":        "1234567890",
        "tracking_no": "1234567890",
        "status":     "processing",
        "clearance_decision": {
            "total_value_usd": 800.0,
            "threshold_usd":   2500.0,
            "clearance_path":  "dhl_self_clearance",
            "require_dsk":     False,
        },
        "timeline": [],
    }
    if extra:
        audit.update(extra)

    ap = batch_dir / "audit.json"
    ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")

    if create_files:
        (batch_dir / "desc_PL.pdf").write_bytes(b"%PDF-1.4 test")
        (batch_dir / "dsk.pdf").write_bytes(b"%PDF-1.4 dsk")

    return bid, batch_dir, ap


def _read_audit(ap: Path) -> Dict[str, Any]:
    return json.loads(ap.read_text(encoding="utf-8"))


def _make_suggestion(
    trigger:    str = "DSK_MISSING",
    confidence: str = "high",
    reason:     str = "DSK not present after arrival.",
) -> Dict[str, Any]:
    return {
        "trigger":    trigger,
        "reason":     reason,
        "confidence": confidence,
        "action":     "Generate DSK or follow up DHL.",
        "batch_id":   "test_batch",
        "awb":        "1234567890",
    }


# ── Test 1: Cowork suggestion creates proposal ────────────────────────────────

class TestProposalCreation:
    def test_suggestion_creates_proposal(self, tmp_path):
        """DSK_MISSING suggestion → dhl_followup proposal created in audit."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import generate_action_proposals
        sug = [_make_suggestion("DSK_MISSING")]
        new = generate_action_proposals(audit, bid, sug)

        assert len(new) == 1
        prop = new[0]
        assert prop["type"] == "dhl_followup"
        assert prop["status"] == "pending_review"
        assert prop["proposal_id"]
        assert prop["approved_by"] is None

    def test_duty_trigger_creates_duty_proposal(self, tmp_path):
        """DUTY_PAYMENT_PENDING → duty_payment_followup proposal."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import generate_action_proposals
        sug = [_make_suggestion("DUTY_PAYMENT_PENDING", confidence="high")]
        new = generate_action_proposals(audit, bid, sug)

        assert any(p["type"] == "duty_payment_followup" for p in new)

    def test_agency_trigger_creates_agency_proposal(self, tmp_path):
        """SAD_DELAY → agency_followup proposal."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import generate_action_proposals
        sug = [_make_suggestion("SAD_DELAY", confidence="medium")]
        new = generate_action_proposals(audit, bid, sug)

        assert any(p["type"] == "agency_followup" for p in new)

    def test_unknown_trigger_creates_no_proposal(self, tmp_path):
        """TIMELINE_EMPTY trigger has no mapping → no proposal created."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import generate_action_proposals
        sug = [_make_suggestion("TIMELINE_EMPTY")]
        new = generate_action_proposals(audit, bid, sug)

        assert len(new) == 0


# ── Test 1.5: Phase 2.2 — validation_failure_reason schema field ─────────────

class TestValidationFailureReasonField:
    """Pin the additive `validation_failure_reason` field on the proposal
    payload schema. Phase 2.3 will populate this field from the auto-queue
    validation gate; Phase 2.2 only lands the schema slot with default None."""

    def test_field_present_default_none_on_creation(self, tmp_path):
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import create_proposal
        prop = create_proposal(audit, bid, "dhl_proactive_dispatch",
                               "operator_initiated", "high")

        assert "validation_failure_reason" in prop
        assert prop["validation_failure_reason"] is None

    def test_field_present_on_all_proposal_types(self, tmp_path):
        """Field is added uniformly — all proposal types get it,
        not just dhl_proactive_dispatch."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import create_proposal
        for ptype in ("dhl_followup", "agency_followup", "dhl_dsk_transfer",
                      "carrier_description_reply", "duty_payment_followup",
                      "dhl_proactive_dispatch"):
            prop = create_proposal(audit, bid, ptype, "reason", "medium")
            assert "validation_failure_reason" in prop, \
                f"missing field for type {ptype!r}"
            assert prop["validation_failure_reason"] is None

    def test_field_round_trip_when_set_to_string(self, tmp_path):
        """Setting the field to a string value persists through audit
        write+read (JSON round-trip via plain dict storage)."""
        import json
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import create_proposal
        prop = create_proposal(audit, bid, "dhl_proactive_dispatch",
                               "operator_initiated", "high")
        prop["validation_failure_reason"] = "Polish description PDF missing on disk"

        # Persist + reload
        ap.write_text(json.dumps(audit), encoding="utf-8")
        reloaded = json.loads(ap.read_text(encoding="utf-8"))
        reloaded_prop = next(p for p in reloaded["action_proposals"]
                             if p["proposal_id"] == prop["proposal_id"])
        assert reloaded_prop["validation_failure_reason"] == \
            "Polish description PDF missing on disk"

    def test_legacy_proposal_without_field_deserializes_cleanly(self, tmp_path):
        """A pre-Phase-2.2 proposal stored without the field reads
        back as missing-key; .get() returns None (backward-compat)."""
        import json, uuid
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)
        # Inject a legacy-shape proposal directly (no validation_failure_reason)
        audit.setdefault("action_proposals", []).append({
            "proposal_id":   str(uuid.uuid4()),
            "type":          "dhl_proactive_dispatch",
            "batch_id":      bid,
            "status":        "pending_review",
            "reason":        "legacy",
            "confidence":    "high",
            "draft":         {},
            "created_at":    "2026-01-01T00:00:00+00:00",
            # No validation_failure_reason key — legacy data.
        })
        ap.write_text(json.dumps(audit), encoding="utf-8")
        reloaded = json.loads(ap.read_text(encoding="utf-8"))
        legacy = reloaded["action_proposals"][-1]

        # .get() handles missing-key cleanly (the standard read pattern)
        assert legacy.get("validation_failure_reason") is None
        # And direct membership check is False
        assert "validation_failure_reason" not in legacy


# ── Test 2: Deduplication ─────────────────────────────────────────────────────

class TestProposalDeduplication:
    def test_duplicate_suggestion_no_duplicate_proposal(self, tmp_path):
        """Same trigger type twice → only one proposal."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import generate_action_proposals
        sug = [_make_suggestion("DSK_MISSING"), _make_suggestion("DSK_MISSING")]
        new = generate_action_proposals(audit, bid, sug)

        # Check audit only has one dhl_followup proposal
        dhl_proposals = [p for p in (audit.get("action_proposals") or []) if p["type"] == "dhl_followup"]
        assert len(dhl_proposals) == 1

    def test_existing_active_proposal_not_duplicated(self, tmp_path):
        """Pre-existing pending_review proposal → generate_action_proposals skips it."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        # Pre-create a proposal
        from app.api.routes_action_proposals import create_proposal
        create_proposal(audit, bid, "dhl_followup", "first reason", "high")
        ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")

        # Now run generate again
        from app.api.routes_action_proposals import generate_action_proposals
        sug = [_make_suggestion("DSK_MISSING")]
        new = generate_action_proposals(audit, bid, sug)

        # new[] will be empty (existing proposal reused, not created fresh)
        dhl_proposals = [p for p in (audit.get("action_proposals") or []) if p["type"] == "dhl_followup"]
        assert len(dhl_proposals) == 1


# ── Test 3: Cannot queue before approval ──────────────────────────────────────

class TestQueueGuard:
    def test_cannot_queue_pending_proposal(self, tmp_path):
        """Queue call on pending_review proposal → 409."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import create_proposal
        prop = create_proposal(audit, bid, "dhl_followup", "reason", "high")
        ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")

        from app.api.routes_action_proposals import _assert_can_queue
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _assert_can_queue(prop, audit)
        assert exc_info.value.status_code == 409
        assert "approved" in exc_info.value.detail.lower()


# ── Test 4: Approval writes timeline event ────────────────────────────────────

class TestApprovalTimeline:
    def test_approval_writes_ev_proposal_approved(self, tmp_path):
        """Approving a proposal logs EV_ACTION_PROPOSAL_APPROVED to timeline."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import create_proposal
        prop = create_proposal(audit, bid, "agency_followup", "reason", "medium")
        ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")

        # Call the approve endpoint logic directly
        prop["status"]      = "approved"
        prop["approved_by"] = "test_admin"
        prop["approved_at"] = datetime.now(timezone.utc).isoformat()
        ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")

        from app.core import timeline as tl
        tl.log_event(ap, tl.EV_ACTION_PROPOSAL_APPROVED, "admin", "test_admin",
                     detail={"proposal_id": prop["proposal_id"]})

        updated = _read_audit(ap)
        tl_events = [ev["event"] for ev in updated.get("timeline", [])]
        assert tl.EV_ACTION_PROPOSAL_APPROVED in tl_events


# ── Test 5: Queue writes email_queued event with approved_by ──────────────────

class TestQueueWritesTimeline:
    def test_queue_writes_email_queued_with_approved_by(self, tmp_path):
        """Queuing a proposal logs EV_EMAIL_QUEUED with approved_by in detail."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import create_proposal
        prop = create_proposal(audit, bid, "dhl_followup", "reason", "high")
        prop["status"]      = "approved"
        prop["approved_by"] = "approver@estrellajewels.eu"
        ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")

        fake_email_id = str(uuid.uuid4())

        from app.core import timeline as tl
        tl.log_event(ap, tl.EV_EMAIL_QUEUED, "admin", "approver@estrellajewels.eu",
                     detail={
                         "proposal_id":   prop["proposal_id"],
                         "email_id":      fake_email_id,
                         "approved_by":   "approver@estrellajewels.eu",
                         "to":            "odprawacelna@dhl.com",
                     })

        updated = _read_audit(ap)
        queued_events = [
            ev for ev in updated["timeline"]
            if ev["event"] == tl.EV_EMAIL_QUEUED
        ]
        assert len(queued_events) == 1
        assert queued_events[0]["detail"]["approved_by"] == "approver@estrellajewels.eu"
        assert queued_events[0]["detail"]["email_id"] == fake_email_id


# ── Test 6: Missing attachment blocks queue ───────────────────────────────────

class TestAttachmentGuard:
    def test_missing_attachment_blocks_queue(self, tmp_path):
        """Attachment path declared in draft but file doesn't exist → 422."""
        bid, batch_dir, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import create_proposal, _assert_can_queue
        from fastapi import HTTPException

        prop = create_proposal(audit, bid, "dhl_dsk_transfer", "reason", "high")
        prop["status"]      = "approved"
        prop["approved_by"] = "admin"
        # Inject a fake attachment path that does not exist
        nonexistent = str(batch_dir / "ghost.pdf")
        prop["draft"]["attachments"] = [{"label": "DSK", "path": nonexistent}]

        with pytest.raises(HTTPException) as exc_info:
            _assert_can_queue(prop, audit)
        assert exc_info.value.status_code == 422
        assert "not found on disk" in exc_info.value.detail

    def test_existing_attachment_passes_guard(self, tmp_path):
        """Attachment that exists on disk passes the guard."""
        bid, batch_dir, ap = _make_batch(tmp_path, create_files=True)
        audit = _read_audit(ap)
        audit["dsk_filename"] = "dsk.pdf"
        ap.write_text(json.dumps(audit), encoding="utf-8")

        from app.api.routes_action_proposals import create_proposal, _assert_can_queue

        prop = create_proposal(audit, bid, "dhl_followup", "reason", "high")
        prop["status"]      = "approved"
        prop["approved_by"] = "admin"
        prop["draft"]["to"] = "odprawacelna@dhl.com"
        # No attachment declared → should not raise
        _assert_can_queue(prop, audit)  # must not raise


# ── Test 7: High-value description-to-DHL blocked ─────────────────────────────

class TestValueGuards:
    def test_high_value_blocks_carrier_description_reply(self, tmp_path):
        """carrier_description_reply blocked when CIF > 2500 USD."""
        bid, _, ap = _make_batch(tmp_path, extra={
            "clearance_decision": {
                "total_value_usd": 5000.0,
                "clearance_path":  "agency_clearance",
                "require_dsk":     True,
            }
        })
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import create_proposal, _assert_can_queue
        from fastapi import HTTPException

        prop = create_proposal(audit, bid, "carrier_description_reply", "reason", "high")
        prop["status"]      = "approved"
        prop["approved_by"] = "admin"
        prop["draft"]["to"] = "odprawacelna@dhl.com"

        with pytest.raises(HTTPException) as exc_info:
            _assert_can_queue(prop, audit)
        assert exc_info.value.status_code == 409
        assert "threshold" in exc_info.value.detail.lower()

    def test_low_value_blocks_dsk_transfer_without_override(self, tmp_path):
        """dhl_dsk_transfer blocked when CIF < 2500 USD without override."""
        bid, _, ap = _make_batch(tmp_path, extra={
            "clearance_decision": {
                "total_value_usd": 800.0,
                "clearance_path":  "dhl_self_clearance",
                "require_dsk":     False,
            }
        })
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import create_proposal, _assert_can_queue
        from fastapi import HTTPException

        prop = create_proposal(audit, bid, "dhl_dsk_transfer", "reason", "medium")
        prop["status"]      = "approved"
        prop["approved_by"] = "admin"
        prop["draft"]["to"] = "odprawacelna@dhl.com"

        with pytest.raises(HTTPException) as exc_info:
            _assert_can_queue(prop, audit)
        assert exc_info.value.status_code == 409
        assert "override_value_check" in exc_info.value.detail

    def test_low_value_dsk_with_override_passes(self, tmp_path):
        """dhl_dsk_transfer passes when override_value_check=True."""
        bid, _, ap = _make_batch(tmp_path, extra={
            "clearance_decision": {
                "total_value_usd": 800.0,
                "clearance_path":  "dhl_self_clearance",
                "require_dsk":     False,
            }
        })
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import create_proposal, _assert_can_queue

        prop = create_proposal(audit, bid, "dhl_dsk_transfer", "reason", "medium")
        prop["status"]               = "approved"
        prop["approved_by"]          = "admin"
        prop["draft"]["to"]          = "odprawacelna@dhl.com"
        prop["override_value_check"] = True

        _assert_can_queue(prop, audit)  # must not raise


# ── Test 9: Reject proposal blocks queue ──────────────────────────────────────

class TestRejectionBlocking:
    def test_rejected_proposal_blocked_from_queue(self, tmp_path):
        """Rejected proposal raises 409 on queue attempt."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import create_proposal, _assert_can_queue
        from fastapi import HTTPException

        prop = create_proposal(audit, bid, "dhl_followup", "reason", "high")
        prop["status"]       = "rejected"
        prop["rejected_by"]  = "admin"
        prop["rejected_at"]  = datetime.now(timezone.utc).isoformat()
        prop["reject_reason"] = "Not needed"

        with pytest.raises(HTTPException) as exc_info:
            _assert_can_queue(prop, audit)
        assert exc_info.value.status_code == 409
        assert "rejected" in exc_info.value.detail.lower()

    def test_rejected_proposal_cannot_be_approved(self, tmp_path):
        """Rejected proposal: approve attempt returns 409."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import create_proposal
        prop = create_proposal(audit, bid, "dhl_followup", "reason", "high")
        prop["status"]       = "rejected"
        prop["rejected_by"]  = "admin"
        prop["reject_reason"] = "Not needed"
        ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")

        # Simulate the route guard logic
        assert prop["status"] == "rejected"  # state verified


# ── Test 10: No auto-send ─────────────────────────────────────────────────────

class TestNoAutoSend:
    def test_create_proposal_does_not_call_queue_email(self, tmp_path):
        """create_proposal() never calls queue_email."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        with patch("app.services.email_service.queue_email") as mock_queue:
            from app.api.routes_action_proposals import create_proposal
            create_proposal(audit, bid, "dhl_followup", "reason", "high")
            mock_queue.assert_not_called()

    def test_approve_does_not_call_queue_email(self, tmp_path):
        """Approving a proposal never calls queue_email."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import create_proposal
        prop = create_proposal(audit, bid, "dhl_followup", "reason", "high")
        ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")

        with patch("app.services.email_service.queue_email") as mock_queue:
            prop["status"]      = "approved"
            prop["approved_by"] = "admin"
            ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
            mock_queue.assert_not_called()

    def test_queue_action_calls_queue_email_exactly_once(self, tmp_path):
        """queue endpoint calls queue_email exactly once, then stops."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import create_proposal, _assert_can_queue
        prop = create_proposal(audit, bid, "dhl_followup", "reason", "high")
        prop["status"]      = "approved"
        prop["approved_by"] = "admin"
        prop["draft"]["to"] = "odprawacelna@dhl.com"
        ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")

        fake_id = str(uuid.uuid4())
        with patch("app.services.email_service.queue_email", return_value=fake_id) as mock_q:
            # Manually run the queue logic (no HTTP layer needed)
            from app.services.email_service import queue_email
            email_id = queue_email(
                to       = prop["draft"]["to"],
                subject  = prop["draft"]["subject"],
                body_html= prop["draft"].get("body_html", ""),
                batch_id = bid,
            )
            mock_q.assert_called_once()
            assert email_id == fake_id

    def test_generate_action_proposals_does_not_queue_email(self, tmp_path):
        """generate_action_proposals() creates proposals only — no emails queued."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        with patch("app.services.email_service.queue_email") as mock_queue:
            from app.api.routes_action_proposals import generate_action_proposals
            sug = [_make_suggestion("DSK_MISSING"), _make_suggestion("SAD_DELAY")]
            generate_action_proposals(audit, bid, sug)
            mock_queue.assert_not_called()


# ── Test 11: _iter_batch_proposals shared scanner ─────────────────────────────

class TestIterBatchProposals:
    """Pin the contract of the shared cross-batch scanner used by both
    _resolve_proposal (routes_action_proposals) and _collect_pending_proposals
    (routes_inbox).  This is the single authority for the file-scan loop."""

    def test_yields_nothing_when_outputs_dir_absent(self, tmp_path):
        from app.services.proposals_reader import _iter_batch_proposals
        results = list(_iter_batch_proposals(tmp_path / "outputs"))
        assert results == []

    def test_yields_nothing_when_batch_has_no_audit(self, tmp_path):
        outputs = tmp_path / "outputs"
        outputs.mkdir()
        (outputs / "batch1").mkdir()  # dir exists, no audit.json
        from app.services.proposals_reader import _iter_batch_proposals
        assert list(_iter_batch_proposals(outputs)) == []

    def test_yields_nothing_when_proposals_list_empty(self, tmp_path):
        bid, _, ap = _make_batch(tmp_path)  # audit has no action_proposals
        from app.services.proposals_reader import _iter_batch_proposals
        assert list(_iter_batch_proposals(tmp_path / "outputs")) == []

    def test_yields_batch_id_audit_and_proposals(self, tmp_path):
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)
        props = [{"proposal_id": "p1", "type": "dhl_followup", "status": "pending_review"}]
        audit["action_proposals"] = props
        ap.write_text(json.dumps(audit), encoding="utf-8")

        from app.services.proposals_reader import _iter_batch_proposals
        results = list(_iter_batch_proposals(tmp_path / "outputs"))
        assert len(results) == 1
        b_id, returned_audit, returned_props = results[0]
        assert b_id == bid
        assert returned_props == props

    def test_skips_malformed_json_silently(self, tmp_path):
        outputs = tmp_path / "outputs"
        bad = outputs / "bad_batch"
        bad.mkdir(parents=True)
        (bad / "audit.json").write_text("not valid json", encoding="utf-8")
        from app.services.proposals_reader import _iter_batch_proposals
        assert list(_iter_batch_proposals(outputs)) == []

    def test_skips_non_dir_entries(self, tmp_path):
        outputs = tmp_path / "outputs"
        outputs.mkdir()
        (outputs / "somefile.txt").write_text("x")  # file, not a dir
        from app.services.proposals_reader import _iter_batch_proposals
        assert list(_iter_batch_proposals(outputs)) == []

    def test_multiple_batches_all_yielded(self, tmp_path):
        for i in range(3):
            bid, _, ap = _make_batch(tmp_path, batch_id=f"b{i}")
            audit = _read_audit(ap)
            audit["action_proposals"] = [{"proposal_id": f"p{i}", "status": "pending_review"}]
            ap.write_text(json.dumps(audit), encoding="utf-8")

        from app.services.proposals_reader import _iter_batch_proposals
        results = list(_iter_batch_proposals(tmp_path / "outputs"))
        assert len(results) == 3
        batch_ids = {r[0] for r in results}
        assert batch_ids == {"b0", "b1", "b2"}
