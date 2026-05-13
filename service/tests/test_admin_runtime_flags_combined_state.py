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


@pytest.fixture(autouse=True)
def _restore_phase_pair_flags():
    """Autouse: snapshot/restore ALL phase-pair flag values around every test
    in this file — including tests that don't use the `client` fixture
    (e.g. boot-replay tests that drive `load_persisted_flags_into_settings`
    directly via `setattr`). Prevents inter-file test pollution where a
    DORMANT-leaving test breaks downstream tests in
    test_dhl_selfclearance_p0_admin_runtime_flags.py that assume default
    SHADOW state."""
    snapshot = {name: getattr(settings, name) for name in _PHASE_PAIR_FLAGS}
    yield
    for name, value in snapshot.items():
        try:
            setattr(settings, name, value)
        except Exception:
            pass


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key-secret")

    from app.main import app
    yield TestClient(app)


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
    # Issue #49: pX live requires predecessor live. Seed predecessor LIVE.
    _PREDECESSOR = {"p3": "p2", "p4": "p3", "p5": "p4"}
    if phase in _PREDECESSOR:
        _set_phase_pair(_PREDECESSOR[phase], shadow=True, live=True)
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


@pytest.mark.parametrize("phase", ["p2", "p3", "p4", "p5"])
def test_forbidden_attempt_does_not_mutate_store_or_emit_flipped_audit(client, tmp_path, phase):
    """Per security review: rejection must leave settings AND store AND
    audit-log unchanged with respect to a successful flip. The rejection
    audit entry IS expected (tamper-evidence), but no `flipped` event."""
    import json as _json

    _set_phase_pair(phase, shadow=True, live=True)

    store_path = tmp_path / "dhl_selfclearance_runtime_flags.json"
    audit_path = tmp_path / "dhl_selfclearance_runtime_flags_audit.jsonl"

    r = _post(client, f"dhl_selfclearance_{phase}_shadow_mode", False)
    assert r.status_code == 400

    # Persistent store: must contain NO entry for the rejected flag.
    if store_path.exists():
        store = _json.loads(store_path.read_text())
        assert f"dhl_selfclearance_{phase}_shadow_mode" not in store

    # Audit log: must contain a `rejected` entry for this attempt, but NO
    # `flipped` entry for the same flag.
    assert audit_path.exists(), "Rejection should produce tamper-evidence audit entry"
    lines = [
        _json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()
    ]
    rejected = [
        e for e in lines
        if e.get("event") == "admin_runtime_flag_rejected"
        and e.get("flag_name") == f"dhl_selfclearance_{phase}_shadow_mode"
    ]
    flipped = [
        e for e in lines
        if e.get("event") == "admin_runtime_flag_flipped"
        and e.get("flag_name") == f"dhl_selfclearance_{phase}_shadow_mode"
    ]
    assert len(rejected) == 1, f"Expected exactly 1 rejection entry, got {rejected}"
    assert len(flipped) == 0,  f"Expected NO flipped entry on rejected POST, got {flipped}"


@pytest.mark.parametrize("phase", ["p2", "p3", "p4", "p5"])
def test_rejection_audit_entry_carries_full_forensic_context(client, tmp_path, phase):
    """Per security AUDIT-TRACE-COMPLETENESS: rejection audit entries must
    include phase, attempted_value, current_shadow, current_live,
    resulting_shadow, resulting_live so probing patterns can be forensically
    reconstructed."""
    import json as _json

    _set_phase_pair(phase, shadow=True, live=True)
    audit_path = tmp_path / "dhl_selfclearance_runtime_flags_audit.jsonl"

    r = _post(client, f"dhl_selfclearance_{phase}_shadow_mode", False)
    assert r.status_code == 400

    lines = [
        _json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()
    ]
    rejected = [
        e for e in lines
        if e.get("event") == "admin_runtime_flag_rejected"
        and e.get("error_code") == "FORBIDDEN_FLAG_COMBINATION"
    ]
    assert len(rejected) == 1
    entry = rejected[0]
    assert entry.get("phase") == phase
    assert entry.get("dimension") == "shadow_mode"
    assert entry.get("attempted_value") is False
    assert entry.get("current_shadow") is True
    assert entry.get("current_live") is True
    assert entry.get("resulting_shadow") is False
    assert entry.get("resulting_live") is True
    assert entry.get("actor") == "test"


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
    # Issue #49: pX live requires predecessor live. Seed predecessor LIVE.
    _PREDECESSOR = {"p3": "p2", "p4": "p3", "p5": "p4"}
    if phase in _PREDECESSOR:
        _set_phase_pair(_PREDECESSOR[phase], shadow=True, live=True)
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


# ── GET endpoint: derived phase-state labels (gap-hunter F3) ─────────────────

def test_get_returns_phases_block_with_state_labels(client):
    _set_phase_pair("p2", shadow=False, live=False)   # DORMANT
    _set_phase_pair("p3", shadow=True,  live=False)   # SHADOW
    _set_phase_pair("p4", shadow=True,  live=True)    # LIVE
    _set_phase_pair("p5", shadow=False, live=False)   # DORMANT

    r = client.get(_URL, headers=_AUTH)
    assert r.status_code == 200
    body = r.json()

    # Backwards-compat: flat flag map still at top level.
    assert "dhl_selfclearance_p2_live_enabled" in body
    assert body["dhl_selfclearance_p2_live_enabled"] is False

    # Adjunct phase-state classification under `_phases`.
    phases = body["_phases"]
    assert phases["p2"]["state"] == "DORMANT"
    assert phases["p3"]["state"] == "SHADOW"
    assert phases["p4"]["state"] == "LIVE"
    assert phases["p5"]["state"] == "DORMANT"
    # Tuple values surfaced for completeness.
    assert phases["p3"]["shadow_mode"] is True
    assert phases["p3"]["live_enabled"] is False


def test_classify_phase_state_truth_table():
    from app.api.routes_admin_runtime_flags import _classify_phase_state
    # ADR-018 truth table
    assert _classify_phase_state(False, False) == "DORMANT"
    assert _classify_phase_state(True,  False) == "SHADOW"
    assert _classify_phase_state(True,  True)  == "LIVE"
    assert _classify_phase_state(False, True)  == "FORBIDDEN"


def test_get_does_not_include_underscore_phases_as_flag_name(client):
    """Defensive: `_phases` adjunct key must NOT be confused with a real
    flag name. Verify the existing `_ALLOWED_FLAGS` set excludes it."""
    from app.api.routes_admin_runtime_flags import ALLOWED_FLAG_NAMES
    assert "_phases" not in ALLOWED_FLAG_NAMES


# ── Boot-time replay: ADR-018 §a startup enforcement (gap-hunter F1) ─────────

def test_startup_replay_repairs_persisted_forbidden_combination(monkeypatch, tmp_path):
    """If the persisted JSON store contains a (False, True) combination —
    whether by hand-edit, race condition, or pre-validator-era state — the
    boot-time replay MUST detect it and force the affected phase back to
    DORMANT before any phase code can act on the corrupt state."""
    import json as _json

    monkeypatch.setattr(settings, "storage_root", tmp_path)

    # Seed a persisted store with a FORBIDDEN p3 combination.
    store = {
        "dhl_selfclearance_p3_shadow_mode":  False,
        "dhl_selfclearance_p3_live_enabled": True,   # FORBIDDEN with shadow=False
        "dhl_selfclearance_p2_shadow_mode":  True,   # SHADOW (legal)
    }
    store_path = tmp_path / "dhl_selfclearance_runtime_flags.json"
    store_path.write_text(_json.dumps(store))

    # Ensure starting in-memory state is DORMANT for both phases (so any
    # post-replay corruption is attributable to the replay itself).
    _set_phase_pair("p2", shadow=False, live=False)
    _set_phase_pair("p3", shadow=False, live=False)

    from app.api.routes_admin_runtime_flags import load_persisted_flags_into_settings

    applied = load_persisted_flags_into_settings()

    # All three flags were applied — but the p3 FORBIDDEN combination must
    # have been REPAIRED back to DORMANT after the per-flag replay.
    assert "dhl_selfclearance_p3_live_enabled" in applied
    assert getattr(settings, "dhl_selfclearance_p3_shadow_mode")  is False
    assert getattr(settings, "dhl_selfclearance_p3_live_enabled") is False, (
        "Boot replay must repair FORBIDDEN persisted state to DORMANT — "
        "ADR-018 §a startup enforcement"
    )

    # p2 SHADOW state must be preserved (legal combination).
    assert getattr(settings, "dhl_selfclearance_p2_shadow_mode")  is True
    assert getattr(settings, "dhl_selfclearance_p2_live_enabled") is False

    # Audit log must record the repair for forensic visibility.
    audit_path = tmp_path / "dhl_selfclearance_runtime_flags_audit.jsonl"
    assert audit_path.exists()
    repair_entries = [
        _json.loads(line) for line in audit_path.read_text().splitlines()
        if line.strip()
        and _json.loads(line).get("event") == "runtime_flags_startup_forbidden_combo_repaired"
    ]
    assert len(repair_entries) == 1
    repair = repair_entries[0]
    assert repair["phase"] == "p3"
    assert repair["prior_shadow"] is False
    assert repair["prior_live"]   is True
    assert repair["forced_shadow"] is False
    assert repair["forced_live"]   is False


def test_startup_replay_no_repair_when_all_states_legal(monkeypatch, tmp_path):
    """The startup sweep must NOT touch any phase whose persisted state is
    already DORMANT/SHADOW/LIVE. Only FORBIDDEN combinations get repaired."""
    import json as _json

    monkeypatch.setattr(settings, "storage_root", tmp_path)

    # All four phases in legal states.
    store = {
        "dhl_selfclearance_p2_shadow_mode":  True,   # SHADOW
        "dhl_selfclearance_p3_shadow_mode":  True,   # SHADOW
        "dhl_selfclearance_p3_live_enabled": True,   # → LIVE (with shadow=True)
        "dhl_selfclearance_p4_shadow_mode":  False,  # DORMANT
        "dhl_selfclearance_p5_shadow_mode":  True,   # SHADOW
    }
    (tmp_path / "dhl_selfclearance_runtime_flags.json").write_text(_json.dumps(store))

    _set_phase_pair("p2", shadow=False, live=False)
    _set_phase_pair("p3", shadow=False, live=False)
    _set_phase_pair("p4", shadow=False, live=False)
    _set_phase_pair("p5", shadow=False, live=False)

    from app.api.routes_admin_runtime_flags import load_persisted_flags_into_settings
    load_persisted_flags_into_settings()

    # Verify no repair happened.
    audit_path = tmp_path / "dhl_selfclearance_runtime_flags_audit.jsonl"
    if audit_path.exists():
        lines = [_json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()]
        repairs = [e for e in lines if e.get("event") == "runtime_flags_startup_forbidden_combo_repaired"]
        assert repairs == [], f"Expected no repair audit entries, got {repairs}"

    # Verify states are preserved.
    assert getattr(settings, "dhl_selfclearance_p3_shadow_mode")  is True
    assert getattr(settings, "dhl_selfclearance_p3_live_enabled") is True


def test_startup_replay_repairs_multiple_phases_independently(monkeypatch, tmp_path):
    """Two phases simultaneously corrupt → both repaired, two audit entries."""
    import json as _json

    monkeypatch.setattr(settings, "storage_root", tmp_path)

    store = {
        "dhl_selfclearance_p2_shadow_mode":  False,
        "dhl_selfclearance_p2_live_enabled": True,    # FORBIDDEN
        "dhl_selfclearance_p4_shadow_mode":  False,
        "dhl_selfclearance_p4_live_enabled": True,    # FORBIDDEN
    }
    (tmp_path / "dhl_selfclearance_runtime_flags.json").write_text(_json.dumps(store))

    for ph in ("p2", "p3", "p4", "p5"):
        _set_phase_pair(ph, shadow=False, live=False)

    from app.api.routes_admin_runtime_flags import load_persisted_flags_into_settings
    load_persisted_flags_into_settings()

    assert getattr(settings, "dhl_selfclearance_p2_live_enabled") is False
    assert getattr(settings, "dhl_selfclearance_p4_live_enabled") is False

    audit_path = tmp_path / "dhl_selfclearance_runtime_flags_audit.jsonl"
    lines = [_json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()]
    repairs = [e for e in lines if e.get("event") == "runtime_flags_startup_forbidden_combo_repaired"]
    repaired_phases = {e["phase"] for e in repairs}
    assert repaired_phases == {"p2", "p4"}


def test_startup_enforcement_helper_uses_coordinator_function(monkeypatch, tmp_path):
    """Single-source-of-truth: the startup sweep helper must reuse
    `_enforce_flag_combination` from the coordinator — same binding identity
    rule as the runtime POST validator."""
    import app.api.routes_admin_runtime_flags as route_mod
    import app.services.dhl_clearance_coordinator as coord_mod
    # The function imported at module scope must be the same object.
    assert route_mod._enforce_flag_combination is coord_mod._enforce_flag_combination
    # Sanity: the startup helper is exported for direct testing.
    assert hasattr(route_mod, "_enforce_startup_combined_states")


# ── Per-phase concurrency lock (Issue #48) ───────────────────────────────────

def _drain_phase_locks():
    """Reset all phase locks to released state. Called between tests that
    deliberately leave a lock held to verify timeout behaviour."""
    from app.api.routes_admin_runtime_flags import _PHASE_LOCKS
    for lock in _PHASE_LOCKS.values():
        # Release if held; ignore if not held.
        try:
            lock.release()
        except RuntimeError:
            pass


@pytest.fixture(autouse=True)
def _release_phase_locks_after_test():
    """Autouse: release any phase lock left held by a test. Belt-and-braces
    cleanup; with the context-manager design every test SHOULD release on
    its own, but timeout-simulation tests deliberately hold a lock."""
    yield
    _drain_phase_locks()


def test_lock_single_post_succeeds_without_contention(client):
    """Baseline: a single POST acquires + releases the lock and returns 200."""
    _set_phase_pair("p2", shadow=True, live=False)
    r = _post(client, "dhl_selfclearance_p2_live_enabled", True)
    assert r.status_code == 200, r.json()


@pytest.mark.parametrize("phase", ["p2", "p3", "p4", "p5"])
def test_lock_two_concurrent_posts_same_phase_one_returns_503(monkeypatch, tmp_path, phase):
    """Operator scenario: two admins flip flags on the SAME phase
    simultaneously. With per-phase lock, one wins; the other times out
    on lock acquisition and returns 503 LOCK_ACQUISITION_TIMEOUT."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key-secret")
    # Tighten timeout so the test runs fast — patch module constant.
    import app.api.routes_admin_runtime_flags as route_mod
    monkeypatch.setattr(route_mod, "LOCK_ACQUISITION_TIMEOUT_SECONDS", 0.5)

    _set_phase_pair(phase, shadow=True, live=False)

    # Hold the phase lock externally to simulate a concurrent in-flight POST.
    held = route_mod._PHASE_LOCKS[phase]
    assert held.acquire(blocking=True), "test setup: could not acquire phase lock"

    try:
        from app.main import app
        c = TestClient(app)
        r = c.post(
            _URL,
            headers=_AUTH,
            json={"flag_name": f"dhl_selfclearance_{phase}_live_enabled",
                  "value": True, "actor": "test"},
        )
        assert r.status_code == 503
        body = r.json()["detail"]
        assert body["error_code"] == "LOCK_ACQUISITION_TIMEOUT"
        assert phase in body["detail"]
        assert "retry" in body["hint"].lower()
    finally:
        held.release()


def test_lock_two_concurrent_posts_different_phases_both_succeed(monkeypatch, tmp_path):
    """Per-phase isolation: a held P2 lock does NOT block a P3 POST."""
    import app.api.routes_admin_runtime_flags as route_mod
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key-secret")
    monkeypatch.setattr(route_mod, "LOCK_ACQUISITION_TIMEOUT_SECONDS", 0.5)

    # Issue #49: P3 live requires P2 live. Seed P2 LIVE before holding lock.
    _set_phase_pair("p2", shadow=True, live=True)
    _set_phase_pair("p3", shadow=True, live=False)

    p2_lock = route_mod._PHASE_LOCKS["p2"]
    assert p2_lock.acquire(blocking=True)

    try:
        from app.main import app
        c = TestClient(app)
        # P3 POST should succeed — its lock is independent.
        r = c.post(
            _URL,
            headers=_AUTH,
            json={"flag_name": "dhl_selfclearance_p3_live_enabled",
                  "value": True, "actor": "test"},
        )
        assert r.status_code == 200, r.json()
    finally:
        p2_lock.release()


def test_lock_released_after_successful_post(client, monkeypatch):
    """After a 200 POST, the per-phase lock must be released so subsequent
    POSTs against the same phase succeed without waiting."""
    _set_phase_pair("p2", shadow=True, live=False)

    r1 = _post(client, "dhl_selfclearance_p2_live_enabled", True)
    assert r1.status_code == 200

    # Second POST — lock must be free.
    r2 = _post(client, "dhl_selfclearance_p2_live_enabled", False)
    assert r2.status_code == 200


def test_lock_released_after_rejected_forbidden_post(client):
    """A FORBIDDEN-rejection POST must still release the lock — exception
    path cleanup discipline."""
    _set_phase_pair("p3", shadow=True, live=True)

    # This POST is rejected with 400 FORBIDDEN (would yield (False, True))
    r1 = _post(client, "dhl_selfclearance_p3_shadow_mode", False)
    assert r1.status_code == 400

    # Lock must be released — subsequent legal POST succeeds.
    r2 = _post(client, "dhl_selfclearance_p3_live_enabled", False)
    assert r2.status_code == 200


def test_lock_released_after_unknown_flag_posts_nothing(client):
    """An UNKNOWN_FLAG rejection happens BEFORE the lock acquisition path
    (because _coerce_and_validate runs first). Verify the lock state for
    valid phases remains untouched after such a rejection."""
    import app.api.routes_admin_runtime_flags as route_mod

    r = _post(client, "not_a_flag", True)
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "UNKNOWN_FLAG"

    # All 4 phase locks must still be acquirable (not held).
    for phase in ("p2", "p3", "p4", "p5"):
        lock = route_mod._PHASE_LOCKS[phase]
        assert lock.acquire(blocking=False), f"{phase} lock leaked after UNKNOWN_FLAG"
        lock.release()


def test_get_endpoint_not_blocked_by_held_post_lock(monkeypatch, tmp_path):
    """GET is read-only — the operator can inspect state even while another
    operator holds a per-phase lock during a POST."""
    import app.api.routes_admin_runtime_flags as route_mod
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key-secret")

    p2_lock = route_mod._PHASE_LOCKS["p2"]
    assert p2_lock.acquire(blocking=True)

    try:
        from app.main import app
        c = TestClient(app)
        r = c.get(_URL, headers=_AUTH)
        assert r.status_code == 200
        # Sanity: response shape preserved.
        assert "dhl_selfclearance_p2_live_enabled" in r.json()
        assert "_phases" in r.json()
    finally:
        p2_lock.release()


def test_lock_timeout_audited(monkeypatch, tmp_path):
    """Lock timeouts must produce an `admin_runtime_flag_lock_timeout`
    audit entry for forensic reconstruction of contention patterns."""
    import json as _json
    import app.api.routes_admin_runtime_flags as route_mod

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key-secret")
    monkeypatch.setattr(route_mod, "LOCK_ACQUISITION_TIMEOUT_SECONDS", 0.3)

    _set_phase_pair("p4", shadow=True, live=False)
    p4_lock = route_mod._PHASE_LOCKS["p4"]
    assert p4_lock.acquire(blocking=True)

    try:
        from app.main import app
        c = TestClient(app)
        r = c.post(
            _URL, headers=_AUTH,
            json={"flag_name": "dhl_selfclearance_p4_live_enabled",
                  "value": True, "actor": "tejal"},
        )
        assert r.status_code == 503

        audit_path = tmp_path / "dhl_selfclearance_runtime_flags_audit.jsonl"
        lines = [_json.loads(l) for l in audit_path.read_text().splitlines() if l.strip()]
        timeouts = [e for e in lines if e.get("event") == "admin_runtime_flag_lock_timeout"]
        assert len(timeouts) == 1
        assert timeouts[0]["phase"] == "p4"
        assert timeouts[0]["actor"] == "tejal"
        assert timeouts[0]["timeout_seconds"] == 0.3
    finally:
        p4_lock.release()


def test_lock_acquisition_and_release_audited(client, tmp_path):
    """Successful POSTs produce both `lock_acquired` and `lock_released`
    audit entries with held_seconds for forensic completeness."""
    import json as _json

    # Issue #49: P5 live requires P4 live (which requires P3, P2). Seed chain.
    _set_phase_pair("p2", shadow=True, live=True)
    _set_phase_pair("p3", shadow=True, live=True)
    _set_phase_pair("p4", shadow=True, live=True)
    _set_phase_pair("p5", shadow=True, live=False)
    r = _post(client, "dhl_selfclearance_p5_live_enabled", True)
    assert r.status_code == 200

    audit_path = tmp_path / "dhl_selfclearance_runtime_flags_audit.jsonl"
    lines = [_json.loads(l) for l in audit_path.read_text().splitlines() if l.strip()]

    acquired = [e for e in lines if e.get("event") == "admin_runtime_flag_lock_acquired"]
    released = [e for e in lines if e.get("event") == "admin_runtime_flag_lock_released"]
    assert len(acquired) == 1 and acquired[0]["phase"] == "p5"
    assert len(released) == 1 and released[0]["phase"] == "p5"
    assert "held_seconds" in released[0]
    assert released[0]["held_seconds"] >= 0


def test_lock_per_phase_isolation(monkeypatch, tmp_path):
    """Holding the P2 lock does not affect P3/P4/P5 locks (and vice versa)."""
    import app.api.routes_admin_runtime_flags as route_mod
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key-secret")

    p2 = route_mod._PHASE_LOCKS["p2"]
    p3 = route_mod._PHASE_LOCKS["p3"]
    p4 = route_mod._PHASE_LOCKS["p4"]
    p5 = route_mod._PHASE_LOCKS["p5"]

    assert p2.acquire(blocking=True)
    try:
        # Other 3 must remain acquirable while p2 is held.
        assert p3.acquire(blocking=False)
        p3.release()
        assert p4.acquire(blocking=False)
        p4.release()
        assert p5.acquire(blocking=False)
        p5.release()
    finally:
        p2.release()


def test_lock_not_acquired_for_non_phase_pair_flags(monkeypatch, tmp_path):
    """Flags like `tracker_paused`, `classifier_min_*`, `value_threshold_usd`
    do NOT participate in ADR-018's combined-state invariant. They MUST NOT
    acquire any phase lock — verified by attempting POST while ALL 4 phase
    locks are held externally."""
    import app.api.routes_admin_runtime_flags as route_mod
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key-secret")

    # Hold all 4 phase locks.
    for phase in ("p2", "p3", "p4", "p5"):
        assert route_mod._PHASE_LOCKS[phase].acquire(blocking=True)

    try:
        from app.main import app
        c = TestClient(app)
        # Non-phase-pair flag POSTs must succeed — they bypass the lock.
        for flag, value in [
            ("dhl_selfclearance_p3_tracker_paused",       True),
            ("dhl_selfclearance_p4_classifier_min_confidence", 0.9),
            ("dhl_selfclearance_followup_working_interval_sec", 600),
            ("dhl_selfclearance_value_threshold_usd",      2500),
        ]:
            r = c.post(
                _URL, headers=_AUTH,
                json={"flag_name": flag, "value": value, "actor": "test"},
            )
            assert r.status_code == 200, (
                f"non-pair flag {flag} should bypass lock; got {r.status_code} {r.json()}"
            )
    finally:
        for phase in ("p2", "p3", "p4", "p5"):
            try:
                route_mod._PHASE_LOCKS[phase].release()
            except RuntimeError:
                pass


def test_lock_acquire_phase_lock_helper_no_op_for_none_phase():
    """Direct test of the context manager — None phase yields without
    acquiring any lock."""
    from app.api.routes_admin_runtime_flags import _acquire_phase_lock, _PHASE_LOCKS

    # None phase is a no-op — must not touch any lock.
    with _acquire_phase_lock(None, flag_name="some_flag", actor="test"):
        # Inside the no-op context, all locks are still acquirable.
        for phase, lock in _PHASE_LOCKS.items():
            assert lock.acquire(blocking=False), f"{phase} lock unexpectedly held"
            lock.release()


def test_lock_acquire_phase_lock_helper_unknown_phase_no_op():
    """Defensive: an unknown phase identifier (e.g. 'p99') must be a no-op
    rather than KeyError."""
    from app.api.routes_admin_runtime_flags import _acquire_phase_lock

    with _acquire_phase_lock("p99", flag_name="hypothetical", actor="test"):
        pass  # no exception expected


def test_boot_replay_does_not_acquire_phase_lock(monkeypatch, tmp_path):
    """Boot-replay runs single-threaded before the route is mounted. It
    must NOT contend for phase locks. Verified by holding all 4 locks
    externally and confirming `load_persisted_flags_into_settings`
    completes without timing out."""
    import json as _json
    import app.api.routes_admin_runtime_flags as route_mod

    monkeypatch.setattr(settings, "storage_root", tmp_path)

    store = {
        "dhl_selfclearance_p2_shadow_mode":  True,
        "dhl_selfclearance_p3_shadow_mode":  True,
    }
    (tmp_path / "dhl_selfclearance_runtime_flags.json").write_text(_json.dumps(store))

    # Hold all 4 phase locks — boot-replay must ignore them.
    for phase in ("p2", "p3", "p4", "p5"):
        assert route_mod._PHASE_LOCKS[phase].acquire(blocking=True)

    try:
        from app.api.routes_admin_runtime_flags import load_persisted_flags_into_settings
        # Time-bound the call so a regression that adds locking would deadlock
        # rather than block forever.
        import threading as _t
        result_box = {}

        def _runner():
            try:
                result_box["applied"] = load_persisted_flags_into_settings()
            except Exception as e:  # pragma: no cover
                result_box["error"] = e

        thread = _t.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join(timeout=2.0)
        assert not thread.is_alive(), "boot replay deadlocked on a phase lock"
        assert "error" not in result_box
        assert "applied" in result_box
    finally:
        for phase in ("p2", "p3", "p4", "p5"):
            try:
                route_mod._PHASE_LOCKS[phase].release()
            except RuntimeError:
                pass


def test_lock_default_timeout_is_5_seconds():
    """Operator-visible constant — timeout SHOULD be 5s by default per
    Issue #48 specification."""
    from app.api.routes_admin_runtime_flags import LOCK_ACQUISITION_TIMEOUT_SECONDS
    assert LOCK_ACQUISITION_TIMEOUT_SECONDS == 5.0


def test_lock_count_is_exactly_four():
    """Per Issue #48 design: exactly 4 locks (one per P2/P3/P4/P5).
    Adding more phases later requires updating both `_ALLOWED_FLAGS` AND
    `_PHASE_LOCKS` AND `_PHASE_PAIR_RE` — same coupling rule documented
    near the regex."""
    from app.api.routes_admin_runtime_flags import _PHASE_LOCKS
    assert set(_PHASE_LOCKS.keys()) == {"p2", "p3", "p4", "p5"}
    assert len(_PHASE_LOCKS) == 4


def test_lock_timeout_writes_both_lifecycle_and_rejection_audit_entries(monkeypatch, tmp_path):
    """Per gap-hunter F9 (LOW): dual audit-write on lock-timeout is
    intentional. The lifecycle event (`admin_runtime_flag_lock_timeout`)
    captures the lock-level forensic context; the rejection event
    (`admin_runtime_flag_rejected` with error_code=LOCK_ACQUISITION_TIMEOUT)
    categorises it alongside other 4xx rejections. A future refactor that
    "deduplicates" these would silently drop forensic redundancy.

    This test guards the dual-write contract."""
    import json as _json
    import app.api.routes_admin_runtime_flags as route_mod

    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "api_key", "test-key-secret")
    monkeypatch.setattr(route_mod, "LOCK_ACQUISITION_TIMEOUT_SECONDS", 0.2)

    _set_phase_pair("p3", shadow=True, live=False)
    p3_lock = route_mod._PHASE_LOCKS["p3"]
    assert p3_lock.acquire(blocking=True)

    try:
        from app.main import app
        c = TestClient(app)
        r = c.post(
            _URL, headers=_AUTH,
            json={"flag_name": "dhl_selfclearance_p3_live_enabled",
                  "value": True, "actor": "amit"},
        )
        assert r.status_code == 503

        audit_path = tmp_path / "dhl_selfclearance_runtime_flags_audit.jsonl"
        lines = [_json.loads(l) for l in audit_path.read_text().splitlines() if l.strip()]

        timeouts = [e for e in lines if e.get("event") == "admin_runtime_flag_lock_timeout"]
        rejections = [
            e for e in lines
            if e.get("event") == "admin_runtime_flag_rejected"
            and e.get("error_code") == "LOCK_ACQUISITION_TIMEOUT"
        ]
        assert len(timeouts)   == 1, f"expected 1 lifecycle timeout entry, got {timeouts}"
        assert len(rejections) == 1, f"expected 1 rejection entry, got {rejections}"
    finally:
        p3_lock.release()


def test_lock_released_after_store_write_failure(client, monkeypatch):
    """Per testing-verification recommendation: STORE_WRITE_FAILED path
    raises HTTPException(500) inside the `with _acquire_phase_lock` block.
    The `finally` must release the lock; otherwise the next POST against
    the same phase would time out forever."""
    import app.api.routes_admin_runtime_flags as route_mod

    _set_phase_pair("p2", shadow=True, live=False)

    # Inject _save_store failure via monkeypatch.
    def _failing_save_store(flag_map):
        raise OSError("simulated disk full")

    monkeypatch.setattr(route_mod, "_save_store", _failing_save_store)

    r = _post(client, "dhl_selfclearance_p2_live_enabled", True)
    assert r.status_code == 500
    assert r.json()["detail"]["error_code"] == "STORE_WRITE_FAILED"

    # Settings rolled back.
    assert getattr(settings, "dhl_selfclearance_p2_live_enabled") is False

    # Lock released — next acquire must succeed without blocking.
    p2 = route_mod._PHASE_LOCKS["p2"]
    assert p2.acquire(blocking=False), (
        "p2 lock leaked after STORE_WRITE_FAILED — finally block did not release"
    )
    p2.release()


def test_lock_held_seconds_is_non_negative_under_clock_step(client):
    """Lifecycle audit's `held_seconds` field uses time.monotonic() so it
    is robust against NTP step-back. Under any wall-clock manipulation the
    field must remain non-negative."""
    import json as _json

    # Issue #49: P4 live requires P3 live (which requires P2). Seed chain.
    _set_phase_pair("p2", shadow=True, live=True)
    _set_phase_pair("p3", shadow=True, live=True)
    _set_phase_pair("p4", shadow=True, live=False)
    r = _post(client, "dhl_selfclearance_p4_live_enabled", True)
    assert r.status_code == 200

    audit_path = settings.storage_root / "dhl_selfclearance_runtime_flags_audit.jsonl"
    lines = [_json.loads(l) for l in audit_path.read_text().splitlines() if l.strip()]
    released = [e for e in lines if e.get("event") == "admin_runtime_flag_lock_released"]
    assert len(released) == 1
    assert released[0]["held_seconds"] >= 0
