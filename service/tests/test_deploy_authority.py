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
    # Surfaced when origin/main was merged in: both are false positives of the
    # substring regexes (the write-verb / production token sits inside a comment,
    # not in executable code), classified honestly rather than by weakening the regex.
    "service/app/api/routes_webhooks_wfirma_status.py": "REFERENCE_ONLY - reads version.txt; the only write-verb (Out-File) is inside the #969 BOM-explanation comment",
    "service/scripts/dhl-lane-b-throttle-check.ps1": "OPERATIONAL - throttle self-test; redirects its stamp to $env:TEMP and only names C:\\PZ in a 'never touch' comment",
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


# --------------------------------------------------- health-endpoint auth (2026-07-29)
# The read-only validator probed the health endpoints ANONYMOUSLY, but they are
# authenticated (require_api_key / X-API-Key) BY DESIGN, so both returned 401 and a
# valid deploy could never close. The fix authenticates the probe with the SAME
# credential the service loads -- WITHOUT weakening the route and WITHOUT logging the
# secret. These pins hold that contract in both directions: the endpoint must stay
# authenticated, and the validator must stay a non-leaking legitimate caller.
ROUTES_PZ = REPO / "service" / "app" / "api" / "routes_pz.py"


def test_health_probe_authenticates_without_weakening_route():
    val = _read(VALIDATOR)
    assert "X-API-Key" in val, "the health probe must send an X-API-Key header"
    assert re.search(r"Invoke-WebRequest[^\n]*-Headers", val), (
        "the health request must carry the auth header"
    )
    # The route the validator hits must remain guarded -- making /health anonymous to
    # satisfy the validator is the forbidden fix. Match within the decorator window
    # (not a single greedy line) so a routine multi-line reformat of the decorator
    # does not produce a false CI block.
    route = _read(ROUTES_PZ)
    m = re.search(r'@router\.get\("/health"', route)
    assert m, "the /health route decorator must exist"
    decorator = route[m.start():m.start() + 300]
    assert "dependencies=[_auth]" in decorator, (
        "the /health route must remain authenticated (dependencies=[_auth])"
    )
    assert "_auth = Depends(require_api_key)" in route, (
        "_auth must remain require_api_key; the endpoint may not be made anonymous"
    )


def test_health_credential_source_is_config_not_hardcoded():
    cfg = json.loads(_read(CONFIG))
    assert cfg.get("health_auth_env_file"), "config must name the health credential .env"
    assert cfg.get("health_auth_env_var") == "API_KEY", (
        "the health credential is the service API_KEY"
    )
    val = _read(VALIDATOR)
    assert "health_auth_env_file" in val and "health_auth_env_var" in val, (
        "the validator must read the credential source from config keys, not a literal"
    )
    assert "PZ_HEALTH_API_KEY" in val, (
        "an explicit operator-shell env override must be supported"
    )


def test_health_key_is_never_logged():
    """The credential variable may appear only where the request is built -- never in
    a result detail or any host/output sink."""
    val = _read(VALIDATOR)
    key_var = "$healthKey"
    assert key_var in val, "the health-auth fix must be present"
    for line in val.splitlines():
        if key_var not in line:
            continue
        assert not line.strip().startswith("Add-Result"), (
            f"credential leaked into a result detail: {line!r}"
        )
        assert "Write-Host" not in line, f"credential leaked into host output: {line!r}"
        assert "Write-Output" not in line, f"credential leaked into output: {line!r}"


def test_health_probe_fails_explicitly_when_credential_missing():
    val = _read(VALIDATOR)
    assert "if (-not $healthKey)" in val, (
        "there must be an explicit unavailable-credential branch"
    )
    idx = val.index("if (-not $healthKey)")
    seg = val[idx:idx + 400]
    assert "Add-Result" in seg and "$false" in seg, (
        "the unavailable-credential branch must record a FAILED result, never a silent pass"
    )
    assert "credential unavailable" in val


def test_health_env_read_is_defensive_and_dotenv_faithful():
    """An unreadable .env must FAIL structurally (return $null -> explicit per-URL
    FAIL), never crash the Stop-mode validator; and the value must be parsed like
    python-dotenv (the service's own loader) so a healthy .env carrying an inline
    comment on the API_KEY line is not sent as a wrong key and rejected 401."""
    val = _read(VALIDATOR)
    # Defensive read: the .env Get-Content is guarded so a permission error returns
    # $null instead of terminating the script before the check table prints.
    assert re.search(
        r"try\s*\{[^}]*Get-Content[^}]*\}\s*catch\s*\{\s*return \$null\s*\}", val, re.DOTALL
    ), "the .env read must be wrapped so an unreadable file fails structurally, not fatally"
    # python-dotenv-faithful inline-comment stripping on unquoted values.
    assert ".IndexOf(' #')" in val, (
        "an unquoted value's inline comment ( whitespace + '#' ) must be stripped to "
        "match python-dotenv, or a commented API_KEY line 401s a healthy deploy"
    )


# --------------------------------------------------- rollback provenance (2026-07-29)
# One metadata field (unit.json 'sha') served two authorities: (1) which deployment may
# be rolled back (authorization), and (2) which SHA the restored bytes represent
# (content identity). Invoke-Rollback reused the deployment SHA for BOTH, so after a
# rollback production held the OLD application bytes but advertised the NEWER deployment
# SHA in version.txt. These pins keep the two identities separate: deployment_sha
# authorizes; restored_sha is stamped after restore; a unit that cannot establish
# restored_sha fails closed instead of guessing the deployment SHA.
def _rollback_segment(body: str) -> str:
    start = body.index("function Invoke-Rollback")
    rest = body[start + len("function Invoke-Rollback"):]
    end = rest.index("\nfunction ") if "\nfunction " in rest else len(rest)
    return rest[:end]


def _backup_segment(body: str) -> str:
    start = body.index("function New-BackupUnit")
    rest = body[start + len("function New-BackupUnit"):]
    end = rest.index("\nfunction ") if "\nfunction " in rest else len(rest)
    return rest[:end]


def test_backup_records_deployment_and_restored_sha_separately():
    """The backup unit must record the deployment SHA (authorization) and the
    pre-deployment production SHA (restored content) as two distinct fields."""
    seg = _backup_segment(_read(DEPLOY_SCRIPT))
    assert "deployment_sha = $Sha" in seg, "the deployment SHA must be recorded explicitly"
    assert "restored_sha = $restoredSha" in seg, "the pre-deployment SHA must be recorded"
    # restored_sha is the pre-deployment marker, read BEFORE any mutation.
    i_read = seg.index("Read-VersionMarker -Path $Cfg.version_file")
    i_write = seg.index("unit.json")
    assert i_read < i_write, "the pre-deployment marker must be read before unit.json is written"


def test_backup_snapshots_predeployment_marker_immutably():
    """A write-once copy of the pre-deployment marker corroborates restored_sha, since
    unit.json is rewritten when 'complete' flips true."""
    seg = _backup_segment(_read(DEPLOY_SCRIPT))
    assert "version.pre.txt" in seg, "an immutable pre-deployment marker snapshot must be captured"
    # It is captured inside the plan-guarded pre-backup block (no writes under -WhatIf).
    assert "$script:PlanOnly" in seg, "the snapshot must be a no-op under -WhatIf"


def test_rollback_authorizes_with_deployment_sha():
    """Authorization binding is unchanged: rollback is authorized against the SHA whose
    deployment created the unit, never the restored-content SHA."""
    seg = _rollback_segment(_read(DEPLOY_SCRIPT))
    assert 'Assert-Authorization -Cfg $Cfg -Sha $deploymentSha -Action "rollback"' in seg, (
        "rollback must authorize with the deployment SHA"
    )
    assert "$meta.deployment_sha" in seg, "the deployment SHA comes from the recorded field"
    # scope is still carried into authorization.
    assert "-UnitScope $Scope" in seg, "rollback authorization must remain scope-bound"


def test_rollback_stamps_restored_sha_not_deployment_sha():
    """The fix: production advertises the restored-content SHA after a rollback."""
    seg = _rollback_segment(_read(DEPLOY_SCRIPT))
    assert "Write-VersionFile -Cfg $Cfg -Sha $restoredSha" in seg, (
        "rollback must stamp the version marker with the restored-content SHA"
    )
    assert "Write-VersionFile -Cfg $Cfg -Sha $sha" not in seg, (
        "rollback must NOT stamp the deployment SHA over restored bytes (the original bug)"
    )
    assert "Write-VersionFile -Cfg $Cfg -Sha $deploymentSha" not in seg, (
        "rollback must not stamp the deployment SHA under any name"
    )


def test_rollback_uses_two_distinct_identities():
    """Authorization identity and restored-content identity are separate variables,
    so they are allowed to differ (the normal case: rolling an old tree back)."""
    seg = _rollback_segment(_read(DEPLOY_SCRIPT))
    assert "$deploymentSha =" in seg, "authorization identity must be its own variable"
    assert "$restoredSha = Resolve-RestoredSha" in seg, (
        "restored identity must come from the trusted-metadata resolver"
    )


def test_restored_sha_resolver_fails_closed_and_never_guesses():
    """A unit that cannot establish restored_sha from trusted metadata must BLOCK, and
    must never fall back to the deployment SHA or a filename split."""
    body = _read(DEPLOY_SCRIPT)
    assert "function Resolve-RestoredSha" in body, "the restored-SHA resolver must exist"
    start = body.index("function Resolve-RestoredSha")
    seg = body[start:body.index("function Invoke-Rollback")]
    # Legacy / missing evidence blocks explicitly.
    assert "records no restored-content SHA" in seg, "a unit with no evidence must be refused"
    assert "NOT used as a fallback" in seg, "the deployment SHA must be a stated non-fallback"
    # Malformed metadata is rejected, not trusted.
    assert "-match $script:SHA_RX" in seg, "the metadata SHA must be format-validated"
    # Two trusted sources that disagree are refused, not silently reconciled.
    assert "inconsistent restored-content evidence" in seg, (
        "disagreeing metadata and snapshot must block rather than guess"
    )
    # It must not reconstruct identity from the unit id or deployment SHA.
    assert "$UnitId.Split" not in seg, "the resolver must not guess a SHA from the unit id"
    assert "$Sha" not in seg, "the resolver must not see or use the incoming deployment SHA"


def test_version_marker_reader_never_guesses():
    """Read-VersionMarker validates against the SHA regex and returns $null on anything
    unrecognisable -- callers fail closed rather than trusting a partial value."""
    body = _read(DEPLOY_SCRIPT)
    assert "function Read-VersionMarker" in body, "a validating marker reader must exist"
    start = body.index("function Read-VersionMarker")
    rest = body[start:]
    seg = rest[:rest.index("\nfunction ", 1)]
    assert "-match $script:SHA_RX" in seg, "the reader must validate the SHA shape"
    assert "return $null" in seg, "an unrecognisable marker must yield $null, never a guess"


def test_rollback_closure_asserts_marker_matches_restored_content():
    """Rollback must not report success if the written marker and the restored content
    disagree -- it reads the marker back and refuses, leaving the service stopped."""
    seg = _rollback_segment(_read(DEPLOY_SCRIPT))
    i_write = seg.index("Write-VersionFile -Cfg $Cfg -Sha $restoredSha")
    i_readback = seg.index("Read-VersionMarker -Path $Cfg.version_file")
    i_complete = seg.index("ROLLBACK COMPLETE")
    assert i_write < i_readback < i_complete, (
        "the marker must be written, then read back and verified, before success is reported"
    )
    assert "does not equal the restored-content SHA" in seg, (
        "a marker/content mismatch must throw, not pass"
    )
    # The success line reports the restored content, not the deployment SHA.
    assert "restored to content $restoredSha" in seg
