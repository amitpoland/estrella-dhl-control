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
def test_unknown_or_invalid_state_fails_closed_with_diagnostic(tmp_path, state):
    """An undeclared state must never fall through to write-permitted behaviour.

    `MERGED_VERIFIED` is the real transport-m1 value that sat outside every enum.
    """
    entry = _entry(state="IN_PROGRESS")
    entry["state"] = state
    _write_registry(tmp_path, entry)
    d = _run_guard(tmp_path, f"git commit -m x  # {BRANCH}")
    assert d is not None, "unknown state fell through to a silent allow"
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
