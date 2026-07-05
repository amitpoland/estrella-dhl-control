# W3-page6b — Inventory PageHeader Actions Row

**Slice:** W3-page6b  
**Date:** 2026-07-04  
**Branch:** deploy/latest  
**File edited:** `service/app/static/v2/inventory-page.jsx` (4331 lines after edits)  
**Build record written by:** Claude Code (sonnet-4-6)  
**git status line count:** before=42 / after=43

---

## Summary

Implemented the Inventory PageHeader actions row — three controls from the wireframe header — inside `InventoryPage`. Also repaired the dead `inv:upload` CustomEvent in `InventoryOverviewTab` (census: REMOVE, no listener existed anywhere in the codebase).

### Controls added

| Control | Test ID | State | Wiring |
|---|---|---|---|
| ↑ Upload Document | `inv-hdr-upload` | ENABLED | `navigateToDocuments()` → `history.pushState` + `PopStateEvent('popstate')` → shell router |
| Cycle count | `inv-hdr-cycle-count` | DISABLED (planned) | IV-HDR-1 census tag, honest title naming gap |
| ↓ Export | `inv-hdr-export` | Context-sensitive | `handleExport()` → `exportCsv()` → Blob URL download |

### Export state machine

| Active tab | Export state | Title |
|---|---|---|
| Overview | disabled | "Export not available for this tab — select a data tab..." |
| Consignment | disabled | same |
| Mapping | disabled | same |
| Sample Out / Sample Return / Client Return / Producer Return / Temp Sale / Temp Purchase / Temp Warehouse | disabled when no rows loaded | "Load records in the active tab to enable export" |
| Any data tab with rows | ENABLED | "Export N rows from the current tab as CSV" |

### Dead control repair

`InventoryOverviewTab` "Upload Document" quick-action card previously dispatched `new CustomEvent('inv:upload')`. Grep confirmed zero listeners anywhere in the codebase. Replaced with `onClick={navigateToDocuments}` (census: REMOVE on the dangling event dispatch).

---

## New helpers added (inside IIFE, before `InventoryPage`)

```javascript
function navigateToDocuments() { ... }  // history.pushState + PopStateEvent
function exportCsv(headers, rows, filename) { ... }  // Blob URL → <a> click
```

## `InventoryPage` state additions

```javascript
const [exportMeta, setExportMeta] = useState(null);
const handleTabChange = useCallback(...);    // clears exportMeta on switch
const reportExport = useCallback(...);       // tabs call this with headers+rows
const handleExport = useCallback(...);       // fires exportCsv
const TABS_WITH_NO_TABLE = ['overview', 'consignment', 'mapping'];
```

## Tab signatures updated (reportExport prop)

All seven data tabs received `reportExport` prop:
`SampleOutTab`, `SampleReturnTab`, `ClientReturnTab`, `ProducerReturnTab`, `TempSaleTab`, `TempPurchaseTab`, `TempWarehouseTab`.

Each tab has a `useEffect` watching its loaded data state that calls `reportExport(headers, rows)` or `reportExport(null, null)` when empty.

---

## Nine-criteria gate table

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | **Three wireframe controls present** | PASS | DOM eval: 3 children in `[data-testid="inv-header-actions"]`, all correct testids |
| 2 | **Upload → real navigation (no fake event)** | PASS | `history.pushState({page:'documents'},'',' /v2/documents')` + `PopStateEvent` fires shell router; `inv:upload` event removed from Overview card |
| 3 | **Cycle count — Lesson-M planned-state honesty** | PASS | `disabled=true`, `opacity=0.6`, `cursor=not-allowed`, title names gap + census tag IV-HDR-1 |
| 4 | **Export — context-sensitive state** | PASS | Overview tab: title="Export not available for this tab..."; Sample Out (no data): title="Load records in the active tab to enable export"; no tab has hardcoded enable |
| 5 | **Dead `inv:upload` CustomEvent repaired** | PASS | Grep confirms zero remaining `inv:upload` dispatches; Overview card now calls `navigateToDocuments()` |
| 6 | **No spread-rest operator used** | PASS | Only named destructuring in all new code; no `{...rest}` anywhere in added code |
| 7 | **Browser verified — at least 2 tabs walked** | PASS | Overview: Export disabled (no-table tab); Sample Out: switched, Export disabled (no data, correct title change); Temp Warehouse: switched, Export disabled (no data) |
| 8 | **Regression tests green** | PASS | PZ regression: 160/160 passed; smoke suite: 63 passed, 1 skipped |
| 9 | **No commit/push/PR/deploy / C:\PZ untouched** | PASS | FORBIDDEN actions not taken; git status: only `inventory-page.jsx` modified + this build record |

---

## Browser verification evidence

```
[inv-header-actions] found: true
  top=177px, height=31px, width=1072px, children=3

[inv-hdr-upload]      disabled=false, cursor=pointer, opacity=1
[inv-hdr-cycle-count] disabled=true,  cursor=not-allowed, opacity=0.6
  title="Cycle count — IV-HDR-1: net-new capability, no backend owner..."

[Overview tab]
[inv-hdr-export] disabled=true, title="Export not available for this tab — select a data tab..."

[Sample Out tab (no records)]
[inv-hdr-export] disabled=true, title="Load records in the active tab to enable export"

[Temp Warehouse tab (no stock data in dev)]
[inv-hdr-export] disabled=true, title="Load records in the active tab to enable export"
```

---

## Test results

```
PZ regression: 160/160 PASS (python test_pz_regression.py)
Smoke suite:   63 PASS, 1 skipped (pytest tests/ -m smoke)
```

---

## Census tags

| Tag | Type | Control |
|---|---|---|
| IV-HDR-1 | WIREFRAME-REQUIRED (net-new, no backend owner) | Cycle count button |
| (REMOVE) | Dead CustomEvent dispatch in InventoryOverviewTab | `inv:upload` |

---

## Scope guard

Only `service/app/static/v2/inventory-page.jsx` was edited (aside from this build record). No other files touched. No backend changes. No new routes. No new DB tables.
