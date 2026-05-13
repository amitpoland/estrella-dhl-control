"""
test_admin_runtime_flags_combined_state.py — ADR-018 combined-state validator.

Verifies that the admin runtime-flags POST endpoint validates the RESULTING
(shadow_mode, live_enabled) state across both dimensions for any DHL
self-clearance phase pair (P2/P3/P4/P5), computed from
(current_settings ∪ POST_diff). Single-field validation alone is insufficient.

Coverage matrix
===============
For each phase ∈ {p2, p3, p4, p5}:
  - 4 truth-table transitions (DORMANT/SHADOW/LIVE/FORBIDDEN per ADR-018):
      DORMANT → SHADOW   (current=False+False, POST shadow=True)         — ALLOWED
      SHADOW  → LIVE     (current=True+False,  POST live=True)           — ALLOWED
      LIVE    → SHADOW   (current=True+True,   POST live=False)          — ALLOWED
      SHADOW  → DORMANT  (current=True+False,  POST shadow=False)        — ALLOWED
  - 2 FORBIDDEN attempts:
      DORMANT → FORBIDDEN  (current=False+False, POST live=True)         — REJECTED
      LIVE    → FORBIDDEN  (current=True+True,   POST shadow=False)      — REJECTED
  - 2 idempotent no-ops:
      DORMANT (same)       (current=False+False, POST shadow=False)      — ALLOWED
      LIVE (same)          (current=True+True,   POST live=True)         — ALLOWED

Single-source-of-truth check
============================
The route module imports `_enforce_flag_combination` from the coordinator.
A regression test asserts the import binding so refactors that try to
re-implement the rule inline get caught.

Per Lesson A (engineering_lessons.md): assert the import resolves to the
actual coordinator function object — not a stub or a shadow. This is the
"real-builder regression" pattern applied to a helper-import boundary.
"""
from __future__ import annotations

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


@pytest.fixture()
def client(monkeypatch, tmp_path):
    snapshot = {name: getattr(settings, name) for name in _PHASE_PAIR_FLAGS}

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key-secret")

    from app.main import app
    yield TestClient(app)

    for name, value in snapshot.items():
        try:
            setattr(settings, name, value)
        except Exception:
            pass


def _set_phase_pair(phase: str, *, shadow: bool, live: bool) -> None:
    """Directly set both dimensions of a phase pair on the settings object,
    bypassing the admin endpoint. Used to seed the 'current state' before a
    POST that exercises the combined-state validator."""
    setattr(settings, f"dhl_selfclearance_{phase}_shadow_mode", shadow)
    setattr(settings, f"dhl_selfclearance_{phase}_live_enabled", live)


def _post(client: TestClient, flag_name: str, value):
    return client.post(
        _URL,
        headers=_AUTH,
        json={"flag_name": flag_name, "value": value, "actor": "test"},
    )


# ── Single-source-of-truth: helper import binding ────────────────────────────

def test_route_imports_coordinator_helper_not_a_stub():
    """Per ADR-018 + the user-supplied PHASE D constraint: the admin route
    must import `_enforce_flag_combination` from the coordinator module
    (single source of truth). Not re-implement it.

    This regression test guards against a future refactor that drops the
    import and inlines the (False, True) check — which would create two
    places to update on the next ADR-018 amendment."""
    from app.api import routes_admin_runtime_flags as route_mod
    from app.services import dhl_clearance_coordinator as coord_mod

    # The bound name in the route module must be the actual coordinator
    # function object — not a copy, not a stub.
    assert route_mod._enforce_flag_combination is coord_mod._enforce_flag_combination, (
        "Admin route must import _enforce_flag_combination from the coordinator "
        "(single source of truth for ADR-018 Invariant 1). Found a different "
        "binding — likely an inline re-implementation."
    )

    # Same for the exception class — catching a different ForbiddenFlagCombination
    # would silently mask a real ADR-018 violation.
    assert route_mod.ForbiddenFlagCombination is coord_mod.ForbiddenFlagCombination


# ── Allowed transitions across all 4 phases ──────────────────────────────────

@pytest.mark.parametrize("phase", ["p2", "p3", "p4", "p5"])
def test_dormant_to_shadow_allowed(client, phase):
    _set_phase_pair(phase, shadow=False, live=False)
    r = _post(client, f"dhl_selfclearance_{phase}_shadow_mode", True)
    assert r.status_code == 200, r.json()
    assert r.json()["new_value"] is True


@pytest.mark.parametrize("phase", ["p2", "p3", "p4", "p5"])
def test_shadow_to_live_allowed(client, phase):
    _set_phase_pair(phase, shadow=True, live=False)
    r = _post(client, f"dhl_selfclearance_{phase}_live_enabled", True)
    assert r.status_code == 200, r.json()
    assert r.json()["new_value"] is True


@pytest.mark.parametrize("phase", ["p2", "p3", "p4", "p5"])
def test_live_to_shadow_allowed(client, phase):
    _set_phase_pair(phase, shadow=True, live=True)
    r = _post(client, f"dhl_selfclearance_{phase}_live_enabled", False)
    assert r.status_code == 200, r.json()
    assert r.json()["new_value"] is False


@pytest.mark.parametrize("phase", ["p2", "p3", "p4", "p5"])
def test_shadow_to_dormant_allowed(client, phase):
    _set_phase_pair(phase, shadow=True, live=False)
    r = _post(client, f"dhl_selfclearance_{phase}_shadow_mode", False)
    assert r.status_code == 200, r.json()
    assert r.json()["new_value"] is False


# ── FORBIDDEN attempts across all 4 phases ───────────────────────────────────

@pytest.mark.parametrize("phase", ["p2", "p3", "p4", "p5"])
def test_dormant_post_live_true_rejected_as_forbidden(client, phase):
    """current shadow=False, live=False; POST live=True → resulting (False,True) → REJECT."""
    _set_phase_pair(phase, shadow=False, live=False)
    r = _post(client, f"dhl_selfclearance_{phase}_live_enabled", True)
    assert r.status_code == 400, r.json()
    body = r.json()["detail"]
    assert body["error_code"] == "FORBIDDEN_FLAG_COMBINATION"
    assert body["field"] == "value"
    assert phase in body["detail"]
    assert "ADR-018" in body["hint"]


@pytest.mark.parametrize("phase", ["p2", "p3", "p4", "p5"])
def test_live_post_shadow_false_rejected_as_forbidden(client, phase):
    """current shadow=True, live=True; POST shadow=False → resulting (False,True) → REJECT."""
    _set_phase_pair(phase, shadow=True, live=True)
    r = _post(client, f"dhl_selfclearance_{phase}_shadow_mode", False)
    assert r.status_code == 400, r.json()
    body = r.json()["detail"]
    assert body["error_code"] == "FORBIDDEN_FLAG_COMBINATION"
    # Verify the validator REPORTS the resulting (not the POST) state in the message.
    assert "live_enabled=True" in body["detail"]
    assert "shadow_mode=False" in body["detail"]


@pytest.mark.parametrize("phase", ["p2", "p3", "p4", "p5"])
def test_forbidden_attempt_does_not_mutate_settings(client, phase):
    """A rejected POST must NOT change in-memory settings. Verifies the
    combined-state gate fires BEFORE setattr()."""
    _set_phase_pair(phase, shadow=True, live=True)
    before_shadow = getattr(settings, f"dhl_selfclearance_{phase}_shadow_mode")
    before_live   = getattr(settings, f"dhl_selfclearance_{phase}_live_enabled")
    assert before_shadow is True and before_live is True

    r = _post(client, f"dhl_selfclearance_{phase}_shadow_mode", False)
    assert r.status_code == 400

    # Settings unchanged.
    assert getattr(settings, f"dhl_selfclearance_{phase}_shadow_mode") is True
    assert getattr(settings, f"dhl_selfclearance_{phase}_live_enabled") is True


# ── Idempotent no-ops ────────────────────────────────────────────────────────

@pytest.mark.parametrize("phase", ["p2", "p3", "p4", "p5"])
def test_dormant_post_shadow_false_idempotent(client, phase):
    """current shadow=False, live=False; POST shadow=False → no state change → ALLOWED."""
    _set_phase_pair(phase, shadow=False, live=False)
    r = _post(client, f"dhl_selfclearance_{phase}_shadow_mode", False)
    assert r.status_code == 200


@pytest.mark.parametrize("phase", ["p2", "p3", "p4", "p5"])
def test_live_post_live_true_idempotent(client, phase):
    """current shadow=True, live=True; POST live=True → no state change → ALLOWED."""
    _set_phase_pair(phase, shadow=True, live=True)
    r = _post(client, f"dhl_selfclearance_{phase}_live_enabled", True)
    assert r.status_code == 200


# ── Non-phase-pair flags must NOT be subject to the combined-state gate ──────

def test_tracker_paused_not_subject_to_combined_state(client):
    """`dhl_selfclearance_p3_tracker_paused` is a phase-3 flag but is NOT a
    member of the (shadow_mode, live_enabled) pair. The combined-state
    validator must no-op for it."""
    # Set p3 to LIVE state so any spurious application of the rule would
    # surface; tracker_paused flips must remain unaffected.
    _set_phase_pair("p3", shadow=True, live=True)
    r = _post(client, "dhl_selfclearance_p3_tracker_paused", True)
    assert r.status_code == 200


def test_classifier_threshold_not_subject_to_combined_state(client):
    _set_phase_pair("p4", shadow=False, live=False)
    r = _post(client, "dhl_selfclearance_p4_classifier_min_confidence", 0.85)
    assert r.status_code == 200


def test_followup_interval_not_subject_to_combined_state(client):
    r = _post(client, "dhl_selfclearance_followup_working_interval_sec", 600)
    assert r.status_code == 200


def test_value_threshold_not_subject_to_combined_state(client):
    r = _post(client, "dhl_selfclearance_value_threshold_usd", 2500)
    assert r.status_code == 200


# ── Phase isolation: a forbidden p2 POST does not block other phases ─────────

def test_forbidden_p2_attempt_does_not_affect_p3(client):
    """Each phase's combined-state is independent. Rejecting a p2 FORBIDDEN
    POST must not interfere with a subsequent p3 ALLOWED POST."""
    _set_phase_pair("p2", shadow=False, live=False)
    _set_phase_pair("p3", shadow=False, live=False)

    r1 = _post(client, "dhl_selfclearance_p2_live_enabled", True)
    assert r1.status_code == 400

    r2 = _post(client, "dhl_selfclearance_p3_shadow_mode", True)
    assert r2.status_code == 200


# ── Helper-level unit tests ──────────────────────────────────────────────────

def test_parse_phase_pair_extracts_phase_and_dimension():
    from app.api.routes_admin_runtime_flags import _parse_phase_pair

    assert _parse_phase_pair("dhl_selfclearance_p2_shadow_mode") == ("p2", "shadow_mode")
    assert _parse_phase_pair("dhl_selfclearance_p3_live_enabled") == ("p3", "live_enabled")
    assert _parse_phase_pair("dhl_selfclearance_p4_shadow_mode") == ("p4", "shadow_mode")
    assert _parse_phase_pair("dhl_selfclearance_p5_live_enabled") == ("p5", "live_enabled")


def test_parse_phase_pair_returns_none_for_non_pair_flags():
    from app.api.routes_admin_runtime_flags import _parse_phase_pair

    assert _parse_phase_pair("dhl_selfclearance_p3_tracker_paused") is None
    assert _parse_phase_pair("dhl_selfclearance_p5_pz_trigger_enabled") is None
    assert _parse_phase_pair("dhl_selfclearance_p4_classifier_min_confidence") is None
    assert _parse_phase_pair("dhl_selfclearance_followup_working_interval_sec") is None
    assert _parse_phase_pair("dhl_selfclearance_value_threshold_usd") is None


def test_parse_phase_pair_returns_none_for_phase_zero_or_one():
    """ADR-018 Invariants apply only to P2/P3/P4/P5. P0 has no live/shadow
    pair; P1 was scaffold-only. Both must not match."""
    from app.api.routes_admin_runtime_flags import _parse_phase_pair

    assert _parse_phase_pair("dhl_selfclearance_p0_live_enabled") is None
    assert _parse_phase_pair("dhl_selfclearance_p1_shadow_mode") is None
    assert _parse_phase_pair("dhl_selfclearance_p6_live_enabled") is None


def test_parse_phase_pair_rejects_partial_matches():
    from app.api.routes_admin_runtime_flags import _parse_phase_pair

    # Exact full-match required — no leading/trailing fluff allowed.
    assert _parse_phase_pair("prefix_dhl_selfclearance_p2_shadow_mode") is None
    assert _parse_phase_pair("dhl_selfclearance_p2_shadow_mode_suffix") is None
    assert _parse_phase_pair("") is None
