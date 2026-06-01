"""
test_remediation_b7_product_registration.py — Integration tests for B7.

Verifies wfirma_product_registration creates inbox proposal when
missing products are detected at proforma draft-build time.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


class TestRegistrationProposalCreated:
    def test_proposal_created_on_unsynced_product(self, monkeypatch, tmp_path):
        from app.core.config import settings
        from app.services.wfirma_product_registration import create_registration_proposal, PROP_PRODUCT_NOT_SYNCED, REGISTRATION_CHANNEL

        audit = {"batch_id": "BATCH_REG", "action_proposals": []}
        proposal = create_registration_proposal(audit, "BATCH_REG", ["PC-UNSYNCED-1"])
        assert proposal is not None
        assert proposal["type"] == PROP_PRODUCT_NOT_SYNCED
        assert proposal["channel"] == REGISTRATION_CHANNEL
        assert proposal["status"] == "pending_review"
        ctx = proposal.get("context", {})
        assert "PC-UNSYNCED-1" in ctx.get("unsynced_product_codes", [])

    def test_dispatch_blocked_when_flag_off(self, monkeypatch):
        from app.core.config import settings
        from app.services.wfirma_product_registration import dispatch_registration
        monkeypatch.setattr(settings, "wfirma_create_product_allowed", False)
        result = dispatch_registration("B1", {}, "operator")
        assert result["ok"] is False
        assert "WFIRMA_CREATE_PRODUCT_ALLOWED" in result["error"]

    def test_registration_referenced_in_proforma_routes(self):
        """The proforma route references wfirma_product_registration at the
        missing-products advisory path — source-grep proof."""
        src = (Path(__file__).parent.parent / "app" / "api" / "routes_proforma.py"
               ).read_text(encoding="utf-8")
        assert "wfirma_product_registration" in src
        assert "create_registration_proposal" in src
        assert "registration proposal emitted" in src

    def test_audit_proposal_written(self, tmp_path):
        """create_registration_proposal writes to audit dict in-memory."""
        from app.services.wfirma_product_registration import create_registration_proposal
        audit = {"batch_id": "B_WRITE", "action_proposals": []}
        create_registration_proposal(audit, "B_WRITE", ["PC-A", "PC-B"])
        assert len(audit["action_proposals"]) == 1
        assert audit["action_proposals"][0]["context"]["unsynced_count"] == 2
