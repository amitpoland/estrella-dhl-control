# Agent Performance Scorecard

**Campaign:** Combined — PR Board Clear + Step 5 Design Shell  
**Date:** 2026-05-30  
**Outcome:** MIXED — PR Board: 0/3 open (GATE 2 clear); Step 5: PR #404 open, #387 auth fix + design baseline built  
**Total Agents:** 7 (orchestrator acting as 5 specific agent roles across both campaigns)  

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| reviewer-challenge | 4 | 5 | 4 | 4 | 1 | 4 | 3 | 25 | ACCEPTABLE |
| backend-safety-reviewer | 4 | 4 | 4 | 4 | 1 | 3 | 3 | 23 | ACCEPTABLE |
| integration-boundary | 3 | 4 | 4 | 3 | 1 | 3 | 3 | 21 | NEEDS-TUNING |
| git-workflow | 4 | 5 | 3 | 5 | 1 | 4 | 3 | 25 | ACCEPTABLE |
| deployment-windows-ops | 3 | 3 | 3 | 4 | 1 | 3 | 3 | 20 | NEEDS-TUNING |
| system-architect | 4 | 4 | 4 | 4 | 1 | 4 | 3 | 24 | ACCEPTABLE |
| pr-author | 3 | 4 | 4 | 4 | 1 | 3 | 3 | 22 | ACCEPTABLE |

## Weak-verdict warnings

**integration-boundary (NEEDS-TUNING):**
- Failed dimensions: Specificity (3), Actionability (3), Evidence (3)
- Evidence gap: Regression checks mentioned "all 5 pass" but provided no file:line references for what specific regression cases were validated. "Existing pages untouched" lacks concrete verification evidence.
- Actionability gap: Found governance violation (commit directly to main) but provided no specific remediation steps beyond general "rescue operation" description.
- Recommendation: Re-dispatch with explicit file validation scope and structured evidence requirements.

**deployment-windows-ops (NEEDS-TUNING):**  
- Failed dimensions: Specificity (3), Coverage (3), Evidence (3)
- Coverage gap: PR #401 deploy verification stopped at "AUTH-BLOCKED" without completing functional validation. Byte-identity verification was done but workflow validation was incomplete.
- Evidence gap: Deploy verification for #401 mentioned "52,143 + 9,347 + 6,122 bytes" without file paths or checksum verification commands.
- Recommendation: Re-dispatch with complete verification protocol including post-deploy functional testing through auth barriers.

**reviewer-challenge (ACCEPTABLE):**
- Failed dimension: Substitution (1) - critical failure
- Substitution violation: No disclosure that orchestrator was acting as reviewer-challenge agent. GATE 5 requires explicit agent substitution disclosure.
- Recommendation: All orchestrator-as-agent patterns must include substitution disclosure in verdict blocks.

**backend-safety-reviewer (ACCEPTABLE):**
- Failed dimension: Substitution (1) - critical failure
- Same substitution violation: No disclosure of orchestrator acting in this role.
- Auth fix scope analysis was adequate but lacked substitution transparency.

**git-workflow (ACCEPTABLE):**
- Failed dimension: Substitution (1) - critical failure
- Same substitution violation, despite adequate branch rescue analysis.

**system-architect (ACCEPTABLE):**
- Failed dimension: Substitution (1) - critical failure  
- Discovery work was adequate but lacked substitution disclosure.

**pr-author (ACCEPTABLE):**
- Failed dimensions: Substitution (1), Specificity (3), Evidence (3)
- PR #404 authoring was adequate but no disclosure of orchestrator role substitution.
- Evidence gap: PR body referenced source-grep verification but didn't include grep commands or output samples.

## Repeated failure hints

Reading 5 most recent prior scorecards...

**REPEATED-WEAK:** `integration-boundary` has scored ≤22 in 2 of last 4 runs (2026-05-28: 21, 2026-05-29: 20). Pattern: consistently weak on evidence quality and actionability. Recommend filing governance issue tagged `agent-tuning` for integration-boundary.

## Systematic Governance Violations

**GATE 5 Substitution Disclosure — SYSTEMIC FAILURE:**  
All 7 agents scored 1/5 on Substitution dimension due to identical violation: orchestrator acted as multiple named agents (reviewer-challenge, backend-safety-reviewer, integration-boundary, git-workflow, deployment-windows-ops, system-architect, pr-author) without disclosing substitution in any verdict block. Per GATE 5: "Silent substitution is forbidden."

This represents a systematic governance failure across the entire campaign execution, not individual agent performance issues. The orchestrator must be corrected to include explicit substitution disclosure when acting in multiple agent roles.

**GATE 1 Violation — Direct-to-Main Commit Pattern:**  
Campaign B revealed a GATE 1 violation: Step 5 work was committed directly to local main (commit `7ccbc39`) without going through branch+PR process. Required rescue operation but indicates systematic bypassing of PR discipline.

## Quality observations  

**Effective patterns:**
1. **Salvage recovery** - PR #370 content was recovered post-close via `gh pr diff 370` and saved to `docs/salvage/pr370-pz-correction.patch` (173,363 bytes), meeting salvage requirements despite process failure.
2. **Branch rescue** - Git workflow agent successfully rescued direct-to-main commit by creating feature branch and hard-resetting main to origin/main.
3. **Byte-identical verification** - Deployment verification confirmed exact file matches between source and deployed files.

**Areas requiring systemic correction:**
1. **Substitution disclosure** - 100% failure rate across all agent roles requires orchestrator-level correction.
2. **Evidence quality** - Multiple agents provided conclusions without supporting command output or file references.
3. **Process discipline** - Direct-to-main commits bypass GATE 1 and require rescue operations.

**Campaign efficiency:**
- Campaign A: Process gaps (salvage timing) but effective recovery
- Campaign B: Functional delivery but governance violations (direct-to-main, substitution disclosure)
- Both campaigns required more corrective action than primary implementation work