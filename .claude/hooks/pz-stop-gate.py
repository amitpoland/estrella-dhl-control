#!/usr/bin/env python
"""
PZ Stop-gate hook.

Purpose: refuse to finish the turn while the regression suite is RED on
the current .py working-tree changes. Wedge-safe: no dirty .py paths in
the working tree -> allow; missing state -> allow (assumes nothing has
been edited yet this session).

Why a separate gate (and why we don't re-run tests here): B1's
PostToolUse hook already runs the suite on every .py edit and records
its outcome to .claude/.regression-state. The Stop gate just reads that
file — no redundant runs, no extra latency at end-of-turn.

One-shot override: if the operator really needs to stop on a known-red
state, create the sentinel  .claude/.allow-red-stop  (e.g. on Windows:
`New-Item .claude/.allow-red-stop`). The gate deletes it on use so it
cannot mask a second red stop.

Behaviour:
  - No dirty .py in working tree            -> exit 0 (allow).
  - State missing or "pass"                 -> exit 0 (allow).
  - State "fail" + sentinel present         -> delete sentinel, exit 0,
                                                stderr warning.
  - State "fail" + no sentinel              -> exit 2, stderr explaining.
  - Any internal error                       -> exit 0 (NEVER wedge the
                                                session from this gate).
"""
import os
import re
import sys
import subprocess


def _repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", ".."))


def _claude_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, ".."))


# Match a .py path anywhere in a porcelain line — covers staged/unstaged/
# renamed-to/untracked. Case-insensitive (.PY counts).
_PY_LINE_RX = re.compile(r"\.py(\s|$)", re.IGNORECASE)


def _has_dirty_py():
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=_repo_root(),
            capture_output=True,
            timeout=20,
        )
    except Exception:
        return False  # cannot determine -> assume not dirty -> allow
    if r.returncode != 0:
        return False
    text = (r.stdout or b"").decode("utf-8", errors="replace")
    for line in text.splitlines():
        if _PY_LINE_RX.search(line):
            return True
    return False


def _read_state():
    path = os.path.join(_claude_dir(), ".regression-state")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip().lower()
    except Exception:
        return ""  # treat as pass/missing


def _consume_override():
    path = os.path.join(_claude_dir(), ".allow-red-stop")
    if not os.path.exists(path):
        return False
    try:
        os.remove(path)
    except Exception:
        # could not delete — still treat as consumed so we don't wedge,
        # but warn so operator knows to remove it manually.
        sys.stderr.write(
            f"stop-gate: WARNING — override sentinel at '{path}' could not be "
            f"deleted; please remove manually to avoid silent reuse.\n"
        )
    return True


def main():
    try:
        if not _has_dirty_py():
            return 0
        state = _read_state()
        if state != "fail":
            return 0
        if _consume_override():
            sys.stderr.write(
                "stop-gate: RED stop OVERRIDDEN (one-shot sentinel consumed). "
                "Regression is still failing — fix before next stop.\n"
            )
            return 0
        sys.stderr.write(
            "Regression is RED — fix before finishing, or override once: "
            "touch .claude/.allow-red-stop\n"
        )
        return 2
    except Exception as e:
        # Never wedge the session from this gate.
        sys.stderr.write(f"stop-gate: internal error ignored: {e}\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())
