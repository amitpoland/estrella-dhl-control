# Sample-Out Stage 1 — Operational Design

**Status:** Design only. No code changes. No migration. No tests.
**Scope:** The first inventory write that mutates lifecycle truth via `inventory_state_engine.transition()`. Establishes the pattern for every subsequent lifecycle-affecting write.
**Branch context:** `feat/sample-out-design`, cut from `main` @ `c2902dc` (which has the Move stock PR #16 merge). All Move stock reference artifacts and prior design docs are present on this branch.

---

## 0. Branch reality check

| Artifact | On branch? | Notes |
|---|---|---|
| `service/app/services/inventory_state_engine.py` | yes | cited directly throughout this doc |
| `service/app/services/warehouse_db.py` | yes | includes idempotency helpers `record_scan_with_idempotency` (~line 497), `find_movement_event_by_idempotency` (~line 614), `ensure_idempotency_schema` (~line 641) — design patterns from these |
| `service/app/services/reservation_db.py` | yes | cited for `reservation_queue` schema (lines 89-119) |
| `service/app/services/inventory_location_writer.py` (Move stock writer) | yes | reference pattern for idempotency + precheck + state-gate |
| `service/app/api/routes_inventory_writes.py` (Move stock router) | yes | reference pattern for `MoveStockError` → HTTP status mapping |
| `service/app/db/migrations/draft_20260512_002516_idempotency_key.py.draft` | yes | reference pattern for idempotent migration scripts |
| `service/app/static/dashboard.html` | yes | InventoryPage + BatchDetailPage exist; Move stock UI surfaces are live |
| `docs/operational-memory/inventory/BUTTON_REGISTRY.md` | yes (from Group A merge) | Sample-out is button #5 in the registry |
| `docs/operational-memory/inventory/RISK_3_4_DESIGN_STUBS.md` | yes (from Group A merge) | supersedes the prior stub for Sample-out |
| `docs/inspection/reconciliation-engine-architecture.md` | not yet merged to main (lives on `feat/reconciliation-engine-inspection`) | cited where relevant; the substantive reconciliation rules in §6 are independent of that doc being on disk |

The design below grounds every assertion in `file:line` citations to source files that are present on this branch.

---

## 1. Lifecycle transition: `WAREHOUSE_STOCK → SAMPLE_OUT`

### 1.1 New state

Proposal: add `SAMPLE_OUT` to `inventory_state_engine.STATES` (`inventory_state_engine.py:81-85`).

```
SAMPLE_OUT  = "SAMPLE_OUT"
```

Definition: a piece that has physically left the warehouse for a non-sale purpose (customer review, quality check, marketing photo, trade show, or other operator-justified reason) and is **expected to return**. It is **not** sold, **not** committed to a customer invoice, and **not** counted against open Proforma availability.

### 1.2 New legal transitions

Proposed additions to `LEGAL_TRANSITIONS` (`inventory_state_engine.py:88-96`):

| From | To | Trigger label |
|---|---|---|
| `WAREHOUSE_STOCK` | `SAMPLE_OUT` | `sample_out_marked` |
| `SAMPLE_OUT` | `WAREHOUSE_STOCK` | `sample_returned` |

Trigger-name justification: the existing engine uses past-tense or `_marked` suffixed labels for operator-explicit transitions — see `direct_dispatch_marked` (`inventory_state_engine.py:102`) and `warehouse_receive` / `client_dispatched` / `invoice_issued` (`inventory_state_engine.py:101-106`). `sample_out_marked` matches the `_marked` pattern for operator-explicit lifecycle moves that require evidence. `sample_returned` matches the receive-style past-participle pattern.

The corresponding `DEFAULT_TRIGGER` rows would mirror the existing dict at `inventory_state_engine.py:99-107`.

### 1.3 Required evidence (validity gate inside `transition()`)

Mirror the pattern used for `DIRECT_DISPATCH_READY` at `inventory_state_engine.py:254-268` (each missing piece raises a distinct `ValueError` so the operator UI can show the exact gap).

For `to_state == SAMPLE_OUT`:

| Field | Constraint | Error if missing |
|---|---|---|
| `operator` | non-empty string | `"operator"` |
| `recipient_client_name` | non-empty string | `"recipient_client_name"` |
| `expected_return_date` | ISO 8601 (`YYYY-MM-DD`), parses to a date strictly in the future relative to server now (UTC) | `"expected_return_date (future ISO 8601)"` |
| `reason` | member of `SAMPLE_OUT_REASONS` enum (see below) | `"reason (one of: customer_review, quality_check, marketing_photo, trade_show, other)"` |
| `idempotency_key` | non-empty string | `"idempotency_key"` |

`recipient_client_id` is **optional** because a client may not yet be in master data when a sample goes out (e.g. trade show prospect).

Proposed enum (kept in the new writer module, not in the engine, so the engine stays domain-agnostic):

```
SAMPLE_OUT_REASONS = frozenset({
    "customer_review", "quality_check", "marketing_photo",
    "trade_show", "other",
})
```

### 1.4 Single-writer discipline

The new writer (designed as `sample_out_writer.py`, not yet on disk) **must** route every state change through `inventory_state_engine.transition()` (`inventory_state_engine.py:207-310`). It must never `INSERT` or `UPDATE` `inventory_state` directly.

Contrast with Move stock: Move stock writes only the physical location metadata (`inventory_current_location`) and **does not call `transition()`** because moving a piece between tray locations is not a lifecycle event. Sample-out is fundamentally different — it is a lifecycle event — and therefore the single-writer rule applies in full.

The `transition()` function already serializes via `_lock` (`inventory_state_engine.py:117`, used at line 235) and enforces the legal-transitions rule at lines 242–248 by raising `ValueError` for any combination not present in `LEGAL_TRANSITIONS`. No additional locking is needed in the writer.

---

## 2. Audit evidence schema

### 2.1 Fields captured per sample-out event

| Field | Type | Source | Notes |
|---|---|---|---|
| `event_id` | UUID v4 string | server-set | new row id |
| `piece_id` (= `scan_code`) | string | request | matches `inventory_state.scan_code` UNIQUE column at `warehouse_db.py:138` |
| `operator` | string, non-empty | request | validated |
| `recipient_client_name` | string, non-empty | request | validated |
| `recipient_client_id` | string, optional | request | empty allowed |
| `timestamp` (`occurred_at`) | ISO 8601 UTC | server-set | matches existing `_now()` at `inventory_state_engine.py:120-121` |
| `reason` | enum | request | one of `SAMPLE_OUT_REASONS` |
| `expected_return_date` | ISO 8601 date | request | future-dated |
| `notes` | string, optional | request | free text |
| `idempotency_key` | string, non-empty | caller | UNIQUE per `(scan_code, idempotency_key)` |
| `lifecycle_event_id` | FK | server-derived | references the `inventory_state_events.id` row written by `transition()` |

### 2.2 Storage proposal

The engine already writes an append-only audit row to `inventory_state_events` on every transition (`inventory_state_engine.py:298-305`; schema at `warehouse_db.py:156-168`). That row captures: `id`, `scan_code`, `from_state`, `to_state`, `trigger`, `occurred_at`, `operator`, `note`. The lifecycle audit chain is therefore already in place. What the design must add is **sample-specific evidence** (recipient, reason, expected_return_date, idempotency_key).

**Two options:**

| Option | Description | Trade-offs |
|---|---|---|
| **A.** Extend `inventory_state_events` with `recipient`, `reason`, `expected_return_date`, `idempotency_key` columns | Single audit table; every transition has the same schema, with NULLs where N/A | Pollutes a generic table with sample-specific columns; expected_return_date and reason are meaningless for `warehouse_receive` events; harder to add UNIQUE `(scan_code, idempotency_key)` because the index would need to filter by `to_state` |
| **B.** New dedicated table `sample_out_events` with the columns above + FK `lifecycle_event_id → inventory_state_events.id` | Sample-specific evidence isolated; clean UNIQUE `(scan_code, idempotency_key)` for replay safety; future evidence tables (e.g. `repair_out_events`) follow the same pattern | Two-row insert per sample-out transaction; must be inside the same `transition()` connection or a wrapping transaction to stay atomic |

**Recommendation: Option B.**

Rationale:
1. Option B keeps `inventory_state_events` (`warehouse_db.py:156-168`) generic and stable as a domain-agnostic audit trail. Future lifecycle events (repair-out, lab-out, photo-shoot-out) each add their own evidence table without re-shaping the generic table.
2. The UNIQUE replay-safety constraint becomes `UNIQUE(scan_code, idempotency_key)` on `sample_out_events` alone — a clean, single-purpose index. Under Option A the same constraint would require a partial index that varies by `to_state` and is harder to reason about.
3. Atomicity is achievable by extending `transition()` with an optional `extra_writes` callback or — preferred — by having `sample_out_writer.py` open its own SQLite transaction that wraps `transition()` plus the `sample_out_events` insert. Because `_connect()` (`inventory_state_engine.py:124-129`) uses `check_same_thread=False`, a careful wrapping transaction inside the writer is feasible. The exact mechanism is a Stage 2 implementation detail.

### 2.3 Schema sketch (DESIGN ONLY — no migration drafted)

```
CREATE TABLE IF NOT EXISTS sample_out_events (
    id                     TEXT PRIMARY KEY,
    lifecycle_event_id     TEXT NOT NULL,         -- FK → inventory_state_events.id
    scan_code              TEXT NOT NULL,
    direction              TEXT NOT NULL,         -- 'OUT' | 'RETURN'
    operator               TEXT NOT NULL,
    recipient_client_name  TEXT NOT NULL DEFAULT '',
    recipient_client_id    TEXT NOT NULL DEFAULT '',
    reason                 TEXT NOT NULL DEFAULT '',
    expected_return_date   TEXT NOT NULL DEFAULT '',
    notes                  TEXT NOT NULL DEFAULT '',
    idempotency_key        TEXT NOT NULL,
    occurred_at            TEXT NOT NULL,
    origin_event_id        TEXT NOT NULL DEFAULT '' -- on RETURN: links back to the original OUT row
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_sample_out_idem
    ON sample_out_events (scan_code, idempotency_key);
CREATE INDEX IF NOT EXISTS idx_sample_out_scan
    ON sample_out_events (scan_code, occurred_at);
CREATE INDEX IF NOT EXISTS idx_sample_out_open
    ON sample_out_events (direction, expected_return_date);
```

Migration draft is **not** produced here. Stage 2 will draft and apply it through the same channel used elsewhere in `service/app/db/migrations/`.

---

## 3. Return path: `SAMPLE_OUT → WAREHOUSE_STOCK`

### 3.1 Transition row

Already covered in section 1.2: `(SAMPLE_OUT, WAREHOUSE_STOCK): "sample_returned"`.

### 3.2 Required evidence for the return

| Field | Constraint |
|---|---|
| `operator` | non-empty |
| `idempotency_key` | non-empty; UNIQUE per `(scan_code, idempotency_key)` |
| `origin_event_id` | must reference an existing `sample_out_events.id` row where `direction='OUT'` AND `scan_code` matches |

No `expected_return_date` is needed on return; no `reason` is needed (the implicit reason is "returned"); `notes` remains optional.

### 3.3 Replay safety

Identical pattern to the Move stock model described in the operator brief: the DB UNIQUE index on `(scan_code, idempotency_key)` ensures a duplicate POST (same key) cannot insert twice. On `IntegrityError` the writer reads back the existing row and returns success — the operation is replay-idempotent.

The lifecycle write itself is also replay-safe at the state-engine level: a second call to `transition(scan_code, SAMPLE_OUT)` for a piece already in `SAMPLE_OUT` raises `ValueError` at `inventory_state_engine.py:243-248` because `(SAMPLE_OUT, SAMPLE_OUT)` is not in `LEGAL_TRANSITIONS`. The writer catches this and maps it to `409 WRONG_STATE` for the caller.

### 3.4 Partial-return handling

The single-writer rule (`inventory_state_engine.py:235`, `_lock` and per-scan-code `transition()`) is **per-piece**. A "sample batch" of N pieces is modelled as N independent `transition()` calls. Operator decision: a sample group is **not** a first-class entity. If the operator wants to group them in the UI, that is a presentation concern over the existing `recipient_client_name` + `occurred_at` window — not a new database concept.

This is the simplest contract that preserves single-writer discipline and matches the way the engine already treats every other lifecycle move (`PURCHASE_TRANSIT → WAREHOUSE_STOCK` happens one scan at a time on receive; `WAREHOUSE_STOCK → SALES_TRANSIT` happens one scan at a time on invoice issue).

Partial returns therefore work naturally: out of 5 pieces sent to a client, 3 returned → 3 `transition(SAMPLE_OUT → WAREHOUSE_STOCK)` calls. The remaining 2 stay in `SAMPLE_OUT` until they return or are escalated under the aging policy (section 6.3).

### 3.5 Audit-trail continuity

Every return row in `sample_out_events` carries `origin_event_id` pointing to the originating OUT row. The audit chain for one scan_code is therefore queryable in two ways:

1. Lifecycle chain via `inventory_state_events.scan_code` (the generic trail, `inventory_state_engine.py:146-156`).
2. Evidence chain via `sample_out_events.scan_code` joined to `inventory_state_events.id` (sample-specific trail).

Both must reconcile: every `SAMPLE_OUT` → `WAREHOUSE_STOCK` transition in `inventory_state_events` must have exactly one matching `direction='RETURN'` row in `sample_out_events` with `origin_event_id` set.

---

## 4. Forbidden transitions

`transition()` rejects every transition not in `LEGAL_TRANSITIONS` by default — see `inventory_state_engine.py:242-248`:

```python
legal = LEGAL_TRANSITIONS.get(from_state, frozenset())
if to_state not in legal:
    raise ValueError(
        f"Illegal transition for {scan_code!r}: "
        f"{from_state!r} → {to_state!r}. "
        f"Legal next states from {from_state!r}: {sorted(legal)}"
    )
```

That single guard is the enforcement mechanism for everything below. No additional code is required to forbid these — they simply must **not** be added to `LEGAL_TRANSITIONS`.

| Forbidden transition | Reason |
|---|---|
| `SAMPLE_OUT → CLOSED` | A sample must return before any terminal state. Closing in `SAMPLE_OUT` would orphan physical inventory off the books. |
| `SAMPLE_OUT → SALES_TRANSIT` | Converting a sample to a sale is a Phase B / Phase E flow that has not been designed. When designed, it will go through `SAMPLE_OUT → WAREHOUSE_STOCK → SALES_TRANSIT` (return then sell), or via a dedicated `sample_converted_to_sale` trigger if business requires skipping the intermediate state. Until that decision exists, this transition is forbidden. |
| `SAMPLE_OUT → CLIENT_DISPATCHED` | `CLIENT_DISPATCHED` is reserved for direct-dispatch sales paths (`inventory_state_engine.py:15-18`, `:111-115`). Samples are explicitly **not** direct-dispatch goods. |
| `SAMPLE_OUT → PURCHASE_TRANSIT` | Cannot un-ship goods from the supplier. |
| `SAMPLE_OUT → DIRECT_DISPATCH_READY` | `DIRECT_DISPATCH_READY` requires evidence including a prior `RECEIVE` movement event (`inventory_state_engine.py:262-263`) and customs clearance. A sample piece is past the warehouse-receive stage and is not a direct-dispatch candidate by definition. |
| `SAMPLE_OUT → SAMPLE_OUT` | Cannot double-sample a piece. |
| `WAREHOUSE_STOCK → SAMPLE_OUT` while a reservation exists | This is a soft check, not a hard transition forbid: see section 6.2 — extending `_check_warehouse_readiness` is one option; alternately the writer enforces it. |
| `DIRECT_DISPATCH_READY → SAMPLE_OUT` | A piece flagged for direct dispatch is committed to a customer; sampling it would break the commercial commitment. |
| `CLIENT_DISPATCHED → SAMPLE_OUT` | Goods already on the way to the customer; cannot retroactively reclassify. |
| `SALES_TRANSIT → SAMPLE_OUT` | Same — already invoiced and en route. |
| `PURCHASE_TRANSIT → SAMPLE_OUT` | Goods not yet at warehouse; cannot sample-out something you do not have. |
| `CLOSED → SAMPLE_OUT` | Terminal state has no legal out-edges (`inventory_state_engine.py:95`: `CLOSED: frozenset()`). |

Operator implication: the only way into `SAMPLE_OUT` is from `WAREHOUSE_STOCK`, and the only way out is back to `WAREHOUSE_STOCK`. This is intentionally narrow.

---

## 5. UI surfaces (proposal, not JSX)

All surfaces below are **data-testid contracts** — Stage 2 writes the JSX. The current `dashboard.html` does **not yet** carry the 5 disabled `inventory-action-*` placeholder buttons referenced in the operator brief (verified by `Grep` for `inventory-action|sample_out|sample-out|sample_return|sample-return` in `service/app/static/dashboard.html` — zero matches). The buttons are therefore greenfield additions.

### 5.1 InventoryPage

| `data-testid` | Surface | Behaviour |
|---|---|---|
| `inventory-action-sample-out` | piece drawer / row action | enabled only when piece is in `WAREHOUSE_STOCK`; opens a modal collecting `recipient_client_name`, `recipient_client_id` (optional), `reason`, `expected_return_date`, `notes`; submits to the Stage 2 writer endpoint with a fresh `idempotency_key`; disabled in any other state with tooltip stating the gating state |
| `inventory-action-sample-return` | piece drawer / row action | enabled only when piece is in `SAMPLE_OUT`; opens a confirm modal with current outstanding metadata and a `notes` field; submits with fresh `idempotency_key`; disabled in any other state |
| `inventory-piece-drawer-sample-aging` | piece drawer aging indicator | rendered only when state is `SAMPLE_OUT`; shows `days outstanding = today - occurred_at` and `days overdue = today - expected_return_date` (negative if still inside window); colour-codes amber at `>= expected_return_date` and red at `expected_return_date + 14d` |
| `inventory-filter-sample-out` | inventory grid filter chip | toggle showing only pieces currently in `SAMPLE_OUT`; chip count = engine `list_by_state('SAMPLE_OUT')` length, equivalent to `count_by_state()['SAMPLE_OUT']` (`inventory_state_engine.py:177-194`) |
| `inventory-stale-sample-alert` | dashboard banner | rendered when any sample is past `expected_return_date + 14d`; click navigates to the filtered grid |

### 5.2 BatchDetailPage

The Group B per-batch state strip is the natural home (per project memory: *Group B live in production, 2026-05-12, per-batch + per-piece inventory read endpoints*).

| `data-testid` | Surface | Behaviour |
|---|---|---|
| `batch-detail-sample-count` | pill in the per-batch state strip | renders `count_by_state(batch_id)['SAMPLE_OUT']` (`inventory_state_engine.py:177-194`); zero hides the pill |
| `batch-detail-sample-exposure` | secondary pill | renders count + (if available) sum of commercial value of outstanding samples for this batch; commercial value lookup is a Stage 2 join concern (candidate source: `v_sales_to_wfirma` per `routes_proforma.py:402-406`); if value is not derivable, render only the count |

No JSX in this design. The above are **contracts** the Stage 2 implementation must honour.

### 5.3 Out of scope for Stage 1 UI

- Sample-out bulk operations (multi-select then sample-out N pieces in one modal) — defer to Stage 1.5 or Stage 2.
- Recipient master-data integration (autocomplete from a client list) — defer; `recipient_client_id` stays optional.
- Sample-conversion-to-sale flow — explicitly forbidden in section 4, deferred to a future phase.

---

## 6. Reconciliation implications

Sample-out is the first lifecycle write covered by Stage 1. Stage 2 reconciliation must understand it before sample-out ships to production.

### 6.1 Drift class 1 — physical inventory vs lifecycle state

**Definition.** A piece is physically present in the warehouse (`inventory_current_location.current_location` is a real warehouse location) but `inventory_state.state == 'SAMPLE_OUT'`. Or vice versa: `inventory_state` says `WAREHOUSE_STOCK` but the piece has no current physical location, or its location is "OUT".

**Detection.** A reconciliation pass joins `inventory_state` (`warehouse_db.py:136-146`) to `inventory_current_location` (see `get_movement_history` and `get_inventory_at_location` at `warehouse_db.py:486-509`) on `scan_code`. Mismatches are flagged.

**Repair.** Operator-gated SAFE-recompute via `inventory_state_engine.transition()` with `trigger="sample_returned_reconcile"` and operator marker `"system:reconcile"`. Never bypass `transition()`. The reconcile job must produce a `sample_out_events` RETURN row matching the lifecycle write, with `origin_event_id` set to the original OUT row.

### 6.2 Drift class 2 — lifecycle state vs commercial reservation

**Definition.** A row exists in `reservation_queue` (`reservation_db.py:89-119`) for a `(batch_id, product_code)` whose scan_codes are currently in `SAMPLE_OUT`. The Proforma readiness gate would then incorrectly accept the piece as available.

**Current behaviour.** The Proforma stock check at `routes_proforma.py:417-449` uses `ise.PROFORMA_ELIGIBLE_STATES` (`inventory_state_engine.py:113-115`), which equals `{WAREHOUSE_STOCK, DIRECT_DISPATCH_READY, CLIENT_DISPATCHED}`. `SAMPLE_OUT` is **not** in that set — and **must not be added** to it. As long as the new state is omitted from `PROFORMA_ELIGIBLE_STATES`, a sampled-out piece naturally fails the readiness gate (`routes_proforma.py:441-449`), which returns `"sample_out"` as a blocking reason (Stage 2 will need to add the new bucket label to `_eligible_sets` and the status function).

**Required change in `_stock_status`.** Add a branch:

```
if any(sc in in_sample_out for sc in scs):
    return "sample_out"
```

This is a **read-side** projection change, not a state-engine change.

**Reservation reconciliation.** When a `reservation_queue` row references a product whose scan_codes are sampled out, the reservation should be flagged `blocking_reason="sample_out"` (using the existing column at `reservation_db.py:105`). It does **not** auto-cancel; an operator must either wait for return, choose alternate pieces, or override.

### 6.3 Aging policy

| Threshold | Action | Surface |
|---|---|---|
| `expected_return_date` | piece flagged "due" | `inventory-piece-drawer-sample-aging` turns amber |
| `expected_return_date + 14d` | piece flagged "stale" | `inventory-stale-sample-alert` banner; row prominently coloured in inventory grid |
| `expected_return_date + 30d` | block new sample-outs to the same `recipient_client_name` until resolved (operator override possible) | new sample-out modal returns a blocking error with the override field |

The thresholds are configurable at Stage 2 (proposal: store in a small `policy_config` JSON; not yet on disk). They are **policy**, not lifecycle truth — the lifecycle state remains `SAMPLE_OUT` regardless of how stale.

### 6.4 Reconciliation Stage 2 dependencies

Stage 2 of reconciliation (`reconcile_batch(batch_id)`) must learn three things before sample-out ships:

1. **Read the new state.** Any per-batch projection of state distribution must include `SAMPLE_OUT` as a bucket. `count_by_state()` already returns a dict keyed by every state in `STATES` (`inventory_state_engine.py:177-194`) — once `SAMPLE_OUT` is added to `STATES`, the function returns it automatically with zero code change.
2. **Drift detection.** Add the two drift classes from 6.1 and 6.2 as new detection rules.
3. **Repair semantics.** Repairs route through `transition()` only; never UPDATE `inventory_state` directly. This is the same rule as everywhere else; documented here because sample-out is the first write where the rule has real teeth.

### 6.5 Reconciliation order of operations

The single-writer discipline (`inventory_state_engine.py:235-310`) plus the `_lock` mutex means that reconciliation writes and operator writes serialize naturally. There is no race between a reconcile-time `SAMPLE_OUT → WAREHOUSE_STOCK` repair and an operator-initiated `sample_returned` for the same scan_code: whichever wins the lock first transitions; the second sees `from_state=WAREHOUSE_STOCK` and raises (because `(WAREHOUSE_STOCK, WAREHOUSE_STOCK)` is not in `LEGAL_TRANSITIONS`). The writer maps the resulting `ValueError` to `409 WRONG_STATE` and surfaces to the operator UI.

---

## 7. Failure-modes table

| Failure mode | Trigger | Detection | Mitigation |
|---|---|---|---|
| Concurrent sample-out on the same piece | Two operators POST sample-out for the same `scan_code` in parallel with different `idempotency_key`s | `_lock` (`inventory_state_engine.py:117`, held at line 235) serializes; the second call sees `from_state=SAMPLE_OUT` and the `(SAMPLE_OUT, SAMPLE_OUT)` lookup at `inventory_state_engine.py:242-248` returns an empty `legal` set | Writer catches `ValueError`, returns `409 WRONG_STATE` |
| Concurrent sample-out with same `idempotency_key` (true replay) | Browser retries or network double-fire | UNIQUE `(scan_code, idempotency_key)` index on `sample_out_events` raises `IntegrityError` on the second insert | Writer catches `IntegrityError`, reads back the row written first, returns `200 OK` with the original `event_id` — replay-idempotent |
| Sample-out followed by Move stock (physical relocation while sampled) | Operator scans a sampled piece into a new tray | Move stock writer is location-only; per the operator brief, it does **not** state-gate by `WAREHOUSE_STOCK`. **Decision required:** does Move stock allow location updates for pieces in `SAMPLE_OUT`? Recommendation: **no** — block, because the piece is physically off-site. The Move stock writer should add `SAMPLE_OUT` to its forbidden-state list | `409 WRONG_STATE` from Move stock writer |
| Return-from-sample with wrong `scan_code` (typo) | Caller posts a return for a non-existent scan | Writer entry: `get_state(scan_code)` returns `None` (`inventory_state_engine.py:134-143`) | `404 PIECE_NOT_FOUND` |
| Return-from-sample of a piece that was never sampled | Caller posts return for a piece currently `WAREHOUSE_STOCK` | `transition()` rejects: `(WAREHOUSE_STOCK, WAREHOUSE_STOCK)` not in `LEGAL_TRANSITIONS` (`inventory_state_engine.py:242-248`) | `409 WRONG_STATE` |
| Return-from-sample with mismatched `origin_event_id` | Caller posts return referencing a different piece's OUT row | Writer validates `origin_event_id` exists, has `direction='OUT'`, and `scan_code` matches the request scan_code | `400 BAD_REQUEST` |
| `expected_return_date` in the past | Operator clock skew or typo | Writer entry validation: parse as ISO 8601, compare to `_now()` | `400 BAD_REQUEST` with field "expected_return_date" |
| `reason` not in enum | UI bug or direct API call | Writer entry validation against `SAMPLE_OUT_REASONS` | `400 BAD_REQUEST` |
| DB unavailable | `warehouse_db._db_path is None` | `_connect()` (`inventory_state_engine.py:124-129`) raises `RuntimeError("warehouse_db not initialised…")` | Writer maps to `503 DB_UNAVAILABLE` |
| Migration pending (new `sample_out_events` table not yet created) | Schema not applied | Writer precheck: `SELECT name FROM sqlite_master WHERE type='table' AND name='sample_out_events'`; if absent, return early | `503 MIGRATION_PENDING` with explicit message |
| Reservation references a sampled-out piece | A `reservation_queue` row covers a product whose scan_codes are in `SAMPLE_OUT` when proforma is attempted | New branch in `_stock_status` (`routes_proforma.py:434-449`) returns `"sample_out"`; `_check_warehouse_readiness` (`routes_proforma.py:86-`) is unaffected because it operates on PZ-side rows, not scan-code-level availability | Blocking reason surfaced in the proforma UI; operator must wait for return or choose alternate pieces |
| Reconciliation drift discovered post-hoc | Audit reveals state `SAMPLE_OUT` but physical scan shows piece in the warehouse | Stage 2 detection job (`reconcile_batch`) | Operator-gated SAFE-recompute via `transition(SAMPLE_OUT → WAREHOUSE_STOCK)` with `operator='system:reconcile'`, `trigger='sample_returned_reconcile'`, and a synthetic `idempotency_key` of form `reconcile:{reconcile_run_id}:{scan_code}` |
| Operator cancels sample-out (regret) | Operator wants to undo a sample-out immediately after submitting | The only legal exit is the return path. Treat cancel as an early return with `reason="operator_cancel"` in `notes`, not a separate trigger | `200 OK` via `sample_returned` |

---

## 8. Open / pending operator decisions

None of the items below block Stage 2. They are flagged so the Stage 2 implementer asks the operator the first time they hit one.

1. **Move stock + SAMPLE_OUT interaction.** Section 7 recommends Move stock rejects relocation while `SAMPLE_OUT`. The Move stock writer (not on this branch) must add `SAMPLE_OUT` to its forbidden-state list. Confirm before Stage 2 ships.
2. **Commercial value lookup for `batch-detail-sample-exposure`.** If `v_sales_to_wfirma` (referenced at `routes_proforma.py:402-406`) is not available for unbilled pieces, the pill renders count only. Confirm whether a fallback (e.g. `purchase_invoice_lines.rate_usd × fx_rate`) is acceptable.
3. **Aging policy thresholds.** 14d and 30d are operator-set defaults. Confirm or revise before Stage 2.
4. **Sample group as a first-class entity.** The design treats each piece as an independent transition. If operators routinely send 50-piece sample drops to a single trade show, a "sample drop" entity may be worth adding in a later phase. Not in Stage 1 scope.

---

## 9. Stage 2 implementation prompt skeleton

> *Reference only — do not run from this design doc.*

```
Implement Sample-out Stage 2 per docs/operational-memory/inventory/SAMPLE_OUT_DESIGN.md.

Scope (Stage 2 only):
1. Add SAMPLE_OUT to inventory_state_engine.STATES.
2. Add the two new rows to LEGAL_TRANSITIONS and DEFAULT_TRIGGER per section 1.2.
3. Extend transition() with the SAMPLE_OUT evidence gate per section 1.3
   (mirror the DIRECT_DISPATCH_READY block at lines 254-268).
4. Draft + apply the sample_out_events migration per section 2.3.
5. Add sample_out_writer.py with:
   - precheck for MIGRATION_PENDING
   - precheck for DB_UNAVAILABLE
   - state-gate validation
   - idempotency via UNIQUE(scan_code, idempotency_key) + IntegrityError replay
   - routes through transition() — never UPDATE inventory_state directly
6. Add routes_inventory_sample.py with:
   - POST /api/v1/inventory/pieces/{piece_id}/sample-out
   - POST /api/v1/inventory/pieces/{piece_id}/sample-return
   Both forward to sample_out_writer.py with caller-supplied Idempotency-Key.
7. Extend routes_proforma._stock_status to return "sample_out" when any
   scan_code is in SAMPLE_OUT (section 6.2).
8. Add the UI surfaces in section 5 to dashboard.html.
9. Tests:
   - state engine: every forbidden transition in section 4 raises
   - writer: idempotent replay, 409 on wrong state, 400 on bad evidence,
     503 on missing schema, 503 on missing DB
   - integration: round-trip OUT → RETURN, audit-trail join holds
10. Update PROFORMA_ELIGIBLE_STATES: do NOT add SAMPLE_OUT.
11. Reconciliation Stage 2 adds drift classes 6.1 + 6.2.

Do NOT:
- modify Move stock or its branch
- touch the hybrid-auth branch
- recompute landed cost or any financial value
- bypass transition()
```

---

## Result tag

`READY-FOR-STAGE-2`

The four items in section 8 are non-blocking. Stage 2 can proceed and surface each item for operator confirmation at the first natural decision point.
