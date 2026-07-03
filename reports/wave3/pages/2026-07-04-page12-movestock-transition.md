# Wave-3 Page 12 Build Record — MoveStockModal Stage-Transition Tab

**Date:** 2026-07-04  
**Slice:** W3-page12 (census #12, scope S)  
**File:** `service/app/static/v2/inventory-page.jsx`  
**Branch:** `deploy/latest` @ `dd6358e0` (pre-edit HEAD)  
**pz-api.js:** No transport method added — `getInventoryMovements` and `getInventoryBatchState` exist and were confirmed present before implementation.

---

## Census Entry (scope S)

Live-app inventory flagged: "MoveStockModal stage-transition tab disabled" — a dead control from the B×7-1 era. The tab toggle had `pending: true`, `disabled`, `opacity:0.55`, `cursor:not-allowed`, and a "BACKEND-PENDING · PHASE C" amber badge.

---

## Backend Truth (pre-build research)

Routes searched: `routes_inventory.py`, `routes_inventory_writes.py`, `routes_inventory_sample.py`, `routes_inventory_returns.py`.

**Finding: NO manual stage-transition POST route exists.**

- `routes_inventory_writes.py` — only `POST /inventory/pieces/{id}/location` (metadata-only, no lifecycle state change; explicitly docs "never calls `inventory_state_engine.transition()`")
- `routes_inventory_sample.py` — `POST /inventory/pieces/{id}/sample-out` and `POST /inventory/pieces/{id}/sample-return` (dedicated sample modal paths, live)
- `routes_inventory_returns.py` — `POST /inventory/pieces/{id}/return-from-client`, `return-to-producer`, `return-from-producer` (dedicated returns modal paths, live)
- No `POST /inventory/pieces/{id}/stage-transition` or `promote` endpoint anywhere in the codebase

**Operator lifecycle rule (KNOWLEDGE.md §Operator lifecycle rules):**  
"Manual Move Stock page = exception/correction path only; the document is the primary trigger."  
(PZ → auto-promote; invoice → auto-issue; sample/return → their live modals)

**`inventory_state_engine.py` LEGAL_TRANSITIONS** (all verified):
- `None → PURCHASE_TRANSIT` trigger: `pz_generated`
- `PURCHASE_TRANSIT → WAREHOUSE_STOCK` trigger: `warehouse_receive` (auto on PZ booking / `run_stock_promotion`)
- `WAREHOUSE_STOCK → SALES_TRANSIT` trigger: `invoice_issued` (auto on proforma→invoice / `run_stock_issue`)
- `WAREHOUSE_STOCK → SAMPLE_OUT` trigger: `sample_out_marked` (POST `/inventory/pieces/{id}/sample-out`)
- `WAREHOUSE_STOCK → RETURNED_FROM_CLIENT` trigger: `returned_from_client_received`
- `WAREHOUSE_STOCK → RETURNED_TO_PRODUCER` trigger: `returned_to_producer_shipped`
- `SAMPLE_OUT → WAREHOUSE_STOCK` trigger: `sample_returned`
- `SAMPLE_OUT → RETURNED_FROM_CLIENT` trigger: `returned_from_client_received`
- `RETURNS → WAREHOUSE_STOCK` trigger: `returned_restocked` / `returned_from_producer_restocked`
- `SALES_TRANSIT → CLOSED` trigger: `delivery_confirmed` (no operator POST route — IV-TS-1)
- `CLOSED` — terminal, no successors

---

## What Was Built

The stage-transition tab changes from **silently disabled** to an **honest document-driven guide + exception/correction path**:

### Toggle fix
Removed `pending: true`, `disabled`, `opacity:0.55`, `cursor:not-allowed`, and "BACKEND-PENDING · PHASE C" badge from the Stage transition button. Both toggle options are now equally clickable. New subtitle: "Document-driven guide + exception path".

### Stage-transition panel (renders when `moveType === 'stage'`)

1. **Architecture doctrine banner** (`ms-stage-doctrine`) — explains transitions are document-driven; this tab is the exception/correction path.

2. **WAREHOUSE_STOCK group** (`ms-stage-group-wh`) — 4 transitions, each with:
   - State name, real trigger, endpoint/function name
   - Deep-link button to the dedicated tab/modal:
     - → SALES_TRANSIT: "Go to Temp Sale tab ↗" (fires `inv:jump → tempSale`)
     - → SAMPLE_OUT: "Go to Sample Out tab ↗" (fires `inv:jump → sampleOut`)
     - → RETURNED_FROM_CLIENT: "Go to Client Return tab ↗" (fires `inv:jump → clientReturn`)
     - → RETURNED_TO_PRODUCER: "Go to Return to Producer tab ↗" (fires `inv:jump → producerReturn`)

3. **PURCHASE_TRANSIT group** (`ms-stage-group-pt`) — explains auto-promote via `run_stock_promotion` / BE-1; references Temp Purchase tab.

4. **SAMPLE_OUT group** (`ms-stage-group-so`) — two successors:
   - → WAREHOUSE_STOCK: "Go to Sample Return tab ↗" (fires `inv:jump → sampleReturn`)
   - → RETURNED_FROM_CLIENT: escalate path, references Goods Return tab.

5. **RETURNED_FROM_CLIENT / RETURNED_TO_PRODUCER group** (`ms-stage-group-returns`) — restocking events via Return to Producer tab and Goods Return tab.

6. **SALES_TRANSIT → CLOSED group** (`ms-stage-group-terminal`) — `delivery_confirmed`, no POST route (IV-TS-1, future slice). CLOSED = terminal.

7. **Lesson-M disclosure — IV-ST-1** (`ms-stage-lesson-m`) — amber panel:
   - Wireframe "Confirm move → Consignment" has no backend POST route (WFIRMA-GATED · OI-1)
   - Wireframe "Confirm move → Temp Sale" has no backend POST route (invoice-driven `invoice_issued`)
   - Both tracked under census IV-ST-1

8. **Close button** (`ms-stage-close`)

---

## Nine Operator Criteria — Evidence Table

| # | Criterion | Evidence |
|---|---|---|
| 1 | **Layout matches wireframe** | Wireframe shows two-tab toggle (wh→wh + stage); toggle preserved. Stage tab now shows content (honest guide) vs wireframe's mock form which relied on fake `SU-…` paste input (FORBIDDEN by operator rule — no raw ID paste). Wireframe spec honored in spirit; ID-paste input replaced by document-driven guide per operator rule. |
| 2 | **Components match** | Tab toggle uses existing CSS vars (`--accent`, `--card`, `--border`); all groups use `--bg-subtle` / `--border`; Lesson-M banner uses `--badge-amber-*`. No new components. |
| 3 | **Buttons work** | wh→wh tab: all existing form elements intact + submit. Stage tab: 5 deep-link buttons (`inv:jump` CustomEvent, tested in browser — modal closes, tab navigation fires). Close button present. No dead buttons. |
| 4 | **API wiring correct** | No invented endpoint. Every transition listed names its real backend route. Deep-links use `inv:jump` event (existing pattern from multiple tabs). No `getInventoryMovements` / `getInventoryBatchState` calls needed here (panel reads from the engine's static LEGAL_TRANSITIONS knowledge, not from a live endpoint). |
| 5 | **No dead controls** | Stage tab was the only dead control (disabled button). Now selectable and shows honest content. Lesson-M badge documents IV-ST-1 as planned-future. |
| 6 | **No placeholder content** | All transition rows cite real `inventory_state_engine.py` triggers and real endpoint URLs. No lorem ipsum, no fake SU IDs, no hardcoded mock data. |
| 7 | **No console errors** | Verified: `preview_console_logs(level='error')` → "No console logs." Pin 11/11 green. Smoke 63/63 green. |
| 8 | **No duplicate authority** | Modal is the ONLY Move Stock modal (no second implementation). Deep-links navigate to existing tabs; nothing duplicated. |
| 9 | **Smoke test passes** | `cd service && python -m pytest tests/ -m smoke -q` → 63 passed, 1 skipped, 18852 deselected, 1 warning. Pin `test_master_consumption_rule.py` → 11/11. |

**Page gate: 9/9 PASS**

---

## Census Tags Introduced

- **IV-ST-1** — wireframe "Confirm move → Consignment" and "Confirm move → Temp Sale" have no backend POST routes; Lesson-M disclosed in `ms-stage-lesson-m` panel. Status: planned, tracked.

---

## Tree Counts

| Metric | Value |
|---|---|
| `git status --short \| wc -l` before | 42 |
| `git status --short \| wc -l` after | 43 (+1 from `.claude/launch.json` created by preview system — not a code edit) |
| Files edited | 1 (`service/app/static/v2/inventory-page.jsx`) |
| Lines added (modal section) | ~215 lines added, ~65 restructured into conditional block |
| pz-api.js | NOT modified (transport methods confirmed pre-existing) |
| Commits | 0 (NO COMMIT per task constraints) |

---

## Constraints Honored

- No `git stash/clean/reset` executed
- No `commit/push/PR/deploy` executed  
- No `C:\PZ` touched
- No `npm install` executed
- No new transport methods added to `pz-api.js` (existing methods confirmed sufficient)
- No invented transition endpoint
- Lesson M: IV-ST-1 honestly disclosed with reason (not silently hidden)
