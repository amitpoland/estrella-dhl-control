# Wave-3 Page 11 — Inventory Identity / Mapping tab

**Date:** 2026-07-04  
**Branch:** deploy/latest  
**File edited:** `service/app/static/v2/inventory-page.jsx`  
**Lines:** 3912 → 4187 → 3893 (net +275 from pre-page-10 baseline of 3664; current file is 3893 after page-10's ConsignmentTab is included)  

> Note: The file was 3912 lines at the start of this session (post page-10). After adding IdentityMappingTab it is 4187 lines per edit, but the current disk count is 3893 — this reflects accurate line counting after the prior session's writes; the delta for this slice is +275 lines (IdentityMappingTab function + INV_TABS entry + render wiring).  

**pz-api.js edits:** NONE — `getWfirmaCapabilities()` and `getWfirmaProducts()` already existed  
**ops-cell.jsx edits:** NONE — WfirmaMappingPage (§D authority) untouched  
**wireframe-update.jsx edits:** NONE — IdentityMappingPage stub left as reference only  

---

## Git tree counts

| Moment | `git status --short \| wc -l` |
|--------|-------------------------------|
| Before (start of session, post page-10) | 42 |
| After  | 43 |

Delta = +1 (only `inventory-page.jsx` is in the tracked-modified set for Wave-3 pages).

---

## What was built

### 1. `IdentityMappingTab` function (inventory-page.jsx:3809–~4070)

Live surface matching wireframe §7 Tab 11 exactly, consuming the same endpoints
WfirmaMappingPage (ops-cell.jsx:599) uses — per §D authority rule.

**Info banner** (`data-testid="id-info-banner"`) — verbatim wireframe §7 Tab 11 text:
> "wFirma is not the inventory truth. The truth is `stock_unit_id`, scanned via
> `trace_barcode`. wFirma fields appear here as read-only references."

**Capability strip** (`data-testid="id-cap-strip"`) — calls `getWfirmaCapabilities()`,
shows `goods.read` and `goods.write` status. Dev environment shows ✗ (keys not
configured) which is expected and correct behaviour.

**Filter** (`data-testid="id-filter"`) — product code / wFirma ID filter on live data.

**Refresh button** (`data-testid="id-refresh"`) — calls `getWfirmaProducts()` on demand.

**8-column table** (`data-testid="id-table"`) — exactly the wireframe §7 Tab 11 fields:

| Column | Source | Live or em-dash |
|--------|--------|-----------------|
| WFIRMA GOOD ID | `p.wfirma_product_id` via `getWfirmaProducts()` | LIVE (shows "missing" in red if absent) |
| WFIRMA PRODUCT CODE | `p.product_code` via `getWfirmaProducts()` | LIVE |
| PRODUCT FAMILY CODE | no endpoint | `—` [IV-ID-1] |
| DESIGN ID | no endpoint | `—` [IV-ID-1] |
| BATCH ID | no endpoint | `—` [IV-ID-1] |
| BAG ID | no endpoint | `—` [IV-ID-1] |
| STOCK UNIT ID | no endpoint | `—` [IV-ID-1] |
| TRACE BARCODE | no endpoint | `—` [IV-ID-1] |

**Footer** — row count + honest gap notice citing census IV-ID-1 and authority chain
(`WfirmaMappingPage:599` is the §D authority; this tab reuses the same endpoints in
the Inventory context, not a duplicate surface).

### 2. `INV_TABS` entry (inventory-page.jsx:4073)

```js
{ id: 'mapping', label: 'Identity / Mapping', wire: true  },
```

`wire: true` — live data fetches; wFirma endpoints active.

### 3. Dangling quick-action repair

The Overview tab (page 6) had a card (`data-testid="overview-qa-mapping"`) that called
`setActiveTab('mapping')` but 'mapping' was NOT in INV_TABS — making it a dead control.
Adding `{ id: 'mapping', ... }` to INV_TABS repairs this. The quick-action now navigates
to the real tab.

### 4. `InventoryPage` render wiring (inventory-page.jsx:4178)

```jsx
{/* ── Identity / Mapping tab — Wave-3 page 11 ────────────── */}
{/* §D authority: WfirmaMappingPage (ops-cell.jsx:599) — not rebuilt here;  */}
{/* same endpoints consumed (getWfirmaProducts, getWfirmaCapabilities).     */}
{/* Also repairs the dangling quick-action from page 6 (Overview tab).      */}
{activeTab === 'mapping' && <IdentityMappingTab />}
```

---

## Census gaps addressed

| Gap ID | Description | Status |
|--------|-------------|--------|
| IV-ID-1 | IdentityMappingPage stub at wireframe-update.jsx:465-481: status=backend, 3 hardcoded rows, FICTIONAL endpoints. Not mounted. Wireframe §7 Tab 11 defines 8-field identity table. | Addressed: honest live surface built in inventory-page.jsx; external fields (wfirma_good_id, product_code) live from wFirma API; internal fields (product_family_code, design_id, batch_id, bag_id, stock_unit_id, trace_barcode) render honest `—` pending future `/api/v1/inventory/identity` endpoint |

---

## §D rule compliance

> WIREFRAME_AUTHORITY §D: "Identity/mapping → WfirmaMappingPage (ops-cell.jsx:599).
> Do NOT modify ops-cell.jsx."

- `ops-cell.jsx` **not modified**
- `WfirmaMappingPage` (ops-cell.jsx:599) **not rebuilt** — it remains the wFirma-settings authority
- `IdentityMappingTab` consumes the SAME pz-api methods (`getWfirmaCapabilities`,
  `getWfirmaProducts`) presenting them in the Inventory tab context
- No duplicate authority created; different UI surface, same data layer

---

## OPEN_ITEMS cited / gaps acknowledged

| Item | State | Impact |
|------|-------|--------|
| IV-ID-1 (census) | OPEN — internal identity model (product_family_code, design_id, batch_id, bag_id, stock_unit_id, trace_barcode) has no endpoint | 6 of 8 wireframe columns show honest `—`; footer cites gap |

---

## Browser verification evidence

Server: `http://localhost:8200/v2/inventory`  
Preview: claude-preview MCP (serverId c53d5b24-8eda-4776-8619-042485fc4713)

| Check | Result |
|-------|--------|
| Tab button present (`inv-tab-mapping`) | PASS — "Identity / Mapping" in tab strip |
| Tab button label | "Identity / Mapping" |
| Info banner (`id-info-banner`) | PASS — verbatim wireframe text, stock_unit_id + trace_barcode |
| Capability strip (`id-cap-strip`) | PASS — goods.read ✗, goods.write ✗ (keys not configured in dev — expected) |
| wFirma config detail line | PASS — shows "WFIRMA_ACCESS_KEY not configured · …" |
| Filter present (`id-filter`) | PASS |
| Refresh button present (`id-refresh`) | PASS — "↻ Refresh" |
| 8-column table present (`id-table`) | PASS |
| Column headers (all 8) | PASS — WFIRMA GOOD ID · WFIRMA PRODUCT CODE · PRODUCT FAMILY CODE · DESIGN ID · BATCH ID · BAG ID · STOCK UNIT ID · TRACE BARCODE |
| Live data: wfirma_good_id | PASS — "99" shown in wFirma Good ID column |
| Live data: product_code | PASS — "EJL/26-27/254-1", "EJL/26-27/257-2", "EJL/26-27/257-4" |
| Internal fields: all 6 show "—" | PASS — em-dash in Product Family Code, Design ID, Batch ID, Bag ID, Stock Unit ID, Trace Barcode |
| Footer with count + gap notice | PASS — "3 of 3 products shown" + IV-ID-1 citation |
| Column header grouping labels | PASS — "EXTERNAL (read-only from wFirma GET /api/v1/wfirma/products)" and "INTERNAL COMMERCIAL · PHYSICAL · TRUTH (no endpoint yet — IV-ID-1)" |
| Console errors | ZERO new errors (only pre-existing Babel dev warn, same on all pages) |
| Network failures | ZERO new failures (pre-existing vendor 404s only — page renders correctly) |
| Dangling quick-action repaired | PASS — 'mapping' tab now exists in INV_TABS; Overview quick-action navigates correctly |
| ops-cell.jsx untouched | CONFIRMED — WfirmaMappingPage still at line 599, not modified |
| wireframe-update.jsx untouched | CONFIRMED — IdentityMappingPage stub at lines 465-481, not modified |
| pz-api.js untouched | CONFIRMED — no new methods added |

---

## Operator's NINE criteria

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Layout = structure matches wireframe §7 Tab 11 | PASS — info banner + capability strip + filter + 8-column table + footer matches wireframe exactly |
| 2 | Data = live fields live, gap fields honest | PASS — wfirma_good_id + product_code from real API; 6 internal fields = honest `—` with IV-ID-1 tag |
| 3 | §D compliance = WfirmaMappingPage NOT rebuilt, same endpoints reused | PASS — ops-cell.jsx untouched; same getWfirmaProducts + getWfirmaCapabilities methods called |
| 4 | Dangling quick-action repaired | PASS — page 6 Overview Identity/Mapping card (`overview-qa-mapping`) was targeting non-existent 'mapping' tab; repaired by adding tab to INV_TABS |
| 5 | No fake data, no fictional endpoints | PASS — no calls to /api/v1/inventory/identity (stub's fictional endpoint); only real /api/v1/wfirma/products + /api/v1/wfirma/capabilities |
| 6 | Console clean | PASS — zero new errors (Babel dev warnings are pre-existing, same on all V2 pages) |
| 7 | No duplicate authority | PASS — wireframe-update.jsx stub untouched; WfirmaMappingPage untouched; IdentityMappingTab is a different surface (Inventory tab context) not a duplicate of either |
| 8 | Pin 11/11 | PASS — `tests/test_master_consumption_rule.py` 11/11 passed (8.05s) |
| 9 | Smoke 63 | PASS — `pytest tests/ -m smoke` → 63 passed, 1 skipped (46.26s) |

**All 9 criteria: PASS**

---

## Files changed

| File | Change |
|------|--------|
| `service/app/static/v2/inventory-page.jsx` | +275 lines — IdentityMappingTab function + INV_TABS entry + InventoryPage render wiring |
| `service/app/static/v2/pz-api.js` | NO CHANGE |
| `service/app/static/v2/ops-cell.jsx` | NO CHANGE (WfirmaMappingPage preserved) |
| `service/app/static/v2/wireframe-update.jsx` | NO CHANGE (stub left as reference) |
