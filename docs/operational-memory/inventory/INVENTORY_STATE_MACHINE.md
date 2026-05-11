# Inventory State Machine — Architecture v2

**Version:** v2 (supersedes v1)
**Status:** Design doc (read-only inspection; no schema applied)
**Scope:** Lifecycle state per scannable piece + reservation linkage at Estrella PZ Processor

---

## Preamble

- **Architecture:** extend-existing. We build on the live `inventory_state` table and `reservation_queue` table. No greenfield ledger; no parallel state store.
- **Schema choice for the future bridge table (Section 5):** header-lines (parent allocation operation + child piece rows). DESIGN ONLY — no SQL applied, no migration file, no DDL.
- **Allocation types (operator-confirmed):** `PROFORMA`, `DIRECT_DISPATCH`, `SAMPLE`, `CONSIGNMENT`, `DISPLAY`, `REPAIR`, `QUARANTINE`. Excluded by operator: `SALE` (firm sales always route via PROFORMA) and `INTERNAL_TRANSFER` (warehouse location change is metadata only — no inventory_state transition).
- **Allocation status enum:** `DRAFT`, `ACTIVE`, `CANCELLED`, `CONSUMED`, `EXPIRED`.
- **Core principle — single writer:** every state change goes through `inventory_state_engine.transition()` (`service/app/services/inventory_state_engine.py:207`). Every other code site reads from `inventory_state` or computes derived views. There are no parallel writers and no future code path may introduce one.

The inspector report referenced in the brief (`docs/inspection/inventory-proforma-flow-map.md`) was not present on disk at write-time; findings below are grounded directly in the source files cited line-by-line.

---

## Section 1 — `reservation_queue` deep inspection

### Schema (DDL at `service/app/services/reservation_db.py:89-119`)

| Column | Type | Nullability | Source |
|---|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | NOT NULL | `reservation_db.py:90` |
| `queue_key` | TEXT UNIQUE | NOT NULL | `reservation_db.py:91` |
| `batch_id` | TEXT | NOT NULL | `reservation_db.py:92` |
| `client_name` | TEXT | NOT NULL | `reservation_db.py:93` |
| `client_ref` | TEXT DEFAULT `''` | NOT NULL | `reservation_db.py:94` |
| `sales_doc_no` | TEXT DEFAULT `''` | NOT NULL | `reservation_db.py:95` |
| `design_no` | TEXT | NOT NULL | `reservation_db.py:96` |
| `product_code` | TEXT | NOT NULL | `reservation_db.py:97` |
| `qty` | REAL | NOT NULL | `reservation_db.py:98` |
| `unit_price` | REAL DEFAULT `0` | NOT NULL | `reservation_db.py:99` |
| `currency` | TEXT DEFAULT `'USD'` | NOT NULL | `reservation_db.py:100` |
| `status` | TEXT DEFAULT `'pending'` | NOT NULL | `reservation_db.py:101` |
| `wfirma_product_id` | TEXT DEFAULT `''` | NOT NULL | `reservation_db.py:102` |
| `wfirma_customer_id` | TEXT DEFAULT `''` | NOT NULL | `reservation_db.py:103` |
| `wfirma_reservation_id` | TEXT DEFAULT `''` | NOT NULL | `reservation_db.py:104` |
| `blocking_reason` | TEXT DEFAULT `''` | NOT NULL | `reservation_db.py:105` |
| `last_error` | TEXT DEFAULT `''` | NOT NULL | `reservation_db.py:106` |
| `created_at` | TEXT DEFAULT CURRENT_TIMESTAMP | NOT NULL | `reservation_db.py:107` |
| `updated_at` | TEXT DEFAULT CURRENT_TIMESTAMP | NOT NULL | `reservation_db.py:108` |
| `ready_at` | TEXT DEFAULT `''` | NOT NULL | `reservation_db.py:109` |
| `submitted_at` | TEXT DEFAULT `''` | NOT NULL | `reservation_db.py:110` |
| `completed_at` | TEXT DEFAULT `''` | NOT NULL | `reservation_db.py:111` |

**Indexes** (`reservation_db.py:115-118`):

- `idx_reservation_queue_batch` on `batch_id`
- `idx_reservation_queue_status` on `status`
- `idx_reservation_queue_product_code` on `product_code`
- `idx_reservation_queue_client` on `client_name`
- Implicit UNIQUE index on `queue_key` from column constraint.

**Foreign keys** (`reservation_db.py:112-113`):

- `product_code → product_master(product_code)` declared `DEFERRABLE INITIALLY DEFERRED` to permit `product_code='UNMAPPED'` inserts before the master row exists.
- No other FK. **No FK from `reservation_queue` to `inventory_state`** and **no `scan_code` column at all**.

### Writers

| Function | File:line | Scenario |
|---|---|---|
| `upsert_reservation_queue()` | `reservation_db.py:402-455` | Initial insert/update from intake (status defaults to `pending`). |
| `update_queue_status()` | `reservation_db.py:500-515` | Generic status update — used to reject/fail rows. Called at `routes_reservations.py:214`. |
| `update_queue_ready()` | `reservation_db.py:518-533` | `pending → ready` after both product and customer mappings resolve. Called at `reservation_worker.py:292`. |
| `mark_queue_group_submitting()` | `reservation_db.py:536-556` | Atomic `ready → submitting` group lock during wFirma create. |
| `mark_queue_group_created()` | `reservation_db.py:559-577` | `submitting → created`, stamps `wfirma_reservation_id`. Called at `reservation_worker.py:420`. |
| `mark_queue_group_failed()` | `reservation_db.py:580-595` | `submitting → failed` on wFirma error. |

### Readers

| Function | File:line | Use |
|---|---|---|
| `get_reservation_queue_row()` | `reservation_db.py:458-467` | Single-row lookup by id. |
| `list_reservation_queue()` | `reservation_db.py:470-497` | Worker iterates `pending`/`ready`/`submitting` cohorts. |
| `list_product_codes_from_queue()` | `reservation_db.py:598-617` | Worker enumerates distinct product_codes for wFirma sync. |
| `process_ready_reservations()` | `reservation_worker.py:309` | Groups ready rows by `(batch_id, client_name, sales_doc_no)` and creates wFirma reservations. |
| `promote_pending_to_ready()` | `reservation_worker.py:~250-304` | Reads `pending` rows + mapping tables, promotes to `ready`. |

### Structural gap (confirmed)

`reservation_queue.scan_code` **does not exist** (evidence: the DDL block at `reservation_db.py:89-114` lists no such column; the only piece-identity columns are `design_no` and `product_code`, which are sku-level, not piece-level). This is the structural reason a single design with N physical pieces in `inventory_state` cannot be unambiguously linked back to its reserving queue row: a reservation grants `qty=N` against a `product_code`, but the system has no record of *which* N pieces (`scan_code` values) are bound to it. The Section 5 bridge fixes this gap.

### Double-allocation risk (confirmed)

`_check_warehouse_readiness()` at `routes_proforma.py:86-150` does **not** read `inventory_state` at all — it only validates `audit.wfirma_export.wfirma_pz_doc_id` is set and that `pz_rows.json` has no unresolved product_codes / no price conflicts. The actual stock-readiness gate is in the main proforma-preview function via `_state_codes(batch_id)` at `routes_proforma.py:417-454`, but that aggregation is batch-scoped — two different proformas issued back-to-back against the same batch_id both see the same union of `WAREHOUSE_STOCK` scan_codes as available, because no scan_code is marked *consumed-by-an-earlier-reservation* between the two reads. Without a per-scan_code reservation link, double allocation cannot be detected at the readiness gate.

---

## Section 2 — Pieces feeding `inventory_state`

### Schema (`warehouse_db.py:136-153`)

`inventory_state` columns: `id (PK, TEXT uuid)`, `scan_code (TEXT UNIQUE NOT NULL)`, `product_code`, `design_no`, `batch_id`, `state`, `updated_at`, `updated_by`, `note`. UNIQUE on `scan_code` enforces one current state per piece. Companion append-only event log at `inventory_state_events` (`warehouse_db.py:156-168`).

### Seeding path

The seeder is `seed_purchase_transit(batch_id, line_records)` defined at `routes_packing.py:36-116`. For each packing line it computes `pdb._compute_scan_code(line)`, calls `ise.get_state(sc)` to skip already-seeded codes, and calls `ise.transition(scan_code=sc, to_state=ise.PURCHASE_TRANSIT, …)` (`routes_packing.py:56-62`). Failures are caught per-row and logged; the function is best-effort and never raises into the upload flow.

### Call sites

`seed_purchase_transit` is wired in three places:

- `routes_packing.py:371` — main packing upload endpoint after extractor stores lines.
- `routes_packing.py:640` — explicit re-seed endpoint for existing packing_lines.
- `routes_intake.py:485` and `routes_intake.py:921` — intake flows that pre-stage packing data.

### Unique key per piece

`scan_code` (returned by `pdb._compute_scan_code(line)`, `routes_packing.py:51`). The composite identity is `(product_code, design_no, scan_code)` per the engine header (`inventory_state_engine.py:51`), with `scan_code` as the authoritative key.

### Why dev DB has zero rows

The seeder is wired, but it requires (a) a successful packing-list ingest and (b) `pdb._compute_scan_code(line)` returning a non-empty string for at least one row. The empty-row state in the dev DB indicates that no packing upload has been run against this DB instance — not that the seeder is broken or unwired. Test fixtures confirm the seeder works end-to-end (`tests/test_purchase_transit_seeding.py:55`, `tests/test_warehouse_stock_promotion.py:61`).

### Extension recommendation

`seed_purchase_transit()` already lives at the correct extension point — it is the canonical entry that **every** packing-list ingestion path funnels through (three call sites above). No new function is needed. If any future ingest path is added, it must call `seed_purchase_transit()` rather than write to `inventory_state` directly.

---

## Section 3 — Reservation ↔ `inventory_state` bridge

### Current lifecycle of a queue row

`pending` (insert at `reservation_db.py:402-455`) → `ready` (`update_queue_ready` at `reservation_db.py:518`, called from `reservation_worker.py:292` once both mappings resolve) → `submitting` (atomic lock at `reservation_db.py:536`) → `created` (success at `reservation_db.py:559`, called from `reservation_worker.py:420`) or `failed` (`reservation_db.py:580`).

### Proposed lockstep with `inventory_state`

The bridge introduces two new `inventory_state` states slotted into the existing sequence between `WAREHOUSE_STOCK` and `SALES_TRANSIT`:

```
PURCHASE_TRANSIT
  → WAREHOUSE_STOCK
        → RESERVED_FOR_PROFORMA   (new)   when reservation_queue row → 'ready'
              → DISPATCH_PENDING  (new)   when reservation_queue row → 'created'
                    → SALES_TRANSIT      (existing, on invoice issuance)
                          → CLOSED       (existing)
```

These augment but do not replace `DIRECT_DISPATCH_READY` / `CLIENT_DISPATCHED` — those remain the direct-dispatch chain unchanged.

### Single-writer enforcement

The bridge logic lives inside `reservation_worker.update_queue_ready` and `mark_queue_group_created` call sites (`reservation_worker.py:292` and `:420`). Immediately after each `rdb.update_queue_*` call, the worker calls `inventory_state_engine.transition(scan_code, new_state, reason="reservation-bridge", trigger="reservation_ready" | "reservation_created")` for each scan_code bound to that queue row. **No write to `inventory_state` happens inside `reservation_db.py`** — that module continues to own only `reservation_queue` writes. Single writer preserved.

### Required FK / consistency rule

A `reservation_queue` row in status `created` must correspond to **N** `inventory_state` rows in state `DISPATCH_PENDING`, where N is read from `wfirma_reservation_lines` (the line count materialised by `mark_queue_group_created`). This is **not** enforceable as a SQL FK across two SQLite databases (`reservations.db` and `warehouse.db`), so it is enforced by:

1. The bridge writes a `(reservation_queue.id, scan_code)` pair into the new `allocation_pieces` table (Section 5) atomically with each `transition()` call.
2. A read-side invariant check counts `allocation_pieces` rows for the operation_id and compares to `wfirma_reservation_lines` count; mismatch raises an audit-log error but does not block (rollback path is a `CANCELLED` allocation_group).

---

## Section 4 — Direct-dispatch readiness

### The endpoint

`POST /api/v1/inventory-state/mark-direct-dispatch` at `routes_lifecycle.py:469`. Body: `MarkDirectDispatchReq(batch_id, operator, customer_allocation, scan_codes, evidence_note)`. Validates operator + customer_allocation are non-empty (`:491-497`), validates scan_codes non-empty (`:498`), reads customs evidence from `audit.json` (`:502-511`), then iterates scan_codes (`:517`).

### What it calls

For each scan_code it calls `_ise.transition(scan_code=sc, to_state=DIRECT_DISPATCH_READY, …, customs_cleared=True)`. The transition engine (`inventory_state_engine.py:254-268`) enforces evidence on `DIRECT_DISPATCH_READY`: operator must be non-empty, customer_allocation must be non-empty, customs_cleared must be `True`, and a RECEIVE event must already exist in `inventory_movement_events` for that scan_code. Missing items raise a `ValueError` listing each gap.

### Missing UI surface

The endpoint has no UI caller. The New Shipment modal (per orchestrator brief: `dashboard.html:2777-2868`) has no direct-dispatch checkbox. Wiring proposal (DO NOT IMPLEMENT — design only):

- Add a checkbox `Mark for direct dispatch (skip warehouse)` to the modal.
- When checked, after the shipment is created the dashboard POSTs to `/api/v1/inventory-state/mark-direct-dispatch` with the scan_codes returned from intake, operator = current logged-in user, customer_allocation = the client_name from the new-shipment form.
- The customs-clearance evidence will arrive later in the lifecycle; the endpoint already returns 400 with `missing` list if evidence is absent, so the UI shows that as a deferred action ("Direct dispatch pending customs clearance").

### Do not delete

The endpoint is not orphaned in a removable sense — it is the future API for the direct-dispatch path. It is fully evidence-gated and idempotent (`:475` documents idempotency). Removal would force re-implementation of the same evidence contract.

---

## Section 5 — Header-lines allocation table (DESIGN ONLY)

No SQL applied. No migration file. No DDL written to any `.sql` or `.py.draft`. The schema below is the agreed shape for future implementation.

### Parent: `allocation_groups`

```
allocation_groups
  operation_id           TEXT PRIMARY KEY              -- uuid4
  allocation_type        TEXT NOT NULL                 -- enum: PROFORMA, DIRECT_DISPATCH,
                                                       --       SAMPLE, CONSIGNMENT,
                                                       --       DISPLAY, REPAIR, QUARANTINE
  allocated_by           TEXT NOT NULL                 -- user_id or 'system'
  timestamp              TEXT NOT NULL                 -- ISO8601 UTC
  status                 TEXT NOT NULL                 -- enum: DRAFT, ACTIVE, CANCELLED,
                                                       --       CONSUMED, EXPIRED
  linked_reservation_id  TEXT NULL                     -- reservation_queue.id (PROFORMA)
                                                       -- or wfirma_reservation_drafts.id;
                                                       -- NULL for SAMPLE/DISPLAY/REPAIR/etc.
  notes                  TEXT NOT NULL DEFAULT ''
```

Indexes: `idx_alloc_groups_status (status)`, `idx_alloc_groups_type (allocation_type)`, `idx_alloc_groups_reservation (linked_reservation_id) WHERE linked_reservation_id IS NOT NULL`.

### Child: `allocation_pieces`

```
allocation_pieces
  line_id        TEXT PRIMARY KEY                      -- uuid4
  operation_id   TEXT NOT NULL                         -- FK → allocation_groups(operation_id)
  scan_code      TEXT NOT NULL                         -- FK → inventory_state(scan_code)
  line_status    TEXT NOT NULL                         -- enum: PENDING, CONFIRMED, CANCELLED
```

Indexes: `idx_alloc_pieces_operation (operation_id)`, `idx_alloc_pieces_scan (scan_code)`.

### Double-allocation invariant (pseudo-SQL, design-only)

```
-- At most one ACTIVE confirmed allocation per scan_code:
CREATE UNIQUE INDEX uq_one_active_allocation_per_piece
  ON allocation_pieces (scan_code)
  WHERE line_status = 'CONFIRMED'
    AND operation_id IN (
      SELECT operation_id FROM allocation_groups WHERE status = 'ACTIVE'
    );
```

SQLite does not support subqueries in partial-index predicates, so the production implementation will enforce this in the bridge code (`reservation_worker` / proforma confirmer) inside the same transaction that writes the row — same single-writer discipline as `inventory_state`.

---

## Section 6 — Migration plan (extend-existing)

### Trivial (no change or one-line addition)

- `seed_purchase_transit()` at `routes_packing.py:36` — unchanged. Already the canonical seeder.
- `inventory_state_engine.transition()` at `inventory_state_engine.py:207` — adds two new entries to `LEGAL_TRANSITIONS` (`inventory_state_engine.py:88`) and to `DEFAULT_TRIGGER` (`:99`); same shape as existing entries. No structural change to the function body.
- `STATES` frozenset at `inventory_state_engine.py:81-85` — append `RESERVED_FOR_PROFORMA` and `DISPATCH_PENDING`.
- `PROFORMA_ELIGIBLE_STATES` at `inventory_state_engine.py:113-115` — no change. `RESERVED_FOR_PROFORMA` is **not** eligible for a *new* proforma (that's the point of the reservation).

### Rewrite

- `reservation_worker.promote_pending_to_ready()` (around `reservation_worker.py:292`) — after the `rdb.update_queue_ready` call, add the bridge step that resolves the scan_codes for the `product_code` (from `inventory_state` filtered by `state='WAREHOUSE_STOCK'` and `batch_id`), creates an `allocation_groups` row with `allocation_type='PROFORMA'` and `status='DRAFT'`, writes `allocation_pieces` rows, and calls `ise.transition()` for each scan_code into `RESERVED_FOR_PROFORMA`. Scope: ~40 LOC.
- `reservation_worker.process_ready_reservations()` at `reservation_worker.py:309-440` — on the success branch (`reservation_worker.py:419-435`) flip the linked `allocation_groups.status` from `DRAFT` to `ACTIVE`, mark `allocation_pieces.line_status='CONFIRMED'`, and call `ise.transition()` per scan_code to `DISPATCH_PENDING`. Scope: ~30 LOC.
- `routes_proforma._check_warehouse_readiness()` at `routes_proforma.py:86` and the in-route gate at `routes_proforma.py:417-454` — change the stock-eligibility check from set-membership on `WAREHOUSE_STOCK` union to subtracting `scan_codes already in an ACTIVE allocation_groups`. Scope: ~20 LOC of new helper + one-line use.

### Blocked (operator design call required before touching)

- The two-state move `RESERVED_FOR_PROFORMA → SALES_TRANSIT` must be triggered by the proforma → sales-invoice promotion. The current invoice-issuance code path was not inspected in this pass; operator must confirm the trigger point (invoice creation event vs. wFirma webhook).
- Cancellation semantics: when a reservation row goes `failed` (`reservation_db.py:580`), the bridge must roll back the matching `allocation_groups` to `CANCELLED` and call `ise.transition()` back from `RESERVED_FOR_PROFORMA` to `WAREHOUSE_STOCK`. This reverse transition is not currently in `LEGAL_TRANSITIONS` — operator must approve the directionality.

### Data migration

- `inventory_state` rows in dev DB: **0** (confirmed). Migration is trivial: re-run any packing upload, the seeder fills the table.
- New tables `allocation_groups` + `allocation_pieces`: empty on creation. No backfill needed; the bridge starts capturing on first reservation after deploy.

### Test fixture impact

Per the orchestrator brief, `service/tests/` contains zero raw state-string literals. Confirmed by spot-checks: tests import constants (`from app.api.routes_packing import seed_purchase_transit`, `inventory_state_engine as ise`) rather than hard-code state names. Adding new states will not require fixture rewrites.

---

## Section 7 — Phase 4 implementation order (operator-confirmed override)

### Task 1 — `GET /api/v1/inventory/state/{batch_id}` (batch-level read)

- **Endpoint contract**
  - Request: path param `batch_id`. No body.
  - Response 200: `{ "batch_id": str, "counts": {state: int}, "pieces": [{scan_code, product_code, design_no, state, updated_at}] }` — `counts` derived from `ise.count_by_state(batch_id)` (`inventory_state_engine.py:177`); `pieces` from a new helper joining `inventory_state` rows for the batch.
  - Response 404 if no rows exist for the batch_id.
- **Why first:** read-only, no writers; depends on no other task. Validates that seeding actually happened for a given shipment before any UI is built.
- **Tests:** empty batch returns 404; seeded batch returns expected counts; multi-state batch returns disjoint counts summing to total.
- **Approvals:** none — read-only.

### Task 2 — UI: shipment detail batch state strip

- Wires Task 1. Renders a per-state badge row (PURCHASE_TRANSIT / WAREHOUSE_STOCK / DIRECT_DISPATCH_READY / CLIENT_DISPATCHED / SALES_TRANSIT / CLOSED) with counts on the shipment detail page.
- **Tests:** Playwright snapshot of the strip for a seeded fixture batch; count text matches API response.
- **Approvals:** UX lead for visual treatment.

### Task 3 — `GET /api/v1/inventory/pieces/{piece_id}` (per-piece drawer source)

- **Endpoint contract**
  - Request: path param `piece_id` (= scan_code).
  - Response 200: `{ scan_code, product_code, design_no, batch_id, state, updated_at, updated_by, note, history: [{from_state, to_state, trigger, occurred_at, operator, note}] }` — composes `ise.get_state()` (`inventory_state_engine.py:134`) + `ise.get_history()` (`:146`).
  - Response 404 if scan_code unknown.
- **Why third:** Task 2's badges are clickable into the drawer; the drawer needs this data.
- **Tests:** unknown scan_code returns 404; history ordering is by `occurred_at` ascending; concurrent transition followed by read returns latest state.
- **Approvals:** none — read-only.

### Task 4 — UI: piece detail drawer

- Wires Task 3. Right-side drawer opened on click from the batch strip or a future piece list. Shows current state, full history timeline, and (in a later task) action buttons.
- **Tests:** drawer opens with correct piece, history renders in order.
- **Approvals:** UX lead.

### Task 5 — `POST /api/v1/inventory/pieces/{piece_id}/location` (move stock; metadata only)

- **Endpoint contract**
  - Request: `{ "to_location": str, "operator": str, "note": str }`.
  - Response 200: updated piece row with new `location` field (requires adding a `location` column to `inventory_state` — design only, not in this doc).
  - **No state transition fired.** Operator-confirmed: moving stock is location metadata, not a lifecycle change.
- **Why last:** introduces a write, requires security review (operator authentication + audit-log discipline), and depends on Task 3's read API for the drawer's confirmation refresh.
- **Tests:** location updates; no `inventory_state_events` row is appended (move-stock writes a separate `inventory_location_events` audit, design-only).
- **Approvals:** **gated** on security review (operator auth) and operator sign-off on the location-events audit shape.

---

## Cross-cutting notes

- All FK/consistency invariants that cannot be expressed as a SQLite FK (because `reservation_queue` lives in `reservations.db` and `inventory_state` lives in `warehouse.db`) are enforced inside the bridge code under the existing `_lock` (`inventory_state_engine.py:117`) plus the worker's transactional update boundary.
- `inventory_state_engine.transition()` already serialises all writes via `_lock` + a per-call SQLite transaction (`inventory_state_engine.py:235`). The bridge inherits this serialisation by calling `transition()` rather than touching the table directly.
- The seven allocation types map onto allocation_groups, not onto distinct inventory_state states. The state machine remains compact: a piece in `RESERVED_FOR_PROFORMA` is reserved against *some* allocation type, and the operation_id in `allocation_groups` records which one. This keeps `LEGAL_TRANSITIONS` from exploding.
