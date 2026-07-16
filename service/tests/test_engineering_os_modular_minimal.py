"""
test_engineering_os_modular_minimal.py — EJ Engineering OS v1.4 (MODULAR-MINIMAL) governance pins.

Static doc-content / command-registration / no-duplicate-authority checks only, following the
`test_ai_token_governance.py` marker pattern (read a governance doc, assert required markers).

No test here simulates Claude Code runtime behaviour or native `/loop` / `/goal` internals — it
pins repository-owned policy text and the absence of any project command that shadows native
authority. §13 is governance over the native `/loop` (repetition/monitoring) and `/goal`
(convergence) authorities; there is no project loop command.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINEERING_OS = REPO_ROOT / ".engineering-os"
COMMANDS = REPO_ROOT / ".claude" / "commands"
SKILLS = REPO_ROOT / ".claude" / "skills"
CONSTITUTION = ENGINEERING_OS / "00_ENGINEERING_CONSTITUTION.md"
KNOWLEDGE_ENGINE = ENGINEERING_OS / "10_KNOWLEDGE_ENGINE.md"
VERSION_HISTORY = ENGINEERING_OS / "VERSION_HISTORY.md"
COMMAND_REGISTRY = COMMANDS / "COMMAND_REGISTRY.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _flat(path: Path) -> str:
    """Whitespace-normalized read — for markers that may wrap across source line breaks."""
    return re.sub(r"\s+", " ", _read(path))


def _skill_exists(name: str) -> bool:
    """A project skill is <name>.md or <name>/SKILL.md under .claude/skills/."""
    return (SKILLS / f"{name}.md").exists() or (SKILLS / name / "SKILL.md").exists()


# ── 1. Canonical documents exist ─────────────────────────────────────────────

def test_constitution_exists() -> None:
    assert CONSTITUTION.exists()


def test_version_history_exists() -> None:
    assert VERSION_HISTORY.exists()


# ── 2. v1.4 pointer consistent across all owners (req. 14) ───────────────────

def test_constitution_banner_names_v14() -> None:
    assert "v1.4" in _read(CONSTITUTION)


def test_version_history_names_v14() -> None:
    assert "v1.4" in _read(VERSION_HISTORY)


def test_claude_md_pointer_names_v14() -> None:
    assert "EJ Engineering OS v1.4" in _read(CLAUDE_MD)


def test_version_pointer_consistent_no_stale_v13_active() -> None:
    # §6 (constitution) and §4.2 (knowledge engine) both own the "active canonical version"
    # pointer; neither may still declare v1.3 active after the v1.4 bump.
    for path in (CONSTITUTION, KNOWLEDGE_ENGINE):
        flat = _flat(path)
        assert "active canonical version is **v1.4**" in flat, f"{path.name} must name v1.4 active"
        assert "active canonical version is **v1.3**" not in flat, f"{path.name} still names v1.3 active"


def test_amendment_gate_advanced_to_v15() -> None:
    assert "no v1.5 change" in _flat(KNOWLEDGE_ENGINE).lower()


# ── 3. §11 Evidence Contract remains armed (req. 12) ─────────────────────────

def test_evidence_contract_tiers_present() -> None:
    txt = _read(CONSTITUTION)
    for marker in ("Evidence Contract", "VERIFIED", "PRIOR EVIDENCE", "UNVERIFIED"):
        assert marker in txt, f"00_CONSTITUTION missing §11 marker: {marker!r}"


# ── 4. §12 MODULAR-MINIMAL + Anti-Bloat remain armed (req. 13) ───────────────

def test_modular_minimal_principle_named() -> None:
    assert "MODULAR-MINIMAL" in _read(CONSTITUTION)


def test_anti_bloat_gate_present() -> None:
    assert "Anti-Bloat" in _read(CONSTITUTION)


def test_modernization_not_default() -> None:
    assert "Modernization is not a default mode" in _flat(CONSTITUTION)


# ── 5. §13 governance over native /loop + /goal (req. 7–11) ──────────────────

def test_s13_named_as_governance_over_native() -> None:
    # §13 heading routes through native authorities, not a bespoke loop command.
    flat = _flat(CONSTITUTION)
    assert "Bounded Engineering Loop" in flat
    assert "governance over native `/loop` and `/goal`" in flat


def test_s13_goal_is_convergence_authority() -> None:  # req. 7
    flat = _flat(CONSTITUTION)
    assert "`/goal`" in flat
    assert "convergence" in flat.lower()
    assert "independent convergence evaluation" in flat


def test_s13_loop_is_repetition_monitoring_authority() -> None:  # req. 8
    flat = _flat(CONSTITUTION)
    assert "`/loop`" in flat
    assert "monitoring" in flat.lower()


def test_s13_os_supplies_governance_not_duplicate_execution() -> None:  # req. 9
    flat = _flat(CONSTITUTION)
    assert "does **not** own loop execution" in flat
    assert "does **not** reimplement, rename, wrap, shadow, or clone" in flat


def test_s13_includes_required_governance_inputs() -> None:  # req. 10 (inputs)
    txt = _read(CONSTITUTION)
    for marker in (
        "OBJECTIVE", "TASK_CLASSIFICATION", "CANONICAL_AUTHORITY", "ALLOWED_SCOPE",
        "FORBIDDEN_SCOPE", "SUCCESS_EVIDENCE", "VERIFY_CMD", "ITERATION_CAP",
        "STOP_CONDITIONS", "HOLD_CONDITIONS", "OPERATOR_GATES", "ROLLBACK_POINT",
    ):
        assert marker in txt, f"§13 missing required governance input: {marker!r}"


def test_s13_exit_states_present() -> None:  # req. 10 (exit states)
    txt = _read(CONSTITUTION)
    for marker in ("CONVERGED", "CAP_REACHED", "HOLD_TRIGGERED", "OPERATOR_GATE", "VERIFICATION_FAILED"):
        assert marker in txt, f"§13 missing exit state: {marker!r}"


def test_s13_references_anti_hold_for_operator_gates() -> None:
    # Operator-gate/HOLD conditions are owned by CLAUDE.md ANTI-HOLD, not re-invented in §13.
    assert "ANTI-HOLD" in _read(CONSTITUTION)


def test_s13_discloses_advisory_vs_mechanical_boundary() -> None:  # req. 11
    flat = _flat(CONSTITUTION)
    assert "not mechanically enforced" in flat
    assert "Do not describe advisory prompt rules as mechanically enforced" in flat


# ── 6. No duplicate loop/goal authority, no shadowing (req. 1–6, 15) ─────────

def test_no_pz_loop_command_file() -> None:  # req. 1
    assert not (COMMANDS / "pz-loop.md").exists()


def test_pz_loop_not_registered() -> None:  # req. 2
    assert "/pz-loop" not in _read(COMMAND_REGISTRY)


def test_no_project_loop_command() -> None:  # req. 3
    assert not (COMMANDS / "loop.md").exists()


def test_no_project_goal_command() -> None:  # req. 4
    assert not (COMMANDS / "goal.md").exists()


def test_no_project_skill_shadows_loop() -> None:  # req. 5
    assert not _skill_exists("loop")


def test_no_project_skill_shadows_goal() -> None:  # req. 6
    assert not _skill_exists("goal")


def test_pz_loop_zero_refs_in_active_surfaces() -> None:  # req. 15
    # Active authority surfaces must carry no /pz-loop reference. VERSION_HISTORY.md is the one
    # deliberate exception — it documents the removal as the durable audit trail (§9/§10).
    for path in (CONSTITUTION, CLAUDE_MD, COMMAND_REGISTRY):
        assert "pz-loop" not in _read(path), f"{path.name} still references pz-loop"


def test_version_history_pz_loop_framed_as_removal() -> None:
    # VERSION_HISTORY is the deliberate audit-trail exception: any pz-loop mention there must be
    # framed as removal/correction, never as active authorization.
    flat = _flat(VERSION_HISTORY)
    assert "pz-loop" in flat, "VERSION_HISTORY should retain the removal audit trail"
    assert "Duplicate-authority correction note" in flat
    assert "was removed" in flat or "it was removed" in flat


# ── 7. Registry integrity (req. 16) + single OS authority ────────────────────

def test_registry_count_matches_actual_commands() -> None:  # req. 16
    # Actual command files = every .md in .claude/commands/ except the registry itself.
    actual = sorted(p.name for p in COMMANDS.glob("*.md") if p.name != "COMMAND_REGISTRY.md")
    assert len(actual) == 14, f"expected 14 command files, found {len(actual)}: {actual}"
    reg = _read(COMMAND_REGISTRY)
    assert "14 project commands" in reg
    assert "15 project commands" not in reg and "9 project commands" not in reg
    # Quick-matrix rows (lines beginning "| `/") must equal the command count.
    matrix_rows = sum(1 for line in reg.splitlines() if line.startswith("| `/"))
    assert matrix_rows == 14, f"expected 14 matrix rows, found {matrix_rows}"


def test_registry_backfills_preserved() -> None:
    reg = _read(COMMAND_REGISTRY)
    for cmd in ("/authority-census", "/context-lite", "/context-pr", "/context-task", "/implement-slice"):
        assert cmd in reg, f"legitimate backfilled command missing from registry: {cmd}"


def test_exactly_one_constitution_file() -> None:
    matches = sorted(ENGINEERING_OS.glob("*CONSTITUTION*.md"))
    assert len(matches) == 1, f"expected exactly one constitution file, found: {matches}"
