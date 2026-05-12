# Returns Lifecycle Design — Stage 1

Status: **design only** (no implementation, no migration, no deploy).
Scope: design the inventory truth lifecycle for **returned from client**
and **returned to producer**, mirroring the patterns already live in
production for `WAREHOUSE_STOCK`, `SAMPLE_OUT`, move-stock, and the
unified piece timeline.

Branch reality check
- Production HEAD: `a0fcf96` (Stage 2 aggregator counts SAMPLE_OUT, PR
  #21 merged).
- All cited code is on the live `main`.
- `SAMPLE_OUT_DESIGN.md` is referenced from source
  (`inventory_state_engine.py:80-82`) but is not present in this
  worktree — citations below go to runtime code directly.

---

## 0. Two states, not one

The Sample-out model uses **one** lifecycle state (`SAMPLE_OUT`) with a
`direction` column on `sample_out_events`
(`warehouse_db.py:754-804`, `inventory_sample_writer.py:151-180`,
`:261-285`). That works because a sampled piece is physically with a
single recipient class (client) and the lifecycle is symmetric
(out → warehouse).

Returns are not symmetric:
- **RETURNED_FROM_CLIENT** — piece is physically in the warehouse
  receiving area, awaiting QA/regrade. It is inside our four walls.
- **RETURNED_TO_PRODUCER** — piece is physically with the producer.
  It is outside our four walls.

These have different aging rules, different escalation paths, and
different aggregator implications (samples-tile semantics: pieces are
"out at recipient"; returns-tile semantics: pieces are split across
"inbound RMA in warehouse" and "shipped back to producer").

**Decision: two separate states.** This is consistent with the
existing
`inventory_state_engine.STATES` model where each state corresponds to
exactly one physical-custody class
(`inventory_state_engine.py:85-90`).

---

## 1. `RETURNED_FROM_CLIENT` lifecycle

A piece that previously left the warehouse to a client (either as
sold goods via `CLIENT_DISPATCHED` or `SALES_TRANSIT`, or as a sample
via `SAMPLE_OUT`) is being physically received back into the warehouse
for inspection, regrade, or disposition.

Semantically distinct from `SAMPLE_OUT → WAREHOUSE_STOCK` (the
existing clean-return path at `inventory_state_engine.py:114, 127`).
A sample-return is *expected* and *clean*; a `RETURNED_FROM_CLIENT`
event is an unexpected or non-routine return: warranty claim, customer
refusal, post-sample-review rejection, dimension issue, etc.

### Physical custody
- In the warehouse, in the receiving / RMA area.
- Out of saleable stock (excluded from `PROFORMA_ELIGIBLE_STATES`).

### Successor states
- `WAREHOUSE_STOCK` — piece passed QA, restocked.
- `RETURNED_TO_PRODUCER` — piece failed QA, escalated to producer.
- `CLOSED` — piece written off (operator/finance decision).

### Predecessor states
- `CLIENT_DISPATCHED` — RMA after a direct-dispatch shipment.
- `SALES_TRANSIT` — return intercepted before delivery confirmation.
- `SAMPLE_OUT` — sample returned with a problem (alternative to the
  clean `sample_returned` trigger).

### Default trigger
`returned_from_client_received`

---

## 2. `RETURNED_TO_PRODUCER` lifecycle

A piece is being physically shipped back to the producer for rework,
replacement, or settlement. The piece is not in warehouse possession
and is not saleable.

### Physical custody
- With the producer (outside our four walls).
- Out of saleable stock.

### Successor states
- `WAREHOUSE_STOCK` — producer replaced/repaired and shipped back;
  the returned piece becomes fresh stock again. (Equivalent to a
  fresh `PURCHASE_TRANSIT → WAREHOUSE_STOCK` cycle in semantics,
  modelled here as a same-piece restore.)
- `CLOSED` — producer settled (credit note / replacement under
  different scan_code), piece is retired.

### Predecessor states
- `WAREHOUSE_STOCK` — defective stock found in the warehouse, sent
  back without ever going to a client.
- `RETURNED_FROM_CLIENT` — escalated from QA fail.

### Default trigger
`returned_to_producer_shipped`

### Operator decision (resolved)
Whether a `RETURNED_TO_PRODUCER → CLOSED` outcome should retire the
scan_code permanently or allow a future `CLOSED → WAREHOUSE_STOCK`
re-issue path. The existing engine forbids any successor from
`CLOSED` (`inventory_state_engine.py:109` — empty frozenset), so a
re-issue would require either a new scan_code or a new state
(`REISSUED_BY_PRODUCER`).

**Decided: No. `CLOSED` remains terminal. Producer replacements use a
new scan_code.** This preserves the existing `CLOSED`-is-terminal
invariant; no new state, no new transition out of `CLOSED`.

---

## 3. Legal transitions

Additions to `inventory_state_engine.LEGAL_TRANSITIONS`
(`:101-115`). All other entries unchanged.

```
WAREHOUSE_STOCK:       frozenset({SALES_TRANSIT, SAMPLE_OUT,
                                  RETURNED_TO_PRODUCER})

CLIENT_DISPATCHED:     frozenset({CLOSED, RETURNED_FROM_CLIENT})

SALES_TRANSIT:         frozenset({CLOSED, RETURNED_FROM_CLIENT})

SAMPLE_OUT:            frozenset({WAREHOUSE_STOCK, RETURNED_FROM_CLIENT})

RETURNED_FROM_CLIENT:  frozenset({WAREHOUSE_STOCK,
                                  RETURNED_TO_PRODUCER,
                                  CLOSED})

RETURNED_TO_PRODUCER:  frozenset({WAREHOUSE_STOCK, CLOSED})
```

`PROFORMA_ELIGIBLE_STATES` at `:134-136` stays
`{WAREHOUSE_STOCK, DIRECT_DISPATCH_READY, CLIENT_DISPATCHED}` —
returns are explicitly NOT proforma-eligible (mirrors `SAMPLE_OUT`'s
exclusion).

### `DEFAULT_TRIGGER` additions (`:118-128`)

```
(WAREHOUSE_STOCK,      RETURNED_TO_PRODUCER):  "returned_to_producer_shipped"
(CLIENT_DISPATCHED,    RETURNED_FROM_CLIENT):  "returned_from_client_received"
(SALES_TRANSIT,        RETURNED_FROM_CLIENT):  "returned_from_client_received"
(SAMPLE_OUT,           RETURNED_FROM_CLIENT):  "returned_from_client_received"
(RETURNED_FROM_CLIENT, WAREHOUSE_STOCK):       "returned_restocked"
(RETURNED_FROM_CLIENT, RETURNED_TO_PRODUCER):  "returned_escalated_to_producer"
(RETURNED_FROM_CLIENT, CLOSED):                "returned_written_off"
(RETURNED_TO_PRODUCER, WAREHOUSE_STOCK):       "returned_from_producer_restocked"
(RETURNED_TO_PRODUCER, CLOSED):                "returned_to_producer_settled"
```

---

## 4. Forbidden transitions

Forbidden by absence from `LEGAL_TRANSITIONS` (same enforcement
mechanism as the existing `SAMPLE_OUT → anything-but-WAREHOUSE_STOCK`
forbids at `inventory_state_engine.py:110-114`, blocked by the
legality check at `:279-285`):

- `RETURNED_FROM_CLIENT → SAMPLE_OUT` — must restock first
- `RETURNED_FROM_CLIENT → SALES_TRANSIT` — must restock first
- `RETURNED_FROM_CLIENT → CLIENT_DISPATCHED` — direct dispatch from
  RMA is forbidden; piece must pass QA back into stock
- `RETURNED_FROM_CLIENT → DIRECT_DISPATCH_READY` — same reason
- `RETURNED_FROM_CLIENT → PURCHASE_TRANSIT` — backwards in lifecycle
- `RETURNED_TO_PRODUCER → SAMPLE_OUT` — producer-held pieces cannot
  be sampled
- `RETURNED_TO_PRODUCER → SALES_TRANSIT` — producer-held pieces are
  not saleable
- `RETURNED_TO_PRODUCER → CLIENT_DISPATCHED` — same
- `RETURNED_TO_PRODUCER → DIRECT_DISPATCH_READY` — same
- `RETURNED_TO_PRODUCER → RETURNED_FROM_CLIENT` — physical custody
  contradiction (piece is at producer, not at client)
- `RETURNED_TO_PRODUCER → PURCHASE_TRANSIT` — a producer replacement
  is modelled as `RETURNED_TO_PRODUCER → WAREHOUSE_STOCK` directly,
  or `→ CLOSED` followed by a new scan_code's standard intake.
- `CLOSED → anything` — terminal, unchanged from
  `inventory_state_engine.py:109`.

---

## 5. Evidence requirements

Mirrors the Sample-out evidence gate at
`inventory_state_engine.py:307-348` and the
`DIRECT_DISPATCH_READY` gate at `:291-305`. Two new evidence blocks in
`transition()`:

### 5.1 `to_state == RETURNED_FROM_CLIENT`

Required:
- `operator` non-empty
- `return_reason` in `RETURNED_FROM_CLIENT_REASONS` frozenset:
  - `warranty_claim`
  - `customer_refused`
  - `post_sample_review_reject`
  - `dimension_issue`
  - `quality_complaint`
  - `wrong_item_shipped`  *(decided: include from day one; drop later if unused)*
  - `other`
- `source_holder_name` non-empty — the client/recipient who returned
  the piece (mirrors `recipient_client_name` semantic from
  `:316-317`).
- `received_date` ISO 8601, **not in the future**. Inverse of
  `SAMPLE_OUT`'s `expected_return_date` rule at `:325-343` — for an
  inbound receipt the date is by definition in the past or now.
- `linked_origin_event_id` — id of the prior
  `inventory_state_events` row that put the piece in
  `CLIENT_DISPATCHED` / `SALES_TRANSIT` / `SAMPLE_OUT`. Writer fills
  this from `find_origin_*` lookup; raises `NO_OPEN_OUTBOUND_EVENT`
  if no eligible origin is found (mirrors
  `find_origin_sample_out_event` pattern at
  `warehouse_db.py:824-842`).

Optional:
- `carrier_inbound_ref` — RMA ticket / waybill number
- `notes`

### 5.2 `to_state == RETURNED_TO_PRODUCER`

Required:
- `operator` non-empty
- `return_reason` in `RETURNED_TO_PRODUCER_REASONS` frozenset:
  - `defect`
  - `dimension_out_of_spec`
  - `quality_reject`
  - `post_inspection_reject`
  - `recall`
  - `other`
- `producer_name` non-empty (free-text; producer-master integration
  is a separate scoped task and not blocking)
- `expected_resolution_date` ISO 8601, **in the future**. Same shape
  as the Sample-out `expected_return_date` gate at
  `inventory_state_engine.py:325-343`.

Optional:
- `producer_id` — master-data id if known
- `carrier_outbound_ref` — outbound waybill
- `notes`

### 5.3 Successor evidence

Engine evidence gates apply only on entry to the gated state. The
exit transitions (`RETURNED_FROM_CLIENT → WAREHOUSE_STOCK`,
`RETURNED_FROM_CLIENT → RETURNED_TO_PRODUCER`,
`RETURNED_FROM_CLIENT → CLOSED`,
`RETURNED_TO_PRODUCER → WAREHOUSE_STOCK`,
`RETURNED_TO_PRODUCER → CLOSED`) require only the standard
`operator` + `scan_code` arguments — matching the existing
`SAMPLE_OUT → WAREHOUSE_STOCK` pattern
(`inventory_sample_writer.py:287-295`).

The writer is responsible for capturing additional return-cycle
evidence (e.g. QA decision, settlement reference) in the dedicated
`returns_events` table — exactly like
`sample_out_events.direction='return'` at
`warehouse_db.py:786-799`.

---

## 6. Timeline integration

`inventory_piece_view.get_piece_detail()` already composes three
event kinds (`inventory_piece_view.py:39-46, 161-194`):
`lifecycle`, `movement`, `sample`.

### 6.1 New event source

Add a fourth kind: `returns`.

- Source table: `returns_events` (new), schema mirrors
  `sample_out_events` at `warehouse_db.py:754-804`.
- Reader: `warehouse_db.get_returns_history(scan_code)` mirroring
  `get_sample_out_history` at `warehouse_db.py:845-862` (read-only,
  ascending by `occurred_at`, empty list on missing DB).
- Composition in `inventory_piece_view._returns_entries()` mirroring
  `_sample_entries()` at `inventory_piece_view.py:113-131`. Detail
  block carries `direction` (`'from_client' | 'to_producer' |
  'restock' | 'producer_restock'`), `return_reason`,
  `source_holder_name` or `producer_name`,
  `received_date` / `expected_resolution_date`, and
  `linked_origin_event_id`.

### 6.2 Sort + tie-break

Sort key unchanged
(`inventory_piece_view._sort_key` at `:135-140`):
`(occurred_at asc, kind priority asc, event_id asc)`.

`_KIND_PRIORITY` extended (`:35-39`):
```
lifecycle: 0
movement:  1
sample:    2
returns:   3
```

Returns events tie-break **after** sample events because the
typical operational order is "piece at recipient → sample event → piece
returned → returns event" — keeping the sample row above the matching
returns row when both share `occurred_at`.

### 6.3 Drawer rendering

Drawer at `service/app/static/dashboard.html` (Phase B.2 Timeline
section, post-PR #19) renders 3 kinds today. Add a fourth icon:
- `lifecycle` → `◆` (unchanged)
- `movement`  → `→` (unchanged)
- `sample`    → `↗` / `↙` (unchanged)
- `returns`   → `⤺` for inbound (`direction='from_client'`),
                `⤻` for outbound (`direction='to_producer'`).

Sample row's inline recipient/date pattern (post-PR #19) is mirrored
for returns:
- `from_client` rows surface `source_holder_name` + `received_date`.
- `to_producer` rows surface `producer_name` +
  `expected_resolution_date`.

### 6.4 Legacy `history` alias

The `history` field (legacy lifecycle-only subset, preserved one
release per PIECE_TIMELINE_DESIGN.md §7.3) is unchanged — returns
events are not lifecycle events.

---

## 7. Aggregator implications

`inventory_stage2_aggregator.aggregate_stage2()` currently derives
two tiles live (`final_stock`, `samples`) and leaves three null
(`returns`, `consignment`, `unknown`) — see
`inventory_stage2_aggregator.py:75-129`.

### 7.1 `returns` tile becomes live

After Stage 2 implementation, `count_by_state()` will include both
`RETURNED_FROM_CLIENT` and `RETURNED_TO_PRODUCER` (because
`count_by_state` pre-seeds all `STATES` keys at
`inventory_state_engine.py:200`).

Aggregator change:
```
returns.count =
    int(state_counts["RETURNED_FROM_CLIENT"])
  + int(state_counts["RETURNED_TO_PRODUCER"])
returns.basis =
    "inventory_state.state IN ('RETURNED_FROM_CLIENT', 'RETURNED_TO_PRODUCER')"
returns.confidence = "HIGH"
```

Drop `RETURNS_LIMITATION` and the corresponding append at
`inventory_stage2_aggregator.py:42-46, 117`.

Degrade paths: same shape as the new SAMPLE_OUT missing-key path at
`inventory_stage2_aggregator.py:103-110`. If either required key is
absent from a partial mock dict, returns degrades with a targeted
limitation.

### 7.2 `unknown` limitation reworded

`UNKNOWN_LIMITATION` at `inventory_stage2_aggregator.py:52-56` is
worded `"... while returns/consignment are null"`. After Stage 2,
returns is no longer null — text becomes
`"... while consignment is null"`.

### 7.3 Sub-buckets (decided: include from day one)

The brief calls "returns" a single tile. The aggregator returns one
`count` per tile, but the response shape is JSON — adding optional
`subcounts` is non-breaking.

**Decided: include `subcounts.from_client` and `subcounts.to_producer`
in the returns response from the first Stage 2 ship.** The inbound
vs outbound split changes what action the operator takes next, and
the data is free to compute from the same `count_by_state()` call.
Tests pin the shape against fake state-count dicts.

```jsonc
"returns": {
  "count": 7,
  "basis": "inventory_state.state IN ('RETURNED_FROM_CLIENT', 'RETURNED_TO_PRODUCER')",
  "confidence": "HIGH",
  "subcounts": {
    "from_client": 3,
    "to_producer": 4
  }
}
```

### 7.4 No new endpoint

The Stage 2 endpoint `GET /api/v1/inventory/stage2/aggregate` is
unchanged. No new route, no new auth surface.

---

## 8. Aging / escalation rules

### 8.1 `RETURNED_FROM_CLIENT` — QA stall escalation

Pieces in `RETURNED_FROM_CLIENT` represent inventory sitting in the
RMA area awaiting QA decision.

**Decided thresholds:**
- **Soft (amber)**: 7 days since `received_date`. Drawer aging pill
  flips amber (mirrors SAMPLE_OUT aging at the existing
  `_SAMPLE_OVERDUE_DAYS` constant in `dashboard.html` post-Sample-out
  UI deploy — returns are tighter than samples).
- **Hard (red)**: 30 days since `received_date`. Drawer aging pill
  red; operator prompted to escalate to producer or close. No DB-side
  block (RMA pile-up is an operational signal, not a write-gate).

### 8.2 `RETURNED_TO_PRODUCER` — producer SLA

Pieces in `RETURNED_TO_PRODUCER` represent claims open against the
producer. The Sample-out 30-day recipient-overdue block at
`inventory_sample_writer.py:130-145` and the supporting query
`warehouse_db.count_open_overdue_samples_for_recipient` at
`warehouse_db.py:864-890` are the closest existing analogue.

**Decided thresholds:**
- **Soft (amber)**: 30 days since the `RETURNED_TO_PRODUCER` event.
- **Hard (red)**: 60 days since the `RETURNED_TO_PRODUCER` event,
  OR `expected_resolution_date` has passed — whichever is sooner. The
  expected-resolution path means an operator-set deadline always
  trumps the 60d default when it's tighter.
- **No block-new rule** on producer side. Unlike samples (where the
  recipient is a client and the operator can stop sending more
  samples until they return), producer claims are independent.
  Blocking new `WAREHOUSE_STOCK → RETURNED_TO_PRODUCER` against a
  producer with overdue open claims is operationally counterproductive
  — it traps defective stock in saleable inventory. Document
  explicitly: no block, only visibility.

### 8.3 Drawer surfaces

- Lifecycle pill colour for `RETURNED_FROM_CLIENT`: amber (operator
  attention class, matches SAMPLE_OUT tone in
  `dashboard.html` `_STATE_TONE` post-Sample-out UI deploy).
- Lifecycle pill colour for `RETURNED_TO_PRODUCER`: red — the piece
  is outside our possession and represents an open commercial claim.
- Aging pill matches §8.1 / §8.2 thresholds.

### 8.4 No reconciliation engine in this scope

The brief excludes reconciliation. Aging is presentation-only.
A future reconciliation pass can read these states + ages and
surface them as drift candidates.

---

## 9. Failure modes

### 9.1 Origin not found (inbound)

`RETURNED_FROM_CLIENT` requires `linked_origin_event_id` to a prior
outbound event. If no matching `CLIENT_DISPATCHED` / `SALES_TRANSIT` /
`SAMPLE_OUT` event exists for the scan_code, writer returns
`NO_OPEN_OUTBOUND_EVENT` (mirrors `NO_OPEN_SAMPLE_OUT` at
`inventory_sample_writer.py:253-257`). HTTP 409.

### 9.2 Replay / idempotency

Caller-supplied `idempotency_key` enforced by partial UNIQUE index
on `returns_events(scan_code, idempotency_key)` WHERE
`idempotency_key != ''`. On `sqlite3.IntegrityError` matching the
index, writer fetches the prior row and returns `status='replayed'`
with the same `event_id`. Mirrors Sample-out at
`inventory_sample_writer.py:147-180`.

### 9.3 Migration pending

`warehouse_db.ensure_returns_schema()` precheck identical in shape to
`ensure_sample_out_schema()` at `warehouse_db.py:720-751`. Returns
False → writer raises with code `MIGRATION_PENDING` → route maps to
HTTP 503. No traceback leak (`inventory_sample_writer.py:79-84`
pattern).

### 9.4 Wrong state

State-gate check before write (mirrors
`inventory_sample_writer.py:117-128`). Piece must be in one of the
allowed predecessor states per §1 / §2. HTTP 409 `WRONG_STATE`.

### 9.5 Concurrent writes

Same as Sample-out — no app-level lock. DB UNIQUE serialises the
writers (`inventory_sample_writer.py:18-23` doc; same applies).

### 9.6 Aggregator missing-key degrade

If a mock returns a `count_by_state()` dict missing either
`RETURNED_FROM_CLIENT` or `RETURNED_TO_PRODUCER`, the aggregator
degrades the returns tile with limitation
`"returns: <STATE> state missing from count_by_state result"`.
Production never hits this — `count_by_state()` at
`inventory_state_engine.py:200` pre-seeds all `STATES` keys at 0.

### 9.7 Audit-chain orphan

A `RETURNED_FROM_CLIENT → RETURNED_TO_PRODUCER` event must carry a
`linked_inbound_event_id` (the `returns_events` row that recorded the
inbound). If the inbound row cannot be found (e.g. data drift),
writer rejects with `NO_OPEN_INBOUND_RETURNS_EVENT`. Mirrors the
sample-return origin-pair-up pattern at
`inventory_sample_writer.py:248-258`.

---

## 10. Stage 2 implementation plan

Branch: `feat/returns-lifecycle` (cut from `main` after `a0fcf96`).

Mirrors the Sample-out Stage 2 sequence (PR #17) end-to-end.

### Step 1 — Migration draft (manual apply)

`service/app/db/migrations/draft_<ts>_returns_events.py.draft`
mirroring the Sample-out migration at
`service/app/db/migrations/draft_20260512_122327_sample_out_events.py.draft`.

Table:
```
CREATE TABLE returns_events (
  id                       TEXT PRIMARY KEY,
  scan_code                TEXT NOT NULL,
  direction                TEXT NOT NULL,        -- 'from_client' | 'to_producer'
                                                 --                | 'restock'
                                                 --                | 'producer_restock'
                                                 --                | 'close_writeoff'
                                                 --                | 'close_settled'
  operator                 TEXT NOT NULL DEFAULT '',
  source_holder_name       TEXT NOT NULL DEFAULT '',  -- 'from_client' only
  producer_name            TEXT NOT NULL DEFAULT '',  -- 'to_producer' only
  producer_id              TEXT NOT NULL DEFAULT '',
  return_reason            TEXT NOT NULL DEFAULT '',
  received_date            TEXT NOT NULL DEFAULT '',  -- 'from_client'
  expected_resolution_date TEXT NOT NULL DEFAULT '',  -- 'to_producer'
  carrier_inbound_ref      TEXT NOT NULL DEFAULT '',
  carrier_outbound_ref     TEXT NOT NULL DEFAULT '',
  notes                    TEXT NOT NULL DEFAULT '',
  idempotency_key          TEXT NOT NULL DEFAULT '',
  linked_state_event_id    TEXT NOT NULL DEFAULT '',  -- to inventory_state_events.id
  linked_origin_event_id   TEXT NOT NULL DEFAULT '',  -- prior outbound (sample/dispatch)
  linked_inbound_event_id  TEXT NOT NULL DEFAULT '',  -- prior returns_events.id (escalation chain)
  occurred_at              TEXT NOT NULL,
  created_at               TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_returns_idempotency
  ON returns_events(scan_code, idempotency_key)
  WHERE idempotency_key != '';

CREATE INDEX idx_returns_state_lookup
  ON returns_events(scan_code, direction, occurred_at);
```

Idempotent. Operator applies manually before any writer can run.

### Step 2 — State engine

`inventory_state_engine.py`:
- Add `RETURNED_FROM_CLIENT` and `RETURNED_TO_PRODUCER` to `STATES`
  (`:85-90`).
- Add `RETURNED_FROM_CLIENT_REASONS` and
  `RETURNED_TO_PRODUCER_REASONS` frozensets.
- Extend `LEGAL_TRANSITIONS` per §3.
- Extend `DEFAULT_TRIGGER` per §3.
- Add evidence blocks in `transition()` per §5, mirroring the
  existing `DIRECT_DISPATCH_READY` block at `:291-305` and
  `SAMPLE_OUT` block at `:307-348`. New `transition()` kwargs:
  `return_reason`, `source_holder_name`, `producer_name`,
  `producer_id`, `received_date`, `expected_resolution_date`,
  `linked_origin_event_id`, `linked_inbound_event_id`,
  `carrier_inbound_ref`, `carrier_outbound_ref`. All optional;
  evidence gates only consult the ones that apply to the to_state.

### Step 3 — warehouse_db helpers

Add to `warehouse_db.py`:
- `ensure_returns_schema()` — mirror of `ensure_sample_out_schema`
  (`:720-751`).
- `record_returns_event()` — mirror of `record_sample_out_event`
  (`:754-804`).
- `find_returns_event_by_idempotency()` — mirror of
  `find_sample_out_event_by_idempotency` (`:807-821`).
- `find_origin_outbound_event()` — looks up the most recent
  unmatched outbound event (CLIENT_DISPATCHED / SALES_TRANSIT /
  SAMPLE_OUT) for a scan_code. Required for
  `linked_origin_event_id` resolution at the writer layer.
- `find_open_inbound_returns_event()` — mirror of
  `find_origin_sample_out_event` (`:824-842`). Used by escalation
  writes (`RETURNED_FROM_CLIENT → RETURNED_TO_PRODUCER`).
- `count_open_returns_to_producer_for_producer()` — count of open
  to-producer events past `expected_resolution_date` (for aging
  surfaces; no block).
- `get_returns_history(scan_code)` — mirror of
  `get_sample_out_history` and `get_movement_history`. Read-only.

### Step 4 — Writer

`service/app/services/inventory_returns_writer.py` (NEW). Public
functions:
- `return_from_client(scan_code, operator, source_holder_name,
   return_reason, received_date, idempotency_key, ...)`
- `return_to_producer(scan_code, operator, producer_name,
   return_reason, expected_resolution_date, idempotency_key, ...)`
- `restock_from_returns(scan_code, operator, idempotency_key, ...)`
  — handles both `RETURNED_FROM_CLIENT → WAREHOUSE_STOCK` and
  `RETURNED_TO_PRODUCER → WAREHOUSE_STOCK`. Writer reads current
  state to pick the right transition.
- `escalate_to_producer(scan_code, operator, producer_name,
   return_reason, expected_resolution_date, idempotency_key, ...)`
  — `RETURNED_FROM_CLIENT → RETURNED_TO_PRODUCER`. Carries
  `linked_inbound_event_id`.
- `close_returns(scan_code, operator, settlement_ref,
   idempotency_key, ...)` — `*_RETURNED_* → CLOSED`.

Single-writer discipline: never directly mutates `inventory_state`
or `inventory_state_events`. All state changes via
`inventory_state_engine.transition()`. Mirrors
`inventory_sample_writer` discipline (`:1-23`).

### Step 5 — Router

`service/app/api/routes_inventory_returns.py` (NEW). Endpoints under
`/api/v1/inventory`:
- `POST /pieces/{piece_id}/return-from-client`
- `POST /pieces/{piece_id}/return-to-producer`
- `POST /pieces/{piece_id}/returns-restock`
- `POST /pieces/{piece_id}/returns-escalate-to-producer`
- `POST /pieces/{piece_id}/returns-close`

Router-level `Depends(require_api_key)`. Status-code map mirrors the
Sample-out router at
`service/app/api/routes_inventory_sample.py:73-88`.

Existing read-only invariant tests
(`service/tests/test_inventory_*.py`'s `test_no_write_methods_*`
patterns; see `test_inventory_stage2_aggregate.py:88-110` for the
shared allowlist contract evolution) will need 5 additional
allowlisted paths added.

### Step 6 — Aggregator

`inventory_stage2_aggregator.py`:
- Add returns derivation per §7.1.
- Drop `RETURNS_LIMITATION`.
- Reword `UNKNOWN_LIMITATION` per §7.2.
- Optionally add `subcounts` per §7.3 (recommended).

### Step 7 — Piece view + drawer

- `inventory_piece_view.py`: add `_returns_entries()`, extend
  `_KIND_PRIORITY`, plumb new reader. Keep legacy `history` alias
  unchanged (lifecycle-only).
- `service/app/static/dashboard.html`:
  - Extend `_STATE_TONE` for `RETURNED_FROM_CLIENT` (amber) and
    `RETURNED_TO_PRODUCER` (red).
  - Add returns icons (`⤺` / `⤻`) and per-direction inline detail
    block in the Timeline row renderer.
  - Add state-gated action panels for returns transitions (mirrors
    the Sample-out forms post-Sample-out UI deploy).
  - Drop the "(backend pending)" suffix on the Returns Stage 2 tile
    hint added by PR #20 / refined by PR #22; replace with a live
    hint similar to the Samples tile.

### Step 8 — Tests

Mirror the Sample-out test surface (PR #17 + #19 + #21):
- `test_inventory_state_engine_returns.py` — transition legality,
  forbidden-by-absence, evidence gates per §5.
- `test_inventory_returns_writer.py` — happy path, replay,
  state-gate, migration-precheck, origin-not-found,
  inbound-not-found, restock both directions, escalation,
  close.
- `test_inventory_stage2_aggregate.py` — extend for live `returns`
  count + subcounts; drop the
  `test_returns_consignment_unknown_remain_pending` returns
  assertion.
- `test_inventory_piece_view_timeline.py` — extend with
  `returns` kind composition, sort, tie-break.
- `test_dashboard_inventory_piece_drawer.py` — returns icons,
  per-direction inline detail, action panel state-gating.
- `test_dashboard_inventory_stage2_wiring.py` — returns tile
  becomes live.

### Step 9 — Deploy

Same Path-2 pattern. Touches state engine + warehouse_db + new
services + new router + aggregator + dashboard. Migration applies
manually first; then file copy; then elevated restart; then smoke.

---

## Stage 1 deliverables

- `RETURNS_LIFECYCLE_DESIGN.md` (this document).

## Operator decisions (resolved 2026-05-12)

All five Stage 1 decisions accepted by the operator at their proposed
defaults. No overrides; no follow-up questions; no implementation
ambiguity remaining.

| § | Decision | Resolution |
|---|---|---|
| 2   | `RETURNED_TO_PRODUCER → CLOSED` re-issue path? | **No.** `CLOSED` remains terminal. Producer replacements use a new scan_code. |
| 7.3 | Include `subcounts.{from_client,to_producer}` in the returns aggregator response? | **Yes.** Include from day one. |
| 8.1 | Soft / hard aging thresholds for `RETURNED_FROM_CLIENT`? | **7 days soft (amber) / 30 days hard (red).** |
| 8.2 | Soft / hard aging thresholds for `RETURNED_TO_PRODUCER`? | **30 days soft / 60 days hard, OR `expected_resolution_date` if sooner.** No block-new rule. |
| 5.1 | Include `wrong_item_shipped` in `RETURNED_FROM_CLIENT_REASONS`? | **Yes.** Include from day one; drop later if unused. |

---

## Result tag

**READY-FOR-STAGE-2**

All Stage 1 operator decisions are resolved. The design has no
remaining open questions. Stage 2 implementation can start against
the plan in §10.
