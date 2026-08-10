# Waterfall — Ledger Cold Latency (BEFORE default-window change)

**Measured:** 2026-08-10T10:48:52Z (instrumented-v2)  
**Server:** worktree uvicorn `http://127.0.0.1:47214`  
**Code:** `C:\PZ-wt\ledger-cold` @ branch `feat/accounting-ledger-cold-latency` (instrumentation landed; default still YTD)  
**Creds / storage:** prod `C:\PZ\.env` + `C:\PZ\storage` (read-only GETs only)  
**Raw JSON:** `.claude/memory/measure-ledger-cold-instrumented-v2.json`

---

## Verdict

Cold AR/AP latency after PR #1169 is **dominated by upstream wFirma HTTP wait** (`wfirma_wait_ms` ≈ 90–95% of wall). EJ normalize+aggregate is **≤40 ms**. Warm TTL is already excellent (≤40 ms, `wfirma_wait_ms=0`). Narrowing the **default operator window to current quarter** is the evidence-backed cold-path reduction that hits ≤5 s without changing AR/AP formulas.

---

## Cold YTD

| Probe | http_ms | wfirma_wait_ms | ej_normalize_ms | ej_aggregate_ms | ej_ms | cache | per_*_calls | pages (inv/exp + pay) |
|-------|--------:|---------------:|----------------:|----------------:|------:|:-----:|------------:|----------------------:|
| `/ledgers/clients?limit=15` | 17843 | **16098** | 24 | 9 | 33 | false | customer=0 | 2 + 4 |
| `/ledgers/management-analysis.json` | 19632 | **18675** | 16 | 2 | 18 | false | customer=0 | 2 + 4 |
| `/ledgers/payables-analysis.json` | 7897 | **7405** | 16 | 4 | 20 | false | supplier=0 | 3 + 4 |

### Per-page upstream (AR clients YTD sample)

- Invoice pages: ~6.4 s, ~10.2 s  
- Payment pages: ~0.25–0.83 s  

### Per-page upstream (AP YTD sample)

- Expense pages: ~2.5 s, ~2.6 s, ~0.7 s  
- Payment pages: ~0.37–0.43 s  

---

## Warm YTD (same process TTL, refresh=0)

| Probe | http_ms | wfirma_wait_ms | ej_ms | cache_hit |
|-------|--------:|---------------:|------:|:---------:|
| clients | **39** | **0** | 9 | true |
| payables | **21** | **0** | 3 | true |

---

## Cold narrower windows (decision evidence)

| Window | AR clients http / wfirma / ej | AP payables http / wfirma / ej |
|--------|-------------------------------:|-------------------------------:|
| Quarter 2026-07-01→08-10 | **4102 / 3920 / 3** | **1049 / 1006 / 2** |
| Month 2026-08-01→08-10 | **1657 / 1550 / 0** | **438 / 420 / 0** |

---

## Decision pointer

See `.claude/memory/plan-accounting-ledger-cold-latency.md` Phase C: **default = current quarter**; YTD remains explicit preset; formulas unchanged.
