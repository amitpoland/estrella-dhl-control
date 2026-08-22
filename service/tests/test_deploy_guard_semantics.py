"""Deploy-guard semantics: the guard classifies the ACTION, not the string.

Root cause pinned here: the guard used to deny any command whose text merely
CONTAINED "deploy-pz.ps1". Measured before the fix, 15 of 16 read-only
inspections of the deployment script were denied -- `sed -n ... Deploy-PZ.ps1`,
`git diff -- ...Deploy-PZ.ps1`, `Get-FileHash ...`, even `echo "Deploy-PZ.ps1"`.
A protected filename in command text is evidence of reading, not of execution.

Two halves, and BOTH must hold:
  READ_ONLY  -> allowed. Inspecting deployment code must be frictionless.
  EXECUTION / PRODUCTION MUTATION / UNKNOWN -> denied. Unchanged, fail closed.

A test added here is a permanent claim about guard behaviour. Adding a command
to ALLOWED_READS is a policy decision: it asserts that shape cannot execute
anything and cannot write.
"""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GUARD_PATH = REPO / ".claude" / "hooks" / "pz-deploy-guard.py"

# The hook filename contains dashes, so it cannot be imported by name.
_spec = importlib.util.spec_from_file_location("pz_deploy_guard", GUARD_PATH)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)  # type: ignore[union-attr]

DEPLOY = r".claude\deploy\Deploy-PZ.ps1"
DEPLOY_POSIX = ".claude/deploy/Deploy-PZ.ps1"


# ---------------------------------------------------------------- read corpus
# Every one of these is a real inspection an engineer performs on deployment
# code. All were denied before 2026-08-20.
ALLOWED_READS = [
    # POSIX / Git Bash reads
    "sed -n '1,40p' " + DEPLOY_POSIX,
    "cat " + DEPLOY_POSIX,
    "head -50 " + DEPLOY_POSIX,
    "tail -20 " + DEPLOY_POSIX,
    "awk '/param/{print}' " + DEPLOY_POSIX,
    "wc -l " + DEPLOY_POSIX,
    # search -- the protected name inside a PATTERN is not execution
    'grep -rn "Deploy-PZ.ps1" .claude/',
    r'rg "Deploy-PZ\.ps1" --glob "*.md"',
    'grep -rn "Deploy-PZ.ps1" . 2>/dev/null',
    "grep -c . " + DEPLOY_POSIX + " | head -1",
    # PowerShell reads
    "Get-Content " + DEPLOY,
    "Get-Item " + DEPLOY,
    "Get-FileHash " + DEPLOY,
    "Select-String -Path " + DEPLOY + " -Pattern robocopy",
    # git reads, including revision-pinned reads (Lesson Q rule 7)
    "git diff -- " + DEPLOY_POSIX,
    "git show HEAD:" + DEPLOY_POSIX,
    "git log --oneline -- " + DEPLOY_POSIX,
    "git ls-files " + DEPLOY_POSIX,
    "git blame " + DEPLOY_POSIX,
    # prose / quoting variants
    'echo "Deploy-PZ.ps1"',
    "echo 'the canonical authority is Deploy-PZ.ps1'",
    # runtime-config scripts are equally readable
    r"Get-Content service\scripts\env_config_manager.ps1",
    "sed -n '1,20p' service/scripts/activate_pz_lifecycle.py",
    # reading a PRODUCTION file is inspection, not mutation
    r"Get-Content C:\PZ\version.txt",
    r"Get-FileHash C:\PZ\app\main.py",
    # local-repository git writes: the name is prose or a pathspec, not a call
    'git commit -m "fix(guard): Deploy-PZ.ps1 reads are not executions"',
    "git add " + DEPLOY_POSIX,
    'git tag -a v1 -m "pins Deploy-PZ.ps1 behaviour"',
    # prose that DESCRIBES a guarded operation is not that operation
    'git commit -m "guard now blocks Stop-Service PZService and robocopy C:\\PZ\\app"',
    'grep -rn "robocopy .* C:\\PZ\\app" .claude/',
    'echo "never run sc.exe stop PZService by hand"',
    # gh prose: a PR describing deployment work is not deployment
    'gh pr create --title "fix(guard): Deploy-PZ.ps1 reads are not deploys"',
    'gh pr comment 1 --body "robocopy into C:\\PZ stays operator-only"',
    "gh pr view 1295",
    # a non-inert but harmless segment must not re-block an inert sibling
    'git push && gh pr create --title "guard: Deploy-PZ.ps1 reads"',
    # ordinary work that mentions nothing protected
    "pytest service/tests/test_deploy_authority.py -q",
    "git status --porcelain",
]


@pytest.mark.parametrize("command", ALLOWED_READS)
def test_read_only_inspection_is_allowed(command):
    verdict = guard.classify_command(command)
    assert verdict is None, (
        "read-only inspection must not be blocked; guard returned %r for: %s"
        % (verdict, command)
    )


# ----------------------------------------------------------- dangerous corpus
# (command, expected matched_rule). These must stay denied.
BLOCKED = [
    # --- execution of the canonical deploy script, every invocation shape ---
    (r".\Deploy-PZ.ps1 -Release", "deploy-script-invocation"),
    (r"& .\Deploy-PZ.ps1", "deploy-script-invocation"),
    (r".\Deploy-PZ.ps1 -WhatIf", "deploy-script-invocation"),
    (r"powershell -File " + DEPLOY, "deploy-script-invocation"),
    ("pwsh -NoProfile " + DEPLOY_POSIX + " -WhatIf", "deploy-script-invocation"),
    (r"Start-Process powershell -ArgumentList '" + DEPLOY + "'", "deploy-script-invocation"),
    (r". .\Deploy-PZ.ps1", "deploy-script-invocation"),
    (r"cmd /c powershell " + DEPLOY, "deploy-script-invocation"),
    (r"iex (Get-Content " + DEPLOY + " -Raw)", "deploy-script-invocation"),
    (r"Invoke-Expression (Get-Content " + DEPLOY + ")", "deploy-script-invocation"),
    (r"bash -c '.\Deploy-PZ.ps1'", "deploy-script-invocation"),
    # rollback is equally production-mutating
    (r".\Deploy-PZ.ps1 -Rollback", "deploy-script-invocation"),
    # --- bypass attempts ---
    # chaining a real read with a real execution
    ("grep -n x " + DEPLOY_POSIX + r" && .\Deploy-PZ.ps1", "deploy-script-invocation"),
    ("cat " + DEPLOY_POSIX + r" ; & .\Deploy-PZ.ps1", "deploy-script-invocation"),
    # variable indirection -- caught at the assignment segment
    (r"$s = '.\Deploy-PZ.ps1'; & $s", "deploy-script-invocation"),
    # command substitution hides the payload
    (r"& $(echo .\Deploy-PZ.ps1)", "deploy-script-invocation"),
    # staging a renamed copy is itself blocked
    ("cp " + DEPLOY_POSIX + " /tmp/x.ps1", "deploy-script-invocation"),
    (r"Copy-Item " + DEPLOY + r" C:\temp\x.ps1", "deploy-script-invocation"),
    # in-place edit of the deploy script is a write, not a read
    ("sed -i 's/a/b/' " + DEPLOY_POSIX, "deploy-script-invocation"),
    # an encoded command cannot be classified at all
    ("powershell -enc SQBuAHYAbwBrAGUALQBFAHgAcAByAA==", "encoded-command"),
    ("pwsh -EncodedCommand UgBlAG0AbwB2AGUALQBJAHQAZQBtAA==", "encoded-command"),
    # --- production writes ---
    (r"robocopy .\service\app C:\PZ\app /MIR", "deploy-to-prod-PZ"),
    (r"Copy-Item -Recurse .\service\app C:\PZ\app", "deploy-to-prod-PZ"),
    (r"xcopy /E service\app C:\PZ\app", "deploy-to-prod-PZ"),
    (r"cp pz_import_processor.py C:\PZ\engine\pz_import_processor.py", "deploy-to-prod-PZ"),
    (r"Set-Content C:\PZ\version.txt 'abc'", "deploy-to-prod-PZ"),
    # redirection into production
    ("grep -n x " + DEPLOY_POSIX + r" > C:\PZ\app\x.py", "redirect-into-prod"),
    (r"echo 1 >> C:\PZ\.env", "redirect-into-prod"),
    # --- runtime configuration writers ---
    (r"powershell .\service\scripts\env_config_manager.ps1", "runtime-config-write"),
    ("python service/scripts/activate_pz_lifecycle.py", "runtime-config-write"),
    # --- production service control (CLAUDE.md core rule 3) ---
    ("sc.exe stop PZService", "service-control"),
    ("sc.exe start PZService", "service-control"),
    ("nssm restart PZService", "service-control"),
    ("Restart-Service PZService", "service-control"),
    ("Stop-Service -Name PZService -Force", "service-control"),
    # --- merge / push authority ---
    ("gh pr merge 1234 --squash", "gh-pr-merge"),
    ("git push origin main", "git-push-main"),
    # --- ambiguous production access fails closed ---
    (r"python -c \"open(r'C:\PZ\app\main.py','w')\"", "unclassified-prod-touch"),
]


@pytest.mark.parametrize("command,rule", BLOCKED)
def test_dangerous_action_is_blocked(command, rule):
    verdict = guard.classify_command(command)
    assert verdict is not None, "must be blocked but was allowed: %s" % command
    assert verdict["matched_rule"] == rule, (
        "wrong rule for %r: expected %s, got %s" % (command, rule, verdict["matched_rule"])
    )
    assert verdict["result"].startswith("BLOCK_")
    assert verdict["authority_required"] == "operator"


# --------------------------------------------------------- adversarial corpus
# Bypass attempts. Each was run against the classifier during the 2026-08-20
# campaign; `pipe-to-interpreter` and the escape-normalisation rule exist
# because these found real holes. The rule is not pinned -- only that the
# action does not get through.
BYPASS_ATTEMPTS = [
    # escape / quote splitting of the protected name
    ".\\Deploy-PZ.ps`1",
    '.\\Dep"loy-PZ.ps1',
    ".\\Dep^loy-PZ.ps1",
    "powershell -c \"& '.claude\\deploy\\Deploy-PZ.ps1'\"",
    # interpreter wrappers
    "python -c \"import subprocess; subprocess.run(['.\\\\Deploy-PZ.ps1'])\"",
    "bash -c 'powershell .claude/deploy/Deploy-PZ.ps1'",
    "Start-Job -ScriptBlock { .\\Deploy-PZ.ps1 }",
    "Invoke-Command -ScriptBlock { .\\Deploy-PZ.ps1 }",
    # indirection
    "$p = Get-Item .\\Deploy-PZ.ps1; & $p",
    "& (Get-ChildItem -Filter Deploy-PZ.ps1).FullName",
    "Move-Item .claude\\deploy\\Deploy-PZ.ps1 x.ps1",
    # a genuine read chained or piped into an execution
    "cat " + DEPLOY_POSIX + " && powershell " + DEPLOY_POSIX,
    "git show HEAD:" + DEPLOY_POSIX + " | powershell -",
    "grep x " + DEPLOY_POSIX + r" || .\Deploy-PZ.ps1",
    # production writes reached indirectly
    r"Get-Content a.py | Set-Content C:\PZ\app\a.py",
    r"robocopy service\app C:/PZ/app /MIR",
    r"cd C:\PZ\app; Copy-Item x.py y.py",
    r"New-Item -Path C:\PZ\app\z.py -ItemType File",
    r"Remove-Item -Recurse C:\PZ\app",
    # service control with the target before the verb
    "Get-Service PZService | Stop-Service",
    "net stop PZService",
    "sc.exe config PZService start= disabled",
    # runtime config via a non-obvious invocation
    r". .\service\scripts\env_config_manager.ps1",
]


@pytest.mark.parametrize("command", BYPASS_ATTEMPTS)
def test_bypass_attempt_fails_closed(command):
    assert guard.classify_command(command) is not None, (
        "bypass succeeded -- this command reached execution: %s" % command
    )


def test_block_verdicts_are_structured():
    """Phase 8: a decision carries operation, rule, reason and authority --
    never a message that misdescribes the requested action."""
    verdict = guard.classify_command(r".\Deploy-PZ.ps1 -Release")
    assert set(verdict) == {
        "result", "matched_rule", "operation", "reason", "authority_required"
    }
    assert verdict["operation"] == "DEPLOY_EXECUTION"
    # the reason must describe EXECUTION, and must not claim reading is a write
    assert "execution" in verdict["reason"].lower()
    assert "reading" in verdict["reason"].lower()


def test_read_only_vocabulary_excludes_arbitrary_interpreters():
    """Python/PowerShell/bash are arbitrary execution: never read-only heads,
    however innocent one example looks."""
    for interpreter in ("python", "python3", "bash", "sh", "powershell", "pwsh",
                        "cmd", "node", "perl", "iex", "invoke-expression",
                        "start-process", "&", "."):
        assert interpreter not in guard.READ_ONLY_HEADS, (
            "%s is arbitrary execution and must not be a read-only head" % interpreter
        )


def test_git_write_subcommands_are_not_read_only():
    for sub in ("push", "commit", "merge", "reset", "checkout", "clean", "apply"):
        assert sub not in guard.GIT_READ_ONLY_SUBCOMMANDS


def test_gh_pr_merge_is_never_prose():
    """`merge` must not join the gh prose set -- it has its own Council gate."""
    assert guard.GH_PROSE_RX.search("gh pr merge 1295 --squash") is None
    assert guard.classify_command("gh pr merge 1295 --squash")["matched_rule"] == "gh-pr-merge"
    # and it stays gated when chained behind an inert command
    verdict = guard.classify_command('gh pr create --title "x" && gh pr merge 1295 --squash')
    assert verdict is not None and verdict["matched_rule"] == "gh-pr-merge"


def test_git_push_is_never_treated_as_a_local_write():
    """`push` in GIT_LOCAL_WRITE_SUBCOMMANDS would disable rule 'git-push-main'."""
    assert "push" not in guard.GIT_LOCAL_WRITE_SUBCOMMANDS
    assert guard.classify_command("git push origin main")["matched_rule"] == "git-push-main"


def test_classifier_is_deterministic_and_cheap():
    """Phase 11: the guard runs on EVERY shell command. Classification must be
    parsing, not reasoning. Budget is per-command and generous by 2 orders of
    magnitude; it exists to fail if someone adds a subprocess or network call."""
    corpus = ALLOWED_READS + [c for c, _ in BLOCKED]
    first = [guard.classify_command(c) for c in corpus]
    second = [guard.classify_command(c) for c in corpus]
    assert first == second, "classification must be deterministic"

    start = time.perf_counter()
    for _ in range(20):
        for command in corpus:
            guard.classify_command(command)
    per_call_ms = (time.perf_counter() - start) * 1000 / (20 * len(corpus))
    assert per_call_ms < 5.0, "classification too slow: %.3f ms/command" % per_call_ms


# ---------------------------------------------------------------------------
# 2026-08-21. Six more false positives measured in one session, plus one false
# NEGATIVE that mattered far more than all of them: the guard knew the
# production tree as C:\\PZ and C:\\PZ/, but not as /c/PZ -- the MSYS mount form
# the Bash tool emits natively, and therefore the spelling an agent reaches for
# first. `cp -r service/app/. /c/PZ/app/` classified as read-only.
#
# All seven share one shape: the guard decided by where a NAME appeared in the
# command text rather than by what the command DOES to the thing named.
# ---------------------------------------------------------------------------

PROD = "C:" + chr(92) + "PZ"
PROD_BASH = "/c/PZ"


@pytest.mark.parametrize(
    "command",
    [
        # a protected path inside a heredoc BODY is data; the write goes to notes.md
        "cat >> notes.md <<'MD'" + chr(10) + "marker at " + PROD + chr(92)
        + "version.txt" + chr(10) + "MD",
        # ... and inside a quoted echo argument it is prose; the write goes to /tmp
        "echo 'see " + PROD + chr(92) + "version.txt' > /tmp/note.txt",
        # byte-verifying a deployment is the whole point of the deployment doctrine
        "git hash-object " + PROD + chr(92) + "app" + chr(92) + "services"
        + chr(92) + "main.py",
        "diff -r " + PROD_BASH + "/app service/app",
        # a redirect to an UNprotected target does not make an inspection a write
        "grep -rn 'Deploy-PZ.ps1 -Release' docs/ > /tmp/hits.txt",
    ],
)
def test_reading_stays_frictionless_when_the_name_is_not_the_target(command):
    """A protected name in a heredoc body, a quoted string, or beside an
    unprotected redirect target is prose. Only an operand or a redirect TARGET
    is an operation."""
    assert guard.classify_command(command) is None, command


@pytest.mark.parametrize(
    "command",
    [
        "echo x > " + PROD_BASH + "/version.txt",
        "cp evil.py " + PROD_BASH + "/app/main.py",
        "cp -r service/app/. " + PROD_BASH + "/app/",
        "rm " + PROD_BASH + "/storage/carrier/carrier_shipments.db",
        "mv build " + PROD_BASH + "/app",
    ],
)
def test_the_git_bash_spelling_of_production_is_still_production(command):
    """THE false negative. /c/PZ, C:\\PZ and C:/PZ are one directory. A guard
    that can be evaded by spelling the path differently is not a guard."""
    verdict = guard.classify_command(command)
    assert verdict is not None, "production write went unguarded: " + command
    assert verdict["authority_required"] == "operator"


@pytest.mark.parametrize(
    "sibling",
    [PROD_BASH + "-main/app", PROD_BASH + "-verify", PROD + "-verify",
     PROD + "-wt" + chr(92) + "slice"],
)
def test_widening_the_path_vocabulary_did_not_swallow_sibling_trees(sibling):
    """C:\\PZ-verify and /c/PZ-main are working trees, not production."""
    assert guard._is_prod_pz_path(sibling.lower()) is False


def test_a_heredoc_that_an_interpreter_executes_is_still_code():
    """The heredoc body is data only when nothing runs it. Feed the same body to
    python and it is code again -- otherwise stripping bodies would become the
    evasion it exists to prevent."""
    body = "import shutil; shutil.rmtree('" + PROD_BASH + "/app')"
    command = "python - <<'PY'" + chr(10) + body + chr(10) + "PY"
    assert guard._strip_heredoc_prose(command) == command
    assert guard.classify_command(command) is not None


def test_redirecting_over_the_deploy_script_is_a_protected_write():
    """Overwriting the deployment authority is a write to a protected surface,
    even though its path carries no production token."""
    assert guard._redirects_into_protected(
        "echo pwned > .claude" + chr(92) + "deploy" + chr(92) + "Deploy-PZ.ps1")


# ---------------------------------------------------------------------------
# E3/E4 (2026-08-21). Two further defects of the same family.
#
# E3: the segment splitter split on every `|`, including quoted ones, so a
#     grep whose PATTERN contained an alternation was torn into fragments and
#     one fragment looked like a command naming the deployment script.
# E4: doctrine requires commands the guard could not classify. A doctrine step
#     that the guard refuses is not a step -- the two must stay coherent.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        # the pipe is inside a quoted regex; the shell does not split there
        "grep -rn 'deploy-audit" + chr(92) + "|DEPLOY_AUDIT' .claude/deploy/Deploy-PZ.ps1",
        'grep -n "a' + chr(92) + '|b" ' + DEPLOY,
        "grep -rn 'a|b' docs/ ; echo done",
    ],
)
def test_a_quoted_pipe_is_not_a_shell_separator(command):
    assert guard.classify_command(command) is None, command


def test_an_unquoted_pipe_is_still_a_separator():
    """Quote awareness must not lose real pipes: the interpreter rule depends
    on seeing them."""
    assert len(guard._split_segments("cat x | python -")) == 2
    assert guard.classify_command(
        "cat " + PROD + chr(92) + "version.txt | python -") is not None


# Commands the governing doctrine REQUIRES. Each must be classifiable as
# read-only, or the doctrine asks for something the guard forbids. git
# hash-object was the first such gap: byte verification is mandatory after
# every deploy, and the guard called it an unclassifiable production touch.
DOCTRINE_REQUIRED = [
    "git hash-object " + PROD + chr(92) + "app" + chr(92) + "services" + chr(92) + "x.py",
    "git hash-object " + PROD_BASH + "/app/services/x.py",
    "git ls-remote origin main",
    "git rev-parse HEAD",
    "git status --porcelain",
    "git diff --name-only abc..def -- service/app",
    "git merge-base --is-ancestor abc def",
    "git branch -a --contains abc",
    "git log --oneline abc..def",
    "cat " + PROD + chr(92) + "version.txt",
    "cat " + PROD_BASH + "/version.txt",
    "diff -r " + PROD_BASH + "/app service/app",
    "ls -la " + PROD_BASH + "/storage/carrier/",
]


@pytest.mark.parametrize("command", DOCTRINE_REQUIRED)
def test_every_doctrine_required_command_is_classifiable_as_read_only(command):
    """GUARD / DOCTRINE COHERENCE. If this fails, either the doctrine or the
    guard is wrong -- never resolve it by skipping the doctrine step."""
    assert guard.classify_command(command) is None, command
