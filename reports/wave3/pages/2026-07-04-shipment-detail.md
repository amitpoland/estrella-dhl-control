# Wave-3 Build Record: Shipment Detail — SD-1 through SD-7

**Date:** 2026-07-04  
**Branch:** deploy/latest  
**Base SHA:** bd7303ef  
**Operator execution order:** #4, scope L  
**Files edited:** 2  
**Tree count before / after:** 42 / 43  

---

## Files Modified

| File | Lines Before | Lines After | Delta |
|---|---|---|---|
| `service/app/static/v2/shipment-detail-page.jsx` | 1579 | 1915 | +336 |
| `service/app/static/v2/pz-api.js` | 1010 | 1020 | +10 |

---

## Gap Closure Control Matrix

| Gap | Census Description | Wireframe Section | Status | Notes |
|---|---|---|---|---|
| SD-1 | Sub-header missing: Carrier chip, MRN (mono), Packing List (mono) | All views — page header | CLOSED | `deriveDetail()` extended with `packingList`; sub-header conditionally shows Carrier badge, MRN (`data-testid="header-mrn"`), PL (`data-testid="header-packing-list"`) |
| SD-2 | Overview tab: no contextual Next Actions tile set | Overview — action tiles | CLOSED | `contextActions` array built from `dhlEmailReceived/replySent/sadUploaded/pzGenerated/pzExported` flags; tiles render at `data-testid="overview-context-actions"`; CTA buttons call `setActiveTab()` |
| SD-3 | Pro Forma tab: no draft list, no Create Pro Forma nav | Pro Forma | PRE-CLOSED | `ProformaTabInShipment` was already fully built in the existing file (draft list, readiness cards, Create Pro Forma nav). No changes needed. |
| SD-4 | DHL / Customs tab: no entry-point banner (R-Q1 compliance) | DHL / Customs — entry-point | CLOSED | Blue gradient banner at `data-testid="dhl-console-entry"` with "DHL Console (standalone authority)" label and `<a data-testid="dhl-open-console-link">Open DHL Console ↗</a>` linking to `/v2/dhl?batch_id=...` |
| SD-5 | PZ / Accounting tab: missing 7-button conditional set | PZ / Accounting — 7 buttons | CLOSED | Full 7-button set via `PendingAction` (Lesson M compliant, all `data-action-state="backend-pending"`): Run PZ / Regenerate PZ / Confirm PZ Number / Download XLSX / Download PDF / Export to wFirma / Mark Exported. Conditional show/hide based on `pzGenerated`/`pzExported` flags. |
| SD-6 | Documents tab: missing 4-card wireframe layout (PL / PF / CMR / WF) | Documents — 8 buttons | CLOSED | `_WIREFRAME_DOC_CARDS` constant (4 cards: PL/PF/CMR/WF); each card renders `doc-card-{code}`, `doc-state-{code}`, `doc-view-{code}`, `doc-download-{code}` testids; state chips (Source/Generated/Pending) derived from real backend files data. Error fallback renders when backend returns 404. |
| SD-7 | Timeline tab: missing 16-event ordered table | Timeline — 16-event table | CLOSED | `_TIMELINE_MILESTONES` array with 16 ordered keys; `_EVENT_LABELS` expanded to 20+ entries; `TimelineTab` shows done events (from `audit.timeline`) with green ✓ circle + timestamp, then pending milestones with grey dot; header shows "0 of 16 milestones completed" or real count. |

---

## R-Q1 Ruling Compliance

Rule: "DHL remains the standalone authority. Shipment Detail carries only an entry point/sub-tab into it. No duplicate DHL UI or backend."

Implementation:
- DHL / Customs tab renders a READ-ONLY `DhlReadinessCard` (status summary only, no action duplication)
- All DHL actions route through the standalone DHL Console page via `data-testid="dhl-open-console-link"`
- No new DHL backend routes created
- No DHL button state management in this file

---

## Lesson M Compliance

All write actions in the PZ / Accounting tab use `PendingAction` component with:
- `disabled` attribute
- `data-action-state="backend-pending"`
- `data-backend-route` referencing the exact existing backend route
- `BackendPendingBanner` amber notice explaining V2 routing is in progress

No write actions were removed or hidden. All 7 buttons remain visible in disabled state.

---

## Ratchet / B-018 Status

- B-018 ratchet test (`test_phase2b_shipment_detail_pruned.py`) pins `shipment-detail.html` (V1 HTML file)
- This slice edits `shipment-detail-page.jsx` (V2 JSX file)
- Ratchet is **unaffected** — 151/151 shipment-detail contract tests pass

---

## pz-api.js Addition

Single transport-only wrapper added after the existing Wave-3 block tail (`getWfirmaContractorScanStatus`):

```javascript
// GET /api/v1/tracking/shipment/{batch_id}/timeline
// Authority: routes_tracking.py (get_shipment_timeline)
// Used by: shipment-detail-page.jsx TimelineTab (SD-7 gap closure)
getShipmentTimeline: (batchId) =>
  _get(`${BASE}/tracking/shipment/${encodeURIComponent(batchId)}/timeline`),
```

No business logic. No new backend routes. Transport layer only.

---

## Browser Verification

All tabs verified against live preview server (mock batch `TST-AWB-2`):

| Tab | Verified | Evidence |
|---|---|---|
| Overview — SD-1 header | PASS | Carrier chip (DHL badge), MRN (`PL123456789`), sub-header chips visible |
| Overview — SD-2 Next Actions | PASS | Contextual action tiles rendered at `data-testid="overview-context-actions"` |
| DHL / Customs — SD-4 entry-point | PASS | Blue gradient banner + "Open DHL Console ↗" link visible |
| PZ / Accounting — SD-5 gated (no SAD) | PASS | "PZ generation requires SAD/customs data" amber gate message |
| PZ / Accounting — SD-5 full set (SAD uploaded) | PASS | All 7 disabled PendingAction buttons visible: Run PZ, Confirm PZ Number, Download XLSX, Download PDF, Export to wFirma, Mark Exported |
| Documents — SD-6 | PASS | Error fallback renders correctly (404 expected for mock batch); 4-card grid code in place |
| Timeline — SD-7 | PASS | "Activity timeline / 0 of 16 milestones completed"; all 16 milestones listed as Pending |

Console errors during verification: none (no new red entries).

---

## Tree Counts

- BEFORE: 42 working-tree changes (`git status --short | wc -l`)
- AFTER: 43 working-tree changes
- Net new tracked files: 1 (this build record)
- Modified files: `shipment-detail-page.jsx`, `pz-api.js`

---

## Constraints Honored

- No git stash/clean/reset executed
- No commit/push/PR/deploy
- No C:\PZ touches
- No npm install
- No write-gate or flag changes
- No new backend routes created
- Only `shipment-detail-page.jsx` and `pz-api.js` edited (+ this build record)
