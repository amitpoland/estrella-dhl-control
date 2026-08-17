# EJ Accounting + CFO MIS — implementation checkpoint (NOT production-complete)

**Tree:** `C:\PZ-wt\accounting-cfo-mis` · **Branch:** `feat/accounting-cfo-mis`  
**Base / prod SHA:** `2f04ae1c` (aligned across C:\PZ, C:\PZ-main, origin/main)

## DONE

### Prior slices (unchanged authority)
- Slice 0 WZ DIRECT JOIN, AR baseline lock, financial_reporting_db, as-of payments,
  Client Balance all_outstanding + 20/page, canonical 7-bucket aging, Carrier Master
  FEDEX/UPS/OTHER, AWB projection helper, Treasury DB + import + daily close routes.

### P1 — Kill CFO cold waterfall (this session)
- `local_fact_universe.py` — AR/AP facts from reporting + payment_state
- `build_management_analysis` / `build_payables_analysis` default **`source=local`**
- Live waterfall only via `source=live` or `refresh=1`
- Response exposes `as_of`, `source`, `freshness`, `reconciliation_status`, `projection`
- Fail-honest `503 LOCAL_PROJECTION_UNAVAILABLE` when projection empty
- Stale never labeled fresh
- Tests: `test_local_fact_universe.py` green

### P2 — CFO MIS UI hierarchy
- `ManagementAnalysisView` in `ledgers-page.jsx`: Liquidity → Receivables → Overdue →
  Payables → Aging → Treasury trend → Working Capital → Exceptions
- Source/freshness/reconciliation badges; Refresh = live (`refresh:1`)

### P3 — Accounting document UI
- Shared `accounting-register-filter.jsx`; AccDocGrid for Invoice/CN/WZ/PZ/PW/RW;
  MM unsupported honest; WZ/PZ AWB via Logistics projection

### P4 — Client / Supplier workspace
- Full-width Client Ledger tabs; lazy statement; overdue-first sort including
  oldest_overdue_date; Supplier AP parity improvements

### P5 — Webhooks (partial)
- WH-001 domain router + WH-005 quarantine (`wfirma_webhook_event_router.py`)
- Scheduler SELECT includes `event_type`; non-invoice → no InvoiceSnapshotProcessor
- `Produkty.*` / `Towary.*` → STOCK (no inventory mutate until OI-10 payload proof)
- WH-008: multi-key already present; rotation UI not built

### Treasury security
- Review: `.claude/memory/TREASURY-WRITE-SECURITY-REVIEW-2026-08-17.md`
- Verdict PASS_WITH_FIXES → TRE-001 atomic confirm + TRE-002 session operator **REMEDIATED**

## NOT DONE (blocking full closure / deploy)
- Production backfill of `financial_reporting.sqlite` (local CFO path needs rows)
- AR/AP reconciliation report vs Stage A baseline after backfill
- Perf before/after measurement on live host
- Inventory qty webhook: capture one real payload before consume
- WH-002..WH-009 remaining consumers
- Browser smoke (GATE 6)
- 7-agent gate + Deploy-PZ.ps1
- Campaign commits / PR (hold until backfill + recon coherent, unless escalation)

## Test evidence (this session, focused)
- local fact universe + analytics phase1 + ledger scope + MA UI + webhook routing: green
- treasury db + bank import (incl. double-confirm refuse): green
- P3/P4 wiring suites: 81 passed (subagent)

## Deploy status
**NOT DEPLOYED.** Local CFO path is code-complete but requires reporting DB backfill before production can leave the live waterfall.
