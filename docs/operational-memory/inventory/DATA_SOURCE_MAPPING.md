# Inventory Data Source Mapping — Doc 3 v1

This document is the per-state source-of-truth ledger that accompanies **Doc 1 v2** (the extend-existing inventory state architecture) and **Doc 2** (the lifecycle transition catalogue). For every inventory state and every Stage 2 aggregate category that the dashboard surfaces, it records exactly which table column, derived expression, or external API the count comes from; the SQL (or pseudocode) that produces it; the index that supports it; and whether the data source exists in production today or is pending implementation of Doc 1 v2 §3.

Two important caveats up front. First, several artifacts named in the task brief — `service/app/services/inventory_stage2_aggregator.py`, `service/app/api/routes_inventory.py`, the `/api/v1/inventory/stage2/aggregate` endpoint, and the 5-bucket payload — **do not exist in the repository today**. They are part of Doc 1 v2's proposed extension. Where this document references them it does so as PENDING. Second, the four databases that participate in the lifecycle bridge (`warehouse.db`, `reservations.db`, `wfirma.db`, `proforma_links.db`) live in separate SQLite files; cross-DB FK constraints are physically impossible there. The integrity caveat at the end of the document spells out the consequence.

All file:line citations are against the working tree at branch `claude/zealous-johnson-6d6d34`.

---

## PURCHASE_TRANSIT

| Field | Value |
|---|---|
| Status | EXISTS |
| Source of truth | `inventory_state.state = 'PURCHASE_TRANSIT'` (warehouse.db) |
| Storage backend | SQLite, `storage_root/warehouse.db` |
| Schema declaration | `service/app/services/warehouse_db.py:136-146` |
| Query (count) | `SELECT state, COUNT(*) AS n FROM inventory_state GROUP BY state` then read `counts['PURCHASE_TRANSIT']` — see `inventory_state_engine.py:188-194` |
| Query (list) | `SELECT * FROM inventory_state WHERE state=?` (`inventory_state_engine.py:170-173`); optional `AND batch_id=?` |
| Index supporting count query | `idx_invstate_state ON inventory_state(state)` at `warehouse_db.py:148-149` |
| Index supporting list query | same; for batch-scoped list `idx_invstate_batch` at `warehouse_db.py:150-151` |
| Used by | `inventory_state_engine.count_by_state()` at `inventory_state_engine.py:177-194`; transition entry point at `inventory_state_engine.py:207-310` |
| Frontend tile | none today (no Stage 2 aggregator wired). Would be `data-testid="inventory-stage2-purchase-transit"` under Doc 1 v2. |
| Notes | Created by `transition(None → PURCHASE_TRANSIT, trigger='pz_generated')`. One row per `scan_code` enforced by `UNIQUE(scan_code)` at line 138. |

---

## WAREHOUSE_STOCK

| Field | Value |
|---|---|
| Status | EXISTS |
| Source of truth | `inventory_state.state = 'WAREHOUSE_STOCK'` (warehouse.db) |
| Storage backend | SQLite, `storage_root/warehouse.db` |
| Schema declaration | `service/app/services/warehouse_db.py:136-146` |
| Query (count) | `SELECT state, COUNT(*) FROM inventory_state WHERE state='WAREHOUSE_STOCK' GROUP BY state` (via `count_by_state` at `inventory_state_engine.py:188-194`) |
| Query (list) | `SELECT * FROM inventory_state WHERE state='WAREHOUSE_STOCK'` (`inventory_state_engine.py:170-173`) |
| Index supporting count query | `idx_invstate_state` at `warehouse_db.py:148-149` |
| Index supporting list query | same |
| Used by | `count_by_state` / `list_by_state` in `inventory_state_engine.py`; this is the value Doc 1 v2 maps onto the Stage 2 `final_stock` bucket. |
| Frontend tile | `data-testid="inventory-stage2-final-stock"` (planned — endpoint not yet built). |
| Notes | Enters via `PURCHASE_TRANSIT → WAREHOUSE_STOCK` (`warehouse_receive`) at `inventory_state_engine.py:90, 101`. Eligible for Proforma per `PROFORMA_ELIGIBLE_STATES` at lines 113-115. |

---

## DIRECT_DISPATCH_READY

| Field | Value |
|---|---|
| Status | EXISTS |
| Source of truth | `inventory_state.state = 'DIRECT_DISPATCH_READY'` (warehouse.db) |
| Storage backend | SQLite, `storage_root/warehouse.db` |
| Schema declaration | `warehouse_db.py:136-146` |
| Query (count) | `SELECT state, COUNT(*) FROM inventory_state WHERE state='DIRECT_DISPATCH_READY' GROUP BY state` |
| Query (list) | `SELECT * FROM inventory_state WHERE state=?` |
| Index supporting count query | `idx_invstate_state` at `warehouse_db.py:148-149` |
| Index supporting list query | same |
| Used by | `count_by_state` / `list_by_state` in `inventory_state_engine.py`. Transition gated by 4-piece evidence (operator, customer_allocation, customs_cleared=True, prior RECEIVE event) at `inventory_state_engine.py:254-268`. |
| Frontend tile | none today; would surface under a "direct dispatch" tile in Doc 1 v2. |
| Notes | The only non-warehouse-pool eligible Proforma state alongside WAREHOUSE_STOCK and CLIENT_DISPATCHED (`PROFORMA_ELIGIBLE_STATES`). Evidence gate is in lifecycle code, not SQL — bypassing it requires raw DB writes. |

---

## CLIENT_DISPATCHED

| Field | Value |
|---|---|
| Status | EXISTS |
| Source of truth | `inventory_state.state = 'CLIENT_DISPATCHED'` (warehouse.db) |
| Storage backend | SQLite, `storage_root/warehouse.db` |
| Schema declaration | `warehouse_db.py:136-146` |
| Query (count) | `SELECT state, COUNT(*) FROM inventory_state WHERE state='CLIENT_DISPATCHED' GROUP BY state` |
| Query (list) | `SELECT * FROM inventory_state WHERE state=?` |
| Index supporting count query | `idx_invstate_state` at `warehouse_db.py:148-149` |
| Index supporting list query | same |
| Used by | `inventory_state_engine` public API; Proforma readiness gate (`PROFORMA_ELIGIBLE_STATES` line 113-115). |
| Frontend tile | none today. |
| Notes | Reached from `DIRECT_DISPATCH_READY` via `client_dispatched` trigger (line 92, 103). Eligible for *late* Proforma issuance. |

---

## SALES_TRANSIT

| Field | Value |
|---|---|
| Status | EXISTS |
| Source of truth | `inventory_state.state = 'SALES_TRANSIT'` (warehouse.db) |
| Storage backend | SQLite, `storage_root/warehouse.db` |
| Schema declaration | `warehouse_db.py:136-146` |
| Query (count) | `SELECT state, COUNT(*) FROM inventory_state WHERE state='SALES_TRANSIT' GROUP BY state` |
| Query (list) | `SELECT * FROM inventory_state WHERE state=?` |
| Index supporting count query | `idx_invstate_state` at `warehouse_db.py:148-149` |
| Index supporting list query | same |
| Used by | `inventory_state_engine` public API. |
| Frontend tile | none today. |
| Notes | Reached from `WAREHOUSE_STOCK` via `invoice_issued` trigger (line 91, 104). Terminal next state is `CLOSED`. |

---

## CLOSED

| Field | Value |
|---|---|
| Status | EXISTS |
| Source of truth | `inventory_state.state = 'CLOSED'` (warehouse.db) |
| Storage backend | SQLite, `storage_root/warehouse.db` |
| Schema declaration | `warehouse_db.py:136-146` |
| Query (count) | `SELECT state, COUNT(*) FROM inventory_state WHERE state='CLOSED' GROUP BY state` |
| Query (list) | `SELECT * FROM inventory_state WHERE state=?` |
| Index supporting count query | `idx_invstate_state` at `warehouse_db.py:148-149` |
| Index supporting list query | same |
| Used by | `inventory_state_engine`; terminal state — no outbound transitions (`LEGAL_TRANSITIONS[CLOSED] = frozenset()`, line 95). |
| Frontend tile | none today. |
| Notes | Reached from either `SALES_TRANSIT` or `CLIENT_DISPATCHED` via `delivery_confirmed` (lines 93-94, 105-106). |

---

## RESERVED_FOR_PROFORMA  *(PENDING)*

| Field | Value |
|---|---|
| Status | PENDING — proposed new state in Doc 1 v2 §3 |
| Source of truth | Would be `inventory_state.state = 'RESERVED_FOR_PROFORMA'` after the bridge worker adds it to `STATES` / `LEGAL_TRANSITIONS` at `inventory_state_engine.py:81-96`. |
| Storage backend | SQLite, `storage_root/warehouse.db` (same table) |
| Schema declaration | No schema change needed — `inventory_state.state` is plain `TEXT NOT NULL`. Bridge requires only the Python constant + transition entries. |
| Query (count) | `SELECT state, COUNT(*) FROM inventory_state WHERE state='RESERVED_FOR_PROFORMA' GROUP BY state` |
| Query (list) | `SELECT * FROM inventory_state WHERE state='RESERVED_FOR_PROFORMA'` |
| Index supporting count query | `idx_invstate_state` already covers it — `warehouse_db.py:148-149`. No new index required. |
| Index supporting list query | same |
| Used by | not yet wired |
| Frontend tile | not yet wired |
| Notes | Bridge invariant: a `RESERVED_FOR_PROFORMA` row should correspond 1:1 to a row in `reservation_queue` (reservations.db) with status `pending`/`ready`, and/or `wfirma_reservation_drafts` (wfirma.db) with `ready_to_create=0` or `=1`. See cross-DB caveat at the bottom. |

---

## DISPATCH_PENDING  *(PENDING)*

| Field | Value |
|---|---|
| Status | PENDING — proposed new state in Doc 1 v2 §3 |
| Source of truth | Would be `inventory_state.state = 'DISPATCH_PENDING'` after Doc 1 v2 §3 bridge adds it to the state set and transition map. |
| Storage backend | SQLite, `storage_root/warehouse.db` |
| Schema declaration | No schema change needed (state column is free-form TEXT). |
| Query (count) | `SELECT state, COUNT(*) FROM inventory_state WHERE state='DISPATCH_PENDING' GROUP BY state` |
| Query (list) | `SELECT * FROM inventory_state WHERE state='DISPATCH_PENDING'` |
| Index supporting count query | `idx_invstate_state` already covers it — `warehouse_db.py:148-149`. |
| Index supporting list query | same |
| Used by | not yet wired |
| Frontend tile | not yet wired |
| Notes | Intended to represent goods that have a Proforma issued (`proforma_drafts.status` not in `{draft, cancelled}`, schema at `proforma_invoice_link_db.py:437-456`) but are not yet handed to carrier. Blocked on bridge implementation. |

---

## Stage 2 aggregate: `final_stock`

| Field | Value |
|---|---|
| Status | EXISTS — but the aggregator endpoint that publishes it does NOT exist today |
| Source of truth | `final_stock = count(inventory_state WHERE state='WAREHOUSE_STOCK')`. Direct alias of the WAREHOUSE_STOCK count above. |
| Storage backend | SQLite, `storage_root/warehouse.db` |
| Schema declaration | `warehouse_db.py:136-146` |
| Query (count) | identical to WAREHOUSE_STOCK count query above |
| Query (list) | n/a at aggregate level |
| Index supporting count query | `idx_invstate_state` at `warehouse_db.py:148-149` |
| Index supporting list query | n/a |
| Used by | Will be used by the proposed `/api/v1/inventory/stage2/aggregate` (PENDING — no `routes_inventory.py` exists in tree). |
| Frontend tile | `data-testid="inventory-stage2-final-stock"` (planned). |
| Notes | This is the only Stage 2 bucket whose numerator is wired in production data today. The other four (`samples`, `returns`, `consignment`, `unknown`) have no source table at all. |

---

## Stage 2 aggregate: `samples`

| Field | Value |
|---|---|
| Status | PENDING (null today — no source) |
| Source of truth | Would require a new lifecycle state (`SAMPLE_ALLOCATED` / `SAMPLE_DISPATCHED`) or a separate `sample_releases` table. Neither exists in the repository (verified via Glob/Grep). |
| Storage backend | n/a |
| Schema declaration | none — no `sample_releases` table, no `SAMPLE_*` state constant |
| Query (count) | n/a — would be `SELECT COUNT(*) FROM sample_releases WHERE status='active'` after a future migration |
| Query (list) | n/a |
| Index supporting count query | n/a |
| Index supporting list query | n/a |
| Used by | not wired |
| Frontend tile | `data-testid="inventory-stage2-samples"` (planned, returns `null` until source exists). |
| Notes | Returns `null` rather than `0` so downstream dashboards distinguish "no source" from "zero items". |

---

## Stage 2 aggregate: `returns`

| Field | Value |
|---|---|
| Status | PENDING (null today — no source) |
| Source of truth | Would require a `RETURNED_*` lifecycle state or a returns table. Neither exists. Note: `warehouse_db.ACTION_STATUS_MAP` includes a `RETURN` *movement action* (`warehouse_db.py:52-59`), but that is physical-location bookkeeping only and does not feed `inventory_state`. |
| Storage backend | n/a |
| Schema declaration | none |
| Query (count) | n/a |
| Query (list) | n/a |
| Index supporting count query | n/a |
| Index supporting list query | n/a |
| Used by | not wired |
| Frontend tile | `data-testid="inventory-stage2-returns"` (planned, null). |
| Notes | A future bridge might derive this from `inventory_movement_events.action='RETURN'` joined to an open-vs-closed flag on `inventory_state`, but no such derivation is implemented. |

---

## Stage 2 aggregate: `consignment`

| Field | Value |
|---|---|
| Status | PENDING (null today — no source) |
| Source of truth | Would require a `CONSIGNMENT_*` lifecycle state and/or a `consignment_*` table. Neither exists in the repository. |
| Storage backend | n/a |
| Schema declaration | none |
| Query (count) | n/a |
| Query (list) | n/a |
| Index supporting count query | n/a |
| Index supporting list query | n/a |
| Used by | not wired |
| Frontend tile | `data-testid="inventory-stage2-consignment"` (planned, null). |
| Notes | Consignment behaviour is sometimes loosely associated with `CLIENT_DISPATCHED` for late-Proforma clients, but they are not equivalent and the system does not flag consignment explicitly today. |

---

## Stage 2 aggregate: `unknown`

| Field | Value |
|---|---|
| Status | PENDING (null today — residual) |
| Source of truth | Residual bucket: rows in `inventory_state` whose `state` value is not in the recognized 5-bucket mapping, computed as `total - sum(known buckets)`. |
| Storage backend | SQLite, `storage_root/warehouse.db` |
| Schema declaration | `warehouse_db.py:136-146` |
| Query (count) | `SELECT COUNT(*) FROM inventory_state` minus the known buckets — implementation would live in the future aggregator. |
| Query (list) | `SELECT * FROM inventory_state WHERE state NOT IN (...)` |
| Index supporting count query | `idx_invstate_state` at `warehouse_db.py:148-149` for `WHERE state NOT IN ...`; for the total, no covering index — full table scan, acceptable at current data volume (low thousands of rows). |
| Index supporting list query | same |
| Used by | not wired |
| Frontend tile | `data-testid="inventory-stage2-unknown"` (planned, null until aggregator exists). |
| Notes | Should always be zero in a healthy system; non-zero indicates schema drift (a lifecycle state added in code but not mapped to a bucket). |

---

## Cross-DB integrity caveat

The four databases involved in the Doc 1 v2 lifecycle bridge live in **separate SQLite files** and therefore cannot enforce referential integrity at the SQL layer:

| Logical table | Physical file | Schema declared at |
|---|---|---|
| `inventory_state` | `storage_root/warehouse.db` | `warehouse_db.py:136-146` |
| `reservation_queue` | `storage_root/reservations.db` | `reservation_db.py:89-114` |
| `wfirma_reservation_drafts` | `storage_root/wfirma.db` | `wfirma_db.py:83-98` |
| `proforma_drafts` | `storage_root/proforma_links.db` | `proforma_invoice_link_db.py:437-456` |

SQLite `FOREIGN KEY` constraints (including the existing `reservation_queue.product_code → product_master.product_code` at `reservation_db.py:112-113`) only work within a single attached database file. There is no portable way to declare or enforce `inventory_state.scan_code ↔ reservation_queue.queue_key` (or any other cross-file relation) at the SQL level.

**Consequence for Doc 1 v2 §3:** the bridge invariants that bind `RESERVED_FOR_PROFORMA` rows to live reservation rows, and `DISPATCH_PENDING` rows to live proforma drafts, must be enforced in **worker code** — either in the transition function (`inventory_state_engine.transition()` at `inventory_state_engine.py:207-310`) by validating the partner row exists before allowing the state change, or in a reconciliation worker that scans for orphans. A periodic invariant check (e.g. `inventory_state.state='RESERVED_FOR_PROFORMA' AND scan_code NOT IN attached.reservation_queue.queue_keys`) requires the worker to `ATTACH DATABASE` both files in a read-only session, or to load both tables into memory and diff. There is no transactional path.

Index reality check: every index claim in this document was verified against `grep -n "CREATE INDEX" service/app/services/*.py` (and the equivalent for `CREATE UNIQUE INDEX`). The only index supporting `state`-keyed lookups on `inventory_state` is `idx_invstate_state` at `warehouse_db.py:148-149`; if `RESERVED_FOR_PROFORMA` or `DISPATCH_PENDING` are added without further schema work, that index already covers their count and list queries.
