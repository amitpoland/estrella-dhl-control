# Worktree governance cleanup — 2026-07-30

**Authority:** git worktree registry + CLAUDE.md *Canonical working-tree registry / WORKTREE DISCIPLINE*
(rules 1–6) + GATE 3 (branch status designation / salvage before deletion).

**Scope:** repository worktree governance only. **No application code, no production runtime, no
financial / customs / inventory / accounting / invoice-write system was read for mutation or
touched.** The only mutations performed were `git worktree remove` and `git branch -d`.

**Before:** 35 worktrees (1 main + 34 linked) · **After:** 20 worktrees (1 main + 19 linked)
**Removed:** 15 worktrees · **Branches deleted:** 10 (all via merged-only `-d`, never `-D`)
**Forced removal used:** never — `--force` was not passed on any pass.

Machine-readable inventory preserved:
`wt-before.txt` / `wt-after.txt` / `wt-state.tsv` (session scratchpad, `git worktree list --porcelain`).

---

## 1. Registry consistency (checked before any mutation)

| Check | Before | After |
|---|---|---|
| `git worktree list` entries | 35 | 20 |
| `.git/worktrees` admin dirs | 34 (= 35 − 1 main tree) | 19 (= 20 − 1 main tree) |
| `git worktree prune --dry-run` | *(empty)* | *(empty)* |
| Locked worktrees (`.git/worktrees/*/locked`) | 0 | 0 |
| Shared stash stack | 13 | **13 (unchanged)** |

**No registry inconsistency was found, and none was introduced.** One apparent anomaly was
investigated and cleared: the admin dir `.git/worktrees/PZ-sales-campaign` does not match any
worktree path, but its `gitdir` file resolves to `C:/PZ-main/.git` — it is the live `C:\PZ-main`
tree under a stale historical directory name. This is the already-documented cosmetic issue
(rename deferred to post-2B via git-supported recreation); git resolves it correctly. **Not an
orphan, not pruned, not touched.**

### Stash finding (governance-relevant, no action taken)

`git stash list` reports **13 entries from every worktree** — the stash stack lives in the common
`.git` directory and is shared repo-wide; it is *not* per-worktree state. It therefore never
blocked a removal, and `git worktree remove` does not touch it. One entry depends on a branch in
the removal set:

- `stash@{0}: WIP on fix/action-proposals-reaction-409` → commit `c2811131`

Stash entries are independent refs under `refs/stash`, so deleting the branch cannot orphan them.
**Verified after the deletion: stash count still 13, `stash@{0}` still resolves to `c2811131`.**

---

## 2. Removed worktrees (15)

Every row satisfied **all** preconditions, revalidated immediately before its own removal:
0 tracked-dirty · 0 untracked · 0 unique commits vs `origin/main` · HEAD is an ancestor of
`origin/main` · not locked · no active owner in `active-campaigns.json` · no open PR.

| # | Worktree | Branch (deleted) | HEAD | Merge evidence |
|---|---|---|---|---|
| 1 | `C:\PZ-verify\.claude\worktrees\nice-chaum-b2853b` | `fix/cliq-breaker-recovery` | `6d6d272a` | PR #1042 MERGED, deployed as `92222849` |
| 2 | `C:\PZ-verify\.claude\worktrees\busy-margulis-a73bab` | `claude/exciting-jemison-555e3d` | `dd59559f` | no PR; content in main via #1036 |
| 3 | `C:\PZ-wt\965-secfix` | `fix/965-carrier-mutation-rbac` | `557b9eb3` | PR #1002 MERGED |
| 4 | `C:\PZ-wt\dep-final` | *(detached)* | `c8be511f` | ancestor of main |
| 5 | `C:\PZ-wt\dep-secrel` | *(detached)* | `42f3efed` | ancestor of main |
| 6 | `C:\PZ-wt\deploy-1036-verify` | *(detached)* | `c7903686` | prior production SHA, superseded by `92222849` |
| 7 | `C:\PZ-wt\deploy-authority` | `fix/deploy-health-auth` | `bfb4baad` | PR #1038 MERGED |
| 8 | `C:\PZ-wt\deploy-main` | *(detached)* | `5fd29e8a` | ancestor of main |
| 9 | `C:\PZ-wt\fix-carrier-tests` | `fix/carrier-tests-logistics-role` | `d7e4bbb2` | PR #1035 MERGED |
| 10 | `C:\PZ-wt\fix439` | `fix/action-proposals-reaction-409` | `f424f397` | PR #998 MERGED |
| 11 | `C:\PZ-wt\proforma-mapping-repair` | `fix/proforma-mapping-repair` | `6bfb1c73` | PR #1021 MERGED |
| 12 | `C:\PZ-wt\salvage-964` | `salvage/customs-test-contracts` | `190558f6` | PR #999 MERGED |
| 13 | `C:\PZ-wt\sec-warehouse-965` | `fix/warehouse-apikey-disclosure` | `ef80a3f9` | PR #1034 MERGED |
| 14 | `C:\PZ-wt\shipments-trace` | *(detached)* | `d70a86ac` | ancestor of main |
| 15 | `C:\PZ-wt\wfirma-breaker-recovery` | `fix/wfirma-breaker-recovery` | `1f2d226d` | PR #1041 MERGED, deployed in `c7903686` |

**Branches deleted (10):** rows 1, 2, 3, 7, 9, 10, 11, 12, 13, 15. All with `git branch -d`
(merged-only safe delete); every one reported `Deleted branch … (was <sha>)`. The five detached
trees had no branch to delete. **No `-D` / force delete was used anywhere.**

GATE 3 archive tags were **not** required: every removed tree had **zero** unique commits against
`origin/main`, so no commit existed that deletion could strand. Salvage was likewise not required:
every tree had zero dirty and zero untracked files.

### Known cosmetic artifact — two empty directories

Rows 1 and 2 live under `C:\PZ-verify\.claude\worktrees\`. For both, git deleted every file,
removed the `.git/worktrees/<name>` admin dir, and deregistered the worktree — but the final
`rmdir` of the now-empty top-level directory returned `Permission denied` / `Device or resource
busy`, because the Claude Code host process holds open handles on its own `.claude/worktrees/`
children (row 1 was this session's own working directory).

Confirmed aftermath for both: **0 files, 0 subdirectories, deregistered from `git worktree list`,
admin dir gone, `prune --dry-run` clean.** The removal is logically complete; only two empty
folders remain:

- `C:\PZ-verify\.claude\worktrees\nice-chaum-b2853b\`
- `C:\PZ-verify\.claude\worktrees\busy-margulis-a73bab\`

They hold no data and no git state, are invisible to `git status` in `C:\PZ-verify`, and can be
deleted with a plain `rmdir` once this session exits. **Force removal was deliberately not
attempted** — the failure was an OS file lock, not a governance condition, and forcing would not
have changed the outcome. All 13 `C:\PZ-wt\*` removals completed with the directory fully gone.

---

## 3. Retained — protected (3)

| Worktree | Branch / HEAD | Reason retained |
|---|---|---|
| `C:\PZ-verify` | `fix/wfirma-resolve-mapping-error-classification` @ `160582e4` | **Main working tree** of the repository and SOURCE OF TRUTH for all git/file-hash checks. Operator-declared strictly off-limits. 2 tracked-dirty + 37 untracked files. |
| `C:\PZ-main` | `main` @ `92222849` | Permanent integration tree, pinned to `main`, ff-only. Clean. Deploy source authority. |
| `C:\PZ-pr7` | `fix/proforma-multidraft-transport-docs` @ `779c1b5f` | **Registry-owned**: `active-campaigns.json` → campaign `transport-m1`, owner "M1-gate session", state `MERGED_PENDING_ARCHIVE`, allowed operations "read/verify/review ONLY (write-restricted — denied even for owner)". Also 8 unique commits. |

---

## 4. Retained — blocked candidates (17)

Each of these failed at least one precondition. **None was removed; none was forced; no dirty or
unmerged state was discarded.**

### 4a. Blocked on dirty working state (9)

Uncommitted work would be destroyed by removal. All are `claude/*` session scratch trees under
`C:\PZ-verify\.claude\worktrees\`.

| Worktree | Branch | Tracked-dirty | Untracked |
|---|---|---|---|
| `admiring-boyd-def3fa` | `claude/admiring-boyd-def3fa` | 2 | 2 |
| `agitated-kepler-b81d6d` | `claude/agitated-kepler-b81d6d` | 4 | 1 |
| `compassionate-moser-2125c8` | `claude/compassionate-moser-2125c8` | 4 | 0 |
| `eager-wu-936eb1` | `claude/eager-wu-936eb1` | 6 | 2 |
| `friendly-blackwell-b1664e` | `claude/friendly-blackwell-b1664e` | 1 | 0 |
| `goofy-benz-e8b88f` | `claude/goofy-benz-e8b88f` | 2 | 0 |
| `hopeful-dubinsky-ce2921` | `claude/hopeful-dubinsky-ce2921` | 1 | 0 |
| `jolly-chaplygin-5f2c92` | `claude/jolly-chaplygin-5f2c92` | 2 | 0 |
| `practical-jepsen-cda6ba` | `claude/practical-jepsen-cda6ba` | 5 | 1 |

Note: all nine sit at commits already contained in `origin/main` (0 unique commits) — so the
*only* thing blocking them is the uncommitted diff. Disposition therefore requires a GATE 3
salvage pass (copy the dirty files to `C:\PZ-archive\evidence-<date>\<tree>\`, then re-evaluate),
not a removal decision. **Left for a separate, operator-visible salvage slice.**

### 4b. Blocked on unique commits not in `origin/main` (8)

Removal is safe only after each unique commit receives a GATE 3 disposition (merged, archive-tagged,
or explicitly abandoned).

| Worktree | Branch | Unique commits | Extra |
|---|---|---|---|
| `C:\PZ-wt\rollback-provenance` | `fix/rollback-provenance` | 2 | **PR #1039 OPEN — explicitly off-limits this campaign** |
| `.claude\worktrees\xenodochial-wiles-6f88af` | `integration/convert-persist-reconcile-authority` | 13 | + 3 untracked |
| `C:\PZ-wt\a1-integration` | `claude/a1-comparator-integration` | 4 | A1 comparator, believed superseded-by-content (#946) — needs archive tag before deletion |
| `C:\PZ-wt\deploy-source-authority` | `fix/deploy-source-authority` | 3 | |
| `C:\PZ-wt\packing-authority-restoration` | `fix/proforma-phase3-utf8-read` | 3 | |
| `C:\PZ-wt\reconcile-938-repair` | `fix/proforma-failed-link-recovery` | 2 | + 1 untracked |
| `C:\PZ-wt\merge-guard` | `fix/council-authorized-merge-guard` | 1 | PR #950 no longer open — needs merged/abandoned determination |
| `.claude\worktrees\issue-927-convert-test-repoint` | `test/927-repoint-convert-flow-pins` | 1 | |

---

## 5. Ownership inconsistencies observed

1. **Registry under-coverage (the significant finding).** `active-campaigns.json` records exactly
   **one** campaign (`transport-m1` → `C:\PZ-pr7`). The other 19 retained worktrees — including 17
   with dirty state or unique commits — have **no recorded owner, no campaign, and no lifecycle
   state**. Per CLAUDE.md rule 6, "a worktree that outlives its campaign is governance debt."
   Removal was still safe to refuse for all 17 (each fails a hard precondition on its own
   evidence), but the registry cannot currently answer "who owns this tree" for any of them.
2. **`fix/deploy-health-auth` (PR #1038)** was recorded in session memory as OPEN; it is in fact
   MERGED and fully contained in `origin/main`. Memory index corrected as part of this campaign.
3. **`.git/worktrees/PZ-sales-campaign`** — stale admin-dir name for the live `C:\PZ-main` tree
   (§1). Cosmetic, already documented, deliberately not touched.
4. **Worktree location non-compliance (pre-existing, not created here).** CLAUDE.md rule 3 requires
   temporary worktrees at `C:\PZ-wt\<campaign-slug>`. Eleven retained trees live under
   `C:\PZ-verify\.claude\worktrees\` (tool-created session trees). Not actionable by deletion —
   noted so the convention and the tooling can be reconciled.

---

## 6. Result against the architectural goal

| Goal | Status |
|---|---|
| One protected production/main tree | ✅ `C:\PZ-main` (clean, on `main`) |
| One explicitly protected verification tree | ✅ `C:\PZ-verify` (untouched) |
| Active campaign trees with recorded owners | ⚠️ only `C:\PZ-pr7` is registry-recorded; 17 trees remain unowned |
| No stale merged worktrees | ✅ **all 15 fully-merged, clean trees removed** |
| No ambiguous branch ownership | ⚠️ improved (10 merged branches deleted); 8 branches with unique commits still need GATE 3 disposition |
| No deletion of dirty or unmerged state | ✅ **zero dirty files and zero unique commits were deleted** |

---

## 7. Carried forward (GATE 4 dispositions owed — worktree governance only)

Kept deliberately separate from the application-layer GATE 4 items (`_wfirma_error_envelope`
disclosure, unbreakered Cliq `httpx` paths, `dhl_client` breaker audit) — those are **not** part of
this campaign.

| # | Item | Disposition | Target session |
|---|---|---|---|
| 1 | GATE 3 salvage pass for the 9 dirty `claude/*` scratch trees (§4a): salvage each to `C:\PZ-archive\evidence-2026-07-30\<tree>\`, diff against `origin/main`, then re-evaluate for removal. | **SCHEDULED** | Next worktree-governance session — **must precede** item 2, since a salvage failure changes the removal set. |
| 2 | GATE 3 disposition for the 7 unique-commit trees in §4b **excluding** `rollback-provenance`: classify each with `git cherry origin/main <branch>` (patch-equivalence, **not** ancestry — per the archive-tag durability rule), archive-tag any sole-anchor commits as `archive/<branch>-2026-07-30`, then remove. Repo is PUBLIC → tag-push is rejected by default, so tags stay local and the `C:\PZ-archive` off-box backup must be verified first. | **SCHEDULED** | Same next worktree-governance session, after item 1. |
| 3 | `C:\PZ-wt\rollback-provenance` — PR #1039 open, operator-declared off-limits. | **SCHEDULED (blocked)** | The session that closes PR #1039 (merge or abandon). Not before. |
| 4 | Register owner + lifecycle state for every retained worktree in `active-campaigns.json`, or record an explicit exemption (§5 item 1). This is the root cause that made items 1–2 necessary. | **SCHEDULED** | Same next worktree-governance session — do this **first**, so items 1–2 are executed against a registry that can answer "who owns this tree". |
| 5 | `rmdir` the two empty leftover directories in §2. | **SCHEDULED (trivial)** | Any session started after this one exits and releases the handles. |

Ordering for the next session: **4 → 1 → 2**, with 3 gated on PR #1039 and 5 available at any time.

**Not disposed here, deliberately:** the application-layer GATE 4 items carried by the Cliq/wFirma
breaker campaigns (`_wfirma_error_envelope` raw-exception disclosure; the five unbreakered
`httpx.AsyncClient` Cliq paths; `routes_pz.py:149/184` bare `post_to_channel` /
`deliver_batch_result`; the `dhl_client` `.state` audit). Those retain their existing dispositions
in `TASK_STATE.md` and the deploy closure reports. Mixing them into worktree cleanup was explicitly
out of scope.
