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

# Known offenders, recorded 2026-08-21 and awaiting an operator correction.
# xfail(strict=False) so the suite goes GREEN the moment they are corrected --
# never relax MAX_CONTAINING_REFS to make them pass.
KNOWN_UNCORRECTED = {
    "accounting-cfo-mis": "expected_head 2f04ae1c is PR #1264's merge commit (105 refs)",
    "packing-advance": "expected_head dbd38d35 is PR #1287's merge commit (51 refs)",
}


def _entries():
    if not REGISTRY.exists():
        return []
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except ValueError:
        pytest.fail("operational registry is unreadable")
    return sorted((data.get("campaigns") or {}).items())


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
    if name in KNOWN_UNCORRECTED:
        pytest.xfail(KNOWN_UNCORRECTED[name])
    head = (entry.get("expected_head") or "").strip()
    assert head, "%s has no expected_head" % name
    refs = _containing_refs(head)
    assert len(refs) <= MAX_CONTAINING_REFS, (
        "%s: expected_head %s is contained by %d refs -- that is a main-side "
        "commit, not a branch tip (registry rule `sha_authority`)"
        % (name, head[:12], len(refs)))
