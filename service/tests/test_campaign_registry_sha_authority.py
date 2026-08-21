"""A recorded expected_head must be a BRANCH TIP, never a main-side commit.

This repository squash-merges, so a merged branch tip stops being reachable and
whoever updates the registry reaches for the SHA that is still visible -- the
main-side merge commit. Two of three entries were written that way.

Detection is containment, not ancestry: a genuine branch tip appears in one or
two refs; a main-side commit appears in dozens. The registry schema already
forbids this in prose (`sha_authority`); nothing enforced it until now.

The registry is gitignored operational state, so this test SKIPS where the file
is absent (CI) and runs where it exists (the workstation that owns it).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# The registry is gitignored, so a worktree does not carry it. Its canonical
# location is absolute (policies.json: operational_registry.canonical_location);
# prefer the repo-relative copy, fall back to the canonical tree, so the test
# actually RUNS on the host that owns the registry instead of always skipping.
_CANONICAL = Path("C:/") / "PZ-main" / ".claude" / "state" / "active-campaigns.json"
_LOCAL = REPO / ".claude" / "state" / "active-campaigns.json"
REGISTRY = _LOCAL if _LOCAL.exists() else _CANONICAL

# Threshold, not a sample: a branch tip is contained by its own branch and
# perhaps one worktree ref. Anything above this is main-side.
MAX_CONTAINING_REFS = 5

# Both 2026-08-21 offenders were corrected on 2026-08-22, so no entry is
# exempt any more and the assertion below stands unconditionally.
#
# The first version of this test carried them as `pytest.xfail(...)` calls.
# That was wrong twice over: imperative xfail ABORTS the test before the
# assertion runs, so a corrected entry could never XPASS and the check could
# never observe its own success -- the very thing it was written to detect.
# A check that cannot report "fixed" is not a check.


def _entries():
    if not REGISTRY.exists():
        return []
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except ValueError:
        pytest.fail("operational registry is unreadable")
    return sorted((data.get("campaigns") or {}).items())


def _branch_tip(branch):
    out = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--verify", "refs/heads/" + branch],
        capture_output=True, text=True, timeout=30)
    return out.stdout.strip() if out.returncode == 0 else None


def _containing_refs(sha):
    out = subprocess.run(
        ["git", "-C", str(REPO), "branch", "-a", "--contains", sha],
        capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        pytest.skip("SHA %s is not resolvable in this clone" % sha[:12])
    return [line for line in out.stdout.splitlines() if line.strip()]


@pytest.mark.parametrize("name,entry", _entries() or [("none", None)])
def test_expected_head_is_a_branch_tip_not_a_main_side_sha(name, entry):
    if entry is None:
        pytest.skip("no operational registry on this host")
    head = (entry.get("expected_head") or "").strip()
    if not head and not (entry.get("last_verified_head") or "").strip():
        # SCOPE REGISTRATION (R12) requires the entry to exist BEFORE the first
        # commit, and at that moment there is no branch tip to record. Both head
        # fields empty is that state, and it is legitimate. One empty and one
        # set is not, and falls through to the assertion below.
        pytest.skip("%s: registered pre-first-commit, no tip yet (R12)" % name)
    assert head, "%s has last_verified_head but no expected_head" % name

    branch = (entry.get("branch") or "").strip()
    tip = _branch_tip(branch) if branch else None
    if tip:
        # The EXACT test. Containment was only ever a proxy for it, and the proxy
        # is ambiguous: a main-side merge commit and a branch tip that has since
        # been merged both appear in dozens of refs. The branch ref is the fact,
        # so use the fact wherever the branch still exists.
        assert tip.startswith(head) or head.startswith(tip[:len(head)]), (
            "%s: expected_head %s is not the tip of %s (tip is %s). A registry "
            "records the BRANCH TIP; a main-side merge or squash commit "
            "identifies nothing (registry rule `sha_authority`)."
            % (name, head[:12], branch, tip[:12]))
        return

    # Branch deleted (the usual squash-merge outcome): fall back to containment.
    # A genuine tip is carried by one or two refs; a main-side commit by dozens.
    refs = _containing_refs(head)
    assert len(refs) <= MAX_CONTAINING_REFS, (
        "%s: branch %r no longer exists and expected_head %s is contained by %d "
        "refs -- that is a main-side commit, not a branch tip"
        % (name, branch, head[:12], len(refs)))
