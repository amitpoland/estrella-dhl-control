# Navigation Map

**Base SHA:** aa414d90
**Census timestamp:** 2026-07-01T015910Z
**Inspector agent:** navigation-inspector
**Mode:** READ-ONLY — no app code was modified
---

# Navigation Map

**Base SHA:** aa414d90
**Total slugs wired:** 34
**Redirects:** 12
**Menu items visible:** 18

## SPA Router Table

| Slug | Full URL | Component | Wired | In Menu | Redirects To |
|---|---|---|---|---|---|
| dashboard | /v2/dashboard | DashboardKanban (via DashboardPage) | YES | YES | — |
| inbox | /v2/inbox | InboxPage | YES | YES | — |
| shipments | /v2/shipments | DashboardPage | YES | YES | — |
| detail | /v2/detail | ShipmentDetailPage | YES | NO | — |
| dhl | /v2/dhl | DhlCustomsPage | YES | YES | — |
| proforma | /v2/proforma | ProformaListPage | YES | YES | — |
| proforma_detail | /v2/proforma_detail | ProformaDetailPage | YES | NO | — |
| proforma_search | /v2/proforma_search | ProformaSearchPage | YES | NO | — |
| documents | /v2/documents | DocumentsHubPage | YES | YES | — |
| accounting | /v2/accounting | AccountingHub (AccountingPage) | YES | YES | — |
| inventory | /v2/inventory | InventoryPage | YES | YES | — |
| reports | /v2/reports | ReportsPage | YES | YES | — |
| admin | /v2/admin | AdminSettingsPage | YES | YES (Setup) | — |
| master | /v2/master | MasterPage | YES | YES (Setup) | — |
| carriers | /v2/carriers | CarriersPage | YES | YES (Setup) | — |
| wfirma_setup | /v2/wfirma_setup | WfirmaMappingPage | YES | YES (Setup) | — |
| api_status | /v2/api_status | ApiStatusPage | YES | YES (Setup) | — |
| diagnostics | /v2/diagnostics | DiagnosticsPage | YES | YES (Setup) | — |
| automation | /v2/automation | AiBridgePage | YES | YES (Setup) | — |
| intelligence | /v2/intelligence | IntelligencePage | YES | YES (Setup) | — |
| coverage | /v2/coverage | CoverageMapPage | YES | YES (Setup) | — |
| actions | /v2/actions | ActionCenterPage | YES | NO | inbox |
| proposals | /v2/proposals | ActionProposalsPage | YES | NO | inbox |
| email_queue | /v2/email_queue | EmailQueuePage | YES | NO | inbox |
| reservation | /v2/reservation | ReservationCellPage | YES | NO | inbox |
| shipping | /v2/shipping | ShippingOpsPage | YES | NO | shipments |
| scanner | /v2/scanner | WarehouseScannerPage | YES | NO | inventory |
| move_stock | /v2/move_stock | MoveStockPage | YES | NO | inventory |
| identity | /v2/identity | IdentityMappingPage | YES | NO | inventory |
| sample_out | /v2/sample_out | SampleOutPage | YES | NO | inventory |
| sample_return | /v2/sample_return | SampleReturnPage | YES | NO | inventory |
| goods_return | /v2/goods_return | GoodsReturnPage | YES | NO | inventory |
| return_prod | /v2/return_prod | ReturnToProducerPage | YES | NO | inventory |

## Visible Menu Tree

- Dashboard (`dashboard`)
- Inbox (`inbox`) [badge: NEW]
- Shipments (`shipments`)
- DHL (`dhl`)
- Pro Forma (`proforma`)
- Documents (`documents`)
- Accounting (`accounting`) [badge: NEW]
- Inventory (`inventory`)
- Reports (`reports`)
- Setup (`g_setup`) [group — collapses/expands]
  - Settings (`admin`)
  - Master Data (`master`)
  - Carriers (`carriers`)
  - wFirma (`wfirma_setup`)
  - API Status (`api_status`)
  - Diagnostics (`diagnostics`)
  - Automation (`automation`)
  - Intelligence Hub (`intelligence`)
  - Coverage Map (`coverage`)

## Mismatches

### Invisible routes (wired but not in menu)
- `detail` → ShipmentDetailPage (entered programmatically via row click from Shipments)
- `proforma_detail` → ProformaDetailPage (entered via drill-down from Pro Forma list)
- `proforma_search` → ProformaSearchPage (entered via button on Pro Forma header, not sidebar)
- `actions` → ActionCenterPage (redirect target is `inbox`; component renders if navigated directly before redirect fires)
- `proposals` → ActionProposalsPage (redirect target is `inbox`)
- `email_queue` → EmailQueuePage (redirect target is `inbox`)
- `reservation` → ReservationCellPage (redirect target is `inbox`)
- `shipping` → ShippingOpsPage (redirect target is `shipments`)
- `scanner` → WarehouseScannerPage (redirect target is `inventory`)
- `move_stock` → MoveStockPage (redirect target is `inventory`)
- `identity` → IdentityMappingPage (redirect target is `inventory`)
- `sample_out` → SampleOutPage (redirect target is `inventory`)
- `sample_return` → SampleReturnPage (redirect target is `inventory`)
- `goods_return` → GoodsReturnPage (redirect target is `inventory`)
- `return_prod` → ReturnToProducerPage (redirect target is `inventory`)

### Broken menu items (in menu but not wired)
(None — every menu item has a corresponding wired page renderer in index.html)

### Redirect shadows (slug in both WIRED_PAGES and ROUTE_REDIRECTS)
- `actions` → redirects to `inbox` (ActionCenterPage component exists and renders at `page === 'actions'`, but `handleNav('actions')` and direct URL `/v2/actions` both resolve to `inbox` via ROUTE_REDIRECTS before `setPage` is called — ActionCenterPage is effectively unreachable at runtime via URL or sidebar)
- `proposals` → redirects to `inbox` (ActionProposalsPage exists but unreachable via URL/nav)
- `email_queue` → redirects to `inbox` (EmailQueuePage exists but unreachable via URL/nav)
- `reservation` → redirects to `inbox` (ReservationCellPage exists but unreachable via URL/nav)
- `shipping` → redirects to `shipments` (ShippingOpsPage exists but unreachable via URL/nav)
- `scanner` → redirects to `inventory` (WarehouseScannerPage exists but unreachable via URL/nav)
- `move_stock` → redirects to `inventory` (MoveStockPage exists but unreachable via URL/nav)
- `identity` → redirects to `inventory` (IdentityMappingPage exists but unreachable via URL/nav)
- `sample_out` → redirects to `inventory` (SampleOutPage exists but unreachable via URL/nav)
- `sample_return` → redirects to `inventory` (SampleReturnPage exists but unreachable via URL/nav)
- `goods_return` → redirects to `inventory` (GoodsReturnPage exists but unreachable via URL/nav)
- `return_prod` → redirects to `inventory` (ReturnToProducerPage exists but unreachable via URL/nav)

### Legacy nav dead links (pz-design-v2.js)

The `NAV_ROUTES` table in `pz-design-v2.js` maps slugs to standalone `/dashboard/` HTML files that pre-date the unified `/v2/index.html` SPA. All of these are stale:

- `dashboard` → `/dashboard/dashboard-v2.html`: replaced by `/v2/` SPA; file may not exist under current static layout
- `inbox` → `/dashboard/inbox-v2.html`: replaced by `/v2/inbox` SPA route; separate HTML file retired
- `shipments` → `/dashboard/shipment-detail-v3.html`: replaced by `/v2/shipments` SPA route
- `proforma` → `/dashboard/proforma-v2.html`: replaced by `/v2/proforma` SPA route
- `proforma-detail` → `/dashboard/proforma-detail-v2.html`: replaced by `/v2/proforma_detail` SPA route (slug also differs: hyphen vs underscore)
- `documents` → `/dashboard/documents-v2.html`: replaced by `/v2/documents` SPA route
- `accounting` → `/dashboard/accounting-hub-v2.html`: replaced by `/v2/accounting` SPA route
- `inventory` → `/dashboard/inventory-v2.html`: replaced by `/v2/inventory` SPA route
- `reports` → `/dashboard/dashboard.html`: stale V1 target, replaced by `/v2/reports`
- `master` → `/dashboard/customer-master-v2.html`: replaced by `/v2/master` SPA route
- `box-types` → `/dashboard/master-data-v2.html`: slug `box-types` is present in pz-design-v2.js NAV_TREE (under Setup) but is absent from components.jsx NAV_TREE and has no wired page in index.html — entirely dead
- `admin` → `/dashboard/admin-users.html`: replaced by `/v2/admin` SPA route
- `api_status` → `/dashboard/ai-advisory-v2.html`: replaced by `/v2/api_status` SPA route; target filename also misleading (ai-advisory vs api-status)

Additionally, `pz-design-v2.js` NAV_TREE is missing the `dhl` entry (added in Sprint 31 only to `components.jsx`), so the legacy nav has no path to the DHL Hub.

### Atlas nav dead links (atlas-shared.js)

The `ATLAS_PAGES` array in `atlas-shared.js` links to `/dashboard/atlas/<name>-v2.html` files. The following linked targets do not exist on disk under `service/app/static/atlas/`:

- `inbox` → `/dashboard/atlas/inbox-v2.html`: file absent from disk (INFERRED)
- `accounting` → `/dashboard/atlas/accounting-v2.html`: file absent from disk (INFERRED)

The following `ATLAS_PAGES` entries target files that exist on disk:
- `dashboard` → `/dashboard/atlas/dashboard-v2.html` ✓
- `shipments` → `/dashboard/atlas/shipments-v2.html` ✓
- `documents` → `/dashboard/atlas/documents-v2.html` ✓
- `pz` → `/dashboard/atlas/pz-v2.html` ✓
- `proforma` → `/dashboard/atlas/proforma-v2.html` ✓
- `ledgers` → `/dashboard/atlas/ledgers-v2.html` ✓
- `search` → `/dashboard/atlas/search-v2.html` ✓
- `api_status` → `/dashboard/atlas/api-status-v2.html` ✓

The `pz` slug in ATLAS_PAGES has no equivalent wired page in the `/v2/` SPA index.html (no `page === 'pz'` branch). The Atlas pages are a parallel legacy navigation layer and are not integrated into the main SPA router.

## Sources

- `C:\PZ-verify\service\app\static\v2\index.html` lines 1–926 — primary SPA shell; ROUTE_REDIRECTS (lines 361–373), page rendering conditionals (lines 591–893)
- `C:\PZ-verify\service\app\static\v2\components.jsx` lines 1–148 — canonical NAV_TREE used by the Sidebar component loaded in the SPA (Sprint 31 version, includes `dhl`)
- `C:\PZ-verify\service\app\static\pz-design-v2.js` lines 1–400 — legacy shared component module; contains older NAV_TREE (lines 70–92) missing `dhl`, contains `box-types`; NAV_ROUTES (lines 95–109) pointing to deprecated `/dashboard/` HTML paths
- `C:\PZ-verify\service\app\static\atlas\atlas-shared.js` lines 1–200 — Atlas V2 shared primitives; ATLAS_PAGES (lines 140–151) cross-page nav strip
- `C:\PZ-verify\service\app\static\v2\pages.jsx` lines 1–1048 — DhlClearancePage, CustomsDocumentsPage, PzAccountingPage, WarehousePage, SalesProformaPage, WfirmaExportPage, ReportsPage, LearningParserPage, AdminSettingsPage
- `C:\PZ-verify\service\app\static\v2\pages-v2.jsx` lines 1–1662 — DhlCustomsPage, AccountingPage, EmailQueuePage, AiBridgePage, ActionProposalsPage, IntelligencePage, ReportsPage (override)
- `C:\PZ-verify\service\app\static\v2\wireframe-update.jsx` — CoverageMapPage (line 178), ActionCenterPage (line 338), IdentityMappingPage (line 465), MoveStockPage (line 484), SampleOutPage (line 503), SampleReturnPage (line 521), GoodsReturnPage (line 539), ReturnToProducerPage (line 557)
- `C:\PZ-verify\service\app\static\v2\ops-cell.jsx` — WarehouseScannerPage (line 94), ReservationCellPage (line 274), WfirmaMappingPage (line 599), DiagnosticsPage (line 1002)
- `C:\PZ-verify\service\app\static\v2\master-page.jsx` line 391 — MasterPage
- `C:\PZ-verify\service\app\static\v2\inventory-page.jsx` line 673 — InventoryPage; line 25 — DocumentViewerPage
- `C:\PZ-verify\service\app\static\v2\proforma-list.jsx` line 36 — ProformaListPage
- `C:\PZ-verify\service\app\static\v2\proforma-detail.jsx` line 1844 — ProformaDetailPage
- `C:\PZ-verify\service\app\static\v2\proforma-search.jsx` line 9 — ProformaSearchPage
- `C:\PZ-verify\service\app\static\v2\dashboard-page.jsx` line 39 — DashboardPage
- `C:\PZ-verify\service\app\static\v2\dashboard-kanban.jsx` line 275 — DashboardKanban
- `C:\PZ-verify\service\app\static\v2\inbox-page.jsx` line 540 — InboxPage
- `C:\PZ-verify\service\app\static\v2\shipment-detail-page.jsx` line 274 — ShipmentDetailPage (canonical; loaded by index.html line 299)
- `C:\PZ-verify\service\app\static\v2\carriers-page.jsx` line 125 — CarriersPage
- `C:\PZ-verify\service\app\static\v2\api-status-page.jsx` line 367 — ApiStatusPage
- `C:\PZ-verify\service\app\static\v2\documents-hub.jsx` line 69 — DocumentsHubPage
- `C:\PZ-verify\service\app\static\v2\shipping-ops.jsx` line 72 — ShippingOpsPage
- `C:\PZ-verify\service\app\static\v2\ledgers-page.jsx` line 79 — LedgersPage
- Disk glob of `C:\PZ-verify\service\app\static\atlas\` — confirmed present: dashboard-v2.html, documents-v2.html, ledgers-v2.html, proforma-v2.html, pz-v2.html, search-v2.html, shipments-v2.html, api-status-v2.html; confirmed absent: inbox-v2.html, accounting-v2.html
