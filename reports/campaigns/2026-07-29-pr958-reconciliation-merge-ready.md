# PR #958 — Deploy Single-Authority: Merge-Ready Verification Report

**Date:** 2026-07-29
**PR:** [#958](https://github.com/amitpoland/estrella-dhl-control/pull/958) — `refactor(deploy): one deployment authority, self-verifying (replaces #955, #956)`
**Branch:** `fix/deploy-single-authority`
**Status:** OPEN · non-draft · `MERGEABLE` / `CLEAN`
**Worktree used for all git ops:** `C:\PZ-wt\deploy-authority`

---

## 1. Reconciliation Result

Brought current with `origin/main` by a **normal merge** — no squash, no history rewrite. Branch is now conflict-free and mergeable.

| Marker | SHA |
|---|---|
| Pre-merge branch HEAD (**reviewed head**) | `7846fc463fcc30ff359799a4beded921d200dc9c` |
| Merged `origin/main` | `f12f9c90040c411bc9e42a68042bd1e3c8903eed` |
| Reconciliation merge commit (parents 7846fc46 + f12f9c90) | `c4cee5cf914c8d2205deeba4d10205872eddbd65` |
| **Final branch tip** | `c08fd4187581e0db2ea6e739f9049d85f78c9107` |

Local tip == `origin/fix/deploy-single-authority` == `c08fd418`. Tree clean.

## 2. Conflict Resolution

Exactly two conflicts (recomputed against the advanced main `f12f9c90`, not the brief's older SHA):

1. **`.claude/commands/deploy.md`** → took the **branch** (109-line governance/authority-model doc). Verified it contains **no runnable** `robocopy` / `sc.exe` / `verify_deploy_close.ps1` invocation — the single "robocopy" hit is descriptive prose. Main's discarded copy was the 210-line prose-as-script runbook this PR exists to retire.
2. **`.claude/manifests/verify_deploy_close.ps1`** → took the **delete** (`git rm`). Main's edits to the retired dual-purpose deployer do not resurrect it; its version-file write was already migrated to `Deploy-PZ.ps1`.

## 3. Replacement Proof (zero live callers for deleted authorities)

Net delta over merged main = **50 files**: 34 retired manifests/scripts **deleted** (27 `windows_deploy_*.ps1`, 4 `deploy_delta_*.md`, `verify_deploy_close.ps1`, `verify_sync.py`, hygiene cleanup), one config-driven executor + validator added, `test_deploy_authority.py` added. No surviving executable caller references any deleted script. `test_deploy_authority.py` makes re-duplication a **failing test**.

## 4. Safety Preservation

`service/app/api/routes_webhooks_wfirma_status.py` (auto-merged) keeps **both**:
- main #969's BOM-tolerant reader — `_SHA_FILE.read_text(encoding="utf-8-sig").strip()` (defense-in-depth against a UTF-8 BOM), **and**
- the branch's corrected attribution comment (`Deploy-PZ.ps1` = sole writer, replacing the `verify_deploy_close.ps1` reference).

Branch-vs-main delta on that file is **comment-only**; the reader is untouched. `verify_runtime_sync.py` gains `_is_production()` so production is **never** a sync destination (safety hardening, in-scope).

## 5. Tests (post-merge, this reconciliation — no unexplained "pre-existing")

| Suite | Result |
|---|---|
| `service/tests/test_deploy_authority.py` | **29 / 29** |
| `service/tests/test_wfirma_status.py` (version-file consumer) | **44 passed, 1 skipped** (graceful) |
| Root golden `test_pz_regression.py` | **160 / 160, exit 0** |
| Both `.ps1` authorities | parse clean; config validates |
| Pre-commit smoke hook (on `c4cee5cf`) | **63 passed, 1 skipped** |

**Two writer-test failures investigated, not waved off.** Merging main surfaced two files that trip the substring writer-detector; both are genuine false positives and were added to `PRODUCTION_WRITER_ALLOWLIST` with explicit reasons rather than weakening `WRITE_RX`:
- `routes_webhooks_wfirma_status.py` — sole write-verb (`Out-File`) is inside the #969 BOM comment; file only reads `version.txt`. At reviewed head `7846fc46` the file had no write token, so the test passed there — the failure is merge-introduced, not a branch regression.
- `service/scripts/dhl-lane-b-throttle-check.ps1` (new from main) — throttle self-test writing only to `$env:TEMP`; names the production tree only in a "never touch" comment.

## 6. Review Disposition

PR #958 carries **zero GitHub review submissions and zero inline review comments**. The R1–R10 dispositions are pre-emptive self-review items in `reports/campaigns/2026-07-29-pr958-deploy-single-authority-brief.md §9` — not live reviewer threads. Nothing on GitHub is left unresolved. The PR body has been refreshed with a dated **Reconciliation with origin/main (2026-07-29)** section carrying all SHAs, conflict calls, and refreshed test counts.

## 7. Sibling PR #961 Disposition

`fix/deploy-xo-flag-consistency` was **closed unmerged by operator `amitpoland` on 2026-07-19** (10 days before this session). Its four touched files (`deploy.md`, `verify_deploy_close.ps1`, `production_deployment_rule.md`, `deploy_release_manager.md`) are all **superseded** by this consolidation. I performed **read-only** inspection only — no action taken.

## 8. Remaining Risks

- **Nothing executed against production.** Every runtime claim rests on syntax checks + unit tests. `Test-PZDeployClose.ps1`, the `-Bootstrap` first-deploy path, and artifact/backup roots are **unexercised** until a first live deploy.
- Artifact retention is unmanaged (no cleanup policy) — disk headroom needs monitoring after first use.
- File-sync exit semantics (`0-3` ok / `>=4` fatal-unless-inventory / `>=8` always fatal) confirmed only on first live convergence.
- **`.env` writer campaign:** unrelated open thread; not addressed here and not required for this PR.

## 9. Merge Guard

**Pin merge authorization to the reviewed head SHA: `c08fd4187581e0db2ea6e739f9049d85f78c9107`.** Any push that advances the branch past this SHA invalidates this verification and requires re-review.

## 10. Deployment Status

**No deploy performed. No production write. No `PZService` restart. No production-copy or rollback executed. No `PZ_DEPLOY_OPERATOR_TOKEN` set or exposed. `C:\PZ` untouched; `C:\PZ-main` clean on `main`.** This entire reconciliation was git- and test-only, executed in worktree `C:\PZ-wt\deploy-authority`.

## Next Exact Step

**Request explicit operator merge approval for PR #958 at pinned head `c08fd418`.** Do not merge, deploy, or write to production without it.
