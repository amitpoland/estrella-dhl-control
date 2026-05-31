#!/usr/bin/env python
"""
PZ deploy / merge PreToolUse guard.

Purpose: before Claude Code runs a *production deploy* or a *merge/push-to-main*
shell command, ask the operator to confirm (interactive "ask") — NOT a hard block.
For every other command the guard stays completely silent and never interferes.

Wiring: registered as a PreToolUse hook in .claude/settings.json with
matcher "Bash|PowerShell" (the two shell tool names on this box). Claude Code
pipes the PreToolUse event JSON to this script on stdin.

Guarded when the shell command (case-insensitive) matches ANY of:
  1. a copy/write INTO the prod tree:  Copy-Item | robocopy | xcopy | cp  ->  C:\PZ
  2. gh pr merge
  3. git push to main / origin main

Behaviour:
  - Guarded   -> print ONLY the permissionDecision="ask" JSON to stdout, exit 0.
  - Otherwise -> exit 0 with NO output (must never block ordinary commands).
  - Fails OPEN: any error (bad JSON, missing fields) -> exit 0, no output.
    A guard must never wedge the session; this is an "ask", not a "deny".

Output is written as raw UTF-8 bytes so the em-dash in the reason cannot trip
a cp1252 Windows console (which would otherwise crash the hook).
"""
import sys
import json
import re


def _extract_command(data):
    """Pull the shell command from a PreToolUse payload, tolerating simplified
    test payloads that put 'command' at the top level."""
    if not isinstance(data, dict):
        return ""
    tool_input = data.get("tool_input")
    if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        return tool_input["command"]
    if isinstance(data.get("command"), str):
        return data["command"]
    return ""


def _is_guarded(command):
    low = command.lower()

    # 1. copy/write into the production tree (C:\PZ)
    has_copy = (
        "copy-item" in low
        or "robocopy" in low
        or "xcopy" in low
        or re.search(r"\bcp\b", low) is not None
    )
    targets_pz = ("c:\\pz" in low) or ("c:/pz" in low)
    if has_copy and targets_pz:
        return True

    # 2. gh pr merge
    if "gh pr merge" in low:
        return True

    # 3. git push to main / origin main
    if "git push" in low and re.search(r"git\s+push\b[^\n]*\bmain\b", low):
        return True

    return False


def main():
    # BOM-transparent read (Lesson L). Read BYTES and decode utf-8-sig so a
    # leading UTF-8 BOM (EF BB BF) is stripped regardless of the console code
    # page. Text-mode stdin on Windows decodes those bytes as 3 cp1252 chars
    # ("ï»¿"), which would break json.loads and make the guard silently
    # fail-open (never ask) — the dangerous failure mode.
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    except Exception:
        try:
            raw = sys.stdin.read()
        except Exception:
            return 0
    # Defensive: strip a proper BOM char and a mis-decoded BOM, then whitespace.
    raw = raw.lstrip("﻿").lstrip("ï»¿").strip()
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        return 0  # fail open — never block on malformed input

    command = _extract_command(data)
    if not command.strip():
        return 0

    if _is_guarded(command):
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": "PZ guard: production deploy / merge — confirm before running.",
            }
        }
        try:
            sys.stdout.buffer.write(
                json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            )
            sys.stdout.buffer.flush()
        except Exception:
            # As a last resort, ASCII-escaped JSON is still valid + parses identically.
            sys.stdout.write(json.dumps(payload, separators=(",", ":")))
        return 0

    # ordinary command — silent, never blocks
    return 0


if __name__ == "__main__":
    sys.exit(main())
