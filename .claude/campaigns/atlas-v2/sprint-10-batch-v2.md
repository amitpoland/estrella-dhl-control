# Sprint 10 — Batch V2

**Campaign:** Atlas-V2  
**Sprint:** 10 of 13  
**Branch:** `atlas-v2/sprint-10-batch-v2`  
**Dependency:** Sprint 09 merged  
**New file:** `service/app/static/batch-v2.html`  
**URL:** `/dashboard/batch-v2.html`

---

## Authority Boundary

```
OWNS:  batch creation (new batch from chat_id/AWB), batch list with status,
       batch status overview, linked shipments per batch,
       "Cancel batch" button (gated, confirmation required),
       cross-batch search and filter
NEVER: shipment editing, proforma drafts, PZ creation, customs,
       DHL label creation, customer master editing, product mapping
```

---

## Page Purpose

Batch management: create new batches, see all batches and their pipeline
status, cancel a batch. This is a management surface — not a per-shipment
detail view (that's shipment-v2.html) and not an aggregation dashboard
(that's dashboard-v2.html in Sprint 13).

---

## APIs This Page Consumes

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/v1/batch/sessions` | Read | Batch list |
| `POST /api/v1/batch/start` | Write | Create new batch |
| `POST /api/v1/batch/cancel` | Write (gated) | Cancel a batch |
| `GET /api/v1/batch/status/{chat_id}` | Read | Single batch status |

---

## Mandatory Agents

| Order | `subagent_type` | Purpose |
|-------|-----------------|---------|
| 1 | `chief-orchestrator` | Routing |
| 2 | `system-architect` | Verify batch lifecycle API |
| 3 | `gap-detection` | Missing endpoints |
| 4 | `reviewer-challenge` | Attack any plan touching shipment editing |
| 5 | `backend-api` | Add endpoints if needed |
| 6 | `backend-safety-reviewer` | Review cancel write path |
| 7 | `frontend-ui` | Build batch-v2.html |
| 8 | `frontend-flow-reviewer` | Review |
| 9 | `testing-verification` | Tests |
| 10 | `test-coverage-reviewer` | Review |
| 11 | `gap-hunter` | Cross-phase |
| 12 | `browser-verifier` | Open page, test batch list + cancel flow |
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

1. Batch list loads with status badges, AWB, creation date, linked shipment count
2. Search/filter by status works
3. "Create New Batch" form: AWB + optional chat_id; "Start Batch" Btn fires POST
4. "Cancel Batch" requires confirmation modal; fires POST /cancel; updates list
5. Click batch row → links to shipment-v2.html?batch_id=...
6. All interactive elements have `data-testid`
7. No shipment editing, no proforma, no PZ
8. Rollback: remove file; no restart needed

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 10 — Batch V2
Branch: atlas-v2/sprint-10-batch-v2 (create from origin/main, Sprint 09 must be merged)

STACK CONSTRAINTS — mandatory, read before any UI work:
1. Read `.claude/skills/frontend-design.md` BEFORE touching any HTML/JS
2. `.claude/skills/ui-ux-pro-max` is supplemental only — read `EJ_OVERRIDES.md` first
3. Stack: Vanilla HTML + Babel JSX. NO Vite. NO TypeScript. NO Tailwind. NO bundler.
4. Pattern file: service/app/static/proforma-v2.html
5. Shared layer: window.EstrellaShared, window.PzApi, window.PzState, window.PzComponents
6. CSS: custom properties only. Zero hardcoded hex.

TASK:
Create service/app/static/batch-v2.html — batch management page.
URL: /dashboard/batch-v2.html

AUTHORITY:
OWNS: batch creation, batch list + status, cancel batch (gated)
NEVER: shipment editing, proforma, PZ, customs, DHL label, customer/product editing

APIs:
- GET /api/v1/batch/sessions
- POST /api/v1/batch/start
- POST /api/v1/batch/cancel (confirmation modal required)
- GET /api/v1/batch/status/{chat_id}

MANDATORY AGENT SEQUENCE:
1. system-architect
2. gap-detection
3. reviewer-challenge
4. backend-api + backend-safety-reviewer
5. frontend-ui
6. frontend-flow-reviewer
7. testing-verification
8. test-coverage-reviewer
9. gap-hunter
10. browser-verifier
11. integration-boundary
12. git-workflow + pr-author

TEST BASELINE:
- make verify → 160/160
- tests/test_proforma_v2_contract.py → 44/44
- tests/test_carrier_*.py → 366/366

End with /deploy after PR merges.
```
