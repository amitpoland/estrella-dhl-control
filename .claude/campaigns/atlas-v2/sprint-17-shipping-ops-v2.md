# Sprint 17 — Shipping Ops V2

**Campaign:** Atlas-V2  
**Sprint:** 17 of 23  
**Branch:** `atlas-v2/sprint-17-shipping-ops-v2`  
**Dependency:** Sprint 16 (Carriers) merged — carrier registry must exist  
**New file:** `service/app/static/shipping-ops-v2.html`  
**URL:** `/dashboard/shipping-ops-v2.html`  
**Design source:** `design-files/shipping-ops.jsx`

---

## Authority Boundary

```
OWNS:  Multi-carrier shipment & label operations wireframe — rate planning,
       AWB generation triggers (gated, status-chip disabled until backend ready),
       label print queue, carrier service selection, pickup scheduling display
NEVER: Real AWB generation against live carriers (backend not built),
       carrier credential management (carriers-v2 + admin-v2),
       customs document mutations (documents-v2 / shipment-v2)
```

**Discipline:** every write button on this page MUST be wireframe-disabled with a
status chip naming the missing backend (`Backend pending`, `API required`, `Carrier
approval required`). The page exists to validate UX before backend implementation —
real writes are deferred to a future sprint.

---

## APIs

| Endpoint | Purpose | Status |
|----------|---------|--------|
| `GET /api/v1/carriers` | (from Sprint 16) | exists after Sprint 16 |
| `GET /api/v1/shipments/queue` | Pending shipments queue | NEW read-only |
| `GET /api/v1/labels/print-queue` | Print queue state | NEW read-only |
| All POST endpoints | Disabled stubs only | Not implemented this sprint |

---

## Page Structure

- PageHeader (h1: "Shipping Operations", subtitle: "Carrier label & dispatch planning")
- Status legend strip: Planned · Backend pending · API required · Carrier approval required
- Queue panel: pending shipments awaiting label
- Label print queue panel: ZPL/PDF status per pending label
- Carrier service selector (visual only, no write)
- All write buttons: disabled + `ShipStatus` chip naming required backend

---

## Mandatory Agents

Same 15. Adds:
- `reviewer-challenge` MUST flag any non-disabled write button (Lesson F discipline)
- `button-functionality` agent verdict: every disabled button has visible chip naming missing backend

---

## Acceptance Criteria

1. Page loads, no console errors
2. Queue + print-queue panels render with real backend data (read-only)
3. **All write buttons disabled** with `ShipStatus` chip naming required backend
4. Status legend strip explains all chip colors
5. SessionBanner on errors
6. `data-testid` on every interactive surface
7. Zero writes verified via Network panel
8. Rollback: remove file

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 17 — Shipping Ops V2
Branch: atlas-v2/sprint-17-shipping-ops-v2 (Sprint 16 merged required)

STACK CONSTRAINTS: same as Sprint 14.
Design ref: git show origin/atlas-v2/source-bundle:design-files/shipping-ops.jsx

TASK: Create shipping-ops-v2.html — multi-carrier label operations wireframe.

AUTHORITY:
OWNS: read-only queues + planning UI + disabled-write wireframe
NEVER: real AWB writes, credential management, customs mutations

WIREFRAME DISCIPLINE:
- EVERY write button disabled with ShipStatus chip naming missing backend
- reviewer-challenge MUST block any non-disabled write
- button-functionality verdict required for each disabled button

BACKEND: read-only queue endpoints only. No POST/PUT/DELETE this sprint.

GATE 2 + 15-agent sequence + test baseline: same as Sprint 14.

End with /deploy after merge.
```
