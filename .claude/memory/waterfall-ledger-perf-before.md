# Waterfall — Accounting Ledger Performance (BEFORE)

**Measured:** 2026-08-10T07:46:48Z  
**Target:** production NSSM `http://127.0.0.1:47213`  
**Git tree:** `C:\PZ-wt\ledger-perf` @ `7bdd689cea1f274681a5f5d175cee498f7dc3330` (`feat/accounting-ledger-performance`, clean)  
**Window:** `2026-01-01` → `2026-08-10` (YTD)  
**Method:** read-only `X-API-Key` GETs via `.claude/memory/measure_ledger_perf_before.py`  
**Raw JSON:** `.claude/memory/measure-ledger-perf-before.json`  
**Browser duration:** API-equivalent cold timings below (browser shell not required to prove server N+1; UI adds same EJ routes).

---

## Verdict (one line)

**PROVEN N+1 on Client Balance / Client Ledger roster** (`list_client_balances` → per-client `_build_statement_dict` → contractor + invoices/find + payments/find). Overview `limit=100` **times out at 180s**. Supplier roster already bulk (`per_supplier_wfirma_calls=0`) but cold ~15s; supplier **drill re-fetches the entire AP universe**. MA already bulk (`per_customer_wfirma_calls=0`) but cold ~23s.

---

## 1. Client Balance (`AccClientBalance` → `GET /api/v1/ledgers/clients?limit=15`)

```
Client Balance (limit=15, YTD)
total:                19.219 s
EJ requests:          1
EJ route:             GET /api/v1/ledgers/clients
EJ server time:       ≈19.2 s (client RTT to local NSSM)
wFirma requests:      ≈45+ sequential (PROVEN N+1)
  per row on page:    contractors/get (via lookup_wfirma_contractor)
                      + invoices/find (paginated, contractor filter)
                      + payments/find (paginated, contractor filter)
  × 15 customers on page
docs returned:        15 roster rows (all balance_available=true)
normalized rows:      N/A (statement reduced per client; no shared fact table)
aggregation:          aggregate_statement × 15 (serial)
response size:        6 411 bytes
duplicate requests:   none for this single call; hub Overview separately fires limit=100
React:                AccClientBalance useEffect once; PzApi 8s TTL coalesce (helps hub re-entry only)
root cause:           statement-per-client loop in routes_ledgers.list_client_balances
```

**Scaling evidence (same endpoint, same window):**

| limit | elapsed | result |
|------:|--------:|--------|
| 3 | 10.228 s | 200, 3 rows |
| 15 | 19.219 s | 200, 15 rows |
| 100 | **180.006 s** | **TIMEOUT** (client 180s ceiling) |

Approx ~1.3 s/client at limit=15. Code citation: `list_client_balances` loops `page` and calls `_build_statement_dict(cid, …)` for every customer with a contractor id.

---

## 2. Client Ledger landing (`ClientLedgerView` → same roster endpoint, limit=15)

```
Client Ledger landing
total:                19.219 s (same authority as Client Balance limit=15)
EJ requests:          1 (+ auto-select triggers drill — see §3)
EJ route:             GET /api/v1/ledgers/clients?limit=15&start=0&from&to
wFirma:               same N+1 as §1
response:             6 411 bytes / 15 rows
FE paging:            limit=15, start=(page-1)*15 (server page of Customer Master, not #1168 register paging)
root cause:           identical N+1 roster builder
```

Note: FE `listClientBalancesShared` uses `force` when custom period set; Refresh sets `refreshKey` → cache bypass. TTL=8s in-flight coalesce already present in `pz-api.js` — **does not fix cold N+1**.

---

## 3. Client Ledger drill (`statement.json` for first roster contractor)

```
Client Ledger drill (contractor 201184867)
total:                2.771 s
EJ requests:          1
EJ route:             GET /api/v1/ledgers/clients/{id}/statement.json
wFirma requests:      ~3+ (1 contractor preflight + invoices/find pages + payments/find pages)
docs / entries:       0 entries in this sample (empty currencies) — still paid full round-trips
response size:        368 bytes
root cause:           acceptable on-demand single-contractor statement; NOT the roster bottleneck
```

Landing+first drill wall ≈ **19.2 + 2.8 ≈ 22 s** useful UI (list then statement).

---

## 4. Supplier Ledger landing (`SupplierLedgerView` → payables-analysis)

```
Supplier Ledger landing
total:                15.086 s
EJ requests:          1
EJ route:             GET /api/v1/ledgers/payables-analysis.json?status=outstanding
wFirma requests:      7 (bulk; per_supplier_wfirma_calls=0)
  expenses/find × 3 pages → 438 expenses normalized
  payments/find × 4 pages → 669 payments normalized
aggregation:          build_payables_analysis / match_payments_to_expenses (server duration_ms=15058)
suppliers returned:   13 (FE then slices 15-row client page)
response size:        18 297 bytes
N+1?:                 DISPROVED for supplier roster (already bulk)
root cause (latency): cold full-period bulk expenses+payments (~15s), not per-supplier loop
```

---

## 5. Supplier Ledger drill (`suppliers/{id}/statement.json`)

```
Supplier Ledger drill (contractor 38142296)
total:                14.477 s
EJ requests:          1
EJ route:             GET /api/v1/ledgers/suppliers/{id}/statement.json
wFirma requests:      ~7 again (FULL bulk expenses+payments, then Python filter to one contractor)
response size:        51 451 bytes
root cause:           drill reloads entire AP fact universe instead of reusing landing bulk / short-TTL fact cache
```

Landing+drill wall ≈ **15.1 + 14.5 ≈ 29.6 s** if both cold (duplicate bulk).

---

## 6. Customer / Master list

```
Customer Master list
total:                0.039 s
EJ route:             GET /api/v1/customer-master?limit=50
wFirma requests:      0 (local SQLite Customer Master)
rows / bytes:         50 / 110 796
root cause:           none — already fast; out of campaign critical path
```

---

## 7. Supplier / Master list

```
Supplier Master list
total:                0.007 s
EJ route:             GET /api/v1/suppliers?limit=50
wFirma requests:      0 (local)
rows / bytes:         5 / 3 171
root cause:           none — already fast
```

---

## 8. Management Analysis load (comparison — bulk AR)

```
Management Analysis (AR)
total:                23.334 s
EJ route:             GET /api/v1/ledgers/management-analysis.json
wFirma requests:      6 (bulk; per_customer_wfirma_calls=0)
  invoices/find × 2 pages → 365 invoices
  payments/find × 4 pages → 669 payments
aggregation:          build_management_analysis duration_ms=23285
response size:        32 648 bytes
root cause (latency): bulk YTD pull + match/age (~23s cold) — architecture already correct (zero per-customer calls)
```

**Comparison:** MA loads **all** AR facts in ~23s with **6** wFirma calls. Client Balance limit=15 takes ~19s with **~45+** calls and still only covers 15 customers. Overview limit=100 **cannot complete** under 180s.

---

## N+1 proof summary

| Surface | N+1? | Evidence |
|---------|------|----------|
| Client Balance / Client Ledger roster | **YES — PROVEN** | Code loop + limit 3/15/100 timing (100 timeout) |
| Client statement drill | No (1 contractor) | 2.8s single statement |
| Supplier Ledger landing | **No** | `per_supplier_wfirma_calls=0`, 7 bulk calls |
| Supplier statement drill | No N+1, but **duplicate full bulk** | ~14.5s ≈ landing cost |
| Management Analysis | **No** | `per_customer_wfirma_calls=0`, 6 bulk calls |
| Customer/Supplier Master | No | local SQLite |

Estimated Client Balance wFirma calls:

- **limit=15:** ≥ 15 × (1 contractors/get + ≥1 invoices/find + ≥1 payments/find) ≈ **≥45**
- **limit=100 (Overview KPI):** ≥300 → **timeout**

---

## Existing helpers (inspect inventory)

| Asset | Role today |
|-------|------------|
| `wfirma_client.fetch_invoices_for_period` / `fetch_payments_for_period` / `fetch_expenses_for_period` | MA + AP bulk fact load |
| `accounting_analytics.build_management_analysis` / `build_payables_analysis` | Shared AR/AP remaining + aging from bulk facts |
| `ledger_aggregator.aggregate_statement` / `remaining_after_payments` / match helpers | Statement authority (formulas must stay Δ=0) |
| `routes_ledgers.list_client_balances` | **N+1 roster** — join Customer Master page × statement |
| `pz-api.js` `_fetchClientBalancesShared` | 8s TTL + in-flight coalesce (FE only; wrong limits don't share) |
| `accounting_register_paging.py` (#1168) | year/page/limit=15/sort for **document registers** — not yet used by ledger rosters |

---

## Duplicate / wasteful request patterns

1. **Accounting Overview KPI** calls `listClientBalances({ limit: 100 })` — guaranteed multi-minute / timeout path.
2. **Client Balance** and **Client Ledger** both use limit=15 but different cache keys vs Overview limit=100 → no shared FE cache hit across hub sections.
3. **Supplier drill** repeats full expenses+payments bulk already paid by landing.
4. Client Ledger auto-selects first client → always pays roster N+1 **plus** one statement.

---

## Hard targets vs before

| Target | Before |
|--------|--------|
| cold ≤5s useful | Client Balance 19s; Supplier land 15s; MA 23s — **FAIL** |
| warm page/year ≤3s | not measured (no server fact cache yet; FE 8s only for identical QS) |
| hard ceiling 10s | Overview limit=100 **TIMEOUT 180s** — **FAIL** |
| no routine timeout | Overview KPI path times out — **FAIL** |
| per_customer_wfirma_calls=0 on balance | **FAIL** (N+1) |
| per_supplier_wfirma_calls=0 on roster | **PASS** (already) |

---

## What NOT to do (confirmed by measure)

- Do not parallelize hundreds of per-client statement calls (Overview already proves sequential N+1 is fatal; concurrency would hammer wFirma).
- Do not raise timeouts as the primary fix (limit=100 needs architecture change).
- Do not change AR/AP formulas — reuse `build_portfolio_from_facts` / `remaining_after_payments` / existing matchers.
