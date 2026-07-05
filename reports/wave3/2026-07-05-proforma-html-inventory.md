# Proforma — HTML DOM inventory + classification (authoritative spec)

**Date:** 2026-07-05 · Source: live Playwright DOM extraction of the pinned wireframe (f7dd5e38) Proforma screen (not memory). Classification vs current React (`proforma-list.jsx` / `proforma-detail.jsx`).

## LIST screen (`/proforma`)

| # | HTML element (cited) | Class | Notes |
|---|---|---|---|
| Heading "Pro Forma" + subtitle | IMPLEMENTED | PageHeader |
| "Pro Forma Drafts" h2 + "Packing List is the source…" | IMPLEMENTED | ported landing |
| Export CSV (header) | IMPLEMENTED | header |
| 5 KPI cards (Extracting/Operator Review/Ready/Pushed/Error) | IMPLEMENTED | live aggregate |
| Toolbar: **Import Packing List** (gold, always on → 4-step wizard modal) | **PORT** | modal not built; exec = `POST /proforma/upload-packing-list` (DC-12) **not deployed → BACKEND GAP** |
| Toolbar: **+ Create Draft** (→ source-picker modal: Packing List / Shipment / Manual / Clone) | **PORT** | modal not built; reuse existing create/import endpoints |
| Toolbar: Push/Send/Print — disabled w/o selection, show `(N)` with selection | IMPLEMENTED (this slice) | count-aware; single→detail reuse |
| Selection action bar (N selected + Clear + selected-actions) | IMPLEMENTED (this slice) | N selected + Clear; bulk actions = authority gap |
| 8-col table: ☐ · Draft No · Customer · Shipment · Items · Total · Match · Status | REUSE + PORT | cols present; sub-lines (source·date / AWB / Cust+Prod / wfirma-doc / block-reason) = PORT (reuse search fields, "—" where absent) |
| Row → detail (full-page nav) | IMPLEMENTED | onDrill |
| Checkbox select-all (indeterminate) | REUSE | select-all present (indeterminate = PORT nicety) |
| Filters / search / pagination | OUT OF SCOPE | HTML has none |

## DETAIL screen (`/proforma_detail`) — mostly already built (`proforma-detail.jsx`)

| HTML element | Class |
|---|---|
| Back · draft no · status/Editing badge | IMPLEMENTED |
| Action buttons (Edit/Preview/Print/Send/AWB/Prior/Approve/Post/Convert) status-conditional | REUSE (present) |
| Edit mode (Cancel / Save changes) | REUSE |
| Exporter / Customer / Currency-Payment cards | REUSE |
| 6 tabs (Overview/Items/Source/Logistics/Documents/Audit) | REUSE |
| **PushToWfirmaModal** (⚠ FINANCIAL WRITE · idempotencyKey · 2-step confirm · `POST /proforma/{id}/push-to-wfirma`) | REUSE (existing confirmed post) |

## Authority gaps (STOP — new authority / operator approval)
1. **`POST /proforma/upload-packing-list`** — Import 4-step wizard execution (DC-12; not deployed). New endpoint.
2. **Bulk Push/Send** on multi-selection — new bulk financial write path. New authority.
3. **Print** — no print endpoint. Backend gap.

## This slice (committed): count-aware toolbar (`(N)`), selection action bar + Clear, single-select Push/Send routing to the existing confirmed per-draft flow. Verified in Preview, console clean.

## Next PORT slices (reuse-first; UI rendered even where backend-gapped, per UI-before-backend)
- Import Packing List 4-step wizard modal (Upload→Extraction→Mapping→Create) — render full UI; execution shows AUTHORITY GAP (upload-packing-list not deployed).
- Create Draft source-picker modal (4 options) — wire Packing-List→import wizard, Manual/Clone→existing create.
- Table row sub-lines (source·date / AWB / Cust+Prod match / wfirma-doc / block-reason).
