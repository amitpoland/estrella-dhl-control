# Workflow Advisory Engine — Monitoring & Alerting Strategy

**Status**: ACTIVE  
**Audience**: Engineering, SRE, Governance  
**Last revised**: 2026-05-25  
**Paired with**: `workflow-advisory-runbook.md`, `workflow-advisory-checkpoints.md`

---

## Monitoring philosophy

The advisory engine is read-only (advisory_class="R"). Failures degrade gracefully
to deterministic explanations — they do not break the workflow. Monitoring goals are:

1. **Budget integrity** — spend stays below the configured ceiling
2. **Provider compliance** — every call goes through the approved provider (ADR-020)
3. **Quality assurance** — LLM explanations are accurate and not hallucinating
4. **Circuit breaker health** — CB opens and closes as expected; no stuck-open state
5. **Test suite currency** — AI subsystem tests remain green across deploys

---

## Monitoring queries (SQLite — `C:\PZ\storage\ai_call_ledger.db`)

### M1 — Daily spend vs. configured ceiling

```sql
-- Run daily. Compare result against ai_advisory_budget_usd_per_day in config.
-- Warning threshold: 75% of configured ceiling.
-- Critical threshold: 90% of configured ceiling.
-- (See §Alert Thresholds for percentage-based rules.)
SELECT
    date(timestamp) AS day,
    COUNT(*)                                             AS total_calls,
    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END)        AS successful_calls,
    ROUND(SUM(COALESCE(actual_cost, estimated_cost, 0)), 6) AS total_spend_usd,
    ROUND(AVG(COALESCE(actual_cost, estimated_cost, 0)), 6) AS avg_cost_per_call,
    ROUND(AVG(latency_ms), 0)                            AS avg_latency_ms
FROM ai_calls
WHERE service = 'ai_advisory'
  AND date(timestamp) = date('now')
GROUP BY day;
```

### M2 — Error rate (last 24 hours)

```sql
SELECT
    error_type,
    COUNT(*) AS count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct
FROM ai_calls
WHERE service = 'ai_advisory'
  AND timestamp >= datetime('now', '-24 hours')
GROUP BY error_type
ORDER BY count DESC;
```

### M3 — Budget burn rate (rolling 7 days)

```sql
-- Alert when daily_spend >= 75% of ai_advisory_budget_usd_per_day (WARNING)
-- Alert when daily_spend >= 90% of ai_advisory_budget_usd_per_day (CRITICAL)
-- Thresholds are percentages of the configured value, not hardcoded dollar amounts.
-- Current production ceiling: $2.00/day (AI_ADVISORY_BUDGET_USD_PER_DAY=2.00)
-- → WARNING threshold at current ceiling: $1.50; CRITICAL: $1.80
-- If the ceiling changes, recalculate thresholds from config — not from this query.
SELECT
    date(timestamp)                                      AS day,
    COUNT(*)                                             AS calls,
    ROUND(SUM(COALESCE(actual_cost, estimated_cost, 0)), 6) AS spend_usd
FROM ai_calls
WHERE service = 'ai_advisory'
  AND date(timestamp) >= date('now', '-7 days')
GROUP BY day
ORDER BY day;
```

### M4 — LLM vs. deterministic call split

```sql
-- Tracks how often LLM synthesis fires vs. falling back to deterministic path.
-- High deterministic rate may indicate: circuit breaker open, budget ceiling reached,
-- cache hits, or flag disabled.
SELECT
    date(timestamp)     AS day,
    provider_used,
    fallback_used,
    COUNT(*)            AS calls,
    SUM(success)        AS successes
FROM ai_calls
WHERE service = 'ai_advisory'
  AND date(timestamp) >= date('now', '-7 days')
GROUP BY day, provider_used, fallback_used
ORDER BY day, provider_used;
```

### M5 — Provider compliance check (ADR-020)

```sql
-- ADR-020 sole approved provider: 'anthropic_api'
-- ALERT on any row where provider_used is not in the ADR-approved set.
-- If a future ADR supersedes ADR-020 and approves a new provider,
-- add that value to the IN() list before the new provider goes live.
-- Do NOT simply remove this check — update the approved set instead.
--
-- ADR reference: .claude/adr/ADR-020-anthropic-api-sole-provider.md
-- Current approved provider set: {'anthropic_api'}
SELECT
    id,
    timestamp,
    batch_id,
    provider_requested,
    provider_used,
    fallback_used,
    error_type
FROM ai_calls
WHERE service = 'ai_advisory'
  AND provider_used NOT IN (
      'anthropic_api'  -- ADR-020 sole provider; expand only when superseding ADR approves new provider
  )
  AND timestamp >= datetime('now', '-24 hours')
ORDER BY timestamp DESC;
```

Any result from M5 is a governance violation requiring immediate investigation.
See §Alert Classification.

### M6 — Circuit breaker incident log

```sql
-- CB-related errors appear as error_type values.
-- 'circuit_breaker_open' means the CB tripped on this call.
-- The CB threshold and reset interval are configurable via
-- ai_gateway_circuit_breaker_threshold and ai_gateway_circuit_breaker_reset_s.
-- Default: 5 consecutive failures trip the CB; 60s reset interval.
SELECT
    timestamp,
    error_type,
    object_id  AS batch_id,
    latency_ms
FROM ai_calls
WHERE service = 'ai_advisory'
  AND error_type IS NOT NULL
  AND timestamp >= datetime('now', '-24 hours')
ORDER BY timestamp DESC;
```

### M7 — Deterministic quality sample (weekly, auditable)

Quality review must use a **deterministic systematic sample**, not random selection,
so that any reviewer can reconstruct the exact set of rows reviewed.

```sql
-- Step 1: Count total successful advisory calls in the trailing 7 days.
SELECT COUNT(*) AS week_total
FROM ai_calls
WHERE service = 'ai_advisory'
  AND success = 1
  AND timestamp >= datetime('now', '-7 days');

-- Step 2: Compute step size N = max(1, floor(week_total / 10)).
-- If week_total < 10, review all rows (no sampling needed).

-- Step 3: Select every Nth row by rowid (deterministic, reproducible).
-- Replace :step_n with the computed N value.
WITH numbered AS (
    SELECT
        rowid,
        id,
        timestamp,
        object_id       AS batch_id,
        actual_input_tokens,
        actual_output_tokens,
        actual_cost,
        provider_used,
        ROW_NUMBER() OVER (ORDER BY rowid ASC) AS rn
    FROM ai_calls
    WHERE service = 'ai_advisory'
      AND success = 1
      AND timestamp >= datetime('now', '-7 days')
)
SELECT *
FROM numbered
WHERE rn % :step_n = 1   -- systematic: every Nth row starting from row 1
ORDER BY rowid ASC;
```

**Audit record requirement**: For each weekly quality review, record in the
quality review log:

| Field | Example |
|-------|---------|
| `week_start` | 2026-05-19 |
| `week_end` | 2026-05-25 |
| `total_success_rows` | 47 |
| `step_n` | 4 |
| `first_sampled_rowid` | 1023 |
| `rows_reviewed` | 12 |
| `quality_verdict` | ACCEPTABLE / NEEDS_REVIEW / ESCALATE |
| `reviewer` | initials |

This record allows any future auditor to reconstruct the exact rows reviewed by
running Step 3 with the recorded `step_n` and `week_start`/`week_end` bounds.

If `total_success_rows < 10`, the review log records `step_n=1` and notes
"all rows reviewed — volume below 10-row floor."

### M8 — Post-deploy smoke validation

Run after any PZService restart or deployment touching AI-related files:

```sql
-- Confirm last 5 rows are clean (run within 10 min of restart).
SELECT
    id,
    timestamp,
    success,
    error_type,
    provider_used,
    fallback_used,
    actual_cost
FROM ai_calls
WHERE service = 'ai_advisory'
ORDER BY id DESC
LIMIT 5;
```

Expected: `success=1`, `error_type=NULL`, `provider_used='anthropic_api'`,
`fallback_used=0`.

**Test metric note**: Post-deploy validation requires two distinct passes:

1. **AI subsystem tests** (142 tests, run on any host with Python + pytest):
   These cover `ai_advisory`, `ai_gateway`, `ai_call_ledger`, `ai_parser`,
   `test_phase2b_provider_selection`, and `test_phase3_cowork_provider`.
   Passage confirms AI subsystem contract is intact.
   *This is necessary but not sufficient for production deploy.*

2. **Production deploy gates** (Windows host only, run via `make verify`):
   - PZ regression suite: 160 tests
   - Carrier suite: 381 tests
   These are separate suites on the Windows production host. They must pass
   before any deploy to `C:\PZ`.

A deploy to `C:\PZ` based solely on "142/142 AI tests pass" is under-gated.
Both suites must pass.

---

## Alert classification

| Severity | Condition | Action |
|----------|-----------|--------|
| CRITICAL | M5 returns any row (provider != ADR-approved set) | Immediate investigation; notify Amit; do not restart until root cause found |
| CRITICAL | `cowork_enabled=true` in `/status` response | ADR-020 violation; notify Amit immediately |
| CRITICAL | `fallback_enabled=true` in `/status` response | Unexpected flag change; notify Amit |
| WARNING | Daily spend ≥ 75% of `ai_advisory_budget_usd_per_day` | Monitor closely; no action unless trending to CRITICAL |
| WARNING | Daily spend ≥ 90% of `ai_advisory_budget_usd_per_day` | Alert Kaushal; spending will auto-cease at 100%; investigate call volume |
| WARNING | Circuit breaker open for > 5 minutes (M6) | Check `pz_stderr.log`; may be transient Anthropic outage; notify Kaushal if sustained |
| INFO | M7 quality review shows unexpected explanation content | Log in quality review record; if pattern recurring, escalate to Amit |

**Alert threshold reference**: WARNING at 75% and CRITICAL at 90% of the
configured `ai_advisory_budget_usd_per_day` value. These percentages are the
governance invariants — not the dollar values. At the current production ceiling
of $2.00/day, these compute to $1.50 (WARNING) and $1.80 (CRITICAL). If the
ceiling is changed via config, recalculate from the new ceiling value; do not
use the dollar figures as fixed thresholds.

---

## Circuit breaker state machine

```
            ┌──────────────────────────────────────────┐
            │                                          │
   NEW CALL  ▼                                         │
 ┌──────────────────┐  N consecutive   ┌─────────────────┐
 │   CLOSED         │  failures        │   OPEN           │
 │  (calls allowed) │─────────────────►│  (calls blocked) │
 └──────────────────┘  (N = ai_gateway │  returns None    │
          ▲            _circuit_        └─────────────────┘
          │            breaker_                 │
          │            threshold)               │ after ai_gateway_
          │                                     │ circuit_breaker_reset_s
          │            ┌─────────────────┐      │ seconds
          └────────────│   HALF-OPEN     │◄─────┘
            success    │  (one test call)│
                       └─────────────────┘
                             │
                             │ failure
                             ▼
                         OPEN again
```

The CB threshold and reset interval are read from config at runtime:
- `ai_gateway_circuit_breaker_threshold` (default: 5)
- `ai_gateway_circuit_breaker_reset_s` (default: 60.0 seconds)

Both can be adjusted via environment variable and PZService restart.
The Anthropic CB and cowork CB counters are isolated — one path's failures
never affect the other.

---

## Decision tree: "advisory engine returned unexpected output"

```
Advisory engine returned unexpected output
│
├─ Is gateway_available=false?
│    YES → Circuit breaker open or API key issue.
│          Check pz_stderr.log. Check /status for active_provider.
│          Wait 60s for CB reset. If persists, check Anthropic API key.
│
├─ Is llm_used=false when you expected true?
│    YES → Check: is ai_advisory_llm_enabled=true in /status?
│          Is budget_ok=true? Is cache TTL hit (cached=true)?
│          If budget_ok=false: spending will resume tomorrow. No action needed.
│          If cache hit: wait 300s for TTL expiry.
│
├─ Is the explanation factually wrong (wrong domain named, wrong status)?
│    YES → Check get_batch_readiness() output for this batch directly.
│          Advisory mirrors readiness — if readiness is wrong, fix readiness.
│          If readiness is correct but advisory explanation differs, this is
│          an LLM synthesis error. Log for M7 quality review. Report to Kaushal.
│
├─ Is active_provider != 'anthropic_api'?
│    YES → CRITICAL governance violation. Notify Amit immediately.
│          Do not restart service until root cause confirmed.
│
└─ Is cowork_enabled=true or fallback_enabled=true?
     YES → ADR-020 violation. Notify Amit. Check .env for unexpected flag change.
```

---

## Escalation map

| Signal | Route | Owner |
|--------|-------|-------|
| Provider violation (M5) | Immediate → Amit | Amit |
| ADR-020 flag violation | Immediate → Amit | Amit |
| Circuit breaker sustained open | → Kaushal (IT) | Kaushal |
| Budget WARNING threshold | → Kaushal monitor | Kaushal |
| Budget CRITICAL threshold | → Kaushal + Amit | Amit |
| Quality review ESCALATE | → Amit | Amit |
| Unexpected 5xx from endpoints | → Kaushal | Kaushal |

---

## References

- `service/app/services/ai_gateway.py` — CB logic (`_CB_THRESHOLD`, `_CB_RESET_AFTER_S`)
- `service/app/services/ai_call_ledger.py` — ledger schema, daily cost query
- `service/app/core/config.py` — `ai_gateway_circuit_breaker_threshold`, `ai_gateway_circuit_breaker_reset_s`, `ai_advisory_budget_usd_per_day`
- `.claude/adr/ADR-020-anthropic-api-sole-provider.md` — approved provider set
- `workflow-advisory-runbook.md` — operator quick-reference
- `workflow-advisory-checkpoints.md` — review schedule
