"""
test_dhl_clearance_coordinator_force.py — coordinator force=True semantics
+ triggered_by return field + caller contract (ADR-019, P1-PREC3, R-C9).

Lesson A: tests instantiate the REAL DhlClearanceCoordinator and exercise
the real dispatch_proactive() against synthetic Path A audit fixtures —
no stubs of the coordinator itself.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.core.config import settings  # noqa: E402
from app.services.dhl_clearance_coordinator import (  # noqa: E402
    DhlClearanceCoordinator,
    DispatchInput,
    ForceRequiresActor,
    CallerRejectsForce,
)


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


def _path_a_audit() -> Dict[str, Any]:
    """Synthetic Path A audit suitable for coordinator dispatch."""
    return {
        "batch_id": "B-FORCE-1",
        "dhl_awb": "1234567890",
        "clearance_decision": {"clearance_path": "dhl_self_clearance"},
    }


def _input(audit: Dict[str, Any], batch_id: str = "B-FORCE-1") -> DispatchInput:
    return DispatchInput(batch_id=batch_id, awb=str(audit.get("dhl_awb", "")), audit=audit)


# ── Default behaviour: force=False, caller=sweep, triggered_by="sweep" ──────

def test_dispatch_proactive_default_caller_is_sweep():
    """Default caller is sweep; default force is False; return shape carries
    triggered_by='sweep' even on the DORMANT short-circuit."""
    setattr(settings, "dhl_selfclearance_p2_shadow_mode", False)
    setattr(settings, "dhl_selfclearance_p2_live_enabled", False)
    coord = DhlClearanceCoordinator()
    res = coord.dispatch_proactive(_input(_path_a_audit()))
    assert res["status"] == "skipped"
    assert res["reason"] == "dormant_state"
    assert res["triggered_by"] == "sweep"
    assert res["idempotent"] is False


def test_dispatch_proactive_admin_route_normal_triggered_by_label():
    """caller='admin_route' + force=False → triggered_by='admin_override_normal'."""
    setattr(settings, "dhl_selfclearance_p2_shadow_mode", False)
    setattr(settings, "dhl_selfclearance_p2_live_enabled", False)
    coord = DhlClearanceCoordinator()
    res = coord.dispatch_proactive(
        _input(_path_a_audit()), caller="admin_route", force=False,
    )
    assert res["triggered_by"] == "admin_override_normal"


def test_dispatch_proactive_admin_route_force_triggered_by_label():
    """caller='admin_route' + force=True → triggered_by='admin_override_force'."""
    setattr(settings, "dhl_selfclearance_p2_shadow_mode", False)
    setattr(settings, "dhl_selfclearance_p2_live_enabled", False)
    coord = DhlClearanceCoordinator()
    res = coord.dispatch_proactive(
        _input(_path_a_audit()),
        caller="admin_route", force=True, actor="amit",
    )
    assert res["triggered_by"] == "admin_override_force"


# ── Force-contract guards (ADR-019 Invariant 2 + 4) ─────────────────────────

def test_force_without_actor_raises_ForceRequiresActor():
    """force=True without actor must raise (admin route should have caught
    this earlier; coordinator-level guard is belt-and-braces)."""
    coord = DhlClearanceCoordinator()
    with pytest.raises(ForceRequiresActor):
        coord.dispatch_proactive(
            _input(_path_a_audit()),
            caller="admin_route", force=True, actor=None,
        )


def test_force_with_empty_actor_raises_ForceRequiresActor():
    coord = DhlClearanceCoordinator()
    with pytest.raises(ForceRequiresActor):
        coord.dispatch_proactive(
            _input(_path_a_audit()),
            caller="admin_route", force=True, actor="   ",
        )


def test_sweep_caller_with_force_true_raises_CallerRejectsForce():
    """ADR-019 Invariant 4: sweep MUST never set force=True."""
    coord = DhlClearanceCoordinator()
    with pytest.raises(CallerRejectsForce):
        coord.dispatch_proactive(
            _input(_path_a_audit()),
            caller="sweep", force=True, actor="amit",
        )


# ── Idempotency: force=False respects prior dispatch ────────────────────────

def test_force_false_returns_idempotent_when_prior_dispatch_exists():
    """Audit pre-seeded with a prior p2_dispatch.message_id; force=False
    should short-circuit with idempotent=True."""
    setattr(settings, "dhl_selfclearance_p2_shadow_mode", True)
    setattr(settings, "dhl_selfclearance_p2_live_enabled", False)
    audit = _path_a_audit()
    audit["dhl_clearance"] = {
        "p2_dispatch": {
            "message_id": "shadow:B-FORCE-1:abcdef123456",
            "shadow": True,
            "content_sha256": "deadbeef",
        }
    }
    coord = DhlClearanceCoordinator()
    res = coord.dispatch_proactive(
        _input(audit), caller="admin_route", force=False,
    )
    assert res["idempotent"] is True
    assert res["message_id"] == "shadow:B-FORCE-1:abcdef123456"
    assert res["triggered_by"] == "admin_override_normal"


def test_force_true_archives_prior_into_history_and_re_dispatches():
    """force=True must bypass idempotency, archive prior into history,
    and clear current p2_dispatch so a fresh dispatch fires."""
    setattr(settings, "dhl_selfclearance_p2_shadow_mode", True)
    setattr(settings, "dhl_selfclearance_p2_live_enabled", False)
    audit = _path_a_audit()
    audit["dhl_clearance"] = {
        "p2_dispatch": {
            "message_id": "shadow:B-FORCE-1:OLDOLD",
            "shadow": True,
            "content_sha256": "OLDSHA",
        }
    }
    coord = DhlClearanceCoordinator()
    # Force=True with no AWB-stable lookup will short-circuit at the
    # AWB-stable gate (status=skipped, reason=awb_unstable) — that's fine
    # for this test; what we're verifying is the archive-to-history step.
    coord.dispatch_proactive(
        _input(audit),
        caller="admin_route", force=True, actor="amit",
    )
    history = audit["dhl_clearance"].get("p2_dispatch_history", [])
    assert len(history) == 1
    assert history[0]["message_id"] == "shadow:B-FORCE-1:OLDOLD"
    assert history[0]["archived_by"] == "amit"
    assert history[0]["archive_reason"] == "force_redispatch"
    # Current p2_dispatch is cleared (empty dict)
    assert audit["dhl_clearance"]["p2_dispatch"] == {}
