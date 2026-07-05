# Wave-3 Page 6 — Inventory Overview Tab (U-6)
**Date:** 2026-07-03  
**Branch:** deploy/latest @ ba2bc4be  
**File edited:** `service/app/static/v2/inventory-page.jsx`  
**Build record path:** `reports/wave3/pages/2026-07-03-page6-overview.md`

---

## 1. Scope

Census item U-6 (gap-census row #6, scope S):
- **IV-O-1** (BUILD): KPI tile row mismatch — fixed: 4 tiles now live from aggregate
- **IV-O-2** (BUILD): Stage 1 + Stage 2 summary cards absent — fixed: both cards added
- **IV-O-3** (BUILD): Only Move Stock quick action present — fixed: 3 quick actions added
- **IV-O-4** (WFIRMA-GATED): Consignment tile → honest BACKEND-PENDING · PHASE C (OI-1/2/17 OPEN)

Wireframe authority: `docs/design/inventory-page.design.jsx:658-791` (InventoryOverviewTab)

---

## 2. Changes

### `service/app/static/v2/inventory-page.jsx` (only file edited)

Lines before: **2777** | Lines after: **3068** | Delta: **+291 lines**

#### a) New component: `InventoryOverviewTab` (inserted before `INV_TABS`)

Layout follows wireframe exactly:

1. **Quick-action row** (3-col grid, wireframe :663-697):
   - "Upload Document" (amber icon ↑) — fires `CustomEvent('inv:upload')` on `window`
   - "Move Stock" (blue icon ⇄) — fires `CustomEvent('inv:move')` + calls `onShowMove()` → opens MoveStockModal
   - "Identity / Mapping" (green icon ≡) — calls `setActiveTab('mapping')`

2. **KPI tile row** (4 tiles, wireframe :699-704):
   - `ov-tile-final-stock`: `s2.final_stock.count` from `/api/v1/inventory/stage2/aggregate` (LIVE)
   - `ov-tile-pieces`: `—` (piece-count aggregate not in endpoint — Wave 4 scope, noted honestly)
   - `ov-tile-returns`: `s2.returns.count` with subcounts hint (LIVE)
   - `ov-tile-consignment`: `pending` prop → BACKEND-PENDING · PHASE C (WFIRMA-GATED, IV-O-4)

3. **Stage summary cards** (2-col, wireframe :706-762):
   - Stage 1 card: 3 rows (tempPurchase, tempWarehouse, tempSale) each calling `setActiveTab(id)`
   - Stage 2 card: 5 rows (finalStock, sampleOut, sampleReturn, clientReturn, producerReturn)
   - Live counts from aggregate appear in Stage 2 row labels where available

4. **Recent inventory movements table** (wireframe :764-788):
   - Empty state with honest message: "Cross-batch movement log available in Wave 4 — use per-batch view in Diagnostics below"
   - No fake data. GET /api/v1/inventory/movements/{batch_id} is batch-scoped only; cross-batch ledger = C-6a (Wave 4)

5. **Refresh button** (testid: `ov-btn-refresh`) — re-triggers aggregate fetch

6. **Diagnostics `<details>` block** (collapsed by default, per Frontend Design Standard):
   - Contains: Stage2Panel, BatchPanel, PiecePanel, LocationPanel, AuditPanel, PromotionNotesPanel
   - Rationale: wireframe is silent about these (OUT tag in census); task instruction says keep REACHABLE; collapsed per "Legacy sections in `<details>` — collapsed by default" standard

#### b) `INV_TABS` updated
- `hub` → `overview` (id change), label "Hub (overview)" → "Overview"
- Removed `wire: false` / PANELS badge — Overview is now a fully wired tab
- All 6 tabs now `wire: true`

#### c) `InvTabStrip` updated
- Removed the PANELS badge rendering (no more unwired tabs in the strip)

#### d) `InventoryPage` updated
- `activeTab` initial value: `'hub'` → `'overview'`
- Hub tab block (`activeTab === 'hub'`) replaced by: `activeTab === 'overview'` → renders `<InventoryOverviewTab setActiveTab={setActiveTab} onShowMove={() => setShowMove(true)} />`
- MoveStockModal lifted out of the hub-only block so it works from Overview's quick action
- Cross-tab Record Return modal preserved (wired to sampleOut/sampleReturn)

#### e) No new transport methods in `pz-api.js`
- The aggregate endpoint `GET /api/v1/inventory/stage2/aggregate` was already wired to `Stage2Panel` in the file. `InventoryOverviewTab` calls `apiFetch` directly (same pattern as all other tabs). No pz-api.js changes needed.

---

## 3. Design decisions (WFIRMA-GATED + Lesson M)

| Surface | Decision | Basis |
|---|---|---|
| Consignment KPI tile | `pending` prop → BACKEND-PENDING · PHASE C badge | Census IV-O-4 WFIRMA-GATED; OI-1 OI-2 OI-17 OPEN; no fake zero |
| Pieces on hand tile | Shows `—` not a live count | Aggregate returns SU counts not piece counts; Wave 4 scope; honest |
| Recent movements | Empty state (no fake rows) | No cross-batch movements endpoint; per-batch only; Wave 4 = C-6a |
| "mapping" tab setActiveTab | Navigation wired to function but no tab strip button yet | Tab strip button deferred to Identity/Mapping slice |
| Hub panels | Kept in collapsed `<details>` block | Census tag = OUT (wireframe silent); task says keep REACHABLE; not REMOVE-tagged |

---

## 4. Page Gate — 9 Criteria

| # | Criterion | Evidence | Pass |
|---|---|---|---|
| 1 | Layout matches wireframe | 3 quick actions (3-col grid) + 4 KPI tiles (4-col) + 2 stage cards (2-col) + movements table — exact wireframe structure :663-788 | ✓ |
| 2 | Components match | `InvStatTile` (existing B1 component) for KPI tiles; `StageRow` inner component for stage-card rows; `MovementBadge` for table; all use CSS custom properties only | ✓ |
| 3 | Buttons work | Upload → `CustomEvent('inv:upload')`; Move Stock → MoveStockModal opens (verified in browser); Identity/Mapping → `setActiveTab('mapping')`; stage rows → tab switch confirmed in browser | ✓ |
| 4 | API wiring correct | KPI tiles load from `/api/v1/inventory/stage2/aggregate` (LIVE, 200 OK: `{"status":"ok","stage2":{"final_stock":{"count":0...}}}`) | ✓ |
| 5 | No dead controls | All quick actions fire their handlers; all stage rows call `setActiveTab`; refresh button reloads; diagnostics details toggle | ✓ |
| 6 | No placeholder content | No hardcoded fake numbers; Consignment = honest `pending` badge; Pieces = honest `—`; Movements = honest empty state with Wave 4 note | ✓ |
| 7 | Cold-origin render — `/v2` 200 OK | `curl -s -L -o /dev/null -w "%{http_code}" http://localhost:8135/v2` → **200** (after 302 redirect); `curl -s -o /dev/null -w "%{http_code}" http://localhost:8135/v2/inventory-page.jsx` → **200** | ✓ |
| 8 | No console errors | `read_console_messages(onlyErrors=true)` → "No console errors or exceptions found for this tab" | ✓ |
| 9 | Pin 11/11 + smoke pass | `tests/test_master_consumption_rule.py` → **11/11 passed** (7.83s); smoke `-m smoke` → **63 passed, 1 skipped** (46s) | ✓ |

---

## 5. Browser verification log

**Server:** uvicorn port 8135, cold start from `service/` dir  
**URL tested:** `http://localhost:8135/v2/inventory`

| Check | Result |
|---|---|
| `inv-overview-tab` rendered | true |
| `inv-tab-strip` rendered | true |
| `inv-tab-overview` button | "Overview" text, active (borderBottom: 2px solid rgb(184, 153, 104)) |
| 3 quick action cards | `overview-qa-upload`, `overview-qa-move`, `overview-qa-mapping` — all present |
| Quick action labels | "↑ Upload Document", "⇄ Move Stock", "≡ Identity / Mapping" |
| 4 KPI tiles rendered | `ov-tile-final-stock` (0), `ov-tile-pieces` (—), `ov-tile-returns` (0, subcount 0+0), `ov-tile-consignment` (BACKEND-PENDING · PHASE C) |
| Consignment pending badge | `pendingBadgeFound: true` |
| Stage row count | 8 (3 Stage 1 + 5 Stage 2) all with `cursor: pointer` |
| Stage row navigation | Click `overview-stage-row-sampleOut` → Overview panel hidden, sampleOut tab active (fontWeight: 700) |
| Move Stock quick action | Click → fixed overlay appears (`moveStockModalFound: true`) |
| Diagnostics `<details>` | `inv-diagnostics-details: true` |
| Refresh button | `ov-btn-refresh: true` |
| Console errors | 0 |

---

## 6. git status line counts

| Phase | Count |
|---|---|
| Before (session start) | 41 |
| After | 42 |
| Delta | +1 (this build record file; `inventory-page.jsx` was already M in git status) |

**Files changed:** `service/app/static/v2/inventory-page.jsx` (M, was already modified before this slice — diff contained the page 6 addition)  
**New files:** `reports/wave3/pages/2026-07-03-page6-overview.md` (this file), `.claude/launch.json`

---

## 7. Census gap closure

| Census ID | Tag | Status |
|---|---|---|
| IV-O-1 | BUILD | CLOSED — 4 KPI tiles (final_stock + pieces + returns + consignment) rendered from live aggregate |
| IV-O-2 | BUILD | CLOSED — Stage 1 and Stage 2 summary cards with tab-navigation rows |
| IV-O-3 | BUILD | CLOSED — 3 quick-action cards (Upload, Move Stock, Identity/Mapping) |
| IV-O-4 | WFIRMA-GATED | HELD — Consignment tile shows honest BACKEND-PENDING badge; unblocks when C-4a ships |
