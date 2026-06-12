# Campaign Scorecard: PR #563 non-ASCII API Key Hotfix

**Date:** 2026-06-12  
**Campaign:** wFirma blocker diagnosis → non-ASCII API-key hotfix #563 → deploy  
**Branch:** fix/api-key-nonascii-encoding @ ff1f4b5  
**Agents evaluated:** 11 (5 pre-merge review + 6 deploy gate)  
**Campaign outcome:** SUCCESS — merged and deployed with workflow-class fix  

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| security-permissions | 5 | 4 | 5 | 5 | 5 | 4 | 5 | 33 | EXEMPLARY |
| backend-safety-reviewer (round 1) | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| reviewer-challenge (round 1) | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| backend-safety-reviewer (round 2) | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| reviewer-challenge (round 2) | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| deploy-git-diff-reviewer | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| deploy-backend-impact-reviewer | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| deploy-persistence-storage-reviewer | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| deploy-security-reviewer | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| deploy-qa-reviewer | 5 | 5 | 4 | 5 | 5 | 5 | 5 | 34 | EXEMPLARY |
| deploy-lead-coordinator | 4 | 4 | 4 | 4 | 5 | 2 | 5 | 28 | EXEMPLARY |

## Weak-verdict warnings

**No NEEDS-TUNING or UNRELIABLE verdicts in this campaign.**

**Deploy-lead-coordinator integrity concern:**
- Failed dimension: Evidence (2) — **REPEATED FABRICATION PATTERN**. Generated fabricated filenames in "authorized sync plan": auth/middleware.py, routes/routes_dashboard.py, core/utils.py. These files DO NOT exist in the diff or repository. Real diff contained 9 files: core/security.py, routes/routes_awb.py, routes/routes_dhl_clearance.py, routes/routes_pz.py, routes/routes_shipment.py, routes/routes_supplier.py, routes/routes_upload.py, routes/routes_wfirma.py, tests/test_security_api_key.py.
- Pattern significance: This is the **2nd occurrence** of fabrication by deploy-lead-coordinator. Previous instance in 2026-06-12 pr560 scorecard involved SHA fabrication (hallucinated full SHA from 7-character prefix).
- Impact: Orchestrator correctly disregarded fabricated plan and used verified file list. No operational impact but integrity breach.
- Recommendation: **GATE 4 disposition required** — file agent-tuning governance issue for deploy-lead-coordinator fabrication pattern.

## Repeated failure hints

**Deploy-lead-coordinator fabrication pattern:** 2nd occurrence in 2 consecutive campaigns (2026-06-12 pr560: SHA fabrication; 2026-06-12 pr563: filename fabrication). Pattern: generates factual-sounding but non-existent details beyond provided evidence.

**REPEATED-WEAK flag:** While deploy-lead-coordinator scored EXEMPLARY on total points, the Evidence dimension failure represents a systematic integrity issue requiring governance intervention.

## Pattern analysis

**Exceptional adversarial review performance:** Round 1 backend-safety-reviewer and reviewer-challenge independently detected the incomplete fix (2/10 sites vs 10/10 sites), preventing shipment of a partial solution. Both agents provided exact file:line references for the 7 additional vulnerable sites. This represents the highest-value catch in the campaign.

**Workflow-class thinking (Lesson I compliance):** Reviewer-challenge correctly identified this as a DoS vulnerability class affecting all compare_digest sites, not just the reported auth-500 symptom. Proper causation analysis distinguished between direct fix value (remove DoS) and uncertain wFirma symptom causation.

**Deploy gate excellence:** 6/6 deploy agents performed at EXEMPLARY level. Deploy-security-reviewer correctly verified constant-time preservation across all 10 sites. Deploy-qa-reviewer appropriately handled pre-existing test failures as diff-untouched (proper scoping).

**Campaign execution efficiency:** Two-round review cycle with expansion from 2 sites to 10 sites demonstrates effective adversarial review. Final deploy verification confirmed non-ASCII→401 (expected) vs previous non-ASCII→500 (DoS).

**Root cause accuracy:** Campaign correctly distinguished between proximate cause (non-ASCII API key TypeError) and the wFirma generation symptom, maintaining causation honesty while fixing the demonstrated vulnerability class.

## GATE 4 disposition verification

**Deploy-lead-coordinator integrity failure requires disposition per GATE 4:**
- **Finding:** Repeated fabrication pattern (Evidence dimension failure, 2nd occurrence)
- **DISPOSITION:** ISSUE — governance issue required for agent-tuning (fabrication prevention)
- **Status:** PENDING — orchestrator must file agent-tuning issue for deploy-lead-coordinator

## Self-evaluation status

Last self-evaluation: 2026-06-06 (6 calendar days ago)  
**Self-evaluation:** Not due — within 7-day window

## Campaign quality summary

**Campaign-level verdict:** EXCEPTIONAL — high-value adversarial review prevented incomplete fix shipment; proper workflow-class expansion per Lesson I; successful deploy with live verification. Only weakness: deploy-lead-coordinator fabrication pattern (2nd occurrence).

**Adversarial review effectiveness:** Round 1 backend-safety + reviewer-challenge catch of 7 additional vulnerable sites represents exemplary adversarial value. Prevented production deployment of partial security fix.

**System health indicator:** 10/11 agents performed at EXEMPLARY level. Deploy gate maintains 100% reliability. Agent ecosystem health excellent except for deploy-lead-coordinator integrity pattern requiring governance attention.