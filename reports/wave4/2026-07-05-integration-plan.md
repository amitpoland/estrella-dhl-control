# Safe Integration Plan — merge `origin/main` into the RC line (2026-07-05)

**Plan only. No merge, no push, no PR, no code executed.** Goal: bring
`feat/w4-item11-source-extraction` (198 ahead / 15 behind) up to date with
`origin/main` **without** touching the RC branch or operator WIP.

Merge-base: `aa414d90`. **True conflict set = 52 files** (files changed by BOTH
sides since the merge-base — computed via merge-base, not the polluted two-dot diff).

## 1. Exact branch strategy — isolated **git worktree** (no stash)

Use a separate worktree so the primary working tree (which holds the uncommitted
operator WIP — `pz-api.js` dedup + `.claude` files + untracked
`.claude/skills/wfirma-api-integration/`) is **never touched**, and the RC branch
stays byte-for-byte pristine. `git stash` is NOT used (operator directive).

- Worktree dir: `../pz-verify-integration` (outside the repo tree).
- Integration branch: `integration/w3-w4-rc`, based on the RC tip.
- The merge happens entirely in that worktree; the primary `C:\PZ-verify` tree and
  the RC branch are inert throughout.
- **Fallback (only if worktrees are unavailable):** create a WIP parking branch
  `wip/operator-parking-2026-07-05`, commit the operator WIP there for durable
  recovery, `git restore` the primary tree clean, then create `integration/w3-w4-rc`
  in place. (Worktree is preferred — it needs no WIP move at all.)

## 2. Conflict-resolution policy per file group

| Group | Files | Policy |
|---|---|---|
| **A — governance skills (50)** | all `.claude/skills/*` (clean-code, design, fullstack-governance, master, webapp-testing) + `.claude/SKILL_ROUTING.md` + `.claude/capabilities/SKILLS.md` | **MAIN WINS** (`--theirs`). Duplicate-add: #816/#817 already landed the canonical suite; the branch's copies are redundant. |
| **B — CLAUDE.md (1)** | `CLAUDE.md` | **HAND-MERGE (union).** Keep the branch's Phase-C Constitution + Wave-3/4 Engineering Lessons AND main's #816/#817 skill-routing / freeze-policy additions. Never drop either side. |
| **C — pz-api.js (1)** | `service/app/static/v2/pz-api.js` | **HAND-MERGE (union).** Union the branch's Wave-3/4 transport wrappers with main's changes. **Do NOT** introduce the operator dedup WIP — leave the duplicate `uploadPackingList` as-is (harmless; operator dedups separately, unapproved here). |
| **D — auto-resolved to main (no conflict)** | `carrier/adapters/live.py`, `test_carrier_live_adapter.py`, `test_carrier_product_discovery.py` (#810–814); `static/v2/master-page.jsx` (#809); `static/customer-master-v2.html` | **MAIN WINS automatically** — the branch never modified these, so the merge fast-forwards them to main's version with zero conflict. Exactly the desired outcome. |
| **E — Wave-3/4 feature (no conflict)** | `proforma-detail.jsx`, `proforma-list.jsx`, `accounting-hub.jsx`, `routes_proforma.py`, `routes_accounting.py`, `routes_ledgers.py`, reports/docs | **OURS / auto.** Not in the conflict set → preserved verbatim. |

## 3. Exact command sequence (operator-run; NOT executed here)

```sh
cd /c/PZ-verify
git fetch origin

# Isolated worktree — primary tree & operator WIP untouched; RC branch pristine
git worktree add ../pz-verify-integration -b integration/w3-w4-rc feat/w4-item11-source-extraction
cd ../pz-verify-integration                    # clean tree; NO operator WIP present here

git merge --no-ff origin/main                  # conflicts: 50 .claude + CLAUDE.md + pz-api.js

# Group A — main wins:
git checkout --theirs -- .claude/skills .claude/SKILL_ROUTING.md .claude/capabilities/SKILLS.md
git add            -- .claude/skills .claude/SKILL_ROUTING.md .claude/capabilities/SKILLS.md

# Group B & C — hand-merge in an editor, then stage:
#   CLAUDE.md                        → union (branch governance + main skill-routing)
#   service/app/static/v2/pz-api.js  → union (branch wrappers + main); NO operator dedup
git add -- CLAUDE.md service/app/static/v2/pz-api.js

git diff --name-only --diff-filter=U           # must print nothing (all resolved)
git commit --no-edit                           # merge commit on integration branch ONLY
```

## 4. Rollback plan (fully isolated → trivial, zero-risk)

```sh
# a) mid-merge, before commit:
git merge --abort

# b) full teardown after the fact:
cd /c/PZ-verify
git worktree remove ../pz-verify-integration --force
git branch -D integration/w3-w4-rc
```

`feat/w4-item11-source-extraction` is never modified → guaranteed pristine. The
primary working tree (operator WIP) is never touched → nothing to restore. The
whole exercise lives in a throwaway worktree + throwaway branch.

## 5. Tests after merge (run inside the worktree)

```sh
python test_pz_regression.py                                   # expect 160/160
cd service && python -m pytest -m smoke -q                     # expect 63 passed / 1 skipped
python -m pytest tests/test_carrier_live_adapter.py \
                 tests/test_carrier_product_discovery.py -q    # now on main's #813/#814 → expect green
# frontend: @babel/preset-react transpile of proforma-detail/list, accounting-hub; V2 structural pins
```

Also confirm: the known pre-existing reds are **unchanged** (not newly introduced by
the merge); no CP4 `wfirma_create_*_allowed` flag flipped; `git diff --stat` shows
only the expected group-A/B/C resolutions plus main's auto-merged files.

## 6. First PR — **Wave-4 reuse only** (not the full W3/W4 RC)

The integration branch above is a **merge rehearsal + full-RC green proof**, not the
PR itself. For the actual first PR, carve the smallest class-scoped unit:

- **First PR = Wave-4 reuse only.** It is conflict-free, read-only, low blast radius
  (10 items: 3–4 frontend files + a few read endpoints + docs), and independently
  reviewable — satisfies PR-classification + GATE-2. Cut it as a cherry-pick of the
  Wave-4 feature commits onto a fresh branch from the freshly-merged `main`.
- **Wave-3 parity** → a separate, larger feature PR (big frontend port).
- **Governance skills** → **NO PR** (already on main via #816/#817).
- **supplier-invoice-OCR / carrier plumbing** → separate PRs (distinct concerns).

Rationale: a single 345-file / 198-commit PR mixes classes and is unreviewable;
starting with the conflict-free, read-only Wave-4 slice gets value landed under GATE 1
with minimal risk while the larger Wave-3 port is reviewed separately.
