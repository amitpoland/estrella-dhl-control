# Waterfall — Ledger Cold Latency (AFTER quarter default)

**Measured:** 2026-08-10 (instrumented worktree uvicorn `:47214`)  
**Decision applied:** default Balance / clients window = **current UTC quarter** (YTD remains explicit preset)  
**Raw JSON:** `.claude/memory/measure-ledger-cold-after.json`  
**Before:** `.claude/memory/waterfall-ledger-cold-before.md`

---

## Cold default (no `from` / FE quarter)

| Probe | period | http_ms | wfirma_wait_ms | ej_ms | cache | per_* |
|-------|--------|--------:|---------------:|------:|:-----:|------:|
| clients limit=15 refresh=1 | 2026-07-01→08-10 | **3877** | 3634 | 3 | false | customer=0 |
| payables outstanding refresh=1 | 2026-07-01→08-10 | **986** | 948 | 2 | false | supplier=0 |

## Warm default / quarter

| Probe | http_ms | wfirma_wait_ms | cache |
|-------|--------:|---------------:|:-----:|
| clients | **31** | 0 | true |
| payables | **4** | 0 | true |

## Explicit YTD still available (unchanged semantics)

| Probe | period | http_ms | wfirma_wait_ms |
|-------|--------|--------:|---------------:|
| clients refresh=1 | 2026-01-01→08-10 | 16631 | 15566 |

---

## Before → After (cold Balance / roster)

| Path | Before (YTD default) | After (quarter default) |
|------|---------------------:|------------------------:|
| AR clients | ~17843 ms (wfirma ~16098) | **~3877 ms** (wfirma ~3634) |
| AP payables | ~7897 ms (wfirma ~7405) | **~986 ms** (wfirma ~948) |
| Warm AR | ~39 ms | **~31 ms** |
| Warm AP | ~21 ms | **~4 ms** |

N+1 still gone. AR/AP formulas unchanged (window selection only). EJ still negligible vs wFirma.
