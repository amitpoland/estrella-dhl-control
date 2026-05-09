# System Inventory & UI Plan
**Date:** 2026-05-03  
**Purpose:** Full audit of every built module — status, location, tests, UI gap, and recommended action.  
**Rule:** No code changes based on this document until owner decisions are confirmed (Section 9).

---

## 1. Executive Summary

| Category | Count | Notes |
|---|---|---|
| API router files | 32 | All registered in main.py |
| Service modules | ~107 | Backend logic, parsers, builders, monitors |
| Database tables | 22 | Across packing.db, documents.db, warehouse.db, wfirma.db, tracking.db, users.db |
| Static HTML pages | 7 | dashboard, batch, warehouse, login, signup, forgot-password, admin-users |
| Dashboard nav items | 11 | Several link to unimplemented or partially-wired sections |
| Test files | 72 | 1 324 tests passing, 1 skipped |
| CLI diagnostic tools | 3 | check_dhl_config, check_wfirma_config, regenerate_stale_batches |

### System state in four sentences

**Stable core** (do not touch): PZ import processor, SAD/ZC429 parser, invoice/packing parser, document DB, DHL clearance pipeline, tracking DB, auth system, batch dashboard, Zoho Cliq delivery, WorkDrive upload.

**Partially active** (backend built, limited/no UI): Warehouse audit, sales linkage, wFirma reservation preview, tracking master export, intelligence engine, AI bridge, barcode/ZPL label, analytics, canonical filename system.

**Backend-only with no UI at all**: wFirma capabilities checker, wFirma config CLI, cowork coordinator, agency SLA engine, active shipment monitor sweep, event trigger engine, shipment closure, service invoice monitor.

**Blocked** (do not build on until gate passes): wFirma reservation create (`POST /reservations/create`) — blocked until `check_wfirma_config` is fully green.

---

## 2. Full Feature Inventory

### 2.1 Core Parsing & Processing

| # | Module | Key Files | DB Tables | Endpoints | UI Location | Status | Tests | Real Use | Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **PZ Import Processor** | `pipelines/pz.py`, `routes_pz.py` | `pz_documents` | `POST /api/v1/pz/process` | Dashboard → Batch → Pipeline tab (Run PZ button) | **ACTIVE** | ✅ | Every shipment | HIGH | Keep |
| 2 | **SAD/ZC429 XML Parser** | `customs_xml_parser.py`, `customs_parser_orchestrator.py` | `customs_declarations` | via PZ process | Dashboard → Batch → Audit Review | **ACTIVE** | ✅ `test_customs_ai_validation.py` | Every shipment | HIGH | Keep |
| 3 | **SAD/ZC429 PDF Parser** | `services/` (`parse_zc429` in orchestrator) | `customs_declarations` | via PZ process | Dashboard → Batch → Audit Review | **ACTIVE** | ✅ | Fallback to XML | HIGH | Keep |
| 4 | **AI Customs Parser** | `ai_customs_parser.py` | — | via orchestrator | hidden fallback | **ACTIVE (fallback)** | ✅ `test_customs_ai_validation.py` | Last-resort only | MEDIUM | Keep hidden |
| 5 | **Invoice Parser** | `invoice_intake_parser.py`, `invoice_packing_extractor.py` | `invoice_lines` | via intake/PZ | Dashboard → Batch → Documents tab | **ACTIVE** | ✅ `test_packing_db.py` | Every shipment | HIGH | Keep |
| 6 | **Packing List Parser** | `invoice_packing_extractor.py` | `packing_lines`, `packing_documents` | via intake/PZ | Dashboard → Batch → Documents tab | **ACTIVE** | ✅ `test_packing_db.py` | Every shipment | HIGH | Keep |
| 7 | **AWB Parser** | `awb_parser.py` | `awb_documents`, `shipment_documents` | `POST /api/v1/shipment` (intake) | Dashboard → Batch → Shipment Summary | **ACTIVE** | ✅ `test_intake.py` | Every shipment | HIGH | Keep |
| 8 | **Canonical Filename System** | `output_filenames.py` | — | internal | hidden | **ACTIVE** | ✅ `test_output_filenames.py` | Every output file | MEDIUM | Keep |
| 9 | **Audit Memo / Report** | `audit_merge.py`, `routes_batch.py` audit endpoints | — | `GET /api/v1/batch/audit/{batch_id}` | Dashboard → Batch → Audit Review tab | **ACTIVE** | ✅ `test_audit_merge.py` | Every shipment | HIGH | Keep |

### 2.2 DHL Clearance Pipeline

| # | Module | Key Files | DB Tables | Endpoints | UI Location | Status | Tests | Real Use | Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| 10 | **DHL Email Evidence** | `email_evidence_ingestor.py`, `email_evidence_store.py`, `email_evidence_processor.py` | `document_extracted_fields`, `document_extraction_json` | `GET /api/v1/batch/batches/{id}/email-evidence` | Dashboard → DHL Clearance nav item | **ACTIVE** | ✅ `test_email_evidence_v2.py` | Every DHL shipment | HIGH | Keep |
| 11 | **DHL Reply Builder** | `dhl_reply_builder.py`, `dhl_self_clearance_builder.py` | — | `POST /api/v1/dhl/send-reply/{batch_id}` | Dashboard → Batch → Required Actions | **ACTIVE** | ✅ `test_dhl_reply_builder.py` | Every DHL shipment | HIGH | Keep |
| 12 | **DHL Follow-up SLA** | `dhl_followup_sla.py`, `dhl_followup_email_builder.py` | — | `GET /api/v1/dhl-followup/reply-status/{id}` | hidden / background | **ACTIVE (background)** | ✅ `test_dhl_followup_sla.py` | Every DHL shipment | HIGH | Keep |
| 13 | **DSK Email Builder** | `routes_dsk.py`, `dhl_self_clearance_builder.py` | — | `POST /api/v1/dsk/generate` | Dashboard → Batch → Required Actions | **ACTIVE** | ✅ `test_self_clearance_flow.py` | Low-value shipments | MEDIUM | Keep |
| 14 | **Clearance Decision Engine** | `clearance_decision.py` | — | internal | hidden | **ACTIVE** | ✅ `test_self_clearance_flow.py` | Every shipment | HIGH | Keep |
| 15 | **DHL Document Classifier** | `dhl_document_classifier.py`, `attachment_pattern_engine.py` | — | internal | hidden | **ACTIVE** | ✅ `test_dhl_document_engine.py` | Every DHL email | MEDIUM | Keep |

### 2.3 Agency (Customs Broker) Pipeline

| # | Module | Key Files | DB Tables | Endpoints | UI Location | Status | Tests | Real Use | Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| 16 | **Agency Email Builder** | `agency_email_builder.py`, `agency_forward_after_dhl_builder.py` | — | `POST /api/v1/agency/email-package/{id}` | Dashboard → Batch → Required Actions | **ACTIVE** | ✅ `test_agency_flow_fix.py` | High-value shipments | HIGH | Keep |
| 17 | **Agency SAD Monitor** | `agency_sad_monitor.py` | — | `POST /api/v1/agency-documents/{id}/received` | Batch → Required Actions | **ACTIVE** | ✅ `test_agency_preclearance.py` | Every agency shipment | HIGH | Keep |
| 18 | **Agency SLA Engine** | `agency_sla_engine.py` | — | background | hidden | **ACTIVE (background)** | ✅ partial | Every agency shipment | HIGH | Keep |

### 2.4 Tracking

| # | Module | Key Files | DB Tables | Endpoints | UI Location | Status | Tests | Real Use | Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| 19 | **Tracking DB** | `tracking_db.py` | `shipment_tracking_events` | `GET /api/v1/tracking/events/{batch_id}` | Dashboard → Batch → Timeline tab | **ACTIVE** | ✅ `test_tracking_db.py` | Every shipment | HIGH | Keep |
| 20 | **Tracking Service** | `tracking_service.py`, `tracking_normalizer.py`, `tracking_intelligence.py` | — | `GET /api/v1/tracking/{tracking_no}` | Dashboard → Batch → Shipment Summary | **ACTIVE** | ✅ multiple | Every shipment | HIGH | Keep |
| 21 | **Tracking Master Export** | `tracking_master_export.py` | `shipment_tracking_events` | `POST /api/v1/tracking/events/export` | **NO UI PANEL** | **BACKEND-ONLY** | ✅ `test_tracking_db.py` | Not exposed | LOW | Expose in Admin/Reports |

### 2.5 Warehouse

| # | Module | Key Files | DB Tables | Endpoints | UI Location | Status | Tests | Real Use | Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| 22 | **Warehouse Scanner** | `warehouse_db.py`, `routes_warehouse.py`, `warehouse.html` | `inventory_current_location`, `inventory_movement_events`, `warehouse_locations` | `POST /api/v1/warehouse/scan`, `GET /api/v1/warehouse/locations` | `/dashboard/warehouse.html` — separate page | **ACTIVE** | ✅ `test_warehouse.py`, `test_warehouse_ui.py` | Live scanning | HIGH | Keep, add nav link |
| 23 | **Warehouse Audit** | `warehouse_audit.py`, `routes_warehouse_audit.py` | reads warehouse_db | `GET /api/v1/warehouse/{id}/audit-summary/{batch_id}` | **NOT VISIBLE in main dashboard** | **BACKEND-ONLY** | ✅ `test_warehouse_audit.py` | Reservation gate | HIGH | Expose in Batch detail / Warehouse page |
| 24 | **Barcode / ZPL Label** | `routes_packing.py` | — | `GET /api/v1/packing/{id}/barcode`, `GET /api/v1/packing/{id}/barcode/zpl`, `POST /api/v1/packing/{id}/barcode/print` | **NO UI PANEL** | **BACKEND-ONLY** | ✅ `test_barcode_label.py` | Not yet in use | LOW | Add to Warehouse page when printer is ready |

### 2.6 Document Registry

| # | Module | Key Files | DB Tables | Endpoints | UI Location | Status | Tests | Real Use | Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| 25 | **Document DB Registry** | `document_db.py`, `routes_upload.py` (files) | `shipment_documents`, `sales_documents` | `GET /api/v1/upload/files/{batch_id}/{filename}` | Batch detail → Documents tab (partial) | **ACTIVE** | ✅ `test_document_db.py` | Every shipment | HIGH | Keep, improve UI viewer |
| 26 | **document_extracted_fields / JSON store** | `email_evidence_store.py` | `document_extracted_fields`, `document_extraction_json` | `GET /api/v1/batch/batches/{id}/email-evidence` | Batch detail → DHL Evidence panel | **ACTIVE** | ✅ | DHL email processing | MEDIUM | Keep |

### 2.7 Sales & wFirma

| # | Module | Key Files | DB Tables | Endpoints | UI Location | Status | Tests | Real Use | Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| 27 | **Sales Linkage** | `sales_linkage.py`, `routes_sales.py` | `sales_documents`, `sales_packing_lines` | `GET /api/v1/sales/linkage/{batch_id}` | **NO UI PANEL** | **BACKEND-ONLY** | ✅ `test_sales_linkage.py` | Reservation gate | HIGH | Expose in Batch detail |
| 28 | **wFirma PZ Export (clipboard/JSON)** | `routes_wfirma.py` | reads pz_documents | `POST /api/v1/upload/shipment/{id}/wfirma/clipboard`, `GET .../wfirma/json` | Dashboard → wFirma Export nav item (partial) | **ACTIVE** | ✅ `test_wfirma_export.py` | Post-PZ workflow | MEDIUM | Keep |
| 29 | **wFirma Reservation Preview** | `wfirma_reservation.py`, `routes_wfirma_reservation.py` | `wfirma_customers`, `wfirma_products`, `wfirma_reservation_drafts`, `wfirma_reservation_lines` | `GET /api/v1/wfirma/reservation-preview/{id}` | **NO UI PANEL** | **BACKEND-ONLY** | ✅ `test_wfirma_reservation.py` | Pre-reservation check | HIGH | Expose in wFirma section |
| 30 | **wFirma Capabilities** | `wfirma_capabilities.py`, `routes_wfirma_capabilities.py` | — | `GET /api/v1/wfirma/capabilities` | **NO UI PANEL** | **BACKEND-ONLY** | ✅ `test_wfirma_capabilities.py` | Config validation | MEDIUM | Expose in Admin |
| 31 | **wFirma Customer/Product Mapping** | `wfirma_db.py`, `routes_wfirma_capabilities.py` | `wfirma_customers`, `wfirma_products` | `PUT /api/v1/wfirma/customers/{name}`, `PUT /api/v1/wfirma/products/{code}`, `GET ...` | **NO UI PANEL** | **BACKEND-ONLY** | ✅ `test_wfirma_capabilities.py` | Pre-reservation | HIGH | Expose in wFirma Setup screen |
| 32 | **wFirma Config Checker CLI** | `app/tools/check_wfirma_config.py` | — | CLI only | **TERMINAL ONLY** | **BACKEND-ONLY** | ✅ `test_check_wfirma_config.py` | Pre-live check | HIGH | Add to Admin panel |
| 33 | **wFirma Reservation Create** | `wfirma_client.py` (live methods), `routes_wfirma_reservation.py` | `wfirma_reservation_drafts`, `wfirma_reservation_lines` | **NOT YET BUILT** | — | **BLOCKED** | Partial | Not yet | HIGH | Build only after diagnostic green |

### 2.8 Cowork & Intelligence

| # | Module | Key Files | DB Tables | Endpoints | UI Location | Status | Tests | Real Use | Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| 34 | **Intelligence Engine** | `intelligence_engine.py`, `intelligence_parser.py`, `email_intelligence_store.py` | — | `GET /api/v1/intelligence/shipment/{id}/status` | Dashboard → Intelligence nav item (exists) | **ACTIVE** | ✅ `test_intelligence_engine.py` | Email scan | MEDIUM | Keep, verify nav wiring |
| 35 | **AI Bridge** | `ai_bridge.py`, `routes_ai_bridge.py` | — | `POST /api/v1/ai-bridge/build`, `POST /api/v1/ai-bridge/classify` | Dashboard → AI Bridge nav item (exists) | **ACTIVE** | ✅ `test_ai_bridge.py` | Background | LOW | Keep |
| 36 | **Cowork Coordinator** | `cowork_coordinator.py`, `cowork_result_processor.py`, `cowork_action_runner.py` | — | `POST /{awb}/cowork-result` | hidden / background | **ACTIVE (background)** | ✅ `test_cowork_pipeline.py` | Scheduled | MEDIUM | Keep hidden |
| 37 | **Action Proposals** | `routes_action_proposals.py`, `routes_proposals.py` | — | `GET /api/v1/action-proposals/...`, `GET /api/v1/proposals/...` | Dashboard → Batch → Proposals tab | **ACTIVE** | ✅ `test_action_proposals.py` | Per-batch | MEDIUM | Keep |
| 38 | **Learning / Parser Feedback** | `routes_learning.py` | — | `GET /api/v1/invoice-learning/...` | Dashboard → Learning nav item (exists) | **ACTIVE** | ✅ | Feedback loop | LOW | Keep, verify nav wiring |

### 2.9 Infrastructure & Admin

| # | Module | Key Files | DB Tables | Endpoints | UI Location | Status | Tests | Real Use | Risk | Action |
|---|---|---|---|---|---|---|---|---|---|---|
| 39 | **Auth System** | `auth/`, `routes_auth.py`, `login.html`, `signup.html` | `users`, `login_attempts`, `reset_tokens` | `/auth/login`, `/auth/signup`, `/auth/refresh` | `/login`, `/signup`, `/forgot-password`, `/admin-users` | **ACTIVE** | ✅ `test_email_sender.py` | Every user | HIGH | Keep |
| 40 | **Admin User Management** | `routes_admin.py`, `admin-users.html` | `users` | `POST /api/v1/admin/users/{id}/approve` | `/admin-users.html` | **ACTIVE** | partial | Owner only | HIGH | Keep |
| 41 | **WorkDrive Uploader** | `workdrive_uploader.py`, `workdrive_retry_service.py` | — | called by PZ process | hidden / auto-post-PZ | **ACTIVE** | ✅ `test_workdrive_upload.py` | Every PZ output | HIGH | Keep |
| 42 | **WorkDrive Sync (TrueSync legacy)** | `workdrive_sync.py` | — | — | — | **DEPRECATED** | — | Replaced by REST upload | LOW | Keep hidden, do not use |
| 43 | **Active Shipment Monitor** | `active_shipment_monitor.py` | — | `POST /api/v1/monitor/active-shipments/run` | hidden / cron | **ACTIVE (background)** | ✅ `test_active_shipment_monitor.py` | Scheduled | MEDIUM | Keep |
| 44 | **Stale Cache Tool** | `app/tools/regenerate_stale_batches.py` | — | CLI only | **TERMINAL ONLY** | **BACKEND-ONLY** | ✅ `test_regenerate_stale_batches.py` | Operator | LOW | Add to Admin panel |
| 45 | **DHL Config Checker CLI** | `app/tools/check_dhl_config.py` | — | CLI only | **TERMINAL ONLY** | **BACKEND-ONLY** | ✅ `test_dhl_credential_detection.py` | Operator | MEDIUM | Add to Admin panel |
| 46 | **Analytics** | `routes_analytics.py` | — | `GET /api/v1/analytics/...` | Dashboard → Analytics nav item (exists) | **PARTIAL** | partial | Not yet | LOW | Verify nav wiring |
| 47 | **Email Queue / SMTP** | `email_service.py`, `email_sender.py` | — | `GET /api/v1/email-queue`, `POST .../send` | hidden | **ACTIVE** | ✅ `test_email_sender.py` | Every reply | HIGH | Keep |
| 48 | **System Health** | `routes_system.py`, `storage_health.py` | — | `GET /api/v1/system/health`, `/health-full`, `/storage/health` | hidden | **ACTIVE** | ✅ `test_storage_health.py` | Ops | LOW | Expose in Admin |
| 49 | **Print Agent** | planned concept | — | — | — | **NOT BUILT** | — | — | — | Keep in roadmap |

---

## 3. Active vs Not-Active Lists

### A — Fully active and used in real workflow

1. PZ Import Processor (core)
2. SAD/ZC429 XML + PDF parsers
3. Invoice + Packing parser
4. AWB parser + intake
5. DHL email evidence pipeline
6. DHL reply builder + DSK builder
7. Agency email + forward builder
8. Clearance decision engine
9. Tracking DB + tracking service
10. Document DB registry
11. Auth system (login/signup/admin)
12. Batch dashboard (main UI)
13. WorkDrive REST uploader
14. Zoho Cliq delivery
15. Email service / SMTP queue
16. Active shipment monitor (background)
17. Cowork coordinator (background)

### B — Backend built, not visible in UI

1. Warehouse Audit (`/api/v1/warehouse/{id}/audit-summary/{batch_id}`) — used as a gate for reservation but no panel in batch detail
2. Sales Linkage (`/api/v1/sales/linkage/{batch_id}`) — reservation dependency, no visible panel
3. wFirma Reservation Preview (`/api/v1/wfirma/reservation-preview/{batch_id}`) — full service built, no UI
4. wFirma Capabilities (`/api/v1/wfirma/capabilities`) — no setup screen
5. wFirma Customer/Product Mapping (`PUT/GET /api/v1/wfirma/customers`, `/products`) — no mapping UI
6. wFirma Config CLI (`python3 -m app.tools.check_wfirma_config`) — terminal only
7. Tracking Master Export (`POST /api/v1/tracking/events/export`) — no download button anywhere
8. Barcode / ZPL (`/api/v1/packing/{id}/barcode`) — no panel, no print button
9. System Health endpoints — not surfaced in admin panel
10. Stale Cache Tool (CLI) — terminal only
11. DHL Config Checker (CLI) — terminal only

### C — UI visible but not fully connected or partially wired

1. `wFirma Export` nav item → links to clipboard/JSON export, but no reservation preview panel
2. `Analytics` nav item → section exists, content unclear
3. `Intelligence` nav item → section exists, may not be rendering data
4. `AI Bridge` nav item → section exists, experimental
5. `Learning / Parser` nav item → section exists, verification needed
6. Warehouse page (`/warehouse.html`) — active but no link in main dashboard nav

### D — Experimental / should remain hidden

1. AI Customs Parser — fallback only, must not be surfaced
2. WorkDrive TrueSync legacy (`workdrive_sync.py`) — replaced, deprecated
3. Old batch flow (`debug_allow_old_batch_flow`) — disabled by default, keep hidden
4. Print Agent — not built, concept only

---

## 4. UI / Frontend Gap Analysis

| Backend Feature | What UI Is Missing | Where It Should Appear | New Screen or Panel? | Priority |
|---|---|---|---|---|
| Warehouse Audit | Audit result panel showing missing_scans, stuck_inventory, invalid_flows, orphan_scans | Batch detail (new tab or section) + Warehouse page | Panel in existing Batch detail | HIGH |
| Sales Linkage | Table showing which sales lines are matched/unmatched to packing lines | Batch detail → new "Sales" tab or section | Panel in Batch detail | HIGH |
| wFirma Reservation Preview | Grouped preview per client: product code, qty, unit price, stock_ok, customer_match, product_match, ready_to_create | Batch detail → wFirma section, or new Sales/wFirma screen | Panel + dedicated screen | HIGH |
| wFirma Customer Mapping | Table of client names → wFirma IDs, with manual edit/confirm | New wFirma Setup screen | **New screen** | HIGH |
| wFirma Product Mapping | Table of product codes → wFirma product IDs + stock levels | New wFirma Setup screen | **New screen** | HIGH |
| wFirma Capabilities / Config | Config health: which credentials present, which features enabled | Admin/Settings or wFirma Setup screen | Panel in Admin | MEDIUM |
| Tracking Master Export | Download button for SHIPMENT_TRACKING_MASTER.xlsx | Reports / Analytics nav section | Button in Reports | MEDIUM |
| Barcode / ZPL | Print button per packing line with ZPL preview | Warehouse page or Batch detail Documents | Panel when printer configured | LOW |
| System Health | Storage health, lock status, version | Admin panel | Panel in Admin | MEDIUM |
| CLI Tools | check_wfirma_config, check_dhl_config, regenerate_stale_batches results | Admin panel — "Diagnostics" section | Panel in Admin | MEDIUM |
| Warehouse Scanner nav | Warehouse page exists but no link in main sidebar | Main nav sidebar | Add nav item | HIGH |

---

## 5. Claude Design Wireframe Plan

### WF-01 — New Shipment Intake Screen
- **Purpose:** Create a new shipment from scratch — AWB, invoices, packing list, sales docs
- **Primary action:** Enter AWB number → upload files section by section → trigger intake
- **Data shown:** AWB field, Section A (Shipment/AWB), Section B (Purchase Documents), Section C (Sales Documents), auto-detected file types
- **Buttons:** Upload files, Confirm intake, Clear
- **Endpoints:** `POST /api/v1/shipment`, `POST /api/v1/upload/{batch_id}/upload`
- **Priority:** HIGH — current intake UI is inside the dashboard but not clearly surfaced

### WF-02 — Batch Dashboard (Shipments List)
- **Purpose:** Overview of all active shipments, status badges, quick actions
- **Primary action:** Click shipment → open batch detail
- **Data shown:** Batch ID, AWB, status, DHL status, customs status, PZ status, last update, action flags
- **Buttons:** Recheck, Open, Filter by status, Search
- **Endpoints:** `GET /api/v1/batch/batches`
- **Priority:** HIGH — exists but needs redesign (current table is very dense)

### WF-03 — Batch Detail (Shipment View)
- **Purpose:** Full view of one shipment — all stages, docs, actions, audit
- **Primary action:** Trigger actions per stage (DHL reply, PZ run, wFirma export)
- **Tabs:** Overview, Documents, DHL/Customs, PZ/Accounting, Sales/wFirma, Warehouse, Timeline, Technical
- **Data shown:** Shipment metadata, parsed docs, verification checks, action buttons per stage
- **Priority:** HIGH — current batch.html and dashboard detail both exist but are split

### WF-04 — Document Registry Screen
- **Purpose:** Browse all documents registered for a shipment — view, download, classify
- **Primary action:** Click document → view extracted fields
- **Data shown:** Filename, type, upload date, extracted fields, raw text, confidence
- **Buttons:** Download, Re-classify, View fields
- **Endpoints:** `GET /api/v1/upload/files/{batch_id}/{filename}`, document DB endpoints
- **Priority:** MEDIUM

### WF-05 — Warehouse Scanner Screen
- **Purpose:** Scan items in/out of warehouse locations (mobile-friendly)
- **Primary action:** Enter scan code → select action (RECV, MOVE, DISPATCH) → confirm
- **Data shown:** Scan result, current location, movement history, warnings
- **Buttons:** Scan, Undo last, View location inventory
- **Endpoints:** `POST /api/v1/warehouse/scan`, `GET /api/v1/warehouse/inventory/{scan_code}`
- **Priority:** HIGH — page exists (`warehouse.html`) but not linked in main nav

### WF-06 — Warehouse Audit Screen
- **Purpose:** Show gap analysis for a shipment — what is missing, stuck, or invalid
- **Primary action:** View audit results before approving reservation
- **Data shown:** missing_scans list, stuck_inventory, invalid_flows, orphan_scans, summary badge
- **Buttons:** Refresh audit, Export, Approve (when clean)
- **Endpoints:** `GET /api/v1/warehouse/{id}/audit-summary/{batch_id}`
- **Priority:** HIGH — gate for reservation, but no UI today

### WF-07 — Sales Linkage / Reservation Preview Screen
- **Purpose:** Show how sales documents link to packing lines and what goes to wFirma
- **Primary action:** Review reservation preview per client, confirm ready_to_create
- **Data shown:** Per-client grouping, product codes, quantities, unit prices, stock_ok, customer_match, product_match, ready_to_create flag
- **Buttons:** View details, Confirm mapping, Submit reservation (blocked until gate)
- **Endpoints:** `GET /api/v1/sales/linkage/{batch_id}`, `GET /api/v1/wfirma/reservation-preview/{batch_id}`
- **Priority:** HIGH

### WF-08 — wFirma Setup & Mapping Screen
- **Purpose:** Configure wFirma credentials, map customers, map products
- **Sections:** Credential health (from capabilities endpoint), Customer mapping table, Product mapping table
- **Data shown:** Config status per field, customer list with wFirma ID match status, product list with wFirma ID + stock
- **Buttons:** Edit mapping, Save, Run diagnostic, Check capabilities
- **Endpoints:** `GET /api/v1/wfirma/capabilities`, `GET/PUT /api/v1/wfirma/customers`, `GET/PUT /api/v1/wfirma/products`
- **Priority:** HIGH (required before reservation go-live)

### WF-09 — Admin / System Health Screen
- **Purpose:** Operator view — system health, credential status, storage, diagnostics
- **Sections:** Health checks, Storage status, DHL credential status, wFirma credential status, Locks, User management link
- **Data shown:** Health endpoint results, env key presence (no values), storage GB used, lock count
- **Buttons:** Run diagnostics, Clear locks, Regenerate stale batches, Go to user management
- **Endpoints:** `GET /api/v1/system/health-full`, `GET /api/v1/system/storage/health`, `GET /api/v1/system/storage/locks`
- **Priority:** MEDIUM

---

## 6. Proposed Navigation Structure

```
┌──────────────────────────────────────────────────┐
│  SIDEBAR NAV                                     │
├──────────────────────────────────────────────────┤
│  ▦  Dashboard          (shipments list)          │
│  ✈  Intake             (new shipment)            │
│  ⬡  Shipments          (all batches)             │
│  ⊟  Documents          (document registry)      │
│                                                  │
│  ── Warehouse ────────────────────────────────── │
│  ⊡  Scanner            (/warehouse.html)         │
│  ⊞  Audit              (per-shipment audit)      │
│                                                  │
│  ── Sales & wFirma ──────────────────────────── │
│  ⊕  Sales Linkage      (linkage preview)         │
│  ↗  wFirma Export      (clipboard/JSON)          │
│  ⊛  wFirma Setup       (mapping + config)        │
│                                                  │
│  ── Operations ──────────────────────────────── │
│  ≡  Reports            (tracking export, etc.)   │
│  ◈  Intelligence       (email scan results)      │
│  ◎  Learning           (parser feedback)         │
│                                                  │
│  ── Admin ───────────────────────────────────── │
│  ⚙  System Health      (diagnostics)            │
│  👤 Users              (admin-users.html)        │
└──────────────────────────────────────────────────┘
```

**Changes from current nav:**
- Add `Intake` (currently buried in Dashboard)
- Add `Warehouse Scanner` (page exists, not in nav)
- Add `Warehouse Audit` (no UI today)
- Add `Sales Linkage` (no UI today)
- Add `wFirma Setup` (no UI today)
- Add `System Health` (currently hidden)
- Rename `wFirma Export` to stay focused on export-only until reservation is live

---

## 7. Keep / Hide / Delete Recommendations

| Module | Recommendation | Reason |
|---|---|---|
| PZ Processor | **KEEP ACTIVE** | Core — every shipment |
| SAD/ZC429 parsers (XML + PDF) | **KEEP ACTIVE** | Core |
| Invoice + Packing parsers | **KEEP ACTIVE** | Core |
| AWB parser | **KEEP ACTIVE** | Core |
| DHL clearance pipeline | **KEEP ACTIVE** | Core |
| Agency pipeline | **KEEP ACTIVE** | Core |
| Tracking DB + service | **KEEP ACTIVE** | Core |
| Document DB | **KEEP ACTIVE** | Core |
| Auth system | **KEEP ACTIVE** | Core |
| WorkDrive REST uploader | **KEEP ACTIVE** | Core |
| Email SMTP service | **KEEP ACTIVE** | Core |
| Warehouse Scanner | **KEEP ACTIVE + ADD TO NAV** | Page exists, not discoverable |
| Warehouse Audit | **EXPOSE IN UI** | Needed as reservation gate |
| Sales Linkage | **EXPOSE IN UI** | Needed as reservation gate |
| wFirma Reservation Preview | **EXPOSE IN UI** | Already built, just needs a panel |
| wFirma Customer/Product Mapping | **EXPOSE IN UI** (new Setup screen) | Required before reservation |
| wFirma Capabilities endpoint | **EXPOSE IN ADMIN** | Useful for operator |
| wFirma Config CLI | **EXPOSE IN ADMIN** (diagnostic panel) | Useful for operator |
| Tracking Master Export | **EXPOSE IN REPORTS** | Useful but hidden |
| Barcode / ZPL | **KEEP HIDDEN** until printer is ready | No value until hardware configured |
| Analytics nav item | **VERIFY WIRING** — keep if functional | Unclear state |
| Intelligence nav item | **VERIFY WIRING** — keep if functional | Unclear state |
| AI Bridge nav item | **KEEP HIDDEN from non-admin** | Experimental |
| WorkDrive TrueSync legacy | **KEEP HIDDEN** permanently | Replaced by REST |
| Old batch flow | **KEEP HIDDEN** — `debug_allow_old_batch_flow=False` | Backward compat only |
| AI Customs Parser | **KEEP HIDDEN** as fallback | Never surface directly |
| Cowork coordinator | **KEEP HIDDEN** | Background only |
| Print Agent | **KEEP IN ROADMAP** | Not built |
| wFirma Reservation Create | **DO NOT BUILD YET** | Blocked on diagnostic gate |

---

## 8. Next Implementation Roadmap

### Phase 1 — Inventory cleanup & expose critical backend tools in UI (no new features)
1. Add Warehouse Scanner to main nav sidebar
2. Add Warehouse Audit panel to Batch detail (new tab or section)
3. Add Sales Linkage panel to Batch detail (new tab or section)
4. Add wFirma Reservation Preview panel to Batch detail (read-only)
5. Verify and fix Analytics / Intelligence / Learning nav items
6. Add System Health page (use existing endpoints)

### Phase 2 — Claude Design wireframes & UI redesign by section
1. Commission WF-01 through WF-09 from Claude Design
2. Review and approve wireframes with owner
3. Implement approved redesigns section by section
4. Priority order: WF-02 (Dashboard), WF-05 (Warehouse), WF-07 (Sales/wFirma), WF-08 (wFirma Setup), WF-09 (Admin)

### Phase 3 — wFirma live integration
1. Set `.env` credentials (`WFIRMA_APP_KEY`, `WFIRMA_API_LOGIN`, `WFIRMA_API_PASSWORD`, `WFIRMA_COMPANY_ID`, `WFIRMA_WAREHOUSE_ID`)
2. Run `./deploy-service.sh` + `python3 -m app.tools.check_wfirma_config`
3. Confirm all 10 diagnostic checks green
4. Build `POST /api/v1/wfirma/reservations/create`
5. Map all 4 customers and 14 products
6. Run first reservation in preview-confirm mode

### Phase 4 — Print agent / advanced warehouse UX
1. Design print agent architecture (hardware interface)
2. Activate barcode/ZPL endpoint in Warehouse page
3. Build print queue and label preview
4. Advanced warehouse: multi-location routing, returns flow

---

## 9. Final Decision Questions for Owner

1. **Which nav sections should be visible first?** Suggested priority: Warehouse Scanner (already works, just hidden), Warehouse Audit, Sales Linkage, wFirma Setup. Confirm order.

2. **Should experimental features stay hidden?** AI Bridge, Analytics, Intelligence — confirm whether these should be operator-only or remain in the nav.

3. **Should the old upload flow (`batch.html`) be kept?** There are two batch-detail views: the legacy `batch.html` page and the in-dashboard `BatchDetailPage` component. Should they be consolidated?

4. **Should WorkDrive upload be automatic (as it is now) or allow manual retry?** Current: automatic on PZ process, retry queue in background. Option: add a manual "Re-upload to WorkDrive" button in Batch detail.

5. **Should wFirma stay preview-only until API keys are ready?** Current gate: `check_wfirma_config` must be fully green before `POST /reservations/create` is built. Confirm this rule stands.

6. **Should Warehouse Scanner be mobile-first?** The page exists but is desktop-only. If staff will use phones to scan, it needs responsive/mobile-first redesign.

7. **Should the reservation create UI show a confirmation step?** Before submitting to wFirma, show a "you are about to create X reservations for Y clients" confirmation modal. Recommended: yes.

8. **What is the priority for the barcode/ZPL printer?** Feature is built but no printer is configured. Add to Phase 4 roadmap or defer indefinitely?

9. **Should the diagnostic CLI tools be surfaced in the Admin UI?** Current: terminal-only. Recommended: expose as read-only panels in System Health screen so non-technical operators can verify config status.

10. **Proposed navigation structure (Section 6)** — confirm which items to add and which to remove before Claude Design begins wireframes.

---

## 10. Final Report

**Changed files:** `docs/system_inventory_and_ui_plan.md` (new, this file)  
**Tests run:** 1 324 passed (pre-existing; this document makes no code changes)

### Top 10 active features
1. PZ Import Processor — core calculation and output pipeline
2. DHL Email Evidence — auto-classification of DHL customs email attachments
3. SAD/ZC429 XML Parser — source of truth for customs declarations
4. Tracking DB + service — event log per shipment
5. Document DB Registry — unified file registry across all document types
6. Auth system — user login, JWT, admin management
7. DHL Reply Builder — automatic DHL customs reply construction
8. Agency Email Builder — forward package to customs broker
9. WorkDrive REST Uploader — automatic cloud backup post-PZ
10. Batch Dashboard — primary operator interface

### Top 10 backend-only features (no UI today)
1. Warehouse Audit — gap detection (used as reservation gate)
2. Sales Linkage — links sales documents to packing/warehouse state
3. wFirma Reservation Preview — per-client grouped reservation draft
4. wFirma Customer/Product Mapping — local ID resolution tables
5. wFirma Capabilities endpoint — config health check
6. Tracking Master Export — full event history as XLSX
7. Barcode/ZPL Label — label generation for warehouse items
8. wFirma Config Checker CLI — credential + endpoint diagnostic
9. System Health endpoints — storage, locks, version
10. Stale Cache Regeneration CLI — batch audit repair tool

### Recommended next step
**Do not write code. Do the following in order:**
1. Owner reviews this document and answers the 10 questions in Section 9
2. Confirm navigation structure (Section 6) — what is added/removed
3. Submit WF-01 through WF-09 list to Claude Design for wireframes
4. After wireframe approval: Phase 1 (expose hidden features) — estimated ~5 targeted code changes, no new logic
5. After Phase 1: wFirma gate (Section 8, Phase 3) — only when `.env` credentials are ready
