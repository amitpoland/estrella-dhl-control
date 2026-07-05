#!/usr/bin/env python
"""
Census-mode write guard — PreToolUse hook.

Active ONLY when EJ_CENSUS=1 is set in the environment.
Transparent (exit 0, no output) when EJ_CENSUS is not set.

WRITE TOOLS  (Write | Edit | MultiEdit | NotebookEdit):
  Blocked unless the target path is exactly inside:
    C:\\PZ-verify\\reports\\authority-census\\
  Every other path is denied — including .claude\\ (which must not be
  touched during a live census scan).

SHELL TOOLS  (Bash | PowerShell):
  Blocked command patterns (census is read-only; these mutate state):
    rm / Remove-Item              — file deletion
    mv / Move-Item                — file move / rename
    git commit                    — history write
    git push                      — remote write
    gh pr                         — PR creation / modification
    robocopy                      — production sync
    sc.exe  /  sc start|stop|...  — Windows service control
    nssm                          — NSSM service manager
    curl -X POST|PUT|PATCH|DELETE — external write requests

  Explicitly allowed (benign):
    mkdir / New-Item -ItemType Directory

Output: raw UTF-8 bytes (Lesson L — Windows cp1252 guard).
"""
import os
import sys
import json
import re

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Substring token — target path must CONTAIN this (case-insensitive) after
# normalization to forward slashes. .claude\ is NOT allowed — every write
# outside reports\authority-census\ is denied during census mode.
ALLOWED_WRITE_TOKEN = "reports/authority-census/"

WRITE_TOOLS = frozenset({"write", "edit", "multiedit", "notebookedit"})
SHELL_TOOLS = frozenset({"bash", "powershell"})

# (human_label, compiled_pattern)  — evaluated in order; first match wins
_SHELL_DENY = [
    ("rm",                re.compile(r"\brm\b",                     re.I)),
    ("Remove-Item",       re.compile(r"\bremove-item\b",            re.I)),
    ("mv",                re.compile(r"\bmv\b",                     re.I)),
    ("Move-Item",         re.compile(r"\bmove-item\b",              re.I)),
    ("git commit",        re.compile(r"\bgit\s+commit\b",           re.I)),
    ("git push",          re.compile(r"\bgit\s+push\b",             re.I)),
    ("gh pr",             re.compile(r"\bgh\s+pr\b",                re.I)),
    ("robocopy",          re.compile(r"\brobocopy\b",               re.I)),
    ("sc service-ctl",    re.compile(
        r"\bsc\.exe\b|\bsc\s+(?:start|stop|create|delete|config)\b", re.I)),
    ("nssm",              re.compile(r"\bnssm\b",                   re.I)),
    ("curl write",        re.compile(
        r"\bcurl\b.{0,400}-X\s+(?:POST|PUT|PATCH|DELETE)",          re.I | re.S)),
]

# ---------------------------------------------------------------------------
# I/O helpers  (BOM-tolerant stdin, same pattern as pz-danger-guard.py)
# ---------------------------------------------------------------------------

def _read_stdin_json():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    except Exception:
        try:
            raw = sys.stdin.read()
        except Exception:
            return None
    raw = raw.lstrip("﻿").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return None


def _emit(decision, reason):
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    out = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    try:
        sys.stdout.buffer.write(out)
        sys.stdout.buffer.flush()
    except Exception:
        sys.stdout.write(out.decode("utf-8", errors="replace"))


# ---------------------------------------------------------------------------
# Path extraction (handles Write, Edit, MultiEdit, NotebookEdit payloads)
# ---------------------------------------------------------------------------

def _write_path(tool_name, tool_input):
    if tool_name == "notebookedit":
        return (tool_input.get("notebook_path") or "").strip()
    return (tool_input.get("file_path") or "").strip()


def _is_census_output(path):
    """True iff the normalized target path is under reports/authority-census/."""
    norm = path.lower().replace("\\", "/")
    return ALLOWED_WRITE_TOKEN in norm


# ---------------------------------------------------------------------------
# Shell rule evaluation
# ---------------------------------------------------------------------------

def _shell_deny_label(command):
    """Return the label of the first matching deny rule, or None."""
    for label, rx in _SHELL_DENY:
        if rx.search(command):
            return label
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if os.environ.get("EJ_CENSUS", "0") != "1":
        return 0  # Not in census mode — transparent pass-through

    data = _read_stdin_json()
    if data is None:
        _emit(
            "ask",
            "census-guard [EJ_CENSUS=1]: could not parse PreToolUse payload — "
            "confirm before proceeding.",
        )
        return 0

    tool_name = (data.get("tool_name") or "").lower()
    tool_input = data.get("tool_input") or {}

    # -- write-tool guard ----------------------------------------------------
    if tool_name in WRITE_TOOLS:
        path = _write_path(tool_name, tool_input)
        if not path:
            _emit(
                "ask",
                "census-guard [EJ_CENSUS=1]: write tool with no file_path — "
                "confirm intent in census mode.",
            )
            return 0
        if _is_census_output(path):
            return 0  # Only allowed write target
        _emit(
            "deny",
            (
                f"census-guard [EJ_CENSUS=1]: blocked {tool_name} to '{path}'. "
                "Census is READ-ONLY for all paths except "
                r"reports\authority-census\."
            ),
        )
        return 0

    # -- shell guard ---------------------------------------------------------
    if tool_name in SHELL_TOOLS:
        # Defensive extraction: different shell tools use different keys.
        # Bash uses "command"; some MCP shell tools use "script" or "code".
        command = (
            tool_input.get("command")
            or tool_input.get("script")
            or tool_input.get("code")
            or ""
        )
        label = _shell_deny_label(command)
        if label:
            _emit(
                "deny",
                (
                    f"census-guard [EJ_CENSUS=1]: blocked shell pattern '{label}'. "
                    "Census mode prohibits: rm, mv, git commit, git push, gh pr, "
                    "robocopy, sc.exe, nssm, curl write requests."
                ),
            )
        return 0

    return 0  # all other tools — pass through


if __name__ == "__main__":
    sys.exit(main())
