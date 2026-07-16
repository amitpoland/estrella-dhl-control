# Active-campaign registry (`.campaigns/active.json`)

Operator-ratified policy (2026-07-16), born from the MEDIUM-2 transport-tip churn incident:
one campaign branch was reset by three different writers in under an hour because branch
ownership and the canonical tip lived only in chat threads, session memory, and reflog
archaeology. `active.json` is the single machine-readable authority that replaces that
guesswork. It composes with — does not replace — the CLAUDE.md PATH-GUARD working-tree
registry and WORKTREE DISCIPLINE.

## The four rules

1. **One branch = one implementation owner.** The `owner` named in `active.json` is the only
   session that may write the branch (commit, reset, cherry-pick, rebase, force-move). Every
   other session is READ-ONLY on it, regardless of what any chat message or review verdict says.
2. **One campaign = one worktree.** Reuse the registered worktree. A new worktree needs
   explicit operator approval and lives under `C:\PZ-wt\<slug>`; it is archived at campaign
   close.
3. **The canonical SHA is registry-authoritative.** The branch tip must equal `canonical_sha`.
   A tip that differs from the registry is an incident — regardless of author or intent —
   and must be reported, not silently "fixed" by another reset.
4. **Every session reads this file first.** Before any write to a campaign branch, read
   `active.json`. Never reconstruct ownership or the canonical tip from reflog, chat threads,
   or memory files.

## Update protocol

A lagging registry is as dangerous as none, so:

- **Update-BEFORE-write, owner-only.** The owner updates `canonical_sha`/`status` as part of
  the same action that moves the branch — the registry entry is the CONSULTED AUTHORITY the
  reset targets, not a mirror written after the fact. Only the owner writes its campaign entry.
- **Superseded SHAs are recorded, tagged, and dispositioned** (e.g. "NEVER cherry-pick") in
  the `superseded` list — they are never merely deleted.
- **`status` is an explicit enum:** `IN_PROGRESS` → `READY_FOR_REBASE_AFTER_<gate>` →
  `REBASED_PENDING_REVIEW` → `PR_OPEN` → `MERGED` → entry moved to the closed log.
- **Campaign close** = remove the entry from `active.json` + archive the worktree.

## Why this file exists (worked example)

In the 2026-07-16 incident, a second session — instructed to run an independent candidate
comparison — reset the campaign branch to the losing candidate. With this registry present,
that session would have read `owner = M1-gate session` and `canonical_sha = 14d629f5` before
touching the branch, seen that it owned neither, and stopped. The A-vs-B tip churn does not
happen.
