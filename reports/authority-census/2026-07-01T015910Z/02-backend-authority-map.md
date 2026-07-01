# Backend Authority Map

**Base SHA:** aa414d90
**Census timestamp:** 2026-07-01T015910Z
**Inspector agent:** backend-route-inspector
**Mode:** READ-ONLY — no app code was modified
---

# Backend Authority Map

**Base SHA:** aa414d90
**Route files found:** 78 (77 active, 1 dead)
**Registered routers:** 88 `include_router` calls in `main.py` (some files export multiple router objects; `dashboard_router` mounted twice by design)
**Duplicate-prefix groups:** 14

## Route File Table

| Domain | Prefix | Route File(s) | Endpoints | In main.py | Collision Risk | Notes |
|---|---|---|---|---|---|---|
| PZ Engine | `/api/v1` | `routes_pz.py` | 16 | YES | HIGH | Bare `/api/v1` prefix shares namespace with `routes_lifecycle.py` |
| Lifecycle | `/api/v1` | `routes_lifecycle.py` | 8 | YES | HIGH | Bare `/api/v1` prefix; path segments are distinct (`/agency-documents/`, `/service-invoices/`, `/closure/`, `/lifecycle/`, `/inventory-state/`) |
| Dashboard | `/dashboard` + `/api/v1/dashboard` | `routes_dashboard.py` | 32 | YES (double-mounted: bare + `prefix="/api/v1"`) | MEDIUM | Intentional alias mount; both mounts point to same handlers. Documented in main.py comment. |
| Bot / Cliq | `/api/v1/cliq` | `routes_bot.py` | 1 | YES | NONE | — |
| Batch (Cliq legacy) | `/api/v1/batch` | `routes_batch.py` | 8 | YES | MEDIUM | Shares prefix with `routes_batch_readiness.py`; paths non-overlapping |
| Batch Readiness | `/api/v1/batch` | `routes_batch_readiness.py` | 1 | YES | MEDIUM | Path: `/{batch_id}/readiness`; distinct from `routes_batch.py` sub-paths |
| Debug | `/api/v1/debug` | `routes_debug.py` | 6 | YES | NONE | — |
| Upload / Shipment | `/api/v1/upload` | `routes_upload.py` | 7 | YES | HIGH | Same prefix as `routes_wfirma.py`; both mount under `/api/v1/upload/shipment/{batch_id}/` |
| wFirma Export | `/api/v1/upload` | `routes_wfirma.py` | 12 | YES | HIGH | Sub-paths: `/{batch_id}/wfirma/*`, `/{batch_id}/pz_preview`, `/{batch_id}/pz_create` etc. Intentional design but no documented ordering guarantee. |
| Auth | `/auth` | `routes_auth.py` | 13 | YES | NONE | — |
| Admin Core | `/api/v1/admin` | `routes_admin.py` | 5 | YES | LOW | Sub-prefixes used by backup/runtime-flags/dhl-clearance/contractor-projection avoid overlap |
| Admin Backup | `/api/v1/admin/backup` | `routes_admin_backup.py` | 4 | YES | LOW | Sub-prefix of `/api/v1/admin` family |
| Admin DHL Clearance | `/api/v1/admin/dhl-clearance` | `routes_admin_dhl_clearance.py` | 1 | YES | LOW | Sub-prefix of `/api/v1/admin` family |
| Admin Runtime Flags | `/api/v1/admin/runtime-flags` | `routes_admin_runtime_flags.py` | 2 | YES | LOW | Sub-prefix of `/api/v1/admin` family |
| Contractor Projection | `/api/v1/admin/contractor-projection` | `routes_contractor_projection.py` | 3 | YES | LOW | Sub-prefix of `/api/v1/admin` family |
| Tracking (live) | `/api/v1/tracking` | `routes_tracking.py` | 5 | YES | MEDIUM | Shares prefix with `routes_tracking_db.py`; main.py comment notes DB router registered before tracking router to avoid `/{tracking_no}` eating `/events/*` |
| Tracking DB | `/api/v1/tracking` | `routes_tracking_db.py` | 4 | YES | MEDIUM | Path: `/events/{batch_id}`, `/events`, `/events/export`; mounted BEFORE `routes_tracking.py` per main.py comment line 508 |
| Invoice Learning | `/api/v1/invoice-learning` | `routes_learning.py` | 4 | YES | NONE | — |
| Proposals | `/api/v1/proposals` | `routes_proposals.py` | 6 | YES | NONE | — |
| DSK | `/api/v1/dsk` | `routes_dsk.py` | 4 | YES | NONE | — |
| DHL Clearance | `/api/v1/dhl` | `routes_dhl_clearance.py` | 17 | YES | MEDIUM | Shares `/api/v1/dhl` prefix with `routes_dhl_readiness.py`; paths non-overlapping |
| DHL Readiness | `/api/v1/dhl` | `routes_dhl_readiness.py` | 1 | YES | MEDIUM | Path: `/readiness/{batch_id}`; distinct from `routes_dhl_clearance.py` paths |
| Agency | `/api/v1/agency` | `routes_agency.py` | 2 | YES | NONE | — |
| wFirma Core | `/api/v1/wfirma` | `routes_wfirma_capabilities.py` | 27 | YES | HIGH | Three files share `/api/v1/wfirma`; no documented ordering guarantee |
| wFirma Reservation | `/api/v1/wfirma` | `routes_wfirma_reservation.py` | 3 | YES | HIGH | Sub-paths: `/reservation-preview/*`, `/reservations/*`; distinct but no ordering lock |
| wFirma Contractors | `/api/v1/wfirma` | `routes_wfirma_contractors.py` | 2 | YES | HIGH | Sub-paths: `/contractors/scan`, `/contractors/scan/status` |
| Analytics | `/api/v1/analytics` | `routes_analytics.py` | 1 | YES | NONE | — |
| Intelligence | `/api/v1/intelligence` | `routes_intelligence.py` | 9 | YES | MEDIUM | Shares prefix with `routes_intelligence_graph.py`; graph router adds `/graph` sub-path |
| Intelligence Graph | `/api/v1/intelligence` | `routes_intelligence_graph.py` | 1 | YES | MEDIUM | Path: `/graph`; distinct from `routes_intelligence.py` paths |
| Action Proposals | `/api/v1/action-proposals` | `routes_action_proposals.py` | 6 | YES | NONE | — |
| AI Bridge | `/api/v1/ai-bridge` | `routes_ai_bridge.py` | 7 | YES | NONE | — |
| Monitor | `/api/v1/monitor` | `routes_monitor.py` | 1 | YES | NONE | — |
| Orchestrator | `/api/v1/orchestrator` | `routes_orchestrator.py` | 3 | YES | NONE | — |
| DHL Followup | `/api/v1/dhl-followup` | `routes_dhl_followup.py` | 6 | YES | NONE | — |
| DHL Followup Status | `/api/v1/dhl/followup-automation` | `routes_dhl_followup_status.py` | 2 | YES | NONE | Sub-path of `/api/v1/dhl` family but distinct sub-segment |
| DHL Documents | `/api/v1/dhl-documents` | `routes_dhl_documents.py` | 2 | YES | NONE | — |
| Intake | `/api/v1/shipment` | `routes_intake.py` | 4 | YES | NONE | — |
| Execute | `/api/v1/execute` | `routes_execute.py` | 1 | YES | NONE | — |
| AI Advisory | `/api/v1/ai/advisory` | `routes_ai_advisory.py` | 2 | YES | NONE | — |
| Master Data Intelligence | `/api/v1/master-data/intelligence` | `routes_mdi.py` | 2 | YES | NONE | — |
| Search | `/api/v1/search` | `routes_search.py` | 1 | YES | NONE | — |
| Inbox | `/api/v1/inbox` | `routes_inbox.py` | 2 | YES | NONE | — |
| Workflow Intelligence | `/api/v1/workflow` | `routes_workflow_intelligence.py` | 1 | YES | NONE | — |
| Operations Intelligence | `/api/v1/operations` | `routes_operations_intelligence.py` | 1 | YES | NONE | — |
| Settings | `/api/v1/settings` | `routes_settings.py` | 2 | YES | NONE | — |
| System | `/api/v1/system` | `routes_system.py` | 1 | YES | NONE | — |
| Deploy Status | `/api/v1/deploy` | `routes_deploy_status.py` | 1 | YES | NONE | — |
| Agents | `/api/v1/agents` | `routes_agents.py` | 1 | YES | NONE | — |
| Packing | `/api/v1/packing` | `routes_packing.py` | 18 | YES | MEDIUM | Shares prefix with `routes_packing_resolution.py`; resolution adds `/{batch_id}/contractor-resolution*` paths, distinct |
| Packing Dev | `/api/v1/dev` | `routes_packing.py` (dev_router) | (part of 18 total) | YES | NONE | Exported as `dev_router` from same file |
| Packing Resolution | `/api/v1/packing` | `routes_packing_resolution.py` | 4 | YES | MEDIUM | Sub-paths: `/{batch_id}/contractor-resolution*`; distinct from `routes_packing.py` |
| Sales | `/api/v1/sales` | `routes_sales.py` | 1 | YES | NONE | — |
| Proforma | `/api/v1/proforma` | `routes_proforma.py` | 56 | YES | MEDIUM | Shares prefix with `routes_proforma_adopt.py`; adopt adds `/adopt-issued/*` and `/enrich-fullnumber/*`, distinct |
| Proforma Adopt | `/api/v1/proforma` | `routes_proforma_adopt.py` | 2 | YES | MEDIUM | Sub-paths: `/adopt-issued/*`, `/enrich-fullnumber/*` |
| Warehouse | `/api/v1/warehouse` | `routes_warehouse.py` | 6 | YES | MEDIUM | Shares `/api/v1/warehouse` with `routes_warehouse_audit.py`; audit adds `/audit/*`, receipt uses sub-prefix `/receipt` |
| Warehouse Audit | `/api/v1/warehouse` | `routes_warehouse_audit.py` | 2 | YES | MEDIUM | Path: `/audit/{batch_id}*` |
| Warehouse Receipt | `/api/v1/warehouse/receipt` | `routes_warehouse_receipt.py` | 2 | YES | LOW | Sub-prefix of `/api/v1/warehouse`; distinct segment |
| Correction Registry | `/api/v1/corrections` | `routes_correction_registry.py` | 9 | YES | NONE | — |
| Ledgers | `/api/v1/ledgers` | `routes_ledgers.py` | 3 | YES | NONE | — |
| Carrier Webhook | `/api/v1/carrier/webhook` | `routes_carrier_webhook.py` | 1 | YES | NONE | Sub-segment of `/api/v1/carrier`; distinct; mounted before carrier_shadow |
| Webhooks wFirma | `/api/v1/webhooks` | `routes_webhooks_wfirma.py` | 1 | YES | MEDIUM | Shares prefix with `routes_webhooks_wfirma_status.py`; status adds `/wfirma/status` |
| Webhooks wFirma Status | `/api/v1/webhooks` | `routes_webhooks_wfirma_status.py` | 1 | YES | MEDIUM | Path: `/wfirma/status`; distinct from receiver |
| Carrier Shadow | `/api/v1/carrier` | `routes_carrier_shadow.py` | 2 | YES | HIGH | Both shadow and actions share `/api/v1/carrier`; main.py comment requires shadow mounted before actions |
| Carrier Actions | `/api/v1/carrier` | `routes_carrier_actions.py` | 4 | YES | HIGH | Dynamic `/{batch_id}/shipment` path risks swallowing static `/shadow/log` and `/status` if order reversed |
| Inventory | `/api/v1/inventory` | `routes_inventory.py` | 3 | YES | MEDIUM | Four files share `/api/v1/inventory`; all use `/{piece_id}/…` sub-paths except inventory.py's `/stage2/aggregate` |
| Inventory Writes | `/api/v1/inventory` | `routes_inventory_writes.py` | 1 | YES | MEDIUM | Path: `/pieces/{piece_id}/location` |
| Inventory Sample | `/api/v1/inventory` | `routes_inventory_sample.py` | 2 | YES | MEDIUM | Paths: `/pieces/{piece_id}/sample-out`, `/pieces/{piece_id}/sample-return` |
| Inventory Returns | `/api/v1/inventory` | `routes_inventory_returns.py` | 3 | YES | MEDIUM | Paths: `/pieces/{piece_id}/return-*` |
| Description Admin | `/api/v1/description-admin` | `routes_description_admin.py` | 3 | YES | NONE | — |
| Customer Master | `/api/v1/customer-master` | `routes_customer_master.py` | 10 | YES | LOW | Client-addresses and carrier-accounts use `/{contractor_id}/…` sub-paths; no overlap with list/read/upsert |
| Client Addresses | `/api/v1/customer-master/{contractor_id}/shipping-addresses` | `routes_client_addresses.py` | 5 | YES | LOW | Sub-resource of customer-master |
| Client Carrier Accounts | `/api/v1/customer-master/{contractor_id}/carrier-accounts` | `routes_client_carrier_accounts.py` | 5 | YES | LOW | Sub-resource of customer-master |
| Suppliers | `/api/v1/suppliers` | `routes_suppliers.py` | 9 | YES | NONE | — |
| HS Codes | `/api/v1/hs-codes` | `routes_master_data.py` (hs_router) | 6 | YES | NONE | — |
| Units | `/api/v1/units` | `routes_master_data.py` (units_router) | 5 | YES | NONE | — |
| Product Local | `/api/v1/product-local` | `routes_master_data.py` (pl_router) | 6 | YES | NONE | — |
| Incoterms | `/api/v1/incoterms` | `routes_master_data.py` (incoterms_router) | 5 | YES | NONE | — |
| VAT Config | `/api/v1/vat-config` | `routes_master_data.py` (vat_router) | 4 | YES | NONE | — |
| FX Rates | `/api/v1/fx-rates` | `routes_master_data.py` (fx_router) | 4 | YES | NONE | — |
| Carriers Config | `/api/v1/carriers-config` | `routes_master_data.py` (carriers_config_router) | 4 | YES | NONE | — |
| Designs | `/api/v1/designs` | `routes_master_data.py` (designs_router) | 5 | YES | NONE | — |
| Master Audit | `/api/v1/master/audit` | `routes_master_data.py` (audit_router) | 4 | YES | NONE | — |
| Metals | `/api/v1/metals` | `routes_master_jewelry.py` (metals_router) | 5 | YES | NONE | — |
| Stones | `/api/v1/stones` | `routes_master_jewelry.py` (stones_router) | 5 | YES | NONE | — |
| Warehouses Master | `/api/v1/warehouses` | `routes_master_jewelry.py` (warehouses_router) | 5 | YES | NONE | — |
| Box Types | `/api/v1/box-types` | `routes_box_types.py` (box_types_router) | 4 | YES | NONE | — |
| Finance Postings | `/api/v1/finance/postings` | `routes_finance_postings.py` | 1 | YES | NONE | — |
| Reservations (DEAD) | `/api/v1` | `routes_reservations.py` | 6 | **NO** | — | DEAD — not imported in main.py |

## Dead routes

| File | Endpoints | Orphaned service? | Action |
|---|---|---|---|
| `service/app/api/routes_reservations.py` | 6 (`POST /api/v1/products/import-purchase-packing`, `POST /api/v1/reservations/import-sales-packing`, `GET /api/v1/reservations/queue`, `POST /api/v1/wfirma/products/sync-by-codes`, `POST /api/v1/reservations/process-pending`, `POST /api/v1/reservations/{queue_id}/reset`) | YES — `reservation_queue.db` is initialised at startup via `init_reservation_db` (main.py line 188) and the DB init is noted in lifespan commentary as backing the reservation routes; `routes_wfirma_reservation.py` (which IS active) also uses `reservation_queue.db` indirectly, but the sync endpoints in this dead file have no live surface | Register router in main.py or formally retire and document as superseded by `routes_wfirma_reservation.py` |

## Duplicate-prefix groups

| Risk | Prefix | Files | Issue |
|---|---|---|---|
| HIGH | `/api/v1/upload` | `routes_upload.py`, `routes_wfirma.py` | Both mount under `/api/v1/upload/shipment/{batch_id}/…`; no documented FastAPI ordering guarantee for sub-paths that differ only at depth 4. Main.py registers `upload_router` before `wfirma_router` (lines 466, 470). |
| HIGH | `/api/v1/wfirma` | `routes_wfirma_capabilities.py`, `routes_wfirma_reservation.py`, `routes_wfirma_contractors.py` | Three routers share the same bare prefix with 32 combined endpoints; no ordering comment in main.py; capability router has 27 endpoints including dynamic `/{product_code}` and `/{client_name}` paths that could shadow reservation and contractor paths depending on FastAPI route-matching order. |
| HIGH | `/api/v1/carrier` | `routes_carrier_shadow.py`, `routes_carrier_actions.py` | `routes_carrier_actions.py` declares dynamic `/{batch_id}/shipment` which could shadow `/shadow/log` and `/status` if mount order were reversed; main.py comment on line 514 explicitly states shadow registered before actions to protect static paths. Current order is safe but fragile. |
| HIGH | `/api/v1` (bare) | `routes_pz.py`, `routes_lifecycle.py` | Both use the bare `/api/v1` prefix with no sub-prefix grouping. `routes_pz.py` has 16 endpoints with paths like `/pz/process`, `/health`, `/feedback`, `/learning/summary`, `/pz/lineage/…`, `/files/…`. `routes_lifecycle.py` has 8 endpoints under different path segments. No documented ordering guarantee; FastAPI will resolve by first-match. |
| MEDIUM | `/api/v1/batch` | `routes_batch.py`, `routes_batch_readiness.py` | `routes_batch_readiness.py` adds `/{batch_id}/readiness` under the same prefix; non-overlapping with `routes_batch.py` sub-paths but no ordering comment. |
| MEDIUM | `/api/v1/tracking` | `routes_tracking.py`, `routes_tracking_db.py` | Dynamic `/{tracking_no}` in `routes_tracking.py` would match `/events` if DB router not mounted first. Main.py line 508 comment explicitly documents ordering requirement. Risk is mitigated by documented order. |
| MEDIUM | `/api/v1/dhl` | `routes_dhl_clearance.py`, `routes_dhl_readiness.py` | 17 + 1 endpoints; paths non-overlapping (`/scan-inbox`, `/match-and-handle`, `/clearance-status/*`, `/generate-description/*`, `/download/*`, `/generate-customs-package/*`, `/sad-ready/*`, `/approve/*` vs `/readiness/*`). |
| MEDIUM | `/api/v1/intelligence` | `routes_intelligence.py`, `routes_intelligence_graph.py` | `routes_intelligence_graph.py` adds `/graph` sub-path; distinct from all `routes_intelligence.py` paths (`/suggestions`, `/config`, `/refresh`, `/actors`, `/classify`, `/status`). |
| MEDIUM | `/api/v1/webhooks` | `routes_webhooks_wfirma.py`, `routes_webhooks_wfirma_status.py` | Receiver: `POST /api/v1/webhooks/wfirma`; Status: `GET /api/v1/webhooks/wfirma/status`. Same leading path segment; HTTP method differs for `/wfirma` vs sub-path `/wfirma/status`. |
| MEDIUM | `/api/v1/packing` | `routes_packing.py`, `routes_packing_resolution.py` | Resolution router adds `/{batch_id}/contractor-resolution*`; distinct from packing router paths. |
| MEDIUM | `/api/v1/proforma` | `routes_proforma.py`, `routes_proforma_adopt.py` | Adopt router adds `/adopt-issued/*` and `/enrich-fullnumber/*`; `routes_proforma.py` has 56 endpoints. Path separation appears adequate. |
| MEDIUM | `/api/v1/warehouse` | `routes_warehouse.py`, `routes_warehouse_audit.py` | Audit adds `/audit/{batch_id}*`; distinct from warehouse paths (`/config`, `/scan`, `/inventory/*`, `/locations*`). |
| MEDIUM | `/api/v1/inventory` | `routes_inventory.py`, `routes_inventory_writes.py`, `routes_inventory_sample.py`, `routes_inventory_returns.py` | All four share prefix; paths differentiated by terminal verb suffixes (`/location`, `/sample-out`, `/sample-return`, `/return-*`). |
| LOW | `/api/v1/admin` family | `routes_admin.py`, `routes_admin_backup.py`, `routes_admin_runtime_flags.py`, `routes_admin_dhl_clearance.py`, `routes_contractor_projection.py` | Each uses a distinct sub-prefix (`/backup`, `/runtime-flags`, `/dhl-clearance`, `/contractor-projection`); no path overlap. |
| LOW | `/api/v1/customer-master` family | `routes_customer_master.py`, `routes_client_addresses.py`, `routes_client_carrier_accounts.py` | Sub-resources use `/{contractor_id}/shipping-addresses` and `/{contractor_id}/carrier-accounts`; distinct from core CRUD. |

## Orphaned services

(Services started at startup whose route file is not registered in main.py.)

| Service | Started at | Corresponding route file | Status |
|---|---|---|---|
| `reservation_queue.db` (via `init_reservation_db`) | `main.py` lifespan, line 188 — non-fatal try/except | `service/app/api/routes_reservations.py` | ORPHANED — DB is initialised and used at startup; the 6 operator-facing sync endpoints in `routes_reservations.py` are unreachable because the file is never imported or registered. `routes_wfirma_reservation.py` (active, line 504) provides reservation-preview and create endpoints but does NOT expose the import-packing or process-pending endpoints that `routes_reservations.py` declares. |

## Sources

| File | Lines read |
|---|---|
| `C:\PZ-verify\service\app\main.py` | 1–739 (full file) |
| `C:\PZ-verify\service\app\api\routes_pz.py` | 1–30, endpoint grep |
| `C:\PZ-verify\service\app\api\routes_dashboard.py` | 1–79 |
| `C:\PZ-verify\service\app\api\routes_bot.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_batch.py` | 1–90 |
| `C:\PZ-verify\service\app\api\routes_debug.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_upload.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_auth.py` | 1–30, 57 |
| `C:\PZ-verify\service\app\api\routes_admin.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_admin_backup.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_tracking.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_learning.py` | 1–20 |
| `C:\PZ-verify\service\app\api\routes_proposals.py` | 1–24 |
| `C:\PZ-verify\service\app\api\routes_dsk.py` | 1–15 |
| `C:\PZ-verify\service\app\api\routes_dhl_clearance.py` | 1–69 |
| `C:\PZ-verify\service\app\api\routes_agency.py` | 1–15 |
| `C:\PZ-verify\service\app\api\routes_wfirma.py` | 1–15, 105–215 |
| `C:\PZ-verify\service\app\api\routes_analytics.py` | 1–25 |
| `C:\PZ-verify\service\app\api\routes_intelligence.py` | 1–29 |
| `C:\PZ-verify\service\app\api\routes_action_proposals.py` | 1–50 |
| `C:\PZ-verify\service\app\api\routes_ai_bridge.py` | 1–41 |
| `C:\PZ-verify\service\app\api\routes_monitor.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_orchestrator.py` | 1–35 |
| `C:\PZ-verify\service\app\api\routes_dhl_followup.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_dhl_followup_status.py` | 1–40 |
| `C:\PZ-verify\service\app\api\routes_dhl_documents.py` | 1–35 |
| `C:\PZ-verify\service\app\api\routes_lifecycle.py` | 1–30, 24–105 |
| `C:\PZ-verify\service\app\api\routes_intake.py` | 1–65 |
| `C:\PZ-verify\service\app\api\routes_execute.py` | 1–40 |
| `C:\PZ-verify\service\app\api\routes_ai_advisory.py` | 1–40 |
| `C:\PZ-verify\service\app\api\routes_mdi.py` | 1–28 |
| `C:\PZ-verify\service\app\api\routes_operations_intelligence.py` | 1–50 |
| `C:\PZ-verify\service\app\api\routes_search.py` | 1–40 |
| `C:\PZ-verify\service\app\api\routes_tracking_db.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_workflow_intelligence.py` | 1–50 |
| `C:\PZ-verify\service\app\api\routes_settings.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_system.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_deploy_status.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_agents.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_packing.py` | 1–30, 3130 (dev_router) |
| `C:\PZ-verify\service\app\api\routes_packing_resolution.py` | 1–55 |
| `C:\PZ-verify\service\app\api\routes_box_types.py` | 1–45 |
| `C:\PZ-verify\service\app\api\routes_contractor_projection.py` | 1–55 |
| `C:\PZ-verify\service\app\api\routes_intelligence_graph.py` | 1–55 |
| `C:\PZ-verify\service\app\api\routes_inventory.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_inventory_returns.py` | 1–45 |
| `C:\PZ-verify\service\app\api\routes_inventory_sample.py` | 1–40 |
| `C:\PZ-verify\service\app\api\routes_inventory_writes.py` | 1–35 |
| `C:\PZ-verify\service\app\api\routes_sales.py` | 1–35 |
| `C:\PZ-verify\service\app\api\routes_proforma.py` | 1–65 |
| `C:\PZ-verify\service\app\api\routes_proforma_adopt.py` | 1–55 |
| `C:\PZ-verify\service\app\api\routes_batch_readiness.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_reservations.py` | 1–45 |
| `C:\PZ-verify\service\app\api\routes_dhl_readiness.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_webhooks_wfirma.py` | 1–45 |
| `C:\PZ-verify\service\app\api\routes_webhooks_wfirma_status.py` | 1–50 |
| `C:\PZ-verify\service\app\api\routes_wfirma_contractors.py` | 1–40 |
| `C:\PZ-verify\service\app\api\routes_wfirma_reservation.py` | 1–40 |
| `C:\PZ-verify\service\app\api\routes_wfirma_capabilities.py` | 1–55 |
| `C:\PZ-verify\service\app\api\routes_carrier_webhook.py` | 1–45 |
| `C:\PZ-verify\service\app\api\routes_carrier_actions.py` | 1–45 |
| `C:\PZ-verify\service\app\api\routes_carrier_shadow.py` | 1–35 |
| `C:\PZ-verify\service\app\api\routes_warehouse.py` | 1–50 |
| `C:\PZ-verify\service\app\api\routes_warehouse_audit.py` | 1–30 |
| `C:\PZ-verify\service\app\api\routes_warehouse_receipt.py` | 1–40 |
| `C:\PZ-verify\service\app\api\routes_correction_registry.py` | 1–35 |
| `C:\PZ-verify\service\app\api\routes_description_admin.py` | 1–45 |
| `C:\PZ-verify\service\app\api\routes_customer_master.py` | 1–60 |
| `C:\PZ-verify\service\app\api\routes_client_addresses.py` | 1–45 |
| `C:\PZ-verify\service\app\api\routes_client_carrier_accounts.py` | 1–45 |
| `C:\PZ-verify\service\app\api\routes_suppliers.py` | 1–60 |
| `C:\PZ-verify\service\app\api\routes_master_data.py` | 1–15, 134, 242, 349, 463, 573, 710, 850, 965, 1099 (router declarations) |
| `C:\PZ-verify\service\app\api\routes_master_jewelry.py` | 1–15, 125, 228, 330 (router declarations) |
| `C:\PZ-verify\service\app\api\routes_finance_postings.py` | 1–70 |
| `C:\PZ-verify\service\app\api\routes_ledgers.py` | 1–65 |
| `C:\PZ-verify\service\app\api\routes_inbox.py` | 1–50 |
| `C:\PZ-verify\service\app\api\routes_admin_dhl_clearance.py` | 1–75 |
| `C:\PZ-verify\service\app\api\routes_admin_runtime_flags.py` | 1–95 |
| Glob pattern `service/app/api/routes_*.py` | all 78 matches enumerated |
| Ripgrep `APIRouter(` across all route files | all declarations |
| Ripgrep `@router.(get\|post\|put\|delete\|patch)(` across all route files | endpoint counts per file |
