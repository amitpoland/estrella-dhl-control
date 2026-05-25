# Workflow Advisory Engine — Operator Runbook

**Status**: ACTIVE  
**Audience**: Operators (Tejal, Jigar, Izabela, Kaushal, Jeff)  
**Engine class**: R (Read-only AI — hardcoded, cannot be relaxed without a new ADR)  
**Last revised**: 2026-05-25  
**Paired with**: `workflow-advisory-monitoring.md`, `workflow-advisory-checkpoints.md`

---

## Purpose

The Workflow Advisory Engine answers one question in plain English:
**"Why is this batch's workflow blocked, and what must happen to unblock it?"**

It reads the output of `get_batch_readiness()` and expresses those conditions in
a human-readable explanation. When the LLM flag is enabled, it optionally
synthesises the explanation using Claude Haiku. Whether or not the LLM fires, the
underlying readiness truth comes from `get_batch_readiness()` — the advisory engine
never re-derives it.

---

## Trust Boundary and Authority Separation

**Read this section before acting on any advisory output.**

### What the advisory engine IS

- An **explanatory layer**. It reads existing workflow authority output and
  describes what it sees in plain English.
- Downstream of `get_batch_readiness()`. The engine consumes readiness truth;
  it does not produce it.
- Read-only at every level: `advisory_class="R"` is hardcoded in
  `service/app/services/ai_advisory.py` and cannot be changed without a new ADR
  and 7-agent deploy gate review.

### What the advisory engine is NOT

- **Not a readiness authority.** `get_batch_readiness()` owns readiness truth.
  If you disagree with what the engine reports, the disagreement is with the
  underlying workflow state — not with the advisory engine.
- **Not a decision gate.** A "workflow is blocked" explanation does not
  create the block. The block exists in the warehouse, sales, wFirma, or DHL
  authority domain and must be cleared there.
- **Not a write path.** There is no code path from the advisory engine to
  wFirma writes, DHL sends, email dispatch, or database mutations.
  `test_ai_advisory_no_writes.py` enforces this boundary; it must never be
  deleted.

### Authority hierarchy when advisory conflicts with other signals

If advisory output says "batch is ready" but another authoritative surface
(wFirma, DHL, warehouse scan log) says otherwise — **authoritative workflow
state wins**. The advisory engine reflects truth; it does not produce it.

If advisory output says "batch is blocked" but the operator has independent
evidence that all conditions are met — check `get_batch_readiness()` output
directly. The advisory engine's explanation is only as current as its cache
TTL (300 seconds by default).

---

## Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/ai/advisory/workflow-blockers/{batch_id}` | GET | Why is this batch blocked (or ready)? |
| `/api/v1/ai/advisory/status` | GET | Advisory subsystem health, flags, spend |

Both require `X-API-Key` header with the service API key.

---

## Response fields — workflow-blockers

| Field | Type | Meaning |
|-------|------|---------|
| `ok` | bool | Request succeeded |
| `ready_for_closure` | bool | Whether batch passes all closure gates |
| `blocked_domains` | list | Domains that are blocking (warehouse / sales / wfirma / dhl) |
| `explanation` | str | Plain-English summary |
| `domain_details` | object | Per-domain structured reasoning |
| `llm_used` | bool | True only if an LLM call succeeded for this response |
| `model_used` | str or null | Model ID when `llm_used=true`; null otherwise |
| `source` | str | `batch_readiness` (deterministic only) or `batch_readiness+llm` |
| `advisory_class` | str | Always `"R"` — hardcoded read-only class |
| `generated_at` | str | ISO-8601 UTC timestamp |
| `cached` | bool | True if result served from TTL cache |

---

## What each blocked domain means and how to unblock it

### warehouse

| Status code | What it means | Who unblocks it |
|-------------|--------------|-----------------|
| `n/a` | Warehouse not yet reached in workflow | Jigar (warehouse lead) |
| `empty` | No packing lines recorded | Jigar — scan in items |
| `partial` | Some items scanned, not all | Jigar — complete the scan |

### sales

| Status code | What it means | Who unblocks it |
|-------------|--------------|-----------------|
| `n/a` | Sales step not applicable | — |
| `partial` | Sales lines incomplete or unlinked | Tejal (accounts) |

### wfirma

| Status code | What it means | Who unblocks it |
|-------------|--------------|-----------------|
| `not_configured` | wFirma reservation not set up | Tejal |
| `blocked` | wFirma blocked by upstream condition | Tejal — check wFirma UI |
| `created` | wFirma document exists ✅ | No action required |

### dhl

| Status code | What it means | Who unblocks it |
|-------------|--------------|-----------------|
| `sla_breach` | DHL SLA window has elapsed | Kaushal (IT) — check DHL portal |
| `awaiting event` | Waiting for DHL tracking milestone | Monitor — no manual action yet |

---

## Response fields — status endpoint

| Field | Meaning |
|-------|---------|
| `ai_advisory_llm_enabled` | LLM synthesis flag (true in production) |
| `ai_parser_enabled` | Parser flag |
| `gateway_available` | True if API key present and circuit breaker closed |
| `model` | Configured model (production: `claude-haiku-4-5-20251001`) |
| `max_tokens_per_call` | Max tokens per LLM call |
| `budget_usd_per_day` | Configured daily ceiling (`ai_advisory_budget_usd_per_day`) |
| `spent_usd_today` | Ledger-derived today's spend |
| `budget_ok` | False when `spent_usd_today >= budget_usd_per_day` |
| `cache_ttl_seconds` | TTL for response cache (default 300) |
| `cowork_enabled` | Must always be false (cowork DEPRECATED — ADR-020) |
| `cowork_available` | Must always be false |
| `fallback_enabled` | Must always be false |
| `active_provider` | Must always be `anthropic_api` or `none` (never `claude_cowork`) |
| `api_key_health` | Optional admin API key health; null if not configured |

---

## Circuit breaker

The gateway has an independent circuit breaker for the Anthropic API path.
It trips after a configurable number of consecutive failures (default 5,
set by `ai_gateway_circuit_breaker_threshold` in config/env). After tripping,
it enters open state and blocks new LLM calls. It resets to half-open after
`ai_gateway_circuit_breaker_reset_s` seconds (default 60; configurable via env).

To change either value: update the environment variable and restart PZService.
No code change required.

The Anthropic CB and cowork CB are **isolated** — failures on one path never
affect the other.

When the circuit breaker is open:
- `/workflow-blockers/{batch_id}` returns a deterministic (non-LLM) explanation
  with `llm_used=false`
- `/status` shows `gateway_available=false`
- No budget is consumed

The CB resets automatically. If it remains open after 60+ seconds, check
`C:\PZ\logs\pz_stderr.log` for the underlying error.

---

## Budget behavior

Daily budget ceiling is set by `ai_advisory_budget_usd_per_day` (env:
`AI_ADVISORY_BUDGET_USD_PER_DAY`). Production ceiling: $2.00/day.

When daily spend reaches the ceiling:
- All LLM synthesis is suppressed for the remainder of the day
- Deterministic explanations continue serving without interruption
- The endpoint still returns 200 with `llm_used=false`
- No operator action required; the ceiling resets at midnight UTC

Burn rate at production haiku pricing: approximately $0.000372/call.
At $2.00/day ceiling: ~5,376 calls before ceiling is hit.

---

## Escalation triggers

Stop and notify Kaushal (IT) if:

| Symptom | Likely cause |
|---------|-------------|
| `/status` shows `gateway_available=false` for > 5 minutes | Circuit breaker open or API key problem |
| `spent_usd_today` near or above `budget_usd_per_day` | Budget ceiling approaching/reached |
| `active_provider != 'anthropic_api'` | Governance violation — must be investigated immediately |
| `cowork_enabled: true` or `fallback_enabled: true` | Config violation — these must remain false |
| 5xx errors from `/workflow-blockers/` endpoint | Service restart may be needed |

Stop and notify Amit if:

| Symptom | Meaning |
|---------|---------|
| `active_provider` reports anything other than `anthropic_api` or `none` | Provider governance violation — see ADR-020 |
| `cowork_enabled: true` in `/status` response | Cowork path was re-enabled — this violates ADR-020 |

---

## Quick-reference check commands (Windows production)

```powershell
# Load API key from .env
$k = (Get-Content "C:\PZ\.env" | Where-Object { $_ -match "^AUTH_SECRET_KEY=" } | ForEach-Object { $_.Split("=",2)[1] })

# Check advisory status
(Invoke-WebRequest "http://127.0.0.1:47213/api/v1/ai/advisory/status" -Headers @{"X-API-Key"=$k} -UseBasicParsing).Content

# Check a specific batch
(Invoke-WebRequest "http://127.0.0.1:47213/api/v1/ai/advisory/workflow-blockers/YOUR_BATCH_ID" -Headers @{"X-API-Key"=$k} -UseBasicParsing).Content

# Check last 20 ledger rows
python -c "import sqlite3; con=sqlite3.connect(r'C:\PZ\storage\ai_call_ledger.db'); rows=con.execute('SELECT id,timestamp,success,actual_cost,provider_used,fallback_used,error_type FROM ai_calls ORDER BY id DESC LIMIT 20').fetchall(); [print(r) for r in rows]; con.close()"

# Check stderr log
Get-Content C:\PZ\logs\pz_stderr.log -Tail 80
```

---

## What operators must never do

- Do NOT set `AI_COWORK_ENABLED=true` in `.env`. The cowork path is deprecated
  (ADR-020). Setting it true violates governance.
- Do NOT set `AI_FALLBACK_ENABLED=true` without explicit operator written approval
  and a new session review.
- Do NOT attempt to "fix" the advisory engine when the advisory engine is correctly
  reporting a blocked workflow. The block is in the workflow domain — fix it there.
- Do NOT treat advisory output as authoritative when it conflicts with wFirma,
  DHL, or warehouse scan state.

---

## References

- `service/app/api/routes_ai_advisory.py` — endpoint implementation
- `service/app/services/ai_advisory.py` — engine logic, forbidden-action list
- `service/app/services/ai_gateway.py` — call path, circuit breaker, budget guard
- `service/app/services/ai_call_ledger.py` — spend tracking
- `docs/ai-governance/ai-capability-map.md` — class definitions and phase plan
- `.claude/adr/ADR-020-anthropic-api-sole-provider.md` — provider lock-down decision
- `service/tests/test_ai_advisory_no_writes.py` — no-write boundary enforcement
- `workflow-advisory-monitoring.md` — monitoring queries and alerting thresholds
- `workflow-advisory-checkpoints.md` — governance review schedule
