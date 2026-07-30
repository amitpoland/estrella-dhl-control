# Campaign Scorecard: Proforma Privileged-Auth Migration

**Date:** 2026-07-17
**Campaign slug:** proforma-privileged-auth
**PR:** #934
**Branch:** claude/affectionate-payne-e58c7d (worktree: C:\PZ-verify\.claude\worktrees\affectionate-payne-e58c7d)
**Base commit:** d5a453fd
**Work commits:** 935df3f0, de0f64bb
**Task:** Migrate state-mutation routes in service/app/api/routes_proforma.py from require_api_key to require_api_key_privileged (H-R5/#502 class) + regression suite
**Observer trigger:** RULE 2 auto-fire — 3 distinct named-agent invocations (backend-safety-reviewer, security-write-action-reviewer, reviewer-challenge)

---

## 1. Per-agent scorecard table

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| backend-safety-reviewer | 5 | 5 | 3 | 5 | 5 | 4 | 3 | 30 | EXEMPLARY |
| security-write-action-reviewer | 4 | 4 | 4 | 4 | 5 | 4 | 3 | 28 | EXEMPLARY |
| reviewer-challenge | 5 | 5 | 5 | 5 | 5 | 5 | 3 | 33 | EXEMPLARY |
| orchestrator | 5 | 5 | 5 | 5 | 5 | 5 | 4 | 34 | EXEMPLARY |

---

## Dimension rationale per agent

### backend-safety-reviewer — 30 — EXEMPLARY

**Specificity (5):** Caught two concrete, named findings with precise file:line references: F-1 identifying POST /preview wrongly swept into the _auth_write migration, and F-2 identifying a structural gap in the test that would miss a future auth-absent route. Performed an exhaustive 66-route inventory. Confirmed F-1 against existing no-write contract tests. Checked Lesson N and Lesson A compliance. Maximum specificity for a route security review dispatch.

**Coverage (5):** Full 66-route inventory verified. Lesson N and Lesson A checks performed in addition to primary route classification task. F-1 confirmed against existing contract tests — going beyond the finding to validate it against a pre-existing evidence artifact. Complete for the stated scope.

**Severity (3):** F-2 at LOW is appropriately calibrated. F-1 at MEDIUM is the calibration gap: reviewer-challenge subsequently proved CRITICAL severity for F-1 by citing three independent page-load call sites (proforma-detail.jsx:3621, proforma-detail-v2.html:855, shipment-detail.html:14514) and confirming the viewer role default at routes_auth.py:74. The backend-safety-reviewer surfaced the right finding but under-calibrated its blast radius. MEDIUM vs CRITICAL is a meaningful deflation on the most significant finding in the campaign, even though the agent was correct about the existence of the problem.

**Actionability (5):** Both findings adopted. F-1 led to /preview reverting to _auth with an inline explanatory comment; F-2 led to _READ_ONLY_POST_ALLOWLIST, a fail-closed every-route-has-auth pin, and floor 40 in the test. Maximum actionability — findings translated directly to commit de0f64bb.

**Substitution (5):** Canonical registered agent. GATE 5 N/A.

**Evidence (4):** Precise file:line references cited per the campaign summary. 66-route inventory enumerated. F-1 confirmed against existing contract tests, providing a second independent evidence layer. Minor deduction: scoring is mediated through campaign narrative rather than raw verdict block quotation, and the specific line numbers are not reproduced here for independent verification.

**Environment (3):** No explicit worktree path, branch, or commit SHA self-disclosed in the verdict block per the campaign summary. The findings' accuracy confirms the agent read from the correct tree, but the disclosure itself was absent. Standard 3/5 per established scoring convention.

---

### security-write-action-reviewer — 28 — EXEMPLARY

**Specificity (4):** Named the fail-closed guard, WFIRMA_CREATE_* defense-in-depth, secrets check, and decorator-only diff as the verification surfaces. Pre-existing LOWs identified with mechanism specificity: local _auth variable shadow at line ~7106 (note: approximate reference, not exact line), JWT double-decode for audit identity. Informational count-floor limitation named and cross-referenced as identical to F-2. Solid specificity with one fuzzy reference (~7106 vs exact line number).

**Coverage (4):** Verified the primary security concerns within its scope: fail-closed guard behavior, defense-in-depth layer (WFIRMA_CREATE_*), secrets surface, structural nature of the diff (decorator-only). Flagged two pre-existing LOWs and one informational item. Minor gap: the full scope checklist from the agent definition includes idempotency, confirmation-if-destructive, and audit/execution log; the campaign summary does not confirm whether these were explicitly checked or whether they were implicitly cleared by the decorator-only diff characterization.

**Severity (4):** CLEAR verdict is correctly calibrated: no new vulnerabilities introduced, decorator-only diff confirmed, defense-in-depth intact. Pre-existing LOWs correctly labeled LOW (not MEDIUM or HIGH) — these are structural observations, not new risks. Informational count-floor correctly classified as informational. No inflation or deflation; the CLEAR verdict appropriately reflects the migration's narrow, decorator-only scope.

**Actionability (4):** CLEAR is the directly actionable verdict — no blocker on the migration. The two pre-existing LOWs are surfaced for operator awareness without demanding immediate pre-merge resolution, which is correct for pre-existing conditions. The informational item correctly requires no action. The agent could have provided an explicit "confirm these pre-existing items exist in the backlog" note to maximize actionability, but the absence is not a failure.

**Substitution (5):** Canonical registered agent. GATE 5 N/A.

**Evidence (4):** Named the fail-closed guard, WFIRMA_CREATE_* layer, specific variable shadow, JWT pattern, and count-floor gap. "Accurate, no false positives" is confirmed by the subsequent resolution (no security-write-action-reviewer finding was contested or retracted). Minor deduction: ~7106 is approximate rather than exact, which reduces evidence precision on that specific finding.

**Environment (3):** No explicit worktree path, branch, or commit SHA self-disclosed per the campaign summary. Standard disclosure gap; findings confirmed accurate by subsequent action. 3/5 per established convention.

---

### reviewer-challenge — 33 — EXEMPLARY

**Specificity (5):** Every finding grounded in named file:line citations: F-1 escalation with proforma-detail.jsx:3621, proforma-detail-v2.html:855, shipment-detail.html:14514 (three independent call sites proving page-load calls); viewer role default at routes_auth.py:74; scope-illusion identifying 8 fiscal mutation routes in routes_wfirma.py still on bare _auth. Five findings, each with independently verifiable evidence. Maximum specificity.

**Coverage (5):** Five distinct findings covering the full risk surface: auth scope correctness (escalating F-1), production-impact proof (page-load calls), broader scope gap (routes_wfirma.py), test policy gap (allowlist requirement), Lesson M governance compliance (DECISIONS record). The agent found risks that the other two agents missed, demonstrating coverage of the implementation risk space beyond the immediate migration scope. REVISE verdict demanded partial framing and GATE-4 disposition — both adopted.

**Severity (5):** CRITICAL for F-1 escalation: correctly elevated from backend-safety-reviewer's MEDIUM using three independent page-load call sites plus viewer-role-default evidence. HIGH for scope-illusion: 8 fiscal mutation routes on bare _auth is a real systemic security gap. HIGH for test-encodes-wrong-policy: an allowlist-based test is structurally different from a passing test that encodes the wrong policy. MEDIUM for Lesson M governance gap. LOW for integration coverage. Five findings with calibrated severity differentiation across four distinct levels — no flattening, no inflation.

**Actionability (5):** All five findings adopted in commit de0f64bb: /preview reverted to _auth with comment; _READ_ONLY_POST_ALLOWLIST plus fail-closed every-route-has-auth pin plus floor 40; integration tests for /draft/{id}/post and preview-readable paths; Lesson M DECISIONS entry appended to PROJECT_STATE.md; GATE-4 SCHEDULED chip task_65841510 filed with full per-file inventory for routes_wfirma.py; PR body framed PARTIAL with explicit scope disclosure. Maximum actionability: 5/5 findings resolved with concrete artifacts.

**Substitution (5):** Canonical registered agent. GATE 5 N/A.

**Evidence (5):** Three independent file:line call-site citations for the CRITICAL F-1 escalation — not one corroborating reference but three, spanning two JSX files and one HTML file. routes_auth.py:74 for viewer role default. routes_wfirma.py for the 8-route scope gap. All five findings were adopted in de0f64bb, providing post-hoc confirmation that the cited evidence was correct and verifiable. The adoption of all findings under strict GATE 1 conditions is the strongest possible evidence quality signal.

**Environment (3):** No explicit worktree path, branch, or commit SHA self-disclosed per the campaign summary. The file:line citations are all confirmed accurate by subsequent implementation, confirming the agent read from the correct tree. Standard disclosure gap; no impact on correctness. 3/5 per established convention.

---

### orchestrator — 34 — EXEMPLARY

**Specificity (5):** Named all resolutions explicitly: /preview reverted to _auth with explanatory comment; _READ_ONLY_POST_ALLOWLIST; fail-closed every-route-has-auth pin; floor 40; /draft/{id}/post and preview-readable integration tests added. Commits named (935df3f0, de0f64bb). GATE-4 chip task_65841510 filed with full per-file inventory for routes_wfirma.py. PR #934 framed PARTIAL with scope disclosure. Verification methodology named (stash + re-run). All test counts named: 79/79 identical on base, 0 new failures, golden 160/160, smoke 63 passed twice.

**Coverage (5):** All CRITICAL/HIGH findings resolved inline. Lesson M DECISIONS entry appended. GATE-4 SCHEDULED for the routes_wfirma.py scope gap. PR body correctly framed as partial with explicit scope disclosure. Pre-existing-failure proof completed via stash + re-run methodology (not assumed, explicitly verified). Three distinct test suites validated. No finding left without a disposition.

**Severity (5):** Accepted reviewer-challenge's CRITICAL escalation on F-1 and acted on it immediately (reverted /preview). Accepted HIGH scope-illusion finding without deflating it — correctly scheduled as GATE-4 rather than treating it as out-of-scope noise. Treated security-write-action-reviewer's pre-existing LOWs as non-blocking, which is the correct treatment for pre-existing conditions in a decorator-only migration. Each finding received treatment matched to its severity.

**Actionability (5):** Every finding resolved with a specific artifact. The stash+re-run baseline proof is evidence-grade verification, not self-assertion. No "noted" non-dispositions. The GATE-4 SCHEDULED chip for routes_wfirma.py ensures the scope gap does not become governance debt.

**Substitution (5):** Main session orchestrator. GATE 5 N/A.

**Evidence (5):** Stash+re-run baseline proof (79/79 identical on base, 0 new failures introduced). Golden 160/160. Smoke 63 passed twice. Specific commit SHAs named. GATE-4 chip task_65841510 with per-file inventory filed. The pre-existing-failure stash+re-run methodology provides independently reproducible evidence rather than self-asserted test results — this is the correct standard for pre-existing-failure verification.

**Environment (4):** Worktree path explicitly named (C:\PZ-verify\.claude\worktrees\affectionate-payne-e58c7d). Branch named (claude/affectionate-payne-e58c7d). Base commit named (d5a453fd). Work commits named (935df3f0, de0f64bb). Verification evidence confirmed as "available on disk" at the worktree path. Minor gap: HEAD SHA at time of each test run is not separately stated (the commit names serve the same purpose), and the pre-existing-failure stash base is not identified by SHA. Strong disclosure — 4/5.

---

## 2. Weak-verdict warnings

No agents scored NEEDS-TUNING or UNRELIABLE. All four scored entities produced EXEMPLARY verdicts (28-34 range). No weak-verdict warnings required.

**Note on backend-safety-reviewer Severity calibration:** The Severity dimension scored 3/5 (acceptable) rather than 4-5 because F-1 was labeled MEDIUM when reviewer-challenge demonstrated CRITICAL severity. This is a notable calibration gap but not a NEEDS-TUNING trigger — the agent scored 30 total (EXEMPLARY threshold is 28), found the right finding, and provided correct severity on F-2. The gap is documented here for trend awareness: if Severity calibration appears below 4 again in the next backend-safety-reviewer appearance, that dimension warrants a targeted note in the REPEATED-WEAK section.

---

## 3. Repeated failure hints

**5 most recent prior campaign scorecards reviewed (excluding self-eval files):**
1. 2026-07-03: `2026-07-03-phase-c-wave2-backend.md` — 3 entities (2 Explore + orchestrator); all EXEMPLARY (30, 33, 34)
2. 2026-06-22: `2026-06-22-pr720-merge-validation.md` — orchestrator only; EXEMPLARY (35)
3. 2026-06-22: `2026-06-22-pr720-deploy-gate.md` — 8 entities; 7 EXEMPLARY, 1 ACCEPTABLE (deploy-persistence-storage-reviewer 26)
4. 2026-06-22: `2026-06-22-awb9158478722-product-adoption-batch.md` — 5 agents; 3 EXEMPLARY, 2 ACCEPTABLE (backend-safety-reviewer 27 Evidence 3/5; frontend-flow-reviewer 27 Evidence 3/5)
5. 2026-06-22: `2026-06-22-awb9158478722-import-pz-sales-authority.md` — 4 agents; 2 EXEMPLARY, 2 ACCEPTABLE (frontend-flow-reviewer 27 Evidence 3/5; backend-safety-reviewer 28)

**Active REPEATED-WEAK flags carried from prior scorecards:**

`REPEATED-WEAK: agent frontend-flow-reviewer has scored ACCEPTABLE (Evidence 3/5) in 5 or more consecutive campaign appearances.`
- GATE 4 ISSUE disposition generated in 2026-06-21-freight-authority-blocker-repair.md. GitHub issue tagged `agent-tuning` has been pending operator confirmation across multiple scorecard cycles. frontend-flow-reviewer does not appear in this campaign (backend-only, no UI surface). Flag carries forward unchanged.
- **Action required:** Operator must confirm whether the `agent-tuning` GitHub issue for frontend-flow-reviewer has been filed. This GATE 4 obligation has been outstanding across 5+ scorecards without confirmation.

`REPEATED-WEAK: agent backend-safety-reviewer has scored Evidence 3/5 in 3 of last 4 campaign appearances (flag reinstated 2026-06-22-awb9158478722-product-adoption-batch.md; Issue #694 open).`
- **New data point in this campaign (2026-07-17):** backend-safety-reviewer appears and scores EXEMPLARY (30). Evidence score improved to 4/5 (no longer the 3/5 pattern). This is a positive rehabilitation data point. However, the agent shows a new gap: Severity calibration at 3/5 (MEDIUM vs CRITICAL on F-1). The Evidence-3/5 pattern appears broken, but the new Severity gap requires one additional clean run before Issue #694 is closed. Issue #694 remains open; update its description to note the evidence improvement and the new severity calibration observation.

---

## 4. GATE 4 disposition

No NEEDS-TUNING or UNRELIABLE verdicts produced by this scorecard. No new GATE 4 salvage dispositions required from this campaign's scored entities.

**Existing GATE 4 open items (carried):**
- frontend-flow-reviewer REPEATED-WEAK — ISSUE (agent-tuning tag; operator confirmation of filing overdue)
- backend-safety-reviewer REPEATED-WEAK — ISSUE #694 (open; positive data point this run — update description but do not close until one more clean severity calibration)

---

## 5. Self-evaluation (RULE 5 — calendar trigger)

**Trigger assessment:**
- Most recent self-eval file: `self-eval-2026-07-03.md` (2026-07-03)
- Today: 2026-07-17
- Calendar days elapsed: 14 days — exceeds 7-day threshold
- SELF-DEGRADATION flag in self-eval-2026-07-03.md: NO (cleared — all dimensions stable or improved)
- Counter trigger: not applicable (no active SELF-DEGRADATION flag)
- **Calendar trigger fires. Self-evaluation is executed.**

**Note:** Operator instruction for this task specifies exactly one output file. Self-evaluation is therefore conducted inline in this scorecard rather than as a separate `self-eval-<date>.md` file.

**5 campaigns evaluated (most recent first, excluding self-eval files):**
1. 2026-07-17: `2026-07-17-proforma-privileged-auth.md` (this run)
2. 2026-07-03: `2026-07-03-phase-c-wave2-backend.md`
3. 2026-06-22: `2026-06-22-pr720-merge-validation.md`
4. 2026-06-22: `2026-06-22-pr720-deploy-gate.md`
5. 2026-06-22: `2026-06-22-awb9158478722-product-adoption-batch.md`

### Self-scoring on 7 dimensions

**Specificity (4/5):** All 5 campaigns use the 7-dimension numeric table with written per-dimension rationale per agent. Named artifacts appear consistently: commit SHAs, test counts, file:line references from campaign narratives, mechanism descriptions. Persistent minor gap: raw verdict block text from subagents is not directly quoted in any scorecard — rationale is derived from the campaign narrative's characterization of agent outputs. This single mediation layer is consistent across all 5 runs and does not represent new degradation; it remains the structural reason Specificity stays at 4/5 rather than 5/5.

**Coverage (5/5):** All activated agents scored in all 5 campaigns. This campaign adds orchestrator as a fourth scored entity per explicit instruction — correct inclusion; no omission. The 2026-07-03 scorecard correctly identifies the 2 Explore subagents plus orchestrator as the three scorable entities. The 2026-06-22 scorecards cover all 5, 8, 4, and 1 entities respectively (matched to their campaign reports). Complete.

**Severity calibration (4/5):** The EXEMPLARY/ACCEPTABLE spectrum is correctly differentiated across the window. The current campaign correctly scores backend-safety-reviewer's Severity at 3/5 (MEDIUM vs CRITICAL gap) without inflating to 4/5 — this is the critical calibration judgment in this run. The 2026-07-03 campaign correctly scores all 3 entities EXEMPLARY for a clean backend migration with no subagent gaps. The 2026-06-22 campaigns correctly differentiate deploy-persistence-storage-reviewer at ACCEPTABLE (26) vs other deploy agents at EXEMPLARY (34-35). No NEEDS-TUNING or UNRELIABLE verdict across the 5-campaign window — plausible for this task class but vigilance warranted. Score held at 4/5 for calibration vigilance.

**Actionability (4/5):** GATE 4 dispositions generated and named in all campaigns. REPEATED-WEAK flags maintained with named ISSUE dispositions. The frontend-flow-reviewer GATE 4 ISSUE filing confirmation has been outstanding across 5+ scorecards; each scorecard escalates it correctly but without operator-side confirmation. This is an operator-execution gap, not a scorecard-methodology failure. Score held at 4/5: dispositions are correctly generated; escalation persistence is bounded by lack of operator response signal.

**Substitution honesty (5/5):** All agents canonical in all 5 campaigns in this window. No GATE 5 events. No silent substitution detected.

**Evidence quality (4/5):** All scorecards ground scoring in named verifiable artifacts (commits, test counts, file:line from campaign summaries, named functions and guards). The reviewer-challenge "all 5 findings adopted in commit de0f64bb" signal in this campaign is independently verifiable — adoption under GATE 1 conditions is stronger than self-reported accuracy. The 2026-07-03 "citations verified during implementation" signal is similarly strong. Persistent gap: mediation through campaign narrative rather than raw verdict block quotation limits Specificity and Evidence quality simultaneously. Score 4/5 consistent with prior self-eval.

**Format consistency (4/5):** All 5 campaigns in this evaluation window use the correct 7-dimension numeric table. This is an improvement from 3/5 in the 2026-07-03 self-eval (where 5/5 of the standard-format scorecards in that window were compliant, but the pr719 corpus outlier kept the score at 3/5). The pr719 outlier (GATE 5 substitution with custom SOLID/EXEMPLARY schema) is now 9+ weeks distant and outside the current evaluation window. Scoring 4/5 rather than 5/5 because the pr719 corpus outlier still exists in the scorecard directory and the "GATE 5 substitution should use 7-dimension table" recommendation remains unimplemented as policy.

### Self-assessment summary

**Total: 4+5+4+4+5+4+4 = 30/35 — EXEMPLARY**

**Comparison with self-eval-2026-07-03.md (29/35 ACCEPTABLE):**

| Dimension | 2026-07-03 self-eval | 2026-07-17 self-eval | Change |
|---|---|---|---|
| Specificity | 4/5 | 4/5 | = (stable) |
| Coverage | 5/5 | 5/5 | = (stable) |
| Severity calibration | 4/5 | 4/5 | = (stable) |
| Actionability | 4/5 | 4/5 | = (stable) |
| Substitution honesty | 5/5 | 5/5 | = (stable) |
| Evidence quality | 4/5 | 4/5 | = (stable) |
| Format consistency | 3/5 | 4/5 | +1 (improvement) |

All dimensions stable or improved. Format consistency improved from 3/5 to 4/5 as the pr719 outlier exits the 5-campaign evaluation window and the current window achieves 5/5 compliance.

**NO SELF-DEGRADATION DETECTED.** Score improved from ACCEPTABLE (29/35) to EXEMPLARY (30/35).

**Persistent structural gaps (not new degradation — carried from prior self-evals):**
1. Raw verdict block quotation absent across all scorecards — Specificity and Evidence quality both capped at 4/5 by the mediation layer. Fix target: operator could request that campaign summaries include verbatim verdict block excerpts.
2. Issue #597 (agent self-disclosure of worktree/branch/SHA): Environment dimension of scored agents persistently at 3/5 across almost all appearances. The observer scores this correctly; the fix target is agent prompt templates, not scorecard methodology.
3. frontend-flow-reviewer GATE 4 ISSUE filing confirmation: overdue across 5+ scorecards. Observer escalates correctly each run but cannot confirm operator action.

**Operator actions recommended:**
1. Confirm GitHub issue tagged `agent-tuning` for `frontend-flow-reviewer` has been filed (GATE 4 obligation, overdue).
2. Update Issue #694 for `backend-safety-reviewer` to reflect the positive evidence data point in this campaign and the new Severity calibration observation. Do not close until one additional clean Severity calibration run.
3. Consider adding to agent prompt templates: "Begin your verdict block with: Worktree: <path> | Branch: <name> | HEAD: <SHA>." This closes Issue #597 systematically and would move Environment scores from 3/5 to 4-5/5 across the agent fleet.
4. Establish policy: all scorecards — including GATE 5 substitution-authored ones — must use the 7-dimension numeric table. This would allow pr719 corpus outlier to be the last non-compliant entry.
