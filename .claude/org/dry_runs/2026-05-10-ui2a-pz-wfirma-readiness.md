# UI-2a Readiness — PZ / wFirma Chrome Restyle

**Mode:** PRE-IMPLEMENTATION
**Scope:** confirm exactly which PZ / wFirma visual elements can be
restyled in UI-2a without touching workflow logic. Doc-only.
**Baseline:** `6400a2c` (UI-1 closed)
**Coordinator pass:** in-context (Opus); reviewers
(UI/UX Planner, Backend Architect, Operator Safety, QA Lead,
Gap Hunter) executed as Coordinator-simulated parallel reads.

---

## 0. Pre-flight gates

| Gate | Result |
|---|---|
| `git status --short` | clean |
| Branch | `feature/dhl-label-workflow-planning` |
| PZ + wFirma focused tests (5 files) | **65 / 65** pass |
| Full dashboard suite (36 files) | 1107 / 1107 pass at `6400a2c` |
| `make verify` | 160 / 160 pass at `6400a2c` |

---

## 1. Block boundaries in `dashboard.html`

The PZ / wFirma operational surface lives across **four discrete
blocks**, each with its own block-fence anchor:

| ID | Block | Lines | Owner state | Block fence |
|---|---|---|---|---|
| **B-1** | Per-batch **PZ / wFirma** main tab | 5073 – 5845 | `activeTab === 'PZ / wFirma' && (` (line 5073) … `)}` (line 5845) | ~770 lines |
| **B-2** | Per-batch **PZ / wFirma** legacy reservation preview block | 5847 – 6343 | `activeTab === 'PZ / wFirma' && (() => {` (line 5847) … `})()}` (line 6343) | ~496 lines |
| **B-3** | **wFirma confirm modal** | 8341 – 8363 | `<div data-testid="wfirma-confirm-modal">` (line 8341) … `</div>{/* /wfirma-confirm-modal */}` (line 8363) | ~22 lines |
| **B-4** | **wFirma customer + product search rows** | 8916 – ~9050 | `<div data-testid="customer-search-row">` (line 8916), `<div data-testid="product-search-row">` (line 8976) | ~135 lines |

These four blocks together carry the per-batch PZ pipeline, the
reservation preview, the modal confirm gate, and the
customer/product search prefill controls. No other surface in
dashboard.html touches PZ / wFirma logic.

---

## 2. Tests protecting each workflow

Five test files, **65 tests total**, pin the PZ + wFirma surface.
A grep across them produced the exact substrings each one
asserts.

| Test file | Tests | Pinned substrings (sample) |
|---|---|---|
| `test_dashboard_run_pz_gate.py` | 11 | `Run PZ`, `runPzDisabled`, `!canRunPZ`, `safe_to_run_pz === true`, `sadDecisionPresent`, `SAD validation failed`, `/api/v1/upload/shipment/${...}/process`, `title=`, opacity ternary, generic-error path |
| `test_dashboard_pz_operator_header.py` | 0 (file collected; no `def test_` — header sentinel only) | (no active assertions) |
| `test_dashboard_polish_desc_delete.py` | 8 | backend-route-tests, not dashboard.html source-grep — protect the `routes_pz` Polish-description delete route. **Out of UI-2a scope.** |
| `test_dashboard_wfirma_reservation_preview_panel.py` | 15 | `wFirma` in DETAIL_TABS, `/api/v1/wfirma/reservation-preview/`, `reservationPreview` state hooks, `ready_to_create`, `blocking_reasons`, capability flags, summary counts + currency, per-document required fields, per-row required fields, stock-status badges, loading state, error state, empty-documents state, balanced-braces sanity, `wfirma` panel branch |
| `test_dashboard_wfirma_search.py` | 17 | `customer-search-btn`, `product-search-btn`, `customer-search-row`, `product-search-row`, customer/product result testids, `/api/v1/wfirma/contractors` (read), `/api/v1/wfirma/goods` (read), no `customers/add`, no `goods/add`, no `method: 'PUT'`, customer/product save still required after search, prefill via state setter, mark-matched on hit |

**Test pinning categories (cross-cutting):**

| Category | Examples | Restyle implication |
|---|---|---|
| **Logic variable names** | `canRunPZ`, `runPzDisabled`, `sadDecisionPresent`, `safe_to_run_pz`, `reservationPreview` | MUST NOT rename or move |
| **Endpoint strings** | `/api/v1/upload/shipment/${id}/process`, `/api/v1/wfirma/reservation-preview/${id}`, `/api/v1/wfirma/contractors`, `/api/v1/wfirma/goods` | MUST NOT change |
| **Forbidden markers** | `customers/add`, `goods/add`, `method: 'PUT'` | MUST stay absent |
| **Operator-visible copy** | `Run PZ`, `SAD validation failed`, `Create Reservation`, `Already created` | MUST NOT edit |
| **Testid landmarks** | `pz-already-created-banner`, `pz-document-panel`, `pz-lock-status-banner`, `pz-lock-doc-id`, `pz-lock-source`, `pz-lock-event`, `wfirma-create-btn`, `wfirma-create-disabled-reason`, `wfirma-skip-msg`, `wfirma-log-warn`, `wfirma-confirm-modal`, `wfirma-confirm-submit-btn`, `customer-search-row`, `customer-search-btn`, `product-search-row`, `product-search-btn`, plus customer/product result testids | MUST NOT rename or remove |
| **Brace balance** | `test_dashboard_html_braces_balanced` (B-2 block specifically) | Net brace balance must NOT change |

---

## 3. Forbidden logic areas (NO TOUCH under UI-2a)

The following lines / patterns are **execution-bearing logic** and
are off-limits to UI-2a. Restyle that brushes against any of these
is a logic edit, which the migration matrix forbids.

### B-1 forbidden (PZ main tab, lines 5073-5845)

| Lines (approx) | What | Why off-limits |
|---|---|---|
| 5240 – 5269 | `canRunPZ` / `runPzDisabled` / `sadDecisionPresent` / `safe_to_run_pz` calculations + Run PZ button text ternary | Pinned by 11 `test_dashboard_run_pz_gate.py` tests |
| 5253 | `fetch('/api/v1/upload/shipment/${...}/process', ...)` | Endpoint URL pinned |
| 5271 – 5360 | `pzGenerated`, refresh-mapping, `/api/v1/upload/shipment/${id}/wfirma/pz/refresh-mapping` POST | Backend contract |
| 5375 – 5430 | `pz-already-created-banner`, `pz-document-panel` | Testid landmarks |
| 5435 – 5680 | `pz-lock-status-banner` (read-only summary from `pz_preview.pz_lock_status`) — `pz-lock-doc-id`, `pz-lock-source`, `pz-lock-event`, `ls.reason === 'pz_created_by_system'`, `ls.reason === 'pz_adopted_existing'`, terminal-event branches | Cross-state messaging logic + 5 testids |
| 5400 – 5430 | "Date: …", canonical mapping check (`wfirma_pz_fullnumber`), Refresh Mapping button | wFirma mapping contract |

### B-2 forbidden (legacy reservation preview, lines 5847-6343)

| Lines (approx) | What | Why off-limits |
|---|---|---|
| 5851 – 5870 | `reservationPreview`, `rp.error`, `rp.documents`, `rp.blocking_reasons`, `rp.ready_to_create` accessors | All pinned by 15 `wfirma_reservation_preview_panel` tests |
| 5928 – 5933 | Refresh button + `loadReservationPreview` callback | Pinned |
| 6067 – 6071 | `wfirma-skip-msg`, `wfirma-log-warn` | Testid landmarks |
| 6082 – 6096 | `wfirma-create-disabled-reason`, `wfirma-create-btn` | Testid landmarks + button onClick must remain |
| 6100 – 6200 | "Already created" / "Create Reservation" branches, `createResults[d.client_name]` | Operator-visible copy + per-client state |

### B-3 forbidden (wFirma confirm modal, lines 8341-8363)

| Lines | What | Why off-limits |
|---|---|---|
| 8341 | `wfirma-confirm-modal` testid | Pinned |
| 8358 | `wfirma-confirm-submit-btn` testid + onClick | Pinned + executes wFirma `pz_create` |

### B-4 forbidden (customer/product search, lines 8916-~9050)

| Lines | What | Why off-limits |
|---|---|---|
| 8916, 8920 | `customer-search-row`, `customer-search-btn` testids | Pinned |
| 8976, 8980 | `product-search-row`, `product-search-btn` testids | Pinned |
| Anywhere | `/api/v1/wfirma/contractors`, `/api/v1/wfirma/goods` | Pinned read endpoints |
| Anywhere | `customers/add`, `goods/add` | Forbidden-marker tests; absence pinned |
| Anywhere | `method: 'PUT'` near search handlers | Forbidden |

---

## 4. Safe styling-only targets

After excluding all the above, the **actually-restyleable surface
under UI-2a is small.** Concretely:

### S-1 (B-1) — PZ main-tab cosmetic chrome only

| Style property | Current pattern | Safe to align with design? |
|---|---|---|
| Card-container `padding` (e.g., `padding: '14px 18px'`) | inline objects | yes — values only |
| Card-container `borderRadius` | mostly `4`, `6`, `8` | yes — pick one design value |
| Section-header typography (`fontSize`, `fontWeight`, `letterSpacing`, `textTransform`) on row labels like "PZ Document", "PZ Lock Status" | varies | yes — but no copy / testid touch |
| Badge `fontSize` / `padding` | varies | yes |
| `marginBottom` between cards | `8`, `10`, `12`, `16` | yes |

### S-2 (B-2) — legacy reservation preview cosmetic chrome only

| Style property | Current pattern | Safe? |
|---|---|---|
| `sectionStyle` const at line 5867 (`{ padding: 14, marginBottom: 12 }`) | hoisted | **yes — single point of change** |
| `tblStyle` const at line 5868 (`{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }`) | hoisted | **yes — single point of change** |
| `thStyle` / `tdStyle` typography + spacing | hoisted | **yes — single point of change** |

The hoisted `sectionStyle`, `tblStyle`, `thStyle`, `tdStyle`
constants in B-2 are the **highest-leverage safe restyle** of the
entire surface — change four objects, restyle the whole reservation
preview card without touching any logic.

### S-3 (B-3) — modal cosmetic chrome only

The modal is already minimal. Safe targets: backdrop opacity,
modal border-radius, modal max-width, button group spacing. Logic
is in the submit handler — out of scope.

### S-4 (B-4) — search-row cosmetic chrome only

`<div data-testid="customer-search-row" style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>` — gap + marginBottom values are safe to align. The buttons themselves use the existing `<Btn>` primitive (already token-driven via UI-1).

### S-5 — cross-cutting via existing CSS variables

UI-1 already swung the brand palette. Anything that already says
`var(--accent)` / `var(--text-*)` / `var(--badge-*-*)` automatically
inherited the design's values. UI-2a does NOT need to re-touch
these references. **Net effect:** if a card's coloring already
goes through CSS variables, UI-2a may add nothing for that card.

---

## 5. Recommended UI-2a scope (narrow)

Given the test pinning density, the **safe and recommended UI-2a
scope is narrower than the original migration matrix entry**. The
original matrix said "restyle StatTile + table chrome." The
existing dashboard does NOT use a `StatTile` component on the
PZ / wFirma surface — it uses inline `<div>` blocks. Adopting a
new `StatTile` JSX component would be a refactor, NOT a CSS
restyle, and is forbidden under UI-2a.

**Refined UI-2a scope (recommended):**

| Touch | Files | Approx diff |
|---|---|---|
| **Pivot the four hoisted style constants in B-2** (`sectionStyle`, `tblStyle`, `thStyle`, `tdStyle`) to use design's spacing / typography conventions | `dashboard.html` | ~15 lines |
| **Align padding / border-radius / margin values** in B-1 card containers to design conventions (no new tokens; just pick the design's `14px 18px` / `12px 16px` / `8px 14px` patterns where applicable) | `dashboard.html` | ~30-50 lines |
| **Touch zero logic, zero strings, zero testids** | n/a | 0 |
| **New tests** | `service/tests/test_dashboard_pz_chrome.py` | new file, ~25 tests |

The new test file pins:
1. The four hoisted style consts in B-2 still exist (by name).
2. Their values match the design's chosen spacing/typography.
3. Every UI-2a-protected logic variable / endpoint / forbidden
   marker / testid / copy still appears in dashboard.html
   (parametrised against the §3 forbidden list).
4. Brace balance unchanged (B-2 already has this gate).
5. Existing 65 PZ + wFirma tests must remain green at HEAD.

**Do NOT under UI-2a:**
- Add a new `StatTile` component or refactor any existing inline div into one.
- Add or rename any data-testid.
- Change any operator-visible copy ("Run PZ", "SAD validation failed", "Already created", "Create Reservation", etc.).
- Change any endpoint string.
- Move JSX between blocks.
- Replace inline styles with CSS classes (that's a separate refactor phase if ever justified).
- Touch the wFirma confirm modal's submit handler, the wFirma create button's onClick, or the search row's prefill logic.

---

## 6. Implementation command for UI-2a

Once the operator approves this readiness check, the next session
should open with this exact header:

```
MODE: IMPLEMENTATION (single code lane)
SCOPE: UI-2a — PZ / wFirma chrome restyle (narrow)
BASELINE COMMIT: 6400a2c
LANE SERIALIZATION: ENFORCED
ALLOWED:
  - service/app/static/dashboard.html
  - service/tests/test_dashboard_pz_chrome.py
FORBIDDEN:
  - service/app/api/**
  - service/app/services/**
  - existing dashboard JSX structure
  - data-testid values
  - operator-visible copy
  - endpoint strings
  - logic variable names (canRunPZ, runPzDisabled, sadDecisionPresent,
    safe_to_run_pz, reservationPreview, etc. — see readiness §3)
  - new components (no StatTile etc.)
  - new feature flags
  - main merge

/context
Task:
Implement UI-2a — narrow PZ / wFirma chrome restyle.

Refined scope (per 2026-05-10-ui2a-pz-wfirma-readiness.md §5):
  - Pivot the four hoisted style consts in B-2:
      sectionStyle, tblStyle, thStyle, tdStyle
    (lines ~5867-5870 of dashboard.html) to design's spacing
    and typography conventions.
  - Align card container padding / border-radius / margin
    values in B-1 (~lines 5073-5845) to design conventions.
  - Touch zero logic, zero strings, zero testids.

Tests:
Create:
  - service/tests/test_dashboard_pz_chrome.py
Required tests:
  1. Hoisted style consts in B-2 still exist by name.
  2. Their values match the design's spacing/typography.
  3. Every readiness §3 forbidden-touch item still appears
     unchanged in dashboard.html.
  4. Brace balance unchanged.
  5. Existing 65 PZ + wFirma tests remain green.

Run:
cd service && python3 -m pytest \
  tests/test_dashboard_pz_chrome.py \
  tests/test_dashboard_pz_operator_header.py \
  tests/test_dashboard_run_pz_gate.py \
  tests/test_dashboard_polish_desc_delete.py \
  tests/test_dashboard_wfirma_reservation_preview_panel.py \
  tests/test_dashboard_wfirma_search.py \
  tests/test_dashboard_*.py \
  -q --timeout=60 -W ignore

Then:
cd service && python3 -m pytest tests/test_carrier_*.py tests/test_dhl_*.py -q --timeout=60 -W ignore

Then:
make verify

Commit:
style(dashboard): align PZ / wFirma chrome to Estrella design tokens

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

## 7. Final recommendation

```
═══════════════════════════════════════════════════════════════════
  UI-2a READINESS — PZ / wFirma chrome restyle
  Date:     2026-05-10
  Baseline: 6400a2c
═══════════════════════════════════════════════════════════════════

  Ready to open UI-2a?                 YES — at the NARROW scope
                                        defined in §5.

  Open the original wider scope?        NO — adopting StatTile or
                                        moving JSX is not "chrome
                                        restyle"; it's a refactor.

  Surface mapped:
    B-1   PZ main tab               lines 5073 – 5845  (~770 lines)
    B-2   reservation preview       lines 5847 – 6343  (~496 lines)
    B-3   wFirma confirm modal      lines 8341 – 8363  (~22 lines)
    B-4   customer/product search   lines 8916 – ~9050 (~135 lines)

  Test gate:
    65 PZ + wFirma tests at HEAD            green
    1107 full dashboard suite at HEAD       green
    160 / 160 make verify at HEAD           green

  Forbidden touch (§3):
    18 logic variable names / endpoint URLs / forbidden markers
    16 operator-visible copy strings
    16 data-testid landmarks
    Plus brace-balance invariant.

  Safe restyle targets (§4):
    4 hoisted style consts in B-2 (single highest-leverage point)
    Card-container padding / radius / margin in B-1
    Search-row gap + marginBottom in B-4
    Modal cosmetic chrome in B-3

  Recommended next lane:
    UI-2a — narrow chrome restyle, single commit, single test
    file, ~30-50 lines of style-value changes.

  Pre-conditions before UI-2a fires:
    (a) operator approves the narrow scope of §5,
    (b) operator approves the forbidden-touch list of §3,
    (c) operator approves the implementation header in §6,
    (d) stabilization-window posture allows a CSS-only commit.

═══════════════════════════════════════════════════════════════════
```

## Self-review

- **What this readiness catches:** the migration-matrix recommendation said "restyle StatTile + table chrome" — but the existing dashboard does not use a StatTile component on PZ / wFirma. Adopting one would be a refactor, not a chrome restyle. This artifact narrows the scope to the actually-safe surface.
- **The four hoisted style consts in B-2** are the highest-leverage restyle target: change four objects, restyle the entire reservation-preview card without touching any logic.
- **What this artifact deliberately does NOT decide:** whether to ever introduce a `StatTile` JSX component on the PZ surface. That decision belongs to a future PRE-IMPLEMENTATION campaign opened only after sandbox-shadow operational evidence per the stabilization-window posture.
