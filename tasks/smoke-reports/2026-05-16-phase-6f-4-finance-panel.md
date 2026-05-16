# 6F.4 — Read-only Finance Posting Breakdown Panel — Deploy Smoke Report

**Date:** 2026-05-16  
**Merge SHA:** `acc92dc037416ec397e75cc436f957e4aa63e6a2` (PR #118)  
**Deployed file:** `service/app/static/dashboard.html` → `C:\PZ\app\static\dashboard.html` (1,448,681 bytes)  
**PZService status after deploy:** RUNNING

---

## 1. Pre-deploy gate

- 7-agent inline gate verdict: **READY-TO-DEPLOY**
  - LEAD_COORDINATOR / GIT_DIFF / BACKEND_IMPACT / PERSISTENCE / SECURITY / QA / RELEASE: all CLEAR.
- Pre-deploy tests:
  - finance_panel_contracts: 12/12
  - finance_postings_contracts: 37/37
  - finance_postings_db: 38/38
  - master_data_hard_rules: 27/27
  - runner_v2_hard_rules: 12/12
  - **PZ regression: 160/160**

## 2. Deploy actions

| Step | Command | Result |
|---|---|---|
| Sync runtime | `robocopy "...\service\app" "C:\PZ\app" /E /XO ...` | Exit 3 (1 copied, 324 skipped, 0 failed). dashboard.html updated. |
| Restart | `sc.exe stop PZService; sc.exe start PZService` | STATE: RUNNING |

## 3. API smoke

| Check | Expected | Actual | Pass |
|---|---|---|---|
| Local health | HTTP 200 | HTTP 200 | ✅ |
| Public health | HTTP 200 | HTTP 200 | ✅ |
| `GET /api/v1/finance/postings/999999/breakdown` | HTTP 404 with detail | HTTP 404 `{"detail":"Posting not found: id=999999"}` | ✅ |
| stderr tail (last 15 lines) | Clean uvicorn startup | `INFO: Application startup complete.` / `INFO: Uvicorn running on http://127.0.0.1:47213` | ✅ |

## 4. Static asset verification

The dashboard route (`GET /dashboard/{path}`) requires a valid session cookie, so API-level fetch returns a redirect to `/login`. Verification was performed by inspecting the deployed file on disk.

| Anchor | Found in `C:\PZ\app\static\dashboard.html` |
|---|---|
| `FinancePostingBreakdownPanel` function declaration | yes |
| `<FinancePostingBreakdownPanel />` render in `DiagnosticsPage` | yes |
| `data-testid="diagnostics-finance-posting-panel"` | yes |
| `data-testid="diagnostics-finance-readonly-badge"` | yes |
| `data-testid="diagnostics-finance-posting-empty"` | yes |
| Total panel anchors counted (`grep -c`) | **5** |

## 5. Browser smoke (operator-driven, deferred)

The following browser smoke steps must be performed by the operator with a valid session. They are non-blocking for this deploy because the contract tests + API smoke already cover the read-only-ness and 404 path:

1. Log in at `https://pz.estrellajewels.eu/login`.
2. Open Diagnostics page.
3. Confirm "Finance posting breakdown" card visible between version panel and the design-preview footer.
4. Confirm the "Read-only" badge appears (testid `diagnostics-finance-readonly-badge`).
5. Type `999999` in the posting id input.
6. Click **Fetch**.
7. Confirm the empty-state copy appears (testid `diagnostics-finance-posting-empty`) explaining the store is dormant by design.
8. Confirm no console errors.
9. Confirm the page contains no "Create posting", "Run backfill", "Close settlement", "Allocate payment", or "Create charge" buttons.
10. Confirm no auto-fetch triggered network calls before the operator clicked Fetch.

## 6. Verdict

**6F.4 deploy: PASS.**

Hard-rule gates remained green throughout (no engine writes, no schema change, no FX, no posting/settlement/charge create surface, no wFirma/PZ/DHL coupling, no backfill execution surface).

## 7. Rollback (only if needed)

```bash
git revert -m 1 acc92dc --no-edit
# then re-run Steps 5 (robocopy) + 6 (PZService restart) from the deploy rule
```

This reverts to the state before PR #118 (no Diagnostics finance panel; the GET breakdown endpoint remains live since it shipped in 6F.3 / PR #115).
