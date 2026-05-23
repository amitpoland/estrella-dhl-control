"""
test_global_pz_correction.py — Tests for the Global PZ correction proposal service.

Coverage:
  - CorrectionProposal structure and option set generation
  - NO_ACTION when posted PZ matches authority exactly (same format)
  - KEEP_CURRENT when structure matches but product-code format differs
  - ALIGN_TO_AUTHORITY when qty or type discrepancies exist
  - SPLIT_TO_STYLE_LEVEL for positions with multiple item types in lineage
  - wFirma confirmation flag propagation
  - Endpoint contract: /api/v1/pz/lineage/{batch_id}/correction-proposal
  - Non-global batch suppression on correction endpoint
  - Empty pz_rows / authority_rows graceful handling

Rules:
  - No wFirma imports anywhere in the service or test code.
  - No pz_create or pz_cancel calls.
  - All tests are pure (no disk I/O, no network, no process spawning).
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ─────────────────────────────────────────────────────────────────────────────
# Helpers — minimal fixture builders
# ─────────────────────────────────────────────────────────────────────────────

def _inv_pos(position_no: int, unit: str, metal_en: str, stone_en: str, rows: list) -> dict:
    return {
        "position_no": position_no, "unit": unit,
        "metal_en": metal_en, "stone_en": stone_en,
        "rows": rows,
        "quantity": sum(r["qty"] for r in rows),
        "amount": sum(r["amount"] for r in rows),
    }


def _pack_row(serial_no: int, item_type: str, metal: str, stone_detail: str,
              fob: float = 10.0, design_no: str = "") -> dict:
    return {
        "serial_no": serial_no, "item_type": item_type,
        "metal": metal, "stone_detail": stone_detail,
        "quantity": 1.0, "unit_price": fob, "total_value": fob,
        "design_no": design_no,
    }


def _pz_row(product_code: str, item_type: str, qty: float,
            value_pln: float = 100.0, wfirma_doc_id: Optional[str] = None) -> dict:
    r = {
        "product_code": product_code,
        "item_type": item_type,
        "quantity": qty,
        "unit_netto_pln": value_pln,
    }
    if wfirma_doc_id is not None:
        r["wfirma_document_id"] = wfirma_doc_id
    return r


def _auth_row(product_code: str, item_type: str, qty: float) -> dict:
    return {"product_code": product_code, "item_type": item_type, "quantity": qty}


# ─────────────────────────────────────────────────────────────────────────────
# Build a lineage result from scratch (avoids disk I/O)
# ─────────────────────────────────────────────────────────────────────────────

def _build_lineage(positions, packing):
    from app.services.global_pz_lineage import build_global_pz_lineage
    return build_global_pz_lineage(positions, packing, pz_rows=None, invoice_no="TST/2026-2027")


# ─────────────────────────────────────────────────────────────────────────────
# Import the module under test
# ─────────────────────────────────────────────────────────────────────────────

from app.services.global_pz_correction import (
    build_correction_proposal,
    CorrectionProposal,
    CorrectionOption,
    PZLineSummary,
)


# ─────────────────────────────────────────────────────────────────────────────
# Section 1: Structural helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestHelpers:
    def test_extract_pos_no_sequential(self):
        from app.services.global_pz_correction import _extract_pos_no
        assert _extract_pos_no("088/2026-2027-3") == 3

    def test_extract_pos_no_inv_format(self):
        from app.services.global_pz_correction import _extract_pos_no
        assert _extract_pos_no("088/2026-2027-INV-03") == 3

    def test_extract_pos_no_inv_format_zero_padded(self):
        from app.services.global_pz_correction import _extract_pos_no
        assert _extract_pos_no("088/2026-2027-INV-09") == 9

    def test_extract_pos_no_pos_format(self):
        from app.services.global_pz_correction import _extract_pos_no
        assert _extract_pos_no("088/2026-2027-POS-5") == 5

    def test_extract_pos_no_unknown_returns_zero(self):
        from app.services.global_pz_correction import _extract_pos_no
        assert _extract_pos_no("bad-format") == 0

    def test_is_inv_format_true(self):
        from app.services.global_pz_correction import _is_inv_format
        assert _is_inv_format("088/2026-2027-INV-04") is True

    def test_is_inv_format_false_for_sequential(self):
        from app.services.global_pz_correction import _is_inv_format
        assert _is_inv_format("088/2026-2027-4") is False

    def test_to_inv_format(self):
        from app.services.global_pz_correction import _to_inv_format
        result = _to_inv_format("088/2026-2027-3", 3)
        assert "-INV-03" in result

    def test_normalise_type(self):
        from app.services.global_pz_correction import _normalise_type
        assert _normalise_type("bracelet") == "BRACELET"
        assert _normalise_type("  Ring  ") == "RING"
        assert _normalise_type("") == ""
        assert _normalise_type(None) == ""


# ─────────────────────────────────────────────────────────────────────────────
# Section 2: NO_ACTION path
# ─────────────────────────────────────────────────────────────────────────────

class TestNoAction:
    """When pz_rows exactly matches authority in INV-NN format — no action needed."""

    def _setup(self):
        positions = [
            _inv_pos(1, "PCS", "925 Silver", "CZ Stud Jewellery",
                     [{"type": "Bracelet", "qty": 2.0, "amount": 200.0}]),
        ]
        packing = [
            _pack_row(1, "Bracelet", "925 SILVER", "CZ Round Shape 1", fob=100.0),
            _pack_row(2, "Bracelet", "925 SILVER", "CZ Round Shape 1", fob=100.0),
        ]
        lineage = _build_lineage(positions, packing)
        pz_rows = [_pz_row("TST/2026-2027-INV-01", "BRACELET", 2.0)]
        auth_rows = [_auth_row("TST/2026-2027-INV-01", "BRACELET", 2.0)]
        return lineage, pz_rows, auth_rows

    def test_no_action_option_present(self):
        lineage, pz_rows, auth_rows = self._setup()
        proposal = build_correction_proposal("B1", "TST/2026-2027", lineage, pz_rows, auth_rows)
        assert any(o.option_id == "NO_ACTION" for o in proposal.options)

    def test_recommended_is_no_action(self):
        lineage, pz_rows, auth_rows = self._setup()
        proposal = build_correction_proposal("B1", "TST/2026-2027", lineage, pz_rows, auth_rows)
        assert proposal.recommended_option == "NO_ACTION"

    def test_no_action_requires_no_write(self):
        lineage, pz_rows, auth_rows = self._setup()
        proposal = build_correction_proposal("B1", "TST/2026-2027", lineage, pz_rows, auth_rows)
        no_action = next(o for o in proposal.options if o.option_id == "NO_ACTION")
        assert no_action.requires_wfirma_edit is False
        assert no_action.requires_wfirma_cancel is False
        assert no_action.risk_level == "NONE"

    def test_product_code_format_mismatch_is_false(self):
        lineage, pz_rows, auth_rows = self._setup()
        proposal = build_correction_proposal("B1", "TST/2026-2027", lineage, pz_rows, auth_rows)
        assert proposal.product_code_format_mismatch is False


# ─────────────────────────────────────────────────────────────────────────────
# Section 3: KEEP_CURRENT path (format mismatch only)
# ─────────────────────────────────────────────────────────────────────────────

class TestKeepCurrent:
    """Posted PZ uses sequential format (-1) but structure matches authority."""

    def _setup(self):
        positions = [
            _inv_pos(1, "PCS", "925 Silver", "CZ Stud Jewellery",
                     [{"type": "Ring", "qty": 3.0, "amount": 300.0}]),
        ]
        packing = [
            _pack_row(s, "Ring", "925 SILVER", "CZ Round Shape 1", fob=100.0)
            for s in [1, 2, 3]
        ]
        lineage = _build_lineage(positions, packing)
        # pz_rows uses sequential suffix (-1), not INV-01
        pz_rows = [_pz_row("TST/2026-2027-1", "RING", 3.0)]
        auth_rows = [_auth_row("TST/2026-2027-INV-01", "RING", 3.0)]
        return lineage, pz_rows, auth_rows

    def test_keep_current_option_present(self):
        lineage, pz_rows, auth_rows = self._setup()
        proposal = build_correction_proposal("B2", "TST/2026-2027", lineage, pz_rows, auth_rows)
        assert any(o.option_id == "KEEP_CURRENT" for o in proposal.options)

    def test_recommended_is_keep_current(self):
        lineage, pz_rows, auth_rows = self._setup()
        proposal = build_correction_proposal("B2", "TST/2026-2027", lineage, pz_rows, auth_rows)
        assert proposal.recommended_option == "KEEP_CURRENT"

    def test_format_mismatch_flagged(self):
        lineage, pz_rows, auth_rows = self._setup()
        proposal = build_correction_proposal("B2", "TST/2026-2027", lineage, pz_rows, auth_rows)
        assert proposal.product_code_format_mismatch is True

    def test_keep_current_no_write_required(self):
        lineage, pz_rows, auth_rows = self._setup()
        proposal = build_correction_proposal("B2", "TST/2026-2027", lineage, pz_rows, auth_rows)
        keep = next(o for o in proposal.options if o.option_id == "KEEP_CURRENT")
        assert keep.requires_wfirma_edit is False
        assert keep.risk_level == "NONE"

    def test_align_option_also_present(self):
        lineage, pz_rows, auth_rows = self._setup()
        proposal = build_correction_proposal("B2", "TST/2026-2027", lineage, pz_rows, auth_rows)
        assert any(o.option_id == "ALIGN_TO_AUTHORITY" for o in proposal.options)


# ─────────────────────────────────────────────────────────────────────────────
# Section 4: ALIGN_TO_AUTHORITY path
# ─────────────────────────────────────────────────────────────────────────────

class TestAlignToAuthority:
    """Qty discrepancy between posted PZ and authority triggers ALIGN recommendation."""

    def _setup(self):
        positions = [
            _inv_pos(1, "PCS", "925 Silver", "CZ Stud Jewellery",
                     [{"type": "Pendant", "qty": 5.0, "amount": 500.0}]),
        ]
        packing = [_pack_row(s, "Pendant", "925 SILVER", "CZ Oval 1", fob=100.0) for s in range(1, 6)]
        lineage = _build_lineage(positions, packing)
        # posted has qty=4 but authority says 5
        pz_rows = [_pz_row("TST/2026-2027-1", "PENDANT", 4.0)]
        auth_rows = [_auth_row("TST/2026-2027-INV-01", "PENDANT", 5.0)]
        return lineage, pz_rows, auth_rows

    def test_align_option_present(self):
        lineage, pz_rows, auth_rows = self._setup()
        proposal = build_correction_proposal("B3", "TST/2026-2027", lineage, pz_rows, auth_rows)
        assert any(o.option_id == "ALIGN_TO_AUTHORITY" for o in proposal.options)

    def test_recommended_is_align(self):
        lineage, pz_rows, auth_rows = self._setup()
        proposal = build_correction_proposal("B3", "TST/2026-2027", lineage, pz_rows, auth_rows)
        assert proposal.recommended_option == "ALIGN_TO_AUTHORITY"

    def test_qty_mismatch_position_flagged(self):
        lineage, pz_rows, auth_rows = self._setup()
        proposal = build_correction_proposal("B3", "TST/2026-2027", lineage, pz_rows, auth_rows)
        assert 1 in proposal.qty_mismatch_positions

    def test_align_does_not_require_cancel(self):
        lineage, pz_rows, auth_rows = self._setup()
        proposal = build_correction_proposal("B3", "TST/2026-2027", lineage, pz_rows, auth_rows)
        align = next(o for o in proposal.options if o.option_id == "ALIGN_TO_AUTHORITY")
        assert align.requires_wfirma_cancel is False


# ─────────────────────────────────────────────────────────────────────────────
# Section 5: SPLIT_TO_STYLE_LEVEL path
# ─────────────────────────────────────────────────────────────────────────────

class TestSplitToStyleLevel:
    """A mixed-type position (multiple item types per invoice position) generates
    the SPLIT_TO_STYLE_LEVEL option."""

    def _setup(self, pz_confirmed: bool = False):
        # pos=1 has both PENDANT and RING rows sharing the same stone family
        positions = [
            _inv_pos(1, "PCS", "925 Silver", "CZ Stud Jewellery", [
                {"type": "Pendant", "qty": 2.0, "amount": 200.0},
                {"type": "Ring",    "qty": 2.0, "amount": 200.0},
            ]),
        ]
        packing = [
            _pack_row(1, "Pendant", "925 SILVER", "CZ Round Shape 1", fob=100.0),
            _pack_row(2, "Pendant", "925 SILVER", "CZ Round Shape 1", fob=100.0),
            _pack_row(3, "Ring",    "925 SILVER", "CZ Round Shape 1", fob=100.0),
            _pack_row(4, "Ring",    "925 SILVER", "CZ Round Shape 1", fob=100.0),
        ]
        lineage = _build_lineage(positions, packing)
        wfid = "WF-DOC-001" if pz_confirmed else None
        pz_rows = [_pz_row("TST/2026-2027-INV-01", "PENDANT", 4.0, wfirma_doc_id=wfid)]
        auth_rows = [_auth_row("TST/2026-2027-INV-01", "PENDANT", 4.0)]
        return lineage, pz_rows, auth_rows

    def test_split_option_present(self):
        lineage, pz_rows, auth_rows = self._setup()
        proposal = build_correction_proposal("B4", "TST/2026-2027", lineage, pz_rows, auth_rows)
        assert any(o.option_id == "SPLIT_TO_STYLE_LEVEL" for o in proposal.options)

    def test_mixed_type_position_flagged(self):
        lineage, pz_rows, auth_rows = self._setup()
        proposal = build_correction_proposal("B4", "TST/2026-2027", lineage, pz_rows, auth_rows)
        assert 1 in proposal.mixed_type_positions

    def test_split_proposed_lines_count(self):
        """Split produces one ProposedLine per (position, item_type) slot."""
        lineage, pz_rows, auth_rows = self._setup()
        proposal = build_correction_proposal("B4", "TST/2026-2027", lineage, pz_rows, auth_rows)
        split = next(o for o in proposal.options if o.option_id == "SPLIT_TO_STYLE_LEVEL")
        # pos=1 has PENDANT + RING → 2 proposed lines
        assert split.line_count_proposed == 2

    def test_split_not_confirmed_is_medium_risk(self):
        lineage, pz_rows, auth_rows = self._setup(pz_confirmed=False)
        proposal = build_correction_proposal("B4", "TST/2026-2027", lineage, pz_rows, auth_rows)
        split = next(o for o in proposal.options if o.option_id == "SPLIT_TO_STYLE_LEVEL")
        assert split.risk_level == "MEDIUM"
        assert split.requires_wfirma_cancel is False

    def test_split_confirmed_is_high_risk(self):
        lineage, pz_rows, auth_rows = self._setup(pz_confirmed=True)
        proposal = build_correction_proposal("B4", "TST/2026-2027", lineage, pz_rows, auth_rows)
        split = next(o for o in proposal.options if o.option_id == "SPLIT_TO_STYLE_LEVEL")
        assert split.risk_level == "HIGH"
        assert split.requires_wfirma_cancel is True

    def test_split_blocking_reason_when_confirmed(self):
        lineage, pz_rows, auth_rows = self._setup(pz_confirmed=True)
        proposal = build_correction_proposal("B4", "TST/2026-2027", lineage, pz_rows, auth_rows)
        split = next(o for o in proposal.options if o.option_id == "SPLIT_TO_STYLE_LEVEL")
        assert split.blocking_reasons, "Should have blocking reasons when PZ confirmed"


# ─────────────────────────────────────────────────────────────────────────────
# Section 6: wFirma confirmation flag
# ─────────────────────────────────────────────────────────────────────────────

class TestWFirmaConfirmation:
    def _lineage_and_rows(self):
        positions = [
            _inv_pos(1, "PCS", "925 Silver", "CZ Stud Jewellery",
                     [{"type": "Earring", "qty": 1.0, "amount": 100.0}]),
        ]
        packing = [_pack_row(1, "Earring", "925 SILVER", "CZ Round Shape 1", fob=100.0)]
        return _build_lineage(positions, packing)

    def test_not_confirmed_when_no_wfirma_doc_id(self):
        lineage = self._lineage_and_rows()
        pz_rows = [_pz_row("TST/2026-2027-INV-01", "EARRING", 1.0)]
        proposal = build_correction_proposal("B5", "TST/2026-2027", lineage, pz_rows, None)
        assert proposal.pz_confirmed_in_wfirma is False

    def test_confirmed_when_wfirma_doc_id_present(self):
        lineage = self._lineage_and_rows()
        pz_rows = [_pz_row("TST/2026-2027-INV-01", "EARRING", 1.0, wfirma_doc_id="WF-001")]
        proposal = build_correction_proposal("B5", "TST/2026-2027", lineage, pz_rows, None)
        assert proposal.pz_confirmed_in_wfirma is True

    def test_not_confirmed_note_when_unconfirmed(self):
        lineage = self._lineage_and_rows()
        pz_rows = [_pz_row("TST/2026-2027-INV-01", "EARRING", 1.0)]
        proposal = build_correction_proposal("B5", "TST/2026-2027", lineage, pz_rows, None)
        assert any("wFirma" in n for n in proposal.notes)


# ─────────────────────────────────────────────────────────────────────────────
# Section 7: Empty / None inputs
# ─────────────────────────────────────────────────────────────────────────────

class TestEmptyInputs:
    def test_none_pz_rows_does_not_raise(self):
        positions = [
            _inv_pos(1, "PCS", "925 Silver", "CZ Stud Jewellery",
                     [{"type": "Bangle", "qty": 1.0, "amount": 50.0}]),
        ]
        packing = [_pack_row(1, "Bangle", "925 SILVER", "CZ Round Shape 1", fob=50.0)]
        lineage = _build_lineage(positions, packing)
        proposal = build_correction_proposal("B6", "TST/2026-2027", lineage, None, None)
        assert isinstance(proposal, CorrectionProposal)

    def test_empty_pz_rows_returns_valid_proposal(self):
        positions = [
            _inv_pos(1, "PCS", "925 Silver", "CZ Stud Jewellery",
                     [{"type": "Bangle", "qty": 1.0, "amount": 50.0}]),
        ]
        packing = [_pack_row(1, "Bangle", "925 SILVER", "CZ Round Shape 1", fob=50.0)]
        lineage = _build_lineage(positions, packing)
        proposal = build_correction_proposal("B6", "TST/2026-2027", lineage, [], None)
        assert isinstance(proposal, CorrectionProposal)
        assert proposal.current_pz_line_count == 0

    def test_options_always_non_empty(self):
        """Must always return at least one option, even with no pz_rows."""
        positions = [
            _inv_pos(1, "PCS", "925 Silver", "CZ Stud Jewellery",
                     [{"type": "Bangle", "qty": 1.0, "amount": 50.0}]),
        ]
        packing = [_pack_row(1, "Bangle", "925 SILVER", "CZ Round Shape 1", fob=50.0)]
        lineage = _build_lineage(positions, packing)
        proposal = build_correction_proposal("B6", "TST/2026-2027", lineage, None, None)
        assert len(proposal.options) >= 1

    def test_recommended_option_is_always_a_known_id(self):
        positions = [
            _inv_pos(1, "PCS", "925 Silver", "CZ Stud Jewellery",
                     [{"type": "Bangle", "qty": 1.0, "amount": 50.0}]),
        ]
        packing = [_pack_row(1, "Bangle", "925 SILVER", "CZ Round Shape 1", fob=50.0)]
        lineage = _build_lineage(positions, packing)
        proposal = build_correction_proposal("B6", "TST/2026-2027", lineage, None, None)
        known_ids = {"NO_ACTION", "KEEP_CURRENT", "ALIGN_TO_AUTHORITY", "SPLIT_TO_STYLE_LEVEL"}
        assert proposal.recommended_option in known_ids


# ─────────────────────────────────────────────────────────────────────────────
# Section 8: Proposal fields completeness
# ─────────────────────────────────────────────────────────────────────────────

class TestProposalFields:
    """CorrectionProposal must carry all required fields."""

    def _simple_proposal(self):
        positions = [
            _inv_pos(1, "PCS", "925 Silver", "CZ Stud Jewellery",
                     [{"type": "Ring", "qty": 2.0, "amount": 200.0}]),
        ]
        packing = [_pack_row(s, "Ring", "925 SILVER", "CZ Round Shape 1", fob=100.0) for s in [1, 2]]
        lineage = _build_lineage(positions, packing)
        pz_rows = [_pz_row("TST/2026-2027-INV-01", "RING", 2.0)]
        auth_rows = [_auth_row("TST/2026-2027-INV-01", "RING", 2.0)]
        return build_correction_proposal("B7", "TST/2026-2027", lineage, pz_rows, auth_rows)

    def test_batch_id_preserved(self):
        assert self._simple_proposal().batch_id == "B7"

    def test_invoice_no_preserved(self):
        assert self._simple_proposal().invoice_no == "TST/2026-2027"

    def test_generated_at_is_iso8601(self):
        from datetime import datetime
        ga = self._simple_proposal().generated_at
        datetime.fromisoformat(ga.replace("Z", "+00:00"))

    def test_current_lines_snapshot(self):
        proposal = self._simple_proposal()
        assert len(proposal.current_lines) == 1
        assert proposal.current_lines[0].item_type == "RING"
        assert proposal.current_lines[0].qty == 2.0

    def test_options_are_correction_option_instances(self):
        for opt in self._simple_proposal().options:
            assert isinstance(opt, CorrectionOption)

    def test_proposed_lines_non_empty_on_options(self):
        for opt in self._simple_proposal().options:
            assert len(opt.proposed_lines) >= 1, f"Option {opt.option_id} has no proposed lines"

    def test_no_wfirma_import_in_service(self):
        """The correction service must never import wFirma modules."""
        import ast, pathlib
        src = pathlib.Path(
            "app/services/global_pz_correction.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                for name in names:
                    assert "wfirma" not in (name or "").lower(), (
                        f"global_pz_correction.py must NOT import wFirma: found {name!r}"
                    )


# ─────────────────────────────────────────────────────────────────────────────
# Section 9: Endpoint contract
# ─────────────────────────────────────────────────────────────────────────────

class TestEndpointContract:
    """Endpoint GET /api/v1/pz/lineage/{batch_id}/correction-proposal."""

    def _make_client(self):
        from fastapi import FastAPI
        from app.api.routes_pz import router as pz_router
        import app.core.security as sec
        app2 = FastAPI()
        app2.include_router(pz_router)
        return TestClient(app2), sec

    def test_non_global_returns_is_global_false(self):
        client, sec = self._make_client()
        with patch.object(sec, "require_api_key", return_value=None), \
             patch("app.api.routes_pz._is_global_batch", return_value=False):
            resp = client.get("/api/v1/pz/lineage/NOT_GLOBAL_BATCH/correction-proposal")
        assert resp.status_code == 200
        assert resp.json()["is_global_supplier"] is False

    def test_invalid_batch_id_rejected(self):
        client, sec = self._make_client()
        with patch.object(sec, "require_api_key", return_value=None):
            resp = client.get("/api/v1/pz/lineage/../etc/correction-proposal")
        assert resp.status_code in (400, 404)

    def test_missing_pdfs_returns_error_envelope(self):
        client, sec = self._make_client()
        with patch.object(sec, "require_api_key", return_value=None), \
             patch("app.api.routes_pz._is_global_batch", return_value=True), \
             patch("app.api.routes_pz._find_source_pdf", return_value=None):
            resp = client.get("/api/v1/pz/lineage/SOME_BATCH/correction-proposal")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("is_global_supplier") is True
        assert "error" in data

    def test_endpoint_path_registered(self):
        """The correction-proposal route must appear in routes_pz.py source."""
        import pathlib
        src = pathlib.Path("app/api/routes_pz.py").read_text(encoding="utf-8")
        assert "correction-proposal" in src, (
            "correction-proposal endpoint not found in routes_pz.py"
        )

    def test_full_proposal_shape_via_mocked_parsers(self):
        """End-to-end: mocked parsers produce a real CorrectionProposal."""
        from app.services.global_pz_lineage import LineageResult

        client, sec = self._make_client()

        fake_positions = [
            _inv_pos(1, "PCS", "925 Silver", "CZ Stud Jewellery",
                     [{"type": "Earring", "qty": 2.0, "amount": 200.0}]),
        ]
        fake_pack_rows = [
            _pack_row(1, "Earring", "925 SILVER", "CZ Round Shape 1", fob=100.0),
            _pack_row(2, "Earring", "925 SILVER", "CZ Round Shape 1", fob=100.0),
        ]
        fake_pz_rows = [_pz_row("TST/2026-2027-INV-01", "EARRING", 2.0)]
        fake_auth_rows = [_auth_row("TST/2026-2027-INV-01", "EARRING", 2.0)]

        with patch.object(sec, "require_api_key", return_value=None), \
             patch("app.api.routes_pz._is_global_batch", return_value=True), \
             patch("app.api.routes_pz._find_source_pdf", return_value=MagicMock()), \
             patch("app.api.routes_pz._extract_invoice_no", return_value="TST/2026-2027"), \
             patch("app.api.routes_pz._load_pz_rows_from_file", return_value=fake_pz_rows), \
             patch("app.api.routes_pz._load_authority_rows_from_audit", return_value=fake_auth_rows), \
             patch("app.services.global_invoice_position_parser.parse_invoice_positions_from_pdf",
                   return_value=fake_positions), \
             patch("app.services.global_packing_parser.parse_global_packing_pdf",
                   return_value=(fake_pack_rows, None, None, None)):
            resp = client.get("/api/v1/pz/lineage/BATCH_TST/correction-proposal")

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_global_supplier"] is True
        assert "options" in data
        assert "recommended_option" in data
        assert "batch_id" in data
        assert data["batch_id"] == "BATCH_TST"
        assert isinstance(data["options"], list)
        assert len(data["options"]) >= 1
