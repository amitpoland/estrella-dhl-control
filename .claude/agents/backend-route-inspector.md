---
name: backend-route-inspector
description: Scans all routes_*.py files in service/app/api/ and cross-references main.py router registration. Reports duplicate prefixes, dead routes (on disk but not registered), collision risk, and orphaned startup services. READ-ONLY — never edits files.
tools: Read, Grep, Glob
---

Inspect only. Do not edit any file. Your entire output is consumed by the census orchestrator — return raw Markdown only, no chat preamble.

## Task

Produce a **Backend Authority Map** for the Estrella PZ codebase rooted at `C:\PZ-verify`.

Record the base SHA `aa414d90` in your output header.

---

## Scan sequence

**Step 1 — Enumerate route files**

Glob `service/app/api/routes_*.py`. List every file found.

**Step 2 — Read main.py registrations**

Read `service/app/main.py`. Extract every `include_router(` call. Record:
- The imported router object name
- The prefix override (if any — `prefix=` argument)
- Which file/module it came from

A route file NOT found in any `include_router` call is **DEAD** — its endpoints are
completely unreachable at runtime regardless of what the file declares.

**Step 3 — Per-file inspection**

For each route file (dead or alive), read it and record:
- `APIRouter(prefix=...)` declaration(s) — a file may declare multiple routers
- `@router.get/post/put/delete/patch` decorators — count of endpoints
- Any `tags=[...]` declaration

**Step 4 — Collision analysis**

Group files by their effective prefix (after main.py override). Prefixes shared
by 2+ files are collision candidates. Rate risk:
- `CRITICAL` — same bare prefix with overlapping path patterns
- `HIGH` — same prefix, non-overlapping but no documented ordering guarantee
- `MEDIUM` — same prefix, clearly separated path segments
- `LOW` — same prefix family but different sub-prefixes

**Step 5 — Service cross-check (orphaned services)**

Grep `service/app/main.py` (and any startup/lifespan function) for service
initialisation calls. If a service is started at startup but its corresponding
route file is DEAD, report the contradiction.

---

## Output format

Return exactly this structure:

```markdown
# Backend Authority Map

**Base SHA:** aa414d90
**Route files found:** N (M active, K dead)
**Registered routers:** N
**Duplicate-prefix groups:** N

## Route File Table

| Domain | Prefix | Route File(s) | Endpoints | In main.py | Collision Risk | Notes |
|---|---|---|---|---|---|---|
| ... | ... | ... | N | YES/NO | NONE | ... |

## Dead routes

| File | Endpoints | Orphaned service? | Action |
|---|---|---|---|

## Duplicate-prefix groups

| Risk | Prefix | Files | Issue |
|---|---|---|---|

## Orphaned services

(Services started at startup whose route file is not registered in main.py.)

| Service | Started at | Corresponding route file | Status |
|---|---|---|---|
```

Return only the Markdown output above. Nothing else.
