# Estrella PZ — V2 Frontend Architecture Plan

**Generated:** 2026-05-20  
**Decision locked:** 2026-05-20 — STABLE BACKEND + NEW FRONTEND SHELL  
**Basis:** Operator architectural directive + `docs/wireframe_brief.md` + static analysis  
**Status:** LOCKED DIRECTION — first scope (Proforma V2) implementation-ready

---

## 0. Strategic Foundation

The backend is stable institutional infrastructure — do not rewrite:
- DHL customs orchestration
- PZ lifecycle (C13E stabilized)
- wFirma gates (all write flags, ZC429/export gates)
- Customer Master (C24 stabilized)
- Packing ingestion (C22 stabilized)
- Warehouse projection
- Audit logic / shipment lifecycle / operator sequencing

What gets replaced:
- The rendering shell (`shipment-detail.html` as an all-in-one surface)
- State orchestration
- Page composition
- UI authority structure

V1 is frozen except critical fixes. Do NOT continue adding features to `shipment-detail.html`.

---

## 1. Page Set (delivery order enforced)

| Order | Page | URL | Authority | Priority |
|---|---|---|---|---|
| 1 | Proforma V2 | `/dashboard/proforma-v2.html` | Draft rendering, customer mapping, preview, readiness | FIRST — narrowest authority, highest operator pain |
| 2 | Customer Master V2 | `/dashboard/customer-master-v2.html` | Customer CRUD, NIP/address, wFirma customer matching | HIGH |
| 3 | Products V2 | `/dashboard/products-v2.html` | Product authority, SKU→wFirma product mapping, VAT rates | HIGH |
| 4 | PZ V2 | `/dashboard/pz-v2.html` | PZ lifecycle, wFirma reservation, warehouse audit gate | HIGH |
| 5 | Shipment V2 | `/dashboard/shipment-v2.html` | Pipeline, documents, timeline, DHL clearance status | MEDIUM |
| 6 | Dashboard V2 | `/dashboard/dashboard-v2.html` | Batch list aggregation only (read-only) | LAST — depends on all domain pages |

**Why this order:** Domain pages first. Aggregation last. Dashboard-v2 depends on all other domain truths being stable — build it last. `shipment-detail.html` was the wrong model precisely because it tried to own all these domains simultaneously.

---

## 2. Authority Boundaries (hard — do not cross)

```
proforma-v2.html
  OWNS:  draft rendering, customer mapping (display + save),
         proforma preview, readiness visualization,
         approve / re-open / cancel draft, service charges
  NEVER: DHL, warehouse, customs, audit intelligence,
         sales linkage, PZ creation, wFirma write (gated only)

customer-master-v2.html
  OWNS:  customer CRUD (name, NIP, address, payment method),
         wFirma customer ID mapping, bill_to / ship_to defaults
  NEVER: proforma drafts, PZ, warehouse, product mapping

products-v2.html
  OWNS:  product authority (SKU → wFirma product),
         Polish name, VAT rate, unit, sync status
  NEVER: customer mapping, proforma drafts, PZ lifecycle

pz-v2.html
  OWNS:  PZ lifecycle display (readiness → run → wFirma create),
         warehouse audit gate status, wFirma reservation preview,
         PZ adopt / refresh mapping
  NEVER: proforma drafts, customer authority editing, DHL clearance

shipment-v2.html
  OWNS:  shipment pipeline, documents tab, timeline, DHL status,
         MRN/SAD tracking, broker reply
  NEVER: proforma draft editing, PZ creation, wFirma writes,
         warehouse scan operations

dashboard-v2.html
  OWNS:  batch list (read-only aggregation), filter pills, search
  NEVER: any editing surface, any write operation
```

**The separation is the real fix.** `shipment-detail.html` was not the problem — mixed authorities were. A 15k-line file can survive if authority is clean. A 2k-line file becomes chaos if 6 domains own overlapping truth.

---

## 2b. V2 Migration Discipline Rules (binding — treat as invariants)

### Two absolute rules

```
ONE PAGE = ONE DOMAIN AUTHORITY
NO PAGE MAY OWN ANOTHER PAGE'S BUSINESS LOGIC
```

These two rules, if kept, prevent V2 from becoming the next `shipment-detail.html`.

### Forbidden patterns (resist these during implementation)

| Temptation | Why it fails |
|---|---|
| "quickly reuse some V1 renderer" | Imports V1 authority confusion into V2 |
| "temporarily duplicate logic" | Temporaries become permanent; duplication = split authority |
| "just add one more section into shipment-detail.html" | V1 freeze violation — breaks migration |
| "copy state transforms from V1" | State transforms in V1 often embed multiple domain assumptions |
| "mix preview + accounting + customs in same page" | Recreates the fragmentation on a new filename |
| "make it beautiful first" | Visual polish before authority stabilization = building on sand |

### Priority ordering for V2 work

Build in this order per page. Do not skip ahead:

1. **Deterministic** — given inputs, always same output. No implicit global state.
2. **Inspectable** — every API call visible in DevTools. Every state change traceable.
3. **Authority-clean** — page touches only its own domain APIs.
4. **Workflow-safe** — no action fires without explicit operator click. No auto-saves.
5. **Cache-safe** — no stale state survives across page loads. No `window.*` state singletons.
6. **Deployment-safe** — removing the file from production is the complete rollback.
7. **Visually polished** — last. Only after steps 1–6 verified.

### The critical single decision

Dashboard-v2 is LAST. This alone prevents months of instability. If dashboard-v2 came first, it would depend on unstable renderer contracts, temporary state adapters, and duplicated logic — recreating the V1 problem under a new filename.

---

## 3. Static Serving — No New Python Routes

The existing `/dashboard/{path:path}` handler (`main.py` line 505) serves any file in `app/static/`. New V2 pages land at their URLs automatically when deployed. No `main.py` changes needed.

---

## 4. Shared Layer Architecture

Four files. Each has a single, bounded responsibility. Load order per page:
```html
<script src="/dashboard/pz-api.js"></script>
<script src="/dashboard/pz-state.js"></script>
<script src="/dashboard/pz-components.js"></script>
<script src="/dashboard/dashboard-shared.js"></script>
```

**Layer responsibility matrix (hard — do not blur):**

| File | Responsibility | Forbidden from |
|---|---|---|
| `pz-api.js` | Transport only — fetch wrapper, error normalization | Business logic, state, rendering |
| `pz-state.js` | Normalization + workflow state — data shaping, loading/error/data hooks | Transport, rendering, domain rules |
| `pz-components.js` | Reusable rendering primitives — domain-aware but stateless | Fetching, workflow decisions, multi-domain logic |
| `dashboard-shared.js` | Visual primitives only — Badge, Card, Btn, layout atoms | Domain knowledge of any kind |

The right now problem is `render + fetch + state + workflow + transformation` inside one component. These four layers separate those concerns permanently.

### 4.1 `dashboard-shared.js` (existing + additions)

Exposes `window.EstrellaShared`. No changes to existing exports.  
Additions to support V2:

| New primitive | Purpose | Props |
|---|---|---|
| `GateBlock` | Render `blocking_reasons` or `export_blockers` array as styled list | `reasons[]`, `variant: error\|warn`, `title?` |
| `SectionHeader` | 13px bold section divider with optional action slot | `label`, `action?` |
| `CompactTable` | Standard table with `thStyle`/`tdStyle` conventions | `cols[]`, `rows[]`, `onRowClick?`, `emptyLabel?` |
| `StatusDot` | Inline colored circle for row-level status | `status: ok\|warn\|error\|pending` |
| `EmptyState` | Consistent loading / empty / error container | `state: loading\|empty\|error`, `message` |

Rule: add only when ≥2 V2 pages need the primitive.

### 4.2 `pz-api.js` (new)

Thin fetch adapter. No caching. Consistent error shape.
Exposes `window.PzApi`.

```javascript
// Error shape (always): { ok: false, status: number, error: string }
// Success shape:         { ok: true, data: <response body> }

window.PzApi = {
  // Proforma
  getProformaDrafts(batchId),
  previewProforma(batchId, clientName),
  getDraft(draftId),
  patchDraftLine(draftId, lineId, body),
  patchDraft(draftId, body),
  approveDraft(draftId),
  reopenDraft(draftId),
  cancelDraft(draftId),
  resetDraftFromSalesPacking(draftId),
  addDraftLine(draftId, body),
  deleteDraftLine(draftId, lineId),
  addServiceCharge(draftId, body),
  getServiceProducts(),

  // Customer Master
  listCustomerMaster(params),
  getCustomerMaster(clientKey),
  saveCustomerMaster(clientKey, body),

  // Products (product bridge)
  listProducts(params),
  getProduct(productCode),
  saveProduct(productCode, body),

  // Batch list (read-only)
  getBatches(filters),
  getBatchSummary(batchId),
}
```

### 4.3 `pz-state.js` (new)

React hook patterns for page-level data fetching.  
Exposes `window.PzState`. No global shared state — each hook is per-component instance.

```javascript
window.PzState = {
  // Returns { drafts, loading, error, reload }
  useProformaDrafts(batchId),

  // Returns { preview, loading, error, reload }
  useProformaPreview(batchId, clientName),

  // Returns { draft, loading, error, reload }
  useDraft(draftId),

  // Returns { record, loading, error, save, saving }
  useCustomerMaster(clientKey),

  // Returns { batches, loading, error, reload }
  useBatches(filters),
}
```

### 4.4 `pz-components.js` (new)

Domain-specific React components — not generic UI, not page logic.  
Reusable across V2 pages. Exposes `window.PzComponents`.

```javascript
window.PzComponents = {
  // Renders blocking_reasons + export_blockers + ready status
  ProformaReadinessGate({ preview, onReload }),

  // Draft state chip: draft/approved/cancelled/etc.
  DraftStateChip({ state }),

  // Inline-editable line row for draft line table
  DraftLineRow({ line, editable, onSave, onDelete }),

  // Customer authority card: matched / not matched / remap
  CustomerAuthorityCard({ resolution, clientName, onRemapOpen }),

  // Per-line product authority row
  ProductAuthorityRow({ line, productRecord }),

  // DEV-BYPASS warning banner
  DevBypassBanner({ active }),
}
```

---

## 5. First V2 Scope — `proforma-v2.html`

### 5.1 URL

```
/dashboard/proforma-v2.html?batch_id=SHIPMENT_...&client=ClientName
```

`batch_id` required. `client` optional — defaults to first draft in list.

### 5.2 Component Tree

```
ProformaV2Root
├── SessionBanner
├── BatchCrumb (batch_id, AWB, carrier badge → links back to shipment)
├── ClientSelector (Sel: which client to view)
│
├── ReadinessGate
│   ├── ProformaReadinessGate (from PzComponents)
│   └── DevBypassBanner       (if bypass active)
│
├── DraftPanel
│   ├── DraftStateChip
│   ├── [DraftHeader: draft_id, currency, issued_number if approved]
│   ├── DraftLineTable
│   │   └── DraftLineRow ×N  (CompactTable + inline edit)
│   ├── ServiceChargeTable   (CompactTable)
│   ├── DraftRemarksEditor   (textarea + explicit Save button)
│   └── DraftActionBar
│       ├── Btn "Approve Proforma"  (primary — only when state allows)
│       ├── Btn "Re-open Draft"     (outline — only when approved)
│       ├── Btn "Cancel Draft"      (danger — confirmation required)
│       └── Btn "Reset from Sales"  (ghost)
│
├── CustomerCard
│   └── CustomerAuthorityCard (from PzComponents)
│
└── ProductMappingSection
    └── ProductAuthorityRow ×N (per draft line — shows match status)
```

### 5.3 Save Discipline

- Every write button labels the exact write: "Save Line", "Approve Proforma", "Save Customer Mapping"
- No auto-save anywhere
- "Cancel Draft" requires `<Modal>` confirmation before calling API
- Disabled buttons show reason in `title` attribute or inline helper text

### 5.4 Gate Display

| State | Display |
|---|---|
| `blocking_reasons` non-empty | Red `GateBlock` — create blocked |
| `export_blockers` non-empty | Amber `GateBlock` — bypass active, create still blocked |
| Both empty | Green chip "Ready to Issue" |
| `DEV-BYPASS` active | Amber `DevBypassBanner` above gate |

### 5.5 API Calls

```
GET  /api/v1/proforma/drafts/{batch_id}
POST /api/v1/proforma/preview/{batch_id}/{client_name}   (non-mutating readiness check)
GET  /api/v1/proforma/draft/{draft_id}
PATCH /api/v1/proforma/draft/{draft_id}/lines/{line_id}
POST /api/v1/proforma/draft/{draft_id}/approve
POST /api/v1/proforma/draft/{draft_id}/re-open
POST /api/v1/proforma/draft/{draft_id}/cancel
POST /api/v1/proforma/draft/{draft_id}/reset-from-sales-packing
GET  /api/v1/customer-master                              (customer authority)
PUT  /api/v1/customer-master/{client_key}                 (save customer mapping)
GET  /api/v1/proforma/product-options                     (product authority per line)
```

Zero new backend APIs. Zero schema changes.

### 5.6 Acceptance Criteria

1. Page loads at correct URL with valid session; redirects to login without session
2. Readiness gate renders — `blocking_reasons` red, `export_blockers` amber, empty = green chip
3. Draft line table renders; inline edit calls PATCH; "Save Line" toast confirms
4. "Approve Proforma" enabled only when state allows; calls POST /approve
5. "Cancel Draft" shows confirmation modal; calls POST /cancel on confirm
6. Customer card shows authority status + "Matched" / "No mapping" badge; remap saves correctly
7. Product mapping rows show per-line authority status dots
8. `DevBypassBanner` visible when bypass active; absent when off
9. No broken buttons, no `console.error` on load, no 4xx on happy path
10. Rollback: remove file from `C:\PZ\app\static\`, no restart needed

### 5.7 Estimated Size

| File | Lines |
|---|---|
| `proforma-v2.html` | ~800 |
| `pz-api.js` | ~150 |
| `pz-state.js` | ~120 |
| `pz-components.js` | ~200 |
| `dashboard-shared.js` additions | ~80 |
| Tests (contract + integration) | ~60 |
| Total | ~1,410 |

---

## 6. V1 Freeze Rules

Effective immediately. `shipment-detail.html` and `dashboard.html` are frozen to:

| Allowed | Not allowed |
|---|---|
| Critical bug fixes (breaking production flow) | New feature additions |
| Security patches | New tabs or sections |
| Governance-mandated hotfixes | New rendering surfaces |
| | Refactoring (do it in V2 instead) |

"Critical" = production is broken or data is at risk. Cosmetic issues, missing states, and UX improvements wait for V2.

---

## 7. Migration Phases

```
PHASE 1 — Build isolated V2 pages against existing APIs
  Proforma V2 → Customer Master V2 → Products V2 → PZ V2 → Shipment V2 → Dashboard V2
  V1 stays live throughout.

PHASE 2 — Validate with operator (2-week parallel run per page)
  Operator uses both. Files friction reports. V2 pages patched.
  V1 pages: critical fixes only.

PHASE 3 — Move authority surfaces one at a time
  When operator confirms V2 page covers full workflow, V1 loses that domain.
  "Try V2 →" links appear in V1 tabs.

PHASE 4 — Retire V1 renderers
  After operator confirms each V2 page covers full workflow.
  V1 pages moved to `_archive/` in static dir (kept for rollback, not served).
  Requires explicit operator sign-off per page retired.

PHASE 5 — Keep backend stable throughout
  No backend API removals. No schema changes unless unavoidable.
  Backend accretes (additive only); frontend migrates.
```

---

## 8. Isolation Contract

| Concern | V1 | V2 |
|---|---|---|
| Global batch state | `window.currentBatch` style globals | URL params only (`?batch_id=`, `?client=`) |
| React root | Single root in dashboard.html | Each page own `ReactDOM.render()` |
| Navigation between pages | Tab click | Full `href` — bookmarkable |
| Shared state | Mixed | `window.PzState` hooks (per-component, no global) |
| Shared components | `window.EstrellaShared` | Same + new V2 primitives |
| Domain components | Inline | `window.PzComponents` |
| API calls | Inline fetch | `window.PzApi` wrapper |

---

## 9. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `previewProforma` POST is slow | Medium | Loading state + debounce on client change |
| Draft state stale after approve (other session) | Low | Refetch on action completion; conflict modal |
| `dashboard-shared.js` regression in V1 | Low | Additions only; existing exports unchanged; test in V1 before V2 deploy |
| Pre-existing test failures mask V2 regressions | Medium | V2 tests are new files; run separately; 9 known pre-existing failures documented |
| V1 "frozen" rule violated under pressure | Medium | Document rule in CLAUDE.md Engineering Lessons; flag any `shipment-detail.html` PR for reviewer-challenge |

---

## 10. Rollback

V2 is additive-only. Rollback = delete V2 files from `C:\PZ\app\static\`. No restart.  
Shared layer additions to `dashboard-shared.js` are backward-compatible (new exports only).  
`pz-api.js` + `pz-state.js` + `pz-components.js` are only loaded by V2 pages.

---

## 11. Open Items for Operator

1. **Default client on Proforma V2** when `?client=` is absent — first draft in list or "select client" prompt?  
   Assumption: default to first draft's client.

2. **"Try V2 →" link in V1 tabs** — opt-in link in proforma tab header pointing to `proforma-v2.html?batch_id=X&client=Y`?  
   Assumption: yes, add opt-in link (no forced redirect).

3. **Customer authority 5 clients + product authority 12 products** — still needed in production before Proforma V2 shows "Ready to Issue" for shipment 4218922912. Data entry via Customer Master tab (V1 or V2).
