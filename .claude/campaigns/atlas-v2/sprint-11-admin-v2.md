# Sprint 11 — Admin V2

**Campaign:** Atlas-V2  
**Sprint:** 11 of 13  
**Branch:** `atlas-v2/sprint-11-admin-v2`  
**Dependency:** Sprint 10 merged  
**New file:** `service/app/static/admin-v2.html`  
**URL:** `/dashboard/admin-v2.html`

---

## Authority Boundary

```
OWNS:  user management (list, add, edit roles, disable),
       runtime flags display (read-only — no toggles for fiscal flags),
       email queue status (read-only view),
       system health summary (read from /api/v1/health)
NEVER: WFIRMA_CREATE_* flag toggling from UI,
       self-clearance admin flag toggling without operator confirmation,
       user password changes that bypass auth route,
       any fiscal gate modification
```

---

## Critical Rule: Runtime Flags

The admin page shows runtime flag state (from `GET /api/v1/admin/self-clearance`)
**read-only**. It does NOT expose a toggle for `WFIRMA_CREATE_PZ`, `WFIRMA_CREATE_INVOICE`,
or any other fiscal flag. The one exception: the `self-clearance` P4/P5 kill-switch
toggle (which calls `POST /api/v1/admin/self-clearance`) is allowed but requires
operator confirmation with a typed-confirmation modal before firing.

---

## APIs This Page Consumes

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/v1/auth/users` | Read | User list |
| `PUT /api/v1/auth/users/{id}` | Write | Edit user role / disable |
| `POST /api/v1/auth/signup` | Write | Create new user |
| `GET /api/v1/admin/email-queue` | Read | Email queue status |
| `GET /api/v1/admin/self-clearance` | Read | Self-clearance runtime flags |
| `POST /api/v1/admin/self-clearance` | Write (gated) | Toggle self-clearance kill-switch only |
| `GET /api/v1/health` | Read | System health |

---

## Mandatory Agents

| Order | `subagent_type` | Purpose |
|-------|-----------------|---------|
| 1 | `chief-orchestrator` | Routing |
| 2 | `system-architect` | Verify admin routes, runtime flag boundaries |
| 3 | `gap-detection` | Missing admin endpoints |
| 4 | `reviewer-challenge` | Attack any plan exposing fiscal flag toggles |
| 5 | `security-permissions` | Verify admin routes are auth-gated |
| 6 | `backend-safety-reviewer` | Review all write paths |
| 7 | `frontend-ui` | Build admin-v2.html |
| 8 | `frontend-flow-reviewer` | Review |
| 9 | `testing-verification` | Tests |
| 10 | `test-coverage-reviewer` | Review |
| 11 | `gap-hunter` | Cross-phase |
| 12 | `browser-verifier` | Open page, verify user management + flag read-only display |
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

1. User list loads (admin role required)
2. "Add User" form → "Create User" Btn fires POST /signup
3. "Edit User" → role dropdown → "Save Role" Btn fires PUT
4. "Disable User" Btn → confirmation modal → fires PUT with active=false
5. Email queue table shows read-only status
6. Runtime flags section shows flag values — read-only labels, no toggles (except self-clearance kill-switch)
7. Self-clearance kill-switch toggle requires typed confirmation ("CONFIRM" must be typed)
8. Health status shows from /api/v1/health
9. No WFIRMA_CREATE_* toggle anywhere
10. Rollback: remove file; no restart needed

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 11 — Admin V2
Branch: atlas-v2/sprint-11-admin-v2 (create from origin/main, Sprint 10 must be merged)

STACK CONSTRAINTS — mandatory, read before any UI work:
1. Read `.claude/skills/frontend-design.md` BEFORE touching any HTML/JS
2. `.claude/skills/ui-ux-pro-max` is supplemental only — read `EJ_OVERRIDES.md` first
3. Stack: Vanilla HTML + Babel JSX. NO Vite. NO TypeScript. NO Tailwind. NO bundler.
4. Pattern file: service/app/static/proforma-v2.html
5. Shared layer: window.EstrellaShared, window.PzApi, window.PzState, window.PzComponents
6. CSS: custom properties only. Zero hardcoded hex.

TASK:
Create service/app/static/admin-v2.html — user management and system admin page.
URL: /dashboard/admin-v2.html

AUTHORITY:
OWNS: user CRUD, runtime flags display (read-only mostly), email queue status, health summary
NEVER: WFIRMA_CREATE_* toggling from UI, fiscal gate modification, password changes outside auth route

CRITICAL RULE:
Runtime flags are displayed READ-ONLY. The ONLY toggle allowed is the self-clearance kill-switch
(POST /api/v1/admin/self-clearance) and it requires a typed confirmation modal before firing.
NO WFIRMA_CREATE_PZ or WFIRMA_CREATE_INVOICE toggle — ever.

MANDATORY AGENT SEQUENCE:
1. system-architect — runtime flag boundaries
2. gap-detection
3. reviewer-challenge — attack any fiscal flag toggle
4. security-permissions — verify admin routes are auth-gated
5. backend-safety-reviewer
6. frontend-ui
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
