# Sprint 02 — Inbox V2

**Campaign:** Atlas-V2  
**Sprint:** 02 of 13  
**Branch:** `atlas-v2/sprint-02-inbox-v2`  
**Dependency:** Sprint 01 merged  
**New file:** `service/app/static/inbox-v2.html`  
**URL:** `/dashboard/inbox-v2.html`

---

## Authority Boundary

```
OWNS:  DHL clearance email inbox display, pending-customs list,
       per-shipment clearance status badges, email thread preview,
       "View shipment" link (navigates to shipment-v2 when built),
       filter pills (All / Awaiting DHL Email / SAD Pending / Action Required)
NEVER: Any write to customs docs, shipment state mutations, DHL API calls
       that modify state, email send, SAD upload, ZC429 approval
```

---

## Page Purpose

The Inbox V2 page is the operator's first view of the clearance pipeline:
which shipments are waiting on DHL emails, which have received them, which
are waiting on SADs, and which need attention. It is a **read-only** status
board sourced from existing backend endpoints.

This is NOT a customs document editor. It is a filtered view of the pipeline.

---

## APIs This Page Consumes (all existing, read-only)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/batch/sessions` | Batch list with status fields |
| `GET /api/v1/dashboard/batches/{batch_id}/readiness` | Per-batch clearance readiness |
| `GET /api/v1/tracking/{batch_id}` | DHL tracking + email status |

If any of these do not return inbox-compatible data (missing `clearance_status` field, missing `dhl_email_received` flag), the backend-api agent must add a **read-only** response field to the existing endpoint — no schema changes, no new route files.

---

## Shared Layer Extensions (if needed)

- `pz-api.js`: add `getInboxItems(filters)` — calls `/api/v1/batch/sessions` with clearance filter params
- `pz-state.js`: add `useInboxItems(filters)` hook
- No `dashboard-shared.js` changes (no domain knowledge)

---

## Mandatory Agents

| Order | `subagent_type` | Purpose |
|-------|-----------------|---------|
| 1 | `chief-orchestrator` | Routing |
| 2 | `system-architect` | Verify authority boundary, check API availability |
| 3 | `gap-detection` | Missing APIs, missing backend fields |
| 4 | `reviewer-challenge` | Attack any plan that reaches into customs-write territory |
| 5 | `backend-api` | Add read-only fields to existing endpoints if needed |
| 6 | `backend-safety-reviewer` | Verify no unsafe writes in any new backend code |
| 7 | `frontend-ui` | Build inbox-v2.html (frontend-design.md override in effect) |
| 8 | `frontend-flow-reviewer` | Review page flow |
| 9 | `testing-verification` | Tests for new endpoint fields + page |
| 10 | `test-coverage-reviewer` | Review test quality |
| 11 | `gap-hunter` | Cross-phase contradictions |
| 12 | `browser-verifier` | Open page, verify filter pills work, verify status badges correct |
| 13 | `integration-boundary` | Verify API calls wired end-to-end |
| 14 | `git-workflow` | Commit |
| 15 | `pr-author` | PR |

---

## Test Baseline

```bash
make verify                 # 160/160
cd service && python3 -m pytest tests/test_proforma_v2_contract.py -q  # 44/44
cd service && python3 -m pytest tests/test_carrier_*.py -q             # 366/366
```

Sprint adds: tests for any new backend endpoint fields; DOM-testid assertions.

---

## Acceptance Criteria

1. Page loads at `/dashboard/inbox-v2.html` — no console errors, no 4xx on load
2. Filter pills render: All / Awaiting DHL Email / SAD Pending / Action Required
3. Selecting a filter updates the list without page reload
4. Each row shows: batch_id, AWB, status Badge, timestamp of last DHL email, "View" Btn
5. Empty state shown when filter returns no results
6. "View" Btn links to shipment-v2.html (stub link acceptable if Sprint 03 not yet merged)
7. Auth error → `SessionBanner`; network error → `SessionBanner`
8. All interactive elements have `data-testid`
9. Zero writes to any backend from this page
10. Rollback: remove `inbox-v2.html` from `C:\PZ\app\static\`; no service restart needed

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 02 — Inbox V2
Branch: atlas-v2/sprint-02-inbox-v2 (create from origin/main, Sprint 01 must be merged first)

STACK CONSTRAINTS — mandatory, read before any UI work:
1. Read `.claude/skills/frontend-design.md` BEFORE touching any HTML/JS
2. `.claude/skills/ui-ux-pro-max` is supplemental only — read `EJ_OVERRIDES.md` first
3. Stack: Vanilla HTML + Babel JSX. NO Vite. NO TypeScript. NO Tailwind. NO bundler.
4. Pattern file: service/app/static/proforma-v2.html — follow CDN load order and IIFE structure exactly
5. Shared layer: window.EstrellaShared, window.PzApi, window.PzState, window.PzComponents
6. CSS: custom properties only (--bg, --text, --badge-*, --accent). Zero hardcoded hex.

TASK:
Create service/app/static/inbox-v2.html — the clearance pipeline inbox.
URL: /dashboard/inbox-v2.html (no new Python route needed — served by existing /dashboard/{path} handler)

AUTHORITY:
OWNS: DHL clearance email inbox display, pending-customs list, per-shipment clearance status badges, filter pills (All / Awaiting DHL Email / SAD Pending / Action Required), email thread preview (read-only), "View shipment" link
NEVER: customs state mutations, DHL API calls that modify state, email send, SAD upload, ZC429 approval, any write action

PAGE STRUCTURE:
- PageHeader (h1: "Clearance Inbox", subtitle: "Pending customs items")
- FilterBar: filter pills for status (All / Awaiting DHL Email / SAD Pending / Action Required)
- InboxList: rows using CompactTable — columns: Batch ID, AWB, Status (Badge), Last Email, Action
- EmptyState when filter returns nothing
- SessionBanner for auth/network errors

APIs to use (existing, read-only):
- GET /api/v1/batch/sessions — batch list
- GET /api/v1/dashboard/batches/{batch_id}/readiness — per-batch status
If existing endpoints lack clearance_status or dhl_email_received fields, have backend-api add read-only response fields to the EXISTING endpoint — no new route files.

MANDATORY AGENT SEQUENCE:
1. system-architect — verify API availability, check what fields exist
2. gap-detection — missing API fields, missing backend data
3. reviewer-challenge — attack any plan that adds write buttons or customs mutations
4. backend-api — add read-only fields if needed (backend-safety-reviewer reviews any backend change)
5. frontend-ui — build inbox-v2.html
6. frontend-flow-reviewer — review
7. testing-verification — tests for new fields + page
8. test-coverage-reviewer — review tests
9. gap-hunter — cross-phase check
10. browser-verifier — open page, verify filters and status badges
11. integration-boundary — verify API wiring
12. git-workflow + pr-author — commit and PR

TEST BASELINE — must hold before PR opens:
- make verify → 160/160
- cd service && python3 -m pytest tests/test_proforma_v2_contract.py -q → 44/44
- cd service && python3 -m pytest tests/test_carrier_*.py -q → 366/366

End with /deploy after PR merges.
```
