# Plan — Accounting Ledger Performance

**Phase:** 0 context + 1 waterfall complete · **Phase 2 not started**  
**Worktree:** `C:\PZ-wt\ledger-perf`  
**Branch:** `feat/accounting-ledger-performance`  
**HEAD:** `7bdd689cea1f274681a5f5d175cee498f7dc3330` (clean; == baseline after PR #1168)  
**Waterfall:** `.claude/memory/waterfall-ledger-perf-before.md`

---

## Phase 0 confirmation

| Check | Result |
|-------|--------|
| HEAD == `7bdd689c…` | YES |
| Branch name | `feat/accounting-ledger-performance` |
| Tree clean | YES (no porcelain at measure start) |
| Skills | `ej-dashboard-fullstack-governance`, `ej-dashboard-webapp-testing` read |
| Out of scope | Sales Analysis / Bank Rec / Consignment — not started |

### Inspect targets (mapped)

| UI | Transport | Route | Service | Facts |
|----|-----------|-------|---------|-------|
| AccClientBalance / ClientLedger list | `PzApi.listClientBalances*` | `GET /ledgers/clients` | `list_client_balances` → `_build_statement_dict` | **per-client** invoices+payments (**N+1**) |
| Client drill | `apiFetch` statement.json | `GET /ledgers/clients/{id}/statement.json` | `_build_statement_dict` → `aggregate_statement` | per contractor (OK) |
| SupplierLedger list | `PzApi.getPayablesAnalysis` | `GET /ledgers/payables-analysis.json` | `build_payables_analysis` | **bulk** expenses+payments |
| Supplier drill | `PzApi.getSupplierStatement` | `GET /ledgers/suppliers/{id}/statement.json` | bulk fetch + filter + `aggregate_supplier_statement` | **re-bulk** (waste) |
| MA | `PzApi.getManagementAnalysis` | `GET /ledgers/management-analysis.json` | `build_management_analysis` | **bulk** invoices+payments |
| Customer Master | `PzApi.listCustomerMaster` | `GET /customer-master` | customer_master_db | local |
| Supplier Master | `PzApi.listSuppliers` | `GET /suppliers` | local | local |
| #1168 paging | `listAccountingDocs` | accounting documents | `accounting_register_paging.py` | year/page/limit=15 |

### Existing MA / coalescing helpers to reuse

- `fetch_invoices_for_period` / `fetch_payments_for_period` / `fetch_expenses_for_period`
- `build_management_analysis` / `build_payables_analysis` / `build_portfolio_from_facts`
- `remaining_after_payments`, match_payments_to_* in `ledger_aggregator`
- FE `_fetchClientBalancesShared` (8s TTL + in-flight) — extend pattern; fix Overview limit=100

---

## Root cause (exact)

1. **Primary:** `list_client_balances` computes each of ≤N Customer Master rows via full `_build_statement_dict` (live contractor + invoices/find + payments/find). Measured: limit=15 → **19.2s**; limit=100 Overview → **180s timeout**.
2. **Secondary:** Supplier drill reloads full AP bulk universe (~14.5s) instead of sharing landing/MA-window facts.
3. **Tertiary:** Cold bulk MA/AP YTD still ~15–23s (correct architecture, needs coalesce/TTL + optional warm reuse when windows match).
4. **FE:** Overview KPI requests `limit:100` of the N+1 endpoint — guaranteed timeout path.

---

## Phase 2 fix sketch (DO NOT implement until operator continues)

### A. Client Balance / Client Ledger roster → bulk AR projection

1. One bulk `fetch_invoices_for_period` + `fetch_payments_for_period` for the roster window (reuse MA loaders).
2. Project balances with **same** remaining equation as MA / statement (`remaining_after_payments` / portfolio helpers) — **Δ must stay 0.00**.
3. Join to Customer Master page of **15** rows (`start`/`limit`); **`per_customer_wfirma_calls=0`**.
4. Optional: skip live `lookup_wfirma_contractor` per row on roster (meta already on Master); keep preflight only on drill.
5. Change Overview KPI off `limit:100` N+1 — derive receivable from bulk portfolio or shared cached roster summary.

### B. Supplier roster

- Already bulk. Keep `per_supplier_wfirma_calls=0`.
- Ensure FE shows **15-row page** of outstanding suppliers without refetch; align year filter with #1168 defaults where applicable.

### C. Drill-down

- Client: keep on-demand `statement.json` (already ~2.8s).
- Supplier: **do not** re-bulk full history; filter from in-flight/short-TTL shared AP fact universe for the same `(from,to)` (or pass contractor filter after one shared load).

### D. Coalescing / short-TTL (only if measured useful)

- Server in-flight coalesce for identical fact universe key `(kind, from, to, types…)`.
- Short TTL (tens of seconds); **Refresh force-bypass**; auth-safe; never second accounting authority.
- Reuse MA bulk when windows match Client Balance / MA.

### E. FE cleanup

- Fix Overview `limit:100`.
- Ensure Balance vs Ledger share params so FE coalesce hits.
- Stale-response guards on period/page changes (ignore out-of-order).
- Preserve explicit Refresh = fresh facts.

### F. Must not change

AR/AP formulas, currencies, credits-outside-aging, due-date semantics, #1168 register paging behavior, wFirma writes, Sales Analysis.

---

## Phase 3–5 (queued)

- Tests: zero roster N+1; one bulk AR / one bulk AP; coalesce; cache key+Refresh bypass; 15-row+year; AR/AP Δ=0; no write verbs.
- Browser desktop+390 timings; `security-review` on cache isolation.
- Commit → one PR → floors → seven-agent gate → App-only deploy → production before/after.

---

## HOLD conditions (campaign)

accounting totals change · AR/AP drift · cache leak across users · stale period after filter · N+1 hidden by concurrency · full history for 15-row lists · timeout-only "fix" · security HIGH/CRITICAL
