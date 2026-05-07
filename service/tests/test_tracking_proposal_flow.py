"""
test_tracking_proposal_flow.py — Cowork tracking proposal integration tests.

Tests:
  1.  DHL API pending → TRACKING_LOOKUP_REQUIRED trigger → tracking_lookup proposal created
  2.  tracking_lookup proposal cannot queue email (queue guard)
  3.  POST /api/v1/tracking/batch/{batch_id}/update writes audit.tracking
  4.  POST /api/v1/tracking/batch/{batch_id}/update logs EV_TRACKING_UPDATED
  5.  Update endpoint closes linked tracking_lookup proposal (done)
  6.  tracking_lookup draft has no email recipients
  7.  tracking_lookup draft has correct cowork fields (awb, tracking_url, channel)
  8.  generate_action_proposals maps PUBLIC_TRACKING_LOOKUP_REQUIRED → tracking_lookup
  9.  tracking_lookup proposal does not appear as email in any queue
  10. Full flow: pending → proposal → update → timeline → proposal done
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch, MagicMock

import pytest

# ── Path + env ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("API_KEY",      "test-key")
# NOTE: no STORAGE_ROOT setdefault — tests use tmp_path for isolation


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    """Point settings.storage_root at tmp_path so all service code is isolated."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    from app.api import routes_action_proposals, routes_tracking
    from app.services import action_email_builder
    for mod in (routes_action_proposals, routes_tracking, action_email_builder):
        monkeypatch.setattr(mod, "_OUTPUTS", tmp_path / "outputs")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_batch(root: Path, extra: Dict[str, Any] | None = None, batch_id: str | None = None):
    bid = batch_id or str(uuid.uuid4())[:8]
    batch_dir = root / "outputs" / bid
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit: Dict[str, Any] = {
        "batch_id":    bid,
        "awb":         "1234567890",
        "tracking_no": "1234567890",
        "status":      "processing",
        "clearance_decision": {
            "total_value_usd": 800.0,
            "clearance_path":  "dhl_self_clearance",
        },
        "timeline": [],
    }
    if extra:
        audit.update(extra)
    ap = batch_dir / "audit.json"
    ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    return bid, batch_dir, ap


def _read_audit(ap: Path) -> Dict[str, Any]:
    return json.loads(ap.read_text(encoding="utf-8"))


# ── Test 1: Trigger → tracking_lookup proposal ───────────────────────────────

class TestTrackingProposalCreation:
    def test_trigger_creates_tracking_lookup_proposal(self, tmp_path):
        """PUBLIC_TRACKING_LOOKUP_REQUIRED → tracking_lookup proposal in audit."""
        bid, _, ap = _make_batch(tmp_path, extra={
            "tracking": {
                "cowork_tracking_required": True,
                "cowork_result_received":   False,
                "tracking_url":             "https://www.dhl.com/...",
                "carrier":                  "DHL",
                "cowork_tracking_reason":   "API pending",
            }
        })
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import generate_action_proposals
        from app.agents.cowork_coordinator import detect_triggers
        suggestions = detect_triggers(audit, bid)
        new = generate_action_proposals(audit, bid, suggestions)

        tracking_proposals = [p for p in new if p["type"] == "tracking_lookup"]
        assert len(tracking_proposals) == 1
        assert tracking_proposals[0]["status"] == "pending_review"

    def test_trigger_mapping_includes_tracking(self):
        """_TRIGGER_TO_TYPE maps both tracking trigger names to tracking_lookup."""
        from app.api.routes_action_proposals import _TRIGGER_TO_TYPE
        assert _TRIGGER_TO_TYPE.get("PUBLIC_TRACKING_LOOKUP_REQUIRED") == "tracking_lookup"
        assert _TRIGGER_TO_TYPE.get("TRACKING_LOOKUP_REQUIRED") == "tracking_lookup"

    def test_no_proposal_when_result_already_received(self, tmp_path):
        """No tracking_lookup proposal when cowork_result_received=True."""
        bid, _, ap = _make_batch(tmp_path, extra={
            "tracking": {
                "cowork_tracking_required": True,
                "cowork_result_received":   True,   # already done
            }
        })
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import generate_action_proposals
        from app.agents.cowork_coordinator import detect_triggers
        suggestions = detect_triggers(audit, bid)
        new = generate_action_proposals(audit, bid, suggestions)

        tracking_proposals = [p for p in new if p["type"] == "tracking_lookup"]
        assert len(tracking_proposals) == 0


# ── Test 2: Queue guard for tracking_lookup ───────────────────────────────────

class TestTrackingLookupQueueGuard:
    def test_tracking_lookup_cannot_queue_email(self):
        """_assert_can_queue raises 422 for tracking_lookup type."""
        from app.api.routes_action_proposals import _assert_can_queue
        from fastapi import HTTPException

        proposal = {
            "proposal_id": str(uuid.uuid4()),
            "type":        "tracking_lookup",
            "status":      "approved",
            "approved_by": "admin",
            "draft":       {"to": "", "cc": "", "subject": ""},
        }
        audit = {"batch_id": "test", "clearance_decision": {"total_value_usd": 0}}

        with pytest.raises(HTTPException) as exc_info:
            _assert_can_queue(proposal, audit)
        assert exc_info.value.status_code == 422
        detail = exc_info.value.detail
        # detail may be dict or str
        detail_str = json.dumps(detail) if isinstance(detail, dict) else str(detail)
        assert "cowork" in detail_str.lower() or "invalid_action" in detail_str

    def test_tracking_lookup_blocked_even_when_approved(self):
        """Even approved tracking_lookup proposals cannot go to queue."""
        from app.api.routes_action_proposals import _assert_can_queue, _NON_EMAIL_TYPES
        assert "tracking_lookup" in _NON_EMAIL_TYPES


# ── Tests 3–4: Update endpoint ────────────────────────────────────────────────

class TestTrackingUpdateEndpoint:
    def test_update_writes_tracking_to_audit(self, tmp_path):
        """POST /batch/{batch_id}/update writes status to audit.tracking."""
        bid, _, ap = _make_batch(tmp_path)

        from app.api.routes_tracking import update_tracking_for_batch, TrackingUpdateBody
        body = TrackingUpdateBody(
            status="customs",
            last_event="Cleared customs at Warsaw",
            location="WARSAW - PL",
            event_time="2026-04-28T10:00:00Z",
            source="cowork",
        )
        result = update_tracking_for_batch(bid, body)

        assert result["ok"] is True
        updated = _read_audit(ap)
        assert updated["tracking"]["status"] == "customs"
        assert updated["tracking"]["last_event"] == "Cleared customs at Warsaw"
        assert updated["tracking"]["cowork_result_received"] is True
        assert updated["tracking"]["cowork_tracking_required"] is False

    def test_update_logs_ev_tracking_updated(self, tmp_path):
        """POST /batch/{batch_id}/update logs EV_TRACKING_UPDATED to timeline."""
        bid, _, ap = _make_batch(tmp_path)

        from app.api.routes_tracking import update_tracking_for_batch, TrackingUpdateBody
        from app.core import timeline as tl
        body = TrackingUpdateBody(status="in_transit", last_event="In transit", source="cowork")
        update_tracking_for_batch(bid, body)

        updated = _read_audit(ap)
        events = [ev["event"] for ev in updated.get("timeline", [])]
        assert tl.EV_TRACKING_UPDATED in events

    def test_update_404_for_unknown_batch(self, tmp_path):
        """Unknown batch_id → 404."""
        from app.api.routes_tracking import update_tracking_for_batch, TrackingUpdateBody
        from fastapi import HTTPException
        body = TrackingUpdateBody(status="in_transit", last_event="test")
        with pytest.raises(HTTPException) as exc_info:
            update_tracking_for_batch("nonexistent_xyz_batch", body)
        assert exc_info.value.status_code == 404

    def test_update_does_not_touch_clearance_decision(self, tmp_path):
        """Update never modifies clearance_decision."""
        bid, _, ap = _make_batch(tmp_path, extra={
            "clearance_decision": {"total_value_usd": 1500.0, "clearance_path": "dhl_self_clearance"}
        })
        before = _read_audit(ap)["clearance_decision"]

        from app.api.routes_tracking import update_tracking_for_batch, TrackingUpdateBody
        body = TrackingUpdateBody(status="delivered", last_event="Delivered")
        update_tracking_for_batch(bid, body)

        after = _read_audit(ap)["clearance_decision"]
        assert after == before


# ── Test 5: Update closes linked proposal ────────────────────────────────────

class TestProposalClosedOnUpdate:
    def test_update_marks_proposal_done(self, tmp_path):
        """If proposal_id supplied, tracking_lookup proposal status → done."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        # Create a tracking_lookup proposal
        from app.api.routes_action_proposals import create_proposal
        prop = create_proposal(audit, bid, "tracking_lookup", "API pending", "high")
        prop_id = prop["proposal_id"]
        ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")

        from app.api.routes_tracking import update_tracking_for_batch, TrackingUpdateBody
        body = TrackingUpdateBody(
            status="in_transit",
            last_event="In transit",
            source="cowork",
            proposal_id=prop_id,
        )
        update_tracking_for_batch(bid, body)

        updated = _read_audit(ap)
        proposals = updated.get("action_proposals", [])
        matching = [p for p in proposals if p["proposal_id"] == prop_id]
        assert len(matching) == 1
        assert matching[0]["status"] == "done"
        assert matching[0]["done_source"] == "cowork"


# ── Tests 6–7: tracking_lookup draft content ──────────────────────────────────

class TestTrackingLookupDraft:
    def test_draft_has_no_email_recipients(self, tmp_path):
        """tracking_lookup draft has empty to/cc."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.services.action_email_builder import build_email_draft
        draft = build_email_draft("tracking_lookup", audit)

        assert draft["to"] == ""
        assert draft["cc"] == ""

    def test_draft_has_cowork_fields(self, tmp_path):
        """tracking_lookup draft has channel=cowork, awb, tracking_url."""
        bid, _, ap = _make_batch(tmp_path, extra={"carrier": "DHL"})
        audit = _read_audit(ap)

        from app.services.action_email_builder import build_email_draft
        draft = build_email_draft("tracking_lookup", audit)

        assert draft["channel"] == "cowork"
        assert draft["awb"] == "1234567890"
        assert draft["tracking_url"]
        assert "dhl.com" in draft["tracking_url"]

    def test_draft_fedex_url_for_fedex_carrier(self, tmp_path):
        """FedEx carrier → FedEx tracking URL in draft."""
        bid, _, ap = _make_batch(tmp_path, extra={"carrier": "FedEx", "awb": "123456789012"})
        audit = _read_audit(ap)

        from app.services.action_email_builder import build_email_draft
        draft = build_email_draft("tracking_lookup", audit)

        assert "fedex.com" in draft["tracking_url"]


# ── Test 8: generate_action_proposals maps trigger ───────────────────────────

class TestTriggerToProposalMapping:
    def test_public_tracking_trigger_maps_to_tracking_lookup(self, tmp_path):
        """generate_action_proposals: PUBLIC_TRACKING_LOOKUP_REQUIRED → tracking_lookup."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        from app.api.routes_action_proposals import generate_action_proposals
        sug = [{
            "trigger":    "PUBLIC_TRACKING_LOOKUP_REQUIRED",
            "reason":     "DHL API pending",
            "confidence": "low",
            "action":     "Open public tracking",
            "batch_id":   bid,
            "awb":        "1234567890",
        }]
        new = generate_action_proposals(audit, bid, sug)
        assert any(p["type"] == "tracking_lookup" for p in new)


# ── Test 9: no email queued ───────────────────────────────────────────────────

class TestNoEmailForTracking:
    def test_tracking_lookup_not_in_email_queue(self, tmp_path):
        """Creating and 'completing' a tracking_lookup proposal never calls queue_email."""
        bid, _, ap = _make_batch(tmp_path)
        audit = _read_audit(ap)

        with patch("app.services.email_service.queue_email") as mock_q:
            from app.api.routes_action_proposals import create_proposal, generate_action_proposals
            sug = [{"trigger": "PUBLIC_TRACKING_LOOKUP_REQUIRED", "reason": "test",
                    "confidence": "low", "action": "", "batch_id": bid, "awb": "1234567890"}]
            generate_action_proposals(audit, bid, sug)
            mock_q.assert_not_called()

            from app.api.routes_tracking import update_tracking_for_batch, TrackingUpdateBody
            ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
            body = TrackingUpdateBody(status="in_transit", last_event="test")
            update_tracking_for_batch(bid, body)
            mock_q.assert_not_called()


# ── Test 10: Full flow ─────────────────────────────────────────────────────────

class TestFullTrackingFlow:
    def test_full_flow_pending_to_done(self, tmp_path):
        """
        Full flow:
          cowork_tracking_required=True
          → detect_triggers fires
          → proposal created (pending_review)
          → update endpoint called
          → audit.tracking written
          → EV_TRACKING_UPDATED on timeline
          → proposal marked done
        """
        bid, _, ap = _make_batch(tmp_path, extra={
            "tracking": {
                "cowork_tracking_required": True,
                "cowork_result_received":   False,
                "tracking_url":             "https://www.dhl.com/test",
                "carrier":                  "DHL",
                "cowork_tracking_reason":   "API pending",
            }
        })
        audit = _read_audit(ap)

        # Step 1: detect trigger + create proposal
        from app.agents.cowork_coordinator import detect_triggers
        from app.api.routes_action_proposals import generate_action_proposals
        suggestions = detect_triggers(audit, bid)
        new = generate_action_proposals(audit, bid, suggestions)
        assert any(p["type"] == "tracking_lookup" for p in new)
        prop_id = next(p["proposal_id"] for p in new if p["type"] == "tracking_lookup")
        ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")

        # Step 2: update endpoint closes the loop
        from app.api.routes_tracking import update_tracking_for_batch, TrackingUpdateBody
        from app.core import timeline as tl
        body = TrackingUpdateBody(
            status="cleared",
            last_event="Shipment cleared customs",
            location="WARSAW - PL",
            source="cowork",
            proposal_id=prop_id,
        )
        result = update_tracking_for_batch(bid, body)
        assert result["ok"] is True

        # Step 3: verify final state
        final = _read_audit(ap)
        assert final["tracking"]["status"] == "cleared"
        assert final["tracking"]["cowork_tracking_required"] is False
        assert final["tracking"]["cowork_result_received"] is True

        tl_events = [ev["event"] for ev in final.get("timeline", [])]
        assert tl.EV_TRACKING_UPDATED in tl_events

        done_proposals = [
            p for p in final.get("action_proposals", [])
            if p["proposal_id"] == prop_id and p["status"] == "done"
        ]
        assert len(done_proposals) == 1
