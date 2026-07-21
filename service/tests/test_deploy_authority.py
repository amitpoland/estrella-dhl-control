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
                "forbidden_flags", "authorization_helper", "test_baseline_contract"):
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
    assert "Assert-Authorization" in body, "script must refuse production writes without signed authorization"
    assert "authorization_helper" in body, "the authorization helper path comes from config"
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


# ============================================================================
# Repo-wide production-writer inventory.
#
# The first version of these tests scanned only `.claude/**/*.ps1` and
# `.claude/deploy/`. That blindness let FOUR undeclared production writers survive
# a campaign that claimed "no hidden deployment authority left behind":
# verify_runtime_sync.py --sync, env_config_manager.ps1, activate_pz_lifecycle.py,
# and run_backup.py. These tests scan the whole repository.
# ============================================================================

# Requiring a QUOTED literal let a writer evade the scan by building the path
# indirectly -- os.path.join(os.environ["SYSTEMDRIVE"], "PZ", "app") or
# Path("C:\\") / "PZ" / "app". Match the token wherever it appears, plus the
# indirect-construction shape.
PROD_PATH_RX = re.compile(
    r"c:[\\/]{1,2}pz(?![\w\-])"
    r"|[\"']PZ[\"']\s*[,)/]",
    re.IGNORECASE,
)
WRITE_RX = re.compile(
    r"shutil\.copy|shutil\.copytree|\bos\.replace\b|open\([^)]*['\"][wa]|write_text|write_bytes"
    r"|\brobocopy\b|Copy-Item|\bxcopy\b|Set-Content|Out-File|WriteAllText",
    re.IGNORECASE,
)

# Every file that names the production tree AND writes, with its classification.
# Nothing may be added here without a stated authority class. The point is that the
# inventory is explicit and cannot grow silently -- an unclassified writer fails.
#
#   DEPLOYMENT      -> may write production code; exactly one such authority
#   RUNTIME_CONFIG  -> writes C:\PZ\.env; see UNGOVERNED note below
#   OPERATIONAL     -> maintenance/diagnostic; must not write production code
#   REFERENCE_ONLY  -> names paths for guarding, config, or docs; writes elsewhere
PRODUCTION_WRITER_ALLOWLIST = {
    ".claude/deploy/windows_prod_v2.json": "DEPLOYMENT - sole configuration authority",
    ".claude/deploy/Deploy-PZ.ps1": "DEPLOYMENT - sole execution + rollback authority",
    ".claude/deploy/Test-PZDeployClose.ps1": "DEPLOYMENT - sole validation authority, read-only",
    ".claude/hooks/pz-deploy-guard.py": "REFERENCE_ONLY - denies production writes",
    ".claude/hooks/deploy_authorization.py": "REFERENCE_ONLY - authorizes production writes",
    ".claude/hooks/merge_authorization.py": "REFERENCE_ONLY - protected-path markers",
    "service/tests/test_deploy_authority.py": "REFERENCE_ONLY - this inventory",
    "service/app/tools/verify_runtime_sync.py": "OPERATIONAL - refuses production destinations",
    # UNGOVERNED (tracked, NOT closed by this campaign). These write C:\PZ\.env, which
    # controls live service behaviour. They have no operator authorization, no lock, no
    # backup and no audit trail. They are merge-protected (merge_authorization.py) and
    # inventoried here so they cannot multiply, but consolidating them behind a single
    # runtime-configuration authority is a separate campaign.
    "service/scripts/env_config_manager.ps1": "RUNTIME_CONFIG - UNGOVERNED, tracked",
    "service/scripts/activate_pz_lifecycle.py": "RUNTIME_CONFIG - UNGOVERNED, tracked",
    "service/scripts/dhl-email-auto-scan.ps1": "OPERATIONAL - scheduled scan, no code write",
    "service/scripts/review_launch.py": "OPERATIONAL - review tooling",
    "service/scripts/backfill_skip_events_f255bbb5.py": "OPERATIONAL - one-off backfill",
    "service/app/api/routes_dhl_clearance.py": "REFERENCE_ONLY - storage paths, not code",
    # Surfaced only after PROD_PATH_RX was broadened to catch unquoted/indirect paths.
    "scripts/cp3_capture.py": "OPERATIONAL - capture tooling, no production code write",
    "service/tools/backfill_service_product_registry.py": "OPERATIONAL - data backfill",
}


def _source_files():
    for pat in ("**/*.py", "**/*.ps1"):
        for p in REPO.glob(pat):
            rel = p.relative_to(REPO).as_posix()
            if any(rel.startswith(s) for s in (".git/", "node_modules/", "reports/", ".claude/memory/")):
                continue
            # Test files reference production paths in fixtures and assertions; they
            # never execute against production.
            if rel.startswith("service/tests/") and rel != "service/tests/test_deploy_authority.py":
                continue
            if "__pycache__" in rel or "/.claude/worktrees/" in rel:
                continue
            yield p, rel


def test_no_undeclared_production_writers():
    """A file that both names the production tree AND performs a write is a
    production writer. Every one must be explicitly accounted for."""
    offenders = {}
    for p, rel in _source_files():
        if rel in PRODUCTION_WRITER_ALLOWLIST:
            continue
        body = _read(p)
        if PROD_PATH_RX.search(body) and WRITE_RX.search(body):
            offenders[rel] = "names the production tree and performs writes"
    assert not offenders, (
        "undeclared production writer(s) found. Either route the write through "
        "Deploy-PZ.ps1, make the file refuse production destinations, or add it to "
        f"PRODUCTION_WRITER_ALLOWLIST with a justification: {offenders}"
    )


def test_runtime_sync_refuses_production_destinations():
    """verify_runtime_sync.py --sync was a second, unguarded writer into the runtime
    engine path: no authorization, no lock, no backup, invisible to the guard."""
    body = _read(REPO / "service" / "app" / "tools" / "verify_runtime_sync.py")
    assert "_is_production" in body, "sync tool must detect production destinations"
    assert "def _is_forbidden" in body and "_is_production(path)" in body, (
        "the production check must be wired into _is_forbidden, which _sync_file consults"
    )


def test_no_competing_backup_authority_in_prescriptive_docs():
    """run_backup.py produces a manifest-less format incompatible with -Rollback.
    The deploy policy must not instruct an operator to run it as a deploy backup."""
    offenders = []
    for md in _prescriptive_markdown():
        if "run_backup.py" in _read(md):
            offenders.append(str(md.relative_to(REPO)))
    assert not offenders, (
        "deployment docs must reference only the canonical backup (Deploy-PZ.ps1 "
        f"New-BackupUnit): {offenders}"
    )


def test_no_git_revert_rollback_in_policy():
    """Rollback restores validated artifacts. git revert as a production rollback
    mutates the certified source and was explicitly retired."""
    body = _read(POLICY).lower()
    assert "git revert" not in body, (
        "production_deployment_rule.md must not document git revert as rollback; "
        "use Deploy-PZ.ps1 -Rollback -Unit <unit>"
    )


# ---------------------------------------------------------------- regressions
def test_reviewed_sha_is_explicit_and_never_recomputed():
    """The two-invocation design let origin/main advance between the gate run and the
    deploy run, shipping an unreviewed commit. The target must be operator-supplied."""
    body = _read(DEPLOY_SCRIPT)
    assert "$ReviewedSHA" in body, "-ReviewedSHA must be a parameter"
    assert "-ReviewedSHA is required" in body, "a deploy without an explicit target must be refused"
    assert "advanced BEYOND the reviewed target" in body, (
        "the script must refuse to deploy when origin/main has moved past the reviewed SHA"
    )
    assert "Get-IncomingRange" not in body, (
        "the deployed target must never be recomputed from a fresh origin/main read"
    )


def test_version_file_written_bom_free_and_validated_by_bytes():
    """PowerShell 5.1 Out-File -Encoding utf8 emits a BOM. Python's utf-8 reader does
    not strip it and it is not whitespace, so the endpoint would serve a corrupt SHA.
    The old validator used Get-Content, which strips BOM -> silent false PASS."""
    deploy = _read(DEPLOY_SCRIPT)
    assert "ASCIIEncoding" in deploy, "version file must be written BOM-free"
    assert "| Out-File" not in deploy and "Out-File -FilePath" not in deploy, (
        "Out-File -Encoding utf8 emits a BOM on PS 5.1; the version file must not use it"
    )
    assert "0xEF" in deploy, "the writer must assert the result is BOM-free"
    val = _read(VALIDATOR)
    assert "ReadAllBytes" in val, "validation must read raw bytes, not text"
    assert "BOM-free" in val, "validation must explicitly check for a BOM"
    # The version-file and HEAD checks must be EXACT. (-like remains legitimate for
    # matching backup unit directories, which are named "<sha>-<stamp>".)
    assert '$actual -eq $ExpectedSHA' in val, "version-file SHA comparison must be exact"
    assert '$head.Trim() -eq $ExpectedSHA' in val, "HEAD SHA comparison must be exact"
    assert '$actual -like' not in val and '$head -like' not in val, (
        "SHA comparisons must not use wildcard prefix matching"
    )


def test_rollback_unit_rejects_traversal():
    body = _read(DEPLOY_SCRIPT)
    assert "UNIT_RX" in body, "unit identifiers must be format-validated"
    assert r"^[0-9a-f]{40}-\d{8}-\d{6}$" in body, "unit format must be anchored"
    idx_check = body.index("not a valid unit identifier")
    idx_stop = body.index("Set-ServiceState -Cfg $Cfg -Target Stopped", body.index("function Invoke-Rollback"))
    assert idx_check < idx_stop, "traversal must be rejected BEFORE the service is stopped"


def test_empty_protection_arrays_are_rejected():
    body = _read(DEPLOY_SCRIPT)
    assert "is present but EMPTY" in body, (
        "an empty protected_dirs would let /MIR delete production storage/logs/cloudflared"
    )
    for key in ("engine_files", "protected_dirs", "protected_files", "protected_runtime_paths"):
        assert key in body, f"{key} must be non-empty-validated"


def test_lock_taken_before_any_mutable_preparation():
    body = _read(DEPLOY_SCRIPT)
    i_lock = body.index("Enter-DeployLock -Cfg $cfg")
    i_art = body.index("New-ReleaseArtifact -Cfg $cfg")
    i_bak = body.index("New-BackupUnit -Cfg $cfg")
    assert i_lock < i_art and i_lock < i_bak, (
        "the lock must be held before artifact staging and backup creation"
    )


def test_backup_taken_with_service_stopped():
    body = _read(DEPLOY_SCRIPT)
    i_stop = body.index("Set-ServiceState -Cfg $cfg -Target Stopped")
    i_bak = body.index("New-BackupUnit -Cfg $cfg")
    assert i_stop < i_bak, "the backup must be taken from a stopped, stable runtime tree"
    assert "SERVICE_STOPPED_NO_DEPLOY" in body, (
        "a preparation failure after the stop must emit an explicit recovery state"
    )


def test_stale_lock_recovery_is_pid_aware():
    body = _read(DEPLOY_SCRIPT)
    assert "Get-Process -Id $lockPid" in body, "staleness must be decided by process existence"
    assert "ForceUnlock" in body, "an explicit operator override must exist"
    assert "STALE LOCK CLEARED (audit)" in body, "clearing a lock must be auditable"
    assert "CreateNew" in body, "lock creation must be atomic, not Test-Path then write"


def test_whatif_requires_no_authorization_and_writes_nothing():
    body = _read(DEPLOY_SCRIPT)
    assert 'if (-not $script:PlanOnly) { Assert-Authorization' in body, (
        "-WhatIf must not require a production authorization"
    )
    assert "plan mode takes none" in body, "-WhatIf must not create a lock"
    for fn in ("Write-VersionFile", "New-Manifest", "Invoke-Robocopy", "Set-ServiceState"):
        seg = body[body.index(f"function {fn}"):]
        seg = seg[:seg.index("\nfunction ") if "\nfunction " in seg else len(seg)]
        assert "$script:PlanOnly" in seg, f"{fn} must be a no-op under -WhatIf"


def test_rollback_survives_missing_engine_metadata():
    body = _read(DEPLOY_SCRIPT)
    assert "-Optional" in body, "component manifests must be optional so app-only units restore"
    assert "contains no restorable component" in body, (
        "only a unit with NO restorable component may fail outright"
    )


def test_authorization_is_signed_not_presence_only():
    """Presence of an env var is not authorization: an agent can set one in a wrapper
    script. Authorization must be cryptographically bound to SHA, action and scope."""
    auth = _read(REPO / ".claude" / "hooks" / "deploy_authorization.py")
    assert "hmac.compare_digest" in auth, "signature check must be constant-time"
    assert "_SIGNED_FIELDS" in auth and "reviewed_sha" in auth, "signature must cover the SHA"
    assert '"action"' in auth and '"scope"' in auth, "signature must cover action and scope"
    assert "expires_at" in auth and "jti" in auth, "authorizations must expire and be single-use"
    deploy = _read(DEPLOY_SCRIPT)
    assert "operator_token_env" not in deploy, "presence-only token gating must be gone"
    assert "the agent cannot derive it" not in deploy.lower(), (
        "a security claim the implementation does not enforce must not be asserted"
    )


def test_guard_covers_deploy_config_in_merge_protection():
    body = _read(REPO / ".claude" / "hooks" / "merge_authorization.py")
    assert '".claude/deploy/"' in body, (
        "a config-only PR could repoint runtime paths and redirect /MIR convergence"
    )
