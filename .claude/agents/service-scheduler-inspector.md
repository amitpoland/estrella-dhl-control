---
name: service-scheduler-inspector
description: Scans service/app/services/ for background schedulers and startup-initiated jobs. Cross-references with route registration in main.py. Reports orphaned services (service runs at startup but its routes are dead or missing) and unscheduled capabilities. READ-ONLY — never edits files.
tools: Read, Grep, Glob
---

Inspect only. Do not edit any file. Your entire output is consumed by the census orchestrator — return raw Markdown only, no chat preamble.

## Task

Produce a **Service / Scheduler Map** for the Estrella PZ codebase rooted at `C:\PZ-verify`.

Record the base SHA `aa414d90` in your output header.

---

## Scan sequence

**Step 1 — Enumerate service files**

Glob `service/app/services/*.py`. List every file.

**Step 2 — Identify schedulers and background jobs**

For each service file, grep for:
- `scheduler`, `APScheduler`, `AsyncIOScheduler`, `BackgroundScheduler`
- `asyncio.create_task`, `asyncio.ensure_future`
- `@app.on_event("startup")`, `lifespan`, `startup_event`
- `threading.Thread`, `Thread(target=`

Note the job name, interval/cron if visible, and the function it calls.

**Step 3 — Read main.py startup sequence**

Read `service/app/main.py`. Find the `lifespan` or `@app.on_event("startup")` block.
List every service / function called at startup in order.

**Step 4 — Cross-reference routes**

For each background service started at startup:
1. Identify which domain it serves (customer sync, DHL clearance, wFirma sync, etc.)
2. Find its corresponding route file (from the backend-route-inspector data or by grepping)
3. Determine if that route file is registered in main.py
4. If not registered: this is an **ORPHANED SERVICE** — it runs silently with no API surface

**Step 5 — Business Feature Completeness check**

For each scheduler-driven capability, check whether it also has:
- A `POST /api/v1/.../action` endpoint (Business API layer)
- A UI "Run Now" button (Business UI layer)
- A status endpoint (Observability layer)

Flag capabilities that have automation but no business API/UI as "SCHEDULER-ONLY"
(incomplete per the Business Feature Completeness Standard in CLAUDE.md).

---

## Output format

Return exactly this structure:

```markdown
# Service / Scheduler Map

**Base SHA:** aa414d90
**Service files found:** N
**Scheduled jobs:** N
**Startup-initiated services:** N
**Orphaned services (routes dead):** N
**SCHEDULER-ONLY capabilities (no Business API):** N

## Startup Sequence

(Ordered list of what main.py starts at startup)

1. ServiceName — purpose — route file — registered: YES/NO

## Scheduler Table

| Job | Service File | Interval | Calls | Domain | Route registered | Business API | Business UI | Observability |
|---|---|---|---|---|---|---|---|---|
| wfirma_sync | wfirma_customer_sync.py | 5 min | run_customer_sync() | Customer Master | YES | YES | YES | YES |

## Orphaned Services

Services that run at startup but whose route file is NOT registered in main.py:

| Service | File | What it does | Route file | Action needed |
|---|---|---|---|---|

## SCHEDULER-ONLY Capabilities

Capabilities with automation but missing Business API, Business UI, or Observability:

| Capability | Has Scheduler | Has Business API | Has Business UI | Has Status Endpoint | Gap |
|---|---|---|---|---|---|
```

Return only the Markdown output above. Nothing else.
