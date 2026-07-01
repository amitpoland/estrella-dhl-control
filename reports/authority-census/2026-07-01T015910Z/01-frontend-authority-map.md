# Frontend Authority Map

**Base SHA:** aa414d90
**Census timestamp:** 2026-07-01T015910Z
**Inspector agent:** frontend-authority-inspector
**Mode:** READ-ONLY — no app code was modified
---

# Frontend Authority Map

**Base SHA:** aa414d90
**Files scanned:** 22 HTML (service/app/static/) + 8 HTML (service/app/static/atlas/) + 33 JSX (service/app/static/v2/)

---

## Authority Table

| # | Module | Canonical URL | Authority File | Status | Legacy/Duplicate Files |
|---|---|---|---|---|---|
| 1 | Dashboard (Kanban) | `/v2/dashboard` | `service/app/static/v2/dashboard-kanban.jsx` (`DashboardKanban`) | AUTHORITY | `service/app/static/dashboard-v2.html` (pre-V2 SPA shell, LEGACY); `service/app/static/atlas/dashboard-v2.html` (atlas stub, ORPHAN) |
| 2 | Inbox | `/v2/inbox` | `service/app/static/v2/inbox-page.jsx` (`InboxPage`) | AUTHORITY | `service/app/static/inbox-v2.html` (standalone pre-V2 shell, LEGACY); `service/app/static/atlas/` no inbox file exists |
| 3 | Shipments (batch list) | `/v2/shipments` | `service/app/static/v2/dashboard-page.jsx` (`DashboardPage`) | AUTHORITY | `service/app/static/dashboard.html` (V1 authority still live at `/dashboard/`, LEGACY); `service/app/static/atlas/shipments-v2.html` (atlas stub, ORPHAN) |
| 4 | Shipment Detail | `/v2/shipments` → `page=detail` | `service/app/static/v2/shipment-detail-page.jsx` (`ShipmentDetailPage`) | FRAGMENTED | `service/app/static/shipment-detail.html` (V1, live at `/dashboard/shipment-detail.html`, LEGACY); `service/app/static/shipment-detail-v3.html` (standalone pre-V2 design shell, LEGACY); `service/app/static/v2/shipment-detail-page.v1.jsx` (NOT loaded by index.html, DEAD); `service/app/static/v2/shipment-detail-page.v2.jsx` (NOT loaded by index.html, DEAD) |
| 5 | DHL / Customs | `/v2/dhl` | `service/app/static/v2/pages-v2.jsx` (`DhlCustomsPage`) + `service/app/static/v2/dhl-scan-status.jsx` + `service/app/static/v2/dhl-daily-summary.jsx` | FRAGMENTED | `service/app/static/dhl-automation-v2.html` (standalone pre-V2 shell, still linked from V1 dashboard at line 1109, LEGACY) |
| 6 | Pro Forma List | `/v2/proforma` | `service/app/static/v2/proforma-list.jsx` (`ProformaListPage`) | AUTHORITY | `service/app/static/proforma-v2.html` (standalone pre-V2 shell, referenced in `pz-design-v2.js` route map, LEGACY); `service/app/static/atlas/proforma-v2.html` (atlas stub that redirects to the legacy shell, ORPHAN) |
| 7 | Pro Forma Detail | `/v2/proforma_detail` | `service/app/static/v2/proforma-detail.jsx` (`ProformaDetailPage`) | AUTHORITY | `service/app/static/proforma-detail-v2.html` (standalone pre-V2 shell, referenced in `pz-design-v2.js`, LEGACY) |
| 8 | Pro Forma Search | `/v2/proforma_search` | `service/app/static/v2/proforma-search.jsx` (`ProformaSearchPage`) | AUTHORITY | — |
| 9 | Documents Hub | `/v2/documents` | `service/app/static/v2/documents-hub.jsx` (`DocumentsHubPage`) | AUTHORITY | `service/app/static/documents-v2.html` (standalone pre-V2 shell, LEGACY); `service/app/static/atlas/documents-v2.html` (atlas stub, ORPHAN) |
| 10 | Accounting Hub | `/v2/accounting` | `service/app/static/v2/accounting-hub.jsx` (`AccountingHub`) | AUTHORITY | `service/app/static/accounting-hub-v2.html` (standalone pre-V2 shell, LEGACY) |
| 11 | Ledgers | `/v2/accounting` (sub-panel) | `service/app/static/v2/ledgers-page.jsx` (`LedgersPage`) | FRAGMENTED | `service/app/static/atlas/ledgers-v2.html` (atlas stub, ORPHAN); `AccountingHub` in `accounting-hub.jsx` renders its own ledger sub-panel |
| 12 | Inventory | `/v2/inventory` | `service/app/static/v2/inventory-page.jsx` (`InventoryPage` + `DocumentViewerPage`) | AUTHORITY | `service/app/static/inventory-v2.html` (standalone pre-V2 shell — components extracted from here at Sprint 29, LEGACY) |
| 13 | Reports | `/v2/reports` | `service/app/static/v2/pages.jsx` (`ReportsPage`) | AUTHORITY | — |
| 14 | Master Data | `/v2/master` | `service/app/static/v2/master-page.jsx` (`MasterPage`) | AUTHORITY | `service/app/static/master-data-v2.html` (standalone pre-V2 shell, LEGACY); `service/app/static/customer-master-v2.html` (Customer Master subset, linked from proforma-detail, LEGACY) |
| 15 | Carriers | `/v2/carriers` | `service/app/static/v2/carriers-page.jsx` (`CarriersPage`) | AUTHORITY | — |
| 16 | wFirma Setup | `/v2/wfirma_setup` | `service/app/static/v2/ops-cell.jsx` (`WfirmaMappingPage`) | AUTHORITY | `service/app/static/wfirma-inbox-v2.html` (standalone pre-V2 wFirma recovery page, LEGACY) |
| 17 | API Status | `/v2/api_status` | `service/app/static/v2/api-status-page.jsx` (`ApiStatusPage`) | AUTHORITY | `service/app/static/atlas/api-status-v2.html` (atlas stub, ORPHAN) |
| 18 | Diagnostics | `/v2/diagnostics` | `service/app/static/v2/ops-cell.jsx` (`DiagnosticsPage`) | DUPLICATE | `WfirmaMappingPage` and `DiagnosticsPage` share the same file; both are distinct routed pages |
| 19 | Automation Center | `/v2/automation` | `service/app/static/v2/pages-v2.jsx` (`AiBridgePage`) | DUPLICATE | `EmailQueuePage`, `ActionProposalsPage`, `IntelligencePage` also reside in `pages-v2.jsx` |
| 20 | Intelligence Hub | `/v2/intelligence` | `service/app/static/v2/pages-v2.jsx` (`IntelligencePage`) | DUPLICATE | See row 19 |
| 21 | Admin / Settings | `/v2/admin` | `service/app/static/v2/pages.jsx` (`AdminSettingsPage`) | AUTHORITY | `service/app/static/admin-users.html` (live at `/admin/users`, user management only — different domain scope, AUTHORITY) |
| 22 | Coverage Map | `/v2/coverage` | `service/app/static/v2/wireframe-update.jsx` (`CoverageMapPage`) | DUPLICATE | `ActionCenterPage`, `IdentityMappingPage`, `MoveStockPage`, `SampleOutPage`, `SampleReturnPage`, `GoodsReturnPage`, `ReturnToProducerPage`, `OperationalStatusStrip` also in `wireframe-update.jsx` |
| 23 | Shipping Ops | `/v2/shipping` (UNREACHABLE — `shipping→shipments` redirect) | `service/app/static/v2/shipping-ops.jsx` (`ShippingOpsPage`) | UNREACHABLE | Slug `shipping` redirects to `shipments`; `ShippingOpsPage` renders at `/v2/shipping` but that URL is caught by `ROUTE_REDIRECTS` |
| 24 | Action Center | `/v2/actions` (UNREACHABLE — `actions→inbox` redirect) | `service/app/static/v2/wireframe-update.jsx` (`ActionCenterPage`) | UNREACHABLE | Slug `actions` redirects to `inbox` |
| 25 | Reservation Cell | `/v2/reservation` (UNREACHABLE — `reservation→inbox` redirect) | `service/app/static/v2/ops-cell.jsx` (`ReservationCellPage`) | UNREACHABLE | Slug `reservation` redirects to `inbox` |
| 26 | Warehouse Scanner | `/v2/scanner` (UNREACHABLE — `scanner→inventory` redirect) | `service/app/static/v2/ops-cell.jsx` (`WarehouseScannerPage`) | UNREACHABLE | Slug `scanner` redirects to `inventory`; also `service/app/static/warehouse.html` (V1, linked from V1 nav, LEGACY) |
| 27 | Login | `/login` | `service/app/static/login.html` | AUTHORITY | — |
| 28 | Signup | `/signup` | `service/app/static/signup.html` | AUTHORITY | — |
| 29 | Forgot Password | `/forgot-password` | `service/app/static/forgot-password.html` | AUTHORITY | — |
| 30 | Admin Users | `/admin/users` | `service/app/static/admin-users.html` | AUTHORITY | — |
| 31 | V2 SPA Shell | `/v2/*` | `service/app/static/v2/index.html` | AUTHORITY | `service/app/static/atlas-shell.html` (standalone shell render-verify harness, DEAD — no route in main.py) |
| 32 | Atlas Shell (legacy campaign) | (no canonical V2 route) | `service/app/static/atlas/atlas-shared.js` | ORPHAN | `atlas/dashboard-v2.html`, `atlas/shipments-v2.html`, `atlas/documents-v2.html`, `atlas/ledgers-v2.html`, `atlas/proforma-v2.html`, `atlas/pz-v2.html`, `atlas/search-v2.html`, `atlas/api-status-v2.html` — all ORPHAN (linked from `atlas-shared.js` nav but `accounting-v2.html` and `inbox-v2.html` link targets are dead files) |
| 33 | PZ / Customs Docs (Atlas) | `/dashboard/atlas/pz-v2.html` | `service/app/static/atlas/pz-v2.html` | ORPHAN | Not linked from V2 shell; only reachable via atlas nav strip |
| 34 | Global Search overlay | (Cmd-K / Ctrl-K modal) | `service/app/static/v2/global-search.jsx` (`GlobalSearch`) | AUTHORITY | — |
| 35 | Link-as-Sales Backfill panel | embedded in ProformaListPage | `service/app/static/v2/link-as-sales-backfill.jsx` | AUTHORITY | — |
| 36 | Client Detail Modal | embedded popup | `service/app/static/v2/client-detail.jsx` (`ClientDetailModal`) | AUTHORITY | — |
| 37 | Client KYC / Consignment | embedded modal | `service/app/static/v2/client-kyc-and-consignment.jsx` | AUTHORITY | — |
| 38 | Modals (New Shipment, API Checklist) | embedded modals | `service/app/static/v2/modals.jsx` | AUTHORITY | — |
| 39 | Legacy batch page | `/dashboard/batch.html` | `service/app/static/batch.html` | LEGACY | V2 shell (`shipments` + `detail`) supersedes; batch.html redirects to `dashboard.html?id=` |

---

## Status counts

| Status | Count |
|---|---|
| AUTHORITY | 21 |
| FRAGMENTED | 3 |
| DUPLICATE | 4 |
| LEGACY | 14 |
| DEAD | 3 |
| UNREACHABLE | 4 |
| ORPHAN | 9 |

---

## Top fragmentation

1. **Shipment Detail** — 5 competing files: `shipment-detail-page.jsx` (V2 authority), `shipment-detail.html` (V1 live), `shipment-detail-v3.html` (pre-V2 design shell), `shipment-detail-page.v1.jsx` (dead versioned copy), `shipment-detail-page.v2.jsx` (dead versioned copy). The V1 page remains the primary operator surface for direct-link workflows; V2 `detail` page is only reachable by clicking a row in the V2 shipments list.

2. **DHL / Customs** — 4 competing files: `pages-v2.jsx:DhlCustomsPage` (V2 authority), `dhl-scan-status.jsx` (sub-card, composed inside DhlCustomsPage), `dhl-daily-summary.jsx` (sub-card, composed inside DhlCustomsPage), `dhl-automation-v2.html` (still linked from V1 dashboard inline link at line 1109 — LEGACY but reachable).

3. **wireframe-update.jsx** — 8 page-class components (`CoverageMapPage`, `ActionCenterPage`, `IdentityMappingPage`, `MoveStockPage`, `SampleOutPage`, `SampleReturnPage`, `GoodsReturnPage`, `ReturnToProducerPage`) plus the global `OperationalStatusStrip` shell component share one file with no single dominant owner; `coverage` is the only active route; the remaining 7 are either UNREACHABLE (via redirect) or DEAD routes never added to the router.

---

## Sources

- `C:\PZ-verify\service\app\static\v2\index.html` — `ROUTE_REDIRECTS` object (lines 361–373); all `<script type="text/babel">` tags listing loaded JSX files (lines 297–326)
- `C:\PZ-verify\service\app\static\v2\components.jsx` — `NAV_TREE` array (lines 10–36)
- `C:\PZ-verify\service\app\static\v2\mock-badge.jsx` — `WIRED_PAGES` array (line 59)
- `C:\PZ-verify\service\app\static\v2\pages.jsx` — `ReportsPage`, `AdminSettingsPage`, `DhlClearancePage`, `PzAccountingPage`, `WfirmaExportPage`, `SalesProformaPage`, `WarehousePage`, `LearningParserPage`
- `C:\PZ-verify\service\app\static\v2\pages-v2.jsx` — `DhlCustomsPage`, `EmailQueuePage`, `AiBridgePage`, `ActionProposalsPage`, `IntelligencePage`
- `C:\PZ-verify\service\app\static\v2\wireframe-update.jsx` — `CoverageMapPage`, `ActionCenterPage`, `IdentityMappingPage`, `MoveStockPage`, `SampleOutPage`, `SampleReturnPage`, `GoodsReturnPage`, `ReturnToProducerPage`, `OperationalStatusStrip`
- `C:\PZ-verify\service\app\static\v2\ops-cell.jsx` — `WarehouseScannerPage`, `ReservationCellPage`, `WfirmaMappingPage`, `DiagnosticsPage`
- `C:\PZ-verify\service\app\static\v2\shipment-detail-page.jsx` — `ShipmentDetailPage` (live authority)
- `C:\PZ-verify\service\app\static\v2\shipment-detail-page.v1.jsx` — `ShipmentDetailPage` (dead versioned copy, not loaded by index.html)
- `C:\PZ-verify\service\app\static\v2\shipment-detail-page.v2.jsx` — `ShipmentDetailPage` (dead versioned copy, not loaded by index.html)
- `C:\PZ-verify\service\app\static\atlas\atlas-shared.js` — `ATLAS_PAGES` nav array (lines 140–151)
- `C:\PZ-verify\service\app\main.py` — route registrations for `/login`, `/signup`, `/forgot-password`, `/admin/users`, `/dashboard/*`, `/v2/*` (lines 562–738)
- `C:\PZ-verify\service\app\static\pz-design-v2.js` — pre-V2 shell routing table (lines 96–108) confirms legacy HTML files were the previous navigation authority
