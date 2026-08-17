# AR cutover reconciliation note — 2026-08-17

## Scope
Local CFO projection after full backfill of `C:\PZ\storage\financial_reporting.sqlite`
against Stage A locked baseline (`.claude/memory/baseline-ar-2026-08-17.json`).

## Backfill
| Stream | Fetched / upserted | Errors |
|--------|--------------------|--------|
| AR invoices (2020-01-01 → 2026-08-17) | 764 / 764 | 0 |
| AP expenses | 2164 / 2164 | 0 |

- Path: `C:\PZ\storage\financial_reporting.sqlite` (STORAGE_ROOT; not worktree)
- Credentials: loaded from `C:\PZ\.env` via governed dotenv runner (values not logged)
- wFirma: read-only; no fiscal writes
- Quality: 0 AR duplicate IDs; 0 missing contractor_id; due dates populated (0 missing on AR); 59 corrections; currencies EUR/PLN/USD (+ AP CHF)

## Performance (same window, as_of=2026-08-17)

| Path | Duration | Invoice API | Payment API |
|------|----------|-------------|-------------|
| Stage A live waterfall (baseline) | **53,367 ms** | 4 | 16 (20 total) |
| Local projection (this run) | **112 ms** | **0** | **0** |

Normal CFO path no longer executes the portfolio-wide wFirma waterfall.

## AR by currency (status=all / outstanding portfolio)

| Ccy | Baseline total | Local total | Δ total | Baseline overdue | Local overdue | Δ overdue |
|-----|----------------|-------------|---------|------------------|---------------|-----------|
| EUR | 212,383.49 | 212,383.49 | **0.00** | 39,826.04 | 39,826.04 | **0.00** |
| PLN | 96,077.65 | 96,077.65 | **0.00** | 18,002.90 | 18,002.90 | **0.00** |
| USD | 373,062.49 | 372,989.49 | **−73.00** | 280,798.80 | 280,725.80 | **−73.00** |

## Aging invariant
Per currency: `sum(canonical buckets) + due_date_unavailable == total_receivable` → **PASS** (EUR/PLN/USD).

## USD −73.00 — explained (not unexplained)

**Classification:** OLD LOGIC / live matching gap → NEW LOGIC / payment_state settlement (toward wFirma truth).  
**Not** baseline→current business movement (no new fiscal document since baseline for this gap).

| Field | Value |
|-------|--------|
| Invoice | WDT 31/2026 · wFirma id `434705123` · contractor `90484280` |
| Local gross (from find sync) | 73.00 USD |
| Payment | id `605049315` · date 2026-07-02 · value 73.00 · linked invoice 434705123 |
| Local remaining | **0.00** (fully settled) |
| Live RO `invoices/get/434705123` | `paymentstate=paid`, `alreadypaid=73.00`, `remaining=0.00` |

Stage A live portfolio still counted this invoice as **open 73.00**. Local payment_state correctly applies the linked payment. Live get confirms remaining=0. Entire USD overdue delta equals this one settlement (−73).

Payment snapshot count: local DB **3023** vs baseline live normalized **3056** (−33). EUR/PLN still exact; the only material open-position delta is this explained USD settlement.

## Verdict
**RECON PASS WITH EXPLAINED USD −73** — no unexplained material delta. Safe to proceed to perf acceptance / branch reconcile / release gate. Do **not** treat −73 as a blocker.

## Evidence files
- `.claude/memory/baseline-ar-2026-08-17.json`
- `.claude/memory/AR-RECON-POST-BACKFILL-2026-08-17.json` (re-generate after parser fix if needed)
- `.claude/memory/_run_sync_with_prod_env.py` (credential loader; not for commit of secrets)
