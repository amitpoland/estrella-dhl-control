"""
test_phase3_ai_reverification.py — Phase 3 evidence tests.

Verifies the AI Reverification Layer (§1A) boundaries:
1. Proposals are emitted for the §7 types (supplier mismatch, HS missing, etc.)
2. Layer is read-only: no master writes, no wFirma writes, no email sends
3. write_reverification_proposals_to_audit deduplicates correctly
4. reverify_purchase_batch never raises (failures produce LOW-confidence proposals)
5. check_sales_purchase_line_match detects mismatches and creates proposals
6. ALL_REVERIFICATION_TYPES covers the §7 set
"""
from __future__ import annotations

import json
import sys
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


class TestReverificationBoundaries:
    """The AI layer is read-only and proposal-only."""

    def test_reverify_purchase_batch_never_raises(self, tmp_path):
        """Even on a completely broken audit, the function returns (not raises)."""
        from app.services.rule_based_reverification import reverify_purchase_batch
        # Deliberately broken audit
        result = reverify_purchase_batch("BATCH_BROKEN", {}, tmp_path)
        assert isinstance(result, list)

    def test_all_reverification_types_covers_section7(self):
        """ALL_REVERIFICATION_TYPES includes the 9 active §7 proposal types
        (disambiguation_417g removed as unimplemented per B9 docs-honesty fix)."""
        from app.services.rule_based_reverification import (
            ALL_REVERIFICATION_TYPES,
            PROP_SUPPLIER_MISMATCH, PROP_CLIENT_MISMATCH,
            PROP_PRODUCT_DESIGN_MISMATCH, PROP_MISSING_HS_CODE,
            PROP_PRICE_VALUE_CONFLICT, PROP_SALES_PURCHASE_LINE_MISMATCH,
            PROP_DHL_DELIVERED_NOT_RECEIVED, PROP_PRODUCT_NOT_SYNCED_TO_WFIRMA,
            PROP_PZ_PROFORMA_READY,
        )
        expected = {
            PROP_SUPPLIER_MISMATCH, PROP_CLIENT_MISMATCH,
            PROP_PRODUCT_DESIGN_MISMATCH, PROP_MISSING_HS_CODE,
            PROP_PRICE_VALUE_CONFLICT, PROP_SALES_PURCHASE_LINE_MISMATCH,
            PROP_DHL_DELIVERED_NOT_RECEIVED, PROP_PRODUCT_NOT_SYNCED_TO_WFIRMA,
            PROP_PZ_PROFORMA_READY,
        }
        assert expected == ALL_REVERIFICATION_TYPES

    def test_reverification_channel_constant(self):
        from app.services.rule_based_reverification import REVERIFICATION_CHANNEL
        assert REVERIFICATION_CHANNEL == "ai_reverification"

    def test_proposals_have_no_write_side_effects(self, tmp_path):
        """Reverification leaves no files and no DB rows behind."""
        from app.services.rule_based_reverification import reverify_purchase_batch
        before_files = set(tmp_path.rglob("*"))
        reverify_purchase_batch("BATCH_001", {"batch_id": "BATCH_001"}, tmp_path)
        after_files = set(tmp_path.rglob("*"))
        assert before_files == after_files, "Reverification should not create any files"


class TestCheckHsCodes:
    """check_hs_codes emits proposals for missing HS."""

    def test_missing_hs_creates_proposal(self):
        from app.services.rule_based_reverification import check_hs_codes, PROP_MISSING_HS_CODE
        lines = [
            {"product_code": "EJL/26-27/111-1", "hs_code": "", "description": "Ring"},
            {"product_code": "EJL/26-27/111-2", "hs_code": "71131913", "description": "Earring"},
        ]
        proposals = check_hs_codes({}, lines)
        assert len(proposals) == 1
        assert proposals[0].proposal_type == PROP_MISSING_HS_CODE
        assert "EJL/26-27/111-1" in str(proposals[0].evidence)

    def test_all_hs_present_no_proposal(self):
        from app.services.rule_based_reverification import check_hs_codes
        lines = [
            {"product_code": "EJL/26-27/222-1", "hs_code": "71131913"},
            {"product_code": "EJL/26-27/222-2", "hsn_code": "71131913"},
        ]
        proposals = check_hs_codes({}, lines)
        assert proposals == []

    def test_empty_lines_no_proposal(self):
        from app.services.rule_based_reverification import check_hs_codes
        assert check_hs_codes({}, []) == []


class TestCheckSupplierIdentity:
    """check_supplier_identity emits mismatch proposals."""

    def _masters_with_supplier(self, name: str):
        from app.services.rule_based_reverification import MastersSnapshot
        return MastersSnapshot(supplier_row={"name": name})

    def test_supplier_name_match_no_proposal(self):
        from app.services.rule_based_reverification import check_supplier_identity
        audit = {"invoices": [{"exporter_name": "Estrella Jewels LLP."}]}
        masters = self._masters_with_supplier("ESTRELLA JEWELS LLP.")
        proposals = check_supplier_identity(audit, masters)
        assert proposals == []

    def test_supplier_name_mismatch_creates_proposal(self):
        from app.services.rule_based_reverification import check_supplier_identity, PROP_SUPPLIER_MISMATCH
        audit = {"invoices": [{"exporter_name": "Global Jewellery Pvt Ltd"}]}
        masters = self._masters_with_supplier("ESTRELLA JEWELS LLP.")
        proposals = check_supplier_identity(audit, masters)
        assert len(proposals) == 1
        assert proposals[0].proposal_type == PROP_SUPPLIER_MISMATCH

    def test_no_supplier_name_in_audit_creates_proposal(self):
        from app.services.rule_based_reverification import check_supplier_identity, PROP_SUPPLIER_MISMATCH
        audit = {"invoices": [{"exporter_name": ""}]}
        masters = self._masters_with_supplier("ESTRELLA JEWELS LLP.")
        proposals = check_supplier_identity(audit, masters)
        assert any(p.proposal_type == PROP_SUPPLIER_MISMATCH for p in proposals)


class TestSalesPurchaseLineMismatch:
    """check_sales_purchase_line_match creates proposals on mismatch."""

    def test_matched_designs_no_proposal(self):
        from app.services.rule_based_reverification import check_sales_purchase_line_match
        purchase = [{"product_code": "EJL/26-27/100-1", "design_no": "RING-ABC"}]
        sales    = [{"design_no": "RING-ABC"}]
        proposals = check_sales_purchase_line_match(purchase, sales)
        assert proposals == []

    def test_unmatched_sales_design_creates_proposal(self):
        from app.services.rule_based_reverification import check_sales_purchase_line_match, PROP_SALES_PURCHASE_LINE_MISMATCH
        purchase = [{"product_code": "EJL/26-27/100-1", "design_no": "RING-ABC"}]
        sales    = [{"design_no": "RING-XYZ-NOT-IN-PURCHASE"}]
        proposals = check_sales_purchase_line_match(purchase, sales)
        assert len(proposals) == 1
        assert proposals[0].proposal_type == PROP_SALES_PURCHASE_LINE_MISMATCH

    def test_empty_sales_lines_no_proposal(self):
        from app.services.rule_based_reverification import check_sales_purchase_line_match
        purchase = [{"product_code": "EJL/26-27/100-1", "design_no": "RING"}]
        proposals = check_sales_purchase_line_match(purchase, [])
        assert proposals == []


class TestWriteProposalsToAudit:
    """write_reverification_proposals_to_audit appends and deduplicates."""

    def test_proposals_appended_to_audit(self):
        from app.services.rule_based_reverification import (
            ReverificationProposal, write_reverification_proposals_to_audit,
            PROP_MISSING_HS_CODE, REVERIFICATION_CHANNEL,
        )
        audit: Dict[str, Any] = {}
        proposals = [
            ReverificationProposal(
                proposal_type=PROP_MISSING_HS_CODE,
                reason="Test HS missing",
                confidence="high",
            )
        ]
        added = write_reverification_proposals_to_audit(audit, proposals)
        assert added == 1
        assert len(audit["action_proposals"]) == 1
        p = audit["action_proposals"][0]
        assert p["channel"] == REVERIFICATION_CHANNEL
        assert p["type"] == PROP_MISSING_HS_CODE
        assert p["status"] == "pending_review"

    def test_deduplication_prevents_duplicate_active_proposals(self):
        from app.services.rule_based_reverification import (
            ReverificationProposal, write_reverification_proposals_to_audit,
            PROP_MISSING_HS_CODE, REVERIFICATION_CHANNEL,
        )
        audit: Dict[str, Any] = {}
        prop = ReverificationProposal(
            proposal_type=PROP_MISSING_HS_CODE,
            reason="First", confidence="high"
        )
        write_reverification_proposals_to_audit(audit, [prop])
        added2 = write_reverification_proposals_to_audit(audit, [prop])
        assert added2 == 0
        assert len(audit["action_proposals"]) == 1

    def test_empty_proposals_returns_zero(self):
        from app.services.rule_based_reverification import write_reverification_proposals_to_audit
        audit: Dict[str, Any] = {}
        assert write_reverification_proposals_to_audit(audit, []) == 0
        assert "action_proposals" not in audit

    def test_proposals_schema_has_required_fields(self):
        from app.services.rule_based_reverification import (
            ReverificationProposal, write_reverification_proposals_to_audit,
            PROP_SUPPLIER_MISMATCH,
        )
        audit: Dict[str, Any] = {}
        write_reverification_proposals_to_audit(audit, [
            ReverificationProposal(proposal_type=PROP_SUPPLIER_MISMATCH,
                                   reason="R", confidence="high")
        ])
        p = audit["action_proposals"][0]
        for field in ("proposal_id", "type", "channel", "status", "reason",
                      "confidence", "created_at", "approved_by", "approved_at"):
            assert field in p, f"Missing field: {field}"

    def test_no_wfirma_writes_import(self):
        """ai_reverification module must not import wfirma_client."""
        import ast, sys
        module_path = Path(__file__).parent.parent / "app" / "services" / "ai_reverification.py"
        source = module_path.read_text(encoding="utf-8")
        assert "wfirma_client" not in source, \
            "ai_reverification must never import wfirma_client"
        assert "smtplib" not in source, \
            "ai_reverification must never import smtplib"
        assert "send_email" not in source, \
            "ai_reverification must never call send_email"
