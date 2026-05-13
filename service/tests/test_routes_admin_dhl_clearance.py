"""
test_routes_admin_dhl_clearance.py — admin override route for P2 ignition.

ADR-019 Model C admin route: POST /api/v1/admin/dhl-clearance/proactive-dispatch/{batch_id}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.core.config import settings  # noqa: E402


_AUTH = {"X-API-Key": "test-key-secret"}
_URL = "/api/v1/admin/dhl-clearance/proactive-dispatch"

_PHASE_PAIR_FLAGS = (
    "dhl_selfclearance_p2_live_enabled",
    "dhl_selfclearance_p2_shadow_mode",
)


@pytest.fixture(autouse=True)
def _restore_flags():
    snap = {n: getattr(settings, n) for n in _PHASE_PAIR_FLAGS}
    yield
    for n, v in snap.items():
        try:
            setattr(settings, n, v)
        except Exception:
            pass


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key-secret")
    from app.main import app
    yield TestClient(app)


def _seed_audit(tmp_path: Path, batch_id: str, *, path: str = "dhl_self_clearance",
                with_prior: bool = False) -> Path:
    audit_dir = tmp_path / "outputs" / batch_id
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / "audit.json"
    audit: Dict[str, Any] = {
        "batch_id": batch_id,
        "dhl_awb": "1234567890",
        "clearance_decision": {"clearance_path": path},
    }
    if with_prior:
        audit["dhl_clearance"] = {
            "p2_dispatch": {
                "message_id": f"shadow:{batch_id}:OLDOLD",
                "shadow": True,
                "content_sha256": "OLDSHA",
            }
        }
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    return audit_path


# ── Auth ─────────────────────────────────────────────────────────────────────

def test_post_without_api_key_returns_401(client, tmp_path):
    _seed_audit(tmp_path, "B-AUTH-1")
    r = client.post(f"{_URL}/B-AUTH-1", json={})
    assert r.status_code == 401


def test_post_with_wrong_api_key_returns_401(client, tmp_path):
    _seed_audit(tmp_path, "B-AUTH-2")
    r = client.post(f"{_URL}/B-AUTH-2", headers={"X-API-Key": "wrong"}, json={})
    assert r.status_code == 401


# ── force=False default (idempotent / DORMANT) ──────────────────────────────

def test_admin_force_false_default_invokes_coordinator(client, tmp_path):
    """force=False default → coordinator runs; DORMANT short-circuits."""
    setattr(settings, "dhl_selfclearance_p2_shadow_mode", False)
    setattr(settings, "dhl_selfclearance_p2_live_enabled", False)
    _seed_audit(tmp_path, "B-NORMAL-1")
    r = client.post(f"{_URL}/B-NORMAL-1", headers=_AUTH, json={})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["status"] == "skipped"
    assert body["reason"] == "dormant_state"
    assert body["triggered_by"] == "admin_override_normal"


def test_admin_idempotent_with_prior_dispatch(client, tmp_path):
    """force=False on already-dispatched batch returns idempotent skip."""
    setattr(settings, "dhl_selfclearance_p2_shadow_mode", True)
    setattr(settings, "dhl_selfclearance_p2_live_enabled", False)
    _seed_audit(tmp_path, "B-IDEM-1", with_prior=True)
    r = client.post(f"{_URL}/B-IDEM-1", headers=_AUTH, json={})
    assert r.status_code == 200
    body = r.json()
    assert body["idempotent"] is True
    assert body["triggered_by"] == "admin_override_normal"
    assert body["message_id"] == "shadow:B-IDEM-1:OLDOLD"


# ── force=True validation ────────────────────────────────────────────────────

def test_force_true_missing_reason_400(client, tmp_path):
    _seed_audit(tmp_path, "B-FORCE-MR")
    r = client.post(f"{_URL}/B-FORCE-MR", headers=_AUTH,
                    json={"force": True, "actor": "amit"})
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "MISSING_REASON"


def test_force_true_short_reason_400(client, tmp_path):
    _seed_audit(tmp_path, "B-FORCE-SR")
    r = client.post(f"{_URL}/B-FORCE-SR", headers=_AUTH,
                    json={"force": True, "actor": "amit", "reason": "too short"})
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "REASON_TOO_SHORT"


def test_force_true_missing_actor_400(client, tmp_path):
    _seed_audit(tmp_path, "B-FORCE-MA")
    r = client.post(f"{_URL}/B-FORCE-MA", headers=_AUTH,
                    json={"force": True, "reason": "Valid reason text here"})
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "MISSING_ACTOR"


def test_force_true_short_actor_400(client, tmp_path):
    _seed_audit(tmp_path, "B-FORCE-SA")
    r = client.post(f"{_URL}/B-FORCE-SA", headers=_AUTH,
                    json={"force": True, "reason": "Valid reason text here", "actor": "ab"})
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "ACTOR_TOO_SHORT"


# ── force=True success path ──────────────────────────────────────────────────

def test_force_true_with_valid_reason_and_actor_bypasses_idempotency(client, tmp_path):
    """force=True with prior dispatch: bypasses idempotency, archives prior,
    re-dispatches (will skip on awb_unstable since no carrier DB seeded — OK
    because what we're testing is that the force path was taken)."""
    setattr(settings, "dhl_selfclearance_p2_shadow_mode", True)
    setattr(settings, "dhl_selfclearance_p2_live_enabled", False)
    _seed_audit(tmp_path, "B-FORCE-OK", with_prior=True)
    r = client.post(f"{_URL}/B-FORCE-OK", headers=_AUTH,
                    json={"force": True, "reason": "DHL bounced; resending",
                          "actor": "amit"})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["triggered_by"] == "admin_override_force"
    assert body["idempotent"] is False
    # The prior message_id was archived (current may be skipped/awb_unstable)
    audit = json.loads(
        (tmp_path / "outputs" / "B-FORCE-OK" / "audit.json").read_text()
    )
    history = audit["dhl_clearance"].get("p2_dispatch_history", [])
    assert len(history) == 1
    assert history[0]["archived_by"] == "amit"


def test_force_true_audit_log_records_warning_level(client, tmp_path):
    setattr(settings, "dhl_selfclearance_p2_shadow_mode", True)
    setattr(settings, "dhl_selfclearance_p2_live_enabled", False)
    _seed_audit(tmp_path, "B-FORCE-AUDIT")
    r = client.post(f"{_URL}/B-FORCE-AUDIT", headers=_AUTH,
                    json={"force": True, "reason": "DHL bounced; resending",
                          "actor": "tejal"})
    assert r.status_code == 200
    audit_log = tmp_path / "dhl_selfclearance_dispatch_admin_audit.jsonl"
    assert audit_log.exists()
    entries = [json.loads(l) for l in audit_log.read_text().splitlines() if l.strip()]
    overrides = [e for e in entries if e.get("event") == "admin_dispatch_override"
                 and e.get("force") is True]
    assert len(overrides) == 1
    assert overrides[0]["log_level"] == "WARNING"
    assert overrides[0]["actor"] == "tejal"
    assert overrides[0]["reason"] == "DHL bounced; resending"
    assert overrides[0]["triggered_by"] == "admin_override_force"


# ── Path B handling ──────────────────────────────────────────────────────────

def test_admin_route_returns_422_on_path_b(client, tmp_path):
    _seed_audit(tmp_path, "B-PATHB-1", path="agency_clearance")
    r = client.post(f"{_URL}/B-PATHB-1", headers=_AUTH, json={})
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "OUT_OF_SCOPE"


# ── Audit not found ──────────────────────────────────────────────────────────

def test_admin_route_returns_404_on_missing_audit(client, tmp_path):
    r = client.post(f"{_URL}/B-MISSING", headers=_AUTH, json={})
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "AUDIT_NOT_FOUND"


# ── Lesson A: real coordinator invocation (no stubs) ────────────────────────

def test_admin_route_uses_real_coordinator(client, tmp_path):
    """Lesson A canonical: route invokes the REAL coordinator (no monkeypatched
    stub). Verify by checking that the coordinator's exception classes are
    the ones that would be raised (we hit DORMANT → no exception, but the
    return shape proves the real coordinator ran)."""
    setattr(settings, "dhl_selfclearance_p2_shadow_mode", False)
    setattr(settings, "dhl_selfclearance_p2_live_enabled", False)
    _seed_audit(tmp_path, "B-REAL-1")
    r = client.post(f"{_URL}/B-REAL-1", headers=_AUTH, json={})
    body = r.json()
    # Real coordinator returns these 6 keys (Lesson A signature contract)
    expected_keys = {"status", "reason", "message_id", "content_sha256",
                     "idempotent", "triggered_by"}
    assert expected_keys.issubset(set(body.keys())), \
        f"Coordinator return shape missing keys: {expected_keys - set(body.keys())}"
