# Wave-3 Page 7 — Temp Purchase Tab Build Record

**Date:** 2026-07-03
**Branch:** deploy/latest @ f17ef844 (base)
**Slice:** Wave-3 / U-3 (page 7) — census #7, scope L (merchandising-grade register)
**Files edited:**
- `service/app/static/v2/inventory-page.jsx` (3068 lines before; 3353 lines after; +285 lines)
- `service/app/static/v2/pz-api.js` (909 lines before; 926 lines after; +17 lines)

**New file (untracked):**
- `reports/wave3/pages/2026-07-03-page7-temp-purchase.md` (this file)

**Gap rows addressed:** IV-TP-1 (Temp Purchase merchandising register — C-3e wired), IV-TP-2 (Upload Packing List — Lesson-M honest-disabled)

**Tree-integrity check:**
- Dirty-file count before page 7: 42
- Dirty-file count after page 7: 43 (one new untracked: this build record)
- Both edited source files (`inventory-page.jsx`, `pz-api.js`) were already in the modified-tracked set; no new dirty entries added to existing source files.

---

## Gap Rows Addressed

| Gap | Tag | Description | Resolution |
|-----|-----|-------------|------------|
| IV-TP-1 | BUILD | Temp Purchase merchandising register absent; C-3e backend shipped Wave 2 | `TempPurchaseTab` component added; `getMerchandisingView` added to pz-api.js Wave-3 block; tab entry added to `INV_TABS`; render wired in `InventoryPage` with `openViewer` + `onShowMove` props |
| IV-TP-1 (partial) | BUILD | "Receive" action — manual piece promotion has no dedicated endpoint beyond MoveStockModal | Lesson-M honest action: dispatches `inv:move` CustomEvent + opens existing `MoveStockModal` (inventory-page.jsx:1755); census tag IV-TP-1 (scan_code pre-fill future slice) |
| IV-TP-2 | PENDING | "Upload Packing List" — no packing-list upload endpoint in `routes_inventory.py` | Lesson-M honest-disabled button with title tooltip naming future route (`POST /api/v1/packing-lists/upload`); census tag IV-TP-2 |

---

## Backend Authority Determination

**Primary read:**
- `GET /api/v1/inventory/merchandising/{batch_id}` — `routes_inventory.py:127` (C-3e, LIVE)
- Response shape: `{ ok, batch_id, count, rows:[{scan_code, product_code, design_no, batch_no, pack_sr, ctg, client_po, karat, color, quality, dia_wt, size, qty, uom, gross_weight, net_weight, state}] }`
- Client-side filter: `rows.filter(r => r.state === 'PURCHASE_TRANSIT')` — the Temp Purchase population
- Honest empty: unknown `batch_id` → `rows=[]` (HTTP 200) — verified live at endpoint
- Cross-batch aggregate: NO endpoint exists. Tab uses per-batch batch selector (BatchPanel precedent).

**Action backends traced:**
1. **View doc** → `DocumentViewerPage` (shell-global, `window.DocumentViewerPage`). `openViewer` prop passed `InventoryPage → TempPurchaseTab`. Authority: existing component. LIVE.
2. **Receive** → dispatches `inv:move` CustomEvent + calls `onShowMove()`. Authority: `MoveStockModal` (inventory-page.jsx:1755). `run_stock_promotion()` (stock_promotion.py) is the document-driven backend (BE-1) for PURCHASE_TRANSIT→WAREHOUSE_STOCK; `MoveStockModal` is the ONLY operator-facing manual UI. Census tag IV-TP-1: scan_code pre-fill into modal = future slice.
3. **Upload Packing List** (toolbar) → Lesson-M honest-disabled. No `POST /api/v1/packing-lists/upload` route exists in any `routes_*.py`. The existing `inv:upload` CustomEvent targets the document hub (`routes_upload`), which is not packing-list ingestion. Census tag IV-TP-2.

---

## Page Gate — 9 Criteria

### Criterion 1 — Layout matches wireframe section

Wireframe authority: `docs/design/inventory-page.design.jsx` `TempPurchaseTab` (lines 6472–).

**KPI tiles (4) — wireframe `stats` array:**
- Open packing lists = total rows in batch ✓ (testid `tp-kpi-open`)
- Awaiting goods (lines) = PURCHASE_TRANSIT count, amber ✓ (testid `tp-kpi-awaiting`)
- Partially arrived = rows with empty state, amber ✓ (testid `tp-kpi-partial`)
- Closed-out = rows beyond PURCHASE_TRANSIT, green ✓ (testid `tp-kpi-closed`)

**Stage 1 info banner (wireframe verbatim):**
"Stage 1 — Document layer. These lines come from supplier invoices & packing lists. Goods are *expected* but not physically confirmed. No final stock is created here." ✓

**Table header — wireframe `InvTable columns` exact order:**
Table title: "Open packing-list lines" ✓  
Badge: "from invoices & packing lists" ✓  
Columns (13): PK SR · CTG · CLIENT PO · DESIGN NO · KARAT · COLOR · QUALITY · DIA WT · COL WT · QTY · SIZE · STATE · ACTIONS ✓  
(Note: wireframe's `Total` and `AWB` columns are not in the C-3e response; Col Wt maps to `net_weight`; State = PURCHASE_TRANSIT badge; this is the correct C-3e-backed mapping per task authority)

**Row actions (wireframe per-row `actions`):**
- "View doc" — live, opens DocumentViewer ✓
- "Receive" — opens MoveStockModal (existing authority) ✓

**Toolbar actions (wireframe toolbar):**
- Load batch / ↻ Refresh — live ✓
- + Upload Packing List — Lesson-M honest-disabled with census tag IV-TP-2 ✓

### Criterion 2 — API method added IMMEDIATELY AFTER `getInventoryMovements` in Wave-3 block

`getMerchandisingView` added at `pz-api.js:907–924`, immediately after `getInventoryMovements` block ending at line 905.
Verified: `grep -n "getMerchandisingView" pz-api.js` → line 922. ✓

### Criterion 3 — Only inventory-page.jsx and pz-api.js edited (no other source files)

`git status --short | wc -l`: 42 → 43 (only new untracked file is this build record).
No additional source-file dirty entries introduced. ✓

### Criterion 4 — Tab entry added to INV_TABS

`{ id: 'tempPurchase', label: 'Temp Purchase', wire: true }` added to `INV_TABS` array (inventory-page.jsx:3256). ✓

### Criterion 5 — No fake data / no fabricated inventory rows

Tab uses `window.PzApi.getMerchandisingView(bid)` (live API call to C-3e).
No hardcoded rows anywhere in `TempPurchaseTab`. ✓
Honest-empty state rendered when no PURCHASE_TRANSIT rows exist. ✓

### Criterion 6 — 3 actions traced to existing backend or Lesson-M disabled

| Action | Trace | Status |
|--------|-------|--------|
| View doc | `DocumentViewerPage` (shell-global) | LIVE ✓ |
| Receive | `MoveStockModal` (inventory-page.jsx:1755) — existing authority | LIVE (opens existing modal) ✓ |
| Upload Packing List | No route in `routes_inventory.py` | Lesson-M honest-disabled, census IV-TP-2 ✓ |

### Criterion 7 — Endpoint actually called; browser fetch verified (ACTUALLY RUN)

**Evidence:**
- `curl -s "http://127.0.0.1:8135/api/v1/inventory/merchandising/SHIPMENT_TEST_NONEXISTENT"` → `{"ok":true,"batch_id":"SHIPMENT_TEST_NONEXISTENT","count":0,"rows":[]}` ✓
- `curl -s "http://127.0.0.1:8135/v2/pz-api.js" | grep "getMerchandisingView"` → `getMerchandisingView: (batchId) =>` ✓ (served from running uvicorn on port 8135)
- JS verify: after entering `TEST_BATCH_123` and clicking Load batch — `emptyExists: true`, `tableExists: true`, `kpiValues all 0` (API call to C-3e returned `rows:[]`) ✓

### Criterion 8 — Browser: Temp Purchase tab renders with 0 console errors (ACTUALLY RUN)

**Evidence (browser-verified, tab ID 1576677613):**
- `mcp__claude-in-chrome__javascript_tool` confirmed: `tpTabExists: true`, `kpiTileCount: 4`, `bannerExists: true`, `toolbarExists: true`, `promptExists: true` ✓
- After load: `tableExists: true`, `emptyExists: true`, `refreshBtnExists: true`, `kpiCount 4+strip` ✓
- Column count confirmed: `columnCount: 13` with exact headers `[PK SR, CTG, CLIENT PO, DESIGN NO, KARAT, COLOR, QUALITY, DIA WT, COL WT, QTY, SIZE, STATE, ACTIONS]` ✓
- `read_console_messages` → No console messages (0 errors) ✓
- Screenshot captured (ss_2446u7gjd): Temp Purchase tab active, Stage 1 banner visible, 4 KPI tiles, 13-column table with honest-empty message, footer endpoint reference ✓

### Criterion 9 — Wave-3 comment block matches all pages 1-6 pattern (ACTUALLY RUN)

Pattern check against pages 1-6:
- Header comment block with Wireframe authority, backend reads, column definitions, KPI mapping, action traces, Lesson-M disclosures, census tags ✓
- `data-testid` on root (`temp-purchase-tab`), KPI strip (`tp-kpi-strip`), toolbar (`tp-toolbar`), batch input (`tp-batch-input`), load button (`tp-btn-load`), upload button (`tp-btn-upload`), table (`tp-table`), empty state (`tp-empty`), info banner (`tp-info-banner`), refresh (`tp-refresh`) ✓
- `InvStatTile`, `InvFetchBtn` used (same shared components as pages 1-6) ✓
- Inline `TH`/`TD` style objects (same pattern as TempSaleTab page 5) ✓
- `useCallback` for `load` function (same as pages 1-5) ✓
- Endpoint reference footer (same as TempSaleTab) ✓

---

## Summary

| Item | Value |
|------|-------|
| Census # | 7 |
| Scope | L (merchandising-grade register) |
| U-slot | U-3 |
| Backend | GET /api/v1/inventory/merchandising/{batch_id} (C-3e, LIVE) |
| New API method | `getMerchandisingView` (pz-api.js:922) |
| Component | `TempPurchaseTab` (inventory-page.jsx:2449) |
| Tab wired | `INV_TABS` + `InventoryPage` render |
| Columns | 13 (PK SR · CTG · CLIENT PO · DESIGN NO · KARAT · COLOR · QUALITY · DIA WT · COL WT · QTY · SIZE · STATE · ACTIONS) |
| KPI tiles | 4 (Open packing lists · Awaiting goods · Partially arrived · Closed-out) |
| Actions live | View doc + Receive (opens MoveStockModal) |
| Actions disabled | Upload Packing List (IV-TP-2) |
| Console errors | 0 |
| Browser verified | YES (JS introspection + API fetch verified) |
| Screenshot | ss_2446u7gjd (captured 2026-07-03) |
| Lines added | +285 (inventory-page.jsx) · +17 (pz-api.js) |
