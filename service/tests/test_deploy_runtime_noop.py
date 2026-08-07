"""Pins for the runtime no-op short-circuit in Deploy-PZ.ps1.

The optimisation lets a merge that changed only tests, docs or CI skip the service
stop/stage/mirror/restart cycle, because the release artifact is built from
``source_app`` plus ``engine_files`` and nothing else. It has exactly one dangerous
failure mode: declaring a no-op when runtime bytes really did change. Production
would then keep serving the old code while the version marker claimed the new commit,
and the next deploy's identity gate would anchor on that lie.

Two things can cause it, and neither is visible by reading the script:

  1. the comparison runs over a pathspec that matches nothing -- ``git diff --quiet``
     over a path that does not exist exits 0, which reads as "no differences";
  2. the marker advances on the strength of the comparison alone, so a wrong verdict
     launders drift into a "verified" identity.

(1) is a fact about the repository and is checked here against the real config.
(2) is a fact about the script's ordering and is pinned as such.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / ".claude" / "deploy" / "windows_prod_v2.json"
DEPLOY_SCRIPT = REPO / ".claude" / "deploy" / "Deploy-PZ.ps1"


def _cfg() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _app_pathspec(cfg: dict) -> str:
    """The repo-relative pathspec Get-SourceRelativePath derives, computed the same way."""
    root = cfg["source_root"].rstrip("\\/")
    app = cfg["source_app"].rstrip("\\/")
    assert app.lower().startswith(root.lower() + "\\"), (
        f"source_app {app!r} is not inside source_root {root!r}; no repo-relative "
        "pathspec can be derived and the comparison would match nothing"
    )
    return app[len(root) + 1:].replace("\\", "/")


def _tracked(pathspec: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "--", pathspec],
        capture_output=True, text=True, check=True,
    ).stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def test_app_pathspec_matches_tracked_files():
    """A pathspec matching nothing makes every deploy look like a no-op."""
    spec = _app_pathspec(_cfg())
    assert _tracked(spec), (
        f"the derived application pathspec {spec!r} matches no tracked file. "
        "'git diff --quiet' over it would exit 0 for ANY change and every deploy "
        "would be declared a runtime no-op."
    )


def test_engine_files_match_tracked_files():
    """Engine files are compared by name at source_root; a stale name matches nothing."""
    for name in _cfg()["engine_files"]:
        assert _tracked(name), (
            f"engine file {name!r} from config matches no tracked file at the repo "
            "root. The engine half of the no-op comparison would be vacuous."
        )


def test_app_pathspec_excludes_the_test_tree():
    """The premise of the optimisation: tests cannot reach the artifact."""
    spec = _app_pathspec(_cfg())
    assert not [p for p in _tracked(spec) if "/tests/" in p or p.endswith("/tests")], (
        f"tracked test files live under the deployed pathspec {spec!r}. A test-only "
        "merge would then register as a runtime difference, and the short-circuit "
        "would never fire for the case it exists to serve."
    )


def test_marker_advances_only_after_identity_is_reproved():
    """The no-op must re-prove production IS the target before recording it as such."""
    body = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    start = body.index("RUNTIME NO-OP: the reviewed target changes nothing")
    end = body.index("Set-ServiceState -Cfg $cfg -Target Stopped", start)
    block = body[start:end]

    # The no-op body lives in Invoke-DeployMain, whose target parameter is $TargetSha
    # (operator-supplied via -ReviewedSHA, or the resolved origin/main tip via -Release).
    reproof = block.index("Assert-ProductionMatchesRecordedSha -Cfg $cfg -ExpectSha $TargetSha")
    write = block.index("Write-VersionFile -Cfg $cfg -Sha $TargetSha")
    assert reproof < write, (
        "the no-op path writes the version marker without first re-proving that the "
        "runtime tree IS the reviewed target. A wrong no-op verdict would then be "
        "recorded as a verified identity."
    )


def test_inconclusive_git_result_is_never_a_no_op():
    """Only exit 1 means 'differences'; anything else must block, not fall through."""
    body = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    fn = body[body.index("function Test-RuntimeUnchanged"):body.index("function Invoke-Preflight")]
    assert re.search(r"if \(\$code -ne 0\) \{\s*\n\s*throw", fn), (
        "Test-RuntimeUnchanged must throw on any git exit code other than 0 or 1. "
        "An inconclusive comparison is not a licence to proceed: the release artifact "
        "is staged from the same working tree."
    )
    assert "$paths.Count -lt 1" in fn, (
        "an empty pathspec makes 'git diff' compare the whole tree; it must be refused"
    )
