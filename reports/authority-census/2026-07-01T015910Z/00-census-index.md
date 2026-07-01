# Authority Census Index

**Base SHA:** aa414d90
**Census timestamp:** 2026-07-01T015910Z
**Scanned by:** /authority-census Phase-1 (5-agent pack)
**Mode:** READ-ONLY — no app code was modified

---

## Deliverables

| # | Report | File |
|---|---|---|
| 1 | Frontend Authority Map | [01-frontend-authority-map.md](01-frontend-authority-map.md) |
| 2 | Backend Authority Map | [02-backend-authority-map.md](02-backend-authority-map.md) |
| 3 | Navigation Map | [03-navigation-map.md](03-navigation-map.md) |
| 4 | API Wrapper Comparison | [04-api-wrapper-map.md](04-api-wrapper-map.md) |
| 5 | Service / Scheduler Map | [05-service-scheduler-map.md](05-service-scheduler-map.md) |

---

## Summary Counters

| Metric | Value |
|---|---|
| Frontend files scanned | 63 (22 HTML + 8 atlas HTML + 33 v2 JSX) |
| Backend route files scanned | 78 (77 registered + 1 dead) |
| Modules at AUTHORITY status | 21 |
| Modules FRAGMENTED or DUPLICATE | 7 (3 FRAGMENTED + 4 DUPLICATE) |
| DEAD files found | 3 |
| ORPHAN files found | 9 |
| UNREACHABLE slugs | 12 (via ROUTE_REDIRECTS) |
| Scheduled jobs found | 4 (1 APScheduler BackgroundScheduler + 3 asyncio.create_task loops) |
| SCHEDULER-ONLY capabilities (no Business API) | 2 (Phase 3 Customer Sync, Phase 4A Payment Sync) |
| Dead routes (not in main.py) | 1 (`routes_reservations.py`) |

---

## Top Risk Items

1. **Shipment Detail is 5-way fragmented.** `shipment-detail-page.jsx` (V2 authority), `shipment-detail.html` (V1 live at `/dashboard/shipment-detail.html`), `shipment-detail-v3.html` (pre-V2 design shell), and two dead versioned JSX copies (`.v1.jsx`, `.v2.jsx`, not loaded by V2 index.html). V1 remains the primary operator surface for direct-link workflows; V2 detail page is only reachable via row-click. Highest single-module fragmentation in the platform.

2. **Phase 4A Payment Sync is scheduler-only and has no observable state.** `sync_payments_for_contractor()` runs every 30s inside `wfirma_webhook_scheduler.py` writing to `payment_state.db`, but no `POST /api/v1/wfirma/payments/sync` endpoint exists, no Run-Now button, no status endpoint, and `payment_state.db` is written but never read by any API surface. Business Feature Completeness Standard: all four layers missing. `accounting-hub.jsx` UI stubs a call to a non-existent backend route.

3. **12 slugs are UNREACHABLE via ROUTE_REDIRECTS.** `actions`, `proposals`, `email_queue`, `reservation` → `inbox`; `shipping` → `shipments`; `scanner`, `move_stock`, `identity`, `sample_out`, `sample_return`, `goods_return`, `return_prod` → `inventory`. Component code (`ShippingOpsPage`, `ActionCenterPage`, `ReservationCellPage`, `WarehouseScannerPage`, `IdentityMappingPage`, `MoveStockPage`, `SampleOutPage`, `SampleReturnPage`, `GoodsReturnPage`, `ReturnToProducerPage`) exists in `wireframe-update.jsx` / `ops-cell.jsx` / `shipping-ops.jsx` but the router intercepts before the component mounts. Lesson M exposure risk — capability suppression without formal DECISIONS entry.

4. **`routes_reservations.py` exists on disk but is not registered in main.py.** `init_reservation_db()` is called at startup (non-fatal try/except) and `reservation_worker.py` service exists, but the routes are not imported into `main.py` via `include_router`. `wfirma_reservation_router` may cover part of the surface, but the reservation queue routes themselves are dead. Also correlates with `/v2/reservation` UNREACHABLE slug (item 3).

5. **`getDraftVisibility` is the only root pz-api.js method with no v2 equivalent.** Backend endpoint at `routes_proforma.py:8722` is live; v2 pages use `getDraftReadiness` instead, but the Phase 5.5A visibility endpoint (operator-facing workflow state distinct from readiness) is not exposed in v2 PzApi. All other root methods are ported to v2 (29/30 = 96.7% coverage). No dead legacy methods in root.
