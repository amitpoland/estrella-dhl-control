# Wave-3 Page 1 — Sample Out Tab Build Record

**Date:** 2026-07-03  
**Branch:** deploy/latest  
**Slice:** Wave-3 / U-1  
**File(s) edited:**
- `service/app/static/v2/inventory-page.jsx` (lines 815–1416 after edit; was 1058 lines, now 1416)
- `service/app/static/v2/pz-api.js` (lines 771–792 added; was 765 lines, now 792)

**Gap rows addressed:** IV-SO-1, IV-SO-2, IV-SO-3, IV-SO-4

**Tree-integrity check:** `git diff --name-only` — pre-existing operator-dirty files
(`config.py`, `main.py`, `vision_extractor.py`, `components.jsx`, `index.html`,
`mock-badge.jsx`) are unchanged by this slice. Only `inventory-page.jsx` and `pz-api.js`
added to the diff. `wireframe-update.jsx` has zero diff (stub left in place per directive —
removal is a REMOVE-tagged later slice). Dirty-file count before: 41. Modified-tracked
count before: 6. Modified-tracked count after: 8 (6 pre-existing + 2 this slice).

---

## Gap Rows Addressed

| Gap | Tag | Description | Resolution |
|-----|-----|-------------|------------|
| IV-SO-1 | BUILD | SampleOutPage stub in wireframe-update.jsx not mounted; fictional endpoints | `SampleOutTab` added to `inventory-page.jsx` IIFE; stub left untouched per directive |
| IV-SO-2 | BUILD | 4 KPI tiles absent from stub | KPI strip (4 tiles: Active out / Closing soon / Overdue / Returned) derived from live API response |
| IV-SO-3 | BUILD | 10-col table + status filter + recipient filter absent | 10-column table exactly per wireframe §7 Tab 7; status and recipient filter controls added |
| IV-SO-4 | BUILD | "+ Issue Sample" toolbar button absent | Button wired to `IssueSampleModal` → POST `/api/v1/inventory/pieces/{id}/sample-out` |

---

## Page Gate — 9 Criteria

### Criterion 1 — Layout matches wireframe section

Wireframe §7 Tab 7 defines:
- KPI strip (4 tiles): Active out · Closing soon (≤3 days) · Overdue · Returned (mo.) ✓ — `InvStatTile` ×4 in grid, `data-testid` so-kpi-{active,closing,overdue,returned}
- Table: 10 columns (Sample ID · Source SU · Design · Qty · Issued to · Purpose · Issued · Return by · Days left (colored) · Status · Actions) ✓ — exact column order, `<th>` labels verbatim
- Status filter (open/returned) ✓ — `<select data-testid="so-filter-status">`
- Recipient filter ✓ — `<input data-testid="so-filter-recipient">`
- "+ Issue Sample" toolbar button ✓ — `<button data-testid="btn-issue-sample">`
- Row actions: Record Return (if out/overdue) · View ✓ — rendered per row; both disabled with `title` = backend-pending reason (Lesson M honest-disabled, see Criterion 5)
- Tab strip entry ✓ — `InvTabStrip` with `sampleOut` tab

All 7 wireframe §7 Tab 7 regions are present.

### Criterion 2 — Components match (shared primitives, CSS vars)

- **Shared primitives used (IIFE-private atoms):** `InvStatTile` (KPI tiles), `InvFetchBtn` (refresh button), `window.Modal` (Issue modal), `window.Btn` (modal actions) — all pre-existing in the IIFE or components.jsx
- **CSS custom properties only:** All colors use `var(--bg)`, `var(--card)`, `var(--border)`, `var(--border-subtle)`, `var(--text)`, `var(--text-2)`, `var(--text-3)`, `var(--accent)`, `var(--accent-text)`, `var(--badge-amber-*)`, `var(--badge-red-*)`, `var(--badge-green-*)`, `var(--badge-neutral-*)` — zero hardcoded hex
- **No TypeScript, no Tailwind, no bundler** — plain JSX inside IIFE per CLAUDE.md frontend rules
- `data-testid` on every interactive element (verified below)

### Criterion 3 — Buttons work (handler → endpoint)

| Button | data-testid | Handler | Endpoint |
|--------|-------------|---------|----------|
| + Issue Sample | `btn-issue-sample` | `() => setShowIssue(true)` → opens `IssueSampleModal` | — |
| Issue Sample Out (modal submit) | `so-submit-issue` | `submit()` → `window.PzApi.issueSampleOut(pieceId, payload)` | POST `/api/v1/inventory/pieces/{piece_id}/sample-out` (`routes_inventory_sample.py:91`) |
| Cancel (modal) | `so-cancel` | `onClose()` | — |
| ↻ Refresh | `so-refresh` | `load()` | GET `/api/v1/inventory/samples` (`routes_inventory_sample.py:149`) |
| Record Return (row, disabled) | `so-btn-record-return` | `disabled` + `title="backend-pending — Sample Return tab (Wave-3 U-1 slice 2)"` | n/a — Lesson M honest-disabled |
| View (row, disabled) | `so-btn-view` | `disabled` + `title="backend-pending — detail view (future slice)"` | n/a — Lesson M honest-disabled |

### Criterion 4 — API wiring correct

**GET `/api/v1/inventory/samples`**
- Backend: `routes_inventory_sample.py:149–191` (LIVE, Wave-2 backend)
- Wrapper: `pz-api.js:771` `getInventorySamples(params)` — `_get(${BASE}/inventory/samples${qs})`
- Response fields consumed:
  - `data.samples[]` → table rows
  - `s.sample_id` → Sample ID column
  - `s.scan_code` → Source SU column
  - `s.sample_reason` → Purpose column (mapped via `SAMPLE_REASON_LABELS`)
  - `s.expected_return_date` → Return by + DaysLeftChip
  - `s.out_at` → Issued date
  - `s.recipient_client_name` → Issued to column
  - `s.status` (`'open'|'returned'`) → SampleStatusChip + DaysLeftChip logic + KPI derivation

**POST `/api/v1/inventory/pieces/{piece_id}/sample-out`**
- Backend: `routes_inventory_sample.py:91–122` (LIVE)
- Request schema (`SampleOutRequest`, `routes_inventory_sample.py:40–64`):
  - `operator` ✓ — resolved via `_resolveOperator()` in `pz-api.js:issueSampleOut`
  - `recipient_client_name` ✓ — from modal field
  - `recipient_client_id` ✓ — empty string (optional per schema)
  - `expected_return_date` ✓ — date input ISO 8601
  - `sample_reason` ✓ — select from enum {customer_review, quality_check, marketing_photo, trade_show, other}
  - `idempotency_key` ✓ — generated as `'so-' + Date.now() + '-' + random`
  - `notes` ✓ — optional textarea
- Wrapper: `pz-api.js:781` `issueSampleOut(pieceId, payload)`

### Criterion 5 — No dead controls

| Control | State | Reason |
|---------|-------|--------|
| Record Return (row action, if out/overdue) | `disabled` + `title` text | Sample Return tab is a separate Wave-3 slice (U-1 slice 2); the per-piece `POST /api/v1/inventory/pieces/{id}/sample-return` route exists but the tab that drives it is not yet built — honest-disabled per Lesson M |
| View (row action) | `disabled` + `title` text | Detail view is a future slice; no detail endpoint exists — honest-disabled per Lesson M |
| Tab strip "Hub (overview)" | live — switches to hub panels | PANELS badge makes its nature visible |
| Tab strip "Sample Out" | live — renders SampleOutTab | — |

No silent dead controls. Every disabled button carries a `title` explaining why and naming the blocking reason (Lesson M §5-state: `planned`/`backend-pending`).

### Criterion 6 — No placeholder content

Grep of diff for hardcoded data arrays:
- `const INV_TABS = [...]` — tab configuration (IDs + labels), NOT data rows ✓
- `const SAMPLE_REASON_LABELS = {...}` — enum→display-label map, NOT fixture data ✓
- `MAP[status]` inside `SampleStatusChip` and `DaysLeftChip` — style maps, NOT data ✓
- No `'SMP-XXXX'`, `'Aurum Trading'`, `'EJ-D-XXXXX'` fixture strings in diff ✓

All table rows are derived from `res.data.samples` (live API). Honest empty state renders when `samples.length === 0`.

### Criterion 7 — Console error check

**Babel JSX compile check:**
```
node_modules/.bin/babel service/app/static/v2/inventory-page.jsx --presets @babel/preset-react --out-file NUL
→ (no output = no errors)

node_modules/.bin/babel service/app/static/v2/pz-api.js --presets @babel/preset-react --out-file NUL
→ (no output = no errors)
```

**Cold uvicorn boot:**
```
GET http://localhost:8125/v2/index.html → HTTP 200
No 'error' or 'Error' lines in stderr
```

### Criterion 8 — No duplicate authority

- `SampleOutTab`, `IssueSampleModal`, `DaysLeftChip`, `SampleStatusChip`, `INV_TABS`, `InvTabStrip` — all IIFE-scoped private functions, NOT exported to `window.*`
- Single window export from `inventory-page.jsx`: `window.InventoryPage` (line 1413) — unchanged, same single export
- `SampleOutPage` stub in `wireframe-update.jsx:492–507` — untouched; `git diff` confirms zero change to that file
- No `window.SampleOutPage` or `window.SampleOutTab` exists anywhere in the v2 static directory (confirmed via `Select-String`)
- No routing collision: `sample_out` slug remains redirected → `inventory` (index.html ROUTE_REDIRECTS, unchanged)

### Criterion 9 — Smoke + master consumption

```
cd service && PYTHONUTF8=1 python -m pytest tests -m smoke -q
→ 63 passed, 1 skipped, 18852 deselected — PASS

cd service && python -m pytest tests/test_master_consumption_rule.py -v
→ 11 passed — PASS
```

---

## Files Touched with Line Ranges

| File | Before | After | Changed region |
|------|--------|-------|----------------|
| `service/app/static/v2/inventory-page.jsx` | 1058 lines | 1416 lines | Lines 815–1416 (new components + revised InventoryPage) |
| `service/app/static/v2/pz-api.js` | 765 lines | 792 lines | Lines 764–791 (two new inventory/sample methods) |
| `service/app/static/v2/wireframe-update.jsx` | unchanged | unchanged | SampleOutPage stub at lines 492–507: zero diff |
