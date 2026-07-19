"""Docs-governance validator for the single-task lifecycle model + Resume Rule.

Static string checks over the governance documents. NO app imports, no network,
no DB — this is a pure text-consistency pin so the 8-state lifecycle and the
resumable-EXECUTION_BLOCKED Resume Rule cannot silently drift, fork into a
competing enum, or leak into the `.campaigns/` branch-write state machine.

Authority split under test:
  - Lifecycle state model .............. .claude/TASK_EXECUTION_PROTOCOL.md
  - Resume Rule / HOLD semantics ....... docs/governance/anti-hold-and-completion.md §7
  - Live task instance / checkpoint .... .claude/memory/TASK_STATE.md
  - Thin pointers ...................... CLAUDE.md, .engineering-os/00_ENGINEERING_CONSTITUTION.md §13.F
  - UNCHANGED (separate axis) .......... .campaigns/{schema.json,policies.json}
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# service/tests/<file> -> parents[2] == repo root
REPO = Path(__file__).resolve().parents[2]

PROTOCOL = REPO / ".claude" / "TASK_EXECUTION_PROTOCOL.md"
ANTIHOLD = REPO / "docs" / "governance" / "anti-hold-and-completion.md"
TASKSTATE = REPO / ".claude" / "memory" / "TASK_STATE.md"
CLAUDEMD = REPO / "CLAUDE.md"
OS_CONST = REPO / ".engineering-os" / "00_ENGINEERING_CONSTITUTION.md"
CAMPAIGN_SCHEMA = REPO / ".campaigns" / "schema.json"
CAMPAIGN_POLICIES = REPO / ".campaigns" / "policies.json"

LIFECYCLE_STATES = [
    "DISCOVERY",
    "PLANNING",
    "IMPLEMENTING",
    "VALIDATING",
    "EXECUTION_BLOCKED",
    "READY_FOR_PR",
    "UNDER_REVIEW",
    "COMPLETE",
]

# States that belong ONLY to the campaign branch-write registry (the other axis).
# They must NOT appear as single-task lifecycle states, and the lifecycle-only
# states must NOT be injected into the registry enum.
REGISTRY_ONLY_STATES = [
    "READY_FOR_REBASE",
    "REBASED_PENDING_REVIEW",
    "PR_OPEN",
    "MERGED",
    "FROZEN",
    "LOCKED",
    "DEPLOYING",
    "ARCHIVED",
]


def _read(p: Path) -> str:
    assert p.exists(), f"governance file missing: {p}"
    return p.read_text(encoding="utf-8")


def test_lifecycle_model_defined_once_in_protocol():
    text = _read(PROTOCOL)
    for state in LIFECYCLE_STATES:
        assert state in text, f"{state} missing from lifecycle authority {PROTOCOL.name}"
    assert "Lifecycle states (canonical single-task axis)" in text
    # Canonical table must be complete: NOT_STARTED is defined here, not only in mirrors.
    assert "NOT_STARTED" in text, "canonical lifecycle table missing NOT_STARTED (pre-start)"
    # Phase 1 must set the canonical state, not the deprecated IN_PROGRESS spelling.
    assert "to `DISCOVERY`" in text, "Phase 1 must set TASK_STATE to DISCOVERY, not IN_PROGRESS"
    # The two-axis separation must be stated explicitly.
    assert "separate axis" in text
    assert "derives mechanically from" in text
    # Resumable, not restartable — pointer to the authority for the full rule.
    assert "resumable, not restartable" in text.lower()
    assert "anti-hold-and-completion.md" in text


def test_resume_rule_defined_once_in_antihold():
    text = _read(ANTIHOLD)
    assert "## 7. EXECUTION_BLOCKED and the Resume Rule" in text
    assert "resumable, not restartable" in text.lower()
    # The six bounded checks must all be present.
    for token in [
        "Current branch == recorded branch",
        "Current HEAD == recorded HEAD",
        "preserved_diff_hash",
        "authority owner still canonical",
        "dependency now available",
        "conflicting campaign writer",
    ]:
        assert token in text, f"Resume Rule missing check: {token!r}"
    # Prohibitions: no unrestricted rediscovery, no repeated retries, no silent rebase.
    assert "earliest invalid checkpoint" in text
    assert "do not re-run discovery" in text.lower() or "do not restart" in text.lower()
    assert "NO_REPEATED_RETRIES" in text or "retry the execution repeatedly" in text
    for verb in ["rebase", "reset", "cherry-pick"]:
        assert verb in text, f"no-silent-{verb} rule missing"
    # Operator ruling triggers.
    assert "operator ruling" in text.lower()
    # Subordination — weakens no gate.
    assert "weakens no gate" in text or "adds no hook and weakens no gate" in text


def test_antihold_status_values_migrated_to_lifecycle():
    text = _read(ANTIHOLD)
    for state in LIFECYCLE_STATES:
        assert state in text, f"{state} missing from anti-hold status values"
    # EXECUTION_BLOCKED is documented as the resumable refinement of BLOCKED-HOLD.
    assert "refinement of the former `BLOCKED-HOLD`" in text


def test_taskstate_has_lifecycle_enum_and_checkpoint_block():
    text = _read(TASKSTATE)
    for state in LIFECYCLE_STATES:
        assert state in text, f"{state} missing from TASK_STATE.md status enum"
    # Required checkpoint keys for a resumable block.
    for key in [
        "suspended_from",
        "recorded_branch",
        "recorded_head",
        "next_command",
        "retry_policy",
        "NO_REPEATED_RETRIES",
    ]:
        assert key in text, f"checkpoint template missing key: {key}"


def test_thin_pointers_present_and_resolve():
    claude = _read(CLAUDEMD)
    assert "EXECUTION_BLOCKED" in claude
    assert "resumable, not restartable" in claude.lower()
    assert "anti-hold-and-completion.md" in claude

    os_const = _read(OS_CONST)
    assert "Resumable exit (EXECUTION_BLOCKED)" in os_const
    assert "anti-hold-and-completion.md" in os_const
    # OS stays subordinate — it must NOT redefine the six checks itself.
    assert "Current branch == recorded branch" not in os_const


def test_campaign_branch_write_axis_unchanged():
    """The `.campaigns/` registry enum must not gain lifecycle-only states, and the
    lifecycle model must not adopt registry-only branch-write states as its own."""
    policies = json.loads(_read(CAMPAIGN_POLICIES))
    enum = policies.get("state_enum", [])
    # Registry enum unchanged: exactly the 9 branch-write states, no lifecycle leakage.
    assert "EXECUTION_BLOCKED" not in enum
    assert "READY_FOR_PR" not in enum
    assert "UNDER_REVIEW" not in enum
    assert set(enum) == {"IN_PROGRESS", *REGISTRY_ONLY_STATES}, (
        f"campaign registry state_enum changed unexpectedly: {enum}"
    )
    # Schema likewise must not reference the lifecycle-only states.
    schema_text = _read(CAMPAIGN_SCHEMA)
    assert "EXECUTION_BLOCKED" not in schema_text


def test_registry_only_states_not_claimed_as_lifecycle_states():
    """Lifecycle authority must not silently absorb the branch-write vocabulary
    (mapping references are allowed; adopting them as lifecycle STATES is not)."""
    assert set(LIFECYCLE_STATES).isdisjoint(set(REGISTRY_ONLY_STATES))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
