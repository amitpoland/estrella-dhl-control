# Phase 1 Inspector Report — Operator Review Required

Inspector report committed to `feat/inspection-report` @ `0f00500`.
Campaign base SHA: `07f41ad54c507a3b5257bd1ac885074645f0361b` (main HEAD at pre-flight).

PR URL hint: https://github.com/amitpoland/estrella-dhl-control/pull/new/feat/inspection-report

Report location: `docs/inspection/inventory-proforma-flow-map.md` (216 lines, 22KB).

## Key findings (one-line summaries)

- **Inventory model**: state-column canonical (`inventory_state.state` TEXT NOT NULL). Single writer (`inventory_state_engine.transition`). 5 readers, all REWRITE-class if model changes. Zero raw state-string literals in test fixtures.
- **Double-allocation risk**: YES. No reservation table links to `inventory_state.scan_code`. `_check_warehouse_readiness` counts batch-wide, not per-line claim. Two proforma drafts on the same batch for different clients can both pass.
- **Reservation reality**: `reservation_queue`, `wfirma_reservation_drafts`, `wfirma_reservation_lines` exist. WRITTEN and READ but **disjoint from `inventory_state`** — no `scan_code` link column.
- **Production data volume (dev DB = `C:\PZ\storage`)**:
  - `inventory_state`: 0 rows
  - `shipment_documents`: 10 (2026-05-09 → 2026-05-11)
  - `proforma_drafts`: 4 (all `status='created'`)
  - wFirma posted: 0
- **Missing tables**: `inventory_allocations`, `inventory_reservations`, `shipment_batches`, `proforma_posted`.
- **5 disabled inventory action buttons** target states (`SAMPLE_OUT`, `RETURNED_*`, `CONSIGNMENT_*`) that **do not exist in `STATES`** (`inventory_state_engine.py:81-85`).
- **`mark-direct-dispatch` endpoint exists** at `routes_lifecycle.py:469` but has **no UI caller**.
- **Inspector's recommendation**: finish mapping/wiring existing flow first — DO NOT implement allocation ledger now. State-column model is clean; uniquely-owned by one file; production has 0 inventory rows on this host (no operational pressure proving double-allocation). Ledger rewrite is cheap per §7.5 but premature.

## What operator must decide before Phase 2

The campaign spec asks for 4 architecture decisions. The inspector report's §8 recommendation diverges from the campaign's Phase 2 assumption ("Doc 1 v2 allocation ledger architecture"). Reconcile before authorizing.

1. **Doc 1 v2 architecture**:
   - `greenfield-ledger` — replace state column with event-sourced ledger
   - `extend-existing` — keep state column, add `inventory_allocations` table linking `scan_code` to draft/reservation
   - `brownfield` — keep state column, add `scan_code` to `reservation_queue`; no new table
   - *(Inspector recommends NOT pursuing ledger now; if operator overrides, capture rationale.)*

2. **Allocation ledger schema** (if applicable):
   - `header-lines` — one allocation row per proforma draft × line
   - `one-row-per-piece` — one allocation row per `scan_code`

3. **`allocation_type` enum** (which categories to include): pick subset of
   `SALE`, `SAMPLE_OUT`, `SAMPLE_RETURN`, `CONSIGNMENT_OUT`, `CONSIGNMENT_RETURN`, `GOODS_RETURN`, `RETURN_TO_PRODUCER`, `INTERNAL_MOVE`.

4. **Implementation order**: confirm or revise the campaign's Phase 4 Risk-1 target (`View stock detail` then `Move stock`). Inspector's §9 proposes a different first task: `GET /api/v1/inventory/state/{batch_id}` (per-batch state strip on shipment detail).

## When operator approves Phase 2

Operator must paste into Claude Code:

```
PHASE 2 AUTHORIZED.
Architecture: <greenfield-ledger / extend-existing / brownfield>
Schema: <header-lines / one-row-per-piece>
Allocation types: <list>
Continue.
```

Without this exact phrase format, do NOT continue to Phase 2.

## Branches created so far in campaign

| Branch | SHA | Status |
|---|---|---|
| `feat/inspection-report` | `0f00500` | pushed to origin |

## Hands-off branches (per spec)

- `feat/hybrid-auth-prep` — untouched.

## Hard halt log

None. Pre-flight passed after a clean checkout from `feat/hybrid-auth-prep` to `main` (working tree was already clean; switch was a recovery of "current branch must equal main" precondition).
