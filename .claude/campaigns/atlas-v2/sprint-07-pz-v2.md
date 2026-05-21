# Sprint 07 — PZ V2

**Campaign:** Atlas-V2  
**Sprint:** 07 of 13  
**Branch:** `atlas-v2/sprint-07-pz-v2`  
**Dependency:** Sprint 06 merged (product mapping must be stable first)  
**New file:** `service/app/static/pz-v2.html`  
**URL:** `/dashboard/pz-v2.html?batch_id=<BATCH_ID>`

---

## Authority Boundary

```
OWNS:  PZ lifecycle display: readiness → run → wFirma reservation preview → PZ create,
       warehouse audit gate status display, wFirma reservation preview (read-only),
       PZ adopt / refresh mapping display, PZ document status Badge
NEVER: proforma draft editing, customer authority editing, DHL clearance,
       direct wFirma writes bypassing existing _guard_wfirma_export gate,
       any action that sets WFIRMA_CREATE_PZ=True in config,
       fiscal gate modification
```

---

## Page Purpose

The PZ lifecycle page for a single batch. Shows the gated pipeline:
is the batch ready for PZ? What is the wFirma reservation status?
Has the PZ been created? What is the PZ document ID?

**Critical rule:** This page MUST NOT unlock `WFIRMA_CREATE_PZ=True` or any
other fiscal gate. The `_guard_wfirma_export` check in the backend MUST be
respected. Every PZ creation button calls the existing gated backend endpoint —
it does not call wFirma directly.

---

## APIs This Page Consumes (existing)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/v1/dashboard/batches/{batch_id}/readiness` | Read | PZ prerequisite gate status |
| `GET /api/v1/wfirma/shipment/{batch_id}/setup-detail` | Read | Product + customer mapping status |
| `GET /api/v1/batch/{batch_id}/pz-status` | Read | Current PZ document state |
| `POST /api/v1/execute/pz/{batch_id}` | Write (gated) | Trigger PZ creation (gated by backend) |

If `GET /api/v1/batch/{batch_id}/pz-status` does not exist, `backend-api` adds it as a
read-only endpoint returning `{ pz_doc_id, pz_status, created_at }` from `documents.db`.

**PZ creation button is the critical write.** It calls the existing gated endpoint only.
The backend owns the gate — the UI cannot bypass it.

---

## Write Safety Rules (non-negotiable — `backend-safety-reviewer` blocks any violation)

- "Run PZ" Btn fires `POST /api/v1/execute/pz/{batch_id}` only
- Button disabled if `proforma.ready = false` OR `export_blockers` present
- Button disabled reason shown: "Blocked: [reason list]"
- PZ creation confirmation modal required before POST
- No `WFIRMA_CREATE_PZ` flag toggle from UI — ever
- `_guard_wfirma_export` backend check must still block if gate is closed

---

## Mandatory Agents

| Order | `subagent_type` | Purpose |
|-------|-----------------|---------|
| 1 | `chief-orchestrator` | Routing |
| 2 | `system-architect` | Verify PZ gate pattern, confirm backend guard still intact |
| 3 | `gap-detection` | Missing PZ status endpoint |
| 4 | `reviewer-challenge` | **Aggressively** attack any plan that bypasses `_guard_wfirma_export` |
| 5 | `backend-api` | Add read-only PZ status endpoint if needed |
| 6 | `backend-safety-reviewer` | **Mandatory** — verify write gate is truly gated |
| 7 | `security-permissions` | Verify no new fiscal gate bypass |
| 8 | `frontend-ui` | Build pz-v2.html |
| 9 | `frontend-flow-reviewer` | Review |
| 10 | `testing-verification` | Tests including disabled-state and gate tests |
| 11 | `test-coverage-reviewer` | Review |
| 12 | `gap-hunter` | Cross-phase |
| 13 | `browser-verifier` | Open page — specifically verify "Run PZ" is disabled when gate closed |
| 14 | `integration-boundary` | API wiring |
| 15 | `git-workflow` + `pr-author` | Commit + PR |

---

## Test Baseline

```bash
make verify                 # 160/160
cd service && python3 -m pytest tests/test_proforma_v2_contract.py -q  # 44/44
cd service && python3 -m pytest tests/test_carrier_*.py -q             # 366/366
```

Sprint adds: gate-state test (Run PZ button disabled when `export_blockers` present).

---

## Acceptance Criteria

1. Page loads with valid `?batch_id=` — no console errors
2. PZ readiness gate renders — shows `blocking_reasons` (red), `export_blockers` (amber), or "Ready for PZ" (green)
3. "Run PZ" Btn disabled when gate closed; disabled reason visible
4. "Run PZ" Btn enabled only when all gates green; opens confirmation modal
5. After PZ creation: PZ document ID shown with Badge "PZ Created"
6. wFirma reservation preview section shows product/customer mapping status
7. `_guard_wfirma_export` backend check still blocks when gate is closed (test this in browser)
8. No `WFIRMA_CREATE_PZ` toggle anywhere on page
9. All interactive elements have `data-testid`
10. Rollback: remove file; no restart needed

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 07 — PZ V2
Branch: atlas-v2/sprint-07-pz-v2 (create from origin/main, Sprint 06 must be merged)

STACK CONSTRAINTS — mandatory, read before any UI work:
1. Read `.claude/skills/frontend-design.md` BEFORE touching any HTML/JS
2. `.claude/skills/ui-ux-pro-max` is supplemental only — read `EJ_OVERRIDES.md` first
3. Stack: Vanilla HTML + Babel JSX. NO Vite. NO TypeScript. NO Tailwind. NO bundler.
4. Pattern file: service/app/static/proforma-v2.html
5. Shared layer: window.EstrellaShared, window.PzApi, window.PzState, window.PzComponents
6. CSS: custom properties only. Zero hardcoded hex.

TASK:
Create service/app/static/pz-v2.html — PZ lifecycle display and gated PZ creation.
URL: /dashboard/pz-v2.html?batch_id=<BATCH_ID>

AUTHORITY:
OWNS: PZ readiness gate display, wFirma reservation preview (read-only), PZ create (gated), PZ status
NEVER: proforma editing, customer editing, DHL, WFIRMA_CREATE_PZ flag toggle, _guard_wfirma_export bypass

CRITICAL SAFETY RULE:
The "Run PZ" button calls POST /api/v1/execute/pz/{batch_id} ONLY.
This endpoint is already gated by _guard_wfirma_export in the backend.
The UI may NOT bypass this gate. The UI may NOT enable WFIRMA_CREATE_PZ from a UI toggle.
backend-safety-reviewer MUST verify this before PR opens.

APIs:
- GET /api/v1/dashboard/batches/{batch_id}/readiness
- GET /api/v1/wfirma/shipment/{batch_id}/setup-detail
- GET /api/v1/batch/{batch_id}/pz-status (add if missing — read-only)
- POST /api/v1/execute/pz/{batch_id} (gated write — confirmation modal required)

MANDATORY AGENT SEQUENCE:
1. system-architect — verify PZ gate pattern
2. gap-detection
3. reviewer-challenge — aggressively attack any fiscal gate bypass
4. backend-api — add pz-status endpoint if missing
5. backend-safety-reviewer — MANDATORY, verify _guard_wfirma_export still intact
6. security-permissions
7. frontend-ui — build pz-v2.html
8. frontend-flow-reviewer
9. testing-verification — include gate-closed test (Run PZ disabled)
10. test-coverage-reviewer
11. gap-hunter
12. browser-verifier — specifically verify Run PZ disabled when gate closed
13. integration-boundary
14. git-workflow + pr-author

TEST BASELINE:
- make verify → 160/160
- tests/test_proforma_v2_contract.py → 44/44
- tests/test_carrier_*.py → 366/366

End with /deploy after PR merges.
```
