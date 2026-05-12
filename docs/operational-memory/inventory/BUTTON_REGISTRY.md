# Inventory Button Registry — Doc 2 v1 (Issue #27 refresh, 2026-05-13)

**Architecture reference:** Doc 1 v2 — `INVENTORY_STATE_MACHINE.md` (extend-existing; single writer = `inventory_state_engine.transition()`; header-lines allocation table is DESIGN ONLY).

> **Issue #27 refresh note (2026-05-13).** Doc 2 v1 was authored before PR #17 / #18 (Sample-out live) and PR #22 (Returns lifecycle live). The button-row TODO/PARTIAL labels below are preserved as design-intent history; for **current operational status** read the on-main code (see source-of-truth pointers below). Buttons #2 (Move stock), #5 (Sample out), #6 (Sample return), #8 (Goods return) and #9 (Return to producer) are now LIVE in the piece drawer per `dashboard.html:1782` (status banner: *"Move-stock, Sample-out, Sample-return, Return-from-client, Return-to-producer, and Return-from-producer are live"*). The five "disabled-button" placeholder rows at `dashboard.html:1329-1343` referenced throughout this doc **no longer exist** — those placeholders were replaced by live state-gated forms in the piece drawer (Phase B.1 block `dashboard.html:2027+`, Phase B.2 block `dashboard.html:2151+` and `:2217+`).

**Source-of-truth files cited in this registry (line numbers refreshed to on-main HEAD `3670e2c`, 2026-05-13):**
- `service/app/services/inventory_state_engine.py` — state constants `:74-92` (includes `SAMPLE_OUT` at `:83`, `RETURNED_FROM_CLIENT` at `:91`, `RETURNED_TO_PRODUCER` at `:92` — added by PR #17/#18 and PR #22); `STATES` frozenset at `:94`; `LEGAL_TRANSITIONS` at `:132`; `PROFORMA_ELIGIBLE_STATES` at `:197`; `_lock` at `:201`; `get_state` at `:218`; `get_history` at `:230`; `list_by_state` at `:243`; `count_by_state` at `:261`; `transition()` at `:291`.
- `service/app/api/routes_inventory.py` — router prefix `/api/v1/inventory`; live endpoints include `GET /stage2/aggregate`, `GET /pieces/{piece_id}` (`:57`), `GET /state/{batch_id}` (`:74`).
- `service/app/api/routes_inventory_writes.py` — `POST /pieces/{id}/location` (Move stock, live).
- `service/app/api/routes_inventory_sample.py` — `POST /pieces/{id}/sample-out`, `POST /pieces/{id}/sample-return` (live, PR #17/#18).
- `service/app/api/routes_inventory_returns.py` — `POST /pieces/{id}/return-from-client`, `POST /pieces/{id}/return-to-producer`, `POST /pieces/{id}/return-from-producer` (live, PR #22).
- `service/app/api/routes_lifecycle.py:469` — `POST /api/v1/lifecycle/inventory-state/mark-direct-dispatch` (write half of direct-dispatch).
- `service/app/api/routes_packing.py:723` — dev-only `POST /inventory-state/seed-batch`.
- `service/app/services/reservation_db.py:89-114` — `reservation_queue` schema.
- `service/app/static/dashboard.html` — `InventoryPage` at `:1286`; live action banner at `:1782`; Phase B.1 sample-out drawer block at `:2027+`; Phase B.2 return-from-client drawer at `:2151+`; Phase B.2 return-to-producer drawer at `:2217+`; Stage 2 tile grid at `:1700-1702` (samples / returns / consignment hints inline at those lines).

**Allocation model (DESIGN ONLY, Doc 1 v2 §5):**
- Types: `PROFORMA`, `DIRECT_DISPATCH`, `SAMPLE`, `CONSIGNMENT`, `DISPLAY`, `REPAIR`, `QUARANTINE`.
- Status enum: `DRAFT`, `ACTIVE`, `CANCELLED`, `CONSUMED`, `EXPIRED`.
- No `SALE`, no `INTERNAL_TRANSFER`.
- No `inventory_allocations` table has been built. Buttons #5 / #6 / #8 / #9 below shipped against the `inventory_state` state machine directly (no allocation table); button #7 still depends on the table.

**Lifecycle states (current — `STATES` frozenset, `inventory_state_engine.py:94`):**
`PURCHASE_TRANSIT`, `WAREHOUSE_STOCK`, `DIRECT_DISPATCH_READY`, `CLIENT_DISPATCHED`, `SALES_TRANSIT`, `CLOSED`, **`SAMPLE_OUT`** (PR #17/#18), **`RETURNED_FROM_CLIENT`** (PR #22), **`RETURNED_TO_PRODUCER`** (PR #22) — 9 states total. Consignment / quarantine sub-states are still NOT in `STATES`; only consignment (button #7) is genuinely design-only today.

**Move stock is location-metadata only.** It updates physical location in `warehouse_db` movement events without calling `transition()`. No state change. (Live since PR #17/#18.)

---

## Phase 4 prerequisite (NOT a row in this registry)

**`GET /api/v1/inventory/state/{batch_id}`** — batch-level read endpoint.

- Inspector recommendation §9; documented in Doc 1 v2 §7.
- Returns disjoint counts per state + per-line `[{scan_code, product_code, design_no, state, updated_at}]` rows for the batch.
- Backed by `inventory_state_engine.count_by_state(batch_id)` and `list_by_state(state, batch_id)` (already exists, lines 159–194).
- Status: **TODO** — wrap existing engine functions in a route under `routes_inventory.py`.
- Why it's a prerequisite: every button below that scopes to a batch needs this read. Phase 4 task #1; UI strip wiring (task #2) consumes it; View stock detail (button #1, task #3) drills from it.

---

## Phase 4 order (operator override from spec)

1. `GET /api/v1/inventory/state/{batch_id}` (prerequisite above)
2. UI strip wires #1
3. **Button #1 — View stock detail** (overnight)
4. UI piece drawer
5. **Button #2 — Move stock** (overnight; security-review gated)

Phase 6 design stubs: buttons #5–#9. Buttons #3 and #4 are overnight-feasible reads.

---

## 1. View stock detail

| Field | Value |
|---|---|
| Page | Inventory page + Shipment detail (Warehouse tab) |
| UI element | Row click on `inventory-attention-row` (`dashboard.html:1387`); per-scan row in piece drawer (TODO) |
| Action type | READ |
| Risk class | Risk-1 |
| Endpoint (proposed) | `GET /api/v1/inventory/scan/{scan_code}` |
| Auth | `Depends(require_api_key)` |
| Request payload | n/a |
| Response shape | `{ scan_code, product_code, design_no, batch_id, state, updated_at, updated_by, note, history: [{from_state, to_state, trigger, occurred_at, operator, note}] }` |
| State transition triggered | none |
| Data source | `inventory_state` + `inventory_state_events` (via `get_state` and `get_history`, `inventory_state_engine.py:134`, `:146`) |
| Dependencies | Phase 4 prerequisite (batch read). None other. |
| Backend status | PARTIAL — engine functions exist; HTTP route TODO |
| Frontend status | PARTIAL — `inventory-attention-row` exists at `dashboard.html:1387`; per-scan drawer TODO |
| Tests required | engine returns full history; 404 on unknown scan_code; auth required; idempotent re-read |
| Overnight feasibility | YES |
| Operator approval needed | NO |
| Execution route required | NO |
| Idempotency rule | N/A (read) |
| Rollback / reversal path | N/A (read) |
| Notes | Wraps `get_state()` + `get_history()`. Pure read. No new tables. |

---

## 2. Move stock

| Field | Value |
|---|---|
| Page | Inventory page (button `inventory-preview-action-move_stock`, `dashboard.html:1331`) + Shipment detail |
| UI element | Currently disabled button `data-testid="inventory-preview-action-move_stock"` at `dashboard.html:1330-1343` |
| Action type | WRITE (metadata only — no state transition) |
| Risk class | Risk-1 |
| Endpoint (proposed) | `POST /api/v1/inventory/move` |
| Auth | `Depends(require_api_key)` |
| Request payload | `{ scan_codes: [str], from_location: str, to_location: str, operator: str, note: str, idempotency_key: str }` |
| Response shape | `{ moved: [{scan_code, from_location, to_location, event_id}], rejected: [{scan_code, reason}] }` |
| State transition triggered | **none** — lifecycle state unchanged. Writes only `inventory_movement_events` (action=`MOVE`). |
| Data source | `inventory_movement_events` table (warehouse_db) |
| Dependencies | View stock detail (#1) for selection UX |
| Backend status | TODO |
| Frontend status | PARTIAL — disabled button placeholder at `dashboard.html:1331` |
| Tests required | metadata-only (no `inventory_state` row touched); idempotency_key dedupe; rejected reasons (scan_code unknown / wrong batch); audit event written |
| Overnight feasibility | YES (security-review gated — operator confirmed) |
| Operator approval needed | YES — confirm "Move stock never triggers state transitions" before merge |
| Execution route required | NO (Risk-1 metadata-only write; no customs/posting effect) |
| Idempotency rule | `idempotency_key` → return previous result if seen; same `(scan_code, to_location, operator)` within 60s also a no-op |
| Rollback / reversal path | Post the inverse `MOVE` event (to → from). No state to unwind. |
| Notes | Must NOT call `inventory_state_engine.transition()`. Single writer rule preserved — `transition()` stays the only lifecycle writer; this writes movement metadata only. |

---

## 3. Direct dispatch visibility

| Field | Value |
|---|---|
| Page | Inventory page + Shipment detail |
| UI element | Filter chip / lifecycle tile for `DIRECT_DISPATCH_READY` and `CLIENT_DISPATCHED` |
| Action type | READ |
| Risk class | Risk-1 |
| Endpoint (proposed) | `GET /api/v1/inventory/direct-dispatch?batch_id={id}` (read half) |
| Auth | `Depends(require_api_key)` |
| Request payload | n/a |
| Response shape | `{ batch_id, ready: [{scan_code, customer_allocation, updated_at}], dispatched: [{scan_code, customer_allocation, updated_at}], counts: {ready: int, dispatched: int} }` |
| State transition triggered | none (read). Write half exists separately at `routes_lifecycle.py:469`. |
| Data source | `inventory_state` filtered by `state IN ('DIRECT_DISPATCH_READY','CLIENT_DISPATCHED')` (via `list_by_state`) |
| Dependencies | Phase 4 prerequisite |
| Backend status | PARTIAL — `list_by_state(DIRECT_DISPATCH_READY, batch_id)` and `list_by_state(CLIENT_DISPATCHED, batch_id)` exist; HTTP route TODO. Write counterpart `POST /api/v1/lifecycle/inventory-state/mark-direct-dispatch` at `routes_lifecycle.py:469`. |
| Frontend status | TODO — lifecycle tile grid at `dashboard.html:1348-1364` does not currently surface direct-dispatch buckets |
| Tests required | empty batch returns `[]` + zero counts; auth required; counts match per-row arrays |
| Overnight feasibility | YES (read + UI wiring; the write was shipped already) |
| Operator approval needed | NO |
| Execution route required | NO |
| Idempotency rule | N/A (read) |
| Rollback / reversal path | N/A (read). Write reversal would require a new transition not currently in `LEGAL_TRANSITIONS` — out of scope for the read button. |
| Notes | `routes_lifecycle.py:469` write is technically orphaned from any inventory-page button today — this read endpoint + a confirm-dialog action in the piece drawer would close that loop, but is not part of this button row. |

---

## 4. Inventory event timeline

| Field | Value |
|---|---|
| Page | Shipment detail (Warehouse tab) + per-scan drawer |
| UI element | Timeline panel triggered from View stock detail (#1) |
| Action type | READ |
| Risk class | Risk-1 |
| Endpoint (proposed) | `GET /api/v1/inventory/scan/{scan_code}/events` (or fold into #1's response) |
| Auth | `Depends(require_api_key)` |
| Request payload | n/a |
| Response shape | `{ scan_code, events: [{id, from_state, to_state, trigger, occurred_at, operator, note}] }` ordered by `occurred_at` ASC |
| State transition triggered | none |
| Data source | `inventory_state_events` (via `get_history`, `inventory_state_engine.py:146`) |
| Dependencies | Phase 4 prerequisite; can ship inline with #1 |
| Backend status | PARTIAL — engine `get_history` exists; route TODO |
| Frontend status | TODO |
| Tests required | append-only ordering; empty list on unknown scan; auth required |
| Overnight feasibility | YES |
| Operator approval needed | NO |
| Execution route required | NO |
| Idempotency rule | N/A (read) |
| Rollback / reversal path | N/A — events are append-only by design (no UPDATE/DELETE on `inventory_state_events`) |
| Notes | Could be merged into the View-stock-detail response (#1) as a `history` field; separate endpoint preferred if list grows large. |

---

## 5. Sample out

| Field | Value |
|---|---|
| Page | Inventory page (disabled button `inventory-preview-action-sample_out`, `dashboard.html:1332`) + Shipment detail |
| UI element | Disabled button at `dashboard.html:1332`; intended drawer trigger from View stock detail |
| Action type | WRITE |
| Risk class | Risk-2 (single-state transition, low blast radius; no customs effect) |
| Endpoint (proposed) | `POST /api/v1/inventory/sample/out` |
| Auth | `Depends(require_api_key)` |
| Request payload | `{ scan_codes: [str], client_name: str, expected_return_date: str (ISO), operator: str, note: str, idempotency_key: str }` |
| Response shape | `{ allocations: [{scan_code, allocation_id, type: "SAMPLE", status: "ACTIVE"}], rejected: [{scan_code, reason}] }` |
| State transition triggered | **DESIGN ONLY** — no `SAMPLE_OUT` state exists in `STATES` (engine line 74–85). Either: (a) add a new state + transition to engine, or (b) keep lifecycle at `WAREHOUSE_STOCK` and represent sample status only in the future `inventory_allocations` table. BLOCKED — operator decision: which model. |
| Data source | future `inventory_allocations` (DESIGN ONLY, Doc 1 v2 §5); status `ACTIVE`, type `SAMPLE` |
| Dependencies | inventory_allocations table; View stock detail (#1) |
| Backend status | TODO (design stub) |
| Frontend status | PARTIAL — disabled button at `dashboard.html:1332` |
| Tests required | scan must be in `WAREHOUSE_STOCK`; double-sample-out rejected (allocation already `ACTIVE`); idempotency; client_name required |
| Overnight feasibility | NO — Phase 6 design stub |
| Operator approval needed | YES — pick the state-vs-allocation model above |
| Execution route required | YES (operator-explicit; downstream customer/financial linkage) |
| Idempotency rule | `idempotency_key` → return existing allocation_id; replays must not double-allocate |
| Rollback / reversal path | Cancel the allocation (status → `CANCELLED`); Sample return (#6) is the normal "completed" path (`CONSUMED`) |
| Notes | Must reconcile with the engine's single-writer rule: any new lifecycle state requires a `transition()` extension; an allocation-only approach leaves `inventory_state` untouched and is closer to extend-existing. |

---

## 6. Sample return

| Field | Value |
|---|---|
| Page | Inventory page (disabled button `inventory-preview-action-sample_return`, `dashboard.html:1333`) + Shipment detail |
| UI element | Disabled button at `dashboard.html:1333` |
| Action type | WRITE |
| Risk class | Risk-2 |
| Endpoint (proposed) | `POST /api/v1/inventory/sample/return` |
| Auth | `Depends(require_api_key)` |
| Request payload | `{ allocation_id: str, scan_codes: [str], outcome: "returned"\|"sold"\|"lost", operator: str, note: str, idempotency_key: str }` |
| Response shape | `{ allocation_id, new_status, scan_outcomes: [{scan_code, returned_to_state}] }` |
| State transition triggered | DESIGN ONLY — depends on Sample-out (#5) model decision. If allocation-only: status `ACTIVE → CONSUMED` (returned), or `→ CANCELLED` (lost). If new state added: `SAMPLE_OUT → WAREHOUSE_STOCK` (returned). BLOCKED — operator decision tied to #5. |
| Data source | future `inventory_allocations` |
| Dependencies | Sample out (#5) |
| Backend status | TODO (design stub) |
| Frontend status | PARTIAL — disabled button at `dashboard.html:1333` |
| Tests required | only matching `allocation_id` for client; partial return (subset of scans); `outcome=sold` requires invoice linkage check |
| Overnight feasibility | NO — Phase 6 design stub |
| Operator approval needed | YES — outcome enum + sold-path linkage |
| Execution route required | YES |
| Idempotency rule | `idempotency_key`; replaying same outcome on a `CONSUMED` allocation is a no-op |
| Rollback / reversal path | If outcome was set wrong: corrective allocation event (audit-trail forward, not destructive) |
| Notes | "sold" outcome should not cross-write to sales invoicing here; the sales flow remains separate. |

---

## 7. Consignment flows

| Field | Value |
|---|---|
| Page | Inventory page + Shipment detail |
| UI element | Stage 2 `consignment` tile at `dashboard.html:1446`; no dedicated button today (Doc 1 v2 §5 introduces it) |
| Action type | WRITE (multiple sub-actions: send, receive-back, sell-from-consignment) |
| Risk class | Risk-3 — state transition + reservation_queue update + external client effect |
| Endpoint (proposed) | `POST /api/v1/inventory/consignment/send`, `POST /api/v1/inventory/consignment/return`, `POST /api/v1/inventory/consignment/convert-to-sale` |
| Auth | `Depends(require_api_key)` |
| Request payload | send: `{scan_codes, client_name, expected_return_date, terms, operator, note, idempotency_key}`; return / convert: `{allocation_id, scan_codes, operator, note, idempotency_key}` |
| Response shape | `{ allocation_id, type: "CONSIGNMENT", status, scan_outcomes: [...] }` |
| State transition triggered | DESIGN ONLY — no consignment state in `STATES`. Same model decision as #5. Convert-to-sale must coordinate with `reservation_queue` (`reservation_db.py:89`) and possibly the existing `WAREHOUSE_STOCK → SALES_TRANSIT` transition (engine line 91). BLOCKED — operator decision. |
| Data source | future `inventory_allocations` + `reservation_queue` (`reservation_db.py:89-114`) |
| Dependencies | Sample out (#5) pattern decision; reservation_queue coupling design |
| Backend status | TODO (design stub) |
| Frontend status | TODO — Stage 2 tile exists for visibility only |
| Tests required | send creates ACTIVE allocation; return reverts state; convert-to-sale creates a single `reservation_queue` row, not two; idempotency across all three sub-actions; title-retention reflected in any export |
| Overnight feasibility | NO — Phase 6 design stub |
| Operator approval needed | YES — terms model, title-retention semantics, reservation_queue coupling |
| Execution route required | YES |
| Idempotency rule | `idempotency_key` per sub-action; convert-to-sale must dedupe against `reservation_queue.queue_key` |
| Rollback / reversal path | Pre-conversion: status → `CANCELLED`. Post-conversion: cancellation goes through the existing sales/proforma reversal path, not here. |
| Notes | Highest-coupling of the four allocation-type buttons; do not start until #5/#6 model is locked. |

---

## 8. Goods return

| Field | Value |
|---|---|
| Page | Inventory page (disabled button `inventory-preview-action-goods_return`, `dashboard.html:1334`) + Shipment detail |
| UI element | Disabled button at `dashboard.html:1334`; Stage 2 `returns` tile at `dashboard.html:1445` |
| Action type | WRITE |
| Risk class | Risk-3 — state transition + possible reservation_queue reversal + RMA/debit-note implications |
| Endpoint (proposed) | `POST /api/v1/inventory/goods-return` |
| Auth | `Depends(require_api_key)` |
| Request payload | `{ scan_codes: [str], reason: "client_return"\|"defect"\|"wrong_item", originating_sales_doc: str, operator: str, note: str, idempotency_key: str }` |
| Response shape | `{ allocation_id, status, scan_outcomes: [{scan_code, returned_to_state}], rma_ref: str\|null }` |
| State transition triggered | DESIGN ONLY — closest existing path is reverting `CLOSED → WAREHOUSE_STOCK` or `CLIENT_DISPATCHED → WAREHOUSE_STOCK`, neither of which is in `LEGAL_TRANSITIONS` (engine line 88–96). Engine would need a new legal transition + trigger, OR returns are modelled as a new allocation type `RETURN` that does not unwind state. BLOCKED — operator decision. |
| Data source | future `inventory_allocations` (type `RETURN`-equivalent — note Doc 1 v2 enumerates `REPAIR`, `QUARANTINE` but not `RETURN`; clarify); possibly `reservation_queue` |
| Dependencies | invoice / sales-doc lookup for `originating_sales_doc` validation |
| Backend status | TODO (design stub) |
| Frontend status | PARTIAL — disabled button at `dashboard.html:1334` |
| Tests required | reason enum enforced; originating_sales_doc must exist; idempotency; debit-note hand-off (if any) is logged but not auto-issued |
| Overnight feasibility | NO — Phase 6 design stub |
| Operator approval needed | YES — pick the model (state-reversal vs new allocation type) and confirm whether Doc 1 v2 §5 needs a `RETURN` allocation type added |
| Execution route required | YES |
| Idempotency rule | `idempotency_key`; same `(originating_sales_doc, scan_codes)` within window collapses to one record |
| Rollback / reversal path | Cancel the return allocation; if state was reverted, re-dispatch via the normal path |
| Notes | Doc 1 v2 §5 allocation enum lacks `RETURN`. Either map returns to `QUARANTINE` (received-pending-disposition) or extend the enum — operator decision. |

---

## 9. Return to producer

| Field | Value |
|---|---|
| Page | Inventory page (disabled button `inventory-preview-action-return_prod`, `dashboard.html:1335`) + Shipment detail |
| UI element | Disabled button at `dashboard.html:1335` |
| Action type | WRITE |
| Risk class | Risk-4 — may require customs documentation (re-export); affects posting state |
| Endpoint (proposed) | `POST /api/v1/inventory/return-to-producer` |
| Auth | `Depends(require_api_key)` |
| Request payload | `{ scan_codes: [str], producer_id: str, reason: "defect"\|"wrong_spec"\|"surplus", customs_required: bool, operator: str, note: str, idempotency_key: str }` |
| Response shape | `{ allocation_id, status, customs_doc_ref: str\|null, scan_outcomes: [...] }` |
| State transition triggered | DESIGN ONLY — closest is treating scans as terminal-out via a new legal transition `WAREHOUSE_STOCK → CLOSED` with `trigger=returned_to_producer`, OR as a `QUARANTINE` allocation that blocks any further Proforma. Customs implication: if `customs_required=True`, a re-export document path must run before the lifecycle write commits. BLOCKED — operator decision + customs gate design. |
| Data source | future `inventory_allocations` (type `QUARANTINE` or new); customs evidence in `audit.json` similar to direct-dispatch's customs gate at `routes_lifecycle.py:502-511` |
| Dependencies | producer master data; customs-doc generation hook |
| Backend status | TODO (design stub) |
| Frontend status | PARTIAL — disabled button at `dashboard.html:1335` |
| Tests required | customs_required=True with missing customs evidence returns 400 (mirror of `_customs_cleared_from_audit` pattern); producer_id must exist; idempotency; scans removed from Proforma-eligible pool |
| Overnight feasibility | NO — Phase 6 design stub |
| Operator approval needed | YES — customs-doc workflow, terminal-state vs. allocation model, blocking effect on `PROFORMA_ELIGIBLE_STATES` (engine line 113–115) |
| Execution route required | YES — Risk-4, customs touch |
| Idempotency rule | `idempotency_key`; replay returns existing `customs_doc_ref` |
| Rollback / reversal path | Pre-shipment: cancel allocation, status → `CANCELLED`. Post-shipment: irreversible; would require an inbound goods receipt as a new event. |
| Notes | Highest risk class of the nine. Customs-gate pattern from `mark-direct-dispatch` (`routes_lifecycle.py:469-511`) is the closest existing template — reuse the audit.json clearance shape rather than inventing one. |

---

## Summary index — DESIGN-INTENT history

| # | Button | Risk | Overnight | Backend | Frontend |
|---|---|---|---|---|---|
| 1 | View stock detail | 1 | YES | PARTIAL | PARTIAL |
| 2 | Move stock | 1 | YES (security-gated) | TODO | PARTIAL (disabled) |
| 3 | Direct dispatch visibility | 1 | YES | PARTIAL | TODO |
| 4 | Inventory event timeline | 1 | YES | PARTIAL | TODO |
| 5 | Sample out | 2 | NO (Phase 6) | TODO | PARTIAL (disabled) |
| 6 | Sample return | 2 | NO (Phase 6) | TODO | PARTIAL (disabled) |
| 7 | Consignment flows | 3 | NO (Phase 6) | TODO | TODO |
| 8 | Goods return | 3 | NO (Phase 6) | TODO | PARTIAL (disabled) |
| 9 | Return to producer | 4 | NO (Phase 6) | TODO | PARTIAL (disabled) |

## Summary index — ON-MAIN status (Issue #27 refresh, 2026-05-13)

| # | Button | Risk | Backend | Frontend | Live on main? |
|---|---|---|---|---|---|
| 1 | View stock detail | 1 | LIVE — `GET /api/v1/inventory/pieces/{piece_id}` (`routes_inventory.py:57`) | LIVE — piece drawer | **YES** (Issue #27 acceptance criterion: endpoint list update) |
| 2 | Move stock | 1 | LIVE — `POST /pieces/{id}/location` (`routes_inventory_writes.py`) | LIVE — piece drawer form | **YES** (banner at `dashboard.html:1782`) |
| 3 | Direct dispatch visibility | 1 | PARTIAL — `GET /api/v1/inventory/state/{batch_id}` is live (`routes_inventory.py:74`); explicit `/direct-dispatch` filter endpoint still TODO | TODO | PARTIAL |
| 4 | Inventory event timeline | 1 | LIVE — `GET /pieces/{piece_id}` returns history via `get_history()` (`inventory_state_engine.py:230`) | LIVE — piece drawer | YES (folded into #1) |
| 5 | Sample out | 2 | LIVE — `POST /pieces/{id}/sample-out` (`routes_inventory_sample.py`, PR #17/#18) | LIVE — piece drawer (`dashboard.html:2027+`) | **YES** |
| 6 | Sample return | 2 | LIVE — `POST /pieces/{id}/sample-return` (`routes_inventory_sample.py`) | LIVE | **YES** |
| 7 | Consignment flows | 3 | TODO (still design-only) | TODO | NO — Stage 2 tile shows `null` for consignment |
| 8 | Goods return | 3 | LIVE — `POST /pieces/{id}/return-from-client` (`routes_inventory_returns.py`, PR #22) | LIVE — piece drawer (`dashboard.html:2151+`) | **YES** |
| 9 | Return to producer | 4 | LIVE — `POST /pieces/{id}/return-to-producer` + `POST /pieces/{id}/return-from-producer` (`routes_inventory_returns.py`, PR #22) | LIVE — piece drawer (`dashboard.html:2217+`) | **YES** |

**Blocked-on-operator decisions (still relevant for #7, otherwise resolved):**
- ~~Allocation-only vs new-state model for samples/consignment/returns (#5, #6, #7, #8).~~ **Resolved for #5/#6/#8/#9 — shipped against the state machine directly** (no allocation table). Decision still open for #7 (consignment).
- ~~Whether Doc 1 v2 §5 allocation enum needs a `RETURN` type added, or whether returns map to `QUARANTINE` (#8).~~ **Resolved — returns shipped as first-class states `RETURNED_FROM_CLIENT` / `RETURNED_TO_PRODUCER`, not as allocation-table entries.**
- Customs-doc workflow + Proforma-eligibility blocking for Return-to-producer (#9) — **partially resolved**: returns to producer is wired but Proforma-eligibility implications need a follow-up audit pass.
- ~~Confirm Move stock is metadata-only with no `transition()` call (#2 security review).~~ **Resolved — Move-stock ships as live; metadata-only invariant preserved.**
