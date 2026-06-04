# THIS TREE IS RETIRED — do not build, branch, verify, or deploy from here

**Retired 2026-06-04.** Aligned to `origin/main` @ `e49f697`.

This directory (`C:\Users\Super Fashion\PZ APP`) is a **retired scratch clone**. It is
NOT the source of truth and NOT the NSSM AppDirectory.

## Where to work instead

| Path | Role |
|---|---|
| `C:\PZ-verify` | **Canonical** — all git / branch / build / file-hash / deploy-verify work happens here |
| `C:\PZ` | **Production** — NSSM `PZService` (port 47213); deploys robocopy verified bytes in; never `git` here |
| `C:\Users\Super Fashion\PZ APP` | **This tree — retired.** Holds `CLAUDE.md` for reference; do not act on git state from here |

Binding registry: the *"Canonical working-tree registry (PATH GUARD — permanent)"*
section in `CLAUDE.md`, and `service/docs/ops/working-tree-convention.md`
(landed in PR #440).

## Why this matters

Running `gh`/`git` from this tree produced false signals repeatedly — most visibly the
`"local changes would be overwritten by merge"` error, which is a property of this
tree's stale/dirty state, NOT of the PR being merged (GitHub-side merges still
succeeded). This tree was 11 commits behind `origin/main` with stale tracked
experiments when retired.

## State at retirement

- Tracked files hard-reset to `origin/main` (`e49f697`); tree is now tracked-clean.
- The prior dirty tracked experiments were archived (recoverable): `git stash list`
  → `stash@{0}: scratch-retire-archive-2026-06-04`.
- Untracked campaign artifacts (audit notes, throwaway smoke/dev scripts) were left in
  place — `reset --hard` does not remove untracked files.

## Operator-only actions

- **Deleting this tree** and **`git clean -fd`** of its untracked pile are operator
  decisions, not automated maintenance. Until then, keep it aligned to `origin/main`.
