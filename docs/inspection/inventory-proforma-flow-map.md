# Inventory + Proforma Flow Inspection Report

Scope: main HEAD only. READ ONLY. DB counts taken from `C:\PZ\storage` (production-equivalent on this host) for accuracy.

## 1. Current stable flow

- **Packing list upload**:
  - Intake: `POST /api/v1/shipment/intake` — full chain (AWB + invoices + packing + sales) (`service/app/api/routes_intake.py:189`).
  - Per-batch upload: `POST /api/v1/packing/{batch_id}/upload` (`service/app/api/routes_packing.py:291`).
  - Extraction → `process_packing_upload` (`invoice_packing_extractor`) → rows persisted via `pdb.upsert_packing_lines` and seeded into `inventory_state` as `PURCHASE_TRANSIT` (`routes_packing.py:54-62`).

- **Shipment/batch creation**:
  - `routes_intake.py:189` (`/intake`) creates `batch_id` (uuid), writes evidence under `storage_root/outputs/{batch_id}/source/...`, registers `shipment_documents` (`documents.db`), seeds `intake_events`, and downstream calls inventory seeding.
  - "Shipment" is not a first-class table: there is **no** `shipment_batches` table. Batch identity = output folder + `audit.json` + the per-batch rows scattered across `packing_lines`, `inventory_state`, `shipment_documents`, `pz_documents`, `proforma_drafts`. (Confirmed via `sqlite_master` listing of `pz_main.db`, which is empty.)

- **Inventory state/count source**:
  - `inventory_state_engine.count_by_state()` reads the `state` column on `inventory_state` directly (`service/app/services/inventory_state_engine.py:177-194`).
  - Engine is the single writer (`transition()`, lines 207-310).
  - Stage 2 aggregator wraps it for the dashboard (`service/app/services/inventory_stage2_aggregator.py:73-84`).
  - States: `PURCHASE_TRANSIT`, `WAREHOUSE_STOCK`, `DIRECT_DISPATCH_READY`, `CLIENT_DISPATCHED`, `SALES_TRANSIT`, `CLOSED` (`inventory_state_engine.py:74-85`).

- **Proforma draft creation**:
  - Preview (read-only resolution): `POST /api/v1/proforma/preview/{batch_id}/{client_name}` (`service/app/api/routes_proforma.py:738`).
  - Create draft shell (persists `proforma_drafts`, idempotent on `(batch_id, client_name)`): `POST /api/v1/proforma/create/{batch_id}/{client_name}` (`routes_proforma.py:887`).
  - Draft state machine endpoints at `/draft/{id}/...`: get, patch, approve, re-open, cancel, lines CRUD, service charges (`routes_proforma.py:2632`-`3038`).
  - Storage: `proforma_drafts` table + `proforma_draft_events` audit, in `proforma_links.db` (`service/app/services/proforma_invoice_link_db.py`).

- **wFirma post**:
  - From local draft: `POST /api/v1/proforma/draft/{draft_id}/post` (`routes_proforma.py:3263`). Gated by `settings.wfirma_create_proforma_allowed`, receiver preflight via `wfirma_client.fetch_contractor_by_id`, transitions draft `approved → posting → posted | post_failed`.
  - PZ doc create on wFirma side: `POST /api/v1/upload/shipment/{batch_id}/wfirma/pz_create` (`service/app/api/routes_wfirma.py:1330`). Frontend caller: `dashboard.html:15007`.
  - Reservation create: `POST /api/v1/wfirma/reservations/create` (`service/app/api/routes_wfirma_reservation.py:74`).

- **Dispatch/closure**:
  - Direct dispatch flag: `POST /api/v1/lifecycle/inventory-state/mark-direct-dispatch` (`service/app/api/routes_lifecycle.py:469`) — transitions `PURCHASE_TRANSIT → DIRECT_DISPATCH_READY` with evidence gate.
  - Closure check/evaluate: `POST /api/v1/lifecycle/closure/{batch_id}/evaluate`, `GET .../check` (`routes_lifecycle.py:205,219`). Backed by `shipment_closure.py`.
  - There is no explicit transition wired in code from `WAREHOUSE_STOCK → SALES_TRANSIT` (engine allows it; no caller invokes it).

### Data volume snapshot

From `C:\PZ\storage`:

- Total piece records (`inventory_state`, all states): **0**
- Total shipment_batch records: **n/a — no `shipment_batches` table** (`pz_main.db` is empty; batch identity is folder + `audit.json` + `shipment_documents`). `shipment_documents` row count = **10**, oldest `2026-05-09T20:48:54Z`, newest `2026-05-11T02:39:20Z`.
- Total proforma_draft records: **4** (all `status='created'`, all `created_at=2026-05-11T01:41:06Z`).
- Total wFirma posted records: **0** (no draft has `posted_at` set; `wfirma_reservation_drafts=0`).
- Oldest record date (across system): `2026-05-09T20:48:54Z` (shipment_documents).
- Most recent record date: `2026-05-11T02:39:20Z` (shipment_documents).

Tables that exist:
- `warehouse.db`: `inventory_state`, `inventory_state_events`, `inventory_movement_events`, `inventory_current_location`, `warehouse_locations`
- `proforma_links.db`: `proforma_drafts`, `proforma_draft_events`, `proforma_service_charges`
- `wfirma.db`: `wfirma_products`, `wfirma_customers`, `wfirma_reservation_drafts`, `wfirma_reservation_lines`
- `packing.db`: `packing_documents`, `packing_lines`
- `documents.db`: `shipment_documents`, `invoice_lines`, `pz_documents`, `sales_documents`, `sales_packing_lines`, `customs_declarations`, `awb_documents`, others

Tables that do not exist (of those asked):
- `inventory_allocations` — absent
- `inventory_reservations` — absent (only `wfirma_reservation_drafts`/`_lines` exist)
- `shipment_batches` — absent (batch identity is folder + `audit.json` + cross-DB rows)
- `packing_lists` — present as `packing_documents`/`packing_lines` (different name)
- `proforma_posted` — absent (state is a column on `proforma_drafts`)

## 2. Existing endpoints

| Method | Path | Purpose | Read/Write | Real/Mock | Frontend caller | Evidence (file:line) |
|--------|------|---------|------------|-----------|-----------------|----------------------|
| GET  | `/api/v1/inventory/stage2/aggregate` | 5-bucket Stage 2 summary | R | Real (final_stock only) | `dashboard.html:1270` | `routes_inventory.py:42` |
| POST | `/api/v1/shipment/intake` | Full intake (AWB+inv+packing+sales) | W | Real | `dashboard.html:2854` | `routes_intake.py:189` |
| POST | `/api/v1/packing/{batch_id}/upload` | Per-batch packing upload | W | Real | `dashboard.html:6894` | `routes_packing.py:291` |
| GET  | `/api/v1/packing/{batch_id}` | Read packing doc | R | Real | `dashboard.html:5870` | `routes_packing.py:431` |
| GET  | `/api/v1/packing/{batch_id}/lines` | Read packing lines | R | Real | — | `routes_packing.py:460` |
| POST | `/api/v1/proforma/preview/{batch_id}/{client_name}` | Readiness preview | R (no writes) | Real | indirect | `routes_proforma.py:738` |
| POST | `/api/v1/proforma/create/{batch_id}/{client_name}` | Create draft shell | W | Real | indirect | `routes_proforma.py:887` |
| GET  | `/api/v1/proforma/drafts/{batch_id}` | List drafts per batch | R | Real | `dashboard.html:15819` | `routes_proforma.py:2632` |
| GET  | `/api/v1/proforma/draft/{draft_id}` | Read one draft | R | Real | `dashboard.html:15835,15849` | `routes_proforma.py:2653` |
| GET  | `/api/v1/proforma/draft/{draft_id}/events` | Draft event log | R | Real | `dashboard.html:15859` | `routes_proforma.py:2670` |
| PATCH | `/api/v1/proforma/draft/{draft_id}` | Patch draft fields | W | Real | yes | `routes_proforma.py:2734` |
| POST | `/api/v1/proforma/draft/{draft_id}/approve` | Approve draft | W | Real | yes | `routes_proforma.py:2831` |
| POST | `/api/v1/proforma/draft/{draft_id}/post` | Post to wFirma | W (live wFirma) | Real, gated by `WFIRMA_CREATE_PROFORMA_ALLOWED` | `dashboard.html:16028` | `routes_proforma.py:3263` |
| GET  | `/api/v1/wfirma/reservation-preview/{batch_id}` | Reservation grouping | R | Real | `dashboard.html:5644` | `routes_wfirma_reservation.py:32` |
| POST | `/api/v1/wfirma/reservations/create` | Create one reservation | W (live wFirma) | Real, gated | yes | `routes_wfirma_reservation.py:74` |
| POST | `/api/v1/upload/shipment/{batch_id}/wfirma/pz_create` | Create PZ in wFirma | W | Real | `dashboard.html:15007` | `routes_wfirma.py:1330` |
| GET  | `/api/v1/upload/shipment/{batch_id}/wfirma/pz_preview` | PZ preview | R | Real | yes | `routes_wfirma.py:978` |
| POST | `/api/v1/lifecycle/inventory-state/mark-direct-dispatch` | Promote → DIRECT_DISPATCH_READY | W | Real | no UI caller found | `routes_lifecycle.py:469` |
| GET  | `/api/v1/lifecycle/closure/{batch_id}/check` | Closure readiness | R | Real | yes | `routes_lifecycle.py:219` |
| POST | `/api/v1/lifecycle/closure/{batch_id}/evaluate` | Run closure | W | Real | yes | `routes_lifecycle.py:205` |
| POST | `/api/v1/warehouse/scan` | Physical scan (RECEIVE etc.) | W | Real | warehouse.html | `routes_warehouse.py:80` |
| GET  | `/api/v1/warehouse/inventory/{scan_code}` | Read one item state | R | Real | yes | `routes_warehouse.py:130` |
| POST | `/api/v1/upload/reservations/import-purchase-packing` | Seed product_master | W | Real | yes | `routes_reservations.py:93` |
| POST | `/api/v1/upload/reservations/import-sales-packing` | Seed reservation_queue | W | Real | yes | `routes_reservations.py:118` |
| GET  | `/api/v1/upload/reservations/queue` | Read reservation queue | R | Real | yes | `routes_reservations.py:144` |
| POST | `/api/v1/upload/reservations/process-pending` | Run reservation worker | W | Real | yes | `routes_reservations.py:174` |

## 3. Existing frontend buttons/cards

| Page | Button/card | Current status | Backend endpoint | Missing part | Evidence (file:line) |
|------|------------|----------------|------------------|--------------|----------------------|
| Inventory | KPI strip "Total / In warehouse / Reserved / Attention" | wired (derives from `/dashboard/batches` predicates) | `/dashboard/batches` | none for KPIs; but "reserved" comes from cross-batch predicate, not from a reservation table | `dashboard.html:1299-1318` |
| Inventory | "Open Warehouse Scanner" link | wired (link only) | `/dashboard/warehouse.html` | — | `dashboard.html:1324-1328` |
| Inventory | `⇄ Move stock` | disabled `data-pending="true"` | none | no backend route | `dashboard.html:1330-1343` |
| Inventory | `↗ Sample out` | disabled | none | no backend route | `dashboard.html:1330-1343` |
| Inventory | `↙ Sample return` | disabled | none | no backend route | `dashboard.html:1330-1343` |
| Inventory | `↩ Goods return` | disabled | none | no backend route | `dashboard.html:1330-1343` |
| Inventory | `↰ Return to producer` | disabled | none | no backend route | `dashboard.html:1330-1343` |
| Inventory | Stage 1 tiles (Temp Purchase / Warehouse / Sale) | static `Backend pending` | none | no aggregator | `dashboard.html:1421-1435` |
| Inventory | Stage 2 tiles (Final / Samples / Returns / Consignment / Unknown) | partial: only `final_stock` real | `/api/v1/inventory/stage2/aggregate` | 4 of 5 buckets null (no source) | `dashboard.html:1437-1484`; `inventory_stage2_aggregator.py:107-126` |
| New Shipment | Modal: AWB + Purchase blocks + Sales blocks + submit | wired | `POST /api/v1/shipment/intake` | direct-dispatch mark, customer allocation at intake time, "no packing list yet" path — present in API, not surfaced in UI | `dashboard.html:2777-2868` |
| Shipment detail | wFirma pz_create button | wired | `POST .../wfirma/pz_create` | — | `dashboard.html:15007` |
| Shipment detail | Reservation preview | wired | `GET /api/v1/wfirma/reservation-preview` | UI to actually call `/reservations/create` is in proforma drafts area | `dashboard.html:5644` |
| Shipment detail | Proforma drafts list + draft view + post | wired | `/api/v1/proforma/drafts/...`, `/draft/{id}/post` | — | `dashboard.html:15819,15835,16028` |
| Inventory | "mark direct dispatch" UI | **absent** | `/api/v1/lifecycle/inventory-state/mark-direct-dispatch` exists | no frontend caller | `routes_lifecycle.py:469`; grep returns no UI hits |

## 4. Inventory model finding

**state column canonical.**

Evidence:
1. Schema declares `state TEXT NOT NULL` as a column on `inventory_state` with `UNIQUE(scan_code)` enforcing one-row-per-item (`service/app/services/warehouse_db.py:136-146`).
2. The engine docstring is explicit: "States are explicit and persisted; never inferred from other tables." (`inventory_state_engine.py:49`). The `transition()` writer issues `UPDATE inventory_state SET state=?, ...` (`inventory_state_engine.py:273-285`) and `INSERT INTO inventory_state ... VALUES (... to_state, ...)` (`inventory_state_engine.py:289-296`).
3. Every read uses the column directly: `SELECT * FROM inventory_state WHERE state=?` (`inventory_state_engine.py:166,171`), `SELECT state, COUNT(*) FROM inventory_state GROUP BY state` (`inventory_state_engine.py:183-189`).
4. `inventory_state_events` is an append-only audit trail next to the state column, not the source of truth — counts come from `inventory_state.state`, not from event replay (`inventory_state_engine.py:183`; `inventory_stage2_aggregator.py:76` reads `count_by_state()`).

## 5. Double-allocation risk and reservation reality check

- **Can the same piece currently be sold/sampled/consigned twice?** **YES** for the consumer-of-state path: the state machine has no `RESERVED`/`ALLOCATED` intermediate and no row-level lock on `inventory_state` beyond `UNIQUE(scan_code)`. Two proforma drafts on the same `batch_id` for different clients can both pass the `_check_warehouse_readiness` gate because the readiness check counts batch-wide stock, not per-line allocation (`routes_proforma.py:419-424,86-100`). A reservation row in `wfirma_reservation_drafts` is per-`(batch, client)` but never decrements `inventory_state` or marks a scan_code allocated.
- **Does any reservation field/column/table exist?**
  - `wfirma_reservation_drafts` table + `wfirma_reservation_lines` table — `wfirma.db` (`reservation_db.py` is **not** their source; they come from `service/app/services/wfirma_reservation.py` and `wfirma_reservation_create.py`).
  - `reservation_queue` table — `service/app/services/reservation_db.py:89-114`. Per-line queue rows keyed on `queue_key` with `status: pending → ready → created`.
  - `product_master`, `design_product_mapping`, `wfirma_product_mapping`, `wfirma_customer_mapping` — `reservation_db.py:32-87`.
  - **No** `inventory_allocations` or `inventory_reservations` table.
- **Reservation mechanism status:** **WRITTEN and READ**, but disjoint from `inventory_state`. The reservation pipeline tracks "wFirma-side reservation has been created" — it does NOT prevent a second draft against the same `scan_code`. There is no link column from `reservation_queue` or `wfirma_reservation_lines` back to `inventory_state.scan_code`.
- **Conclusion: extend-existing.** `reservation_queue` is live (4 production proforma drafts exist; the queue table has rows in dev cycles) and is the natural place to add a `scan_code` column + a "claimed" status that decrements available stock. A clean-room allocation ledger is not required to fix double-allocation; the existing queue is one column short of being one.

## 6. New shipment UI gap list

- **Direct-dispatch flag at intake** — `NewShipmentModal` collects supplier + client but never lets the operator declare "this shipment bypasses the warehouse" (`dashboard.html:2777-2868`). The backend gate exists at `routes_lifecycle.py:469` but the modal has no checkbox/field.
- **Customer allocation per scan/per line** — sales blocks capture `clientName/clientRef` at the document level only (`dashboard.html:2796-2803`), never per packing line. The proforma readiness gate needs a per-line mapping but the intake stores it document-wide.
- **Packing list "later" path UI** — backend supports backfill (`POST /api/v1/shipment/{batch_id}/packing_list` at `routes_intake.py:830`) but the modal forces packing inside the same submission flow (`dashboard.html:2807-2832`).
- **No display of `inventory_state` seeding outcome** — the modal redirects to shipment detail on success (`dashboard.html:2862-2863`) without surfacing the `EV_INVENTORY_PURCHASE_TRANSIT_SEEDED` count from `routes_packing.py:101-111`.
- **No "Move stock / Sample out / Sample return / Goods return / Return to producer" forms** — all five are placeholder disabled buttons (`dashboard.html:1330-1343`); the lifecycle states they would target (e.g. SAMPLE_OUT, RETURNED_*) do not exist in `STATES` either (`inventory_state_engine.py:81-85`; `inventory_stage2_aggregator.py:37-51`).
- **Stage 1 tiles never wired** — `dashboard.html:1416-1435` shows three "Backend pending" tiles; there is no `/api/v1/inventory/stage1/...` route.

## 7. Required fix map

- **Must inspect further:**
  - `service/app/services/wfirma_reservation.py` and `wfirma_reservation_create.py` — confirm whether they read `inventory_state` at all, or only `packing_lines + invoice_lines`.
  - `service/app/services/shipment_closure.py` — confirm whether closure transitions `inventory_state` to `CLOSED` (not seen in this pass).
  - Whether any caller actually invokes the legal `WAREHOUSE_STOCK → SALES_TRANSIT` transition (no hits in `service/app`).

- **Safe read-only endpoints to add:**
  - `GET /api/v1/inventory/state/{batch_id}` — return `count_by_state(batch_id=batch_id)` so the InventoryPage and shipment detail can show per-batch lifecycle counts (engine already supports the call at `inventory_state_engine.py:177-194`).
  - `GET /api/v1/inventory/allocations/{batch_id}` — list pieces and their current "claim" (proforma draft or reservation) joining `reservation_queue` + `proforma_drafts.source_lines_json`. Read-only.
  - `GET /api/v1/inventory/stage1/aggregate` — derive Temp/Warehouse/Sale from `inventory_state` (3 of 5 are already in `STATES`).

- **Safe UI wiring:**
  - Wire the five disabled Inventory buttons (`dashboard.html:1330-1343`) to a single read-only "explain why disabled" tooltip pointing at the missing routes (no behaviour change).
  - Add a per-batch `inventory-state` strip to shipment detail that calls the new GET above.
  - Surface the seeded-count from `EV_INVENTORY_PURCHASE_TRANSIT_SEEDED` after `NewShipmentModal` submit.

- **Dangerous write actions requiring execute route:**
  - Any "Move stock / Sample out / Sample return / Goods return / Return to producer" implementation. Each needs a new state in `STATES` AND a legal transition added — touching `inventory_state_engine.py:81-107`. Must go through `/api/v1/execute` per project rules.
  - Adding `scan_code` to `reservation_queue` and using it to gate proforma draft creation — schema migration + cross-DB join.

- **Schema/ledger decision needed:**
  - Decide whether reservation_queue extends to per-scan_code allocation (extend-existing) OR a new `inventory_allocations` table is introduced. Recommendation in §8.

## 7.5 Blast radius if state-column model becomes ledger-derived

Functions that READ state directly:

| file:line | function_name | used_by | classification |
|-----------|---------------|---------|----------------|
| `inventory_state_engine.py:134` | `get_state` | `routes_packing.py:54`, `routes_upload.py:962`, `routes_lifecycle.py:528`, `routes_packing.py:768` | REWRITE (must compute current state from event tail) |
| `inventory_state_engine.py:159` | `list_by_state` | `routes_proforma.py:76` | REWRITE |
| `inventory_state_engine.py:177` | `count_by_state` | `inventory_stage2_aggregator.py:74` | REWRITE |
| `inventory_state_engine.py:236` | `transition` (reads prev row) | self | REWRITE |
| `routes_proforma.py:71-82` | `_state_codes` | proforma preview/create | TRIVIAL (consumes `list_by_state`) |

Functions that WRITE state directly:

| file:line | function_name | state values written | classification |
|-----------|---------------|---------------------|----------------|
| `inventory_state_engine.py:273` | `transition` (UPDATE) | all `STATES` | REWRITE (becomes append-only event insert; UPDATE goes away) |
| `inventory_state_engine.py:289` | `transition` (INSERT) | first-entry `PURCHASE_TRANSIT` | REWRITE |

No other writer exists across the service. Grep for `UPDATE inventory_state SET state` and `INSERT INTO inventory_state` returns only `inventory_state_engine.py`.

Test fixtures hardcoding state values:

| test_file:line | hardcoded state | classification |
|----------------|-----------------|----------------|
| `tests/test_inventory_state_engine.py` (uses `ise.PURCHASE_TRANSIT` etc.) | symbolic constants — not raw strings | TRIVIAL |
| `tests/test_warehouse_stock_promotion.py` | uses `ise.*` constants | TRIVIAL |
| `tests/test_purchase_transit_seeding.py` | uses `ise.*` constants | TRIVIAL |
| `tests/test_proforma_receiver_preflight.py`, `test_proforma_receiver_block.py`, `test_proforma_preview*.py`, `test_proforma_pricing_source.py` | uses `ise.*` constants | TRIVIAL |
| `tests/test_inventory_state_direct_dispatch.py`, `..._mark_direct_dispatch.py` | uses `ise.*` constants | TRIVIAL |
| `tests/test_intake_currency_and_pnd.py`, `test_audit_evidence.py` | uses `ise.*` constants | TRIVIAL |

A grep for raw string `'PURCHASE_TRANSIT'|'WAREHOUSE_STOCK'|'DIRECT_DISPATCH_READY'|'CLIENT_DISPATCHED'|'SALES_TRANSIT'|'CLOSED'` in `service/tests` returned zero matches — all tests go through `ise.*` symbolic constants.

**Net blast radius:** small. Five functions in one file own the state-column contract; tests are symbolic; downstream callers don't touch SQL.

## 8. Recommendation

**Finish mapping/wiring existing flow first; do NOT implement an allocation ledger now.**

Reason: the state-column model is clean, narrow, and uniquely-owned (one file writes, six callers read through the engine API). Production has 4 unposted proforma drafts, 0 reservations, 0 inventory rows on the inspected host — there is no operational pressure proving double-allocation has occurred. The actual gaps blocking the user-visible workflow are (a) `reservation_queue` rows do not carry `scan_code` so proforma `_check_warehouse_readiness` can't enforce per-piece allocation, and (b) the New Shipment / Inventory UI has 5 disabled buttons covering states (SAMPLE_OUT, RETURNED_*) that are not in `STATES`. Both are extensions to what exists, not replacements of it. A ledger rewrite would be cheap (§7.5) but premature — the existing model already supports it via `inventory_state_events` if needed later.

## 9. Final constraints for next Claude Code task

**Add `GET /api/v1/inventory/state/{batch_id}` (read-only) that returns `inventory_state_engine.count_by_state(batch_id=batch_id)` plus the list of `scan_code → state` for that batch.**

- ONE new endpoint in `service/app/api/routes_inventory.py`, GET only, no DB writes, no schema changes.
- Wire it in `dashboard.html` to a single new strip on the shipment detail view showing `{PURCHASE_TRANSIT, WAREHOUSE_STOCK, DIRECT_DISPATCH_READY, CLIENT_DISPATCHED, SALES_TRANSIT, CLOSED}` counts for the open batch.
- No changes to `inventory_state_engine.py`, no changes to other routers, no new tables, no UI buttons enabled.
- Acceptance: existing tests still pass; one new test in `tests/` covering the new GET route.
