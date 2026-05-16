# B-MD1 — Admin · Users Deploy Smoke Report

**Date:** 2026-05-16  
**Merge SHA:** `2101e70daa0c2ea4a65479398ad582d5d11f0691` (PR #128)  
**Deployed file:** `service/app/static/dashboard.html` → `C:\PZ\app\static\dashboard.html` (1,466,409 bytes, +17,728 vs pre-deploy)  
**PZService status after deploy:** RUNNING

---

## 1. Pre-deploy gate

8-agent inline review verdict: **READY-TO-MERGE-AND-DEPLOY**.

| Agent | Verdict |
|---|---|
| Architecture | CLEAR — AdminUsersPage separate from MasterDataPage |
| Backend/API | CLEAR — Only existing /auth/users endpoints used |
| DB/schema | CLEAR — No schema change; zero `*_db.py` in diff |
| Frontend/UI | CLEAR — All 5 writes funnel through `_runAction` with mandatory `window.confirm` |
| Security/write-safety | CLEAR — Admin gate + Access-Denied banner + self-lockout + role allow-list |
| QA | CLEAR — 20 new tests (14 frontend + 6 backend); MasterDataPage isolation pinned |
| Release | CLEAR — dashboard.html only; standard restart |
| Browser/API smoke | CLEAR — checklist documented in implementation plan §7 |

Pre-deploy tests:
- `test_dashboard_admin_users_design.py` + `test_auth_admin_user_routes.py`: **20/20**
- `test_dashboard_master_design.py` + `test_master_data_hard_rules.py` + `test_runner_v2_hard_rules.py`: **129/129**
- **PZ regression: 160/160**
- `campaign_status doctor`: no issues

## 2. Deploy actions

| Step | Command | Result |
|---|---|---|
| Sync | `robocopy ...\static dashboard.html /XO` | Exit 1 (1 file copied, 0 failed) |
| Restart | `sc.exe stop/start PZService` | STATE: RUNNING |

## 3. Health checks

| Check | Expected | Actual |
|---|---|---|
| Local health | 200 | **200** ✅ |
| Public health | 200 | **200** ✅ |
| stderr tail | uvicorn startup clean | clean ✅ |

## 4. Source-grep + API-contract smoke (executed)

| # | Check | Expected | Actual | Pass |
|---|---|---|---|---|
| 1 | AdminUsersPage anchors in deployed dashboard.html | ≥ 10 | **15** | ✅ |
| 2 | `admin_users` nav child entry | ≥ 1 | 2 | ✅ |
| 3 | `page === 'admin_users'` route | 1 | 1 | ✅ |
| 4 | Frontend `ADMIN_USERS_ROLES` matches backend `ROLES` | exact match | both `('admin','accounts','logistics','auditor','viewer')` | ✅ |
| 5 | `GET /auth/users` requires auth | 401/403 unauth | HTTP 401 | ✅ |
| 6 | `POST /auth/users/<id>/approve` requires auth | 401/403 unauth | HTTP 401 | ✅ |
| 7 | MasterDataPage contains zero `/auth/users` writes | NONE | NONE | ✅ |

## 5. Write smoke (deferred to operator)

**No destructive admin action performed on real production accounts.**

Per the campaign brief, destructive real-user action is unsafe without a safe test user. None exists in the current users registry (no `*+test@*` or sandbox user account).

The mechanical safety envelope is fully verified by:
- 13 frontend source-grep contracts (component existence, route wiring, nav entry, admin gate, endpoint allow-list, POST-only writes, role allow-list, no create/delete user, self-lockout, confirm dialogs, refresh as safe GET, action testids, isolation from MasterDataPage)
- 7 backend route contracts (require_admin on all 5 routes, role validator, ROLES allow-list pinned, self-target guards on reject + deactivate, POST-only on the 5 paths)
- Live API: both GET and POST against `/auth/users` correctly require auth (HTTP 401 unauth)

Operator browser smoke checklist for completion when an admin operator session is available:

1. Log in as admin at `https://pz.estrellajewels.eu/login`.
2. Navigate Setup → Admin · Users. Page renders table with counters.
3. Search "test" or any partial email. Table filters client-side; no network call.
4. Click Refresh. Single GET to `/auth/users` fires.
5. On a pending row (if any), click Approve. Confirm dialog appears with the email + "approval email will be queued". Cancel — no network call fires.
6. On a pending row, click Reject. Confirm dialog mentions rejection email. Cancel — no network call.
7. On an approved active row (not self), Role selector renders the 5 values; selecting a different value opens a confirm dialog with "From … To …". Cancel — no network call.
8. On an approved active row (not self), click Deactivate. Confirm dialog appears. Cancel — no network call.
9. On the current admin's own row, the Actions column shows `—` (self-lockout guard).
10. The header has a disabled "Invite user · Backend pending / out of scope" chip.
11. Open MasterDataPage → click Users entity → confirm the table renders but **no** Approve / Reject / Deactivate / Role buttons exist on rows.
12. Browser console: no errors throughout.
13. `pz_stderr.log` since deploy: no new tracebacks; no mentions of `finance_dual_write` (6F.5 remains default-OFF).

When this checklist completes, append the verdicts to this report and mark the operator-smoke section closed.

## 6. Verdict

**B-MD1 deploy: PASS.** Activation status of `/auth/users` admin writes: **wired in UI, gated by admin role, awaiting first operator action.**

Hard-rule gates remained green throughout (no auth route change, no schema change, no MasterDataPage write surface added, no finance/wFirma/PZ/DHL/customs/FX coupling, no `.env` change, 6F.5 dual-write still default-OFF — `finance_postings.sqlite` size unchanged at 81,920 bytes).

## 7. Rollback (if needed)

```bash
git revert -m 1 2101e70daa0c2ea4a65479398ad582d5d11f0691 --no-edit
git push
# Then merge revert PR, robocopy dashboard.html, restart PZService.
```

Reverts to the state before PR #128 (no AdminUsersPage component, no nav child, no admin_users route; Users panel inside MasterDataPage stays as today's read-only table).
