# Scorecard — Atlas-V2 Sprint 01 — Proforma V2 Hardening

**Date**: 2026-05-28  
**Campaign**: Atlas-V2 | Sprint 01 — Proforma V2 Hardening  
**Branch**: `atlas-v2/sprint-01-proforma-hardening`  
**PR**: #383  
**Outcome**: COMPLETED — PR open, all gates passed  
**Agents scored**: 6 (4 direct + 2 substituted)  
**Trigger**: RULE 2 auto-fire — operator explicit request to score Sprint 01 campaign

## Campaign summary

**Task**: Close 7 identified gaps in `proforma-v2.html` and `pz-components.js` per sprint specification  
**Files changed**: `service/app/static/proforma-v2.html` (+40), `service/app/static/pz-components.js` (+54), `service/tests/test_proforma_v2_contract.py` (+111, 9 new tests)  
**Critical incidents**: Branch error (wrong target branch), test scope error (regex too broad), cherry-pick recovery executed  
**Test results**: 160/160 golden ✓, 53/53 proforma contracts ✓, 381/381 carrier ✓  
**Authority boundary**: Lesson F compliance confirmed — no V1 files touched, authority-clean implementation

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| gap-detection | 3 | 4 | 4 | 4 | 2 | 3 | 4 | 24 | ACCEPTABLE |
| frontend-ui | 4 | 5 | 4 | 4 | 5 | 4 | 4 | 30 | EXEMPLARY |
| testing-verification | 4 | 4 | 4 | 4 | 5 | 4 | 4 | 29 | EXEMPLARY |
| backend-safety-reviewer | 4 | 4 | 4 | 4 | 2 | 4 | 4 | 26 | ACCEPTABLE |
| browser-verifier | 3 | 3 | 4 | 3 | 2 | 3 | 3 | 21 | NEEDS-TUNING |
| git-workflow | 5 | 4 | 4 | 5 | 5 | 5 | 4 | 32 | EXEMPLARY |

## Weak-verdict warnings

**browser-verifier (NEEDS-TUNING):**
- Failed dimensions: Specificity (3), Coverage (3), Actionability (3), Substitution (2), Evidence (3), Environment (3)
- Evidence gap: Verdict block relied on "Chrome MCP + source-grep" but provided no specific console log evidence, no network tab inspection results, no DOM interaction verification beyond basic page mount
- Substitution failure: Used "Chrome MCP + source-grep" without disclosing this was a substitute for canonical browser-verifier agent and without confirming capability equivalence per GATE 5
- Coverage gap: Claimed "no console errors, 53/53 tests" but did not verify the 7 specific Sprint 01 gaps were functionally correct (readiness gate rendering, customer card save, product authority StatusDot, etc.)
- Recommendation: Re-dispatch browser-verifier with explicit functional verification scope — test each of the 7 gap closures interactively, not just source code presence

**gap-detection (ACCEPTABLE, but borderline):**
- Substitution failure: Used "inline analysis" instead of canonical gap-detection agent without proper GATE 5 disclosure
- Coverage adequate: All 7 gaps from sprint spec were identified and addressed
- Recommendation: Use canonical gap-detection agent or provide explicit substitution disclosure

**backend-safety-reviewer (ACCEPTABLE, but borderline):**
- Substitution failure: Used "inline check" instead of canonical agent without GATE 5 disclosure
- Coverage/Evidence adequate: Correctly verified pz-components.js has zero fetch calls, confirmed API boundaries respected

## Repeated failure hints

Reading 5 most recent prior scorecards (`2026-05-26-combined-deploy-pr376-pr377-lessonf.md`, `2026-05-26-pr375-deploy-atlas-v2-shell.md`, `2026-05-26-pr374-deploy-followup-status-v2.md`, `2026-05-19-campaign9-commercial-completion.md`, `2026-05-19-campaign8-production-deploy.md`):

No repeated failure patterns detected. This is the first scorecard for Atlas-V2 Sprint work, so no historical baseline for sprint-specific agents. Standard agents (frontend-ui, testing-verification, git-workflow) performing within expected ranges.

## Per-agent scoring rationale

### gap-detection (24/35 - ACCEPTABLE)
**Strengths**: All 7 sprint gaps identified and addressed correctly. Implementation followed sprint spec precisely.
**Weaknesses**: GATE 5 violation — used "inline analysis" substitution without disclosure of capability equivalence or registry mismatch explanation. Specificity adequate but could be stronger.
**Evidence**: Summary states "identified all 7 gaps from sprint spec" but lacks specific file:line citations.

### frontend-ui (30/35 - EXEMPLARY)
**Strengths**: Clean implementation of all 7 gaps. Layer purity maintained (no fetch calls in pz-components.js). Lesson F compliance confirmed.
**Evidence**: 40 lines added to proforma-v2.html, 54 lines to pz-components.js. Test baseline maintained (160/160, 53/53, 381/381).
**Environment**: File changes confirmed in git diff. Authority boundary respected.

### testing-verification (29/35 - EXEMPLARY)
**Strengths**: Added 9 new tests in `TestSprint01Hardening` class. Test scope error caught and fixed (regex narrowed from broad match to ProductAuthorityRow function body only).
**Evidence**: +111 lines in test_proforma_v2_contract.py. Self-correction when initial test was too broad.
**Coverage**: All new functionality covered by source-grep tests.

### backend-safety-reviewer (26/35 - ACCEPTABLE)
**Strengths**: Correctly verified API boundary compliance. Confirmed pz-components.js has zero fetch calls.
**Weaknesses**: GATE 5 violation — "inline check" substitution without disclosure.
**Evidence**: Explicit verification that "pz-components.js has zero fetch calls — all API calls flow through page-layer callbacks."

### browser-verifier (21/35 - NEEDS-TUNING)
**Critical gaps**: 
- **Specificity**: "page mounts, no console errors" is too generic. No specific console log outputs provided.
- **Coverage**: Did not functionally verify the 7 specific gaps were working (readiness gate state changes, customer card save button wiring, product StatusDot rendering).
- **Evidence**: No DevTools console screenshots, network tab inspection, or DOM interaction evidence.
- **Substitution**: Used Chrome MCP without GATE 5 disclosure of capability equivalence.
- **Environment**: No confirmation of which worktree/branch was actually tested.

### git-workflow (32/35 - EXEMPLARY)
**Strengths**: Excellent error recovery. Detected branch error (commit landed on wrong branch), executed clean cherry-pick to correct target, pushed successfully.
**Evidence**: Specific branch names provided (`fix/inbox-authority-hardening` → `atlas-v2/sprint-01-proforma-hardening`). PR #383 opened correctly.
**Actionability**: Clear description of branch fix process. Root cause identified ("git checkout appeared to succeed but active branch was different").

## Self-evaluation trigger check

**Most recent self-eval**: `self-eval-2026-05-26.md` (2 days ago)  
**Days since last self-eval**: 2  
**Campaigns since SELF-DEGRADATION flag**: N/A (last self-eval showed EXEMPLARY)  
**Self-evaluation**: Not triggered (run 1 of next 7-day cycle)