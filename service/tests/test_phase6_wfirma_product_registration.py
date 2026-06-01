"""
test_phase6_wfirma_product_registration.py — Phase 6 evidence tests.

Verifies:
1. create_registration_proposal creates proposal for unsynced codes
2. Flag-off path blocks the write (dispatch returns ok=False with flag message)
3. Deduplication: one pending proposal per batch
4. Empty unsynced list → no proposal
5. Module never imports wfirma_client directly
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


class TestProposalCreation:
    def test_creates_proposal_for_unsynced_codes(self):
        from app.services.wfirma_product_registration import (
            create_registration_proposal,
            PROP_PRODUCT_NOT_SYNCED, REGISTRATION_CHANNEL,
        )
        audit: Dict[str, Any] = {}
        proposal = create_registration_proposal(
            audit, "BATCH1", ["EJL/26-27/100-1", "EJL/26-27/100-2"]
        )
        assert proposal is not None
        assert proposal["type"]    == PROP_PRODUCT_NOT_SYNCED
        assert proposal["channel"] == REGISTRATION_CHANNEL
        assert proposal["status"]  == "pending_review"
        assert len(audit["action_proposals"]) == 1
        ctx = proposal.get("context", {})
        assert "EJL/26-27/100-1" in ctx.get("unsynced_product_codes", [])

    def test_no_proposal_for_empty_unsynced_list(self):
        from app.services.wfirma_product_registration import create_registration_proposal
        audit: Dict[str, Any] = {}
        result = create_registration_proposal(audit, "BATCH2", [])
        assert result is None
        assert "action_proposals" not in audit

    def test_deduplication_one_proposal_per_batch(self):
        from app.services.wfirma_product_registration import create_registration_proposal
        audit: Dict[str, Any] = {}
        create_registration_proposal(audit, "BATCH3", ["PC-1"])
        create_registration_proposal(audit, "BATCH3", ["PC-1", "PC-2"])
        assert len(audit["action_proposals"]) == 1

    def test_proposal_context_has_flag_name(self):
        from app.services.wfirma_product_registration import create_registration_proposal
        audit: Dict[str, Any] = {}
        proposal = create_registration_proposal(audit, "BATCH4", ["PC-X"])
        assert proposal is not None
        assert "WFIRMA_CREATE_PRODUCT_ALLOWED" in str(proposal.get("context", {}))


class TestFlagOffBlocksWrite:
    def test_dispatch_blocked_when_flag_off(self, monkeypatch):
        from app.services.wfirma_product_registration import dispatch_registration
        from app.core.config import settings
        monkeypatch.setattr(settings, "wfirma_create_product_allowed", False)
        result = dispatch_registration("BATCH5", {}, "operator")
        assert result["ok"] is False
        assert "WFIRMA_CREATE_PRODUCT_ALLOWED" in result["error"]
        assert "flag must be enabled" in result["error"]

    def test_dispatch_guard_is_present_in_source(self):
        """The dispatch function must contain the flag guard — source-grep proof."""
        import pathlib
        src = (pathlib.Path(__file__).parent.parent / "app" / "services"
               / "wfirma_product_registration.py").read_text(encoding="utf-8")
        assert "wfirma_create_product_allowed" in src, \
            "dispatch_registration must check the write flag before writing to wFirma"
        assert "not settings.wfirma_create_product_allowed" in src, \
            "guard must explicitly check flag is False to block the write"


class TestNoBoundaryViolations:
    def test_module_does_not_import_wfirma_client_directly(self):
        module_path = (
            Path(__file__).parent.parent / "app" / "services"
            / "wfirma_product_registration.py"
        )
        source = module_path.read_text(encoding="utf-8")
        # The module must not call wfirma_client directly — only via /products/resolve
        # (the dispatch function calls routes_wfirma._resolve_products_for_batch)
        assert "from ..services.wfirma_client" not in source
        assert "wfirma_client.create_product" not in source
        assert "smtplib" not in source
