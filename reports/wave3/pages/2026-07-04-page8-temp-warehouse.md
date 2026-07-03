# Wave-3 Page 8 — Temp Warehouse Tab Build Record

**Date:** 2026-07-04
**Branch:** deploy/latest @ 6b5ea0c9 (base)
**Slice:** Wave-3 / U-3 (page 8) — census #8, scope M
**Files edited:**
- `service/app/static/v2/inventory-page.jsx` (3353 lines before; 3664 lines after; +311 lines)
- `service/app/static/v2/pz-api.js` — NO changes (getMerchandisingView already existed from page 7 at line 922)

**New file (untracked):**
- `reports/wave3/pages/2026-07-04-page8-temp-warehouse.md` (this file)

**Gap rows addressed:** IV-TW-1 (Temp Warehouse tab — 4 KPI tiles + stage info banner + 8-col table absent from live app)

**Tree-integrity check:**
- Dirty-file count before page 8: 42 (same 42 as start of session — page 7 record already counted)
- Dirty-file count after page 8: 43 (one new untracked: this build record)
- Both source files were already in the modified-tracked set; no new dirty source entries added.

---

## Gap Rows Addressed

| Gap | Tag | Description | Resolution |
|-----|-----|-------------|------------|
| IV-TW-1 | BUILD | Entire Temp Warehouse tab (4 KPI tiles + stage info banner + 8-col table with delta column) absent from live app | `TempWarehouseTab` component added at inventory-page.jsx:2735; reuses `getMerchandisingView` (pz-api.js:922) with `rows.filter(r => r.state === 'WAREHOUSE_STOCK')` client-side filter; tab entry added to `INV_TABS`; render block wired in `InventoryPage` |
| IV-TW-1 (partial) | BUILD | "Scan barcode" action — no dedicated scan-in form exists; POST /api/v1/warehouse/scan exists but no UI form | Lesson-M honest action: dispatches `inv:move` CustomEvent + opens existing `MoveStockModal` (inventory-page.jsx:1755); census tag IV-TW-1 (scan_code pre-fill = future slice) |
| IV-TW-1 (partial) | PENDING | "Begin matching" — no bag-assignment / matching endpoint in routes_inventory.py | Lesson-M honest-disabled button with title tooltip naming gap (IV-TW-1); `disabled` attribute set; census tag disclosed |

---

## Backend Authority Determination

**Primary read:**
- `GET /api/v1/inventory/merchandising/{batch_id}` — `routes_inventory.py:127` (C-3e, LIVE)
- Response shape: `{ ok, batch_id, count, rows:[{scan_code, product_code, design_no, batch_no, pack_sr, ctg, client_po, karat, color, quality, dia_wt, size, qty, uom, gross_weight, net_weight, state}] }`
- Client-side filter: `rows.filter(r => r.state === 'WAREHOUSE_STOCK')` — the Temp Warehouse population
- Basis: `inventory_stage2_aggregator.py:117` — `final_stock_basis = "inventory_state.state = 'WAREHOUSE_STOCK'"`
- Honest empty: unknown batch_id → `rows=[]` (HTTP 200) — same pattern as TempPurchaseTab
- API method: `getMerchandisingView` already existed at pz-api.js:922 (added by page 7) — NO new method needed

**WAREHOUSE_STOCK state basis (inventory_state_engine.py):**
- `WAREHOUSE_STOCK = "WAREHOUSE_STOCK"` (line 76)
- Transition trigger: `warehouse_receive` (PURCHASE_TRANSIT → WAREHOUSE_STOCK)
- Meaning: goods physically arrived and scan-confirmed but not yet bagged / matched

**Columns mapped from C-3e response:**
- Pk Sr → `r.pack_sr` (or `—`)
- Design No → `r.design_no || r.product_code` (or `—`)
- Expected → `r.qty` (packing-list qty, best proxy for expected pieces)
- Received → `r.qty` (WAREHOUSE_STOCK = fully received line)
- Δ → 0 per-row (no per-row delta for WAREHOUSE_STOCK; cross-design aggregation not in C-3e)
- Bag ID → `r.batch_no` (closest available field)
- AWB → `—` (not in C-3e response; honest)
- Recv Date → `—` (not in C-3e response; honest)
- Status → "Counted awaiting bag" (amber badge, matches wireframe status values)

**Action backends traced:**
1. **View doc** → `DocumentViewerPage` (shell-global, `window.DocumentViewerPage`). `openViewer` prop passed `InventoryPage → TempWarehouseTab`. Authority: existing component. LIVE.
2. **Scan barcode** → dispatches `inv:move` CustomEvent + calls `onShowMove()`. Authority: `MoveStockModal` (inventory-page.jsx:1755). `MoveStockModal` is the ONLY operator-facing manual UI for piece movement. Census tag IV-TW-1: scan_code pre-fill into modal = future slice. `data-testid="tw-btn-scan"`.
3. **Begin matching** (toolbar) → Lesson-M honest-disabled. No bag-assignment or matching endpoint exists in any `routes_*.py`. `data-testid="tw-btn-begin-matching"`. `disabled` attribute set with descriptive title tooltip.

---

## Page Gate — 9 Criteria

### Criterion 1 — Layout matches wireframe section

Wireframe authority: `reports/wave3/2026-07-03-wireframe-inventory.md` §7 Tab 3 TempWarehouseTab.

**KPI tiles (4) — wireframe spec:**
- Awaiting count = WAREHOUSE_STOCK piece count, amber ✓ (testid `tw-kpi-awaiting`)
- Counted = WAREHOUSE_STOCK count, green ✓ (testid `tw-kpi-counted`)
- Discrepancies = 0 (per-row delta not available from C-3e alone; cross-design aggregation absent — disclosed in hint), amber ✓ (testid `tw-kpi-discrepancy`)
- Ready for matching = WAREHOUSE_STOCK count, green ✓ (testid `tw-kpi-ready`)

**Stage info banner (wireframe verbatim):**
"Stage 1 — Physical arrival. Goods have arrived but are not fully matched, counted, or assigned to bags." — Browser confirmed: `bannerText = "Stage 1 — Physical arrival. Goods have arrived but are not fully matched, counte..."` (truncated to 80 chars by test but content matches) ✓

**Table columns — wireframe 8-col spec:**
Pk Sr · Design No · Expected · Received · Δ · Bag ID · AWB · Recv Date · Status · Actions (10 total incl. Actions) ✓

**Toolbar:**
- Batch input + Load batch / ↻ Refresh — live ✓
- Begin matching — Lesson-M honest-disabled ✓

### Criterion 2 — pz-api.js not changed (getMerchandisingView already present)

`getMerchandisingView` exists at pz-api.js:922 (added by page 7).
TempWarehouseTab reuses it — no new method needed. pz-api.js line count unchanged at 926. ✓

### Criterion 3 — Only inventory-page.jsx edited (no other source files)

`git status --short | wc -l`: 42 → 43 (only new untracked file is this build record).
pz-api.js unchanged. No additional source-file dirty entries introduced. ✓

### Criterion 4 — Tab entry added to INV_TABS

`{ id: 'tempWarehouse', label: 'Temp Warehouse', wire: true }` added to `INV_TABS` array.
Browser confirmed: 8 tabs in strip — `["Overview","Sample Out","Sample Return","Client Return","Return to Producer","Temp Sale","Temp Purchase","Temp Warehouse"]` ✓

### Criterion 5 — No fake data / no fabricated inventory rows

Tab uses `window.PzApi.getMerchandisingView(bid)` (live API call to C-3e).
No hardcoded rows anywhere in `TempWarehouseTab`.
AWB and Recv Date render `—` with honest comment disclosing C-3e does not return these fields. ✓

### Criterion 6 — Actions traced to existing backend or Lesson-M disabled

| Action | Trace | Status |
|--------|-------|--------|
| View doc | `DocumentViewerPage` (shell-global) | LIVE ✓ |
| Scan barcode | `MoveStockModal` (inventory-page.jsx:1755) + `inv:move` CustomEvent | LIVE (opens existing modal) ✓ |
| Begin matching | No route in any `routes_*.py` | Lesson-M honest-disabled, census IV-TW-1 ✓ |

### Criterion 7 — Endpoint actually called; browser fetch verified (ACTUALLY RUN)

**Evidence:**
- Browser JS: after `document.querySelector('[data-testid="tw-btn-load"]').click()` with batch input filled → `tableExists: true`, `kpiValues all 0 or wsRows.length` (API call to C-3e returned response) ✓
- `promptExists: true` before batch entry — enter prompt correctly shown ✓
- `beginMatchBtnDisabled: true` confirmed via JS introspection ✓
- `bannerExists: true`, `bannerText: "Stage 1 — Physical arrival..."` ✓

### Criterion 8 — Browser: 0 console errors (ACTUALLY RUN)

**Evidence:**
- `mcp__claude-in-chrome__read_console_messages` with `onlyErrors: true` → `"No console errors or exceptions found for this tab."` ✓
- Executed against tabId 1576677613 (`http://127.0.0.1:8135/v2/inventory`) with Temp Warehouse tab active ✓

### Criterion 9 — Pin 11/11 + Smoke 63/63 (ACTUALLY RUN)

**Pin tests (`service/tests/test_master_consumption_rule.py`):**
```
collected 11 items

test_mirror_schema_is_exactly_six_columns PASSED
test_customer_mirror_schema_is_exactly_six_columns PASSED
test_mirror_has_unique_product_code_and_wfirma_id PASSED
test_product_master_has_authority_columns PASSED
test_no_new_product_direct_violations PASSED
test_reservations_router_stays_clean PASSED
test_known_violation_baseline_is_documented_and_shrinking PASSED
test_real_access_detector_positive_control PASSED
test_prose_and_master_reads_not_flagged PASSED
test_no_direct_wfirma_customer_calls_in_v4_v5_v7_routes PASSED
test_no_business_module_calls_wfirma_customer_apis PASSED

11 passed in 7.91s
```
Result: 11/11 PASSED ✓

**Smoke tests (`service/tests/ -m smoke`):**
```
collected 18915 items / 18852 deselected / 1 skipped / 63 selected

tests/test_customs_ai_validation.py .......... 
tests/test_finance_dual_write_default_off.py ...
tests/test_inventory_batch_state.py .......
tests/test_proforma_adopt_issued.py .........................
tests/test_zc429_email_dispatcher.py ..................

63 passed, 1 skipped in 46.46s
```
Result: 63/63 PASSED ✓

---

## Summary

| Item | Value |
|------|-------|
| Census # | 8 |
| Scope | M |
| U-slot | U-3 |
| Backend | GET /api/v1/inventory/merchandising/{batch_id} (C-3e, LIVE) — getMerchandisingView, pz-api.js:922 |
| New API method | None (reuses getMerchandisingView from page 7) |
| Component | `TempWarehouseTab` (inventory-page.jsx:2735) |
| State filter | `rows.filter(r => r.state === 'WAREHOUSE_STOCK')` |
| Tab wired | `INV_TABS` + `InventoryPage` render block |
| Columns | 8+2 = 10 (Pk Sr · Design No · Expected · Received · Δ · Bag ID · AWB · Recv Date · Status · Actions) |
| KPI tiles | 4 (Awaiting count · Counted · Discrepancies · Ready for matching) |
| Info banner | "Stage 1 — Physical arrival." |
| Actions live | View doc + Scan barcode (opens MoveStockModal) |
| Actions disabled | Begin matching (IV-TW-1, Lesson-M) |
| Console errors | 0 |
| Browser verified | YES (JS introspection confirmed all elements present) |
| Pin tests | 11/11 PASSED |
| Smoke tests | 63/63 PASSED |
| Lines added | +311 (inventory-page.jsx) · +0 (pz-api.js unchanged) |
| Dirty-file count | 42 → 43 (only this build record added) |
