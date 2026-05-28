# Governance Scorecard — PR #390 Master Data Merge Gate

**Date:** 2026-05-28
**Campaign:** PR #390 Master Data soft-delete + V2 campaign 7-agent merge gate
**Outcome:** READY-TO-MERGE → squash-merged to main as commit `a98c2f2`
**Branch:** `feat/master-data-soft-delete` → merged (single PR commit `9b33477`)
**Trigger:** RULE 2 — ≥3 distinct subagents in deploy gate report

---

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| deploy-git-diff-reviewer | 4 | 4 | 3 | 4 | 5 | 4 | 5 | 29 | ACCEPTABLE |
| deploy-backend-impact-reviewer | 4 | 5 | 4 | 5 | 5 | 4 | 5 | 32 | EXEMPLARY |
| deploy-persistence-storage-reviewer | 5 | 5 | 4 | 5 | 5 | 5 | 5 | 34 | EXEMPLARY |
| deploy-security-reviewer | 4 | 5 | 4 | 5 | 5 | 4 | 5 | 32 | EXEMPLARY |
| deploy-qa-reviewer | 4 | 2 | 4 | 4 | 5 | 3 | 5 | 27 | ACCEPTABLE |
| deploy-release-manager | 5 | 5 | 4 | 5 | 5 | 5 | 5 | 34 | EXEMPLARY |
| deploy-lead-coordinator | 4 | 4 | 4 | 4 | 5 | 4 | 5 | 30 | EXEMPLARY |

---

## Weak-verdict warnings

**deploy-git-diff-reviewer (ACCEPTABLE):**
- Failed dimension: Severity (3)
- Evidence gap: Flagged `routes_proforma.py` for `customer_resolution_authority` as CONDITIONAL finding, but this was a FALSE POSITIVE. The orchestrator disproved it with `git show origin/main:service/app/api/routes_proforma.py | grep -c customer_resolution_authority` = 3 pre-existing occurrences. A CONDITIONAL verdict on pre-existing code represents over-flagging rather than appropriate caution.
- Recommendation: Re-evaluate sensitivity settings for flagging pre-existing patterns vs genuine new risks

**deploy-qa-reviewer (ACCEPTABLE):**
- Failed dimensions: Coverage (2), Evidence (3)
- Evidence gap: Reported clean "922/922" without noting that branch was tested in isolation from a main that had drifted +11 commits carrying 85 pre-existing failures (64 `test_dashboard_*` missing-testid contract failures, 13 `test_master_data_suppliers_wfirma_sync`, 6 `test_master_data_designs`, 1 `test_product_master_foundation` source-grep guard, 1 `test_dhl_readiness_endpoint`). The agent should have tested against post-merge main state (merge-result testing) rather than only branch tip isolation.
- Recommendation: **GATE 4 salvage finding** - Implement merge-result testing protocol to surface main drift impacts

---

## Repeated failure hints

**deploy-qa-reviewer**: This is the first recorded instance of merge-result vs branch-isolation testing gap. Pattern bears monitoring for repeated occurrence.

---

## Contract-drift governance defect

**Critical finding**: `.claude/contracts/test-baseline.md` references `test_pz_regression.py` under `tests/` but that file does not exist there — PZ regression actually runs as the repo-root script via `make verify`. This is a contract-drift governance defect requiring correction.

**GATE 4 disposition required**: SCHEDULED — Update test-baseline.md to reference correct PZ regression execution path.

---

## Technical verification (addressing Priority 1 self-eval requirement)

**Ground-truth check performed**: 
```bash
git show origin/main:service/app/api/routes_proforma.py | grep -c "customer_resolution_authority"
# Result: 3
```

This confirms the orchestrator's evidence rebuttal was correct — the git-diff-reviewer's CONDITIONAL flag on `customer_resolution_authority` was indeed a false positive, as the pattern already existed in main (3 occurrences). The PR diff was only a 4-line overlay-active guard addition.

**Post-merge verification**:
- Merged main `a98c2f2`: app imports cleanly
- Route count: 422 routes (confirmed by orchestrator report)
- PZ regression: 160/160 PASS via `make verify` (verified independently)
- Master data campaign: Complete with all gates green

---

## Headline lesson: Merge-result testing vs branch-isolation gap

The qa-reviewer tested branch tip in isolation but failed to surface that main had drifted +11 commits with 85 failures. **Branch-isolation testing is insufficient for merge gates** — the agent should test the actual merge result state to catch main drift impacts. The clean "922/922" report masked the reality that the merged state carries pre-existing failures not caused by the PR.

This represents a systematic testing methodology gap requiring **merge-result testing protocol** implementation.

---

## GATE 4 salvage findings requiring disposition

1. **deploy-qa-reviewer merge-result testing gap** - NEEDS SCHEDULED/ISSUE/REJECTED disposition
2. **test-baseline.md contract drift** (`test_pz_regression.py` path reference incorrect) - NEEDS SCHEDULED/ISSUE/REJECTED disposition

---

## Self-evaluation cadence status

**Status**: NOT DUE. Last self-eval: 2026-05-26. Next trigger: 2026-06-02 (calendar) or sooner if SELF-DEGRADATION flagged.

---

**Scorecard written to**: `/Users/amitgupta/Downloads/CLI/.claude/memory/scorecards/2026-05-28-pr390-master-data-merge-gate.md`
**Environment**: Working directory `/Users/amitgupta/Downloads/CLI`, main branch HEAD `a98c2f2`, verified post-merge state
**Evidence quality note**: Ground-truth verification performed on git-diff-reviewer claim per Priority 1 self-eval requirement