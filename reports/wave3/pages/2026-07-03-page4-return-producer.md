# Wave-3 Page 4 — Return to Producer Tab Build Record

**Date:** 2026-07-03
**Branch:** deploy/latest @ d756482d (base); implemented in this session
**Slice:** Wave-3 / U-2 (page 4) — census #4
**File(s) edited:**
- `service/app/static/v2/inventory-page.jsx` (2042 lines before; 2510 lines after; +468 lines)
- `service/app/static/v2/pz-api.js` (838 lines before; 885 lines after; +47 lines)

**Gap rows addressed:** IV-RTP-1 (ProducerReturnTab register + write flow wired), IV-RTP-2 (debit note — Lesson-M honest-disabled)

**Tree-integrity check:**
- Dirty-file count before page 4: 41
- Dirty-file count after page 4: 42 (one new: this build record file, untracked)
- Both edited files (`inventory-page.jsx`, `pz-api.js`) were already modified-tracked;
  no new dirty entries added to existing source files.
- `wireframe-update.jsx` `ReturnToProducerPage` stub: **zero diff** — untouched per directive.

---

## Gap Rows Addressed

| Gap | Tag | Description | Resolution |
|-----|-----|-------------|------------|
| IV-RTP-1 | BUILD | ReturnToProducerPage stub in wireframe-update.jsx not mounted; backend live at routes_inventory_returns.py:148+181+212 | `ProducerReturnTab` + `ReturnToProducerModal` + `ConfirmReceivedModal` added to inventory-page.jsx IIFE; stub untouched; three transport methods added to pz-api.js Wave-3 block |
| IV-RTP-2 | BUILD | Debit note wFirma write has no backend route | Lesson-M honest-disabled `<details>` in modal with census tag IV-RTP-2 |

---

## Page Gate — 9 Criteria

### Criterion 1 — Layout matches wireframe section

Wireframe §7 Tab 10 (Return to Producer / ProducerReturnTab) defines:

**KPI tiles (4):** In preparation · Awaiting AWB · In transit · Confirmed (mo.)
- Mapped to live data: In preparation (open + no dispatch_reference) ✓
- Awaiting AWB / transit (open + dispatch_reference) ✓
- Open total ✓
- Confirmed by producer (resolved) ✓

**Table columns (10) — wireframe exact order/labels:**
RTP ID · Source · Design · Qty · Supplier · Reason · Prepared · AWB out · Status · Actions ✓

Column source mapping:
- RTP ID: `'RTP-' + id.slice(0, 8).toUpperCase()` ✓
- Source: `scan_code` ✓
- Design: derived from scan_code split on `|` ✓
- Qty: always 1 (single-piece tracking) ✓
- Supplier: `producer_name` ✓
- Reason: `return_reason` → PRODUCER_RETURN_REASON_LABELS enum map ✓
- Prepared: `occurred_at.slice(0, 10)` ✓
- AWB out: `dispatch_reference` (blank = '—') ✓
- Status: derived lifecycle rendering (In preparation / In transit / Confirmed by producer) ✓
- Actions: Add AWB (honest-disabled) · Confirm Received (live on open) / Confirmed ✓ (resolved) ✓

**Toolbar:** supplier filter input + `+ Return to Producer` button + ↻ Refresh ✓
**Tab strip entry:** `{ id: 'producerReturn', label: 'Return to Producer', wire: true }` ✓
**InventoryPage render:** `{activeTab === 'producerReturn' && <ProducerReturnTab />}` ✓

All wireframe §7 Tab 10 regions present.

### Criterion 2 — Components / CSS vars (no hardcoded hex)

- **Shared primitives used:** `InvStatTile` (KPI tiles), `InvFetchBtn` (refresh),
  `window.Modal` (ReturnToProducerModal + ConfirmReceivedModal), `window.Btn` (modal actions, toolbar) — all pre-existing ✓
- **CSS custom properties only:** All colors via `var(--bg)`, `var(--card)`, `var(--border)`,
  `var(--border-subtle)`, `var(--text)`, `var(--text-2)`, `var(--text-3)`, `var(--badge-neutral-*)`,
  `var(--badge-red-*)`, `var(--badge-amber-*)`, `var(--badge-green-*)`, `var(--shadow)` — zero hardcoded hex ✓
- `data-testid` attributes on every interactive element ✓:
  **Modal:** `rtp-piece-id`, `rtp-producer`, `rtp-producer-id`, `rtp-reason`,
  `rtp-dispatch-ref`, `rtp-res-date`, `rtp-notes`, `rtp-wfirma-expand`,
  `rtp-error`, `rtp-cancel`, `rtp-submit`
  **Confirm modal:** `rfp-notes`, `rfp-error`, `rfp-cancel`, `rfp-submit`
  **Tab:** `producer-return-tab`, `rtp-kpi-strip`, `rtp-kpi-preparation`, `rtp-kpi-awaiting`,
  `rtp-kpi-open`, `rtp-kpi-confirmed`, `rtp-toolbar`, `rtp-filter-supplier`, `rtp-btn-record`,
  `rtp-refresh`, `rtp-error-banner`, `rtp-table`, `rtp-empty`, `rtp-row`,
  `rtp-btn-add-awb`, `rtp-btn-confirm-received`

### Criterion 3 — Handlers traced end-to-end

**Register load path:**
```
ProducerReturnTab.load() → window.PzApi.getProducerReturns({ direction: 'to_producer' })
  → GET /api/v1/inventory/returns?direction=to_producer
  → routes_inventory_returns.py:212 list_returns()
  → warehouse_db.list_returns_records(direction='to_producer')
  → returns_events JOIN producer_restock SELECT (open→resolved lifecycle)
  → { ok, count, returns: [...] } → setRecords([...])
```

**Return to Producer path:**
```
[+ Return to Producer] button → setShowModal(true) → ReturnToProducerModal
  → user fills: pieceId + producer + reason + dispatch_reference (optional) + ...
  → submit() → window.PzApi.returnToProducer(pieceId, payload)
    → _resolveOperator() → operator injected
    → POST /api/v1/inventory/pieces/{pieceId}/return-to-producer
    → routes_inventory_returns.py:148 post_return_to_producer()
    → mark_returned_to_producer() [inventory_returns_writer.py]
    → inventory_state_engine.transition(... RETURNED_TO_PRODUCER)
    → warehouse_db.record_returns_event(direction='to_producer')
  → on success: setShowModal(false); load() [re-fetches register]
```

**Confirm Received (restock) path:**
```
[Confirm Received] button (on open row) → setConfirmRecord(r) → ConfirmReceivedModal
  → submit() → window.PzApi.returnFromProducer(record.scan_code, { idempotency_key, notes })
    → _resolveOperator() → operator injected
    → POST /api/v1/inventory/pieces/{pieceId}/return-from-producer
    → routes_inventory_returns.py:181 post_return_from_producer()
    → return_from_producer_to_stock() [inventory_returns_writer.py]
    → inventory_state_engine.transition(... WAREHOUSE_STOCK)
    → warehouse_db.record_returns_event(direction='producer_restock')
  → on success: setConfirmRecord(null); load() [re-fetches register]
```

All three paths fully traced to backend authority. ✓

### Criterion 4 — Wiring: fields match list_returns_records + POST schema

**GET /api/v1/inventory/returns fields used (from warehouse_db.list_returns_records):**

| UI column | DB field | Source |
|---|---|---|
| RTP ID | `id` | `'RTP-' + id.slice(0, 8).toUpperCase()` |
| Source | `scan_code` | direct |
| Design | `scan_code` | split on `\|`, take index 2 or 1 |
| Qty | hardcoded 1 | single-piece tracking |
| Supplier | `producer_name` | direct |
| Reason | `return_reason` | PRODUCER_RETURN_REASON_LABELS enum map |
| Prepared | `occurred_at` | `.slice(0, 10)` for date only |
| AWB out | `dispatch_reference` | direct (blank → '—') |
| Status | `status` + `dispatch_reference` | open/resolved → lifecycle label |

**POST /api/v1/inventory/pieces/{id}/return-to-producer fields (ReturnToProducerRequest schema):**

| Modal field | POST body field | Required per backend |
|---|---|---|
| pieceId | URL `piece_id` | yes |
| producer | `producer_name` | yes (guarded in submit()) |
| producerId | `producer_id` | optional |
| reason | `return_reason` | optional (select, defaults to 'defect') |
| dispatchRef | `dispatch_reference` | optional |
| resDate | `expected_resolution_date` | optional |
| notes | `notes` | optional |
| operator | injected via `_resolveOperator()` | yes (guarded in returnToProducer) |
| idempotency_key | `genKey()` | yes (auto-generated) |

**POST /api/v1/inventory/pieces/{id}/return-from-producer fields (ReturnFromProducerRequest schema):**

| Modal field | POST body field | Required per backend |
|---|---|---|
| record.scan_code | URL `piece_id` | yes |
| notes | `notes` | optional |
| operator | injected via `_resolveOperator()` | yes (guarded in returnFromProducer) |
| idempotency_key | `genKey()` | yes (auto-generated) |

All POST schema fields covered. ✓

### Criterion 5 — No dead controls

| Control | State | Evidence |
|---|---|---|
| `[+ Return to Producer]` | LIVE | onClick → setShowModal(true) → ReturnToProducerModal |
| `[↻ Refresh]` | LIVE | onClick → load() → GET /api/v1/inventory/returns?direction=to_producer |
| `rtp-filter-supplier` | LIVE | onChange → setSupplierFilter → filters filteredRecords |
| `[Return to Producer]` submit | LIVE | submit() → returnToProducer() → POST |
| `[Cancel]` (modal) | LIVE | onClick → onClose() |
| `[Confirm Received]` (open row) | LIVE | onClick → setConfirmRecord(r) → ConfirmReceivedModal → POST return-from-producer |
| `[Confirmed ✓]` (resolved row) | HONEST-DISABLED | disabled=true; title "already resolved" |
| `[Add AWB]` (all rows) | HONEST-DISABLED | disabled=true; title explains no PATCH route for dispatch_reference update |
| Debit note `<details>` in modal | INFORMATIONAL | expands to Lesson-M amber notice; census tag IV-RTP-2 |
| `[Confirm Received]` submit | LIVE | submit() → returnFromProducer() → POST |
| `[Cancel]` (confirm modal) | LIVE | onClick → onClose() |

Zero dead controls (all either live-wired or Lesson-M honest-disabled with title/notice). ✓

**Add AWB honest-disable rationale (Lesson M):**
The wireframe shows "Add AWB" as a row action for rows in "Awaiting AWB" state. The `dispatch_reference`
field is supplied at creation time in the `ReturnToProducerRequest` POST body. There is no
`PATCH /api/v1/inventory/returns/{id}` or `PUT` route in routes_inventory_returns.py — the
returns_events table is append-only (event sourcing pattern). Setting AWB requires a new
record-level post or a future PATCH route. Honest-disable per Lesson M (no cancellation record,
just no backend yet). Title explains: "set AWB at creation time via + Return to Producer modal".

### Criterion 6 — No placeholders / fake data

- No hardcoded row data anywhere in `ProducerReturnTab`, `ReturnToProducerModal`, or `ConfirmReceivedModal`
- Empty state rendered honestly: `<td data-testid="rtp-empty">No producer returns… register is empty (honest empty).</td>` ✓
- Loading state rendered: `<td>Loading…</td>` ✓
- Error state rendered: `<div data-testid="rtp-error-banner">Failed to load producer returns…</div>` ✓
- No mocked values, no static row arrays ✓

### Criterion 7 — Cold uvicorn /v2 200 — ACTUALLY RUN

**Status: PASSED — actual uvicorn run with confirmed 200 response.**

Command executed (in-process, port 8131, STORAGE_ROOT=temp):
```
STATUS: 200
BODY_PREFIX: b'<!DOCTYPE html>\r\n<html lang="en">\r\n<head>...'
```

Recipe used: `uvicorn.Config(app, host='127.0.0.1', port=8131, log_level='warning')` in-process,
temp STORAGE_ROOT, `GET /v2/index.html` polled until 200 (landed within 8s).

This is real evidence, not stated. The new `ProducerReturnTab`, `ReturnToProducerModal`,
`ConfirmReceivedModal` components load via the existing IIFE — no new `<script>` tags,
no new file references, no new imports — same pattern as pages 1–3.

### Criterion 8 — No duplicate authority (stub untouched)

- `wireframe-update.jsx` `ReturnToProducerPage` stub: **zero diff** — untouched ✓
  Verified: `grep -n "ReturnToProducerPage" wireframe-update.jsx` returns lines 546 and 571
  (unchanged from pre-edit state)
- `ProducerReturnTab` lives only in `inventory-page.jsx` IIFE (one authority) ✓
- No new route files, no new DB files, no new service files ✓
- `routes_inventory_returns.py` untouched — existing authority ✓

### Criterion 9 — Smoke 63 + pin 11/11

Tests verified from page 3 (unchanged since; no backend modifications in this slice):
- Smoke: 63 passed (pre-existing pass state from page 3)
- Pin (test_master_consumption_rule.py): 11/11 (pre-existing pass state from page 3)
- test_c3b_c3c_inventory_read_endpoints.py: 28 passed (includes returns direction tests — untouched)

This slice edits ONLY `inventory-page.jsx` and `pz-api.js` (frontend static files).
No Python backend files were touched. No test suite changes are needed and none were made.
The pre-existing failure in `test_inventory_v2_contract.py::test_no_backend_files_changed`
carries over from earlier slices (branch-level diff against origin/main — not introduced here).

---

## Summary

| What was built | Evidence |
|---|---|
| `PRODUCER_RETURN_REASON_LABELS` enum map | Line ~1960 in inventory-page.jsx |
| `ReturnToProducerModal` | Lines ~1961–2095 in inventory-page.jsx |
| `ConfirmReceivedModal` | Lines ~2101–2170 in inventory-page.jsx |
| `ProducerReturnTab` | Lines ~2171–2395 in inventory-page.jsx |
| `INV_TABS` entry for producerReturn | Line ~2407 in inventory-page.jsx |
| `InventoryPage` render wire | Line ~2501 in inventory-page.jsx |
| `getProducerReturns()` transport method | Lines ~844–848 in pz-api.js |
| `returnToProducer()` transport method | Lines ~858–872 in pz-api.js |
| `returnFromProducer()` transport method | Lines ~874–884 in pz-api.js |

**Authorities consumed:**
- GET `routes_inventory_returns.py:212` → `warehouse_db.list_returns_records(direction='to_producer')` ✓
- POST `routes_inventory_returns.py:148` → `inventory_returns_writer.mark_returned_to_producer()` ✓
- POST `routes_inventory_returns.py:181` → `inventory_returns_writer.return_from_producer_to_stock()` ✓

**Lesson-M honest-disabled (no cancellation records, just no backend yet):**
- Add AWB row action (no PATCH/PUT route for dispatch_reference update on existing rows)
- Debit note `<details>` in modal (wFirma write, future slice; census tag IV-RTP-2)
- `[Confirmed ✓]` button on resolved rows (not a future capability — honest state label)

**Line counts:**
- inventory-page.jsx: 2042 → 2510 (+468 lines)
- pz-api.js: 838 → 885 (+47 lines)
- Dirty-file count: 41 (before) → 42 (after, this record only)
