# Test Validation Table — 11 PR-Ready Branches

Read-only enumeration of files changed per branch (vs `origin/main` @ `07f41ad`). No tests were run against branches; results captured during each branch's own implementation are cited.

## Per-branch file impact

| Branch | New tests | Modified tests | Touches `dashboard.html`? | Touches `main.py`? | Recorded test pass on its own branch |
|---|---|---|---|---|---|
| `feat/inspection-report` | 0 | 0 | no | no | n/a (docs only) |
| `feat/doc-1-v2-allocation-ledger` | 0 | 0 | no | no | n/a (docs only) |
| `feat/doc-2-button-registry` | 0 | 0 | no | no | n/a (docs only) |
| `feat/doc-3-data-source-mapping` | 0 | 0 | no | no | n/a (docs only) |
| `feat/doc-4-failure-modes` | 0 | 0 | no | no | n/a (docs only) |
| `feat/inventory-risk2-designs` | 0 | 0 | no | no | n/a (docs only) |
| `feat/inventory-risk34-stubs` | 0 | 0 | no | no | n/a (docs only) |
| `feat/inventory-state-batch-read` | 1 (`test_inventory_batch_state.py`) | 0 | no | no | 7/7 PASS; Path 2 150/150 PASS |
| `feat/inventory-ui-shipment-state-strip` | 1 (`test_dashboard_inventory_state_strip.py`) | 0 | **yes** | no | 10/10 PASS; Atlas 658/658 PASS |
| `feat/inventory-piece-detail-read` | 1 (`test_inventory_piece_view.py`) | 0 | no | no | 8/8 PASS |
| `feat/inventory-ui-piece-detail-drawer` | 1 (`test_dashboard_inventory_piece_drawer.py`) | 1 (`test_dashboard_inventory_design.py`) | **yes** | no | 11/11 new + 1 updated PASS; Atlas 674/674 PASS |

## Aggregate

- Total new test files added across the campaign: **4** (Group B reads/UI) + **0** (docs) = **4** on the 11 listed branches.
- Total test files modified (assertion updates): **1** (`test_dashboard_inventory_design.py` on the piece-drawer branch — relaxed the "exactly 1 apiFetch in InventoryPage" gate to allow the second user-triggered piece lookup, with an explicit allowlist for the new URL).
- Branches touching `service/app/static/dashboard.html`: **2** (`feat/inventory-ui-shipment-state-strip`, `feat/inventory-ui-piece-detail-drawer`). They modify different functions in the same file (`BatchDetailPage` vs `InventoryPage`); merge-order matters but no line conflicts are expected.
- Branches touching `service/app/main.py`: **0** across the 11 listed. The Move stock branch (`feat/inventory-button-move-stock`) also does NOT touch `main.py` — wiring is deploy-time.

## Operator attention flags

- **None of the 11 branches need a `main.py` change at merge time.** The router for `feat/inventory-state-batch-read` and `feat/inventory-piece-detail-read` extends the existing `inventory_router` (already wired in `main.py` at `07f41ad` for the Stage 2 endpoint), so adding new GET routes to it does not require a new include.
- **The two dashboard.html branches** touch separate React functions:
  - `feat/inventory-ui-shipment-state-strip` → `BatchDetailPage` (new state hooks + JSX strip).
  - `feat/inventory-ui-piece-detail-drawer` → `InventoryPage` (new state hooks + drawer JSX + lookup input).
  - These can be merged in any order; the second merge will fast-forward without conflict if the first already landed.

## Merge-order guidance

Suggested sequence for Group B once Group A is merged:

1. `feat/inventory-state-batch-read` (backend) — no dashboard.html change, lowest risk.
2. `feat/inventory-ui-shipment-state-strip` (frontend) — wires to #1's endpoint.
3. `feat/inventory-piece-detail-read` (backend) — no dashboard.html change.
4. `feat/inventory-ui-piece-detail-drawer` (frontend) — wires to #3's endpoint + updates one existing inventory-design test.

Reversing the within-pair order (UI before backend) deploys a UI that hits a 404 endpoint until backend lands — graceful (the error chip path is tested), but not ideal.

## Out of scope for this table

- No tests were actually executed against the branches; this table enumerates file additions only. Each branch's recorded pass count comes from its implementation-time run (cited in the per-branch commit message and the original `MORNING_REPORT.md`).
- The Move stock branch (`feat/inventory-button-move-stock` @ `50f7101`) is intentionally absent from the 11-branch list per the campaign final wrap-up spec; it has its own PR body in `MOVE_STOCK_PR_BODY.md` and a separate deployment dependency on running the idempotency migration.
