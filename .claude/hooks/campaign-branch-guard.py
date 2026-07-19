#!/usr/bin/env python
"""
Campaign-branch ownership PreToolUse guard (fail closed).

Operator ruling 2026-07-17: only an ENFORCED guard prevents un-chartered
campaign-branch writes. Spec: .campaigns/OWNERSHIP-GUARD-SPEC.md.
Registry (gitignored, never tracked): C:\\PZ-main\\.claude\\state\\active-campaigns.json,
fallback <CLAUDE_PROJECT_DIR>\\.claude\\state\\active-campaigns.json.

Behaviour:
  - Branch-write command in scope of a registered campaign -> run checks 2-6,
    deny/ask per spec table.
  - `git worktree add` -> ask (operator approval gate, WORKTREE DISCIPLINE rule 2).
  - Registry unreadable while an entry may apply -> ask (never silently allow).
  - Everything else -> exit 0 silently.

Output convention cloned from pz-danger-guard.py (raw UTF-8, Lesson L).
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HEARTBEAT_FRESH_MINUTES = 15

# Lifecycle states declared in .campaigns/schema.json + policies.json.state_enum.
# Parity with those two files and OWNERSHIP-GUARD-SPEC.md is pinned by
# service/tests/test_campaign_branch_guard.py.
KNOWN_STATES = (
    "IN_PROGRESS",
    "READY_FOR_REBASE",
    "REBASED_PENDING_REVIEW",
    "PR_OPEN",
    "MERGED",
    "MERGED_PENDING_ARCHIVE",
    "FROZEN",
    "LOCKED",
    "DEPLOYING",
    "ARCHIVED",
)

# Write-restricted: denied for ALL sessions INCLUDING the registered owner (§6).
# MERGED_PENDING_ARCHIVE joins these (ADR-campaign-state-lifecycle-sha-authority,
# 2026-07-19): the branch is merged, the worktree is still registered, and no
# legitimate write remains. Because 4a runs before check 5, a merged campaign can
# never raise a spurious branch-drift incident — drift detection stays fully active
# for every writable state and is merely superseded here by a stricter deny.
RESTRICTED_STATES = ("FROZEN", "LOCKED", "DEPLOYING", "ARCHIVED", "MERGED_PENDING_ARCHIVE")

WRITE_VERBS = re.compile(
    r"\bgit\b[^\n|;&]*?\b("
    r"commit|reset|rebase|cherry-pick|merge"
    r"|branch\s+-(?:f|d|D|m|M)\b"
    r"|checkout\s+-B\b|switch\s+-C\b"
    r"|push\s+[^\n]*--force(?:-with-lease)?"
    r")",
    re.IGNORECASE,
)
WORKTREE_ADD = re.compile(r"\bgit\b[^\n|;&]*?\bworktree\s+add\b", re.IGNORECASE)


def _read_stdin_json():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    except Exception:
        try:
            raw = sys.stdin.read()
        except Exception:
            return None
    raw = raw.strip()
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
    sys.stdout.buffer.write(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    sys.stdout.buffer.flush()


# Canonical operational-registry location. Module-level so tests can exercise the real
# guard against a fixture registry by rebinding this name in-process. Deliberately NOT
# an environment variable: an env-settable registry path would be a bypass vector in a
# fail-closed enforcement hook.
CANONICAL_REGISTRY = r"C:\PZ-main\.claude\state\active-campaigns.json"


def _registry_paths():
    paths = [CANONICAL_REGISTRY]
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    if proj:
        paths.append(os.path.join(proj, ".claude", "state", "active-campaigns.json"))
    return paths


def _load_registry():
    """Return (registry-dict-or-None, corrupt: bool)."""
    for p in _registry_paths():
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8-sig") as fh:
                    return json.load(fh), False
            except Exception:
                return None, True
    return None, False


def _norm(p):
    return os.path.normcase(os.path.normpath(p or ""))


def _git(args, cwd):
    try:
        out = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=10
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def _in_scope(entry, command_low, cwd):
    branch = (entry.get("branch") or "").lower()
    worktree = _norm(entry.get("worktree"))
    if branch and branch in command_low:
        return True
    if worktree and worktree.lower().replace("\\", "/") in command_low.replace("\\", "/"):
        return True
    if worktree and _norm(cwd).startswith(worktree):
        return True
    return False


def _heartbeat_fresh(lock):
    hb = (lock or {}).get("heartbeat_at") or (lock or {}).get("claimed_at")
    if not hb:
        return False
    try:
        ts = datetime.fromisoformat(hb.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - ts < timedelta(minutes=HEARTBEAT_FRESH_MINUTES)
    except Exception:
        return False


def main():
    data = _read_stdin_json()
    if data is None:
        return 0  # unparseable payload is handled by pz-danger-guard's ask

    tool_input = data.get("tool_input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else ""
    if not isinstance(command, str) or not command.strip():
        return 0
    command_low = command.lower()

    is_write = WRITE_VERBS.search(command) is not None
    is_wt_add = WORKTREE_ADD.search(command) is not None
    if not is_write and not is_wt_add:
        return 0

    if is_wt_add:
        _emit(
            "ask",
            "campaign-branch-guard: `git worktree add` requires explicit operator approval "
            "(WORKTREE DISCIPLINE rule 2; location must be C:\\PZ-wt\\<slug>).",
        )
        return 0

    registry, corrupt = _load_registry()
    if corrupt:
        _emit(
            "ask",
            "campaign-branch-guard: operational registry exists but is unreadable — "
            "confirm with the operator before any campaign-branch write (fail closed, check 1).",
        )
        return 0
    if not registry:
        return 0  # no registry yet -> no campaign entries to govern

    cwd = data.get("cwd") or os.getcwd()
    session_id = str(data.get("session_id") or "")

    for name, entry in (registry.get("campaigns") or {}).items():
        if not isinstance(entry, dict) or not _in_scope(entry, command_low, cwd):
            continue

        worktree = entry.get("worktree") or ""
        target_tree = worktree if os.path.isdir(worktree) else cwd
        owner = entry.get("owner", "?")
        expected = (entry.get("expected_head") or "").lower()
        state = (entry.get("state") or entry.get("status") or "").upper()
        phase = entry.get("phase") or ""

        # 4a-pre — UNKNOWN/SCHEMA-INVALID STATE (fail-closed enforcement boundary).
        # An undeclared state must NEVER fall through to write-permitted behaviour:
        # `MERGED_VERIFIED` (transport-m1, 2026-07-18) sat outside every enum and
        # would otherwise have been treated as an ordinary writable state. Surface it
        # explicitly instead of guessing intent.
        if state and state not in KNOWN_STATES:
            _emit("ask", f"campaign-branch-guard[{name}]: unrecognised campaign state "
                         f"'{state}' — not in the declared lifecycle enum "
                         f"(.campaigns/schema.json, policies.json.state_enum). Treating as "
                         f"RESTRICTED pending an operator ruling: confirm the intended state "
                         f"before any write. Fail-closed by design; never assume writable.")
            return 0
        if not state:
            _emit("ask", f"campaign-branch-guard[{name}]: campaign entry has no `state` "
                         f"(required by .campaigns/schema.json). Treating as RESTRICTED "
                         f"pending an operator ruling — fail closed, never assume writable.")
            return 0

        # 4a — STATE enforcement (operator second ruling §6): write-restricted states
        # deny EVEN FOR THE OWNER. Ownership match alone never permits a write.
        if state in RESTRICTED_STATES:
            _emit("deny", f"campaign-branch-guard[{name}]: campaign state is {state}"
                          f"{' (phase ' + phase + ')' if phase else ''} — allowed: read/verify/review; "
                          f"denied: commit/reset/rebase/cherry-pick/merge for ALL sessions including "
                          f"the owner (§6 state matrix). Operator/owner must transition the state first.")
            return 0

        actual_branch = _git(["branch", "--show-current"], target_tree)
        actual_head = (_git(["rev-parse", "HEAD"], target_tree) or "").lower()

        # 2 — branch mismatch
        if actual_branch is not None and entry.get("branch") and actual_branch != entry["branch"]:
            _emit("deny", f"campaign-branch-guard[{name}]: branch mismatch — tree has "
                          f"'{actual_branch}', registry expects '{entry['branch']}' (check 2).")
            return 0

        # 3 — worktree mismatch (command targets the campaign branch outside its registered tree)
        if worktree and not _norm(cwd).startswith(_norm(worktree)) and \
           (entry.get("branch") or "").lower() in command_low and \
           _norm(worktree).replace("\\", "/") not in _norm(command).replace("\\", "/"):
            _emit("deny", f"campaign-branch-guard[{name}]: worktree mismatch — campaign branch may "
                          f"only be written in its registered worktree {worktree} (check 3).")
            return 0

        # 4 — owner / lock (with checks 6 + stale-lock recovery folded into the
        # denial classification: a non-holder is ALWAYS denied; the message
        # distinguishes a live concurrent writer from a stale/crashed owner)
        lock = entry.get("lock")
        if not lock:
            _emit("ask", f"campaign-branch-guard[{name}]: write-lock unclaimed. Registered owner: "
                         f"{owner}. Operator must confirm this session may claim it (check 4).")
            return 0
        if lock.get("session_id") != session_id:
            if _heartbeat_fresh(lock):
                _emit("deny", f"campaign-branch-guard[{name}]: concurrent writer — lock held by "
                              f"session {lock.get('session_id', '?')[:12]}… with a fresh heartbeat; "
                              f"registered owner: {owner} (check 6).")
            else:
                _emit("deny", f"campaign-branch-guard[{name}]: owner mismatch — lock held by session "
                              f"{lock.get('session_id', '?')[:12]}… (heartbeat STALE >"
                              f"{HEARTBEAT_FRESH_MINUTES} min — possibly a crashed owner); current "
                              f"session {session_id[:12]}…; registered owner: {owner}. Stale-owner "
                              f"recovery: only the operator may reassign the lock by editing the "
                              f"registry entry (check 4).")
            return 0

        # 5 — unexpected HEAD
        if expected and actual_head and not actual_head.startswith(expected):
            _emit("deny", f"campaign-branch-guard[{name}]: unexpected HEAD {actual_head[:8]} "
                          f"(expected {expected[:8]}). File an incident and request an operator "
                          f"ruling — NEVER auto-correct (check 5).")
            return 0

        return 0  # all checks passed for the matching entry

    return 0


if __name__ == "__main__":
    sys.exit(main())
