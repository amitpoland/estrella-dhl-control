# Wave-3 Build Record: /automation → Action Center (R-Q2)

**Date:** 2026-07-04
**Branch:** deploy/latest
**Sub-slice:** (a) R-Q2 automation → Action Center
**Criterion 10 (control matrix gate):** PASS — Wireframe-Required Missing = 0

---

## Summary

Promoted `ActionCenterPage` from hardcoded mock stub to the `/automation` route
authority per R-Q2 ruling: "Action Center is operator authority; AI Bridge is
backend capability." Wire: `GET /api/v1/action-proposals` (routes_action_proposals.py
prefix `/api/v1/action-proposals`) loads pending proposals cross-batch. AI Bridge
surfaced as a right-rail link/panel (backend capability, not a separate page).

---

## Files Changed

| File | Change |
|---|---|
| `service/app/static/v2/wireframe-update.jsx` | ActionCenterPage: hardcoded mock → live `PzApi.listBatches()` + `apiFetch(/api/v1/action-proposals/{batch_id})` |
| `service/app/static/v2/index.html` | Automation route: `AiBridgePage` → `ActionCenterPage`; title "Automation Center" → "Action Center"; comment updated to R-Q2 cite |

---

## Control Matrix

| Census ID | Control | Disposition | Authority |
|---|---|---|---|
| R-Q2 | /automation slug | WIRED — ActionCenterPage mounted as operator authority | routes_action_proposals.py `/api/v1/action-proposals` |
| R-Q2 | AI Bridge access | NAVIGATE — right-rail panel links to AI Bridge status | pages-v2.jsx AiBridgePage (backend capability) |
| AC-WF-1 | Pending proposals queue | LIVE — cross-batch proposals via existing endpoints | `GET /api/v1/action-proposals/{batch_id}` |
| AC-WF-2 | Approval policy | STATIC — policy text (correct, no backend needed) | N/A (policy display) |
| AC-WF-3 | Today stats rail | HONEST-GATED — shows `—` (daily aggregate not exposed) | Backend Required |

Wireframe-Required Missing = **0** — criterion 10 PASS.

---

## Backend Truth Citations

| Control | Endpoint | Route file | Verified |
|---|---|---|---|
| Proposals queue | `GET /api/v1/action-proposals` | `routes_action_proposals.py:45` prefix | EXISTING endpoint, no new routes |
| Batch list | `GET /api/v1/dashboard/batches` | `routes_dashboard.py` | `PzApi.listBatches()` existing |

---

## R-Q2 Compliance

Rule: "/automation -> Action Center -> AI Bridge. AI Bridge is backend capability;
Action Center is the operator authority."

Implementation:
- `/automation` slug → `ActionCenterPage` (this page, operator-facing queue)
- AI Bridge reachable via right-rail panel linking to AI Bridge status
- No duplicate AI Bridge route created
- `AiBridgePage` still accessible via `intelligence` → `Setup` → `Automation` sub-tab (Lesson-M: capability preserved, relocated behind Action Center, not removed)

Lesson-M note: `AiBridgePage` was the prior `/automation` mount. It is now reachable as
a sub-surface from Action Center's right rail. The capability is NOT removed — it is
relocated per R-Q2 operator ruling (legitimate relocation; cancellation documented in
DECISIONS.md R-Q2 entry 2026-07-04).

---

## Tree Count

**Before / After (modified tracked files):** 11 / 11 (no new tracked files added)
