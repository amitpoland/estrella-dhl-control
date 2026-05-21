# Sprint 08 — Warehouse V2

**Campaign:** Atlas-V2  
**Sprint:** 08 of 13  
**Branch:** `atlas-v2/sprint-08-warehouse-v2`  
**Dependency:** Sprint 07 merged  
**New file:** `service/app/static/warehouse-v2.html`  
**URL:** `/dashboard/warehouse-v2.html`

---

## Authority Boundary

```
OWNS:  warehouse scan-in workflow display, packing-list verification status,
       physical movement records (read display + scan confirmation button),
       per-batch warehouse audit status, "Confirm Scan" write (explicit click)
NEVER: PZ creation, proforma, customer master, product mapping,
       inventory piece reservation, consignment state changes,
       DHL clearance, wFirma writes
```

---

## Page Purpose

The Jigar-facing warehouse operations page. Shows which batches are in the
warehouse, what's been scanned, what packing list verification status is.
Replaces the warehouse section of `shipment-detail.html`.

Primary user: Jigar (mobile-first, warehouse floor). Design for mobile viewport
(375px+) as the primary breakpoint. Larger screens are secondary.

---

## APIs This Page Consumes

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/v1/batch/sessions` | Read | Batch list with warehouse status |
| `GET /api/v1/warehouse/{batch_id}/status` | Read | Scan status, packing list verification |
| `POST /api/v1/warehouse/{batch_id}/confirm-scan` | Write | Confirm scan-in |

If warehouse endpoints don't exist, `backend-api` adds them as thin wrappers
over existing `documents.db` warehouse state fields.

---

## Mobile-First Design Rules

- Touch targets ≥44×44px on all interactive elements
- Scan confirmation Btn: large, full-width on mobile
- Status badges visible at arm's length (font ≥ 12px, high contrast)
- No hover-only information — everything tappable
- Offline-aware: if network fails, show "Last updated: X minutes ago" banner

---

## Mandatory Agents

| Order | `subagent_type` | Purpose |
|-------|-----------------|---------|
| 1 | `chief-orchestrator` | Routing |
| 2 | `system-architect` | Verify warehouse API, mobile-first requirement |
| 3 | `gap-detection` | Missing warehouse endpoints |
| 4 | `reviewer-challenge` | Attack any plan touching PZ or inventory state |
| 5 | `backend-api` | Add warehouse status endpoints if missing |
| 6 | `backend-safety-reviewer` | Review scan-confirm write path |
| 7 | `frontend-ui` | Build warehouse-v2.html (mobile-first) |
| 8 | `ux-flow` | Mobile UX — Jigar's workflow under warehouse conditions |
| 9 | `frontend-flow-reviewer` | Review |
| 10 | `testing-verification` | Tests |
| 11 | `test-coverage-reviewer` | Review |
| 12 | `gap-hunter` | Cross-phase |
| 13 | `browser-verifier` | Test at 375px viewport — all buttons tappable |
| 14 | `integration-boundary` | API wiring |
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

1. Page loads — no console errors at 375px viewport
2. Batch list shows warehouse-relevant statuses (scanned, not scanned, verified)
3. Per-batch scan status visible without expanding — visible at a glance
4. "Confirm Scan" Btn large and tappable; requires confirmation (no accidental fire)
5. Packing list verification status per batch (matched / mismatched / not verified)
6. Network error banner shows when offline
7. All interactive elements ≥44×44px touch target
8. All interactive elements have `data-testid`
9. No PZ, proforma, or wFirma operations from this page
10. Rollback: remove file; no restart needed

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 08 — Warehouse V2
Branch: atlas-v2/sprint-08-warehouse-v2 (create from origin/main, Sprint 07 must be merged)

STACK CONSTRAINTS — mandatory, read before any UI work:
1. Read `.claude/skills/frontend-design.md` BEFORE touching any HTML/JS
2. `.claude/skills/ui-ux-pro-max` is supplemental only — read `EJ_OVERRIDES.md` first
3. Stack: Vanilla HTML + Babel JSX. NO Vite. NO TypeScript. NO Tailwind. NO bundler.
4. Pattern file: service/app/static/proforma-v2.html
5. Shared layer: window.EstrellaShared, window.PzApi, window.PzState, window.PzComponents
6. CSS: custom properties only. Zero hardcoded hex.

TASK:
Create service/app/static/warehouse-v2.html — warehouse scan-in and packing verification.
URL: /dashboard/warehouse-v2.html
PRIMARY USER: Jigar — mobile-first design required (375px primary breakpoint)

AUTHORITY:
OWNS: scan-in workflow display, packing-list verification status, scan confirmation (explicit click)
NEVER: PZ creation, inventory reservation, consignment state, DHL, wFirma

MOBILE-FIRST RULES:
- Touch targets ≥44×44px
- Scan confirmation Btn: large, full-width on mobile
- No hover-only information
- Network-aware: "Last updated: X min ago" banner when offline

APIs (add if missing):
- GET /api/v1/warehouse/{batch_id}/status
- POST /api/v1/warehouse/{batch_id}/confirm-scan (with confirmation modal)

MANDATORY AGENT SEQUENCE:
1. system-architect — verify warehouse API availability, mobile requirement
2. gap-detection
3. reviewer-challenge
4. backend-api — add warehouse endpoints if missing (backend-safety-reviewer reviews)
5. frontend-ui — build warehouse-v2.html (mobile-first)
6. ux-flow — Jigar's workflow under warehouse conditions
7. frontend-flow-reviewer
8. testing-verification
9. test-coverage-reviewer
10. gap-hunter
11. browser-verifier — test specifically at 375px viewport
12. integration-boundary
13. git-workflow + pr-author

TEST BASELINE:
- make verify → 160/160
- tests/test_proforma_v2_contract.py → 44/44
- tests/test_carrier_*.py → 366/366

End with /deploy after PR merges.
```
