"""Governance pins for the campaign-branch ownership guard.

Authority: `.campaigns/` (schema.json, policies.json, OWNERSHIP-GUARD-SPEC.md).
Enforcement: `.claude/hooks/campaign-branch-guard.py` (PreToolUse, fail closed).
Decision:    docs/decisions/ADR-campaign-state-lifecycle-sha-authority.md

The REAL guard module is loaded from its real path and driven through its real `main()`
with a real stdin payload â€” no re-implementation, no mutated copy (Lesson A: stubs must
never stand in for the thing under test). Only `CANONICAL_REGISTRY` is rebound, so the
fixture registry is read instead of the live machine one; every code path exercised is
production code.
"""
import ast
import importlib.util
import io
import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GUARD = os.path.join(REPO_ROOT, ".claude", "hooks", "campaign-branch-guard.py")
BANNER = os.path.join(REPO_ROOT, ".claude", "hooks", "campaign-session-banner.py")
CAMPAIGNS = os.path.join(REPO_ROOT, ".campaigns")

BRANCH = "fix/example-campaign"
OWNER_SESSION = "session-owner-0001"
OTHER_SESSION = "session-other-9999"

# Distinct SHAs: a campaign branch tip and a main-side squash commit. The whole point
# of the ADR is that these live in different fields and are never interchanged.
TIP_SHA = "1111111111111111111111111111111111111111"
SQUASH_SHA = "2222222222222222222222222222222222222222"


# --------------------------------------------------------------------------- helpers

def _write_registry(tmp_path, entry):
    """Write a registry at the CLAUDE_PROJECT_DIR fallback location."""
    state_dir = tmp_path / ".claude" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "active-campaigns.json").write_text(
        json.dumps({"campaigns": {"example": entry}}), encoding="utf-8"
    )
    return tmp_path


def _load_guard_module():
    """Import the real hook file as a module (its hyphenated name is not importable)."""
    spec = importlib.util.spec_from_file_location("campaign_branch_guard", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeStdin:
    def __init__(self, raw):
        self.buffer = io.BytesIO(raw)

    def read(self):
        return self.buffer.getvalue().decode("utf-8")


class _CapturedStdout:
    def __init__(self):
        self.buffer = io.BytesIO()


def _run_guard(tmp_path, command, session_id=OWNER_SESSION, cwd=None, registry=None):
    """Drive the real guard's `main()` end-to-end. Returns the decision dict or None.

    `CANONICAL_REGISTRY` is rebound to the fixture so the live machine registry cannot
    shadow it â€” otherwise every behavioural assertion below would silently go vacuous
    on a developer machine while still reporting green.
    """
    mod = _load_guard_module()
    mod.CANONICAL_REGISTRY = str(registry) if registry else str(
        tmp_path / ".claude" / "state" / "active-campaigns.json"
    )
    payload = {
        "tool_input": {"command": command},
        "cwd": cwd or str(tmp_path),
        "session_id": session_id,
    }
    real_stdin, real_stdout = sys.stdin, sys.stdout
    old_proj = os.environ.get("CLAUDE_PROJECT_DIR")
    # Neutralise the fallback path too, so only the rebound canonical path is consulted.
    os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path / "_no_fallback_")
    sys.stdin = _FakeStdin(json.dumps(payload).encode("utf-8"))
    sys.stdout = _CapturedStdout()
    try:
        rc = mod.main()
        out = sys.stdout.buffer.getvalue().decode("utf-8").strip()
    finally:
        sys.stdin, sys.stdout = real_stdin, real_stdout
        if old_proj is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = old_proj
    assert rc == 0, "guard must always exit 0; decisions travel in the JSON payload"
    if not out:
        return None  # silent allow
    return json.loads(out)["hookSpecificOutput"]


def _entry(state="IN_PROGRESS", expected_head=TIP_SHA, lock="owner", merge=None, worktree=None):
    e = {
        "branch": BRANCH,
        "worktree": worktree or "C:\\PZ-wt\\example",
        "owner": "example owner session",
        "expected_head": expected_head,
        "state": state,
    }
    if lock == "owner":
        e["lock"] = {"session_id": OWNER_SESSION, "claimed_at": "2026-07-19T00:00:00Z",
                     "heartbeat_at": "2999-01-01T00:00:00Z"}
    elif lock == "none":
        e["lock"] = None
    if merge is not None:
        e["merge"] = merge
    return e


def _git(args, cwd):
    return subprocess.run(["git"] + args, cwd=str(cwd),
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A real, self-contained git repo to act as the campaign worktree.

    Deliberately NOT the repository under test: when this suite runs from an exported
    tree (`git archive`) there is no .git, `rev-parse HEAD` returns empty, and check 5
    silently short-circuits into an allow — a vacuous pass. Owning the fixture repo
    makes the drift pins hold in any execution context.
    """
    d = tmp_path / "campaign_repo"
    d.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "campaign-branch"], cwd=str(d), check=True)
    subprocess.run(["git", "config", "user.email", "t@example.invalid"], cwd=str(d), check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=str(d), check=True)
    (d / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=str(d), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(d), check=True)
    return d


def _repo_entry(repo, state="IN_PROGRESS", expected_head=None, lock="owner", merge=None):
    """An entry bound to the fixture repo, so checks 2/3 pass and 4/5 are truly reached."""
    e = _entry(state=state,
               expected_head=expected_head or _git(["rev-parse", "HEAD"], repo),
               lock=lock, merge=merge, worktree=str(repo))
    e["branch"] = _git(["branch", "--show-current"], repo)
    return e


# ------------------------------------------------------------------ scope / pass-through

def test_non_write_command_passes_silently(tmp_path):
    """Read-only commands are never governed, regardless of registry contents."""
    _write_registry(tmp_path, _entry())
    assert _run_guard(tmp_path, f"git status --short {BRANCH}") is None


def test_out_of_scope_write_passes_silently(tmp_path):
    """A write to an unrelated branch is not the guard's business."""
    _write_registry(tmp_path, _entry())
    assert _run_guard(tmp_path, "git commit -m 'unrelated work'") is None


# ------------------------------------------------------------------- required test matrix

def test_old_format_record_without_merge_preserves_existing_behaviour(tmp_path, repo):
    """An untouched legacy record (no `merge` key) behaves exactly as before.

    Bound to the real repo so checks 2/3 pass and execution reaches check 4 — otherwise
    the worktree-mismatch deny would mask the behaviour actually under test.
    """
    entry = _repo_entry(repo, state="IN_PROGRESS", lock="none")
    assert "merge" not in entry
    _write_registry(tmp_path, entry)
    d = _run_guard(tmp_path, "git commit -m x", cwd=str(repo))
    # lock unclaimed -> ask (check 4), the pre-existing behaviour
    assert d["permissionDecision"] == "ask"
    assert "write-lock unclaimed" in d["permissionDecisionReason"]


@pytest.mark.parametrize("session", [OWNER_SESSION, OTHER_SESSION])
def test_merged_pending_archive_denies_owner_and_non_owner(tmp_path, session):
    """The new state is write-restricted for EVERY session, owner included."""
    _write_registry(tmp_path, _entry(state="MERGED_PENDING_ARCHIVE"))
    d = _run_guard(tmp_path, f"git commit -m x  # {BRANCH}", session_id=session)
    assert d["permissionDecision"] == "deny"
    assert "MERGED_PENDING_ARCHIVE" in d["permissionDecisionReason"]


def test_claimed_lock_writable_state_with_mismatched_expected_head_denies(tmp_path, repo):
    """Drift detection stays ACTIVE in writable states.

    This is the non-vacuous check-5 pin: the lock is held by this very session and the
    heartbeat is fresh, so checks 1-4 all pass and execution genuinely reaches check 5.
    Without a claimed lock the guard would `ask` at check 4 and this test would pass
    for the wrong reason. The worktree must also be a REAL git tree — against a
    non-repo path `rev-parse HEAD` returns nothing and check 5 short-circuits into a
    silent allow, which is a second way this pin can go vacuous.
    """
    _write_registry(tmp_path, _repo_entry(repo, state="IN_PROGRESS",
                                          expected_head=SQUASH_SHA))
    d = _run_guard(tmp_path, "git commit -m x", cwd=str(repo))
    assert d is not None, "expected a decision, got silent allow"
    assert d["permissionDecision"] == "deny"
    assert "unexpected HEAD" in d["permissionDecisionReason"]


def test_matching_branch_tip_expected_head_allows_when_other_gates_pass(tmp_path, repo):
    """Correct branch-tip expected_head + held lock + writable state => silent allow."""
    _write_registry(tmp_path, _repo_entry(repo, state="IN_PROGRESS"))
    assert _run_guard(tmp_path, "git commit -m x", cwd=str(repo)) is None


def test_merge_squash_sha_mismatch_has_no_independent_effect(tmp_path, repo):
    """`merge` is inert: a squash SHA unrelated to HEAD must not influence any decision.

    Identical to the allow case above except for the added `merge` object. If the guard
    ever compared merge.squash_sha against HEAD, this would flip to a deny.
    """
    _write_registry(tmp_path, _repo_entry(repo, state="IN_PROGRESS",
                                          merge={"pr": 940, "squash_sha": SQUASH_SHA,
                                                 "merged_at": "2026-07-17T22:27:37Z"}))
    assert _run_guard(tmp_path, "git commit -m x", cwd=str(repo)) is None


@pytest.mark.parametrize("state", ["FROZEN", "LOCKED", "DEPLOYING", "ARCHIVED"])
def test_existing_restricted_states_still_deny(tmp_path, state):
    """Pre-existing write-restricted states are unchanged by this campaign."""
    _write_registry(tmp_path, _entry(state=state))
    d = _run_guard(tmp_path, f"git reset --hard  # {BRANCH}")
    assert d["permissionDecision"] == "deny"
    assert state in d["permissionDecisionReason"]


@pytest.mark.parametrize("state", ["MERGED_VERIFIED", "TOTALLY_MADE_UP", ""])
def test_unknown_or_invalid_state_fails_closed_with_diagnostic(tmp_path, repo, state):
    """An undeclared state must never fall through to write-permitted behaviour.

    `MERGED_VERIFIED` is the real transport-m1 value that sat outside every enum.
    """
    entry = _repo_entry(repo, state="IN_PROGRESS")
    entry["state"] = state
    _write_registry(tmp_path, entry)
    d = _run_guard(tmp_path, "git commit -m x", cwd=str(repo))
    assert d is not None, "unknown state fell through to a silent allow"
    # branch/worktree agree, so the unrecognised state itself is the reason to stop
    assert d["permissionDecision"] == "ask"
    reason = d["permissionDecisionReason"]
    assert "RESTRICTED" in reason
    if state:
        assert state in reason, "diagnostic must name the offending value"


def test_absent_registry_allows_silently(tmp_path):
    """Documented behaviour: no registry => no campaign entries to govern."""
    assert _run_guard(tmp_path, f"git commit -m x  # {BRANCH}") is None


def test_corrupt_registry_asks_never_silently_allows(tmp_path):
    """Documented behaviour: unreadable registry escalates, never permits."""
    state_dir = tmp_path / ".claude" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "active-campaigns.json").write_text("{not valid json", encoding="utf-8")
    d = _run_guard(tmp_path, f"git commit -m x  # {BRANCH}")
    assert d["permissionDecision"] == "ask"
    assert "unreadable" in d["permissionDecisionReason"]


def test_worktree_add_still_asks(tmp_path):
    """WORKTREE DISCIPLINE rule 2 gate is unchanged."""
    d = _run_guard(tmp_path, "git worktree add C:\\PZ-wt\\new-thing")
    assert d["permissionDecision"] == "ask"
    assert "operator approval" in d["permissionDecisionReason"]


def test_unknown_state_does_not_soften_branch_mismatch_deny(tmp_path, repo):
    """An unrecognised state must never DOWNGRADE a categorical deny into an ask.

    Regression pin for a defect found in review: placing the unknown-state check ahead
    of checks 2/3 turned an automatic branch-mismatch `deny` into an operator-
    confirmable `ask`. Branch mismatch does not depend on state, so it must still win.
    """
    entry = _repo_entry(repo, state="IN_PROGRESS")
    entry["state"] = "MERGED_VERIFIED"          # undeclared
    entry["branch"] = "some/other-branch"       # ... and the tree is on a different branch
    _write_registry(tmp_path, entry)
    d = _run_guard(tmp_path, "git commit -m x", cwd=str(repo))
    assert d["permissionDecision"] == "deny", "bad state must not soften a check-2 deny"
    reason = d["permissionDecisionReason"]
    assert "branch mismatch" in reason
    assert "MERGED_VERIFIED" in reason, "the unrecognised state must still be surfaced"


def test_unknown_state_does_not_soften_worktree_mismatch_deny(tmp_path, repo):
    """Same guarantee for check 3 (worktree mismatch)."""
    entry = _repo_entry(repo, state="IN_PROGRESS")
    entry["state"] = ""                          # missing state
    entry["worktree"] = str(tmp_path / "elsewhere")
    _write_registry(tmp_path, entry)
    d = _run_guard(tmp_path, f"git commit -m x  # {entry['branch']}", cwd=str(tmp_path))
    assert d["permissionDecision"] == "deny"
    assert "worktree mismatch" in d["permissionDecisionReason"]


def test_multi_entry_registry_first_match_wins_is_documented(tmp_path, repo):
    """Two campaigns, both in scope: the guard decides on the first match and stops.

    Documents (does not endorse) the pre-existing first-match-wins behaviour so a future
    change to entry resolution is a visible test failure rather than a silent shift.
    """
    a = _repo_entry(repo, state="ARCHIVED")
    b = _repo_entry(repo, state="IN_PROGRESS")
    state_dir = tmp_path / ".claude" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "active-campaigns.json").write_text(
        json.dumps({"campaigns": {"a_first": a, "b_second": b}}), encoding="utf-8"
    )
    d = _run_guard(tmp_path, "git commit -m x", cwd=str(repo))
    assert d is not None and d["permissionDecision"] == "deny"
    assert "a_first" in d["permissionDecisionReason"], "first matching entry decides"


@pytest.mark.parametrize("bad_state", [123, {"a": 1}, ["MERGED"], 12.5, True])
def test_non_string_state_never_crashes_and_fails_closed(tmp_path, repo, bad_state):
    """A hand-edited registry with a non-string `state` must not crash the guard.

    Regression pin: `(entry.get("state") or ...).upper()` raised AttributeError on an
    int/dict/list BEFORE the fail-closed KNOWN_STATES gate could see it — so the one
    input class that most needs the gate was the one that bypassed it.
    """
    entry = _repo_entry(repo, state="IN_PROGRESS")
    entry["state"] = bad_state
    _write_registry(tmp_path, entry)
    d = _run_guard(tmp_path, "git commit -m x", cwd=str(repo))
    assert d is not None, "malformed state produced a silent allow"
    assert d["permissionDecision"] in ("ask", "deny")
    assert "RESTRICTED" in d["permissionDecisionReason"]


def test_non_string_state_does_not_outrank_branch_mismatch_deny(tmp_path, repo):
    """Categorical deny precedence survives the coercion change."""
    entry = _repo_entry(repo, state="IN_PROGRESS")
    entry["state"] = {"nonsense": True}
    entry["branch"] = "some/other-branch"
    _write_registry(tmp_path, entry)
    d = _run_guard(tmp_path, "git commit -m x", cwd=str(repo))
    assert d["permissionDecision"] == "deny"
    assert "branch mismatch" in d["permissionDecisionReason"]


def _run_entrypoint(tmp_path, extra_env=None):
    """Run the hook as a real subprocess through its __main__ entrypoint."""
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    env.update(extra_env or {})
    payload = {"tool_input": {"command": "git commit -m x"}, "cwd": str(tmp_path),
               "session_id": "s"}
    return subprocess.run([sys.executable, GUARD], input=json.dumps(payload).encode(),
                          capture_output=True, env=env, timeout=60)


def test_entrypoint_exception_cannot_silently_allow(tmp_path):
    """A crash inside main() must escalate, never pass the write through.

    Forces a real exception by running a copy of the hook whose main() raises, then
    asserts the __main__ wrapper still produces a blocking/escalating outcome. The copy
    keeps the real __main__ block verbatim — only main() is replaced.
    """
    src = io.open(GUARD, encoding="utf-8").read()
    assert "if __name__ == \"__main__\":" in src
    head, tail = src.split("if __name__ == \"__main__\":", 1)
    broken = (head
              + "\ndef main():\n    raise RuntimeError('forced entrypoint failure')\n\n"
              + "if __name__ == \"__main__\":" + tail)
    victim = tmp_path / "broken_guard.py"
    victim.write_text(broken, encoding="utf-8")
    payload = {"tool_input": {"command": "git commit -m x"}, "cwd": str(tmp_path),
               "session_id": "s"}
    p = subprocess.run([sys.executable, str(victim)], input=json.dumps(payload).encode(),
                       capture_output=True, timeout=60)
    out = p.stdout.decode("utf-8").strip()
    if out:
        d = json.loads(out)["hookSpecificOutput"]
        assert d["permissionDecision"] in ("ask", "deny"), "must not resolve to allow"
        assert "INTERNAL ERROR" in d["permissionDecisionReason"]
        assert p.returncode == 0, "a structured decision is returned with exit 0"
    else:
        assert p.returncode == 2, "no decision emitted => must use the blocking exit code"


def test_entrypoint_does_not_copy_banner_fail_open_pattern():
    """The banner may fail open (display only); the enforcement guard may not."""
    src = io.open(GUARD, encoding="utf-8").read()
    tail = src.split('if __name__ == "__main__":', 1)[1]
    assert "_emit(" in tail, "entrypoint must emit a decision on failure"
    assert ("sys.exit(2)" in tail or "else 2" in tail), \
        "must retain a blocking exit-code fallback when stdout is unusable"
    # the banner's bare `except Exception: sys.exit(0)` must not appear here
    assert "except Exception:\n        sys.exit(0)" not in tail
    # and no unconditional exit-0 inside the failure handler
    handler = tail.split("except BaseException as exc", 1)[-1]
    assert "sys.exit(0)\n" not in handler, \
        "an unconditional exit 0 in the failure handler would be a silent allow"


@pytest.mark.parametrize("bad_sid", [123, {"a": 1}, ["s"], 12.5, True, None])
def test_non_string_lock_session_id_never_crashes(tmp_path, repo, bad_sid):
    """A non-string `lock.session_id` must not raise on the display slice.

    Same class as the `state` defect: an exception here escapes to the entrypoint
    handler, which emits `ask` — silently downgrading a categorical `deny`.
    """
    entry = _repo_entry(repo, state="IN_PROGRESS")
    entry["lock"] = {"session_id": bad_sid, "claimed_at": "2026-01-01T00:00:00Z",
                     "heartbeat_at": "2999-01-01T00:00:00Z"}
    _write_registry(tmp_path, entry)
    d = _run_guard(tmp_path, "git commit -m x", cwd=str(repo))
    assert d is not None, "malformed lock produced a silent allow"
    assert d["permissionDecision"] in ("deny", "ask")
    assert "INTERNAL ERROR" not in d["permissionDecisionReason"], "must not crash-and-downgrade"


@pytest.mark.parametrize("payload_sid", [None, "", "  "])
def test_null_lock_holder_with_absent_payload_session_never_allows(tmp_path, repo, payload_sid):
    """Regression pin for a bypass introduced while fixing the session_id crash.

    Coercing the holder (`str(None) -> ""`) made a null lock.session_id compare EQUAL to
    an absent payload session_id (also ""), silently PERMITTING a non-owner write that
    the original cross-type `!=` correctly denied. Ownership must never be inferred from
    two empty strings.
    """
    entry = _repo_entry(repo, state="IN_PROGRESS")
    entry["lock"] = {"session_id": None, "claimed_at": "2026-01-01T00:00:00Z",
                     "heartbeat_at": "2999-01-01T00:00:00Z"}
    _write_registry(tmp_path, entry)
    d = _run_guard(tmp_path, "git commit -m x", cwd=str(repo),
                   session_id=payload_sid if payload_sid is not None else "")
    assert d is not None, "null holder + empty payload session resolved to a SILENT ALLOW"
    assert d["permissionDecision"] in ("ask", "deny")
    assert "malformed lock.session_id" in d["permissionDecisionReason"]


@pytest.mark.parametrize("bad_lock", ["a-string", ["s"], 42, 3.5])
def test_malformed_lock_object_fails_closed(tmp_path, repo, bad_lock):
    """A non-dict `lock` cannot establish ownership -> explicit fail-closed decision."""
    entry = _repo_entry(repo, state="IN_PROGRESS")
    entry["lock"] = bad_lock
    _write_registry(tmp_path, entry)
    d = _run_guard(tmp_path, "git commit -m x", cwd=str(repo))
    assert d is not None, "malformed lock produced a silent allow"
    assert d["permissionDecision"] in ("ask", "deny")
    assert "malformed write-lock" in d["permissionDecisionReason"]


def test_malformed_lock_does_not_outrank_branch_mismatch_deny(tmp_path, repo):
    """Categorical deny precedence survives the lock hardening."""
    entry = _repo_entry(repo, state="IN_PROGRESS")
    entry["lock"] = {"session_id": {"nonsense": True}, "claimed_at": "x"}
    entry["branch"] = "some/other-branch"
    _write_registry(tmp_path, entry)
    d = _run_guard(tmp_path, "git commit -m x", cwd=str(repo))
    assert d["permissionDecision"] == "deny"
    assert "branch mismatch" in d["permissionDecisionReason"]


def test_valid_matching_lock_still_allows(tmp_path, repo):
    """The happy path is unchanged by the coercion."""
    _write_registry(tmp_path, _repo_entry(repo, state="IN_PROGRESS"))
    assert _run_guard(tmp_path, "git commit -m x", cwd=str(repo)) is None


def test_spec_documents_the_implemented_check_order():
    """Spec's Order column must match the order checks appear in the guard source.

    Compares relative ordering only — not exact text — so ordinary wording edits to
    either file cannot break it, but a real order divergence will.
    """
    src = io.open(GUARD, encoding="utf-8").read()
    # Anchor on each check's own section comment (`# <id> — ...`), which is unique.
    # NOT on the emitted messages: checks 2 and 3 are deliberately re-evaluated inside
    # the 4a-pre precedence guard, so their text appears twice and a text search would
    # report the copy rather than the canonical check site.
    code_pos = {}
    for line_no, line in enumerate(src.splitlines()):
        stripped = line.strip()
        for cid in ("4a-pre", "4a", "2", "3", "4", "5"):
            if stripped.startswith("# %s — " % cid) and cid not in code_pos:
                code_pos[cid] = line_no
    missing = {"4a-pre", "4a", "2", "3", "4", "5"} - set(code_pos)
    assert not missing, "guard is missing check section comments for: %s" % sorted(missing)
    code_order = [k for k, _ in sorted(code_pos.items(), key=lambda kv: kv[1])]

    spec = io.open(os.path.join(CAMPAIGNS, "OWNERSHIP-GUARD-SPEC.md"), encoding="utf-8").read()
    ordinal = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "6th": 6, "7th": 7}
    rows = []
    for line in spec.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 2 and cells[1] in ordinal and cells[0] in code_pos:
            rows.append((ordinal[cells[1]], cells[0]))
    spec_order = [name for _, name in sorted(rows)]

    assert spec_order == code_order, (
        "OWNERSHIP-GUARD-SPEC.md Order column disagrees with the implementation.\n"
        "spec: %s\ncode: %s" % (spec_order, code_order)
    )


# ------------------------------------------------------------------------ parity pins

def _load(name):
    with open(os.path.join(CAMPAIGNS, name), "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def _guard_tuple(path, const):
    """Read a module-level tuple of string literals without importing the hook.

    The hooks live at `.claude/hooks/` with hyphenated filenames, so they are not
    importable as modules; parsing the literal is the honest way to pin parity.
    """
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == const for t in node.targets
        ):
            return set(ast.literal_eval(node.value))
    raise AssertionError(f"{const} not found in {path}")


NEW_STATE = "MERGED_PENDING_ARCHIVE"


def test_new_state_declared_in_schema_and_policies():
    schema_enum = set(
        _load("schema.json")["properties"]["campaigns"]["additionalProperties"]
        ["properties"]["state"]["enum"]
    )
    assert NEW_STATE in schema_enum
    assert NEW_STATE in set(_load("policies.json")["state_enum"])


def test_state_enum_parity_schema_policies_and_both_hooks():
    """One concept, five homes (known debt) â€” this pin turns silent drift into a failure."""
    schema_enum = set(
        _load("schema.json")["properties"]["campaigns"]["additionalProperties"]
        ["properties"]["state"]["enum"]
    )
    assert schema_enum == set(_load("policies.json")["state_enum"])
    assert schema_enum == _guard_tuple(GUARD, "KNOWN_STATES")
    assert schema_enum == _guard_tuple(BANNER, "KNOWN_STATES")


def test_restricted_state_parity_policies_spec_and_both_hooks():
    guard_restricted = _guard_tuple(GUARD, "RESTRICTED_STATES")
    assert guard_restricted == _guard_tuple(BANNER, "RESTRICTED")

    matrix = _load("policies.json")["state_operation_matrix"]
    policy_restricted = {
        k for k, v in matrix.items()
        if not k.startswith("_") and k not in ("OTHER_STATES", "UNKNOWN_STATE")
        and "commit" in (v.get("denied") or [])
    }
    assert guard_restricted == policy_restricted

    with open(os.path.join(CAMPAIGNS, "OWNERSHIP-GUARD-SPEC.md"), "r",
              encoding="utf-8") as fh:
        spec = fh.read()
    for state in guard_restricted:
        assert state in spec, f"{state} missing from the guard spec matrix"


def test_expected_head_is_documented_as_branch_tip_only():
    desc = (
        _load("schema.json")["properties"]["campaigns"]["additionalProperties"]
        ["properties"]["expected_head"]["description"]
    )
    assert "BRANCH-TIP" in desc.upper()
    assert "never a main-side" in desc or "never a main" in desc


def test_merge_object_is_optional_and_documented_inert():
    props = _load("schema.json")["properties"]["campaigns"]["additionalProperties"]
    assert "merge" not in props["required"], "`merge` must stay optional (old records)"
    assert "expected_head" in props["required"], "`expected_head` must stay required"
    merge = props["properties"]["merge"]
    assert set(merge["properties"]) == {"pr", "squash_sha", "merged_at"}
    assert "INERT" in merge["description"].upper()


def test_no_deployment_lifecycle_fields_in_campaign_schema():
    """Deployment/UAT/production state belongs to PROJECT_STATE.md, not here."""
    props = _load("schema.json")["properties"]["campaigns"]["additionalProperties"]["properties"]
    forbidden = {"deployment", "production_validation", "uat", "business_owner_signoff",
                 "production_complete", "deployed_sha", "deploy_reported_at"}
    assert not (forbidden & set(props)), "campaign registry must not own deployment lifecycle"
    assert not (forbidden & set(props["merge"]["properties"]))
