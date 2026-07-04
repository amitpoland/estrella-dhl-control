# Wave-3 Retroactive Control Matrices
**Date:** 2026-07-04  
**Branch:** deploy/latest  
**Method:** wireframe §7 (inventory-page sections) from `2026-07-03-wireframe-inventory.md`; build records from `reports/wave3/pages/`; live code cross-checked in `service/app/static/v2/inventory-page.jsx`

**Classification key:**
- **IMPLEMENTED** — control present in live JSX with a wired handler or live data source
- **BACKEND GATED** — Lesson-M honest-disabled: present in live code, disabled with title explaining the backend gap; census tag assigned
- **OPERATOR RULED** — added per Entry-Point Rule operator mandate; not in pinned wireframe as a discrete control but mandated as workflow entry point
- **OUT OF SCOPE** — census OUT tag; wireframe silent; untouched
- **MISSING** — wireframe-required control, absent from live code, no tag

---

## Page 1 — Sample Out Tab (SampleOutTab)

**Wireframe §7 Tab 7** | **Build record:** `2026-07-03-page1-sample-out.md`  
**Census gaps:** IV-SO-1, IV-SO-2, IV-SO-3, IV-SO-4

| # | Control | Classification | Evidence |
|---|---------|---------------|---------|
| 1 | 4 KPI tiles (Active out / Closing soon / Overdue / Returned) | IMPLEMENTED | `so-kpi-{active,closing,overdue,returned}` — live from API |
| 2 | 10-column table (Sample ID · Source SU · Design · Qty · Issued to · Purpose · Issued · Return by · Days left · Status) | IMPLEMENTED | Exact 10 columns per wireframe §7 Tab 7 |
| 3 | Status filter select | IMPLEMENTED | `data-testid="so-filter-status"` |
| 4 | Recipient filter input | IMPLEMENTED | `data-testid="so-filter-recipient"` |
| 5 | + Issue Sample toolbar button | IMPLEMENTED | `btn-issue-sample` → `IssueSampleModal` → POST `/api/v1/inventory/pieces/{id}/sample-out` |
| 6 | Record Return row action (if out/overdue) | BACKEND GATED | `so-btn-record-return` — Lesson M: sample return tab not yet built (p1) then made live in page 2 |
| 7 | View row action | BACKEND GATED | `so-btn-view` — Lesson M: no detail endpoint; future slice |
| 8 | ↻ Refresh button | IMPLEMENTED | `so-refresh` → `load()` → GET `/api/v1/inventory/samples` |

**Matrix line:**
`Wireframe controls: 8 · Implemented: 6 · Backend gated: 2 · Operator ruled: 0 · Out of scope: 0 · Missing: 0`

---

## Page 2 — Sample Return Tab (SampleReturnTab)

**Wireframe §7 Tab 8** | **Build record:** `2026-07-03-page2-sample-return.md`  
**Census gaps:** IV-SR-1, IV-SR-2, IV-SR-3 (IV-SR-2 expands to 3 items below), IV-SR-4

| # | Control | Classification | Evidence |
|---|---------|---------------|---------|
| 1 | 4 KPI tiles (Awaiting inspection / In repair / Restocked mo. / Written off mo.) | BACKEND GATED | 3 tiles Lesson M honest-pending (QC sub-buckets no backend); 1 tile (total returned) live from API |
| 2 | 10-column table (Return ID · Sample · Design · Qty · Returned from · Received · Condition · Inspector · Decision · Status) | IMPLEMENTED | Exact 10 columns per wireframe; Condition/Inspector/Decision columns render `—` (backend-pending honest) |
| 3 | Recipient filter input | IMPLEMENTED | `data-testid="sr-filter-recipient"` |
| 4 | Inspect row action | BACKEND GATED | `sr-btn-inspect` — Lesson M: QC write endpoints absent |
| 5 | View row action | BACKEND GATED | `sr-btn-view` — Lesson M: no detail endpoint |
| 6 | ↻ Refresh button | IMPLEMENTED | `sr-refresh` → `load()` → GET `/api/v1/inventory/samples?status=returned` |
| 7 | Record Return (cross-tab action from Sample Out) | IMPLEMENTED | `sr-submit-return` → `RecordReturnModal` → POST `/api/v1/inventory/pieces/{id}/sample-return` |

**Matrix line:**
`Wireframe controls: 7 · Implemented: 4 · Backend gated: 3 · Operator ruled: 0 · Out of scope: 0 · Missing: 0`

---

## Page 3 — Client Return Tab (ClientReturnTab)

**Wireframe §7 Tab 9** | **Build record:** `2026-07-03-page3-client-return.md`  
**Census gaps:** IV-CR-1, IV-CR-2

| # | Control | Classification | Evidence |
|---|---------|---------------|---------|
| 1 | 4 KPI tiles (Awaiting inspection / Inspected / Restocked / Routed to RTP) | BACKEND GATED | 3 tiles Lesson M honest-pending (QC sub-buckets); 1 tile (recorded total) live |
| 2 | 10-column RMA table (RMA ID · Invoice · Client · Design · Qty · Value · Reason · Received · Condition · Decision · Status) | IMPLEMENTED | 10 data columns; Value/Condition/Decision show `—` with backend-pending title |
| 3 | Client filter input | IMPLEMENTED | `data-testid="cr-filter-client"` |
| 4 | + Record Client Return toolbar button | IMPLEMENTED | `cr-btn-record-return` → `RecordClientReturnModal` → POST `/api/v1/inventory/pieces/{id}/return-from-client` |
| 5 | Inspect row action | BACKEND GATED | `cr-btn-inspect` — Lesson M: QC outcome writes no backend route |
| 6 | Credit Note row action | BACKEND GATED | `cr-btn-credit-note` — Lesson M: wFirma write no backend route |
| 7 | ↻ Refresh button | IMPLEMENTED | `cr-refresh` → GET `/api/v1/inventory/returns?direction=from_client` |

**Matrix line:**
`Wireframe controls: 7 · Implemented: 4 · Backend gated: 3 · Operator ruled: 0 · Out of scope: 0 · Missing: 0`

---

## Page 4 — Return to Producer Tab (ProducerReturnTab)

**Wireframe §7 Tab 10** | **Build record:** `2026-07-03-page4-return-producer.md`  
**Census gaps:** IV-RTP-1, IV-RTP-2

| # | Control | Classification | Evidence |
|---|---------|---------------|---------|
| 1 | 4 KPI tiles (In preparation / Awaiting AWB / In transit / Confirmed mo.) | IMPLEMENTED | `rtp-kpi-{preparation,awaiting,open,confirmed}` — derived live from API data |
| 2 | 10-column table (RTP ID · Source · Design · Qty · Supplier · Reason · Prepared · AWB out · Status) | IMPLEMENTED | Exact 10 columns per wireframe §7 Tab 10 |
| 3 | Supplier filter input | IMPLEMENTED | `rtp-filter-supplier` |
| 4 | + Return to Producer toolbar button | IMPLEMENTED | `rtp-btn-record` → `ReturnToProducerModal` → POST `/api/v1/inventory/pieces/{id}/return-to-producer` |
| 5 | Add AWB row action (awaiting AWB rows) | BACKEND GATED | `rtp-btn-add-awb` — Lesson M: no PATCH route for dispatch_reference update on existing rows |
| 6 | Confirm Received row action (open rows) | IMPLEMENTED | `rtp-btn-confirm-received` → `ConfirmReceivedModal` → POST `/api/v1/inventory/pieces/{id}/return-from-producer` |
| 7 | View docs row action | BACKEND GATED | implicit in page 4 — not explicitly mentioned in build record as a separate wired control; wireframe shows "View docs" as a row action; not found as a wired testid in the page 4 record |
| 8 | ↻ Refresh button | IMPLEMENTED | `rtp-refresh` → GET `/api/v1/inventory/returns?direction=to_producer` |

**Note on control 7:** The wireframe §7 Tab 10 defines row actions "Add AWB (if awaiting) · View docs". The page 4 build record documents `rtp-btn-add-awb` (honest-disabled) and `rtp-btn-confirm-received` (live). "View docs" does not appear as a wired or disabled testid in the page 4 build record. This is classified as **MISSING**.

**Matrix line:**
`Wireframe controls: 8 · Implemented: 5 · Backend gated: 2 · Operator ruled: 0 · Out of scope: 0 · Missing: 1`

**Missing controls: "View docs" row action (§7 Tab 10, not wired or disabled in page 4 build record)**

---

## Page 5 — Temp Sale Tab (TempSaleTab)

**Wireframe §7 Tab 4** | **Build record:** `2026-07-03-page5-temp-sale.md`  
**Census gaps:** IV-TS-1

| # | Control | Classification | Evidence |
|---|---------|---------------|---------|
| 1 | 4 KPI tiles (Open reservations / Awaiting goods / Reserved / Sales-invoice gate LOCKED) | IMPLEMENTED | `ts-kpi-{open,awaiting,reserved,gate}` — LOCKED gate tile is always amber; live counts derived from API |
| 2 | Gate banner (verbatim wireframe text) | IMPLEMENTED | `ts-gate-banner` — wireframe verbatim text rendered |
| 3 | 8-column table (Proforma · Client · Design No · Qty · Value · Linked to · Status) | IMPLEMENTED | 8 columns; Proforma and Value show honest `—` (Lesson M, no linkage in inventory_state) |
| 4 | Batch selector toolbar (batch ID input + Load batch) | IMPLEMENTED | `ts-batch-input` + `ts-btn-load` |
| 5 | View proforma row action | BACKEND GATED | `ts-btn-view-proforma` — Lesson M: no proforma_id field in inventory_state; census IV-TS-1 |
| 6 | Issue invoice row action | BACKEND GATED | `ts-btn-issue-invoice` — Lesson M: no delivery_confirmed POST route; census IV-TS-1 |
| 7 | ↻ Refresh button | IMPLEMENTED | `ts-refresh` |

**Matrix line:**
`Wireframe controls: 7 · Implemented: 5 · Backend gated: 2 · Operator ruled: 0 · Out of scope: 0 · Missing: 0`

---

## Page 6 — Inventory Overview Tab (InventoryOverviewTab)

**Wireframe §7 Tab 1** | **Build record:** `2026-07-03-page6-overview.md`  
**Census gaps:** IV-O-1, IV-O-2, IV-O-3, IV-O-4

| # | Control | Classification | Evidence |
|---|---------|---------------|---------|
| 1 | KPI tile: Stock units (final) | IMPLEMENTED | `ov-tile-final-stock` — live from aggregate |
| 2 | KPI tile: Pieces on hand | IMPLEMENTED | `ov-tile-pieces` — renders `—` honestly (aggregate has no piece-count bucket; Wave 4) |
| 3 | KPI tile: Reserved (3rd wireframe tile) | IMPLEMENTED | `ov-tile-returns` — mapped to Returns tile (closest live aggregate proxy; see note below) |
| 4 | KPI tile: Available (4th wireframe tile) | BACKEND GATED | `ov-tile-consignment` — WFIRMA-GATED (IV-O-4); Consignment renders BACKEND-PENDING badge |
| 5 | KPI tile: Total value (5th wireframe tile — wireframe §7 Tab 1 shows 5 tiles) | MISSING | Wireframe §7 Tab 1 defines: Stock units · Pieces on hand · Reserved · Available · Total value. The live Overview only has 4 KPI tiles (final_stock / pieces / returns / consignment). "Reserved" and "Available" tiles are not individually implemented as wireframe-labelled tiles. "Total value" tile is absent entirely. |
| 6 | Stage 1 summary card (Open packing lists · Awaiting goods · Partially arrived · Closed-out) | IMPLEMENTED | Stage 1 card with 3 StageRow navigation entries (tempPurchase / tempWarehouse / tempSale) |
| 7 | Stage 2 summary card (Final stock units · Reserved · Samples out · Consignment out) | IMPLEMENTED | Stage 2 card with 5 StageRow entries |
| 8 | Quick action: Upload Packing List | IMPLEMENTED | `overview-qa-upload` → `navigateToDocuments()` (WIREFRAME-REQUIRED, repaired in page 6b) |
| 9 | Quick action: New Consignment | OPERATOR RULED | Not in Overview quick-action grid (4th card absent); only 3 quick-action cards present (Upload / Move Stock / Identity); wireframe bundle `7289f2fd` grid has Upload + Move but not New Consignment as a separate card; census IV-O-3 partial OPERATOR-RULED |
| 10 | Quick action: Issue Sample | OPERATOR RULED | Same as above — not in 3-card quick-action grid; census IV-O-3 partial OPERATOR-RULED |
| 11 | Quick action: Move Stock (→ MoveStockModal) | IMPLEMENTED | `overview-qa-move` → `MoveStockModal` via `inv:move` + `onShowMove()` |
| 12 | ↻ Refresh button | IMPLEMENTED | `ov-btn-refresh` |

**Note on tiles:** The wireframe §7 Tab 1 specifies 5 KPI tiles (Stock units · Pieces on hand · Reserved · Available · Total value). The build record (page 6) implemented 4 tiles (final_stock / pieces / returns / consignment). The 5th wireframe tile "Total value" is absent, and the "Reserved" / "Available" wireframe labels do not map to any live tile. However per page 6 build record the implementation was ruled sufficient at 9/9 gate. For the purpose of strict control counting: "Total value" (the 5th wireframe KPI tile) is MISSING.

**Matrix line:**
`Wireframe controls: 12 · Implemented: 7 · Backend gated: 1 · Operator ruled: 2 · Out of scope: 0 · Missing: 2`

**Missing controls:** (1) KPI tile "Total value" (5th wireframe §7 Tab 1 tile — no live tile or honest placeholder; the aggregate does not expose a value field); (2) Quick action "New Consignment" and "Issue Sample" are OPERATOR-RULED (classified above) so they are not MISSING from a wireframe-required standpoint.

**Correction after operator-ruled re-classification:** Counting only wireframe-required items:
`Wireframe controls: 10 · Implemented: 7 · Backend gated: 1 · Operator ruled: 0 · Out of scope: 0 · Missing: 2`

(The 2 Operator-Ruled items are excluded from the wireframe-required count per their source tag.)

---

## Page 6b — Inventory PageHeader Actions Row

**Wireframe §7 PageHeader** | **Build record:** `2026-07-04-page6b-header-actions.md`  
**Census gaps:** IV-HDR-1, IV-HDR-2, IV-HDR-3

| # | Control | Classification | Evidence |
|---|---------|---------------|---------|
| 1 | ↑ Upload Document (header button) | IMPLEMENTED | `inv-hdr-upload` — `navigateToDocuments()` → `/v2/documents` (IV-HDR-2 closed) |
| 2 | Cycle count (header button) | BACKEND GATED | `inv-hdr-cycle-count` — Lesson M honest-disabled; census IV-HDR-1; no backend owner |
| 3 | ↓ Export (header button) | IMPLEMENTED | `inv-hdr-export` — context-sensitive: disabled on non-data tabs; enabled with rows loaded (IV-HDR-3 closed) |

**Matrix line:**
`Wireframe controls: 3 · Implemented: 2 · Backend gated: 1 · Operator ruled: 0 · Out of scope: 0 · Missing: 0`

---

## Page 7 — Temp Purchase Tab (TempPurchaseTab)

**Wireframe §7 Tab 2** | **Build record:** `2026-07-03-page7-temp-purchase.md`  
**Census gaps:** IV-TP-1, IV-TP-2

| # | Control | Classification | Evidence |
|---|---------|---------------|---------|
| 1 | 4 KPI tiles (Open packing lists / Awaiting goods / Partially arrived / Closed-out) | IMPLEMENTED | `tp-kpi-{open,awaiting,partial,closed}` — derived from merchandising view |
| 2 | Stage info banner (verbatim wireframe text) | IMPLEMENTED | `tp-info-banner` — wireframe Stage 1 banner text |
| 3 | 13-column table (PK SR · CTG · CLIENT PO · DESIGN NO · KARAT · COLOR · QUALITY · DIA WT · COL WT · QTY · SIZE · STATE · ACTIONS) | IMPLEMENTED | 13 columns confirmed by browser verification (columnCount: 13) |
| 4 | View doc row action | IMPLEMENTED | Opens `DocumentViewerPage` (shell-global) |
| 5 | Receive row action | IMPLEMENTED | Dispatches `inv:move` + opens `MoveStockModal` |
| 6 | + Upload Packing List toolbar button | BACKEND GATED | `tp-btn-upload` — Lesson M honest-disabled; no `POST /api/v1/packing-lists/upload`; census IV-TP-2 |
| 7 | Batch selector + Load batch | IMPLEMENTED | `tp-batch-input` + `tp-btn-load` |
| 8 | ↻ Refresh button | IMPLEMENTED | `tp-refresh` |

**Matrix line:**
`Wireframe controls: 8 · Implemented: 7 · Backend gated: 1 · Operator ruled: 0 · Out of scope: 0 · Missing: 0`

---

## Page 8 — Temp Warehouse Tab (TempWarehouseTab)

**Wireframe §7 Tab 3** | **Build record:** `2026-07-04-page8-temp-warehouse.md`  
**Census gaps:** IV-TW-1

| # | Control | Classification | Evidence |
|---|---------|---------------|---------|
| 1 | 4 KPI tiles (Awaiting count / Counted / Discrepancies / Ready for matching) | IMPLEMENTED | `tw-kpi-{awaiting,counted,discrepancy,ready}` — derived from WAREHOUSE_STOCK filter |
| 2 | Stage info banner (verbatim wireframe text) | IMPLEMENTED | `tw-info-banner` — Stage 1 physical arrival banner confirmed in browser |
| 3 | 8-column table (Pk Sr · Design No · Expected · Received · Δ · Bag ID · AWB · Recv Date · Status) | IMPLEMENTED | 10 columns including Status + Actions; 8 data columns match wireframe; AWB/Recv Date show honest `—` |
| 4 | View doc row action | IMPLEMENTED | Opens `DocumentViewerPage` (shell-global) |
| 5 | Scan barcode row action | IMPLEMENTED | `tw-btn-scan` — dispatches `inv:move` + opens `MoveStockModal` |
| 6 | Begin matching toolbar button | BACKEND GATED | `tw-btn-begin-matching` — Lesson M honest-disabled; no bag-assignment endpoint; census IV-TW-1 |
| 7 | Batch selector + Load batch | IMPLEMENTED | `tw-batch-input` + `tw-btn-load` |
| 8 | ↻ Refresh button | IMPLEMENTED | `tw-refresh` |

**Matrix line:**
`Wireframe controls: 8 · Implemented: 7 · Backend gated: 1 · Operator ruled: 0 · Out of scope: 0 · Missing: 0`

---

## Page 10 — Consignment Tab (ConsignmentTab — WFIRMA-GATED)

**Wireframe §7 Tab 5** | **Build record:** `2026-07-04-page10-consignment-gated.md`  
**Census gaps:** IV-CN-1, IV-CN-2, IV-CN-3  
**Gate:** OI-1 (MM via API), OI-2 (consignment warehouse), OI-17 (allocation model) — all OPEN

| # | Control | Classification | Evidence |
|---|---------|---------------|---------|
| 1 | 3 sub-tabs (Issue / Proforma Issue / Balance/Valuation) | BACKEND GATED | `cn-sub-{issue,proforma,balance}` — structure present, all gated; OI banner cites 3 OPEN OIs |
| 2 | Issue sub-tab: 4 KPI tiles | BACKEND GATED | All tiles show `—` / PENDING; OI-gated |
| 3 | Issue sub-tab: 9-column table (Cons. ID · Client · Design · Qty · Value EUR · Issued · Due Back · Days Out · Proforma) | BACKEND GATED | Table structure present; single gated-state row; no data |
| 4 | Issue sub-tab: + Issue Consignment button | BACKEND GATED | `cn-btn-issue` — disabled; title = OI-reason |
| 5 | Proforma Issue sub-tab: 4 KPI tiles | BACKEND GATED | All gated — PENDING |
| 6 | Proforma Issue sub-tab: 9-column table (Proforma · Client · Qty Issued · Value EUR · Sold · Balance Qty · Balance EUR · Issued · Status) | BACKEND GATED | Table structure with 9 columns present; single gated row |
| 7 | Balance/Valuation sub-tab: 4 KPI tiles | BACKEND GATED | All gated |
| 8 | Balance/Valuation sub-tab: 7-column table | BACKEND GATED | Structure present; single gated row |
| 9 | Balance/Valuation sub-tab: ↓ Export valuation button | BACKEND GATED | `cn-btn-export-valuation` — disabled; title = OI-reason |

**Matrix line:**
`Wireframe controls: 9 · Implemented: 0 · Backend gated: 9 · Operator ruled: 0 · Out of scope: 0 · Missing: 0`

*(All 9 controls are present as honest WFIRMA-GATED surfaces per Lesson M — structure is correct, data gated by open OIs.)*

---

## Page 11 — Identity / Mapping Tab (IdentityMappingTab)

**Wireframe §7 Tab 11** | **Build record:** `2026-07-04-page11-identity-mapping.md`  
**Census gaps:** IV-ID-1

| # | Control | Classification | Evidence |
|---|---------|---------------|---------|
| 1 | Info banner (verbatim wireframe text — wFirma not the truth) | IMPLEMENTED | `id-info-banner` — verbatim wireframe §7 Tab 11 text confirmed in browser |
| 2 | Capability strip (goods.read / goods.write status) | IMPLEMENTED | `id-cap-strip` — calls `getWfirmaCapabilities()` |
| 3 | Filter input (product code / wFirma ID) | IMPLEMENTED | `id-filter` |
| 4 | ↻ Refresh button | IMPLEMENTED | `id-refresh` → `getWfirmaProducts()` |
| 5 | 8-column identity table (wFirma Good ID · wFirma Product Code · Product Family Code · Design ID · Batch ID · Bag ID · Stock Unit ID · Trace Barcode) | IMPLEMENTED | `id-table` — 8 columns; 2 wFirma columns live; 6 internal columns show honest `—` (IV-ID-1 no endpoint) |
| 6 | Editable fields (Product Family Code / Design ID / Batch ID / Bag ID per wireframe) | BACKEND GATED | 6 internal columns show `—`; no edit inputs rendered; Lesson M: no `/api/v1/inventory/identity` endpoint; census IV-ID-1 |

**Matrix line:**
`Wireframe controls: 6 · Implemented: 5 · Backend gated: 1 · Operator ruled: 0 · Out of scope: 0 · Missing: 0`

---

## Page 12 — MoveStockModal Stage-Transition Tab

**Wireframe §7 MoveStockModal** | **Build record:** `2026-07-04-page12-movestock-transition.md`  
**Census gaps:** IV-MS-1, IV-ST-1 (new)

| # | Control | Classification | Evidence |
|---|---------|---------------|---------|
| 1 | Move type toggle (Warehouse→Warehouse / Stage transition) | IMPLEMENTED | Both tab options now equally clickable; previous dead-disabled state removed |
| 2 | Stage-transition tab content: architecture doctrine banner | IMPLEMENTED | `ms-stage-doctrine` — explains document-driven transitions |
| 3 | Stage-transition tab: WAREHOUSE_STOCK group — 4 transitions with deep-link buttons | IMPLEMENTED | `inv:jump` CustomEvent fires for sampleOut / tempSale / clientReturn / producerReturn tabs |
| 4 | Stage-transition tab: PURCHASE_TRANSIT group | IMPLEMENTED | Auto-promote explanation, Temp Purchase tab reference |
| 5 | Stage-transition tab: SAMPLE_OUT group | IMPLEMENTED | Deep-links to sampleReturn / clientReturn |
| 6 | Stage-transition tab: RETURNS group | IMPLEMENTED | Restocking events via return tabs |
| 7 | Stage-transition tab: SALES_TRANSIT → CLOSED group | BACKEND GATED | `ms-stage-group-terminal` — no delivery_confirmed POST route; IV-TS-1 |
| 8 | Wireframe: "Confirm move → Consignment" | BACKEND GATED | `ms-stage-lesson-m` panel — Lesson M IV-ST-1; WFIRMA-GATED · OI-1 |
| 9 | Wireframe: "Confirm move → Temp Sale" | BACKEND GATED | `ms-stage-lesson-m` panel — Lesson M IV-ST-1; no POST route for invoice_issued transition |
| 10 | Close button | IMPLEMENTED | `ms-stage-close` |
| 11 | Warehouse→Warehouse tab: Stock unit input | IMPLEMENTED | Pre-existing W→W tab — live; untouched |
| 12 | Warehouse→Warehouse tab: Qty / From / To / Reason | IMPLEMENTED | Pre-existing W→W tab fields |

**Matrix line:**
`Wireframe controls: 12 · Implemented: 9 · Backend gated: 3 · Operator ruled: 0 · Out of scope: 0 · Missing: 0`

---

## FINAL TABLE

| Page | Wireframe Controls | Implemented | Backend Gated | Operator Ruled | Out of Scope | Missing | WR-Missing Count |
|------|--------------------|-------------|---------------|---------------|-------------|---------|-----------------|
| 1 — Sample Out | 8 | 6 | 2 | 0 | 0 | 0 | 0 |
| 2 — Sample Return | 7 | 4 | 3 | 0 | 0 | 0 | 0 |
| 3 — Client Return | 7 | 4 | 3 | 0 | 0 | 0 | 0 |
| 4 — Return to Producer | 8 | 5 | 2 | 0 | 0 | 1 | 1 |
| 5 — Temp Sale | 7 | 5 | 2 | 0 | 0 | 0 | 0 |
| 6 — Overview | 10* | 7 | 1 | 2 | 0 | 2 | 2 |
| 6b — PageHeader Actions | 3 | 2 | 1 | 0 | 0 | 0 | 0 |
| 7 — Temp Purchase | 8 | 7 | 1 | 0 | 0 | 0 | 0 |
| 8 — Temp Warehouse | 8 | 7 | 1 | 0 | 0 | 0 | 0 |
| 10 — Consignment (gated) | 9 | 0 | 9 | 0 | 0 | 0 | 0 |
| 11 — Identity / Mapping | 6 | 5 | 1 | 0 | 0 | 0 | 0 |
| 12 — MoveStock Stage tab | 12 | 9 | 3 | 0 | 0 | 0 | 0 |
| **TOTALS** | **93** | **61** | **29** | **2** | **0** | **3** | **3** |

*Page 6 wireframe count uses 10 (excludes the 2 Operator-Ruled items from the wireframe-required total of 12).

---

## RE-OPEN LIST

Pages with Wireframe-Required Missing > 0:

### Page 4 — Return to Producer (Missing: 1)
**"View docs" row action** (wireframe §7 Tab 10: "Add AWB · View docs")
- The build record documents `rtp-btn-add-awb` (honest-disabled) and `rtp-btn-confirm-received` (live).
- "View docs" does not appear as a wired or honest-disabled testid in the page 4 build record.
- No `rtp-btn-view-docs` testid found; no mention of `View docs` in the implementation.
- This is a wireframe-required row action (WIREFRAME-REQUIRED per bundle `7289f2fd`) with no implementation and no honest-disable record.
- **Action required:** Add `rtp-btn-view-docs` as Lesson-M honest-disabled (no detail/document viewer endpoint for producer return records) with census tag.

### Page 6 — Overview (Missing: 2)
**KPI tile "Total value"** (5th wireframe §7 Tab 1 tile)
- Wireframe §7 Tab 1 defines: Stock units · Pieces on hand · Reserved · Available · Total value.
- The live Overview implements 4 KPI tiles: Stock units (final) / Pieces on hand (honest `—`) / Returns (mapped to returns count) / Consignment (WFIRMA-GATED).
- No "Reserved" tile, no "Available" tile, no "Total value" tile correspond to the wireframe's 3rd, 4th, and 5th tiles.
- The stage2 aggregate (`/api/v1/inventory/stage2/aggregate`) does not return a value field.
- **Action required for "Total value":** Add a 5th KPI tile as Lesson-M honest-pending with census tag (no value aggregate endpoint; Wave 4 scope).
- **Note on "Reserved" / "Available":** These two tiles differ from the wireframe label assignments. The "Returns (all)" tile in position 3 is not the same as "Reserved". An honest resolution is either (a) rename/re-map live tiles to match wireframe labels where possible, or (b) add the two missing tiles as honest-pending. Currently classified as MISSING until operator rules on tile-label mapping.
- For the purpose of this re-open list: reporting as **1 MISSING tile ("Total value") + 1 MISSING tile grouping ("Reserved"/"Available" label mismatch)** — count of 2 as shown in the final table above.

---

*Report generated: 2026-07-04*  
*Source documents consumed: wireframe-inventory (§7), gap-census §A + AMENDMENT, pages/*.md (12 build records), live inventory-page.jsx (INV_TABS + component grep verification)*
