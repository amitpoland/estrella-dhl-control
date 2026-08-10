# Plan — Accounting Ledger Cold Latency

**Worktree:** `C:\PZ-wt\ledger-cold`  
**Branch:** `feat/accounting-ledger-cold-latency`  
**Base:** `86729b09` (main; includes PR #1169 + #1170)  
**Scope:** instrument → measure → decide → implement cold-path reduction only  
**Out of scope:** reopen #1169 architecture, Sales Analysis, DHL, new accounting authority, timeout increases

---

## Phase A — Instrumentation (DONE)

Added to fact-universe / MA / payables / client-balance / supplier-statement `query_stats`:

| Field | Meaning |
|-------|---------|
| `wfirma_wait_ms` | Sum of upstream HTTP round-trips in `_paginate_find_collection` |
| `ej_normalize_ms` | Python date-filter + XML→fact parse |
| `ej_aggregate_ms` | Portfolio / statement-index aggregation |
| `ej_ms` | `ej_normalize_ms + ej_aggregate_ms` |
| `*_page_wait_ms` | Per-page upstream timings (capped ≤40) |
| `route_wall_ms` | Client-balances route wall (where applicable) |

On TTL cache hit: this-request `wfirma_wait_ms` / `duration_ms` = 0; originals under `cached_*`.

N+1 counters unchanged: `per_customer_wfirma_calls=0`, `per_supplier_wfirma_calls=0`.

---

## Phase B — Measure (DONE)

Instrumented uvicorn from worktree on `:47214` with prod `.env` / `C:\PZ\storage` (read-only GETs).  
Evidence: `.claude/memory/waterfall-ledger-cold-before.md` + `measure-ledger-cold-instrumented-v2.json`.

### Cold YTD (2026-01-01 → 2026-08-10)

| Probe | http_ms | wfirma_wait_ms | ej_ms | share wFirma |
|-------|--------:|---------------:|------:|-------------:|
| AR clients limit=15 | 17843 | 16098 | 33 | **~90%** |
| AR MA | 19632 | 18675 | 18 | **~95%** |
| AP payables | 7897 | 7405 | 20 | **~94%** |

Warm YTD (TTL): AR clients **39 ms** (`wfirma=0`), AP **21 ms** (`wfirma=0`).

### Cold narrower windows (same code, force refresh)

| Window | AR clients | AP payables |
|--------|----------:|------------:|
| Quarter (2026-07-01→08-10) | **4102 ms** | **1049 ms** |
| This month (2026-08-01→08-10) | **1657 ms** | **438 ms** |

EJ processing is tens of ms — **not** the bottleneck. Remaining cold time is upstream wFirma page RTT (often 0.4–10 s per page).

---

## Phase C — Decision (LOCKED)

**Chosen: narrower default period = current calendar quarter** for Balance / Client Ledger / Supplier Ledger / AccClientBalance cold entry (and Overview receivable KPI window for hub cold-path parity).

### Why not the others

| Option | Verdict |
|--------|---------|
| **Narrower default (quarter)** | **YES** — AR cold ~4.1 s (≤5 s target), AP ~1.0 s; formulas unchanged; YTD one click away |
| This-month default | Faster (~1.7 s) but too short for operational “open balances” view; quarter is better UX |
| Staged loading (fast first page then fill) | Deferred — would need UI progressive semantics; wFirma still dominates full-universe fill; not required once default ≤5 s |
| Better upstream date/type filters | Date filters already sent; pages still slow per-RTT; type filters already `normal/correction/proforma`. No safe filter proven to cut pages without semantic risk in this slice |
| Timeout increase | **Forbidden** by brief |

### Semantic guarantee

- AR/AP remaining / aging / matching formulas **unchanged**.
- Default window change is **operator period selection only**, not fiscal redefinition.
- **YTD full portfolio** remains available via explicit **YTD** period preset (Client/Supplier Ledger period bar) and Custom range. Register “All Years” on document lists is unrelated and unchanged.
- Refresh still force-bypasses TTL; warm cache + coalesce preserved.

---

## Phase D — Implement (DONE)

1. FE: default preset `ytd` → `quarter` on Client Ledger + Supplier Ledger tabs.
2. FE: `LDG_WINDOW()` / AccClientBalance / Overview MA KPI → quarter start (label discloses period).
3. BE: empty `from` on `/ledgers/clients` → quarter start (aligned with FE).
4. Tests: timing fields; N+1=0; cache/Refresh; no write verbs; default-window; FE preset — **23 passed**.
5. After measure: cold default AR **3877 ms** / AP **986 ms**; warm **31 / 4 ms**; explicit YTD still ~16.6 s.

See `.claude/memory/waterfall-ledger-cold-after.md`.

---

## Targets vs evidence

| Target | Status |
|--------|--------|
| Cold Balance/roster ≤5 s useful | **Met by quarter default** (~4.1 s AR / ~1.0 s AP) |
| Warm ≤3 s | **Already** ~20–40 ms |
| Ordinary action not routinely >10 s | Met for default path; YTD explicit remains slow (~18–20 s) — operator-chosen |
| Instrument proves remaining time | **Proven:** wfirma_wait ≫ ej |
