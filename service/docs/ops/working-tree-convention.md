# Working-tree convention — VERIFY_DIR is canonical, the scratch tree is retired

> **Binding source:** the authoritative registry is the *"Canonical working-tree
> registry (PATH GUARD — permanent)"* section in `CLAUDE.md`. This document is the
> operational elaboration and is subordinate to it; if the two ever disagree,
> `CLAUDE.md` wins.

This convention exists because the same two issues produced false signals repeatedly
across the recent campaign (2B.3a / 2B.3b deploy / #434 / #432 review / #432 deploy):
an uncommitted deploy ledger riding the working tree through every `reset --hard`,
and a stale, dirty scratch clone being the directory `gh`/`git` ran from.

## The two clones on this box

| Path | Role | Authority |
|---|---|---|
| `C:\PZ-verify` | **VERIFY_DIR** — canonical working clone | **YES.** All branch/build/review/deploy work happens here. |
| `C:\Users\Super Fashion\PZ APP` | scratch clone (original project dir; holds `CLAUDE.md`) | **NO.** Retired. Do not build, branch, or judge git state from here. |

`C:\PZ` is the **production** install (NSSM `PZService`), not a git working tree —
deploys robocopy verified bytes into it; never `git` against `C:\PZ`.

## Rules

1. **All git operations target VERIFY_DIR.** Branch, commit, rebase, push, and read
   committed bytes (`git show origin/main:<path>`) from `C:\PZ-verify`. A subagent's
   first line must state its absolute path + SHA; reject any verdict not rooted in
   VERIFY_DIR.

2. **Run `gh` against an explicit repo, not an implicit cwd.** When `gh` is invoked
   from a shell whose cwd is the scratch tree, it can attempt a local pull that
   collides with the scratch tree's dirty state ("local changes would be overwritten
   by merge"). That error is a property of the scratch tree, **not** of the PR being
   merged — the GitHub-side merge still succeeds. Do not treat it as a deploy signal.

3. **The deploy ledger is append-only and must be committed promptly.**
   `.claude/memory/local-commit-deploys.jsonl` is written local-append during a deploy
   and **batched into the next docs/governance PR**. Do not let it accumulate
   uncommitted across multiple deploys — an uncommitted ledger survives `reset --hard`
   only by luck (stash/pop dance) and is one mistake away from being wiped. Each
   ledger line records: timestamp, sha, files, restart flag, EXPECTED hashes,
   `prod_size_bytes`, hash-gate result, and a note. **Never** a secret value.

4. **The scratch tree is retired, not deleted.** Default maintenance: align it to
   `origin/main` with `git reset --hard origin/main` so its tracked state stops
   diverging. `reset --hard` leaves untracked files in place (non-destructive).
   **Deletion of the scratch tree — and `git clean -fd` of its untracked pile — is an
   operator-only action.** A `SCRATCH-TREE-RETIRED.md` marker at the scratch root
   records this.

5. **Path-guard phrasing for prompts.** Campaign prompts should say
   "VERIFY_DIR (`C:\PZ-verify`) only — NOT `C:\Users\Super Fashion\PZ APP`" and pin the
   expected SHA, so a fresh session cannot accidentally act on the stale scratch clone.

6. **One session per working tree.** Only one Claude Code session may operate against
   `C:\PZ-verify` at a time. Two sessions on one tree race branch state and produce
   duplicate commits (incident 2026-06-04: `0c22cfb` committed direct-to-main by one
   session, `6ad62a6` landed on the wrong branch by another). If a second session must
   be opened to investigate while a first is mid-task, the second session must be
   read-only (no branch creates, no commits) or must use a separate git worktree.

## Operational notes

**proforma_drafts.db (0-byte stub):** `C:\PZ\app\storage\proforma_drafts.db` is an
empty 0-byte placeholder. It is NOT in the `main.py` lifespan init sequence. Real
proforma drafts live in the `proforma_drafts` table inside `proforma_links.db`.
The 0-byte file is safe to delete, but verify first:
`Select-String "proforma_drafts.db" C:\PZ-verify\service\app\main.py`
(should return nothing). Add this check before any cleanup so the file is not
silently referenced elsewhere at runtime.

## Why hard-reset of the scratch tree is safe

Before retiring, every file that mattered was confirmed to live in git or on an open
PR branch — e.g. `ADR-028-v2-shell-no-dashboard-shared.md` and
`atlas-v2-render-gate.md` are on `origin/main`; `pzservice-silent-crash-2026-06-03.md`
and `windows-deploy-runbook-template.md` are on the #437 / #435 branches. The scratch
tree's modified tracked files were stale experiments superseded by VERIFY_DIR work
(it was 11 commits behind `e49f697` at retirement). No sole copy of anything was
discarded.

## Repository Consolidation (2026-07-17) — 4-permanent-folder architecture

Operator ruling 2026-07-17 ended the worktree explosion (76 `PZ*` folders on `C:\`,
81 worktrees, 353 local branches). The permanent set is now exactly:

| Folder | Role |
|---|---|
| `C:\PZ` | Production (NSSM) — untouchable |
| `C:\PZ-main` | Integration, pinned to `main`, ff-only |
| `C:\PZ-verify` | Verification, primary git tree, source of truth |
| `C:\PZ-active` | Current implementation campaign (one at a time) |
| `C:\PZ-archive` | Cold storage: zips + salvaged evidence (not git) |

Everything else is temporary: approved worktrees live under `C:\PZ-wt\<campaign-slug>`
and are deleted when the campaign closes. Before creating any worktree: `git worktree list`
first, reuse if possible, and obtain explicit operator approval for a new one. Before
deleting any tree: salvage dirty files to `C:\PZ-archive\evidence-<date>\` and archive-tag
unique commits (`archive/<name>-<date>`).

The retired scratch clone `C:\Users\Super Fashion\PZ APP` was decommissioned 2026-07-17:
21 worktrees removed, full clone (incl. `.git`) preserved as `C:\PZ-archive\PZ-APP-retired.zip`,
folder deleted. Full disposition log: `C:\PZ-archive\dispositions-2026-07-17.log`.
