# C-8a (goods stock-change webhook handler) — Implementation Readiness Audit

**Date:** 2026-07-04 · Research only, no code. Wave 4 · C-8a. Scope: wFirma "Produkty » Zmiana ilości na magazynie" (Products » Stock quantity change) webhook handler.

## 1. Dependency table

| Dependency | Current owner | Implemented? | Needs change? | Risk |
|---|---|---|---|---|
| Webhook receiver (POST /api/v1/webhooks/wfirma) | `routes_webhooks_wfirma.py` | YES | No | Low |
| Auth / key (503 unconfigured · 400 bad-JSON · 403 const-time key) | `routes_webhooks_wfirma.py` | YES | No | Low |
| Persistence + idempotency | `wfirma_webhook_db` (`event_id` PRIMARY KEY, INSERT OR IGNORE) | YES | No | Low |
| Snapshot + scheduler dispatch | `wfirma_snapshot_processor` + `wfirma_webhook_scheduler` (enrichment/customer/payment/contractor ticks) | YES | Add a stock tick + processor | Low |
| Stock read primitive | `wfirma_client.get_stock` (C-9a, `20572146`) | YES | No | Low |
| **Stock persistence target (count/reserved)** | Product Master / mirror | **NO — none exists** (`product_local` has no stock col; Master = identity-only, Constitution §6; C-9a uncached) | **YES — needs a target OR event-record-only decision** | **HIGH (blocker)** |
| **Stock-change payload contract** (event_type string + good-id field) | wFirma (skill `webhooks.md`) | **Undocumented in skill** (UI label only) | Needs a live sample (OI-10) | **HIGH (blocker)** |
| Activation (key on prod + UI registration) | OI-7 / OI-10 | operator-gated | — | Operator |

## 2. Event contract

- **Webhook event name:** "Produkty » Zmiana ilości na magazynie" (UI label). **Wire `event_type` string: UNDOCUMENTED in skill.**
- **Expected payload fields:** **UNDOCUMENTED** — `webhooks.md` states JSON + standard goods-branch envelope conventions but does not specify the stock-change payload (which field carries the good `id` / new count). Requires a live sample.
- **Auth/key behavior:** `webhook_key` in JSON body, constant-time (`hmac.compare_digest`) vs `settings.wfirma_webhook_key`; 503/400/403 as above (existing receiver — reused unchanged).
- **Idempotency key:** `payload["id"]` → `event_id` PRIMARY KEY + INSERT OR IGNORE (existing; duplicate delivery is a no-op).
- **Lookup path:** payload good id (field **undocumented**) → `get_stock(wfirma_good_id)` (C-9a, authoritative re-read; never trust payload count).
- **Stock refresh path:** `get_stock` → **no persistence target (BLOCKED)** — Master is identity-only, no stock cache exists.

## 3. Implementation order (files only — once unblocked)

1. `service/app/services/wfirma_stock_sync_processor.py` (new — mirrors `wfirma_enrichment_processor.py`).
2. `service/app/services/wfirma_webhook_scheduler.py` (add `_run_stock_sync_tick` alongside the existing ticks).
3. **Persistence target — TBD by operator decision** (a new stock-projection `*_db`, or event-record-only; a new table is a schema change requiring approval — cited blocker, not chosen here).
4. `service/tests/test_wfirma_stock_sync_processor.py` (new).

## 4. Tests (defined; blocked until §2/§target resolved)

- **Unit:** stock-change event routed to the stock processor (non-matching event_type ignored).
- **Webhook auth:** 503 unconfigured · 400 bad-JSON · 403 missing/invalid key (existing receiver contract — already covered).
- **Idempotency:** duplicate `event_id` processed once (INSERT OR IGNORE + processing-state guard).
- **Invalid payload:** missing good-id field → defensive reject/log, no crash (blocked: field name undocumented).
- **Stock-refresh:** mock `get_stock` → assert target updated (blocked: no target defined).

## 5. Activation boundary

- **Buildable now:** none end-to-end. The receiver + auth + persistence + idempotency + snapshot/dispatch + `get_stock` all exist, but the processor's **parse** (undocumented event_type/field) and **action** (no persistence target) are the two undefined pieces — building either would require assuming a wFirma payload shape (forbidden) or adding schema without approval (forbidden).
- **Operator-gated:** OI-7 (`WFIRMA_WEBHOOK_KEY` set on prod) + OI-10 (register the stock-change event in wFirma UI — which also yields the live payload sample that resolves §2).

## Verdict

C-8a BLOCKED: (1) stock-change webhook payload contract undocumented in skill (event_type + good-id field) — needs a live sample via wFirma-UI test registration (OI-10); (2) no persistence target for refreshed stock (Product Master is identity-only per Constitution §6; C-9a is uncached) — requires an operator decision: event-record-only, or a new stock-projection table (schema change, needs approval).
