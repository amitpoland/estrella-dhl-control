# AI Consolidation Inventory — EJ Dashboard Portal

**Status**: UPDATED (Phase 2 SHIPPED — Anthropic API sole provider locked 2026-05-25)
**Owner**: orchestrator + security-permissions
**Last revised**: 2026-05-25
**Purpose**: Complete platform-wide inventory of every AI/LLM execution path, governance
gaps, and the migration work required before Phase 2 ships.

> **Provider lock-down note (2026-05-25)**: Phase 2, Phase 2B, Phase 2C shipped and deployed.
> 3-canary quality validation complete. Anthropic Claude API confirmed as sole production
> runtime AI provider. Cowork path (Phase 2B stub) is DEPRECATED — `AI_COWORK_ENABLED` must
> remain false. See `ai-capability-map.md` §10 and ADR-020 for full rationale.

This document is the discovery output of the AI Consolidation Campaign
(2026-05-23). It supersedes any informal understanding of "what uses AI."

---

## 1. Complete AI Inventory

### 1A — Live LLM Services (Anthropic API, active on main)

| Service | Path | Model | max_tokens | Trigger | Class |
|---|---|---|---|---|---|
| `ai_customs_parser` | `service/app/services/ai_customs_parser.py` | claude-sonnet-4-6 | 2000 | Deterministic parser fails | R |
| `ai_customs_evidence` | `service/app/services/ai_customs_evidence.py` | claude-sonnet-4-6 | 1500 | Low-confidence evidence recovery | R |

Both services were absent from the capability map §3 prior to 2026-05-23.
Both are retroactively classified Class-R. Neither touches `/execute`.
Remediation of governance gaps is tracked below.

### 1B — Deterministic AI Services (no LLM calls)

These services have "AI" or "intelligence" in their names but make no external API calls.
They are listed here to prevent re-investigation.

| Service | Path | What it actually does |
|---|---|---|
| `ai_advisory` | `service/app/services/ai_advisory.py` | Rule-based workflow-blocker explanation from `batch_readiness` |
| `intelligence_engine` | `service/app/services/intelligence_engine.py` | Heuristic scoring, status classification |
| `proforma_intelligence` | `service/app/services/proforma_intelligence.py` | Deterministic proforma readiness scoring |
| `customs_description_engine` | `customs_description_engine.py` | Polish customs description proposals (rule-based) |
| `polish_description_generator` | `polish_description_generator.py` | Description draft generation (rule-based) |
| `learning_agent` | `service/app/services/learning_agent.py` | Pattern matching from prior batches (no LLM) |
| `invoice_learning_agent` | `service/app/services/invoice_learning_agent.py` | Invoice pattern matching (no LLM) |
| `ai_bridge` | `service/app/api/routes_ai_bridge.py` | File-based task envelope coordination with external AI tools |
| `cowork_coordinator` | `service/app/agents/cowork_coordinator.py` | Rule-based automation; calls `queue_email()` (Lesson E compliant) |

### 1C — Document Processing Pipeline

| Component | Library | External API? | Notes |
|---|---|---|---|
| PDF extraction | `pdfplumber` | No | All PDF parsing is local |
| OCR | None | No | No OCR library in use; no vision API |
| LLM document input | Text-only via `pdfplumber` | Yes (Anthropic) | First 8000 chars of extracted text only |
| Image processing | None | No | No image-to-text pipeline exists |

PDF content is truncated to 8000 characters before any LLM call.
Neither service sends raw binary, images, or full document blobs to Anthropic.

### 1D — External API Inventory (all AI)

| Provider | API client | Auth | Services using it | Status |
|---|---|---|---|---|
| Anthropic | `anthropic.Anthropic` (direct) + via `ai_gateway.py` | `settings.anthropic_api_key` | `ai_customs_parser`, `ai_customs_evidence`, `ai_advisory` | **SOLE PROVIDER — ACTIVE** |
| Cowork (Phase 2B stub) | `anthropic.Anthropic` (separate key slot) | `settings.ai_cowork_api_key` | None (stub, never used in production) | **DEPRECATED 2026-05-25** |
| OpenAI | None | — | No OpenAI usage anywhere in codebase | Not used |

**Provider decision (2026-05-25)**: Anthropic Claude API is confirmed as the only runtime AI provider after 3-canary validation. The cowork path in `ai_gateway.py` (Path A, `AI_COWORK_ENABLED`) is deprecated. The flag defaults False and must not be flipped. ADR-020 records the formal decision.

---

## 2. Governance Gap Inventory

Eight gaps were identified across the two live LLM services.
Severity: **HIGH** = must resolve before Phase 2 ships; **MEDIUM** = resolve before Phase 3.

### Gap 1 — No Rule 8 call-log (BOTH SERVICES) — HIGH

**What Rule 8 requires** (from `ai-capability-map.md` §7):
Every LLM call must log: `prompt_template_id`, `input_hash`, `output_hash`, `model_id`,
`latency_ms`, `cost_usd`, `cached` — to a separate AI call ledger. Raw text must NOT be
logged.

**Current state**: Neither service logs any of these fields. There is no `ai_call_ledger.py`
module anywhere in the codebase.

**Where to fix**: Phase 3 — `ai_call_ledger.py` creation + retrofit of both services.

---

### Gap 2 — No redaction before LLM call (BOTH SERVICES) — HIGH

**Risk**: Customer names, VAT numbers, addresses, invoice reference numbers may be present
in PDF-extracted customs document text and transmitted to Anthropic's API verbatim.

**Current state**: Neither service applies any redaction transform before the API call.
`carrier/persistence/redactor.py` exists (confirmed by prior audit) but is not wired to
either AI service.

**Redaction table required** (before Phase 2):
```
customer_name     → [CUSTOMER]
vat_number        → [VAT_ID]
eu_vat_number     → [EU_VAT]
address_lines     → [ADDRESS]
invoice_ref       → [INV_REF]
```

**Where to fix**: Phase 6 prerequisite for document intelligence; partial retrofit to
existing services in Phase 3 alongside call-log.

---

### Gap 3 — `ai_parser_enabled` flag not wired at service level — ✅ PATCHED (Phase 3A, 2026-05-23)

**Was**: Flag only enforced at `customs_parser_orchestrator.py:446`. Direct callers bypassed it.

**Fix applied**:
- `ai_customs_parser.py` — added `ai_parser_enabled` check immediately after api_key check.
  Returns `None` when flag is `False`, before any PDF extraction or Anthropic client creation.
- `ai_customs_evidence.py` — added `ai_parser_enabled` check inside `_provider_available()`.
  Gate returns `False` when flag is `False`; `extract_customs_evidence()` returns `None`.

**Tests added**: `service/tests/test_ai_safety_flag_gate.py` — 10 tests:
- Returns None when disabled (both services)
- No Anthropic client instantiated when disabled (both services)
- No API call attempted when disabled (both services)
- Disabled flag beats valid API key present (both services)
- Enabled path still returns dict (both services)

**Verification**: 10/10 new tests pass; 49/49 existing AI/customs tests pass, zero regressions.

---

### Gap 4 — No caching (BOTH SERVICES) — MEDIUM

**Risk**: Identical PDF extracts (retried batches, duplicate document uploads) trigger
redundant Anthropic API calls with identical cost.

**Current state**: No in-process or persistent cache on either service.

**Recommended approach**: SHA-256 of the truncated text string as cache key;
in-process dict with TTL (Phase 3 `ai_call_ledger.py` can own the cache layer).

---

### Gap 5 — No retry logic for API failures (BOTH SERVICES) — MEDIUM

**Risk**: Transient Anthropic API errors (429 rate limit, 503) propagate as exceptions
directly to callers with no retry.

**Current state**: Neither service implements retry or exponential backoff.

**Recommended approach**: Max 3 retries, exponential backoff 1s/2s/4s, retry only on
`anthropic.RateLimitError` and `anthropic.APIStatusError` (5xx). No retry on 4xx (bad
input).

---

### Gap 6 — No timeout on LLM calls (BOTH SERVICES) — MEDIUM

**Risk**: Slow Anthropic responses (network latency, overloaded API) block the request
thread indefinitely.

**Current state**: `anthropic.Anthropic()` is instantiated with no `timeout` parameter.

**Recommended approach**: 30-second timeout. If exceeded, log the attempt as TIMEOUT in
call-log and return `None` (same as no-API-key path).

---

### Gap 7 — No cost / budget tracking (BOTH SERVICES) — MEDIUM

**Risk**: Unexpected PDF volume spikes (a large batch, a retry loop) can run up API costs
with no visibility until the monthly invoice.

**Current state**: Neither service tracks input/output token counts or estimated cost.

**T3 budget ceiling** (from `token-budget-policy.md`): 2k/4k max_tokens per call (both
services already comply on max_tokens). Cost tracking per call and daily ceiling enforcement
are not yet wired.

---

### Gap 8 — Dual independent client instantiation — LOW

**Risk**: Each service instantiates its own `anthropic.Anthropic` client independently.
This makes it impossible to:
- Apply global middleware (timeout, redaction, call-log) in one place
- Rotate API keys without touching multiple files
- Enforce stop conditions uniformly

**Current state**: Two separate `anthropic.Anthropic(api_key=api_key)` instances at:
- `ai_customs_parser.py` line 104
- `ai_customs_evidence.py` line 250

---

## 3. Duplication Analysis

| Concern | Duplicated across | Unified target |
|---|---|---|
| `anthropic.Anthropic` instantiation | 2 files | `ai_gateway.py` |
| API key retrieval (`getattr(settings, "anthropic_api_key", None)`) | 2 files | `ai_gateway.py` |
| Inline hardcoded system prompts | 2 files | `ai_gateway.py` prompt registry |
| Fallback-on-None return pattern | 2 files | `ai_gateway.py` |
| PDF text truncation (8000 chars) | 1 file | Shared input normaliser |

There are no duplicate LLM providers (no OpenAI alongside Anthropic).
There is no duplicate PDF library (pdfplumber only).
The duplication problem is architectural (no shared client) not data-integrity.

---

## 4. Unified AI Gateway Architecture

**Recommended module**: `service/app/services/ai_gateway.py`

This is a thin coordination module — it does not contain business logic. Every runtime
LLM call routes through it.

```
caller
  └─→ ai_gateway.call(prompt_template_id, vars, max_tokens, model)
         ├─ stop-condition check (ai_parser_enabled flag)
         ├─ redact(vars)  ← redactor.py wired here
         ├─ build prompt from template registry
         ├─ cache lookup (SHA-256 of redacted prompt)
         │    hit → log CACHED=True → return cached result
         │    miss → continue
         ├─ anthropic.Anthropic(api_key).messages.create(timeout=30)
         │    retry: max 3, exponential backoff, 429+5xx only
         ├─ log to ai_call_ledger (prompt_template_id, input_hash, output_hash,
         │                          model, latency_ms, cost_usd, cached)
         └─ return result
```

**What the gateway does NOT do**:
- Does not contain customs parsing logic
- Does not interpret API responses
- Does not write to database
- Does not call `/execute`

**Prompt templates**: Inline prompts from both services migrate to a template registry
inside the gateway (dict keyed by template ID). No raw f-strings in service code.

**Phase assignment**: `ai_gateway.py` is the first deliverable of Phase 3.

---

## 5. Migration Roadmap

### Before Phase 2 ships (blocking)

Phase 2 wires a real LLM call into `ai_advisory.synthesise_explanation()`. The call-log
and flag-gate gaps must exist in working form before Phase 2 ships, because Phase 2 adds
a third live LLM service and amplifies every existing gap.

| Task | Target file | Gap closed |
|---|---|---|
| Build `ai_gateway.py` (client + timeout + retry) | NEW | Gap 8, Gap 5, Gap 6 |
| Wire `ai_parser_enabled` flag inside `ai_customs_parser` | `ai_customs_parser.py` | Gap 3 |
| Wire `ai_parser_enabled` flag inside `ai_customs_evidence` | `ai_customs_evidence.py` | Gap 3 |
| Build `ai_call_ledger.py` (SQLite append, no raw text) | NEW | Gap 1 |
| Wire call-log into `ai_customs_parser` via gateway | `ai_customs_parser.py` | Gap 1 |
| Wire call-log into `ai_customs_evidence` via gateway | `ai_customs_evidence.py` | Gap 1 |

These six tasks are Phase 3 work but are **Phase 2 preconditions**.
Phase 3 must ship before or simultaneously with Phase 2. See
`ai-roadmap-phase2-to-phase10.md` §Phase 3 for full implementation spec.

### Phase 3 (complete retrofitting)

| Task | Gap closed |
|---|---|
| In-process cache inside gateway | Gap 4 |
| Cost tracking (token count × model price) per call | Gap 7 |
| Partial redaction for customs text (structured fields only) | Gap 2 partial |

### Phase 6 (document intelligence — full redaction)

| Task | Gap closed |
|---|---|
| Full redaction table wired to all LLM calls (Rule 9) | Gap 2 complete |
| No raw PDF text to any external API (Rule 9 enforcement) | Gap 2 complete |

---

## 6. Services That Must Be Retrofitted Before Phase 2

| Service | What retrofit is required | When |
|---|---|---|
| `ai_customs_parser.py` | Route through `ai_gateway.py`; add flag check; add call-log | Phase 3 (before Phase 2 merge) |
| `ai_customs_evidence.py` | Route through `ai_gateway.py`; add flag check; add call-log | Phase 3 (before Phase 2 merge) |
| `ai_advisory.py` | Wire new LLM call through `ai_gateway.py` from day one (no retrofit needed — built fresh) | Phase 2 |

All three services must use `ai_gateway.py` by the time Phase 2 is live on main.

---

## 7. Source-Grep Verification Tests (required at Phase 3 close)

Phase 3 must ship with tests that enforce the gateway contract. Minimum required:

```python
# test_ai_gateway_contract.py

# 1. No service imports anthropic directly
assert grep("from anthropic", "services/ai_customs_parser.py") == []
assert grep("from anthropic", "services/ai_customs_evidence.py") == []
assert grep("import anthropic", "services/ai_customs_parser.py") == []
assert grep("import anthropic", "services/ai_customs_evidence.py") == []

# 2. Both services check ai_parser_enabled before any LLM call
assert grep("ai_parser_enabled", "services/ai_customs_parser.py") != []
assert grep("ai_parser_enabled", "services/ai_customs_evidence.py") != []

# 3. ai_call_ledger is called inside ai_gateway
assert grep("ai_call_ledger", "services/ai_gateway.py") != []

# 4. No raw text logged (Rule 8)
assert grep("log.*body", "services/ai_gateway.py") == []
assert grep("log.*text", "services/ai_gateway.py") == []
```

---

## 8. References

- `docs/ai-governance/ai-capability-map.md` — canonical class definitions and insertion point registry
- `docs/ai-governance/ai-roadmap-phase2-to-phase10.md` — per-phase token budgets and implementation specs
- `docs/ai-governance/token-budget-policy.md` — T1–T4 tier rules and ceiling enforcement
- `docs/ai-governance/api-fallback-policy.md` — fail-open / fail-closed policy per service class
- `.claude/memory/scorecards/2026-05-23-ai-governance-master-bootstrap.md` — GATE 4 dispositions for pre-existing gaps
