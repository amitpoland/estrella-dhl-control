# LIVE-APP INVENTORY — Wave-3 Gap Census
**Branch:** deploy/latest  
**Date:** 2026-07-03  
**Scope:** V2 SPA — `service/app/static/v2/`  
**Status:** Read-only inspection. No files edited outside this report.

---

## SECTION 1 — ROUTING TRUTH

### WIRED_PAGES (19 entries)
Source: `mock-badge.jsx:68`

```
proforma, proforma_search, inbox, inventory, dhl, shipments, automation,
intelligence, documents, proforma_detail, wfirma_setup, master, carriers,
dashboard, api_status, diagnostics, coverage, detail, supplier_invoice_review
```

Any slug NOT in this list receives a purple MOCK banner. Pages in NAV_TREE but not in WIRED_PAGES: `accounting`, `reports`, `admin`.

### NAV_TREE
Source: `components.jsx:10-45`

| Nav slot | Slug | Badge | In WIRED_PAGES |
|---|---|---|---|
| Dashboard | `dashboard` | — | YES |
| Inbox | `inbox` | NEW | YES |
| Shipments | `shipments` | — | YES |
| DHL | `dhl` | — | YES |
| Pro Forma | `proforma` | — | YES |
| Documents | `documents` | — | YES |
| Accounting | `accounting` | NEW | NO → MOCK |
| Supplier Invoices | `supplier_invoice_review` | NEW | YES |
| Inventory | `inventory` | — | YES |
| Reports | `reports` | — | NO → MOCK |
| Setup > Settings | `admin` | — | NO → MOCK |
| Setup > Master Data | `master` | — | YES |
| Setup > Carriers | `carriers` | — | YES |
| Setup > wFirma | `wfirma_setup` | — | YES |
| Setup > API Status | `api_status` | — | YES |
| Setup > Diagnostics | `diagnostics` | — | YES |
| Setup > Automation | `automation` | — | YES |
| Setup > Intelligence Hub | `intelligence` | — | YES |
| Setup > Coverage Map | `coverage` | — | YES |

### ROUTE_REDIRECTS (13 entries)
Source: `index.html:368-382`

| Input slug | Canonical target | Reason |
|---|---|---|
| `actions` | `inbox` | alias |
| `proposals` | `inbox` | alias |
| `email_queue` | `inbox` | alias |
| `reservation` | `inbox` | alias |
| `shipping` | `shipments` | alias |
| `scanner` | `inventory` | alias |
| `identity` | `inventory` | alias |
| `sample_out` | `inventory` | Phase B — stub retired |
| `sample_return` | `inventory` | Phase B — stub retired |
| `goods_return` | `inventory` | Phase B — stub retired |
| `return_prod` | `inventory` | Phase B — stub retired |
| `move_stock` | `inventory` | Phase B FOLD (2026-07-03) |
| `move_location` | `inventory` | Phase B FOLD — page retired |

### Script Load Order (34 scripts)
Source: `index.html:297-327`

Pre-body globals: `pz-api.js`, `pz-state.js`, `estrella-doc-proforma.jsx`, `estrella-doc-cmr.jsx`, `estrella-doc-packing.jsx`

In-body order:
1. `components.jsx`
2. `dashboard-page.jsx`
3. `shipment-detail-page.jsx`
4. `modals.jsx`
5. `pages.jsx`
6. `pages-v2.jsx`
7. `client-detail.jsx`
8. `master-page.jsx`
9. `inventory-page.jsx`
10. `ledgers-page.jsx`
11. `client-kyc-and-consignment.jsx`
12. `wireframe-update.jsx`
13. `shipping-ops.jsx`
14. `ops-cell.jsx`
15. `carriers-page.jsx`
16. `api-status-page.jsx`
17. `documents-hub.jsx`
18. `accounting-hub.jsx`
19. `dashboard-kanban.jsx`
20. `inbox-page.jsx`
21. `proforma-search.jsx`
22. `link-as-sales-backfill.jsx`
23. `proforma-list.jsx`
24. `proforma-detail.jsx`
25. `supplier-invoice-review.jsx`
26. `global-search.jsx`
27. `dhl-scan-status.jsx`
28. `dhl-daily-summary.jsx`
29. `mock-badge.jsx`

---

## SECTION 2 — PER-WIRED-PAGE DETAIL (nav order)

### PAGE: dashboard
**File:** `dashboard-kanban.jsx`  
**Status:** LIVE  
**Sprint:** 40  

**Layout regions:**
- KPI tiles bar (derived live from batch data)
- 6-lane Kanban board: new → docs → customs → ready → booked → done
- Per-card: batch ID, shipment summary, status chip

**Data:** GET /api/v1/dashboard/batches (live)  
**Placeholder items:** 0 (all 15 fake PIPELINE_SHIPMENTS removed in Sprint 40)  
**Dead controls:** 0  

---

### PAGE: inbox
**File:** `inbox-page.jsx`  
**Status:** LIVE  
**Sprint:** 2B.2  

**Data:** GET /api/v1/inbox  
**Placeholder items:** 0  
**Dead controls:** 0 (based on Sprint wiring entry)  

---

### PAGE: shipments
**File:** `dashboard-page.jsx` (FilteredShipmentsTable), also `pages.jsx` for MOCK table  
**Status:** LIVE for DashboardPage; `pages.jsx` defines `FilteredShipmentsTable` using `MOCK_SHIPMENTS` (hardcoded array)  
**Sprint:** 32  

**Caution:** `pages.jsx` contains a `FilteredShipmentsTable` built on a hardcoded `MOCK_SHIPMENTS` array. This is in the script load order. Whether the live DashboardPage or the mock table renders at `shipments` depends on which component is mounted in `index.html` routing — routing mounts `<DashboardPage>` for `shipments`, so MOCK_SHIPMENTS in pages.jsx is dead code for this page but still loaded globally.

**Data:** GET /api/v1/dashboard/batches  
**Placeholder items:** MOCK_SHIPMENTS array in pages.jsx (dead for shipments render, present in global scope)  
**Dead controls:** 0  

---

### PAGE: detail
**File:** `shipment-detail-page.jsx`  
**Status:** LIVE  
**Sprint:** detail-wiring  

**Data:** GET /api/v1/dashboard/batches/{batch_id} (full-audit authority)  
**Layout:** CIF, clearance date, customs agent, LRN, SAD/NBP rates, A00/B00, PZ number, wFirma doc id, line count, invoice count, activity timeline — all from live audit  
**Write actions:** Visible + disabled (Lesson M — on their domain pages)  
**Placeholder items:** 0  
**Dead controls:** Write buttons visible but disabled intentionally (Lesson M compliant)  

---

### PAGE: dhl
**File:** `pages-v2.jsx` (DhlCustomsPage), `dhl-scan-status.jsx`, `dhl-daily-summary.jsx`  
**Status:** LIVE  
**Sprint:** 31  

**Data (read-only, 4 GET endpoints):**
- DHL projector
- scan status
- daily summary
- carrier status

**Placeholder items:** 0  
**Dead controls:** 0  

---

### PAGE: proforma
**File:** `proforma-list.jsx`  
**Status:** LIVE  
**Sprint:** Sprint 36 series  

**Data:** Live proforma list endpoints  
**Placeholder items:** 0  
**Dead controls:** 0  

---

### PAGE: proforma_search
**File:** `proforma-search.jsx`  
**Status:** LIVE  
**Sprint:** M6-cleanup  

**Data:** GET /api/v1/proforma/search via PzApi.searchProformaDrafts  
**Placeholder items:** 0  
**Dead controls:** 0  

---

### PAGE: proforma_detail
**File:** `proforma-detail.jsx`  
**Status:** LIVE  
**Sprint:** 36 Phase 2  

**Layout regions:**
- 8-button toolbar: Edit / Delete / Duplicate / PostToWFirma / Convert / Print / Send / Generate
- SELLER / BUYER / RECIPIENT party cards
- ReservationTab wired to blocking_reasons
- OverviewTab KV grid (16 fields)
- PostToWFirmaModal

**Data:**
- Exporter from GET /api/v1/settings/company-profile
- Lines from editable_lines
- FX from exchange_rate
- PDF download wired

**Placeholder items:** 0  
**Dead controls:** 0 (all 8 toolbar buttons wired per Sprint 36)  

---

### PAGE: documents
**File:** `documents-hub.jsx`  
**Status:** LIVE  
**Sprint:** 35  

**Data:** GET /api/v1/dashboard/batches  
**Placeholder items:** 0  
**Dead controls:** 0  

---

### PAGE: supplier_invoice_review
**File:** `supplier-invoice-review.jsx`  
**Status:** LIVE  
**Sprint:** supplier-invoice-ocr (2026-07-02)  

**Data:**
- POST /api/v1/supplier-invoice-ocr (upload)
- GET drafts endpoint
- POST confirm
- POST reject

**Placeholder items:** 0  
**Dead controls:** 0  

---

### PAGE: inventory
**File:** `inventory-page.jsx` (1059 lines)  
**Status:** LIVE with PHASE-C pending items  
**Sprint:** 30 (hub) + Phase B FOLD (2026-07-03)  

**Layout regions and panels:**

#### DocumentViewerPage (lines 25-171) — Shell-global viewer
**PLACEHOLDER CONTENT — NOT INVENTORY-SPECIFIC:**
- Hardcoded fallback metadata: doc type `'Packing List'`, id `'PL-EJL-26-27-013'`, AWB `'DHL-1234567890'`, shipment `'SHP-2026-0142'` (lines ~30-50)
- Hardcoded packing table: 3 fixture rows (lines ~80-120)
  - Columns: Pk Sr, Ctg, Client PO, Design No, Karat, Color, Quality, Dia Wt, Col Wt, Qty, Size, Value, Total
- "Linked entities" section: 4 hardcoded `<a href="#">` links
- "Other documents" section: 4 hardcoded names
- **Placeholder count: 3 hardcoded data blocks (meta + table + links)**

This component is exported as `window.DocumentViewerPage` and is shell-global, not inventory-specific. The placeholder data is fallback content shown when `doc` prop has no real data.

#### Stage2Panel (lines 297-338) — Auto-loads on mount
**Status:** LIVE (3 of 4 tiles), PHASE C (1 tile)  
**API:** GET /api/v1/inventory/stage2/aggregate  
**KPI tiles:**
1. In Transit — live
2. At Warehouse — live
3. Dispatched — live
4. **Consignment** — shows `"BACKEND-PENDING · PHASE C"` badge (uses `pending` prop) — dead tile

**Dead controls:** "Consignment" tile is a static badge, no action

#### BatchPanel (lines 342-416) — User-triggered (batch_id input)
**Status:** LIVE  
**API:** GET /api/v1/inventory/state/{batch_id}  
**Table columns:** Scan code, State, Design, Updated  
**Dead controls:** 0  

#### PiecePanel (lines 420-548) — Two modes
**Status:** LIVE  
- Piece mode: GET /api/v1/inventory/pieces/{piece_id}
- Scan mode: GET /api/v1/warehouse/inventory/{scan}

**Dead controls:** 0  

#### LocationPanel (lines 552-638) — Auto-loads locations
**Status:** LIVE  
**APIs:**
- GET /api/v1/warehouse/locations (auto-load)
- GET /api/v1/warehouse/locations/{code}/inventory (click)

**Table columns:** Scan code, Status, Design, Bag  
**Dead controls:** 0  

#### AuditPanel (lines 642-707) — User-triggered
**Status:** LIVE  
**APIs:**
- GET /api/v1/warehouse/audit-summary/{batch_id}
- GET /api/v1/warehouse/audit/{batch_id}

**Dead controls:** 0  

#### PromotionNotesPanel (lines 717-811) — Batch-scoped
**Status:** LIVE  
**APIs:** PzApi.getPromotionNotes(batchId) → GET /api/v1/inventory/promotion-notes/{batch_id}; PzApi.getPromotionNote(noteNo)  
**Table columns:** Note no, Trigger, Pieces, Operator, Created  
**Dead controls:** 0  

#### MoveStockModal (lines 842-1015) — Phase B FOLD from move_location
**Status:** PARTIAL — two tabs, one live, one dead  

Tab 1 — "Warehouse → Warehouse" (LIVE):
- PzApi.getWarehouseLocations() → GET /api/v1/warehouse/locations
- PzApi.getLocationInventory(locationCode) → GET /api/v1/warehouse/locations/{code}/inventory
- PzApi.movePieceLocation(pieceId, body) → POST /api/v1/inventory/pieces/{piece_id}/location

Table columns: checkbox, Piece (scan_code), Design, Product code, Status  

Tab 2 — "Stage transition" (DEAD — BACKEND-PENDING · PHASE C):
- Entire tab disabled, line ~989 banner: `"Backend-pending — Phase C. Moving freshly-received stock not yet placed at a location..."`
- No API call wired

**Dead controls in MoveStockModal:** 1 (stage transition tab — fully disabled, no handler)  

#### InventoryPage shell (lines 1020-1053)
- One button: `"⇄ Move Stock"` → opens MoveStockModal

**Inventory page summary:**
- Placeholder items: 4 (DocumentViewerPage fallback meta + table + links + Other docs section; Consignment tile PHASE-C badge)
- Dead controls: 2 (Consignment tile is a static badge; MoveStockModal stage-transition tab is disabled)

---

### PAGE: automation
**File:** Not inspected in detail (AiBridgePage)  
**Status:** LIVE  
**Sprint:** 33  
**Data:** ai-bridge authority endpoints  
**Placeholder items:** 0 (per sprint changelog)  
**Dead controls:** 0  

---

### PAGE: intelligence
**File:** Not inspected in detail (IntelligencePage)  
**Status:** LIVE  
**Sprint:** 34  
**Data:** intelligence + invoice-learning authority  
**Placeholder items:** 0  
**Dead controls:** 0  

---

### PAGE: carriers
**File:** `carriers-page.jsx`  
**Status:** LIVE  
**Sprint:** 39  
**Data:**
- GET /api/v1/carriers-config/
- GET /api/v1/carrier/status
- GET /api/v1/master/audit/?entity=carriers_config (Audit tab)

**Placeholder items:** 0 (all hardcoded CARRIERS/WEBHOOKS/SESSIONS/AUDIT/AVAILABLE_NEW removed)  
**Dead controls:** 0  

---

### PAGE: master
**File:** `master-page.jsx`  
**Status:** LIVE  
**Sprint:** 38  
**Data:** Live GET endpoints for 12 entity tabs (10 full CRUD, Users read-only, Roles static)  
**Placeholder items:** 0 (all SEED data removed)  
**Dead controls:** 0 (writes disabled with explicit reasons per Sprint 38)  

---

### PAGE: wfirma_setup
**File:** Not inspected in detail (WfirmaMappingPage)  
**Status:** LIVE  
**Sprint:** 37  
**Data:**
- GET /wfirma/capabilities
- GET /wfirma/customers
- GET /wfirma/products

**Placeholder items:** 0  
**Dead controls:** 0  

---

### PAGE: api_status
**File:** `api-status-page.jsx`  
**Status:** LIVE  
**Sprint:** 41  
**Data:** 12 live subsystem health endpoints  
**Placeholder items:** 0 (all 4 fake arrays removed)  
**Dead controls:** 0  

---

### PAGE: diagnostics
**File:** Not inspected in detail (DiagnosticsPage)  
**Status:** LIVE  
**Sprint:** 42  
**Data:**
- GET /health-full
- GET /storage/health
- GET /storage/locks
- GET /system/version
- GET /debug/pending

**Placeholder items:** 0  
**Dead controls:** CLI tools visible but disabled (intentional — Lesson M)  

---

### PAGE: coverage
**File:** `wireframe-update.jsx` (CoverageMapPage, lines 178-332)  
**Status:** LIVE  
**Sprint:** 43  
**Data:** GET /openapi.json via PzApi.getOpenApiSpec  
**Placeholder items:** 0 (all 46 hardcoded COVERAGE_ROWS removed)  
**Dead controls:** 0  

---

## SECTION 3 — PERSISTENT SHELL PLACEHOLDER (All Pages)

### OperationalStatusStrip
**File:** `wireframe-update.jsx:68-98`  
**Rendered:** On every V2 page via shell  
**Status:** FULLY HARDCODED — not wired to any backend  

6 hardcoded static items:
1. wFirma
2. DHL Inbox
3. Email Queue
4. Cliq Webhook
5. Cowork Bridge
6. WorkDrive

No API call. The strip always shows the same static data regardless of actual system state. This is a persistent placeholder on all 19 WIRED pages.

---

## SECTION 4 — BACKEND READ SURFACE (Wave-2 Endpoints)

### Endpoints that EXIST on backend but have ZERO frontend consumption:

| Endpoint | Backend file | Line | pz-api.js method | Any JSX call |
|---|---|---|---|---|
| GET /api/v1/inventory/samples | `routes_inventory_sample.py` | 149 | NONE | NONE |
| GET /api/v1/inventory/returns | `routes_inventory_returns.py` | 212 | NONE | NONE |
| GET /api/v1/inventory/merchandising/{batch_id} | `routes_inventory.py` | 127 | NONE | NONE |
| GET /api/v1/inventory/movements/{batch_id} | `routes_inventory.py` | 203 | NONE | NONE |
| GET /api/v1/proforma/service-products | `routes_proforma.py` | 4546 | `getServiceProducts` (pz-api.js:134) | NONE |

All five endpoints are fully implemented on the backend and exposed by the router, but no V2 JSX page calls any of them.

`getServiceProducts` is defined in `pz-api.js:134` as `_get('/api/v1/proforma/service-products')` but grep across all V2 JSX files finds zero calls to it.

### Inventory page endpoint coverage vs Wave-2 gaps:

The Inventory page (`inventory-page.jsx`) consumes 8 endpoints live:
1. GET /api/v1/inventory/stage2/aggregate
2. GET /api/v1/inventory/state/{batch_id}
3. GET /api/v1/inventory/pieces/{piece_id}
4. GET /api/v1/warehouse/inventory/{scan}
5. GET /api/v1/warehouse/locations
6. GET /api/v1/warehouse/locations/{code}/inventory
7. GET /api/v1/warehouse/audit-summary/{batch_id}
8. GET /api/v1/warehouse/audit/{batch_id}

Plus via PromotionNotesPanel: GET /api/v1/inventory/promotion-notes/{batch_id}, GET /api/v1/inventory/promotion-note/{note_no}  
Plus via MoveStockModal (W→W tab): POST /api/v1/inventory/pieces/{piece_id}/location

**NOT consumed by inventory page (Wave-2 gap):**
- /api/v1/inventory/samples
- /api/v1/inventory/returns
- /api/v1/inventory/merchandising/{batch_id}
- /api/v1/inventory/movements/{batch_id}

---

## SECTION 5 — KNOWN STUBS

### SampleOutPage
**File:** `wireframe-update.jsx:492-507`  
**Status:** `status=partial` — STUB  
**Content:** 3 hardcoded fixture rows  
**Endpoints listed in stub:** POST /api/v1/inventory/samples/out and others — FICTIONAL (not in backend)  
**Routing:** RETIRED — slug `sample_out` redirects to `inventory` (index.html:376)  
**Mounted in index.html:** NO  
**Exported:** YES — `window.SampleOutPage` via wireframe-update.jsx:564-572  
**Operator reachable:** NO  

### SampleReturnPage
**File:** `wireframe-update.jsx:510-525`  
**Status:** `status=backend` — STUB  
**Content:** 3 hardcoded rows  
**Endpoints:** FICTIONAL  
**Routing:** RETIRED — slug `sample_return` redirects to `inventory`  
**Mounted in index.html:** NO  
**Operator reachable:** NO  

### GoodsReturnPage
**File:** `wireframe-update.jsx:528-543`  
**Status:** `status=backend` — STUB  
**Content:** 3 hardcoded rows  
**Endpoints:** FICTIONAL  
**Routing:** RETIRED — slug `goods_return` redirects to `inventory`  
**Mounted in index.html:** NO  
**Operator reachable:** NO  

### ReturnToProducerPage
**File:** `wireframe-update.jsx:546-561`  
**Status:** `status=future` — STUB  
**Content:** 3 hardcoded rows  
**Endpoints:** FICTIONAL  
**Routing:** RETIRED — slug `return_prod` redirects to `inventory`  
**Mounted in index.html:** NO  
**Operator reachable:** NO  

**Note at wireframe-update.jsx:484-490:** MoveStockPage formerly in this file was RETIRED because it caused a global name collision with the live inventory-page.jsx MoveStockModal. The comment documents the collision explicitly.

### ConsignmentTab
**File:** `client-kyc-and-consignment.jsx:282`  
**Status:** FULLY MOCK — all data hardcoded  
**Content:**
- `issued` array: 4 hardcoded rows (CON-2604-001 through CON-2603-007)
- `proformaIssued` array: 4 hardcoded rows
- KPI tiles: hardcoded values (14, 2, 3, "EUR 8,420" and similar)
- Sub-tabs: Issue, Proforma Issue, Balance/Valuation — all hardcoded

**Buttons with no handler:**
- "Issue Consignment" (no handler)
- "Convert to sale" (no handler)
- "Recall" (no handler)
- "↓ Export valuation" (no handler)

**Table columns (Issue tab):** Cons. ID, Client, Design, Qty, Value (EUR), Issued, Due back, Days out, Proforma, Status, actions  
**Exported:** YES — `client-kyc-and-consignment.jsx:439`: `Object.assign(window, { ClientKycModal, ConsignmentTab, DocActions })`  
**Mounted in index.html routing:** NO — the tab is globally available but no route renders it  
**Operator reachable:** NO  

### ActionCenterPage
**File:** `wireframe-update.jsx:338-419`  
**Status:** NOT IN WIRED_PAGES — receives MOCK banner  
**Content:** 6 hardcoded queue rows (A-2482 through A-2487)  
**Buttons:** "Bulk approve" → PendingBtn (no real endpoint)  
**Routing:** No slug defined, not accessible  

### IdentityMappingPage
**File:** `wireframe-update.jsx:465-481`  
**Status:** `status=backend`, 3 hardcoded rows  
**Endpoints:** FICTIONAL  
**Routing:** slug `identity` redirects to `inventory` (index.html:374)  
**Operator reachable:** NO  

### DhlClearancePage / CustomsDocumentsPage
**File:** `pages.jsx`  
**Status:** Uses MOCK_SHIPMENTS (hardcoded array)  
**Routing:** NOT IN WIRED_PAGES  
**Operator reachable:** NO  

### TopBar dead controls
**File:** `components.jsx`  
- Notification bell (lines 346-349): rendered but no `onClick` handler
- User avatar dropdown (lines 351-363): rendered but no `onClick` handler

These are shell-level dead controls present on every wired page.

---

## END SUMMARY TABLE

| Page | Canonical File | LIVE / MOCK | Placeholder Items | Dead Controls | Unconsumed Wave-2 Endpoints Relevant To It |
|---|---|---|---|---|---|
| dashboard | `dashboard-kanban.jsx` | LIVE | 0 | 0 | none |
| inbox | `inbox-page.jsx` | LIVE | 0 | 0 | none |
| shipments | `dashboard-page.jsx` | LIVE | MOCK_SHIPMENTS in pages.jsx (dead code, not rendered) | 0 | none |
| detail | `shipment-detail-page.jsx` | LIVE | 0 | 0 (write buttons disabled/Lesson M) | none |
| dhl | `pages-v2.jsx` + dhl-*.jsx | LIVE | 0 | 0 | none |
| proforma | `proforma-list.jsx` | LIVE | 0 | 0 | /proforma/service-products (defined in pz-api.js, never called) |
| proforma_search | `proforma-search.jsx` | LIVE | 0 | 0 | none |
| proforma_detail | `proforma-detail.jsx` | LIVE | 0 | 0 | none |
| documents | `documents-hub.jsx` | LIVE | 0 | 0 | none |
| supplier_invoice_review | `supplier-invoice-review.jsx` | LIVE | 0 | 0 | none |
| inventory | `inventory-page.jsx` | LIVE (partial) | 4 (DocViewer fallback + Consignment PHASE-C tile) | 2 (Consignment tile badge; MoveStockModal stage-transition tab) | /inventory/samples · /inventory/returns · /inventory/merchandising/{id} · /inventory/movements/{id} |
| automation | `(AiBridgePage)` | LIVE | 0 | 0 | none |
| intelligence | `(IntelligencePage)` | LIVE | 0 | 0 | none |
| carriers | `carriers-page.jsx` | LIVE | 0 | 0 | none |
| master | `master-page.jsx` | LIVE | 0 | 0 | none |
| wfirma_setup | `(WfirmaMappingPage)` | LIVE | 0 | 0 | none |
| api_status | `api-status-page.jsx` | LIVE | 0 | 0 | none |
| diagnostics | `(DiagnosticsPage)` | LIVE | 0 | CLI tools disabled/intentional | none |
| coverage | `wireframe-update.jsx:178-332` | LIVE | 0 | 0 | none |
| accounting | `accounting-hub.jsx` | MOCK (not in WIRED_PAGES) | all | all | none |
| reports | `(ReportsPage)` | MOCK (not in WIRED_PAGES) | all | all | none |
| admin | unknown | MOCK (not in WIRED_PAGES) | all | all | none |

**Stubs exported to window but unreachable via any route:**
- `SampleOutPage` — wireframe-update.jsx:492-507
- `SampleReturnPage` — wireframe-update.jsx:510-525
- `GoodsReturnPage` — wireframe-update.jsx:528-543
- `ReturnToProducerPage` — wireframe-update.jsx:546-561
- `ConsignmentTab` — client-kyc-and-consignment.jsx:282

**Persistent shell-level issues (affects all 19 wired pages):**
- `OperationalStatusStrip` (wireframe-update.jsx:68-98): static hardcoded data, never calls backend
- TopBar notification bell: no handler (components.jsx:346-349)
- TopBar user avatar dropdown: no handler (components.jsx:351-363)

**Wave-2 backend endpoints with zero frontend consumption (all five):**
1. GET /api/v1/inventory/samples (`routes_inventory_sample.py:149`)
2. GET /api/v1/inventory/returns (`routes_inventory_returns.py:212`)
3. GET /api/v1/inventory/merchandising/{batch_id} (`routes_inventory.py:127`)
4. GET /api/v1/inventory/movements/{batch_id} (`routes_inventory.py:203`)
5. GET /api/v1/proforma/service-products (`routes_proforma.py:4546`) — pz-api.js method exists at line 134, no JSX caller
