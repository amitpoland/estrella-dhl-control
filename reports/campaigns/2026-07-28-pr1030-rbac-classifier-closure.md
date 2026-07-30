# PR #1030 — RBAC structural allowlist classifier: verification + reconciliation closure

**Date:** 2026-07-28
**Session:** primary `C:\PZ-verify` (9742361b)
**Branch:** `fix/rbac-privileged-auth-classifier` @ **eeeb6e26** (pushed)
**Base:** `origin/main` @ **776d327f**
**Status:** ✅ **VERIFIED · MERGE-READY · HANDED OFF TO OPERATOR** (autonomous merge blocked by the operator-only merge guard — this is the enforced backstop, not a defect)
**Constraint honored:** allowed edit surface = `service/tests/test_rbac_structural_allowlist.py` only. No runtime route, `security.py`, config, deploy script, hook, Customer Master, or posting/conversion file touched. No production contact. No deploy. No service restart.

---

## 1. What the PR does

Teaches the RBAC structural classifier to recognize `require_api_key_privileged` as a **privileged** guard (adds it to `_PRIVILEGED_AUTH_NAMES`) and removes the now-privileged routes from the bare `_BARE_AUTH_ALLOWLIST`. Test-only change; **no runtime authorization is altered**. `require_api_key_privileged` (`service/app/core/security.py:62`) is `require_api_key` plus a fail-closed `_WRITE_CAPABLE_ROLES` gate (403 for non-write-capable sessions) — genuinely privileged, so the classifier was under-counting it as bare.

## 2. Six source-truth verifications (Phase 2 — all confirmed against route source, not comments/names)

| Removed from bare allowlist | Guard on current main | Privileged? | Landed by |
|---|---|---|---|
| 29 × `routes_proforma.py` mutation routes | `require_api_key_privileged` (`_auth_write`) | ✅ yes | on branch base |
| 4 × inventory-returns routes | `require_api_key_privileged` | ✅ yes | on branch base |
| 3 × `routes_carrier_actions.py` (`/shipment`, `/…/do-not-use`, `/label-package`) | `require_role("admin","logistics")` | ✅ yes | **557b9eb3** (post-branch) |
| 2 × `routes_warehouse.py` (`/scan`, `/locations`) | `require_api_key_privileged` (`_auth_write`) | ✅ yes | **1b349ed9 / ef80a3f9** (post-branch) |
| 1 × `routes_warehouse_receipt.py` (`/confirm`) | `require_api_key_privileged` (`_auth_write`) | ✅ yes | **1b349ed9 / ef80a3f9** (post-branch) |

Every removal has route-source proof. No allowlist entry was deleted without confirming the route is actually privileged. No route was weakened; the runtime auth is unchanged.

## 3. The reconciliation — why a merge-of-main, not a 6-line hand-edit (material nuance for the operator)

The operator approved **Option A** ("remove the 6 verified-stale entries, 108→102, push, re-verify green, then merge"). Verification surfaced two facts that were not visible when Option A was chosen:

1. **A literal hand-edit on the branch would turn the branch RED.** The 6 carrier/warehouse removals are only valid *in the presence of main's route-hardening* (557b9eb3, 1b349ed9/ef80a3f9). The branch was cut before those merges, so on the branch's own route files those 6 routes are still bare and still need their allowlist entries — removing them there is a false-stale removal. The removals become correct **only after main's routes are present**, i.e. only via a merge/rebase of main. The merge is therefore the *required* mechanism, not scope creep.
2. **Current `origin/main` is itself RED on this test.** `test_allowlist_count_matches_scan` on main today: **106 bare != 135 allowlist** (29 stale proforma entries), because main's scanner does not yet recognize `require_api_key_privileged`. The hardening PRs tightened routes without migrating this structural test (Lesson-O class). **PR #1030 also repairs this pre-existing main breakage.**

**Mechanism used:** `git merge origin/main` into the branch. git's 3-way merge **auto-combined** both allowlist removal sets with **zero manual editing of the test file** — main's −6 and the branch's −33 reconciled to **allowlist = 102**, with `require_api_key_privileged` recognized as privileged. Because no line was hand-edited, there was no opportunity to weaken or broaden the allowlist by hand.

Arithmetic: merge-base allowlist 141 − 33 (branch) − 6 (main) = **102 bare == 102 allowlist** → green.

**Net PR diff vs `origin/main` = `service/tests/test_rbac_structural_allowlist.py` only** (confirmed via `git diff origin/main --name-only` and `gh pr view --json files`). The one-file scope is intact.

## 4. Test evidence

- RBAC structural suite on the committed merge tree (eeeb6e26): **6 passed in 6.48s**
  (`test_no_new_bare_mutation_routes`, `test_no_stale_allowlist_entries`, `test_allowlist_count_matches_scan`, `test_scanner_finds_mutation_routes`, `test_privileged_routes_still_present`, `test_require_api_key_privileged_is_privileged`).
- Pre-commit smoke hook on the merge: **63 passed, 1 skipped**.
- `origin/main` re-verified unchanged at 776d327f immediately before commit (stop-condition check).

## 5. Phase-4 merge guard (all pass)

state OPEN · not draft · head `eeeb6e26` = pushed SHA · base `main` · `MERGEABLE` / `CLEAN` · files = test file only · 0 reviews / no new comments · origin/main unchanged.

## 6. Phase-5 merge — BLOCKED (operator-only, by design)

`gh pr merge 1030 --squash` returned:
> `PZ deploy-guard: BLOCKED rule 'gh-pr-merge' — gh pr merge is operator-only unless Council-authorized — autonomous merge disabled.`

This is the standing operator-merge-only guard (Council-Authorized Merge Guard, default-off, no signer). The agent must not merge. **Operator action required.**

### Exact operator merge command
```
gh pr merge 1030 --squash --delete-branch
```
(Suggested squash subject: `fix(rbac): recognize require_api_key_privileged in structural allowlist classifier (#1030)`.)

## 7. Post-merge notes (no action taken by this session)

- **No deployment.** This is a test-only change with no runtime/route/engine impact — nothing to sync to `C:\PZ`. No 7-agent deploy gate is owed.
- After the operator merges, `origin/main` goes GREEN on `test_rbac_structural_allowlist.py` (currently RED). No further reconciliation needed.
- GATE-2 after merge: implementation PRs 2 → 1 open (#958 remains).

## 8. Worktree lifecycle

Reconciliation was performed in worktree `C:\PZ-wt\rbac-1030` (branch fully pushed to origin; no unique unpushed state remains). The worktree is removed at close of this handoff; the branch persists on origin for the operator merge.
