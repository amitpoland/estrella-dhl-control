# UI-2b Readiness — wFirma Partial Migrate (Style Only)

**Mode:** PRE-IMPLEMENTATION
**Scope:** identify the wFirma-specific visual surfaces that can
be restyled in UI-2b without touching workflow logic. Doc-only.
**Baseline:** `9c6a3b8` (UI-2a closed)
**Coordinator pass:** in-context (Opus); reviewers (UI/UX
Planner, QA Lead, Gap Hunter) executed as Coordinator-simulated
parallel reads. Operator Safety + Backend Architect + Security
NOT activated this session — UI-2b touches no write/action
surface, no endpoint or payload, and no auth/flag boundary.

---

## 0. Pre-flight gates

| Gate | Result |
|---|---|
| `git status --short` | clean |
| Branch | `feature/dhl-label-workflow-planning` |
| wFirma + Run-PZ focused tests (3 files) | **43 / 43** pass |
| Full dashboard suite at HEAD `9c6a3b8` | 1169 / 1169 pass |
| `make verify` | 160 / 160 pass |

---

## 1. wFirma surface inventory

The wFirma-specific operator surface lives across **three
discrete sub-surfaces** inside dashboard.html. UI-2a has already
touched the four hoisted style consts in B-2 (table chrome) and
the customer/product search-row gap+margin in B-4. UI-2b
addresses the remaining wFirma chrome that UI-2a did NOT touch.

| ID | Sub-surface | Lines (approx) | Touched by UI-2a? |
|---|---|---|---|
| **W-α** | B-2 reservation-preview **per-document footer row** containing `wfirma-create-btn` and the result-state pills | 6064 – 6103 (~40 lines) | **No** — UI-2a touched only the four hoisted style consts (`sectionStyle`, `tblStyle`, `thStyle`, `tdStyle`); the footer row's own inline-style chrome was not addressed |
| **W-β** | B-3 reservation **confirm modal** (`wfirma-confirm-modal`) | 8336 – 8368 (~33 lines) | **No** — UI-2a explicitly excluded the modal interior |
| **W-γ** | B-4 customer/product **search-result info pills** (the inline style block immediately below each search row) | 8925-8950, 8985-9010 (~50 lines) | **No** — UI-2a touched only the row containers (gap + marginBottom); the result-info pill chrome was not addressed |

These three sub-surfaces together carry the entire visible
wFirma operator chrome that UI-2a left untouched. Nothing else
in dashboard.html is a wFirma-specific style site.

---

## 2. Existing workflow contracts

The wFirma surface is bound by these contracts. UI-2b MUST NOT
disturb any of them.

### Reservation preview → confirm modal flow (W-α + W-β)

```
operator clicks `wfirma-create-btn`
  → setCreateConfirm({ client_name, doc })             // pure UI state
  → modal opens with client + doc + line-count summary
  → operator clicks `wfirma-confirm-submit-btn`
  → submitReservation(client_name)                    // single fetch site
  → POST → backend → result.ok / result.code / result.error
  → footer pill renders the right state
```

| Contract | Anchor |
|---|---|
| The Create-Reservation **always** opens the modal first. Never POSTs from the button click. | onClick on `wfirma-create-btn` line 6100 calls `setCreateConfirm`, NOT a fetch. |
| The modal's submit re-runs the **live wFirma diagnostic** before submission. The fineprint at line 8355 documents this. | "If anything has changed since the preview, the request will be blocked." |
| Already-created reservations show "Already created" disabled state — never an alert(), never a bare button. | Line 6102: ternary on `alreadyCreated`. |
| The disabled-state message **always** names a reason (`disabledReason`). | Lines 6084-6094: parametrised disabled-reason rendering. |
| The skip path (`milestone_skip`) renders explicitly — distinct from "already created". | Line 6068-6069. |
| Log-write failure renders explicitly — distinct from create failure. | Line 6072: `wfirma-log-warn`. |
| Modal cancel never POSTs. | Line 8358: `setCreateConfirm(null)`. |

### Search → prefill flow (W-γ)

```
operator types name + clicks `customer-search-btn` / `product-search-btn`
  → searchWfirmaCustomer / searchWfirmaProduct
  → GET /api/v1/wfirma/contractors  /  GET /api/v1/wfirma/goods  (read-only)
  → searchInfo.kind = 'hit' | 'miss' | 'multi' | ...
  → result-info pill shows status + (on hit) prefills editingCustomer / editingProduct
  → operator must still click Save (no auto-save)
```

| Contract | Anchor |
|---|---|
| Search is GET only. Never PUT, never POST. Pinned by `test_search_handlers_do_not_use_method_put`. | regex sweep |
| Search **never** calls `customers/add` or `goods/add` (forbidden auto-create endpoints). Pinned by `test_no_auto_create_customer_endpoint_referenced` + `test_no_auto_create_product_endpoint_referenced`. | absence |
| Search prefills via React state setter only — no auto-save. Pinned by `test_customer_search_prefills_via_state_setter` + `test_product_*`. | UI logic |
| Save is still required after search. Pinned by `test_customer_save_still_required_after_search` + `test_product_*`. | UI logic |
| Hit / miss / multi states render distinct testids. Pinned by `test_customer_search_result_testids_present` + `test_product_*`. | testid set |

---

## 3. Existing test coverage

Three files cover the wFirma surface UI-2b would touch (43 tests
at HEAD):

| Test file | Tests | Coverage |
|---|---|---|
| `test_dashboard_wfirma_reservation_preview_panel.py` | 15 | Reservation preview: tab registration, endpoint wiring, state hooks, ready_to_create flag, blocking_reasons, capability flags, summary counts + currency, per-document required fields, per-row required fields, stock-status badges, loading/error/empty states, brace balance, panel branch presence |
| `test_dashboard_wfirma_search.py` | 17 | Customer/product search: button + row testids, hit-test result testids, GET endpoint references, no-PUT, save-still-required, no-auto-create-customer, no-auto-create-product, prefill-via-state-setter, mark-matched-on-hit |
| `test_dashboard_run_pz_gate.py` | 11 | Run PZ button SAD-decision gate (PZ side; included as adjacent dependency). |

The 62 UI-2a tests in `test_dashboard_pz_chrome.py` already pin
the wFirma testids, endpoint URLs, operator copy, and forbidden
markers. UI-2b builds on that foundation rather than duplicating
it.

---

## 4. Safe styling-only targets for UI-2b

After excluding all logic-bearing pieces, the actually-restyleable
surface for UI-2b is:

### W-α — B-2 footer row chrome (≈ 4 lines)

The outer flex row at line 6064:

```jsx
<div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--border-subtle)',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              gap: 12, flexWrap: 'wrap' }}>
```

Safe value-only changes:
- `marginTop: 12 → 14` (align with sectionStyle's marginBottom 14 from UI-2a)
- `paddingTop: 10 → 12` (align with design)
- `gap: 12 → 14` (more breathing room)

Logic-bearing pieces inside the row (must NOT touch):
- result-state branching (`alreadyCreated`, `result && !result.ok`, `canCreate`, `batchWfirmaBlocked`)
- the four `data-testid="wfirma-*"` landmarks
- onClick handler on `wfirma-create-btn`
- button label ternary `alreadyCreated ? 'Already created' : 'Create Reservation'`
- operator copy: 'Skipped: already progressed (SAD/PZ/Completed)', '✓ Created — wFirma ID:', '⚠ Action completed but log write failed', '✗', 'Disabled —', 'Ready to submit to wFirma'

### W-β — B-3 confirm modal chrome (≈ 4 lines)

The modal body at lines 8344-8357 has four cosmetic style sites:

| Line | Element | Safe value-only changes |
|---|---|---|
| 8344 | description text wrapper `{ fontSize: 12, color: 'var(--text-2)', marginBottom: 12, lineHeight: 1.5 }` | `marginBottom: 12 → 14` (consistency with W-α) |
| 8347 | summary box `{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6, padding: '10px 12px', marginBottom: 14, fontSize: 12, lineHeight: 1.6 }` | `padding: '10px 12px' → '12px 14px'` (align with design); `borderRadius: 6 → 8` (slightly softer) |
| 8354 | fineprint `{ fontSize: 11, color: 'var(--text-3)', marginBottom: 12 }` | `marginBottom: 12 → 14` |
| 8357 | button row `{ display: 'flex', gap: 8, justifyContent: 'flex-end' }` | `gap: 8 → 10` (align with W-γ) |

Logic-bearing pieces (must NOT touch):
- modal title `Confirm wFirma Reservation`
- description text body (operator copy)
- summary box's data labels: Client / Document / Ref / Lines / Total value
- fineprint copy
- button labels: Cancel / Confirm & Create / Submitting…
- `submitReservation(createConfirm.client_name)` handler
- testids: `wfirma-confirm-modal`, `wfirma-confirm-submit-btn`
- the value formatters (`Number(total).toLocaleString('pl-PL', …)`, currency lookup)

### W-γ — B-4 search-result pill chrome (≈ 6 lines)

The result-info pill at lines 8925-8950 (customer) and 8985-9010
(product):

```jsx
<div data-testid={`customer-search-${searchInfo.kind}`}
     style={{
       fontSize: 11, padding: '6px 10px', borderRadius: 6, marginBottom: 12,
       color: …, background: …, border: …
     }}>
```

Safe value-only changes:
- `padding: '6px 10px' → '8px 12px'` (consistency with UI-2a's th/td padding)
- `borderRadius: 6 → 6` (already aligned)
- `marginBottom: 12 → 14` (consistency with W-α and W-β)

Logic-bearing pieces (must NOT touch):
- the `data-testid={`customer-search-${searchInfo.kind}`}` template (testid landmark contract)
- the conditional `color: …`, `background: …`, `border: …` branching
- inner copy

---

## 5. Forbidden logic / copy / testid / endpoints

UI-2b must keep these unchanged. Comprehensive list:

### Logic variables
`reservationPreview`, `searchInfo`, `searchBusy`, `editingCustomer`,
`editingProduct`, `createConfirm`, `createBusy`, `createResults`,
`alreadyCreated`, `canCreate`, `batchWfirmaBlocked`, `isDisabled`,
`disabledReason`, `wfirmaPrimary`, `result.ok`, `result.code`,
`result.error`, `result.log_write_failed`, `result.stage`,
`result.reason`, `result.wfirma_reservation_id`.

### Endpoints
`/api/v1/wfirma/reservation-preview/`, `/api/v1/wfirma/contractors`,
`/api/v1/wfirma/goods`, the wFirma execute endpoint inside
`submitReservation` (whichever route that is — UI-2b never reads
the function body).

### Testids
`wfirma-create-btn`, `wfirma-create-disabled-reason`,
`wfirma-skip-msg`, `wfirma-log-warn`, `wfirma-confirm-modal`,
`wfirma-confirm-submit-btn`, `customer-search-row`,
`customer-search-btn`, `product-search-row`, `product-search-btn`,
the `customer-search-${kind}` and `product-search-${kind}`
template testids.

### Operator copy
`Confirm wFirma Reservation`, `You are about to submit one
reservation to wFirma. This action calls the wFirma API and
reserves stock against this client's order.`, `Client:`,
`Document:`, `Ref:`, `Lines:`, `Total value:`, `The system will
re-run the live wFirma diagnostic before submission. If anything
has changed since the preview, the request will be blocked.`,
`Cancel`, `Confirm & Create`, `Submitting…`, `Already created`,
`Create Reservation`, `Disabled —`, `Ready to submit to wFirma`,
`Skipped: already progressed (SAD/PZ/Completed)`,
`✓ Created — wFirma ID:`, `⚠ Action completed but log write failed`,
`Search wFirma`, `Looks up the contractor in wFirma — read-only,
does not save.`, `Looks up the good in wFirma — read-only, does
not save.`.

### Forbidden markers (must stay absent)
`customers/add`, `goods/add`, `method: 'PUT'` near search,
any `alert(` near wFirma surfaces, any bare wFirma export button.

---

## 6. Design elements rejected

The matrix at `2026-05-10-operational-module-migration-matrix.md`
§6 records eight unsafe simplifications in the new design (US-1
through US-8). The wFirma-specific rejects, restated for UI-2b:

| Reject | Source in design | Why rejected |
|---|---|---|
| **Bare "Export to wFirma!" button with `alert()`** (US-2) | `pages.jsx` line ~200: `<Btn small variant="gold" onClick={() => alert('Exported to wFirma!')}>↗ Export</Btn>` | One-click alert is a no-confirmation, no-actor, no-reason write surface. Existing dashboard properly gates wFirma-create through a confirmation modal with operator-visible diagnostic re-run; UI-2b must NOT regress that. |
| **No reservation preview before create** (US-2 corollary) | The design's `WfirmaExportPage` has a "Ready for wFirma Export" table with no diagnostic preview | Existing flow always shows reservation preview + capability flags + blocking reasons before allowing create. UI-2b must NOT collapse that. |
| **Auto-create customer / product** (US-2 corollary) | Implicit in the design's master-data merging | Existing dashboard explicitly forbids `customers/add` and `goods/add`; pinned by tests. UI-2b must NOT add either. |
| **Bare write surfaces — no actor / no reason** (US-7) | Generic across the design's write buttons | Existing wFirma confirm modal binds to `createConfirm.client_name + doc` operator-context. UI-2b must NOT regress. |
| **No disabled-state messaging discipline** (US-8) | Design's wireframe pages grey out without reason | Existing dashboard always renders `Disabled — {disabledReason}` with named reason. UI-2b must NOT regress. |

UI-2b rejects all of the above by leaving the existing flows
unchanged. The CSS-only restyle does not touch a single
write-handler, button copy, or disabled-reason template.

---

## 7. Proposed UI-2b implementation scope

### Touched files

| File | Diff size |
|---|---|
| `service/app/static/dashboard.html` | ≈ 8-12 lines (4-row footer + 4-line modal chrome + 2 search-pill chrome) |
| `service/tests/test_dashboard_wfirma_chrome.py` (new) | ≈ 200 lines, 35-40 tests |

### Style value changes

| ID | Site | Change |
|---|---|---|
| W-α-1 | B-2 footer row | `marginTop: 12 → 14`, `paddingTop: 10 → 12`, `gap: 12 → 14` |
| W-β-1 | Modal description | `marginBottom: 12 → 14` |
| W-β-2 | Modal summary box | `padding: '10px 12px' → '12px 14px'`, `borderRadius: 6 → 8` |
| W-β-3 | Modal fineprint | `marginBottom: 12 → 14` |
| W-β-4 | Modal button row | `gap: 8 → 10` |
| W-γ-1 | Customer search-result pill | `padding: '6px 10px' → '8px 12px'`, `marginBottom: 12 → 14` |
| W-γ-2 | Product search-result pill | `padding: '6px 10px' → '8px 12px'`, `marginBottom: 12 → 14` |

### NOT in scope

- No JSX restructure
- No new component (no StatTile, no Modal-replacement, no Button-replacement)
- No endpoint change
- No copy change
- No testid change
- No new feature flag
- No backend touch
- No `.claude/**` edit
- No main merge / push

---

## 8. Required tests

New file: `service/tests/test_dashboard_wfirma_chrome.py`

| Class | Tests |
|---|---|
| **8.1 Chrome alignment (positive)** | 7 tests — pin each of the seven W-α/W-β/W-γ value changes |
| **8.2 Logic-variable preservation** | parametrised; ≈ 21 logic variables (above) |
| **8.3 Endpoint preservation** | parametrised; 3 wFirma endpoints |
| **8.4 Testid landmark preservation** | parametrised; 12 wFirma testids |
| **8.5 Operator copy preservation** | parametrised; ≈ 18 wFirma operator-copy strings |
| **8.6 Forbidden marker absence** | parametrised; `customers/add`, `goods/add`, `alert(`, `method: 'PUT'` near search |
| **8.7 No new component** | absence of `<StatTile`, `function StatTile`, `<WfirmaExportPage`, etc. |
| **8.8 Block fences unchanged** | `wfirma-confirm-modal`, `wfirma-create-btn`, both search-row testids still present |
| **8.9 Whole-file brace balance** | unchanged |
| **8.10 No hardcoded hex in restyled chrome** | sweep over W-α / W-β / W-γ regions for `#xxxxxx` |
| **8.11 UI-1 + UI-2a values still flow through** | sanity check of `--accent: #B89968`, `--text: #1B2538`, plus the four hoisted B-2 style consts |

Approximate total: 35-40 tests.

---

## 9. Final recommendation

```
═══════════════════════════════════════════════════════════════════
  UI-2b READINESS — wFirma partial migrate (style only)
  Date:     2026-05-10
  Baseline: 9c6a3b8
═══════════════════════════════════════════════════════════════════

  Ready to open UI-2b?                 YES — at the NARROW scope
                                        defined in §7.

  Surface mapped:
    W-α   B-2 reservation-preview footer row     ~4 lines
    W-β   B-3 confirm modal chrome               ~4 lines
    W-γ   B-4 search-result pills (cust+prod)    ~2 lines

  Total dashboard.html diff: ~8-12 lines.

  Test gate:
    43 wFirma + Run-PZ tests at HEAD             green
    1169 full dashboard suite at HEAD            green
    160 / 160 make verify at HEAD                green

  Forbidden touch (§5):
    21 logic variable names
    3 endpoint URLs (read-only wFirma)
    12 data-testid landmarks
    ~18 operator-visible copy strings
    Forbidden markers: customers/add, goods/add, alert(),
                      method:'PUT' near search

  Design rejects (§6):
    - Bare 'Export to wFirma!' button (US-2)
    - No-preview-before-create simplification (US-2 corollary)
    - Auto-create customer/product (US-2 corollary)
    - Bare write surfaces (US-7)
    - No disabled-state messaging (US-8)

  Recommended next lane:
    UI-2b — narrow chrome restyle, single commit, single test
    file, ~8-12 lines of style-value changes; ~35-40 new tests.

  Pre-conditions before UI-2b fires:
    (a) operator approves the narrow scope of §7,
    (b) operator approves the forbidden-touch list of §5,
    (c) operator approves the rejected-design-elements list of §6,
    (d) the stabilization window can absorb a CSS-only commit,
    (e) the implementation header below is acceptable.

═══════════════════════════════════════════════════════════════════
```

### Recommended UI-2b implementation header (copy-paste-ready)

```
MODE: IMPLEMENTATION (single code lane)
SCOPE: UI-2b — wFirma chrome restyle (narrow)
BASELINE COMMIT: 9c6a3b8
LANE SERIALIZATION: ENFORCED
ALLOWED:
  - service/app/static/dashboard.html
  - service/tests/test_dashboard_wfirma_chrome.py
FORBIDDEN:
  - service/app/api/**
  - service/app/services/**
  - existing dashboard JSX structure
  - data-testid values
  - operator-visible copy
  - endpoint strings
  - logic variable names
  - new components (no StatTile etc.)
  - new feature flags
  - main merge

/context
Task:
Implement UI-2b — narrow wFirma chrome restyle.

Per readiness §7, change exactly seven inline-style values
across three sub-surfaces:
  - W-α footer row (B-2): marginTop 12→14, paddingTop 10→12, gap 12→14
  - W-β confirm modal: 4 spacing/radius alignments
  - W-γ search-result pills (cust + prod): padding + marginBottom

Touch zero logic, zero copy, zero testids, zero endpoints.

Tests:
Create:
  - service/tests/test_dashboard_wfirma_chrome.py
Required tests per readiness §8:
  - 7 chrome-alignment positive tests (pin each value change)
  - 21 logic-var preservation (parametrised)
  - 3 endpoint preservation (parametrised)
  - 12 testid landmark preservation (parametrised)
  - ~18 operator-copy preservation (parametrised)
  - 4 forbidden-marker absence (parametrised)
  - no-StatTile / no-new-component absence
  - block-fence preservation
  - whole-file brace balance
  - no-hex-in-restyled-chrome
  - UI-1 + UI-2a values still flow through

Run:
cd service && python3 -m pytest \
  tests/test_dashboard_wfirma_chrome.py \
  tests/test_dashboard_pz_chrome.py \
  tests/test_dashboard_wfirma_reservation_preview_panel.py \
  tests/test_dashboard_wfirma_search.py \
  tests/test_dashboard_run_pz_gate.py \
  tests/test_dashboard_*.py \
  -q --timeout=60 -W ignore

Then:
make verify

Commit:
style(dashboard): align wFirma chrome to Estrella design tokens

Output:
Files changed:
Style values aligned:
Logic preserved (count of pinned items still present):
Tests run:
make verify result:
Commit hash:
Next legal lane:
```

---

## Self-review

What this readiness catches that wasn't in the matrix or the
UI-2a readiness:

- **The wFirma confirm modal's interior chrome is the largest
  single safe restyle target the campaign has remaining.** Four
  inline-style sites; all logic-free.
- **The B-2 footer row at line 6064 is logically separate from
  the four hoisted style consts UI-2a touched.** UI-2a aligned
  the *table* chrome inside reservation preview; the *action
  bar* footer was untouched. UI-2b closes that gap.
- **Search-result pills have `padding: '6px 10px'`** — the
  outer search-row was already restyled in UI-2a but the inner
  pill kept the old padding scale. UI-2b aligns it.

What this readiness deliberately does NOT decide:
- Whether to ever introduce a `<Modal>` component refactor
  (existing `Modal` JSX is already a primitive in dashboard.html;
  UI-2b leaves it alone).
- Whether the design's **AccountingPage > wFirma Sync sub-tab**
  ever gets adopted. That would be a navigation-paradigm shift,
  not a chrome restyle, and is firmly out of UI-2b scope.
