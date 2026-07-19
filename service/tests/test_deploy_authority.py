"""Deployment-authority governance pins.

Deployment authority became duplicated across 29 execution files, 5 rollback models,
4 validation owners and 3 conflicting source paths because duplication was only ever
caught by human review of prose. These tests make re-duplication a FAILING TEST.

Authority model enforced here:
  configuration -> .claude/deploy/windows_prod_v2.json        (only)
  execution     -> .claude/deploy/Deploy-PZ.ps1               (only)
  validation    -> .claude/deploy/Test-PZDeployClose.ps1      (only, read-only)
  policy        -> service/docs/production_deployment_rule.md (governance only)
  version file  -> written by Deploy-PZ.ps1                   (only writer)

PRESCRIPTIVE vs DESCRIPTIVE: markdown that tells an operator what to run now must
contain no executable deployment commands. Markdown that RECORDS what happened
(scorecards, reports, incident write-ups, engineering lessons) legitimately quotes
commands and is exempt -- stripping it would destroy history.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

CONFIG = REPO / ".claude" / "deploy" / "windows_prod_v2.json"
DEPLOY_SCRIPT = REPO / ".claude" / "deploy" / "Deploy-PZ.ps1"
VALIDATOR = REPO / ".claude" / "deploy" / "Test-PZDeployClose.ps1"
GUARD = REPO / ".claude" / "hooks" / "pz-deploy-guard.py"
POLICY = REPO / "service" / "docs" / "production_deployment_rule.md"

# Markdown that instructs an operator what to run NOW.
PRESCRIPTIVE_DIRS = [
    REPO / ".claude" / "commands",
    REPO / ".claude" / "agents",
    REPO / ".claude" / "contracts",
    REPO / ".claude" / "runbooks",
    REPO / ".claude" / "deploy",
]
PRESCRIPTIVE_FILES = [POLICY, REPO / "service" / "docs" / "windows-deploy-runbook-template.md"]

# Executable deployment verbs. Matched only inside prescriptive markdown.
EXEC_RX = re.compile(r"\brobocopy\b|\bsc\.exe\s+(stop|start)\b|\bnssm\s+(stop|start|restart)\b", re.IGNORECASE)

# Production path literals that must exist only in the config.
PATH_RX = re.compile(r"C:\\\\?PZ(\\\\|\\|-releases|-backups|\b)", re.IGNORECASE)


def _prescriptive_markdown() -> list[Path]:
    out: list[Path] = []
    for d in PRESCRIPTIVE_DIRS:
        if d.exists():
            out.extend(sorted(d.rglob("*.md")))
    out.extend([p for p in PRESCRIPTIVE_FILES if p.exists()])
    return out


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------- single authority
def test_exactly_one_execution_authority():
    scripts = sorted(REPO.glob(".claude/**/*.ps1"))
    names = [p.name for p in scripts]
    assert names.count("Deploy-PZ.ps1") == 1, f"expected exactly one Deploy-PZ.ps1, found {names}"
    stale = [p for p in scripts if p.name.startswith("windows_deploy_")]
    assert not stale, f"per-SHA deploy scripts must not return: {[p.name for p in stale]}"
    assert not (REPO / ".claude" / "manifests" / "verify_deploy_close.ps1").exists(), (
        "verify_deploy_close.ps1 was a second deployer (robocopy + service restart) and is retired"
    )


def test_exactly_one_validation_authority():
    assert VALIDATOR.exists()
    body = _read(VALIDATOR)
    for verb in ("robocopy", "sc.exe stop", "sc.exe start", "Set-Content", "Out-File"):
        assert verb.lower() not in body.lower(), f"validation must be read-only; found '{verb}'"


def test_exactly_one_configuration_authority():
    cfg = json.loads(_read(CONFIG))
    assert cfg["schema_version"] == 2
    for key in ("source_root", "runtime_app", "runtime_engine", "artifact_root",
                "backup_root", "version_file", "engine_files", "protected_dirs",
                "forbidden_flags", "operator_token_env", "test_baseline_contract"):
        assert key in cfg, f"config missing required key: {key}"
    assert "/XO" in cfg["forbidden_flags"], "/XO caused the 2026-07-07 incident and stays forbidden"


# --------------------------------------------------------------- no duplication
FENCE_RX = re.compile(r"```[\s\S]*?```")


def test_no_executable_deploy_logic_in_prescriptive_markdown():
    """Executable logic means a COMMAND BLOCK, not a prose mention.

    Governance docs must remain able to name a command in order to forbid it
    (e.g. forbidden-paths.md saying '/MIR is never permitted'). What they may not
    do is carry a runnable block an operator can paste. So only fenced blocks are
    scanned.
    """
    offenders = {}
    for md in _prescriptive_markdown():
        hits = [b for b in FENCE_RX.findall(_read(md)) if EXEC_RX.search(b)]
        if hits:
            offenders[str(md.relative_to(REPO))] = len(hits)
    assert not offenders, (
        "prescriptive markdown must explain, never execute. Move commands into "
        f"Deploy-PZ.ps1: {offenders}"
    )


def test_no_deployment_path_literals_outside_config():
    offenders = {}
    allowed = {CONFIG.resolve(), Path(__file__).resolve()}
    for p in sorted((REPO / ".claude" / "deploy").rglob("*")):
        if p.is_file() and p.resolve() not in allowed:
            body = _read(p)
            # The script may name paths only through config keys, never literally.
            bad = [m.group(0) for m in PATH_RX.finditer(body)]
            if bad:
                offenders[str(p.relative_to(REPO))] = sorted(set(bad))
    assert not offenders, f"production paths must come from config only: {offenders}"


def test_engine_filenames_only_in_config():
    cfg = json.loads(_read(CONFIG))
    offenders = {}
    for name in cfg["engine_files"]:
        for p in sorted((REPO / ".claude" / "deploy").rglob("*")):
            if p.is_file() and p.resolve() != CONFIG.resolve() and name in _read(p):
                offenders.setdefault(str(p.relative_to(REPO)), []).append(name)
    assert not offenders, (
        "engine filenames are configuration; the script must iterate config.engine_files: "
        f"{offenders}"
    )


def test_test_counts_only_in_baseline_contract():
    """Deploy surfaces must not hardcode pass counts (they drifted to 604/469/412)."""
    count_rx = re.compile(r"\b(?:412|469|584|604)\b")
    offenders = {}
    for p in [CONFIG, DEPLOY_SCRIPT, VALIDATOR, POLICY]:
        if p.exists() and count_rx.search(_read(p)):
            offenders[str(p.relative_to(REPO))] = count_rx.findall(_read(p))
    assert not offenders, f"counts belong only in .claude/contracts/test-baseline.md: {offenders}"


# --------------------------------------------------------------- runtime contracts
def test_version_file_has_exactly_one_writer():
    cfg = json.loads(_read(CONFIG))
    assert "version_file" in cfg
    writers = []
    for p in sorted(REPO.rglob("*.ps1")):
        body = _read(p)
        if "version_file" in body and ("Out-File" in body or "Set-Content" in body):
            writers.append(p.name)
    assert writers == ["Deploy-PZ.ps1"], (
        f"version.txt must have exactly one writer (production reads it via "
        f"routes_webhooks_wfirma_status.py); found {writers}"
    )


def test_guard_denies_deploy_script_invocation():
    """The guard is a text matcher. A config-driven script carries no C:\\PZ token,
    so without a name-based rule the guard would be silently bypassed."""
    body = _read(GUARD)
    assert "DEPLOY_SCRIPT_RX" in body, "guard must recognise the deployment script by name"
    assert re.search(r"deploy-pz\\?\.ps1", body, re.IGNORECASE), "guard rule must match Deploy-PZ.ps1"
    assert "deploy-script-invocation" in body, "guard must emit a deny label for script invocation"


def test_deploy_script_defends_itself():
    body = _read(DEPLOY_SCRIPT)
    assert "Assert-OperatorToken" in body, "script must refuse production writes without the operator token"
    assert "operator_token_env" in body, "operator token env var name comes from config"
    assert "Enter-DeployLock" in body, "concurrent operator execution must be refused"


def test_rollback_never_mutates_git():
    body = _read(DEPLOY_SCRIPT)
    for forbidden in ("git revert", "git reset", "git checkout"):
        assert forbidden not in body.lower(), (
            f"rollback must restore from validated backups, never '{forbidden}'"
        )


def test_rollback_requires_validated_manifest():
    body = _read(DEPLOY_SCRIPT)
    assert "Test-AgainstManifest" in body
    assert body.count("Test-AgainstManifest") >= 4, (
        "backup integrity and restored state must both be manifest-verified, app and engine"
    )


@pytest.mark.parametrize("retired", [
    ".claude/manifests/verify_deploy_close.ps1",
    "reports/deploy/verify_sync.py",
])
def test_retired_deployment_scripts_are_gone(retired):
    assert not (REPO / retired).exists(), f"{retired} was retired; it must not return"
