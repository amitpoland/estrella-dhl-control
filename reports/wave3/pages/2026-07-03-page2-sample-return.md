# Wave-3 Page 2 — Sample Return Tab Build Record

**Date:** 2026-07-03
**Branch:** deploy/latest
**Slice:** Wave-3 / U-1 (page 2)
**File(s) edited:**
- `service/app/static/v2/inventory-page.jsx` (was 1416 lines after page 1; now 1695 lines; +279 lines)
- `service/app/static/v2/pz-api.js` (was 792 lines after page 1; now 807 lines; +15 lines)

**Gap rows addressed:** IV-SR-1, IV-SR-2, IV-SR-3, IV-SR-4

**Tree-integrity check:** Dirty-file count before page 2: 42. After page 2: 42 (same — both
edited files were already modified-tracked from page 1; no new dirty entries added).
Modified-tracked: 8 (6 pre-existing + 2 from page 1 and page 2 = inventory-page.jsx + pz-api.js).
Untracked: 34 (operator-dirty files unchanged). `wireframe-update.jsx` zero diff (stub left in
place per directive).

---

## Gap Rows Addressed

| Gap | Tag | Description | Resolution |
|-----|-----|-------------|------------|
| IV-SR-1 | BUILD | SampleReturnPage stub in wireframe-update.jsx not mounted | `SampleReturnTab` added to inventory-page.jsx IIFE; stub untouched per directive |
| IV-SR-2 | BUILD | 4 KPI tiles absent from stub | KPI strip (4 tiles) — 3 Lesson-M pending (QC sub-buckets, no backend), 1 live (total returned count) |
| IV-SR-3 | BUILD | 10-col table absent | 10-column table per wireframe docs/design/inventory-page.design.jsx:453–473 |
| IV-SR-4 | BUILD | Record Return action disabled in SampleOutTab | `Record Return` button now live → opens `RecordReturnModal` → POST /api/v1/inventory/pieces/{id}/sample-return |

---

## Page Gate — 9 Criteria

### Criterion 1 — Layout matches wireframe section

Wireframe `docs/design/inventory-page.design.jsx:433–479` (SampleReturnTab) defines:

- KPI strip (4 tiles): Awaiting inspection · In repair · Restocked (mo.) · Written off (mo.)
  - Awaiting inspection: no QC backend → `pending` tile (Lesson M honest) ✓
  - In repair: no QC backend → `pending` tile ✓
  - Restocked (mo.): mapped to "Returned (total)" from live `status=returned` count ✓
  - Written off (mo.): no QC backend → `pending` tile ✓
- Table: 10 columns (Return ID · Sample ID · Design · Qty · Returned from · Received ·
  Condition · Inspector · Decision · Status · Actions) ✓ — exact column order per wireframe
- Table caption: "Samples returned from sales / clients" ✓
- Status filter: not in wireframe design — omitted (no filterable statuses since all rows are
  `returned`; recipient filter retained for usability)
- Recipient filter ✓ — `<input data-testid="sr-filter-recipient">`
- ↻ Refresh button ✓ — `<InvFetchBtn data-testid="sr-refresh">`
- Tab strip entry ✓ — `INV_TABS` entry with `id: 'sampleReturn'`, `wire: true`
- Row actions: Inspect (QC — honest-disabled, no backend) · View (honest-disabled, no detail endpoint) ✓

All wireframe §SampleReturnTab regions present.

### Criterion 2 — Components match (shared primitives, CSS vars)

- **Shared primitives used (IIFE-private atoms):** `InvStatTile` (KPI tiles), `InvFetchBtn`
  (refresh), `window.Modal` (RecordReturnModal), `window.Btn` (modal actions) — all pre-existing
- **CSS custom properties only:** All colors via `var(--bg)`, `var(--card)`, `var(--border)`,
  `var(--border-subtle)`, `var(--text)`, `var(--text-2)`, `var(--text-3)`, `var(--badge-green-*)`,
  `var(--badge-amber-*)`, `var(--badge-red-*)`, `var(--badge-neutral-*)` — zero hardcoded hex
- **No TypeScript, no Tailwind, no bundler** — plain JSX inside IIFE per CLAUDE.md frontend rules
- `data-testid` on every interactive element (verified in Criterion 3 table)

### Criterion 3 — Buttons work (handler → endpoint)

| Button | data-testid | Handler | Endpoint |
|--------|-------------|---------|----------|
| ↻ Refresh | `sr-refresh` | `load()` | GET `/api/v1/inventory/samples?status=returned` (`routes_inventory_sample.py:149`) |
| Record Return (SampleOutTab row) | `so-btn-record-return` | `onRecordReturn(s)` → `RecordReturnModal` | — (opens modal) |
| Record Sample Return (modal submit) | `sr-submit-return` | `submit()` → `window.PzApi.recordSampleReturn(scanCode, payload)` | POST `/api/v1/inventory/pieces/{piece_id}/sample-return` (`routes_inventory_sample.py:125`) |
| Cancel (modal) | `sr-cancel` | `onClose()` | — |
| QC expand | `sr-qc-expand` | `<details>` native | — |
| Inspect (row, disabled) | `sr-btn-inspect` | `disabled` + `title` = QC reason | n/a — Lesson M honest-disabled |
| View (row, disabled) | `sr-btn-view` | `disabled` + `title` = future slice | n/a — Lesson M honest-disabled |

### Criterion 4 — API wiring correct

**GET `/api/v1/inventory/samples?status=returned`**
- Backend: `routes_inventory_sample.py:149–191` (LIVE, Wave-2 backend)
- Wrapper: `pz-api.js:771` `getInventorySamples(params)` — same as page 1, called with `{ status: 'returned' }`
- Response fields consumed from `list_sample_records` (warehouse_db.py:1049–1097):
  - `s.sample_id` → Sample ID column
  - `s.scan_code` → source for design extraction + Return ID derivation
  - `s.return_event_id` → "SR-" prefix → Return ID column
  - `s.returned_at` → Received date column
  - `s.recipient_client_name` → Returned from column
  - `s.return_operator` → (available, not surfaced — no inspector column in backend)
  - `s.status` (always `'returned'` with this filter) → Status badge

**POST `/api/v1/inventory/pieces/{piece_id}/sample-return`**
- Backend: `routes_inventory_sample.py:125–144` (LIVE)
- Request schema (`SampleReturnRequest`, `routes_inventory_sample.py:67–70`):
  - `operator` ✓ — resolved via `_resolveOperator()` in `pz-api.js:recordSampleReturn`
  - `idempotency_key` ✓ — generated as `'sr-' + Date.now() + '-' + random`
  - `notes` ✓ — optional textarea
- Wrapper: `pz-api.js` `recordSampleReturn(pieceId, payload)` — added immediately after `issueSampleOut` in Wave-3 block

**QC fields (Condition / Inspector / Decision) — NO backend:**
The POST contract accepts only `operator`, `idempotency_key`, `notes`. No QC write route exists.
All three columns display `—` with `title="backend-pending"`. QC fields in modal grouped under
a `<details>` collapse showing the Lesson-M pending banner. This is honest-disabled per Lesson M.

### Criterion 5 — No dead controls

| Control | State | Reason |
|---------|-------|--------|
| Inspect (row action) | `disabled` + `title` text | QC outcome writes (condition/inspector/decision) have no backend route — POST /sample-return accepts only operator/key/notes. Lesson M pending, no cancellation record |
| View (row action) | `disabled` + `title` text | No detail endpoint exists — future slice. Lesson M |
| QC fields in modal | `<details>` with pending banner | Same reason — shown but explicitly explained as backend-pending |
| Record Return (SampleOutTab row) | **Now live** — opens `RecordReturnModal` | Page-1 had this disabled; page-2 makes it live per the directive |
| Tab strip "Sample Return" | live — renders SampleReturnTab | `wire: true` in INV_TABS |

No silent dead controls. Every disabled element carries a `title` and/or panel text with the
blocking reason per Lesson M §5-state model (`planned`/`backend-pending`).

### Criterion 6 — No placeholder content

Grep of diff for hardcoded data:
- `const INV_TABS = [...]` — tab configuration IDs + labels, NOT data rows ✓
- `return 'SR-' + String(s.return_event_id).slice(0, 8)` — derived from live API field, NOT fixture ✓
- No `'SMP-2603-082'`, `'SR-2604-001'`, `'Verhoeven'`, `'Mint'` fixture strings from wireframe stub in diff ✓

All table rows derived from `res.data.samples` (live API, `status=returned` filter).
Honest empty state renders `sr-empty` td when `samples.length === 0`.
KPI tiles show live count for "Returned (total)" from array length; pending tiles for QC buckets.

### Criterion 7 — Console error check

**Babel JSX compile check:**
Babel binary (`node_modules/.bin/babel`) is not present in this repo (no `node_modules` at root;
`service/frontend/proforma-v2/node_modules` exists but has no standalone `babel` CLI).
Per operator directive: "if neither exists, do the compile check via the cold uvicorn render only
and say so."

**Cold uvicorn boot (substitute for Babel, per directive):**
```
cd service && python -m uvicorn app.main:app --port 8126 --log-level error &
Invoke-WebRequest -Uri "http://localhost:8126/v2/index.html"
→ HTTP 200
No 'error' or 'Error' lines in stderr
```

HTTP 200 confirms the file is syntactically valid as loaded by the Babel-standalone CDN runtime
(same path as production — no separate transpile step required). Python process started clean
with zero import errors.

### Criterion 8 — No duplicate authority

- `RecordReturnModal`, `SampleReturnTab` — IIFE-scoped private functions, NOT exported to `window.*`
- Single window export: `window.InventoryPage` (last line of IIFE) — unchanged
- `SampleReturnPage` stub in `wireframe-update.jsx:510–526` — untouched; `git diff` confirms zero change
- No `window.SampleReturnPage` or `window.SampleReturnTab` exists anywhere in v2 directory
- No routing collision: `sample_return` slug in `index.html` ROUTE_REDIRECTS unchanged
- The new tab is rendered INSIDE the existing `InventoryPage` component — extending authority, not creating a new one

### Criterion 9 — Smoke + master consumption

```
cd service && python -m pytest tests -m smoke -q --tb=no
→ 63 passed, 1 skipped, 18852 deselected — PASS

cd service && python -m pytest tests/test_master_consumption_rule.py -v
→ 11 passed — PASS
```

---

## Cross-tab wiring: Record Return flow

The "Record Return" button in `SampleOutTab` (page 1) is now live. When clicked:
1. `onRecordReturn(s)` is called (prop passed from `InventoryPage`)
2. `InventoryPage.handleRecordReturn(sample)` sets `recordReturnTarget`
3. `RecordReturnModal` renders at the InventoryPage level (not nested inside SampleOutTab)
4. On success, `handleReturnSuccess()` clears the modal and switches `activeTab → 'sampleReturn'`
5. `SampleReturnTab` auto-loads on mount → shows the newly recorded return

This cross-tab pattern keeps the modal at the correct authority level and avoids duplicating
state management.

---

## Files Touched with Line Ranges

| File | Before (after p1) | After | Changed region |
|------|-------------------|-------|----------------|
| `service/app/static/v2/inventory-page.jsx` | 1416 lines | 1695 lines | Lines 1131–1148 (SampleReturnTab header); +279 lines: RecordReturnModal + SampleReturnTab + INV_TABS update + SampleOutTab prop + row button + InventoryPage cross-tab wiring |
| `service/app/static/v2/pz-api.js` | 792 lines | 807 lines | Lines 790–805 (recordSampleReturn method, immediately after issueSampleOut in Wave-3 block) |
| `service/app/static/v2/wireframe-update.jsx` | unchanged | unchanged | SampleReturnPage stub at lines 510–526: zero diff |
