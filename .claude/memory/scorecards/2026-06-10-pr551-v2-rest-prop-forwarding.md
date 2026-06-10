# Campaign Scorecard — PR #551 fix(v2): forward rest props (data-testid, title, aria-*) from Btn/Card/Input to DOM

**Date**: 2026-06-10  
**SHA deployed**: 3b66ddf  
**Branch**: fix/v2-btn-testid-forwarding  
**Campaign type**: V2 shared primitives bug fix  

## Campaign summary

V2 shared primitives (Btn, Card, Input) were destructuring fixed prop lists and dropping data-testid/title/aria-* attributes, confirmed in production. Orchestrator classified per Lesson I as workflow class "shared V2 primitives swallowing rest props." Fixed all three primitives with dashboard-shared.js `...rest` pattern, added comprehensive source-grep test suite (11 tests). Real-browser verification via React 18 + Babel standalone harness confirmed 9/9 DOM checks pass.

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| reviewer-challenge | 3 | 4 | 3 | 4 | 5 | 3 | 3 | 25 | ACCEPTABLE |
| frontend-flow-reviewer | 5 | 5 | 4 | 5 | 5 | 5 | 5 | 34 | EXEMPLARY |

## Weak-verdict warnings

**reviewer-challenge (ACCEPTABLE):**
- Failed dimensions: Specificity (3), Evidence (3), Environment (3)
- Context gaps: Claimed "no browser verification" despite orchestrator having already run real-browser harness (stale info). Suggested TypeScript/PropTypes whitelisting off-stack (repo is vanilla Babel JSX). Did provide file:line evidence across 5 files and appropriate findings classification (LOW/MEDIUM), but missed context about orchestrator's actual verification scope.
- Evidence quality: Provided spread order analysis and failure scenario enumeration, but suggestions weren't fully aligned with project stack constraints.
- Recommendation: Acceptable performance with context awareness gap - continue dispatch with better context about completed verification steps.

## Repeated failure hints

**reviewer-challenge**: This agent has appeared in 3 recent scorecards. Checking pattern:
- 2026-06-09 proforma-toolbar-gate: EXEMPLARY (33/35)  
- 2026-06-08 pr507-reverification-proposal-gating: EXEMPLARY (32/35)  
- Current: ACCEPTABLE (25/35)  

No repeated-weak pattern detected — this is an isolated context-awareness gap, not systemic degradation.

## Self-evaluation status

Most recent self-eval: 2026-06-06 (4 calendar days ago)  
Self-evaluation due: No (trigger at 7+ calendar days)  
Campaign count since last self-eval: 5th campaign scorecard run  

Next self-eval trigger: 2026-06-13 or later