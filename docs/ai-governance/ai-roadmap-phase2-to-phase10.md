# AI Maturity Roadmap — EJ Dashboard Portal
# Phases 2 to 10

**Status**: ACTIVE — Phase 2 SHIPPED (2026-05-25). Anthropic API confirmed as sole production provider.
**Authority**: docs/ai-governance/ai-capability-map.md §1 (class definitions), §6 (forbidden-action list), §10 (provider lock-down)
**Token governance**: docs/ai-governance/token-budget-policy.md (binding on every phase)
**API fallback**: docs/ai-governance/api-fallback-policy.md (binding on every phase)
**Paired with**: Lesson E (email automation safety), Lesson F (V2 authority isolation)
**Provider ADR**: `.claude/adr/ADR-020-anthropic-api-sole-provider.md`

This document is the single source of truth for the phased AI maturity plan.
No phase relaxes capability-map §6. Every phase ships disabled-by-default.
No phase may start until the preceding phase is CLOSED and live on production.

---

## Platform-wide Authority Map

| Domain | Authority module | Notes |
|---|---|---|
| Customer Master | `services/customer_master.py` | CustomerMasterResolver |
| Product Master | `services/wfirma_db.py` | get_product(), get_products_batch() |
| Inventory lifecycle | `services/inventory_state_engine.py` | State engine, lifecycle phases |
| Batch readiness / gating | `services/batch_readiness.py` | get_batch_readiness() — only source allowed |
| PZ/wFirma write | `services/wfirma_client.py` | Only via routes_execute.py gate |
| DHL/Customs | `services/dhl_clearance_coordinator.py` | Coordinator + manifest + SAD parser |
| Action execution gate | `api/routes_execute.py` | Single write-action gate for all Class-X |
| Proforma | `api/routes_proforma.py` | _build_preview() canonical authority |
| Invoice/packing parser | `services/invoice_packing_extractor.py` | Structured extraction authority |
| Audit / timeline | `services/inventory_batch_state.py` | EV_ events, append-only |
| Workflow explanation | `services/ai_advisory.py` | Class-R, wraps batch_readiness only |

AI modules MUST read from these authorities. AI modules MUST NOT define parallel
authority, re-derive financial truth, or redefine readiness.

---

## Pre-existing Live LLM Services (retroactively classified)

These services have active Anthropic API calls on main. They are NOT Phase 2 additions.
They are retroactively mapped here so future governance does not double-classify them.

| Service | Class | Model | max_tokens | Phase mandate |
|---|---|---|---|---|
| `ai_customs_parser.py` | R | claude-sonnet-4-6 | 2000 | Must add Rule 8 call-log by Phase 3 |
| `ai_customs_evidence.py` | R | claude-sonnet-4-6 | 1500 | Must add Rule 8 call-log by Phase 3 |

Both are within the T3 hard stop (4000 tokens). Both are read-only.
Neither exports to wFirma or execute_action. Gap: no call-log exists yet (Rule 8 violation).
Remediation: add call-log to both before Phase 3 closes.

---

## Phase 2 — Gated LLM Explanation

**Goal**: Wire Anthropic LLM into `ai_advisory.synthesise_explanation()` behind
`ai_advisory_llm_enabled` flag. Operator sees richer natural-language explanation
of why a batch is blocked. No change to authority structure.

| Item | Value |
|---|---|
| Class | R (read-only) — no writes, no proposals |
| Authority owner | batch_readiness.get_batch_readiness() — unchanged |
| Model | claude-haiku-4-5-20251001 (Haiku mandatory — api-fallback-policy §5) |
| max_tokens | 500 output (T4 tier) |
| Token budget | $1.00/day, 1000 tokens/call (from config defaults) |
| Forbidden | All §6 items. No action proposals. No customer/product data in prompt. |
| Redaction | batch_id + domain status only in prompt. No PII. |
| Prompt-injection | Input is structured dict from batch_readiness — not raw user text. Low risk. |
| Flag | `ai_advisory_llm_enabled=False` in config — flip to True in .env to enable |
| Fallback | On abort/timeout/budget: return Phase 1 deterministic result unchanged |
| Tests required | (1) llm_used=True in response when flag=True. (2) prompt_hash logged per Rule 8. (3) Cache hit suppresses second call within TTL. (4) Budget trip-wire aborts at $1.00/day. (5) Fallback to deterministic on any error. (6) All Phase 1 source-grep tests still pass. |
| Deploy gate | 7-agent gate + Rule 8 call-log file confirmed on disk |
| Rollback | Set `ai_advisory_llm_enabled=False` in .env — zero code change needed |
| "Done" criteria | llm_used=True visible in ai-advisory-v2.html response, call-log file growing, Phase 1 contract tests green, $0 spend when flag=False |

---

## Phase 3 — AI Call Ledger and Caching

**Provider note**: All Phase 3 LLM calls use Anthropic Claude API exclusively (Path B direct via `ai_gateway.py`). The cowork path (`AI_COWORK_ENABLED`) is deprecated as of 2026-05-25. The cowork consolidation sub-task originally planned for Phase 3 is CANCELLED. Phase 3 scope: ledger + cache + retrofit of `ai_customs_parser.py` / `ai_customs_evidence.py` only.

**Goal**: Centralize the Rule 8 call-log requirement into a shared `ai_call_ledger.py`
service. Retrofit ai_customs_parser.py and ai_customs_evidence.py (pre-existing LLM calls)
to write to the ledger. Add Redis-free in-process cache shared across all AI services.

| Item | Value |
|---|---|
| Class | Infrastructure (no new AI surface) |
| Authority owner | New: `services/ai_call_ledger.py` |
| Token budget | No additional calls; audit only |
| Forbidden | Ledger is append-only; no deletion, no external upload |
| Tests required | (1) Every LLM call produces a ledger entry. (2) Duplicate call within TTL returns cached=True with no new ledger entry. (3) Ledger survives PZService restart (file-backed). (4) Retroactive: ai_customs_parser and ai_customs_evidence write to ledger. |
| Deploy gate | Standard 7-agent gate |
| "Done" criteria | Unified ledger file on disk, all 3 LLM services writing to it, cache hit rate visible in ledger |

---

## Phase 4 — Customer Master Intelligence

**Goal**: Advisory surface for customer completeness gaps, EU VAT validation status,
and potential duplicate contractor detection. Class-A (operator sees advisory; no write).

| Item | Value |
|---|---|
| Class | A (advisory — operator chooses whether to act) |
| Authority owner | `services/customer_master.py` — read only |
| New surface | New V2 page: `customer-intelligence-v2.html` (NOT on V1 frozen pages) |
| New endpoint | `GET /api/v1/ai/advisory/customer-completeness/{contractor_id}` |
| AI task | Score customer completeness (nip, vat_eu_number, ship_to, payment_method). Flag EU VAT not validated. Surface likely duplicates by name/VAT similarity. |
| Model | claude-haiku-4-5-20251001 |
| max_tokens | 500 (T4) |
| Redaction | Customer names → [CUSTOMER], VAT → [VAT_ID] before external API call |
| Forbidden | No write to customer_master_db. No wfirma_client call. No contractor creation. |
| Tests required | (1) No-write source-grep proof. (2) Completeness score for complete customer = 1.0. (3) Missing VAT = flagged in advisory. (4) Redaction verified before API call. (5) Duplicate candidates returned only as advisory — no auto-merge. |
| "Done" criteria | Operator can open a customer record and see completeness advisory without triggering any write |

---

## Phase 5 — Product / Finishing Intelligence

**Goal**: Advisory surface for product description quality, missing finishing fields
(metal, stone, carat), and product-code sync gaps between invoice and wFirma.

| Item | Value |
|---|---|
| Class | A (advisory) |
| Authority owner | `services/wfirma_db.py` + `services/invoice_packing_extractor.py` |
| New surface | Inline panel in proforma-v2.html (once proforma-v2 authority is stable per Lesson F) |
| New endpoint | `GET /api/v1/ai/advisory/product-completeness/{product_code}` |
| AI task | Score description quality. Identify missing finishing fields (metal/stone/carat from invoice position vs product master). Flag wfirma_product_id gaps. |
| Model | claude-haiku-4-5-20251001 |
| max_tokens | 500 (T4) |
| Redaction | Product codes stay; supplier names → [SUPPLIER] |
| Forbidden | No write to product master. No wfirma_create. No description overwrite. |
| Dependency | Phase 3 call-ledger must be live before Phase 5 ships |
| Tests required | (1) No-write source-grep proof. (2) Product with complete fields = advisory_score=1.0. (3) Missing metal → flagged. (4) wfirma_product_id absent → advisory flags sync gap. |
| "Done" criteria | Operator can see product completeness advisory without any wFirma write occurring |

---

## Phase 6 — Document Intelligence

**Goal**: Advisory surface for document mismatch analysis — invoice vs packing-list
discrepancies, SAD/ZC429 authority gaps, customs description vs invoice position drift.
Extends existing `ai_customs_parser.py` + `ai_customs_evidence.py` into advisory UI.

| Item | Value |
|---|---|
| Class | R (explanation) + A (advisory on discrepancy) |
| Authority owner | `services/dhl_clearance_coordinator.py` + `services/invoice_packing_extractor.py` |
| New surface | New V2 page: `document-intelligence-v2.html` |
| New endpoint | `GET /api/v1/ai/advisory/document-analysis/{batch_id}` |
| AI task | Surface invoice/packing mismatches. Explain missing SAD sections. Explain ZC429 position authority gaps. Do NOT re-derive customs values. |
| Model | claude-haiku-4-5-20251001 |
| max_tokens | 1000 (T3) — document analysis needs more than advisory |
| Redaction | Customer/supplier names → [CUSTOMER]/[SUPPLIER]. AWB stays. VAT → [VAT_ID]. Raw PDF text MUST NOT be sent — extract structured fields first. |
| Forbidden | No SAD write. No ZC429 creation. No customs value change. Rule 9 applies in full. |
| Prerequisite | Phase 3 call-ledger live. ai_customs_parser + ai_customs_evidence already retrofitted. |
| Tests required | (1) Raw PDF text not in prompt (grep on prompt construction). (2) Mismatch advisory for known discrepant fixture. (3) No customs value mutation (no-write source-grep). |
| "Done" criteria | Operator sees document mismatch advisory with suggested next steps — no automatic correction |

---

## Phase 7 — Natural-Language Search

**Goal**: Operator can ask "show me all batches where DHL customs is waiting on SAD"
or "which customers have unvalidated EU VAT" in natural language. Read-only query
translation over timeline/audit data.

| Item | Value |
|---|---|
| Class | R (search result) |
| Authority owner | `services/inventory_batch_state.py` + timeline data |
| New surface | Search panel on dashboard-v2.html (dashboard-v2 is built last per Lesson F) |
| New endpoint | `POST /api/v1/ai/search` (read-only — POST because query is in body) |
| AI task | Translate natural-language query → structured filter parameters → run against existing read endpoints |
| Model | claude-haiku-4-5-20251001 |
| max_tokens | 200 (T4 — only produces filter params, not prose) |
| Redaction | Query text is operator-typed; no PII expected. Still redact any detected VAT/email patterns before sending. |
| Forbidden | POST body must NEVER trigger a write. Search result is read-only. No execute_action. |
| Unbounded result risk | Result set MUST be capped at 50 rows server-side before returning. |
| Dependency | dashboard-v2.html must be stable before Phase 7 ships (Lesson F). |
| Tests required | (1) Query translation produces only filter params (no action keys). (2) Result capped at 50. (3) No write SQL generated. (4) Cache: same query within 60s returns cached=True. |
| "Done" criteria | Operator can type a question and see a filtered batch list without any page reload or write action |

---

## Phase 8 — Action Proposal Advisor

**Goal**: AI proposes a structured action (Class-X). Operator approves via existing
`routes_action_proposals.py` approve/reject/queue lifecycle before anything executes.
AI never calls execute_action() directly.

| Item | Value |
|---|---|
| Class | X (operator-approved action) |
| Authority owner | `api/routes_execute.py` — unchanged gate |
| New AI contribution | `services/ai_action_proposer.py` — generates ActionProposal structs, never executes |
| Proposal lifecycle | AI → routes_action_proposals.py → operator approve → routes_execute.py |
| Supported proposal types | wfirma_create (PZ), dhl_send_reply, closure_confirm (existing action types) |
| Forbidden | AI must NEVER call execute_action() directly. NEVER bypass routes_action_proposals.py. NEVER generate proposals for action types not in routes_execute.py allowed list. |
| Idempotency | All proposals carry idempotency_key generated at proposal creation time |
| Prompt-injection | Action proposals are structured dicts — operator sees and edits before approve |
| Tests required | (1) ai_action_proposer.py contains no execute_action import (source-grep). (2) Proposal reaches approved state only via routes_action_proposals.py approve endpoint. (3) Rejected proposal cannot be re-proposed within 60s (dedup). (4) Proposal with unknown action_type is rejected at proposer level. |
| Deploy gate | security-permissions agent + backend-safety-reviewer both required |
| "Done" criteria | AI proposes "create PZ for batch X" → operator sees it in proposal queue → approves → PZ created via existing write gate — AI never touched write path directly |

---

## Phase 9 — Operations Assistant

**Goal**: Management-level read surface. Operator asks "summarize this week's PZ
activity" or "which batches are overdue on DHL customs". Produces natural-language
summaries from aggregated read data. Class-A (advisory, no writes).

| Item | Value |
|---|---|
| Class | A (advisory summary) |
| Authority owner | Read aggregates from batch_readiness, customer_master, timeline |
| New surface | New V2 page: `ops-assistant-v2.html` |
| New endpoint | `POST /api/v1/ai/ops-summary` |
| AI task | Aggregate read data → natural-language management summary. No individual PII in summary output. |
| Model | claude-haiku-4-5-20251001 |
| max_tokens | 1000 (T3) |
| Redaction | ALL customer names redacted before external API. Summary output uses "[N customers]" not names. |
| Unbounded context risk | Input to LLM is pre-aggregated counts/statuses — not raw batch list. Aggregate MUST be computed server-side first. |
| Forbidden | No write of any kind. No action proposals. No individual customer data in LLM prompt. |
| Tests required | (1) Aggregation happens server-side before LLM call (grep: no raw list passed to prompt). (2) No customer names in prompt (redaction test). (3) Result is a string summary, not an action. |
| "Done" criteria | Operator sees a plain-language week summary with zero PII and zero write path |

---

## Phase 10 — Controlled Optimization and Forecasting

**Goal**: Read-only pattern analysis. Examples: "batches with these SAD patterns
take 8 days longer" or "customer X has mismatched VAT 70% of the time". Produces
read-only analytical summaries — no automated decisions.

| Item | Value |
|---|---|
| Class | A (advisory analytics) |
| Authority owner | Timeline + audit history — read-only aggregation |
| New surface | Analytics panel within ops-assistant-v2.html |
| AI task | Pattern recognition over historical batch data. Advisory only. No prediction used to trigger an action. |
| Model | claude-haiku-4-5-20251001 (phase 10 may evaluate upgrading to Sonnet with operator cost approval) |
| Token budget | Per-analysis cap: 2000 tokens input, 1000 output (T3). Daily budget ceiling: $5.00 (phase 10 may exceed $1/day — requires operator .env override). |
| Forbidden | No automated decision. No action proposal generation. No feeding forecast back into readiness/gating. |
| Prerequisite | Phases 2–9 all CLOSED and live. Call-ledger data (Phase 3) provides historical call quality inputs. |
| Tests required | (1) Analytical output is read-only string (no action_type field). (2) No batch_readiness re-definition in output. (3) Token usage logged to call-ledger. |
| "Done" criteria | Operator can read a pattern summary and decide whether to act — no automated consequence |

---

## Token-Bleed Control Plan (all phases)

### High-risk files requiring grep-window protocol (Rule 4 mandatory)

| File | LOC | Risk |
|---|---|---|
| `shipment-detail.html` | 14,788 | CRITICAL — never Read() fully |
| `routes_dhl_clearance.py` | 3,221 | HIGH — grep only |
| `proforma_invoice_link_db.py` | 2,860 | HIGH |
| `wfirma_client.py` | 2,602 | HIGH |
| `active_shipment_monitor.py` | 2,464 | HIGH |
| `document_db.py` | 1,880 | MEDIUM |
| `master_data_db.py` | 1,541 | MEDIUM |

### Per-phase token allocation

| Phase | Context risk | Mitigation |
|---|---|---|
| 2 | LOW — batch_readiness dict is small | Pre-aggregate before LLM call |
| 3 | NONE — no new LLM calls | — |
| 4 | MEDIUM — customer record may have many fields | Extract relevant fields only; structured dict, not raw record |
| 5 | MEDIUM — product + invoice data | Extract finishing fields only |
| 6 | HIGH — customs documents are large | Rule 9: extract structured fields; NEVER send raw PDF text |
| 7 | LOW — query is operator text, short | Cap query at 200 chars server-side |
| 8 | LOW — proposals are structured dicts | Action type + batch_id only; no prose context |
| 9 | HIGH — aggregate may be large | Pre-aggregate server-side; pass counts not rows |
| 10 | HIGH — historical pattern data | Cap historical window at 90 days; pass aggregate stats not raw events |

### Mandatory stop conditions (all phases)

1. `ai_fallback_enabled=False` → deterministic path
2. `anthropic_api_key` absent → deterministic path
3. Daily spend ≥ `ai_advisory_budget_usd_per_day` → abort, log BUDGET_EXCEEDED
4. Cache hit within TTL → return cached, log CACHE_HIT
5. Estimated input > `ai_advisory_max_tokens_per_call` → abort, log TOKEN_LIMIT_EXCEEDED
6. Any prompt containing raw customer/VAT/email/phone text → abort, log REDACTION_FAILURE

---

## API Fallback Safety Boundaries

### What fallback may do
- Read from any read-only authority service
- Generate natural-language text for display
- Return structured advisory dicts

### What fallback may never do (§6 binding)
- Call wfirma_writer, wfirma_create, or wfirma_client write paths
- Call execute_action() directly
- Call DHL send paths
- Open a database connection in write mode
- Mutate audit.json, timeline.json, or any per-batch evidence file
- Issue HTTP to live DHL, wFirma, or carrier endpoints
- Re-derive CIF, duty, or freight allocation
- Redefine ready_for_closure

### Audit requirements (Rule 8 — all phases)
Every runtime LLM call MUST log to `ai_call_ledger.py`:
```
ts | prompt_hash | model | input_tokens | output_tokens | latency_ms | cost_usd | result_summary_hash | cached
```
No prompt text. No response text. Hashes only. Append-only file. Never uploaded.

### Fallback reasons (valid triggers for Phase 2+)
1. Timeout — deterministic explanation took >2s
2. Low-confidence deterministic result — batch has partial readiness data
3. Unsupported document type — customs doc outside SAD/ZC429 known types
4. Explicit operator escalation — operator clicks "Explain in detail" button
5. Incomplete deterministic result — batch_readiness returns missing domain data

---

## Sequencing and Gate Rules

- Phase N may not start until Phase N-1 is CLOSED and live on production.
- Each phase ships as its own PR. GATE 2 (max 3 open PRs) applies.
- Each phase requires a scorecard from `agent-performance-observer` per RULE 2.
- Phase 6 requires ai_customs_parser and ai_customs_evidence retroactively logging to call-ledger (Phase 3 retroactive closure requirement).
- Phase 8 is the highest-risk phase (Class-X). It requires security-permissions agent AND backend-safety-reviewer in the 7-agent deploy gate, not just the standard 7.
- No phase is allowed to add `max_tokens` values exceeding 4000 (T3 hard stop) without operator-approved config override.

---

## Residues and Governance Gaps (open before Phase 2 starts)

| Gap | Severity | Resolution target |
|---|---|---|
| `ai_customs_parser.py` and `ai_customs_evidence.py` NOT in capability map §3 | HIGH | Update capability map (this campaign) |
| Neither service writes to ai_call_ledger (Rule 8 violation) | MEDIUM | Phase 3 retroactive requirement |
| `redactor.py` exists but AI services may not use it | MEDIUM | Verify + wire before Phase 6 |
| No duplicate customer detection exists | LOW | Phase 4 scope |
| `proforma_intelligence.py` class unclassified | LOW | Classify before Phase 5 |

---

*No phase relaxes docs/ai-governance/ai-capability-map.md §6.*
*Token governance: docs/ai-governance/token-budget-policy.md — binding on every phase.*
*API fallback: docs/ai-governance/api-fallback-policy.md — binding on every phase.*
