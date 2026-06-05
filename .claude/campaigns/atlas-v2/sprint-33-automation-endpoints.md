# Sprint 33 — Authority Endpoint Reference (Automation Hub)

**Purpose:** Pin the verified `routes_ai_bridge.py` endpoint paths so when the Sprint 33 implementation brief is authored, it inherits authority-correct URLs and skips a re-discovery cycle.

**Status:** Reference only. No implementation. No Sprint 33 brief authored yet.
**Authored:** 2026-06-06, alongside the Sprint 31 DHL Hub planning thread.

---

## Verified backend authority

**Source file:** `service/app/api/routes_ai_bridge.py`
**Router prefix (line 41):** `APIRouter(prefix="/api/v1/ai-bridge", tags=["ai_bridge"])`
**Registered in `main.py` line 405:** `app.include_router(ai_bridge_router)`

### Allowed (READ-ONLY GET) endpoints for Sprint 33

| Endpoint | Source line | Purpose |
|---|---|---|
| `GET /api/v1/ai-bridge/tasks` | routes_ai_bridge.py:165 | List tasks (queue status) |
| `GET /api/v1/ai-bridge/tasks/{task_id}` | routes_ai_bridge.py:183 | Read a specific task |
| `GET /api/v1/ai-bridge/errors` | routes_ai_bridge.py:550 | Read error log |
| `GET /api/v1/ai-bridge/results/{task_id}` | routes_ai_bridge.py:565 | Read task result (parameterised — no parameterless `/results`) |
| `GET /api/v1/ai-bridge/templates` | routes_ai_bridge.py:592 | Read prompt templates |

Auth: all use `dependencies=[_auth]` (require_api_key with session cookie support).

### Write endpoints (FORBIDDEN for Sprint 33 — record only, do NOT consume)

- `POST /api/v1/ai-bridge/tasks/{batch_id}` (line 89) — queue a task
- `POST /api/v1/ai-bridge/results/{task_id}` (line 194) — submit a result

Sprint 33 is a visibility-only Authority-Exposure Sprint; it must consume read endpoints only.

---

## Common confusion: `/api/v1/ai/*` is a DIFFERENT system — do NOT migrate to it

There is a separate live router `routes_ai_advisory.py` mounted at prefix
**`/api/v1/ai/advisory/*`** (e.g. `/api/v1/ai/advisory/status`,
`/api/v1/ai/advisory/workflow-blockers/{batch_id}`). It is the LLM Advisory
service — Phase 2 deterministic-with-LLM advisory, governed by
`ai_advisory_llm_enabled` (default false).

It is NOT the AI Bridge / Automation Center / task queue, and its endpoints
must NOT be substituted into the Sprint 33 Automation Hub.

| Domain | Router prefix | Sprint |
|---|---|---|
| Automation Center (cowork task queue) | `/api/v1/ai-bridge` | **Sprint 33 (this doc)** |
| LLM Advisory service | `/api/v1/ai/advisory` | not part of Sprint 33; stays standalone |

---

## When Sprint 33 is authored

Copy the table above verbatim into the Sprint 33 implementation brief (`sprint-33-automation-hub.md`) as the §3 "ONLY endpoints this page may consume" block, in the same shape as Sprint 31. Apply the same Authority-Exposure Sprint invariants (visibility-only; no POST/PUT/PATCH/DELETE; no task-queue mutation; mock-renderer retirement in the same commit; full 7-agent deploy gate; static-only deploy).

---

## Roadmap position

Sprint 31 — DHL Hub (planned, next)
Sprint 32 — Shipments Hub
**Sprint 33 — Automation Hub** ← endpoints pinned by this file
Sprint 34 — Intelligence Hub

Deferred: Accounting (P1 incomplete), Shipping (pre-P1), Proposals (cancelled — already in Inbox).
