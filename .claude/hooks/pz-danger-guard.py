#!/usr/bin/env python
"""
PZ danger-command PreToolUse guard.

Purpose: hard-deny obviously destructive or audit-bypassing shell commands;
ask before a known-needed-but-dangerous command (git reset --hard).

Wiring: registered as a PreToolUse hook in .claude/settings.json with
matcher "Bash|PowerShell" alongside pz-deploy-guard.py.

Deny rules (case-insensitive substring; permissionDecision="deny"):
  - rm -rf | rm -r / | rmdir / | chmod 777
  - .env.prod | production.config | prod.settings
  - "stella.mail" | "simplex.mail" | "zoho.mail"           (deprecated Zoho connectors)
  - git commit --no-verify | git commit -n                 (skips pre-commit gate)

Ask rules (permissionDecision="ask"):
  - git reset --hard                                       (needed for rollback)

Behaviour:
  - Match deny rule -> permissionDecision="deny" JSON, exit 0.
  - Match ask rule  -> permissionDecision="ask"  JSON, exit 0.
  - No match        -> exit 0 silently.
  - Unparseable     -> permissionDecision="ask"  JSON, exit 0 (surface to operator).

Output is written as raw UTF-8 bytes so non-ASCII reason text cannot trip
a cp1252 Windows console (Lesson L).
"""
import sys
import json
import re


# ---- BOM-transparent stdin read (cloned from pz-deploy-guard.py) -----------
def _read_stdin_json():
    """Return parsed JSON payload, or None on read/parse failure."""
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


# ---- Rule tables -----------------------------------------------------------
# Each rule = (label-for-reason, predicate(low) -> bool).
def _has(sub):
    return lambda low, s=sub: s in low


def _re(pat):
    rx = re.compile(pat)
    return lambda low, rx=rx: rx.search(low) is not None


DENY_RULES = [
    # Destructive filesystem
    ("rm -rf",            _re(r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\b|\brm\s+-[a-z]*f[a-z]*r[a-z]*\b")),
    ("rm -r /",           _re(r"\brm\s+-r\s+/")),
    ("rmdir /",           _re(r"\brmdir\s+/")),
    ("chmod 777",         _has("chmod 777")),
    # Production config touch
    (".env.prod",         _has(".env.prod")),
    ("production.config", _has("production.config")),
    ("prod.settings",     _has("prod.settings")),
    # Deprecated Zoho connectors (quoted form per global script)
    ('"stella.mail"',     _has('"stella.mail"')),
    ('"simplex.mail"',    _has('"simplex.mail"')),
    ('"zoho.mail"',       _has('"zoho.mail"')),
    # Audit-bypass: skipping pre-commit gate
    ("git commit --no-verify", _has("git commit --no-verify")),
    ("git commit -n",     _re(r"\bgit\s+commit\b[^\n]*\s-n(\s|$)")),
]

ASK_RULES = [
    ("git reset --hard",  _re(r"\bgit\s+reset\s+--hard\b")),
]


def _classify(command):
    """Return ('deny'|'ask'|None, label-or-None)."""
    low = command.lower()
    for label, pred in DENY_RULES:
        if pred(low):
            return ("deny", label)
    for label, pred in ASK_RULES:
        if pred(low):
            return ("ask", label)
    return (None, None)


# ---- Output ----------------------------------------------------------------
def _emit(decision, reason):
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    try:
        sys.stdout.buffer.write(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )
        sys.stdout.buffer.flush()
    except Exception:
        sys.stdout.write(json.dumps(payload, separators=(",", ":")))


def main():
    data = _read_stdin_json()
    if data is None:
        # Unparseable -> surface to operator (do NOT silently allow).
        _emit("ask", "PZ danger-guard: could not parse PreToolUse payload — confirm before running.")
        return 0

    command = _extract_command(data)
    if not command.strip():
        return 0

    decision, label = _classify(command)
    if decision == "deny":
        _emit("deny", f"PZ danger-guard: blocked rule '{label}' (destructive / audit-bypass).")
        return 0
    if decision == "ask":
        _emit("ask", f"PZ danger-guard: rule '{label}' is dangerous-but-allowed — confirm before running.")
        return 0

    # ordinary command — silent, never blocks
    return 0


if __name__ == "__main__":
    sys.exit(main())
