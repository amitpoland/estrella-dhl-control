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
    # /MIR is not banned — it is GATED. It is the only mechanism that removes files a
    # newer release deleted/renamed, so exact convergence depends on it; the gate is what
    # keeps it safe. Banning it outright would break Deploy-PZ.ps1 convergence + rollback
    # and resurrect the /XO skew class. (Operator-affirmed 2026-07-31; #958 architecture.)
    assert "/MIR" not in cfg["forbidden_flags"], (
        "/MIR is the load-bearing convergence+rollback mechanism; it is gated, never banned"
    )
    gated = cfg.get("gated_flags", {})
    assert "/MIR" in gated, "/MIR must be declared as a gated (not forbidden) flag"
    mir = gated["/MIR"].lower()
    assert "inventory" in mir and "protected" in mir, (
        "the /MIR gate must require destination-only inventory classification and protected-path exclusion"
    )


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


def test_policy_permits_only_gated_mirror_convergence():
    """Semantic contract for the deploy-sync policy (no fragile line numbers).

    The additive-only model was retired when Deploy-PZ.ps1 became the single
    self-verifying deploy authority (#958). Exact convergence -- which alone removes
    files a newer release deleted or renamed -- is performed by the gated `/MIR`
    inside Deploy-PZ.ps1, after destination-only inventory classification and with
    every protected path excluded. Policy prose used to carry the opposite rule in
    three places ('Additive sync only', 'No deletion, overwrite, or mirror copy',
    'still no /MIR', and a '/XO permitted for a top-up' carve-out), directly
    contradicting the config (/XO forbidden, /MIR gated). This test pins the
    contradiction closed so it cannot silently return.
    """
    body = _read(POLICY).lower()

    # The retired additive-only / unconditional-no-mirror model must not reappear.
    assert "additive sync only" not in body, (
        "'Additive sync only' is the retired pre-#958 model; production converges "
        "exactly to the reviewed artifact via the gated /MIR in Deploy-PZ.ps1"
    )
    assert "no deletion, overwrite, or mirror copy" not in body, (
        "an unconditional no-mirror rule contradicts the gated /MIR convergence"
    )
    assert "still no `/mir`" not in body and "still no /mir" not in body, (
        "the recovery-sync path must not forbid /MIR; exact convergence IS the gated /MIR"
    )

    # /XO stays forbidden without exception -- no 'permitted only for ...' carve-out.
    assert "permitted only for a known-incremental" not in body, (
        "/XO caused the 2026-07-07 skew and is in forbidden_flags; policy grants it no exception"
    )

    # The convergence executor is named, and /MIR is gated to it (never manual / ad hoc).
    assert "deploy-pz.ps1" in body, "policy must name Deploy-PZ.ps1 as the convergence executor"
    assert "/mir" in body, "policy must address /MIR explicitly"
    assert "gated convergence" in body, (
        "policy must permit /MIR only inside the canonical gated convergence"
    )
    assert "manually" in body or "ad hoc" in body, (
        "policy must forbid manual / ad hoc /MIR outside Deploy-PZ.ps1"
    )
    # The gate's precondition must be stated in prose, matching the config's gated_flags.
    assert "destination-only inventory" in body, (
        "policy must state the destination-only inventory precondition for /MIR"
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
    # restored_sha is the pre-deployment marker, read BEFORE any mutation. Anchor to the
    # actual Set-Content write of unit.json (not the substring "unit.json", whose first hit
    # is a comment) so a refactor that moved the read after the write cannot silently pass.
    i_read = seg.index("Read-VersionMarker -Path $Cfg.version_file")
    i_write = seg.index('Set-Content (Join-Path $bak "unit.json")')
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


def test_rollback_validates_authorization_identity_before_using_it():
    """Two of the three deployment-SHA sources are untrusted (a hand-edited unit.json and
    a directory name), so the authorization identity is shape-validated before it reaches
    Assert-Authorization -- never passed through as an empty or unmatchable binding."""
    seg = _rollback_segment(_read(DEPLOY_SCRIPT))
    i_assign = seg.index("$deploymentSha = if ($meta")
    i_validate = seg.index("$deploymentSha -notmatch $script:SHA_RX")
    i_authorize = seg.index('Assert-Authorization -Cfg $Cfg -Sha $deploymentSha')
    assert i_assign < i_validate < i_authorize, (
        "the deployment SHA must be validated after assignment and before it authorizes anything"
    )
    assert "malformed deployment SHA" in seg, "a malformed authorization identity must block"


def test_backup_warns_when_minting_an_unrollbackable_unit():
    """A unit whose pre-deployment marker was unreadable is recorded with a null
    restored_sha and CANNOT be rolled back. Without a deploy-time warning that defect is
    discovered mid-incident, when the rollback that was meant to be the remedy refuses."""
    seg = _backup_segment(_read(DEPLOY_SCRIPT))
    i_read = seg.index("Read-VersionMarker -Path $Cfg.version_file")
    i_warn = seg.index("Write-Warning")
    i_write = seg.index('Set-Content (Join-Path $bak "unit.json")')
    assert i_read < i_warn < i_write, (
        "the missing-provenance warning must follow the read and precede the unit being written"
    )
    assert "$appPresent -and -not $restoredSha" in seg, (
        "warn exactly when there ARE bytes to restore but no identity for them"
    )
    assert "will be REFUSED" in seg, "the warning must state the operational consequence"
    # It is a warning, not a block: refusing the forward deploy would strand production on
    # the state the operator is trying to leave.
    assert "throw" not in seg[i_warn:i_write], "missing provenance must not block the forward deploy"


def test_rollback_reports_a_named_recovery_state_on_failure():
    """The rollback runs when production is ALREADY wrong and it stops the service to work.
    A bare exception would leave a stopped service, an unknown degree of restoration and no
    named next step -- the remedy path must not be weaker than the forward deploy, which
    reports SERVICE_STOPPED_NO_DEPLOY / PARTIAL_DEPLOY."""
    seg = _rollback_segment(_read(DEPLOY_SCRIPT))
    assert "RECOVERY STATE: ROLLBACK_FAILED" in seg, "a failed rollback must name its recovery state"
    # The failure is reported, never swallowed: the exit code must still fail.
    i_state = seg.index("RECOVERY STATE: ROLLBACK_FAILED")
    assert "throw" in seg[i_state:], "the recovery handler must re-throw, not swallow the failure"
    # The operator is told how far it got, not every possibility.
    assert "Position when it failed: $stage" in seg, "the handler must state the actual position reached"
    # The lock is still released -- the handler sits between the try body and finally.
    assert seg.index("catch {", i_state - 800) < seg.index("finally { Exit-DeployLock")
    # It must not offer a hand-written marker as a remedy; there is exactly one writer.
    assert "Do not stamp the version marker by hand" in seg


def test_rollback_stage_is_true_while_the_tree_is_being_overwritten():
    """$stage is what the failure handler reports, so it must be true AT the moment of the
    throw, not only between steps. The app restore runs /MIR, which deletes destination-only
    files before it finishes copying: a throw out of robocopy while the stage still said
    'nothing restored yet' would tell the operator the tree is intact when it is half-written
    -- the single most costly moment to be wrong."""
    seg = _rollback_segment(_read(DEPLOY_SCRIPT))
    nothing = '$stage = "service stopped; nothing restored yet"'
    # Slice from AFTER that assignment -- including it would make the search for a stage
    # assignment below trivially true and the pin would prove nothing.
    i_nothing = seg.index(nothing) + len(nothing)
    i_app_copy = seg.index('-What "app restore"')
    between = seg[i_nothing:i_app_copy]
    assert "$stage =" in between, (
        "the stage must be advanced before the app restore starts, not after it returns"
    )
    assert "IN PROGRESS" in between, "the in-flight stage must say the restore is in progress"
    # And the same for the engine restore, which follows a stage that claims the app is done.
    i_engine_copy = seg.index('-What "engine restore"')
    assert "$stage =" in seg[i_app_copy:i_engine_copy], (
        "the stage must be advanced before the engine restore starts"
    )


def test_rollback_does_not_tell_the_operator_to_rerun_a_rollback_that_succeeded():
    """If restore + stamp + closure assertion all passed and only the service start failed,
    re-running the rollback repeats work that is already correct, fails the same way, and
    burns a second single-use authorization. The remaining fault is the service, not the
    provenance."""
    src = _read(DEPLOY_SCRIPT)
    seg = _rollback_segment(src)
    # A distinguishing stage is set once the restoration is proven, before the service start.
    i_pass = seg.index("closure assertion PASSED")
    i_start = seg.index("Set-ServiceState -Cfg $Cfg -Target Running")
    assert i_pass < i_start, "the success stage must be set BEFORE the service start can throw"
    # The handler branches on it and withholds the re-run advice for that branch.
    handler = seg[seg.index("RECOVERY STATE: ROLLBACK_FAILED"):]
    i_branch = handler.index('closure assertion PASSED')
    assert "Do NOT re-run the rollback" in handler[i_branch:], (
        "the succeeded-restore branch must tell the operator NOT to re-run"
    )
    # The generic re-run advice must sit in a different branch, not unconditionally after.
    branch = handler[i_branch:handler.index("else {", i_branch)]
    assert "Deploy-PZ.ps1 -Rollback -Unit $UnitId" not in branch, (
        "the succeeded-restore branch must not print the re-run command"
    )


def test_policy_warns_about_legacy_units_before_the_rollback_commands():
    """Operators reach the Level 2 / Level 3 procedures first during an incident. The
    legacy-unit refusal must be stated THERE, not only in the explanation below them,
    and the recovery procedure must be concrete rather than an aspiration."""
    body = _read(POLICY)
    i_warn = body.index("Before using Level 2 or Level 3")
    i_level2 = body.index("### Level 2 —")
    i_level3 = body.index("### Level 3 —")
    assert i_warn < i_level2 < i_level3, "the legacy-unit warning must precede both rollback procedures"
    assert "Legacy unit recovery (operator procedure)" in body, (
        "a concrete recovery procedure must exist, not just a statement that recovery is operator-directed"
    )
    proc = body[body.index("Legacy unit recovery (operator procedure)"):]
    proc = proc[:proc.index("**Closure check.**")]
    # The one wrong value an operator would reach for first is named as wrong.
    assert "own** id prefix is the deployment SHA" in proc, (
        "the procedure must name the unit's own id prefix as the wrong source"
    )
    assert "version.pre.txt" in proc, "the procedure must name where the snapshot is written"
    assert "never to production's version marker" in proc, (
        "the procedure must be explicit that it does not write production's marker"
    )
    # The procedure tells the operator to trust evidence found inside a backup unit, so it
    # must first tell them to establish that the unit itself is untampered.
    assert "has not been altered since it was created" in proc, (
        "the procedure must require an integrity check of the unit before trusting its contents"
    )
    # The oldest unit has no preceding unit to derive a pre-deployment SHA from.
    assert "no** preceding unit exists" in proc, (
        "the procedure must cover the oldest unit, which has no preceding unit"
    )
    # A legacy unit throws out of provenance resolution BEFORE Assert-Authorization, so the
    # artifact minted for the refused attempt is normally still spendable.
    assert "unconsumed" in proc, (
        "the procedure must state the authorization state after the initial refusal"
    )


# ------------------------------------------------- production identity gate (pre-backup)
# New-BackupUnit records restored_sha by READING the version marker, not by re-deriving it
# from the bytes it backs up. A HYBRID production tree (marker says X, files partly Y) would
# therefore be backed up mislabelled X and a later rollback would stamp the wrong identity.
# Assert-ProductionMatchesRecordedSha closes that hole: it proves runtime bytes == recorded
# marker BEFORE the service is stopped or any backup is taken, and fails closed otherwise.
def _gate_segment(src: str) -> str:
    start = src.index("function Assert-ProductionMatchesRecordedSha")
    nxt = src.index("\nfunction ", start + 1)
    return src[start:nxt]


def test_production_identity_gate_exists():
    body = _read(DEPLOY_SCRIPT)
    assert "function Assert-ProductionMatchesRecordedSha" in body, (
        "a pre-backup production identity gate must exist so New-BackupUnit cannot mislabel a HYBRID tree"
    )


def test_identity_gate_runs_after_lock_and_before_service_stop():
    """The gate must hold the deploy lock (closing the read/backup TOCTOU) yet run before the
    service is stopped or a backup taken, so a mismatch aborts with production untouched."""
    body = _read(DEPLOY_SCRIPT)
    i_lock = body.index("Enter-DeployLock -Cfg $cfg")
    i_gate = body.index("Assert-ProductionMatchesRecordedSha -Cfg $cfg")
    i_stop = body.index("Set-ServiceState -Cfg $cfg -Target Stopped")
    i_bak = body.index("New-BackupUnit -Cfg $cfg")
    assert i_lock < i_gate < i_stop, (
        "the identity gate must run under the lock but BEFORE the service is stopped"
    )
    assert i_gate < i_bak, "the identity gate must run BEFORE any backup is minted"


def test_identity_gate_is_skipped_only_for_bootstrap():
    """A first-ever deploy has no prior tree to verify; every other deploy must run the gate.
    The call is guarded by exactly `if (-not $Bootstrap)` (the gate itself is wrapped in a
    try/catch that surfaces a RECOVERY STATE envelope, so it is no longer a one-liner)."""
    body = _read(DEPLOY_SCRIPT)
    i_guard = body.index("if (-not $Bootstrap) {")
    i_call = body.index("Assert-ProductionMatchesRecordedSha -Cfg $cfg", i_guard)
    i_else = body.index("Production identity gate skipped (-Bootstrap", i_guard)
    assert i_guard < i_call < i_else, (
        "the gate call must sit inside the `if (-not $Bootstrap)` branch, with the skip in the else"
    )


def test_identity_gate_sources_paths_from_config_only():
    """The gate must address production through config keys, never through a hardcoded path."""
    seg = _gate_segment(_read(DEPLOY_SCRIPT))
    for key in ("$Cfg.version_file", "$Cfg.source_root", "$Cfg.source_app",
                "$Cfg.runtime_app", "$Cfg.protected_dirs", "$Cfg.protected_files"):
        assert key in seg, f"the gate must read {key} from config, not a literal"


def test_identity_gate_fails_closed_on_every_unverifiable_state():
    """Absent/invalid marker, a marker SHA absent from the repo, a missing runtime tree, an
    unresolvable app subtree, and any file discrepancy must all throw BLOCKED - never proceed."""
    seg = _gate_segment(_read(DEPLOY_SCRIPT))
    # marker absent or not a single 40-hex SHA
    assert "is absent or does not hold a single 40-hex commit SHA" in seg
    # recorded SHA is not a commit in the source repo
    assert "which is not a commit in" in seg
    # the runtime application tree is missing entirely
    assert "does not exist; it cannot be verified against" in seg
    # core.autocrlf is neither 'true' nor 'input' -> the object-id compare is inconclusive
    assert "need 'true' or 'input'" in seg
    # any changed/missing/extraneous file
    assert "PRODUCTION IDENTITY MISMATCH" in seg
    # every failure path is a throw, and none of them is a warning that proceeds
    assert seg.count("throw \"BLOCKED:") >= 7, "each unverifiable state must throw, not warn"
    assert "Write-Warning" not in seg, "an identity failure must block, never soft-warn and proceed"


def test_identity_gate_compares_git_object_ids_not_raw_bytes():
    """Runtime files carry CRLF while committed blobs are LF; a raw byte/hash compare would
    false-mismatch every text file. The gate must compare git object ids so the autocrlf
    clean filter normalises both sides."""
    seg = _gate_segment(_read(DEPLOY_SCRIPT))
    assert "git -C $SRC ls-tree -r $recorded" in seg, "expected ids must come from ls-tree at the recorded SHA"
    assert "git -C $SRC hash-object" in seg, "runtime ids must come from hash-object (same clean filter)"
    assert "Get-FileHash" not in seg, "a raw content hash would false-mismatch on CRLF vs LF"


def test_identity_gate_excludes_protected_paths_on_both_sides():
    """storage/logs/.env/__pycache__ are runtime state, never part of the committed tree;
    excluding them on only one side would read as all-extraneous or all-missing."""
    seg = _gate_segment(_read(DEPLOY_SCRIPT))
    assert seg.count("$protDirs -contains $first") == 2, (
        "protected dirs must be excluded from BOTH the expected (ls-tree) and actual (runtime) sides"
    )
    assert seg.count("if ($isProt) { continue }") == 2, (
        "protected files must be excluded from BOTH sides"
    )


def test_identity_gate_is_read_only():
    """The gate is a pure inspection: it must not stop the service, sync, write the marker,
    mint a backup, or take a lock of its own (it runs inside the existing deploy lock)."""
    seg = _gate_segment(_read(DEPLOY_SCRIPT))
    # Strip the <# .. #> doc-comment: it explains the gate by NAMING the very writers the
    # gate must not call, which would false-positive a bare substring scan.
    body_only = re.sub(r"<#.*?#>", "", seg, count=1, flags=re.DOTALL)
    for forbidden in ("Set-ServiceState", "Invoke-Robocopy", "Write-VersionFile",
                      "New-BackupUnit", "New-ReleaseArtifact", "Enter-DeployLock"):
        assert forbidden not in body_only, f"the read-only identity gate must not call {forbidden}"


def test_backup_marker_read_is_documented_as_gate_dependent():
    """The 'restored_sha = Read-VersionMarker' line is only sound because the gate proved the
    bytes match the marker; that dependency must be recorded so the gate is not silently dropped."""
    body = _read(DEPLOY_SCRIPT)
    i_hard = body.index("HARDENING: reading restored_sha from the marker is only SOUND because")
    i_line = body.index("$restoredSha = if ($appPresent) { Read-VersionMarker", i_hard)
    assert i_hard < i_line, "the hardening note must sit directly above the marker read"
    seg = body[i_hard:i_line]
    assert "Assert-ProductionMatchesRecordedSha" in seg, "the note must name the gate it depends on"
    assert "Do NOT drop the gate call and keep this line" in seg, (
        "the note must forbid removing the gate while keeping the marker read"
    )


def test_identity_gate_requires_autocrlf_normalisation():
    """The object-id compare is only sound when git's clean filter normalises the runtime
    CRLF back to the committed LF, which happens only under core.autocrlf true/input. The
    gate must READ that setting and fail closed on anything else - otherwise every text file
    would false-mismatch and the gate would either block every deploy or (worse) be 'fixed'
    by weakening it to a raw compare."""
    seg = _gate_segment(_read(DEPLOY_SCRIPT))
    assert "git -C $SRC config core.autocrlf" in seg, "the gate must read core.autocrlf from the source repo"
    i_check = seg.index("config core.autocrlf")
    i_lstree = seg.index("git -C $SRC ls-tree -r $recorded")
    assert i_check < i_lstree, "the autocrlf pre-check must run BEFORE any object-id hashing"
    # the check must be a hard block, naming both acceptable values
    assert '$autocrlf -ne "true" -and $autocrlf -ne "input"' in seg
    assert "need 'true' or 'input'" in seg


def test_identity_gate_folds_protected_runtime_paths_into_exclusions():
    """protected_runtime_paths is a SEPARATE config key from protected_dirs/protected_files;
    a runtime path named only there must still be excluded, or it would read as extraneous and
    block a legitimate deploy. The gate must fold those leaves into the exclusion set."""
    seg = _gate_segment(_read(DEPLOY_SCRIPT))
    assert "$Cfg.protected_runtime_paths" in seg, "the gate must consult protected_runtime_paths"
    assert "$protDirs += $leaf" in seg, "each protected_runtime_paths leaf must join the exclusion set"


def test_identity_gate_block_surfaces_recovery_state():
    """A gate block is an operator-facing stop like the other deploy failure phases; it must
    print a RECOVERY STATE envelope stating production is untouched and no unit was minted,
    then re-throw so the lock's finally releases and the deploy aborts."""
    body = _read(DEPLOY_SCRIPT)
    assert "RECOVERY STATE: IDENTITY_GATE_BLOCKED" in body, (
        "a blocked identity gate must surface a RECOVERY STATE envelope, not a bare throw"
    )
    i_env = body.index("RECOVERY STATE: IDENTITY_GATE_BLOCKED")
    # the envelope must sit BEFORE the service is stopped, proving nothing was mutated
    i_stop = body.index("Set-ServiceState -Cfg $cfg -Target Stopped")
    assert i_env < i_stop, "the identity-gate recovery envelope must precede the service stop"
    seg = body[i_env:i_stop]
    assert "no rollback unit was minted" in seg, "the envelope must state no misleading unit was created"


def test_bootstrap_over_existing_tree_is_audited():
    """-Bootstrap legitimately skips the gate on a first-ever deploy, but using it against an
    EXISTING production tree skips the identity proof; that must at least emit an audit warning
    so a misused -Bootstrap cannot silently bypass the gate."""
    body = _read(DEPLOY_SCRIPT)
    i_skip = body.index("Production identity gate skipped (-Bootstrap")
    i_stop = body.index("Set-ServiceState -Cfg $cfg -Target Stopped")
    seg = body[i_skip:i_stop]
    assert "Test-Path $cfg.runtime_app" in seg, "the skip branch must detect an existing production tree"
    assert "Write-Warning" in seg and "AUDIT:" in seg, (
        "-Bootstrap over an existing tree must emit an AUDIT warning, not skip silently"
    )
