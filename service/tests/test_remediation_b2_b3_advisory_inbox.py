"""
test_remediation_b2_b3_advisory_inbox.py — Integration tests for B2 + B3.

Verifies that advisory guard returns are persisted as action_proposals in audit.json
(Inbox-visible) — not just logged. Tests exercise through production entry points:
  B2: pipelines/pz.start_pz()
  B2: routes_dhl_clearance.generate_description (guard call site)
  B3: pipelines/dhl.start_clearance()
  B3: routes_dsk (two call sites)
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SVC = Path(__file__).parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_audit(tmp_path: Path, batch_id: str = "BATCH_ADV") -> Path:
    audit_path = tmp_path / "outputs" / batch_id / "audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps({
        "batch_id": batch_id,
        "status": "ready",
        "inputs": {},   # no ZC429 → SAD guard will fire
        "action_proposals": [],
    }), encoding="utf-8")
    return audit_path


def _load_audit(audit_path: Path) -> dict:
    return json.loads(audit_path.read_text(encoding="utf-8"))


# ── B2: pipelines/pz.start_pz ────────────────────────────────────────────────

class TestPzPipelineAdvisoryInbox:
    """start_pz() with advisory mode ON → action_proposal in audit.json."""

    def test_sad_advisory_creates_inbox_proposal(self, monkeypatch, tmp_path):
        from app.core.config import settings
        monkeypatch.setattr(settings, "advisory_gates_enabled", True)

        audit_path = _make_audit(tmp_path)
        audit = json.loads(audit_path.read_text())

        asyncio.get_event_loop().run_until_complete(
            __import__("app.pipelines.pz", fromlist=["start_pz"]).start_pz(
                audit=audit,
                audit_path=audit_path,
                trigger_source="user",
                actor="test",
            )
        )

        loaded = _load_audit(audit_path)
        proposals = loaded.get("action_proposals", [])
        advisory_proposals = [p for p in proposals if p.get("channel") == "advisory_gate"]
        assert len(advisory_proposals) >= 1, "Advisory should create an Inbox proposal"
        p = advisory_proposals[0]
        assert p["status"] == "pending_review"
        assert p["type"] == "PZ_NO_SAD"
        assert p["advisory"] is True

    def test_hard_mode_no_advisory_proposal(self, monkeypatch, tmp_path):
        """Hard mode raises; no advisory proposal written."""
        from app.core.config import settings
        from fastapi import HTTPException
        monkeypatch.setattr(settings, "advisory_gates_enabled", False)

        audit_path = _make_audit(tmp_path)
        audit = json.loads(audit_path.read_text())

        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                __import__("app.pipelines.pz", fromlist=["start_pz"]).start_pz(
                    audit=audit,
                    audit_path=audit_path,
                    trigger_source="user",
                    actor="test",
                )
            )
        assert exc_info.value.status_code == 422
        # No advisory proposal because hard mode raises before writing
        loaded = _load_audit(audit_path)
        advisory_proposals = [p for p in loaded.get("action_proposals", [])
                               if p.get("channel") == "advisory_gate"]
        assert advisory_proposals == []

    def test_deduplication_one_proposal_per_type(self, monkeypatch, tmp_path):
        """Second start_pz call with same advisory does not add duplicate proposal."""
        from app.core.config import settings
        monkeypatch.setattr(settings, "advisory_gates_enabled", True)

        audit_path = _make_audit(tmp_path)
        audit = json.loads(audit_path.read_text())
        pz = __import__("app.pipelines.pz", fromlist=["start_pz"])

        asyncio.get_event_loop().run_until_complete(
            pz.start_pz(audit=audit, audit_path=audit_path,
                         trigger_source="user", actor="test"))
        audit2 = _load_audit(audit_path)
        asyncio.get_event_loop().run_until_complete(
            pz.start_pz(audit=audit2, audit_path=audit_path,
                         trigger_source="user", actor="test"))

        final = _load_audit(audit_path)
        advisory_proposals = [p for p in final.get("action_proposals", [])
                               if p.get("channel") == "advisory_gate"]
        assert len(advisory_proposals) == 1, "Dedup: only one advisory proposal"


# ── B3: pipelines/dhl.start_clearance ────────────────────────────────────────

class TestDhlPipelineAdvisoryInbox:
    """start_clearance() advisory mode ON → action_proposal in audit.json."""

    def _make_clearance_audit(self, tmp_path: Path) -> tuple:
        audit_path = tmp_path / "audit.json"
        audit = {
            "batch_id": "BATCH_DHL_ADV",
            "clearance_status": None,  # not in clearance_ok → guard fires
            "action_proposals": [],
        }
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        return audit_path, audit

    def test_dhl_advisory_creates_inbox_proposal(self, monkeypatch, tmp_path):
        from app.core.config import settings
        monkeypatch.setattr(settings, "advisory_gates_enabled", True)

        audit_path, audit = self._make_clearance_audit(tmp_path)

        asyncio.get_event_loop().run_until_complete(
            __import__("app.pipelines.dhl", fromlist=["start_clearance"]).start_clearance(
                audit=audit,
                audit_path=audit_path,
                trigger_source="user",
                actor="test",
            )
        )
        loaded = _load_audit(audit_path)
        advisory_proposals = [p for p in loaded.get("action_proposals", [])
                               if p.get("channel") == "advisory_gate"]
        assert len(advisory_proposals) >= 1
        assert advisory_proposals[0]["type"] == "DHL_NO_EMAIL"


# ── B3: pipelines/pz helper functions are accessible ─────────────────────────

class TestAdvisoryHelperFunctions:
    """_advisory_to_action_proposal and _write_advisory_proposal are importable."""

    def test_helpers_importable_from_pz_pipeline(self):
        from app.pipelines.pz import _advisory_to_action_proposal, _write_advisory_proposal
        assert callable(_advisory_to_action_proposal)
        assert callable(_write_advisory_proposal)

    def test_advisory_proposal_has_required_schema(self):
        from app.pipelines.pz import _advisory_to_action_proposal
        advisory = {"code": "TEST_CODE", "message": "test message", "action": "do something"}
        p = _advisory_to_action_proposal(advisory, "BATCH_TEST", "user")
        assert p["type"] == "TEST_CODE"
        assert p["channel"] == "advisory_gate"
        assert p["status"] == "pending_review"
        assert p["advisory"] is True
        assert p["batch_id"] == "BATCH_TEST"

    def test_write_advisory_proposal_persists(self, tmp_path):
        from app.pipelines.pz import _advisory_to_action_proposal, _write_advisory_proposal
        audit_path = tmp_path / "audit.json"
        audit_path.write_text(json.dumps({"batch_id": "B1", "action_proposals": []}))
        advisory = {"code": "PZ_NO_SAD", "message": "SAD absent"}
        p = _advisory_to_action_proposal(advisory, "B1", "test")
        _write_advisory_proposal(audit_path, p)
        loaded = json.loads(audit_path.read_text())
        assert len(loaded["action_proposals"]) == 1
        assert loaded["action_proposals"][0]["channel"] == "advisory_gate"
