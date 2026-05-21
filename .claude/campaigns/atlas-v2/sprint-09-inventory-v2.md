# Sprint 09 — Inventory V2

**Campaign:** Atlas-V2  
**Sprint:** 09 of 13  
**Branch:** `atlas-v2/sprint-09-inventory-v2`  
**Dependency:** Sprint 08 merged  
**New file:** `service/app/static/inventory-v2.html`  
**URL:** `/dashboard/inventory-v2.html`

---

## Authority Boundary

```
OWNS:  piece-level stock display, reservation status per piece,
       dispatch state visualization, consignment/sample/damaged states display,
       "Reserve" / "Release reservation" buttons (explicit click, gated),
       stock visibility by batch and by client
NEVER: warehouse scan-in, PZ creation, proforma drafts,
       shipping label creation, DHL API calls, wFirma writes,
       piece-level state machine transitions that bypass backend guards
```

---

## Page Purpose

Piece-level inventory visibility. Operators see what stock is reserved,
dispatched, in consignment, damaged, or available. Reserve/release
buttons call the existing inventory state machine backend endpoints.

The inventory state machine is owned by the backend
(`inventory-state-machine` agent). This page is a **read surface + gated
write surface** — it does not implement state machine logic client-side.

---

## APIs This Page Consumes

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/v1/inventory/stock` | Read | Stock list with states |
| `GET /api/v1/inventory/reservations` | Read | Active reservations |
| `POST /api/v1/inventory/reserve/{piece_id}` | Write (gated) | Reserve a piece |
| `DELETE /api/v1/inventory/reserve/{piece_id}` | Write (gated) | Release reservation |

If these don't exist, `backend-api` adds thin wrappers. No new state machine logic.

---

## Mandatory Agents

| Order | `subagent_type` | Purpose |
|-------|-----------------|---------|
| 1 | `chief-orchestrator` | Routing |
| 2 | `system-architect` | Verify inventory API, state machine boundary |
| 3 | `gap-detection` | Missing inventory endpoints |
| 4 | `reviewer-challenge` | Attack any plan implementing state transitions client-side |
| 5 | `backend-api` | Add inventory endpoints if missing |
| 6 | `backend-safety-reviewer` | Review reserve/release write paths |
| 7 | `frontend-ui` | Build inventory-v2.html |
| 8 | `frontend-flow-reviewer` | Review |
| 9 | `testing-verification` | Tests |
| 10 | `test-coverage-reviewer` | Review |
| 11 | `gap-hunter` | Cross-phase |
| 12 | `browser-verifier` | Open page, verify state badges, test reserve button |
| 13 | `integration-boundary` | API wiring |
| 14 | `git-workflow` + `pr-author` | Commit + PR |

---

## Test Baseline

```bash
make verify                 # 160/160
cd service && python3 -m pytest tests/test_proforma_v2_contract.py -q  # 44/44
cd service && python3 -m pytest tests/test_carrier_*.py -q             # 366/366
```

---

## Acceptance Criteria

1. Stock list loads with piece-level state badges (reserved, dispatched, available, damaged)
2. Filter by state works
3. "Reserve" Btn enabled only for available pieces; disabled for reserved/dispatched
4. Reserve confirmation modal → POST fires → Badge updates
5. "Release reservation" Btn enabled only for reserved pieces
6. Consignment and sample state pieces visually distinct
7. All interactive elements have `data-testid`
8. No state machine logic client-side — UI reflects backend state only
9. Rollback: remove file; no restart needed

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 09 — Inventory V2
Branch: atlas-v2/sprint-09-inventory-v2 (create from origin/main, Sprint 08 must be merged)

STACK CONSTRAINTS — mandatory, read before any UI work:
1. Read `.claude/skills/frontend-design.md` BEFORE touching any HTML/JS
2. `.claude/skills/ui-ux-pro-max` is supplemental only — read `EJ_OVERRIDES.md` first
3. Stack: Vanilla HTML + Babel JSX. NO Vite. NO TypeScript. NO Tailwind. NO bundler.
4. Pattern file: service/app/static/proforma-v2.html
5. Shared layer: window.EstrellaShared, window.PzApi, window.PzState, window.PzComponents
6. CSS: custom properties only. Zero hardcoded hex.

TASK:
Create service/app/static/inventory-v2.html — piece-level stock and reservation management.
URL: /dashboard/inventory-v2.html

AUTHORITY:
OWNS: piece-level stock display, reservation status, reserve/release buttons (gated)
NEVER: warehouse scan-in, PZ, proforma, shipping label, DHL, wFirma, client-side state machine logic

CRITICAL RULE:
The inventory state machine is owned by the backend. This page is a read surface + gated
write surface. DO NOT implement state transition logic client-side. UI reflects backend state only.

APIs (add if missing):
- GET /api/v1/inventory/stock
- GET /api/v1/inventory/reservations
- POST /api/v1/inventory/reserve/{piece_id} (gated, confirmation modal required)
- DELETE /api/v1/inventory/reserve/{piece_id} (gated)

MANDATORY AGENT SEQUENCE:
1. system-architect — inventory API and state machine boundary
2. gap-detection
3. reviewer-challenge — attack any client-side state machine logic
4. backend-api — add endpoints if missing
5. backend-safety-reviewer — review write paths
6. frontend-ui — build inventory-v2.html
7. frontend-flow-reviewer
8. testing-verification
9. test-coverage-reviewer
10. gap-hunter
11. browser-verifier
12. integration-boundary
13. git-workflow + pr-author

TEST BASELINE:
- make verify → 160/160
- tests/test_proforma_v2_contract.py → 44/44
- tests/test_carrier_*.py → 366/366

End with /deploy after PR merges.
```
