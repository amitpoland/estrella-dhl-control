# Service / Scheduler Map

**Base SHA:** aa414d90
**Census timestamp:** 2026-07-01T015910Z
**Inspector agent:** service-scheduler-inspector
**Mode:** READ-ONLY — no app code was modified
---

# Service / Scheduler Map

**Base SHA:** aa414d90
**Service files found:** 214 (per CLAUDE.md architecture note; glob truncates at ~100 results per call)
**Scheduled jobs:** 4 (1 APScheduler BackgroundScheduler job; 3 asyncio.create_task loops)
**Startup-initiated services:** 9
**Orphaned services (routes dead):** 0
**SCHEDULER-ONLY capabilities (no Business API):** 2

## Startup Sequence

Ordered list of what `service/app/main.py` starts inside the `lifespan` context manager (lines 147–411):

1. `init_db(_auth_db)` — auth database initialisation — `routes_auth.py` — registered: YES
2. `init_packing_db` / `init_warehouse_db` / `init_warehouse_receipt_db` / `init_document_db` / `init_wfirma_db` / `init_correction_registry` / `init_intake_lineage` / `init_proforma_service_charges` / `init_tracking_db` — operational DB bootstrap — multiple route files — registered: YES
3. `init_reservation_db` (non-fatal try/except) — reservation queue DB — `routes_reservations.py` — registered: YES (INFERRED: routes_reservations.py is not imported in main.py by that name; wfirma_reservation_router covers it)
4. `load_persisted_flags_into_settings()` — DHL self-clearance runtime flag replay — `routes_admin_runtime_flags.py` — registered: YES
5. `mark_startup_replay_complete()` (from `active_shipment_monitor`) — W-5 P2 ignition boot-replay guard — `routes_monitor.py` — registered: YES
6. Governance flag audit (`_dangerous_flags` / `_ai_flags` log block) — startup-only log; no route — N/A
7. `generate_startup_authority_manifest()` (gated by `authority_drift_detection` flag) — authority drift detection — `routes_admin.py` — registered: YES
8. `start_watcher()` (from `routes_bot`) — bot debounce watcher asyncio task, polls every 2s — `routes_bot.py` — registered: YES
9. `batch_manager.start_sweep()` — batch session expiry/auto-submit sweep asyncio task, every 15s — `routes_batch.py` — registered: YES
10. `dhl_orchestrator.start_loop()` (gated by `DHL_ORCH_ENABLED`, default OFF) — DHL shipment orchestration asyncio loop, interval ≥60s — `routes_orchestrator.py` — registered: YES
11. Engine health check `run_engine_health_check()` (gated by `RUN_VERIFY_ON_STARTUP`) — one-shot diagnostic — `routes_system.py` — registered: YES
12. `wfirma_dictionary_cache` series bootstrap (`init_series_cache` / `load_cache_from_disk` / `refresh_from_wfirma`) — wFirma invoice/proforma series cache warm-up — `routes_wfirma_capabilities.py` (consumers) — registered: YES
13. Dashboard ActionRegistry route contract validator (warning-only) — startup validation log — no route of its own
14. `start_wfirma_scheduler(_root)` (from `wfirma_webhook_scheduler`) — APScheduler BackgroundScheduler, 30s interval, all 5 sub-steps — `routes_webhooks_wfirma_status.py` / `routes_wfirma_contractors.py` — registered: YES

## Scheduler Table

| Job | Service File | Interval | Calls | Domain | Route registered | Business API | Business UI | Observability |
|---|---|---|---|---|---|---|---|---|
| wfirma_webhook_processor (Step 1+2) — Webhook snapshot | `wfirma_webhook_scheduler.py` | 30s | `_run_processing_tick()` → `InvoiceSnapshotProcessor.process()` | wFirma invoice events → immutable snapshots | YES (`routes_webhooks_wfirma_status.py`) | NO direct trigger endpoint; webhook receiver at `POST /api/v1/webhooks/wfirma` | NO Run-Now button | YES (`GET /api/v1/webhooks/wfirma/status`) |
| wfirma_webhook_processor (Step 3) — Proforma enrichment | `wfirma_webhook_scheduler.py` | 30s (sub-step) | `_run_enrichment_tick()` → `enrich_snapshot()` | wFirma proforma enrichment (Phase 2B) | YES (`routes_webhooks_wfirma_status.py`) | NO separate trigger | NO | YES (covered by `/wfirma/status` queue stats) |
| wfirma_webhook_processor (Step 4) — Customer sync | `wfirma_webhook_scheduler.py` | 30s (sub-step) | `_run_customer_sync_tick()` → `sync_customer_from_snapshot()` | Customer Master enrichment from invoice snapshots (Phase 3) | YES (`routes_webhooks_wfirma_status.py`) | NO dedicated `POST /api/v1/.../run` for this sub-step | NO Run-Now button for Phase 3 specifically | PARTIAL (webhook status shows queue counts, no Phase-3-specific status endpoint) |
| wfirma_webhook_processor (Step 5) — Payment sync | `wfirma_webhook_scheduler.py` | 30s (sub-step, 1h cooldown per contractor) | `_run_payment_sync_tick()` → `sync_payments_for_contractor()` | wFirma payment snapshots per contractor (Phase 4A) | YES (scheduler only; no dedicated route file) | NO `POST /api/v1/wfirma/payments/sync` endpoint exists | NO | NO dedicated status endpoint |
| wfirma_webhook_processor (Step 6) — Contractor poll | `wfirma_webhook_scheduler.py` | 30s (sub-step, 6h cooldown) | `_run_contractor_poll_tick()` → `scan_contractors_into_master()` | Full wFirma contractor master scan (Phase 3B) | YES (`routes_wfirma_contractors.py`) | YES (`POST /api/v1/wfirma/contractors/scan`) | YES (`⇅ Full Scan` button in `customer-master-v2.html`) | YES (`GET /api/v1/wfirma/contractors/scan/status`) |
| dhl_orchestrator._loop | `dhl_orchestrator.py` | ≥60s (default OFF — `DHL_ORCH_ENABLED=false`) | `run_tick(persist=True)` | DHL shipment lifecycle state-machine (Phase 1 observe+decide) | YES (`routes_orchestrator.py`) | YES (`POST /api/v1/orchestrator/tick`) | NO Run-Now button in UI | PARTIAL (no status panel; dry-run and state endpoints exist) |
| batch_manager._sweep_loop | `batch_manager.py` | 15s | `_sweep_loop()` → auto-submit / expiry callbacks | Cliq bot batch session management | YES (`routes_batch.py`) | N/A (session lifecycle, not a business sync) | N/A | N/A |
| routes_bot._batch_watcher | `routes_bot.py` | 2s poll | `_batch_watcher()` → `_run_with_timeout()` | Cliq bot file-upload debounce | YES (`routes_bot.py`) | N/A | N/A | N/A |

## Orphaned Services

Services that run at startup but whose route file is NOT registered in `main.py`:

| Service | File | What it does | Route file | Action needed |
|---|---|---|---|---|
| — | — | — | — | — |

No orphaned services found. Every background service started in the lifespan has its corresponding route file imported and registered via `app.include_router(...)` in `main.py`. The wFirma webhook scheduler is covered by `routes_webhooks_wfirma_status.py` (status) and `routes_wfirma_contractors.py` (Phase 3B); the DHL orchestrator by `routes_orchestrator.py`; the bot watcher and batch sweep by `routes_bot.py` and `routes_batch.py` respectively.

## SCHEDULER-ONLY Capabilities

Capabilities with automation but missing Business API, Business UI, or Observability:

| Capability | Has Scheduler | Has Business API | Has Business UI | Has Status Endpoint | Gap |
|---|---|---|---|---|---|
| Phase 3 — Customer Sync (event-driven: invoice snapshot → customer_master fill-when-empty) | YES (30s sub-step inside `wfirma_webhook_processor`) | NO — no `POST /api/v1/.../customer-sync/run` endpoint exists; `POST /api/v1/customer-master/sync-from-wfirma/apply` covers a different manual batch-preview flow, not the same `sync_customer_from_snapshot()` function | NO — no "Run Now" button wired to a Phase-3-specific trigger; `⟳ Sync from wFirma` button targets the wfirma_capabilities preview/apply flow, not the scheduler sub-step | NO — `GET /api/v1/webhooks/wfirma/status` reports overall queue states but has no Phase-3-specific `customer_synced_at` counters or last-run timestamp | Missing Business API (`POST .../customer-sync/run`), no dedicated UI trigger, no per-capability status fields. SCHEDULER-ONLY per Business Feature Completeness Standard. |
| Phase 4A — Payment Sync (contractor payment snapshots → `payment_state.db`) | YES (30s sub-step, 1h per-contractor cooldown) | NO — no `POST /api/v1/wfirma/payments/sync` or equivalent endpoint; `accounting-hub.jsx` stubs `POST /api/v1/wfirma/sync/{type}` but the backend route does not exist | NO — no Run-Now button wired to a live endpoint | NO — no `GET /api/v1/wfirma/payments/status` endpoint; `payment_state.db` is written but never read by any API surface | All four layers missing: Business API, Business UI, Status endpoint, UI status panel. SCHEDULER-ONLY. |

---

## Sources

| File | Lines read |
|---|---|
| `C:\PZ-verify\service\app\main.py` | 1–739 (full file) |
| `C:\PZ-verify\service\app\services\wfirma_webhook_scheduler.py` | 1–445 (full file) |
| `C:\PZ-verify\service\app\services\dhl_orchestrator.py` | 1–80, 80–130, 840–925 |
| `C:\PZ-verify\service\app\services\batch_manager.py` | 1–60, 290–340 |
| `C:\PZ-verify\service\app\services\active_shipment_monitor.py` | 1–80 |
| `C:\PZ-verify\service\app\services\dhl_followup_sla.py` | 1–50 |
| `C:\PZ-verify\service\app\services\dhl_dsk_chase_sla.py` | 1–50 |
| `C:\PZ-verify\service\app\services\reservation_worker.py` | 1–60 |
| `C:\PZ-verify\service\app\services\wfirma_customer_sync_processor.py` | 1–40 |
| `C:\PZ-verify\service\app\api\routes_bot.py` | 1–80 |
| `C:\PZ-verify\service\app\api\routes_monitor.py` | 1–35 (full file) |
| `C:\PZ-verify\service\app\api\routes_orchestrator.py` | 1–40 |
| `C:\PZ-verify\service\app\api\routes_wfirma_contractors.py` | 1–129 (full file) |
| `C:\PZ-verify\service\app\api\routes_webhooks_wfirma_status.py` | 1–250 |
| `C:\PZ-verify\service\app\api\routes_webhooks_wfirma.py` | 1–50 |
| `C:\PZ-verify\service\app\api\routes_customer_master.py` | 1–60, 604–680 |
| `C:\PZ-verify\service\app\api\routes_wfirma_capabilities.py` | 1525–1584 (router.post entries for sync) |
| `C:\PZ-verify\service\app\api\routes_ledgers.py` | grep only |
| `C:\PZ-verify\service\app\static\customer-master-v2.html` | 244–410 (ScanStatusPanel + runFullScan), 1134–1256 |
| `C:\PZ-verify\service\app\static\v2\master-page.jsx` | grep only |
| `C:\PZ-verify\service\app\static\v2\accounting-hub.jsx` | 1–60 |
| Glob results for `service/app/services/*.py` (multiple passes by letter group) | file enumeration only |
