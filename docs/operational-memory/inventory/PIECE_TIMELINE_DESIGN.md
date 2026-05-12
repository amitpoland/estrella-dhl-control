# Piece Timeline Design — Stage 1

Status: **design only** (no implementation, no migration, no deploy).
Scope: design unified per-piece chronology that merges lifecycle
transitions, physical location moves, and Sample-out evidence into one
operator-facing timeline.

Branch reality check
- Production HEAD: `fe9c1ba` (Sample-out UI deployed 2026-05-12).
- All Phase B.1 backend writers + routes are live (see §5 below for
  file:line citations).
- `SAMPLE_OUT_DESIGN.md` is referenced from source
  (`inventory_state_engine.py:82`, `dashboard.html` `_STATE_TONE`
  comment) but is **not present in this worktree** — citations below
  go to the runtime code directly, which is the source of truth.

---

## 0. Glossary

| Term | Meaning |
|------|---------|
| Lifecycle event | Row in `inventory_state_events` — append-only audit of state transitions. |
| Movement event | Row in `inventory_movement_events` — append-only audit of physical location changes. |
| Sample event | Row in `sample_out_events` — append-only audit of sample-out / sample-return evidence. |
| State row | Current row in `inventory_state` — one per `scan_code`. |
| Location row | Current row in `inventory_current_location` — one per `scan_code`. |
| Single-writer discipline | All state changes go through `inventory_state_engine.transition()`; no service mutates `inventory_state` directly. |

---

## 1. Current event sources

Three append-only event tables exist in `warehouse.db`, written by
three different services. Each table is the audit anchor for one
class of operator action.

### 1.1 `inventory_state_events` — lifecycle transitions

- Writer: `inventory_state_engine.transition()` — see
  `service/app/services/inventory_state_engine.py:378-385`
  (single `INSERT` per transition inside the same transaction as the
  `inventory_state` upsert).
- Reader: `inventory_state_engine.get_history()` — see
  `service/app/services/inventory_state_engine.py:167-177` (ordered by
  `occurred_at`).
- Currently surfaced via `GET /api/v1/inventory/pieces/{piece_id}` —
  `service/app/api/routes_inventory.py:57-71` and the underlying
  `inventory_piece_view.get_piece_detail()` at
  `service/app/services/inventory_piece_view.py:16-56`. Field name in
  the response: `history` (a list of these rows).

### 1.2 `inventory_movement_events` — physical location changes

- Writer: `warehouse_db.record_scan_with_idempotency(action="MOVE", ...)`
  called by `inventory_location_writer.move_piece()` — see
  `service/app/services/inventory_location_writer.py:121-147` and the
  underlying INSERT at `service/app/services/warehouse_db.py:568-575`.
- Reader: `warehouse_db.get_movement_history(scan_code)` — see
  `service/app/services/warehouse_db.py:679-688` (ordered by
  `event_time`).
- **Not currently surfaced anywhere on the piece drawer.** The drawer's
  `history` array contains only lifecycle events. Operators cannot see
  location moves in the unified piece view today.

### 1.3 `sample_out_events` — Sample-out / Sample-return evidence

- Writer: `warehouse_db.record_sample_out_event()` — see
  `service/app/services/warehouse_db.py:754-804`. Called from
  `inventory_sample_writer.sample_out()` (lines 150-161) and
  `inventory_sample_writer.sample_return()` (lines 261-269).
- Readers:
  - `warehouse_db.find_sample_out_event_by_idempotency()` —
    `service/app/services/warehouse_db.py:807-821` (replay lookup).
  - `warehouse_db.find_origin_sample_out_event()` —
    `service/app/services/warehouse_db.py:824-842` (pair-up lookup).
  - `warehouse_db.count_open_overdue_samples_for_recipient()` —
    `service/app/services/warehouse_db.py:845-871` (30d block-new gate).
- **No "list all sample events for a scan_code" reader exists yet.**
  The data is captured per-piece but never read back as a list. This is
  a known gap (§7.1 below).
- **Not currently surfaced on the piece drawer.** Operators see the
  state transition row (`WAREHOUSE_STOCK → SAMPLE_OUT`,
  `trigger='sample_out_marked'`) but not the recipient name,
  `expected_return_date`, or `sample_reason`.

### 1.4 Current state / current location (not events — snapshots)

- `inventory_state` (current row per `scan_code`) — read via
  `inventory_state_engine.get_state()` at
  `service/app/services/inventory_state_engine.py:155-164`. Already
  surfaced in the drawer as `pieceDetail.state`.
- `inventory_current_location` (current row per `scan_code`) — read via
  `warehouse_db.get_current_location()` (called inside
  `inventory_location_writer.py:136`). **Not currently surfaced on the
  piece drawer.** Operators can see "warehouse stock" in the lifecycle
  pill but cannot see the actual rack/shelf code without leaving the
  drawer.

---

## 2. Existing fields per source

All citations are to the live runtime, not aspirational schema.

### 2.1 `inventory_state_events` row

Columns from the INSERT at `inventory_state_engine.py:378-385`:

| Field         | Type | Notes                                                          |
|---------------|------|----------------------------------------------------------------|
| `id`          | TEXT | UUID, primary key                                              |
| `scan_code`   | TEXT | piece id                                                       |
| `from_state`  | TEXT | empty string on first row                                      |
| `to_state`    | TEXT | one of `inventory_state_engine.STATES` (`:85-90`)              |
| `trigger`     | TEXT | from `DEFAULT_TRIGGER` (`:118-128`) or caller override         |
| `occurred_at` | TEXT | ISO 8601 UTC                                                   |
| `operator`    | TEXT | operator id                                                    |
| `note`        | TEXT | free-text                                                      |

### 2.2 `inventory_movement_events` row

Columns from the INSERT at `warehouse_db.py:568-575`:

| Field             | Type | Notes                                                  |
|-------------------|------|--------------------------------------------------------|
| `id`              | TEXT | UUID, primary key                                      |
| `batch_id`        | TEXT | from packing_lines                                     |
| `scan_code`       | TEXT | piece id                                               |
| `action`          | TEXT | `"MOVE"` for location-writer, other values exist       |
| `from_location`   | TEXT | empty string on first row                              |
| `to_location`     | TEXT | warehouse location code                                |
| `operator`        | TEXT | operator id                                            |
| `event_time`      | TEXT | ISO 8601 UTC (note: NOT `occurred_at`)                 |
| `note`            | TEXT | free-text; may carry `[UNKNOWN_LOCATION: …]` warning   |
| `created_at`      | TEXT | ISO 8601 UTC                                           |
| `idempotency_key` | TEXT | partial UNIQUE index when non-empty                    |

### 2.3 `sample_out_events` row

Columns from migration draft at
`service/app/db/migrations/draft_20260512_122327_sample_out_events.py.draft:64-80`
and the INSERT at `warehouse_db.py:786-799`:

| Field                    | Type | Notes                                                |
|--------------------------|------|------------------------------------------------------|
| `id`                     | TEXT | UUID, primary key                                    |
| `scan_code`              | TEXT | piece id                                             |
| `direction`              | TEXT | `'out'` or `'return'`                                |
| `operator`               | TEXT | operator id                                          |
| `recipient_client_name`  | TEXT | populated on `out`; empty on `return`                |
| `recipient_client_id`    | TEXT | optional master-data id                              |
| `sample_reason`          | TEXT | enum (`inventory_state_engine.SAMPLE_OUT_REASONS`, `:93-99`) |
| `expected_return_date`   | TEXT | ISO 8601 date; empty on `return`                     |
| `notes`                  | TEXT | free-text                                            |
| `idempotency_key`        | TEXT | partial UNIQUE index when non-empty                  |
| `linked_state_event_id`  | TEXT | FK-equivalent to `inventory_state_events.id` — **currently always empty** (see §7.2) |
| `linked_origin_event_id` | TEXT | FK-equivalent linking a `return` row back to its originating `out` row; populated by `sample_return()` (`inventory_sample_writer.py:268`) |
| `occurred_at`            | TEXT | ISO 8601 UTC                                         |
| `created_at`             | TEXT | ISO 8601 UTC                                         |

### 2.4 Current snapshots (read-only, for header pane)

| Source row                          | Key fields available |
|-------------------------------------|----------------------|
| `inventory_state` (current state)   | `scan_code, product_code, design_no, batch_id, state, updated_at, updated_by, note` |
| `inventory_current_location`        | `scan_code, current_location, current_status, updated_at, updated_by` |

---

## 3. Proposed unified timeline response shape

Single endpoint returns one timeline array per `scan_code`, plus the
existing snapshot fields the drawer already reads.

```jsonc
{
  "piece_id":  "SCAN-001",
  "as_of":     "2026-05-12T13:30:00Z",
  "found":     true,
  "degraded":  false,
  "state":     { /* inventory_state row, unchanged from today */ },
  "location":  { /* inventory_current_location row (new) */ },

  "timeline": [
    {
      "kind":        "lifecycle",          // 'lifecycle' | 'movement' | 'sample'
      "occurred_at": "2026-05-01T09:12:00Z",
      "operator":    "warehouse_op_1",
      "event_id":    "<uuid>",
      "summary":     "PURCHASE_TRANSIT -> WAREHOUSE_STOCK",
      "detail": {
        "from_state": "PURCHASE_TRANSIT",
        "to_state":   "WAREHOUSE_STOCK",
        "trigger":    "warehouse_receive",
        "note":       ""
      }
    },
    {
      "kind":        "movement",
      "occurred_at": "2026-05-02T14:05:00Z",
      "operator":    "warehouse_op_2",
      "event_id":    "<uuid>",
      "summary":     "moved to A-12-3",
      "detail": {
        "action":        "MOVE",
        "from_location": "RECEIVING",
        "to_location":   "A-12-3",
        "note":          ""
      }
    },
    {
      "kind":        "sample",
      "occurred_at": "2026-05-09T11:42:00Z",
      "operator":    "sales_op_1",
      "event_id":    "<uuid>",
      "summary":     "sample-out to Estrella Boutique (customer_review)",
      "detail": {
        "direction":             "out",
        "recipient_client_name": "Estrella Boutique",
        "recipient_client_id":   "",
        "sample_reason":         "customer_review",
        "expected_return_date":  "2026-05-23",
        "linked_origin_event_id": "",
        "notes":                 ""
      }
    }
  ],

  "limitations": [
    /* Empty when all three sources read cleanly. Each element is a
       short string naming the source that degraded, mirroring the
       Stage 2 aggregator's pattern. Examples:
         "movement_events: warehouse_db unavailable"
         "sample_events: migration not applied"
    */
  ]
}
```

### Rationale for the envelope

- One array, one sort key (`occurred_at`), one `kind` discriminator —
  the drawer doesn't have to merge or interleave on the client.
- Each event keeps a stable `event_id` so future tools (linking,
  permalinks) work without re-derivation.
- `summary` is server-rendered for consistency — the drawer can show
  it verbatim or build a custom row from `detail`.
- `limitations` mirrors the existing `inventory_stage2_aggregator`
  envelope shape (see `routes_inventory.py:44-54`), so the operator
  pattern for "this source degraded" stays uniform across endpoints.
- `degraded: true` at the top level when ANY source raised, same
  semantics as `inventory_piece_view.py:36-44` today.

---

## 4. Sorting and grouping rule

### 4.1 Primary sort

- All three event kinds carry an ISO 8601 timestamp:
  - lifecycle: `inventory_state_events.occurred_at`
  - movement:  `inventory_movement_events.event_time` (normalised to
    `occurred_at` in the response)
  - sample:    `sample_out_events.occurred_at`
- Server merges and sorts the unioned list **ascending by `occurred_at`
  string compare**. SQLite stores all three as TEXT in
  `_now()`-produced ISO 8601 UTC (`warehouse_db.py:783` uses `_now()`;
  `inventory_state_engine.py:380-385` uses the same `now` variable
  set above the INSERT block; movement events use the same `now` set
  at `warehouse_db.py:567`-ish). String compare is correct because
  the format is fixed-width ISO 8601 UTC.

### 4.2 Tie-break

When two events share `occurred_at` to the microsecond — common when a
single writer commits state + movement in the same transaction (none
do this today, but a future composite write might) — break ties by:

1. `kind` precedence: `lifecycle` before `movement` before `sample`
   (mirrors causality — a transition usually precedes the side-effect
   write).
2. `event_id` ascending (UUID lex order; stable but arbitrary).

### 4.3 Grouping

**No server-side grouping.** Same-day grouping is a presentation
concern. The drawer can group by day for display (§6) but the API
returns a flat list so other consumers (timeline export, reconciliation
diff tool) get raw data.

---

## 5. Which endpoint should expose it

### Option A — Extend the existing piece view (recommended)

`GET /api/v1/inventory/pieces/{piece_id}` already returns
`state + history`. Replace `history` with `timeline` and add `location`
to the envelope.

- Pros:
  - One round-trip; the drawer already calls this endpoint.
  - Backwards-compatible if `history` stays as an alias (see §7.3).
  - No new auth surface, no new router file.
- Cons:
  - Larger payload per call. For pieces with hundreds of movements
    this could grow; mitigation in §8.5.
  - Renaming `history → timeline` is a breaking field change for any
    other consumer. **Mitigation**: keep `history` populated as the
    `kind == 'lifecycle'` subset for one release cycle.

### Option B — New endpoint `/pieces/{piece_id}/timeline`

- Pros:
  - Existing tests (`test_inventory_piece_view.py:43-94`) keep
    asserting the today-shape unchanged.
  - Clear separation: snapshot vs. chronology.
- Cons:
  - Drawer needs two GETs (snapshot + timeline) and must sequence them
    for the post-write refresh after sample-out / sample-return.
  - Doubles auth/security review surface.

**Recommendation:** Option A with a one-release transitional
`history` alias. Cleaner UX, half the round-trips, same auth posture.

The service-level entrypoint is the existing
`inventory_piece_view.get_piece_detail()` at
`service/app/services/inventory_piece_view.py:16-56`. The Stage 2
implementation should extend that function, NOT create a parallel one.

---

## 6. Drawer UI display proposal

Builds on the existing drawer at
`service/app/static/dashboard.html` around the "Phase B.1" comment
inside `InventoryPage` (the React component the operator already
interacts with). No layout reshuffle — additive only.

### 6.1 Header pane (snapshots)

- Existing: lifecycle pill + aging pill (already shipped on `fe9c1ba`).
- **Add**: current location chip below the pill. Example:
  `📍 A-12-3` (text only — no graphic). Source:
  `location.current_location` from the new envelope field.
  Falls back to "—" when null.
- Existing: scan/product/design/batch/updated rows stay.

### 6.2 Unified Timeline section (replaces existing "History")

- Section title: **Timeline** (replaces today's `History` label).
- Rendered as a vertical list, one `<li>` per `timeline` element,
  newest-last (ascending) to match `occurred_at` order.
- Each row:
  - Left gutter: 1-char kind icon (`◆` lifecycle, `→` movement,
    `↗`/`↙` sample-out/sample-return).
  - Bold: `event.summary`.
  - Below in `--text-3`: `event.occurred_at · event.operator`.
  - Optional 1-line detail under summary when `kind == 'sample'`
    (recipient + expected return date) — this is the operator-asked
    "recipient visibility" item, surfaced finally.

- `data-testid` plan (matches existing conventions):
  - `inventory-piece-drawer-timeline` on the `<ul>`.
  - `inventory-piece-drawer-timeline-row` on each `<li>`, with
    `data-kind="<kind>"` for state-aware tests.
  - `inventory-piece-drawer-timeline-empty` when array is empty.

### 6.3 Limitations chip

When `limitations[]` is non-empty, render a small `--badge-amber`
chip under the Timeline header listing the degraded sources. Same
visual pattern as the Stage 2 aggregator limitations notice on the
Inventory page (already in `dashboard.html`).

### 6.4 What the drawer should NOT do

- No client-side merge of three arrays. The server returns one
  sorted array.
- No client-side date grouping for v1 — keep the diff narrow.
  Day-grouping can be a later display enhancement once operators
  use the unified list.
- No mutation buttons in the timeline rows. Actions stay in the
  existing Sample-out / Sample-return / (future) Move stock panel.

---

## 7. Missing fields / blockers

These are gaps in the current data plane that the Stage 2
implementation either has to fill or work around.

### 7.1 No "list sample events for scan_code" reader (BLOCKER)

`warehouse_db.py` has `find_sample_out_event_by_idempotency` and
`find_origin_sample_out_event` but no
`get_sample_out_history(scan_code)`. Stage 2 must add a thin reader
that returns all rows for a scan_code ordered by `occurred_at`.

- Required follow-up: add `get_sample_out_history(scan_code)` to
  `warehouse_db.py` mirroring the shape of `get_movement_history()`
  at `:679-688`. Read-only; no migration; no contract change.

### 7.2 `linked_state_event_id` is always empty (DATA QUALITY)

`record_sample_out_event()` accepts `linked_state_event_id`
(`warehouse_db.py:765`), but neither `sample_out()` nor
`sample_return()` in `inventory_sample_writer.py` populate it
(see writer code at `:151-161` and `:262-269` — both omit the kwarg).
This means we cannot trivially join a `sample_out_events` row back to
the exact `inventory_state_events` row that recorded the transition.

- Impact on timeline: low — the timeline doesn't need the join because
  it shows both rows separately as different `kind`s. Same `occurred_at`
  ties them visually via sort order.
- Required follow-up (optional, not blocking): populate
  `linked_state_event_id` so the audit chain is hard-linked. Either
  refactor `transition()` to return the event_id it just inserted
  (`inventory_state_engine.py:378-385` already has the id available
  locally but doesn't return it) or have the writer query
  `inventory_state_events` for the most-recent row for that scan_code
  immediately after `transition()` returns. The former is cleaner.

### 7.3 `history` field rename (CONTRACT)

The existing piece-view returns `history` (lifecycle events only).
Stage 2 either:
- Renames it to `timeline` (broader semantic) — breaks any test or
  consumer asserting the field name. Pre-existing tests reference
  `history`: `service/tests/test_inventory_piece_view.py:46, 93, 105`.
- Or keeps `history` as a derived alias = `[e for e in timeline if
  e.kind == 'lifecycle']` for one release.

- Required follow-up: operator decision on rename-vs-alias. Default
  recommendation: alias for one release.

### 7.4 Movement events are gated behind the idempotency migration

`get_movement_history()` is safe to call (returns `[]` when
`_db_path` is None — `warehouse_db.py:680-681`), but the idempotency
migration must be applied for any moves to exist in the first place.
Pre-migration `inventory_movement_events` rows from older flows lack
`idempotency_key` — they'd still show up in the timeline because
`get_movement_history` doesn't filter on that column.

- No follow-up required; behaviour is correct.

### 7.5 No recipient-side visibility in current location row

`inventory_current_location` does not track "currently at recipient X".
When a piece is in SAMPLE_OUT, its `inventory_current_location` row
still shows the last warehouse location. The drawer should source
recipient-when-out from the most-recent open `sample_out_events.out`
row, not from `inventory_current_location`.

- Required follow-up: the unified envelope's `location` field should
  carry a derived `effective_holder` string when state is SAMPLE_OUT.
  Computed server-side as `recipient_client_name` from the open
  sample event. Marked "recipient" vs "warehouse" via a separate
  field so the drawer doesn't conflate them.

### 7.6 SAMPLE_OUT_DESIGN.md not present in worktree

The design reference document is cited from source (engine line 82,
dashboard tone-table comment) but the file itself isn't in this
branch. Not a blocker for timeline design — the runtime code is
authoritative — but operator may want to regenerate/locate that file
before Stage 2 starts, for §8 of that doc which is referenced from
`inventory_sample_writer.py:40` (the 30-day rule).

---

## 8. Test plan (Stage 2)

All tests live in `service/tests/` and follow the existing patterns
visible in `test_inventory_piece_view.py`.

### 8.1 Backend unit tests

- `test_inventory_piece_view_timeline.py` (new):
  - `test_timeline_merges_three_sources` — patch the three readers,
    assert the returned `timeline` interleaves correctly by
    `occurred_at`.
  - `test_timeline_kind_discriminator` — each entry has a `kind` in
    `{lifecycle, movement, sample}`.
  - `test_timeline_summary_lifecycle_format` — lifecycle summary is
    `"<from> -> <to>"` (or `"-> <to>"` on first row).
  - `test_timeline_summary_movement_format` — `"moved to <loc>"` /
    `"moved <from> -> <to>"`.
  - `test_timeline_summary_sample_out_format` — includes
    `recipient_client_name` + `sample_reason`.
  - `test_timeline_summary_sample_return_format` — references the
    linked origin event id when present.
  - `test_timeline_tiebreak_on_equal_occurred_at` — lifecycle wins.
  - `test_timeline_empty_for_unknown_scan` — found=False, timeline=[].
  - `test_timeline_degraded_when_movement_reader_raises` —
    `degraded=True`, `limitations` lists `movement_events: …`.
  - `test_timeline_degraded_when_sample_reader_raises` — same shape.
  - `test_history_alias_preserved` (only if §7.3 chooses alias) —
    `response["history"] == [e for e in response["timeline"] if e["kind"]=="lifecycle"]`.

- `test_warehouse_db_sample_history_reader.py` (new):
  - `test_get_sample_out_history_returns_chronological_rows`.
  - `test_get_sample_out_history_empty_for_unknown_scan`.
  - `test_get_sample_out_history_no_writes` — function does not write
    to any table (source-grep for `INSERT|UPDATE|DELETE` inside the
    new function).

### 8.2 Route-level tests

- Extend `service/tests/test_inventory_piece_view.py` (existing file
  at `:1-145`):
  - Adjust `test_envelope_schema` (currently `:43-47`) to expect
    `timeline` (and `history` if aliased) and `location`.
  - Adjust `test_found_piece_returns_state_and_history` to assert the
    new envelope while keeping the existing fake state pattern.
  - Add `test_route_remains_get_only` style is already there at
    `:23-30, 110-131` — no change needed; the route stays read-only.

### 8.3 Single-writer invariant tests (unchanged)

- `test_no_db_writes_in_aggregator_source` pattern already exists at
  `test_inventory_stage2_aggregate.py:111-139`. Mirror it for the
  timeline service: `test_no_db_writes_in_piece_view_source`.

### 8.4 UI tests

- Extend `service/tests/test_dashboard_inventory_piece_drawer.py`:
  - `test_drawer_renders_timeline_testid` — `inventory-piece-drawer-timeline`
    is present in the JSX source.
  - `test_drawer_renders_location_chip` — `data-testid` for the new
    location chip.
  - `test_drawer_handles_empty_timeline` — `inventory-piece-drawer-timeline-empty`
    branch is in source.
  - `test_drawer_does_not_invent_history_field` — no `history.map(`
    pattern outside the alias-preserve fallback.

- Source-grep test: the drawer's POST allowlist (added in Sample-out UI
  commit) still passes — `_postSample('sample-out'` and
  `_postSample('sample-return'` remain the only POST surfaces.

### 8.5 Pagination / size

- For Stage 2 default: no pagination. Return the full timeline.
- Add an upper bound test: `test_timeline_does_not_exceed_500_events`
  — if any single piece exceeds 500 events (currently nowhere close;
  worst observed piece has < 10 in production), the server truncates
  to the most-recent 500 and adds `"timeline_truncated"` to
  `limitations[]`. Implement as a guard, not a requirement.

---

## 9. Stage 2 implementation plan

Branch: `feat/piece-timeline` (cut from `main` after `fe9c1ba`).

### Step 1 — Backend reader (warehouse_db)

- Add `get_sample_out_history(scan_code)` to `warehouse_db.py`,
  mirroring `get_movement_history()` at `:679-688`. SQL:
  `SELECT * FROM sample_out_events WHERE scan_code=? ORDER BY occurred_at`.
- No migration. Read-only.

### Step 2 — Service composition (inventory_piece_view)

- Rewrite `get_piece_detail()` at
  `service/app/services/inventory_piece_view.py:16-56` to compose
  three readers + two snapshots:
  - `inventory_state_engine.get_state(piece_id)`
  - `warehouse_db.get_current_location(piece_id)` (new field
    `location`)
  - `inventory_state_engine.get_history(piece_id)` → lifecycle events
  - `warehouse_db.get_movement_history(piece_id)` → movement events
  - `warehouse_db.get_sample_out_history(piece_id)` → sample events
- Each reader call wrapped in `try/except Exception` (mirroring the
  existing pattern at `:34-44`) that populates `limitations[]` and
  sets `degraded=True` for that source.
- Merge → sort by `occurred_at` → tie-break per §4.2 → emit unified
  `timeline` array with `kind` + `summary` + `detail`.
- Keep `history` as derived alias if §7.3 chooses alias path.

### Step 3 — Route layer

- `service/app/api/routes_inventory.py:57-71` stays as the entrypoint.
  No new route. No new auth. The response shape change is the only
  diff.

### Step 4 — Drawer wiring

- `service/app/static/dashboard.html` `InventoryPage` — replace the
  current `History` section with the unified `Timeline` section per §6.
- Render `location` chip below the lifecycle pill row.
- Add `limitations` chip when array is non-empty.
- No new POST. No change to `_postSample`. No change to the
  Sample-out / Sample-return forms.

### Step 5 — Tests

- All tests per §8. Existing assertions on `pieceDetail.history` are
  preserved by the alias (or updated to `pieceDetail.timeline` with
  a contract evolution comment if rename path is chosen).

### Step 6 — Manual smoke (post-merge, pre-deploy)

- Look up a piece in WAREHOUSE_STOCK → see lifecycle row(s) + movement
  row(s) interleaved by time; location chip shows current rack.
- Look up a piece in SAMPLE_OUT → see the sample-out row with
  recipient + expected return date inline; aging pill matches.
- Look up a returned piece → see paired sample-out + sample-return
  rows with the return showing `linked_origin_event_id` reference.

### Step 7 — Deploy

Same Path-2 mechanism as Sample-out UI (static-file + service Python).
This deploy DOES touch service Python (inventory_piece_view.py +
warehouse_db.py reader addition), so it requires elevated restart
and the full operator handshake. No migration.

---

## Result tag

**READY-FOR-STAGE-2**

Three blockers were identified and resolved inline:

- §7.1 (`get_sample_out_history` reader missing) → Stage 2 Step 1
  adds it; trivial scope.
- §7.2 (`linked_state_event_id` always empty) → marked optional, not
  blocking; timeline works without the hard link.
- §7.3 (`history` rename) → default to alias-for-one-release; operator
  can override on Stage 2 PR.

No operator decision required before implementation can begin.
