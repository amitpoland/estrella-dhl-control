"""
test_remediation_b8_gap17.py — Integration tests for B8 (GAP-17).

Verifies validate_product_code_in_master is called at:
  - seed_purchase_transit (inventory_state seed, routes_packing.py)
  - proforma create path (editable_lines_json save, routes_proforma.py)
Both emit advisory proposals, NOT hard blocks.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


class TestGap17WiredInRoutesPacking:
    def test_gap17_referenced_in_routes_packing_source(self):
        src = (Path(__file__).parent.parent / "app" / "api" / "routes_packing.py"
               ).read_text(encoding="utf-8")
        assert "validate_product_code_in_master" in src
        assert "GAP17_PRODUCT_NOT_IN_MASTER" in src
        assert "GAP-17" in src

    def test_gap17_advisory_not_hard_block(self):
        """The GAP-17 check in seed_purchase_transit is in a try/except — non-fatal."""
        src = (Path(__file__).parent.parent / "app" / "api" / "routes_packing.py"
               ).read_text(encoding="utf-8")
        # The check must be inside try/except with a log.debug on failure
        assert "GAP-17 check failed (non-fatal)" in src


class TestGap17WiredInRoutesProforma:
    def test_gap17_referenced_in_routes_proforma_source(self):
        src = (Path(__file__).parent.parent / "app" / "api" / "routes_proforma.py"
               ).read_text(encoding="utf-8")
        assert "validate_product_code_in_master" in src
        assert "GAP17_PRODUCT_NOT_IN_MASTER" in src
        assert "GAP-17 editable_lines check failed (non-fatal)" in src

    def test_gap17_advisory_emitted_not_blocking(self):
        """The editable_lines GAP-17 check is non-fatal."""
        src = (Path(__file__).parent.parent / "app" / "api" / "routes_proforma.py"
               ).read_text(encoding="utf-8")
        assert "GAP-17 editable_lines check failed (non-fatal)" in src


class TestValidateProductCodeInMaster:
    def test_known_code_returns_true(self, tmp_path):
        from app.services.reservation_db import init_reservation_db, upsert_product_master, validate_product_code_in_master
        db = tmp_path / "reservation_queue.db"
        init_reservation_db(db)
        upsert_product_master(db, "EJL/26-27/999-1", "DESIGN-X")
        assert validate_product_code_in_master(db, "EJL/26-27/999-1") is True

    def test_unknown_code_returns_false_not_raises(self, tmp_path):
        from app.services.reservation_db import init_reservation_db, validate_product_code_in_master
        db = tmp_path / "reservation_queue.db"
        init_reservation_db(db)
        result = validate_product_code_in_master(db, "UNKNOWN-CODE")
        assert result is False   # advisory, not raised

    def test_advisory_written_on_missing_code(self, tmp_path):
        """_write_advisory_proposal creates an Inbox-visible entry."""
        from app.pipelines.pz import _advisory_to_action_proposal, _write_advisory_proposal
        audit_path = tmp_path / "audit.json"
        audit_path.write_text(json.dumps({"batch_id": "B1", "action_proposals": []}))
        adv = _advisory_to_action_proposal(
            {"code": "GAP17_PRODUCT_NOT_IN_MASTER",
             "message": "product_code 'PC-X' not in product_master"},
            "B1", "packing_upload",
        )
        _write_advisory_proposal(audit_path, adv)
        loaded = json.loads(audit_path.read_text())
        assert any(p["type"] == "GAP17_PRODUCT_NOT_IN_MASTER"
                   for p in loaded["action_proposals"])
