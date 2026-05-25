# Workflow Advisory Engine — Next Checkpoint Criteria

**Status**: ACTIVE  
**Audience**: Governance, Compliance, Engineering leads  
**Last revised**: 2026-05-25  
**Paired with**: `workflow-advisory-runbook.md`, `workflow-advisory-monitoring.md`

---

## Purpose

This document defines what must be verified at each governance checkpoint before
the Workflow Advisory Engine is permitted to proceed to the next operational stage.
It records the current stage, scheduled checkpoints, and the criteria required for
each "PASS" verdict.

---

## Current stage: Controlled normal advisory use

As of 2026-05-25, the advisory engine is approved for **controlled normal advisory
use**. Broad traffic enablement requires explicit operator approval and passage of
the 24-48h monitoring gate.

**What is allowed now**:
- Operators may call `/api/v1/ai/advisory/workflow-blockers/{batch_id}` for any batch.
- The LLM synthesis flag is ON (`AI_ADVISORY_LLM_ENABLED=true`) in production.
- No traffic rate limits beyond the daily budget ceiling.

**What requires additional approval**:
- Enabling `AI_FALLBACK_ENABLED=true` — requires new session review + written operator approval.
- Enabling `AI_COWORK_ENABLED=true` — violates ADR-020; never permitted without a new ADR.
- Any Phase 3+ expansion (Class-A or Class-D surfaces) — requires separate PR + 7-agent gate.

---

## Trust Boundary Invariants (must pass at every checkpoint)

These invariants must hold at every governance checkpoint. A single invariant
failure blocks the corresponding checkpoint verdict.

| Invariant | How to verify | Failure action |
|-----------|--------------|----------------|
| `advisory_class="R"` hardcoded in service | `grep advisory_class service/app/services/ai_advisory.py` | BLOCK — alert Amit |
| No write imports in advisory module | `python -m pytest service/tests/test_ai_advisory_no_writes.py -v` | BLOCK — alert Amit |
| `active_provider='anthropic_api'` in `/status` | Query `/status` endpoint | BLOCK — provider governance violation |
| `cowork_enabled=false` in `/status` | Query `/status` endpoint | BLOCK — ADR-020 violation |
| `fallback_enabled=false` in `/status` | Query `/status` endpoint | FLAG for review |
| All AI flag defaults are False (config.py) | `python -m pytest service/tests/test_ai_token_governance.py -v` | BLOCK — restore defaults |

---

## Checkpoint 1 — 24–48h post-activation gate (DUE: 2026-05-26 to 2026-05-27)

### Purpose

Confirm the engine is stable, spending predictably, and producing quality output
after real traffic before authorising broad use.

### Pass criteria

| # | Criterion | Verification method | Required result |
|---|-----------|---------------------|-----------------|
| 1 | Budget OK | `/status`: `budget_ok=true` | true |
| 2 | Spend safely below cap | M1 query: daily spend | < 40% of `ai_advisory_budget_usd_per_day` |
| 3 | No fallback used | M4 query: `fallback_used` column | 0 on all recent rows |
| 4 | No error types | M2 query | No non-null `error_type` values |
| 5 | No CB warnings | `pz_stderr.log` | No circuit_breaker lines |
| 6 | No new errors | `pz_stderr.log` | No new ERROR lines |
| 7 | Advisory quality acceptable | Manual review of 3–5 recent explanations | Correct domain diagnosis, no hallucinations |
| 8 | Provider compliance | M5 query | Zero rows returned |
| 9 | AI subsystem tests | `pytest service/tests/test_ai_*.py -q` | 142/142 pass |
| 10 | Provider config | `/status`: `active_provider` | `anthropic_api` |

**Test scope note — Criterion 9**: The 142 AI subsystem tests confirm the AI
subsystem contract is intact. They do not substitute for the production deploy
gates. The production deploy gate requires:
- PZ regression suite: 160 tests (Windows host, `make verify`)
- Carrier suite: 381 tests (Windows host)

"142/142 AI tests pass" is necessary but not sufficient for a production deploy.
Both suites must pass before any sync to `C:\PZ`.

### Pass threshold

Criteria 1–8 must all pass. Criteria 9–10 confirm current state; any failure
blocks the gate until resolved.

### Outcome if PASS

Operator issues explicit "broad traffic approved" instruction. Engineering records
the approval in PROJECT_STATE.md under FACTS.

### Outcome if FAIL on any criterion

Hold at controlled advisory use. Investigate specific failure. Do not proceed.

---

## Checkpoint 2 — 30-day health review (DUE: 2026-06-25)

### Purpose

Confirm sustained stable operation over 30 days of real advisory traffic.
Validate budget model against actual burn rate.

### Pass criteria

| # | Criterion | Verification method | Required result |
|---|-----------|---------------------|-----------------|
| 1 | Daily spend trend | M1 query: 30-day average | Average < 40% of `ai_advisory_budget_usd_per_day` |
| 2 | Budget ceiling never hit | M3 query: any day at 100% | Zero days at ceiling |
| 3 | Provider compliance | M5 query: 30-day window | Zero rows returned |
| 4 | CB trips | M6 query: 30-day window | ≤ 3 CB trips total; no sustained (> 5 min) open state |
| 5 | Error rate | M2 query: 30-day window | < 2% of calls |
| 6 | AI subsystem tests | `pytest service/tests/test_ai_*.py -q` | 142/142 pass |
| 7 | Trust boundary invariants | All items in §Trust Boundary Invariants | All pass |
| 8 | Quality sample review | M7 query (deterministic) | ACCEPTABLE verdict |
| 9 | Advisory-to-closure correlation | Manual sample: 5 batches | Advisory was cited as helpful or neutral |

**Budget threshold note — Criterion 1 and 2**: Thresholds are expressed as
percentages of `ai_advisory_budget_usd_per_day` (config parameter). At the
current production value of $2.00/day:
- 40% ceiling = $0.80/day average target
- WARNING threshold: 75% of configured ceiling (currently $1.50 at $2.00)
- CRITICAL threshold: 90% of configured ceiling (currently $1.80 at $2.00)

If `ai_advisory_budget_usd_per_day` changes, recalculate dollar examples from
the new configured value. The percentage rules are the invariants.

**Quality sample note — Criterion 8**: Run the M7 deterministic query from
`workflow-advisory-monitoring.md`. Record `week_start`, `total_success_rows`,
`step_n`, `first_sampled_rowid`, and `rows_reviewed` in the quality review log.
Do NOT use random selection — systematic sampling required for audit traceability.

### Outcome if PASS

Record in PROJECT_STATE.md. Advisory engine cleared for Phase 3 planning.

### Outcome if FAIL on criteria 1–3 or 7

Block Phase 3 planning. Investigate root cause. Re-run checkpoint after fix.

### Outcome if FAIL on criteria 4–9

Flag for review. Phase 3 planning may proceed but must address the failing item
in the Phase 3 PR scope.

---

## Checkpoint 3 — Pre-Phase 3 readiness review (DUE: before Phase 3 implementation begins)

### Purpose

Confirm that expanding the AI subsystem (Phase 3: ledger centralization +
ai_customs_parser/ai_customs_evidence retrofit) does not violate the trust
boundary established in Phases 1–2C.

### Pass criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | Checkpoint 2 verdict: PASS | See Checkpoint 2 record |
| 2 | ADR-020 still current | No superseding ADR exists; `active_provider=anthropic_api` |
| 3 | Phase 3 scope does not introduce a new AI class | Reviewer-challenge verdict on Phase 3 PR |
| 4 | Phase 3 scope does not add write paths to any AI module | `test_ai_advisory_no_writes.py` extended to cover new modules |
| 5 | Phase 3 cowork consolidation task: CANCELLED | Confirmed — cowork DEPRECATED per ADR-020; retrofit only |
| 6 | pre-existing LLM services to retrofit: listed | `ai_customs_parser.py` + `ai_customs_evidence.py` (both Class-R) |
| 7 | New budget model validated | Token budget rule 6 ceiling still $2.00/day or revised with operator approval |

### Auto-trigger conditions

Checkpoint 3 fires automatically when ANY of the following occur:
- A PR is opened touching `ai_customs_parser.py` or `ai_customs_evidence.py`
- A PR is opened adding a new entry to §3 of `ai-capability-map.md`
- A PR is opened modifying `ai_advisory.py` or `ai_gateway.py` in a way that adds a new call type
- Checkpoint 2 verdict is PASS and the operator issues a Phase 3 go-ahead

---

## Checkpoint auto-trigger conditions (all checkpoints)

In addition to calendar-based scheduling, any checkpoint fires automatically when:

| Trigger | Fires | Action |
|---------|-------|--------|
| `active_provider` != `anthropic_api` in `/status` | Immediate | CRITICAL — stop all AI activity, notify Amit |
| `cowork_enabled=true` in `/status` | Immediate | ADR-020 violation — notify Amit |
| Daily spend hits 90% of `ai_advisory_budget_usd_per_day` | Same day | Review Checkpoint 2 budget criteria |
| Any AI module gains a write import | On next PR review | GATE 1 blocker — notify Amit |
| `test_ai_advisory_no_writes.py` is modified or deleted | On PR open | GATE 1 blocker — reviewer-challenge mandatory |
| A PR is opened superseding ADR-020 | On PR open | Checkpoint 3 prerequisite — full 7-agent gate review |

---

## SQL validation query — checkpoint verification

Run this query to confirm all governance invariants are intact before recording
a checkpoint verdict:

```sql
-- Checkpoint invariant verification
-- Run against C:\PZ\storage\ai_call_ledger.db
-- A clean install returns zero rows for the VIOLATIONS section.

-- SECTION 1: Recent spend vs. ceiling
-- (Replace 2.00 with current ai_advisory_budget_usd_per_day if changed)
SELECT
    'spend_today'             AS check_name,
    ROUND(SUM(COALESCE(actual_cost, estimated_cost, 0)), 6) AS value,
    CASE
        WHEN SUM(COALESCE(actual_cost, estimated_cost, 0)) < 1.50 THEN 'OK'       -- < 75% of $2.00
        WHEN SUM(COALESCE(actual_cost, estimated_cost, 0)) < 1.80 THEN 'WARNING'  -- 75-90% of $2.00
        ELSE 'CRITICAL'
    END AS status
FROM ai_calls
WHERE service = 'ai_advisory'
  AND date(timestamp) = date('now')

UNION ALL

-- SECTION 2: Provider compliance violations (ADR-020)
-- Any result here is a governance violation requiring immediate action.
-- ADR reference: .claude/adr/ADR-020-anthropic-api-sole-provider.md
SELECT
    'provider_violation'      AS check_name,
    CAST(COUNT(*) AS TEXT)    AS value,
    CASE WHEN COUNT(*) = 0 THEN 'OK' ELSE 'CRITICAL' END AS status
FROM ai_calls
WHERE service = 'ai_advisory'
  AND provider_used NOT IN (
      'anthropic_api'  -- ADR-020 approved set; update only when superseding ADR approves new provider
  )
  AND timestamp >= datetime('now', '-24 hours')

UNION ALL

-- SECTION 3: Unexpected fallback use
SELECT
    'fallback_violations'     AS check_name,
    CAST(COUNT(*) AS TEXT)    AS value,
    CASE WHEN COUNT(*) = 0 THEN 'OK' ELSE 'FLAG' END AS status
FROM ai_calls
WHERE service = 'ai_advisory'
  AND fallback_used = 1
  AND timestamp >= datetime('now', '-24 hours')

UNION ALL

-- SECTION 4: Error rate (24h)
SELECT
    'error_rate_pct'          AS check_name,
    CAST(ROUND(
        SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) * 100.0 / MAX(COUNT(*), 1), 1
    ) AS TEXT) AS value,
    CASE
        WHEN SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) * 100.0 / MAX(COUNT(*), 1) < 2
        THEN 'OK'
        ELSE 'WARNING'
    END AS status
FROM ai_calls
WHERE service = 'ai_advisory'
  AND timestamp >= datetime('now', '-24 hours');
```

**Note on dollar thresholds in Section 1**: The $1.50 and $1.80 values in the
CASE expression above are derived from the current production ceiling of $2.00/day
(75% and 90% respectively). If `AI_ADVISORY_BUDGET_USD_PER_DAY` changes in `.env`,
update the CASE thresholds to match 75%/90% of the new configured value. The
percentage rules are the governance invariants — not the absolute dollar amounts.

---

## Validation gaps (acknowledged risks)

These gaps are known and accepted for Phase 2. They are tracked as scheduled
work for Phase 3 or later:

| Gap | Risk | Mitigation in place | Target phase |
|-----|------|---------------------|-------------|
| No ledger backfill if DB deleted | Historical spend data lost | Ledger DB is append-only; scheduled backup not yet implemented | Phase 3 |
| No alert deduplication | Repeated alerts for same CB open event | Manual filtering in pz_stderr.log | Phase 3 |
| No automated quality review | M7 requires manual execution weekly | Calendar reminder; audit record requirement enforces discipline | Phase 4 |
| Budget ceiling resets daily (UTC midnight) | Near-ceiling spend at 23:50 UTC risks a burst | Burn rate ($0.000372/call) makes this extremely unlikely at current volume | Monitor at Checkpoint 2 |
| `cowork_available` field uses `cowork_enabled` only | Does not check key presence | Cosmetic only — cowork must remain false regardless | Low priority |

---

## Assumptions

| # | Assumption | If wrong |
|---|------------|----------|
| A1 | Production Python version remains 3.9.6 (ADR-020 Python check basis) | Re-evaluate provider options; update ADR if upgrade occurs |
| A2 | Anthropic API billing remains per-token and maps to `actual_cost_usd` | Re-validate budget model; may require ADR-020 amendment |
| A3 | Advisory call volume stays below 1,000 calls/day in Phase 2 | Review budget ceiling; M3 7-day trend will detect early |
| A4 | All advisory calls use `task_type='advisory_explanation'` in ledger | If additional task types added, M1-M4 queries must include them |
| A5 | SQLite WAL mode sufficient for concurrent ledger writes | Review if service becomes multi-process (Phase 7+) |

---

## Checkpoint record (append only)

| Date | Checkpoint | Verdict | Recorded by | Notes |
|------|------------|---------|-------------|-------|
| 2026-05-25 | Canary (pre-Checkpoint 1) | PASS — 3/3 canaries | Amit | $0.001116 total; ADR-020 issued |
| — | Checkpoint 1 | PENDING | — | Due 2026-05-26 to 2026-05-27 |
| — | Checkpoint 2 | PENDING | — | Due 2026-06-25 |
| — | Checkpoint 3 | PENDING | — | Before Phase 3 begins |

---

## References

- `workflow-advisory-runbook.md` — operator guide and trust boundary
- `workflow-advisory-monitoring.md` — M1–M8 SQL queries, alert thresholds, CB state machine
- `docs/ai-governance/ai-capability-map.md` — class definitions, phase plan, §10 provider lock-down
- `.claude/adr/ADR-020-anthropic-api-sole-provider.md` — provider governance (ADR-020)
- `service/app/services/ai_advisory.py` — advisory_class="R" hardcoded
- `service/tests/test_ai_advisory_no_writes.py` — no-write boundary enforcement (must not be deleted)
- `service/tests/test_ai_token_governance.py` — flag defaults enforcement
- `.claude/memory/PROJECT_STATE.md` — current stage, canary facts, open monitoring gate
