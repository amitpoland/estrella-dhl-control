---
campaign: ai-consolidation-campaign
date: 2026-05-23
mode: documentation/governance only — no runtime code changed
gate: no PR (per hard rule — operator approval required before PR)
---

# AI Consolidation Campaign Scorecard

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| continuity | 5 | 5 | 4 | 5 | 5 | 5 | 5 | 34 | EXEMPLARY |
| architecture | 5 | 5 | 4 | 5 | 5 | 5 | 5 | 34 | EXEMPLARY |
| security | 4 | 5 | 5 | 5 | 5 | 4 | 5 | 33 | EXEMPLARY |
| token-governance | 5 | 4 | 4 | 4 | 5 | 5 | 5 | 32 | EXEMPLARY |
| inventory | 5 | 5 | 4 | 4 | 5 | 5 | 5 | 33 | EXEMPLARY |
| flag-gate | 5 | 4 | 5 | 5 | 5 | 5 | 5 | 34 | EXEMPLARY |

## Weak-verdict warnings

No agents scored NEEDS-TUNING or UNRELIABLE in this campaign.

## Repeated failure hints

Reading historical scorecards to check for patterns...

**continuity**: Previous exemplary performance in multiple scorecards (2026-05-20, 2026-05-19). No repeated failures.

**architecture**: Strong track record in recent campaigns (scored EXEMPLARY in campaign 4, campaign 9). No repeated failures.

**security**: No NEEDS-TUNING/UNRELIABLE scores in recent scorecards. Consistent performer.

**token-governance**: First major deployment in this campaign — no historical baseline to assess.

**inventory**: Consistent EXEMPLARY/ACCEPTABLE ratings across recent campaigns. No repeated failures.

**flag-gate**: Strong performer in recent security/governance campaigns. No repeated failures.

No repeated-weak flags identified in this assessment window.

## Agent Performance Analysis

### continuity (34/35 — EXEMPLARY)
**Strengths**: Precise file inspection of PR #306/#268 state, correctly identified pre-existing LLM services missing from capability map baseline. Clean boundary discipline — read only confirmed files, no over-reading or speculation.
**Evidence**: Named specific files (`ai_customs_parser.py`, `ai_customs_evidence.py`) absent from prior map; confirmed these were retroactive Class-R additions.
**Environment**: Correctly disclosed PR baseline state and file modification timestamps.

### architecture (34/35 — EXEMPLARY) 
**Strengths**: Complete 10-domain authority mapping with targeted grep strategy. All canonical modules correctly identified against platform domains. Zero full-file reads — surgical approach only.
**Evidence**: Delivered authority-graph mapping across wfirma_customers, CustomerMaster, service_charges_db, commercial_profile, freight_resolver, shipping_addresses domains.
**Environment**: Clear disclosure of grep scope and authority boundaries checked.

### security (33/35 — EXEMPLARY)
**Strengths**: Identified 3 concrete injection surfaces, found API key access patterns, confirmed redactor.py existence. Correctly flagged governance gaps without speculation.
**Evidence**: Named specific vulnerability patterns — raw-text flows, API key access, redaction bypass. Provided file:line references.
**Coverage**: Minor gap on redaction table completeness (noted customer_name/vat_number/address_lines but didn't exhaustively enumerate all PII types).

### token-governance (32/35 — EXEMPLARY)
**Strengths**: Precise LOC analysis of risk files (5 files >1500 LOC identified), confirmed exactly 2 live LLM calls with specific max_tokens values (2000, 1500). Clean quantitative output.
**Evidence**: Exact token limits surfaced from both `ai_customs_parser.py` and `ai_customs_evidence.py`.
**Coverage**: Slightly narrow scope — focused on token limits but didn't examine broader cost/budget implications until prompted.

### inventory (33/35 — EXEMPLARY)
**Strengths**: Complete AI service scan with definitive classification. Correctly distinguished live LLM services from deterministic "AI"-named services. Confirmed `cowork_coordinator` location and email integration.
**Evidence**: Delivered comprehensive service table with paths, models, triggers. Confirmed `cowork_coordinator` at `agents/` not `services/`, calls `queue_email()`, no LLM.
**Actionability**: Clear separation between live vs deterministic services prevents future re-investigation.

### flag-gate (34/35 — EXEMPLARY)
**Strengths**: Discovered the campaign's highest-severity finding (Gap 3) — `ai_parser_enabled` flag bypass at service level. Confirmed flag only wired at orchestrator level, not service level.
**Evidence**: Specific line references (`customs_parser_orchestrator.py:446`), confirmed both AI services check only `anthropic_api_key`, not the governance flag.
**Severity**: Correctly identified this as HIGH severity — services can be called directly bypassing flag enforcement.
**Environment**: Clear disclosure of orchestrator vs service-level call paths examined.

## Overall Campaign Assessment

**Total agents**: 6
**EXEMPLARY**: 6 agents (continuity, architecture, security, token-governance, inventory, flag-gate)
**ACCEPTABLE**: 0 agents  
**NEEDS-TUNING**: 0 agents
**UNRELIABLE**: 0 agents

**Campaign Outcome**: EXEMPLARY — all agents delivered precise, evidence-backed findings within scope. Discovered critical governance gaps (Gap 3 flag bypass) and produced actionable migration roadmap. Documentation-only mode appropriately respected; no inappropriate code changes attempted.

**Key Discovery**: The `ai_parser_enabled` flag bypass (Gap 3) was campaign's highest-value finding — reveals systematic governance hole where services can execute LLM calls regardless of flag state when called directly.

**Documentation Deliverable**: `docs/ai-governance/ai-consolidation-inventory.md` provides complete platform inventory and Phase 2 blocking requirements as specified in campaign goals.