"""
test_phase7_dhl_delivery_bridge.py — Phase 7 evidence tests.

Verifies the DHL→inventory lifecycle bridge:
1. is_dhl_delivered correctly detects delivered status in multiple audit shapes
2. create_delivery_confirmation_proposal creates proposal when delivered
3. No auto-transition: state only moves on explicit operator confirm
4. Deduplication: one pending proposal per batch
5. is_received_confirmed detects approved proposals
6. Module has no DHL API calls
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


class TestIsDelivered:
    """is_dhl_delivered detection."""

    def test_detects_tracking_delivered_status(self):
        from app.services.dhl_delivery_bridge import is_dhl_delivered
        audit = {"tracking": [{"status": "Delivered", "description": "Package delivered"}]}
        assert is_dhl_delivered(audit) is True

    def test_detects_clearance_status_delivered(self):
        from app.services.dhl_delivery_bridge import is_dhl_delivered
        audit = {"clearance_status": "delivered_and_cleared"}
        assert is_dhl_delivered(audit) is True

    def test_not_delivered_when_no_signal(self):
        from app.services.dhl_delivery_bridge import is_dhl_delivered
        audit = {"clearance_status": "dhl_email_received"}
        assert is_dhl_delivered(audit) is False

    def test_attempted_delivery_not_delivered(self):
        from app.services.dhl_delivery_bridge import is_dhl_delivered
        audit = {"tracking": [{"status": "Delivery attempted", "description": "Delivery attempted"}]}
        assert is_dhl_delivered(audit) is False

    def test_empty_audit_not_delivered(self):
        from app.services.dhl_delivery_bridge import is_dhl_delivered
        assert is_dhl_delivered({}) is False


class TestProposalCreation:
    """create_delivery_confirmation_proposal."""

    def test_creates_proposal_when_delivered(self):
        from app.services.dhl_delivery_bridge import (
            create_delivery_confirmation_proposal,
            PROP_DHL_DELIVERED_NOT_RECEIVED, DELIVERY_BRIDGE_CHANNEL,
        )
        audit = {"clearance_status": "delivered_to_warehouse", "action_proposals": []}
        proposal = create_delivery_confirmation_proposal(audit, "BATCH1")
        assert proposal is not None
        assert proposal["type"] == PROP_DHL_DELIVERED_NOT_RECEIVED
        assert proposal["channel"] == DELIVERY_BRIDGE_CHANNEL
        assert proposal["status"] == "pending_review"
        assert len(audit["action_proposals"]) == 1

    def test_no_proposal_when_not_delivered(self):
        from app.services.dhl_delivery_bridge import create_delivery_confirmation_proposal
        audit = {"clearance_status": "dhl_email_received"}
        result = create_delivery_confirmation_proposal(audit, "BATCH2")
        assert result is None

    def test_deduplication_prevents_second_proposal(self):
        from app.services.dhl_delivery_bridge import create_delivery_confirmation_proposal
        audit = {"clearance_status": "delivered_final"}
        create_delivery_confirmation_proposal(audit, "BATCH3")  # first
        create_delivery_confirmation_proposal(audit, "BATCH3")  # second (should dedup)
        assert len(audit["action_proposals"]) == 1

    def test_no_proposal_when_already_confirmed(self):
        from app.services.dhl_delivery_bridge import (
            create_delivery_confirmation_proposal,
            PROP_DHL_DELIVERED_NOT_RECEIVED, DELIVERY_BRIDGE_CHANNEL,
        )
        audit = {
            "clearance_status": "delivered_to_warehouse",
            "action_proposals": [{
                "type":    PROP_DHL_DELIVERED_NOT_RECEIVED,
                "channel": DELIVERY_BRIDGE_CHANNEL,
                "status":  "approved",
            }]
        }
        result = create_delivery_confirmation_proposal(audit, "BATCH4")
        assert result is None

    def test_proposal_has_resolution_data_fields(self):
        from app.services.dhl_delivery_bridge import create_delivery_confirmation_proposal
        audit = {"clearance_status": "delivered", "tracking": [{"status": "Delivered"}]}
        proposal = create_delivery_confirmation_proposal(audit, "BATCH5")
        assert proposal is not None
        rd = proposal.get("resolution_data", {})
        assert "received_by" in rd
        assert "received_at" in rd
        assert "location" in rd


class TestReceivedConfirmed:
    """is_received_confirmed detects approval."""

    def test_confirmed_when_proposal_approved(self):
        from app.services.dhl_delivery_bridge import (
            is_received_confirmed,
            PROP_DHL_DELIVERED_NOT_RECEIVED, DELIVERY_BRIDGE_CHANNEL,
        )
        audit = {"action_proposals": [{
            "type":    PROP_DHL_DELIVERED_NOT_RECEIVED,
            "channel": DELIVERY_BRIDGE_CHANNEL,
            "status":  "approved",
        }]}
        assert is_received_confirmed(audit) is True

    def test_not_confirmed_when_pending(self):
        from app.services.dhl_delivery_bridge import (
            is_received_confirmed,
            PROP_DHL_DELIVERED_NOT_RECEIVED, DELIVERY_BRIDGE_CHANNEL,
        )
        audit = {"action_proposals": [{
            "type":    PROP_DHL_DELIVERED_NOT_RECEIVED,
            "channel": DELIVERY_BRIDGE_CHANNEL,
            "status":  "pending_review",
        }]}
        assert is_received_confirmed(audit) is False

    def test_not_confirmed_when_no_proposals(self):
        from app.services.dhl_delivery_bridge import is_received_confirmed
        assert is_received_confirmed({}) is False


class TestNoDhlApiCalls:
    """Module must not call DHL API."""

    def test_no_dhl_api_import(self):
        module_path = (
            Path(__file__).parent.parent / "app" / "services" / "dhl_delivery_bridge.py"
        )
        source = module_path.read_text(encoding="utf-8")
        assert "dhl_client" not in source, "Must not call DHL API client"
        assert "_http_request" not in source
        assert "requests.get" not in source
        assert "wfirma_client" not in source

    def test_execute_requires_explicit_operator(self, tmp_path):
        """execute_goods_received raises ValueError when required fields missing."""
        from app.services.dhl_delivery_bridge import execute_goods_received
        proposal = {"proposal_id": "P1"}
        with pytest.raises(ValueError, match="received_by.*received_at"):
            execute_goods_received("BATCH_T", proposal, {}, "operator", tmp_path)
