# Inventory Failure Modes — Doc 4 v1

## Preamble

This document enumerates the failure modes for each of the nine inventory buttons (Doc 2 button registry) and the six core state transitions defined by `inventory_state_engine.STATES` (Doc 1 v2 §3). It is the failure-domain complement to Doc 1 v2 (state model), Doc 2 (button registry and locked operator ordering), and Doc 3 (UI/endpoint feasibility for the four read-only overnight wins). Every WRITE button is analysed across eight failure categories; every READ button across four. Where the codebase already enforces a guarantee, the file:line is cited; where it does not, the gap is flagged explicitly and forbidden hedges (`appears`, `likely`, `seems to`) are avoided.

Cross-DB integrity is the principal structural risk. The product writes to four independent SQLite files: `warehouse.db` (`inventory_state`, `inventory_state_events`, `inventory_movement_events` — see `service/app/services/warehouse_db.py:136-168`), `reservations.db` (`reservation_queue` — `service/app/services/reservation_db.py:89-114`), `wfirma.db` (`wfirma_reservation_drafts`), and `proforma_links.db` (`proforma_drafts`). SQLite cannot express a foreign key across attached databases, so cross-DB referential integrity must be enforced in worker code — never in SQL. The module-level lock `inventory_state_engine._lock` (`service/app/services/inventory_state_engine.py:117`) serialises calls to `transition()` within a single Python process; it does NOT serialise across multiple uvicorn workers, so cross-process race conditions remain possible and must be mitigated by idempotency keys at the route layer. The architecture is extend-existing: `transition()` is the only writer to `inventory_state`, and `reservation_queue.scan_code` does not exist (the table is sku-level only — `reservation_db.py:89-114`), which is the root cause of the double-allocation class of failures called out below.

---

## 1. View stock detail (READ)

### Failure modes
| # | Trigger | Detection | Mitigation |
|---|---|---|---|
| 1 | piece_id valid but `inventory_state` row missing (item known to packing but never transitioned) | API returns 200 with empty body; route test asserts 404 not 200-empty | Return 404 with `reason="no_state_row"`; UI shows "no lifecycle record" instead of blank panel |
| 2 | Endpoint accessible without `require_api_key` (Path 2 auth gap noted in Doc 3) | Route smoke test: call without X-API-Key, assert 401 | Add `dependencies=[_auth]` at decorator level mirroring `routes_lifecycle.py:469` |
| 3 | Stale data — read fires while `transition()` holds `_lock` and the SQLite WAL has not yet been written | Reader returns the pre-transition `state`; `inventory_state_events` count differs from `inventory_state.updated_at` by >1s | Acceptable for a read; UI labels the row with `updated_at` so operator sees timestamp; document "read may lag write by one WAL fsync" |
| 4 | Index miss at scale (full table scan if filtering by `product_code` without index) | `idx_invstate_product` already covers `product_code` (`warehouse_db.py:152-153`); slow-query log over 200ms | Existing indexes `idx_invstate_state`, `idx_invstate_batch`, `idx_invstate_product` cover the four read paths; no new index needed |

### Specific concerns
- View stock detail joins `inventory_state` + last `inventory_state_events` row + `inventory_movement_events` last RECEIVE. Three queries against `warehouse.db` only — no cross-DB.
- Sales reservation status (from `reservation_queue`) requires a second connection to `reservations.db`; if reservation lookup fails, panel must still render warehouse data.

### Test cases required
- `test_view_stock_detail_returns_404_on_unknown_piece`
- `test_view_stock_detail_requires_api_key`
- `test_view_stock_detail_renders_when_reservation_db_unreachable`

---

## 2. Move stock (WRITE — metadata only, NO state change)

### Failure modes
| # | Trigger | Detection | Mitigation |
|---|---|---|---|
| 1 | Concurrency — two operators move the same `scan_code` to different bins within 100ms | Last-write-wins on `current_location`; `inventory_movement_events` gets two MOVE rows | Accept last-write-wins; both MOVE events are preserved in audit; UI shows current+history |
| 2 | Network drop after MOVE INSERT but before response | Client retries with same `idempotency_key`; without it, second click creates duplicate MOVE event | REQUIRE `idempotency_key` on POST; route dedupes on (key, scan_code) before INSERT. GAP: no `idempotency_key` table exists today (grep of `service/app/` finds usages only in `routes_carrier_actions.py`, `routes_wfirma.py`, none in inventory routes) — must be added |
| 3 | Partial DB write — MOVE event INSERT succeeds, `inventory_state.note` UPDATE fails | SQLite single-DB atomicity: wrap both in single transaction; on exception, both roll back | Use a single `with con:` block; document that move stock writes ONLY to `warehouse.db` |
| 4 | Cross-DB inconsistency | N/A — Move stock touches only `warehouse.db` | No mitigation needed; documented as out-of-scope |
| 5 | Double-allocation | N/A — Move stock does not affect reservation eligibility | None |
| 6 | State invariant violation — operator moves an item in CLOSED state | GAP: today `_check_transition()` does not exist; `transition()` validates only via `LEGAL_TRANSITIONS` (`inventory_state_engine.py:88-96`). Move stock bypasses `transition()` entirely | Add explicit pre-check: refuse MOVE if `state in (CLOSED, SALES_TRANSIT)` |
| 7 | Audit gap — `inventory_movement_events` row missing after UPDATE | Single-transaction atomicity prevents this within `warehouse.db` | Same transaction as #3 |
| 8 | Customs implication | N/A | None |

### Specific concerns
- Move stock MUST NOT call `transition()` — confirmed by Doc 1 v2.
- A move on a CLOSED item is meaningless but currently not blocked.

### Test cases required
- `test_move_stock_does_not_change_lifecycle_state`
- `test_move_stock_idempotent_under_same_key`
- `test_move_stock_rejected_on_closed_item`
- `test_move_stock_concurrent_writes_preserve_audit`

---

## 3. Direct dispatch visibility (READ)

### Failure modes
| # | Trigger | Detection | Mitigation |
|---|---|---|---|
| 1 | Empty result — batch has no rows in `DIRECT_DISPATCH_READY` or `CLIENT_DISPATCHED` | `list_by_state()` returns `[]` (`inventory_state_engine.py:159-174`); UI test asserts empty-state message rendered, not blank table | Return `{"items": [], "reason": "no_direct_dispatch_for_batch"}`; UI shows "no direct-dispatch items" |
| 2 | Auth bypass | Same as Button 1 #2 | `dependencies=[_auth]` |
| 3 | Stale data — read fires during `mark-direct-dispatch` batch loop | `_lock` serialises engine writes; reader sees a consistent point-in-time; partial-batch transitions visible mid-batch | Document: reads MAY observe a partial batch. UI shows progress count, not "all-or-nothing" |
| 4 | Index miss | `idx_invstate_state` covers the WHERE clause (`warehouse_db.py:148-149`) | None — existing index sufficient |

### Specific concerns
- Direct dispatch visibility surfaces customer_allocation, which is stored as `note` field today (no dedicated column). Doc 1 v2 §3 names this as PENDING. Until column added, parse from `note`.

### Test cases required
- `test_direct_dispatch_visibility_filters_by_state`
- `test_direct_dispatch_visibility_requires_api_key`
- `test_direct_dispatch_visibility_renders_partial_batch_during_mark`

---

## 4. Inventory event timeline (READ)

### Failure modes
| # | Trigger | Detection | Mitigation |
|---|---|---|---|
| 1 | Empty result — scan_code with state row but no events (impossible in practice because `transition()` always writes an event — `inventory_state_engine.py:298-305`) | `get_history()` returns `[]`; assertion: if state row exists, event count ≥ 1 | If invariant violated, log `INV_AUDIT_GAP` and surface "audit incomplete" |
| 2 | Auth bypass | Same as above | `dependencies=[_auth]` |
| 3 | Stale data — event written but WAL not flushed | `idx_invstate_events_scan` indexes (scan_code, occurred_at) (`warehouse_db.py:167-168`); reader sees committed rows only | Accept last-WAL-fsync delay; no mitigation needed |
| 4 | Index miss | Existing composite index covers timeline query | None |

### Specific concerns
- Timeline must merge `inventory_state_events` (lifecycle) + `inventory_movement_events` (physical) by `occurred_at` / `event_time`. Two queries, one DB, no cross-DB risk.
- Reservation events live in `reservations.db`; timeline read MUST be resilient to that DB being absent (return warehouse rows only).

### Test cases required
- `test_event_timeline_merges_lifecycle_and_movement`
- `test_event_timeline_resilient_to_missing_reservation_db`
- `test_event_timeline_invariant_state_row_implies_event_row`

---

## 5. Sample out (WRITE — Risk-3, design only)

### Failure modes
| # | Trigger | Detection | Mitigation |
|---|---|---|---|
| 1 | Concurrency — two operators issue sample-out for same scan_code within 100ms in single uvicorn process | `_lock` (`inventory_state_engine.py:117`) serialises; second call sees new state, fails `LEGAL_TRANSITIONS` check at line 242-248 | First call wins; second receives `ValueError`, surfaced as 409. Cross-process: `_lock` does NOT span workers — REQUIRE idempotency_key dedupe at route layer |
| 2 | Network drop after `transition()` commit, before response | Client retries; second call sees new state, raises illegal-transition `ValueError` | Idempotency_key dedupe returns the prior result; document "retry-safe via key" |
| 3 | Partial DB write within `warehouse.db` — `inventory_state` UPDATE commits but `inventory_state_events` INSERT fails | Both run inside `with _lock, _connect() as con:` block (`inventory_state_engine.py:235-310`); SQLite autocommits at block exit; on exception both roll back | Confirmed atomic. Add test `test_transition_atomic_on_event_insert_failure` |
| 4 | Cross-DB inconsistency — Sample out should also record into a `sample_out_log` table (new, design phase). If that lives in `warehouse.db`, single-transaction. If in a separate samples.db, two-phase | Detect via `BRIDGE_INCONSISTENCY` log emitted at bridge call site | Keep sample_out_log inside `warehouse.db` to avoid bridge. If separate DB required, write samples row FIRST (idempotent insert), then call `transition()`, then mark samples row `confirmed`. On engine failure: samples row stays `pending`, quarantine job retries |
| 5 | Double-allocation — same scan_code claimed by sample-out and a reservation. `reservation_queue` has NO `scan_code` (`reservation_db.py:89-114`), so DB cannot enforce uniqueness | Today: undetectable at SQL layer. Detection requires worker-code check `get_state(scan_code) in PROFORMA_ELIGIBLE_STATES` before sample-out | Pre-flight in route: refuse sample-out if state ∈ {RESERVED_FOR_PROFORMA, DISPATCH_PENDING}. This is the same root cause flagged for buttons 6-9 |
| 6 | State invariant violation — sample-out attempted from PURCHASE_TRANSIT | `LEGAL_TRANSITIONS[PURCHASE_TRANSIT] = {WAREHOUSE_STOCK, DIRECT_DISPATCH_READY}` (`inventory_state_engine.py:90`); sample-out target not in set; raises | Route maps `ValueError` to HTTP 409 with from/to states; UI shows "cannot sample from transit" |
| 7 | Audit gap — `inventory_state_events` write fails after `inventory_state` UPDATE succeeded | Same transaction; cannot happen within `warehouse.db` (#3). For external samples_log: possible. Log line `INV_AUDIT_GAP` | Quarantine: write a `inventory_state_events_quarantine` row with the missing event payload; nightly reconciliation job replays |
| 8 | Customs implication | N/A for sample out | None |

### Specific concerns
- Sample out is Risk-3 design-only — no state currently named SAMPLE_OUT in `STATES`. Adding it requires extending `LEGAL_TRANSITIONS` AND the `STATES` frozenset (`inventory_state_engine.py:81-85`).
- `_check_transition()` does NOT exist as a separate function today; validation is inline at `inventory_state_engine.py:242-248`. Document this as a documentation gap, not a code gap.

### Test cases required
- `test_sample_out_atomic_under_event_insert_failure`
- `test_sample_out_idempotent_under_same_key_cross_process`
- `test_sample_out_rejects_pre_reserved_scan_code`
- `test_sample_out_serialised_by_engine_lock_in_process`

---

## 6. Sample return (WRITE — Risk-3, design only)

### Failure modes
| # | Trigger | Detection | Mitigation |
|---|---|---|---|
| 1 | Concurrency — sample-return called twice (e.g. UI double-click) | `_lock` serialises; second call observes WAREHOUSE_STOCK, raises illegal-transition | Idempotency_key at route returns prior result; UI disables button after first click |
| 2 | Network drop mid-write | Same as sample-out #2 | Same |
| 3 | Partial DB write | Same atomicity guarantee inside `with _lock, _connect()` block | Same |
| 4 | Cross-DB inconsistency — sample_out_log status update lives elsewhere | `BRIDGE_INCONSISTENCY` log line | Update samples row to `returned` AFTER `transition()` succeeds; on failure samples row remains `out`, quarantine job reconciles |
| 5 | Double-allocation | If a reservation was created against the sku while item was out for sample, return path must NOT auto-allocate to that reservation. Detection: pre-flight `count_by_state(state=WAREHOUSE_STOCK)` vs open reservations.qty | Refuse return if returning the piece would exceed promised stock; surface as 409 with reconciliation guidance |
| 6 | State invariant violation — return from a state other than SAMPLE_OUT | Engine raises | Route 409 |
| 7 | Audit gap | Same as sample-out #7 | Same quarantine pattern |
| 8 | Customs implication | N/A | None |

### Specific concerns
- Sample return depends on a SAMPLE_OUT state existing first. Until SAMPLE_OUT is added to `STATES`, this button is design-only and cannot be wired.

### Test cases required
- `test_sample_return_only_from_sample_out`
- `test_sample_return_idempotent`
- `test_sample_return_reconciles_with_open_reservations`

---

## 7. Consignment flows (WRITE — Risk-3, design only)

### Failure modes
| # | Trigger | Detection | Mitigation |
|---|---|---|---|
| 1 | Concurrency — consignment send + reservation create on same scan_code race | `_lock` serialises engine writes; reservation_queue INSERT is in a DIFFERENT DB and is NOT covered by `_lock` | Two-phase: reservation row INSERT in `reservations.db` with status='pending_consignment' FIRST; then engine `transition()`; on engine fail, mark reservation row 'rejected' |
| 2 | Network drop between reservation INSERT and engine transition | Reservation row stranded in 'pending_consignment' | Quarantine: scheduled reconciler scans pending_consignment rows older than 5 min and rolls them back |
| 3 | Partial DB write within `warehouse.db` | Atomic, see button 5 #3 | Same |
| 4 | Cross-DB inconsistency — `reservation_queue` updated in `reservations.db` AND `inventory_state` updated in `warehouse.db`. There is NO two-phase-commit primitive across SQLite files. | Log `BRIDGE_INCONSISTENCY` with both row ids; expose via dashboard counter | Write order: reservation_queue.set_status('created') AFTER engine `transition()` returns. On reservation_queue failure: emit operator alert via Cliq #pz (requirement only, not implemented in design phase); record the engine transition is canonical |
| 5 | Double-allocation — operator sends piece to Client A on consignment while a reservation for Client B exists at sku level. `reservation_queue.scan_code` does not exist (`reservation_db.py:89-114`), so no DB-level uniqueness | Detection requires worker-code lookup: `list_by_state(WAREHOUSE_STOCK, batch_id)` count vs `sum(reservation_queue.qty WHERE status IN (pending, ready))` | Pre-flight reject if free stock < open reservation demand. ROOT CAUSE remediation requires adding `scan_code` column to `reservation_queue` — flagged as schema change, out of scope for Doc 4 |
| 6 | State invariant violation | Engine raises if from-state not legal | Route 409 |
| 7 | Audit gap | Single-transaction warehouse.db writes are atomic; cross-DB samples-log gap possible | Quarantine |
| 8 | Customs implication | Consignment to non-EU destinations may trigger customs — out of scope for Doc 4 v1 | Flag for Doc 5 |

### Specific concerns
- Consignment introduces the worst cross-DB writer in the system: it must touch `inventory_state`, `reservation_queue`, and potentially `proforma_drafts`.
- Without `idempotency_key` and without `reservation_queue.scan_code`, this button is unsafe to enable today.

### Test cases required
- `test_consignment_cross_db_writes_canonical_order`
- `test_consignment_quarantines_stranded_reservation_on_engine_failure`
- `test_consignment_double_allocation_blocked_at_route_layer`

---

## 8. Goods return (WRITE — Risk-3, design only)

### Failure modes
| # | Trigger | Detection | Mitigation |
|---|---|---|---|
| 1 | Concurrency — return processed twice (operator + automated DHL inbound) | `_lock` in-process; cross-process gap requires idempotency_key | Same as sample-out #1 |
| 2 | Network drop mid-write | Same | Idempotency_key returns prior result |
| 3 | Partial DB write | Single-DB atomic | Same |
| 4 | Cross-DB inconsistency — closing a reservation_queue row + reverting `inventory_state` from SALES_TRANSIT to WAREHOUSE_STOCK | NOT legal under current `LEGAL_TRANSITIONS` (`inventory_state_engine.py:88-96`) — there is NO edge SALES_TRANSIT→WAREHOUSE_STOCK | Goods return for a SALES_TRANSIT item requires extending `LEGAL_TRANSITIONS`. Document as schema change |
| 5 | Double-allocation — returned piece re-enters stock while sku-level reservation still open for another client | Same root cause: `reservation_queue.scan_code` absent | Pre-flight check before returning to WAREHOUSE_STOCK |
| 6 | State invariant violation — return from CLOSED | `LEGAL_TRANSITIONS[CLOSED] = frozenset()` (`inventory_state_engine.py:95`); engine raises | Route 409 with clear message: "CLOSED is terminal; create new RMA batch" |
| 7 | Audit gap | Same | Quarantine |
| 8 | Customs implication — goods return from non-EU client may require customs re-entry SAD | Flag in audit; require operator confirmation | Document; out of scope for execution in Doc 4 |

### Specific concerns
- Today the state model has no reverse edges. Goods return DESIGN requires either (a) new edges in `LEGAL_TRANSITIONS` (preferred, explicit) or (b) a separate RMA batch that creates new PURCHASE_TRANSIT rows (cleaner audit, double-counting risk).

### Test cases required
- `test_goods_return_rejected_until_legal_transitions_extended`
- `test_goods_return_blocked_from_closed`
- `test_goods_return_idempotent`

---

## 9. Return to producer (WRITE — Risk-4, customs implication)

### Failure modes
| # | Trigger | Detection | Mitigation |
|---|---|---|---|
| 1 | Concurrency | `_lock` + idempotency_key | Same pattern |
| 2 | Network drop | Same | Same |
| 3 | Partial DB write | Single-DB atomic | Same |
| 4 | Cross-DB inconsistency — must also write to a `producer_return_log` and may update `wfirma_reservation_drafts` to cancel inflight drafts | Two-phase write across `warehouse.db`, `wfirma.db` | Cancel wFirma draft FIRST (idempotent — drafts have explicit `cancelled` state); then `transition()`. On engine fail, wFirma draft stays cancelled (safe — no real-world side effect because draft never reached wFirma confirmation) |
| 5 | Double-allocation — piece returned to producer while reservation still open | sku-level reservation orphaned | Pre-flight: reject if any `reservation_queue` row with matching `product_code` is in status ∈ (pending, ready). Force operator to cancel reservation first |
| 6 | State invariant violation | Engine raises | Route 409 |
| 7 | Audit gap | Quarantine | Same |
| 8 | **Customs implication — duty/SAD not yet cleared, or already cleared and now requiring re-export documentation** | Pre-flight check `_customs_cleared_from_audit(batch_id)` mirroring `routes_lifecycle.py:502-511`; refuse if not cleared. If cleared, REQUIRE operator to attach re-export evidence note. | Hard block at route layer with 400 + structured `missing` field, identical pattern to existing direct-dispatch evidence gate (`routes_lifecycle.py:502-511`). Customs duty refund / re-export filing tracked outside PZ (Doc 5 scope) |

### Specific concerns
- Return to producer is the only Risk-4 button: customs implication makes it the highest-blast-radius write.
- Idempotency_key MUST be required; double-fire on this button could trigger duplicate SAD re-export filings.
- Operator notification REQUIRED (Cliq #pz) on every successful return — design requirement, implementation deferred.

### Test cases required
- `test_return_to_producer_requires_customs_evidence`
- `test_return_to_producer_cancels_wfirma_draft_first`
- `test_return_to_producer_blocked_with_open_reservation`
- `test_return_to_producer_idempotent_under_double_fire`
- `test_return_to_producer_emits_cliq_notification_requirement`

---

## Transition: None → PURCHASE_TRANSIT

### Failure modes
| # | Trigger | Detection | Mitigation |
|---|---|---|---|
| 1 | Concurrency — same scan_code submitted twice (PZ regenerate) | UNIQUE constraint on `inventory_state.scan_code` (`warehouse_db.py:138`); second INSERT fails with IntegrityError | Engine code uses UPDATE-if-exists branch (`inventory_state_engine.py:272-296`); second call hits the UPDATE branch and re-runs `LEGAL_TRANSITIONS` check, which fails because PURCHASE_TRANSIT ∉ legal-from-PURCHASE_TRANSIT. Surface as 409 |
| 2 | Network drop after `transition()` but before PZ generation finalises | Idempotency_key required at PZ route | Existing `process_batch()` flow regenerates deterministically; re-running is safe |
| 3 | Partial DB write | Atomic block | Confirmed atomic |
| 4 | Cross-DB inconsistency | None at this transition — purchase intake is `warehouse.db` only | None |
| 5 | Double-allocation | Not applicable at intake | None |
| 6 | State invariant violation — caller passes `from_state=PURCHASE_TRANSIT` and `to_state=PURCHASE_TRANSIT` | `LEGAL_TRANSITIONS` raises | 409 |
| 7 | Audit gap | Atomic with UPDATE/INSERT | None |
| 8 | Customs implication | None at intake | None |

### Test cases required
- `test_first_transition_creates_state_and_event_atomically`
- `test_duplicate_pz_generation_idempotent`

---

## Transition: PURCHASE_TRANSIT → WAREHOUSE_STOCK

### Failure modes
| # | Trigger | Detection | Mitigation |
|---|---|---|---|
| 1 | Concurrency — two scanner devices RECEIVE same scan_code | `_lock` serialises; second sees WAREHOUSE_STOCK, fails legal check | Idempotency_key dedupe at scan route |
| 2 | Network drop after RECEIVE event INSERT but before lifecycle transition | RECEIVE in `inventory_movement_events` exists, `inventory_state` still PURCHASE_TRANSIT | Engine guarantees: `transition()` is called explicitly AFTER scan; doc says `RECEIVE` does NOT auto-promote (`inventory_state_engine.py:43-44`). Operator/automation calls `transition()` separately |
| 3 | Partial DB write | Atomic | Same |
| 4 | Cross-DB | None | None |
| 5 | Double-allocation | Not applicable | None |
| 6 | State invariant — receive without prior intake | `from_state=None`, target=WAREHOUSE_STOCK; `LEGAL_TRANSITIONS[None] = {PURCHASE_TRANSIT}` — fails | 409, operator must create intake first |
| 7 | Audit gap | Atomic | None |
| 8 | Customs | None | None |

### Test cases required
- `test_receive_event_does_not_auto_promote_lifecycle`
- `test_warehouse_receive_requires_prior_purchase_transit`

---

## Transition: PURCHASE_TRANSIT → DIRECT_DISPATCH_READY (orphaned endpoint)

### Failure modes
| # | Trigger | Detection | Mitigation |
|---|---|---|---|
| 1 | Concurrency — mark-direct-dispatch called twice for same batch | `_lock` serialises per-scan; route loops scan_codes (`routes_lifecycle.py:516-540`); second call sees DIRECT_DISPATCH_READY and reports `outcome="already_ready"` | Idempotency by design — see route docstring `routes_lifecycle.py:472-484` |
| 2 | Network drop mid-batch | Some scan_codes transitioned, others not; client retries | Idempotent per-scan; partial-batch continuation safe |
| 3 | Partial DB write | Atomic per scan_code | Confirmed |
| 4 | Cross-DB | None (warehouse.db only) | None |
| 5 | Double-allocation | If batch has open reservations, marking direct-dispatch removes those scan_codes from WAREHOUSE_STOCK pool — but reservation_queue does not know | Pre-flight: reject mark-direct-dispatch if open reservations exist for any scan_code in batch. NOT IMPLEMENTED today — gap |
| 6 | State invariant — evidence missing | Engine raises ValueError with explicit `missing:` list (`inventory_state_engine.py:254-268`) | Existing 400 with structured error matches Doc 3 contract |
| 7 | Audit gap | Atomic | None |
| 8 | Customs implication — operator must attest `customs_cleared=True`; route validates via `_customs_cleared_from_audit` (`routes_lifecycle.py:502-511`) | Existing 400 with `missing` field | Confirmed working |

### Specific concerns
- This is the only transition today that has an evidence gate. Pattern should be replicated for return-to-producer.
- The "orphaned" label in Doc 1 v2 refers to the fact that DIRECT_DISPATCH_READY items never enter WAREHOUSE_STOCK, so reservation_queue sku-counts include them and over-promise. Worker-code reconciliation needed in the dashboard read layer.

### Test cases required
- `test_mark_direct_dispatch_idempotent_already_ready`
- `test_mark_direct_dispatch_rejects_without_receive_event`
- `test_mark_direct_dispatch_rejects_without_customs_evidence`
- `test_mark_direct_dispatch_partial_batch_continues`

---

## Transition: WAREHOUSE_STOCK → RESERVED_FOR_PROFORMA (PENDING — Doc 1 v2 §3)

### Failure modes
| # | Trigger | Detection | Mitigation |
|---|---|---|---|
| 1 | Concurrency — proforma issued for client A while consignment send issued for client B on same sku, both in single process | `_lock` serialises engine; reservation_queue is in `reservations.db` and writes occur OUTSIDE `_lock` | Bridge order: `reservation_queue.insert(status='pending')` FIRST, then engine `transition()`. If two processes both insert pending rows, both engine transitions can succeed because they update DIFFERENT scan_codes — UNLESS the same scan_code. Then second engine call raises illegal-transition |
| 2 | Network drop after reservation_queue INSERT, before engine transition | Reservation stranded in `pending` with no lifecycle state change | Quarantine: nightly reconciler scans pending reservations older than 1h and rolls back |
| 3 | Partial DB write within warehouse.db | Atomic | Same |
| 4 | Cross-DB inconsistency — reservation_queue committed but inventory_state UPDATE fails | `BRIDGE_INCONSISTENCY` log | Compensating action: `reservation_queue.set_status('rolled_back', reason='engine_transition_failed')` in the exception handler at bridge site |
| 5 | Double-allocation — TWO reservations created for same sku, both succeed because reservation_queue is sku-level not scan_code-level | Detection requires application-level pre-flight: `free_stock = count_by_state(WAREHOUSE_STOCK, batch_id) - sum(open_reservations.qty)`. If `free_stock < requested_qty`, reject | **THIS IS THE PRIMARY DOUBLE-ALLOCATION ROOT CAUSE.** Doc 4 documents the gap; remediation requires schema change to `reservation_queue` (add `scan_code` column or per-scan reservation_items child table) |
| 6 | State invariant — transition called for scan_code in PURCHASE_TRANSIT (not yet received) | Engine raises | Route 409 |
| 7 | Audit gap | Atomic in warehouse.db | None |
| 8 | Customs implication | None for this transition | None |

### Specific concerns
- RESERVED_FOR_PROFORMA is PENDING — not yet in `STATES` frozenset (`inventory_state_engine.py:81-85`). Adding it is a prerequisite for any code-level mitigation.
- Until added, mitigations in this section are design requirements, not code requirements.

### Test cases required
- `test_reserved_for_proforma_blocks_second_reservation_on_same_scan_code`
- `test_reserved_for_proforma_rolls_back_queue_on_engine_failure`
- `test_reservation_queue_pending_quarantine_after_1h_orphan`

---

## Transition: RESERVED_FOR_PROFORMA → DISPATCH_PENDING (PENDING)

### Failure modes
| # | Trigger | Detection | Mitigation |
|---|---|---|---|
| 1 | Concurrency — proforma confirmed twice | `_lock` + idempotency on proforma_drafts.id | Idempotency_key |
| 2 | Network drop | Idempotency dedupe | Same |
| 3 | Partial DB write | Atomic | Same |
| 4 | Cross-DB inconsistency — proforma_drafts.status updated in proforma_links.db, inventory_state in warehouse.db, reservation_queue in reservations.db. THREE-DB write. | `BRIDGE_INCONSISTENCY` with three row ids | Write order: proforma_drafts FIRST (canonical authority for sales doc), reservation_queue SECOND, inventory_state LAST. Compensating action on each failure: roll back in REVERSE order |
| 5 | Double-allocation | Should be impossible if previous transition enforced uniqueness; if not, manifests here | Pre-flight: assert exactly one reservation row exists for this scan_code |
| 6 | State invariant | Engine raises | 409 |
| 7 | Audit gap | Per-DB atomic, cross-DB quarantine | Quarantine |
| 8 | Customs | None | None |

### Test cases required
- `test_dispatch_pending_writes_three_dbs_in_canonical_order`
- `test_dispatch_pending_rollback_reverses_order`

---

## Transition: DISPATCH_PENDING → CLIENT_DISPATCHED

### Failure modes
| # | Trigger | Detection | Mitigation |
|---|---|---|---|
| 1 | Concurrency — DHL handoff scanned twice | `_lock`; second call sees CLIENT_DISPATCHED, raises | Idempotency_key on courier-scan |
| 2 | Network drop | Same | Same |
| 3 | Partial DB write | Atomic | Same |
| 4 | Cross-DB — carrier shipment record (`shipment_db`) updated alongside inventory_state | `BRIDGE_INCONSISTENCY` | Carrier coordinator already uses idempotency (`service/app/services/carrier/coordinator.py`) — extend pattern to call `transition()` AFTER shipment row confirmed |
| 5 | Double-allocation | Should not occur at dispatch | None |
| 6 | State invariant — direct-dispatch path: from DIRECT_DISPATCH_READY; warehouse path: from DISPATCH_PENDING. Engine permits only DIRECT_DISPATCH_READY → CLIENT_DISPATCHED today (`inventory_state_engine.py:92`). DISPATCH_PENDING → CLIENT_DISPATCHED edge is PENDING | Engine raises until edge added | Document as schema change |
| 7 | Audit gap | Per-DB atomic | None |
| 8 | Customs | Export evidence required for non-EU destinations — flag for Doc 5 | None in Doc 4 |

### Test cases required
- `test_client_dispatched_from_dispatch_pending_blocked_until_legal_transition_added`
- `test_client_dispatched_from_direct_dispatch_ready_succeeds`
- `test_client_dispatched_carrier_coord_idempotent`

---

## Transition: CLIENT_DISPATCHED → CLOSED

### Failure modes
| # | Trigger | Detection | Mitigation |
|---|---|---|---|
| 1 | Concurrency — delivery confirmation arrives twice from carrier webhook | `_lock`; second sees CLOSED; raises (CLOSED has no outgoing edges — `inventory_state_engine.py:95`) | Idempotency_key on webhook |
| 2 | Network drop | Idempotency | Same |
| 3 | Partial DB write | Atomic | Same |
| 4 | Cross-DB — close reservation_queue row, close proforma_draft, close carrier shipment, close inventory_state | FOUR-DB write — highest cross-DB complexity in the system | Canonical order: inventory_state LAST. Reasoning: if anything else fails, inventory_state still in CLIENT_DISPATCHED, operator retries close. If inventory_state succeeds and another DB fails, item is CLOSED but reservations/proforma still open — surfaces as dashboard anomaly |
| 5 | Double-allocation | N/A at close | None |
| 6 | State invariant — close from any state other than CLIENT_DISPATCHED or SALES_TRANSIT | Engine raises | 409 |
| 7 | Audit gap | Per-DB atomic; cross-DB quarantine | Quarantine |
| 8 | Customs implication — final closure may trigger archival of customs SAD reference. Out of scope for Doc 4 | Flag in audit | None |

### Specific concerns
- CLOSED is terminal (`LEGAL_TRANSITIONS[CLOSED] = frozenset()`). Any attempt to transition from CLOSED is a hard 409.
- Cross-DB close is the most failure-rich operation in the system. A dedicated reconciliation job is REQUIRED post-implementation; documented here as a design requirement.

### Test cases required
- `test_closed_terminal_rejects_all_outgoing`
- `test_close_writes_four_dbs_inventory_last`
- `test_close_idempotent_under_carrier_webhook_replay`
- `test_close_partial_failure_surfaces_dashboard_anomaly`

---

## Cross-cutting gaps (require remediation before any WRITE button is enabled)

1. **No idempotency_key infrastructure in inventory routes.** Search of `service/app/` finds usages only in `routes_carrier_actions.py`, `routes_wfirma.py`. Must be added to all inventory WRITE routes (Move stock, mark-direct-dispatch, future sample/consignment/return).
2. **`reservation_queue.scan_code` does not exist** (`reservation_db.py:89-114`). Until added, double-allocation prevention can only be approximated by application-code pre-flight checks.
3. **No `_check_transition()` helper** — validation is inline at `inventory_state_engine.py:242-248`. This is acceptable; document so future contributors do not search for a missing function.
4. **`_lock` is module-level, in-process only** (`inventory_state_engine.py:117`). Multi-worker uvicorn defeats it. Either (a) run inventory engine in a single worker, (b) use SQLite `BEGIN IMMEDIATE` at the engine layer, or (c) introduce a file-based lock. Choice deferred to Doc 5.
5. **No metrics/monitoring for `BRIDGE_INCONSISTENCY` log lines.** Current observability is grep-on-logs. Cliq webhook into #pz channel for high-severity inconsistencies is a documented requirement; implementation deferred.
6. **No quarantine tables exist today.** `inventory_state_events_quarantine`, `reservation_queue_quarantine` etc. are referenced in mitigations but must be created before WRITE buttons 5-9 are enabled.
