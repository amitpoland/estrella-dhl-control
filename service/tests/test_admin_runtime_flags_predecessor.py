"""
test_admin_runtime_flags_predecessor.py — Issue #49 override-flag
predecessor-live enforcement.

Rule: REJECT POST that sets `pX_live_enabled=True` if
`p(X-1)_live_enabled=False`, UNLESS `override=true` + `override_reason`
(min 10 chars) + `actor` (min 3 chars) are present.

Predecessor chain:
- P2 has no predecessor (always allowed)
- P3 → P2
- P4 → P3
- P5 → P4

Override path: emits WARNING-level log + audit entry
`admin_runtime_flag_predecessor_override` filterable by event name.

Override does NOT bypass ADR-018 combined-state validator —
FORBIDDEN combinations remain rejected regardless of override.
"""
from __future__ import annotations

import json as _json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_SVC = Path(__file__).parent.parent
sys.path.insert(0, str(_SVC))

from app.core.config import settings  # noqa: E402


_PHASE_PAIR_FLAGS = (
    "dhl_selfclearance_p2_live_enabled",
    "dhl_selfclearance_p2_shadow_mode",
    "dhl_selfclearance_p3_live_enabled",
    "dhl_selfclearance_p3_shadow_mode",
    "dhl_selfclearance_p4_live_enabled",
    "dhl_selfclearance_p4_shadow_mode",
    "dhl_selfclearance_p5_live_enabled",
    "dhl_selfclearance_p5_shadow_mode",
)

_AUTH = {"X-API-Key": "test-key-secret"}
_URL = "/api/v1/admin/runtime-flags/self-clearance"


@pytest.fixture(autouse=True)
def _restore_phase_pair_flags():
    snapshot = {name: getattr(settings, name) for name in _PHASE_PAIR_FLAGS}
    yield
    for name, value in snapshot.items():
        try:
            setattr(settings, name, value)
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _release_phase_locks_after_test():
    from app.api.routes_admin_runtime_flags import _PHASE_LOCKS
    yield
    for lock in _PHASE_LOCKS.values():
        try:
            lock.release()
        except RuntimeError:
            pass


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key-secret")
    from app.main import app
    yield TestClient(app)


def _set_phase_pair(phase: str, *, shadow: bool, live: bool) -> None:
    setattr(settings, f"dhl_selfclearance_{phase}_shadow_mode", shadow)
    setattr(settings, f"dhl_selfclearance_{phase}_live_enabled", live)


def _post(client, body: dict):
    return client.post(_URL, headers=_AUTH, json=body)


# ── P2: no predecessor check ─────────────────────────────────────────────────

def test_p2_live_no_predecessor_check_applied(client):
    """P2 is the first live phase — no predecessor exists. POST must
    succeed even though P2 has no upstream phase."""
    _set_phase_pair("p2", shadow=True, live=False)
    r = _post(client, {
        "flag_name": "dhl_selfclearance_p2_live_enabled",
        "value": True, "actor": "amit",
    })
    assert r.status_code == 200, r.json()


# ── Predecessor live → no override needed ───────────────────────────────────

@pytest.mark.parametrize("phase,predecessor", [
    ("p3", "p2"), ("p4", "p3"), ("p5", "p4"),
])
def test_pX_live_with_predecessor_live_allowed_without_override(client, phase, predecessor):
    """When predecessor live_enabled=True, the POST is allowed without
    override across the entire P3/P4/P5 chain."""
    _set_phase_pair(predecessor, shadow=True, live=True)   # predecessor LIVE
    _set_phase_pair(phase,       shadow=True, live=False)  # this phase SHADOW
    r = _post(client, {
        "flag_name": f"dhl_selfclearance_{phase}_live_enabled",
        "value": True, "actor": "amit",
    })
    assert r.status_code == 200, r.json()


# ── Predecessor not live + no override → REJECT ──────────────────────────────

@pytest.mark.parametrize("phase,predecessor", [
    ("p3", "p2"), ("p4", "p3"), ("p5", "p4"),
])
def test_pX_live_with_predecessor_dormant_and_no_override_rejected(client, phase, predecessor):
    _set_phase_pair(predecessor, shadow=True,  live=False)  # predecessor SHADOW
    _set_phase_pair(phase,       shadow=True,  live=False)
    r = _post(client, {
        "flag_name": f"dhl_selfclearance_{phase}_live_enabled",
        "value": True, "actor": "amit",
    })
    assert r.status_code == 400
    body = r.json()["detail"]
    assert body["error_code"] == "PREDECESSOR_NOT_LIVE"
    assert phase in body["detail"]
    assert predecessor in body["detail"]
    assert "override" in body["hint"]


# ── Override path: complete contract ─────────────────────────────────────────

@pytest.mark.parametrize("phase,predecessor", [
    ("p3", "p2"), ("p4", "p3"), ("p5", "p4"),
])
def test_pX_live_with_predecessor_dormant_and_complete_override_allowed(client, phase, predecessor):
    _set_phase_pair(predecessor, shadow=True, live=False)
    _set_phase_pair(phase,       shadow=True, live=False)
    r = _post(client, {
        "flag_name": f"dhl_selfclearance_{phase}_live_enabled",
        "value": True,
        "actor": "amit",
        "override": True,
        "override_reason": "Drill: testing predecessor bypass during phased rollout",
    })
    assert r.status_code == 200, r.json()


# ── Override missing reason → REJECT ─────────────────────────────────────────

def test_p3_live_override_without_reason_rejected(client):
    _set_phase_pair("p2", shadow=True, live=False)
    _set_phase_pair("p3", shadow=True, live=False)
    r = _post(client, {
        "flag_name": "dhl_selfclearance_p3_live_enabled",
        "value": True, "actor": "amit",
        "override": True,
    })
    assert r.status_code == 400
    body = r.json()["detail"]
    assert body["error_code"] == "MISSING_OVERRIDE_REASON"
    assert body["field"] == "override_reason"


def test_p3_live_override_with_short_reason_rejected(client):
    _set_phase_pair("p2", shadow=True, live=False)
    _set_phase_pair("p3", shadow=True, live=False)
    r = _post(client, {
        "flag_name": "dhl_selfclearance_p3_live_enabled",
        "value": True, "actor": "amit",
        "override": True,
        "override_reason": "too short",  # 9 chars, below min=10
    })
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "MISSING_OVERRIDE_REASON"


# ── Override missing actor (or too short) → REJECT ───────────────────────────

def test_p3_live_override_with_short_actor_rejected(client):
    _set_phase_pair("p2", shadow=True, live=False)
    _set_phase_pair("p3", shadow=True, live=False)
    r = _post(client, {
        "flag_name": "dhl_selfclearance_p3_live_enabled",
        "value": True,
        "actor": "ab",  # 2 chars, below min=3
        "override": True,
        "override_reason": "Valid override reason content here",
    })
    # Note: existing FlagFlipBody requires actor non-empty (caught earlier
    # if actor=""). This test exercises actor=2 chars which passes the
    # earlier check but fails the override-specific min-3 check.
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "MISSING_ACTOR"


# ── Predecessor mapping correctness ──────────────────────────────────────────

def test_p4_predecessor_check_uses_p3_not_p2_or_p5(client):
    """Verify the predecessor map: P4's predecessor is P3 (not P2, not P5)."""
    # P2 LIVE (irrelevant), P3 SHADOW (predecessor), P5 LIVE (irrelevant)
    _set_phase_pair("p2", shadow=True, live=True)
    _set_phase_pair("p3", shadow=True, live=False)
    _set_phase_pair("p4", shadow=True, live=False)
    _set_phase_pair("p5", shadow=True, live=True)
    r = _post(client, {
        "flag_name": "dhl_selfclearance_p4_live_enabled",
        "value": True, "actor": "amit",
    })
    assert r.status_code == 400
    body = r.json()["detail"]
    assert body["error_code"] == "PREDECESSOR_NOT_LIVE"
    assert "p3" in body["detail"]
    assert "p2" not in body["detail"].lower().replace("p3 live", "")  # p2 not the rejection cause


def test_p5_predecessor_check_uses_p4_not_p3(client):
    """Verify the predecessor map: P5's predecessor is P4 (not P3)."""
    _set_phase_pair("p3", shadow=True, live=True)   # P3 live (would satisfy P4 chain but not P5)
    _set_phase_pair("p4", shadow=True, live=False)  # P4 SHADOW — should be the rejection cause
    _set_phase_pair("p5", shadow=True, live=False)
    r = _post(client, {
        "flag_name": "dhl_selfclearance_p5_live_enabled",
        "value": True, "actor": "amit",
    })
    assert r.status_code == 400
    body = r.json()["detail"]
    assert body["error_code"] == "PREDECESSOR_NOT_LIVE"
    assert "p4" in body["detail"]


# ── Override audit entry contents + WARNING level ────────────────────────────

def test_override_audit_entry_contains_required_fields(client, tmp_path):
    _set_phase_pair("p2", shadow=True, live=False)
    _set_phase_pair("p3", shadow=True, live=False)
    r = _post(client, {
        "flag_name": "dhl_selfclearance_p3_live_enabled",
        "value": True, "actor": "tejal",
        "override": True,
        "override_reason": "Production drill — bypass predecessor for QA verification",
    })
    assert r.status_code == 200

    audit_path = tmp_path / "dhl_selfclearance_runtime_flags_audit.jsonl"
    lines = [_json.loads(l) for l in audit_path.read_text().splitlines() if l.strip()]
    overrides = [
        e for e in lines if e.get("event") == "admin_runtime_flag_predecessor_override"
    ]
    assert len(overrides) == 1
    e = overrides[0]
    assert e["phase"] == "p3"
    assert e["predecessor"] == "p2"
    assert e["predecessor_live"] is False
    assert e["actor"] == "tejal"
    assert "drill" in e["override_reason"].lower()
    assert "timestamp" in e
    assert e["log_level"] == "WARNING"


def test_override_audit_uses_warning_log_level_field(client, tmp_path):
    """Override audit MUST be tagged WARNING (not INFO, not ERROR) per
    Issue #49 spec — operators monitor for unusual elevation events."""
    _set_phase_pair("p4", shadow=True, live=False)
    _set_phase_pair("p3", shadow=True, live=False)
    r = _post(client, {
        "flag_name": "dhl_selfclearance_p4_live_enabled",
        "value": True, "actor": "kaushal",
        "override": True,
        "override_reason": "QA bypass for predecessor live check",
    })
    assert r.status_code == 200

    audit_path = tmp_path / "dhl_selfclearance_runtime_flags_audit.jsonl"
    lines = [_json.loads(l) for l in audit_path.read_text().splitlines() if l.strip()]
    overrides = [e for e in lines if e.get("event") == "admin_runtime_flag_predecessor_override"]
    assert len(overrides) == 1
    assert overrides[0]["log_level"] == "WARNING"
    assert overrides[0]["log_level"] != "INFO"
    assert overrides[0]["log_level"] != "ERROR"


# ── live_enabled=False or shadow_mode flips → no predecessor check ──────────

def test_post_setting_live_false_not_subject_to_predecessor_check(client):
    """Flipping live_enabled FROM True TO False: predecessor check does not apply."""
    _set_phase_pair("p2", shadow=True, live=False)
    _set_phase_pair("p3", shadow=True, live=True)
    r = _post(client, {
        "flag_name": "dhl_selfclearance_p3_live_enabled",
        "value": False, "actor": "amit",
    })
    assert r.status_code == 200


def test_post_changing_only_shadow_mode_not_subject_to_predecessor_check(client):
    """Flipping shadow_mode (not live_enabled): predecessor check does not apply."""
    _set_phase_pair("p2", shadow=True, live=False)
    _set_phase_pair("p3", shadow=False, live=False)
    r = _post(client, {
        "flag_name": "dhl_selfclearance_p3_shadow_mode",
        "value": True, "actor": "amit",
    })
    assert r.status_code == 200


# ── Override does NOT bypass combined-state validator ────────────────────────

def test_override_does_not_bypass_combined_state_forbidden(client):
    """Crucial safety check: even with override=true, a POST that would
    produce a FORBIDDEN (shadow=False, live=True) state is REJECTED by
    the combined-state validator BEFORE the predecessor check fires."""
    # Phase P3 in DORMANT (False, False); set predecessor P2 to DORMANT too.
    _set_phase_pair("p2", shadow=False, live=False)
    _set_phase_pair("p3", shadow=False, live=False)
    r = _post(client, {
        "flag_name": "dhl_selfclearance_p3_live_enabled",
        "value": True, "actor": "amit",
        "override": True,
        "override_reason": "Attempt to bypass combined-state via override flag",
    })
    assert r.status_code == 400
    # Combined-state check fires first → FORBIDDEN_FLAG_COMBINATION
    # (NOT predecessor's PREDECESSOR_NOT_LIVE — combined-state is ordered first).
    body = r.json()["detail"]
    assert body["error_code"] == "FORBIDDEN_FLAG_COMBINATION"
    assert body["error_code"] != "PREDECESSOR_NOT_LIVE"


# ── Non-phase-pair flags: no predecessor check ───────────────────────────────

def test_non_phase_pair_flag_not_subject_to_predecessor_check(client):
    """tracker_paused, classifier_min_*, etc. are not phase-pair flags
    and must skip the predecessor check entirely."""
    _set_phase_pair("p2", shadow=True, live=False)
    _set_phase_pair("p3", shadow=True, live=False)
    r = _post(client, {
        "flag_name": "dhl_selfclearance_p3_tracker_paused",
        "value": True, "actor": "amit",
    })
    assert r.status_code == 200


# ── Filterable audit query (operator-review use case) ────────────────────────

def test_override_audit_entries_filterable_by_event_name(client, tmp_path):
    """Operator review query: list all override events. Verifies events
    are queryable by event name as a stable contract."""
    _set_phase_pair("p2", shadow=True, live=False)
    _set_phase_pair("p3", shadow=True, live=False)
    _set_phase_pair("p4", shadow=True, live=False)

    # Two override flips on different phases.
    _post(client, {
        "flag_name": "dhl_selfclearance_p3_live_enabled",
        "value": True, "actor": "amit",
        "override": True, "override_reason": "First override during drill 1",
    })
    # P3 is now live → P4 override no longer needs override.
    # Reset p3 to non-live, then attempt p4 override.
    _set_phase_pair("p3", shadow=True, live=False)
    _set_phase_pair("p4", shadow=True, live=False)
    _post(client, {
        "flag_name": "dhl_selfclearance_p4_live_enabled",
        "value": True, "actor": "amit",
        "override": True, "override_reason": "Second override during drill 2",
    })

    audit_path = tmp_path / "dhl_selfclearance_runtime_flags_audit.jsonl"
    lines = [_json.loads(l) for l in audit_path.read_text().splitlines() if l.strip()]
    overrides = [e for e in lines if e.get("event") == "admin_runtime_flag_predecessor_override"]
    assert len(overrides) == 2
    phases = {e["phase"] for e in overrides}
    assert phases == {"p3", "p4"}


# ── Predecessor map exposed for inspection ───────────────────────────────────

def test_predecessor_map_is_p3_p2_p4_p3_p5_p4():
    """Locked predecessor chain per Issue #49 spec."""
    from app.api.routes_admin_runtime_flags import _PREDECESSOR_MAP
    assert _PREDECESSOR_MAP == {"p3": "p2", "p4": "p3", "p5": "p4"}
    assert "p2" not in _PREDECESSOR_MAP  # P2 has no predecessor


def test_override_thresholds_are_10_and_3():
    """Specification compliance: override_reason min 10 chars, actor min 3."""
    from app.api.routes_admin_runtime_flags import (
        _OVERRIDE_REASON_MIN_CHARS,
        _OVERRIDE_ACTOR_MIN_CHARS,
    )
    assert _OVERRIDE_REASON_MIN_CHARS == 10
    assert _OVERRIDE_ACTOR_MIN_CHARS  == 3


# ── Boundary: override=False explicitly ──────────────────────────────────────

def test_override_explicitly_false_still_rejects_when_predecessor_dormant(client):
    """Per spec, override defaults False. Explicit override=False must
    behave identically to omitting the field."""
    _set_phase_pair("p2", shadow=True, live=False)
    _set_phase_pair("p3", shadow=True, live=False)
    r = _post(client, {
        "flag_name": "dhl_selfclearance_p3_live_enabled",
        "value": True, "actor": "amit",
        "override": False,
        "override_reason": "this should be ignored when override=false",
    })
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "PREDECESSOR_NOT_LIVE"


# ── Rejection audit entries carry forensic context ──────────────────────────

def test_predecessor_rejection_audit_carries_context(client, tmp_path):
    _set_phase_pair("p2", shadow=True, live=False)
    _set_phase_pair("p3", shadow=True, live=False)
    r = _post(client, {
        "flag_name": "dhl_selfclearance_p3_live_enabled",
        "value": True, "actor": "amit",
    })
    assert r.status_code == 400

    audit_path = tmp_path / "dhl_selfclearance_runtime_flags_audit.jsonl"
    lines = [_json.loads(l) for l in audit_path.read_text().splitlines() if l.strip()]
    rejected = [
        e for e in lines
        if e.get("event") == "admin_runtime_flag_rejected"
        and e.get("error_code") == "PREDECESSOR_NOT_LIVE"
    ]
    assert len(rejected) == 1
    e = rejected[0]
    assert e["phase"] == "p3"
    assert e["predecessor"] == "p2"
    assert e["predecessor_live"] is False
    assert e["override_attempted"] is False
