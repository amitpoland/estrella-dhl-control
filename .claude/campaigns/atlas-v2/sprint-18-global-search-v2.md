# Sprint 18 — Global Search V2

**Campaign:** Atlas-V2  
**Sprint:** 18 of 23  
**Branch:** `atlas-v2/sprint-18-global-search-v2`  
**Dependency:** Sprints 02, 03, 04, 05 merged — search needs target pages to navigate to  
**New file:** `service/app/static/global-search-v2.html` + integration into dashboard-shared.js  
**URL:** Cmd-K overlay (not a standalone URL) — surfaces on any V2 page  
**Design source:** `design-files/global-search.jsx`

---

## Authority Boundary

```
OWNS:  Cmd-K (Ctrl-K) search overlay — search across shipments, AWBs, documents,
       clients, suppliers, batches, SKUs. Quick-jump navigation to detail pages.
       Filter chips by type (shipment / awb / doc / client / sku).
NEVER: Edit any record from search results, mutate any data, bypass page-level
       authority (search opens the owning page; never inlines edit).
```

---

## APIs

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/search?q=&types=` | Unified search across types | NEW read-only |
| `GET /api/v1/search/recent` | Operator's recent items | NEW read-only |

Backend implements via existing indexes (no Elasticsearch — SQLite FTS + denormalized
search rows acceptable). `backend-api` agent designs schema; `backend-safety-reviewer`
verdicts read-only.

---

## Page Structure

This is NOT a standalone page — it's an overlay added to `dashboard-shared.js` as a
new component `GlobalSearch` that mounts via keyboard handler:
- Cmd-K (Mac) / Ctrl-K (Windows) → open overlay
- ESC → close
- Type query → debounced search → grouped results (shipment / awb / doc / client / sku)
- Enter / click → navigate to owning page
- Filter chips at top → scope search

**Lesson F watch:** GlobalSearch is added to `dashboard-shared.js` AS A VISUAL ATOM
overlay. It MUST NOT learn domain semantics — only render results from the API.
`frontend-flow-reviewer` verifies no domain leak.

---

## Mandatory Agents

Same 15. Adds:
- `dashboard-shared.js` modification requires explicit `reviewer-challenge` verdict
  that no domain knowledge was added
- `frontend-flow-reviewer` verifies overlay does not break any V2 page

---

## Acceptance Criteria

1. Cmd-K / Ctrl-K opens overlay on every V2 page (proforma, inbox, shipment, documents, customer, products, pz)
2. ESC closes overlay
3. Typing debounces correctly, no per-keystroke API spam
4. Filter chips scope results
5. Enter navigates to owning page
6. `dashboard-shared.js` line count delta ≤ 200; no domain props introduced
7. Overlay z-index above all page content
8. `data-testid` on overlay + each result row
9. SessionBanner on auth error
10. Rollback: revert dashboard-shared.js + remove global-search-v2.html

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 18 — Global Search V2
Branch: atlas-v2/sprint-18-global-search-v2 (Sprints 02/03/04/05 merged)

STACK CONSTRAINTS: same as Sprint 14.
Design ref: git show origin/atlas-v2/source-bundle:design-files/global-search.jsx

TASK: Add Cmd-K global search overlay to dashboard-shared.js + supporting
backend /api/v1/search endpoint.

AUTHORITY:
OWNS: search overlay UI + navigation
NEVER: any inline edit from search results; no domain semantics in dashboard-shared.js

LESSON F BINDING (critical):
- dashboard-shared.js modification requires reviewer-challenge verdict
  certifying NO domain knowledge added (no shipment-state checks, no clearance rules)
- GlobalSearch is a visual atom only — renders results from API
- frontend-flow-reviewer verifies overlay does not break any V2 page

BACKEND: GET /api/v1/search read-only. backend-safety-reviewer verdicts no writes.

GATE 2 + 15-agent sequence + test baseline: same as Sprint 14.
ADDITIONAL TEST: dashboard-shared.js line count + grep for forbidden domain tokens.

End with /deploy after merge.
```
