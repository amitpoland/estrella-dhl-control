#!/usr/bin/env python
"""
PZ frozen-file PreToolUse guard.

Purpose: before Claude Code runs an Edit or Write on a V1-frozen file,
ask the operator to confirm — NOT a hard block.

Wiring: registered as a PreToolUse hook in .claude/settings.json with
matcher "Edit|Write" (the file-edit tool names on this box). Claude Code
pipes the PreToolUse event JSON to this script on stdin.

Frozen files (CLAUDE.md Lesson F — V1 freeze):
  dashboard.html
  shipment-detail.html

Behaviour:
  - Guarded   -> print ONLY the permissionDecision="ask" JSON to stdout, exit 0.
  - Otherwise -> exit 0 with NO output.
  - Fails OPEN: any error -> exit 0, no output (never wedge the session).
"""
import sys
import json
import os


# Basenames that are V1-frozen per Lesson F.
FROZEN_BASENAMES = {
    "dashboard.html",
    "shipment-detail.html",
}


def _extract_file_path(data):
    """Pull file_path from a PreToolUse payload, tolerating simplified test
    payloads that put 'file_path' at the top level."""
    if not isinstance(data, dict):
        return ""
    tool_input = data.get("tool_input")
    if isinstance(tool_input, dict) and isinstance(tool_input.get("file_path"), str):
        return tool_input["file_path"]
    if isinstance(data.get("file_path"), str):
        return data["file_path"]
    return ""


def _is_guarded(file_path):
    if not file_path:
        return False
    basename = os.path.basename(file_path)
    return basename in FROZEN_BASENAMES


def main():
    # BOM-transparent read (same pattern as deploy guard — Lesson L).
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    except Exception:
        try:
            raw = sys.stdin.read()
        except Exception:
            return 0
    raw = raw.lstrip("﻿").lstrip("ï»¿").strip()
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        return 0  # fail open — malformed input never blocks

    file_path = _extract_file_path(data)
    if not file_path.strip():
        return 0

    if _is_guarded(file_path):
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": (
                    f"Lesson F guard: '{os.path.basename(file_path)}' is a V1-frozen file "
                    f"(dashboard.html / shipment-detail.html). "
                    f"Only critical fixes accepted — confirm intentional edit."
                ),
            }
        }
        try:
            sys.stdout.buffer.write(
                json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            )
            sys.stdout.buffer.flush()
        except Exception:
            sys.stdout.write(json.dumps(payload, separators=(",", ":")))
        return 0

    # ordinary edit — silent
    return 0


if __name__ == "__main__":
    sys.exit(main())
