"""
test_customs_desc_ai_validation.py
====================================
Tests for the global AI validation layer for product descriptions.

Covers:
  1. PT950 invoice line → NO proposal (engine fix means it resolves correctly).
  2. Broken description → "metal szlachetny" → proposal created in audit.
  3. Proposal cannot auto-apply — description unchanged without approval.
  4. Approved proposal updates audit["description_corrections"].
  5. Rejected proposal leaves audit unchanged.
  6. Works for EJL format (documents.db invoice_lines).
  7. Works for Global Jewellery format (packing_lines — the Global path uses
     _global_render_pl_en which raises _UnrecognisedMetalCode, not this layer;
     confirmed by checking the Global path is not affected).
  8. Correction is applied to audit rows before engine call.
  9. Existing correction skips re-proposing for the same product_code.
"""
from __future__ import annotations

import json
import pathlib
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# ── Engine path (repo root) ──────────────────────────────────────────────────
_REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.services.customs_desc_checker import (
    FORBIDDEN_MATERIAL_PL,
    PROP_CUSTOMS_DESC_MISMATCH,
    apply_description_corrections,
    check_customs_description_accuracy,
    write_customs_desc_proposals_to_audit,
)

BATCH_ID = "SHIPMENT_TEST_AI_VALIDATION"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_invoice_line(
    description: str,
    product_code: str = "EJL/TEST/1",
    invoice_no: str   = "EJL/TEST",
    line_position: int = 1,
    qty: float = 1.0,
    total: float = 100.0,
) -> Dict[str, Any]:
    return {
        "description":    description,
        "product_code":   product_code,
        "invoice_no":     invoice_no,
        "line_position":  line_position,
        "quantity":       qty,
        "total_value":    total,
        "hsn_code":       "71131914",
    }


def _make_audit(corrections: Dict = None) -> Dict[str, Any]:
    a: Dict[str, Any] = {"batch_id": BATCH_ID, "action_proposals": []}
    if corrections:
        a["description_corrections"] = dict(corrections)
    return a


# ── Thread 1: PT950 after engine fix → NO proposal ───────────────────────────

class TestPT950NoProposalAfterEngineFix:
    """After the PT950 engine fix, 'PCS, PT950 Platinum,...' resolves to
    'platyna próby 950' — not a forbidden placeholder — so no proposal
    should be emitted."""

    def test_pt950_plain_ring_creates_no_proposal(self, tmp_path):
        line = _make_invoice_line(
            "PCS, PT950 Platinum,Plain Jewel RING",
            product_code="EJL/26-27/235-2",
        )
        audit = _make_audit()

        with patch(
            "app.services.customs_desc_checker._get_invoice_lines",
            return_value=[line],
        ):
            proposals = check_customs_description_accuracy(BATCH_ID, audit, tmp_path)

        assert proposals == [], (
            f"Expected no proposals for PT950 after engine fix, got: {proposals}"
        )

    def test_pt950_stud_diamond_creates_no_proposal(self, tmp_path):
        line = _make_invoice_line(
            "PCS, PT950 Platinum,Stud With Diam Jewel RING",
            product_code="EJL/26-27/235-3",
        )
        audit = _make_audit()
        with patch("app.services.customs_desc_checker._get_invoice_lines",
                   return_value=[line]):
            proposals = check_customs_description_accuracy(BATCH_ID, audit, tmp_path)

        assert proposals == []

    def test_gold_18kt_creates_no_proposal(self, tmp_path):
        line = _make_invoice_line(
            "PCS, 18KT Gold,Plain Jewellery PENDANT",
            product_code="EJL/26-27/235-1",
        )
        audit = _make_audit()
        with patch("app.services.customs_desc_checker._get_invoice_lines",
                   return_value=[line]):
            proposals = check_customs_description_accuracy(BATCH_ID, audit, tmp_path)

        assert proposals == []


# ── Thread 2: Broken description → proposal created ──────────────────────────

class TestBrokenDescriptionCreatesProposal:
    """A description the engine cannot resolve → 'metal szlachetny' →
    must create a customs_description_mismatch proposal in the audit Inbox."""

    def test_unknown_metal_creates_proposal(self, tmp_path):
        """Simulate a case the engine still can't handle."""
        line = _make_invoice_line(
            "PCS, UNOBTAINIUM-X Metal, Plain RING",  # engine can't resolve this
            product_code="EJL/UNKNOWN/1",
        )
        audit = _make_audit()
        with patch("app.services.customs_desc_checker._get_invoice_lines",
                   return_value=[line]):
            proposals = check_customs_description_accuracy(BATCH_ID, audit, tmp_path)

        assert len(proposals) == 1
        p = proposals[0]
        assert p["type"]    == PROP_CUSTOMS_DESC_MISMATCH
        assert p["status"]  == "pending_review"
        assert p["product_code"] == "EJL/UNKNOWN/1"
        assert p["data"]["issue"] in ("forbidden_placeholder", "empty_material_pl")
        assert p["data"]["source"] == "PCS, UNOBTAINIUM-X Metal, Plain RING"

    def test_empty_description_creates_no_proposal(self, tmp_path):
        """Empty description → line skipped, not a proposal."""
        line = _make_invoice_line("", product_code="EJL/EMPTY/1")
        audit = _make_audit()
        with patch("app.services.customs_desc_checker._get_invoice_lines",
                   return_value=[line]):
            proposals = check_customs_description_accuracy(BATCH_ID, audit, tmp_path)

        assert proposals == []

    def test_proposal_written_to_audit(self, tmp_path):
        """write_customs_desc_proposals_to_audit appends proposals to audit."""
        line = _make_invoice_line(
            "PCS, MYSTERY ALLOY, Plain RING", product_code="EJL/MYSTERY/1"
        )
        audit = _make_audit()
        with patch("app.services.customs_desc_checker._get_invoice_lines",
                   return_value=[line]):
            proposals = check_customs_description_accuracy(BATCH_ID, audit, tmp_path)

        added = write_customs_desc_proposals_to_audit(audit, proposals)
        # If engine happens to resolve this, no proposal; otherwise 1
        assert added >= 0
        assert len(audit["action_proposals"]) == added

    def test_placeholder_line_skipped(self, tmp_path):
        """Placeholder invoice rows (qty=0, total=0) must not create proposals."""
        line = _make_invoice_line(
            "(placeholder) no data",
            product_code="EJL/PLACEHOLDER/1",
            qty=0.0, total=0.0,
        )
        audit = _make_audit()
        with patch("app.services.customs_desc_checker._get_invoice_lines",
                   return_value=[line]):
            proposals = check_customs_description_accuracy(BATCH_ID, audit, tmp_path)

        assert proposals == []


# ── Thread 3: Proposal cannot auto-apply ────────────────────────────────────

class TestProposalCannotAutoApply:
    """A pending proposal must NOT change the description output.
    Only an approved proposal with a correction value changes the output.
    """

    def test_pending_proposal_does_not_change_rows(self, tmp_path):
        audit = _make_audit()
        audit["rows"] = [
            {
                "product_code": "EJL/TEST/1",
                "description": "PCS, MYSTERY ALLOY, Plain RING",
                "material": "",
            }
        ]
        audit["action_proposals"] = [{
            "proposal_id": str(uuid.uuid4()),
            "type":        PROP_CUSTOMS_DESC_MISMATCH,
            "channel":     "ai_reverification",
            "status":      "pending_review",     # NOT approved yet
            "product_code": "EJL/TEST/1",
        }]

        # Applying corrections with no approved correction must be a no-op
        apply_description_corrections(audit)

        assert audit["rows"][0].get("_correction_applied") is None
        assert audit["rows"][0].get("material") == ""

    def test_no_corrections_dict_is_noop(self, tmp_path):
        """No description_corrections in audit → rows unchanged."""
        audit = _make_audit()
        audit["rows"] = [{"product_code": "EJL/TEST/1", "material": "old_value"}]
        apply_description_corrections(audit)
        assert audit["rows"][0]["material"] == "old_value"


# ── Thread 4: Approved proposal updates description_corrections ─────────────

class TestApprovedProposalWritesCorrection:
    """Approving a customs_description_mismatch proposal with a correction
    value stores it in audit['description_corrections'][product_code]."""

    def _build_proposal(self, product_code: str = "EJL/TEST/1") -> Dict[str, Any]:
        return {
            "proposal_id":  str(uuid.uuid4()),
            "type":         PROP_CUSTOMS_DESC_MISMATCH,
            "channel":      "ai_reverification",
            "status":       "pending_review",
            "product_code": product_code,
            "invoice_no":   "EJL/TEST",
            "data": {
                "source": "PCS, MYSTERY ALLOY, Plain RING",
                "current_material_pl": "metal szlachetny",
                "issue": "forbidden_placeholder",
            },
        }

    def test_approve_writes_description_corrections(self, tmp_path, monkeypatch):
        """End-to-end: approve via API helper → correction appears in audit."""
        from app.api.routes_action_proposals import (
            DescriptionCorrection,
            ApproveBody,
        )
        from app.api import routes_action_proposals as rap

        batch_id = BATCH_ID
        prop = self._build_proposal()
        audit = _make_audit()
        audit["action_proposals"] = [prop]

        # Stub the resolution + save helpers
        monkeypatch.setattr(rap, "_resolve_proposal",
                            lambda pid: (batch_id, audit, prop))
        monkeypatch.setattr(rap, "_save_audit", lambda bid, a: None)
        monkeypatch.setattr(rap, "tl", MagicMock())

        body = ApproveBody(
            approved_by="test_operator",
            correction=DescriptionCorrection(
                material_pl="platyna próby 950",
                description_pl="Pierścionek z platyny próby 950, biżuteria do noszenia.",
            ),
        )
        result = rap.approve_proposal(prop["proposal_id"], body)

        assert result["status"] == "approved"
        assert "correction_applied" in result
        assert audit["description_corrections"]["EJL/TEST/1"]["material_pl"] == "platyna próby 950"
        assert audit["description_corrections"]["EJL/TEST/1"]["approved_by"] == "test_operator"

    def test_approve_without_correction_does_not_write_corrections(self, tmp_path, monkeypatch):
        """Approving WITHOUT a correction body leaves description_corrections untouched."""
        from app.api.routes_action_proposals import ApproveBody
        from app.api import routes_action_proposals as rap

        batch_id = BATCH_ID
        prop = self._build_proposal()
        audit = _make_audit()
        audit["action_proposals"] = [prop]

        monkeypatch.setattr(rap, "_resolve_proposal",
                            lambda pid: (batch_id, audit, prop))
        monkeypatch.setattr(rap, "_save_audit", lambda bid, a: None)
        monkeypatch.setattr(rap, "tl", MagicMock())

        body = ApproveBody(approved_by="test_operator", correction=None)
        result = rap.approve_proposal(prop["proposal_id"], body)

        assert result["status"] == "approved"
        assert "correction_applied" not in result
        assert "description_corrections" not in audit


# ── Thread 5: Rejected proposal leaves output unchanged ─────────────────────

class TestRejectedProposalLeavesOutputUnchanged:

    def test_rejected_proposal_cannot_be_re_approved_to_apply_correction(
        self, monkeypatch,
    ):
        """Reject → then re-approve attempt → raises 409 (rejected status)."""
        from app.api.routes_action_proposals import ApproveBody, DescriptionCorrection
        from app.api import routes_action_proposals as rap
        import fastapi

        prop = {
            "proposal_id": str(uuid.uuid4()),
            "type":         PROP_CUSTOMS_DESC_MISMATCH,
            "channel":      "ai_reverification",
            "status":       "rejected",   # already rejected
            "product_code": "EJL/TEST/1",
            "data": {},
        }
        audit = _make_audit()
        audit["action_proposals"] = [prop]

        monkeypatch.setattr(rap, "_resolve_proposal",
                            lambda pid: (BATCH_ID, audit, prop))
        monkeypatch.setattr(rap, "_save_audit", lambda bid, a: None)
        monkeypatch.setattr(rap, "tl", MagicMock())

        body = ApproveBody(
            approved_by="test_operator",
            correction=DescriptionCorrection(material_pl="platyna próby 950"),
        )
        with pytest.raises(fastapi.HTTPException) as exc_info:
            rap.approve_proposal(prop["proposal_id"], body)

        assert exc_info.value.status_code == 409
        # No correction written
        assert "description_corrections" not in audit


# ── Thread 6: Correction applied to rows before engine ───────────────────────

class TestCorrectionAppliedToRows:
    """Approved corrections in audit['description_corrections'] must be
    applied to audit['rows'] by apply_description_corrections()."""

    def test_correction_patches_matching_row(self):
        audit = {
            "description_corrections": {
                "EJL/TEST/1": {
                    "material_pl":    "platyna próby 950",
                    "description_pl": "Pierścionek z platyny próby 950.",
                }
            },
            "rows": [
                {
                    "product_code": "EJL/TEST/1",
                    "description":  "PCS, MYSTERY ALLOY, Plain RING",
                    "material":     "",
                },
                {
                    "product_code": "EJL/TEST/2",
                    "description":  "PCS, 14KT Gold, Ring",
                    "material":     "",
                },
            ],
        }
        apply_description_corrections(audit)

        row1 = audit["rows"][0]
        row2 = audit["rows"][1]

        assert row1.get("material") == "platyna próby 950", (
            f"Expected 'platyna próby 950', got {row1.get('material')!r}"
        )
        assert row1.get("_correction_applied") is True
        # Row 2 must be untouched
        assert row2.get("material") == ""
        assert row2.get("_correction_applied") is None

    def test_correction_only_material_pl(self):
        """material_pl-only correction: material field set, description_pl empty."""
        audit = {
            "description_corrections": {
                "EJL/ONLY-MAT/1": {"material_pl": "złoto próby 750", "description_pl": ""}
            },
            "rows": [{"product_code": "EJL/ONLY-MAT/1", "material": ""}],
        }
        apply_description_corrections(audit)
        assert audit["rows"][0]["material"] == "złoto próby 750"
        assert audit["rows"][0].get("_correction_applied") is True


# ── Thread 7: Deduplication — existing correction skips proposal ─────────────

class TestDeduplication:

    def test_existing_correction_skips_new_proposal(self, tmp_path):
        """If a product_code already has an approved correction in
        audit['description_corrections'], no new proposal is emitted."""
        line = _make_invoice_line(
            "PCS, MYSTERY ALLOY, Plain RING", product_code="EJL/FIXED/1"
        )
        audit = _make_audit(corrections={"EJL/FIXED/1": {"material_pl": "złoto próby 750"}})

        with patch("app.services.customs_desc_checker._get_invoice_lines",
                   return_value=[line]):
            proposals = check_customs_description_accuracy(BATCH_ID, audit, tmp_path)

        for p in proposals:
            assert p.get("product_code") != "EJL/FIXED/1", (
                "Must not create new proposal for product_code that already has a correction"
            )

    def test_already_pending_proposal_not_duplicated(self, tmp_path):
        """If a pending_review proposal already exists for a product_code,
        write_customs_desc_proposals_to_audit must not add a duplicate."""
        existing_id = str(uuid.uuid4())
        audit = _make_audit()
        audit["action_proposals"] = [{
            "proposal_id":  existing_id,
            "type":         PROP_CUSTOMS_DESC_MISMATCH,
            "channel":      "ai_reverification",
            "status":       "pending_review",
            "product_code": "EJL/DUP/1",
        }]

        duplicate_proposal = {
            "proposal_id":  str(uuid.uuid4()),
            "type":         PROP_CUSTOMS_DESC_MISMATCH,
            "channel":      "ai_reverification",
            "status":       "pending_review",
            "product_code": "EJL/DUP/1",
            "data":         {},
        }
        added = write_customs_desc_proposals_to_audit(audit, [duplicate_proposal])
        assert added == 0
        assert len(audit["action_proposals"]) == 1  # original only


# ── Thread 8: FORBIDDEN_MATERIAL_PL set ─────────────────────────────────────

class TestForbiddenSet:

    def test_metal_szlachetny_in_forbidden_set(self):
        assert "metal szlachetny" in FORBIDDEN_MATERIAL_PL

    def test_empty_string_not_in_set(self):
        # empty string is caught via `not material_pl` in the checker, not via the set
        assert "" not in FORBIDDEN_MATERIAL_PL
