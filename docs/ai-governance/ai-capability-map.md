# AI Capability Map — EJ Dashboard Portal

**Status**: ACTIVE (Phase 2)
**Owner**: orchestrator + reviewer-challenge
**Last revised**: 2026-05-24

This document is the single source of truth for *where AI may run* inside the
EJ Dashboard Portal, *what class of AI each insertion point is*, and *what
gates separate AI output from production state*. It supersedes any informal
"we use AI for X" understanding elsewhere in the codebase.

It is paired with Lesson E (background email automation safety) and Lesson F
(V2 frontend authority isolation). Read both before extending this map.

---

## 1. The Four AI Classes

Every AI surface in this codebase falls into exactly one class. The class
determines blast radius, gate location, and review intensity.

| Class | Definition | Can mutate production state? | Gate |
|---|---|---|---|
| **R — Read-only AI** | Reads existing authority output; renders explanation or summary. Never proposes an action. | No | None beyond standard auth |
| **A — Advisory AI** | Reads authority output; proposes a *next step* for the operator. Operator chooses whether to act. | No | UI surface must label as advisory |
| **D — Draft-generation AI** | Produces a draft artifact (email body, PZ note text, description) that an operator may edit and then submit through the normal write path. | No (drafting only) | Output must be inspectable + editable before any submission |
| **X — Operator-approved action AI** | Proposes a structured action (e.g. "send DHL reply", "create PZ"). Execution is gated behind `/api/v1/execute/{action}` with operator approval. | Only via `execute_action` and only after explicit approve | Mandatory: routes through `routes_execute.py`, must produce idempotency key, must log execution |

There is no "autonomous-write" class. AI never bypasses
`routes_execute.py`. No AI module imports `wfirma_writer`, DHL send paths,
or accounting write paths directly. (See §6 for the enforcement list.)

---

## 2. Engineering-time vs Runtime AI

| Surface | Engineering-time (Claude Code) | Runtime (in-app) |
|---|---|---|
| Code generation, refactors, test scaffolding | YES — this is Claude Code's job | NO |
| Architecture proposals, ADRs, capability mapping | YES | NO |
| `service/app/services/ai_advisory.py` (new) | NO — built by Claude Code, runs as deterministic service | YES |
| `routes_intelligence.py` heuristics | NO | YES (deterministic, no LLM call) |
| `routes_ai_bridge.py` external task bridge | NO | YES (operator-bridged to external AI tools) |
| Future LLM-backed advisory (Phase 2+) | NO | YES — gated, audited, opt-in |

Engineering-time AI never holds a database connection. Runtime AI never edits
source files.

---

## 3. Insertion Point Inventory (current main)

| Path | Class | What it does | Touches `/execute`? |
|---|---|---|---|
| `service/app/api/routes_intelligence.py` | R + A | Heuristic suggestions, classification, status. No LLM. | No |
| `service/app/api/routes_ai_bridge.py` | D | Generates structured task envelopes for external AI; imports operator-edited results back. | No — results land as drafts |
| `service/app/api/routes_action_proposals.py` | X | Proposes actions, approve/reject/queue lifecycle. | Yes — queued actions route through `/execute` |
| `service/app/api/routes_execute.py` | (gate) | Single write-action gate. `wfirma_create`, `closure_confirm`, `dhl_send_reply`. | (is the gate) |
| `service/app/services/ai_customs_evidence.py` | R | Customs document evidence extraction (deterministic). | No |
| `service/app/services/ai_customs_parser.py` | R | Customs parser. | No |
| `customs_description_engine.py` | A | Generates Polish customs description proposals. | No |
| `polish_description_generator.py` | D | Description draft generator. | No |
| `learning_agent.py`, `invoice_learning_agent.py` | R | Pattern learning from prior batches. | No |

**Phase 1 additions (PR #307, 2026-05-23):**

| Path | Class | What it does | Touches `/execute`? |
|---|---|---|---|
| `service/app/services/ai_advisory.py` | R | Computes deterministic "why is this workflow blocked?" explanation from `batch_readiness`. | No |
| `service/app/api/routes_ai_advisory.py` | R | Exposes `GET /api/v1/ai/advisory/workflow-blockers/{batch_id}`. | No |
| `service/app/static/ai-advisory-v2.html` | R | Standalone V2-aligned page rendering the explanation. NOT a modification to V1. | No |

**Phase 2 additions (PR #TBD, 2026-05-24):**

| Path | Class | What it does | Touches `/execute`? |
|---|---|---|---|
| `service/app/services/ai_advisory.py` | R | Phase 2 upgrade: opt-in LLM synthesis via `ai_gateway.call()`. Flag: `ai_advisory_llm_enabled` (default False). Deterministic fallback preserved. | No |
| `service/app/api/routes_ai_advisory.py` | R | New: `GET /api/v1/ai/advisory/status` — observability endpoint for flag state, budget, gateway health. | No |

Phase 2 LLM call parameters: `task_type="advisory_explanation"`, `service_name="ai_advisory"`, `complexity="simple"`, `risk_level="low"`. Budget ceiling: `ai_advisory_budget_usd_per_day` (default $1.00/day). TTL cache: `ai_advisory_cache_ttl_seconds` (default 300s). Response field `llm_used=True` only when LLM call succeeded; `source="batch_readiness+llm"` distinguishes from Phase 1 deterministic path (`source="batch_readiness"`). All Phase 1 contracts unchanged.

**Pre-existing LLM services (retroactively classified 2026-05-23):**

These existed on main before Phase 1 and have active Anthropic API calls.
They are Class-R and within T3 token budget. They are missing a Rule 8 call-log.
Remediation: wire both into `ai_call_ledger.py` by Phase 3 close.

| Path | Class | Model | max_tokens | What it does | Touches `/execute`? |
|---|---|---|---|---|---|
| `service/app/services/ai_customs_parser.py` | R | claude-sonnet-4-6 | 2000 | Customs PDF parsing fallback when deterministic parser fails. | No |
| `service/app/services/ai_customs_evidence.py` | R | claude-sonnet-4-6 | 1500 | Customs evidence extraction from documents. | No |

---

## 4. Phase 1 design rationale and Phase 2 LLM contract

Phase 1 established the contract: **AI advisory is read-only, derived from
existing authority output, and provably cannot mutate state.** The no-LLM
design was intentional — separating authority-leakage risk from prompt-injection
risk into distinct phases.

Phase 2 wires LLM into `ai_advisory.explain_workflow_blockers()` under the
same contract (no writes, no `/execute` calls, no domain authority redefinition).
The prompt-injection posture: `_build_user_prompt()` receives **only structured
fields** from `batch_readiness` authority output — status codes, domain names,
short deterministic message strings. Raw email text, supplier documents, and
operator free-form input are never passed to the model. The input surface is
closed; prompt-injection risk is minimal by construction.

---

## 5. Where AI explanations may render

| Surface | Allowed? | Reason |
|---|---|---|
| New V2 page (e.g. `ai-advisory-v2.html`) | YES | New surface, single-domain (advisory), no V1 freeze conflict (Lesson F). |
| `shipment-detail.html` (V1) | NO — frozen | Lesson F: V1 accepts critical fixes only. |
| `dashboard.html` (V1) | NO — frozen | Same. |
| `proforma-v2.html` (V2) | LATER | Cross-domain coupling; defer until proforma-v2 authority is stable. |
| `dashboard-v2.html` (future) | LATER | Dashboard-v2 is built last per Lesson F. |

The Phase 1 surface is therefore a standalone V2 page. It calls the advisory
endpoint and renders the explanation. It does not import V1 helpers, does
not register on V1 navigation, and does not introduce a new authority.

---

## 6. Forbidden-Action List (binding on every AI module)

Any module classified under §1 (R / A / D / X) MUST NOT do any of the
following. Source-grep tests in `test_ai_advisory_no_writes.py` enforce a
representative subset; reviewers enforce the rest.

1. Call `wfirma_writer.*`, `wfirma_create_*`, or any wFirma write helper.
2. Call DHL send paths (`dhl_*_send`, `email_service.queue_email`,
   `email_service.send`).
3. Call `execute_action(...)` directly — even with `dry_run=True`.
4. Open a database connection in write mode.
5. Mutate `audit.json`, `timeline.json`, or any per-batch evidence file.
6. Issue HTTP requests to live DHL, wFirma, or carrier endpoints.
7. Re-derive financial truth (CIF, duty, freight allocation) — those are
   `process_batch()`'s exclusive authority.
8. Redefine readiness (`ready_for_closure`) — `batch_readiness` owns this.

Violation of any item is a GATE 1 PR-blocker.

---

## 7. Prompt-injection posture (binding as of Phase 2)

Phase 2 ships with an LLM call in `ai_advisory.py`. The posture is now active:

- Untrusted text (DHL email body, supplier document text, customer message)
  MUST be passed to any future LLM as data, never as instructions.
- Any LLM-produced action proposal MUST be re-validated against the same
  authority gates as a human proposal — there is no "trusted because LLM"
  path.
- An LLM's free-form output MUST NOT be fed back into another LLM step
  without operator review when the second step's output would influence a
  write decision.
- All LLM calls MUST log: prompt template id, input hash, output hash,
  model id, latency, cost — to a separate ai-call ledger.

---

## 8. Governance gate map

| Stage | Owner | Artefact |
|---|---|---|
| Capability classification | this document | §1, §3 |
| Insertion-point review | reviewer-challenge | each new PR |
| No-write enforcement | `test_ai_advisory_no_writes.py` + reviewer | every AI module |
| Operator-approved-action gate | `routes_execute.py` | runtime |
| Browser verification | CLAUDE.md §6 / Lesson F | new V2 pages |
| Self-evaluation | `agent-performance-observer` | per-campaign |

---

## 9. Phase plan

Full roadmap detail: `docs/ai-governance/ai-roadmap-phase2-to-phase10.md`

- **Phase 1 — CLOSED, live on production** (SHA 74ff7a8, 2026-05-23). Capability map, advisory skeleton, read-only endpoint, V2 page, no-write tests, token-budget policy, API fallback policy.
- **Phase 2 — SHIPPED (2026-05-24, PR #TBD)**. LLM wired into `ai_advisory.explain_workflow_blockers()` via `ai_gateway.call()`. Feature flag `ai_advisory_llm_enabled` (default False). `ai_call_ledger` logging. `GET /api/v1/ai/advisory/status` endpoint. 25 new tests (82 total advisory). All flags deploy OFF. Deploy manifest: `.claude/manifests/windows_deploy_phase2_advisory.ps1`.
- **Phase 3** — Centralize call-log into `ai_call_ledger.py`. Retrofit pre-existing LLM services (ai_customs_parser, ai_customs_evidence). In-process cache.
- **Phase 4** — Customer Master Intelligence. VAT/EU VAT advisory, completeness scoring, duplicate candidate detection. Class-A, new V2 page.
- **Phase 5** — Product / Finishing Intelligence. Description quality, missing metal/stone/carat fields, wfirma_product_id sync gaps. Class-A.
- **Phase 6** — Document Intelligence. Invoice/packing mismatch advisory, SAD/ZC429 gap explanation. Extends ai_customs_*. Class-R+A. Rule 9 (no raw PDF) mandatory.
- **Phase 7** — Natural-language search over timeline/audit. Class-R, dashboard-v2 dependency.
- **Phase 8** — Action Proposal Advisor. Class-X. Proposes wfirma_create/dhl_send_reply/closure_confirm via routes_action_proposals.py. NEVER calls execute_action directly.
- **Phase 9** — Operations Assistant. Management summaries. Class-A. No PII in prompts.
- **Phase 10** — Controlled optimization and forecasting. Class-A analytics only. No automated decisions.

No phase relaxes §6.
Each phase ships disabled-by-default, behind a config flag, with its own PR and 7-agent deploy gate.
