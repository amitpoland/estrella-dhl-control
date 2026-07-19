# Ownership-guard specification (`campaign-branch-guard.py`)

Fail-closed PreToolUse guard for campaign-branch writes (operator ruling 2026-07-17).
A tracked JSON that sessions merely READ would not have stopped the 2026-07-16 16:45
un-chartered tip reversal — only an enforced guard does. This spec is TRACKED; the
guard implementation lives at `.claude/hooks/campaign-branch-guard.py` and is registered
in `.claude/settings.json` under PreToolUse `Bash|PowerShell`.

## Trigger

Any Bash/PowerShell tool call whose command contains a branch-write verb:
`git commit`, `git reset`, `git rebase`, `git cherry-pick`, `git merge`,
`git branch -f/-D/-d/-m/-M`, `git checkout -B`, `git switch -C`, `git push --force[-with-lease]`,
`git worktree add`.

## Scope resolution

The guard reads the operational registry (first hit wins):
1. `C:\PZ-main\.claude\state\active-campaigns.json` (canonical)
2. `<CLAUDE_PROJECT_DIR>\.claude\state\active-campaigns.json` (fallback)

A command is IN SCOPE for a campaign entry when any of:
- the command text mentions the campaign `branch` name,
- the command text mentions the campaign `worktree` path,
- the tool call's `cwd` is inside the campaign `worktree`.

Commands not in scope of any entry pass silently (the guard governs campaign branches
only — ordinary work is unaffected). `git worktree add` is always in scope (rule 2).

## Checks (fail closed)

Listed by check number. **Evaluation order is not check-number order** — `4a` and `4a-pre`
are evaluated before `2` and `3` (state is cheap and categorical; the branch/worktree probes
shell out to git). The order column below is authoritative and matches
`campaign-branch-guard.py`; `service/tests/test_campaign_branch_guard.py` pins the behaviour.

| # | Order | Check | On failure |
|---|---|---|---|
| 1 | 1st | Registry unreadable/corrupt while a campaign entry may apply | `ask` (surface to operator; never silently allow) |
| 4a-pre | 2nd | **STATE DECLARED**: `state` is present and appears in the lifecycle enum (`.campaigns/schema.json`, `policies.json.state_enum`) | `ask` naming the offending value — an unknown/missing state is a fail-closed boundary and must **never** fall through to write-permitted behaviour. Checks 2 and 3 are evaluated *inside* this branch first, so a bad state can never soften their categorical `deny` into an `ask`. |
| 4a | 3rd | **STATE enforcement (§6)**: campaign `state` ∉ {FROZEN, LOCKED, DEPLOYING, ARCHIVED, MERGED_PENDING_ARCHIVE} | `deny` — for ALL sessions **including the owner**; ownership match alone never permits a write |
| 2 | 4th | Branch checked out at the target tree matches the entry's `branch` (branch mismatch) | `deny` |
| 3 | 5th | Target tree is the entry's registered `worktree` (worktree mismatch) | `deny` |
| 4 | 6th | Session holds the entry's `lock` (`lock.session_id == payload session_id`) — owner mismatch | `deny`; if `lock` is null (unclaimed) → `ask` (operator confirms the claimant). A non-holder's denial is classified: fresh heartbeat (<15 min) → **concurrent writer (check 6)**; stale heartbeat → **stale/crashed owner** — only the operator may reassign the lock by editing the registry entry |
| 5 | 7th | Current HEAD starts with `expected_head` (unexpected HEAD) | `deny` + instruct: file incident, request operator ruling, NEVER auto-correct |
| 7 | n/a | `git worktree add` without operator approval | `ask` (the ask prompt IS the operator-approval gate) |

## Per-state operation matrix (§6)

| State | Allowed | Denied (all sessions, incl. owner) |
|---|---|---|
| FROZEN / LOCKED / DEPLOYING | read, verify, review | commit, reset, rebase, cherry-pick, merge, branch move |
| MERGED_PENDING_ARCHIVE | read, verify, review | commit, reset, rebase, cherry-pick, merge, branch move |
| ARCHIVED | read | all writes |
| *unknown / missing state* | — | all writes (`ask`, fail closed) |
| other declared states | owner writes with claimed lock | any non-owner write |

Registry-field divergence (`expected_head` ≠ `last_verified_head`) is governed by
`policies.json → rules.no_auto_correction`: incident report + operator ruling, never
an auto-correct — the guard's check 5 enforces the write-time actual-HEAD case.

## SHA authority (ADR-campaign-state-lifecycle-sha-authority, 2026-07-19)

`expected_head` and `last_verified_head` are **always campaign branch-tip SHAs**. Main-side
provenance for a merged campaign lives in the optional `merge` object
(`{pr, squash_sha, merged_at}`), which is **inert**: check 5 compares `expected_head` against
the worktree HEAD and **never** reads `merge.squash_sha`. Storing a squash SHA in
`expected_head` is what produced the `transport-m1` false-drift incident.

`MERGED_PENDING_ARCHIVE` covers the window where a campaign is merged but its worktree is
still registered (e.g. post-merge follow-up open). Because check 4a runs before check 5, a
merged campaign cannot raise a spurious branch-drift incident — drift detection remains fully
active for every writable state and is superseded here by a stricter deny, never disabled.

## Session-start banner (§7)

`.claude/hooks/campaign-session-banner.py` (SessionStart) emits one compact card per
active campaign — Campaign / Owner / State / Expected HEAD / Worktree / Allowed
operations — so no session reconstructs campaign context from chat history. Silent
when no registry exists; an unreadable registry prints a treat-as-restricted warning.

## Denial report

Every deny/ask emits: guard name, failed check, registered owner label, current
session id, expected vs actual HEAD, and the required next step (claim protocol,
incident filing, or operator approval).

## Lock claim protocol

The owner session (with operator approval via the check-4 `ask`) records its lock:
update the entry's `lock` to `{session_id, claimed_at, heartbeat_at}`. Only the named
owner or the operator edits an entry (see `policies.json`). Campaign close: status
`MERGED`, entry removed, worktree archived.

## Non-goals

- The guard does not manage non-campaign branches.
- The guard never mutates the registry (read-only; fail-closed decisions only).
- The guard never auto-corrects a diverged tip — divergence is an incident by design.
