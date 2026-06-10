#!/usr/bin/env python
"""
PZ regression PostToolUse hook.

Purpose: after Claude Code edits or writes any .py file in the repo, run
the canonical regression suite (test_pz_regression.py, 160 tests, fast)
and surface failures IMMEDIATELY so the agent fixes them before moving on.

Wiring: registered as a PostToolUse hook in .claude/settings.json under
matcher "Edit|Write" (the file-edit tool names on this box). Claude Code
pipes the PostToolUse event JSON to this script on stdin.

Behaviour:
  - file_path does not end in .py        -> exit 0 silently (no run).
  - Suite PASSES (exit 0)                -> exit 0, one short stdout line.
  - Suite FAILS (exit != 0)              -> exit 2, last ~25 lines of
                                            combined output on stderr.
  - Stdin parse error or no file_path    -> exit 0 silently (Lesson L —
                                            never wedge the session from
                                            a malformed payload).

Portability (Lesson A1.5):
  Interpreter resolved BY EXECUTION (python3 only if it actually runs,
  otherwise python). PYTHONUTF8=1 forces UTF-8 stdio so non-ASCII test
  prints can't crash on a cp1252 console.

Test seam:
  The suite command is read from env var PZ_POSTEDIT_SUITE_CMD if set
  (whitespace-split) so the failure branch can be unit-tested with a
  guaranteed-failing throwaway command. Default:
      test_pz_regression.py
"""
import sys
import json
import os
import subprocess
import shlex


def _read_stdin_json():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    except Exception:
        try:
            raw = sys.stdin.read()
        except Exception:
            return None
    raw = raw.lstrip("﻿").lstrip("ï»¿").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return None


def _extract_file_path(data):
    if not isinstance(data, dict):
        return ""
    tool_input = data.get("tool_input")
    if isinstance(tool_input, dict) and isinstance(tool_input.get("file_path"), str):
        return tool_input["file_path"]
    if isinstance(data.get("file_path"), str):
        return data["file_path"]
    return ""


def _resolve_python():
    """Detect a working interpreter by execution (not by `command -v`).
    On Windows `python3` may be a Store-alias shim that exits non-zero at
    runtime — a PATH check is insufficient."""
    for candidate in ("python3", "python"):
        try:
            r = subprocess.run(
                [candidate, "-c", ""],
                capture_output=True,
                timeout=10,
            )
            if r.returncode == 0:
                return candidate
        except Exception:
            continue
    return None


def _suite_argv():
    """Return the suite command as a list of args. Env override wins."""
    override = os.environ.get("PZ_POSTEDIT_SUITE_CMD", "").strip()
    if override:
        return shlex.split(override, posix=False)
    return ["test_pz_regression.py"]


def _tail(text, n=25):
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def main():
    data = _read_stdin_json()
    if data is None:
        return 0  # malformed payload — never wedge the session
    file_path = _extract_file_path(data)
    if not file_path.strip():
        return 0
    if not file_path.lower().endswith(".py"):
        return 0

    python = _resolve_python()
    if python is None:
        # No interpreter — surface but do not block hard.
        sys.stderr.write("regression: no working Python interpreter found (tried python3, python)\n")
        return 2

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"

    argv = [python] + _suite_argv()
    try:
        r = subprocess.run(
            argv,
            capture_output=True,
            env=env,
            timeout=110,  # leave headroom under settings.json timeout: 120
        )
    except subprocess.TimeoutExpired:
        sys.stderr.write("regression: suite timed out (>110s)\n")
        return 2
    except Exception as e:
        sys.stderr.write(f"regression: failed to launch suite: {e}\n")
        return 2

    if r.returncode == 0:
        sys.stdout.write("regression: 160 green\n")
        return 0

    combined = (r.stdout or b"").decode("utf-8", errors="replace") + \
               (r.stderr or b"").decode("utf-8", errors="replace")
    sys.stderr.write(_tail(combined, 25))
    if not combined.endswith("\n"):
        sys.stderr.write("\n")
    sys.stderr.write(f"regression: FAILED (exit {r.returncode})\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
