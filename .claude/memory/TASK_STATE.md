# TASK_STATE.md

## Current task

- **Task:** EJ Accounting + CFO MIS campaign
- **Worktree:** `C:\PZ-wt\accounting-cfo-mis`
- **Branch:** `feat/accounting-cfo-mis` (ahead of origin/main after merge)
- **Status:** Backfill + AR recon + local perf DONE; Treasury UI added; deploy NOT done

### Completed this resume

1. Preflight: `C:\PZ\.env` credentials present; `STORAGE_ROOT=C:\PZ\storage`; FR DB was missing; 74 GB free
2. Validation window sync OK → full backfill **764 AR / 2164 AP / 0 errors** → `C:\PZ\storage\financial_reporting.sqlite`
3. AR recon vs Stage A: EUR/PLN exact; USD **−73 explained** (WDT 31/2026 paid) — see `AR-CUTOVER-RECONCILIATION-2026-08-17.md`
4. Local MA **~94–112 ms**, **0** portfolio wFirma calls (was ~53 s / 20 calls)
5. Merged unrelated `origin/main` insurance-export tests (`c8e60aa7`)
6. Treasury Hub UI panel + PzApi wrappers (pending commit)

### WH-008 note

`WFIRMA_WEBHOOK_KEY` has **1** slot (len 32). Three wFirma registrations exist — operator must supply comma-separated keys for all three before operational multi-webhook reliance. Do not print keys.

### Inventory webhook

Still blocked on genuine Produkty qty payload (OI-10).

### Next for release

1. Commit Treasury UI + recon note
2. Push + PR
3. Seven-agent gate
4. Deploy-PZ.ps1
5. Prod smoke (SHA, local CFO, freshness badges)
