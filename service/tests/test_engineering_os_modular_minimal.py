"""
test_engineering_os_modular_minimal.py — EJ Engineering OS v1.4 (MODULAR-MINIMAL) governance pins.

Static doc-content / command-registration / no-duplicate-authority checks only, following the
`test_ai_token_governance.py` marker pattern (read a governance doc, assert required markers).
No test here simulates agent runtime behaviour — the behavioural asks (a read-only task does not
start a loop, the iteration cap stops execution, an operator gate stops a mutation) are encoded
as the three worked examples inside `00 §13`, not as fake automated assertions.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINEERING_OS = REPO_ROOT / ".engineering-os"
COMMANDS = REPO_ROOT / ".claude" / "commands"
CONSTITUTION = ENGINEERING_OS / "00_ENGINEERING_CONSTITUTION.md"
KNOWLEDGE_ENGINE = ENGINEERING_OS / "10_KNOWLEDGE_ENGINE.md"
VERSION_HISTORY = ENGINEERING_OS / "VERSION_HISTORY.md"
COMMAND_REGISTRY = COMMANDS / "COMMAND_REGISTRY.md"
PZ_LOOP = COMMANDS / "pz-loop.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _flat(path: Path) -> str:
    """Whitespace-normalized read — for markers that may wrap across source line breaks."""
    return re.sub(r"\s+", " ", _read(path))


# ── 1. Canonical documents exist ─────────────────────────────────────────────

def test_constitution_exists() -> None:
    assert CONSTITUTION.exists()


def test_version_history_exists() -> None:
    assert VERSION_HISTORY.exists()


# ── 2. v1.4 version stamped in all three surfaces ────────────────────────────

def test_constitution_banner_names_v14() -> None:
    assert "v1.4" in _read(CONSTITUTION)


def test_version_history_names_v14() -> None:
    assert "v1.4" in _read(VERSION_HISTORY)


def test_claude_md_pointer_names_v14() -> None:
    txt = _read(CLAUDE_MD)
    assert "EJ Engineering OS v1.4" in txt


def test_version_pointer_consistent_no_stale_v13_active() -> None:
    # §6 (constitution) and §4.2 (knowledge engine) both own the "active canonical version"
    # pointer; neither may still declare v1.3 active after the v1.4 bump.
    for path in (CONSTITUTION, KNOWLEDGE_ENGINE):
        flat = _flat(path)
        assert "active canonical version is **v1.4**" in flat, f"{path.name} must name v1.4 active"
        assert "active canonical version is **v1.3**" not in flat, f"{path.name} still names v1.3 active"


def test_amendment_gate_advanced_to_v15() -> None:
    # After ratifying v1.4, the evidence gate governs v1.5+ (not "no v1.4 change").
    assert "no v1.5 change" in _flat(KNOWLEDGE_ENGINE).lower()


# ── 3. §11 Evidence Contract markers ─────────────────────────────────────────

def test_evidence_contract_tiers_present() -> None:
    txt = _read(CONSTITUTION)
    for marker in ("Evidence Contract", "VERIFIED", "PRIOR EVIDENCE", "UNVERIFIED"):
        assert marker in txt, f"00_CONSTITUTION missing §11 marker: {marker!r}"


# ── 4. §12 MODULAR-MINIMAL + Anti-Bloat markers ──────────────────────────────

def test_modular_minimal_principle_named() -> None:
    assert "MODULAR-MINIMAL" in _read(CONSTITUTION)


def test_anti_bloat_gate_present() -> None:
    assert "Anti-Bloat" in _read(CONSTITUTION)


def test_modernization_not_default() -> None:
    # §12 must state modernization is not a default execution mode.
    assert "Modernization is not a default mode" in _flat(CONSTITUTION)


# ── 5. §13 Bounded Engineering Loop markers ──────────────────────────────────

def test_bounded_loop_named() -> None:
    assert "Bounded Engineering Loop" in _read(CONSTITUTION)


def test_bounded_loop_iteration_cap_present() -> None:
    assert "ITERATION_CAP" in _read(CONSTITUTION)


def test_bounded_loop_default_cap_is_five() -> None:
    assert "default 5" in _read(CONSTITUTION).lower()


def test_bounded_loop_stop_conditions_required() -> None:
    assert "STOP_CONDITIONS" in _read(CONSTITUTION)


def test_bounded_loop_exit_states_present() -> None:
    txt = _read(CONSTITUTION)
    for marker in ("CONVERGED", "CAP_REACHED", "HOLD_TRIGGERED"):
        assert marker in txt, f"00_CONSTITUTION missing §13 exit-state: {marker!r}"


def test_bounded_loop_names_pz_loop_entry_point() -> None:
    assert "pz-loop" in _read(CONSTITUTION)


# ── 6. Cross-reference, not restatement (operator gates owned by CLAUDE.md) ───

def test_constitution_references_anti_hold_for_gates() -> None:
    # §13/§14 must route operator gates to CLAUDE.md ANTI-HOLD rather than re-invent them.
    assert "ANTI-HOLD" in _read(CONSTITUTION)


# ── 7. Command registration — single authority, no duplicate loop command ────

def test_pz_loop_command_file_exists() -> None:
    assert PZ_LOOP.exists()


def test_pz_loop_registered_in_registry() -> None:
    assert "/pz-loop" in _read(COMMAND_REGISTRY)


def test_pz_loop_registered_exactly_once_in_matrix() -> None:
    # Exactly one quick-matrix row (leading "| `/pz-loop`") — no duplicate registrations.
    assert _read(COMMAND_REGISTRY).count("| `/pz-loop`") == 1


def test_loop_builtin_not_shadowed_by_project_command() -> None:
    # /loop is a Claude Code built-in; a project-level loop.md would duplicate that authority.
    assert not (COMMANDS / "loop.md").exists()


def test_registry_stale_count_corrected() -> None:
    assert "9 project commands" not in _read(COMMAND_REGISTRY)
    assert "15 project commands" in _read(COMMAND_REGISTRY)


# ── 8. No duplicate OS / loop authority ──────────────────────────────────────

def test_exactly_one_constitution_file() -> None:
    matches = sorted(ENGINEERING_OS.glob("*CONSTITUTION*.md"))
    assert len(matches) == 1, f"expected exactly one constitution file, found: {matches}"


def test_pz_loop_defers_protocol_to_constitution() -> None:
    # The command is an entry point; the protocol body lives in §13 (it must not restate it).
    txt = _read(PZ_LOOP)
    assert "§13" in txt or "00_ENGINEERING_CONSTITUTION" in txt
