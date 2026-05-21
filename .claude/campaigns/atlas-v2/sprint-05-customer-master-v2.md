# Sprint 05 — Customer Master V2

**Campaign:** Atlas-V2  
**Sprint:** 05 of 13  
**Branch:** `atlas-v2/sprint-05-customer-master-v2`  
**Dependency:** Sprint 04 merged  
**New file:** `service/app/static/customer-master-v2.html`  
**URL:** `/dashboard/customer-master-v2.html` (list) or `?contractor_id=<ID>` (detail)

---

## Authority Boundary

```
OWNS:  customer CRUD (name, NIP, address, payment method, email),
       wFirma customer ID mapping display + "Save Customer Mapping" write,
       bill_to / ship_to defaults, customer list with search/filter,
       "Sync from wFirma" button (calls existing preview + apply endpoints)
NEVER: proforma drafts, PZ lifecycle, product mapping,
       DHL, warehouse, customs, fiscal gate modification
```

---

## Page Purpose

The authoritative customer identity management page. Replaces the
`CustomerMasterCard` scattered across `shipment-detail.html`.
Operators can manage all customers in one place instead of hunting
through per-shipment panels.

This is the first V2 page with a **write surface** — every write button
labels exactly what it writes, confirmation is required for destructive
actions.

---

## APIs This Page Consumes (existing)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/v1/customer-master` | Read | List all customers |
| `GET /api/v1/customer-master/{contractor_id}` | Read | Single customer detail |
| `PUT /api/v1/customer-master/{contractor_id}` | Write | Save customer (name, NIP, address, mapping) |
| `GET /api/v1/customer-master/sync-from-wfirma/preview` | Read | Preview wFirma sync diff |
| `POST /api/v1/customer-master/sync-from-wfirma/apply` | Write | Apply wFirma sync |
| `GET /api/v1/customer-master/dictionaries` | Read | wFirma customer options for mapping |

All routes exist. No new backend code expected.

---

## Write Safety Rules (enforced by `backend-safety-reviewer`)

- Every PUT call requires explicit "Save Customer Master" Btn click
- No auto-save on blur or field change
- "Sync from wFirma" requires two-step: "Preview Sync" first, then "Apply Sync" with confirmation
- No wFirma write flag unlocked by this page

---

## Shared Layer Extensions

- `pz-api.js`: add `listCustomers(params)`, `getCustomer(id)`, `saveCustomer(id, body)`, `previewWfirmaSync()`, `applyWfirmaSync()`
- `pz-state.js`: add `useCustomerList(params)`, `useCustomerDetail(id)` hooks

---

## Mandatory Agents

| Order | `subagent_type` | Purpose |
|-------|-----------------|---------|
| 1 | `chief-orchestrator` | Routing |
| 2 | `system-architect` | Verify write gate pattern, confirm no new wFirma flags |
| 3 | `gap-detection` | Missing API fields |
| 4 | `reviewer-challenge` | Attack any plan that unlocks wFirma writes beyond existing gates |
| 5 | `security-permissions` | Verify write buttons are gated correctly |
| 6 | `frontend-ui` | Build customer-master-v2.html |
| 7 | `backend-safety-reviewer` | Review all write paths |
| 8 | `ux-flow` | Two-step sync UX, form usability |
| 9 | `frontend-flow-reviewer` | Review |
| 10 | `testing-verification` | Tests: write paths, disabled states |
| 11 | `test-coverage-reviewer` | Review |
| 12 | `gap-hunter` | Cross-phase |
| 13 | `browser-verifier` | Open page, test list + detail + save + sync preview |
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

1. Customer list loads with search/filter — no console errors
2. Click row → detail view with all fields populated from API
3. Edit fields → "Save Customer Master" Btn is the only write trigger (no auto-save)
4. Save → success Toast; error → error Toast with message
5. "Preview Sync from wFirma" shows diff table before any apply
6. "Apply Sync" fires only after operator confirms preview; success Toast
7. NIP field validated (format check, not blank on save)
8. All interactive elements have `data-testid`
9. No new wFirma write flags unlocked
10. Rollback: remove file; no restart needed

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 05 — Customer Master V2
Branch: atlas-v2/sprint-05-customer-master-v2 (create from origin/main, Sprint 04 must be merged)

STACK CONSTRAINTS — mandatory, read before any UI work:
1. Read `.claude/skills/frontend-design.md` BEFORE touching any HTML/JS
2. `.claude/skills/ui-ux-pro-max` is supplemental only — read `EJ_OVERRIDES.md` first
3. Stack: Vanilla HTML + Babel JSX. NO Vite. NO TypeScript. NO Tailwind. NO bundler.
4. Pattern file: service/app/static/proforma-v2.html
5. Shared layer: window.EstrellaShared, window.PzApi, window.PzState, window.PzComponents
6. CSS: custom properties only. Zero hardcoded hex.

TASK:
Create service/app/static/customer-master-v2.html
URL: /dashboard/customer-master-v2.html (list) or ?contractor_id=<ID> (detail)

AUTHORITY:
OWNS: customer CRUD, wFirma customer ID mapping, sync from wFirma (two-step)
NEVER: proforma, PZ, products, DHL, wFirma write flags beyond existing gates

WRITE SAFETY RULES:
- Every PUT requires explicit "Save Customer Master" Btn — no auto-save
- wFirma sync: "Preview Sync" first (read-only), then "Apply Sync" requires operator confirmation
- No new wFirma write flags unlocked

APIs (all existing):
- GET/PUT /api/v1/customer-master/{contractor_id}
- GET /api/v1/customer-master/sync-from-wfirma/preview
- POST /api/v1/customer-master/sync-from-wfirma/apply
- GET /api/v1/customer-master/dictionaries

Add to pz-api.js: listCustomers, getCustomer, saveCustomer, previewWfirmaSync, applyWfirmaSync
Add to pz-state.js: useCustomerList, useCustomerDetail hooks

MANDATORY AGENT SEQUENCE:
1. system-architect — verify write gate pattern
2. gap-detection — missing fields
3. reviewer-challenge — attack any plan unlocking new wFirma write flags
4. security-permissions — verify write buttons gated correctly
5. frontend-ui — build customer-master-v2.html
6. backend-safety-reviewer — review all write paths
7. ux-flow — two-step sync UX check
8. frontend-flow-reviewer
9. testing-verification — especially write paths and disabled states
10. test-coverage-reviewer
11. gap-hunter
12. browser-verifier — test list, detail, save, preview sync
13. integration-boundary
14. git-workflow + pr-author

TEST BASELINE:
- make verify → 160/160
- tests/test_proforma_v2_contract.py → 44/44
- tests/test_carrier_*.py → 366/366

End with /deploy after PR merges.
```
