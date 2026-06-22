# AUTHORITY_MAP.md — Estrella PZ Platform

**Campaign:** EJ PLATFORM CONSOLIDATION DISCOVERY
**Inspected:** `origin/main @ fb70e15` (clean detached worktree; read-only)
**Date:** 2026-06-18
**Companion docs:** [V1_V2_CAPABILITY_MATRIX.md](./V1_V2_CAPABILITY_MATRIX.md) · [DUPLICATE_AUTHORITY_REPORT.md](./DUPLICATE_AUTHORITY_REPORT.md) · [MIGRATION_ROADMAP.md](./MIGRATION_ROADMAP.md)

> Every concrete claim is backed by `file:line` evidence. Unverified items are marked **GAP:**. No speculation.

---

## 0. The one fact that reframes the whole campaign

**There is ONE shared FastAPI backend.** The "V1 vs V2" split is **not** two backends — it is a **frontend-generation** boundary over a single service layer (`service/app/main.py:418-508` registers ~80 routers, all shared). Consolidation is therefore overwhelmingly a **frontend** problem; the backend is the stable institutional layer (`docs/v2-architecture-plan.md §0`: "do not rewrite").

**The frontend has FOUR live surfaces, not two:**

| Surface | Location | Status | Shared libs |
|---|---|---|---|
| **V1 monolith** | `static/{dashboard.html (20,332 ln), shipment-detail.html (16,214 ln), batch.html, warehouse.html}` | **FROZEN** — critical-fix only (Lesson F) | `dashboard-shared.js`, `pz-api.js`, `pz-state.js`, `pz-components.js`, `components.js` |
| **Track-1 standalone V2-HTML** | `static/*-v2.html` (13 files) + `shipment-detail-v3.html` | Mixed: `proforma-v2.html` LIVE; others live/stub | v1 shared libs + `pz-design-v2.js` apiFetch shim |
| **Track-2 V2 JSX shell** | `static/v2/index.html` + `static/v2/*.jsx` (~30) | **WIRED_PAGES 17/17 (100%)** | `v2/pz-api.js`, `v2/pz-state.js`, inline apiFetch shim (ADR-028) |
| **Atlas shell** | `static/atlas/*.html` (8) + `atlas/atlas-shared.js` | Mostly read-only stubs; parallel nav tree | `atlas-shared.js` (separate) |

The internal **V2 fragmentation** (three parallel V2 expressions sharing forked copies of the same JS libs) is itself a primary consolidation finding — see [DUPLICATE_AUTHORITY_REPORT.md](./DUPLICATE_AUTHORITY_REPORT.md).

---

## 1. Backend route ownership (business-critical)

`AK` = `require_api_key` · `AK+ROLE` = + `require_role(admin/logistics)` · `AK+ADMIN` = + admin · `AK-ROLE` = master-data write role · `HMAC` = webhook secret · `SESSION` = cookie. Source for all: `service/app/main.py:418-508`.

| Router | Prefix | Primary service(s) | Persistence | Auth |
|---|---|---|---|---|
| `routes_pz.py` | `/api/v1` | `batch_service`, `export_service` (`process_batch()`), `global_pz_push` | per-batch `audit.json`/`pz_rows.json`; `documents.db` (`pz_documents`, `invoice_lines`) | AK |
| `routes_dashboard.py` | `/dashboard` (+`/api/v1`) | `operational_authority` (`derive_status/pz/sad`), `timeline_mapper`, `batch_manager` | per-batch JSON; batch lock | AK / AK+ADMIN (deletes) |
| `routes_wfirma.py` | `/api/v1/upload` | `wfirma_client`, `wfirma_db`, `pz_correction_lifecycle` | `wfirma.db`; `audit.wfirma_export` pointer | AK |
| `routes_wfirma_capabilities.py` | `/api/v1/wfirma` | `wfirma_capabilities`, `wfirma_customer_auto_resolve` | `wfirma.db` (customers, products) | AK |
| `routes_wfirma_reservation.py` | `/api/v1/wfirma` | `wfirma_reservation*` | `wfirma.db` (reservation_drafts/lines) | AK |
| `routes_proforma.py` | `/api/v1/proforma` | `proforma_draft_governance`, `proforma_draft_sync`, `proforma_to_invoice` | `proforma_links.db` (drafts, events, invoice_links, service_charges) | AK |
| `routes_proforma_adopt.py` | `/api/v1/proforma` | `wfirma_client` | `wfirma.db` | AK |
| `routes_sales.py` | `/api/v1/sales` | `sales_linkage` | `documents.db` (sales_documents, sales_packing_lines) | AK |
| `routes_packing.py` | `/api/v1/packing` | `packing_db`, `document_db`, `inventory_state_engine` | `packing.db` | AK / SESSION |
| `routes_warehouse.py` / `_audit` | `/api/v1/warehouse` | `warehouse_db`, `warehouse_audit` | `warehouse.db` (locations, current_location, movement/state events) | AK / SESSION |
| `routes_intake.py` | `/api/v1/shipment` | `awb_parser`, `invoice_packing_extractor`, `supplier_detect`, `intake_lineage` | `documents.db`, `packing.db`, `intake_lineage.db` | AK |
| `routes_lifecycle.py` | `/api/v1` | `agency_sad_monitor`, `shipment_closure` | per-batch `audit.json` timeline | AK |
| `routes_execute.py` | `/api/v1/execute` | lazy per-action (wfirma_create, dhl_send_reply, closure) | delegates | **AK-privileged** |
| `routes_dhl_clearance.py` | `/api/v1/dhl` | `dhl_clearance_coordinator`, `clearance_decision`, `email_routing` | per-batch `audit.json`; `documents.db` | AK / AK+ROLE (send) |
| `routes_dhl_followup*.py` | `/api/v1/dhl-followup` | `dhl_followup_sla`, `dhl_followup_email_builder` | per-batch timeline | AK+ROLE |
| `routes_dhl_documents.py` | `/api/v1/dhl-documents` | inline | per-batch timeline | AK+ROLE |
| `routes_inventory.py` (+ writes/sample/returns) | `/api/v1/inventory` | `inventory_*_writer`, `inventory_state_engine` | `warehouse.db` | AK |
| `routes_tracking*.py` | `/api/v1/tracking` | `tracking_service`, `tracking_db` | `tracking_events.db` | SESSION / AK+ROLE / AK |
| `routes_carrier_webhook.py` | `/api/v1/carrier/webhook` | `carrier.persistence.event_db` | `carrier/carrier_events.db` | **HMAC** |
| `routes_carrier_actions.py`/`_shadow` | `/api/v1/carrier` | `carrier.coordinator`, `carrier.factory` | `carrier/carrier_shipments.db`, `shadow_log.db` | AK |
| `routes_correction_registry.py` | `/api/v1/corrections` | `correction_registry` | `correction_registry.db` | AK+ADMIN |
| `routes_ledgers.py` | `/api/v1/ledgers` | `wfirma_client`, `ledger_aggregator` | reads wFirma API (no local write) | AK |
| `routes_finance_postings.py` | `/api/v1/finance/postings` | inline `finance_postings_db` | `master_data.sqlite` (GAP: path "lazy-on-call", unconfirmed) | AK |
| `routes_customer_master.py` | `/api/v1/customer-master` | `customer_master_db` | GAP: DB path unconfirmed | AK / AK-ROLE / AK+ADMIN |
| `routes_master_data.py` | `/api/v1/{hs-codes,units,…,box-types}` | `master_data_db` | `master_data.sqlite` (11 tables) | AK read / AK-ROLE write |
| `routes_master_jewelry.py` | `/api/v1/{metals,stones,warehouses}` | `metals_db`, `stones_db`, `warehouses_db` | `metals/stones/warehouses.sqlite` | AK read / AK-ROLE write |
| `routes_auth.py` | `/auth` | `auth/database` | `users.db` | **NONE** (public) |

**Read-only intelligence/AI cluster** (`routes_intelligence`, `_graph`, `workflow_`, `operations_`, `mdi`, `search`, `inbox`, `ai_bridge`, `ai_advisory`, `analytics`, `proposals`, `action_proposals`, `agents`, `monitor`, `orchestrator`): all `AK`, advisory/read-only, no business writes. The single AI execution authority is `ai_gateway.py` (ADR-020); no service may construct `anthropic.Anthropic()` directly (`ai_gateway.py:39-43`).

---

## 2. Persistence inventory (data stores)

**SQLite (init at startup, `main.py:164-179`):** `packing.db` · `warehouse.db` · `documents.db` (shipment/customs/awb/pz/sales/product tables) · `wfirma.db` · `correction_registry.db` · `intake_lineage.db` · `proforma_links.db` · `tracking_events.db` · `reservation_queue.db` · `master_data.sqlite` (11 tables) · `metals/stones/warehouses.sqlite` · `carrier/{carrier_events,carrier_shipments,shadow_log}.db` · `ai_call_ledger.db` · `users.db`.

**JSON flat-files (per-batch, under `storage_root/sessions/{batch_id}/`):** `audit.json` (projection; customs/verification/wFirma pointers/WorkDrive ids), `pz_rows.json`, `timeline.jsonl` (append-only durable authority for `reconcile_from_timeline`). **Global:** `email_queue.json`, `dhl_selfclearance_runtime_flags.json` (+ audit `.jsonl`).

**Authority rule (`docs/architecture/authority-ownership-and-incident-classes.md §2.2`):** `audit.json` is a **projection**; **wFirma is the system of record** for booked PZ. `audit.wfirma_export` is a pointer only — every external-reference key MUST be in `audit_merge.PRESERVED_KEYS` or each `process_batch()` run wipes it (the #570/#652 incident class; see memory `project_preserve_external_reference_authority`).

---

## 3. External integration boundaries

| Integration | Owner service | Auth/credential gate | Read/Write | Governing rule |
|---|---|---|---|---|
| **wFirma** | `wfirma_client.py` | 4 keys (`accessKey/secretKey/appKey` + company id); `_headers_for_module()` raises if missing (`wfirma_client.py:295-343`) | PZ create write **gated** by `wfirma_create_pz_allowed` (`:1518`); contractor/goods PUT; reads everywhere | Operator approval for any PZ create |
| **DHL Express** | `dhl_clearance_coordinator.py`, `dhl_followup_sla.py` | settings (GAP: env var names unconfirmed) | reply emails write; inbox/tracking read | self-clearance kill switches in JSON flag store; live label adapter `carrier/adapters/live.py:44` = `NotImplementedError` |
| **Zoho Cliq** | `cliq_service.py` (OAuth), `cliq_bot_service.py` (webhook) | `CLIQ_WEBHOOK_URL` + `cliq_bot_token` | posts to `#PZ` channel | notification never blocks on WorkDrive |
| **Zoho WorkDrive** | `workdrive_uploader.py` | OAuth refresh token | REST upload (primary); `workdrive_sync.py` TrueSync **DEPRECATED** | resource IDs from API response; never search/wait for TrueSync |
| **SMTP/email** | `email_service.py` | Zoho Mail REST (primary) → `email_queue.json` fallback | send | Lesson E five safety properties; sender `import@estrellajewels.eu` |
| **Anthropic** | `ai_gateway.py` (sole authority, ADR-020) | `anthropic_api_key` | all AI calls centralized; `ai_call_ledger.db` records every call | no direct SDK construction allowed |

---

## 4. Frontend entry points by generation (domain → routes called)

| Screen | Surface | Domain | Key backend routes |
|---|---|---|---|
| `dashboard.html` | V1 | cross-batch pipeline | `/dashboard/batches`, `/batch/{id}/readiness`, `/inventory/stage2/aggregate`, `/finance/postings`, `/customer-master`, cn-hsn/cn-decision, broker-followups |
| `shipment-detail.html` | V1 | full lifecycle (DHL/customs/PZ/proforma/wFirma/tracking/closure) | `/dashboard/batches/{id}`, `/packing/{id}`, `/proforma/draft/{id}/*`, `/dhl/*`, `/dsk/*`, `/execute/*`, `/upload/shipment/{id}/wfirma/*`, `/tracking/*` |
| `proforma-v2.html` (+`-detail-v2`) | Track-1 V2-HTML | proforma workspace (LIVE) | `/proforma/drafts/{id}`, `/proforma/draft/{id}/{approve,post,clone,to-invoice,readiness}`, `/wfirma/reservations/create` |
| `customer-master-v2.html`, `master-data-v2.html` | Track-1 V2-HTML | master data CRUD (designated V2 owner) | `/customer-master/*`, `/suppliers/*`, `/master/*`, `/wfirma/customers` |
| `v2/index.html` + `v2/*.jsx` | Track-2 JSX shell | all 17 wired domains | per-page; transport via `v2/pz-api.js` |
| `atlas/*.html` | Atlas shell | parallel read-only views | `/dashboard/batches`, `/search`, `/ledgers/clients/*` |

(Full per-workflow detail in [V1_V2_CAPABILITY_MATRIX.md](./V1_V2_CAPABILITY_MATRIX.md).)

---

## 5. Duplicate-authority flags (backend + cross-surface)

**5.1 — PZ-status derivation divergence (HIGH).** Canonical authority is `operational_authority.derive_pz_status` (`operational_authority.py:115`), correctly consumed by `routes_dashboard.py:31`. **But `routes_wfirma.py:146` `_compute_effective_pz_status()` is a still-live DUPLICATE** with extra "Path B" logic (accepts missing MRN if `pz_output.pdf` present), used at `routes_wfirma.py:289,325,341,1594,1648,1774`. The wFirma create-guard can therefore classify a PZ differently than the dashboard readiness check. Documented history at `operational_authority.py:4-9` ("three places → consolidated two of three") — this is the un-consolidated third. **Disposition: see [DUPLICATE_AUTHORITY_REPORT.md](./DUPLICATE_AUTHORITY_REPORT.md) R-? and [MIGRATION_ROADMAP.md](./MIGRATION_ROADMAP.md) §1.6.**

**5.2 — Warehouse-lifecycle classification is client-side only.** `deriveWarehouseLifecycle()` (`dashboard.html:9272`) buckets shipments (awaiting/partial/in_warehouse/reserved) entirely in 7 lines of V1 JavaScript; no backend endpoint owns this. Any V2 page needing the bucket must re-implement it or the backend must expose it. **Implicit authority gap.**

**5.3 — Readiness is backend-authoritative (no defect).** `pz-state.js:71-73` documents the invariant "data.ready comes from the backend; this hook NEVER computes ready locally." V1 client predicates (`OP_PREDICATES`) read already-derived server fields, not raw audit. Consistent across surfaces.

**5.4 — Valuation planes are intentionally three (no defect).** Sales (`excel_symbol`) / Cost (`packing_xlsx_value`) / Landed PLN (ZC429) are three distinct planes, frozen (`authority-ownership-and-incident-classes.md §2.3`; memory `project_three_authority_pz_engine_freeze`). Not a duplicate.

**5.5 — Frontend duplicate authority (HIGH, the bulk):** forked `pz-api.js`/`pz-state.js`, dual proforma write surfaces, ×5 shipment-detail and ×5 dashboard surfaces — fully enumerated in [DUPLICATE_AUTHORITY_REPORT.md](./DUPLICATE_AUTHORITY_REPORT.md).

---

## Information gaps (verify before acting)
- **GAP-1:** `customer_master`, `client_addresses`, `client_carrier_accounts`, `finance_postings` DB file paths not traced (callers pass paths).
- **GAP-2:** DHL API credential env-var names (read `core/config.py`).
- **GAP-3:** `v2/ledgers-page.jsx`, `v2/master-page.jsx` call APIs via imported hooks (no inline `/api/v1` literals) — route set inferred, not line-cited.
- **GAP-4:** router total is approximate ("~80 registered; ~55 business-critical + read-only intelligence cluster") — exact count not material to authority ownership.
