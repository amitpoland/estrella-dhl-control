# ADR-020: Anthropic Claude API as sole runtime AI provider

Status: Accepted
Date:   2026-05-25
Phase:  Phase 2 (post-canary lock-down)

## Context

Phase 2B (PR #357, 2026-05-24) introduced a dual-provider abstraction layer in
`service/app/services/ai_gateway.py`. Two call paths were designed:

- **Path A** ("cowork"): Anthropic SDK behind `AI_COWORK_ENABLED` flag with a
  separate key slot (`ai_cowork_api_key`). Intended to front an operator-side
  Claude instance as a "primary" provider with Anthropic API fallback.
- **Path B** (direct): `anthropic.Anthropic` using `settings.anthropic_api_key`
  directly — the approach used since Phase 1.

Phase 2C (PR #359, 2026-05-25) added governance hardening prerequisites.

On 2026-05-25, operator-approved 3-canary quality validation was completed using
Path B (Anthropic direct). All three canaries passed with clean signals, correct
domain diagnosis, and predictable cost ($0.000372/call average).

A provider architecture audit (executed same session) evaluated whether the cowork
path, the Claude Agent SDK, or Max plan subscription credits could serve as a
production AI provider. The audit found three independent blockers for the cowork
path in its current form:

1. **Python version incompatibility**: Claude Agent SDK requires Python ≥ 3.10.
   The production Windows service runs Python 3.9.6. Hard blocker.

2. **Billing unpredictability**: Max plan uses monthly subscription credits
   ($200/mo for Max 20x), not API key billing. The per-call cost tracking in
   `ai_call_ledger.py` (Rule 8) cannot reliably attribute spend to Max plan
   credits. `ai_advisory_budget_usd_per_day` becomes unenforceable.

3. **Windows Service subprocess model**: The cowork path's intended usage of
   `claude -p` as a subprocess is undocumented for NSSM-managed Windows services.
   No verified pattern exists for this deployment topology.

Path A was a stub in Phase 2B and never activated in production. The cowork
consolidated call path adds complexity with no validated benefit for Phase 2–6
scope (all Class-R and Class-A advisory calls).

## Decision

**Anthropic Claude API is the sole approved runtime AI provider** for all phases
from Phase 2 through Phase 10.

Every runtime LLM call goes through `ai_gateway.call()` Path B:
```
ai_gateway.call()
  └─ Path B: anthropic.Anthropic(api_key=settings.anthropic_api_key)
       └─ circuit breaker, budget guard, call log, cache
```

The cowork path (`AI_COWORK_ENABLED`) is deprecated. The flag must remain `false`
in all environments.

Developer and operator assist tools (Claude Code CLI, Max plan, `ai_bridge.py`
file coordination) remain available as **engineering-time** instruments. They are
categorically separate from the in-app `ai_gateway.py` call path and are never
runtime AI providers for the service.

## Consequences

**Positive**:
- One provider. One key slot. One circuit breaker. One budget counter.
- `ai_advisory_budget_usd_per_day` is enforceable — Anthropic API billing is
  per-token and maps directly to `actual_cost_usd` in `ai_call_ledger`.
- No Python version constraint: Path B works with Python 3.9.6 (production).
- Canary-validated quality: 3 real production batches confirmed correct domain
  diagnosis and no hallucinations.
- Simpler reasoning: every future phase only needs to specify model + max_tokens.
  No provider-selection logic in Phase 4–10 planning.

**Negative / accepted trade-offs**:
- Cowork Path A code remains in `ai_gateway.py` (removal is a code change, deferred
  to a future cleanup PR). The code is dormant — `AI_COWORK_ENABLED=false` ensures
  it is never reached.
- If a future use case genuinely requires a different provider (e.g., a task needing
  Claude's extended context via Max plan), a new ADR superseding this one is required.

## Rejected alternatives

- **Cowork as primary, Anthropic as fallback**: Rejected. Python version hard blocker.
  Billing unpredictable. No Windows Service subprocess pattern validated.
- **Max plan subscription as primary provider**: Rejected. Credits not trackable via
  per-call ledger. Monthly allocation not appropriate for per-call budget ceiling.
- **OpenAI as alternative provider**: Rejected. Not evaluated; no business requirement
  identified; would require new redaction rules for OpenAI data-handling terms.
- **Keep dual-path architecture open**: Rejected. Cowork path was a stub that adds
  complexity with zero validated benefit. Simplifying now avoids Phase 3–6 confusion
  about which path is authoritative.

## Gate for future provider additions

Any PR that introduces a second runtime AI provider MUST:
1. File a new ADR explicitly superseding this one with rationale.
2. Complete a 3-canary quality validation equivalent to the 2026-05-25 validation.
3. Resolve billing predictability against `ai_advisory_budget_usd_per_day`.
4. Verify compatibility with Python version on the production Windows service.
5. Receive explicit written operator approval before the gate is opened.

## Rollback

This ADR records a governance decision, not a deployment. The production service
already runs with `AI_COWORK_ENABLED=false`. No rollback is required or applicable.
If a future session accidentally sets `AI_COWORK_ENABLED=true`, the correct fix is
to reset it to `false` immediately — not to re-validate the cowork path.

## References

- `docs/ai-governance/ai-capability-map.md` §10 — Provider Lock-Down Decision
- `docs/ai-governance/api-fallback-policy.md` §6 — Provider Architecture
- `docs/ai-governance/ai-consolidation-inventory.md` §1D — External API Inventory
- `service/app/services/ai_gateway.py` — Path A/B implementation (cowork deprecated)
- `.claude/memory/PROJECT_STATE.md` — Canary validation facts, production config
- Phase 2B PR #357 (SHA 9574e94), Phase 2C PR #359 (SHA 40c30f1), PR #360 (SHA aa251b8)
