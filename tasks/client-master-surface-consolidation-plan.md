# Client Master Surface Consolidation — Inspection & Plan

**Status:** Inspection only. No implementation.
**Date:** 2026-05-16
**Prior context:** PR #147 + #148 finished the *terminology* fix. The
operator surface now reads "Client Master" everywhere, but the React
nav still ships TWO entries (`'clients'` and `'customer_master'`) that
hit different API surfaces. This document maps the split and proposes
a consolidation strategy.

---

## Current split

Two Master Data nav entries currently route to two distinct React panels:

| Nav entry | Entity id | React panel `data-testid` | Backing GET endpoint |
|---|---|---|---|
| **Clients** | `'clients'` | `master-clients-panel` | `/api/v1/wfirma/customers/` (wFirma mapping table) |
| **Client Master** | `'customer_master'` | `master-customer-master-panel` | `/api/v1/customer-master/` (operator-managed master) |

A combined effect-hook (`dashboard.html:3676`) preloads BOTH datasets
when EITHER tab is active:

```js
if ((activeEntity === 'clients' || activeEntity === 'customer_master')
    && !custMaster.ts && !custMaster.loading)
  loadCustomerMaster();
```

— so the data is already shared, only the rendering is split.

### Cross-references already wired

- The **Clients** panel reads `customer_master` per row to show
  configured/Risk badges (`getCm(c)` helper, line ~3823).
- The **Clients** "Edit" button (`master-clients-btn-kyc`, line 4357)
  opens `<ClientKycModal>` — which is the same modal the
  **Client Master** "Open full profile" button (`master-cm-btn-open-profile`,
  line 4668) opens. Modal payload: `{ rec: <wFirma client>, custMasterRec: <customer_master row> }`.
- `ClientKycModal` already renders KYC + KUKE + Invoices + Shipping +
  Carriers tabs (line 2342).
- The **Client Master** panel additionally exposes an inline edit form
  for the freight/insurance amounts via `master-cm-btn-edit` and the
  new wFirma Fetch button (`master-cm-btn-fetch-wfirma`).

**Conclusion:** the data model and the modal already treat these as
one entity. Only the *list views* are duplicated.

---

## Problem

Operator confusion:
1. Two nav entries claim to be "the clients page". The legacy "Clients"
   list is a *wFirma mapping projection*; the "Client Master" list is
   the *operator-managed master*. Same business object, two tables.
2. Different actions on each tab. The wFirma Fetch button lives only
   on Client Master. The sync-status indicator lives only on Clients.
   The KYC modal is reachable from BOTH but via different buttons.
3. Search/filter state is per-panel. An operator filtering Clients
   does not see the same filtered set on Client Master.
4. The footer master-data summary (line 6512) still listed both —
   already cleaned up in PR #147 but the nav remains.

---

## Surface inventory (matrix)

| # | Surface | Current label | Entity id | Data source | Belongs in unified CM? | Risk to move | Recommended action |
|---|---|---|---|---|---|---|---|
| 1 | Clients table (list view) | Clients | `'clients'` | `GET /api/v1/wfirma/customers/` | YES — projection of same business object | LOW — read-only list | **Merge into Client Master tab as "Identity" sub-view** |
| 2 | Client Master configuration table | Client Master | `'customer_master'` | `GET /api/v1/customer-master/` | YES — primary master | n/a (target) | **Keep as primary list** |
| 3 | Open full profile (KYC modal) | "Open full profile" / "Edit" | shared modal | `ClientKycModal` | YES — already shared | NONE — already shared | **Single button on unified list** |
| 4 | Shipping tab (inside modal) | Shipping | KYC modal sub-tab | `/api/v1/customer-master/{id}/shipping-addresses` | YES | NONE | Keep in modal |
| 5 | Carriers tab (inside modal) | Carriers | KYC modal sub-tab | `/api/v1/customer-master/{id}/carrier-accounts` | YES | NONE | Keep in modal |
| 6 | KYC tab (inside modal) | KYC | KYC modal sub-tab | `PUT /api/v1/customer-master/{id}` | YES | NONE | Keep in modal |
| 7 | KUKE/Credit tab (inside modal) | Credit | KYC modal sub-tab | same | YES | NONE | Keep in modal |
| 8 | Invoices tab (inside modal) | Invoices | KYC modal sub-tab | same (vat_mode, series ids) | YES | NONE | Keep in modal — Advanced disclosure already added (PR #145) |
| 9 | Freight/Insurance inline editor | inline | inside Client Master row | same | YES | LOW — already in Client Master | Keep inline |
| 10 | wFirma contractor review | review panel | inside Client Master panel | `GET /api/v1/customer-master/sync-from-wfirma/preview` | YES — already inside Client Master | NONE | Keep |

---

## Recommended option: **A — Low-risk consolidation**

Hide the legacy `'clients'` nav entry behind the unified Client Master
tab; surface its content as a **list-mode toggle** inside Client Master.

### Concrete shape

```
Master Data ▸ Client Master                  (single nav entry)

   ┌─ View mode ─┐
   │ • Master    │  ← default: customer_master rows (current behaviour)
   │ • Identity  │  ← wFirma customers projection (current Clients tab)
   │ • Review    │  ← wFirma fetch review (current Fetch button output)
   └─────────────┘
```

- The existing `'clients'` ENTITIES entry is removed from the visible
  sidebar but the `activeEntity === 'clients'` rendering branch stays
  alive (reached via the new internal view-mode toggle so legacy
  testids `master-clients-panel`, `master-clients-btn-kyc`,
  `master-customers-row`, `master-customers-sync` continue to resolve).
- Internal entity id stays `customer_master`. No backend / route /
  schema rename.
- `<ClientKycModal>` remains the single Open-full-profile surface.
- Search/filter input becomes shared (one `query` already exists at
  the page level).

### Why option A and not B

- **Option B (full merge)** would unify the React components into one
  table with mixed columns. Two risks:
  - The two endpoints return *different shapes*
    (`/wfirma/customers/` vs `/customer-master/`). Reconciling them
    server-side or client-side adds a real bug surface, especially for
    operators relying on the per-row `Sync` column today.
  - Loses the 2-list-1-modal mental model the operator has been using
    for months. The KYC modal already covers all sub-detail concerns.
- **Option C (keep separate)** has no business benefit — the operator
  brief explicitly flags the split as confusing.

### Why not rename internals

The brief says:
> keep DB filename if migration risk high
> keep route filename temporarily if needed

A future "rename `/api/v1/customer-master/*` → `/api/v1/client-master/*`"
PR is feasible but out of scope for this consolidation. The
operator-facing language is already correct; route paths are
ops/integration territory.

---

## Files affected (implementation, when scheduled)

### Frontend (only)
- `service/app/static/dashboard.html`:
  - Remove the `{ id: 'clients', label: 'Clients', … }` row from
    `ENTITIES` (sidebar visibility).
  - Add a `[viewMode, setViewMode]` state inside MasterDataPage scoped
    to the customer_master panel (default `'master'`).
  - Wrap the existing two rendering branches in a `switch (viewMode)`
    block so both panels render inside the `customer_master` tab.
  - Header chip strip: 3 buttons (Master / Identity / Review) wired
    via `data-testid="cm-view-mode-master"` etc.
  - Update the panel header subtitle to reflect the active view.
  - Single shared search input — already present at page scope.

### Backend
- **No backend changes.** Route paths, schema, and route filenames
  remain. Migration risk: **zero**.

### Tests
- `service/tests/test_dashboard_master_design.py` — update the sidebar
  count assertion (one fewer visible entry) and add a view-mode-toggle
  presence check.
- `service/tests/test_master_data_cm_wfirma_review.py` — already pins
  the canonical labels; no change needed for consolidation logic.
- Optionally add `service/tests/test_client_master_consolidation.py`
  with the contract tests below.

---

## APIs affected

**None.** The consolidation is a pure UI restructure. The same two GET
endpoints continue to power the two view modes; the same KYC modal
continues to drive sub-tab CRUD on shipping-addresses, carrier-accounts,
and customer_master.

---

## UI movement summary

| Item | Before | After |
|---|---|---|
| Sidebar nav entries (clients + cm) | 2 | 1 (Client Master) |
| Sidebar nav count | 16 visible | 15 visible |
| Visible panels inside CM tab | 1 | 3 view modes |
| KYC modal reach | from both tabs | from any view mode |
| wFirma Fetch button | inside Client Master only | inside Review view mode (same DOM, same testid) |
| Shipping / Carriers / KYC modal sub-tabs | unchanged | unchanged |
| Search/filter input | per-panel | shared (already page-scope) |
| Backend routes | unchanged | unchanged |

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Lost legacy testids if `'clients'` rendering branch is deleted | MEDIUM | Keep the branch; switch on `viewMode` so existing testids resolve when the operator picks "Identity" view |
| External documentation or training material refers to "Clients" sidebar entry | LOW | Add a brief release note in `tasks/lessons.md` after merge; the entry still exists conceptually as "Client Master → Identity view" |
| Operator workflow disruption | LOW-MEDIUM | Default the new view-mode toggle to `'master'` so the post-merge behaviour matches the current "Client Master" tab exactly |
| Search state migration | LOW | The page-level `query` state already feeds both panels; no state changes needed |
| Counts displayed on sidebar (customer.items.length, custMaster.items.length) | LOW | The Client Master count badge already reads `custMaster.items.length`; that becomes the single visible count |
| Tests catching unused `'clients'` entity id | LOW | Internal id stays, only the visible nav entry is removed |
| KYC modal payload assumes both `rec` and `custMasterRec` | LOW | Already handled — modal accepts a stub `rec` if only `custMasterRec` is known (line 4670 fallback) |

---

## Tests needed (when consolidation lands)

| # | Contract | Form |
|---|---|---|
| 1 | Only one visible Client Master nav entry | Source-grep ENTITIES: count of `live: true` items shows the right total; `'clients'` is no longer in the visible ENTITIES list OR is filtered before rendering |
| 2 | No "Clients" + "Client Master" duplication in sidebar render | `data-testid="entity-clients"` not present in rendered MasterDataPage block; only `entity-customer_master` remains |
| 3 | View-mode toggle present with 3 options | testids `cm-view-mode-master`, `cm-view-mode-identity`, `cm-view-mode-review` |
| 4 | All previous actions still reachable | testid presence audit: `master-clients-btn-kyc`, `master-customers-row`, `master-customers-sync`, `master-cm-btn-edit`, `master-cm-btn-open-profile`, `master-cm-btn-fetch-wfirma`, `master-cm-wf-review-panel`, `kyc-panel-shipping`, `kyc-panel-carriers`, `kyc-panel-kyc`, `kyc-panel-invoices` |
| 5 | wFirma review still reachable | `cm-view-mode-review` switches into the review panel; clicking Fetch loads proposals as today |
| 6 | Shipping / Carriers / KYC / KUKE / Invoices still reachable | KYC modal opens from any view mode and renders all sub-tabs |
| 7 | PZ regression remains 160/160 | `python test_pz_regression.py` |

---

## Implementation batches (when scheduled)

### Batch 1 — view-mode scaffolding (smallest)
- Add `viewMode` state and three buttons in the Client Master panel
  header. No nav changes yet.
- Render the existing `master-customer-master-panel` content when
  `viewMode === 'master'` (current behaviour).
- Wrap the existing `'clients'` rendering branch and conditionally
  render it when `viewMode === 'identity'`.
- Wrap the wFirma review panel under `viewMode === 'review'`.
- Tests 3 + 4 + 5 + 6 land here.

### Batch 2 — sidebar hide
- Remove the `{ id: 'clients', … }` row from `ENTITIES`.
- Update `loadCustomerMaster` effect to no longer depend on the
  legacy entity id check (line 3676) — switch to view-mode-aware
  loading.
- Tests 1 + 2 land here.

### Batch 3 — optional polish (deferred)
- Default view-mode persistence in localStorage so an operator who
  prefers Identity view doesn't have to switch on every reload.
- Visual diff polish on the chip strip.
- Possibly: a single combined search filter that scans across both
  data sources at once.

Each batch is independently deployable. PR per batch keeps the GATE 2
(max 3 open PRs) discipline.

---

## Out of scope for this consolidation

- Renaming `/api/v1/customer-master/*` to `/api/v1/client-master/*`
  (separate PR if desired; integration risk is real)
- Renaming `customer_master.sqlite` → `client_master.sqlite` (migration
  risk; not worth it)
- Renaming the internal `'customer_master'` entity id (touches
  every existing test allow-list, no operator benefit)
- Packing-list contractor resolver (still gated)
- wFirma write path (permanent hard stop)
- Finance activation (permanent hard stop)

---

## Decision needed from operator

Before Batch 1 starts, the operator must confirm:
1. Yes to Option A (low-risk view-mode consolidation inside one tab).
2. Default view-mode preference: **Master** (current Client Master
   list view) — preserves existing default behaviour.
3. Acceptance criteria: the visible nav drops from 16 to 15 entries,
   no testid regressions, KYC modal still reachable from every view
   mode, wFirma Fetch button continues to work.
