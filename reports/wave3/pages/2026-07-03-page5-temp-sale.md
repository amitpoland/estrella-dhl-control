# Wave-3 Page 5 — Temp Sale Tab Build Record

**Date:** 2026-07-03
**Branch:** deploy/latest @ f4f87f56 (base); implemented in this session
**Slice:** Wave-3 / U-3 (page 5) — census #5 (IV-TS-1)
**File(s) edited:**
- `service/app/static/v2/inventory-page.jsx` (2510 lines before; 2777 lines after; +267 lines)
- `service/app/static/v2/pz-api.js` (885 lines before; 908 lines after; +23 lines)

**Gap rows addressed:** IV-TS-1 (TempSaleTab register wired; two Lesson-M honest-disabled row actions)

**Tree-integrity check:**
- Dirty-file count before page 5: 41
- Dirty-file count after page 5: 42 (one new: this build record file, untracked)
- Both edited files (`inventory-page.jsx`, `pz-api.js`) were already modified-tracked;
  no new dirty entries added to existing source files.

---

## Gap Rows Addressed

| Gap | Tag | Description | Resolution |
|-----|-----|-------------|------------|
| IV-TS-1 | BUILD | Entire Temp Sale tab absent from live app; C-3d backend shipped in Wave 2 | `TempSaleTab` component added to inventory-page.jsx IIFE; two new API methods added to pz-api.js Wave-3 block (`getInventoryBatchState`, `getInventoryMovements`); tab wired in INV_TABS + InventoryPage render |
| IV-TS-1 (partial) | BUILD | "View proforma" action has no proforma_id linkage in inventory_state | Lesson-M honest-disabled with title tooltip explaining gap + census tag |
| IV-TS-1 (partial) | BUILD | "Issue invoice" (delivery_confirmed) has no operator-facing POST route | Lesson-M honest-disabled + gate banner per wireframe; title tooltip names future route path |

---

## Backend Authority Determination

**Live reads used:**
1. `GET /api/v1/inventory/state/{batch_id}` — `routes_inventory.py:74`; returns `pieces[{scan_code, state, product_code, design_no, updated_at}]`. Filtered client-side to `state === 'SALES_TRANSIT'`. Authority: `inventory_batch_state.get_batch_state`.
2. `GET /api/v1/inventory/movements/{batch_id}` — `routes_inventory.py:203` (C-3f); returns `events[{scan_code, from_state, to_state, trigger, occurred_at, operator, note}]`. Used to extract `client_name` from the `invoice_issued` event note field (`"invoice issue: {client_name}"` per `stock_issue.py:130`).

**Cross-batch aggregate:** No endpoint exists. Tab uses per-batch batch selector (BatchPanel precedent from Hub tab). Lesson-M noted in tab comment.

**Proforma linkage:** The `inventory_state` row and `inventory_state_events` for SALES_TRANSIT carry no `proforma_id` or `invoice_no` field. The `note` field carries `"invoice issue: {client_name}"` (stock_issue.py:130) but no proforma reference. No backend endpoint links a SALES_TRANSIT `scan_code` back to its source proforma. "View proforma" is Lesson-M honest-disabled.

**Delivery confirm route:** Grepped all `routes_*.py` files — no `/delivery-confirm`, `/confirm-delivery`, or `delivery_confirmed` POST endpoint exists. The `SALES_TRANSIT → CLOSED` transition with trigger `delivery_confirmed` is defined in `inventory_state_engine.py` (lines 30, 316) but has no operator-facing caller. "Issue invoice" is Lesson-M honest-disabled.

---

## Page Gate — 9 Criteria

### Criterion 1 — Layout matches wireframe section

Wireframe §7 Tab 4 (Temp Sale / TempSaleTab) defines:

**KPI tiles (4):** Open reservations · Awaiting goods · Reserved · Sales-invoice gate (LOCKED)
- Open reservations: total SALES_TRANSIT pieces in batch ✓
- Awaiting goods: total SALES_TRANSIT (DHL delivery status not distinguishable from current reads; honest approximation rendered with hint) ✓
- Reserved: total SALES_TRANSIT ✓
- Sales-invoice gate: value="LOCKED", always amber, explains no delivery_confirmed route ✓

**Gate banner (wireframe verbatim):** "Sales-invoice gate is enforced. No commercial sale invoice can be issued from a TEMP_SALE row. The invoice is unlocked only when its linked stock has reached FINAL_STOCK after physical verification." ✓

**Table columns (8) — wireframe exact order/labels:**
Proforma · Client · Design No · Qty · Value · Linked to · Status · Actions ✓

Column source mapping:
- Proforma: honest "—" (no proforma_id in inventory_state; Lesson-M tooltip) ✓
- Client: extracted from `invoice_issued` event note ("invoice issue: {client_name}") ✓
- Design No: `p.design_no` or scan_code split on `|` (same algorithm as other tabs) ✓
- Qty: always 1 (single-piece tracking) ✓
- Value: honest "—" (no price field in inventory_state; Lesson-M tooltip) ✓
- Linked to: `scan_code` (piece identifier) ✓
- Status: "Reserved" badge (amber — all SALES_TRANSIT pieces are committed) ✓
- Actions: View proforma (Lesson-M disabled + tooltip) · Issue invoice (Lesson-M disabled + tooltip) ✓

**Toolbar:** batch ID input + Load batch button + ↻ Refresh (after first load) ✓
**Tab strip entry:** `{ id: 'tempSale', label: 'Temp Sale', wire: true }` ✓
**InventoryPage render:** `{activeTab === 'tempSale' && <TempSaleTab />}` ✓

### Criterion 2 — Per-batch read authority confirmed

Live endpoint `GET /api/v1/inventory/state/{batch_id}` (routes_inventory.py:74) returns
`pieces[]` array filterable by `state`. Filtering for `state === 'SALES_TRANSIT'` gives
the Temp Sale register. `GET /api/v1/inventory/movements/{batch_id}` (routes_inventory.py:203)
gives event trail for client_name extraction. Both endpoints confirmed LIVE in routes.

Cross-batch aggregate intentionally absent — no endpoint exists. Per-batch batch picker
is the correct UI authority for this data. Lesson-M note in component comment block.

### Criterion 3 — Lesson-M honest-disabled actions documented

Both wireframe row actions are Lesson-M honest-disabled with:
- `disabled` attribute (cannot click)
- `title` tooltip naming the missing backend + census tag + future-slice path
- Gate banner naming the architectural blocker (delivery_confirmed route missing)
- Component comment block documenting the exact gap with grep evidence

**View proforma:** no proforma_id in inventory_state / inventory_state_events; no cross-join
endpoint. Census tag: IV-TS-1. Future: add proforma_id to stock_issue transition note.

**Issue invoice (delivery_confirmed):** no POST route in any routes_*.py for SALES_TRANSIT → CLOSED.
Census tag: IV-TS-1. Future: POST /api/v1/inventory/pieces/{id}/confirm-delivery.

### Criterion 4 — pz-api.js Wave-3 block: new methods immediately after returnFromProducer

Two new methods added immediately after `returnFromProducer` in the Wave-3 block:
- `getInventoryBatchState(batchId)` — wraps GET /api/v1/inventory/state/{batch_id}
- `getInventoryMovements(batchId, limit)` — wraps GET /api/v1/inventory/movements/{batch_id}

Both carry JSDoc-style comments specifying response shape, authority file + line number,
and Lesson-M note about cross-batch limitation.

### Criterion 5 — No fake data, no hardcoded rows

All table rows render from `pieces` array populated by the live API call. Client name is
extracted from the live events trail. Empty state renders honest empty message.
Prompt renders before first load. No mock arrays, no hardcoded demo rows.

### Criterion 6 — KPI tiles use InvStatTile (existing shared component)

All 4 KPI tiles use the existing `InvStatTile` component with `testid`, `label`, `value`,
`tone`, and `hint` props. No new component created. Pattern matches pages 1–4.

### Criterion 7 — Server cold boot (ACTUALLY RUN)

```
cd C:/PZ-verify/service
python -m uvicorn app.main:app --port 8133 --host 127.0.0.1
```

Result:
- Server started without errors (no import failures, no syntax errors in modified JSX/JS)
- `GET /v2/index.html` → **HTTP 200** ✓
- `GET /v2/inventory-page.jsx` → **HTTP 200** ✓ (TempSaleTab: 11 matches in served file)
- `GET /v2/pz-api.js` → **HTTP 200** ✓ (getInventoryBatchState + getInventoryMovements: 2 matches)

### Criterion 8 — data-testid coverage (9 testids)

| testid | Element |
|--------|---------|
| `temp-sale-tab` | Root div of TempSaleTab |
| `ts-gate-banner` | Sales-invoice gate banner |
| `ts-kpi-strip` | KPI tiles container |
| `ts-kpi-open` | Open reservations tile |
| `ts-kpi-awaiting` | Awaiting goods tile |
| `ts-kpi-reserved` | Reserved tile |
| `ts-kpi-gate` | Sales-invoice gate tile |
| `ts-toolbar` | Batch selector toolbar |
| `ts-batch-input` | Batch ID text input |
| `ts-btn-load` | Load batch button |
| `ts-refresh` | Refresh button |
| `ts-error-banner` | Error state banner |
| `ts-prompt` | Pre-load prompt |
| `ts-table` | Register table |
| `ts-empty` | Empty state row |
| `ts-row` | Each data row |
| `ts-btn-view-proforma` | View proforma (disabled) |
| `ts-btn-issue-invoice` | Issue invoice (disabled) |

### Criterion 9 — Pin 11/11 + Smoke (ACTUALLY RUN)

**Pin (test_master_consumption_rule.py):** 11 / 11 passed ✓
```
tests/test_master_consumption_rule.py::test_mirror_schema_is_exactly_six_columns PASSED
tests/test_master_consumption_rule.py::test_customer_mirror_schema_is_exactly_six_columns PASSED
tests/test_master_consumption_rule.py::test_mirror_has_unique_product_code_and_wfirma_id PASSED
tests/test_master_consumption_rule.py::test_product_master_has_authority_columns PASSED
tests/test_master_consumption_rule.py::test_no_new_product_direct_violations PASSED
tests/test_master_consumption_rule.py::test_reservations_router_stays_clean PASSED
tests/test_master_consumption_rule.py::test_known_violation_baseline_is_documented_and_shrinking PASSED
tests/test_master_consumption_rule.py::test_real_access_detector_positive_control PASSED
tests/test_master_consumption_rule.py::test_prose_and_master_reads_not_flagged PASSED
tests/test_master_consumption_rule.py::test_no_direct_wfirma_customer_calls_in_v4_v5_v7_routes PASSED
tests/test_master_consumption_rule.py::test_no_business_module_calls_wfirma_customer_apis PASSED
============================= 11 passed in 7.71s ==============================
```

**Smoke (pytest -m smoke):** 63 passed, 1 skipped ✓
```
cd C:/PZ-verify/service && python -m pytest tests/ -m smoke -v --tb=short
63 passed, 1 skipped, 18852 deselected in 45.05s
```

No regressions introduced. This slice edits ONLY `inventory-page.jsx` and `pz-api.js`
(frontend static files). No Python backend files were touched.

---

## Execution Flow Trace

**Temp Sale register read path:**
```
Operator types batch_id → clicks [Load batch]
  → load() fires in TempSaleTab
  → Promise.all([
      PzApi.getInventoryBatchState(batchId),    // GET /api/v1/inventory/state/{batch_id}
      PzApi.getInventoryMovements(batchId, 2000) // GET /api/v1/inventory/movements/{batch_id}
    ])
  → stateRes.data.pieces filtered to state==='SALES_TRANSIT' → setPieces(transit)
  → movRes.data.events filtered to trigger==='invoice_issued'
      → note parsed: /^invoice issue:\s*(.+)$/i → clientByCode[scan_code] = client_name
  → table renders SALES_TRANSIT pieces with client_name from events trail
```

**Row action (disabled — Lesson-M):**
```
[View proforma] disabled → title tooltip explains: no proforma_id in inventory_state
[Issue invoice] disabled → title tooltip explains: no delivery_confirmed POST route
```

---

## Lesson-M Disability Register (census IV-TS-1)

| Action | Wireframe | Backend state | Lesson-M note |
|--------|-----------|---------------|---------------|
| View proforma | Row action: link to source proforma | No proforma_id/invoice_no field in inventory_state or inventory_state_events for SALES_TRANSIT | Future: add proforma_id to stock_issue note on transition; expose GET /api/v1/proforma/by-scan-code |
| Issue invoice | Row action: delivery_confirmed | No POST route for SALES_TRANSIT → CLOSED delivery_confirmed transition in any routes_*.py | Future: POST /api/v1/inventory/pieces/{id}/confirm-delivery |
| Value column | Column: monetary value per piece | No value/price field in inventory_state pieces; packing_lines has cif_value but no join endpoint | Future: inventory_state.transition() can carry value from packing_db at issue time |
| Cross-batch aggregate | N/A in wireframe but implied | No GET endpoint aggregates SALES_TRANSIT across batches | Future: GET /api/v1/inventory/sales-transit-aggregate |
