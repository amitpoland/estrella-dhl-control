# UI-3.1 Warehouse + Inventory Operational Shell — Readiness Audit

**Mode:** PRE-IMPLEMENTATION
**Scope:** verify what already exists before any UI-3.1 work is
planned. Doc-only.
**Baseline:** `97ba703` (UI-2c-copy closed)
**Reviewer pass:** Coordinator + Backend Architect + Route/API
Mapper + UI/UX Planner + QA Lead + Gap Hunter +
Operator-Safety (Coordinator-simulated).

> **No `tasks/todo.md` / `tasks/lessons.md` found in the repo**
> (paths inspected: repo root, `service/`, `.claude/`,
> first-three-level descendants). Audit proceeds from observable
> code + the existing artifact corpus.

---

## 0. Pre-flight gates

| Gate | Result |
|---|---|
| `git status --short` | clean |
| Branch | `feature/dhl-label-workflow-planning` |
| Dashboard suite (38 files) at HEAD | 1395 / 1395 pass |
| `make verify` | 160 / 160 pass |

---

## Implemented

### 1. Warehouse audit (per-batch) — full surface

Anchor: `activeTab === 'Warehouse'` block (lines 4893-5091 of
`service/app/static/dashboard.html`).

Existing UI:
- `ReadinessBanner` for warehouse (line 4914: `data-testid="readiness-banner-warehouse"`)
- Refresh button → `loadWarehouseAudit` → GET `/api/v1/warehouse/audit/{batch_id}`
- Loading / error / empty states named
- "Completion Summary" card: total / scanned / dispatched / missing / completion %
- **Reservation gate** card: clean → "✓ Audit clean — reservation gate OPEN"; otherwise "⚠ Audit issues present — reservation gate BLOCKED"
- Four detail sections: missing_scans, stuck_inventory, invalid_flows, orphan_inventory (each with its own table + thStyle/tdStyle chrome)
- Loader callback `loadWarehouseAudit` already wired into `useEffect` on tab activation

Backend support already in place:
- `GET /api/v1/warehouse/audit/{batch_id}` ✓
- `GET /api/v1/warehouse/audit/{batch_id}/lines` (D: 1 — used) ✓

### 2. Packing list — per-batch upload + status

Anchor: `data-testid="packing-list-card"` at line 3534.

- Upload input (`packing-list-upload-input`)
- Empty state (`packing-list-empty-state`)
- Status block (`packing-list-status`)

Backend support:
- POST `/api/v1/packing/{batch_id}/upload` ✓
- GET `/api/v1/packing/{batch_id}` ✓

### 3. Readiness aggregation — five banners + cross-domain card

- `ReadinessBanner` primitive defined at line 1419 (reusable component)
- Five banners shipped: `readiness-banner-warehouse`, `-sales`, `-wfirma`, `-dhl`, plus one inside the BatchControlCenter; aggregated overall in `OverallReadinessCard`
- Five readiness sections under the cross-batch readiness UI: products, customers, bridge, PZ, verdict, errors (lines 12353-12539)
- `loadBatchReadiness` + `loadDhlReadiness` callbacks
- `BatchControlCenter` reads `batchReadiness` + `dhlReadiness` directly; no extra fetches

Backend support:
- GET `/api/v1/batch-readiness/{batch_id}/readiness` ✓
- GET `/api/v1/dhl-readiness/{batch_id}` ✓

### 4. Sales linkage — per-batch readiness flags

Anchor: `activeTab === 'Sales'` (lines 5093-5252).

- `sales-linkage-ready-flag`, `sales-linkage-blocked-flag`, `sales-linkage-blocking-reasons`
- Backend: GET `/api/v1/sales/linkage/{batch_id}` ✓

### 5. Closure / execution visibility — full audit-write flow

Anchor: `closure-eval-card` (line 3159) + `closure-confirm-section` (line 3282).

- 20+ closure testids covering eval / confirm / accounting signals / blocking reasons / next-step / disabled-reason / safe-note / log-warn / metadata / accounting-notice / already-completed / not-ready-reason
- Read path: GET `/api/v1/closure/{batch_id}/check`
- Write path: POST `/api/v1/execute/closure_confirm` (W-7 / B1.b execution-guard contract)

### 6. Service invoices — per-batch list + upload

- `audit.service_invoices` array rendered in PZ / wFirma tab (lines 5934-5972)
- POST `/api/v1/service-invoices/{batch_id}/upload` (D: 1)

### 7. Cross-batch dashboards already shipped

- `dashboard/batches?all=1` (cross-batch list)
- Action proposals cross-batch
- Broker followups cross-batch
- Customer statements picker
- Proforma drafts cross-batch

### 8. Reusable components

Available primitives:
- `<Btn>`, `<Card>`, `<Sel>`, `<Inp>`, `<FormField>`, `<Modal>` (in Modal-named usage)
- `<ReadinessBanner>` (5-banner pattern proven)
- `pillStyle()` helper (matches design-token palette)
- Inline-style consts pattern (sectionStyle, tblStyle, thStyle, tdStyle) used in warehouse, reservation, sales surfaces

---

## Partial

### P-1. Warehouse cross-batch operational view

Per-batch warehouse audit is fully shipped, but there is **no cross-batch warehouse-state dashboard**. The batch list shows a `warehouseHint` column (line 302; `b.warehouse_status_hint`) but operators cannot see, e.g., "all batches in PURCHASE_TRANSIT", "all batches with stuck_inventory", or "warehouse completion across the last N days".

### P-2. Inventory-state lifecycle — backend complete, UI absent except 1 column

Backend has a full `inventory_state_engine.py` with 6 states and 5 transitions:
```
None → PURCHASE_TRANSIT          (trigger: pz_generated)
PURCHASE_TRANSIT → WAREHOUSE_STOCK         (warehouse_receive)
PURCHASE_TRANSIT → DIRECT_DISPATCH_READY   (direct_dispatch_marked)
WAREHOUSE_STOCK  → CLIENT_DISPATCHED       (client_dispatched)
DIRECT_DISPATCH_READY → CLIENT_DISPATCHED  (client_dispatched)
CLIENT_DISPATCHED → CLOSED                 (delivery_confirmed)
```

UI surface:
- `b.warehouse_status_hint` rendered as a single column on the batch list
- **Zero** UI references to the lifecycle state names (no `PURCHASE_TRANSIT`, no `DIRECT_DISPATCH_READY`, no `CLIENT_DISPATCHED`)
- **Zero** operator-visible lifecycle visualization (no timeline, no badge legend)

### P-3. Service-invoices intake

Service-invoice intake UI exists (per-batch fetch upload at line 5972), but:
- No status badges
- No cross-batch service-invoice queue
- No GET endpoint surfaced for "service invoices received in last N days"

---

## Missing

### M-1. Direct-dispatch operator action

Backend route exists and is gated:
- POST `/api/v1/inventory-state/mark-direct-dispatch`

Dashboard exposure: **0 references**. Operator cannot mark a batch as direct-dispatch from the UI today. Matches gap audit **G-10** (P2).

### M-2. Reservations queue + imports

Backend has six routes (`routes_reservations.py`):
- POST `/api/v1/products/import-purchase-packing`
- POST `/api/v1/reservations/import-sales-packing`
- GET `/api/v1/reservations/queue`
- POST `/api/v1/wfirma/products/sync-by-codes`
- POST `/api/v1/reservations/process-pending`
- POST `/api/v1/reservations/{queue_id}/reset`

Dashboard exposure: **0 references**. Matches gap audit **G-6** (P3).

### M-3. Warehouse-locations CRUD + scanner integration

Backend has six routes (`routes_warehouse.py`):
- GET `/api/v1/warehouse/config`
- POST `/api/v1/warehouse/scan`
- GET `/api/v1/warehouse/inventory/{scan_code}`
- POST / GET `/api/v1/warehouse/locations`, `/locations/{code}/inventory`

The warehouse-scanner lives at the **standalone** `/dashboard/warehouse.html` page; the batch-detail dashboard does not link to it from the Warehouse tab. Matches gap audit **G-14** (P4).

### M-4. Lifecycle agency-followup trigger UI

Backend route: POST `/api/v1/lifecycle/agency-followup`. Dashboard exposure: **0**. Matches gap audit **G-10** (P2).

### M-5. Packing barcode print + ZPL surfaces

Backend has three packing routes the dashboard doesn't expose:
- GET `/api/v1/packing/{batch_id}/lines`
- GET `/api/v1/packing/{batch_id}/barcode/zpl`
- POST `/api/v1/packing/{batch_id}/barcode/print`

Matches gap audit **G-15** (P4).

---

## Recommended next implementation

Given the cumulative readiness picture, the **smallest non-redundant next step** is:

### Recommended: P-2 → operator-readable inventory-state badge on the Warehouse tab

Single-batch surface. Adds one operator-readable lifecycle badge near the warehouse readiness banner, reading the existing `batchReadiness.warehouse` and `audit.inventory_state` (if present) — falls back to existing `warehouse_status_hint`. Zero new backend, zero new endpoint, zero write surface.

| Field | Value |
|---|---|
| **Scope** | Add a `inventory-state-badge` element next to `readiness-banner-warehouse`; small label-map (`PURCHASE_TRANSIT` → "In transit from supplier" etc.) using the same `pillStyle()` helper pattern UI-2c-copy used for the shadow-diff badge. |
| **Touches** | `service/app/static/dashboard.html` (≈ 20 lines), one new test file (`tests/test_dashboard_warehouse_lifecycle_badge.py`, ≈ 20 tests). |
| **Endpoints** | None new — reads what's already on the audit / readiness payloads. (If the lifecycle state isn't yet on those payloads, fall back to `warehouse_status_hint` and flag a separate small backend addition as a follow-up — but inspect first.) |
| **Risk** | Low — read-only badge; no write path; falls back gracefully when state is unknown. |
| **Closes** | P-2's most-visible operator gap (lifecycle invisibility) without opening the heavier M-1 / M-2 / M-4 write campaigns. |

**Why not M-1 (mark-direct-dispatch UI)?** Because it's a write surface. Per the stabilization-window posture, the prerequisite is "real operator workflow validation," not adding more write paths. The operator review at `5185f19` recorded this explicitly: write-action work is UI-GAP-2 territory, gated on operational evidence.

**Why not M-2 / M-4 / M-5?** All are write surfaces or complex forms (reservations imports, agency-followup trigger, barcode print). All would require ≥ 1 write-action confirmation drawer per surface. Out of step with the operator-product / restraint phase.

**Why not P-1 (cross-batch warehouse view)?** Net-new top-level page; expands surface area without operator-validated need.

**Why not P-3 (service-invoices status)?** Operator review didn't flag service-invoices as a friction; closure flow already references them; small priority.

---

## Files likely to edit (recommended path)

For the recommended P-2 lifecycle badge:
1. `service/app/static/dashboard.html` — single inline addition near the `readiness-banner-warehouse` element (line 4914). Add a label map + `<span data-testid="warehouse-inventory-state-badge">` rendering operator-readable text from an existing data source.
2. `service/tests/test_dashboard_warehouse_lifecycle_badge.py` — new file, ≈ 20 source-grep tests pinning the badge testid, the label map, no write-verb introduction, no FedEx/UPS leak.

**Not in scope (and explicitly NOT recommended this session):**
- Any `routes_*.py` change
- Any new backend endpoint
- Any flag flip
- Touching closure / packing / sales surfaces
- Anything cross-batch

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| The proposed badge surfaces a lifecycle state that the per-batch audit payload doesn't actually carry today → badge shows fallback text forever | Medium | **Verify the audit / readiness payload shape first** before opening the implementation session. If lifecycle isn't on the payload, the recommended step shifts to "backend allowlist addition to expose `inventory_state` field on the warehouse-audit response" — which is a service edit, OUT of UI-3.1 scope and requires a separate readiness check. |
| Duplicate planning if a UI-3.1 spec doc actually exists somewhere outside the inspected paths | Medium | **`tasks/todo.md` and `tasks/lessons.md` do not exist in this repo.** Operator should confirm whether they exist elsewhere; if so, this audit should be re-run against them. |
| Operator confusion from a new badge if its label map disagrees with the existing `warehouse_status_hint` column on the batch list | Low | Map the same source field; or, if `warehouse_status_hint` is computed differently, defer the badge until the source is unified. |
| Adding any test that pins `PURCHASE_TRANSIT` / `DIRECT_DISPATCH_READY` / `CLIENT_DISPATCHED` as operator-visible strings risks future copy churn (matching the F-3 / F-4 lessons from UI-2c-copy) | Low | Pin the **label map keys** (technical state names) but not the **rendered labels** verbatim — or pin both with a single helper indirection that future copy changes can absorb. |
| Scope creep — adding the badge invites "while we're here, also a lifecycle timeline / cross-batch view / mark-direct-dispatch button" | High | Hard-stop the scope at one badge + the label map. Resist any addition. |

---

## Compact output (per /context schema)

```
Implemented:
  Warehouse audit (per-batch, full)              ✓  lines 4893-5091
  ReadinessBanner primitive + 5 wired banners    ✓  line 1419 + 5 sites
  Closure-eval + closure-confirm flow             ✓  lines 3159-3380
  Packing-list-card (per-batch upload + status)  ✓  line 3534
  Sales-linkage panel                             ✓  lines 5180-5210
  Cross-batch dashboards (5)                      ✓  proposals, broker
                                                     followups, customer
                                                     statements, proforma
                                                     drafts, dashboard
                                                     batches
  Reusable primitives                             ✓  Btn, Card, Sel, Inp,
                                                     FormField, Modal,
                                                     ReadinessBanner,
                                                     pillStyle helper,
                                                     sectionStyle/tblStyle/
                                                     thStyle/tdStyle pattern

Partial:
  P-1  cross-batch warehouse operational view    one column hint only
  P-2  inventory_state lifecycle UI              6 states + 5 transitions
                                                  in backend; zero UI
                                                  except one hint column
  P-3  service-invoices intake                   per-batch upload yes;
                                                  no status badges, no
                                                  cross-batch queue

Missing:
  M-1  mark-direct-dispatch operator UI          backend ready; 0 UI
  M-2  reservations queue + imports              6 routes; 0 UI
  M-3  warehouse-locations CRUD                  5 routes; 0 UI
  M-4  lifecycle agency-followup trigger UI      1 route; 0 UI
  M-5  packing barcode print + ZPL UI            3 routes; 0 UI

Recommended next implementation:
  P-2 → single operator-readable inventory-state badge next to the
       warehouse readiness banner. Single-batch surface, read-only,
       label-map pattern (UI-2c-copy precedent). PRE-CHECK REQUIRED:
       confirm the lifecycle state is on the warehouse-audit or
       batch-readiness payload before opening implementation; if not,
       the recommendation shifts to a backend allowlist addition
       under a separate readiness check.

Files likely to edit:
  service/app/static/dashboard.html
       (≈20 lines near line 4914)
  service/tests/test_dashboard_warehouse_lifecycle_badge.py
       (new file, ≈20 source-grep tests)

Risks:
  - lifecycle state may not be on the audit payload today; verify first
  - tasks/todo.md and tasks/lessons.md don't exist; operator should
    confirm whether the UI-3.1 scope doc lives elsewhere
  - label map disagreement with existing warehouse_status_hint column
  - scope creep into M-1 / M-2 / M-4 write surfaces (hard-stop required)
```

---

## Commit policy

This artifact is doc-only. Commit message: `chore(claude): audit UI-3.1 warehouse + inventory readiness`.

Cell remains at rest after commit. No implementation lane opens unless the operator approves both:
1. The recommended scope (single inventory-state badge), AND
2. The pre-check ("verify lifecycle state is on the payload first") completes successfully.

If the pre-check fails (lifecycle not on payload), implementation is **deferred** until the appropriate backend exposure is decided in a separate session.
