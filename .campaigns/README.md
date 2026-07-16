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
3. **Only the owner moves a campaign branch.** ANY move by a non-owner, OR any move landing
   the tip on a superseded SHA, is an incident. `last_known_tip` is the owner's ADVISORY
   last-known-tip pointer (it may lag; it is NEVER a self-referential same-commit gate) —
   used as a tripwire: tip != `last_known_tip` AND you are not the owner → STOP.
4. **Every session reads this file first.** Before any write to a campaign branch, read
   `active.json`. Never reconstruct ownership or the chartered decision from reflog, chat
   threads, or memory files.

## Update protocol

A lagging registry is as dangerous as none, so:

- **The HARD authority is `owner` + `status` + `superseded[]` + `chartered_decision`** — all
  rebase-stable fields. The gate never depends on a commit hash that a commit would have to
  predict about itself.
- **The owner updates its own entry** (`status` + `last_known_tip`, best-effort) INSIDE that
  campaign's own PR diff — NOT a trailing registry-only commit, and NOT required to equal the
  commit that writes it.
- **Superseded SHAs are recorded, tagged, and dispositioned** (e.g. "NEVER cherry-pick") in
  the `superseded` list — they are never merely deleted.
- **`status` is an explicit enum:** `IN_PROGRESS` → `READY_FOR_REBASE_AFTER_<gate>` →
  `REBASED_PENDING_REVIEW` → `PR_OPEN` → `MERGED` → entry moved to the closed log.
- **Campaign close** = remove the entry from `active.json` + archive the worktree.

## Why this file exists (worked example)

In the 2026-07-16 incident, a second session — instructed to run an independent candidate
comparison — reset the campaign branch to the losing candidate. With this registry present,
that session would have read `owner = M1-gate session` and seen `eb61a012` already in
`superseded[]` before touching the branch — the HARD fields alone stop the write; SHA
equality was never needed. The A-vs-B tip churn does not happen.
