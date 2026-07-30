# PR #1030 — RBAC structural allowlist classifier: FINAL CLOSURE (post-merge)

**Date:** 2026-07-28 (post-merge verification) · closure record dated 2026-07-29 per operator instruction
**Session:** primary `C:\PZ-verify` (9742361b)
**Status:** ✅ **MERGED · VERIFIED ON origin/main · CLOSED**
**Supersedes/finalizes:** `reports/campaigns/2026-07-28-pr1030-rbac-classifier-closure.md` (pre-merge verification + handoff record).

---

## Verified repository truth

| Field | Value |
|---|---|
| **PR number** | #1030 (`fix/rbac-privileged-auth-classifier`) |
| **Reviewed head SHA** | `eeeb6e26d89719a45b3d1cd03fcb393c47e31b36` |
| **Merge SHA** (squash) | `f12f9c90040c411bc9e42a68042bd1e3c8903eed` |
| **Final `origin/main` SHA** | `f12f9c90040c411bc9e42a68042bd1e3c8903eed` |
| **Merged at** | 2026-07-28T21:10:59Z |
| **Merge method** | squash + delete-branch |

### Merge integrity checks (all pass)
- Operator merged the **exact reviewed head** — merged `headRefOid` = `eeeb6e26…` (unchanged from review). ✓
- `git merge-base --is-ancestor f12f9c90 origin/main` → **YES** (f12f9c90 is the origin/main tip). ✓
- `origin/main` advanced `776d327f → f12f9c90` by fast-forward on the local verify clone. ✓

### Changed-file list (the merge commit)
```
service/tests/test_rbac_structural_allowlist.py | 89 +++++++++++----------- (1 file changed, 49 insertions(+), 40 deletions(-))
```
**Exactly one file** — the approved RBAC test. No other file entered the merge.

### RBAC test result — authoritative, clean tree
Ran from `C:\PZ-verify` after `git switch main` + `git pull --ff-only origin main` (HEAD = `f12f9c90`):
```
pytest tests/test_rbac_structural_allowlist.py -v
6 passed in 10.10s
```
- `test_no_new_bare_mutation_routes` PASSED
- `test_no_stale_allowlist_entries` PASSED — 33 privileged routes (29 proforma + 4 inventory-returns) absent from the bare allowlist; the 6 later carrier/warehouse hardening removals remain reconciled
- `test_allowlist_count_matches_scan` PASSED — **bare-route scan count == allowlist size**
- `test_scanner_finds_mutation_routes` PASSED
- `test_privileged_routes_still_present` PASSED
- `test_require_api_key_privileged_is_privileged` PASSED — `require_api_key_privileged` recognized as privileged (`_PRIVILEGED_AUTH_NAMES`, line 87)

`origin/main` was **RED** on `test_allowlist_count_matches_scan` before this PR (106 bare != 135 allowlist, 29 stale proforma). It is now **GREEN**. Classifier gap CLOSED.

### Prior smoke result
Pre-commit smoke hook on the reconciliation merge (eeeb6e26): **63 passed / 1 skipped**.

---

## Scope / safety confirmations

- **No runtime file changed.** No route module, no `service/app/core/security.py`, no service, no engine file. The merge diff is the test file only.
- **No production, configuration, deployment, hook, Customer Master, posting, or conversion file changed.**
- **No deployment or service restart is required or owed.** This is a test-only change with zero runtime/engine impact — nothing to sync to `C:\PZ`; no 7-agent deploy gate applies. (An invented deployment gate for a test-only PR is explicitly out of scope.)

## Reconciliation mechanism (recap)
The reconciliation was a `git merge origin/main` into the branch (not a literal hand-edit): the 6 carrier/warehouse allowlist removals are only valid once main's route-hardening (`557b9eb3` carrier `require_role`; `1b349ed9`/`ef80a3f9` warehouse `require_api_key_privileged`) is present. git's 3-way merge auto-combined branch −33 + main −6 → allowlist 102 == 102 with **zero manual test-file edits**. Net PR diff vs main stayed test-file-only throughout.

## GATE-2 occupancy
Open implementation PRs: 2 → **1** (#1030 merged; **#958 remains deferred and unresolved**).

## Post-merge governance
- `flow-context-keeper` fired (RULE 3 — PR merged to main) to record verified FACTS in `PROJECT_STATE.md`.
- `agent-performance-observer` not triggered (no FINAL REPORT header, zero subagents this campaign).
- Worktree `C:\PZ-wt\rbac-1030` removed at handoff; remote branch deleted by the squash-merge `--delete-branch`.
