#!/usr/bin/env python
"""
Campaign session-start banner (operator second ruling §7).

Every session opens by emitting ONLY the compact campaign card per active
campaign — Campaign / Owner / State / Expected HEAD / Worktree / Allowed
operations — so no session reconstructs context from chat history.

SessionStart hook; stdout becomes session context. Silent when no registry
or no campaigns. Never blocks, never fails the session (all errors -> exit 0).
"""
import json
import os
import sys

# Parity with campaign-branch-guard.RESTRICTED_STATES, .campaigns/policies.json
# state_operation_matrix, and OWNERSHIP-GUARD-SPEC.md — pinned by
# service/tests/test_campaign_branch_guard.py.
RESTRICTED = ("FROZEN", "LOCKED", "DEPLOYING", "ARCHIVED", "MERGED_PENDING_ARCHIVE")

# Declared lifecycle states (.campaigns/schema.json + policies.json.state_enum).
# An entry outside this set is displayed as write-restricted: the guard fails closed
# on it, and the banner must not imply the campaign is writable.
KNOWN_STATES = (
    "IN_PROGRESS", "READY_FOR_REBASE", "REBASED_PENDING_REVIEW", "PR_OPEN", "MERGED",
    "MERGED_PENDING_ARCHIVE", "FROZEN", "LOCKED", "DEPLOYING", "ARCHIVED",
)


def _registry_paths():
    paths = [r"C:\PZ-main\.claude\state\active-campaigns.json"]
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    if proj:
        paths.append(os.path.join(proj, ".claude", "state", "active-campaigns.json"))
    return paths


def main():
    reg = None
    for p in _registry_paths():
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8-sig") as fh:
                    reg = json.load(fh)
                break
            except Exception:
                print("[campaign-registry] registry present but unreadable — treat all "
                      "campaign branches as write-restricted until the operator repairs it.")
                return 0
    if not reg:
        return 0
    campaigns = reg.get("campaigns") or {}
    if not campaigns:
        return 0

    lines = ["[active-campaign registry — read before ANY campaign-branch write; "
             "policy: .campaigns/README.md]"]
    for name, e in campaigns.items():
        if not isinstance(e, dict):
            continue
        state = (e.get("state") or e.get("status") or "?").upper()
        phase = e.get("phase") or ""
        if state in RESTRICTED:
            allowed = "read/verify/review ONLY (write-restricted state — denied even for owner)"
        elif state not in KNOWN_STATES:
            allowed = ("UNRECOGNISED STATE — guard fails closed (ask) on any write; "
                       "operator ruling required")
        else:
            allowed = "owner writes with claimed lock; everyone else READ-ONLY"
        lines.append(
            f"  Campaign: {name} | Owner: {e.get('owner', '?')} | State: {state}"
            f"{(' / ' + phase) if phase else ''} | Expected HEAD: {e.get('expected_head', '?')}"
            f" | Worktree: {e.get('worktree', '?')} | Allowed: {allowed}"
        )
    sys.stdout.buffer.write(("\n".join(lines) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
