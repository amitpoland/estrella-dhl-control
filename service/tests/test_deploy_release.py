"""Pins for the one-command -Release mode of the deployment authority.

-Release exists so the operator's normal workflow is a single command with no SHA
choreography, no mode selection, and no separate signing ceremony -- while keeping
every protection that matters. These pins hold the load-bearing invariants:

  1. FOUR HARD BLOCKERS, no more: gate evidence not GO; runtime identity unprovable;
     backup/copy verification failure (enforced by the inner paths); service unhealthy
     after deploy (closure). CI is deliberately not consulted.
  2. AUTHORIZATION ORDERING: the single-use signed artifact is minted and consumed
     only AFTER the read-only identity proof, under the lock, immediately before the
     first production write -- in every mode. A failed read-only check must never
     cost a jti.
  3. ONE FINAL STATUS: exactly one of ALREADY CURRENT / DEPLOYED / ROLLED BACK /
     FAILED SAFE, printed once.
  4. NO SECOND AUTHORITY: -Release is a flow inside Deploy-PZ.ps1, reusing the same
     lock, gate, artifact, backup, rollback and closure functions as the manual modes.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / ".claude" / "deploy" / "windows_prod_v2.json"
DEPLOY_SCRIPT = REPO / ".claude" / "deploy" / "Deploy-PZ.ps1"
GATE_EVIDENCE = REPO / ".claude" / "hooks" / "gate_evidence.py"

_BODY = DEPLOY_SCRIPT.read_text(encoding="utf-8")
_SHA_A = "a" * 40

AGENTS = [
    "deploy_git_diff_reviewer", "deploy_backend_impact_reviewer",
    "deploy_persistence_storage_reviewer", "deploy_security_reviewer",
    "deploy_qa_reviewer", "deploy_release_manager", "deploy_lead_coordinator",
]


def _block(name: str) -> str:
    """The source text of one top-level function."""
    start = _BODY.index(f"function {name} ")
    nxt = _BODY.find("\nfunction ", start)
    return _BODY[start:nxt if nxt != -1 else len(_BODY)]


# ---------------------------------------------------------------- structure
def test_release_is_a_flow_inside_the_single_authority():
    assert "[switch]$Release" in _BODY, "-Release must be a parameter of the one deploy script"
    assert "function Invoke-ReleaseFlow " in _BODY
    flow = _block("Invoke-ReleaseFlow")
    # Reuse, not reimplementation: the flow must drive the same inner functions.
    for fn in ("Invoke-Preflight", "Assert-ReviewedTarget",
               "Assert-ProductionMatchesRecordedSha", "Test-RuntimeUnchanged",
               "Invoke-DeployMain", "Invoke-Reconcile", "Invoke-Rollback"):
        assert fn in flow, f"-Release must reuse {fn}, never a parallel implementation"


def test_release_refuses_manual_overrides():
    entry = _block("Invoke-Deploy")
    assert "-Release takes no target, mode, or direction parameters" in entry, (
        "-Release combined with -ReviewedSHA/-Reconcile/-Rollback/-FromSha/-ToSha "
        "must be refused, not silently reinterpreted"
    )


def test_release_final_statuses_are_exactly_four():
    flow = _block("Invoke-ReleaseFlow")
    for status in ("ALREADY CURRENT", "DEPLOYED", "ROLLED BACK", "FAILED SAFE"):
        assert status in flow, f"final status {status!r} must exist"
    assert flow.count('RELEASE RESULT: $status') == 1, (
        "the final status must be printed exactly once, from one place"
    )


# ---------------------------------------------------------------- blocker 1: evidence
def test_release_validates_evidence_before_probing_minting_or_locking():
    flow = _block("Invoke-ReleaseFlow")
    i_evidence = flow.index("hard blocker 1/4")
    i_probe = flow.index("Assert-ProductionMatchesRecordedSha")
    i_mint = flow.index("Invoke-ReleaseMint")
    i_lock = flow.index("Enter-DeployLock")
    assert i_evidence < i_probe, "evidence must be validated before any identity probe"
    assert i_evidence < i_mint, "evidence must be validated before any mint"
    assert i_evidence < i_lock, "evidence must be validated before the lock"


def test_release_target_is_origin_main_bound_to_evidence():
    """-Release resolves origin/main itself -- but the resolved SHA is bound to the
    seven-agent evidence (validated for exactly that SHA) and to the reviewed-target
    discipline (Assert-ReviewedTarget), so nothing unreviewed can ship. This is the
    deliberate, evidence-bound exception to 'the operator types the SHA'."""
    flow = _block("Invoke-ReleaseFlow")
    assert "rev-parse origin/main" in flow
    assert "$Cfg.gate_evidence_file $target" in flow, (
        "the evidence must be validated against the resolved target, not a typed SHA"
    )
    assert "Assert-ReviewedTarget -Cfg $Cfg -Sha $target" in flow


def test_config_names_the_standard_evidence_path():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert cfg.get("gate_evidence_file"), "config must carry gate_evidence_file"
    assert "PZ-secrets" in cfg["gate_evidence_file"], (
        "the evidence lives outside the repository, beside the authorization store"
    )
    assert '"gate_evidence_file"' in _BODY, (
        "Get-DeployConfig must require the key so a missing path fails closed"
    )


# ---------------------------------------------------------------- blocker 2: identity
def test_release_identity_gate_refuses_unprovable_runtime():
    flow = _block("Invoke-ReleaseFlow")
    assert "hard blocker 2/4" in flow
    assert "refuses to write over an unproven tree" in flow
    # The marker is evidence, not authority: it appears as a probe candidate only.
    assert "$marker" in flow and "never authority" in flow


# ---------------------------------------------------------------- ordering
def test_authorization_consumed_after_identity_gate_in_ordinary_deploy():
    """A failed read-only identity check must never consume a single-use jti."""
    main = _block("Invoke-DeployMain")
    i_gate = main.index("Assert-ProductionMatchesRecordedSha")
    i_auth = main.index("Assert-Authorization")
    i_stop = main.index("Set-ServiceState -Cfg $cfg -Target Stopped")
    assert i_gate < i_auth, "identity gate must run before the authorization is consumed"
    assert i_auth < i_stop or main.index("Assert-Authorization", i_auth + 1) < i_stop, (
        "authorization must still be consumed before the first mutation (service stop)"
    )


def test_authorization_consumed_after_proof_in_reconcile():
    rec = _block("Invoke-Reconcile")
    i_proof = rec.index("Assert-ProductionMatchesRecordedSha -Cfg $Cfg -ExpectSha $From")
    # The executable call, not a comment that merely names the function.
    i_auth = rec.index("Assert-Authorization -Cfg $Cfg -Sha $To")
    i_stop = rec.index("Set-ServiceState -Cfg $Cfg -Target Stopped")
    assert i_proof < i_auth < i_stop, (
        "reconcile must prove the runtime is -FromSha BEFORE consuming the pair-bound "
        "authorization, and consume it before the service stop"
    )
    assert "MOVED, not removed" in rec, (
        "the relocation must be documented at the old site so a reviewer diffing the "
        "function does not read it as a dropped check"
    )


def test_release_preminta_rollback_before_any_write():
    flow = _block("Invoke-ReleaseFlow")
    i_premint = flow.index('"rollback"')
    i_deploy = flow.index("Invoke-DeployMain")
    i_reconcile = flow.index("Invoke-Reconcile -Cfg")
    assert i_premint < i_deploy and i_premint < i_reconcile, (
        "the rollback authorization must be pre-minted while everything is healthy; "
        "minting one mid-incident costs time"
    )


def test_release_mint_is_internal_and_key_gated():
    mint = _block("Invoke-ReleaseMint")
    assert "sign_deploy_authorization.py" in mint, "the internal mint must use the SAME signer"
    assert "PZ_DEPLOY_AUTH_KEY_FILE" in mint, (
        "the mint failure message must name the external key requirement -- the key "
        "stays outside the repository; -Release removes the ceremony, not the signature"
    )
    # Rollback is evidence-exempt (incident path); deploy/reconcile carry evidence.
    assert '-ne "rollback"' in mint.replace("'", '"')


# ---------------------------------------------------------------- stale lock
def test_stale_lock_autoclears_only_under_release_and_is_audited():
    lock = _block("Enter-DeployLock")
    assert "Get-Process -Id $lockPid" in lock, "staleness stays pid-decided"
    assert "STALE LOCK CLEARED (audit)" in lock, "the clear stays audited"
    assert "$script:ReleaseMode" in lock, "-Release may auto-clear a dead-pid lock"
    assert "-not $ForceUnlock -and -not $script:ReleaseMode" in lock, (
        "outside -Release the explicit -ForceUnlock is still required"
    )
    assert "another deployment is running" in lock, "a LIVE lock always blocks"


# ---------------------------------------------------------------- closure
def test_release_runs_closure_automatically():
    flow = _block("Invoke-ReleaseFlow")
    assert "Test-PZDeployClose.ps1" in flow
    assert "hard blocker 4/4" in flow, "a failed closure is a named hard blocker"


# ---------------------------------------------------------------- gate_evidence CLI
def _evidence_doc(target_sha: str, verdict: str = "GO") -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "schema_version": 1,
        "target_sha": target_sha,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=4)).isoformat(),
        "agents": [
            {"agent": a, "status": "GO", "blockers": [], "risks": []} for a in AGENTS
        ],
        "lead_verdict": verdict,
    }


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GATE_EVIDENCE), *args],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def test_gate_evidence_cli_accepts_a_valid_go(tmp_path):
    p = tmp_path / "latest.json"
    p.write_text(json.dumps(_evidence_doc(_SHA_A)), encoding="utf-8")
    r = _run_cli(str(p), _SHA_A)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "VALID" in r.stdout


def test_gate_evidence_cli_refuses_wrong_sha_missing_file_and_non_go(tmp_path):
    p = tmp_path / "latest.json"
    p.write_text(json.dumps(_evidence_doc(_SHA_A)), encoding="utf-8")
    assert _run_cli(str(p), "b" * 40).returncode == 1, "evidence for another SHA must refuse"
    assert _run_cli(str(tmp_path / "absent.json"), _SHA_A).returncode == 1
    bad = _evidence_doc(_SHA_A)
    bad["agents"][3]["status"] = "BLOCK"
    p.write_text(json.dumps(bad), encoding="utf-8")
    assert _run_cli(str(p), _SHA_A).returncode == 1, "a BLOCK must never validate"


def test_gate_evidence_cli_is_read_only():
    """The -Release preflight validator must only validate: no writes of any kind."""
    src = GATE_EVIDENCE.read_text(encoding="utf-8")
    body = src[src.index("def main("):src.index("if __name__")]
    assert "validate_evidence" in body
    for forbidden in ("open(", "os.makedirs", "os.replace", "os.remove", "write_text"):
        assert forbidden not in body, f"the CLI must not write ({forbidden} found)"
