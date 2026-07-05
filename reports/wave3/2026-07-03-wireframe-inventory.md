# Wireframe Inventory — Wave-3 Gap Census
**Source:** `docs/design/estrella-dashboard-wireframe.html` (1,667,367 bytes, sha256 f7dd5e3889…)
**Produced:** 2026-07-03
**Purpose:** Exhaustive control-level inventory of every screen, table, button, modal, filter, badge, and data-source signal in the canonical wireframe. The gap census compares this document against the live app.

---

## Navigation skeleton

```
NAV_TREE
├── Dashboard       (id: dashboard)
├── Inbox           (id: inbox)      badge: NEW
├── Shipments       (id: shipments)
├── Pro Forma       (id: proforma)
├── Documents       (id: documents)
├── Accounting      (id: accounting) badge: NEW
├── Inventory       (id: inventory)
├── Reports         (id: reports)
└── Setup ▸         (id: g_setup, default: admin)
    ├── Settings    (id: admin)
    ├── Master Data (id: master)
    ├── Carriers    (id: carriers)
    ├── wFirma      (id: wfirma_setup)
    ├── API Status  (id: api_status)
    ├── Diagnostics (id: diagnostics)
    ├── Automation  (id: automation)
    ├── Parser / Learning (id: intelligence)
    └── Coverage Matrix   (id: coverage)
```

**Route redirects (legacy → consolidated):**
- actions / proposals / email_queue / reservation → inbox
- dhl / shipping → shipments
- move_stock / scanner / identity / sample_out / sample_return / goods_return / return_prod → inventory

**FeatureStatus chip vocabulary:** active · partial · backend · future · readonly · approval

**Persistent OperationalStatusStrip** (top banner, all pages):
wFirma · DHL Inbox · Email Queue · Cliq Webhook · Cowork Bridge · WorkDrive

---

## 1. Dashboard

**Nav path:** dashboard | **Layout regions:** 3 (KPI strip, Quick-flow CTAs, Kanban board)

### 1.1 KPI strip (5 tiles)
Active shipments · Urgent · Inbound · Outbound · Total value

### 1.2 Quick-flow CTAs (4 buttons)
- Receive shipment (IN)
- Create outbound shipment (OUT)
- Process new email
- Customer order

### 1.3 Kanban board — 6 lanes (LANES)
| Lane | Color band | Hint |
|---|---|---|
| New / Drafting | neutral | no PI yet |
| Awaiting Documents | amber | PI · INV · PZ pending |
| Customs Clearance | blue | DHL email → ZC429 |
| Ready to Ship | green | PZ confirmed |
| In Transit | blue | carrier tracking live |
| Delivered | green | WZ issued |

Each lane contains shipment cards. Cards show AWB, carrier, status badge, duty value, age.

### 1.4 Global Search (modal, keyboard shortcut ⌘K / Ctrl+K)
- Overlay: position fixed, closes on backdrop click or Esc
- Input: placeholder "Search AWB, PI, INV, batch, client, SKU…"
- Filter chips: All · AWBs · Invoices · Clients · Inventory (SEARCH_FILTERS)
- Results list: label + sub-label, keyboard arrow navigation, Enter to navigate
- SEARCH_INDEX: AWBs, PI numbers, INV numbers, client names, SKUs

---

## 2. Inbox

**Nav path:** inbox | **Layout regions:** 3 (left rail tabs, item list, detail pane)

### 2.1 Left-rail tab strip (INBOX_TABS — 6 tabs with count badges)
| id | Label | Icon | Types |
|---|---|---|---|
| all | All | ✉ | null (all) |
| emails | Emails | ✉ | email |
| proposals | Proposals | ✦ | proposal |
| approvals | Approvals | ◉ | approval |
| reservations | Reservations | ⊕ | reservation |
| customs | Customs | ◐ | customs |

### 2.2 Priority filter (secondary left-rail section)
All priorities · Urgent (red) · High (amber) · Normal (blue) · Info (neutral)

### 2.3 Inbox item list
Each row: icon, type badge, title, sub-line, priority color dot, age, linked AWB/PI chip

### 2.4 Item detail pane (right panel)
Shows selected item: header (title, type badge, priority, age), body (structured content per type), action buttons per type.

**Action buttons by type:**
- email: Reply, Archive, Link to Shipment, Create Proposal
- proposal: Approve, Reject, View Detail
- approval: Approve, Reject, Delegate
- reservation: Confirm, Decline, Hold
- customs: Upload SAD, View Shipment, Generate Reply

---

## 3. Shipments

**Nav path:** shipments | **Layout regions:** 2 (filter toolbar, shipment table) + detail slide-in

### 3.1 Shipment list (FilteredShipmentsTable)
**Columns (7):** AWB / Tracking · Carrier · Overall Status · Net Value · Gross Value · Duty A00 · Actions

**Toolbar / filter controls:**
- Carrier badge filter (DHL / FedEx / neutral chips)
- Search input (implied by component)
- View button per row → opens shipment detail

### 3.2 Shipment detail page (ShipmentDetailPage)
**Layout:** header card + 6-tab subnav

**Header card fields:** AWB, Carrier chip, Overall status badge, MRN (mono), Packing List (mono), Net, Gross, Duty, Workflow stage pills (7 stages)

**Workflow stages (WORKFLOW_STAGES):**
1. Intake · 2. Pre-check · 3. DHL Reply · 4. SAD / ZC429 · 5. Verified · 6. PZ Generated · 7. wFirma Booked

**6 Tabs (SHIPMENT_TABS):**

#### Tab 1 — Overview
Regions: left column (customs values grid, general info), right column (status summary)
- InfoRows: Total Invoice CIF, FOB Value, Freight, Insurance, Net, Gross, Duty A00, Exchange Rate, MRN, Clearance Date, Customs Agent, SAD Status, PZ Status, wFirma Export, Workflow Stage
- Buttons: (contextual per stage)

#### Tab 2 — Pro Forma
- Lists pro forma drafts linked to this shipment
- Empty state: "No pro forma drafts" + "+ Create Pro Forma Draft" button
- Draft row: Draft number (mono), status badge, Customer, Items, Total EUR; action → open draft
- Button: + Create Pro Forma Draft

#### Tab 3 — DHL / Customs (DhlTab)
**Step 1 — DHL Clearance panel**
- Left grid: Total Invoice CIF, FOB Value, Freight, Insurance, DHL Threshold, DSK Recommendation
- Right grid: DHL Email status, Polish Description status, DSK PDF status, Reply Package status, Reply Sent date
- Buttons (6): ⌕ Scan DHL Inbox · ✓ Mark Email Received · ⊞ Generate Polish Desc. · ⊟ Generate DSK · ⊡ Build Reply Package · ↗ Send Reply to DHL (gold, gated on dhlEmailReceived)

**Step 2 — SAD / ZC429 panel**
- Left grid: SAD/ZC429 Status, MRN, LRN, Clearance Date, Customs Agent
- Right grid: SAD Exchange Rate, NBP Accounting Rate, A00 Duty, B00 VAT, Art.33a / Import
- Verification checks (4, shown when uploaded): Invoice reference · CIF / customs value · Importer/exporter · Quantity
- Buttons: ↑ Upload SAD / ZC429 · ✎ Edit · Verify & Lock (gold) · ↓ Download SAD

#### Tab 4 — PZ / Accounting (PzTab)
- Locked state (no SAD): full-page lock message with navigation hint to DHL/Customs tab
- Unlocked state:
  - Left grid: PZ Status, PZ Number, Net Value, Gross Value, Duty A00
  - Right grid: wFirma Status, Export Date, External Doc ID
  - Inline confirm-PZ-number form (conditional): text input + Confirm + Cancel buttons
  - Buttons (conditional): ▶ Run PZ (gold) · ↺ Regenerate PZ · ✎ Confirm PZ Number · ↓ Download XLSX · ↓ Download PDF · ↗ Export to wFirma (gold) · ✓ Mark Exported
  - wFirma exported panel: External Doc ID display

#### Tab 5 — Documents (DocumentsTab)
**Documents grid (2-column, 4 cards):**
| Code | Name | States |
|---|---|---|
| PL | Packing List | source |
| PF | Pro Forma Invoice | draft → generated |
| CMR | CMR | pending → generated |
| WF | wFirma Printout | pending → attached |

State chips: Source · Draft · Generated · Attached · Pending
Per-card buttons: 👁 View (disabled if pending) · ↓ Download (disabled if pending)

#### Tab 6 — Timeline (TimelineTab)
- Chronological event list with green/grey dots
- 16 events (TIMELINE_EVENTS): Shipment created · Invoice uploaded · AWB uploaded · DHL pre-check completed · DHL email received · Polish description generated · DSK generated · Reply package prepared · Reply sent to DHL · SAD/ZC429 uploaded · Customs values parsed · Verification checks passed · PZ unlocked · PZ generated · PZ number confirmed · Exported to wFirma
- Each event: label + date (if done) or "Pending" (if not done)

### 3.3 Shipment status badge vocabulary (STATUS_MAP)
Draft · In Transit · Pre-check Pending · Pre-check Completed · Awaiting DHL Email · DHL Email Received · Reply Package Prepared · Reply Sent · SAD Pending · SAD Uploaded · Customs Parsed · Verification Needed · Customs Verified · Locked · Ready for PZ · Processing · Generated · Ready for Booking · Exported · Awaiting DHL · Awaiting SAD · Action Required · In Preparation · Live · Pending

---

## 4. Pro Forma

**Nav path:** proforma | **Layout regions:** 2 (list page / detail page)

### 4.1 Pro Forma List Page (ProformaListPage)

**Pipeline KPI tiles (5):**
Extracting · Operator Review · Ready · Pushed · Error

**Toolbar:**
- Search input (placeholder: "Search proformas…")
- Filter button
- + New Draft (→ NewProformaDraftModal)

**Table columns (8):**
(checkbox) · Draft No. · Customer · Shipment · Items · Total · Match · Status

**Match chip vocabulary:** auto · partial · manual
**Status badge vocabulary:** draft · extracting · operator_review · ready · pushed · error

### 4.2 New Pro Forma Draft Modal (NewProformaDraftModal)
**Trigger:** + New Draft button on list page
**Header:** "Choose source"
**4 source option buttons:**
- 📄 From Packing List — "Upload Excel/PDF · auto-extract & match (recommended)"
- 📦 From Shipment — "Pull logistics from an existing shipment"
- ✎ Manual Entry — "Build line items by hand — no auto-match"
- ⎘ Clone Existing — "Copy an existing draft"

**Info banner:** "Packing List import is the recommended source…"
**Close button:** × (top right)

### 4.3 Import Packing List Modal (ImportPackingListModal)
**Trigger:** "From Packing List" source option
**4-step wizard:**
1. Upload — file drop zone
2. Extraction — progress / AI parsing
3. Mapping — field alignment
4. Create draft — confirmation

### 4.4 Pro Forma Detail Page (ProformaDetailPage)
**Layout:** header (draft number, status badge, Edit / Save / Cancel buttons) + 6-tab subnav

**Header action buttons:** Edit · Save (shown while editing) · Cancel (shown while editing) · Push to wFirma (gold, gated) · ↓ Download PDF

#### Tab 1 — Overview (OverviewTab)
**Summary stat tiles (4):** Line Items · Total Items · Total {currency} · Total PLN

**Customer & terms panel (edit / view mode):**
- View: Customer name, Email, Currency, Payment method, Payment terms, Incoterm, Status
- Edit: Autocomplete customer search, VAT EU (mono), Country, Email, Currency select, Payment method select, Payment terms text, Incoterm select

**VAT & Insurance panel:**
- View: VAT rate, KUKE insured status, KUKE insurance rate %
- Edit: VAT rate select [0% WDT · 0% · 5% · 8% · 23%], KUKE insured select [Yes/No], insurance rate

**Dates & FX panel:**
- Issue date, Valid until, Exchange rate (EUR/PLN), FX source, FX date

**Shipment reference panel:**
- AWB link, Shipment status badge, Carrier chip

#### Tab 2 — Items / Packing List (ItemsTab)
**Table columns (exact order, 16):**
Sr · Product Code · Design Nr · Ctg · Client PO · Description EN · Description PL · Kt · Col · Quality · Dia Wt · Col Wt · Qty · Value · Total · Size · (delete icon)

**Footer rows:** Freight (EUR), Insurance (EUR), Grand Total
**Editing controls per row:** inline text inputs for all editable cells
**Button:** + Add line (editing mode only)

**Charges fields:** freightEur, insuranceEur

#### Tab 3 — Documents (DocumentsTab — same as shipment detail)
Documents: Packing List · Pro Forma Invoice · CMR · wFirma Printout
State chips: Source · Draft · Generated · Attached · Pending
Per-card: 👁 View · ↓ Download

#### Tab 4 — Matching (implied by list Match chip)
Match state per line: auto-matched · partial-matched · manual

#### Tab 5 — Push to wFirma (WfirmaExportPage context)
**Ready queue table columns (5):** AWB · Net Value · Gross Value · Duty A00 · Actions
**Actions per row:** Review · Push to wFirma (gold, gated)
**Export log table columns (7):** AWB · Export Date · PZ Number · Net · Gross · Duty · Status

#### Tab 6 — Audit Trail (AuditTrailTab)
**Events shown per draft stage:** Packing list uploaded & extracted · Customer matched · Products matched · Operator reviewed · Marked Ready · Pushed to wFirma
**Columns:** timestamp · user · action · status dot (done/warn)

---

## 5. Documents Hub

**Nav path:** documents | **Layout regions:** 2 (tab bar, lane-based document list)

### 5.1 Tabs (3)
Proforma (PI) · PZ — Inbound · Other documents

### 5.2 Lane workflow per tab
**Lanes:** Draft → Approved → Posted

### 5.3 Toolbar buttons (per tab)
- Upload packing list
- New PI / New PZ (depending on tab)

### 5.4 Document Viewer Page (DocumentViewerPage)
**Toolbar buttons:** ← Back · ‹ prev page · › next page · − zoom out · + zoom in · Open in new tab · ↓ Download · ↓ Download all (.zip)

**Side panel metadata fields:**
Document type · Document # · Title · Linked AWB · Linked shipment · Uploaded · Uploaded by · Size · Format · Hash

---

## 6. Accounting

**Nav path:** accounting | **Layout regions:** 2 (KPI strip, 6-tab subnav)

### 6.1 KPI tiles (4)
Purchase ledger (count) · Sales / proforma (count) · wFirma sync (status) · Audit events (count)

### 6.2 Tabs (6 — AccountingPage)
Purchase Ledger (PZ) · Sales / Proforma · Ledgers / Statements · wFirma Sync · Master Data · Audit Trail

---

### Tab A — Purchase Ledger / PZ (PzAccountingPage)

**KPI tiles (4):**
Locked (No SAD) · Ready for PZ · PZ Generated · Exported to wFirma

**Shipment table:** uses FilteredShipmentsTable
**Columns (7):** AWB / Tracking · Carrier · Overall Status · Net Value · Gross Value · Duty A00 · Actions

---

### Tab B — Sales / Proforma (SalesProformaPage)

**KPI tiles (4):**
Drafts · Sent / Accepted · Converted · Awaiting wFirma

**Sub-tabs (3):**
All Proformas · Pipeline · wFirma

**All Proformas table columns (implied):** ID · Client · Date · Valid until · Items · Net · VAT · Gross · Currency · Status · wFirma · Ext Doc · (actions)

**Status values:** Draft · Sent · Accepted · Expired · Converted
**wFirma badge values:** Exported · Pending · Not exported

**Buttons:** + New Proforma (→ NewProformaDraftModal) · View · Export to wFirma

---

### Tab C — Ledgers / Statements (LedgersPage)

**Sub-tabs (2):** Client Ledger · Supplier Ledger

#### Client Ledger view (ClientLedgerView)

**ClientHeaderCard KPI tiles (4):**
Current balance · Overdue balance · Open invoices · Inventory exposure

**Client Ledger table (ClientStatementTable — 10 columns):**
Date · Doc no. · Type · Due · Debit · Credit · Balance · Status · Source · (actions)

**Filters:** search input, client selector

#### Supplier Ledger view
(mirrors Client Ledger structure for suppliers)

---

### Tab D — wFirma Sync (WfirmaMappingPage)

**Capability strip panel:**
- GET /api/v1/wfirma/capabilities
- Capability pills (6): customers.read ✓ · customers.write ✓ · goods.read ✓ · goods.write ✗ · warehouse.read ✓ · reservation.write ✗ (warn)
- Blocking reasons banner: WFIRMA_WAREHOUSE_ID missing · reservation.write scope not granted

**Sub-tabs (2):** Customers · Products

**Customers table columns (5):** Name · wFirma ID · VAT · Country · Match status · Last Sync
**Products table columns (7):** Product Code · wFirma Good · Name · Unit · VAT · Stock · Sync

**Sync badges:** ok · missing · stale

**Toolbar buttons:** search input · ↻ Sync Now (implied)

---

### Tab E — Master Data (MasterDataView)

**5 sub-sections:**

**Clients / Importers table (6 columns):**
Name · Country · NIP / VAT ID · Default Currency · Last activity · (edit)

**Suppliers / Exporters table (5 columns):**
Supplier · Country · Default Carrier · HS Codes · Active

**HS Codes / Tariff table (5 columns):**
HS Code · Description · Duty % · VAT % · Locked

**Currency / FX Rates table:**
Currency · Rate · Last Updated · Source

**VAT Rates table (4 columns):**
Rate · Code · Applies to · Locked

---

### Tab F — Audit Trail (AuditTrailView)

**Table columns (4):** timestamp · user · action · target

**Filters:**
- Search input
- All users select
- All actions select
- Export button

---

## 7. Inventory

**Nav path:** inventory | **Layout regions:** 2 (11-tab subnav, tab content)

### 7.1 Tabs (INV_TABS — 11)
| id | Label | Stage |
|---|---|---|
| overview | Overview | — |
| tempPurchase | Temp Purchase | Stage 1 |
| tempWarehouse | Temp Warehouse | Stage 1 |
| tempSale | Temp Sale | Stage 1 |
| consignment | Consignment | Stage 2 |
| finalStock | Final Stock | Stage 2 |
| sampleOut | Sample Out | Stage 2 |
| sampleReturn | Sample Return | Stage 2 |
| clientReturn | Goods Return from Client | Stage 2 |
| producerReturn | Return to Producer | Stage 2 |
| mapping | Identity / Mapping | — |

---

### Tab 1 — Overview (InventoryOverviewTab)

**KPI tiles:** Stock units · Pieces on hand · Reserved · Available · Total value (5 tiles)

**Stage 1 summary card:** Open packing lists, Awaiting goods, Partially arrived, Closed-out

**Stage 2 summary card:** Final stock units, Reserved, Samples out, Consignment out

**Quick-action buttons:** ↑ Upload Packing List · + New Consignment · ↑ Issue Sample · Move Stock (→ MoveStockModal)

---

### Tab 2 — Temp Purchase (TempPurchaseTab)

**KPI tiles (4):**
Open packing lists · Awaiting goods (lines) · Partially arrived · Closed-out

**Stage info banner:** "Stage 1 — Document layer. These lines come from supplier invoices & packing lists. Goods are expected but not physically confirmed."

**Table: Open packing-list lines**
**Columns (13):** Pk Sr · Design No · Ctg · Client PO · Karat · Color · Quality · Dia Wt · Col Wt · Qty · Size · Value · Total · Supplier · AWB · Expected · Status

**Status values:** Awaiting goods · Partially arrived · Closed-out

**Buttons:** Filter · ↓ Export CSV · + Upload Packing List

---

### Tab 3 — Temp Warehouse (TempWarehouseTab)

**KPI tiles (4):**
Awaiting count · Counted · Discrepancies · Ready for matching

**Stage info banner:** "Stage 1 — Physical arrival. Goods have arrived but are not fully matched, counted or bagged. Discrepancies allowed and tracked. No FINAL_STOCK is created until matching is complete."

**Table: Pending physical match**
**Columns (8):** Pk Sr · Design No · Expected · Received · Δ (delta, colored red/amber/neutral) · Bag ID · AWB · Recv Date · Status

**Status values:** Pending match · Discrepancy · Counted awaiting bag

**Buttons:** Scan barcode · Begin matching

---

### Tab 4 — Temp Sale (TempSaleTab)

**KPI tiles (4):**
Open reservations · Awaiting goods · Reserved · Sales-invoice gate (LOCKED)

**Gate banner:** "Sales-invoice gate is enforced. No commercial sale invoice can be issued from a TEMP_SALE row. The invoice is unlocked only when its linked stock has reached FINAL_STOCK after physical verification."

**Table: Sales reservations awaiting closure**
**Columns (8):** Proforma · Client · Design No · Qty · Value · Linked to · Status · (actions)

**Status values:** Reserved · Awaiting goods · Pre-reserved

**Row actions:** View proforma · Issue invoice (disabled until FINAL_STOCK)

---

### Tab 5 — Consignment (ConsignmentTab)

**Stage info banner:** "Consignment goods. Stock physically with the client (or salesperson) but legally owned by Estrella until sold."

**Sub-tabs (3):** Issue · Proforma Issue · Balance / Valuation

**Issue sub-tab table columns (9):**
Cons ID · Client · Design No · Qty · Value EUR · Issued · Due Back · Days out · Status

**Status values:** Out · Closing soon · Overdue

**Proforma Issue sub-tab table columns (9):**
Cons ID · Proforma · Client · Qty · Value EUR · Issued · Sold · Balance Qty · Balance EUR · Status

**Status values:** Partially sold · Unsold · Unsold (overdue)

---

### Tab 6 — Final Stock (FinalStockTab)

**KPI tiles (5):**
Stock units · Pieces on hand · Reserved · Available · Stock value

**Stage info banner:** "Stage 2 — Inventory truth. Each row is a physically-verified `stock_unit_id`. wFirma fields are read-only references until controlled execution is approved separately."

**Table: Verified stock units**
**Columns (10):** Stock Unit ID · Family · Design · Batch · Bag · Qty · Location · Value PLN · Trace Barcode · wFirma Good ID · wFirma Code · Verified On

**Filter input:** "Filter family / design / batch / bag…"
**Button:** Move Stock (→ MoveStockModal)

---

### Tab 7 — Sample Out (SampleOutTab)

**KPI tiles (4):**
Active out · Closing soon (≤3 days) · Overdue · Returned (mo.)

**Table: Verified stock issued temporarily**
**Columns (10):** Sample ID · Source SU · Design · Qty · Issued to · Purpose · Issued · Return by · Days left (colored) · Status · (actions)

**Status values:** Out · Closing soon · Overdue · Returned

**Row actions:** Record Return (if out/overdue) · View

**Toolbar button:** + Issue Sample

---

### Tab 8 — Sample Return (SampleReturnTab)

**KPI tiles (4):**
Awaiting inspection · In repair · Restocked (mo.) · Written off (mo.)

**Table: Samples coming back from sales / clients**
**Columns (10):** Return ID · Sample (mono) · Design · Qty · Returned from · Received · Condition · Inspector · Decision · Status · (actions)

**Status values:** Awaiting inspection · In repair · Restocked

**Row actions:** Inspect (if awaiting) · View

---

### Tab 9 — Goods Return from Client (ClientReturnTab)

**KPI tiles (4, implied):** Awaiting inspection · Inspected · Restocked · Routed to RTP

**Table: Client RMAs**
**Columns (10):** RMA ID · Invoice · Client · Design · Qty · Value · Reason · Received · Condition · Decision · Status · (actions)

**Status values:** Restocked · Awaiting inspection · Inspected · Routed to RTP

**Reason values:** Size exchange · Damaged in transit · Wrong item shipped · Quality dispute

---

### Tab 10 — Return to Producer (ProducerReturnTab)

**KPI tiles (4):**
In preparation · Awaiting AWB · In transit · Confirmed (mo.)

**Table: Returns prepared for supplier shipment**
**Columns (10):** RTP ID · Source · Design · Qty · Supplier · Reason · Prepared · AWB out · Status · (actions)

**Status values:** Awaiting AWB · Shipped · Confirmed by producer

**Row actions:** Add AWB (if awaiting) · View docs

---

### Tab 11 — Identity / Mapping (MappingTab)

**Info banner:** "wFirma is not the inventory truth. The truth is `stock_unit_id`, scanned via `trace_barcode`. wFirma fields appear here as read-only references."

**Identity fields table (8 fields):**
| Field key | Group | Label | Editable |
|---|---|---|---|
| wfirma_good_id | External (read-only) | wFirma Good ID | no |
| wfirma_product_code | External (read-only) | wFirma Product Code | no |
| product_family_code | Internal commercial | Product Family Code | yes |
| design_id | Internal commercial | Design ID | yes |
| batch_id | Physical | Batch ID | yes |
| bag_id | Physical | Bag ID | yes |
| stock_unit_id | Truth | Stock Unit ID | no (system-generated) |
| trace_barcode | Truth | Trace Barcode | no |

**Trace barcode format:** family · design · batch · bag (e.g. PND-CLASSIC·EJ-PND-0142-A·B-2604-04·BAG-2604-A)

---

### Inventory — Move Stock Modal (MoveStockModal)

**Trigger:** Move Stock button (Overview tab, Final Stock tab)
**Fields:**
- Move type toggle: Warehouse→Warehouse / Stage transition
- Stock unit (text input)
- Quantity (number input)
- From (select): Główny / Branch / Safe vault / Trade fair
- To warehouse (select, if W→W mode) OR To stage (select, if stage transition)
- Issued to / Consignee (if sample or consignment stage)
- Return by (date picker, if sample or consignment stage)
- Reason / notes (textarea)

**Buttons:** Confirm · Cancel

---

## 8. Reports

**Nav path:** reports | **Layout regions:** 2 (KPI strip, table)

### 8.1 KPI tiles (4)
Shipments YTD · Total Duty Paid YTD · Total Gross YTD · Avg. Processing Time

### 8.2 Duty Summary Table
**Columns (6):** Month · Shipments · Total Net (PLN) · Total Gross (PLN) · Total Duty A00 (PLN) · Avg. Exchange Rate

### 8.3 Implied additional reports sections
(Per ReportsPage component — full detail tables for shipment-level breakdown)

---

## 9. Setup — Settings (AdminSettingsPage)

**Nav path:** setup → admin | **Layout regions:** 3 cards

### 9.1 API Configuration card
Fields: API Base URL (text input) · DHL Clearance Email (text input) · wFirma API Key (password input)
Button: Save Settings

### 9.2 Users & Roles card
- User list (name, role, status)
- Button: + Invite User

### 9.3 System Status card
- 4 status tiles: API · Database · Queue · Integration

---

## 10. Setup — Master Data (MasterDataView)

(Same content as Accounting → Tab E — Master Data)
5 sub-sections: Clients/Importers · Suppliers/Exporters · HS Codes/Tariff · Currency/FX Rates · VAT Rates
See Section 6, Tab E for all column definitions.

---

## 11. Setup — Carriers (CarriersPage)

**Nav path:** setup → carriers | **Layout regions:** 2 (KPI strip, tab content)

### 11.1 KPI tiles (4)
Connected (N of M) · Sandbox/Prod · Webhooks 24h · Open Alerts

### 11.2 Tabs (CARRIER_TABS — 6)
Carrier Accounts · Add Carrier · API Integration · Webhooks · Active Sessions · Audit Log

### 11.3 Carrier Accounts tab
**Carrier cards (CarrierCard component):** for each configured carrier:
- Logo / name, status badge (Live / Sandbox)
- Account number, API environment, last used
- Buttons: Configure · Test Connection · Disable

---

## 12. Setup — wFirma (WfirmaMappingPage)

(Same content as Accounting → Tab D — wFirma Sync)
**Sections:** Capability strip · Customers tab · Products tab
See Section 6, Tab D for all column definitions.

---

## 13. Setup — API Status (ApiStatusPage)

**Nav path:** setup → api_status | **Layout regions:** 2 (KPI strip, tab content)

### 13.1 KPI tiles (4)
Healthy/Total · Calls (24h) · P95 latency · Open incidents

### 13.2 Tabs (API_STATUS tabs — 4)
Integrations · Endpoint Registry · Recent Errors · Incidents

### 13.3 Integration health per integration
Status dot (green/red/amber) · name · last ping · uptime %

---

## 14. Setup — Diagnostics (DiagnosticsPage)

**Nav path:** setup → diagnostics | **Layout regions:** 2 (KPI strip, status cards)

### 14.1 KPI tiles (4)
Health checks (N/M) · Storage used · Active locks · Version

### 14.2 OperationalStatusStrip (6 integrations)
wFirma · DHL Inbox · Email Queue · Cliq Webhook · Cowork Bridge · WorkDrive

Each integration: name, status dot, last ping timestamp, latency

### 14.3 Additional diagnostic panels (implied)
Database health · Queue state · Lock registry

---

## 15. Setup — Automation (Action Center / AutomationCenterPage)

**Nav path:** setup → automation | **Layout regions:** 2 (pending queue + right stats rail)

### 15.1 Pending operator actions table (ActionCenterPage)
**Columns (8):** ID · Action · Reference · Amount · Risk · Age · Status · (Review button)

**Risk vocabulary:** low · medium · high (color-coded)
**Feature status vocabulary:** active · partial · backend · future

**Bulk approve button** (disabled, backend-pending)

### 15.2 Right stats rail
**Today summary tiles (4):** Approved · Auto-executed · Rejected · SLA breaches

### 15.3 Action types in queue
- Proforma · approve & issue
- PZ · adopt into wFirma
- Sample Out · release from stock
- Credit limit · raise
- Goods Return · receive from client
- Return to Producer · open RMA

---

## 16. Setup — Parser / Learning (LearningParserPage)

**Nav path:** setup → intelligence | **Layout regions:** 1 (SAD/ZC429 parser tool)

### 16.1 SAD / ZC429 Parser
- Textarea (large, paste SAD text)
- Buttons: Parse · Clear
- Result display fields: MRN · LRN · Clearance date · Agent · Exchange rates · Duty (A00) · VAT (B00)

---

## 17. Setup — Coverage Matrix (CoverageMatrix)

**Nav path:** setup → coverage | **Layout regions:** 2 (filter tiles + table)

### 17.1 Filter tiles (4 — clickable, toggle filter)
active (Wired & shipping) · partial (UI live · backend gaps) · backend (Backend pending) · future (Planned · not scoped)

### 17.2 Search / filter bar
- Text input: "Filter by module, feature, or API path…"
- Clear filter button (conditional)
- Count: "Showing N of M"

### 17.3 Coverage table
**Columns (5):** Module · Feature · Status (FeatureStatus chip) · API placeholder · Notes

**Coverage rows (COVERAGE_ROWS — 40+ entries):**
Modules covered: Shipments · DHL/Customs · Accounting · Ledgers · Inventory · Carriers · Email · Parser · Proforma · Action Center · wFirma Mapping

---

## 18. Shipping Ops (ShippingOpsPage)

**Nav path:** shipments (via routing) | **Layout regions:** 2 (tab bar, content)

**Note:** ShippingOpsPage is accessible via SOQueue / shipping nav redirect. It is the outbound shipment operations panel.

### 18.1 Tabs (SHIPPING_OPS — 9)
Shipment Queue · Create Shipment · Package Builder · Label Preview & Print · Shipment + Tracking Timeline · Warehouse → Carrier Handoff · Return Shipments · Audit Log · Integration Map

### 18.2 Shipment Queue (SOQueue)

**KPI tiles (5):**
Open · Pending pickup · In transit · Exceptions · Delivered (7d)

**Table columns (10):**
Shipment · AWB · Carrier · Client/Consignee · Linked docs · Pkgs · Weight · Lifecycle · State · (open)

**Toolbar buttons (all disabled/backend-pending):**
+ New shipment (disabled — API pending) · Bulk dispatch (disabled) · Pickup request (disabled — carrier pending) · Generate manifest (disabled)

---

## 19. New Shipment Modal (NewShipmentModal)

**Trigger:** + New Shipment button (Shipment Queue)
**Step 1 fields:**
- AWB / Tracking Number (text)
- Carrier (select)
- Client / Sales (select)
- Supplier / Purchase (select)
- Document slots (4): Purchase invoice · Purchase packing · Sales packing · AWB
- + Add another document (button per slot type)

---

## MODALS SUMMARY

| Modal | Trigger | Key fields | Buttons |
|---|---|---|---|
| NewShipmentModal | + New Shipment | AWB, Carrier, Client, Supplier, Document slots (4) | Next / Cancel |
| NewProformaDraftModal | + New Draft | 4 source option buttons | × close |
| ImportPackingListModal | From Packing List source | 4-step wizard (Upload/Extract/Map/Create) | Next / Back / Cancel |
| MoveStockModal | Move Stock buttons | Move type, Stock unit, Qty, From, To, Issued to, Return by, Reason | Confirm · Cancel |
| GlobalSearch | ⌘K / Ctrl+K | Search input, type filter chips | Esc to close |
| DocumentViewerPage | View button on document card | (full page, not modal) | ← Back, page nav, zoom, Download, Download all |

---

## SCREEN LIST SUMMARY TABLE

| Screen | Regions | Buttons (approx.) | Modals triggered | Tables |
|---|---|---|---|---|
| Dashboard | 3 | 4 quick-flow + kanban actions | GlobalSearch | — |
| Inbox | 3 | 5–7 per item type | — | 1 (item list) |
| Shipments (list) | 2 | View per row | NewShipmentModal | 1 |
| Shipment Detail → Overview | 1 | contextual (~4) | — | — (info grids) |
| Shipment Detail → Pro Forma tab | 1 | + Create Pro Forma Draft | — | 1 (draft list) |
| Shipment Detail → DHL/Customs | 2 | 10 | — | — (info grids + verification) |
| Shipment Detail → PZ/Accounting | 1 | 7 (conditional) | — | — (info grids) |
| Shipment Detail → Documents | 1 | 2 per doc card (8 total) | — | — (card grid) |
| Shipment Detail → Timeline | 1 | — | — | 1 (16-event list) |
| Pro Forma List | 2 | 3 toolbar + 2 per row | NewProformaDraftModal, ImportPackingListModal | 1 |
| Pro Forma Detail → Overview | 3 | Edit/Save/Cancel/Push/Download (5) | — | — (info panels) |
| Pro Forma Detail → Items | 1 | + Add line | — | 1 (16-col) |
| Pro Forma Detail → Documents | 1 | 2 per card (8 total) | — | — (card grid) |
| Pro Forma Detail → Push to wFirma | 2 | 2 per row | — | 2 |
| Pro Forma Detail → Audit Trail | 1 | — | — | 1 |
| Documents Hub | 2 | 2 toolbar + view/download per doc | — | 1 per lane |
| Document Viewer | 1 | 8 (toolbar) | — | — |
| Accounting → Purchase Ledger | 2 | View per row | — | 1 (7-col) |
| Accounting → Sales/Proforma | 3 | 3 toolbar + 2 per row | NewProformaDraftModal | 1 |
| Accounting → Client Ledger | 2 | client selector | — | 1 (10-col) |
| Accounting → wFirma Sync | 2 | Sync Now | — | 2 (customers, products) |
| Accounting → Master Data | 5 | edit per row | — | 5 |
| Accounting → Audit Trail | 1 | Export | — | 1 (4-col) |
| Inventory → Overview | 2 | 4 | MoveStockModal | — (summary cards) |
| Inventory → Temp Purchase | 2 | 3 | — | 1 (13-col) |
| Inventory → Temp Warehouse | 2 | 2 | — | 1 (8-col) |
| Inventory → Temp Sale | 2 | 2 per row | — | 1 (8-col) |
| Inventory → Consignment | 3 (3 sub-tabs) | per row actions | — | 2 |
| Inventory → Final Stock | 2 | Move Stock | MoveStockModal | 1 (10-col) |
| Inventory → Sample Out | 2 | + Issue Sample + row actions | — | 1 (10-col) |
| Inventory → Sample Return | 2 | row actions (Inspect/View) | — | 1 (10-col) |
| Inventory → Client Return | 2 | row actions | — | 1 (10-col) |
| Inventory → Return to Producer | 2 | row actions (Add AWB/View docs) | — | 1 (10-col) |
| Inventory → Identity / Mapping | 1 | — | — | 1 (8-field identity model) |
| Reports | 2 | — | — | 1 (6-col duty summary) |
| Setup → Settings | 3 | Save Settings + Invite User | — | — |
| Setup → Master Data | 5 | edit per row | — | 5 |
| Setup → Carriers | 2 | Configure/Test/Disable per carrier | — | 1 per tab |
| Setup → wFirma | 2 | Sync Now | — | 2 |
| Setup → API Status | 2 | — | — | 1 per tab (4 tabs) |
| Setup → Diagnostics | 2 | — | — | — (status tiles) |
| Setup → Automation | 2 | Review per row + Bulk approve | — | 1 (8-col) |
| Setup → Parser/Learning | 1 | Parse + Clear | — | — |
| Setup → Coverage Matrix | 2 | filter tiles (4) + Clear filter | — | 1 (5-col, 40+ rows) |
| Shipping Ops → Shipment Queue | 2 | 4 disabled | NewShipmentModal | 1 (10-col) |
| Shipping Ops (other 8 tabs) | 1 each | varies | — | 1 each (stub) |

---

*Total screens/sub-screens inventoried: 50+ (18 primary pages, 32+ sub-tabs and detail panes)*
*Total tables: 35+*
*Total modals: 6 (NewShipment, NewProformaDraft, ImportPackingList, MoveStock, GlobalSearch, DocumentViewer)*
*Total buttons: 200+ across all screens*
