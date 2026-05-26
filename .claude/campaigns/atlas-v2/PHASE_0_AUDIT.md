# Atlas V2 — Phase 0 Architecture Validation

**Date:** 2026-05-26
**Author:** orchestrator session (autonomous inspection)
**Scope:** read-only inspection. Zero code edits. Zero PRs. Zero sprint-file rewrites.
**Goal:** validate the 23-sprint wireframe campaign against existing EJ Dashboard implementation authority before any sprint fires.

---

## A. Repository Ground Truth (inspected)

### A.1 Static frontend (`service/app/static/`)

| File | LOC | Role | V1/V2 | Status |
|------|-----|------|-------|--------|
| `dashboard.html` | 20,287 | V1 monolith — owns NAV, app shell, all domain pages | V1 | **FROZEN** (Lesson F) |
| `shipment-detail.html` | 15,702 | V1 monolith — per-shipment renderer (incl. PZ Correction) | V1 | **FROZEN** (Lesson F) |
| `batch.html` | 3,819 | V1 batch detail | V1 | FROZEN |
| `warehouse.html` | 601 | V1 warehouse scan-in | V1 | FROZEN |
| `admin-users.html` | 766 | V1 admin | V1 | FROZEN |
| `login.html` / `signup.html` / `forgot-password.html` | ~1,600 | V1 auth | V1 | FROZEN |
| `dashboard-shared.js` | 517 | Visual atoms · `window.EstrellaShared` | V2 layer | ACTIVE |
| `components.js` | 450 | Nav + layout + V1 SectionHeader · `window.EstrellaDash` | V1/V2 bridge | ACTIVE |
| `pz-api.js` | 210 | Transport · `window.PzApi` | V2 layer | ACTIVE |
| `pz-state.js` | 125 | Hooks · `window.PzState` | V2 layer | ACTIVE |
| `pz-components.js` | 343 | Domain renderers · `window.PzComponents` | V2 layer | ACTIVE |
| `proforma-v2.html` | 797 | V2 reference page (Estrella branding, gold) | V2 | DONE |
| `ai-advisory-v2.html` | 143 | V2 page — DIFFERENT design system (blue accent, system font) | V2 | **DIVERGENT** ⚠ |

### A.2 Backend route registry (`service/app/api/routes_*.py`)

**62 route files inventoried.** Highlights relevant to V2 sprints:

| Route file | Prefix | Owns |
|------------|--------|------|
| `routes_dashboard.py` | `/dashboard` | Batches list/detail, files, source-file CRUD, regenerate, status derivation (`_derive_clearance_status`, `_derive_pz_status`, `_derive_sad_status`, `_warehouse_hint`, `_sales_hint`, `_wfirma_hint`) — **this IS the dashboard backend authority** |
| `routes_search.py` | `/api/v1/search` | Global search — **already exists** |
| `routes_ledgers.py` | `/api/v1/ledgers` | Client invoice ledger, client statement, **statement PDF download** — **already exists** |
| `routes_proforma.py` | `/api/v1/proforma` | Proforma drafts, wFirma client matching, prefix/reverse-prefix logic |
| `routes_proforma_adopt.py` | (proforma) | Proforma adoption |
| `routes_pz.py` | `/api/v1/pz` | PZ lineage, correction state machine, 8 correction endpoints |
| `routes_wfirma.py` | `/api/v1/upload` | wFirma PZ create/adopt/confirm + 10 POST writes |
| `routes_wfirma_capabilities.py` | (wFirma) | Capability discovery |
| `routes_wfirma_reservation.py` | (wFirma) | Reservation gating |
| `routes_customer_master.py` | `/api/v1/customer-master` | Customer CRUD + wFirma sync preview/apply + dictionaries |
| `routes_master_data.py` | (master) | Product/master data |
| `routes_inventory.py` | `/api/v1/inventory` | Stage 2 aggregate, piece state, batch state |
| `routes_inventory_writes.py` | (inventory) | Write mutations |
| `routes_inventory_sample.py` | (inventory) | Sample piece flow |
| `routes_inventory_returns.py` | (inventory) | Return flow |
| `routes_reservations.py` | `/api/v1` | Reservation queue + sales-packing import + wFirma sync-by-codes |
| `routes_warehouse.py` | `/api/v1/warehouse` | Scan, locations CRUD, inventory-by-location |
| `routes_warehouse_audit.py` | (warehouse) | Warehouse audit |
| `routes_carrier_actions.py` + `routes_carrier_shadow.py` + `routes_carrier_webhook.py` + `routes_client_carrier_accounts.py` | (carriers) | Carrier accounts + actions + shadow + webhooks |
| `routes_dhl_clearance.py` + `routes_dhl_documents.py` + `routes_dhl_followup.py` + `routes_dhl_readiness.py` + `routes_dsk.py` + `routes_agency.py` | (DHL/customs) | DHL self-clearance flows |
| `routes_correction_registry.py` | (correction) | PZ correction registry |
| `routes_lifecycle.py` | (lifecycle) | Lifecycle state machine endpoints |
| `routes_admin.py` + `routes_admin_dhl_clearance.py` + `routes_admin_runtime_flags.py` | `/api/v1/admin` | Admin + email queue + runtime flags kill-switches |
| `routes_ai_advisory.py` + `routes_ai_bridge.py` + `routes_intelligence.py` + `routes_intelligence_graph.py` + `routes_operations_intelligence.py` + `routes_workflow_intelligence.py` | (AI advisory) | Phase 1 advisory + intelligence graph |
| `routes_action_proposals.py` + `routes_proposals.py` + `routes_orchestrator.py` + `routes_execute.py` | (workflow) | Action engine |
| `routes_settings.py` + `routes_system.py` + `routes_debug.py` + `routes_monitor.py` | (admin) | System surfaces |
| `routes_tracking.py` + `routes_tracking_db.py` | (tracking) | DHL tracking |
| `routes_packing.py` + `routes_packing_resolution.py` | (packing) | Packing list flows |
| `routes_finance_postings.py` + `routes_sales.py` + `routes_suppliers.py` | (finance) | Postings, sales, suppliers |
| `routes_auth.py` | `/api/v1/auth` | Auth |
| `routes_batch.py` + `routes_batch_readiness.py` | `/api/v1/batch` | Batch sessions + readiness |

### A.3 ADR authority (relevant)

| ADR | Binding |
|-----|---------|
| ADR-003 | Coordinator state engine — lifecycle authority |
| ADR-010 | Default-OFF feature flags — must not bypass |
| ADR-011 | Multi-agent engineering cell |
| ADR-017 | Carrier label store retention |
| ADR-018 | Shadow-mode flag defaults |
| ADR-019 | DHL self-clearance proactive dispatch |
| ADR-020 | Anthropic API sole provider |

No ADR explicitly governs frontend layer authority. **Frontend authority is governed by Lesson F + this campaign — there is no codified ADR for V2 yet.** Recommendation: file ADR-021 before Sprint 13 (Dashboard aggregator) opens.

### A.4 NAV_TREE already exists

`components.js` lines 36-55 ship a canonical `window.NAV_TREE`:

```
dashboard, inbox, shipments, documents, accounting, inventory, reports,
g_setup → { admin, admin_users, master, carriers, wfirma_setup, api_status }
```

The 23-sprint plan **must consume this NAV_TREE**, not invent a parallel one. New V2 pages plug into existing nav slots.

---

## B. Authority Map (per sprint)

Format: **Screen** → existing route(s) consumed → service owner → persistence owner → **risk verdict**.

| Sprint | Screen | Existing route | Service / persistence owner | Risk |
|--------|--------|----------------|------------------------------|------|
| 01 | proforma-v2.html | `routes_proforma.py`, `routes_proforma_adopt.py` | proforma_service + wFirma | ✅ DONE — verified consume-only |
| 02 | inbox-v2.html | `routes_batch.py` + `routes_batch_readiness.py` + `routes_tracking.py` + `routes_dhl_clearance.py` | dhl_clearance_service | ⚠ **risk:** sprint claims "may need read-only field additions" — must verify before opening |
| 03 | shipment-v2.html | `routes_dashboard.py` (batch_detail, files) + `routes_pz.py` + `routes_dhl_clearance.py` | dashboard_service + lifecycle | ⚠ **risk:** shipment-detail.html V1 has 15.7K LOC; surface area extraction needed before sprint |
| 04 | documents-v2.html | `routes_dashboard.py` (files, source files) + `routes_dhl_documents.py` | dashboard_service | ✅ consume-only feasible |
| 05 | customer-master-v2.html | `routes_customer_master.py` (full CRUD + wFirma sync exists) | customer_master_service | ✅ **frontend-only sprint** — re-scope sprint file to remove "new endpoints" |
| 06 | products-v2.html | `routes_master_data.py` + `routes_wfirma.py` (products) | master_data_service | ✅ consume-only feasible |
| 07 | pz-v2.html | `routes_pz.py` + `routes_wfirma.py` | pz_correction_state + global_pz_push | ⚠ **collision with PZ Correction V2 campaign** (`.claude/campaigns/pz-correction-v2-uxmod.md`) — separate active campaign owns this surface |
| 08 | warehouse-v2.html | `routes_warehouse.py` + `routes_warehouse_audit.py` | warehouse_service | ✅ consume-only feasible |
| 09 | inventory-v2.html | `routes_inventory.py` + `routes_inventory_writes.py` + `routes_inventory_sample.py` + `routes_inventory_returns.py` + `routes_reservations.py` | inventory_state_machine | ⚠ **5 backend route files; surface area is large** — sprint must explicitly map all 5 in pre-flight |
| 10 | batch-v2.html | `routes_batch.py` + `routes_batch_readiness.py` + `routes_dashboard.py` | batch_service | ✅ consume-only |
| 11 | admin-v2.html | `routes_admin.py` + `routes_admin_dhl_clearance.py` + `routes_admin_runtime_flags.py` + `routes_settings.py` + `routes_system.py` | admin_service | ⚠ **runtime flags = kill-switch authority** — write paths require security-permissions verdict |
| 12 | auth-v2 | `routes_auth.py` | auth_service | ✅ existing |
| 13 | dashboard-v2.html | `routes_dashboard.py` aggregator | dashboard_service | ⚠⚠ **major risk** — V1 dashboard.html is 20K LOC; V2 must NOT duplicate `_derive_*` logic that lives in `routes_dashboard.py`. Backend derivation stays authoritative |
| 14 | accounting-hub-v2.html | **REVISED**: existing `routes_proforma.py`, `routes_wfirma.py` (PZ), `routes_ledgers.py`, `routes_finance_postings.py`, `routes_sales.py`, `routes_suppliers.py` | wFirma + finance_postings | ⚠ sprint file claimed "NEW read-only endpoints for proforma/invoice/credit-note/wz" — **most already exist**; sprint must be re-scoped to consume |
| 15 | ledgers-v2.html | `routes_ledgers.py` **fully exists** incl. statement PDF | ledgers_service | ⚠⚠ sprint file claimed "NEW endpoints" — **all required endpoints already exist**. Re-scope to frontend-only consumption + Lesson G cache-header verification of existing PDF endpoint |
| 16 | carriers-v2.html | `routes_client_carrier_accounts.py` + `routes_carrier_actions.py` + `routes_carrier_shadow.py` + `routes_carrier_webhook.py` | carrier_service | ⚠ 4 backend route files — surface area mapping required pre-sprint |
| 17 | shipping-ops-v2.html | `routes_carrier_actions.py` + `routes_packing.py` + `routes_tracking.py` | carrier + packing | ✅ wireframe-disabled pattern matches sprint discipline |
| 18 | global-search overlay | `routes_search.py` **exists** at `/api/v1/search` | search_service | ⚠ sprint file claimed "NEW endpoint" — **already exists**. Re-scope to frontend overlay only |
| 19 | dashboard-kanban-v2.html | `routes_dashboard.py` `_derive_clearance_status` + `_derive_status` already produce lane data | dashboard_service | ⚠ **lane derivation already in backend** — sprint must consume, not re-derive |
| 20 | ops-cell-v2.html | 6 panels — every endpoint exists | mixed | ✅ pure consume |
| 21 | client-kyc-consignment-v2.html | `routes_customer_master.py` + `routes_inventory_returns.py` + (KYC fields TBD) | customer_master + inventory_state_machine | ⚠ KYC field schema may require new persistence — extends customer-master, must not duplicate identity |
| 22 | api-status-v2.html | `routes_monitor.py` + `routes_admin.py` + `routes_admin_runtime_flags.py` | admin_service | ⚠ aggregated `/api/v1/admin/api-status` does not exist as single endpoint — sprint must verify or add aggregator |
| 23 | docs-suite-v2 | `routes_dashboard.py` (regenerate) + `routes_ledgers.py` (statement PDF) + per-doc-type generators | document_render service | ⚠ Lesson G applies to **every** generator endpoint added/modified |

---

## C. Duplicate Authority Risks (top findings)

### C.1 Two component-layer libraries coexist (HIGH)

`dashboard-shared.js` and `components.js` are both active, with overlapping concerns:
- Both define `SectionHeader` — intentionally different signatures, documented as known split
- NAV_TREE lives in `components.js` AND in `dashboard.html` (twice!)
- STATUS_MAP is duplicated between `dashboard-shared.js` and `dashboard.html` (documented as intentional)

**Risk for V2 sprints:** every new V2 page must pick the right import surface (`EstrellaShared` vs `EstrellaDash`). Sprint files do not consistently specify which.

**Recommendation:** before Sprint 02 fires, add explicit "import surface" clause to every sprint file. Preferred: V2 pages import from `EstrellaShared` only (atoms) + V2-specific layers (`PzApi`, `PzState`, `PzComponents`). `EstrellaDash` is V1 territory.

### C.2 Two V2 design systems in production (HIGH)

- `proforma-v2.html`: Estrella branding (gold #B89968, Plus Jakarta Sans, dark sidebar)
- `ai-advisory-v2.html`: Blue accent (#2563eb), system font, minimal palette

The 23-sprint plan assumes proforma-v2.html as the reference. `ai-advisory-v2.html` is NOT in the sprint list and uses a divergent system.

**Recommendation:** add disposition for `ai-advisory-v2.html`:
- Option A: re-style to match proforma-v2 tokens (1-sprint task, not currently in plan)
- Option B: explicitly accept as a tooling page outside the operator workflow
- Decision needed before Sprint 13 (Dashboard aggregator) so nav doesn't expose a visually inconsistent surface

### C.3 Sprints 14/15/18 claim "new endpoints" that already exist (HIGH)

| Sprint | Sprint file claim | Reality |
|--------|-------------------|---------|
| 14 Accounting Hub | "NEW: `/api/v1/accounting/proforma`, `/api/v1/accounting/invoice`, `/api/v1/accounting/wz`, `/api/v1/accounting/credit-note`" | `routes_proforma.py`, `routes_wfirma.py`, `routes_sales.py`, `routes_finance_postings.py` already serve this data under different prefixes |
| 15 Ledgers | "NEW: `/api/v1/ledger/{party}/transactions`, `/api/v1/ledger/{party}/aging`, `/api/v1/ledger/{party}/statement.pdf`" | `routes_ledgers.py` (prefix `/api/v1/ledgers`) already implements `get_client_invoice_ledger`, `get_client_statement`, `get_client_statement_pdf` |
| 18 Global Search | "NEW: `/api/v1/search?q=&types=`" | `routes_search.py` already exists at `/api/v1/search` with `search()` |

**Recommendation:** before firing 14/15/18, the sprint files must be amended to either:
- Drop the "new endpoint" sections entirely and reference existing routes
- OR explicitly justify additive endpoints (e.g. aggregated convenience endpoints) with system-architect verdict

Without this amendment, these sprints will produce **duplicate authority** in the backend (a second route registry for the same data).

### C.4 Sprint 19 (Kanban) lane derivation already exists (MEDIUM)

`routes_dashboard.py` already has `_derive_clearance_status`, `_derive_status`, `_derive_pz_status`, `_derive_sad_status`. These produce the lane labels Sprint 19 wants.

**Recommendation:** Sprint 19 consumes existing batch list with derived statuses and groups client-side — NO new lane-derivation endpoint.

### C.5 Sprint 13 vs V1 dashboard.html (HIGH)

V1 `dashboard.html` is 20,287 lines. Sprint 13 says "Dashboard V2 is built last." But the sprint doesn't enumerate WHAT V1 dashboard responsibilities are being migrated, only that it aggregates domain pages.

**Risk:** without a V1-dashboard responsibility inventory, Sprint 13 may either (a) miss responsibilities V1 carried implicitly, or (b) duplicate them in V2 while V1 still owns them.

**Recommendation:** add a Sprint 12.5 (or pre-Sprint-13 audit) that produces a `dashboard.html` responsibility map: NAV ownership, page registry, redirect logic, app shell, status badges, modals — each item dispositioned (move to V2, retire, retain in V1).

### C.6 PZ Correction V2 campaign collides with Sprint 07 (MEDIUM)

Active separate campaign at `.claude/campaigns/pz-correction-v2-uxmod.md` creates `pz-correction-v2.html` — overlaps with Sprint 07 (pz-v2.html). Two surfaces claiming PZ authority.

**Recommendation:** decide before either fires:
- (a) Sprint 07 absorbs pz-correction-v2 scope, the standalone campaign is closed
- (b) Sprint 07 is narrowed to "PZ list + PZ creation"; pz-correction-v2 owns correction lifecycle; nav has both entries
- (c) PZ correction is a section within pz-v2.html, separate campaign file is archived

### C.7 Sprint 09 inventory: 5 route files behind one surface (MEDIUM)

`routes_inventory.py`, `routes_inventory_writes.py`, `routes_inventory_sample.py`, `routes_inventory_returns.py`, `routes_reservations.py` all front the inventory domain. Sprint 21 (consignment) also writes here via `routes_inventory_returns.py`.

**Recommendation:** Sprint 09 file must include a "backend surface map" section enumerating all 5 route files and what UI elements consume which. Sprint 21 must explicitly defer return-flow legality to `inventory-state-machine` service (already an agent) rather than implementing client-side state rules.

### C.8 ai-advisory-v2.html unaccounted for (LOW)

Existing V2 file not in the 23-sprint roadmap. Decision needed (re-skin or accept divergence — see C.2).

---

## D. Sprint Readiness Matrix (REVISED)

Verdicts: **READY** (sprint file consistent with reality) · **AMEND** (sprint file needs correction before firing) · **BLOCKED** (cannot fire until prerequisite resolved) · **CONFLICT** (collides with another campaign).

| # | Sprint | Verdict | Required action before firing |
|---|--------|---------|-------------------------------|
| 01 | Proforma V2 Hardening | DONE | — |
| 02 | Inbox V2 | AMEND | Spec the "import surface" (EstrellaShared vs EstrellaDash); identify exact existing endpoint that returns `clearance_status` + `dhl_email_received` (or confirm new field needed) |
| 03 | Shipment V2 | AMEND | Inventory `shipment-detail.html` V1 responsibilities first; produce surface-extraction map |
| 04 | Documents V2 | READY | — |
| 05 | Customer Master V2 | AMEND | Re-scope to frontend-only (backend already complete via `routes_customer_master.py`) |
| 06 | Products V2 | READY | — |
| 07 | PZ V2 | CONFLICT | Resolve overlap with `pz-correction-v2-uxmod` campaign (C.6) |
| 08 | Warehouse V2 | READY | — |
| 09 | Inventory V2 | AMEND | Add 5-route-file surface map; resolve write paths through inventory-state-machine |
| 10 | Batch V2 | READY | — |
| 11 | Admin V2 | AMEND | Specify runtime-flags write-gate posture (kill-switch authority preserved) |
| 12 | Auth V2 | READY | — |
| 13 | Dashboard V2 | BLOCKED | Requires Sprint 12.5 V1-responsibility inventory + ADR-021 frontend-authority codification |
| 14 | Accounting Hub V2 | AMEND | Drop "new endpoint" claims; map to existing routes_proforma + routes_wfirma + routes_finance_postings + routes_sales + routes_suppliers |
| 15 | Ledgers V2 | AMEND | Drop "new endpoint" claims; consume existing `routes_ledgers.py` (statement PDF already exists — verify Lesson G headers, do not re-implement) |
| 16 | Carriers V2 | AMEND | Add 4-route-file surface map (`carrier_actions`, `carrier_shadow`, `carrier_webhook`, `client_carrier_accounts`) |
| 17 | Shipping Ops V2 | READY | — wireframe-disabled discipline aligns with reality |
| 18 | Global Search V2 | AMEND | Drop "new endpoint" claim; consume existing `routes_search.py`. Add NAV slot integration via `components.js` |
| 19 | Dashboard Kanban V2 | AMEND | Remove "new `/api/v1/dashboard/kanban`" endpoint; group existing batch list by derived `_derive_status` client-side |
| 20 | Ops Cell V2 | READY | — pure consume |
| 21 | KYC + Consignment V2 | AMEND | Define KYC field set as customer-master EXTENSION; return-flow must call `routes_inventory_returns.py` (not direct DB) |
| 22 | API Status V2 | AMEND | Decide: add backend aggregator endpoint OR client-side aggregate from existing surfaces |
| 23 | Docs Suite V2 | READY-WITH-GATE | Lesson G regression tests are gate condition (already in sprint file) |

**Tally:** 1 DONE · 6 READY · 13 AMEND · 1 CONFLICT · 1 BLOCKED · 1 READY-WITH-GATE.

**Headline:** 14 of 22 remaining sprints need amendment or unblocking before they can safely fire.

---

## E. Revised Execution Order (proposed)

Honors GATE 2 (≤3 open PRs), Lesson F sequencing, and authority-clean-first principle.

**Wave 0 — Governance fixes (no implementation):**
1. Amend sprint files 02, 03, 05, 09, 11, 14, 15, 16, 18, 19, 21, 22 with reality-aligned scope
2. Resolve PZ Correction overlap (C.6) — written decision
3. File ADR-021 — frontend layer authority (component library boundary, V2 nav integration rule)
4. Pre-Sprint-13 audit: V1 dashboard.html responsibility map

**Wave 1 — Authority-clean reads (consume-only):**
- Sprint 04 Documents V2
- Sprint 06 Products V2
- Sprint 10 Batch V2
- Sprint 12 Auth V2
- Sprint 20 Ops Cell V2
- Sprint 17 Shipping Ops V2 (wireframe-disabled writes)

**Wave 2 — Domain surfaces after amendments land:**
- Sprint 02 Inbox V2 (amended)
- Sprint 05 Customer Master V2 (amended, frontend-only)
- Sprint 08 Warehouse V2
- Sprint 18 Global Search overlay (amended)
- Sprint 15 Ledgers V2 (amended, frontend-only)
- Sprint 14 Accounting Hub V2 (amended)
- Sprint 16 Carriers V2 (amended)
- Sprint 22 API Status V2 (amended)

**Wave 3 — Lifecycle-heavy surfaces:**
- Sprint 03 Shipment V2 (after V1 responsibility extraction)
- Sprint 09 Inventory V2 (after surface map)
- Sprint 11 Admin V2 (after kill-switch posture)
- Sprint 21 KYC + Consignment V2

**Wave 4 — PZ track (after C.6 decision):**
- Sprint 07 PZ V2 OR pz-correction-v2 (per resolution)

**Wave 5 — Visualizers:**
- Sprint 19 Dashboard Kanban V2

**Wave 6 — Aggregator (final domain layer):**
- Sprint 13 Dashboard V2 (after Wave 0–5 land and ADR-021 codified)

**Wave 7 — Document polish:**
- Sprint 23 Docs Suite V2 (Lesson G gated)

---

## F. Exact Next Steps (before Sprint 02 fires)

1. **Operator decision**: PZ Correction V2 collision (C.6) — pick (a)/(b)/(c). Without this, Sprint 07 cannot fire and PZ Correction V2 campaign sits in limbo.

2. **Sprint amendment pass** (zero code, only sprint-file edits): apply C.3 corrections to sprints 14, 15, 18, 19. These four are the most reality-divergent.

3. **Component-import clause**: add to every sprint file a line: `Import surface: EstrellaShared atoms ONLY (no EstrellaDash for V2 pages).` Single line, prevents drift.

4. **ADR-021 draft** — frontend layer authority (component library boundary, V2 nav integration, V1-freeze enforcement, V2 design-system canonicalization). Cite proforma-v2.html as the reference implementation.

5. **V1 dashboard.html responsibility inventory** — required input for Sprint 13. ~1 session of read-only work.

6. **ai-advisory-v2.html disposition** (C.2/C.8) — re-skin sprint OR explicit "accept divergence" entry in atlas-v2.md.

7. **Only AFTER 1–6 are dispositioned**, Sprint 02 fires.

---

## G. What This Audit Did NOT Do

- Did **NOT** edit any sprint file (those edits are Wave 0; require explicit go-ahead)
- Did **NOT** open any PR or branch
- Did **NOT** touch backend code
- Did **NOT** delete or rename anything
- Did **NOT** speculate about root cause of any future failure
- Did **NOT** read every JSX wireframe in source-bundle (sampled headers only; full read deferred to per-sprint amendment work)

---

## H. Files Inspected (provenance)

| File | Inspection depth |
|------|------------------|
| `README.md`, `CLAUDE.md` | listed (CLAUDE.md content available via session context) |
| `.claude/campaigns/atlas-v2.md` | full read |
| `.claude/campaigns/atlas-v2/sprint-{01..23}-*.md` | sprint list + sample contents read |
| `service/app/static/dashboard-shared.js` | header inspected |
| `service/app/static/components.js` | header inspected — NAV_TREE confirmed |
| `service/app/static/proforma-v2.html` | header + CSS tokens inspected |
| `service/app/static/ai-advisory-v2.html` | header inspected — design divergence confirmed |
| `service/app/static/dashboard.html` | NAV_TREE references inspected |
| `service/app/api/routes_*.py` | 62 files listed; targeted greps for routes_ledgers/search/dashboard/customer_master/inventory/reservations/warehouse/wfirma/proforma/admin |
| `.claude/adr/ADR-{001..020}.md` + README | listed; ADR-003/011/019 headers inspected |
| `origin/atlas-v2/source-bundle` design files | listed |

Repository HEAD at inspection time: `main @ ca00640`.

---

**End of Phase 0 Audit.** Awaiting operator disposition on items F.1 and F.6 before any sprint amendments or implementation fires.
