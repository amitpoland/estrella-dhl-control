"""#439: action-proposal approve/reject must 409 on re-action of a non-terminal
(already-approved) proposal, not permit a silent state change.

Before this fix:
  - approve of an already-`approved` proposal silently re-approved and
    overwrote `approved_by` (blocked only rejected/queued/sent).
  - reject of an `approved` proposal was ALLOWED — the dangerous cross-action
    `approved -> rejected` flip under two concurrent operators (blocked only
    queued/sent).

The existing test_rejected_proposal_cannot_be_approved only asserted state; it
never called the endpoint. These drive the real handlers.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi import HTTPException

_SVC = Path(__file__).resolve().parent.parent
if str(_SVC) not in sys.path:
    sys.path.insert(0, str(_SVC))

from app.api import routes_action_proposals as rap  # noqa: E402
from app.api.routes_action_proposals import (  # noqa: E402
    ApproveBody, RejectBody, approve_proposal, reject_proposal, create_proposal,
)


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(rap, "_OUTPUTS", tmp_path / "outputs")


def _seed_approved(tmp_path) -> tuple[str, Path]:
    """A batch with one already-approved proposal on disk; returns (pid, audit_path)."""
    bid = str(uuid.uuid4())[:8]
    d = tmp_path / "outputs" / bid
    d.mkdir(parents=True)
    audit: Dict[str, Any] = {"batch_id": bid, "awb": "1234567890", "timeline": []}
    prop = create_proposal(audit, bid, "dhl_followup", "reason", "high")
    prop["status"]      = "approved"
    prop["approved_by"] = "operator_a@estrellajewels.eu"
    prop["approved_at"] = "2026-07-22T00:00:00Z"
    ap = d / "audit.json"
    ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    return prop["proposal_id"], ap


def _status_of(ap: Path, pid: str) -> str:
    audit = json.loads(ap.read_text(encoding="utf-8"))
    for p in audit.get("action_proposals", []):
        if p.get("proposal_id") == pid:
            return p.get("status", "")
    raise AssertionError("proposal vanished")


def test_approve_already_approved_returns_409(tmp_path):
    pid, ap = _seed_approved(tmp_path)
    with pytest.raises(HTTPException) as ei:
        approve_proposal(pid, ApproveBody(), pz_session="sess")
    assert ei.value.status_code == 409
    # approved_by must NOT have been overwritten by the racing second approve
    audit = json.loads(ap.read_text(encoding="utf-8"))
    prop = next(p for p in audit["action_proposals"] if p["proposal_id"] == pid)
    assert prop["approved_by"] == "operator_a@estrellajewels.eu"


def test_reject_of_approved_returns_409_no_silent_flip(tmp_path):
    """The dangerous one: operator A approved, operator B rejects the same item."""
    pid, ap = _seed_approved(tmp_path)
    with pytest.raises(HTTPException) as ei:
        reject_proposal(pid, RejectBody(reason="changed my mind"), pz_session="sess")
    assert ei.value.status_code == 409
    # status must remain approved — no silent approved -> rejected flip
    assert _status_of(ap, pid) == "approved"


def test_rejected_proposal_still_cannot_be_approved(tmp_path):
    """Pre-existing guard must still hold (regression safety around the new one)."""
    bid = str(uuid.uuid4())[:8]
    d = tmp_path / "outputs" / bid
    d.mkdir(parents=True)
    audit = {"batch_id": bid, "awb": "1", "timeline": []}
    prop = create_proposal(audit, bid, "dhl_followup", "reason", "high")
    prop["status"] = "rejected"
    ap = d / "audit.json"
    ap.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(HTTPException) as ei:
        approve_proposal(prop["proposal_id"], ApproveBody(), pz_session="sess")
    assert ei.value.status_code == 409


def test_pending_proposal_can_still_be_approved_and_rejected(tmp_path):
    """The new guards must not block the legitimate first action on a
    pending_review proposal."""
    # approve a fresh pending proposal
    bid = str(uuid.uuid4())[:8]
    d = tmp_path / "outputs" / bid
    d.mkdir(parents=True)
    audit = {"batch_id": bid, "awb": "1", "timeline": []}
    p1 = create_proposal(audit, bid, "dhl_followup", "reason", "high")
    (d / "audit.json").write_text(json.dumps(audit), encoding="utf-8")
    assert p1["status"] == "pending_review"
    res = approve_proposal(p1["proposal_id"], ApproveBody(), pz_session="sess")
    assert res.get("status") in ("approved", "ok") or res.get("ok") is True

    # reject a different fresh pending proposal
    bid2 = str(uuid.uuid4())[:8]
    d2 = tmp_path / "outputs" / bid2
    d2.mkdir(parents=True)
    audit2 = {"batch_id": bid2, "awb": "2", "timeline": []}
    p2 = create_proposal(audit2, bid2, "dhl_followup", "reason", "high")
    (d2 / "audit.json").write_text(json.dumps(audit2), encoding="utf-8")
    res2 = reject_proposal(p2["proposal_id"], RejectBody(reason="no"), pz_session="sess")
    assert res2.get("status") in ("rejected", "ok") or res2.get("ok") is True
