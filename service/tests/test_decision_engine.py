"""
test_decision_engine.py — Unit + route tests for the decision engine.

Coverage
--------
Engine unit tests (direct calls to decide()):
  1. highest priority selected — high beats medium beats low
  2. empty proposals → idle state
  3. output structure correct — all required keys present
  4. all_actions sorted — full list in priority order, not arbitrary
  5. single medium proposal — returned as primary_action even without high

Route tests:
  6. GET /api/v1/agents/decision/{batch_id} — 200, correct structure
  7. GET with idle batch — 200, status=idle
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ── Proposal factory helpers ──────────────────────────────────────────────────

def _p(action: str, priority: str, reason: str = "test reason") -> dict:
    return {"action": action, "priority": priority, "reason": reason, "next_step": None, "source": "test"}


# ── Engine unit tests ─────────────────────────────────────────────────────────

def test_highest_priority_selected():
    from app.agents.decision_engine import decide

    proposals = [
        _p("Low action",    "low"),
        _p("Medium action", "medium"),
        _p("High action",   "high"),
    ]

    with patch("app.agents.decision_engine.proposal_engine.generate", return_value=proposals):
        result = decide("B_PRIO_1")

    assert result["primary_action"] == "High action"
    assert result["status"] == "action_required"


def test_empty_proposals_returns_idle():
    from app.agents.decision_engine import decide

    with patch("app.agents.decision_engine.proposal_engine.generate", return_value=[]):
        result = decide("B_EMPTY_1")

    assert result["primary_action"] is None
    assert result["status"] == "idle"
    assert result["all_actions"] == []


def test_output_structure_complete():
    from app.agents.decision_engine import decide

    proposals = [_p("Do something", "medium", "some reason")]

    with patch("app.agents.decision_engine.proposal_engine.generate", return_value=proposals):
        result = decide("B_STRUCT_1")

    # All required keys must be present
    assert "primary_action" in result
    assert "reason" in result
    assert "next_step" in result
    assert "status" in result
    assert "all_actions" in result
    assert "batch_id" in result
    assert result["batch_id"] == "B_STRUCT_1"


def test_all_actions_sorted_by_priority():
    from app.agents.decision_engine import decide

    proposals = [
        _p("Low action",    "low"),
        _p("High action",   "high"),
        _p("Medium action", "medium"),
    ]

    with patch("app.agents.decision_engine.proposal_engine.generate", return_value=proposals):
        result = decide("B_SORT_1")

    actions = [p["action"] for p in result["all_actions"]]
    assert actions == ["High action", "Medium action", "Low action"]


def test_single_medium_proposal_returned():
    from app.agents.decision_engine import decide

    proposals = [_p("Check readiness", "medium")]

    with patch("app.agents.decision_engine.proposal_engine.generate", return_value=proposals):
        result = decide("B_MEDIUM_1")

    assert result["primary_action"] == "Check readiness"
    assert result["status"] == "action_required"


# ── Route tests ───────────────────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path):
    from app.core.config import settings
    from app.main import app
    with patch.object(settings, "storage_root", tmp_path):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _auth():
    from app.core.config import settings
    return {"X-API-KEY": settings.api_key or "test-key"}


def test_route_returns_decision(client):
    proposals = [_p("Send DHL follow-up", "high", "SLA breach")]

    with patch("app.agents.decision_engine.proposal_engine.generate", return_value=proposals):
        resp = client.get("/api/v1/agents/decision/B_ROUTE_1", headers=_auth())

    assert resp.status_code == 200
    data = resp.json()
    assert data["primary_action"] == "Send DHL follow-up"
    assert data["status"] == "action_required"
    assert data["batch_id"] == "B_ROUTE_1"
    assert isinstance(data["all_actions"], list)


def test_route_idle_batch(client):
    with patch("app.agents.decision_engine.proposal_engine.generate", return_value=[]):
        resp = client.get("/api/v1/agents/decision/B_IDLE_1", headers=_auth())

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "idle"
    assert data["primary_action"] is None


# ── proposal_engine.generate() direct tests ───────────────────────────────────

def test_generate_no_audit_no_readiness_returns_empty():
    """Missing batch with failing readiness → empty proposal list, no crash."""
    from app.agents.proposal_engine import generate
    with patch("app.agents.proposal_engine._load_audit", return_value=None), \
         patch("app.services.batch_readiness.get_batch_readiness",
               side_effect=Exception("not found")):
        result = generate("B_MISS_1")
    assert result == []


def test_generate_pending_proposal_returned_as_high():
    """pending_review action_proposal → included with priority='high'."""
    from app.agents.proposal_engine import generate
    audit = {
        "action_proposals": [
            {"status": "pending_review", "type": "dhl_followup",
             "reason": "SLA breach", "proposal_id": "P1"},
        ]
    }
    with patch("app.agents.proposal_engine._load_audit", return_value=audit), \
         patch("app.services.batch_readiness.get_batch_readiness",
               side_effect=Exception):
        result = generate("B_PEND_1")
    assert len(result) == 1
    assert result[0]["priority"] == "high"
    assert result[0]["source"] == "action_proposal"
    assert result[0]["proposal_id"] == "P1"
    assert result[0]["type"] == "dhl_followup"


def test_generate_non_pending_proposals_skipped():
    """Proposals with status != 'pending_review' must be excluded."""
    from app.agents.proposal_engine import generate
    audit = {
        "action_proposals": [
            {"status": "done",     "type": "dhl_followup",  "reason": "x", "proposal_id": "P2"},
            {"status": "approved", "type": "agency_followup", "reason": "y", "proposal_id": "P3"},
        ]
    }
    with patch("app.agents.proposal_engine._load_audit", return_value=audit), \
         patch("app.services.batch_readiness.get_batch_readiness",
               side_effect=Exception):
        result = generate("B_SKIP_1")
    assert result == []


def test_generate_readiness_exception_handled():
    """Exception from batch_readiness must not propagate — returns safe empty list."""
    from app.agents.proposal_engine import generate
    with patch("app.agents.proposal_engine._load_audit", return_value=None), \
         patch("app.services.batch_readiness.get_batch_readiness",
               side_effect=RuntimeError("db down")):
        result = generate("B_ERR_1")
    assert isinstance(result, list)
    assert result == []


def test_generate_readiness_next_step_produces_medium_proposal():
    """next_step from batch_readiness → medium-priority proposal."""
    from app.agents.proposal_engine import generate
    br = {"overall": {"next_step": "Upload customs docs"}}
    with patch("app.agents.proposal_engine._load_audit", return_value=None), \
         patch("app.services.batch_readiness.get_batch_readiness", return_value=br):
        result = generate("B_BR_1")
    assert len(result) == 1
    assert result[0]["priority"] == "medium"
    assert result[0]["source"] == "batch_readiness"
    assert result[0]["action"] == "Upload customs docs"


def test_generate_readiness_proposal_has_type_and_proposal_id():
    """batch_readiness proposals must carry type=None and proposal_id=None."""
    from app.agents.proposal_engine import generate
    br = {"overall": {"next_step": "Generate PZ"}}
    with patch("app.agents.proposal_engine._load_audit", return_value=None), \
         patch("app.services.batch_readiness.get_batch_readiness", return_value=br):
        result = generate("B_FIELDS_1")
    assert len(result) == 1
    assert "type" in result[0],        "proposal must have 'type' key"
    assert "proposal_id" in result[0], "proposal must have 'proposal_id' key"
    assert result[0]["type"] is None
    assert result[0]["proposal_id"] is None


# ── Agency SLA follow-up proposal tests ──────────────────────────────────────

def _ts_days_ago(days: float) -> str:
    """Return an ISO-8601 UTC timestamp N days in the past."""
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return dt.isoformat()


def test_agency_sla_no_proposal_when_no_forward():
    """No agency_followup proposal when audit has no agency forward timestamp."""
    from app.agents.proposal_engine import generate
    audit = {"action_proposals": [], "timeline": []}
    with patch("app.agents.proposal_engine._load_audit", return_value=audit), \
         patch("app.services.batch_readiness.get_batch_readiness",
               side_effect=Exception):
        result = generate("B_AGFWD_NONE")
    assert not any(p.get("type") == "agency_followup" for p in result)


def test_agency_sla_no_proposal_when_sad_already_received():
    """No agency_followup proposal when SAD/PZC is already imported."""
    from app.agents.proposal_engine import generate
    audit = {
        "agency_reply_package": {"built_at": _ts_days_ago(5)},
        "sad_imported_ts": "2026-04-01T10:00:00+00:00",
        "action_proposals": [],
    }
    with patch("app.agents.proposal_engine._load_audit", return_value=audit), \
         patch("app.services.batch_readiness.get_batch_readiness",
               side_effect=Exception):
        result = generate("B_AGSAD_RECV")
    assert not any(p.get("type") == "agency_followup" for p in result)


def test_agency_sla_proposal_created_when_overdue():
    """agency_followup proposal is created when forward >= 3 days old and SAD missing."""
    from app.agents.proposal_engine import generate
    audit = {
        "agency_reply_package": {"built_at": _ts_days_ago(4)},
        "action_proposals": [],
    }
    with patch("app.agents.proposal_engine._load_audit", return_value=audit), \
         patch("app.services.batch_readiness.get_batch_readiness",
               side_effect=Exception):
        result = generate("B_AGSLA_OVER")
    matches = [p for p in result if p.get("type") == "agency_followup"]
    assert len(matches) == 1
    p = matches[0]
    assert p["priority"]    == "high"
    assert p["source"]      == "agency_sla"
    assert p["action"]      == "Send agency follow-up"
    assert p["proposal_id"] is None
    assert p["next_step"]   == "Send follow-up to Agencja Celna Spedycja for SAD/PZC"
    assert p["reason"]      == "Agency response overdue: SAD/PZC not received"


def test_agency_sla_no_proposal_when_too_recent():
    """No agency_followup when forward is only 1 day old (< 3-day threshold)."""
    from app.agents.proposal_engine import generate
    audit = {
        "agency_reply_package": {"built_at": _ts_days_ago(1)},
        "action_proposals": [],
    }
    with patch("app.agents.proposal_engine._load_audit", return_value=audit), \
         patch("app.services.batch_readiness.get_batch_readiness",
               side_effect=Exception):
        result = generate("B_AGSLA_NEW")
    assert not any(p.get("type") == "agency_followup" for p in result)


def test_agency_sla_no_duplicate_when_pending_already_exists():
    """No new agency_followup proposal when one is already in pending_review."""
    from app.agents.proposal_engine import generate
    audit = {
        "agency_reply_package": {"built_at": _ts_days_ago(5)},
        "action_proposals": [
            {"type": "agency_followup", "status": "pending_review",
             "reason": "already queued", "proposal_id": "P_AF1"},
        ],
    }
    with patch("app.agents.proposal_engine._load_audit", return_value=audit), \
         patch("app.services.batch_readiness.get_batch_readiness",
               side_effect=Exception):
        result = generate("B_AGDUP")
    # Only the existing one from Source 1 — no second agency_followup from Source 3
    agency_props = [p for p in result if p.get("type") == "agency_followup"]
    assert len(agency_props) == 1
    assert agency_props[0]["source"] == "action_proposal"


def test_agency_sla_outranks_medium_readiness():
    """decision_engine selects agency_followup (high) over medium readiness fallback."""
    from app.agents.decision_engine import decide
    proposals = [
        {"action": "Upload customs docs", "priority": "medium", "reason": "readiness gate",
         "next_step": "Upload customs docs", "source": "batch_readiness",
         "type": None, "proposal_id": None},
        {"action": "Send agency follow-up", "priority": "high",
         "reason": "Agency response overdue: SAD/PZC not received",
         "next_step": "Send follow-up to Agencja Celna Spedycja for SAD/PZC",
         "source": "agency_sla", "type": "agency_followup", "proposal_id": None},
    ]
    with patch("app.agents.decision_engine.proposal_engine.generate", return_value=proposals):
        result = decide("B_AG_VS_MED")
    assert result["primary_action"] == "Send agency follow-up"
    assert result["status"] == "action_required"
    # Medium readiness must still appear in all_actions (just not first)
    all_actions = [p["action"] for p in result["all_actions"]]
    assert "Upload customs docs" in all_actions


def test_unknown_priority_sorted_last():
    """Unknown priority scores below 'low' and must not raise."""
    from app.agents.decision_engine import decide
    proposals = [
        _p("Normal low",   "low"),
        _p("Unknown tier", "critical"),  # unknown — must score 0, below low=1
        _p("High action",  "high"),
    ]
    with patch("app.agents.decision_engine.proposal_engine.generate", return_value=proposals):
        result = decide("B_UNK_1")
    actions = [p["action"] for p in result["all_actions"]]
    assert actions[0] == "High action",   "high must be first"
    assert actions[-1] == "Unknown tier", "unknown priority must be last"
    assert result["status"] == "action_required"
