# Token Budget Policy — EJ Dashboard Portal

**Status**: ACTIVE (Phase 2 — Anthropic API sole provider 2026-05-25)  
**Enforced by**: `test_ai_token_governance.py`  
**Last revised**: 2026-05-25

This document defines the mandatory token-control rules for every AI surface
in this codebase. It supplements `ai-capability-map.md`. These rules bind
Claude Code engineering sessions and runtime AI surfaces equally.

---

## Rule 1 — Project token budget tiers

| Tier | Session type | Soft ceiling | Hard stop |
|---|---|---|---|
| T1 | Claude Code engineering (architecture, refactor) | 150k tokens | 300k tokens |
| T2 | Claude Code subagent call | 15k tokens output | 25k tokens output |
| T3 | Runtime AI API call (in-app, Phase 2+) | 2k tokens output | 4k tokens output |
| T4 | Advisory explanation call (Class R, Phase 2 LLM) | 500 tokens output | 1k tokens output |

Soft ceiling: log a WARNING and emit a `[TOKEN-SOFT-CEILING]` marker.  
Hard stop: abort call, return `{"ok": false, "error": "token_budget_exceeded"}`, log as ERROR.

---

## Rule 2 — Subagent output limits

Every subagent prompt launched from a campaign coordinator MUST include an
explicit output limit instruction. Accepted forms:
- `Report in under 25 lines.`
- `Return a JSON object with fields: X, Y, Z. Nothing else.`
- `Maximum 200 words.`

A subagent prompt that contains no output limit is a GATE 1 PR-blocker on
any PR that introduces a new subagent call.

---

## Rule 3 — When `/compact` is mandatory

Use `/compact` (Claude Code context compaction) before starting any task that:
- Follows a session already longer than 50 messages.
- Will read more than 10 distinct source files.
- Involves running the full test suite (10k+ tests).
- Requires browser verification of more than 3 distinct pages.

`/compact` is NOT a substitute for proper task scoping. It is a hygiene step.

---

## Rule 4 — When large files may be opened

A file ≥ 500 LOC must NOT be read fully unless:
- The task explicitly requires understanding the entire file's structure.
- No `grep`/`ripgrep` window can satisfy the information need.

For files 500–2000 LOC: use `grep -n` + targeted `Read(offset, limit)` windows.  
For files > 2000 LOC: use `grep -n` only unless a specific line range is known.  
Reading `routes_dhl_clearance.py` (2917 LOC) fully is always forbidden — use grep.

---

## Rule 5 — Large renderer file inspection protocol

Files in `service/app/static/` > 300 LOC (e.g. `shipment-detail.html` at ~12k LOC)
MUST be inspected using the following protocol:

```
grep -n "data-testid\|router\.post\|function.*(" file.html | head -50
grep -n "PATTERN" file.html
```

Never call `Read(file)` on a static HTML file > 300 LOC without a specific
`offset + limit`. Reading `shipment-detail.html` fully is always forbidden.

---

## Rule 6 — API fallback token and cost limits

See `api-fallback-policy.md` for the full stop-condition matrix.  
Summary:
- `ai_advisory_max_tokens_per_call`: 1000 (config, hard-enforced at call site)
- `ai_advisory_budget_usd_per_day`: 1.00 (config default) — **production override: $2.00/day** (set in Windows `.env` as of 2026-05-25; canary burn rate $0.000372/call avg → ~5,376 calls before $2.00 ceiling)
- `ai_fallback_enabled`: False by default — must be explicitly set True in `.env`
- Provider: Anthropic API only (sole provider as of 2026-05-25 — see `api-fallback-policy.md` §6)

---

## Rule 7 — API fallback stop conditions

An API fallback call MUST be aborted if any of the following are true at call time:
1. `ai_fallback_enabled` is False.
2. Daily spend counter has reached `ai_advisory_budget_usd_per_day`.
3. The call's estimated input tokens exceed `ai_advisory_max_tokens_per_call`.
4. `anthropic_api_key` is absent or empty.
5. The batch_id passed to the call has been seen in the last 5 minutes (cache hit).

Stop conditions are enforced inside the call site, not just at config-load time.

---

## Rule 8 — Prompt-hash and result-summary logging

Every runtime AI call (Phase 2+) MUST log:
```json
{
  "ts": "<iso8601>",
  "prompt_hash": "<sha256 of prompt text, hex>",
  "model": "<model_id>",
  "input_tokens": <int>,
  "output_tokens": <int>,
  "latency_ms": <int>,
  "cost_usd": <float>,
  "result_summary_hash": "<sha256 of response text, hex>",
  "cached": <bool>
}
```
This log is append-only, stored locally, never sent externally.  
No prompt text. No response text. Hashes only.

---

## Rule 9 — Redaction before external API use

Before any text is sent to an external AI API (Anthropic, OpenAI, etc.):

| Field type | Action |
|---|---|
| AWB / tracking numbers | KEEP — are shipment identifiers, not PII |
| Customer names | REDACT → `[CUSTOMER]` |
| Email addresses | REDACT → `[EMAIL]` |
| Phone numbers | REDACT → `[PHONE]` |
| NIP / VAT numbers | REDACT → `[VAT_ID]` |
| Bank account numbers | REDACT → `[BANK_ACCT]` |
| Passport / ID numbers | REDACT → `[ID_DOC]` |
| Full invoice PDF text | NEVER send raw — extract structured fields first |
| Email body raw text | NEVER send raw — pass only structured facts |

Redaction MUST happen in the call site, not delegated to the calling endpoint.  
Sending raw email or invoice content to an external API is a GATE 1 PR-blocker.

---

## Rule 10 — No repeated context replay

An AI call MUST NOT re-send context that was already processed in a prior
call within the same session if the underlying data has not changed.

Enforcement:
- Cache key: `sha256(batch_id + call_type + input_hash)`.
- TTL: 5 minutes for advisory calls, 30 minutes for classification calls.
- On cache hit: return cached result with `cached: true` in the response.
- Cache is in-process memory only (no Redis, no DB writes).

This prevents thundering-herd token spend when a browser refreshes the
advisory panel repeatedly.

---

## Rule 11 — Maximum final report size

| Report type | Soft limit | Hard limit |
|---|---|---|
| Campaign final report | 120 lines | 200 lines |
| Subagent verdict | 25 lines | 40 lines |
| Browser verification log | 20 lines | 40 lines |
| Test run summary | 10 lines | 20 lines |

Reports exceeding the hard limit MUST be truncated, not streamed in full.
Large log output belongs in a file on disk, cited by path.

---

## Rule 12 — Budget-risk escalation to operator

Claude Code MUST stop and request operator approval when:
1. A task requires opening > 20 source files (not grep-inspected, but fully read).
2. A campaign is estimated to exceed T1 hard stop (300k tokens).
3. A test run is about to execute the full 10k+ suite without a `-k` filter.
4. A runtime AI call would exceed Rule 6 cost limits.
5. Any action would incur an irreversible production change.

Escalation is NOT required for:
- Grep/ripgrep inspection of any file (zero token cost on grep lines).
- Running a targeted `pytest -k` suite under 500 tests.
- Writing new files under 200 LOC.
