# Service / Scheduler Map

**Base SHA:** aa414d90
**Census timestamp:** {{STAMP}}
**Inspector agent:** service-scheduler-inspector
**Mode:** READ-ONLY — no app code was modified
**Service files found:** {{N}}
**Scheduled jobs:** {{J}}
**Startup-initiated services:** {{S}}
**Orphaned services (routes dead):** {{O}}
**SCHEDULER-ONLY capabilities (no Business API):** {{C}}

---

## Startup Sequence

(Ordered list of what main.py starts at startup)

1. ServiceName — purpose — route file — registered: YES/NO
2. …

---

## Scheduler Table

| Job | Service File | Interval | Calls | Domain | Route registered | Business API | Business UI | Observability |
|---|---|---|---|---|---|---|---|---|
| wfirma_sync | `wfirma_customer_sync.py` | 5 min | `run_customer_sync()` | Customer Master | YES | YES | YES | YES |
| … | … | … | … | … | … | … | … | … |

---

## Orphaned Services

| Service | File | What it does | Route file | Action |
|---|---|---|---|---|

---

## SCHEDULER-ONLY Capabilities

Capabilities with automation but missing Business API / Business UI / Observability:

| Capability | Scheduler | Business API | Business UI | Status Endpoint | Gap |
|---|---|---|---|---|---|
