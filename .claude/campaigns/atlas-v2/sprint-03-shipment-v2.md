# Sprint 03 — Shipment V2

**Campaign:** Atlas-V2  
**Sprint:** 03 of 13  
**Branch:** `atlas-v2/sprint-03-shipment-v2`  
**Dependency:** Sprint 02 merged  
**New file:** `service/app/static/shipment-v2.html`  
**URL:** `/dashboard/shipment-v2.html?batch_id=<BATCH_ID>`

---

## Authority Boundary

```
OWNS:  shipment pipeline display, DHL tracking status, customs timeline,
       document links (SADs, ZC429, packing list — links only, no edit),
       broker/agency reply status, phase badges, carrier AWB display,
       "Go to Proforma" link, "Go to PZ" link (navigation only)
NEVER: proforma draft editing, PZ creation, wFirma writes,
       warehouse scan operations, customer master editing,
       DHL API write calls (label creation, shipment creation)
```

---

## Page Purpose

Single-shipment view: what is the current state of this shipment across the
clearance pipeline? Phase badges, DHL tracking, document status, timeline.
This replaces the timeline/documents section of `shipment-detail.html` (V1)
as the authoritative shipment pipeline view.

The page takes `?batch_id=` from URL. All state from URL — no global singletons.

---

## APIs This Page Consumes (existing, read-only)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/batch/sessions` or `GET /api/v1/batch/{batch_id}` | Batch header (AWB, carrier, status) |
| `GET /api/v1/tracking/{batch_id}` | DHL tracking events |
| `GET /api/v1/dashboard/batches/{batch_id}/readiness` | Clearance readiness + phase |
| `GET /api/v1/agents/decision/{batch_id}` | AI intelligence summary (if available) |

If batch detail endpoint (`GET /api/v1/batch/{batch_id}`) doesn't exist as a single-batch read, have `backend-api` add a read-only endpoint — or call `/api/v1/batch/sessions` and filter client-side.

---

## Component Tree

```
ShipmentV2Root
├── SessionBanner
├── BatchHeader (AWB, carrier Badge, shipment date, total_value)
├── PipelineTimeline (phase badges: Pre-check → DHL Email → SAD → Customs → Ready for PZ)
├── DhlTrackingSection (events list, last scan location, delivery estimate)
├── ClearanceSection
│   ├── StatusDot + phase label
│   ├── blocking_reasons (GateBlock if present)
│   └── document links: SAD PDF, ZC429 PDF, Packing List (all open in new tab — no edit)
├── AgencySection (if agency reply expected: status badge, last reply date)
└── QuickLinks
    ├── Btn "View Proforma" → /dashboard/proforma-v2.html?batch_id=...
    └── Btn "View PZ" → /dashboard/pz-v2.html?batch_id=... (stub if Sprint 07 not merged)
```

---

## Mandatory Agents

| Order | `subagent_type` | Purpose |
|-------|-----------------|---------|
| 1 | `chief-orchestrator` | Routing |
| 2 | `system-architect` | Verify batch detail API availability |
| 3 | `gap-detection` | Missing APIs, missing tracking fields |
| 4 | `reviewer-challenge` | Attack any plan touching V1 or adding write buttons |
| 5 | `backend-api` | Add single-batch read endpoint if needed |
| 6 | `backend-safety-reviewer` | Review any backend change |
| 7 | `frontend-ui` | Build shipment-v2.html |
| 8 | `ux-flow` | Timeline UX — operator needs to scan pipeline state quickly |
| 9 | `frontend-flow-reviewer` | Review flow |
| 10 | `testing-verification` | Tests |
| 11 | `test-coverage-reviewer` | Review tests |
| 12 | `gap-hunter` | Cross-phase |
| 13 | `browser-verifier` | Open with real batch_id, verify all sections render |
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

1. Page loads with valid `?batch_id=` — no console errors
2. Batch header shows AWB, carrier badge, shipment date
3. Pipeline timeline shows correct phase badge for current clearance state
4. DHL tracking events render in chronological order
5. Document links open in new tab (do not edit inline)
6. `blocking_reasons` GateBlock renders if present
7. "View Proforma" and "View PZ" buttons navigate correctly
8. Auth error → SessionBanner; 404 batch → EmptyState(state="error")
9. All interactive elements have `data-testid`
10. Zero write operations — this page is fully read-only
11. Rollback: remove `shipment-v2.html` from `C:\PZ\app\static\`; no restart needed

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 03 — Shipment V2
Branch: atlas-v2/sprint-03-shipment-v2 (create from origin/main, Sprint 02 must be merged first)

STACK CONSTRAINTS — mandatory, read before any UI work:
1. Read `.claude/skills/frontend-design.md` BEFORE touching any HTML/JS
2. `.claude/skills/ui-ux-pro-max` is supplemental only — read `EJ_OVERRIDES.md` first
3. Stack: Vanilla HTML + Babel JSX. NO Vite. NO TypeScript. NO Tailwind. NO bundler.
4. Pattern file: service/app/static/proforma-v2.html — follow CDN load order and IIFE structure exactly
5. Shared layer: window.EstrellaShared, window.PzApi, window.PzState, window.PzComponents
6. CSS: custom properties only. Zero hardcoded hex.

TASK:
Create service/app/static/shipment-v2.html — single-shipment pipeline view.
URL: /dashboard/shipment-v2.html?batch_id=<BATCH_ID>
No new Python route needed — served by /dashboard/{path} handler.

AUTHORITY:
OWNS: shipment pipeline, DHL tracking, customs timeline, document links (read-only), phase badges
NEVER: proforma editing, PZ creation, wFirma writes, warehouse scan, DHL write calls

COMPONENT TREE:
- BatchHeader: AWB, carrier Badge, shipment date, total_value
- PipelineTimeline: phase badges (Pre-check → DHL Email → SAD → Customs → Ready for PZ)
- DhlTrackingSection: events list, last scan location
- ClearanceSection: StatusDot + phase label + blocking_reasons GateBlock + document links (SAD PDF, ZC429 PDF, Packing List — all open new tab)
- AgencySection: agency reply status badge, last reply date
- QuickLinks: Btn "View Proforma" → proforma-v2.html?batch_id=..., Btn "View PZ" → pz-v2.html?batch_id=...

APIs (existing, read-only):
- GET /api/v1/batch/sessions (filter client-side by batch_id) OR add GET /api/v1/batch/{batch_id} read endpoint
- GET /api/v1/tracking/{batch_id}
- GET /api/v1/dashboard/batches/{batch_id}/readiness
- GET /api/v1/agents/decision/{batch_id} (AI summary if available)

MANDATORY AGENT SEQUENCE:
1. system-architect — verify which batch detail API to use
2. gap-detection — missing APIs, missing fields
3. reviewer-challenge — attack any write button or V1 file touch
4. backend-api — add read-only batch detail endpoint if needed (backend-safety-reviewer reviews)
5. frontend-ui — build shipment-v2.html
6. ux-flow — timeline UX check (operator reads pipeline state under time pressure)
7. frontend-flow-reviewer — review
8. testing-verification — tests
9. test-coverage-reviewer
10. gap-hunter
11. browser-verifier — open with real batch_id from production, verify all sections
12. integration-boundary
13. git-workflow + pr-author

TEST BASELINE — must hold before PR opens:
- make verify → 160/160
- cd service && python3 -m pytest tests/test_proforma_v2_contract.py -q → 44/44
- cd service && python3 -m pytest tests/test_carrier_*.py -q → 366/366

End with /deploy after PR merges.
```
