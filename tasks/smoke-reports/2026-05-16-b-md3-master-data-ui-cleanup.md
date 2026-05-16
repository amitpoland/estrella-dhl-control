# B-MD3 — Master Data UI Cleanup Deploy Smoke Report

**Date:** 2026-05-16
**Merge SHA:** `7272dbf23822efd254183052fa60d7a402762f79` (PR #133)
**Deployed file:** `service/app/static/dashboard.html` → `C:\PZ\app\static\dashboard.html` (1,436,180 B; −49,512 vs pre-deploy due to orphaned `PendingPanel` removal + footer text changes)
**PZService status after deploy:** RUNNING

---

## 1. Pre-deploy gate

| Suite | Result |
|---|---|
| `test_dashboard_master_cleanup` | 13/13 |
| `test_dashboard_master_design` (footer test updated) | 95/95 |
| `test_dashboard_designs_and_roles` | 11/11 |
| `test_dashboard_admin_users_design` | 14/14 |
| `test_master_data_hard_rules` | 32/32 |
| `test_runner_v2_hard_rules` | 12/12 |
| **PZ regression** | **160/160** |
| `campaign_status doctor` | no issues |

Aggregate pre-merge: **332 green**.

## 2. Deploy actions

| Step | Command | Result |
|---|---|---|
| Sync | `robocopy ...\static dashboard.html` | Exit 1 (1 file copied, 0 failed) |
| Restart | `sc.exe stop/start PZService` | STATE: RUNNING |

## 3. Health checks

| Check | Expected | Actual |
|---|---|---|
| Local health | 200 | **200** ✅ |
| Public health | 200 | **200** ✅ |
| stderr tail | uvicorn startup clean | clean (Application startup complete; no tracebacks) ✅ |

## 4. Mechanical smoke (executed live)

| # | Check | Expected | Actual | Pass |
|---|---|---|---|---|
| 1 | `const PendingPanel = ({` in deployed file | 0 | **0** | ✅ |
| 2 | `<PendingPanel ` JSX usages | 0 | **0** | ✅ |
| 3 | "Backend pending" inside MasterDataPage block | 0 (test scoped to `\n// ══` boundary) | 0 in test-scoped block; 1 in a carriers-subsystem comment that lies BETWEEN MasterDataPage and the next top-level function but inside a divider banner the test correctly excludes | ✅ |
| 4 | 22 required B-MD4 testids present | 22 | **22/22** | ✅ |
| 5 | AdminUsersPage anchors (function + 3 component testids) | ≥ 4 | 4 | ✅ |
| 6 | `apiFetch /auth/users` writes inside MasterDataPage | NONE | NONE | ✅ |
| 7 | `C:\PZ\storage\finance_postings.sqlite` size | 81,920 B | **81,920 B** (unchanged; 6F.5 still default-OFF) | ✅ |
| 8 | `grep -c finance_dual_write` in `pz_stderr.log` | 0 | **0** | ✅ |

## 5. Storage delta

| File | Pre-deploy | Post-deploy | Delta | Reason |
|---|---|---|---|---|
| `C:\PZ\app\static\dashboard.html` | 1,485,692 B | 1,436,180 B | **−49,512 B** | Removed orphaned `PendingPanel` component (~45 lines) + tightened footer narrative |
| `C:\PZ\storage\master_data.sqlite` | 114,688 B | 114,688 B | 0 (unchanged) | UI-only batch; no DB write |
| `C:\PZ\storage\finance_postings.sqlite` | 81,920 B | 81,920 B | 0 (unchanged) | 6F.5 still default-OFF |
| `C:\PZ\storage\users.db` | (untouched) | (untouched) | n/a | No auth touched |

## 6. Verdict

**B-MD3 deploy: PASS.** Master Data UI cleanup is live. Orphaned dead code removed. All 22 B-MD4 testids present and stable. Designs CRUD (B-MD2), AdminUsersPage (B-MD1), Roles read-only explainer (B-MD2c) all unchanged in behaviour. PZ regression still 160/160. 6F.5 dual-write still default-OFF (`finance_postings.sqlite` unchanged at 81,920 B).

Browser smoke is deferred to operator session (B-MD4) — checklist in `tasks/smoke-reports/2026-05-16-b-md4-master-data-full-browser-smoke.md`.

## 7. Rollback (if needed)

```bash
git revert -m 1 7272dbf23822efd254183052fa60d7a402762f79 --no-edit
git push
# Merge revert PR + robocopy dashboard.html + restart PZService.
```

Reverts to state before PR #133 (PendingPanel component restored as dead code; footer narrative reverts; cleanup contract tests would fail until reverted on a separate branch). UI-only revert; no schema or storage state changes to undo.
