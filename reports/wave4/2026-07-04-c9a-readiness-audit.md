# C-9a (get_stock) — Implementation Readiness Audit

**Date:** 2026-07-04 · Research only, no code. Milestone Wave 4 · slice C-9a (double-stock-out verification read; stub `wfirma_client.py:1161`).

## Dependency table

| Dependency | Current owner | Already implemented? | Needs change? | Risk |
|---|---|---|---|---|
| Transport + auth (`_http_request`, accessKey/secretKey/appKey, company_id) | `wfirma_client.py:~340,460` | YES — live | No | Low |
| `goods` module read | `wfirma_client.py:994` (`goods/find` LIVE in prod) | YES | No — get_stock reuses it | Low |
| `get_stock()` | `wfirma_client.py:1161` | NO — `NotImplementedError` stub | YES — implement read+parse | Low |
| Auth / permissions (goods scope) | settings + transport | YES — goods/find works live ⇒ scope granted (OI-4 resolved) | No | Low |
| Retry / circuit breaker | `core/circuit_breaker` "wfirma" (`:460`) | YES | No | Low |
| Error handling | goods/find RuntimeError pattern (`:996-999`) | YES | Mirror it | Low |
| Response parse (count/reserved/available) | `_find_text` helpers | Partial | YES — parse count/reserved; available=count−reserved | Low |
| Warehouse mapping | `settings.wfirma_warehouse_id`, `list_warehouses():536` | YES | Maybe — filter if count is per-warehouse (resolve from live response) | Med |
| Cache layer | product cache (C-3g passthrough retired) | N/A | No — stock is a LIVE read, never cached | Low |
| Reservation layer | `wfirma_reservation.py` | YES | No (optional future consumer) | Low |
| UI consumers | none (primitive for C-5a double-stock-out guard) | N/A | No | Low |
| Polling | on-demand read (stock webhook = OI-10, future) | N/A | No | Low |

## Plan

**Implementation order (files only):** 1) `service/app/services/wfirma_client.py` — implement `get_stock()` (replace stub). 2) `service/tests/test_wfirma_client_get_stock.py` (new) — unit test.

**Read path:** `get_stock(good_id)` → `_http_request("GET","goods","get/{id}")` (fallback `goods/find` id-eq) → parse `<count>`/`<reserved>` → `{count, reserved, available=count−reserved}`. Reuses live transport/auth/breaker; no new endpoint.

**Cache updates:** NONE — stock must be a live verification read; caching would defeat the double-stock-out guard (aligns with C-3g cache-passthrough retirement).

**Tests:** unit-mock `_http_request` → assert count/reserved/available parse; HTTP≠200 → RuntimeError (goods/find precedent); empty-id guard; missing-field defaults. Then `make verify` (golden 160) + `pytest -m smoke`.

**Verification:** `cd service && pytest tests/test_wfirma_client_get_stock.py -v` + `make verify` + smoke. No browser (backend primitive, no UI surface). Optional live read via `test.api2.wfirma.pl` only if OI-5 sandbox authorized — not required for the read primitive.

**Rollback:** revert the single `wfirma_client.py` commit → `get_stock` returns to stub. No schema, no data, no prod state, no consumer depends on it ⇒ zero-risk rollback.

**Blockers:** none gating implementation. Note (not a blocker): whether `count`/`reserved` are per-warehouse or total is resolved inline from the live `goods` response; per-warehouse filtering by `wfirma_warehouse_id` is an internal detail, not an external dependency.

**Verdict:** C-9a IMPLEMENTATION READY
