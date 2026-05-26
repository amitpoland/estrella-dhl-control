# Sprint 20 — Ops Cell V2

**Campaign:** Atlas-V2  
**Sprint:** 20 of 23  
**Branch:** `atlas-v2/sprint-20-ops-cell-v2`  
**Dependency:** Sprints 08 (warehouse) + 11 (admin) merged  
**New file:** `service/app/static/ops-cell-v2.html`  
**URL:** `/dashboard/ops-cell-v2.html`  
**Design source:** `design-files/ops-cell.jsx`

---

## Authority Boundary

```
OWNS:  Surfaces backend modules that lack dedicated UI — Warehouse Scanner,
       Reservation Cell, wFirma Mapping, Diagnostics, Label Print queue,
       Document Extraction registry. Status chips for backend availability.
NEVER: Bypass any owning page's authority. If a module gets a dedicated V2 page
       later, ops-cell deep-links to it instead of inlining the workflow.
```

This page is an **operator escape hatch** for capabilities that don't yet have a
polished page. As each capability gets its own V2 sprint, the corresponding ops-cell
panel becomes a deep-link button instead.

---

## APIs

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/warehouse/scan` | Mobile scan-in (existing) — gated behind operator-role |
| `GET /api/v1/wfirma/customers` | wFirma customer mapping table |
| `GET /api/v1/wfirma/products` | wFirma product mapping table |
| `GET /api/v1/admin/diagnostics` | Health, storage, locks |
| `GET /api/v1/packing/{id}/barcode` | Label print payload |
| `GET /api/v1/batch/{id}/extracted_fields` | Document extraction registry |

All endpoints exist; this page CONSUMES them with status chips for each.

---

## Page Structure

- PageHeader (h1: "Ops Cell", subtitle: "Backend modules without a dedicated page")
- 6 panels (collapsible cards):
  1. Warehouse Scanner — POST /warehouse/scan trigger + scan log
  2. Reservation Cell — gate readiness display
  3. wFirma Mapping — customer + product mapping tables (read-only)
  4. Diagnostics — health, storage, locks (read-only)
  5. Label Print — barcode payload + ZPL queue
  6. Document Extraction — per-batch extracted_fields registry
- Each panel header: title + StatusChip (Ready / Pending / Blocked / API required)
- SessionBanner on auth/permission errors

---

## Mandatory Agents

Same 15. Adds:
- `security-permissions` verdict on operator-role gating for write panels
- `warehouse-ops` agent verdict on scan-in panel
- `wfirma-integration` verdict on mapping panel

---

## Acceptance Criteria

1. Page loads, all 6 panels render
2. Operator-role guard enforced on write actions (warehouse scan)
3. Read panels (mapping, diagnostics, extraction) show real data
4. StatusChip per panel reflects backend availability
5. Each panel collapsible
6. SessionBanner on auth/permission errors
7. `data-testid` on each panel and write action
8. Rollback: remove file

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 20 — Ops Cell V2
Branch: atlas-v2/sprint-20-ops-cell-v2 (Sprints 08 + 11 merged)

STACK CONSTRAINTS: same as Sprint 14.
Design ref: git show origin/atlas-v2/source-bundle:design-files/ops-cell.jsx

TASK: Create ops-cell-v2.html — operator escape hatch for backend modules
without dedicated V2 pages yet.

AUTHORITY:
OWNS: 6 panels surfacing scan-in, reservation, wFirma mapping, diagnostics,
      label print, document extraction
NEVER: bypass owning page authority — if a module later gets dedicated V2 page,
       this panel becomes a deep-link

KEY DISCIPLINE:
- security-permissions verdict on every write panel (operator-role required)
- warehouse-ops verdict on scan-in panel
- wfirma-integration verdict on mapping panel

BACKEND: all endpoints already exist; page consumes only.

GATE 2 + 15-agent sequence + test baseline: same as Sprint 14.

End with /deploy after merge.
```
