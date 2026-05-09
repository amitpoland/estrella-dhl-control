# REPO INTELLIGENCE FOR CLAUDE DESIGN

**Generated**: 2026-05-07
**Source**: HEAD = `64b9cb0` (+ uncommitted dirty tree)
**Scope**: read-only inspection of `service/app/` and `service/app/static/dashboard.html`

This pack is for Claude Design to understand the dashboard, API routes, DHL email flow, AI Bridge, PZ purchase flow, and wFirma sales flow without localhost access. **Every endpoint listed is extracted from a `@router.METHOD(...)` decorator in the codebase.** Nothing invented.

---

## 1. API Endpoints Grouped by Domain

The FastAPI service mounts 39 routers in [service/app/main.py](service/app/main.py:11-47). Endpoints below are listed as `METHOD prefix+path` with the file/line reference.

### 1.1 Auth & Users — `/auth`
File: [routes_auth.py](service/app/api/routes_auth.py)
- `POST /auth/login`
- `POST /auth/logout`
- `POST /auth/signup`
- `GET  /auth/me`
- `POST /auth/forgot-password`
- `POST /auth/reset-password`
- `GET  /auth/users`
- `POST /auth/users/{user_id}/approve`
- `POST /auth/users/{user_id}/reject`
- `POST /auth/users/{user_id}/role`
- `POST /auth/users/{user_id}/deactivate`
- `POST /auth/users/{user_id}/activate`

Sessions: cookie `pz_session` (JWT, HS256, AUTH_SECRET_KEY). Two roles seen in routes: regular + `require_admin`.

### 1.2 Dashboard — `/dashboard`
File: [routes_dashboard.py](service/app/api/routes_dashboard.py) (24 endpoints)
- `GET    /dashboard/batches` — list shipments (UI uses `?all=1`)
- `GET    /dashboard/batches/{batch_id}` — full batch detail
- `GET    /dashboard/batches/{batch_id}/files`
- `DELETE /dashboard/batches/{batch_id}/files/{filename}` (output-dir scope only — see Gap §8)
- `DELETE /dashboard/batches/{batch_id}/files/source/{category}/{filename}`
- `POST   /dashboard/batches/{batch_id}/regenerate`
- `POST   /dashboard/batches/{batch_id}/operator-override`
- `GET    /dashboard/batches/{batch_id}/email-evidence`
- `POST   /dashboard/batches/{batch_id}/email-evidence/rescan`
- `POST   /dashboard/batches/{batch_id}/email-evidence/process`
- `GET    /dashboard/batches/{batch_id}/email-evidence/attachments/{sha256}`
- `GET    /dashboard/batches/{batch_id}/dhl-action-state`
- `GET    /dashboard/batches/{batch_id}/action-diagnostics`
- `GET    /dashboard/batches/{batch_id}/actions`
- `POST   /dashboard/batches/{batch_id}/recheck`
- `POST   /dashboard/batches/{batch_id}/resend`
- `DELETE /dashboard/batches/{batch_id}` — soft-delete (archive)
- `GET    /dashboard/broker-followups`
- `POST   /dashboard/broker-followups/{batch_id}/send`
- `POST   /dashboard/broker-reply/analyze`
- `GET    /dashboard/archive`
- `POST   /dashboard/archive/{batch_id}/restore`
- `DELETE /dashboard/archive/{batch_id}` — admin-only permanent delete
- `POST   /dashboard/archive/cleanup` — admin-only

### 1.3 PZ Core — `/api/v1`
File: [routes_pz.py](service/app/api/routes_pz.py)
- `GET  /api/v1/health`
- `POST /api/v1/pz/process`
- `POST /api/v1/pz/process/_legacy`
- `POST /api/v1/feedback`
- `GET  /api/v1/learning/summary`
- `GET  /api/v1/files/{batch_id}/{filename}`
- `GET  /api/v1/files/{batch_id}/source/{category}/{filename}`

### 1.4 Shipment Lifecycle / Intake / Upload
- File: [routes_intake.py](service/app/api/routes_intake.py) — `/api/v1/shipment`
  - `POST /api/v1/shipment/intake`
  - `POST /api/v1/shipment/{batch_id}/packing_list`
- File: [routes_upload.py](service/app/api/routes_upload.py) — `/api/v1/upload`
  - `POST /api/v1/upload/shipment`
  - `POST /api/v1/upload/shipment/{batch_id}/sad`
  - `POST /api/v1/upload/shipment/{batch_id}/process`
  - `POST /api/v1/upload/shipment/{batch_id}/set_pz`
  - `GET  /api/v1/upload/shipment/{batch_id}/documents`
  - `GET  /api/v1/upload/shipment/{batch_id}/status`
- File: [routes_lifecycle.py](service/app/api/routes_lifecycle.py) — `/api/v1`
  - `POST /api/v1/agency-documents/{batch_id}/received`
  - `POST /api/v1/agency-documents/{batch_id}/upload`
  - `POST /api/v1/service-invoices/{batch_id}/received`
  - `POST /api/v1/service-invoices/{batch_id}/upload`
  - `POST /api/v1/closure/{batch_id}/evaluate`
  - `GET  /api/v1/closure/{batch_id}/check`
  - `POST /api/v1/lifecycle/agency-followup`

### 1.5 DHL Customs — `/api/v1/dhl` + adjacents
- File: [routes_dhl_clearance.py](service/app/api/routes_dhl_clearance.py)
  - `GET  /api/v1/dhl/scan-inbox`
  - `POST /api/v1/dhl/match-and-handle`
  - `GET  /api/v1/dhl/clearance-status/{batch_id}`
  - `POST /api/v1/dhl/generate-description/{batch_id}`
  - `POST /api/v1/dhl/generate-customs-package/{batch_id}`
  - `GET  /api/v1/dhl/sad-ready/{batch_id}`
  - `GET  /api/v1/dhl/reply-status/{batch_id}`
  - `POST /api/v1/dhl/send-reply/{batch_id}`
  - `POST /api/v1/dhl/approve/{batch_id}`
  - `POST /api/v1/dhl/mark-email-received/{batch_id}`
  - `POST /api/v1/dhl/proactive-dispatch/{batch_id}`
  - `GET  /api/v1/dhl/download/{filename}`
- File: [routes_dhl_documents.py](service/app/api/routes_dhl_documents.py) — `/api/v1/dhl-documents`
  - `POST /api/v1/dhl-documents/{batch_id}/received`
  - `POST /api/v1/dhl-documents/{batch_id}/upload`
- File: [routes_dhl_followup.py](service/app/api/routes_dhl_followup.py) — `/api/v1/dhl-followup`
  - `POST /api/v1/dhl-followup/{batch_id}/stop`
  - `POST /api/v1/dhl-followup/{batch_id}/send-now`
  - `POST /api/v1/dhl-followup/{batch_id}/recalculate`
- File: [routes_dhl_readiness.py](service/app/api/routes_dhl_readiness.py)
  - `GET  /api/v1/dhl/readiness/{batch_id}`
- File: [routes_dsk.py](service/app/api/routes_dsk.py) — `/api/v1/dsk`
  - `POST /api/v1/dsk/generate`
  - `GET  /api/v1/dsk/download/{filename}`
  - `POST /api/v1/dsk/email-package`
  - `GET  /api/v1/dsk/audit-log`
- File: [routes_agency.py](service/app/api/routes_agency.py) — `/api/v1/agency`
  - `POST /api/v1/agency/email-package/{batch_id}`
  - `GET  /api/v1/agency/decision/{batch_id}`

### 1.6 Email Queue (Admin) — `/api/v1/admin`
File: [routes_admin.py](service/app/api/routes_admin.py)
- `GET  /api/v1/admin/email-queue` — list queue entries
- `POST /api/v1/admin/email-queue/{queue_id}/send` — manual SMTP send
- `POST /api/v1/admin/email-queue/{email_id}/sent` — mark already-sent (manual reconcile)

### 1.7 Action Proposals — `/api/v1/action-proposals` (no router prefix)
File: [routes_action_proposals.py](service/app/api/routes_action_proposals.py)
- `POST /api/v1/action-proposals/{batch_id}/refresh`
- `GET  /api/v1/action-proposals/{batch_id}` — list for batch
- `POST /api/v1/action-proposals/{proposal_id}/approve`
- `POST /api/v1/action-proposals/{proposal_id}/reject`
- `POST /api/v1/action-proposals/{proposal_id}/queue` — queues + (proactive) drives SMTP send

### 1.8 AI Bridge — `/api/v1/ai-bridge`
File: [routes_ai_bridge.py](service/app/api/routes_ai_bridge.py)
- `POST /api/v1/ai-bridge/tasks/{batch_id}` — create task
- `GET  /api/v1/ai-bridge/tasks?status=pending|processed`
- `GET  /api/v1/ai-bridge/tasks/{task_id}`
- `POST /api/v1/ai-bridge/results/{task_id}` — import result from external AI
- `GET  /api/v1/ai-bridge/results/{task_id}`
- `GET  /api/v1/ai-bridge/errors`
- `GET  /api/v1/ai-bridge/templates`

### 1.9 Intelligence — `/api/v1/intelligence`
File: [routes_intelligence.py](service/app/api/routes_intelligence.py)
- `GET  /api/v1/intelligence/suggestions`
- `GET  /api/v1/intelligence/suggestions/{batch_id}`
- `GET  /api/v1/intelligence/config`
- `POST /api/v1/intelligence/refresh`
- `GET  /api/v1/intelligence/actors`
- `POST /api/v1/intelligence/classify`
- `GET  /api/v1/intelligence/status`
- `POST /api/v1/intelligence/build`
- `GET  /api/v1/intelligence/insights`

### 1.10 wFirma Sales/PZ — `/api/v1/upload` (PZ side) + `/api/v1/wfirma` (master data) + `/api/v1/proforma`
- File: [routes_wfirma.py](service/app/api/routes_wfirma.py) — `/api/v1/upload` prefix
  - `POST /api/v1/upload/shipment/{batch_id}/wfirma/clipboard`
  - `GET  /api/v1/upload/shipment/{batch_id}/wfirma/json`
  - `GET  /api/v1/upload/shipment/{batch_id}/wfirma/pz_preview`
  - `POST /api/v1/upload/shipment/{batch_id}/wfirma/products/resolve`
  - `POST /api/v1/upload/shipment/{batch_id}/wfirma/pz_create` — write PZ to wFirma
  - `POST /api/v1/upload/shipment/{batch_id}/wfirma/pz_adopt` — adopt existing PZ
  - `GET  /api/v1/upload/shipment/{batch_id}/wfirma/pz_document`
- File: [routes_wfirma_capabilities.py](service/app/api/routes_wfirma_capabilities.py) — `/api/v1/wfirma`
  - `GET  /api/v1/wfirma/capabilities`
  - `GET  /api/v1/wfirma/customers` (+ PUT by `client_name`)
  - `GET  /api/v1/wfirma/products` (+ PUT by `product_code`)
  - `GET  /api/v1/wfirma/contractors/search`
  - `GET  /api/v1/wfirma/goods/search`
  - `POST /api/v1/wfirma/goods/search-bulk`
  - `POST /api/v1/wfirma/goods/create-from-product-code/{product_code}`
  - `POST /api/v1/wfirma/goods/refresh-name-from-block/{product_code}`
  - `POST /api/v1/wfirma/customers/create-internal-test`
  - `GET  /api/v1/wfirma/customers/sync-preview`
  - `POST /api/v1/wfirma/customers/sync`
- File: [routes_wfirma_reservation.py](service/app/api/routes_wfirma_reservation.py) — `/api/v1/wfirma`
  - `GET  /api/v1/wfirma/reservation-preview/{batch_id}`
  - `POST /api/v1/wfirma/reservations/create`
  - `POST /api/v1/wfirma/reservations/{draft_id}/reset-stuck`
- File: [routes_proforma.py](service/app/api/routes_proforma.py) — `/api/v1/proforma`
  - `POST /api/v1/proforma/preview/{batch_id}/{client_name}`
  - `POST /api/v1/proforma/create/{batch_id}/{client_name}`
  - `POST /api/v1/proforma/cancel-issued-for-reissue/{batch_id}/{client_name}`
  - `POST /api/v1/proforma/adopt-issued/{batch_id}/{client_name}`
  - `POST /api/v1/proforma/{wfirma_id}/refresh-line-names`
  - `GET  /api/v1/proforma/{batch_id}/{client_name}/document`
- File: [routes_sales.py](service/app/api/routes_sales.py)
  - `GET  /api/v1/sales/linkage/{batch_id}` — preview/create

### 1.11 Warehouse — `/api/v1/warehouse`
- File: [routes_warehouse.py](service/app/api/routes_warehouse.py)
  - `GET  /api/v1/warehouse/config`
  - `POST /api/v1/warehouse/scan`
  - `GET  /api/v1/warehouse/inventory/{scan_code}`
  - `GET  /api/v1/warehouse/locations`
  - `POST /api/v1/warehouse/locations`
  - `GET  /api/v1/warehouse/locations/{location_code}/inventory`
- File: [routes_warehouse_audit.py](service/app/api/routes_warehouse_audit.py) — `/api/v1/warehouse`
  - `GET  /api/v1/warehouse/audit/{batch_id}`
  - `GET  /api/v1/warehouse/audit-summary/{batch_id}`

### 1.12 Tracking — `/api/v1/tracking`
- File: [routes_tracking.py](service/app/api/routes_tracking.py)
  - `GET  /api/v1/tracking/{tracking_no}`
  - `POST /api/v1/tracking/{tracking_no}/refresh`
  - `POST /api/v1/tracking/batch/{batch_id}/update`
  - `POST /api/v1/tracking/{awb}/cowork-result`
  - `GET  /api/v1/tracking/shipment/{batch_id}/timeline`
- File: [routes_tracking_db.py](service/app/api/routes_tracking_db.py)
  - `GET  /api/v1/tracking/events/{batch_id}`
  - `GET  /api/v1/tracking/events`
  - `POST /api/v1/tracking/events/export`
  - `GET  /api/v1/tracking/events/export/download`

### 1.13 Packing — `/api/v1/packing`
File: [routes_packing.py](service/app/api/routes_packing.py)
- `POST /api/v1/packing/{batch_id}/upload`
- `GET  /api/v1/packing/{batch_id}`
- `GET  /api/v1/packing/{batch_id}/lines`
- `GET  /api/v1/packing/{batch_id}/barcode` (PNG) / `.../zpl`
- `POST /api/v1/packing/{batch_id}/barcode/print`

### 1.14 Other domain routers
- `routes_batch.py` — `/api/v1/batch` — Cliq-driven batch session manager (start/add/scan-chat/sessions/cancel/submit + status)
- `routes_batch_readiness.py` — `GET /api/v1/batch/{batch_id}/readiness`
- `routes_proposals.py` — `/api/v1/proposals` — generic proposal capture (capture/list/summary/approve/reject)
- `routes_learning.py` — `/api/v1/invoice-learning` — feedback + supplier-pattern store
- `routes_analytics.py` — `GET /api/v1/analytics/phase-a`
- `routes_execute.py` — `POST /api/v1/execute/{action}` — generic dispatcher backed by execution_engine
- `routes_monitor.py` — `POST /api/v1/monitor/active-shipments/run` — manual sweep trigger
- `routes_agents.py` — `GET /api/v1/agents/decision/{batch_id}` — decision engine read
- `routes_bot.py` — `/api/v1/cliq` — Zoho Cliq webhook events
- `routes_system.py` — `GET /api/v1/system/version`
- `routes_debug.py` — `/api/v1/debug` — health-full / storage / locks / clear-test-sessions
- `routes_reservations.py` — `/api/v1` — purchase/sales packing imports + reservation queue

---

## 2. Existing Dashboard Tabs / Cards & Their Endpoints

The dashboard is a **single-file React (UMD) SPA** at [service/app/static/dashboard.html](service/app/static/dashboard.html) (10,513 lines). Sidebar nav is defined at [line 76](service/app/static/dashboard.html#L76).

### 2.1 Sidebar pages (top-level)

| Sidebar id | Label | Component | Primary endpoints |
|---|---|---|---|
| `dashboard` | Dashboard | `DashboardPage` (line 864) | `GET /dashboard/batches?all=1` |
| `shipments` | Shipments | `ShipmentsTable` (line 7324) | same `batches` from dashboard load |
| `dhl` | DHL Clearance | `DhlClearancePage` (line 7383) | filters `batches` client-side |
| `customs` | Customs Documents | `CustomsDocumentsPage` (line 7406) | filters `batches` |
| `warehouse_scanner` | Warehouse Scanner | external page `/dashboard/warehouse.html` | `/api/v1/warehouse/*` |
| `pz` | PZ / Accounting | `PzAccountingPage` (line 7922) | filters `batches` + per-batch wFirma reads |
| `wfirma` | wFirma | `WfirmaExportPage` (line 7425) | `/api/v1/wfirma/*` |
| `reports` | Analytics | `ReportsPage` (line 8063) | `GET /api/v1/analytics/phase-a` |
| `intelligence` | Intelligence | `IntelligencePage` | `GET /api/v1/intelligence/{suggestions, config, insights}` |
| `ai_bridge` | AI Bridge | `AiBridgePage` | `POST /api/v1/ai-bridge/tasks/{batch_id}`, `GET /tasks?status=pending\|processed`, `GET /results/{task_id}` |
| `learning` | Learning / Parser | `LearningPage` | `GET /api/v1/invoice-learning/patterns/{key}`, `POST /feedback` |
| `admin` | Admin / Settings | `AdminPage` (line 8417) | `/auth/users*`, `/api/v1/admin/email-queue`, `/api/v1/wfirma/customers\|products` |

### 2.2 Batch detail tabs (on `BatchDetailPage`, line 2111)

`activeTab` ranges over: `Overview` · `Documents` · `Timeline` · `Intelligence` · `Proposals` · `Warehouse` · `Sales` · `PZ / wFirma` · `DHL / Customs` (line 2115 sets default `Overview`).

| Tab | Card / Component | Endpoints called |
|---|---|---|
| Overview | `DecisionBanner`, `OverallReadinessCard`, `BatchControlCenter`, action chips | `GET /dashboard/batches/{id}`, `GET /api/v1/batch/{id}/readiness`, `GET /api/v1/agents/decision/{id}` |
| Documents | per-file rows, regenerate, delete | `GET /dashboard/batches/{id}/files`, `POST .../regenerate`, `DELETE .../files/{name}`, `GET /api/v1/dhl/download/{file}`, `GET /api/v1/dsk/download/{file}` |
| Timeline | event list | `GET /api/v1/tracking/shipment/{id}/timeline`, `GET /api/v1/tracking/events/{id}` |
| Intelligence | suggestions feed | `GET /api/v1/intelligence/suggestions/{id}` |
| Proposals | action proposal panel | `GET /api/v1/action-proposals/{id}`, `POST /api/v1/action-proposals/{pid}/{approve\|reject\|queue}` |
| Warehouse | warehouse audit | `GET /api/v1/warehouse/audit/{id}` |
| Sales | sales linkage | `GET /api/v1/sales/linkage/{id}?mode=preview` |
| PZ / wFirma | preview · resolve products · create PZ · adopt PZ · view PZ doc | full `/api/v1/upload/shipment/{id}/wfirma/*` chain + `/api/v1/wfirma/reservation-preview/{id}` |
| DHL / Customs | `DhlActionCard` (line 8903), `EmailEvidenceTimeline` (line 9067), readiness banner, follow-up panel | see §3 |

### 2.3 Workflow checklist (line 1924)

The Batch Control Center maps each step to the tab where the operator acts:

| Step | Required-flag | Tab |
|---|---|---|
| Batch created | `batchId` | — |
| SAD / customs doc uploaded | `hasSad` | DHL / Customs |
| PZ document generated | `hasPz` | PZ / wFirma |
| DHL contacted | `hasDhlContact` | DHL / Customs |
| DHL reply received | `hasDhlReply` | DHL / Customs |
| DSK docs received | `hasDsk` | DHL / Customs |
| Forwarded to agency | `hasAgency` | DHL / Customs |
| SAD / PZC from agency | `hasSadPzc` | DHL / Customs |
| Warehouse scanned | `whReady` | Warehouse |
| Sales linked | `salesReady` | Sales |
| wFirma reservation | `wfirmaReady` | PZ / wFirma |
| Customs cleared | `hasSadPzc && hasDsk` | DHL / Customs |
| Ready for closure | `allReady` | — |

### 2.4 Reusable UI primitives
[dashboard.html](service/app/static/dashboard.html) defines: `SessionBanner`, `Badge`, `Card`, `Btn`, `Modal`, `FormField`, `Inp`, `Sel`, `SectionHeader`, `InfoRow`, `Toast`, `TopBar`, `PageHeader`, `NewShipmentModal`, `ReadinessBanner`, `StatusChip`, `ShipmentsTable`, `StatsRow`, `BarChart`, `StackedBarChart`, `AnalyticsCard`, `StatRow`, `PlaceholderPage` — these are the design tokens to reuse.

---

## 3. DHL Email Queue / Send / Dropdown Status

### 3.1 Backend pieces
- **Queue store**: `storage_root/email_queue.json` (list of dicts). Schema fields: `id`, `queued_at`, `status` (`pending` | `sent` | `failed`), `to`, `cc`, `subject`, `body_html`, `body_text`, `sent_at`, `error`, `error_detail`, `last_send_attempt_at`, `provider_message_id`, `sent_via`, `batch_id`, `from_address`, `account_id`, `email_type`. See [email_service.py:36](service/app/services/email_service.py:36) `queue_email()` and [email_sender.py:180](service/app/services/email_sender.py:180) `send_queued_email()`.
- **SMTP (primary)**: Zoho `smtppro.zoho.in:465` (SSL). Auth user from `SMTP_USER`; sender `from_address` may be a Zoho alias. MIME built in `_build_mime` ([email_sender.py:132](service/app/services/email_sender.py:132)).
- **Attachment resolver**: `_attachments_for_queue(entry)` ([email_sender.py:85](service/app/services/email_sender.py:85)) reads, in priority order:
  1. `audit.action_proposals[*].draft.attachments` (proposal-driven emails — fix from commit `64b9cb0`)
  2. `audit.agency_reply_package.attachments`
  3. `audit.dhl_reply_package.attachments`
- **Silent-send guard**: `_expected_attachment_count` aborts SMTP when expected > 0 and resolved == 0.

### 3.2 Email types in flight (`email_type` field)
`dhl_b2_dsk_only_reply`, `dhl_reply`, `dhl_self_clearance_reply`, `agency_reply_package`, `agency_forward_after_dhl`, `dhl_followup`, `dhl_proactive_dispatch`. Each has its own builder in `service/app/services/`:
- [`dhl_proactive_dispatch_builder.py`](service/app/services/dhl_proactive_dispatch_builder.py) — first-contact / proactive (post-fix: thread-aware subject + correction-mode flag)
- [`dhl_reply_builder.py`](service/app/services/dhl_reply_builder.py)
- [`dhl_self_clearance_builder.py`](service/app/services/dhl_self_clearance_builder.py)
- [`dhl_followup_email_builder.py`](service/app/services/dhl_followup_email_builder.py)
- [`agency_email_builder.py`](service/app/services/agency_email_builder.py)
- [`agency_forward_after_dhl_builder.py`](service/app/services/agency_forward_after_dhl_builder.py)
- [`action_email_builder.py`](service/app/services/action_email_builder.py) — registry that dispatches to type-specific builder

### 3.3 Operator UI for email queue
- `AdminPage` ([line 8417](service/app/static/dashboard.html#L8417)) has an Email Queue card driven by `GET /api/v1/admin/email-queue`. Manual send via `POST /api/v1/admin/email-queue/{id}/send` is wired in.
- `DhlActionCard` ([line 8903](service/app/static/dashboard.html#L8903)) shows DHL status drop-down with state chips: `awaiting_start`, `package`, `queued`, `sent`, `failed` (line 6311).
- Action proposals (Batch detail → Proposals tab) → `POST /api/v1/action-proposals/{id}/queue` is the **preferred path** post-fix: it queues + immediately sends (proactive type).

### 3.4 Auto-send drivers (which observers call `send_queued_email`)
[active_shipment_monitor.py](service/app/services/active_shipment_monitor.py) call sites:
- line 478 — `dhl_b2_dsk_only_reply`
- line 555 — `dhl_reply`
- line 640 — `dhl_self_clearance_reply`
- line 1321 — `agency_forward_after_dhl`
- line 1682 — `dhl_followup`

**Not auto-sent**: `dhl_proactive_dispatch` — operator must hit `/queue` (which now drives SMTP synchronously after commit `64b9cb0`).

### 3.5 Auto-queue trigger (Path A) — flag-gated
`_ensure_path_a_auto_queue` ([asm:816](service/app/services/active_shipment_monitor.py:816)) requires:
1. `clearance_decision.clearance_path` = Path A (`dhl_self_clearance` or `carrier_self_clearance` alias)
2. `tracking_events` contains a `DEPARTED_ORIGIN` / `DEPARTED_ORIGIN_HUB` event
3. `auto_queue_started_at` not set (idempotency)
4. **`settings.enable_path_a_auto_queue == True`** — defaults to `False`; not set in `.env`

**Note**: trigger is origin-departure (Mumbai/Hong Kong/Leipzig), **not** Poland-arrival. Poland-arrival (`_PL_CUSTOMS_STAGES`) only drives the DHL-followup SLA timer ([dhl_followup_sla.py:117-172](service/app/services/dhl_followup_sla.py:117)).

---

## 4. AI Bridge — Existing Features

### 4.1 Endpoints
See §1.8. Tasks are persisted as JSON files at `storage_root/ai_bridge/tasks/<task_id>.json` (browseable; ~25 visible in current storage).

### 4.2 Service files
- [`ai_bridge.py`](service/app/services/ai_bridge.py) — task creation, listing, get/save (single source of truth)
- [`cowork_action_runner.py`](service/app/services/cowork_action_runner.py) — executes actions returned by the external Cowork session
- [`cowork_result_processor.py`](service/app/services/cowork_result_processor.py) — validates Cowork structured result before action execution

### 4.3 Operating model (per [CLAUDE.md](CLAUDE.md) §9)
1. Scheduler creates task via `POST /ai-bridge/tasks/{batch_id}` (PZ App-driven)
2. External "Claude Cowork" session reads the task JSON, gathers Zoho mail/Cliq/WorkDrive evidence, returns **structured JSON only** (no email send, no audit mutation)
3. PZ App ingests via `POST /ai-bridge/results/{task_id}` → validation → `cowork_action_runner` decides next action (queue email via existing service, mark received, etc.)
4. Audit logs `cowork_action_executed` / `cowork_action_failed` / `cowork_result_processed` / `cowork_result_rejected`

**Cowork hard rules (from CLAUDE.md):** Cowork must NEVER directly send emails, mutate CIF/duty/invoice values, close shipments, choose recipients, attach files, or override sender identity.

### 4.4 Templates
`GET /api/v1/ai-bridge/templates` returns supported task kinds. Errors: `GET /api/v1/ai-bridge/errors`.

### 4.5 UI
`AiBridgePage` (sidebar `ai_bridge`) — list tasks, file new task, view results JSON, browse error log.

---

## 5. PZ Purchase Flow

### 5.1 Pipeline
```
Cliq batch session  ─►  /api/v1/upload/shipment   (master upload of invoices + AWB)
                       │
                       ├─►  /api/v1/upload/shipment/{id}/sad     (SAD/ZC429 upload)
                       │
                       ├─►  /api/v1/upload/shipment/{id}/process (parse + verify + generate PDF + XLSX)
                       │
                       └─►  /api/v1/upload/shipment/{id}/set_pz  (assign PZ doc number)
```

Source-of-truth: `process_batch()` in the engine (see [CLAUDE.md](CLAUDE.md) §1). Outputs per batch: `pz_pdf`, `calc_xlsx`, `audit_memo`, `audit_en`, `audit_pl`, `polish_desc`, `corrections` (named via [output_filenames.py](service/app/services/output_filenames.py)).

### 5.2 Customs description PDF (Polish)
- Service-side generator: [`customs_description_engine.py`](customs_description_engine.py) (root-level, imported by [description_engine.py:159](service/app/services/description_engine.py:159))
- Output: `storage_root/polish_descriptions/POLISH_DESC_AWB_<AWB>_<DATE>.pdf`
- SAD-ready JSON: `SAD_READY_<AWB>_<DD-MM-YYYY>.json` (same dir)
- Includes: per-invoice item blocks, consolidated customs summary, FOB/Freight/Insurance/CIF rows (post commit `64b9cb0`)

### 5.3 PZ → Warehouse → Sales chain
1. PZ generated → batch ready for warehouse scan (`POST /api/v1/warehouse/scan`)
2. Warehouse audit (`GET /api/v1/warehouse/audit/{batch_id}`) confirms unit-level intake
3. Sales linkage (`GET /api/v1/sales/linkage/{batch_id}`) maps purchased lots to sales reservations
4. wFirma PZ created (`POST /api/v1/upload/shipment/{batch_id}/wfirma/pz_create`) or adopted (existing wFirma PZ)
5. Closure (`POST /api/v1/closure/{batch_id}/evaluate`) — hard blockers: customs_docs_received + pz_generated; service-invoices are accounting-only signals.

### 5.4 Engine outputs to dashboard
- `Documents` tab lists each artifact with download URLs:
  - PZ PDF — `pz_pdf` key
  - Calculation XLSX — `calc_xlsx`
  - Audit EN/PL/Memo PDFs — `audit_en`, `audit_pl`, `audit_memo`
  - Correction Report — `corrections`

---

## 6. wFirma Sales Flow

### 6.1 Master data
- Customers: `GET /api/v1/wfirma/customers` (filterable), `PUT /api/v1/wfirma/customers/{client_name}` (edit). Sync: `POST /api/v1/wfirma/customers/sync` after preview.
- Products: `GET /api/v1/wfirma/products` (+PUT). Search wFirma goods: `GET /api/v1/wfirma/goods/search`, bulk: `POST /api/v1/wfirma/goods/search-bulk`.
- Customer commercial profile: [customer_commercial_profile.py](service/app/services/customer_commercial_profile.py), invoice snapshot DB: [customer_invoice_snapshot_db.py](service/app/services/customer_invoice_snapshot_db.py).

### 6.2 Sales lifecycle endpoints
1. **Reservation preview**: `GET /api/v1/wfirma/reservation-preview/{batch_id}`
2. **Create reservation**: `POST /api/v1/wfirma/reservations/create`
3. **Reset stuck draft**: `POST /api/v1/wfirma/reservations/{draft_id}/reset-stuck`
4. **Proforma preview**: `POST /api/v1/proforma/preview/{batch_id}/{client_name}`
5. **Issue proforma**: `POST /api/v1/proforma/create/{batch_id}/{client_name}`
6. **Cancel for re-issue**: `POST /api/v1/proforma/cancel-issued-for-reissue/{batch_id}/{client_name}`
7. **Adopt existing wFirma proforma**: `POST /api/v1/proforma/adopt-issued/{batch_id}/{client_name}`
8. **Refresh line names** (after wFirma good-name update): `POST /api/v1/proforma/{wfirma_id}/refresh-line-names`
9. **View proforma doc**: `GET /api/v1/proforma/{batch_id}/{client_name}/document`
10. **Proforma → invoice conversion**: handled by [proforma_to_invoice.py](service/app/services/proforma_to_invoice.py) (recently dirty — separate workstream)

### 6.3 Service files
- [`wfirma_client.py`](service/app/services/wfirma_client.py) — REST client
- [`wfirma_capabilities.py`](service/app/services/wfirma_capabilities.py) — feature flag gate
- [`wfirma_db.py`](service/app/services/wfirma_db.py) — local mirror
- [`wfirma_customer_sync.py`](service/app/services/wfirma_customer_sync.py)
- [`wfirma_reservation.py`](service/app/services/wfirma_reservation.py), [`wfirma_reservation_create.py`](service/app/services/wfirma_reservation_create.py)
- [`proforma_to_invoice.py`](service/app/services/proforma_to_invoice.py)
- [`proforma_invoice_link_db.py`](service/app/services/proforma_invoice_link_db.py)
- [`sales_linkage.py`](service/app/services/sales_linkage.py)
- Capability flags in [config.py](service/app/core/config.py:181-187): `wfirma_create_proforma_allowed`, `wfirma_edit_product_allowed`, `wfirma_edit_invoice_allowed`, `wfirma_sync_customers_allowed`, `wfirma_delete_invoice_allowed`, `wfirma_create_pz_allowed`. All default `False`.

### 6.4 UI surface
- `WfirmaExportPage` (sidebar `wfirma`, line 7425) — master data browse/edit
- `PzAccountingPage` (sidebar `pz`, line 7922) — per-batch PZ view
- `BatchDetailPage` → `PZ / wFirma` tab — preview → resolve products → create/adopt → view doc

---

## 7. Recommended Merged Accounting Module Structure

The current dashboard splits accounting concerns across **PZ / Accounting**, **wFirma**, and pieces of **Documents**. A coherent merged module:

```
Sidebar:  Accounting
  ├── Tab: Overview
  │     - this batch's PZ status (number + wFirma id + lock state)
  │     - this batch's proforma status (preview / issued / converted to invoice / wFirma id)
  │     - service invoices (DHL fees, agency fees) attached to this batch
  │     - GET /dashboard/batches/{id}, GET /api/v1/wfirma/reservation-preview/{id}
  │
  ├── Tab: Purchase (PZ)
  │     - Card: PZ document     → /api/v1/upload/shipment/{id}/wfirma/pz_preview
  │                              → ../pz_create OR ../pz_adopt
  │                              → ../pz_document
  │     - Card: Customs costs   → from engine: total_a00_pln + B00 ref
  │     - Card: Service invoices→ /api/v1/service-invoices/{id}/(received|upload)
  │
  ├── Tab: Sales
  │     - Card: Reservation     → /api/v1/wfirma/reservation-preview/{id}
  │                              → ../reservations/create
  │                              → reset-stuck recovery
  │     - Card: Proforma        → /api/v1/proforma/preview/.../create/.../adopt-issued
  │                              → cancel-issued-for-reissue
  │                              → refresh-line-names (after wFirma goods edit)
  │                              → document view
  │     - Card: Invoice (post-conversion) → proforma_to_invoice link via /sales/linkage/{id}
  │
  ├── Tab: Master Data
  │     - Customers tab    → /api/v1/wfirma/customers (list/edit/sync-preview/sync)
  │     - Products tab     → /api/v1/wfirma/products (list/edit), /goods/search, /goods/create-from-product-code
  │     - Capabilities     → /api/v1/wfirma/capabilities (read-only flag display)
  │
  ├── Tab: Audit
  │     - PZ readiness + locks   → /api/v1/dhl/readiness/{id} (existing readiness banner)
  │     - Closure check          → /api/v1/closure/{id}/check
  │     - Closure evaluate       → /api/v1/closure/{id}/evaluate
  │     - Sales linkage map      → /api/v1/sales/linkage/{id}
  │
  └── Tab: Reports
        - Existing Analytics phase-A    → /api/v1/analytics/phase-a
        - Per-customer revenue rollup   (NEW — see §8 Gaps)
        - Per-supplier purchase rollup  (NEW)
        - Open service-invoice ledger   (NEW)
```

This keeps **Purchase, Sales, Master Data, Audit** as a single Accounting cluster while preserving every existing endpoint. The DHL/Customs domain stays separate (operational, not accounting).

---

## 8. Missing Features / Gaps

Listed as **backend exists but UI gap** vs **truly missing**.

### 8.1 Backend exists, UI gap

| # | Capability | Backend | UI gap |
|---|---|---|---|
| 1 | Email queue browse/send/error inspection | `GET /api/v1/admin/email-queue`, `POST /admin/email-queue/{id}/send` | `AdminPage` has a list, but no rich filter (by `email_type` / `batch_id`), no error_detail viewer, no retry button next to failed entries |
| 2 | Service-invoice ledger | `POST /api/v1/service-invoices/{id}/received\|upload`, [service_invoice_monitor.py](service/app/services/service_invoice_monitor.py) | No accounting-side aggregate view (per supplier, open vs paid, per-batch fee breakdown) |
| 3 | Proforma → invoice conversion status | `proforma_to_invoice.py` + `proforma_invoice_link_db.py` | Sales tab shows proforma status but no clear "conversion done / pending / failed" state with link to the wFirma invoice id |
| 4 | DHL ticket / thread browser | `email_evidence_store` indexes by AWB + thread_id | No standalone "DHL conversations" view; only embedded in batch detail |
| 5 | wFirma customer sync diff preview | `GET /api/v1/wfirma/customers/sync-preview` | Wired in AdminPage but minimal; would benefit from per-row apply/skip controls |
| 6 | Action proposals queue (operator inbox) | `GET /api/v1/action-proposals/{batch_id}` per batch | No cross-batch view ("show all pending_review proposals across all shipments") |
| 7 | Tracking events export | `POST /api/v1/tracking/events/export` + `GET /export/download` | No UI button to trigger an export by date range or carrier filter |
| 8 | Closure evaluation history | `POST /api/v1/closure/{id}/evaluate` writes audit | No closure-history card showing prior evaluation runs |
| 9 | Path A auto-queue config / status | `settings.enable_path_a_auto_queue` flag | No UI toggle/status read; operators don't know whether it's on |
| 10 | DHL inbox scanner result | `GET /api/v1/dhl/scan-inbox` | Operator must hit it ad-hoc; no scheduled-scan dashboard surface |

### 8.2 Truly missing (no backend either)

| # | Capability | Why it would matter |
|---|---|---|
| A | **Retry button on failed queue entries directly from DhlActionCard** | Today operator must navigate to AdminPage |
| B | **Per-batch resend dialog with correction-mode pre-set** | Today the `correction=True` builder flag is reachable only via direct API or orchestrator scripting |
| C | **Path-A auto-queue UI feedback** — "next AWB to ship at DEPARTED_ORIGIN" preview + flag toggle | Avoids surprises when the flag is enabled |
| D | **Proactive-dispatch UI surface** — list AWBs eligible for proactive customs send + one-click create-and-queue | Today only the proposal-flow path; no batch-level dashboard |
| E | **Sales reservation diff vs. PZ inventory** | Catch over-allocation before wFirma create |
| F | **Dashboard delete endpoint scope mismatch** ([routes_dashboard.py:741](service/app/api/routes_dashboard.py:741) — known 404 root cause) — endpoint resolves under `outputs/{batch_id}/`, but Polish description PDFs live at `polish_descriptions/`. Either the endpoint needs a category param, or the dashboard needs separate delete buttons per file class. |
| G | **Email Evidence cross-AWB search** — find any DHL ticket / message by ticket# regardless of batch | Useful when DHL replies before AWB is mapped |
| H | **Audit timeline filter / export** | Today timeline is read-only embedded; no operator-facing query tool |
| I | **wFirma capability gate UI** — admin-side toggle (with audit) for the six `wfirma_*_allowed` flags | Today they live only in `.env` |

### 8.3 Architectural debt visible from inspection

- **Two sources for clearance path**: `audit.clearance_path` (top-level legacy) vs `audit.clearance_decision.clearance_path`. All observers correctly read the latter via [`clearance_path_alias.normalize_path()`](service/app/services/clearance_path_alias.py); UI should follow the same pattern.
- **Tracking events vs timeline**: locked invariant — `audit.tracking_events` is the transport telemetry source of truth; only `carrier_arrived_poland` and `carrier_delivered` cross into `audit.timeline` (see uncommitted dirty work in `tracking_normalizer.py`). UI should read both with source tags.
- **wFirma capability gate**: every wFirma write route is fronted by the `capabilities` registry. UI must call `GET /api/v1/wfirma/capabilities` to learn which buttons to enable/disable.

---

## 9. Files Claude Design Should Reference

### 9.1 Routing & shape
- [service/app/main.py](service/app/main.py) — every router mounted (lines 11-47, 167+)
- [service/app/api/](service/app/api/) — 39 `routes_*.py` files (one per domain)

### 9.2 UI source of truth
- [service/app/static/dashboard.html](service/app/static/dashboard.html) — single-file React SPA
  - NAV_ITEMS at line 76
  - `BatchDetailPage` at line 2111 (tab switch at line 2115; effects 2478-2491 lazy-load each tab's data)
  - `App` at line 10330 (page switch 10479-10487)
  - `DhlActionCard` at line 8903 (DHL flow operator card)
  - `EmailEvidenceTimeline` at line 9067 (email evidence per batch)
  - `AdminPage` at line 8417 (queue + master-data admin)
  - `IntelligencePage`, `AiBridgePage`, `LearningPage`, `ReportsPage` referenced at 10484-10487

### 9.3 Operational rules / business logic
- [CLAUDE.md](CLAUDE.md) — operating rules, Cliq integration, Cowork rules, financial rules
- [docs/dhl_clearance_paths.md](docs/dhl_clearance_paths.md) — Path A / B / agency definitions (referenced from [active_shipment_monitor.py:1107](service/app/services/active_shipment_monitor.py:1107))

### 9.4 Domain services (read for behaviors UI must reflect)
| Domain | File |
|---|---|
| Active monitor (sweep loop) | [active_shipment_monitor.py](service/app/services/active_shipment_monitor.py) |
| Action proposals | [routes_action_proposals.py](service/app/api/routes_action_proposals.py) |
| Email queue write | [email_service.py](service/app/services/email_service.py) |
| Email SMTP send + attachment resolver | [email_sender.py](service/app/services/email_sender.py) |
| Email evidence store | [email_evidence_store.py](service/app/services/email_evidence_store.py), [email_evidence_processor.py](service/app/services/email_evidence_processor.py), [email_evidence_ingestor.py](service/app/services/email_evidence_ingestor.py) |
| DHL builders | [dhl_proactive_dispatch_builder.py](service/app/services/dhl_proactive_dispatch_builder.py), [dhl_reply_builder.py](service/app/services/dhl_reply_builder.py), [dhl_self_clearance_builder.py](service/app/services/dhl_self_clearance_builder.py), [dhl_followup_email_builder.py](service/app/services/dhl_followup_email_builder.py) |
| DHL follow-up SLA | [dhl_followup_sla.py](service/app/services/dhl_followup_sla.py) |
| DHL email scan | [dhl_email_monitor.py](dhl_email_monitor.py) (root-level), [routes_dhl_clearance.py](service/app/api/routes_dhl_clearance.py) |
| Customs description PDF | [customs_description_engine.py](customs_description_engine.py), [description_engine.py](service/app/services/description_engine.py) |
| Customs parsing | [customs_parser_orchestrator.py](service/app/services/customs_parser_orchestrator.py), [customs_xml_parser.py](service/app/services/customs_xml_parser.py), [customs_validator.py](service/app/services/customs_validator.py), [ai_customs_parser.py](service/app/services/ai_customs_parser.py) |
| Tracking | [tracking_service.py](service/app/services/tracking_service.py), [tracking_normalizer.py](service/app/services/tracking_normalizer.py), [tracking_intelligence.py](service/app/services/tracking_intelligence.py), [tracking_db.py](service/app/services/tracking_db.py) |
| Decision/execution | [clearance_decision.py](service/app/services/clearance_decision.py), [agency_sad_decision.py](service/app/services/agency_sad_decision.py), [execution_engine.py](service/app/services/execution_engine.py) |
| AI Bridge | [ai_bridge.py](service/app/services/ai_bridge.py), [cowork_action_runner.py](service/app/services/cowork_action_runner.py), [cowork_result_processor.py](service/app/services/cowork_result_processor.py) |
| Intelligence | [intelligence_engine.py](service/app/services/intelligence_engine.py), [intelligence_parser.py](service/app/services/intelligence_parser.py), [intelligence_config_builder.py](service/app/services/intelligence_config_builder.py) |
| wFirma | [wfirma_client.py](service/app/services/wfirma_client.py), [wfirma_capabilities.py](service/app/services/wfirma_capabilities.py), [wfirma_reservation.py](service/app/services/wfirma_reservation.py), [proforma_to_invoice.py](service/app/services/proforma_to_invoice.py), [sales_linkage.py](service/app/services/sales_linkage.py) |
| Warehouse | [warehouse_db.py](service/app/services/warehouse_db.py), [warehouse_audit.py](service/app/services/warehouse_audit.py), [packing_db.py](service/app/services/packing_db.py) |
| Closure & lifecycle | [shipment_closure.py](service/app/services/shipment_closure.py), [service_invoice_monitor.py](service/app/services/service_invoice_monitor.py), [agency_sla_engine.py](service/app/services/agency_sla_engine.py) |
| Dashboard action registry (matrix) | [dashboard_action_registry.py](service/app/services/dashboard_action_registry.py), [dashboard_action_types.py](service/app/services/dashboard_action_types.py) |

### 9.5 Configuration & contracts
- [service/app/core/config.py](service/app/core/config.py) — Pydantic Settings (every flag + default)
- [service/app/core/timeline.py](service/app/core/timeline.py) — canonical event names (`EV_*` constants)
- [service/app/services/output_filenames.py](service/app/services/output_filenames.py) — file naming contract (`POLISH_DESC_AWB_…pdf`, `SAD_READY_…json`, etc.)
- [service/app/config/email_routing.py](service/app/config/email_routing.py) — DHL_TO / INTERNAL_CC canonical recipients
- [service/app/services/clearance_path_alias.py](service/app/services/clearance_path_alias.py) — legacy path normalization

### 9.6 What NOT to read (live data — never display in design specs)
- `storage_root/outputs/<batch_id>/audit.json` (live shipment state)
- `storage_root/email_queue.json` (live queue records)
- `storage_root/polish_descriptions/*.pdf` (live customs PDFs)
- `service/.env` (credentials)
- Any file under `storage_root/` at runtime

---

**End of pack.** All endpoints, file references, and line numbers are extracted from real source. UI gaps in §8 are derived from comparing the dashboard's URL set against the endpoint set in §1.
