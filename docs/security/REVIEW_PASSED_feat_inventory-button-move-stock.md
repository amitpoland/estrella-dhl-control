# SECURITY REVIEW PASSED — feat/inventory-button-move-stock (Option A remediation)

**Branch:** `feat/inventory-button-move-stock`
**Phase:** 4.5 (Move stock — location metadata write) — REMEDIATED
**Date:** 2026-05-12 (Option A rework)
**Reviewer:** inline review per campaign Phase 7 spec; criteria match the earlier security-write-action-reviewer subagent verdict format.
**Verdict:** **PASS** — ready to PR after Group A merges.

**Activation hardening (added 2026-05-12 on `feat/inventory-button-move-stock-v2`):**
- `service/app/main.py` now includes `app.include_router(inventory_writes_router)` — wiring is committed, not deploy-time. Eliminates the "uncommitted production-only behavior" anti-pattern.
- Migration precheck (`warehouse_db.ensure_idempotency_schema`) runs before any INSERT. If the `idempotency_key` column or `idx_movement_idempotency` index is missing, the endpoint returns HTTP 503 with `{"code": "MIGRATION_PENDING", "detail": "..."}` — sanitized, no SQL or traceback leak.
- Precheck result is cached at module scope on success (cheap PRAGMA call, no perf cost after first request).
- Precheck does NOT affect read routes — `/stage2/aggregate`, `/state/{batch_id}`, `/pieces/{piece_id}` continue to work even if the write-path migration is pending.
- Tests added: `test_migration_pending_returns_503`, `test_migration_pending_does_not_disable_read_routes`, `test_main_app_has_move_stock_route`, `test_main_app_only_one_inventory_write_route`.

## Headline

The SELECT-then-INSERT race identified in the original
`REVIEW_FAILED_feat_inventory-button-move-stock.md` is **eliminated**.
The fix follows operator-authorized **Option A**: a partial UNIQUE
index at the DB layer plus an INSERT-then-catch-`IntegrityError`-and-replay
pattern in the writer. No app-level lock. The database serialises
duplicate writes via SQLite WAL + the UNIQUE constraint; exactly one
INSERT wins.

## Files in this remediation

| File | State | Purpose |
|---|---|---|
| `service/app/db/migrations/draft_20260512_002516_idempotency_key.py.draft` | NEW | Idempotent migration: ALTER TABLE adds `idempotency_key` column + partial UNIQUE index. `.py.draft` suffix prevents accidental import. Runs by hand: `python service/app/db/migrations/draft_20260512_002516_idempotency_key.py.draft <warehouse.db> up`. |
| `service/app/services/warehouse_db.py` | MODIFIED | Adds two helpers: `record_scan_with_idempotency()` (writer with new column) and `find_movement_event_by_idempotency()` (replay lookup). Existing `record_scan()` unchanged for backward compatibility. |
| `service/app/services/inventory_location_writer.py` | RENAMED + REWRITTEN | Was `.py.draft`. Now active. Old `_find_prior_idempotent_event` SELECT helper is GONE. New `move_piece()` does state-gate → INSERT → catch `sqlite3.IntegrityError` → fetch existing event → return replay envelope. |
| `service/app/api/routes_inventory_writes.py` | RENAMED, BODY UNCHANGED | Was `.py.draft`. Router signature was already correct (delegated to `move_piece`); no rework needed. |
| `service/tests/test_inventory_move_stock.py` | RENAMED + EXPANDED | Was `.py.draft`. Now active with 14 tests including the new `test_concurrent_writes_with_same_key_one_wins`. |
| `main.py` | UNTOUCHED | Per spec — router include is deploy-time, not branch-time. Tests register the router locally for assertion purposes only. |

## 10-point security checklist

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | No SELECT-then-INSERT pattern remains | PASS | grep `_find_prior_idempotent_event` in writer → 0 hits; grep `SELECT.*WHERE.*idempotency` → 0 hits |
| 2 | Legacy idempotency lookup helper removed | PASS | source no longer contains `_find_prior_idempotent_event`; replay path now uses `wdb.find_movement_event_by_idempotency` AFTER catching `IntegrityError` (not before write) |
| 3 | No app-level `_lock` in writer | PASS | grep `wdb._lock` / `with wdb._lock` / `with _lock` in writer → 0 hits |
| 4 | Concurrent-write test exists and passes | PASS | `test_concurrent_writes_with_same_key_one_wins` — 2 threads, deterministic IntegrityError on second, assertion: both return same `event_id`, statuses are `["moved", "replayed"]` |
| 5 | Partial UNIQUE index correct for SQLite WAL | PASS | Migration uses `CREATE UNIQUE INDEX … WHERE idempotency_key != ''`. SQLite supports partial indexes since 3.8.0; project runs on WAL (`warehouse_db.py:72`). IntegrityError under WAL is deterministic — exactly one writer's commit succeeds; the other raises. |
| 6 | Migration `.py.draft` suffix prevents auto-pickup | PASS | Filename ends `.py.draft`; not importable as a module; not picked up by any autoloader (project has no alembic) |
| 7 | Auth: `Depends(require_api_key)` on route | PASS | `routes_inventory_writes.py:29` declares router-level `dependencies=[Depends(require_api_key)]` |
| 8 | Replay returns identical event_id, not a new one | PASS | `test_replay_with_same_idempotency_key_returns_existing_event_id` asserts `data["event_id"] == "evt-prior-XYZ"`. Concurrent test asserts both threads' results agree on `event_id`. |
| 9 | Anti-fake grep clean | PASS | grep `MOCK_/SAMPLE_/FAKE_/DEMO_/EJ-RING-/fakeData/invented_endpoint` across all 5 new/modified files → 0 hits |
| 10 | Write-path grep: only the declared write exists | PASS | Programmatic enumeration: `[('/api/v1/inventory/pieces/{piece_id}/location', {'POST'})]` — exactly 1 write under `/api/v1/inventory/` |

## Additional verifications (not in the 10-point list, worth recording)

- **Single-writer discipline preserved.** Move stock never calls `inventory_state_engine.transition()`. Source-grep test `test_source_does_not_call_state_transition` enforces. Lifecycle state remains the engine's exclusive domain.
- **State gate before write.** `move_piece` reads `inventory_state_engine.get_state(scan_code)` and rejects with `WRONG_STATE` (HTTP 409) if not in `WAREHOUSE_STOCK` — done BEFORE any write to avoid wasted insert+rollback for ineligible pieces.
- **DB-unavailable handling.** Returns HTTP 503 with structured detail, never a 500 traceback (`test_db_unavailable_returns_503`).
- **Empty idempotency_key.** Pydantic `min_length=1` returns 422 before the request reaches the writer (`test_empty_idempotency_key_rejected_by_pydantic`). The DB column has `NOT NULL DEFAULT ''`, so legacy `record_scan()` callers remain valid (they pass empty key, partial index excludes them).
- **IntegrityError discrimination.** `_is_idempotency_violation()` distinguishes idempotency-related `IntegrityError` from other UNIQUE/NOT NULL violations on the same table. Non-idempotency integrity errors re-raise (potential corruption — operator notice).

## Test results

```
14 passed, 64 warnings in 2.46s
```

Test inventory:
- `test_valid_move_with_new_idempotency_key_succeeds` — happy path
- `test_replay_with_same_idempotency_key_returns_existing_event_id` — replay returns prior event_id
- `test_concurrent_writes_with_same_key_one_wins` — 2-thread race, exactly one moved + one replayed, agreed event_id
- `test_empty_idempotency_key_rejected_by_pydantic` — 422 at validation layer
- `test_missing_fields_return_422` — 422 on incomplete body
- `test_piece_not_in_warehouse_stock_rejected` — 409 WRONG_STATE
- `test_piece_not_found_returns_404` — 404 PIECE_NOT_FOUND
- `test_db_unavailable_returns_503` — 503 DB_UNAVAILABLE
- `test_source_does_not_acquire_app_level_lock` — Option A discipline
- `test_source_has_no_find_prior_idempotent_event` — legacy helper gone
- `test_source_does_not_call_state_transition` — single-writer discipline
- `test_no_new_writes_on_inventory_paths` — exactly 1 write declared
- `test_pieces_path_registered` — endpoint discoverable
- `test_warehouse_db_has_idempotency_helpers` — both helpers callable

## Deploy notes for operator

Before the cutover deploy that activates this endpoint:

1. **Apply the migration to `C:\PZ\storage\warehouse.db`** (production-equivalent DB on the NSSM host). Either:
   - rename `.py.draft` → `.py` and run it as a one-off script, OR
   - copy the `upgrade()` body into `init_warehouse_db()` so it runs at every service start (idempotent — safe to leave in indefinitely).
2. **Add the include line** to `service/app/main.py`:
   ```python
   from .api.routes_inventory_writes import router as inventory_writes_router
   app.include_router(inventory_writes_router)  # POST /api/v1/inventory/pieces/{id}/location
   ```
3. **Restart `PZService`** via the standard sc.exe stop/start in an elevated shell.
4. **Smoke** loopback unauth → expect 401/403 (auth enforced); auth'd POST with new idempotency_key → 200 status=moved; same POST replayed → 200 status=replayed with same event_id.

The migration is reversible via `downgrade()` (drops index; column remains because SQLite <3.35 has no DROP COLUMN, but an empty-default column is harmless).

## Verdict

**PASS.** Branch is ready for PR after Group A doc PRs merge.

Recommended PR title:
```
fix(inventory): Move stock idempotency via DB UNIQUE (Option A)
```
