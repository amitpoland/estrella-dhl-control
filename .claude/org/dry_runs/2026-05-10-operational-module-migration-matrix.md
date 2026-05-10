# Operational Module Migration Matrix — New Dashboard Design

**Mode:** PRE-IMPLEMENTATION
**Scope:** module-by-module coverage matrix between the new
Estrella Atlas design bundle and the existing operational
dashboard. Doc-only — extends the migration analysis at
`2026-05-10-new-dashboard-design-migration.md`.
**Baseline:** `54d2e39` (migration analysis closed)
**Coordinator pass:** in-context (Opus); reviewer roles
(UI/UX Planner, Backend Architect, Route/API Mapper, Operator
Safety, Security, QA Lead, Gap Hunter) executed as
Coordinator-simulated parallel reads.

This artifact is the *deeper* lookup table the operator asked
for: every module the existing service operates, mapped against
the new design's coverage, with a per-module migration verdict.

---

## 0. Pre-flight gates

| Gate | Result |
|---|---|
| `git status --short` | clean |
| Branch | `feature/dhl-label-workflow-planning` |
| Dashboard suite (36 files) | **1032 / 1032** pass |
| `make verify` | **160 / 160** pass |
| Active code lane | none |

---

## 1. Existing module inventory

The operational dashboard ships ten substantive modules. For each
one the table below names the surface in `dashboard.html`, the
per-batch tab it lives under, and the test files that currently
pin it.

| # | Module | Surface in `dashboard.html` | Per-batch tab | Pinning test files |
|---|---|---|---|---|
| 1 | **PZ create / outputs / readiness** | `BatchDetailPage` PZ flow with `pzPreview` state, lock-status banner, unresolved-products card, `wfirma_pz_create` / `pz_adopt` triggers | `PZ / wFirma` | `test_dashboard_run_pz_gate.py`, `test_dashboard_pz_operator_header.py`, `test_dashboard_polish_desc_delete.py` |
| 2 | **wFirma setup / reservation preview / mapping / PZ export** | `wfirma_pz_preview` loader, `wfirma_reservation_preview_panel` card, product `resolve` POST, `wfirma_pz_document` link, `wfirma_search` panel | `PZ / wFirma` (per-batch) + sidebar wFirma quick link | `test_dashboard_wfirma_reservation_preview_panel.py`, `test_dashboard_wfirma_search.py` (the latter pins forbidden `goods/add` marker) |
| 3 | **Warehouse / direct dispatch / barcode / packing list / inventory state** | Warehouse audit panel under `BatchDetailPage`, `packing-list-card`, link to `/dashboard/warehouse.html` standalone scanner | `Warehouse` | `test_dashboard_packing_list_card.py`, `test_dashboard_repair.py` (route-audit), warehouse_scanner page lives separately |
| 4 | **Sales / invoice readiness / WDT** | Sales blocks in shipment-create form, `sales-linkage` panel under `BatchDetailPage`, sales-linkage ready/blocked flags, WDT export through proforma → invoice path | `Sales` + `PZ / wFirma` overlap | `test_dashboard_sales_linkage_panel.py` |
| 5 | **Proforma drafts / proforma-to-invoice conversion** | Proforma drafts cross-batch page, `proforma_draft_panel` per-client card under `BatchDetailPage`, `proforma/to-invoice-preview` + `to-invoice` POSTs | `Sales` (per-client cards) + standalone cross-batch page | `test_dashboard_proforma_draft_panel.py`, `test_dashboard_proforma_drafts_cross_batch.py` |
| 6 | **Customer statements** | Standalone statements picker page + `customer-statement-drawer` (per-customer aging report, PDF link, FROM/TO/AS-OF date filters) | n/a — top-level page | `test_dashboard_customer_statements_picker.py`, `test_dashboard_customer_statement_drawer.py` |
| 7 | **Closure checks** | `closure-eval-card` (read-only `/closure/.../check`), `closure-confirm-section` (POST `/api/v1/execute/closure_confirm` with `payload: {}` + `approved_by`) | `Overview` + `PZ / wFirma` (closure surface) | `test_dashboard_closure_eval_card.py`, `test_dashboard_execution_guards.py` (closure-confirm contract) |
| 8 | **Agency documents** | `agency-docs-received-card` (multipart upload to `/api/v1/agency-documents/{batch_id}/upload`), agency SAD decision card, agency SLA status, agency SAD parse status | `DHL / Customs` | `test_dashboard_agency_docs_card.py`, `test_dashboard_agency_sad_decision.py`, `test_dashboard_agency_sad_parse_status.py`, `test_dashboard_agency_sla_status.py` |
| 9 | **DHL documents received** | `dhl-docs-received-card` (multipart upload to `/api/v1/dhl-documents/{batch_id}/upload`), `dhl-docs-source-auto` / `dhl-docs-source-manual` badges, `dhl-action-state` strip | `DHL / Customs` | `test_dashboard_dhl_documents_received_card.py`, `test_dashboard_dhl_action_state.py` |
| 10 | **Broker followups** | `broker-followup-panel` (drafts list, status badge, missing-invoices, CIF gap, send modal with confirm-warning) + cross-batch broker-followups page | `DHL / Customs` (per-batch) + standalone cross-batch page | `test_dashboard_broker_followup_panel.py`, `test_dashboard_broker_followups_cross_batch.py` |

Auxiliary surfaces also tested but outside the ten focus modules: `test_dashboard_action_proposals_cross_batch.py`, `test_dashboard_actions.py`, `test_dashboard_actions_v2.py`, `test_dashboard_batch_list_status_columns.py`, `test_dashboard_cache_freshness_api.py`, `test_dashboard_doc_suite_design.py`, `test_dashboard_execution_guards.py`, `test_dashboard_missing_functions_matrix.py`, `test_dashboard_nav_design_phase_a.py`, `test_dashboard_readiness_ui.py`, `test_dashboard_repair.py`, `test_dashboard_route_audit.py`, `test_dashboard_visual_phase_f.py`, plus the three carrier-UI tests (`test_dashboard_carrier_overview.py`, `test_dashboard_carrier_timeline.py`, `test_dashboard_carrier_proposals.py`).

---

## 2. New design coverage per module

The new design is a **page-centric** SPA with 22 sidebar entries. The Accounting page (`pages-v2.jsx`) merges PZ + Sales + wFirma + Master + Audit into sub-tabs:

```
Accounting
├── Purchase Ledger (PZ)
├── Sales / Proforma
├── Ledgers / Statements
├── wFirma Sync
├── Master Data
└── Audit Trail
```

Per-module coverage:

| # | Module | Design page(s) | Coverage depth |
|---|---|---|---|
| 1 | PZ create / outputs / readiness | `Accounting > Purchase Ledger (PZ)` (`PzAccountingPage` in `pages.jsx`) | **wireframe** — counts, "Ready for PZ" / "PZ Generated" / "Exported to wFirma" tables driven by `MOCK_SHIPMENTS`. **No** lock-status reasoning, **no** unresolved-products card, **no** product-resolve POST, **no** pz_create / pz_adopt distinction. |
| 2 | wFirma setup / reservation preview / mapping / PZ export | `Accounting > wFirma Sync` (`WfirmaExportPage`) | **wireframe** — "Ready for wFirma Export" table with an `alert('Exported to wFirma!')` placeholder button. **No** reservation preview, **no** product mapping, **no** WDT-export flow, **no** wFirma capabilities surface, **no** real `pz_create` body shape. |
| 3 | Warehouse / direct dispatch / barcode / packing list / inventory state | `inventory` page (`inventory-page.jsx`, 1225 lines), 2-stage architecture (Stage 1 doc layer / Stage 2 final stock + samples) | **partial** — broader scope than the existing dashboard's Warehouse tab; introduces "Move Stock", "Sample Out", "Sample Return", "Goods Return", "Return to Producer" as separate sidebar entries (all wireframe). **Does not** map to existing warehouse-scanner flow (`/dashboard/warehouse.html`) or to existing packing-list cards. |
| 4 | Sales / invoice readiness / WDT | `Accounting > Sales / Proforma` (`SalesProformaPage`) | **wireframe** — proforma list with "Generate Invoice" placeholder. **No** sales-linkage panel, **no** ready/blocked flags, **no** WDT export, **no** preview-to-invoice diff, **no** cancel-and-reissue ergonomics. |
| 5 | Proforma drafts / proforma-to-invoice | `Accounting > Sales / Proforma` (same page) | **wireframe** — proforma rows; **no** draft-vs-issued state, **no** to-invoice-preview comparison, **no** cancel-issued-for-reissue, **no** adopt-issued, **no** refresh-line-names POST. |
| 6 | Customer statements | `Accounting > Ledgers / Statements` (`window.LedgersPage` from `ledgers-page.jsx`, 768 lines) | **wireframe** — ledger lines per client; **no** aging-method picker, **no** PDF link, **no** AS-OF / FROM / TO date controls, **no** warnings panel. |
| 7 | Closure checks | not present in any page | **MISSING** — the existing closure-eval / closure-confirm flow has no place in the design. |
| 8 | Agency documents | `dhl` page (`pages-v2.jsx > DhlCustomsPage`) | **partial** — DHL/Customs page lists shipments and stats; references upload but with mock buttons. **Does not** mirror the existing `/api/v1/agency-documents/{batch_id}/upload` multipart upload, agency SAD decision, agency SAD parse status, or agency SLA status surfaces. |
| 9 | DHL documents received | `dhl` page | **partial** — same surface as agency docs; same gap. **No** auto-detected vs manual-registered badges. |
| 10 | Broker followups | not present in any page | **MISSING** — the broker-followup-panel (drafts list, send modal with confirm-warning, missing-invoices, CIF gap) has no place in the design. |

**Summary:** out of 10 focus modules, the new design covers **0 fully**, **5 as wireframe**, **3 as partial**, and **2 are missing entirely** (closure checks, broker followups).

---

## 3. Existing endpoints per module

| # | Module | Endpoints (representative) |
|---|---|---|
| 1 | PZ | `POST /pz/process`, `GET /shipment/{bid}/wfirma/pz_preview`, `POST /shipment/{bid}/wfirma/pz_create`, `POST /shipment/{bid}/wfirma/pz_adopt`, `GET /shipment/{bid}/wfirma/pz_document`, `POST /shipment/{bid}/wfirma/pz/refresh-mapping`, `GET /pz/files/{bid}/...` (7 routes) |
| 2 | wFirma | `POST /shipment/{bid}/wfirma/clipboard`, `GET /shipment/{bid}/wfirma/json`, `POST /shipment/{bid}/wfirma/products/resolve`, `POST /shipment/{bid}/wfirma/pz_create`, `POST /shipment/{bid}/wfirma/pz_adopt`, `GET /shipment/{bid}/wfirma/pz_document` (8 routes core + **19 routes** in `routes_wfirma_capabilities.py` for setup/health) + 3 in `routes_wfirma_reservation.py` (reservation preview) |
| 3 | Warehouse | `GET /api/v1/warehouse/config`, `POST /api/v1/warehouse/scan`, `GET /api/v1/warehouse/inventory/{scan_code}`, location CRUD (6 routes) + `routes_warehouse_audit.py` (2 routes) |
| 4 | Sales | `GET /api/v1/sales/linkage/{bid}` (1 route) — small surface; sales lives mostly inside proforma |
| 5 | Proforma | 26 routes — preview/create/cancel-issued-for-reissue/adopt-issued/refresh-line-names/document-pdf/to-invoice-preview/to-invoice |
| 6 | Customer statements | distinct route module (`routes_ledgers.py` covers ledger basis); statement PDF link path embedded in dashboard |
| 7 | Closure | `GET /api/v1/closure/{bid}/check` (read-only), `POST /api/v1/execute/closure_confirm` (write, `payload: {}` + `approved_by`) |
| 8 | Agency | `POST /api/v1/agency/email-package/{bid}`, `GET /api/v1/agency/decision/{bid}`, multipart upload via `/api/v1/agency-documents/{bid}/upload` (separate router) |
| 9 | DHL documents | `POST /api/v1/dhl-documents/{bid}/received`, `POST /api/v1/dhl-documents/{bid}/upload` (2 routes), DHL clearance flow has 12 more routes |
| 10 | Broker followups | broker followups consume DHL clearance + dashboard cache routes |

**Total backend surface across these 10 modules: ~110 routes.** The new design's wireframe coverage references roughly 15 of them, mostly for read-only counts.

---

## 4. Existing tests per module (counts)

| # | Module | Test files | Approx test count |
|---|---|---|---|
| 1 | PZ | `test_dashboard_run_pz_gate.py`, `test_dashboard_pz_operator_header.py`, `test_dashboard_polish_desc_delete.py` | ~50 |
| 2 | wFirma | `test_dashboard_wfirma_reservation_preview_panel.py`, `test_dashboard_wfirma_search.py` | ~40 |
| 3 | Warehouse | `test_dashboard_packing_list_card.py` (+ route-audit checks) | ~25 |
| 4 | Sales | `test_dashboard_sales_linkage_panel.py` | ~20 |
| 5 | Proforma | `test_dashboard_proforma_draft_panel.py`, `test_dashboard_proforma_drafts_cross_batch.py` | ~50 |
| 6 | Customer statements | `test_dashboard_customer_statements_picker.py`, `test_dashboard_customer_statement_drawer.py` | ~60 |
| 7 | Closure | `test_dashboard_closure_eval_card.py`, `test_dashboard_execution_guards.py` (closure block) | ~80 |
| 8 | Agency | `test_dashboard_agency_docs_card.py`, `test_dashboard_agency_sad_decision.py`, `test_dashboard_agency_sad_parse_status.py`, `test_dashboard_agency_sla_status.py` | ~70 |
| 9 | DHL documents | `test_dashboard_dhl_documents_received_card.py`, `test_dashboard_dhl_action_state.py` | ~45 |
| 10 | Broker followups | `test_dashboard_broker_followup_panel.py`, `test_dashboard_broker_followups_cross_batch.py` | ~70 |

**Approximate total across the 10 focus modules: ≈ 510 tests** (about half the entire dashboard suite). Any UI migration that breaks the mapping between these testids and the rendered DOM regresses half the trust layer.

---

## 5. Missing from new design

The design has zero coverage for these existing surfaces. If migration runs without protection, they vanish:

| ID | Missing surface | Why it matters |
|---|---|---|
| MS-1 | **Closure-eval card + closure-confirm section** (Module 7) | The closure-confirm execution-guard contract was the W-7 / B1.b stabilization win. Trust-layer pinning. |
| MS-2 | **Broker-followup-panel + cross-batch followups page** (Module 10) | DHL broker chase flow lives entirely in this UI. No backend can replace the operator-facing draft-edit + send-with-confirm step. |
| MS-3 | **Customer statements picker + drawer** (Module 6) | Aging-method selector, AS-OF / FROM / TO controls, PDF link, warnings panel — entire customer-statement workflow is a missing UI. |
| MS-4 | **Sales linkage panel** (Module 4) | The ready/blocked flag with blocking-reasons list is how operators know a batch isn't yet ready for invoice generation. |
| MS-5 | **wFirma reservation preview panel** (Module 2) | Pre-PZ-create reservation reasoning; the operator sees what wFirma would do before clicking. |
| MS-6 | **Polish description delete + edit** (Module 1, PZ) | Dashboard surface for editing PZ line descriptions in Polish. Pinned by `test_dashboard_polish_desc_delete.py`. |
| MS-7 | **DHL action state strip** (Module 9) | DHL milestone visibility — pinned by `test_dashboard_dhl_action_state.py`. |
| MS-8 | **Agency SAD decision + parse-status + SLA cards** (Module 8) | The agency-side customs decision pipeline. Three separate cards in the existing dashboard, all pinned. |
| MS-9 | **Carrier UI W-2.1 / W-2.1a / W-2.2 / W-2.3** (this campaign) | Mentioned in the parent migration analysis at §6 but worth re-stating — the multi-carrier `shipping` page in the design does NOT mirror these surfaces. |
| MS-10 | **Standalone cross-batch read-only pages** | Action proposals (cross-batch), broker-followups (cross-batch), customer statements (picker), proforma drafts (cross-batch). The new design has only the action-proposals cross-batch page. |

---

## 6. Unsafe simplifications in new design

The design *appears* to cover some modules but the simplification is operationally unsafe. Migrating these as-is would silently lose evidence or operator-action gates.

| ID | Unsafe simplification | Concrete risk |
|---|---|---|
| US-1 | **PZ flow collapsed to "Ready / Generated / Exported" filters** with mock-data tables | Hides the lock-status banner, the unresolved-product-codes card, and the create-vs-adopt distinction. Operators would lose the disabled-reason pattern that explains why a button is disabled. |
| US-2 | **wFirma export reduced to a single button "Export to wFirma!" with `alert()`** | No reservation preview, no product-mapping resolve. An operator clicking this button without the existing pre-checks ships a malformed PZ to wFirma. |
| US-3 | **`Accounting` page merges PZ + Sales + wFirma + Master + Audit** into one sub-tab strip | Operators currently navigate per-batch. Top-level merging means the operator must tab-switch within Accounting AND know which batch is in scope. Easy mis-action surface. |
| US-4 | **DHL/Customs page presents upload as a button**, no multipart-upload handler shown | The existing dashboard's `agency-docs-upload-label` + FormData + files-field-name + `loadDhlReadiness` + `loadBatchReadiness` refresh contract is invisible. Trivially loses operational refresh hooks. |
| US-5 | **Mock data with FedEx rows in `dashboard-page.jsx`** | If shipped without filtering, operator sees fake FedEx shipments next to real DHL Express shipments. Trust collapse. |
| US-6 | **"Wireframe only — no live carrier integrations"** subtitle on Shipping Ops page | The page shows action chips ("Backend pending", "Carrier approval required") but renders disabled-but-visible buttons. Operator could attempt the action and discover dead UX. |
| US-7 | **No idempotency / actor / reason discipline** in any of the design's write surfaces | Existing dashboard requires an `approved_by`/`actor` prompt for every closure-confirm and W-2.3 carrier action. New design's "Generate Invoice" / "Export to wFirma" buttons are bare. |
| US-8 | **No disabled-state messaging discipline** | Existing dashboard always names *why* a button is disabled (closure-eval, carrier-proposal, agency upload). New design tends to grey out without a reason badge. Operator confusion. |

---

## 7. Must-preserve workflow rules

Cross-cutting rules the existing dashboard enforces that any migration MUST preserve:

| Rule | Anchor |
|---|---|
| **R-1.** PZ generation only after SAD is linked. | ADR-016 hard lock 1; backend gates this independently — UI must not imply otherwise. |
| **R-2.** No inventory lifecycle move before customs completion. | ADR-012 hard lock 2 (analogous discipline applies to non-self-clearance flows). |
| **R-3.** Closure-confirm body must include `payload: {}` and `approved_by`. | W-7 / B1.b execution-guard test contract. |
| **R-4.** wFirma `pz_create` requires preview + product-resolve to have run first. | Existing dashboard wires the gate; backend may not enforce. |
| **R-5.** Proforma cancel-and-reissue is a two-step: cancel-issued-for-reissue, then a fresh create. | Existing `routes_proforma.py` shape. |
| **R-6.** Operator must enter `approved_by` / actor for every state-mutating action. | Existing `closure-confirm-btn` + W-2.3 confirm drawer. Cannot regress. |
| **R-7.** Agency / DHL document upload uses multipart `FormData` with field name `'files'`. | Pinned by `test_dashboard_agency_docs_card.py` + `test_dashboard_dhl_documents_received_card.py`. |
| **R-8.** Carrier UI says "DHL Express" only. No FedEx / UPS / multi-carrier. | W-2.1a wording lock + multiple parametrised tests. |
| **R-9.** Disabled buttons name their reason. | Operator-Safety review (W-2.3 + closure-eval pattern). |
| **R-10.** No write surface inside read-only block. The Review button OPENS the drawer; the drawer's execute button calls the handler. | W-2.3 confirmation-flow contract. |
| **R-11.** Source-grep tests pin testid + endpoint + copy. Migration must not break these without explicit test updates approved per-phase. | W-7 + W-2 test discipline. |
| **R-12.** Append-only: no historical ADR or program-board row mutated. | Governance OS. |

---

## 8. Migration decision per module

For each of the 10 focus modules, the verdict is one of:
- **keep existing** — module is operationally correct; do not touch UI.
- **restyle only** — adopt visual tokens but leave wiring untouched.
- **partial migrate** — borrow specific cards / patterns; preserve all flows.
- **reject design section** — design's version is unsafe; do not adopt.

| # | Module | Verdict | Rationale |
|---|---|---|---|
| 1 | PZ create / outputs / readiness | **partial migrate** (style only; preserve all wiring) | Design has the right counts but no flow. Adopt the StatTile + table styling; preserve existing lock-status banner, unresolved-products card, pz_create / pz_adopt buttons, disabled-state messaging. |
| 2 | wFirma | **partial migrate** (style only; **REJECT** the design's "Export!" button) | The design's one-click export button is US-2. Reject. Adopt only the panel chrome. |
| 3 | Warehouse / packing list | **keep existing** | The design's Inventory page is a much broader 2-stage redesign that does not map to the existing batch-tab Warehouse panel. Out of UI-1 scope; out of UI-2 scope; revisit in a dedicated future Inventory campaign. |
| 4 | Sales / invoice readiness / WDT | **keep existing** | Design has no equivalent of sales-linkage ready/blocked flags or WDT-export flow. Migration would be a regression. |
| 5 | Proforma | **partial migrate** (style only) | Adopt the proforma row chrome from Accounting > Sales / Proforma. Preserve cancel-and-reissue / adopt-issued / refresh-line-names POSTs from existing per-client cards. |
| 6 | Customer statements | **keep existing** | Statement aging / AS-OF / FROM / TO logic has no replacement in the design's `LedgersPage`. Migration would lose ~60 tests' worth of contract. |
| 7 | Closure checks | **keep existing** | Design has no closure-eval / closure-confirm equivalent. Replacing is impossible. |
| 8 | Agency documents | **partial migrate** (style only) | Adopt DHL / Customs page chrome for the section header. Preserve the existing `agency-docs-received-card` wiring (FormData upload + `loadDhlReadiness` refresh). |
| 9 | DHL documents received | **partial migrate** (style only) | Same as Agency. Preserve `dhl-docs-received-card` + auto/manual badges. |
| 10 | Broker followups | **keep existing** | Design has no broker-followup surface. Replacing is impossible. |

**Cross-cutting rejects (apply to every module):**
- Reject the entire `shipping-ops` page (multi-carrier — already documented in the parent migration artifact).
- Reject all FedEx / UPS sample data in `dashboard-page.jsx`, `master-page.jsx`, `client-kyc-and-consignment.jsx`.
- Reject the document-suite carrier select (`["DHL","FedEx","UPS"]`).

---

## 9. Safe UI migration order

Given the module-level verdicts above, the **only safe migration sequence** is:

```
UI-1   visual shell only             (CSS tokens + fonts; zero markup change)
       allowed: change `--accent`, `--bg`, `--text-*` etc. only
       forbidden: any layout change; any new card; any sidebar adoption

UI-2a  PZ partial migrate (style)    (per Module 1 verdict)
       restyle StatTiles + table chrome; preserve every wiring
       all 50 PZ tests must remain green
       no /pz/process body change; no pz_create body change

UI-2b  wFirma partial migrate (style)
       restyle panel chrome only; reject design's "Export!" button
       all 40 wFirma tests must remain green
       reservation preview + product-resolve flow untouched

UI-2c  Proforma partial migrate (style)
       restyle row + per-client card chrome
       all 50 proforma tests must remain green

UI-2d  Agency + DHL doc cards partial migrate (style)
       restyle page header for DHL / Customs section
       all 115 (agency + DHL doc) tests must remain green
       FormData upload + refresh hooks untouched

UI-3   DHL Express tab restyle       (preserve W-2.1+a / W-2.2 / W-2.3)
       restyle confirmation drawer + proposal panel chrome
       all 157 W-2 tests must remain green

UI-4   write-action parity audit     (separate phase; opens only after UI-1..UI-3
                                      and after sandbox-shadow operational evidence)
       no new write surfaces beyond what already ships

UI-5   cleanup
       consolidate any duplicated components; tests stay green
```

**Rule:** every UI-2.x sub-phase ships a single commit. No UI-2.x phase opens until the prior UI-2.x ships clean. UI-3 opens only after all UI-2.x sub-phases ship. UI-4 opens only after sandbox-shadow operational evidence (per the stabilization-window posture).

---

## 10. Modules that must NOT be touched during UI-1

UI-1 is **visual-shell-only** — CSS tokens + fonts. The following modules must have zero JSX / DOM / class-name change:

| # | Module | Reason |
|---|---|---|
| 3 | Warehouse / packing list | Wide-scope change; out of UI-1 |
| 4 | Sales linkage panel | Ready/blocked flag pinning is fragile |
| 6 | Customer statements | 60-test contract; high fragility |
| 7 | Closure checks | W-7 stabilization win; non-negotiable |
| 10 | Broker followups | Send-modal confirm-warning contract |
| W-2 | DHL Express tab | Most-recent ship; only the absolute simplest token swap is permitted, and only inside UI-3 |

Concretely, UI-1 may **only** change values in the `:root { --accent: …; --bg: …; … }` block at the top of `dashboard.html` and the Google Fonts `<link>` import. **No** JSX edits. **No** `data-testid` value changes. **No** copy changes.

---

## 11. Tests that must remain green

At every phase, this is the gate stack:

```
Phase  Required green
─────  ──────────────────────────────────────────────────────────────
UI-1   1032 dashboard suite (all current pass count)
       1205 carrier + DHL backend suite
       160 / 160 make verify
       — every brand-token must appear in dashboard.html

UI-2a  1032 + new PZ chrome assertions (per-tile testid stable)
       50 PZ tests still pinned to current testids
       backend untouched -> 1205 + 160 unaffected

UI-2b  1032 + 40 wFirma tests still pinned
       wfirma_search forbidden-marker test still green (no goods/add)

UI-2c  1032 + 50 proforma tests still pinned

UI-2d  1032 + 115 agency + DHL-doc tests still pinned

UI-3   1032 + 157 W-2 tests still pinned
       Operator Safety reviewer must spawn (real sub-agent) per
       roles.md trigger ("any change to confirmation dialogs")

UI-4   all of the above + new write-action parity tests

UI-5   all of the above; net file size reduction; no orphaned testids
```

**Cross-phase invariant:** `test_dashboard_repair::test_route_audit_zero_stale` must remain green at every phase (no stale frontend calls). `test_dashboard_wfirma_search::test_no_auto_create_product_endpoint_referenced` must remain green (no `goods/add` substring leaks).

---

## 12. Final recommendation

```
═══════════════════════════════════════════════════════════════════
  RECOMMENDATION — Operational module migration matrix
  Date:     2026-05-10
  Baseline: 54d2e39
═══════════════════════════════════════════════════════════════════

  Migrate the new design?              PARTIAL — style only.

  Per-module verdicts:
    PZ                       partial (style)
    wFirma                   partial (style; reject design's
                                       one-click export button)
    Warehouse / packing      keep existing
    Sales / WDT              keep existing
    Proforma                 partial (style)
    Customer statements      keep existing
    Closure checks           keep existing
    Agency documents         partial (style)
    DHL documents received   partial (style)
    Broker followups         keep existing
    Carrier UI (W-2.x)       partial (style only, in UI-3)

  Cross-cutting rejects:
    - shipping-ops page (entire 669 lines)
    - All FedEx / UPS sample data
    - FedEx-account fields (client KYC, master data)
    - Document-suite multi-carrier select
    - Design's bare write buttons (no actor / no disabled reason)

  Hard preserve (no regression):
    - 1032 dashboard test pass count
    - 1205 carrier + DHL backend test pass count
    - 160 / 160 make verify
    - 12 must-preserve workflow rules from §7
    - "DHL Express" wording lock
    - Append-only ADRs and program board

  Recommended UI-1 scope:
    Single commit. CSS tokens + Google Fonts import only.
    No JSX edit. No data-testid edit. No copy change.
    Phase test: every brand-token from the design's :root block
    appears in dashboard.html's :root block.
    Risk: low. Rollback: revert.

  Open this matrix's first phase only if:
    (a) operator approves PARTIAL migration of all 10 modules
        per the §8 verdicts;
    (b) operator approves the cross-cutting rejects;
    (c) operator approves UI-1 ahead of any UI-2.x;
    (d) operator confirms the stabilization-window posture
        accommodates a single CSS-only commit, OR explicitly opens
        the migration campaign as a successor to the window.

  Otherwise:
    Cell remains at rest at 54d2e39. This matrix is recorded for
    reference. No migration scheduled.

  Signed:    Coordinator (this artifact)
  Reviewers: UI/UX Planner, Backend Architect, Route/API Mapper,
             Operator Safety, Security, QA Lead, Gap Hunter
             (all Coordinator-simulated this session)

═══════════════════════════════════════════════════════════════════
```

---

## Self-review

What this matrix catches that the parent migration analysis did not:
- The design's **PZ flow is wireframe-grade** — no `pz_create` / `pz_adopt` distinction, no lock-status reasoning, no unresolved-products card. (US-1)
- The design's **wFirma export is one button + `alert()`** — directly hostile to existing operational gating. (US-2)
- The **Accounting page merging** of PZ + Sales + wFirma + Master + Audit changes operator navigation in a way that may be desirable but cannot be assumed. (US-3)
- **Closure checks and broker followups are entirely missing** from the design — these are the W-7 stabilization win and the DHL-broker chase flow respectively. Wholesale migration loses both.
- ~510 of the 1032 dashboard tests pin one of these 10 modules. Migration without per-module phase gates would regress half the trust layer.

What this matrix cannot decide:
- Whether the operator wants the navigation paradigm shift (sidebar-first) at all. The matrix scopes to module verdicts, not to navigation architecture.
- Whether the partial migrate (style only) verdicts are sufficient, or whether the operator wants more aggressive component adoption. Future operational evidence (per the stabilization-window posture) is the right input.
