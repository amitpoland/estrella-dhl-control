# UI Functionality Gap Audit — Backend vs. Design vs. Dashboard

**Mode:** PRE-IMPLEMENTATION
**Scope:** every backend capability the service ships, mapped against
the existing dashboard's UI exposure and the new design bundle's
coverage. Doc-only.
**Baseline:** `2d1ea7a` (UI-2b closed)
**Coordinator pass:** in-context (Opus); reviewers (Backend
Architect, Route/API Mapper, UI/UX Planner, QA Lead, Gap Hunter,
Operator Safety) executed as Coordinator-simulated parallel
reads.

**Core rule (operator-set):**
> Existing codebase functionality is source of truth. New design is
> only visual inspiration. If functionality exists but the design
> omits it, mark it as "UI must add/preserve."

---

## 0. Pre-flight gates

| Gate | Result |
|---|---|
| `git status --short` | clean |
| Branch | `feature/dhl-label-workflow-planning` |
| Dashboard suite (38 files) | **1248 / 1248** pass |
| `make verify` | **160 / 160** pass |
| Backend routes (44 route files) | **260 routes** |
| Dashboard distinct testids | 344 |

---

## 1. Backend functionality inventory

Grouped by operational module. **`E:`** = endpoint count. **`D:`** =
how many of those endpoints are referenced from `dashboard.html`.

### 1.1 PZ engine (`routes_pz.py`, 7 endpoints)

| E: | Endpoint | D: |
|---|---|---|
| GET  | `/health` (response model) | 0 |
| POST | `/pz/process` | 1 (Run PZ button) |
| POST | `/pz/process/_legacy` | 0 |
| POST | `/feedback` | 1 |
| GET  | `/learning/summary` | 0 |
| GET  | `/files/{batch_id}/source/{category}/{filename}` | 1 |
| GET  | `/files/{batch_id}/{filename}` | 1 |

Also **`routes_packing.py`** (6 routes — barcode print, line listing, upload):
| E: | Endpoint | D: |
|---|---|---|
| POST | `/{batch_id}/upload` | 1 |
| GET  | `/{batch_id}` | 1 |
| GET  | `/{batch_id}/lines` | 0 |
| GET  | `/{batch_id}/barcode` | 1 |
| GET  | `/{batch_id}/barcode/zpl` | 0 |
| POST | `/{batch_id}/barcode/print` | 0 |

### 1.2 wFirma (8 + 19 + 3 = 30 endpoints)

`routes_wfirma.py` (8): clipboard, json, pz_preview, products/resolve,
pz_create, pz_adopt, pz_document, pz/refresh-mapping. **D: 8/8.**

`routes_wfirma_capabilities.py` (19): health/probe/contractors/goods/
warehouses/services/categories/units/setup endpoints. **D: 4/19**
(only contractors + goods are dashboard-visible; the other 15
diagnostic / setup endpoints are API-only).

`routes_wfirma_reservation.py` (3):
- GET `/reservation-preview/{batch_id}` (D: 1 — used by reservation panel)
- POST `/reservations/create` (D: 0 — submitted by `submitReservation`; URL not pinned in source-grep)
- POST `/reservations/{draft_id}/reset-stuck` (D: 0 — **API-only recovery action**)

### 1.3 Warehouse (`routes_warehouse.py` + `routes_warehouse_audit.py`, 6 + 2 = 8)

| E: | Endpoint | D: |
|---|---|---|
| GET  | `/api/v1/warehouse/config` | 0 (warehouse-scanner page only) |
| POST | `/api/v1/warehouse/scan` | 0 (warehouse-scanner page only) |
| GET  | `/api/v1/warehouse/inventory/{scan_code}` | 0 |
| POST | `/api/v1/warehouse/locations` | 0 |
| GET  | `/api/v1/warehouse/locations` | 0 |
| GET  | `/api/v1/warehouse/locations/{code}/inventory` | 0 |
| GET  | `/api/v1/warehouse/audit/{batch_id}` | 1 (Warehouse tab) |
| GET  | `/api/v1/warehouse/audit/{batch_id}/lines` | 1 |

The warehouse-scanner is a **separate page** (`/dashboard/warehouse.html`).
Locations CRUD is **entirely API-only**.

### 1.4 Sales (`routes_sales.py`, 1 endpoint)

GET `/api/v1/sales/linkage/{batch_id}` (D: 1 — Sales tab linkage panel).

WDT export goes through `routes_proforma.py` (next).

### 1.5 Proforma drafts (`routes_proforma.py`, 26 endpoints)

| E: | Endpoint | D: |
|---|---|---|
| POST | `/preview/{batch_id}/{client_name}` | 1 |
| POST | `/create/{batch_id}/{client_name}` | 1 |
| POST | `/cancel-issued-for-reissue/{batch_id}/{client_name}` | 1 |
| POST | `/adopt-issued/{batch_id}/{client_name}` | 1 |
| POST | `/{wfirma_id}/refresh-line-names` | 1 |
| GET  | `/{batch_id}/{client_name}/document` | 1 |
| GET  | `/{batch_id}/{client_name}/document.pdf` | 1 |
| GET/POST | `/to-invoice-preview/{batch_id}/{client_name}` and `/to-invoice/...` | 1 each |
| 14 routes under `/api/v1/proforma/draft/...` | (CRUD + service-charges + approve / re-open / cancel / post / lines / reset-from-sales-packing) | 19 references in dashboard — **mostly visible** through proforma-draft-panel |

The full draft lifecycle (preview → edit → service-charges → approve → post-to-wFirma) is dashboard-exposed. **D: 19/26** confirmed; the remaining 7 are minor reads/PATCH variants.

### 1.6 Customer statements (`routes_ledgers.py`, 3 endpoints)

| E: | Endpoint | D: |
|---|---|---|
| GET | `/api/v1/clients/{contractor_id}/invoice-ledger.json` | 1 |
| GET | `/api/v1/clients/{contractor_id}/statement.json` | 1 |
| GET | `/api/v1/clients/{contractor_id}/statement.pdf` | 1 (PDF link) |

All three exposed via the customer-statement picker + drawer. D: 3/3.

### 1.7 Closure checks (`routes_lifecycle.py`, partial — 2 routes touch closure)

| E: | Endpoint | D: |
|---|---|---|
| GET  | `/api/v1/closure/{batch_id}/check` | 1 (closure-eval-card) |
| POST | `/api/v1/closure/{batch_id}/evaluate` | **0 — API-only write closure (recovery path)** |

Plus `/api/v1/execute/closure_confirm` (in `routes_execute.py`, the
operator-confirm POST). **D: 1.** Note: `/evaluate` is the
audit-write POST that's distinct from `/check` (read-only) and from
`/execute/closure_confirm` (operator-confirm). **The `/evaluate`
endpoint has zero UI surface.**

### 1.8 DHL Express carrier (W-2.x, 5 + 4 + 2 + 2 + 2 = 15 endpoints)

| E: | Endpoint | D: |
|---|---|---|
| GET  | `/api/v1/carrier/shipments` (cross-batch list) | 0 (W-2.1 uses by-batch only) |
| GET  | `/api/v1/carrier/shipments/{id}` | 0 (W-2.x uses by-batch + transitions) |
| GET  | `/api/v1/carrier/shipments/by-batch/{id}` | 1 (W-2.1) |
| GET  | `/api/v1/carrier/shipments/{id}/transitions` | 1 (W-2.2) |
| GET  | `/api/v1/carrier/labels/{sha256}` | 1 (W-2.2) |
| GET  | `/api/v1/carrier/proposals` (cross-batch) | 0 |
| GET  | `/api/v1/carrier/proposals/by-batch/{id}` | 1 (W-2.3) |
| POST | `/api/v1/carrier/actions/create-shipment/execute` | **0 (W-2.3 deferred to W-2.3b)** |
| POST | `/api/v1/carrier/actions/mark-label-printed/execute` | 1 (W-2.3) |
| POST | `/api/v1/carrier/actions/mark-handed-to-carrier/execute` | 1 (W-2.3) |
| POST | `/api/v1/carrier/actions/cancel-shipment/execute` | 1 (W-2.3) |
| GET  | `/api/v1/carrier/shadow/recent` | **0 — API-only shadow log** |
| GET  | `/api/v1/carrier/shadow/summary` | **0 — API-only shadow summary** |
| POST | `/api/v1/carrier/webhook/dhl/activate` | n/a (DHL → us only) |
| POST | `/api/v1/carrier/webhook/dhl/events` | n/a (DHL → us only) |

**Hidden carrier surfaces:** cross-batch shipment list, single-shipment
detail page, cross-batch proposals, **shadow log review** (matrix W-2.5
phase), **mode-status banner** (W-2.6), and create-shipment write form
(W-2.3b).

### 1.9 Agency documents (`routes_agency.py` + `routes_lifecycle.py` agency-doc routes, 2 + 4 = 6 endpoints)

| E: | Endpoint | D: |
|---|---|---|
| POST | `/api/v1/agency/email-package/{batch_id}` | 1 |
| GET  | `/api/v1/agency/decision/{batch_id}` | **0 — agency SAD decision read; API-only** |
| POST | `/api/v1/agency-documents/{batch_id}/received` | 1 |
| POST | `/api/v1/agency-documents/{batch_id}/upload` | 1 (W-7 / B1.c) |
| POST | `/api/v1/lifecycle/agency-followup` | **0 — API-only agency-followup automation** |
| POST | `/api/v1/inventory-state/mark-direct-dispatch` | **0 — API-only direct-dispatch marker** |

Plus DHL-side document routes (`routes_dhl_documents.py`, 2):
| POST | `/api/v1/dhl-documents/{batch_id}/received` | 1 |
| POST | `/api/v1/dhl-documents/{batch_id}/upload` | 1 (W-7 / B1.c) |

### 1.10 DHL clearance (`routes_dhl_clearance.py`, 12 endpoints, prefix `/api/v1/dhl`)

| E: | Endpoint | D: |
|---|---|---|
| GET  | `/scan-inbox` | 1 |
| POST | `/match-and-handle` | 0 |
| GET  | `/clearance-status/{batch_id}` | 1 (implicit) |
| POST | `/generate-description/{batch_id}` | 0 |
| GET  | `/download/{filename}` | 0 |
| POST | `/generate-customs-package/{batch_id}` | 0 |
| GET  | `/sad-ready/{batch_id}` | 0 |
| GET  | `/reply-status/{batch_id}` | 1 |
| POST | `/send-reply/{batch_id}` | 1 |
| POST | `/approve/{batch_id}` | 0 |
| POST | `/mark-email-received/{batch_id}` | 1 |
| POST | `/proactive-dispatch/{batch_id}` | **0 — DSK self-clearance P2 (ADR-013), entirely API-only** |

**~7 DHL-clearance endpoints API-only.** Significant operator-facing
gap, especially `proactive-dispatch` which carries the W-5 self-
clearance flow.

### 1.11 DHL follow-up (`routes_dhl_followup.py`, 3 endpoints)

POST `/{batch_id}/stop` (D: 1), POST `/{batch_id}/send-now` (D: 1),
POST `/{batch_id}/recalculate` (D: 1). **All exposed.**

### 1.12 Broker followups (cross-cutting, ~5 dashboard cache endpoints)

The broker-followup-panel UI calls `/dashboard/broker-followups/...`
(`routes_dashboard.py`). Cross-batch + per-batch surfaces both
exposed. **D: full.**

### 1.13 Action proposals (`routes_action_proposals.py`, 5 endpoints)

| E: | Endpoint | D: |
|---|---|---|
| POST | `/api/v1/action-proposals/{batch_id}/refresh` | 1 |
| GET  | `/api/v1/action-proposals/{batch_id}` | 1 |
| POST | `/api/v1/action-proposals/{proposal_id}/approve` | 1 |
| POST | `/api/v1/action-proposals/{proposal_id}/reject` | 1 |
| POST | `/api/v1/action-proposals/{proposal_id}/queue` | 1 |

Full coverage. D: 5/5.

### 1.14 Reservations / packing import (`routes_reservations.py`, 6 endpoints — `/api/v1/...`)

| E: | Endpoint | D: |
|---|---|---|
| POST | `/products/import-purchase-packing` | **0 — API-only** |
| POST | `/reservations/import-sales-packing` | **0 — API-only** |
| GET  | `/reservations/queue` | **0 — API-only** |
| POST | `/wfirma/products/sync-by-codes` | **0 — API-only** |
| POST | `/reservations/process-pending` | **0 — API-only** |
| POST | `/reservations/{queue_id}/reset` | **0 — API-only** |

**Entire reservations/packing-import module is API-only.** Operator
cannot trigger these from the dashboard today.

### 1.15 Corrections registry (`routes_correction_registry.py`, 9 endpoints — prefix `/api/v1/corrections`)

POST `/`, GET `/`, GET `/last-accepted`, GET `/rejected`, GET
`/frequency`, GET `/confidence`, GET `/explain`, GET `/stats`, GET
`/types`. **D: 0/9.** **Entire corrections registry is API-only.**

### 1.16 Intelligence / learning (`routes_intelligence.py` 9 + `routes_learning.py` 4 = 13)

| Module | Routes | D: |
|---|---|---|
| Intelligence | 9 (suggestions / config / refresh / actors / classify / status / build / insights) | ~6 |
| Invoice learning | 4 (feedback / summary / patterns / DELETE patterns) | 5 (the prefix `/api/v1/invoice-learning` appears 5 times in dashboard) |

D: ~11/13 — mostly exposed.

### 1.17 Tracking (`routes_tracking.py` + `routes_tracking_db.py`, 5 + 4 = 9)

10 dashboard refs. Mostly exposed.

### 1.18 DSK (`routes_dsk.py`, 4 endpoints)

| E: | Endpoint | D: |
|---|---|---|
| POST | `/api/v1/dsk/generate` | 1 |
| GET  | `/api/v1/dsk/download/{filename}` | 1 |
| POST | `/api/v1/dsk/email-package` | 1 |
| GET  | `/api/v1/dsk/audit-log` | **0 — API-only** |

### 1.19 Intake (`routes_intake.py`, 3 endpoints — prefix `/api/v1/shipment`)

3 routes for shipment intake. **D: 1/3** (only 1 reference). Likely the upload-intake form + 2 follow-up intake reads. Mostly API-only.

### 1.20 Shadow / audit / evidence

- `routes_carrier_shadow.py` (2 routes) — **API-only**.
- `routes_correction_registry.py` (9 routes) — **API-only**.
- Manifests, label-store reads — content-addressed, accessed via
  `/api/v1/carrier/labels/{sha256}` (D: 1).
- Timeline events (`service/app/core/timeline.py`) — read via per-batch
  GET routes; dashboard surfaces them via "Timeline" tab. D: full.

---

## 2. Current UI exposure map

| Module | Fully visible | Partial | Hidden / API-only |
|---|---|---|---|
| **PZ** | Run PZ button, lock-status banner, document panel, file downloads | refresh-mapping (visible but conditional), legacy `/process/_legacy` | learning summary; health probe |
| **wFirma** | clipboard / json / pz_preview / products/resolve / pz_create / pz_adopt / pz_document; contractors+goods search | reservation-preview (visible) | **reservations/{draft_id}/reset-stuck**, 15 capabilities/setup endpoints |
| **Warehouse** | per-batch audit panel | warehouse-scanner standalone page | locations CRUD; inventory by code |
| **Sales** | linkage panel | (small surface) | — |
| **Proforma** | preview / create / cancel-issued / adopt-issued / refresh-line-names / document / drafts CRUD / approve / cancel | minor PATCH variants | — |
| **Customer statements** | picker page + drawer + PDF link | — | — |
| **Closure checks** | `/check` (read-only) + `/execute/closure_confirm` | — | **`/evaluate` (audit-write recovery path) — API-only** |
| **DHL Express carrier** | by-batch shipments + transitions + label evidence + 3 simple actions | (W-2.3 partial — proposals listed, drawer for 3 actions) | **shadow log; cross-batch list; cross-batch proposals; create-shipment write (W-2.3b); mode banner (W-2.6)** |
| **Agency docs** | email-package; agency-documents/upload; agency-documents/received | (W-7 / B1.c) | **agency/decision/{batch_id} read; lifecycle/agency-followup; inventory-state/mark-direct-dispatch** |
| **DHL documents received** | dhl-documents/upload; dhl-documents/received | (W-7 / B1.c) | — |
| **DHL clearance** | scan-inbox, reply-status, send-reply, mark-email-received | clearance-status (implicit) | **match-and-handle, generate-description, generate-customs-package, sad-ready, approve, download/{filename}, proactive-dispatch (W-5 P2)** |
| **DHL follow-up** | stop, send-now, recalculate | — | — |
| **Broker followups** | per-batch panel + cross-batch page | — | — |
| **Action proposals** | refresh, list, approve, reject, queue | — | — |
| **Reservations / packing import** | — | — | **all 6 routes API-only** |
| **Corrections registry** | — | — | **all 9 routes API-only** |
| **Intelligence / learning** | suggestions, config, refresh, classify, build, insights, feedback, summary, patterns | — | DELETE patterns; some diagnostics |
| **Tracking** | per-AWB tracking refresh + lookup | — | — |
| **DSK** | generate, download, email-package | — | **audit-log** |
| **Intake** | upload form (single ref) | — | **2 intake-related routes API-only** |
| **Shadow / audit** | — | — | **carrier shadow logs; corrections registry stats; DSK audit log** |

---

## 3. New design omission map

What the new design at `api.anthropic.com/v1/design/h/SsXdZzIKxDttoOyA8YSnYA`
**does NOT cover** that the existing service supports:

### 3.1 Hard omissions (entire workflows missing)

1. **Closure-eval card + closure-confirm flow.** Operator-confirm payload contract preserved by W-7 / B1.b is invisible in the design.
2. **Broker followups** — per-batch panel + cross-batch page. Design has no broker surface.
3. **Customer statements** picker + drawer. Design's `LedgersPage` is wireframe-grade and lacks aging / AS-OF / PDF link.
4. **Sales linkage panel** — ready/blocked/blocking-reasons UI.
5. **wFirma reservation preview** — pre-PZ-create reasoning panel.
6. **Polish description edit/delete** — pinned by `test_dashboard_polish_desc_delete.py`.
7. **DHL action-state strip** — milestone visibility, pinned by `test_dashboard_dhl_action_state.py`.
8. **Agency SAD decision card + parse-status + SLA cards** — three separate pinned cards.
9. **Carrier UI W-2.x** — design's shipping-ops page is multi-carrier wireframe (US-2 reject); zero replacement for the operational DHL Express tab Estrella ships.

### 3.2 Soft omissions (functions backend supports but dashboard ALSO doesn't expose)

These are the most operationally interesting — invisible to operators today, would stay invisible even after design migration.

| ID | Function | Backend route | Operator value if surfaced |
|---|---|---|---|
| **G-1** | Carrier shadow log review (recent + summary) | `GET /api/v1/carrier/shadow/recent`, `/summary` | Operator-visible diff between stub and live during sandbox shadow — **critical for DL-G1 sandbox shadow validation** |
| **G-2** | Carrier mode banner (live/shadow/stub) | (no endpoint yet — W-2.6 + ADR-018) | Single most important safety surface for any future live-prod cutover |
| **G-3** | Cross-batch carrier shipment list | `GET /api/v1/carrier/shipments?status=&carrier=` | Operator dashboard shows shipments per-batch only; no cross-batch overview |
| **G-4** | Cross-batch carrier proposals | `GET /api/v1/carrier/proposals` | Same — only per-batch today |
| **G-5** | Closure `/evaluate` audit-write recovery | `POST /api/v1/closure/{batch_id}/evaluate` | Recovery path when closure-confirm failed mid-flight; today operator must call API directly |
| **G-6** | Reservations queue + import-purchase-packing + import-sales-packing | `routes_reservations.py` (6 routes) | Entire reservation orchestration is API-only |
| **G-7** | wFirma reservation reset-stuck | `POST /api/v1/wfirma/reservations/{draft_id}/reset-stuck` | Recovery action when a reservation is stuck mid-flight |
| **G-8** | Corrections registry | `routes_correction_registry.py` (9 routes) | Operator-side corrections / explain / stats — all API-only |
| **G-9** | DHL clearance recovery actions | `routes_dhl_clearance.py` 7 hidden routes (match-and-handle, generate-description, generate-customs-package, sad-ready, approve, download, proactive-dispatch) | Customs ops, including W-5 self-clearance P2 (ADR-013) |
| **G-10** | Lifecycle agency-followup + direct-dispatch markers | `routes_lifecycle.py` (2 routes) | Mark a batch as direct-dispatched; trigger agency followup automation |
| **G-11** | Agency SAD decision read | `GET /api/v1/agency/decision/{batch_id}` | Operator can't see the agency's SAD decision today (only the upload + email-package) |
| **G-12** | DSK audit log | `GET /api/v1/dsk/audit-log` | Operator-visible audit trail for DSK generation |
| **G-13** | wFirma diagnostics / health / setup capabilities | `routes_wfirma_capabilities.py` (15 hidden routes) | Setup-time visibility — currently API-only |
| **G-14** | Warehouse locations CRUD | `routes_warehouse.py` (5 hidden routes) | Operator-side location management; currently warehouse-scanner only |
| **G-15** | Packing barcode print + ZPL + lines | `routes_packing.py` (3 hidden routes) | Print-to-warehouse-printer ZPL + per-batch line listing |
| **G-16** | Intake routes 2/3 | `routes_intake.py` | Intake follow-up reads |

---

## 4. Must-preserve list

These functions MUST remain accessible (or become MORE accessible)
during any UI migration. Operator workflow depends on them today.

### 4.1 Already operator-visible — must not regress

1. PZ Run + lock-status + document panel (50 PZ tests pin them).
2. wFirma reservation preview + create flow (15 tests).
3. wFirma customer / product search + prefill (17 tests).
4. Proforma full draft lifecycle (50 proforma tests).
5. Customer statements picker + drawer + PDF (60 tests).
6. Closure-eval read + closure-confirm operator-payload contract (80 tests).
7. Agency docs upload + email-package + DHL docs upload (115 tests).
8. Broker-followup panel + send-modal confirm-warning (70 tests).
9. DHL Express tab — overview + timeline + label evidence + proposal drawer with 3 simple actions (157 tests).
10. Action proposals (cross-batch + per-batch).
11. Sales linkage panel.
12. Tracking refresh + lookup.
13. DSK generate + download + email-package.
14. DHL follow-up stop / send-now / recalculate.
15. Polish description edit/delete.

### 4.2 Currently API-only but operationally important — must NOT be retired

These are NOT visible today but exist in the backend and are
called by operators / Claude / cowork / scripts. Migration must
not break them by, e.g., changing dashboard.html in a way that
removes the underlying state setters or fetches.

1. Closure `/evaluate` recovery write.
2. Carrier shadow log endpoints (sandbox shadow validation depends on them).
3. Lifecycle agency-followup + direct-dispatch.
4. Reservations queue + import + reset.
5. Corrections registry full CRUD.
6. DHL-clearance recovery routes (proactive-dispatch, match-and-handle, generate-customs-package, etc.).
7. DSK audit log.
8. wFirma capabilities / diagnostics.

---

## 5. Must-add UI list

For each gap in §3.2, classify whether it should land in the next
phase of the migration campaign:

| ID | Function | Priority | Where it should live |
|---|---|---|---|
| G-1 | Carrier shadow log review | **P0 — required for DL-G1 sandbox shadow** | New panel inside DHL Express tab (W-2.5 in matrix); read-only, gated by `carrier_dhl_shadow_mode` |
| G-2 | Carrier mode banner | **P0 — operator safety** | Top of DHL Express tab (W-2.6 in matrix); requires ADR-018 + small backend mode-status endpoint |
| G-5 | Closure `/evaluate` recovery | P1 | Recovery sub-action under closure-eval card; behind confirm modal |
| G-7 | wFirma reservation reset-stuck | P1 | Per-document footer button on reservation preview; behind confirm |
| G-9 | DHL-clearance recovery actions (proactive-dispatch + 6 others) | **P1 — W-5 P2 specifically** | DHL / Customs tab; per-action confirm modals |
| G-10 | Lifecycle agency-followup + direct-dispatch | P2 | DHL / Customs tab next to agency cards; behind confirm |
| G-11 | Agency SAD decision read | P2 | Agency SAD section card (read-only) |
| G-12 | DSK audit log | P2 | DSK section, read-only collapse |
| G-3 | Cross-batch carrier list | P3 | New top-level page (or new section in cross-batch page bar) |
| G-4 | Cross-batch carrier proposals | P3 | Same as G-3 |
| G-6 | Reservations queue + imports | P3 | New "Reservations" panel in PZ / wFirma tab; complex (forms + orchestration) |
| G-8 | Corrections registry | P3 | New "Corrections" panel in Intelligence tab |
| G-13 | wFirma capabilities / diagnostics | P4 | Admin / Settings tab |
| G-14 | Warehouse locations CRUD | P4 | New section under warehouse-scanner page |
| G-15 | Packing barcode print + ZPL | P4 | Packing list card sub-actions |
| G-16 | Intake follow-up reads | P4 | Intake form's success state |

---

## 6. Write-action safety map

For every WRITE function (POST / PUT / PATCH / DELETE) currently
hidden or partially exposed, the safety contract that any future UI
must enforce:

| Function | Endpoint | Existing gate | Required UI confirmation | Actor / reason | Rollback / warning |
|---|---|---|---|---|---|
| Closure /evaluate | `POST /api/v1/closure/{id}/evaluate` | API-key auth | Modal with "This writes audit entries" | actor required (operator name) | Cannot be undone — show warning |
| Reservation reset-stuck | `POST /api/v1/wfirma/reservations/{draft_id}/reset-stuck` | API-key | Modal naming the draft id + current status | actor + reason | Reversible if next preview re-issues; show "this releases the wFirma lock" warning |
| Reservations process-pending | `POST /api/v1/reservations/process-pending` | API-key | Modal — operator confirms which batches | actor | Idempotent retry safe |
| Reservations import-{purchase,sales}-packing | `POST /api/v1/products/import-purchase-packing`, `POST /api/v1/reservations/import-sales-packing` | API-key | Modal — file upload + diff preview | actor | Idempotent by sha256 of file contents |
| Reservation queue reset | `POST /api/v1/reservations/{queue_id}/reset` | API-key | Modal naming queue id | actor + reason | Recovery only |
| Lifecycle agency-followup | `POST /api/v1/lifecycle/agency-followup` | API-key | Modal — fires email | actor | Reversible by "Stop follow-up" |
| Lifecycle inventory-state/mark-direct-dispatch | `POST /api/v1/inventory-state/mark-direct-dispatch` | API-key | Modal — irreversible state mark | actor + reason | **Irreversible warning required** |
| DHL clearance approve | `POST /api/v1/dhl/approve/{id}` | API-key | Modal — approves customs clearance | actor + reason | **Irreversible warning** |
| DHL clearance proactive-dispatch | `POST /api/v1/dhl/proactive-dispatch/{id}` | API-key | Modal — sends email to DHL customs | actor + reason | One-way (email sent) |
| DHL clearance generate-customs-package | `POST /api/v1/dhl/generate-customs-package/{id}` | API-key | Modal — generates files | actor | Reversible (regenerate) |
| DHL clearance match-and-handle | `POST /api/v1/dhl/match-and-handle` | API-key | Modal — bulk action | actor | Idempotent reads |
| Carrier action create-shipment | `POST /api/v1/carrier/actions/create-shipment/execute` | API-key + proposal_id + lock | **Full data-entry form (W-2.3b — not a confirm drawer)** | actor + reason | Idempotent by `(batch_id, reference)` |

Cross-cutting requirement (from W-2.3 + W-7 / B1.b precedent):
- Every write surface UI must include `actor` (operator name) input.
- Every write surface UI must include `reason` (free text) field.
- Every irreversible action (cancel, mark-direct-dispatch, approve)
  must show an explicit warning copy with `cannot be undone` /
  `voids …` language.
- Every disabled button must name its `disabledReason`.
- Single armed POST site per write surface — no auto-submit, no
  alert(), no bare button.

---

## 7. Design adaptation recommendation per missing function

For each missing function, where it should live in the UI:

| ID | Recommendation |
|---|---|
| G-1 carrier shadow log | New `<Card data-testid="carrier-shadow-panel">` inside the DHL Express tab, rendered only when `carrier_dhl_shadow_mode=True`. Read-only; matches W-2.5 in the operational matrix. |
| G-2 carrier mode banner | Top-of-tab banner inside the DHL Express tab, sticky. Requires ADR-018 + new GET `/api/v1/carrier/mode` endpoint. Matches W-2.6. |
| G-3 cross-batch carrier list | Standalone read-only page (mirror of action-proposals cross-batch). Net-new top-level page. |
| G-4 cross-batch carrier proposals | Same. |
| G-5 closure `/evaluate` recovery | Sub-section under existing closure-eval card. Hidden behind operator's "Show recovery actions" toggle. Confirmation modal before POST. |
| G-6 reservations queue + imports | New panel inside PZ / wFirma tab with a sub-tab strip ("Queue" / "Import purchase-packing" / "Import sales-packing"). Each sub-tab has its own form. Complex — own implementation phase. |
| G-7 reservation reset-stuck | Per-document footer button on reservation preview card. Behind confirm modal. |
| G-8 corrections registry | New panel inside Intelligence tab. List + filters + per-row "explain". Read-only first; write surfaces follow. |
| G-9 DHL-clearance recovery actions | Existing DHL / Customs tab gets new "Recovery actions" collapse. Each action has its own confirm modal. **W-5 self-clearance P2 (proactive-dispatch) is the highest-priority single function here per ADR-013.** |
| G-10 lifecycle agency-followup + direct-dispatch | DHL / Customs tab, sub-section near agency cards. Direct-dispatch is irreversible — strong warning copy. |
| G-11 agency SAD decision read | Card inside DHL / Customs tab, read-only. |
| G-12 DSK audit log | DSK section, read-only collapse. |
| G-13 wFirma capabilities / diagnostics | Admin / Settings tab. Read-only diagnostics surface. |
| G-14 warehouse locations CRUD | Inside warehouse-scanner page, new "Locations" sub-panel. Read-only first; CRUD second phase. |
| G-15 packing barcode print + ZPL | Inside packing-list card, "Print to warehouse" sub-button. ZPL download as plain link. |
| G-16 intake follow-up reads | Intake form's success state shows the two follow-up read endpoints' results inline. |

---

## 8. Phase plan

```
UI-GAP-1   READ-ONLY missing surfaces                  (lowest risk, highest leverage)
   1.1  G-11  agency SAD decision read card           (DHL / Customs tab)
   1.2  G-12  DSK audit log read panel
   1.3  G-1   carrier shadow log review panel         (W-2.5; gated by shadow_mode)
   1.4  G-13  wFirma capabilities/diagnostics read    (Admin tab)
   1.5  G-3   cross-batch carrier shipment list       (new top-level read-only page)

UI-GAP-2   SAFE WRITE confirmations                    (one armed POST per surface)
   2.1  G-7   wFirma reservation reset-stuck          (per-document footer + confirm modal)
   2.2  G-9   DHL clearance recovery — proactive-dispatch ONLY  (W-5 P2; ADR-013)
   2.3  G-9   DHL clearance recovery — generate-customs-package
   2.4  G-9   DHL clearance recovery — match-and-handle
   2.5  G-9   DHL clearance recovery — approve         (irreversible warning)
   2.6  G-10  lifecycle agency-followup                (reversible)
   2.7  G-10  inventory-state mark-direct-dispatch    (IRREVERSIBLE warning)

UI-GAP-3   COMPLEX FORMS                               (full data-entry; multi-field)
   3.1  G-6   reservations import-purchase-packing form
   3.2  G-6   reservations import-sales-packing form
   3.3  G-6   reservations queue + process-pending UI
   3.4  G-8   corrections registry list + filters + explain    (read first)
   3.5  G-14  warehouse locations CRUD
   3.6  W-2.3b carrier create-shipment data-entry form  (independently scoped)
   3.7  G-2   carrier mode banner + new mode-status endpoint   (W-2.6; needs ADR-018)

UI-GAP-4   CLEANUP / OLD LAYOUT REMOVAL                (only after operational evidence)
   4.1  Remove dead read-only routes from dashboard.html if any have been deprecated
   4.2  Consolidate adjacent confirm-modal patterns into a single primitive (refactor)
   4.3  Per-tab visual chrome consistency pass (post all UI-GAP-1..3)
```

**Sequencing rule:** UI-GAP-1 fully ships before UI-GAP-2 opens. UI-GAP-2 is the largest write-surface campaign of the project to date — opens only after sandbox-shadow operational evidence per the stabilization-window posture. UI-GAP-3 and UI-GAP-4 are out of scope until UI-GAP-2 is fully closed and operator review confirms no friction.

---

## 9. Test plan

For each gap:

| Gap | Existing tests | Required new tests | Source-grep guards |
|---|---|---|---|
| G-1 carrier shadow | `test_carrier_shadow_routes_read_only.py` (backend) | `test_dashboard_carrier_shadow_panel.py` — testid, endpoint pinning, mode-conditional render | only renders when `carrier_dhl_shadow_mode=True` |
| G-2 mode banner | (none — needs ADR-018) | `test_carrier_mode_endpoint.py` (backend) + dashboard banner test | banner reads from new mode endpoint; never directly from settings |
| G-5 closure /evaluate | `test_closure_eval_card.py` (read side) | dashboard test pinning recovery sub-section + confirm-modal + actor input | actor required; cannot-undo warning present |
| G-7 reservation reset-stuck | (none) | dashboard test pinning footer button + confirm modal | actor + reason required |
| G-9 DHL recovery actions | `test_dhl_clearance_*.py` (backend) | per-action dashboard test (one file per action) | one armed POST per surface; irreversible warning where applicable |
| G-10 agency-followup + direct-dispatch | (none — both API-only) | dashboard test pinning DHL/Customs sub-section | direct-dispatch irreversible warning required |
| G-11 agency decision read | (backend) | dashboard test pinning card + read-only marker | endpoint pinning |
| G-12 DSK audit log | (backend) | dashboard test pinning DSK section + audit-log read | endpoint pinning |
| G-3, G-4 cross-batch lists | `test_carrier_*_routes_read_only.py` (backend) | dashboard test pinning new page + endpoint refs | read-only |
| G-6 reservations queue + imports | (backend) | dashboard test pinning forms + multipart upload + idempotency-by-sha256 | actor + reason required |
| G-8 corrections registry | (backend tests under `test_corrections_*.py`) | dashboard test pinning new panel | read-only first |

Cross-cutting source-grep guards each new phase must add:
1. **No FedEx / UPS / multi-carrier** — parametrised against the markers `FedEx IP`, `FedEx Priority`, `["DHL","FedEx","UPS"]`, `Estrella Atlas`, `Shipping Operations`.
2. **No alert() near write surface** — sweep around each new write-surface testid.
3. **No bare write button** — every write must go through a confirm modal/drawer; the trigger button only opens the modal.
4. **`actor` input required** — every write modal must contain a non-empty operator-name input.
5. **`disabledReason`** rendered for every disabled button.
6. **Whole-file brace balance** preserved.
7. **No new component** unless explicitly approved per phase (no surprise StatTile / AccountingPage / WfirmaSyncPage adoption).

---

## 10. Final recommendation

```
═══════════════════════════════════════════════════════════════════
  UI FUNCTIONALITY GAP AUDIT — Backend vs. Design vs. Dashboard
  Date:     2026-05-10
  Baseline: 2d1ea7a
═══════════════════════════════════════════════════════════════════

  Backend functions inventoried:        260 routes across 44 files
                                        (excluding admin/system small files)
  Dashboard distinct testids:           344
  Dashboard tests at HEAD:              1248 / 1248 green
  make verify at HEAD:                  160 / 160 green

  Backend functions NOT exposed in the
  current dashboard (hidden / API-only): 16 named gaps (G-1..G-16)

  New design omits or weakens 9 hard
  workflows + 7 soft surfaces:           closure / broker / customer
                                        statements / sales linkage /
                                        wFirma reservation preview /
                                        Polish description / DHL
                                        action state / agency SAD
                                        decision / W-2 carrier UI

  Must-preserve (existing UI):           15 named workflows totalling
                                        ~510 dashboard tests across
                                        the trust layer.

  Must-add UI (gap closures):            16 named gaps prioritised
                                        P0 → P4. Top three:
                                          G-1  carrier shadow log review (W-2.5)   P0
                                          G-2  carrier mode banner (W-2.6)         P0
                                          G-9  DHL self-clearance proactive-       P1
                                                dispatch (W-5 P2 / ADR-013)

  Recommended NEXT UI phase to implement:
    UI-GAP-1.1 — agency SAD decision read card.
      Lowest-risk read-only surface; small testid set; no
      backend addition; closes G-11. Single commit; mirrors
      W-2.1 / W-2.2 style shape. Ideal first gap-close.

    Alternative NEXT phase (higher impact):
    UI-GAP-1.3 — carrier shadow log review panel.
      Closes G-1; provides operator-visible diff during sandbox
      shadow window (the DL-G1 RELEASE recommendation). Single
      commit; new testids; existing endpoints; feature-flag
      gated render.

  Phases that should WAIT:
    UI-GAP-2 (write confirmations) — opens only after sandbox-
        shadow operational evidence per stabilization-window
        posture.
    UI-GAP-3 (complex forms — reservations imports, corrections
        registry CRUD, carrier create-shipment, mode banner) —
        each is its own PRE-IMPLEMENTATION campaign.
    UI-GAP-4 (cleanup) — only after UI-GAP-1..3 fully ship.

  Design parts to IGNORE (do not migrate at all):
    - shipping-ops page (multi-carrier wireframe)
    - FedEx / UPS sample data in dashboard-page.jsx, master-page,
      client-kyc, document-suite carrier select
    - design's bare 'Export to wFirma!' button + alert() pattern
    - design's <AccountingPage> merged paradigm
    - design's <StatTile> component (if it would replace existing
      inline render — adopt only as additive primitive, never
      replacing protected JSX)

  Functions ALREADY SUFFICIENTLY COVERED (no UI work needed now):
    - PZ Run + lock-status + document panel + file downloads
    - Proforma full draft lifecycle
    - Customer statements picker + drawer + PDF
    - Closure-eval read + closure-confirm operator-payload
    - Agency / DHL document upload (W-7 cards)
    - DHL Express overview + timeline + label evidence + drawer
      for 3 simple actions (W-2.1+a / W-2.2 / W-2.3)
    - Action proposals (cross-batch + per-batch)
    - Broker followups
    - Sales linkage panel
    - DHL follow-up stop / send-now / recalculate
    - DSK generate / download / email-package

  Stabilization-window posture
  ----------------------------
  The cell remains at rest. UI-GAP-1 opens only on operator
  approval of:
    (a) the §8 phase plan,
    (b) the §6 write-action safety map (informational for
        UI-GAP-2 onward),
    (c) the explicit ignore list above,
    (d) a chosen first gap (1.1 vs 1.3 vs alternative).

═══════════════════════════════════════════════════════════════════
```

---

## Self-review

- **What this audit catches:** 16 named hidden / API-only functions (G-1..G-16) the existing dashboard does NOT expose, AND that the new design also omits. If migration ran without this audit, none of these would surface — the operator's existing API-only workflows would silently remain undiscoverable forever.
- **Highest-leverage gap closure:** G-1 (carrier shadow log review) directly enables operator-side validation of the sandbox-shadow window scoped in DL-G1. Closing G-1 is a precondition for sandbox-shadow giving operationally meaningful evidence.
- **Highest-risk gap closure:** G-9 (DHL clearance recovery actions, particularly proactive-dispatch). These are W-5 self-clearance P2 territory — net-new write surfaces for customs operations. Each opens its own PRE-IMPLEMENTATION campaign.
- **What this audit does NOT decide:** which gap closes first. The operator picks UI-GAP-1.1 (agency SAD decision read — easiest) vs. UI-GAP-1.3 (carrier shadow log — highest impact) vs. an entirely different starting point. The phase plan in §8 is *sequenced* but the *trigger* is operator approval.
