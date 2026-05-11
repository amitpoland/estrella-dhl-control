# Risk-2 Button Design Contracts

**Status:** DESIGN ONLY — no implementation in this PR.
**Architecture reference:** Doc 1 v2 (`INVENTORY_STATE_MACHINE.md`), Doc 2 (`BUTTON_REGISTRY.md`), Doc 4 (`FAILURE_MODES.md`).
**Scope:** Two Risk-2 buttons that pair with Phase 4 implementations but exceed the overnight feasibility envelope.

Risk-2 = endpoints that surface existing data via new read shapes. Mostly READ; one (Direct dispatch visibility write path) leans on the orphaned `/api/v1/lifecycle/inventory-state/mark-direct-dispatch` endpoint and only needs UI wiring.

---

## Button 3 — Direct dispatch visibility

### Endpoint contract (READ — proposed)

```
GET /api/v1/inventory/direct-dispatch/{batch_id}
Auth: Depends(require_api_key)
Response:
  {
    "batch_id": <str>,
    "as_of": <ISO8601>,
    "eligible_for_direct_dispatch": [<scan_code>, ...],
    "marked_direct_dispatch_ready": [<scan_code>, ...],
    "dispatched": [<scan_code>, ...],
    "evidence": {
      "customs_cleared":     <bool>,
      "operator_signoff":    <bool|null>,
      "client_allocations":  [{"scan_code": <str>, "client_name": <str>}, ...]
    },
    "degraded": <bool>
  }
```

### Existing pieces it composes (NO new writers)

- `inventory_state_engine.list_by_state("DIRECT_DISPATCH_READY", batch_id=...)` → marked list
- `inventory_state_engine.list_by_state("CLIENT_DISPATCHED", batch_id=...)` → dispatched list
- `inventory_state_engine.list_by_state("PURCHASE_TRANSIT", batch_id=...)` → eligibility candidates (must also have RECEIVE event per engine's existing gate)
- `inventory_movement_events` for the RECEIVE-event check (engine internal helper `_has_receive_event` at `inventory_state_engine.py:197`)
- Audit JSON for `customs_cleared` and `customer_allocation` evidence

### Endpoint contract (WRITE — already exists, just wire UI)

```
POST /api/v1/lifecycle/inventory-state/mark-direct-dispatch
Auth: Depends(require_api_key) (existing)
Status: orphaned — exists at routes_lifecycle.py:469, no UI caller today
Payload (existing):
  { "scan_code": <str>, "operator": <str>, "customs_cleared": true,
    "customer_allocation": {"client_name": <str>}, "evidence_note": <str> }
```

### Test cases needed

- 200 empty (batch with zero pieces in any direct-dispatch state)
- 200 populated (mocked `list_by_state` returning sample piece rows)
- evidence object surfaces `customs_cleared` flag accurately
- 422 on malformed `as_of`
- GET-only — no POST/PUT/PATCH/DELETE on this path
- Service module contains no INSERT/UPDATE/DELETE patterns

### Operator decisions needed before implementation

1. **UI surface:** strip on `BatchDetailPage` (alongside the Phase 4.2 state strip), OR new tab on `BatchDetailPage`, OR per-piece action in the Phase 4.4 drawer?
2. **Eligibility definition:** is "ELIGIBLE" = `PURCHASE_TRANSIT` + RECEIVE event + customs_cleared, or stricter? Doc 1 v2 §4 says the engine's `transition()` already enforces evidence; the read endpoint just surfaces the same gate.
3. **Should the write button be exposed in this PR or held for separate review?** The write endpoint exists but its UI exposure introduces an operator-facing state transition. Lean toward holding for separate Phase (Risk-3 territory).

---

## Button 4 — Inventory event timeline

### Endpoint contract (READ — proposed)

```
GET /api/v1/inventory/events/{batch_id}
Auth: Depends(require_api_key)
Query params (all optional):
  - scan_code   filter to one piece
  - from        ISO8601 lower bound on occurred_at
  - to          ISO8601 upper bound on occurred_at
  - kinds       comma-separated subset of: state, movement
Response:
  {
    "batch_id": <str>,
    "as_of": <ISO8601>,
    "events": [
      {
        "kind": "state" | "movement",
        "scan_code": <str>,
        "occurred_at": <ISO8601>,
        "summary": <str>,        # human-readable one-liner
        "raw": {<original row>}
      }, ...
    ],
    "count": <int>,
    "degraded": <bool>
  }
```

### Existing pieces it composes (NO new writers)

- `inventory_state_engine.get_history(scan_code)` returns `inventory_state_events` rows
- For per-batch view: query `inventory_state_events` joined with `inventory_state` on `scan_code` where `batch_id` matches
- `inventory_movement_events` queried directly via `warehouse_db._connect()` for the movement leg
- Merge both streams chronologically in worker code; tag each event with `kind`

### Test cases needed

- 200 empty (batch with no events)
- 200 single-piece filter via `?scan_code=`
- 200 date-window filter via `?from=`/`?to=`
- 200 `kinds=state` returns only lifecycle events
- 200 `kinds=movement` returns only physical movements
- Sort order = chronological ascending (oldest first)
- 422 on malformed `from`/`to`
- GET-only
- No writes in service source

### Operator decisions needed before implementation

1. **Default page size?** Inventory event volume per batch could grow large. Suggest default `limit=200`, `offset=0` with pagination headers.
2. **Should `inventory_state_events.id` and `inventory_movement_events.id` be exposed verbatim?** They're UUIDs; not PII; default to YES for traceability unless operator objects.
3. **UI placement:** new tab on `BatchDetailPage`, OR section on the Phase 4.4 piece drawer (scoped to one scan_code)?
4. **Refresh strategy:** poll vs. manual refresh button? For overnight feasibility, manual refresh is simpler.

---

## Why these are Risk-2, not Risk-1

Risk-1 (overnight-feasible) = pure thin wrappers over a SINGLE existing engine function. Both Risk-2 endpoints compose data from multiple sources:

- **Direct dispatch visibility** joins `inventory_state` × `inventory_state_events` × audit JSON × `inventory_movement_events` (the RECEIVE-event check)
- **Inventory event timeline** merges TWO event tables chronologically, with optional date and kind filters

Composition logic = more failure modes (cross-DB consistency, ordering bugs, slow queries at scale). Risk-2 ≠ dangerous, but ≠ overnight-trivial either.

---

## What this design does NOT cover

- Write semantics for direct-dispatch operator signoff (held until separate Phase)
- Mass mark-as-eligible (out of scope; one-piece-at-a-time matches the existing orphaned endpoint)
- UI mockups (no JSX in this design doc; Phase 4 patterns provide the precedent)
- Performance budgets (deferred; current data volume per inspector report is 0 rows so academic)

---

## Suggested next implementation prompt skeleton

```
Task: implement GET /api/v1/inventory/direct-dispatch/{batch_id}
Branch: feat/inventory-direct-dispatch-read
Files allowed to edit:
  service/app/services/inventory_direct_dispatch_view.py (NEW)
  service/app/api/routes_inventory.py (extend, read-only)
  service/tests/test_inventory_direct_dispatch_view.py (NEW)
Architecture:
  Compose from inventory_state_engine.list_by_state + audit-JSON read.
  No new writers. Honest empty + honest degraded patterns from Phase 4.1/4.3.
Tests: 6 cases per the contract above. SECURITY review not required for
  a pure read endpoint, but anti-fake grep and write-method grep must
  return zero.
```
