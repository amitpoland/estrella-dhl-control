---
name: backend-route-and-service-builder
description: Read-only / plan-only skill that inspects existing FastAPI routes and services, then proposes exact implementation plans for new route+service pairs following established project patterns. Does not create or modify code.
triggers:
  - plan new route
  - plan new endpoint
  - propose service structure
  - scaffold route plan
  - design API endpoint
tools:
  - Read
  - Bash(find:*)
  - Bash(grep:*)
  - Bash(ls:*)
---

# Backend Route & Service Builder (Plan-Only)

Read-only skill that inspects existing FastAPI route and service patterns, then generates detailed implementation plans for new route+service pairs. Does not write or edit any code.

## Purpose

Produce a complete, copy-paste-ready implementation plan for a new API endpoint and its backing service, following the project's established conventions for authentication, guards, timeline logging, error handling, and response structure.

## When to Use

- Planning a new API endpoint with its service layer.
- Designing a new route file following existing patterns.
- Reviewing what conventions a new service should follow (guards, timeline, auth).
- Comparing existing route structures to identify the correct pattern for a new feature.

## When NOT to Use

- Actually creating or editing route/service files — this skill is plan-only in this phase.
- Fixing bugs in existing routes — edit directly.
- Working on frontend/dashboard HTML — use `dashboard-ui-consistency`.
- Modifying core infrastructure (`guards.py`, `timeline.py`, `config.py`).
- Creating test files.
- Any customs/financial data work — use `customs-pz-safety-checker`.

## Workflow

1. **Understand the request** — clarify what the new endpoint should do, which HTTP method, what input/output it needs.
2. **Inspect existing patterns** — read 2–3 similar route files in `app/api/` to identify the project's conventions:
   - Authentication pattern (cookie-based JWT via `pz_session`).
   - Guard usage (which guards are called, in what order).
   - Timeline logging (which events are logged, with what payload).
   - Error response structure (`HTTPException` with structured detail).
   - Response format (dict with `ok`, status codes).
3. **Inspect existing services** — read the corresponding service files in `app/services/` to understand:
   - Function signature conventions.
   - How audit files are read and written (`write_json_atomic` pattern).
   - How validation is structured.
   - Import patterns.
4. **Check for conflicts** — verify the proposed route path does not collide with existing routes.
5. **Generate plan** — produce a structured implementation plan with:
   - Proposed file paths.
   - Exact function signatures.
   - Required imports.
   - Guard calls needed.
   - Timeline events to log.
   - Error cases to handle.
   - Code outline (pseudocode or skeleton, not executable).
6. **Present for review** — output the plan for user approval. Do not create files.

## Safety Rules

- This skill is strictly read-only. It never creates, edits, or deletes any file.
- It never writes to `app/api/`, `app/services/`, or any other directory.
- It never starts servers or executes application code.
- It does not read or log credentials, tokens, or secrets.
- Generated plans must always include auth checks, guard calls, and timeline logging — never propose routes that bypass these.
- Generated plans must never propose routes that directly write to `FORBIDDEN_FIELDS`.
- This skill will be upgraded to write-capable in a future phase after validation.

## Output Format

```
## Route & Service Implementation Plan
- **Endpoint:** METHOD /api/v1/path
- **Route file:** app/api/routes_<name>.py (new / existing)
- **Service file:** app/services/<name>.py (new / existing)
- **Auth:** (required / optional / none)
- **Guards:** (list of guard_* calls)
- **Timeline events:** (list of events to log)
- **Input schema:** (fields and types)
- **Output schema:** (fields and types)
- **Error cases:** (numbered list)
- **Code outline:** (skeleton with comments)
- **Status:** PLAN ONLY — do not implement without approval
```
