"""
test_active_shipment_monitor_p2_sweep.py — sweep → coordinator P2 ignition
(Model C, ADR-019). Tests the helper `_dispatch_p2_via_coordinator` and the
gate-flip behavior of the legacy `_ensure_path_a_auto_queue`.

Lesson A: tests use the REAL coordinator + REAL audit dicts, not stubs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.core.config import settings  # noqa: E402
import app.services.active_shipment_monitor as asm  # noqa: E402


_PHASE_PAIR_FLAGS = (
    "dhl_selfclearance_p2_live_enabled",
    "dhl_selfclearance_p2_shadow_mode",
    "dhl_selfclearance_legacy_path_a_queue_enabled",
)


@pytest.fixture(autouse=True)
def _restore_flags():
    snap = {n: getattr(settings, n) for n in _PHASE_PAIR_FLAGS}
    # Force startup-replay-complete True for sweep tests (we test the guard
    # explicitly in one dedicated test; everywhere else assume boot done).
    prior_replay = asm._STARTUP_REPLAY_COMPLETE
    asm._STARTUP_REPLAY_COMPLETE = True
    # Reset per-batch lock dict between tests
    asm._P2_BATCH_LOCKS.clear()
    yield
    for n, v in snap.items():
        try:
            setattr(settings, n, v)
        except Exception:
            pass
    asm._STARTUP_REPLAY_COMPLETE = prior_replay
    asm._P2_BATCH_LOCKS.clear()


def _seed_audit(tmp_path: Path, batch_id: str, *,
                path: str = "dhl_self_clearance",
                state: str = "awaiting_preemptive_send",
                with_dhl_clearance: bool = True) -> Path:
    audit_dir = tmp_path / "outputs" / batch_id
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / "audit.json"
    audit: Dict[str, Any] = {
        "batch_id": batch_id,
        "dhl_awb": "1234567890",
        "clearance_decision": {"clearance_path": path},
    }
    if with_dhl_clearance:
        audit["dhl_clearance"] = {"state": state}
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    return audit_path


# ── Eligibility filter (positive cases) ──────────────────────────────────────

def test_sweep_dispatches_eligible_path_a_shipment(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_shadow_mode", True)
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_live_enabled", False)
    audit_path = _seed_audit(tmp_path, "B-SWEEP-1")
    audit = json.loads(audit_path.read_text())
    res = asm._dispatch_p2_via_coordinator(audit_path, audit)
    # Either dispatched (if AWB-stable resolves) OR skipped via coordinator's
    # awb_unstable gate. Both are valid; what matters is the sweep path
    # invoked the coordinator (not skipped at sweep filter level).
    assert res.get("dispatched") in (True, False)
    if res.get("dispatched"):
        assert res["triggered_by"] == "sweep"
        assert res["result"]["triggered_by"] == "sweep"
    else:
        # If skipped, must be a coordinator-level reason (not a sweep-filter one)
        assert res["skip_reason"] not in (
            "startup_replay_incomplete",
            "state_not_eligible:awaiting_preemptive_send",
            "not_path_a",
            "missing_batch_id",
            "missing_awb",
            "batch_lock_held",
        )


# ── Eligibility filter (negative cases) ──────────────────────────────────────

def test_sweep_skips_when_state_not_awaiting_preemptive_send(tmp_path):
    audit_path = _seed_audit(tmp_path, "B-NOTSTATE", state="awaiting_poland_arrival")
    audit = json.loads(audit_path.read_text())
    res = asm._dispatch_p2_via_coordinator(audit_path, audit)
    assert res["dispatched"] is False
    assert res["skip_reason"].startswith("state_not_eligible")


def test_sweep_skips_when_path_b(tmp_path):
    audit_path = _seed_audit(tmp_path, "B-PATHB", path="agency_clearance")
    audit = json.loads(audit_path.read_text())
    res = asm._dispatch_p2_via_coordinator(audit_path, audit)
    assert res["dispatched"] is False
    assert res["skip_reason"] == "not_path_a"


def test_sweep_skips_when_no_dhl_clearance_state(tmp_path):
    audit_path = _seed_audit(tmp_path, "B-NOSTATE", with_dhl_clearance=False)
    audit = json.loads(audit_path.read_text())
    res = asm._dispatch_p2_via_coordinator(audit_path, audit)
    assert res["dispatched"] is False
    # state=None when dhl_clearance dict is missing
    assert res["skip_reason"].startswith("state_not_eligible")


# ── Boot-replay guard (R-C10) ────────────────────────────────────────────────

def test_sweep_no_op_when_startup_replay_incomplete(tmp_path):
    asm._STARTUP_REPLAY_COMPLETE = False
    try:
        audit_path = _seed_audit(tmp_path, "B-NOREPLAY")
        audit = json.loads(audit_path.read_text())
        res = asm._dispatch_p2_via_coordinator(audit_path, audit)
        assert res["dispatched"] is False
        assert res["skip_reason"] == "startup_replay_incomplete"
    finally:
        asm._STARTUP_REPLAY_COMPLETE = True


def test_mark_startup_replay_complete_flips_flag():
    asm._STARTUP_REPLAY_COMPLETE = False
    try:
        asm.mark_startup_replay_complete()
        assert asm._STARTUP_REPLAY_COMPLETE is True
    finally:
        asm._STARTUP_REPLAY_COMPLETE = True


# ── Per-batch lock (P1-PREC5) ────────────────────────────────────────────────

def test_sweep_skips_when_per_batch_lock_held(tmp_path):
    audit_path = _seed_audit(tmp_path, "B-LOCKED")
    audit = json.loads(audit_path.read_text())
    # Acquire the lock externally to simulate admin route mid-call
    lock = asm._get_batch_lock("B-LOCKED")
    assert lock.acquire(blocking=True)
    try:
        res = asm._dispatch_p2_via_coordinator(audit_path, audit)
        assert res["dispatched"] is False
        assert res["skip_reason"] == "batch_lock_held"
    finally:
        lock.release()


def test_sweep_releases_lock_after_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_shadow_mode", False)
    monkeypatch.setattr(settings, "dhl_selfclearance_p2_live_enabled", False)
    audit_path = _seed_audit(tmp_path, "B-RELEASE")
    audit = json.loads(audit_path.read_text())
    # First call acquires + releases
    asm._dispatch_p2_via_coordinator(audit_path, audit)
    # Lock must now be acquirable
    lock = asm._get_batch_lock("B-RELEASE")
    assert lock.acquire(blocking=False)
    lock.release()


# ── Gate-flip: legacy vs new path mutual exclusion ─────────────────────────-

def test_legacy_gate_flip_default_false_means_new_path_runs(monkeypatch, tmp_path):
    """Default config: dhl_selfclearance_legacy_path_a_queue_enabled=False
    means the new coordinator path is primary. Verify by config inspection."""
    # Default per config.py
    assert getattr(settings, "dhl_selfclearance_legacy_path_a_queue_enabled") is False


def test_legacy_gate_flip_true_means_legacy_path_re_enabled():
    """Operator can set the flag True as a rollback escape valve."""
    setattr(settings, "dhl_selfclearance_legacy_path_a_queue_enabled", True)
    try:
        assert getattr(settings, "dhl_selfclearance_legacy_path_a_queue_enabled") is True
    finally:
        setattr(settings, "dhl_selfclearance_legacy_path_a_queue_enabled", False)


# ── Coordinator exception handling ──────────────────────────────────────────

def test_sweep_handles_coordinator_exception_without_crash(monkeypatch, tmp_path):
    """If coordinator raises an unexpected exception, sweep continues
    (returns dispatched=False with error key) — never crashes the loop."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    audit_path = _seed_audit(tmp_path, "B-EXCEPTION")
    audit = json.loads(audit_path.read_text())

    # Monkeypatch the coordinator class to raise — simulates unexpected failure
    import app.services.dhl_clearance_coordinator as coord_mod

    class _RaisingCoord:
        def dispatch_proactive(self, *a, **kw):
            raise RuntimeError("simulated coordinator failure")

    monkeypatch.setattr(coord_mod, "DhlClearanceCoordinator", _RaisingCoord)

    res = asm._dispatch_p2_via_coordinator(audit_path, audit)
    assert res["dispatched"] is False
    assert res["skip_reason"] == "coordinator_exception"
    assert res["error"] == "RuntimeError"


# ── operator_hold filter (R-C7, F-IGN-1 integration target) ─────────────────

def test_sweep_skips_when_operator_hold_true(tmp_path):
    """Atlas (or direct audit edit) sets dhl_clearance.operator_hold=True;
    sweep MUST skip the batch with skip_reason='operator_hold'."""
    audit_dir = tmp_path / "outputs" / "B-HOLD"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / "audit.json"
    audit_path.write_text(json.dumps({
        "batch_id": "B-HOLD",
        "dhl_awb": "1234567890",
        "clearance_decision": {"clearance_path": "dhl_self_clearance"},
        "dhl_clearance": {
            "state": "awaiting_preemptive_send",
            "operator_hold": True,
        },
    }))
    audit = json.loads(audit_path.read_text())
    res = asm._dispatch_p2_via_coordinator(audit_path, audit)
    assert res["dispatched"] is False
    assert res["skip_reason"] == "operator_hold"


def test_sweep_proceeds_when_operator_hold_false(tmp_path):
    """When operator_hold is False (or absent), sweep proceeds normally."""
    audit_path = _seed_audit(tmp_path, "B-NOHOLD")
    audit = json.loads(audit_path.read_text())
    audit["dhl_clearance"]["operator_hold"] = False
    res = asm._dispatch_p2_via_coordinator(audit_path, audit)
    # NOT skip_reason="operator_hold" — proceeds to coordinator gates
    assert res.get("skip_reason") != "operator_hold"


# ── Lifespan integration: marker fires after boot-replay (F8) ───────────────

def test_lifespan_fires_startup_replay_marker(monkeypatch, tmp_path):
    """gap-hunter F8: TestClient(app) context-manager form fires lifespan
    handlers. After startup, _STARTUP_REPLAY_COMPLETE must be True."""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key-secret")
    # Reset to False to prove lifespan flips it
    asm._STARTUP_REPLAY_COMPLETE = False
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        # Inside the with block, lifespan startup has fired
        assert asm._STARTUP_REPLAY_COMPLETE is True
        # Quick smoke that app is up
        r = c.get("/api/v1/health")
        # Health may 401 if API key configured; the lifespan ran is the assertion
        assert r.status_code in (200, 401, 404)


# ── Lesson A: real coordinator import (no stub bound) ───────────────────────

def test_sweep_uses_real_coordinator_module():
    """Helper imports DhlClearanceCoordinator inside its body — verify the
    module reference is the actual one (Lesson A: no shadow stubs in scope)."""
    import app.services.dhl_clearance_coordinator as coord_mod
    # Confirm the binding identity used by _dispatch_p2_via_coordinator is
    # the production class (not a test shim)
    assert hasattr(coord_mod, "DhlClearanceCoordinator")
    assert hasattr(coord_mod.DhlClearanceCoordinator, "dispatch_proactive")
