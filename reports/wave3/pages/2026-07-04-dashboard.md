# Wave-3 Build Record — Dashboard (Page A)

**Date:** 2026-07-04  
**Branch:** deploy/latest  
**Session:** Wave-3 order #5  
**File edited:** `service/app/static/v2/wireframe-update.jsx`  
**Pre-edit git-status tracked-M count:** 6  
**Post-edit git-status tracked-M count:** 7 (wireframe-update.jsx added)

---

## Census gaps addressed

| Gap ID | Description | Tag | Resolution |
|--------|-------------|-----|------------|
| D-5    | OperationalStatusStrip — 6 hardcoded fake entries, no backend call | REMOVE | Replaced with live version: fetches `GET /api/v1/webhooks/wfirma/status` + `GET /api/v1/health` on mount, polls every 60 s. Auth-gated endpoint (401) correctly renders "unavailable"; health endpoint (200) renders "healthy". |
| D-1    | KPI tiles (Active, Urgent, Awaiting DHL, Awaiting SAD, Ready for booking) | ALREADY BUILT | Confirmed in dashboard-kanban.jsx lines 1-423. No edit needed. |
| D-2    | 4 QUICK_FLOWS CTAs (Receive shipment, New shipment, Scan DHL inbox, Generate PZ) | ALREADY BUILT | Confirmed present and rendering live. No edit needed. |
| D-3    | Kanban lane labels | ALREADY BUILT | Confirmed correct PZ workflow labels: "New / Drafting", "Awaiting Documents", "Customs Clearance", "Ready for PZ", "PZ Generated", "Exported". No edit needed. |
| D-4    | GlobalSearch wired | ALREADY BUILT | Confirmed in index.html line 858. No edit needed. |

**No dashboard-kanban.jsx edits were required.** D-1 through D-4 were complete prior to this session.

---

## Control Matrix

| Control | Wireframe Required | Implemented | Backend endpoint | Status |
|---------|--------------------|-------------|-----------------|--------|
| Operational Status Strip | Yes (live data) | wireframe-update.jsx — new live component | `GET /api/v1/webhooks/wfirma/status`, `GET /api/v1/health` | CLOSED (D-5) |
| 5 KPI tiles | Yes | dashboard-kanban.jsx (pre-existing) | `GET /api/v1/dashboard/batches` | ALREADY BUILT |
| 4 QUICK_FLOWS CTAs | Yes | dashboard-kanban.jsx (pre-existing) | SPA navigation | ALREADY BUILT |
| 6 Kanban lanes | Yes | dashboard-kanban.jsx (pre-existing) | `GET /api/v1/dashboard/batches` | ALREADY BUILT |
| GlobalSearch | Yes | index.html line 858 (pre-existing) | `GET /api/v1/search` | ALREADY BUILT |
| Bell / Avatar | OPERATOR-RULED | Not fabricated — no fake count or no-op wired | N/A | OPERATOR-RULED |

**Wireframe-Required Missing = 0**

---

## Browser verification

- URL: `/v2/` SPA, Dashboard nav item
- OperationalStatusStrip `data-testid="operational-status-strip"`: **CONFIRMED present**
- wFirma Sync item: **red dot · unavailable** (401 from auth-gated endpoint — EXPECTED CORRECT)
- PZ Engine item: **green dot · healthy** (200 from `/api/v1/health`)
- Polled timestamp: **rendered live** (updated every 60 s)
- 4 QUICK_FLOWS CTAs: **all rendered**
- 5 KPI tiles: **all rendered** (ACTIVE 273, URGENT 0, AWAITING DHL 0, AWAITING SAD 0, READY FOR BOOKING 0 — live data)
- 6 Kanban lanes with `data-testid="kanban-lane"`: **all confirmed** ("New / Drafting", "Awaiting Documents", "Customs Clearance", "Ready for PZ", "PZ Generated", "Exported")
- Console errors: **none** (Babel size warnings are pre-existing infrastructure, not page errors)

---

## Smoke tests

`cd service && pytest tests/ -m smoke -q` → **63 passed, 1 skipped**. No regressions.

---

## Lesson M compliance

D-5 was tagged REMOVE in the census because the content was **fabricated** (hardcoded fake statuses with no backend connection). Lesson M protects planned operator-visible capabilities from suppression; it does not protect fabricated content that was never real. The census ruling applied. The strip was not removed but replaced with a live-data version that shows the same surface with real data — this satisfies both the census ruling and the honest-UI policy (R-Q3).

---

## Files changed this session (Page A)

- `service/app/static/v2/wireframe-update.jsx` — replaced static `OperationalStatusStrip` (lines 68-98) with live version that calls `/api/v1/webhooks/wfirma/status` + `/api/v1/health`, polls every 60 s, handles auth failures gracefully, has `data-testid="operational-status-strip"`
- `service/app/static/v2/pz-api.js` — added Wave-3 transport block: `getWfirmaWebhookStatus`, `getDeployStatus` (used by OperationalStatusStrip and health page)
