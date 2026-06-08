"""
test_hw3_approver_identity.py — Issue #502 Phase 2 (H-W3).

Approve/reject previously recorded approved_by / rejected_by from the REQUEST
BODY — caller-supplied, hence spoofable. The fix derives the actor SERVER-SIDE
from the session cookie (via _approver_from_session); the body field is ignored.

These tests prove spoofing is impossible:
  - a caller-supplied approved_by / rejected_by NEVER reaches the stored record;
  - the recorded actor is always the session identity (or "session-user" for
    API-key automation with no session cookie).
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.environ.setdefault("API_KEY", "test-key")

from app.api.routes_action_proposals import (  # noqa: E402
    _approver_from_session,
    approve_proposal,
    reject_proposal,
    create_proposal,
    ApproveBody,
    RejectBody,
)

_AUTH = "app.auth.service"


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    from app.api import routes_action_proposals
    monkeypatch.setattr(routes_action_proposals, "_OUTPUTS", tmp_path / "outputs")
    return tmp_path


def _seed_proposal(tmp_path, created_by: str = "bob@estrella.eu") -> str:
    """Create one pending dhl_followup proposal on disk; return proposal_id."""
    bid = "hw3" + str(uuid.uuid4())[:5]
    batch_dir = tmp_path / "outputs" / bid
    batch_dir.mkdir(parents=True, exist_ok=True)
    audit: Dict[str, Any] = {
        "batch_id": bid, "awb": "1234567890", "status": "processing",
        "timeline": [], "action_proposals": [],
    }
    prop = create_proposal(audit, bid, "dhl_followup", "test reason", "medium")
    prop["created_by"] = created_by
    (batch_dir / "audit.json").write_text(json.dumps(audit, ensure_ascii=False),
                                          encoding="utf-8")
    return prop["proposal_id"]


def _session(full_name=None, email=None):
    return {"id": "u1", "full_name": full_name, "email": email,
            "is_active": 1, "is_approved": 1, "role": "admin"}


# ── _approver_from_session unit ──────────────────────────────────────────────

def test_session_full_name_preferred():
    with patch(f"{_AUTH}.decode_token", return_value={"sub": "u1"}), \
         patch(f"{_AUTH}.get_user_by_id", return_value=_session("Alice Operator", "alice@x.eu")):
        assert _approver_from_session("sess") == "Alice Operator"


def test_session_email_fallback():
    with patch(f"{_AUTH}.decode_token", return_value={"sub": "u1"}), \
         patch(f"{_AUTH}.get_user_by_id", return_value=_session(None, "alice@x.eu")):
        assert _approver_from_session("sess") == "alice@x.eu"


def test_no_session_returns_session_user_sentinel():
    assert _approver_from_session(None) == "session-user"


def test_invalid_session_returns_session_user():
    with patch(f"{_AUTH}.decode_token", return_value=None):
        assert _approver_from_session("garbage") == "session-user"


# ── Spoofing is impossible (the core H-W3 proof) ─────────────────────────────

def test_approve_ignores_caller_supplied_approved_by(tmp_path):
    pid = _seed_proposal(tmp_path, created_by="bob@estrella.eu")
    with patch(f"{_AUTH}.decode_token", return_value={"sub": "u1"}), \
         patch(f"{_AUTH}.get_user_by_id", return_value=_session("Alice Operator", "alice@x.eu")):
        resp = approve_proposal(pid, ApproveBody(approved_by="ATTACKER"), pz_session="sess")
    assert resp["approved_by"] == "Alice Operator"
    assert resp["approved_by"] != "ATTACKER"
    # And persisted record matches the session identity, not the body.
    audit = json.loads(next((tmp_path / "outputs").glob("*/audit.json")).read_text(encoding="utf-8"))
    stored = [p for p in audit["action_proposals"] if p["proposal_id"] == pid][0]
    assert stored["approved_by"] == "Alice Operator"


def test_approve_api_key_no_session_uses_sentinel_not_body(tmp_path):
    pid = _seed_proposal(tmp_path)
    # No session cookie (API-key automation) → falls back to "session-user".
    resp = approve_proposal(pid, ApproveBody(approved_by="ATTACKER"), pz_session=None)
    assert resp["approved_by"] == "session-user"
    assert resp["approved_by"] != "ATTACKER"


def test_approve_works_without_body_approved_by(tmp_path):
    """Backward-compat: body.approved_by is now optional (ignored)."""
    pid = _seed_proposal(tmp_path)
    with patch(f"{_AUTH}.decode_token", return_value={"sub": "u1"}), \
         patch(f"{_AUTH}.get_user_by_id", return_value=_session("Alice Operator")):
        resp = approve_proposal(pid, ApproveBody(), pz_session="sess")  # no approved_by
    assert resp["approved_by"] == "Alice Operator"


def test_reject_ignores_caller_supplied_rejected_by(tmp_path):
    pid = _seed_proposal(tmp_path)
    with patch(f"{_AUTH}.decode_token", return_value={"sub": "u1"}), \
         patch(f"{_AUTH}.get_user_by_id", return_value=_session("Alice Operator", "alice@x.eu")):
        resp = reject_proposal(pid, RejectBody(rejected_by="ATTACKER", reason="no"), pz_session="sess")
    audit = json.loads(next((tmp_path / "outputs").glob("*/audit.json")).read_text(encoding="utf-8"))
    stored = [p for p in audit["action_proposals"] if p["proposal_id"] == pid][0]
    assert stored["rejected_by"] == "Alice Operator"
    assert stored["rejected_by"] != "ATTACKER"


# ── Structural guard ─────────────────────────────────────────────────────────

def test_routes_do_not_use_caller_supplied_actor():
    src = (_ROOT / "app" / "api" / "routes_action_proposals.py").read_text(encoding="utf-8")
    # The actor must be assigned from the server-derived var, never the body.
    assert 'proposal["approved_by"] = approved_by' in src
    assert 'proposal["rejected_by"]  = rejected_by' in src
    # No code path may assign the stored actor from the request body.
    assert 'proposal["approved_by"] = body.approved_by' not in src
    assert 'proposal["rejected_by"]  = body.rejected_by' not in src
    assert "approved_by = _approver_from_session(pz_session)" in src
    assert "rejected_by = _approver_from_session(pz_session)" in src
