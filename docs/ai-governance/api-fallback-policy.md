# API Fallback Policy — EJ Dashboard Portal

**Status**: ACTIVE (Phase 2 — Anthropic API sole provider 2026-05-25)  
**Paired with**: `token-budget-policy.md` §6-7  
**Last revised**: 2026-05-25

This document defines how the optional runtime AI API fallback behaves,
when it is allowed to fire, and how it is safely disabled by default.

---

## 1. Fallback is disabled by default

`ai_parser_enabled: bool = False` (existing gate in `config.py`)  
`ai_advisory_llm_enabled: bool = False` (Phase 1B addition to `config.py`)  
`ai_fallback_enabled: bool = False` (Phase 1B addition to `config.py`)

None of these flags may be set True in application defaults. They require
an explicit `.env` override on the target environment. A process that boots
with no `.env` override must behave as if AI is entirely absent.

Tests in `test_ai_token_governance.py` assert all three default to False.

---

## 2. Config fields (enforced by test)

| Field | Type | Default | Notes |
|---|---|---|---|
| `ai_parser_enabled` | bool | False | Existing — XML is source of truth |
| `ai_advisory_llm_enabled` | bool | False | Phase 2 advisory LLM |
| `ai_fallback_enabled` | bool | False | Master on/off for any fallback |
| `ai_advisory_max_tokens_per_call` | int | 1000 | Hard ceiling per call |
| `ai_advisory_budget_usd_per_day` | float | 1.0 | Daily trip-wire |
| `ai_advisory_cache_ttl_seconds` | int | 300 | Repeat-call suppression |
| `anthropic_api_key` | Optional[str] | None | Absent = no calls allowed |

---

## 3. Stop-condition decision tree

```
AI call requested
│
├─ ai_fallback_enabled == False?  → ABORT, return cached/deterministic
├─ anthropic_api_key absent?      → ABORT, return deterministic
├─ daily_spend >= budget_usd?     → ABORT, log BUDGET_EXCEEDED
├─ cache hit (TTL)?               → RETURN cached result, log CACHE_HIT
├─ estimated_input > max_tokens?  → ABORT, log TOKEN_LIMIT_EXCEEDED
└─ proceed → call API → log result hash
```

Every abort path MUST:
1. Return the deterministic (Phase 1) result, not an error.
2. Log the abort reason with batch_id and timestamp.
3. Never raise an exception to the caller.

---

## 4. Redaction before any API call

Applies all redaction rules from `token-budget-policy.md` §9.  
The call site is responsible — no delegation to callers.

---

## 5. Model constraints

Phase 2 advisory calls MUST use:
- Model: `claude-haiku-4-5-20251001` (lowest cost, fastest response)
- Max output: 500 tokens for explanation synthesis
- Temperature: 0 (deterministic output — matches Phase 1 contract)

The advisory model may NOT be `claude-opus-*` without explicit operator
approval and a cost-impact note in the PR description.

---

## 6. Provider architecture (locked 2026-05-25)

**Anthropic Claude API is the sole approved runtime AI provider.**

Full rationale and gate requirements: `docs/ai-governance/ai-capability-map.md` §10.
ADR: `.claude/adr/ADR-020-anthropic-api-sole-provider.md`.

| Path | Provider | Status |
|---|---|---|
| `ai_gateway.call()` Path B (default) | Anthropic API via `anthropic.Anthropic` | **ACTIVE** |
| `ai_gateway.call()` Path A (cowork, `AI_COWORK_ENABLED`) | Cowork stub — Anthropic SDK alias | **DEPRECATED — flag must stay false** |
| `ai_bridge.py` file coordination | Operator-assisted, file-based only | Operator-assist tool, not in-app LLM |
| Claude Code CLI | Engineering-time tool | Developer-only, not in-app LLM |

### Production config (live as of 2026-05-25)

```
AI_COWORK_ENABLED=false          # deprecated — must remain false
AI_FALLBACK_ENABLED=false        # deterministic path is default
AI_GATEWAY_DAILY_BUDGET_USD=2.00 # operator override from default $1.00
```

No second provider may be introduced without a new ADR superseding ADR-020 and explicit operator approval. This applies even if the cowork code path still exists in `ai_gateway.py` — existence in code does not equal authorization to activate.
