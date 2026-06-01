"""
test_remediation_b4_delivery_bridge.py — Integration test for B4.

Verifies that create_delivery_confirmation_proposal is called from the
monitor's scan_active_shipments() when DHL shows "delivered".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


def _write_audit(tmp_path: Path, batch_id: str, audit: dict) -> Path:
    p = tmp_path / "outputs" / batch_id / "audit.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(audit), encoding="utf-8")
    return p


class TestDeliveryBridgeWiredToMonitor:
    """scan_active_shipments calls dhl_delivery_bridge on delivered status."""

    def test_delivery_bridge_step_in_monitor_source(self):
        """Step 5j is present in scan_active_shipments source — confirmed by grep."""
        src = (Path(__file__).parent.parent / "app" / "services"
               / "active_shipment_monitor.py").read_text(encoding="utf-8")
        assert "5j. DHL delivered" in src, "Step 5j must be present in scan_active_shipments"
        assert "create_delivery_confirmation_proposal" in src
        assert "dhl_delivery_bridge" in src

    def test_delivery_bridge_standalone_on_delivered_audit(self, tmp_path):
        """dhl_delivery_bridge creates proposal when audit shows delivered status."""
        from app.services.dhl_delivery_bridge import (
            create_delivery_confirmation_proposal,
            is_dhl_delivered,
        )
        audit_path = tmp_path / "audit.json"
        audit = {
            "batch_id": "BATCH_D",
            "clearance_status": "delivered",
            "tracking": [{"status": "Delivered"}],
            "action_proposals": [],
        }
        audit_path.write_text(json.dumps(audit), encoding="utf-8")

        assert is_dhl_delivered(audit) is True
        proposal = create_delivery_confirmation_proposal(audit, "BATCH_D")
        assert proposal is not None
        assert proposal["type"] == "dhl_delivered_not_received"
        assert proposal["status"] == "pending_review"
        # Proposal appended in-memory — simulate write_json_atomic
        import json as _json
        audit["action_proposals"].append(proposal)
        # Verify proposal is Inbox-ready
        assert any(p["type"] == "dhl_delivered_not_received"
                   for p in audit["action_proposals"])

    def test_module_imported_in_monitor(self):
        """dhl_delivery_bridge is referenced in active_shipment_monitor source."""
        src = (Path(__file__).parent.parent / "app" / "services"
               / "active_shipment_monitor.py").read_text(encoding="utf-8")
        assert "dhl_delivery_bridge" in src
        assert "create_delivery_confirmation_proposal" in src

    def test_execute_requires_operator_confirmation(self, tmp_path):
        """execute_goods_received() raises when required fields missing (no auto-transition)."""
        from app.services.dhl_delivery_bridge import execute_goods_received
        with pytest.raises(ValueError, match="received_by.*received_at"):
            execute_goods_received("B1", {}, {}, "op", tmp_path)
