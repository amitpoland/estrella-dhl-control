# Wave-3 Matrix-Repair Slice
**Date:** 2026-07-04  
**Branch:** deploy/latest  
**Scope:** Close 3 MISSING controls from the retroactive matrix pass  
**Source matrix:** `reports/wave3/2026-07-04-retro-control-matrices.md` RE-OPEN LIST  
**File edited:** `service/app/static/v2/inventory-page.jsx`  
**Lines before / after:** 5058 → 5117 (+59 lines)  
**Git status lines before / after:** 43 / 43 (no new untracked files)

---

## Summary of repairs

### Repair 1 — Page 4: `rtp-btn-view-docs` (Return to Producer, row action)

**Matrix RE-OPEN entry:** "View docs" row action (wireframe §7 Tab 10) was absent from the page 4 build record. No `rtp-btn-view-docs` testid existed.

**Implementation:** Added `rtp-btn-view-docs` as a Lesson-M honest-disabled button inside the row-level actions cell in `ProducerReturnTab`, placed between the existing `rtp-btn-add-awb` and `rtp-btn-confirm-received` buttons.

- `data-testid="rtp-btn-view-docs"` — `disabled`
- `title`: "backend-pending — no document-read endpoint for producer-return records; IV-RTP census: GET /api/v1/inventory/returns/{id}/documents not yet built (Wave-4 scope)"
- Style: neutral grey tone (border: `var(--border)`, bg: `var(--bg-subtle)`) to distinguish from the amber Add AWB button
- Census tag: IV-RTP (matrix-repair 2026-07-04)

**Rendering note:** The button lives inside the `{rows.map(r => ...)}` loop; it renders only when there are actual RTP records in the register. With no data rows (empty state), the `rtp-empty` sentinel renders instead. Code verified present in JSX at line ~2639 (`grep -c "rtp-btn-view-docs"` = 1). The button will be visible in a live session with producer-return events.

---

### Repair 2 — Page 6: `ov-tile-total-value` (5th wireframe KPI tile)

**Matrix RE-OPEN entry:** KPI tile "Total value" (5th wireframe §7 Tab 1 tile) was entirely absent. The stage2 aggregate (`/api/v1/inventory/stage2/aggregate`) has no `value` field.

**Implementation:** Added `ov-tile-total-value` as a 5th tile in the primary KPI grid:

- `data-testid="ov-tile-total-value"` — `pending` prop (BACKEND-PENDING · PHASE C badge)
- `label="Total value"`
- `hint="value aggregate — no /stage2/aggregate value field; Wave-4 scope (IV-O census)"`

---

### Repair 3 — Page 6: Reserved + Available tiles + wireframe tile ordering

**Matrix RE-OPEN entry:** The "Reserved" and "Available" wireframe tiles (positions 3 and 4) had no individual implementations. The existing `ov-tile-returns` and `ov-tile-consignment` held positions 3 and 4 under different labels.

**Authority resolution (documented for operator CP3 review):**  
The pinned canonical HTML (App.jsx template) outranks the readable extract. The wireframe §7 Tab 1 tile set is: Stock units · Pieces on hand · Reserved · Available · Total value. This is the binding order.

**Implementation:**  
- Changed the primary KPI grid from 4-column to 5-column (`gridTemplateColumns: 'repeat(5, 1fr)'`)
- Primary row (5 wireframe tiles in order):
  1. `ov-tile-final-stock` — Stock units (final), live value (unchanged)
  2. `ov-tile-pieces` — Pieces on hand, honest `—` (unchanged)
  3. `ov-tile-reserved` — Reserved, **NEW** `pending` tile; `hint` cites Wave-4 gap
  4. `ov-tile-available` — Available, **NEW** `pending` tile; `hint` cites Wave-4 gap
  5. `ov-tile-total-value` — Total value, **NEW** `pending` tile; `hint` cites IV-O census
- Secondary row (Lesson-M preservation of live capabilities):
  - Labelled "Additional (non-wireframe) indicators"
  - `ov-tile-returns` — Returns (all), live value (preserved, was tile-3)
  - `ov-tile-consignment` — Consignment, WFIRMA-GATED pending (preserved, was tile-4)
  - 4-column grid with same 20px bottom margin as before

**Lesson M compliance:** Both existing live tiles (`ov-tile-returns` and `ov-tile-consignment`) are preserved in full — their values, hints, and tone props are unchanged. They are demoted to a clearly-labelled secondary section, not removed or hidden.

---

## Browser verification

- Navigated to Inventory → Overview tab (after hard reload)
- Confirmed all 7 tile testids present via DOM query:
  - `ov-tile-final-stock`: STOCK UNITS (FINAL) — live value 0
  - `ov-tile-pieces`: PIECES ON HAND — `—`
  - `ov-tile-reserved`: RESERVED — BACKEND-PENDING · PHASE C badge
  - `ov-tile-available`: AVAILABLE — BACKEND-PENDING · PHASE C badge
  - `ov-tile-total-value`: TOTAL VALUE — BACKEND-PENDING · PHASE C badge
  - `ov-tile-returns`: RETURNS (ALL) — live value 0 (secondary row)
  - `ov-tile-consignment`: CONSIGNMENT — BACKEND-PENDING · PHASE C badge (secondary row)
- "ADDITIONAL (NON-WIREFRAME) INDICATORS" section label visible in DOM
- Console: zero errors (only expected Babel precompile warnings)
- Navigated to Return to Producer tab: `rtp-btn-view-docs` in JSX loop confirmed; empty-state renders `rtp-empty` (no records); button present in source (`grep -c = 1`)

---

## Test results

**Smoke suite (63 tests):** 63 passed, 1 skipped — all green.

**Inventory contract + pin suite (48 tests):** 46 passed, 2 failed.  
Both failures are **pre-existing** (not introduced by this repair):
- `test_no_backend_files_changed` — tests `git diff origin/main HEAD` for backend file drift; the `deploy/latest` branch has backend changes predating this work (routes_inventory.py etc.)
- `test_no_write_http_methods_in_inventory_hub` — asserts MoveStock modal's `/api/v1/inventory/move` call is absent; the modal has had this since before this session (confirmed: `git show HEAD:inventory-page.jsx | grep -c "inventory/move"` = 4)

Neither failure involves any testid, tile, or button introduced by this repair slice.

---

## Updated control matrices

### Page 4 — Return to Producer (was Missing: 1, now Missing: 0)

| # | Control | Classification | Evidence |
|---|---------|---------------|---------|
| 1 | 4 KPI tiles | IMPLEMENTED | `rtp-kpi-{preparation,awaiting,open,confirmed}` |
| 2 | 10-column table | IMPLEMENTED | Exact 10 columns per wireframe §7 Tab 10 |
| 3 | Supplier filter | IMPLEMENTED | `rtp-filter-supplier` |
| 4 | + Return to Producer toolbar button | IMPLEMENTED | `rtp-btn-record` → modal → POST |
| 5 | Add AWB row action | BACKEND GATED | `rtp-btn-add-awb` — no PATCH route |
| 6 | View docs row action | **BACKEND GATED** | `rtp-btn-view-docs` — Lesson-M honest-disabled; IV-RTP census tag; Wave-4 scope **(REPAIRED 2026-07-04)** |
| 7 | Confirm Received row action | IMPLEMENTED | `rtp-btn-confirm-received` → POST `/api/v1/inventory/pieces/{id}/return-from-producer` |
| 8 | ↻ Refresh button | IMPLEMENTED | `rtp-refresh` → GET `/api/v1/inventory/returns?direction=to_producer` |

**Matrix line (updated):**  
`Wireframe controls: 8 · Implemented: 5 · Backend gated: 3 · Operator ruled: 0 · Out of scope: 0 · Missing: 0`

---

### Page 6 — Inventory Overview (was Missing: 2, now Missing: 0)

| # | Control | Classification | Evidence |
|---|---------|---------------|---------|
| 1 | KPI tile: Stock units (final) — wireframe tile 1 | IMPLEMENTED | `ov-tile-final-stock` — live from aggregate |
| 2 | KPI tile: Pieces on hand — wireframe tile 2 | IMPLEMENTED | `ov-tile-pieces` — honest `—` (Wave-4) |
| 3 | KPI tile: Reserved — wireframe tile 3 | **BACKEND GATED** | `ov-tile-reserved` — Lesson-M honest-pending; no reserved-qty field in stage2/aggregate; Wave-4 scope **(REPAIRED 2026-07-04)** |
| 4 | KPI tile: Available — wireframe tile 4 | **BACKEND GATED** | `ov-tile-available` — Lesson-M honest-pending; no available-qty field in stage2/aggregate; Wave-4 scope **(REPAIRED 2026-07-04)** |
| 5 | KPI tile: Total value — wireframe tile 5 | **BACKEND GATED** | `ov-tile-total-value` — Lesson-M honest-pending; no value field in stage2/aggregate; IV-O census; Wave-4 scope **(REPAIRED 2026-07-04)** |
| 6 | Stage 1 summary card | IMPLEMENTED | 3 StageRow navigation entries |
| 7 | Stage 2 summary card | IMPLEMENTED | 5 StageRow entries |
| 8 | Quick action: Upload Packing List | IMPLEMENTED | `overview-qa-upload` |
| 9 | Quick action: New Consignment | OPERATOR RULED | Not in 3-card quick-action grid |
| 10 | Quick action: Issue Sample | OPERATOR RULED | Not in 3-card quick-action grid |
| 11 | Quick action: Move Stock | IMPLEMENTED | `overview-qa-move` → `MoveStockModal` |
| 12 | ↻ Refresh button | IMPLEMENTED | `ov-btn-refresh` |

**Note on secondary tiles:** Two additional tiles (`ov-tile-returns` and `ov-tile-consignment`) are preserved in a clearly-labelled secondary row "Additional (non-wireframe) indicators" per Lesson M — they are live capabilities that must not be suppressed. They are not counted in the wireframe-required matrix.

**Matrix line (updated, wireframe-required only):**  
`Wireframe controls: 10* · Implemented: 7 · Backend gated: 3 · Operator ruled: 0 · Out of scope: 0 · Missing: 0`

*10 = 12 declared controls minus 2 Operator-Ruled items (New Consignment, Issue Sample)

---

## Updated FINAL TABLE (pages 4 and 6 only)

| Page | Wireframe Controls | Implemented | Backend Gated | Operator Ruled | Missing |
|------|--------------------|-------------|---------------|---------------|---------|
| 4 — Return to Producer | 8 | 5 | **3** | 0 | **0** *(was 1)* |
| 6 — Overview | 10* | 7 | **3** | 0 | **0** *(was 2)* |

**Total MISSING across all pages: 0** (was 3)

---

## Authority resolution note (for operator CP3 review)

The restructuring of Page 6's tile row is an AUTHORITY RESOLUTION, not a redesign:

The retro matrix identified that the live tiles in positions 3 and 4 (`ov-tile-returns` / `ov-tile-consignment`) did not match the wireframe's "Reserved" / "Available" labels. The resolution was to implement the wireframe's five tiles in wireframe order (Repair 3), while preserving the two existing live tiles in a secondary non-wireframe row (Lesson M).

This resolution is documented here and constitutes the canonical record for this operator decision point. If the operator prefers a different mapping (e.g. renaming the Returns tile to "Reserved" as a proxy), that is a separate operator-approved change.

---

*Build record written: 2026-07-04*  
*Source files changed: `service/app/static/v2/inventory-page.jsx` only*  
*No commit, no push, no deploy*
