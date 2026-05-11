# SECURITY REVIEW FAILED — feat/inventory-button-move-stock

**Branch:** `feat/inventory-button-move-stock`
**Phase:** 4.5 (Move stock — location metadata write)
**Date:** 2026-05-11 overnight campaign
**Reviewer:** security-write-action-reviewer (subagent)
**Verdict:** **FAIL** — must NOT be merged in current form.

## Headline

Idempotency check has a **SELECT-then-INSERT race window**. Two concurrent POSTs with the same `idempotency_key` both pass the lookup, both fall through to `record_scan`, and both write `inventory_movement_events` rows. Multi-write violates the idempotency contract documented in the endpoint's response shape.

## What was implemented (and parked as `.draft`)

Files committed on this branch with `.py.draft` suffix (NOT picked up by Python import; matches the campaign-spec convention for unready code):

- `service/app/services/inventory_location_writer.py.draft` — service module
- `service/app/api/routes_inventory_writes.py.draft` — write router
- `service/tests/test_inventory_move_stock.py.draft` — 11 test cases (10 pass; race not covered by current tests)

Intended endpoint:

```
POST /api/v1/inventory/pieces/{piece_id}/location
{
  "to_location": "WH-A1",
  "operator": "tester",
  "idempotency_key": "key-001",
  "note": ""
}
```

Auth: router-level `Depends(require_api_key)`.
State change: NONE (location metadata only; lifecycle state preserved).
Doc 2 row reference: button #2 "Move stock", Risk-1.

## Full review checklist (10 items)

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | Auth dependency | PASS | router-level `Depends(require_api_key)` |
| 2 | **Idempotency under concurrent calls** | **FAIL** | SELECT in `_find_prior_idempotent_event` NOT serialized with INSERT in `record_scan` |
| 3 | Rollback path | PASS_WITH_CAVEAT | `from_location` captured in event row; API response hides it from caller |
| 4 | PII leakage in logs | PASS | zero loggers in writer; delegated warehouse_db logs are operator-name only |
| 5 | Execution-route bypass | PASS | no `.transition(` call in writer; test enforces |
| 6 | Anti-fake grep | PASS | 0 hits |
| 7 | Write-path grep matches declared | PASS | 1 POST in router, 0 direct SQL writes in service |
| 8 | State-gate enforcement | PASS | `WRONG_STATE` raised before any write |
| 9 | Path collision | PASS | distinct method+path |
| 10 | DB-unavailable handling | PASS | 503 with static detail, no traceback leak |

## Root cause (check 2 detail)

In `inventory_location_writer.py.draft` lines 43–63, `_find_prior_idempotent_event` opens its own `_connect()` WITHOUT acquiring `wdb._lock`. The lock is only acquired later inside `warehouse_db.record_scan` (line ~406).

Race window:

```
T1 SELECT (no match)  →  T2 SELECT (no match)
T1 acquires _lock     →  T2 waits
T1 INSERT (commits, releases lock)
T2 acquires _lock     →  T2 INSERT (commits)
Result: two rows with the same [idem:KEY] marker.
```

There is no UNIQUE constraint on `(scan_code, idempotency_key)` in `inventory_movement_events` schema, so SQLite does not catch the duplicate.

## Remediation options (operator picks)

**Option A — Schema change (preferred for correctness):**
Add a dedicated `idempotency_key` column to `inventory_movement_events` with a UNIQUE index on `(scan_code, idempotency_key)`. Catch `sqlite3.IntegrityError` in the writer and fall back to the replay path. Lock-free, durable across process restarts. Requires a migration.

**Option B — Lock extension (short-term mitigation):**
Hold `wdb._lock` across both `_find_prior_idempotent_event` AND `record_scan`. No migration required. Serializes ALL move-stock writes through a single in-process lock. Sufficient for the current single-process NSSM `PZService` deployment but breaks under multi-worker.

## Minor caveats noted (do not block)

- **Check 3:** the API response hardcodes `"from_location": ""` and `"event_id": None`. The audit row in `inventory_movement_events` HAS this info; the response just doesn't echo it. Minor UX gap if operator UI wants a one-click reverse-move.
- **Check 8 replay semantics:** idempotent replay does NOT re-check current state. Safe (no write occurs) but worth a code comment.

## Operator action required

1. Choose remediation Option A or B.
2. Apply the fix to the `.draft` files, rename back to `.py`, re-run tests, re-run security review.
3. Once PASS, commit + push for normal review.

Until then, **do not merge** `feat/inventory-button-move-stock`. The `.draft` suffix prevents accidental activation if someone does merge.

## Branch state on push

- `.py.draft` files committed (code preserved for operator triage)
- `main.py` NOT modified (no router include)
- 0 new endpoints registered with the app
- 0 production-importable surface added

Nothing in this branch is reachable from the running service until the operator renames the `.draft` files and adds the import.
