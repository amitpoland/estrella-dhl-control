# Sprint 19 — Dashboard Kanban V2

**Campaign:** Atlas-V2  
**Sprint:** 19 of 23  
**Branch:** `atlas-v2/sprint-19-dashboard-kanban-v2`  
**Dependency:** Sprints 02, 03 merged. May be merged BEFORE Sprint 13 dashboard-v2 — they are distinct visualizations.  
**New file:** `service/app/static/dashboard-kanban-v2.html`  
**URL:** `/dashboard/dashboard-kanban-v2.html`  
**Design source:** `design-files/dashboard-kanban.jsx`

---

## Authority Boundary

```
OWNS:  Workflow-first pipeline board — every active shipment as a card in the
       lane matching its current stage (New, Awaiting Docs, Customs, Ready,
       In Transit, Delivered). Quick-start CTAs for common workflows.
NEVER: Drag-to-reorder writes (lane assignment is derived from backend state,
       not operator-set), shipment state mutations, document creation,
       customs writes, label generation.
```

**Critical:** lane membership is **derived** from backend status, NOT operator-set.
Dragging a card across lanes does not change state — state changes happen on the
owning V2 page (shipment-v2). Drag-drop affordance is intentionally absent.

---

## APIs

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/dashboard/kanban` | Pipeline board view, all active shipments grouped by lane | NEW read-only |
| `GET /api/v1/dashboard/kanban/lane/{lane_id}` | Drill-in per lane | optional, NEW |

`backend-api` agent designs lane derivation logic. `backend-safety-reviewer` verdicts read-only.

---

## Page Structure

- PageHeader (h1: "Pipeline", subtitle: "Workflow view")
- 4 Quick-start CTAs: "New Proforma" · "Import Invoice" · "Track AWB" · "Open Inbox"
- Lane strip: New · Awaiting Docs · Customs · Ready · In Transit · Delivered
- Per lane: card stack of shipments (client, value, age, carrier, flag)
- Card click → navigate to shipment-v2
- No drag-drop affordance (intentional)
- EmptyState per lane when empty
- SessionBanner on errors

---

## Mandatory Agents

Same 15. Adds:
- `ux-flow` agent verdict: lane derivation is clear, no operator confusion about drag-drop absence
- `reviewer-challenge` verdict: zero write affordance

---

## Acceptance Criteria

1. Page loads, all lanes render, no console errors
2. Card click navigates to shipment-v2.html?batch_id=<id>
3. Quick-start CTAs navigate to correct pages
4. Per-lane empty state shown when no cards
5. **No drag-drop affordance present** (verified by inspecting DOM for `draggable` attrs)
6. SessionBanner on auth/network errors
7. `data-testid` on every card and CTA
8. Zero writes verified via Network panel
9. Rollback: remove file

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 19 — Dashboard Kanban V2
Branch: atlas-v2/sprint-19-dashboard-kanban-v2 (Sprints 02 + 03 merged)

STACK CONSTRAINTS: same as Sprint 14.
Design ref: git show origin/atlas-v2/source-bundle:design-files/dashboard-kanban.jsx

TASK: Create dashboard-kanban-v2.html — workflow pipeline board.

AUTHORITY:
OWNS: read-only pipeline view, lane membership derived from backend
NEVER: drag-drop writes, state mutations, document creation, customs writes

KEY DISCIPLINE:
- Lane membership is DERIVED from backend; not operator-set
- NO drag-drop affordance in DOM (no `draggable` attr, no onDrop handlers)
- reviewer-challenge MUST verify zero write affordance
- ux-flow MUST verdict that lane-derivation is clear to operator

BACKEND: GET /api/v1/dashboard/kanban read-only. backend-safety-reviewer verdicts.

GATE 2 + 15-agent sequence + test baseline: same as Sprint 14.

End with /deploy after merge.
```
