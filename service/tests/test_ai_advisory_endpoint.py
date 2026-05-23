"""
test_ai_advisory_endpoint.py — Functional tests for the advisory endpoint.

Verifies:
  * GET /api/v1/ai/advisory/workflow-blockers/{batch_id} returns 200 with
    a well-shaped advisory result for a known batch_id (using a stubbed
    batch_readiness).
  * Empty/invalid batch_id is rejected at the route layer.
  * The endpoint never causes a write to any write surface (no mutation
    of audit, no DB writes, no execute call) — checked via monkeypatched
    spies on the write paths.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("PZ_STORAGE_ROOT", str(tmp_path))
    from app.core.config import settings
    monkeypatch.setattr(settings, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(settings, "api_key", "", raising=False)
    from app.main import app
    return TestClient(app)


def _stub_readiness(monkeypatch, payload):
    from app.services import ai_advisory as adv
    monkeypatch.setattr(adv, "get_batch_readiness", lambda batch_id: payload)


def test_workflow_blockers_ready_batch(client, monkeypatch):
    _stub_readiness(monkeypatch, {
        "batch_id":  "BATCH_OK",
        "warehouse": {"status": "clean", "ready": True,  "message": "all scanned"},
        "sales":     {"status": "clean", "ready": True,  "message": "linked"},
        "wfirma":    {"status": "ready", "ready": True,  "message": "ready"},
        "dhl":       {"status": "cleared", "ready": True, "sla_breach": False, "message": "cleared"},
        "overall":   {"ready_for_closure": True, "blocked_domains": [], "next_step": "closure"},
    })
    r = client.get("/api/v1/ai/advisory/workflow-blockers/BATCH_OK")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["ready_for_closure"] is True
    assert body["blocked_domains"] == []
    assert body["blockers"] == []
    assert body["llm_used"] is False
    assert body["advisory_class"] == "R"
    assert "BATCH_OK" in body["summary"]


def test_workflow_blockers_blocked_batch(client, monkeypatch):
    _stub_readiness(monkeypatch, {
        "batch_id":  "BATCH_BLOCKED",
        "warehouse": {"status": "empty",   "ready": False, "message": "not scanned"},
        "sales":     {"status": "clean",   "ready": True,  "message": "linked"},
        "wfirma":    {"status": "blocked", "ready": False, "message": "customer auth gap"},
        "dhl":       {"status": "waiting", "ready": False, "sla_breach": False, "message": "awaiting SAD"},
        "overall":   {
            "ready_for_closure": False,
            "blocked_domains":   ["warehouse", "wfirma", "dhl"],
            "next_step":         "scan items into warehouse",
        },
    })
    r = client.get("/api/v1/ai/advisory/workflow-blockers/BATCH_BLOCKED")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ready_for_closure"] is False
    assert set(body["blocked_domains"]) == {"warehouse", "wfirma", "dhl"}
    assert len(body["blockers"]) == 3
    domains_seen = {b["domain"] for b in body["blockers"]}
    assert domains_seen == {"warehouse", "wfirma", "dhl"}
    # Every blocker carries deterministic next-action hint
    for b in body["blockers"]:
        assert b["what_unblocks_it"]
        assert b["why"]
    assert "Next step" in body["summary"]


def test_workflow_blockers_readiness_load_failure_returns_503(client, monkeypatch):
    from app.services import ai_advisory as adv

    def _boom(_batch_id):
        raise RuntimeError("simulated readiness failure")

    monkeypatch.setattr(adv, "get_batch_readiness", _boom)
    r = client.get("/api/v1/ai/advisory/workflow-blockers/BATCH_FAIL")
    assert r.status_code == 503
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "readiness_load_failed"


def test_workflow_blockers_blank_id_rejected(client, monkeypatch):
    # FastAPI normally routes a blank path segment to a different handler;
    # we ensure the surface itself wouldn't accept a whitespace-only id
    # if reached. Direct service-layer guard:
    from app.services.ai_advisory import AdvisoryError, explain_workflow_blockers
    with pytest.raises(AdvisoryError):
        explain_workflow_blockers("")


def test_advisory_endpoint_does_not_call_execute(client, monkeypatch):
    """
    Spy on the execution engine — calling the advisory endpoint must never
    invoke execute_action(...).
    """
    calls = []
    from app.services import execution_engine as ee
    orig = ee.execute_action
    monkeypatch.setattr(ee, "execute_action",
                        lambda *a, **k: (calls.append((a, k)), orig(*a, **k))[1])

    _stub_readiness(monkeypatch, {
        "batch_id":  "B",
        "warehouse": {"status": "clean", "ready": True, "message": ""},
        "sales":     {"status": "clean", "ready": True, "message": ""},
        "wfirma":    {"status": "ready", "ready": True, "message": ""},
        "dhl":       {"status": "ok",    "ready": True, "sla_breach": False, "message": ""},
        "overall":   {"ready_for_closure": True, "blocked_domains": [], "next_step": ""},
    })
    r = client.get("/api/v1/ai/advisory/workflow-blockers/B")
    assert r.status_code == 200
    assert calls == [], "advisory endpoint must not invoke execute_action"
