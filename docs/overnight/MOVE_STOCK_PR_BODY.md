# Move Stock PR Body — DO NOT OPEN UNTIL GROUP A MERGED

**Branch:** `feat/inventory-button-move-stock` @ `50f7101`
**PR URL hint:** https://github.com/amitpoland/estrella-dhl-control/pull/new/feat/inventory-button-move-stock

**Hold rule:** open only AFTER all 7 Group A doc PRs have been merged into `main`. Doc 2 (button registry) references this button by name; Doc 4 (failure modes) references the idempotency failure mode that this PR resolves. Opening this PR before the docs are merged invites a reviewer to dispute the contract before its supporting evidence is in the trunk.

---

## Title

```
fix(inventory): Move stock idempotency via DB UNIQUE (Option A)
```

## Body

```markdown
## Summary

First write endpoint on the inventory surface: `POST /api/v1/inventory/pieces/{piece_id}/location`. Location metadata only — does NOT transition state. Lifecycle state remains the exclusive domain of `inventory_state_engine.transition()` (single-writer discipline preserved).

This PR is the **Option A remediation** of the original Phase 4.5 work. The first attempt (committed at `379308c` as `.py.draft`) failed security review because the SELECT-then-INSERT idempotency check had a race window. This rework removes the race entirely:

- A partial UNIQUE index at the database layer enforces uniqueness on `(scan_code, idempotency_key) WHERE idempotency_key != ''`.
- The writer attempts the INSERT directly; on `sqlite3.IntegrityError`, it fetches the prior event and returns the replay envelope with the same `event_id`.
- No app-level locking.

## Verification

- **14/14 tests PASS** on this branch (`test_inventory_move_stock.py`) including `test_concurrent_writes_with_same_key_one_wins` (2-thread race: exactly one moved + one replayed, both threads agree on `event_id`).
- **Security re-review: PASS** (10/10 checks). Full doc at `docs/security/REVIEW_PASSED_feat_inventory-button-move-stock.md`.
- Source-grep tests enforce the Option A invariants: no `_find_prior_idempotent_event` remains; no `wdb._lock` acquired in writer; no `.transition(` call.
- Auth: router-level `Depends(require_api_key)` on `routes_inventory_writes.py`.
- Anti-fake grep: clean.
- Write-path grep: exactly one write declared on `/api/v1/inventory/*`.

## Migration step (REQUIRED — operator runs before deploy)

This PR ships an **idempotent migration draft** as `service/app/db/migrations/draft_20260512_002516_idempotency_key.py.draft`. The `.py.draft` suffix prevents Python imports and ensures no autoloader picks it up. The project has no alembic; the migration is a standalone script.

Before deploying this branch to production, operator must apply the migration to `C:\PZ\storage\warehouse.db`:

```powershell
python "C:\PZ\app\db\migrations\draft_20260512_002516_idempotency_key.py.draft" "C:\PZ\storage\warehouse.db" up
```

OR (preferred for permanent integration) copy the `upgrade()` body into `init_warehouse_db()` so it runs at every service start. The migration is idempotent — `_column_exists` and `_index_exists` guards make it safe to re-run.

What the migration does:
1. `ALTER TABLE inventory_movement_events ADD COLUMN idempotency_key TEXT NOT NULL DEFAULT ''`
2. `CREATE UNIQUE INDEX idx_movement_idempotency ON inventory_movement_events (scan_code, idempotency_key) WHERE idempotency_key != ''`

Pre-existing rows from the legacy `record_scan()` writer have an empty key and are excluded from the partial index — they never collide.

## Deploy step (REQUIRED — separate from PR merge)

After merging the PR, two more steps are needed for the endpoint to come live in production:

1. **Add the include line** to `service/app/main.py`:
   ```python
   from .api.routes_inventory_writes import router as inventory_writes_router
   app.include_router(inventory_writes_router)  # POST /api/v1/inventory/pieces/{id}/location
   ```
   This was intentionally NOT done on the branch (campaign rule: deploy-time wiring, not branch-time).

2. **Restart PZService** via the standard `sc.exe stop` / `sc.exe start` flow in an elevated PowerShell (same pattern used for Path 2 deploy).

After restart, smoke test:
- Auth'd POST with new `idempotency_key` → 200, `status=moved`.
- Same POST replayed → 200, `status=replayed`, same `event_id` as the first.
- Auth'd POST on a piece NOT in `WAREHOUSE_STOCK` → 409 `WRONG_STATE`.

## Out of scope

- No state transitions (Move stock = location metadata only)
- No new states added to `STATES`
- No new write methods other than this one endpoint
- Sample-out, Consignment, Returns, Goods-return, Return-to-producer remain BLOCKED on schema work (allocation_groups / allocation_pieces tables not yet built)

## Pre-merge requirements

1. **Group A documentation PRs (7) must be merged first.** Doc 2 (button registry) declares this button; Doc 4 (failure modes) documents the race this PR resolves; Doc 1 v2 (architecture) frames the single-writer discipline preserved here.
2. Migration step (above) must be applied to the deploy target BEFORE the code is deployed. Order: merge PR → apply migration on `C:\PZ` → add main.py include → restart PZService → smoke.

## Merge method

**Create a merge commit. Do not squash. Do not rebase-merge.**
Rationale: preserves the Phase 4.5-remediation commit message (`fix(inventory): Move stock idempotency via DB UNIQUE (Option A)` @ `50f7101`) for campaign traceability. The branch also contains the prior failed-review and the security-passed marker — both worth retaining as history.

## Next step

After this PR merges + migration runs + deploy completes:
- The first inventory write endpoint is live in production.
- Operator can decide which Risk-3/4 button to design next (Sample-out is the natural follow-up since it reuses this idempotency pattern).
- The `allocation_groups` / `allocation_pieces` schema design from Doc 1 v2 §5 can be promoted from design to a real migration as part of that next campaign.
```

---

## Files referenced

- Migration: `service/app/db/migrations/draft_20260512_002516_idempotency_key.py.draft`
- Service: `service/app/services/inventory_location_writer.py`
- Router: `service/app/api/routes_inventory_writes.py`
- Helpers: `service/app/services/warehouse_db.py` (`record_scan_with_idempotency`, `find_movement_event_by_idempotency`)
- Tests: `service/tests/test_inventory_move_stock.py`
- Security review: `docs/security/REVIEW_PASSED_feat_inventory-button-move-stock.md`
- (Historical) prior review: `docs/security/REVIEW_FAILED_feat_inventory-button-move-stock.md`
