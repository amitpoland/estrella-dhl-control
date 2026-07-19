#!/usr/bin/env python
"""
PZ deploy / merge / push-to-main PreToolUse guard.

Purpose: BLOCK (permissionDecision="deny") four operator-only actions that
must never be executed by Claude Code:
  1. copy/write INTO the production tree (C:\\PZ) via shell
  2. gh pr merge
  3. git push to main / origin main
  4. Edit/Write a file under C:\\PZ (closes the direct file-write path)

These are reserved for the human operator. The agent must never deploy to
prod, merge a PR, or push to main, and must never write into C:\\PZ through
any tool. The deploy-guard is a hard DENY authority — not an "ask".

Wiring: registered as a PreToolUse hook in .claude/settings.json under TWO
matchers:
  - "Bash|PowerShell" — guards shell commands (rules 1-3)
  - "Edit|Write"      — guards file_path writes into C:\\PZ (rule 4)

Behaviour:
  - Guarded shell command         -> permissionDecision="deny", exit 0.
  - Guarded Edit|Write file_path  -> permissionDecision="deny", exit 0.
  - Unparseable payload           -> permissionDecision="ask",  exit 0 (FAIL CLOSED).
  - Otherwise                     -> exit 0 with NO output (must never block
                                     ordinary commands or edits).

Output is written as raw UTF-8 bytes so non-ASCII reason text cannot trip
a cp1252 Windows console (Lesson L).
"""
import sys
import os
import json
import re


# 'C:\PZ' as a path token: exact, or followed by \ or /. Case-insensitive.
# Negative lookahead excludes C:\PZ-verify (followed by '-') and C:\PZAPP
# (followed by alphanumeric). Also covers C:/PZ variants.
PROD_PZ_RX = re.compile(r"c:[\\/]pz(?![\w\-])", re.IGNORECASE)

# The canonical deployment script. Matched by NAME because the script is
# configuration-driven: its command line carries no production path token, so the
# path-based rule cannot see it. Covers Deploy-PZ.ps1 however it is invoked
# (relative, absolute, via &, via powershell -File).
DEPLOY_SCRIPT_RX = re.compile(r"deploy-pz\.ps1", re.IGNORECASE)


def _is_prod_pz_path(text):
    """Return True if `text` contains a 'C:\\PZ' path token (case-insensitive,
    backslash or forward-slash separator). Matches C:\\PZ exactly or C:\\PZ\\...,
    C:\\PZ/.... Does NOT match C:\\PZ-verify\\..., C:\\Users\\Super Fashion\\PZ APP."""
    if not text:
        return False
    return PROD_PZ_RX.search(text) is not None


# ---- Payload extraction ----------------------------------------------------
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


# ---- Classification --------------------------------------------------------
def _classify_command(command):
    """Return (rule-label, reason) if the command is guarded, else (None, None)."""
    low = command.lower()

    # 1. copy/write into the production tree (C:\PZ)
    has_copy = (
        "copy-item" in low
        or "robocopy" in low
        or "xcopy" in low
        or re.search(r"\bcp\b", low) is not None
    )
    if has_copy and _is_prod_pz_path(low):
        return ("deploy-to-prod-PZ", "copy/write into C:\\PZ is operator-only")

    # 1b. Invocation of the canonical deployment script.
    #     Deploy-PZ.ps1 reads every production path from windows_prod_v2.json, so the
    #     command text an agent would run ('.\Deploy-PZ.ps1') contains NO C:\PZ token
    #     and rule 1 above would not fire. Without this rule, config-driving the paths
    #     would silently DISABLE the guard. Deny by script name instead of by path.
    #     Rollback is equally production-mutating and is denied by the same rule.
    if DEPLOY_SCRIPT_RX.search(low) is not None:
        return ("deploy-script-invocation",
                "Deploy-PZ.ps1 writes to production and is operator-only "
                "(-WhatIf is also denied to the agent: use the operator shell)")

    # 2. gh pr merge — Council-authorized merge gate
    #    (ADR-council-authorized-merge-gate). Default-OFF + FAIL-CLOSED: replaces
    #    the former UNCONDITIONAL denial with a narrowly-scoped, machine-verifiable
    #    authorization check. With no flag / no trusted signing key / no signed
    #    authorization artifact (the current repository state — no CI signer),
    #    evaluate_merge ALWAYS returns "deny", so the merge denial is NOT weakened.
    #    Protected files / guard self-modification / non-squash / stale head /
    #    expired / consumed / unsigned all deny. Validator error also denies.
    if "gh pr merge" in low:
        try:
            _hook_dir = os.path.dirname(os.path.abspath(__file__))
            if _hook_dir not in sys.path:
                sys.path.insert(0, _hook_dir)
            from merge_authorization import evaluate_merge as _evaluate_merge
            decision, reason = _evaluate_merge(command)
        except Exception as _exc:  # fail closed on ANY error
            decision, reason = ("deny", "merge-authorization validator error: "
                                + type(_exc).__name__)
        if decision == "allow":
            return (None, None)   # Council-authorized squash merge — permit
        return ("gh-pr-merge",
                "gh pr merge is operator-only unless Council-authorized — " + reason)

    # 3. git push to main / origin main
    if "git push" in low and re.search(r"git\s+push\b[^\n]*\bmain\b", low):
        return ("git-push-main", "git push to main is operator-only")

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


# ---- BOM-transparent stdin (Lesson L) --------------------------------------
def _read_stdin_json():
    """Return parsed JSON payload, or None on read/parse failure (fail-closed
    sentinel — caller emits 'ask')."""
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


def main():
    data = _read_stdin_json()
    if data is None:
        # Fail CLOSED — surface to operator rather than silently allowing.
        _emit("ask", "PZ deploy-guard: could not parse PreToolUse payload — confirm before running.")
        return 0

    # Shell-command path (Bash|PowerShell matcher) ---------------------------
    command = _extract_command(data)
    if command.strip():
        label, reason = _classify_command(command)
        if label is not None:
            _emit(
                "deny",
                f"PZ deploy-guard: BLOCKED rule '{label}' — {reason}. "
                f"This action is operator-only; the agent must not run it.",
            )
            return 0

    # File-path write path (Edit|Write matcher) ------------------------------
    file_path = _extract_file_path(data)
    if file_path.strip() and _is_prod_pz_path(file_path):
        _emit(
            "deny",
            f"PZ deploy-guard: BLOCKED Edit/Write into prod tree '{file_path}'. "
            f"C:\\PZ is operator-only — never edit production files directly.",
        )
        return 0

    # ordinary command/edit — silent, never blocks
    return 0


if __name__ == "__main__":
    sys.exit(main())
