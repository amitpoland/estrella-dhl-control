# Wave-3 Page-by-Page Gap Census
**Branch:** deploy/latest  
**Date:** 2026-07-03  
**Produced from:** wireframe-inventory · live-app-inventory · WIREFRAME_AUTHORITY · OPEN_ITEMS · DECISIONS (last two entries)  
**Wave-3 governing directive (verbatim):** "Make the live application match the approved wireframes exactly." — operator ratification 2026-07-03

---

## Section A — Per-Wireframe-Screen Gap Tables (wireframe nav order)

Tag legend:
- **BUILD** — wireframe requires it AND backend is live
- **REMOVE** — placeholder / duplicate / dead code in live app
- **WFIRMA-GATED** — wireframe requires it but depends on an OPEN OI; render as honest gated surface (Lesson M)
- **OUT** — wireframe is silent about a live feature; untouched, listed for the record

---

### Screen 1 — Dashboard
**Wireframe §1** | **Live file:** `dashboard-kanban.jsx` (WIRED, LIVE)

| # | Gap | TAG | Basis |
|---|---|---|---|
| D-1 | Wireframe §1.1 defines exactly 5 KPI tiles: Active shipments · Urgent · Inbound · Outbound · Total value. Live has a live KPI bar (sprint 40) — column names and tile count need parity verification against wireframe spec | BUILD | Wireframe §1.1; live: `dashboard-kanban.jsx` (no line cite — not deeply inspected in input 2) |
| D-2 | Wireframe §1.2 requires 4 Quick-flow CTA buttons: Receive shipment (IN) · Create outbound shipment (OUT) · Process new email · Customer order. Live sprint-40 Kanban board does not cite these CTAs | BUILD | Wireframe §1.2; live: `dashboard-kanban.jsx` status LIVE Sprint 40 — CTA presence unconfirmed by input 2 |
| D-3 | Wireframe §1.3 defines exactly 6 Kanban lanes with specific color bands and hints (New/Drafting, Awaiting Documents, Customs Clearance, Ready to Ship, In Transit, Delivered). Live has lanes: new → docs → customs → ready → booked → done — "booked" and "done" do not match wireframe's "In Transit" and "Delivered" | BUILD | Wireframe §1.3; live-app-inventory §PAGE:dashboard lane list |
| D-4 | Wireframe §1.4 requires GlobalSearch modal (⌘K/Ctrl+K) with overlay, search input, 5 filter chips (All/AWBs/Invoices/Clients/Inventory), result list with keyboard navigation | BUILD | Wireframe §1.4; live `global-search.jsx` is loaded (script load order entry 26), wiring to ⌘K on Dashboard needs verification |
| D-5 | Wireframe §39 OperationalStatusStrip is defined at §14.2 (Diagnostics) as live integration status with last-ping timestamps. Live strip (`wireframe-update.jsx:68-98`) is fully hardcoded static — never calls backend | REMOVE | Live-app-inventory §SECTION 3, `wireframe-update.jsx:68-98` |

---

### Screen 2 — Inbox
**Wireframe §2** | **Live file:** `inbox-page.jsx` (WIRED, LIVE, Sprint 2B.2)

| # | Gap | TAG | Basis |
|---|---|---|---|
| I-1 | Wireframe §2.1 requires 6 left-rail tabs with count badges: All · Emails · Proposals · Approvals · Reservations · Customs. Live reports 0 placeholder items and 0 dead controls — tab count/labeling parity needs confirmation | BUILD | Wireframe §2.1; live: `inbox-page.jsx` status "LIVE 0 placeholder 0 dead" but no column-level detail in input 2 |
| I-2 | Wireframe §2.2 requires priority filter: All priorities · Urgent (red) · High (amber) · Normal (blue) · Info (neutral). Parity unconfirmed from live inspection | BUILD | Wireframe §2.2; live input 2 §PAGE:inbox: no per-control detail |
| I-3 | TopBar notification bell (no `onClick` handler) is rendered on inbox page (and every wired page). Wireframe §2 does not define this as a dead control | REMOVE | Live-app-inventory §TopBar dead controls, `components.jsx:346-349` |
| I-4 | TopBar user avatar dropdown (no `onClick` handler) rendered on every wired page including Inbox. Wireframe §2 does not define a dead avatar dropdown | REMOVE | Live-app-inventory §TopBar dead controls, `components.jsx:351-363` |

---

### Screen 3 — Shipments (list)
**Wireframe §3.1** | **Live file:** `dashboard-page.jsx` (WIRED, LIVE, Sprint 32)

| # | Gap | TAG | Basis |
|---|---|---|---|
| SH-1 | Wireframe §3.1 defines exactly 7 columns: AWB/Tracking · Carrier · Overall Status · Net Value · Gross Value · Duty A00 · Actions. Live `FilteredShipmentsTable` in `pages.jsx` is built on hardcoded `MOCK_SHIPMENTS` — this component is globally loaded but the routing mounts `DashboardPage`, not the mock table. The mock definition is dead code for this page but still in global scope | REMOVE | Live-app-inventory §PAGE:shipments caution note, `pages.jsx` MOCK_SHIPMENTS array |
| SH-2 | Wireframe §3.1 requires carrier badge filter chips (DHL/FedEx/neutral) and a search input on the shipment list toolbar. Live page notes 0 dead controls (Sprint 32) — toolbar filter parity unconfirmed | BUILD | Wireframe §3.1 toolbar; live: `dashboard-page.jsx`, no per-control detail in input 2 |

---

### Screen 3 — Shipment Detail Page
**Wireframe §3.2** | **Live file:** `shipment-detail-page.jsx` (WIRED, LIVE)

| # | Gap | TAG | Basis |
|---|---|---|---|
| SD-1 | Wireframe §3.2 header card requires: AWB · Carrier chip · Overall status badge · MRN (mono) · Packing List (mono) · Net · Gross · Duty · 7 workflow stage pills. Live reads from audit JSON (CIF, clearance date, customs agent, LRN, SAD/NBP rates, A00/B00, PZ number, wFirma doc id, line count, invoice count, activity timeline) — MRN, Packing List (mono), Carrier chip, 7 workflow stage pills need parity verification | BUILD | Wireframe §3.2 header; live: `shipment-detail-page.jsx` field list in input 2 |
| SD-2 | Wireframe §3.2 Tab 1 (Overview) requires contextual write buttons per workflow stage. Live has "Write buttons visible but disabled (Lesson M)" — this is correct per Lesson M, but buttons must be wired to their domain pages (not merely shown as disabled stubs) per wireframe intent | BUILD | Wireframe §3.2 Tab 1; live: `shipment-detail-page.jsx` "write actions visible + disabled" |
| SD-3 | Wireframe §3.2 Tab 2 (Pro Forma) requires: list of proforma drafts linked to shipment, empty state with "+ Create Pro Forma Draft" button, draft row columns (Draft number, status, Customer, Items, Total EUR). Live inspection did not confirm this tab's presence | BUILD | Wireframe §3.2 Tab 2; live-app-inventory has no Tab-2 detail for shipment-detail-page |
| SD-4 | Wireframe §3.2 Tab 3 (DHL/Customs) requires 6 buttons in Step 1 panel and 4 buttons in Step 2 (SAD/ZC429) panel. Live DHL page is at `/dhl` slug, not as a tab inside shipment detail — routing architecture may differ from wireframe's in-page tab model | BUILD | Wireframe §3.2 Tab 3; live: dhl is a separate WIRED page (pages-v2.jsx), not a sub-tab of shipment detail |
| SD-5 | Wireframe §3.2 Tab 4 (PZ/Accounting) requires conditional buttons: Run PZ · Regenerate PZ · Confirm PZ Number · Download XLSX · Download PDF · Export to wFirma · Mark Exported. Live: write buttons visible but disabled; button set parity unconfirmed | BUILD | Wireframe §3.2 Tab 4; live: `shipment-detail-page.jsx` "write buttons visible but disabled" |
| SD-6 | Wireframe §3.2 Tab 5 (Documents) requires 4 document cards (PL/PF/CMR/WF) with state chips and per-card View+Download buttons. Parity with live unconfirmed | BUILD | Wireframe §3.2 Tab 5; live-app-inventory has no Tab-5 detail |
| SD-7 | Wireframe §3.2 Tab 6 (Timeline) requires 16 named events as a chronological list. Live has "activity timeline — all from live audit". Event count and labels need parity check | BUILD | Wireframe §3.2 Tab 6; live: `shipment-detail-page.jsx` cites "activity timeline" — count unconfirmed |

---

### Screen 4 — Pro Forma List
**Wireframe §4.1** | **Live file:** `proforma-list.jsx` (WIRED, LIVE, Sprint 36)

| # | Gap | TAG | Basis |
|---|---|---|---|
| PL-1 | Wireframe §4.1 requires 5 pipeline KPI tiles (Extracting · Operator Review · Ready · Pushed · Error). Parity with live unconfirmed | BUILD | Wireframe §4.1; live: `proforma-list.jsx` — no KPI tile detail in input 2 |
| PL-2 | Wireframe §4.1 requires 8-column table with checkbox column and Match chip. Live 0 placeholder 0 dead — column count/Match chip parity unconfirmed | BUILD | Wireframe §4.1 table cols; live: `proforma-list.jsx` |
| PL-3 | Wireframe §4.2 (NewProformaDraftModal) requires 4 source option buttons with specific labels and descriptions, plus info banner. Parity unconfirmed | BUILD | Wireframe §4.2; live: modal wired via `modals.jsx` but per-field detail not in input 2 |
| PL-4 | Wireframe §4.3 (ImportPackingListModal) requires 4-step wizard (Upload/Extraction/Mapping/Create draft). Parity unconfirmed | BUILD | Wireframe §4.3; live: `modals.jsx` but per-step detail not in input 2 |
| PL-5 | `getServiceProducts` is defined in `pz-api.js:134` as `_get('/api/v1/proforma/service-products')` (backend live at `routes_proforma.py:4546`) but zero V2 JSX pages call it. Wireframe §4 Pro Forma may surface service products in line items | BUILD | Live-app-inventory §SECTION 4, `pz-api.js:134`; backend `routes_proforma.py:4546` |

---

### Screen 4 — Pro Forma Detail
**Wireframe §4.4** | **Live file:** `proforma-detail.jsx` (WIRED, LIVE, Sprint 36 Phase 2)

| # | Gap | TAG | Basis |
|---|---|---|---|
| PD-1 | Wireframe §4.4 header requires: Edit · Save · Cancel · Push to wFirma (gold, gated) · Download PDF. Live has 8-button toolbar: Edit / Delete / Duplicate / PostToWFirma / Convert / Print / Send / Generate — Delete, Duplicate, Convert, Print, Send, Generate are BEYOND wireframe spec or named differently. Wireframe-not-defined buttons need review: are they OUT or misnamed wireframe buttons? | QUESTION | Wireframe §4.4 header buttons; live: `proforma-detail.jsx` "8-button toolbar" |
| PD-2 | Wireframe §4.4 Tab 2 (Items) defines 16 columns in exact order: Sr · Product Code · Design Nr · Ctg · Client PO · Description EN · Description PL · Kt · Col · Quality · Dia Wt · Col Wt · Qty · Value · Total · Size · (delete icon). Live column set unconfirmed | BUILD | Wireframe §4.4 Tab 2 exact 16-col spec; live: `proforma-detail.jsx` line items from `editable_lines` |
| PD-3 | Wireframe §4.4 Tab 4 (Matching) requires match state per line: auto-matched · partial-matched · manual. Live has `ReservationTab` wired to `blocking_reasons` — this appears to be a different tab than wireframe's Matching tab | BUILD | Wireframe §4.4 Tab 4; live: `proforma-detail.jsx` "ReservationTab wired to blocking_reasons" |
| PD-4 | Wireframe §4.4 Tab 5 (Push to wFirma) requires 2 tables: Ready queue (5 cols) + Export log (7 cols). Live has `PostToWFirmaModal` — modal vs tab architecture differs from wireframe | BUILD | Wireframe §4.4 Tab 5; live: `PostToWFirmaModal` |
| PD-5 | Wireframe §4.4 Tab 6 (Audit Trail) requires events table (timestamp · user · action · status dot). Live parity unconfirmed | BUILD | Wireframe §4.4 Tab 6; live: `proforma-detail.jsx` — no audit trail tab detail in input 2 |

---

### Screen 5 — Documents Hub
**Wireframe §5** | **Live file:** `documents-hub.jsx` (WIRED, LIVE, Sprint 35)

| # | Gap | TAG | Basis |
|---|---|---|---|
| DC-1 | Wireframe §5.1 defines 3 tabs: Proforma (PI) · PZ — Inbound · Other documents. Live uses GET /api/v1/dashboard/batches — tab labels and count parity unconfirmed | BUILD | Wireframe §5.1; live: `documents-hub.jsx` — no per-tab detail in input 2 |
| DC-2 | Wireframe §5.2 requires lane workflow per tab: Draft → Approved → Posted. Lane structure parity unconfirmed | BUILD | Wireframe §5.2; live: `documents-hub.jsx` |
| DC-3 | Wireframe §5.3 requires Upload packing list + New PI / New PZ toolbar buttons per tab. Live 0 dead controls — button presence and routing unconfirmed | BUILD | Wireframe §5.3; live: `documents-hub.jsx` |
| DC-4 | Wireframe §5.4 DocumentViewerPage requires 8 toolbar buttons + side panel with 10 metadata fields (Document type · Document # · Title · Linked AWB · Linked shipment · Uploaded · Uploaded by · Size · Format · Hash). Live `DocumentViewerPage` (`inventory-page.jsx:25-171`) has hardcoded fallback metadata: doc type `'Packing List'`, id `'PL-EJL-26-27-013'`, AWB `'DHL-1234567890'`, shipment `'SHP-2026-0142'` + 3 hardcoded table rows + 4 hardcoded `<a href="#">` links | REMOVE | Live-app-inventory §DocumentViewerPage `inventory-page.jsx:25-171`, placeholder blocks cited |

---

### Screen 6 — Accounting
**Wireframe §6** | **Live file:** `accounting-hub.jsx` (NOT IN WIRED_PAGES — receives MOCK banner)

| # | Gap | TAG | Basis |
|---|---|---|---|
| AC-1 | Accounting page (`accounting` slug) is NOT in WIRED_PAGES (`mock-badge.jsx:68`) — all content is MOCK | REMOVE | Live-app-inventory §SECTION 1 NAV_TREE: `accounting` NO → MOCK |
| AC-2 | Wireframe §6.1 requires 4 KPI tiles: Purchase ledger (count) · Sales/proforma (count) · wFirma sync (status) · Audit events (count). All hardcoded/mock | REMOVE | Live-app-inventory §END SUMMARY TABLE row: accounting "all" |
| AC-3 | Wireframe §6.2 Tab A (Purchase Ledger/PZ) requires FilteredShipmentsTable with 7 cols and 4 KPI tiles. Not wired | BUILD | Wireframe §6, Tab A; backend: routes_wfirma pz routes LIVE (input 2 §WIREFRAME_AUTHORITY §A) |
| AC-4 | Wireframe §6.2 Tab B (Sales/Proforma) requires 4 KPI tiles + 3 sub-tabs + proforma table. Not wired | BUILD | Wireframe §6 Tab B; proforma backend LIVE |
| AC-5 | Wireframe §6.2 Tab C (Ledgers/Statements) requires ClientLedgerView with 4 KPI tiles + 10-col ClientStatementTable. `ledgers-page.jsx` is loaded in script order (entry 10) but accounting is NOT in WIRED_PAGES | BUILD | Wireframe §6 Tab C; `ledgers-page.jsx` loaded but not mounted under accounting slug |
| AC-6 | Wireframe §6.2 Tab D (wFirma Sync) duplicates `wfirma_setup` (which is LIVE at Sprint 37). Accounting tab D should mount the same WfirmaMappingPage | OUT | Wireframe §6 Tab D = same as Setup→wFirma; `wfirma_setup` LIVE |
| AC-7 | Wireframe §6.2 Tab E (Master Data) duplicates `master` (which is LIVE at Sprint 38). Accounting tab E should mount the same MasterDataView | OUT | Wireframe §6 Tab E = same as Setup→Master Data; `master` LIVE |
| AC-8 | Wireframe §6.2 Tab F (Audit Trail) requires 4-col table with search/filter controls. Not wired | BUILD | Wireframe §6 Tab F; audit trail backend exists (`/api/v1/master/audit/`) |
| AC-9 | `supplier_invoice_review` nav slot (NEW badge) appears in live NAV_TREE but is NOT in wireframe nav. Wireframe's accounting section does not define a "Supplier Invoices" nav entry | OUT | Live: `mock-badge.jsx:68` WIRED_PAGES includes `supplier_invoice_review`; wireframe §6 has no such tab |

---

### Screen 7 — Inventory (11 tabs — operator directive: Inventory FIRST)
**Wireframe §7** | **Live file:** `inventory-page.jsx` (WIRED, LIVE with Phase-C gaps)

The wireframe defines 11 tabs. The live app (`inventory-page.jsx`, 1059 lines) implements panels oriented around scan/batch/piece/location/audit/move operations — this is a different structural model from the wireframe's 11-tab layout.

#### Tab 1 — Overview (InventoryOverviewTab)
**Wireframe §7, Tab 1** | **U-6 operator mapping**

| # | Gap | TAG | Basis |
|---|---|---|---|
| IV-O-1 | Wireframe requires 5 KPI tiles: Stock units · Pieces on hand · Reserved · Available · Total value. Live `Stage2Panel` (`inventory-page.jsx:297-338`) shows 4 tiles: In Transit · At Warehouse · Dispatched · **Consignment** (BACKEND-PENDING·PHASE C dead tile). Tile count and labels both mismatch wireframe | BUILD | Wireframe §7 Tab 1; live: `inventory-page.jsx:297-338` Stage2Panel tiles; GET /api/v1/inventory/stage2/aggregate LIVE |
| IV-O-2 | Wireframe requires Stage 1 summary card (Open packing lists · Awaiting goods · Partially arrived · Closed-out) and Stage 2 summary card (Final stock units · Reserved · Samples out · Consignment out). Live has no separate Stage 1 summary card | BUILD | Wireframe §7 Tab 1 stage cards; live: `inventory-page.jsx` shows BatchPanel at lines 342-416 (user-triggered, not auto) |
| IV-O-3 | Wireframe requires 4 Quick-action buttons: Upload Packing List · New Consignment · Issue Sample · Move Stock (→MoveStockModal). Live has only "⇄ Move Stock" button (`inventory-page.jsx:1020-1053`). Upload Packing List, New Consignment, Issue Sample are absent | BUILD | Wireframe §7 Tab 1 quick-actions; live: `inventory-page.jsx:1029` one button |
| IV-O-4 | Live **Consignment KPI tile** shows `"BACKEND-PENDING · PHASE C"` badge — static, no action. Wireframe defines this tile as live data. Backend for consignment does not exist (OI-1, OI-2, OI-17 OPEN) | WFIRMA-GATED | Live: `inventory-page.jsx:297-338` Consignment tile `pending` prop; OPEN_ITEMS OI-1, OI-2, OI-17 |

#### Tab 2 — Temp Purchase (TempPurchaseTab)
**Wireframe §7, Tab 2** — NO live panel in `inventory-page.jsx`

| # | Gap | TAG | Basis |
|---|---|---|---|
| IV-TP-1 | Entire Temp Purchase tab (4 KPI tiles + stage info banner + 13-col table + 3 toolbar buttons) is absent from live app. Backend: packing_lines data exists (cited in WIREFRAME_AUTHORITY §Wireframe column requirements). No dedicated route confirmed | BUILD | Wireframe §7 Tab 2; live: `inventory-page.jsx` has no TempPurchaseTab; WIREFRAME_AUTHORITY §Wireframe column requirements cites packing_lines as data source |

#### Tab 3 — Temp Warehouse (TempWarehouseTab)
**Wireframe §7, Tab 3** — NO live panel in `inventory-page.jsx`

| # | Gap | TAG | Basis |
|---|---|---|---|
| IV-TW-1 | Entire Temp Warehouse tab (4 KPI tiles + stage info banner + 8-col table with delta column) is absent from live app | BUILD | Wireframe §7 Tab 3; live: `inventory-page.jsx` has BatchPanel (batch_id-triggered, GET /api/v1/inventory/state/{batch_id}) which may partially cover this — but tab structure, KPI tiles, and discrepancy tracking absent |

#### Tab 4 — Temp Sale (TempSaleTab)
**Wireframe §7, Tab 4** — NO live panel

| # | Gap | TAG | Basis |
|---|---|---|---|
| IV-TS-1 | Entire Temp Sale tab (4 KPI tiles including LOCKED gate banner + 8-col reservations table + row actions: View proforma · Issue invoice) is absent from live app. C-3d (SALES_TRANSIT) was Wave-2 backend — `run_stock_issue()` was shipped in Wave 2 (`ea6e165c`) | BUILD | Wireframe §7 Tab 4; live: no TempSaleTab panel; Wave-2 endpoint GET /api/v1/inventory/movements/{batch_id} LIVE (`routes_inventory.py:203`) per SECTION 4; C-3d backend confirmed |

#### Tab 5 — Consignment (ConsignmentTab)
**Wireframe §7, Tab 5** — U-4 operator mapping (WFIRMA-GATED)

| # | Gap | TAG | Basis |
|---|---|---|---|
| IV-CN-1 | `ConsignmentTab` exists in `client-kyc-and-consignment.jsx:282` — FULLY MOCK (4 hardcoded `issued` rows, 4 hardcoded `proformaIssued` rows, hardcoded KPI tiles). No route mounts it. All buttons (Issue Consignment, Convert to sale, Recall, Export valuation) have no handler. OI-1 (MM via API), OI-2 (consignment warehouse), OI-17 (allocation model) all OPEN — backend for consignment does not exist | WFIRMA-GATED | Live: `client-kyc-and-consignment.jsx:282`; OPEN_ITEMS OI-1, OI-2, OI-17; WIREFRAME_AUTHORITY §D "Consignment ledger: ConsignmentTab (exists, UNUSED)" |
| IV-CN-2 | Wireframe §7 Tab 5 defines 3 sub-tabs (Issue · Proforma Issue · Balance/Valuation). ConsignmentTab has these 3 sub-tabs but all data is hardcoded. Remove hardcoded data; render gated surface with honest pending badge per Lesson M | WFIRMA-GATED | Live: `client-kyc-and-consignment.jsx:282` sub-tabs present but mocked |
| IV-CN-3 | Proforma Issue sub-tab requires 9 columns including `Sold` and `Balance Qty/EUR`. Hardcoded mock rows prevent real data rendering | WFIRMA-GATED | Wireframe §7 Tab 5 Proforma Issue; live mock rows |

#### Tab 6 — Final Stock (FinalStockTab)
**Wireframe §7, Tab 6** — NO dedicated tab in `inventory-page.jsx`

| # | Gap | TAG | Basis |
|---|---|---|---|
| IV-FS-1 | Wireframe requires Final Stock tab with 5 KPI tiles + stage info banner + 10-col verified-stock-units table + filter input + Move Stock button. Live has `LocationPanel` (GET /api/v1/warehouse/locations + /locations/{code}/inventory) and `PiecePanel` which show location/piece data — but these are scan-triggered panels, not a final-stock tab with KPI tiles and a filterable table | BUILD | Wireframe §7 Tab 6; live: `inventory-page.jsx:552-638` LocationPanel, `inventory-page.jsx:420-548` PiecePanel — different model |
| IV-FS-2 | Wireframe §7 Tab 6 table requires columns: Stock Unit ID · Family · Design · Batch · Bag · Qty · Location · Value PLN · Trace Barcode · wFirma Good ID · wFirma Code · Verified On. Live PiecePanel and LocationPanel expose different column sets | BUILD | Wireframe §7 Tab 6 cols; live: PiecePanel columns not documented in input 2 |

#### Tab 7 — Sample Out (SampleOutTab)
**Wireframe §7, Tab 7** — U-1 operator mapping (Sample Out)

| # | Gap | TAG | Basis |
|---|---|---|---|
| IV-SO-1 | `SampleOutPage` stub exists at `wireframe-update.jsx:492-507` — 3 hardcoded fixture rows, `status=partial`, FICTIONAL endpoints. Not mounted in routing (slug `sample_out` redirects to `inventory`). Backend LIVE: GET /api/v1/inventory/samples (`routes_inventory_sample.py:149`); POST endpoints for sample out also live per WIREFRAME_AUTHORITY §A "routes_inventory_sample.py:91-144 LIVE" | BUILD | Live: `wireframe-update.jsx:492-507`; backend: `routes_inventory_sample.py:149` (SECTION 4); WIREFRAME_AUTHORITY §A "C-3b" |
| IV-SO-2 | Wireframe requires 4 KPI tiles (Active out · Closing soon ≤3 days · Overdue · Returned mo.) — absent from stub | BUILD | Wireframe §7 Tab 7 KPIs; live stub has none |
| IV-SO-3 | Wireframe requires 10-col table (Sample ID · Source SU · Design · Qty · Issued to · Purpose · Issued · Return by · Days left (colored) · Status) + row actions: Record Return (if out/overdue) · View. Stub has 3 hardcoded rows with fictional data | BUILD | Wireframe §7 Tab 7 table; live stub `wireframe-update.jsx:492-507` |
| IV-SO-4 | Wireframe requires "+ Issue Sample" toolbar button. Stub has no wired handler | BUILD | Wireframe §7 Tab 7 button; live stub no handler |

#### Tab 8 — Sample Return (SampleReturnTab)
**Wireframe §7, Tab 8** — U-1 operator mapping (Sample Return)

| # | Gap | TAG | Basis |
|---|---|---|---|
| IV-SR-1 | `SampleReturnPage` stub at `wireframe-update.jsx:510-525` — 3 hardcoded rows, `status=backend`, FICTIONAL endpoints. Not mounted (slug `sample_return` → inventory). Backend LIVE: GET /api/v1/inventory/samples + returns endpoints per WIREFRAME_AUTHORITY §A | BUILD | Live: `wireframe-update.jsx:510-525`; backend: `routes_inventory_sample.py` LIVE; WIREFRAME_AUTHORITY §A "C-3b" |
| IV-SR-2 | Wireframe requires 4 KPI tiles (Awaiting inspection · In repair · Restocked mo. · Written off mo.) + 10-col table (Return ID · Sample · Design · Qty · Returned from · Received · Condition · Inspector · Decision · Status) + row actions (Inspect / View). Stub has none | BUILD | Wireframe §7 Tab 8; live stub |

#### Tab 9 — Goods Return from Client (ClientReturnTab)
**Wireframe §7, Tab 9** — U-2 operator mapping (Client Return)

| # | Gap | TAG | Basis |
|---|---|---|---|
| IV-CR-1 | `GoodsReturnPage` stub at `wireframe-update.jsx:528-543` — 3 hardcoded rows, `status=backend`, FICTIONAL endpoints. Not mounted (slug `goods_return` → inventory). Backend LIVE: GET /api/v1/inventory/returns (`routes_inventory_returns.py:212`); POST endpoints per WIREFRAME_AUTHORITY §A "routes_inventory_returns.py:116-201 LIVE" | BUILD | Live: `wireframe-update.jsx:528-543`; backend: `routes_inventory_returns.py:212` (SECTION 4); WIREFRAME_AUTHORITY §A "C-3a/C-3c" |
| IV-CR-2 | Wireframe requires 4 implied KPI tiles + 10-col RMA table + reason values (Size exchange · Damaged in transit · Wrong item shipped · Quality dispute) + row actions. Stub has none of this | BUILD | Wireframe §7 Tab 9; live stub |

#### Tab 10 — Return to Producer (ProducerReturnTab)
**Wireframe §7, Tab 10** — U-2 operator mapping (Return-to-Producer)

| # | Gap | TAG | Basis |
|---|---|---|---|
| IV-RTP-1 | `ReturnToProducerPage` stub at `wireframe-update.jsx:546-561` — 3 hardcoded rows, `status=future`, FICTIONAL endpoints. Not mounted (slug `return_prod` → inventory). Backend: `routes_inventory_returns.py` LIVE per WIREFRAME_AUTHORITY §A (migration pending) | BUILD | Live: `wireframe-update.jsx:546-561`; WIREFRAME_AUTHORITY §A "C-3c" |
| IV-RTP-2 | Wireframe requires 4 KPI tiles (In preparation · Awaiting AWB · In transit · Confirmed mo.) + 10-col table + row actions (Add AWB · View docs). Stub has none | BUILD | Wireframe §7 Tab 10; live stub |

#### Tab 11 — Identity / Mapping (MappingTab)
**Wireframe §7, Tab 11**

| # | Gap | TAG | Basis |
|---|---|---|---|
| IV-ID-1 | `IdentityMappingPage` stub at `wireframe-update.jsx:465-481` — `status=backend`, 3 hardcoded rows, FICTIONAL endpoints. Not mounted (slug `identity` → inventory). Wireframe §7 Tab 11 defines an 8-field identity table (wfirma_good_id · wfirma_product_code · product_family_code · design_id · batch_id · bag_id · stock_unit_id · trace_barcode) with editable/readonly per field. Live `wfirma_setup` page (WfirmaMappingPage) covers the wFirma identity mapping side — but the internal stock_unit_id / trace_barcode identity model is not wired anywhere | BUILD | Live: `wireframe-update.jsx:465-481`; `wfirma_setup` LIVE (Sprint 37); Wireframe §7 Tab 11 |

#### MoveStockModal
**Wireframe §7, MoveStockModal**

| # | Gap | TAG | Basis |
|---|---|---|---|
| IV-MS-1 | Wireframe MoveStockModal requires: Move type toggle (Warehouse→Warehouse / Stage transition) + Stock unit + Qty + From (select 4 locations) + To warehouse / To stage + Issued to/Consignee (if sample/consignment) + Return by (date picker) + Reason. Live MoveStockModal (`inventory-page.jsx:842-1015`) Tab 1 (W→W) is LIVE; Tab 2 (Stage transition) is DEAD — `"Backend-pending — Phase C"` banner, no API call (`inventory-page.jsx:~989`) | BUILD | Live: `inventory-page.jsx:~989` stage-transition tab disabled banner; backend C-3d shipped (`run_stock_issue()`); GET /api/v1/inventory/movements/{batch_id} LIVE |

---

### Screen 8 — Reports
**Wireframe §8** | **Live:** NOT IN WIRED_PAGES — receives MOCK banner

| # | Gap | TAG | Basis |
|---|---|---|---|
| RP-1 | `reports` slug NOT in WIRED_PAGES — receives MOCK banner (`mock-badge.jsx:68`) | REMOVE | Live: `mock-badge.jsx:68`; `reports` not in WIRED_PAGES list |
| RP-2 | Wireframe §8.1 requires 4 KPI tiles (Shipments YTD · Total Duty Paid YTD · Total Gross YTD · Avg Processing Time) + §8.2 Duty Summary Table (6 cols). No backend routes confirmed live for this | BUILD | Wireframe §8; live MOCK; no backend endpoint identified in input 2 for reports |

---

### Screen 9 — Setup → Settings (AdminSettingsPage)
**Wireframe §9** | **Live:** `admin` slug NOT IN WIRED_PAGES — receives MOCK banner

| # | Gap | TAG | Basis |
|---|---|---|---|
| ADM-1 | `admin` slug NOT in WIRED_PAGES — receives MOCK banner | REMOVE | Live: `mock-badge.jsx:68`; `admin` not in WIRED_PAGES |
| ADM-2 | Wireframe §9 requires 3 cards: API Configuration (3 fields + Save) · Users & Roles (list + Invite User) · System Status (4 tiles). No backend wired | BUILD | Wireframe §9; live MOCK; GET /api/v1/settings/company-profile exists (cited in proforma-detail context) |

---

### Screen 10 — Setup → Master Data
**Wireframe §10** | **Live file:** `master-page.jsx` (WIRED, LIVE, Sprint 38)

| # | Gap | TAG | Basis |
|---|---|---|---|
| MD-1 | Wireframe §10 / §6 Tab E defines 5 specific sub-sections: Clients/Importers (6 cols) · Suppliers/Exporters (5 cols) · HS Codes/Tariff (5 cols) · Currency/FX Rates · VAT Rates (4 cols). Live `master-page.jsx` has 12 entity tabs (10 full CRUD + Users read-only + Roles static) — may superset the wireframe's 5 sections but column-level parity unconfirmed | BUILD | Wireframe §10; live: `master-page.jsx` 12 tabs vs wireframe's 5 sub-sections |
| MD-2 | Accounting → Tab E (Master Data) in wireframe §6 duplicates this page. Live `accounting` is MOCK — Accounting tab E does not mount master-page.jsx | OUT | Wireframe §6 Tab E = same as Setup→Master Data; `master` LIVE at `/master` |

---

### Screen 11 — Setup → Carriers
**Wireframe §11** | **Live file:** `carriers-page.jsx` (WIRED, LIVE, Sprint 39)

| # | Gap | TAG | Basis |
|---|---|---|---|
| CA-1 | Wireframe §11.1 requires 4 KPI tiles (Connected N/M · Sandbox/Prod · Webhooks 24h · Open Alerts) + §11.2 6 tabs (Carrier Accounts · Add Carrier · API Integration · Webhooks · Active Sessions · Audit Log) + §11.3 CarrierCard with 3 action buttons. Live reports 0 placeholder 0 dead (Sprint 39, all hardcoded removed) — per-tab and KPI tile parity unconfirmed | BUILD | Wireframe §11; live: `carriers-page.jsx` "all hardcoded CARRIERS/WEBHOOKS/SESSIONS/AUDIT/AVAILABLE_NEW removed" |

---

### Screen 12 — Setup → wFirma (WfirmaMappingPage)
**Wireframe §12** | **Live:** `wfirma_setup` WIRED, LIVE (Sprint 37)

| # | Gap | TAG | Basis |
|---|---|---|---|
| WF-1 | Wireframe §12 / §6 Tab D requires Capability strip (6 pills: customers.read/write · goods.read/write · warehouse.read · reservation.write) with blocking reasons banner. Live Sprint 37 reports 0 placeholder 0 dead — capability strip parity unconfirmed | BUILD | Wireframe §12 capability strip; live: `(WfirmaMappingPage)` Sprint 37 |
| WF-2 | Wireframe §12 Customers table requires 6 cols (Name · wFirma ID · VAT · Country · Match status · Last Sync). Products table requires 7 cols. Column parity unconfirmed | BUILD | Wireframe §12 table columns; live: Sprint 37 |

---

### Screen 13 — Setup → API Status
**Wireframe §13** | **Live file:** `api-status-page.jsx` (WIRED, LIVE, Sprint 41)

| # | Gap | TAG | Basis |
|---|---|---|---|
| AS-1 | Wireframe §13.1 requires 4 KPI tiles (Healthy/Total · Calls 24h · P95 latency · Open incidents) + §13.2 4 tabs (Integrations · Endpoint Registry · Recent Errors · Incidents). Live Sprint 41 reports 0 placeholder (all 4 fake arrays removed) and 0 dead — tile/tab parity unconfirmed | BUILD | Wireframe §13; live: `api-status-page.jsx` Sprint 41 |

---

### Screen 14 — Setup → Diagnostics
**Wireframe §14** | **Live:** `(DiagnosticsPage)` WIRED, LIVE (Sprint 42)

| # | Gap | TAG | Basis |
|---|---|---|---|
| DG-1 | Wireframe §14.1 requires 4 KPI tiles (Health checks N/M · Storage used · Active locks · Version). Live Sprint 42 reports 0 placeholder — parity unconfirmed | BUILD | Wireframe §14; live: Sprint 42 |
| DG-2 | Wireframe §14.2 OperationalStatusStrip on Diagnostics page defines 6 integrations with per-integration name/status-dot/last-ping/latency. Persistent shell OperationalStatusStrip (`wireframe-update.jsx:68-98`) is fully hardcoded — no backend call, same static data on all pages | REMOVE | Wireframe §14.2; live: `wireframe-update.jsx:68-98` static hardcoded |
| DG-3 | Live Diagnostics has "CLI tools visible but disabled (intentional — Lesson M)" — wireframe §14 does not define CLI tools. Whether this is OUT or a Lesson M preserved planned-state element needs verification | QUESTION | Live: `(DiagnosticsPage)` "CLI tools disabled/intentional"; wireframe §14.3 only mentions "Additional diagnostic panels (implied)" |

---

### Screen 15 — Setup → Automation (Action Center)
**Wireframe §15** | **Live:** `automation` WIRED, LIVE (Sprint 33, AiBridgePage)

| # | Gap | TAG | Basis |
|---|---|---|---|
| AU-1 | Wireframe §15 defines ActionCenterPage (8-col pending queue + 4 Today summary tiles + 6 action types). Live `automation` slug mounts `AiBridgePage` (AI Bridge authority, Sprint 33) — NOT ActionCenterPage. The `ActionCenterPage` stub (`wireframe-update.jsx:338-419`) has 6 hardcoded queue rows and a no-op Bulk approve button, is NOT in WIRED_PAGES, has no slug | REMOVE | Live: `wireframe-update.jsx:338-419` ActionCenterPage stub; live `automation` = AiBridgePage (Sprint 33); stub NOT in WIRED_PAGES |
| AU-2 | If wireframe's `automation` = ActionCenterPage, then AiBridgePage (current `automation` mount) may be an OUT item; if wireframe's `automation` = AiBridgePage, then the ActionCenterPage should map elsewhere. The two names conflict | QUESTION | Wireframe §15 labels nav path `setup → automation`; live mounts AiBridgePage at `automation`; wireframe-update.jsx stub exists separately |

---

### Screen 16 — Setup → Parser / Learning
**Wireframe §16** | **Live:** `intelligence` WIRED, LIVE (Sprint 34, IntelligencePage)

| # | Gap | TAG | Basis |
|---|---|---|---|
| PA-1 | Wireframe §16 defines SAD/ZC429 Parser with textarea + Parse/Clear buttons + result display fields (MRN · LRN · Clearance date · Agent · Exchange rates · Duty A00 · VAT B00). Live `intelligence` mounts IntelligencePage (invoice-learning authority, Sprint 34). Whether IntelligencePage includes the SAD parser tool or is entirely separate is unconfirmed | BUILD | Wireframe §16; live: `(IntelligencePage)` Sprint 34 — no per-control detail in input 2 |

---

### Screen 17 — Setup → Coverage Matrix
**Wireframe §17** | **Live file:** `wireframe-update.jsx:178-332` (CoverageMapPage, WIRED, LIVE, Sprint 43)

| # | Gap | TAG | Basis |
|---|---|---|---|
| CM-1 | Wireframe §17.1 requires 4 clickable filter tiles + §17.2 search/filter bar + §17.3 5-col table (Module · Feature · Status · API placeholder · Notes) with 40+ rows. Live Sprint 43 reports 0 placeholder (all 46 hardcoded COVERAGE_ROWS removed), data from GET /openapi.json — parity on 5-col structure and filter tile interactivity unconfirmed | BUILD | Wireframe §17; live: `wireframe-update.jsx:178-332` Sprint 43 |

---

### Screen 18 — Shipping Ops (ShippingOpsPage)
**Wireframe §18** | **Live file:** `shipping-ops.jsx` (loaded, routing via `shipments` alias)

| # | Gap | TAG | Basis |
|---|---|---|---|
| SO-1 | Wireframe §18.2 requires SOQueue with 5 KPI tiles + 10-col table. Toolbar buttons all defined as disabled/backend-pending in wireframe. Live `shipping-ops.jsx` loaded (script order entry 13) — no WIRED_PAGES entry for a separate shipping-ops slug; routing is via `shipping → shipments` alias | BUILD | Wireframe §18; live: `shipping-ops.jsx` loaded; no dedicated slug in WIRED_PAGES |
| SO-2 | Wireframe §19 NewShipmentModal — Step 1 fields (AWB/Carrier/Client/Supplier/4 document slots). Modal wired in `modals.jsx` (script entry 4). Parity unconfirmed | BUILD | Wireframe §19; live: `modals.jsx` |

---

### Persistent Shell Issues (all pages)

| # | Gap | TAG | Basis |
|---|---|---|---|
| SH-A | OperationalStatusStrip (`wireframe-update.jsx:68-98`) — fully hardcoded 6 items, never calls backend. Wireframe defines this as live integration status with last-ping timestamps (§14.2, §39 note) | REMOVE | Live-app-inventory §SECTION 3 `wireframe-update.jsx:68-98` |
| SH-B | TopBar notification bell — no `onClick` handler (`components.jsx:346-349`). Wireframe §2.3 inbox item list and §2.4 action buttons define actionable items; a dead bell is inconsistent | REMOVE | Live-app-inventory §TopBar dead controls `components.jsx:346-349` |
| SH-C | TopBar user avatar dropdown — no `onClick` handler (`components.jsx:351-363`). No wireframe definition of a dead dropdown | REMOVE | Live-app-inventory §TopBar dead controls `components.jsx:351-363` |

---

## Section B — Wave Order

Ordered per operator directive (Inventory FIRST) then by gap severity (dead control=3 · placeholder=3 · missing wireframe control w/ live backend=2 · layout delta=1).

| Priority | Page | Est. Scope | Severity Score | Wave-2 Endpoints Consumed | Campaign Slice Owner |
|---|---|---|---|---|---|
| **1** | **Inventory — Sample Out tab (Tab 7)** | **M** | 8 (2×BUILD w/ live BE, no WFIRMA gate) | GET /api/v1/inventory/samples (`routes_inventory_sample.py:149`) | C-3b |
| **2** | **Inventory — Sample Return tab (Tab 8)** | **M** | 8 | GET /api/v1/inventory/samples + return endpoints | C-3b |
| **3** | **Inventory — Client Return tab (Tab 9)** | **M** | 8 | GET /api/v1/inventory/returns (`routes_inventory_returns.py:212`) | C-3a/C-3c |
| **4** | **Inventory — Return to Producer tab (Tab 10)** | **M** | 6 | GET /api/v1/inventory/returns | C-3c |
| **5** | **Inventory — Temp Sale tab (Tab 4)** | **M** | 6 | GET /api/v1/inventory/movements/{batch_id} (`routes_inventory.py:203`) | C-3d (run_stock_issue shipped) |
| **6** | **Inventory — Overview KPI/quick-actions (Tab 1)** | **S** | 5 | GET /api/v1/inventory/stage2/aggregate (LIVE) | C-3e / U-6 |
| **7** | **Inventory — Temp Purchase tab (Tab 2)** | **L** | 4 | packing_lines (existing DB) | C-3e / U-3 |
| **8** | **Inventory — Temp Warehouse tab (Tab 3)** | **M** | 4 | GET /api/v1/inventory/state/{batch_id} (partial cover) | C-3e |
| **9** | **Inventory — Final Stock tab (Tab 6)** | **M** | 4 | GET /api/v1/warehouse/locations + /locations/{code}/inventory (LIVE) | C-3b / U-5 |
| **10** | **Inventory — Consignment tab (Tab 5)** | **S** | 3 (gated) | none (backend absent) | C-4a (OI-1/OI-2/OI-17 gate) |
| **11** | **Inventory — Identity/Mapping tab (Tab 11)** | **S** | 2 | wfirma_setup endpoints (via wfirma_setup page) | C-3b |
| **12** | **Inventory — MoveStockModal stage transition** | **S** | 2 | POST /api/v1/inventory/pieces/{piece_id}/location (W→W LIVE); movements endpoint | C-3d |
| **13** | **Accounting hub** | **L** | 9 (3×REMOVE + 6×BUILD) | proforma endpoints, ledger endpoints, wfirma sync, audit trail | Wave 4 / accounting-hub |
| **14** | **Dashboard** | **M** | 5 (1×REMOVE OperationalStatusStrip + 2×BUILD CTAs/KPIs + kanban labels) | GET /api/v1/dashboard/batches (LIVE) | atlas-v2 / dashboard |
| **15** | **Shipment Detail** | **L** | 7 (7×BUILD sub-tabs) | GET /api/v1/dashboard/batches/{batch_id} (LIVE) | atlas-v2 / shipment-detail |
| **16** | **Pro Forma Detail** | **M** | 5 (5×BUILD tab/button gaps) | proforma endpoints (LIVE) | atlas-v2 / proforma-detail |
| **17** | **Pro Forma List** | **S** | 3 | proforma list + service-products endpoints | atlas-v2 / proforma |
| **18** | **Setup → Settings (admin)** | **M** | 6 (1×REMOVE + 2×BUILD + MOCK) | GET /api/v1/settings/company-profile (exists) | atlas-v2 / admin |
| **19** | **Reports** | **M** | 6 (1×REMOVE + 2×BUILD + MOCK) | no confirmed backend | atlas-v2 / reports |
| **20** | **Documents Hub** | **S** | 4 (1×REMOVE DocViewer + 3×BUILD) | GET /api/v1/dashboard/batches (LIVE) | atlas-v2 / documents |
| **21** | **Setup → Automation (ActionCenter vs AiBridge)** | **S** | 3 (QUESTION: authority conflict) | ai-bridge endpoints (LIVE) | QUESTION — see Section D |
| **22** | **Setup → Carriers** | **S** | 2 | GET /api/v1/carriers-config/ (LIVE) | atlas-v2 / carriers |
| **23** | **Setup → wFirma** | **S** | 2 | /wfirma/capabilities · /customers · /products (LIVE) | atlas-v2 / wfirma |
| **24** | **Setup → API Status** | **S** | 2 | 12 subsystem health endpoints (LIVE) | atlas-v2 / api-status |
| **25** | **Setup → Diagnostics** | **S** | 3 (1×REMOVE OperationalStatusStrip live + 1×QUESTION CLI tools) | health/storage/locks/version (LIVE) | atlas-v2 / diagnostics |
| **26** | **Setup → Parser/Learning** | **S** | 2 | intelligence endpoints (LIVE) | atlas-v2 / intelligence |
| **27** | **Setup → Coverage Matrix** | **S** | 2 | GET /openapi.json (LIVE) | atlas-v2 / coverage |
| **28** | **Setup → Master Data** | **S** | 2 | 10+ entity endpoints (LIVE) | atlas-v2 / master |
| **29** | **Inbox** | **S** | 2 | GET /api/v1/inbox (LIVE) | atlas-v2 / inbox |
| **30** | **Shipments (list)** | **S** | 3 (1×REMOVE MOCK_SHIPMENTS dead code) | GET /api/v1/dashboard/batches (LIVE) | atlas-v2 / shipments |
| **31** | **Shipping Ops** | **M** | 2 | shipping-ops.jsx loaded | atlas-v2 / shipping-ops |

---

## Section C — Explicit DO-NOT-TOUCH List

These items are either OUT (wireframe is silent) or working business logic the directive preserves. Wave-3 work must not modify these.

### OUT items (live feature, wireframe is silent — listed for the record, untouched)
1. **`supplier_invoice_review` page** (`supplier-invoice-review.jsx`, Sprint 2026-07-02) — not in wireframe nav; LIVE business logic; preserve
2. **`proforma_search` page** (`proforma-search.jsx`, Sprint M6-cleanup) — wireframe §4.1 Pro Forma List covers the list; proforma_search is a supplementary live feature; preserve
3. **`dhl` standalone page** (`pages-v2.jsx` + `dhl-*.jsx`, Sprint 31) — wireframe defines DHL/Customs as a sub-tab of Shipment Detail (§3.2 Tab 3), but the live app has it as a separate wired page; resolving this routing conflict is a QUESTION (see Section D)
4. **Accounting → Tab D/E (wFirma Sync / Master Data)** — wireframe defines these as sub-tabs of Accounting, but `wfirma_setup` and `master` are already live as standalone pages; no duplication needed, cross-mount only when Accounting hub is wired
5. **`ledgers-page.jsx`** (loaded in script order, Sprint 38) — loaded but not mounted under accounting; preserves Client Ledger / Supplier Ledger implementation for future Accounting Tab C wiring
6. **`link-as-sales-backfill.jsx`** (script entry 22) — no wireframe definition; operational sales linkage backfill tool; preserve
7. **`ops-cell.jsx`** (script entry 14) — no wireframe definition; infrastructure support component; preserve
8. **`client-detail.jsx`** (script entry 7) — no wireframe definition; client detail authority; preserve
9. **`client-kyc-and-consignment.jsx`** — ConsignmentTab exists here (UNUSED, WFIRMA-GATED); do NOT rebuild; reuse per WIREFRAME_AUTHORITY §D "do NOT build a second one"
10. **`dhl-scan-status.jsx`, `dhl-daily-summary.jsx`** (script entries 27-28) — DHL operational panels; preserve

### Working business logic to preserve (per Wave-3 directive: "Preserve existing business logic unless the wireframe explicitly requires a change")
1. All write buttons on `shipment-detail-page.jsx` are intentionally visible-but-disabled per Lesson M — do NOT remove; wire to domain pages per wireframe flow
2. `MoveStockModal` Tab 1 (W→W) is LIVE with POST /api/v1/inventory/pieces/{piece_id}/location — do NOT replace; only add Tab 2 (Stage transition) wiring
3. `PromotionNotesPanel` (`inventory-page.jsx:717-811`) — no wireframe equivalent found; preserve as OUT
4. `AuditPanel` (`inventory-page.jsx:642-707`) — maps loosely to wireframe audit trail concept; preserve
5. All Sprint 36-43 cleanup (0 placeholder, 0 dead) on carriers/master/api-status/wfirma/coverage/diagnostics — do NOT regress
6. `run_stock_issue()` shared function (C-3d, Wave 2, `ea6e165c`) — calculation authority; UI must call it, never reimplement
7. `global_pz_push.py`, `wfirma_reservation.py`, `wfirma_reservation_create.py` — whitelisted sync-layer; do NOT modify as part of UI work

---

## Section D — Totals and QUESTION Items

### Gap Totals by Tag

| TAG | Count |
|---|---|
| **BUILD** | 67 |
| **REMOVE** | 16 |
| **WFIRMA-GATED** | 5 |
| **OUT** | 10 |
| **QUESTION** | 3 |
| **TOTAL** | 101 |

### Pages by Estimated Scope

| Scope | Pages |
|---|---|
| **S (Small)** | Inventory Overview KPI/actions · Inventory Consignment (gated surface) · Inventory Identity/Mapping · Inventory MoveStockModal stage tab · Pro Forma List · Setup→Settings (scoped) · Setup→Automation (after QUESTION resolved) · Setup→Carriers · Setup→wFirma · Setup→API Status · Setup→Diagnostics · Setup→Parser · Setup→Coverage · Setup→Master Data · Inbox · Shipments list |
| **M (Medium)** | Inventory Sample Out · Inventory Sample Return · Inventory Client Return · Inventory Return to Producer · Inventory Temp Sale · Inventory Temp Warehouse · Inventory Final Stock · Dashboard · Pro Forma Detail · Reports · Documents Hub · Shipping Ops |
| **L (Large)** | Inventory Temp Purchase · Accounting Hub · Shipment Detail |

### QUESTION Items (ambiguities that cannot be resolved from evidence — operator ruling required before building)

**Q-1 — `dhl` page vs. Shipment Detail Tab 3**
Wireframe §3.2 Tab 3 places DHL/Customs operations inside the Shipment Detail page as a sub-tab. Live app has `dhl` as a separate WIRED page (`pages-v2.jsx`, Sprint 31, 0 placeholder, 0 dead). Two valid interpretations: (a) keep `dhl` as a standalone page and map wireframe Tab 3 to a link/redirect into it; (b) move DHL/Customs content into a sub-tab inside shipment-detail-page.jsx. This affects both Shipment Detail page (SD-3/SD-4 gap items) and the `dhl` page (currently OUT). **Operator ruling needed before touching either page.**

**Q-2 — `automation` slug: ActionCenterPage vs. AiBridgePage**
Wireframe §15 defines `setup → automation` as ActionCenterPage (pending queue + action types). Live mounts AiBridgePage at `automation` (Sprint 33, AI Bridge authority). The `ActionCenterPage` stub (`wireframe-update.jsx:338-419`) is a separate unreachable stub. The wireframe may intend both to coexist (different sub-sections), or AiBridgePage may fully replace ActionCenterPage at the `automation` slug. **Operator ruling needed: what should live at `automation`?**

**Q-3 — Diagnostics CLI tools (Lesson M vs. wireframe)**
Live Diagnostics has "CLI tools visible but disabled (intentional — Lesson M)". Wireframe §14 does not define CLI tools. If these are Lesson M planned-state honesty placeholders, they should remain. If they are artifacts of a prior design round not present in the wireframe, they should be removed. Cannot determine from wireframe or open items alone. **Operator ruling: are the Diagnostics CLI tools planned-state (keep) or non-wireframe artifacts (remove)?**

---

*Report generated: 2026-07-03*  
*Input files consumed: 5 (wireframe-inventory · live-app-inventory · WIREFRAME_AUTHORITY · OPEN_ITEMS · DECISIONS last 2 entries)*  
*Total gap items catalogued: 101 (67 BUILD · 16 REMOVE · 5 WFIRMA-GATED · 10 OUT · 3 QUESTION)*

---

## AMENDMENT 2026-07-04 (operator census-precision ruling)

**Governing decision:** DECISIONS.md entry "2026-07-04 — CENSUS AUDIT PRECISION"  
**Three deliverables:** (1) source-tagging pass over every BUILD gap; (2) Inventory PageHeader actions row as new slice W3-page6b; (3) DocumentsHubPage full control-set re-audit.  
**Wire evidence:** pinned wireframe bundle `f7dd5e38` at `docs/design/estrella-dashboard-wireframe.html`.

---

### A-1 — Source-tagging pass over BUILD gaps

Two source tags defined by the operator ruling:

- **WIREFRAME-REQUIRED** — the control is findable in the pinned wireframe file (`docs/design/estrella-dashboard-wireframe.html`); location in the wireframe bundle is cited.
- **OPERATOR-RULED (ENTRY-POINT RULE)** — Create / Upload / Import / New workflow entry-points the operator mandates even where the file shows only an illustration (e.g. "New Shipment" appears only as SVG text at line ~2829 and as a TopBar `<button>` component in bundle `bcbd4293`; email-import / manual-create / scan do not appear at all). Both tags are BUILD gaps; the difference is their source authority.

The table below re-lists every BUILD gap from Section A. WFIRMA-GATED, REMOVE, OUT, and QUESTION items carry no source tag (they are not BUILD). Inventory PageHeader gaps IV-HDR-* are new (added in A-2 below) and appear at the end of this table.

| Gap ID | Screen | Gap summary | SOURCE |
|---|---|---|---|
| D-1 | Dashboard | 5 KPI tiles exact count and labels per §1.1 | WIREFRAME-REQUIRED — App.jsx template line 524 area; bundle `cd6573d9` (Accounting) and inline dashboard section define 5 KPI tiles with labels |
| D-2 | Dashboard | 4 Quick-flow CTA buttons (Receive · Create outbound · Process email · Customer order) per §1.2 | WIREFRAME-REQUIRED — App.jsx template Dashboard actions row (line 524 area); the 4 CTAs appear in the Dashboard `PageHeader` actions in the inline script |
| D-3 | Dashboard | 6 Kanban lane labels — "In Transit" and "Delivered" missing from live | WIREFRAME-REQUIRED — App.jsx template Kanban section §1.3 defines lane labels verbatim; bundle `dashboard` defines color bands |
| D-4 | Dashboard | GlobalSearch modal (⌘K) with overlay, 5 filter chips, keyboard nav | WIREFRAME-REQUIRED — bundle `4951d978` (GlobalSearch / NewShipmentModal); `global-search.jsx` loaded in script order entry 26 |
| I-1 | Inbox | 6 left-rail tabs with count badges per §2.1 | WIREFRAME-REQUIRED — App.jsx template Inbox section §2.1 defines 6 tab labels |
| I-2 | Inbox | Priority filter 4 levels per §2.2 | WIREFRAME-REQUIRED — App.jsx template Inbox §2.2 |
| SH-2 | Shipments | Carrier badge filter chips + search input on toolbar | WIREFRAME-REQUIRED — App.jsx template Shipments toolbar §3.1; `↓ Export CSV` and carrier chips in template line 545 area |
| SD-1 | Shipment Detail | MRN, Packing List mono, Carrier chip, 7 workflow stage pills in header | WIREFRAME-REQUIRED — bundle `f4bf9d9e` (Shipments/DHL page) defines the stage pills and carrier chip; §3.2 header spec |
| SD-2 | Shipment Detail | Contextual write buttons per workflow stage wired to domain pages | WIREFRAME-REQUIRED — App.jsx template §3.2 Tab 1 defines write buttons per stage |
| SD-3 | Shipment Detail | Tab 2 (Pro Forma) — draft list + "+ Create Pro Forma Draft" + draft row columns | WIREFRAME-REQUIRED — App.jsx template §3.2 Tab 2 |
| SD-4 | Shipment Detail | Tab 3 (DHL/Customs) — 6 buttons Step 1 + 4 buttons Step 2 | WIREFRAME-REQUIRED — bundle `f4bf9d9e` DisBtn controls (Step 1: `+ New shipment`, `Bulk dispatch`, `Pickup request`, `Generate manifest`, `Scan barcode`, `Preview`; Step 2: SAD buttons) |
| SD-5 | Shipment Detail | Tab 4 (PZ/Accounting) — 7-button set per §3.2 Tab 4 | WIREFRAME-REQUIRED — App.jsx template §3.2 Tab 4 button list |
| SD-6 | Shipment Detail | Tab 5 (Documents) — 4 doc cards with state chips + View + Download | WIREFRAME-REQUIRED — App.jsx template §3.2 Tab 5; bundle `7289f2fd` document viewer has `↓ Download` and `👁 View` |
| SD-7 | Shipment Detail | Tab 6 (Timeline) — 16 named events | WIREFRAME-REQUIRED — App.jsx template §3.2 Tab 6 event list |
| PL-1 | Proforma List | 5 pipeline KPI tiles per §4.1 | WIREFRAME-REQUIRED — App.jsx template Proforma section §4.1 |
| PL-2 | Proforma List | 8-column table + checkbox + Match chip | WIREFRAME-REQUIRED — App.jsx template §4.1 table definition |
| PL-3 | Proforma List | NewProformaDraftModal — 4 source buttons + info banner | WIREFRAME-REQUIRED — bundle `2b497d3e` (Proforma); modal with `+ New Proforma` button at Proforma list toolbar |
| PL-4 | Proforma List | ImportPackingListModal — 4-step wizard | WIREFRAME-REQUIRED — App.jsx template §4.3 import packing list wizard; `⬆ Upload packing list` ApiBtn in bundle `99c0e873` |
| PL-5 | Proforma List | `getServiceProducts` API called from V2 proforma UI | WIREFRAME-REQUIRED — App.jsx template §4 Pro Forma line-item editor implies service products; `pz-api.js:134` endpoint live |
| PD-2 | Proforma Detail | 16-column line-item table exact order | WIREFRAME-REQUIRED — App.jsx template §4.4 Tab 2 exact 16-col spec |
| PD-3 | Proforma Detail | Matching tab — auto/partial/manual match state per line | WIREFRAME-REQUIRED — App.jsx template §4.4 Tab 4 matching spec |
| PD-4 | Proforma Detail | Push-to-wFirma tab — 2 tables (Ready queue + Export log) | WIREFRAME-REQUIRED — App.jsx template §4.4 Tab 5 |
| PD-5 | Proforma Detail | Audit Trail tab — events table | WIREFRAME-REQUIRED — App.jsx template §4.4 Tab 6 |
| DC-1 | Documents Hub | 3 tabs PI / PZ / Other with lane counts | WIREFRAME-REQUIRED — bundle `99c0e873` `DOC_KIND` + `LANE_DEF`; tab labels `PI`, `PZ`, `other` in `useState('PI')` |
| DC-2 | Documents Hub | Draft → Approved → Posted lane workflow | WIREFRAME-REQUIRED — bundle `99c0e873` `LANE_DEF` 3 entries; `LaneCard` per-lane button sets |
| DC-3 | Documents Hub | Upload packing list + New Proforma / New Purchase Receipt toolbar buttons per tab | WIREFRAME-REQUIRED — bundle `99c0e873`: `<ApiBtn label="⬆ Upload packing list" ...>` + `<ApiBtn label={\`+ New ${DOC_KIND[tab].label}\`} ...>` in toolbar |
| AC-3 | Accounting | Tab A (PZ/Purchase Ledger) — table + KPIs | WIREFRAME-REQUIRED — App.jsx template §6 Tab A; `↓ Export` at template line 576 |
| AC-4 | Accounting | Tab B (Sales/Proforma) — KPIs + 3 sub-tabs | WIREFRAME-REQUIRED — App.jsx template §6 Tab B |
| AC-5 | Accounting | Tab C (Ledgers/Statements) — ClientLedgerView + 10-col table | WIREFRAME-REQUIRED — App.jsx template §6 Tab C; `ledgers-page.jsx` loaded |
| AC-8 | Accounting | Tab F (Audit Trail) — 4-col table + search/filter | WIREFRAME-REQUIRED — App.jsx template §6 Tab F |
| IV-O-1 | Inventory | 5 KPI tiles (Stock units · Pieces on hand · Reserved · Available · Total value) | WIREFRAME-REQUIRED — bundle `7289f2fd` (Inventory page) 5-tile KPI row |
| IV-O-2 | Inventory | Stage 1 + Stage 2 summary cards | WIREFRAME-REQUIRED — bundle `7289f2fd` Stage summary section |
| IV-O-3 | Inventory | 4 quick-action buttons (Upload Packing List · New Consignment · Issue Sample · Move Stock) | WIREFRAME-REQUIRED (Upload Packing List + Move Stock) · OPERATOR-RULED ENTRY-POINT RULE (New Consignment · Issue Sample — workflow entry points per operator mandate; not standalone buttons in the pinned file's quick-action grid; the grid in bundle `7289f2fd` has Upload Document and fire('inv:move') but not New Consignment or Issue Sample as separate grid cards) |
| IV-TP-1 | Inventory | Entire Temp Purchase tab (4 KPI tiles + stage banner + 13-col table + 3 toolbar buttons) | WIREFRAME-REQUIRED — bundle `7289f2fd` Temp Purchase tab definition |
| IV-TW-1 | Inventory | Entire Temp Warehouse tab (4 KPI tiles + stage banner + 8-col table with delta col) | WIREFRAME-REQUIRED — bundle `7289f2fd` Temp Warehouse tab |
| IV-TS-1 | Inventory | Entire Temp Sale tab (4 KPI tiles + LOCKED gate banner + 8-col table + row actions) | WIREFRAME-REQUIRED — bundle `7289f2fd` Temp Sale tab; lock banner defined in wireframe |
| IV-FS-1 | Inventory | Final Stock tab — 5 KPI tiles + stage banner + 10-col verified-stock table + filter + Move Stock button | WIREFRAME-REQUIRED — bundle `7289f2fd` Final Stock tab; `↑ Upload Document` header button context |
| IV-FS-2 | Inventory | Final Stock tab exact 12-column set | WIREFRAME-REQUIRED — bundle `7289f2fd` Final Stock col spec |
| IV-SO-1 | Inventory | Sample Out tab — real backend wiring replacing stub | WIREFRAME-REQUIRED — bundle `7289f2fd` Sample Out tab; `+ Issue Sample` button |
| IV-SO-2 | Inventory | Sample Out — 4 KPI tiles | WIREFRAME-REQUIRED — bundle `7289f2fd` Sample Out KPI block |
| IV-SO-3 | Inventory | Sample Out — 10-col table + row actions | WIREFRAME-REQUIRED — bundle `7289f2fd` Sample Out table |
| IV-SO-4 | Inventory | "+ Issue Sample" toolbar button | WIREFRAME-REQUIRED — bundle `7289f2fd` toolbar; OPERATOR-RULED ENTRY-POINT RULE (also mandated as a workflow entry point for the Sample Out workflow) |
| IV-SR-1 | Inventory | Sample Return tab — real backend wiring | WIREFRAME-REQUIRED — bundle `7289f2fd` Sample Return tab |
| IV-SR-2 | Inventory | Sample Return — 4 KPI tiles + 10-col table + row actions | WIREFRAME-REQUIRED — bundle `7289f2fd` Sample Return spec |
| IV-CR-1 | Inventory | Client Return tab — real backend wiring | WIREFRAME-REQUIRED — bundle `7289f2fd` Client Return tab |
| IV-CR-2 | Inventory | Client Return — KPIs + 10-col RMA table + reason values + row actions | WIREFRAME-REQUIRED — bundle `7289f2fd` Client Return spec |
| IV-RTP-1 | Inventory | Return to Producer tab — backend wiring | WIREFRAME-REQUIRED — bundle `7289f2fd` Return to Producer tab |
| IV-RTP-2 | Inventory | Return to Producer — 4 KPI tiles + 10-col table + row actions | WIREFRAME-REQUIRED — bundle `7289f2fd` Return to Producer spec |
| IV-ID-1 | Inventory | Identity/Mapping tab — 8-field table, internal stock identity | WIREFRAME-REQUIRED — bundle `7289f2fd` Identity/Mapping tab; internal stock_unit_id / trace_barcode identity model |
| IV-MS-1 | Inventory | MoveStockModal Tab 2 (Stage transition) wiring | WIREFRAME-REQUIRED — App.jsx template MoveStockModal with Move-type toggle; Stage transition tab defined |
| RP-2 | Reports | 4 KPI tiles + Duty Summary Table 6 cols | WIREFRAME-REQUIRED — App.jsx template §8 reports page; `↓ Export PDF` / `↓ Export CSV` buttons at line 752 area |
| ADM-2 | Settings | 3 cards (API Config + Users & Roles + System Status) | WIREFRAME-REQUIRED — App.jsx template §9 AdminSettingsPage 3-card layout |
| MD-1 | Master Data | 5 sub-sections with exact column sets per §10 | WIREFRAME-REQUIRED — App.jsx template §10 master-data sub-sections; bundle `2e34543e` (Admin master-data) toolbar with `↑ Import CSV` / `↓ Export CSV` / `+ New {entity}` |
| CA-1 | Carriers | 4 KPI tiles + 6 tabs + CarrierCard 3 actions | WIREFRAME-REQUIRED — App.jsx template §11 carriers section |
| WF-1 | wFirma | Capability strip 6 pills + blocking reasons banner | WIREFRAME-REQUIRED — App.jsx template §12 wFirma section |
| WF-2 | wFirma | Customers table 6 cols + Products table 7 cols | WIREFRAME-REQUIRED — App.jsx template §12 table column specs |
| AS-1 | API Status | 4 KPI tiles + 4 tabs | WIREFRAME-REQUIRED — App.jsx template §13 |
| DG-1 | Diagnostics | 4 KPI tiles | WIREFRAME-REQUIRED — App.jsx template §14 |
| CM-1 | Coverage Matrix | 4 clickable filter tiles + search/filter bar + 5-col table 40+ rows | WIREFRAME-REQUIRED — App.jsx template §17 |
| PA-1 | Parser/Learning | SAD/ZC429 Parser textarea + Parse/Clear + result fields | WIREFRAME-REQUIRED — App.jsx template §16 |
| SO-1 | Shipping Ops | SOQueue 5 KPI tiles + 10-col table | WIREFRAME-REQUIRED — App.jsx template §18 |
| SO-2 | Shipping Ops | NewShipmentModal Step 1 fields (AWB/Carrier/Client/Supplier/4 doc slots) | WIREFRAME-REQUIRED — bundle `4951d978` NewShipmentModal form fields; App.jsx template §19 |
| IV-HDR-1 | Inventory | "Cycle count" header button | WIREFRAME-REQUIRED — wireframe App.jsx template line 590 (`<Btn variant="outline" small>Cycle count</Btn>`) in Inventory `PageHeader` actions; also bundle `7289f2fd` inline row |
| IV-HDR-2 | Inventory | "↑ Upload Document" header button | WIREFRAME-REQUIRED — wireframe App.jsx template line 588 `<Btn ... onClick={() => window.dispatchEvent(new CustomEvent('inv:upload'))}>↑ Upload Document</Btn>` in Inventory PageHeader |
| IV-HDR-3 | Inventory | "↓ Export" header button | WIREFRAME-REQUIRED — wireframe App.jsx template line 591 `<Btn variant="outline" small>↓ Export</Btn>` in Inventory PageHeader actions row alongside Upload Document and Cycle count |

**Source-tag counts (BUILD gaps only):**  
WIREFRAME-REQUIRED: **68** (includes 3 new IV-HDR-* gaps added in A-2)  
OPERATOR-RULED (ENTRY-POINT RULE): **2** (IV-O-3 partial: New Consignment + Issue Sample; IV-SO-4 partial: Issue Sample mandate)  
*(Note: IV-O-3 carries a split tag — Upload Packing List and Move Stock are WIREFRAME-REQUIRED; New Consignment and Issue Sample are OPERATOR-RULED. IV-SO-4 is primarily WIREFRAME-REQUIRED with OPERATOR-RULED reinforcement.)*

---

### A-2 — Inventory PageHeader Actions Row (new BUILD gaps, slice W3-page6b)

**Screen:** Inventory (Screen 7)  
**Live file:** `inventory-page.jsx`  
**Census authority:** operator ruling 2026-07-04 ("CONFIRMED missing controls: the Inventory PageHeader actions row — '↑ Upload Document' (inv:upload), 'Cycle count', header '↓ Export'")

The live file (`inventory-page.jsx`) as of the census date had the following state on these three controls:

**Live status at census date (pre-amendment):**
- `↑ Upload Document` (page-6 card): fires `window.dispatchEvent(new CustomEvent('inv:upload'))` at `inventory-page.jsx:3567`. Zero `addEventListener` hits in the file — the event is dispatched but nothing listens to it. This is the dangling "no listener" gap the operator confirmed.
- `Cycle count`: absent from inventory-page.jsx entirely (zero occurrences of the string at census date).
- `↓ Export` (header level): absent from the header; only one disabled `↓ Export valuation` button exists at line 3956 (consignment notes panel — a different context).

**Note:** The operator ruling confirms these as BUILD gaps. The census amendment records them as of 2026-07-03 gap state. Subsequent work on `inventory-page.jsx` (sprint W3-page6b) has since implemented these controls; see `inventory-page.jsx:4500–4575` for the implementation — the amendment rows below record the gap as it existed at census time.

| # | Gap | TAG | SOURCE | Wireframe cite | Live cite |
|---|---|---|---|---|---|
| IV-HDR-1 | "Cycle count" header button absent from live inventory page; no backend owner (net-new capability per WIREFRAME_AUTHORITY §D) | BUILD | WIREFRAME-REQUIRED | App.jsx template line 590: `<Btn variant="outline" small>Cycle count</Btn>` in Inventory PageHeader actions row; also bundle `7289f2fd` inline row: `<Btn small variant="outline">Cycle count</Btn>` | `inventory-page.jsx`: zero occurrences at census date; absent entirely from header |
| IV-HDR-2 | "↑ Upload Document" header button dispatches `inv:upload` CustomEvent but zero `addEventListener` in `inventory-page.jsx` — event fires into void; header-level button effectively dead | BUILD | WIREFRAME-REQUIRED | App.jsx template line 588: `<Btn ... onClick={() => window.dispatchEvent(new CustomEvent('inv:upload'))}>↑ Upload Document</Btn>` in Inventory PageHeader | `inventory-page.jsx:3567`: `onClick={() => window.dispatchEvent(new CustomEvent('inv:upload'))}` — fires; `inventory-page.jsx`: zero `addEventListener` hits (confirmed by search) |
| IV-HDR-3 | "↓ Export" header button absent from inventory page header; only a disabled consignment-panel export exists at line 3956 — not the header-level export control | BUILD | WIREFRAME-REQUIRED | App.jsx template line 591: `<Btn variant="outline" small>↓ Export</Btn>` in Inventory PageHeader actions row (third button, after Upload Document and Cycle count) | `inventory-page.jsx:3956`: `↓ Export valuation` (consignment panel, disabled — different control, different context); no header-level `↓ Export` button |

**Slice assignment:** W3-page6b (Inventory PageHeader actions row)  
**Lesson-M note:** "Cycle count" (IV-HDR-1) has no backend owner — it must be rendered as a planned-state honest disabled control with a descriptive title until a backend slice ships. The other two (IV-HDR-2, IV-HDR-3) have existing backend surfaces and must be live controls.

---

### A-3 — DocumentsHubPage Full Control-Set Re-audit

**Screen:** Documents Hub (Screen 5)  
**Wireframe:** bundle `99c0e873` in `docs/design/estrella-dashboard-wireframe.html`; page comment "Documents Hub — full CRUD for every document type"; PageHeader subtitle: "Full create / edit / delete / view / download."  
**Live file:** `service/app/static/v2/documents-hub.jsx` (227 lines, read-only observer)

#### Wireframe control inventory (complete enumeration)

**PageHeader toolbar:**

| Control | Wireframe element | Endpoint stub |
|---|---|---|
| `⬇ Export CSV` | `<Btn variant="outline" small disabled style={{ opacity: 0.7, cursor: 'not-allowed' }}>⬇ Export CSV</Btn>` — disabled in wireframe | N/A (disabled) |
| `⬆ Upload packing list` | `<ApiBtn label="⬆ Upload packing list" endpoint="POST /api/v1/{pi\|pz}/upload-packing-list" ...>` — per-tab toolbar (PI and PZ tabs only) | `POST /api/v1/{pi\|pz}/upload-packing-list` |
| `+ New Proforma` / `+ New Purchase Receipt` | `<ApiBtn label={\`+ New ${DOC_KIND[tab].label}\`} endpoint={\`POST /api/v1/${tab.toLowerCase()}\`} variant="gold" ...>` — dynamic label per active tab | `POST /api/v1/pi` or `POST /api/v1/pz` |

**3-lane Kanban (Draft / Approved / Posted to wFirma) — per PI and PZ tabs:**

| Lane | Controls on each card | Endpoint stubs |
|---|---|---|
| **Draft** | Edit, Approve (gold), Delete 🗑 (danger) | `PATCH .../id`, `POST .../id/approve`, `DELETE .../id` |
| **Approved** | Post to wFirma (gold), Unapprove | `POST .../id/post-to-wfirma`, `POST .../id/unapprove` |
| **Posted** | View 👁, Download ↓ (read-only) | `GET .../id/view`, `GET .../id/download` |

**Other Documents tab (read-only history — Invoice, Order, SAD, CI, CN23, AWB Label, Email PDF):**

| Control | Location | Endpoint stub |
|---|---|---|
| View 👁 | Per-row action | `GET /api/v1/documents/{num}/view` (implied) |
| Download ↓ | Per-row action | `GET /api/v1/documents/{num}/download` |

**CreateModal (shown for Upload packing list and New {type} flows):**

| Control | Mode | Endpoint stub |
|---|---|---|
| Drop-zone + "Parse & create draft" (gold) | `upload` mode | `POST /api/v1/{kind}/upload-packing-list` |
| Form fields + "Create draft" (gold) | `manual` mode | `POST /api/v1/{kind}` |

**Complete wireframe control list (13 distinct controls across hub):**

1. `⬇ Export CSV` (header, disabled)
2. `⬆ Upload packing list` (toolbar, PI+PZ tabs)
3. `+ New Proforma` / `+ New Purchase Receipt` (toolbar, gold, PI+PZ tabs)
4. **Edit** (draft lane, `PATCH`)
5. **Approve** (draft lane, gold, `POST .../approve`)
6. **Delete 🗑** (draft lane, danger, `DELETE`)
7. **Post to wFirma** (approved lane, gold, `POST .../post-to-wfirma`)
8. **Unapprove** (approved lane, `POST .../unapprove`)
9. **View 👁** (posted lane + Other docs tab, `GET .../view`)
10. **Download ↓** (posted lane + Other docs tab, `GET .../download`)
11. **Parse & create draft** (upload modal, gold)
12. **Create draft** (manual modal, gold)
13. **Modal close / cancel** (both modal modes)

#### Live file delta

`service/app/static/v2/documents-hub.jsx` (227 lines) is a **read-only observer page**. Its own comment at line 13 states: `"// This page is READ-ONLY. It never calls a POST, PUT, PATCH, or DELETE endpoint."` It has exactly one `onClick` handler: `onClick={load}` on the `↻ Reload` button.

| Wireframe control | Live status | Gap tag | Source tag |
|---|---|---|---|
| `⬇ Export CSV` (disabled, header) | ABSENT — no Export CSV button in `documents-hub.jsx` | BUILD | WIREFRAME-REQUIRED — App.jsx template line 666 (`<Btn variant="outline" small disabled>⬇ Export CSV</Btn>`) |
| `⬆ Upload packing list` (toolbar) | ABSENT — no upload trigger in `documents-hub.jsx` | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` ApiBtn `label="⬆ Upload packing list"` |
| `+ New Proforma` / `+ New Purchase Receipt` (toolbar, gold) | ABSENT — no create trigger | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` dynamic `label=\`+ New ${DOC_KIND[tab].label}\`` |
| Edit (draft lane) | ABSENT — no edit action | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` LaneCard draft: `<ApiBtn label="Edit" endpoint="PATCH ...">` |
| Approve (draft lane, gold) | ABSENT | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` LaneCard draft: `<ApiBtn label="✓ Approve" endpoint="POST .../approve">` |
| Delete 🗑 (draft lane, danger) | ABSENT | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` LaneCard draft: `<ApiBtn label="🗑" endpoint="DELETE ...">` |
| Post to wFirma (approved lane, gold) | ABSENT | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` LaneCard approved: `<ApiBtn label="↻ Post to wFirma" endpoint="POST .../post-to-wfirma">` |
| Unapprove (approved lane) | ABSENT | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` LaneCard approved: `<ApiBtn label="↶ Unapprove" endpoint="POST .../unapprove">` |
| View 👁 (posted lane) | ABSENT in `documents-hub.jsx`; `View Documents` href links exist per row (static `<a href>`) — not a View modal/viewer action | BUILD (partial — href exists but not a real view action) | WIREFRAME-REQUIRED — bundle `99c0e873` LaneCard posted: `<ApiBtn label="👁 View" endpoint="GET .../view">` |
| Download ↓ (posted lane) | ABSENT | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` LaneCard posted: `<ApiBtn label="↓ Download" endpoint="GET .../download">` |
| Parse & create draft (upload modal) | ABSENT — no CreateModal, no upload modal | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` CreateModal upload mode: `<ApiBtn label="Parse & create draft" ...>` |
| Create draft (manual modal) | ABSENT | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` CreateModal manual mode |
| Modal cancel | ABSENT | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` modal close control |

**Delta summary:** 13 wireframe controls — 0 implemented in live `documents-hub.jsx`. The live file provides only a read-only batch/document list with a Reload button and static `View Documents` links. The 3-lane Kanban architecture, all CRUD actions, the upload/create workflow, and all per-document lane actions are entirely absent.

**Existing census rows updated by this re-audit:**

- DC-1, DC-2, DC-3 are confirmed WIREFRAME-REQUIRED (sources cited above).
- DC-4 (DocumentViewerPage hardcoded fallback metadata) remains REMOVE — unaffected by this re-audit.

**New gap rows added by this re-audit (Documents Hub, slice W3-docs-crud):**

| # | Gap | TAG | SOURCE |
|---|---|---|---|
| DC-5 | Edit button absent on Draft-lane cards | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` LaneCard draft |
| DC-6 | Approve button absent on Draft-lane cards | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` LaneCard draft |
| DC-7 | Delete button absent on Draft-lane cards | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` LaneCard draft |
| DC-8 | Post to wFirma button absent on Approved-lane cards | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` LaneCard approved |
| DC-9 | Unapprove button absent on Approved-lane cards | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` LaneCard approved |
| DC-10 | View action absent on Posted-lane cards (static href ≠ real view action) | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` LaneCard posted |
| DC-11 | Download button absent on Posted-lane cards | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` LaneCard posted |
| DC-12 | Upload packing list toolbar button absent | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` toolbar |
| DC-13 | New Proforma / New Purchase Receipt toolbar button absent | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` toolbar (dynamic label) |
| DC-14 | CreateModal (upload + manual modes) absent — no upload drop-zone or manual draft creation flow | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` CreateModal |
| DC-15 | Other Documents tab View + Download row actions absent | BUILD | WIREFRAME-REQUIRED — bundle `99c0e873` OtherDocsList per-row ApiBtn |
| DC-16 | Export CSV disabled header button absent (even as a correctly disabled control) | BUILD | WIREFRAME-REQUIRED — App.jsx template line 666 |

---

### Amendment totals (net change)

| Change | Count |
|---|---|
| BUILD gaps source-tagged WIREFRAME-REQUIRED | 68 (includes 3 new IV-HDR-* + 13 net-new DC-5 through DC-16 + original 67 re-tagged; original 67 BUILD all re-classified as WIREFRAME-REQUIRED or OPERATOR-RULED) |
| OPERATOR-RULED (ENTRY-POINT RULE) gaps | 2 (partial entries in IV-O-3 and IV-SO-4) |
| New BUILD rows added (W3-page6b: IV-HDR-1/2/3) | 3 |
| New BUILD rows added (DocumentsHub DC-5 through DC-16) | 12 |
| Prior census total | 101 |
| Revised total (101 + 3 IV-HDR + 12 DC new rows) | **116** |

*Amendment produced: 2026-07-04*  
*Governing decision: DECISIONS.md "2026-07-04 — CENSUS AUDIT PRECISION"*  
*Evidence consumed: pinned wireframe `docs/design/estrella-dashboard-wireframe.html` (bundles `99c0e873`, `7289f2fd`, `f4bf9d9e`, `4951d978`, `bcbd4293`, `2b497d3e`, `cd6573d9`, `2e34543e`; inline App.jsx template) + `service/app/static/v2/inventory-page.jsx` + `service/app/static/v2/documents-hub.jsx`*
