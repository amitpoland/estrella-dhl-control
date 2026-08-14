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
import subprocess
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


def _tracked(pathspec: str) -> list[str]:
    """Repository-TRACKED paths matching a pathspec, as forward-slash relatives.

    The deployment copies out of a git checkout, so "a file exists on this disk"
    is not the authority -- "this file is tracked in this repository" is. An
    untracked stray would deploy from one machine and from nowhere else.
    """
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z", "--", pathspec],
        capture_output=True, text=True, check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


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


def test_engine_files_cover_every_root_module_the_app_imports():
    """A root module the app imports but the deploy never copies is a startup crash.

    Repository-root modules live OUTSIDE service/app, so the application sync does
    not carry them; Invoke-EngineSync copies exactly config.engine_files. Until
    2026-08-02 that list held 2 of the 16 root modules service/app imports, so the
    other 14 were deployed NEVER -- they sat at whatever version a past manual copy
    left. description_grammar.py had drifted since 2026-06-08, and PR #1070 added
    three functions to it: the app tree would have imported symbols the runtime copy
    did not have, failing at import time in four modules loaded at startup.

    The suite cannot catch that by importing anything -- under pytest the repository
    root is on sys.path, so every root module is always current. Only the DEPLOYED
    layout splits app from engine. So this pin is a source fact: whatever service/app
    imports from the repository root must be in the list that gets copied.
    """
    cfg = json.loads(_read(CONFIG))
    root_modules = {p[:-3] for p in _tracked("*.py") if "/" not in p}
    app_files = [p for p in _tracked("service/app") if p.endswith(".py")]

    # An empty comparison set would make every assertion below pass while the
    # hazard they guard stands wide open. A rename, a worktree layout change or a
    # bad pathspec must fail LOUDLY here, not silently succeed.
    assert root_modules, "no tracked root modules resolved -- path authority is broken"
    assert len(app_files) > 100, (
        f"only {len(app_files)} tracked service/app modules resolved -- path "
        "authority is broken; this test cannot prove anything from an empty scan"
    )

    import_rx = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)
    imported = {}
    for rel in app_files:
        # Strip the BOM: three tracked app modules carry one, and a BOM sitting
        # ahead of column 0 hides a line-1 import from the ^ anchor.
        for name in import_rx.findall(_read(REPO / rel).lstrip("﻿")):
            if name in root_modules:
                imported.setdefault(name, rel)

    assert imported, (
        "service/app imports NO repository-root module at all -- implausible, so "
        "the import scan itself has stopped working"
    )

    declared = {n[:-3] for n in cfg["engine_files"] if n.endswith(".py")}
    missing = {m: src for m, src in sorted(imported.items()) if m not in declared}
    assert not missing, (
        "these repository-root modules are imported by service/app but are NOT in "
        "engine_files, so no deployment can ever update them in the runtime engine "
        "directory (first importer shown): " + json.dumps(missing, indent=2)
    )


def test_engine_files_are_tracked_root_modules():
    """Every engine_files entry must be a TRACKED repository-root .py file.

    Three ways this list can be wrong, each invisible until production:
      - a name with no file behind it: robocopy copies nothing and the absence
        surfaces only as a runtime ImportError;
      - a file present on the operator's disk but untracked: it would deploy from
        that one machine and from nowhere else, so the release would not be
        reproducible from the reviewed commit;
      - a path that escapes the repository root, which is how a test fixture, a
        doc, or a runtime storage file gets into the engine artifact. learning_store.json
        is the live example: it sits beside these modules in the runtime engine
        directory and is mutated at runtime, so copying it would destroy state.
    """
    cfg = json.loads(_read(CONFIG))
    engine_files = cfg["engine_files"]
    assert engine_files, "engine_files is empty -- no root module would ever deploy"

    tracked_root = {p for p in _tracked("*.py") if "/" not in p}
    assert tracked_root, "no tracked root modules resolved -- path authority is broken"

    offenders = {}
    for name in engine_files:
        if "/" in name or "\\" in name or name != Path(name).name:
            offenders[name] = "not a bare root-level filename"
        elif not name.endswith(".py"):
            offenders[name] = "not a Python module (the engine sync carries code only)"
        elif name not in tracked_root:
            offenders[name] = "not a tracked repository-root file"
    assert not offenders, (
        "engine_files must name only tracked repository-root Python modules: "
        + json.dumps(offenders, indent=2)
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


def test_set_service_state_surfaces_sc_exit_code():
    """sc Access Denied must not collapse into a generic service_wait timeout.

    Authority model (Deploy-PZ.ps1::Set-ServiceState):
      ALREADY_TARGET → no sc.exe
      SC_ACCEPTED → wait for target state
      SC_REJECTED → fail immediately with native exit
      ACCESS_DENIED (exit 5) → elevated Administrator guidance; never widen ACLs
      SC_ACCEPTED_BUT_STATE_TIMEOUT → post-accept transition stall (not Access Denied)

    Capture model prefers $LASTEXITCODE via `| Out-String` (not `2>&1`) under
    ErrorActionPreference=Stop so NativeCommandError cannot swallow the exit code.
    """
    body = _read(DEPLOY_SCRIPT)
    start = body.index("function Set-ServiceState")
    seg = body[start:]
    seg = seg[: seg.index("\nfunction ") if "\nfunction " in seg else len(seg)]

    # No discarded sc authority (the main-branch defect).
    assert not re.search(r"& sc\.exe[^`\n]*\|\s*Out-Null", seg), (
        "sc.exe must not be piped to Out-Null inside Set-ServiceState"
    )
    # Already-at-target short-circuit.
    assert "already $Target" in seg
    # Native exit captured without forcing stderr merge on the live sc call
    # (PS 5.1 + ErrorActionPreference=Stop: stderr-merge wraps NativeCommandError).
    assert "$LASTEXITCODE" in seg
    assert re.search(r"& sc\.exe \$verb \$svc\s*\|\s*Out-String", seg), (
        "sc.exe must pipe stdout to Out-String so $LASTEXITCODE remains readable"
    )
    assert not re.search(r"& sc\.exe[^`\n]*2>&1", seg), (
        "Do not capture the live sc.exe call with stderr-merge under ErrorActionPreference=Stop"
    )
    # ACCESS_DENIED guidance — elevation, never ACL widening.
    assert "exit 5" in seg or "$scCode -eq 5" in seg
    assert "elevated Administrator" in seg
    assert "do not widen service ACLs" in seg.lower() or "do not widen service ACLs" in seg
    assert "sc.exe" in seg and "sdset" not in seg.lower()
    assert "Set-ServiceAcl" not in seg and "AccessControl" not in seg
    # Reject path is immediate and distinct from post-accept timeout.
    assert "failed (exit $scCode)" in seg or "failed (exit" in seg
    assert "service remained $after" in seg or "service remained" in seg
    # Accepted command still waits for actual target; timeout names transition stall.
    assert "service_wait_seconds" in seg
    assert "did not reach $Target" in seg
    assert "returned success" in seg or "STOP_PENDING" in seg
    assert "not a discarded sc.exe failure" in seg


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
    assert "restored_sha = $restoredIdentity" in seg, "the pre-deployment SHA must be recorded"
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
    assert "$appPresent -and -not $restoredIdentity" in seg, (
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


def test_deploy_authorization_is_consumed_after_the_gate_and_before_each_write():
    """Issue #1097 ordering, pinned by index (position pins — structure is a review
    property). The helper burns the single-use jti the moment it allows, so the call's
    POSITION decides what a refusal costs: consumed at the top of the run, an
    IDENTITY_GATE_BLOCKED or lock refusal burns the operator's artifact; consumed after
    a write, that write would be unauthorized.

    The deploy flow has TWO consumption sites by design — one inside the runtime no-op
    branch immediately before its marker advance (the only write on that path), one on
    the main path immediately before the service stop. Both must sit after the lock and
    the identity gate; the no-op site must precede the marker write."""
    body = _read(DEPLOY_SCRIPT)
    i_lock = body.index("Enter-DeployLock -Cfg $cfg")
    i_gate = body.index("Assert-ProductionMatchesRecordedSha -Cfg $cfg")
    auth_needle = 'Assert-Authorization -Cfg $cfg -Sha $TargetSha -Action "deploy"'
    i_auth_noop = body.index(auth_needle)
    i_auth_main = body.index(auth_needle, i_auth_noop + 1)
    i_marker = body.index("Write-VersionFile -Cfg $cfg -Sha $TargetSha")
    i_stop = body.index("Set-ServiceState -Cfg $cfg -Target Stopped")
    assert i_lock < i_gate < i_auth_noop, (
        "authorization must be consumed only AFTER the lock is held and the identity gate "
        "has had its chance to refuse — a zero-write refusal must not burn the artifact"
    )
    assert i_auth_noop < i_marker, (
        "the no-op branch's consumption must precede its marker advance — that advance is "
        "a production write and must never run unauthorized"
    )
    assert i_marker < i_auth_main < i_stop, (
        "the main path's consumption must sit after the no-op branch and immediately "
        "before the service stop, the first mutation of the ordinary deploy"
    )


def test_reconcile_authorization_is_consumed_after_proof1_and_before_the_stop():
    """Issue #1097 ordering for reconcile. PROOF 1 failing is this mode's most likely
    refusal — it exists because production identity is in doubt — and under the old
    ordering that refusal burned the artifact. Auth must sit after PROOF 1 and before
    the service stop; PROOF 2 stays post-stop by design (TOCTOU closure at backup-mint
    time), so this pin deliberately does not constrain auth against PROOF 2."""
    seg = _reconcile_segment(_read(DEPLOY_SCRIPT))
    proofs = [m.start() for m in re.finditer(
        re.escape("Assert-ProductionMatchesRecordedSha -Cfg $Cfg -ExpectSha $From"), seg)]
    i_auth = seg.index('Assert-Authorization -Cfg $Cfg -Sha $To -Action "reconcile"')
    i_stop = seg.index("Set-ServiceState -Cfg $Cfg -Target Stopped")
    assert proofs[0] < i_auth < i_stop, (
        "reconcile must prove the runtime is -FromSha BEFORE consuming the authorization, "
        "and consume BEFORE the service stop — the first operational mutation"
    )


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
    i_line = body.index("elseif ($appPresent) { Read-VersionMarker", i_hard)
    assert i_hard < i_line, "the hardening note must sit directly above the marker read"
    seg = body[i_hard:i_line]
    assert "Assert-ProductionMatchesRecordedSha" in seg, "the note must name the gate it depends on"
    assert "Do NOT drop the gate call and keep this line" in seg, (
        "the note must forbid removing the gate while keeping the marker read"
    )
    # The reconcile override is the ONE case where the marker is deliberately not consulted.
    # It is safe only because the gate proved the runtime against the SUPPLIED identity, which
    # is derived from the bytes rather than claimed about them - and it is dangerous the moment
    # a caller can assert it without that proof. Both halves must be written down, next to the
    # line, or a later reader will take the override for a plain caller-supplied hint.
    assert "RECONCILE EXCEPTION" in seg, (
        "the marker-read line must document why -RestoredSha is allowed to bypass the marker"
    )
    assert "proved against the runtime bytes" in seg, (
        "the reconcile note must state that the supplied identity was PROVED, not asserted"
    )


def test_backup_restored_sha_override_is_shape_validated_and_reconcile_only():
    """-RestoredSha is the only supported override of marker-derived provenance. If it could be
    set to an unresolvable value, or supplied by an ordinary deploy, the unit would carry a
    confident-looking lie - strictly worse than the missing-provenance case the resolver already
    fails closed on."""
    seg = _backup_segment(_read(DEPLOY_SCRIPT))
    assert "[string]$RestoredSha" in seg, "New-BackupUnit must accept the override as a typed parameter"
    assert "$RestoredSha -notmatch $script:SHA_RX" in seg, (
        "the override must be shape-validated against the SHA pattern before it is recorded"
    )
    i_guard = seg.index("$RestoredSha -notmatch $script:SHA_RX")
    i_use = seg.index("$restoredIdentity = if ($RestoredSha)")
    assert i_guard < i_use, "the shape check must run before the value reaches the unit metadata"
    assert "Invoke-Reconcile" in seg, (
        "the parameter doc must name the single caller permitted to use it"
    )


def test_backup_resolved_local_never_shadows_the_restored_sha_parameter():
    """PowerShell variable names are case-INSENSITIVE, so a local named $restoredSha
    silently OVERWRITES the $RestoredSha parameter. That is not hypothetical: it shipped, and
    it made every ordinary deploy record mode='reconcile' (because $unitMode then read the
    resolved value) and made the no-marker case record restored_sha as '' rather than null
    (because the parameter's [string] constraint coerces an assigned $null). Both defects are
    untruthful backup metadata - the exact failure this gate exists to prevent. The local must
    keep a name that cannot fold onto the parameter's."""
    seg = _backup_segment(_read(DEPLOY_SCRIPT))
    # Comments are stripped first: the function documents this very collision by NAMING it, and
    # that prose must not be what trips the check. Everything after an unquoted '#' is comment in
    # PowerShell, so dropping it leaves exactly the text the parser would execute.
    code = "\n".join(line.split("#", 1)[0] for line in seg.splitlines())
    # Matched case-insensitively, exactly as PowerShell itself resolves the name.
    shadow = re.search(r"\$restoredsha\s*=", code, re.IGNORECASE)
    assert shadow is None, (
        f"'{shadow.group(0).strip() if shadow else ''}' assigns to the $RestoredSha parameter "
        "itself: the caller's value is lost, and every later read of the parameter returns the "
        "resolved value instead"
    )
    # ...and the collision must stay documented, so a later tidy-up cannot reintroduce it.
    assert "case-INSENSITIVE" in seg, (
        "the local's name is load-bearing; the reason must be stated where the local is assigned"
    )
    assert "$unitMode = if ($RestoredSha)" in seg, (
        "the unit label must be decided from the PARAMETER (was this an override?), never from "
        "the resolved identity (which is non-null on any ordinary deploy that has a marker)"
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


def test_bootstrap_over_existing_tree_fails_closed():
    """-Bootstrap legitimately skips the gate on a first-ever deploy. Against an EXISTING,
    NON-EMPTY production tree it is the one remaining way to reach New-BackupUnit without
    proving identity - which mints a unit labelled with the old marker over current bytes.
    An audit warning was insufficient because a warning still proceeds; the branch must
    THROW, and must point the operator at the reconciliation mode instead."""
    body = _read(DEPLOY_SCRIPT)
    i_else = body.index("Production identity gate skipped (-Bootstrap")
    i_stop = body.index("Set-ServiceState -Cfg $cfg -Target Stopped")
    # the guard runs BEFORE the skip announcement, so search the whole bootstrap branch
    i_branch = body.rindex("else {", 0, i_else)
    seg = body[i_branch:i_stop]
    assert "Test-Path $cfg.runtime_app" in seg, "the bootstrap branch must detect an existing production tree"
    assert "-Recurse -File" in seg, (
        "existence alone is not the test - an existing but genuinely EMPTY tree may bootstrap, "
        "so the branch must count files"
    )
    assert "throw \"BLOCKED:" in seg, (
        "-Bootstrap over an existing non-empty tree must FAIL CLOSED, not warn and continue"
    )
    assert "Write-Warning" not in seg, (
        "a warning here is a bypass with extra steps; the branch must throw"
    )
    assert "-Reconcile" in seg, (
        "the block must name the authorised repair path (-Reconcile), or operators will "
        "reach for -Bootstrap again"
    )


# ------------------------------------------------------- operator-authorised reconciliation
#
# Reconcile is the only mode that runs against a runtime the identity gate has already
# refused. Every guarantee below exists because the alternative - an operator repairing the
# drift by hand - is precisely how the drift was created. These tests pin the ORDER of the
# proof, the backup and the marker write, because the order is the whole security property:
# any rearrangement produces a confidently-labelled backup of bytes nobody proved.

def _reconcile_segment(body: str) -> str:
    start = body.index("function Invoke-Reconcile")
    rest = body[start + len("function Invoke-Reconcile"):]
    end = rest.index("\nfunction ") if "\nfunction " in rest else len(rest)
    return rest[:end]


def test_reconcile_mode_exists_and_is_dispatched():
    body = _read(DEPLOY_SCRIPT)
    assert "function Invoke-Reconcile" in body, (
        "a runtime whose marker is false has no authorised repair path without this mode"
    )
    for p in ("[switch]$Reconcile", "[string]$FromSha", "[string]$ToSha"):
        assert p in body, f"the reconcile interface requires {p}"
    assert "if ($Reconcile) { Invoke-Reconcile -Cfg $cfg -From $FromSha -To $ToSha; return }" in body, (
        "Invoke-Deploy must dispatch -Reconcile explicitly and return, never fall through to "
        "the ordinary deploy path"
    )


def test_reconcile_authorization_binds_action_and_both_shas():
    """A generic permission to 'reconcile' is insufficient: an artifact minted for one drift
    must not repair a different one. The helper signs the ordered pair, and the script must
    actually pass both halves of it."""
    seg = _reconcile_segment(_read(DEPLOY_SCRIPT))
    assert 'Assert-Authorization -Cfg $Cfg -Sha $To -Action "reconcile" -UnitScope $Scope -SourceSha $From' in seg, (
        "reconcile must authorise the ORDERED PAIR (from -> to), not just the target"
    )
    helper = _read(REPO / ".claude" / "hooks" / "deploy_authorization.py")
    assert '"from_sha"' in helper.split("_SIGNED_FIELDS")[1].split(")")[0], (
        "from_sha must be a SIGNED field; an unsigned direction is decoration an attacker can edit"
    )
    assert "reconcile requires from_sha" in helper, "reconcile without from_sha must DENY"
    assert "nothing to reconcile" in helper, "from_sha == to_sha must DENY"
    assert "from_sha is only meaningful for reconcile" in helper, (
        "a from_sha supplied for deploy/rollback must DENY rather than being ignored"
    )


def test_reconcile_proves_identity_before_and_again_at_backup_time():
    """Guarantees 3 and 4. One proof is not enough: between the first proof and the backup the
    service is stopped and an artifact staged, and a unit is a provenance record that must be
    minted from a runtime proven AT THAT MOMENT."""
    seg = _reconcile_segment(_read(DEPLOY_SCRIPT))
    proofs = [m.start() for m in re.finditer(
        re.escape("Assert-ProductionMatchesRecordedSha -Cfg $Cfg -ExpectSha $From"), seg)]
    assert len(proofs) == 2, (
        f"expected exactly two FromSha proofs (before any mutation, and immediately before the "
        f"backup); found {len(proofs)}"
    )
    i_lock = seg.index("Enter-DeployLock -Cfg $Cfg")
    i_stop = seg.index("Set-ServiceState -Cfg $Cfg -Target Stopped")
    i_backup = seg.index("New-BackupUnit -Cfg $Cfg")
    # guarantee 2: the whole operation is serialised
    assert i_lock < proofs[0], "the first proof must run under the deployment lock"
    # guarantee 3: proven before anything is stopped or written
    assert proofs[0] < i_stop, "the runtime must be proved before the service is stopped"
    # guarantee 4: re-proven with nothing in between that could have changed it
    assert i_stop < proofs[1] < i_backup, (
        "the second proof must sit between the stop and the backup, closing the window in which "
        "the runtime could change after being proved"
    )


def test_reconcile_backup_records_the_proved_identity_not_the_false_marker():
    """Guarantee 5. The marker is the artefact being repaired; copying it into the unit would
    record the very lie the operation exists to correct, and would then disagree with
    version.pre.txt - which Resolve-RestoredSha treats as unresolved provenance, permanently
    refusing every rollback to this unit."""
    body = _read(DEPLOY_SCRIPT)
    seg = _reconcile_segment(body)
    assert "New-BackupUnit -Cfg $Cfg -Sha $To -UnitScope $Scope -RestoredSha $From" in seg, (
        "the reconcile backup must be labelled: deployment_sha = target, restored content = FromSha"
    )
    bak = _backup_segment(body)
    i_meta = bak.index("restored_sha = $restoredIdentity")
    i_pre = bak.index("version.pre.txt")
    assert i_meta < i_pre, "unit.json is written first, then its corroborating marker snapshot"
    # both corroborating sources must carry the SAME proved value, in the same byte shape
    assert "$appPresent -and $RestoredSha" in bak, (
        "the reconcile branch must snapshot the PROVED identity into version.pre.txt"
    )
    assert "WriteAllText((Join-Path $bak \"version.pre.txt\"), $RestoredSha" in bak, (
        "version.pre.txt must hold the proved SHA, written in the same byte shape Write-VersionFile "
        "emits, so both provenance sources parse identically"
    )
    assert 'mode = $unitMode' in bak and '"reconcile" } else { "deploy"' in bak, (
        "a backup directory must let an auditor tell a routine pre-deploy snapshot from one taken "
        "while repairing a false marker"
    )


def test_reconcile_verifies_the_target_before_stamping_the_marker():
    """Guarantees 6, 7 and 8. The manifest proves the tree equals the ARTIFACT; only the gate
    proves it equals the COMMIT. Stamping first would re-create the defect under a new SHA."""
    seg = _reconcile_segment(_read(DEPLOY_SCRIPT))
    i_converge = seg.index("Invoke-Converge -Cfg $Cfg -ArtifactPath $art")
    i_manifest = seg.index('-What "reconciled application"')
    i_verify = seg.index("Assert-ProductionMatchesRecordedSha -Cfg $Cfg -ExpectSha $To")
    i_stamp = seg.index("Write-VersionFile -Cfg $Cfg -Sha $To")
    i_start = seg.index("Set-ServiceState -Cfg $Cfg -Target Running")
    assert i_converge < i_manifest < i_verify < i_stamp < i_start, (
        "order must be converge -> manifest -> prove against ToSha -> stamp marker -> start service"
    )
    assert "$art = New-ReleaseArtifact -Cfg $Cfg -Sha $To" in seg, (
        "convergence must use an artifact staged from the approved target only"
    )
    assert seg.count("Write-VersionFile") == 1, (
        "the marker must be written exactly once, at the end, after verification"
    )


def test_reconcile_failure_leaves_the_old_marker_and_no_trusted_target_label():
    """Guarantee 9. A failure before final verification must not advertise the target, and must
    not leave behind a unit whose label the operator would trust."""
    seg = _reconcile_segment(_read(DEPLOY_SCRIPT))
    assert "RECOVERY STATE: RECONCILE_BLOCKED_NO_WRITE" in seg, (
        "a pre-write failure must be reported as such - the operator's next action differs "
        "entirely from a mid-write failure"
    )
    assert "RECOVERY STATE: RECONCILE_FAILED" in seg, "a mid-write failure needs its own envelope"
    i_nowrite = seg.index("RECOVERY STATE: RECONCILE_BLOCKED_NO_WRITE")
    i_failed = seg.index("RECOVERY STATE: RECONCILE_FAILED")
    assert "unchanged" in seg[i_nowrite:i_nowrite + 900], (
        "the pre-write envelope must state that production and the marker are unchanged"
    )
    assert "-Bootstrap" in seg[i_nowrite:i_nowrite + 900], (
        "the pre-write envelope must warn against reaching for -Bootstrap, which is exactly what "
        "an operator blocked by a failed identity proof will otherwise try next"
    )
    assert "was NOT advanced" in seg[i_failed:], (
        "the mid-write envelope must state the marker still does not advertise the target"
    )
    assert "-Rollback -Unit" in seg[i_failed:], (
        "the mid-write envelope must give the exact recovery command for the unit just minted"
    )
    assert "Exit-DeployLock -Cfg $Cfg" in seg, "the lock must be released on every path"
    assert "finally { Exit-DeployLock -Cfg $Cfg }" in seg, (
        "release must be in a finally block, or a throw strands the lock and blocks the recovery "
        "rollback the envelope just told the operator to run"
    )


def test_reconcile_refuses_ambiguous_or_unproven_invocations():
    """The mode's whole value is that it proves what production is. Every argument shape that
    would let it skip, guess, or double up on that claim must fail closed."""
    body = _read(DEPLOY_SCRIPT)
    seg = _reconcile_segment(body)
    for needle, why in (
        ("$From -notmatch $script:SHA_RX", "FromSha must be a full 40-hex SHA"),
        ("$To -notmatch $script:SHA_RX", "ToSha must be a full 40-hex SHA"),
        ("$From -eq $To", "identical SHAs mean there is nothing to reconcile"),
        ("if ($Bootstrap)", "-Bootstrap would discard the proof this mode exists to make"),
        ("if ($ReviewedSHA)", "two candidate targets in one invocation is unresolvable ambiguity"),
    ):
        assert needle in seg, f"reconcile must refuse: {why}"
    assert seg.count('throw "BLOCKED:') >= 8, (
        "every precondition must throw, not warn"
    )
    # the source tree must be certified at the target, and reconcile must NEVER move HEAD -
    # fast-forwarding the reviewed tree mid-repair makes it impossible to say afterwards which
    # tree the operator actually reviewed
    assert "$head -ne $To" in seg, "reconcile must require the source already checked out at ToSha"
    assert "merge --ff-only" not in seg, "reconcile must not move HEAD"
    assert "merge-base --is-ancestor $To origin/main" in seg, (
        "reconcile is a repair path, not a way to ship an unreviewed commit past the deploy "
        "preconditions"
    )
    # and the flags must not be silently accepted anywhere else
    assert "-FromSha / -ToSha are only valid with -Reconcile" in body, (
        "supplying a direction to an ordinary deploy must throw; ignoring it would let an "
        "operator believe a proof ran when it did not"
    )


# --------------------------------------------------------------- privilege / UAC
def _elevation_segment(body: str) -> str:
    start = body.index("function Request-AdministratorElevationIfNeeded")
    rest = body[start + 1 :]
    end = rest.index("\nfunction ") if "\nfunction " in rest else len(rest)
    return body[start : start + 1 + end]


def _arglist_segment(body: str) -> str:
    start = body.index("function Get-DeployElevationArgumentList")
    rest = body[start + 1 :]
    end = rest.index("\nfunction ") if "\nfunction " in rest else len(rest)
    return body[start : start + 1 + end]


def test_administrator_predicate_uses_windows_token_authority():
    """Privilege must come from the Windows principal token, not username heuristics."""
    body = _read(DEPLOY_SCRIPT)
    assert "function Test-IsAdministrator" in body
    seg = body[body.index("function Test-IsAdministrator") :]
    seg = seg[: seg.index("\nfunction ")]
    assert "WindowsIdentity]::GetCurrent()" in seg
    assert "WindowsPrincipal" in seg
    assert "WindowsBuiltInRole]::Administrator" in seg
    assert "whoami" not in seg.lower()
    assert "$env:USERNAME" not in seg
    assert "Environment]::UserName" not in seg
    assert "IsInRole" in seg


def test_elevation_runs_before_any_authorization_mint_or_consume():
    """Core invariant: privilege proof/self-elevation precedes mint/consume on every write path.

    Control-flow pin (not whole-file index): Invoke-Deploy elevates before dispatching into
    Release/Rollback/Reconcile/DeployMain. Match `function Invoke-Deploy {` exactly so
    Invoke-DeployMain cannot steal the index.
    """
    body = _read(DEPLOY_SCRIPT)
    i_elev_fn = body.index("function Request-AdministratorElevationIfNeeded")
    i_mint_fn = body.index("function Invoke-ReleaseMint")
    assert i_elev_fn < i_mint_fn, "elevation helpers must be defined before mint"

    i_deploy = body.index("function Invoke-Deploy {")
    deploy_seg = body[i_deploy:]
    # Truncate before any trailing content is irrelevant; segment is the function body.
    i_elev_call = deploy_seg.index("Request-AdministratorElevationIfNeeded")
    i_cfg = deploy_seg.index("Get-DeployConfig")
    i_release = deploy_seg.index("Invoke-ReleaseFlow")
    i_rollback = deploy_seg.index("Invoke-Rollback")
    i_reconcile = deploy_seg.index("Invoke-Reconcile")
    i_main = deploy_seg.index("Invoke-DeployMain")
    assert i_elev_call < i_cfg < i_release, (
        "Invoke-Deploy must elevate BEFORE loading config / entering ReleaseFlow"
    )
    assert i_elev_call < i_rollback and i_elev_call < i_reconcile and i_elev_call < i_main

    elev = _elevation_segment(body)
    # Comments may name mint/auth as forbidden; executable calls must be absent.
    assert "Invoke-ReleaseMint -Cfg" not in elev
    assert "Assert-Authorization -Cfg" not in elev
    assert "exit [int]$proc.ExitCode" in elev


def test_non_admin_release_does_not_mint_or_stop_in_unelevated_parent():
    """Unelevated path must exit after UAC child; it must not call mint/stop itself."""
    seg = _elevation_segment(_read(DEPLOY_SCRIPT))
    assert "Start-Process" in seg and "-Verb RunAs" in seg
    assert "exit [int]$proc.ExitCode" in seg
    assert "Invoke-ReleaseMint -Cfg" not in seg
    assert "Assert-Authorization -Cfg" not in seg
    assert "Set-ServiceState -Cfg" not in seg
    assert "sc.exe" not in seg
    assert "FAILED SAFE: Administrator elevation was declined" in seg
    assert "Authorization not minted" in seg
    assert "Production untouched" in seg


def test_whatif_skips_elevation():
    body = _read(DEPLOY_SCRIPT)
    elev = _elevation_segment(body)
    assert "if ($script:PlanOnly) { return }" in elev
    deploy = body[body.index("function Invoke-Deploy {") :]
    assert "Request-AdministratorElevationIfNeeded" in deploy
    assert "-WhatIf: PLAN ONLY" in deploy
    assert re.search(
        r"if \(\$script:PlanOnly\) \{[\s\S]*?-WhatIf: PLAN ONLY[\s\S]*?\}\s*else \{\s*"
        r"# Privilege BEFORE mint[\s\S]*?Request-AdministratorElevationIfNeeded",
        deploy,
    ), "elevation must run only in the non-WhatIf else branch"


def test_elevated_process_does_not_relaunch():
    """Already-Administrator returns; one UAC transition maximum."""
    seg = _elevation_segment(_read(DEPLOY_SCRIPT))
    assert "if (Test-IsAdministrator)" in seg
    assert "Administrator proven" in seg
    i_admin = seg.index("if (Test-IsAdministrator)")
    i_start = seg.index("Start-Process")
    assert i_admin < i_start
    assert "return" in seg[i_admin:i_start]


def test_elevation_preserves_scope_and_mode_switches():
    """App|Engine|Both and canonical modes survive elevation; no arbitrary injection."""
    seg = _arglist_segment(_read(DEPLOY_SCRIPT))
    for flag in (
        "-Release",
        "-Rollback",
        "-Reconcile",
        "-Scope",
        "-ReviewedSHA",
        "-Unit",
        "-FromSha",
        "-ToSha",
        "-Bootstrap",
        "-DeployLog",
    ):
        assert f"tokens.Add('{flag}')" in seg, flag
    assert "tokens.Add($Scope)" in seg
    assert "$ReviewedSHA -notmatch $script:SHA_RX" in seg
    assert "$Unit -notmatch $script:UNIT_RX" in seg
    assert "$FromSha -notmatch $script:SHA_RX" in seg
    assert "$ToSha -notmatch $script:SHA_RX" in seg
    assert "Deploy-PZ.ps1" in seg
    assert "tokens.Add('-WhatIf')" not in seg
    assert "tokens.Add('-NoRun')" not in seg
    assert "schtasks" not in seg.lower()
    assert "sdset" not in seg.lower()
    assert "Assert-CanonicalDeployLogPath" in seg


def test_elevation_requires_user_scoped_auth_env_before_uac():
    """Process-only $env:PZ_DEPLOY_AUTH_* must not reach UAC/mint (RunAs drops it)."""
    body = _read(DEPLOY_SCRIPT)
    assert "function Assert-DeployAuthEnvSurvivesElevation" in body
    elev = _elevation_segment(body)
    assert "Assert-DeployAuthEnvSurvivesElevation" in elev
    assert "PZ_DEPLOY_AUTH_KEY_FILE" in body
    assert "PZ_DEPLOY_AUTH_DIR" in body
    assert "process-scoped" in body.lower() or "Process" in body
    i_assert = elev.index("Assert-DeployAuthEnvSurvivesElevation")
    i_start = elev.index("Start-Process")
    assert i_assert < i_start


def test_uac_decline_message_distinguishes_cancel_from_launch_failure():
    elev = _elevation_segment(_read(DEPLOY_SCRIPT))
    assert "elevation was declined" in elev
    assert "elevation failed" in elev
    assert "(?i)cancel" in elev or "-match '(?i)cancel'" in elev


def test_elevated_transcript_is_canonical_under_localappdata():
    body = _read(DEPLOY_SCRIPT)
    assert "function Assert-CanonicalDeployLogPath" in body
    assert r"PZ-deploy\logs" in body or "PZ-deploy\\logs" in body
    elev = _elevation_segment(body)
    assert "elevated Deploy-PZ transcript" in elev
    assert "Start-Transcript" in body
    assert "Stop-Transcript" in body


def test_canonical_deploy_log_path_avoids_ps51_splitpath_literalpath_leaf():
    """PR #1237: Windows PowerShell 5.1 raises AmbiguousParameterSet for
    `Split-Path -LiteralPath <x> -Leaf`, which blocked UAC self-elevation before mint.

    Assert-CanonicalDeployLogPath (and the Deploy-PZ.ps1 leaf identity check used for
    elevation) must use [System.IO.Path]::GetFileName — never Split-Path -LiteralPath -Leaf.
    """
    body = _read(DEPLOY_SCRIPT)
    start = body.index("function Assert-CanonicalDeployLogPath")
    rest = body[start + 1 :]
    end = rest.index("\nfunction ") if "\nfunction " in rest else len(rest)
    seg = body[start : start + 1 + end]
    assert "[System.IO.Path]::GetFileName($LogFilePath)" in seg, (
        "canonical log leaf must use IO.Path::GetFileName (PS 5.1-safe)"
    )
    assert not re.search(r"Split-Path\s+-LiteralPath\s+\$LogFilePath\s+-Leaf", seg), (
        "Split-Path -LiteralPath -Leaf is AmbiguousParameterSet on Windows PowerShell 5.1"
    )
    # Elevation script-identity leaf check (same defect class).
    arg = _arglist_segment(body)
    assert "[System.IO.Path]::GetFileName($scriptPath)" in arg
    assert not re.search(r"Split-Path\s+-LiteralPath\s+\$scriptPath\s+-Leaf", arg)
    # Whole deploy authority: no remaining LiteralPath+Leaf combo.
    assert not re.search(r"Split-Path\s+-LiteralPath\s+[^\n]+-Leaf", body), (
        "no Split-Path -LiteralPath … -Leaf may remain in Deploy-PZ.ps1 on PS 5.1 hosts"
    )


def test_elevation_argument_builder_refuses_injection_via_path_or_blob():
    """Argument list is structural tokens + quoting helper; no unvalidated command blob."""
    body = _read(DEPLOY_SCRIPT)
    assert "function ConvertTo-ProcessArgumentString" in body
    elev = _elevation_segment(body)
    assert "ConvertTo-ProcessArgumentString" in elev
    assert "Get-DeployElevationArgumentList" in elev
    assert "cmd.exe" not in elev.lower()
    assert "Invoke-Expression" not in elev
    assert re.search(r"(?i)(?<![A-Za-z])iex(?![A-Za-z])", elev) is None


def test_no_second_deploy_authority_or_bat_as_architecture():
    """Self-elevation stays inside Deploy-PZ.ps1; no Deploy-PZ-v2 / permanent BAT launcher."""
    body = _read(DEPLOY_SCRIPT)
    assert "Deploy-PZ-v2" not in body
    elev = _elevation_segment(body)
    assert ".bat" not in elev.lower()
    assert "schtasks" not in elev.lower()
    guard = _read(GUARD)
    assert "Deploy-PZ.ps1" in guard


def test_deploy_md_documents_uac_one_command_contract():
    md = _read(REPO / ".claude" / "commands" / "deploy.md")
    assert "Deploy-PZ.ps1 -Release" in md
    assert "UAC" in md
    assert "per-PR BAT" in md
    assert "never elevates" in md
