# Group B PR Bodies — Read-Path Implementations

Same manual-paste workflow as Group A. Open each URL, paste title, paste body, confirm base = `main`, click **Create pull request** (green button, NOT draft).

Open in this order to keep dependencies clean: B.1 → B.2 → B.3 → B.4.

---

## PR B.1 — `feat/inventory-state-batch-read`

**URL:** https://github.com/amitpoland/estrella-dhl-control/pull/new/feat/inventory-state-batch-read

**Title:**
```
feat(inventory): GET /api/v1/inventory/state/{batch_id} (read-only)
```

**Body:**
```markdown
## Summary

Adds `GET /api/v1/inventory/state/{batch_id}` — a per-batch read endpoint that wraps `inventory_state_engine.count_by_state(batch_id=...)` and `list_by_state(state, batch_id=...)`. Returns `{batch_id, as_of, counts, pieces, total, degraded}`. Honest empty: unknown batch returns 200 with zero counts and empty pieces (callers distinguish via `total`). Honest degraded: warehouse DB unavailable returns 200 with `degraded=true`, never 500. This is the Phase 4 prerequisite from the inspector report §9.

## Verification

- 7/7 new tests PASS on this branch (`test_inventory_batch_state.py`).
- Path 2 baseline (150 tests across Stage 2 aggregator + dashboard wiring + inventory design + coverage + operational bucket filter) confirmed preserved during implementation.
- Anti-fake grep: clean.
- Write-path grep: clean — no new POST/PUT/PATCH/DELETE on `/api/v1/inventory/*`.
- Auth: extends the existing `inventory_router` which has `dependencies=[Depends(require_api_key)]` at router level.
- Service module (`inventory_batch_state.py`) audited — no INSERT/UPDATE/DELETE patterns, no connection management beyond reuse of `inventory_state_engine._connect()`.

## Out of scope

- No state transitions (this is read-only)
- No Move stock work (that's `feat/inventory-button-move-stock`, separate PR)
- No UI changes (the strip that consumes this endpoint is PR B.2)

## Merge method

**Create a merge commit. Do not squash. Do not rebase-merge.**
Rationale: preserves the Phase 4.1 commit message (`feat(inventory): GET /api/v1/inventory/state/{batch_id} read-only` @ `2d57e70`) for campaign traceability.

## Next step

PR B.2 (`feat/inventory-ui-shipment-state-strip`) consumes this endpoint. Deploy via Path-2-style 7-agent gate after Group A docs merge — the docs provide review context.
```

---

## PR B.2 — `feat/inventory-ui-shipment-state-strip`

**URL:** https://github.com/amitpoland/estrella-dhl-control/pull/new/feat/inventory-ui-shipment-state-strip

**Title:**
```
feat(inventory-ui): per-batch inventory state strip on BatchDetailPage
```

**Body:**
```markdown
## Summary

Wires `GET /api/v1/inventory/state/{batch_id}` (PR B.1) into the `BatchDetailPage` Overview tab as a read-only strip. Renders per-state tile counts with honest empty / loading / error / degraded states. Zero counts show em-dash + `data-pending="true"` (matches the Stage 2 honest-null pattern from Path 2). Error chip is isolated to the strip — does NOT crash the rest of the page.

## Verification

- 10/10 new tests PASS on this branch (`test_dashboard_inventory_state_strip.py`).
- Full Atlas composition suite **658/658 PASS** on this branch (no regressions across the 22-file dashboard suite).
- No new `apiFetch` URLs except the single batch-state endpoint.
- 4 testid landmarks for introspection: `inventory-batch-state-strip`, `inventory-batch-state-loading`, `inventory-batch-state-error`, `inventory-batch-state-empty`, plus per-state tile testids.
- No write methods added.

## Out of scope

- No new endpoints (PR B.1 provides the endpoint)
- No piece-level drawer (that's PR B.4)
- No new disabled action buttons

## Merge method

**Create a merge commit. Do not squash. Do not rebase-merge.**
Rationale: preserves the Phase 4.2 commit message (`feat(inventory-ui): per-batch inventory state strip on BatchDetailPage` @ `12849fb`) for campaign traceability.

## Dependency

**PR B.1 (`feat/inventory-state-batch-read`) must merge first**, or be deployed in the same window. UI without backend → strip shows the isolated error chip on every shipment detail page until backend lands.

## Next step

Deploy as part of the Group B 7-agent gate. After Group B is on production, operator decides whether to merge Group C (Move stock) immediately or hold.
```

---

## PR B.3 — `feat/inventory-piece-detail-read`

**URL:** https://github.com/amitpoland/estrella-dhl-control/pull/new/feat/inventory-piece-detail-read

**Title:**
```
feat(inventory): GET /api/v1/inventory/pieces/{piece_id} (read-only)
```

**Body:**
```markdown
## Summary

Adds `GET /api/v1/inventory/pieces/{piece_id}` — a per-piece read endpoint that wraps `inventory_state_engine.get_state(piece_id)` and `get_history(piece_id)`. Returns `{piece_id, as_of, found, state, history, degraded}`. Honest empty: unknown piece returns 200 with `found=false` and empty history (NOT 404 — callers distinguish via the `found` flag). Honest degraded: warehouse DB unavailable returns 200 with `degraded=true`.

## Verification

- 8/8 new tests PASS on this branch (`test_inventory_piece_view.py`).
- Service module (`inventory_piece_view.py`) audited — no INSERT/UPDATE/DELETE patterns.
- Auth: extends existing `inventory_router` with router-level `Depends(require_api_key)`.
- Anti-fake grep: clean.
- Write-path grep: clean.

## Out of scope

- No write paths
- No drawer UI (that's PR B.4)
- No piece-level allocation table writes (Risk-3/4, separate campaign)

## Merge method

**Create a merge commit. Do not squash. Do not rebase-merge.**
Rationale: preserves the Phase 4.3 commit message (`feat(inventory): GET /api/v1/inventory/pieces/{piece_id} read-only` @ `95404ee`) for campaign traceability.

## Next step

PR B.4 (`feat/inventory-ui-piece-detail-drawer`) consumes this endpoint. Deploy via the Group B 7-agent gate.
```

---

## PR B.4 — `feat/inventory-ui-piece-detail-drawer`

**URL:** https://github.com/amitpoland/estrella-dhl-control/pull/new/feat/inventory-ui-piece-detail-drawer

**Title:**
```
feat(inventory-ui): piece detail drawer with scan_code lookup
```

**Body:**
```markdown
## Summary

Adds a user-triggered piece-detail drawer to `InventoryPage`. Lookup is via a scan_code input + button (Enter-key shortcut included). When invoked, fetches `GET /api/v1/inventory/pieces/{scan_code}` (PR B.3) and renders the right-side drawer with state row + chronological history. States rendered: loading / error / empty (`found=false`) / found. Eight testid landmarks for introspection. The 5 disabled inventory action buttons remain disabled and untouched.

## Verification

- 11/11 new tests PASS on this branch (`test_dashboard_inventory_piece_drawer.py`).
- One existing test updated: `test_dashboard_inventory_design.py::test_no_bulk_warehouse_audit_calls`. The original asserted exactly 1 `apiFetch` in `InventoryPage`. The drawer adds a SECOND, user-triggered call. The updated assertion allowlist:
  - Exactly 1 `apiFetch('/api/v1/inventory/stage2/aggregate')` — the Stage 2 mount fetch.
  - At most 1 `apiFetch(/api/v1/inventory/pieces/...)` — the user-triggered lookup.
  - Sum = total; no extras.
  - The SPIRIT of the test (no per-batch N+1 fan-out) is preserved.
- Full Atlas composition + new drawer suite: **674/674 PASS** (was 658; +11 drawer + 5 from the updated inventory-design file).
- No new write methods.

## Out of scope

- No Move stock action (that's `feat/inventory-button-move-stock`, separate PR)
- No drawer-triggered transitions
- The 5 disabled action buttons stay disabled

## Merge method

**Create a merge commit. Do not squash. Do not rebase-merge.**
Rationale: preserves the Phase 4.4 commit message (`feat(inventory-ui): piece detail drawer with scan_code lookup` @ `7ee9d09`) for campaign traceability.

## Dependency

**PR B.3 (`feat/inventory-piece-detail-read`) must merge first**, or be deployed in the same window. Without the endpoint, the drawer's lookup yields the error chip; the rest of `InventoryPage` continues to render normally.

## Next step

After Group B (B.1 → B.4) merges, deploy via the Path-2-style 7-agent gate. Operator then decides Group C (Move stock) timing.
```

---

## Summary table

| # | Branch | Tip SHA | Method | Depends on |
|---|---|---|---|---|
| B.1 | `feat/inventory-state-batch-read` | `2d57e70` | merge commit | (none in Group B) |
| B.2 | `feat/inventory-ui-shipment-state-strip` | `12849fb` | merge commit | B.1 |
| B.3 | `feat/inventory-piece-detail-read` | `95404ee` | merge commit | (none in Group B) |
| B.4 | `feat/inventory-ui-piece-detail-drawer` | `7ee9d09` | merge commit | B.3 |
