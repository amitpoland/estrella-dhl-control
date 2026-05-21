# Sprint 13 — Dashboard V2

**Campaign:** Atlas-V2  
**Sprint:** 13 of 13  
**Branch:** `atlas-v2/sprint-13-dashboard-v2`  
**Dependency:** Sprints 01–12 merged (all domain pages stable)  
**New file:** `service/app/static/dashboard-v2.html`  
**URL:** `/dashboard/dashboard-v2.html`

---

## Authority Boundary

```
OWNS:  operator entry-point shell, cross-domain summary cards,
       navigation links to all V2 domain pages,
       top-level health indicators (batch count, clearance queue depth,
       wFirma sync status, open PZ count),
       notification/alert strip (action-required items),
       session-level UI preferences (collapse state, filter presets)
NEVER: batch creation, proforma drafts, PZ creation, inventory edits,
       warehouse scan-in, admin operations, auth changes,
       any domain-level business logic (all owned by domain pages),
       any direct wFirma or DHL API calls,
       recalculating landed cost, duty, or any financial total
```

---

## Page Purpose

The Dashboard V2 is the **aggregation surface** — the operator's home screen after login.
It shows what needs attention today: how many batches are in flight, how many shipments
need clearance action, whether wFirma sync is healthy, whether any PZ is blocked.

This page **does not own any domain**. It reads summary data from the same backend APIs
that domain pages use. Every summary card links to the relevant domain page.
No business logic lives here — clicking "Clearance queue: 3" goes to `inbox-v2.html`,
not an inline resolver.

**Build order rule:** Dashboard V2 is built LAST because it depends on all domain pages
being stable authority surfaces. Building it early means depending on unstable contracts —
exactly how V1 fragmentation started (Lesson F).

---

## APIs This Page Consumes

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/v1/dashboard/summary` | Read | Aggregate counts: batches, PZs, clearance items, alerts |
| `GET /api/v1/batch/sessions` | Read | Batch pipeline overview (status distribution) |
| `GET /api/v1/health` | Read | System health banner |
| `GET /api/v1/admin/email-queue` | Read | Email queue depth (read-only banner) |

If `GET /api/v1/dashboard/summary` doesn't exist, `backend-api` adds it as a
thin aggregation over existing route data — no new business logic, only counts.

---

## Card Grid

| Card | Data source | Link-out |
|------|-------------|----------|
| Clearance Inbox | `/api/v1/batch/sessions` — batches awaiting email / SAD | `inbox-v2.html` |
| Active Batches | `/api/v1/batch/sessions` — in-flight count | `batch-v2.html` |
| Open PZs | `/api/v1/dashboard/summary` — pz_open count | `pz-v2.html` |
| Inventory Alerts | `/api/v1/dashboard/summary` — pieces needing attention | `inventory-v2.html` |
| wFirma Sync | `/api/v1/dashboard/summary` — last sync status | `admin-v2.html` |
| System Health | `/api/v1/health` — ok / degraded | `admin-v2.html` |

All cards are read-only. No write action originates from this page.

---

## Navigation Rail

The dashboard also owns the primary navigation rail (sidebar or top bar — match the
layout pattern in `proforma-v2.html`). Links to all V2 pages:

- Clearance Inbox (`inbox-v2.html`)
- Batches (`batch-v2.html`)
- Shipments (`shipment-v2.html`)
- Documents (`documents-v2.html`)
- Proforma (`proforma-v2.html`)
- PZ (`pz-v2.html`)
- Inventory (`inventory-v2.html`)
- Warehouse (`warehouse-v2.html`)
- Customers (`customer-master-v2.html`)
- Products (`products-v2.html`)
- Admin (`admin-v2.html`)

The navigation rail is a `dashboard-shared.js` primitive if it has been extracted
into the shared layer by this sprint. If not: inline it, then file an issue to
extract it into `dashboard-shared.js` in a follow-up PR.

---

## Mandatory Agents

| Order | `subagent_type` | Purpose |
|-------|-----------------|---------|
| 1 | `chief-orchestrator` | Routing |
| 2 | `system-architect` | Verify dashboard summary endpoint; confirm all domain page APIs are stable |
| 3 | `gap-detection` | Missing summary endpoints; broken links to domain pages |
| 4 | `reviewer-challenge` | Attack any plan that puts domain logic on this page; confirm build-last rationale holds |
| 5 | `backend-api` | Add `/api/v1/dashboard/summary` aggregation endpoint if missing |
| 6 | `backend-safety-reviewer` | Confirm summary endpoint is read-only; no writes |
| 7 | `frontend-ui` | Build dashboard-v2.html (aggregation only, no domain logic) |
| 8 | `ux-flow` | Navigation usability: does the entry-point orient the operator clearly? |
| 9 | `frontend-flow-reviewer` | Review all nav links; confirm every card links to correct domain page |
| 10 | `testing-verification` | Tests: card renders, nav links present, summary API wired, health banner |
| 11 | `test-coverage-reviewer` | Review |
| 12 | `gap-hunter` | Cross-page contradictions; any domain logic that leaked into dashboard |
| 13 | `browser-verifier` | Open page; verify all 6 cards render; click every nav link; confirm no domain logic |
| 14 | `integration-boundary` | Confirm each card's API wiring; no fake data |
| 15 | `git-workflow` + `pr-author` | Commit + PR |

---

## Test Baseline

```bash
make verify                 # 160/160
cd service && python3 -m pytest tests/test_proforma_v2_contract.py -q  # 44/44
cd service && python3 -m pytest tests/test_carrier_*.py -q             # 366/366
```

---

## Acceptance Criteria

1. Page renders at `/dashboard/dashboard-v2.html` — no console errors
2. All 6 summary cards display with counts from live API (or graceful zero-state)
3. Each card links to the correct V2 domain page
4. Navigation rail links to all 11 domain V2 pages
5. System health banner shows from `/api/v1/health`
6. Email queue depth visible (read-only)
7. No business logic on this page — it is pure aggregation and navigation
8. All interactive elements have `data-testid`
9. No wFirma, DHL, or PZ creation from this page
10. Post-login redirect from `login.html` (`/dashboard/inbox-v2.html`) is NOT replaced — dashboard is the home screen for direct navigation, not the post-login landing page
11. Rollback: remove file; no restart needed

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 13 — Dashboard V2
Branch: atlas-v2/sprint-13-dashboard-v2 (create from origin/main, ALL previous sprints must be merged)

STACK CONSTRAINTS — mandatory, read before any UI work:
1. Read `.claude/skills/frontend-design.md` BEFORE touching any HTML/JS
2. `.claude/skills/ui-ux-pro-max` is supplemental only — read `EJ_OVERRIDES.md` first
3. Stack: Vanilla HTML + Babel JSX. NO Vite. NO TypeScript. NO Tailwind. NO bundler.
4. Pattern file: service/app/static/proforma-v2.html
5. Shared layer: window.EstrellaShared, window.PzApi, window.PzState, window.PzComponents
6. CSS: custom properties only. Zero hardcoded hex.

TASK:
Create service/app/static/dashboard-v2.html — operator home screen / aggregation surface.
URL: /dashboard/dashboard-v2.html

CRITICAL BUILD-ORDER RULE:
Dashboard V2 is built LAST because it depends on all domain pages being stable authority
surfaces. If any domain page (sprints 02–12) is not yet merged, STOP and report which
sprint is blocking.

AUTHORITY:
OWNS: summary cards, navigation rail, health banner, link-outs to domain pages
NEVER: batch creation, proforma, PZ, inventory edits, warehouse scan-in, admin ops,
       auth changes, any domain business logic, wFirma or DHL API calls,
       recalculating any financial total

CARD GRID (read-only, each links to domain page):
- Clearance Inbox → inbox-v2.html
- Active Batches → batch-v2.html
- Open PZs → pz-v2.html
- Inventory Alerts → inventory-v2.html
- wFirma Sync → admin-v2.html
- System Health → admin-v2.html

NAVIGATION RAIL (links to all V2 pages):
inbox-v2, batch-v2, shipment-v2, documents-v2, proforma-v2, pz-v2,
inventory-v2, warehouse-v2, customer-master-v2, products-v2, admin-v2

APIs (add summary endpoint if missing):
- GET /api/v1/dashboard/summary (aggregation only — counts, no logic)
- GET /api/v1/batch/sessions
- GET /api/v1/health
- GET /api/v1/admin/email-queue

IMPORTANT: POST-LOGIN REDIRECT is /dashboard/inbox-v2.html (owned by sprint 12 auth pages).
Dashboard-v2.html is the home screen for direct navigation — do NOT change the post-login redirect.

MANDATORY AGENT SEQUENCE:
1. system-architect — verify domain page APIs are stable; summary endpoint design
2. gap-detection — missing endpoints, broken nav links
3. reviewer-challenge — attack any domain logic on this page; enforce build-last rationale
4. backend-api + backend-safety-reviewer — add summary endpoint if missing (read-only only)
5. frontend-ui — build dashboard-v2.html (aggregation + navigation only)
6. ux-flow — entry-point orientation and navigation usability
7. frontend-flow-reviewer — nav links correct, cards link to right pages
8. testing-verification — cards, nav links, API wiring, health banner
9. test-coverage-reviewer
10. gap-hunter — domain logic leakage check
11. browser-verifier — open page, click all nav links, verify 6 cards, confirm no domain logic
12. integration-boundary — each card's API wiring verified
13. git-workflow + pr-author

TEST BASELINE:
- make verify → 160/160
- tests/test_proforma_v2_contract.py → 44/44
- tests/test_carrier_*.py → 366/366

End with /deploy after PR merges.
```
