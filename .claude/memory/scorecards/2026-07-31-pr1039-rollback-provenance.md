# Campaign Scorecard: Rollback Provenance (PR #1039)

**Date:** 2026-07-31
**Campaign slug:** rollback-provenance
**PR:** #1039 (branch `fix/rollback-provenance`)
**Worktree:** `C:\PZ-wt\rollback-provenance`
**Merge commit:** `1ce0e76d4b31c6cdd9b309c03517e92be719ed89` (merge commit, parents `92222849` + reviewed head `719c28fa`; ancestry preserved, not squashed)
**Deployed:** 2026-07-31T00:33:47+02:00
**Scope:** Five files, 715 insertions / 7 deletions. Zero application code. Deployment tooling only.
**Task:** Fix the two-identity defect in `Invoke-Rollback` (`Deploy-PZ.ps1`): a single `sha` field served as both the authorization target and the restored-content identity, so a rollback restored OLD bytes while stamping the NEWER deployment SHA into `version.txt`.
**Outcome:** CLOSED — merged as true merge commit, deployed with provenance-aware `Deploy-PZ.ps1`, 10/10 closure validation PASS (`Test-PZDeployClose.ps1`), first provenance-aware backup unit (`1ce0e76d…-20260731-003346`) created and verified with both sources (`deployment_sha`, `version.pre.txt`) in agreement.
**Observer trigger:** RULE 2 auto-fire — ≥3 distinct named-agent invocations: implementation-orchestrator, reviewer-challenge, security-permissions.

Primary evidence sources:
- `C:\PZ-verify\reports\campaigns\2026-07-31-pr1039-rollback-provenance-closure.md`
- `C:\PZ-main\.claude\state\active-campaigns.json` → `campaigns.rollback-provenance`

---

## 1. Per-agent scorecard table

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| implementation-orchestrator | 4 | 4 | 4 | 5 | 5 | 4 | 4 | 30 | EXEMPLARY |
| reviewer-challenge | 4 | 5 | 5 | 5 | 5 | 4 | 3 | 31 | EXEMPLARY |
| security-permissions | 3 | 3 | 4 | 4 | 5 | 3 | 3 | 25 | ACCEPTABLE |

---

## Dimension rationale per agent

### implementation-orchestrator — 30 — EXEMPLARY

**Specificity (4):** Named outputs throughout: `deployment_sha` / `restored_sha` / `version.pre.txt` as distinct field identities, all 9 GATE-4 dispositions by name and state, explicit commit SHAs (`719c28fa` for H-1/H-2 fixes, `bd0274a6` for subsequent extensions, `1ce0e76d` for merge commit), test counts (48 pytest structural pins + 21 behavioural checks + golden 160/160), and unit.json field values in the final provenance table. Three in-flight specificity failures corrected before merge: (c) the claim that `C:\PZ-backups` held "exactly two units" was wrong — 16 directories exist, 14 of which fail `UNIT_RX` (`^[0-9a-f]{40}-\d{8}-\d{6}$`) and were never selectable; corrected after direct filesystem enumeration. (d) The overlap check initially used the wrong merge base and was re-done against the true base (`92222849`). These self-corrections confirm the agent verifies its claims, but the initial errors are real specificity failures. Score 4.

**Coverage (4):** Full campaign scope delivered — design, implementation (5 files), 48 structural pytest pins, 21 behavioural test checks via `Test-RollbackProvenance.ps1`, deployment, and 10/10 closure validation. One critical in-flight coverage failure: (b) the first draft of a new structural pin was vacuous — the slice searched for the very assignment it was meant to verify, so any mutation of the protected code would still pass. The vacuousness was caught only by explicitly re-running the pins against the prior revision. A vacuous pin is worse than no pin (false confidence); self-correction before merge preserves final coverage integrity, but the initial failure penalises this dimension. Score 4.

**Severity (4):** Accepted both HIGH findings from reviewer-challenge (H-1, H-2) without deflating them and acted immediately — both fixed and test-pinned before merge. Applied all GATE-4 severity designations at appropriate levels: M-2 as SCHEDULED (not RESOLVED, because executing it requires a real rollback forbidden for this campaign), F-2 as SEPARATE PR requiring its own security review, LOW findings as ACCEPTED with named compensating controls. No inflation or deflation in the final record. Score 4.

**Actionability (5):** All 9 GATE-4 dispositions explicitly recorded in `active-campaigns.json` with finding names, final states, and rationale. Operator boundary (merge / authorization minting / deploy) correctly identified, respected, and documented — including an explicit refusal to run a self-authored wrapper script (`operator-1039-merge-deploy.ps1`) that would have slipped two `pz-deploy-guard`-guarded actions past the name-based rules on a filename technicality, while also failing mid-flight at the mint step for want of a signing key. The legacy-unit compatibility decision was correctly escalated to the operator with a full rationale rather than being guessed, deferred without documentation, or incorrectly backfilled. No "noted" non-dispositions appear in the record. Score 5.

**Substitution (5):** Main session orchestrator. GATE 5 N/A. Score 5.

**Evidence (4):** Strong final evidence: the closure report (§4/§5) quotes the 10/10 PASS transcript verbatim with individual test names and runtime values; unit.json field values verified against the actual backup unit; manifest diff = 0 discrepancies (Lesson P content check, not robocopy copy-count); engine parity confirmed; single NSSM child PID confirmed with no restart loop; `pz_stderr.log` confirms clean startup banner only. The wrong unit count claim ("exactly two units" when there are 16 directories) was a meaningful in-flight evidence error in a claim about the production backup directory. The concurrent-writer incident (248 uncommitted insertions in the worktree attributed to a third party at pre-merge recheck) introduced genuine environment-state confusion before being resolved as self-attribution. Both errors were corrected by direct verification, which is the correct methodology. Score 4.

**Environment (4):** Worktree path (`C:\PZ-wt\rollback-provenance`), branch (`fix/rollback-provenance`), and SHA tracking maintained explicitly in `active-campaigns.json` throughout. `C:\PZ-verify` used as the stated canonical source of truth for git operations. The concurrent-writer incident (who wrote the 5 modified files) was ultimately resolved correctly and documented with full evidence (the five files and their content matched the session's own edit pass responding to the two safety reviews). The worktree-administration note (`C:\PZ-verify\.git\worktrees\rollback-provenance`) was correctly flagged as a dependency constraint. The in-flight attribution confusion and the wrong unit count are genuine environment observation errors, both corrected — reducing from a 5 but not reaching the failure class that scores 1. Score 4.

---

### reviewer-challenge — 31 — EXEMPLARY

**Specificity (4):** Four named findings with mechanism-level specificity:
- **H-1:** Stale `$stage` variable persists through the restoration block. The progress display lies to the operator while bytes are being overwritten — not a display artifact, a correctness failure in safety-critical feedback.
- **H-2:** Re-run advice printed after a successful rollback. An operator following the guidance would re-execute an already-completed action in a production restoration context.
- **F-2:** `-RestoredSha` operator override flag has no independent security review; deferred to a separate PR.
- **L-3:** Single-writer structural pin does not scan `[System.IO.File]::WriteAllText`. Named compensating control (`test_no_undeclared_production_writers`) cited as the reason ACCEPTED is the correct disposition.

All four are mechanically precise — the mechanism of failure is named, not just the finding category. Minor deduction: the closure report and `active-campaigns.json` are the mediation layer; exact line numbers for PowerShell findings are not reproduced in the campaign evidence record (unlike JSX/HTML campaigns where line numbers appear verbatim). Score 4.

**Coverage (5):** Found the two most operationally significant defects in the rollback path — defects introduced during this same campaign that would have shipped without the adversarial review. H-1 directly affects operator situational awareness during a high-stakes production restoration; H-2 gives a misleading post-success instruction that could trigger double-execution of a rollback. The review also surfaced F-2 (a security-scope item requiring a separate PR) and L-3 (a test-scan gap with a named compensating control). Four distinct concern classes covered. Score 5.

**Coverage note — self-sourced defects:** H-1 and H-2 were in code written during this same campaign. Finding campaign-introduced defects is the adversarial reviewer's highest-value outcome; the reviewer-challenge fulfilled exactly that function here.

**Severity (5):** H-1 and H-2 correctly labeled HIGH — stale state in a safety-critical progress display and misleading post-rollback guidance are operator-trust failures in a production deployment script where operator decisions are irrecoverable. SHIP-WITH-MITIGATIONS is the correct verdict level: not BLOCK (the fixes are straightforward and the PR is otherwise sound), not PASS (the mitigations must be applied and pinned before merge). F-2 correctly identified as requiring its own security review. L-3 correctly treated as informational with a named compensating control — no inflation. Four findings, calibrated across HIGH/HIGH/deferred/informational — no flattening. Score 5.

**Actionability (5):** All four findings translated to named artifacts before merge:
- H-1 → Fixed in `719c28fa`, pinned by `test_rollback_stage_is_true_while_the_tree_is_being_overwritten`
- H-2 → Fixed in `719c28fa`, pinned by `test_rollback_does_not_tell_the_operator_to_rerun_a_rollback_that_succeeded`
- F-2 → Deferred to a separate PR, named in GATE-4 dispositions with an explicit "its own security review" requirement
- L-3 → Accepted with named compensating control `test_no_undeclared_production_writers`

No finding left with a non-disposition. All HIGH findings resolved and test-pinned, not merely noted. Score 5.

**Substitution (5):** Canonical registered agent. GATE 5 N/A. Score 5.

**Evidence (4):** Mechanism-specific findings with named code constructs and variable names. The adoption of both HIGH findings as fixes plus named regression pins under GATE 1 conditions before merge is the strongest post-hoc evidence quality confirmation available — the cited code behaviors were accurate enough to produce specific, pinning tests. Minor deduction: the mediation layer means exact line numbers for the PowerShell findings are not independently reproducible from the scorecard evidence record. Score 4.

**Environment (3):** No explicit worktree path, branch, or commit SHA self-disclosed in the verdict block per the closure report. The accurate, mechanism-level identification of H-1 and H-2 confirms the agent read the correct version of the code (the pins that followed named the right variable and the right output string). Standard 3/5 per established disclosure convention. Score 3.

---

### security-permissions — 25 — ACCEPTABLE

**Specificity (3):** Two named findings:
- **LOW-1:** Unit integrity should be corroborated before trusting the unit's own evidence during the legacy-recovery procedure. Resolved by adding a manifest + timestamp corroboration step.
- **LOW-2:** Exception text may print config paths when the script fails. Accepted — operator-run script, paths are already in the tracked config.

Finding names are specific enough to be dispositioned (LOW-1 was fixed, LOW-2 was accepted with a named rationale). However, the closure report characterizes the review outcome at a general level: no mechanism-level description of how the unit-integrity gap could be exploited, no specific exception handling path cited, no PowerShell line reference. Score 3.

**Coverage (3):** The security-permissions scope covers auth, secrets, injection, and integrity properties of the deployment script changes. LOW-1 and LOW-2 are legitimate in-scope findings for that mandate and were correctly surfaced. Coverage gap: H-1 (stale `$stage` variable) and H-2 (misleading re-run advice) are both HIGH-severity issues in the same production-critical `Invoke-Rollback` function that LOW-1's "unit integrity" finding touches. While H-1 and H-2 are strictly correctness/operator-safety issues rather than auth/secrets/injection, a security review of deployment tooling that extends to integrity (LOW-1 found) should reasonably cover operator safety in the same code path. Both H-1 and H-2 were found instead by reviewer-challenge. The security-permissions verdict (PASS-WITH-NOTES) correctly reflects what it found; the gap is what it did not find in the same scope perimeter. Score 3.

**Severity (4):** The two findings it did surface are correctly calibrated as LOW. PASS-WITH-NOTES is the appropriate verdict for a security review where no HIGH or CRITICAL issues are found within the reviewer's scope. No inflation (nothing labeled HIGH that was LOW), no deflation of what it did identify. Score 4.

**Actionability (4):** Both LOW findings had clear, named dispositions: LOW-1 resolved by adding a corroboration step to the legacy-recovery procedure (step 2 of the "Legacy unit recovery" operator procedure); LOW-2 accepted with explicit rationale. PASS-WITH-NOTES gave the operator a clear go signal. Score 4.

**Substitution (5):** Named as `security-permissions` in the campaign registry (`active-campaigns.json`). First scored appearance under this specific name in the scorecard record. Prior campaigns used `security-write-action-reviewer` — a distinct agent with overlapping security-review scope. No substitution claim made; no GATE 5 disclosure required. Score 5.

**Evidence (3):** LOW-1 and LOW-2 are named at a summary level. The mechanism by which missing corroboration creates risk (what could an attacker or misconfiguration do with an uncorroborated unit?) and the specific exception path that exposes config paths are not described in the closure report evidence record. Finding names are traceable to GATE-4 dispositions but not to independently verifiable file references. Score 3.

**Environment (3):** No explicit worktree path, branch, or commit SHA self-disclosed. Standard disclosure gap per established convention. Score 3.

---

## 2. Weak-verdict warnings

No agent scored NEEDS-TUNING (15–21) or UNRELIABLE (7–14). No formal weak-verdict warnings required under the scoring rules. No new GATE 4 salvage dispositions triggered by the current campaign's scored entities.

**Quality signal for security-permissions (ACCEPTABLE 25 — informational, not a weak-verdict warning):**

This is the first scored appearance of `security-permissions` under that name. The Coverage gap (3/5) is the primary quality signal: H-1 and H-2 are HIGH-severity issues in the same code block that LOW-1's unit-integrity finding covers, yet both were missed by this reviewer. The root question is whether "operator safety in deployment scripts" falls within `security-permissions`' prompt scope or strictly outside it. If the agent prompt is scoped to auth/secrets/injection only, the Coverage gap is a prompt-scope limitation rather than a reviewer failure — and the correct remediation is a scope clarification note in the agent definition, not re-dispatch. If the prompt covers "security of deployment tooling" more broadly, then missing two HIGH operator-safety findings in the same function is a genuine coverage failure.

**Recommended action:** If security-permissions appears in another campaign involving deployment-tooling changes and again surfaces only low-severity configuration notes while a parallel reviewer finds HIGH safety issues in the same code, open a GATE 4 SCHEDULED disposition for prompt scope clarification (Lesson K: name what the agent is and is not mandated to check). One data point is insufficient to trigger a REPEATED-WEAK flag. No re-dispatch needed for this task.

---

## 3. Repeated failure hints

**5 most recent prior campaign scorecards reviewed (excluding self-eval files):**

1. **2026-07-28** `2026-07-28-advisory-service-id-draft-fallback.md` — 2 agents scored: security-write-action-reviewer ACCEPTABLE (27), reviewer-challenge EXEMPLARY (31). Neither implementation-orchestrator nor security-permissions appeared.
2. **2026-07-17** `2026-07-17-proforma-privileged-auth.md` — 4 entities scored: backend-safety-reviewer EXEMPLARY (30), security-write-action-reviewer EXEMPLARY (28), reviewer-challenge EXEMPLARY (33), orchestrator EXEMPLARY (34). implementation-orchestrator appeared as "orchestrator": EXEMPLARY. security-permissions did not appear.
3. **2026-07-11** `2026-07-11-pr-queue-clear-b123bd4c-deploy-gate.md` — 8 entities; 6 EXEMPLARY, 2 ACCEPTABLE (deploy-security-reviewer 27, deploy-release-manager 26). None of the current campaign agents appeared.
4. **2026-07-03** `2026-07-03-phase-c-wave2-backend.md` — 3 entities; all EXEMPLARY. None of the current campaign agents appeared.
5. **2026-06-22** `2026-06-22-pr720-merge-validation.md` — orchestrator only; EXEMPLARY (35). None of the current campaign agents appeared.

**reviewer-challenge appearances in the prior 5-campaign window:**
- 2026-07-28: EXEMPLARY (31). 2026-07-17: EXEMPLARY (33). No NEEDS-TUNING or UNRELIABLE appearances. No REPEATED-WEAK flag triggered.

**security-permissions appearances in the prior 5-campaign window:**
- First scored appearance under this name. Note: `security-write-action-reviewer` (distinct agent, overlapping scope) appeared ACCEPTABLE (27) in 2026-07-28 and EXEMPLARY (28) in 2026-07-17 — no NEEDS-TUNING or UNRELIABLE pattern for that agent either. No REPEATED-WEAK flag for security-permissions.

**implementation-orchestrator appearances in the prior 5-campaign window:**
- 2026-07-17: appeared as "orchestrator", scored EXEMPLARY (34). No NEEDS-TUNING or UNRELIABLE appearances. No REPEATED-WEAK flag.

**Active REPEATED-WEAK flags (carried from prior scorecards):**

`REPEATED-WEAK (8th+ consecutive scorecard cycle): agent frontend-flow-reviewer has scored ACCEPTABLE in 5+ consecutive campaign appearances.`
- GATE 4 ISSUE disposition generated in `2026-06-21-freight-authority-blocker-repair.md`. Operator must either confirm the GitHub issue tagged `agent-tuning` has been filed, or provide an explicit REJECTED disposition with reasoning. This item has appeared in every scorecard since that campaign without operator-side confirmation. **This is now 8+ consecutive scorecard cycles without resolution.** A "noted" acknowledgement is not a valid GATE 4 disposition per CLAUDE.md §GATE 4. `frontend-flow-reviewer` does not appear in this campaign (deployment tooling, no UI surface). Flag carries forward. If no confirmation or REJECTED disposition is provided within the next 2 scorecard cycles, this escalation will be filed as a SCHEDULED chip targeting operator disposition at the next project-state review session.

`REPEATED-WEAK: agent backend-safety-reviewer has scored Evidence 3/5 in multiple recent campaigns. Issue #694 open.`
- 2026-07-17 appearance scored EXEMPLARY (30) with Evidence 4/5 — a positive rehabilitation data point. `backend-safety-reviewer` does not appear in the current campaign. Issue #694 remains open pending one more clean severity-calibration run before the pattern can be cleared. Flag carries forward unchanged.

---

## 4. GATE 4 disposition

No NEEDS-TUNING or UNRELIABLE verdicts produced by this scorecard. No new GATE 4 salvage dispositions created by the current campaign's scored entities.

**Existing GATE 4 open items (carried forward):**
- `frontend-flow-reviewer` REPEATED-WEAK — **ISSUE** (agent-tuning tag; operator confirmation of filing is overdue; 8+ consecutive scorecard cycles). Valid dispositions: SCHEDULED (specific session target), ISSUE (confirm the GitHub issue has been filed), or REJECTED (explicit operator reasoning logged in PROJECT_STATE.md DECISIONS). "Recommendation noted" is not a valid disposition.
- `backend-safety-reviewer` REPEATED-WEAK — **Issue #694** (open; positive evidence-quality data point in 2026-07-17; awaiting one additional clean severity-calibration appearance before closing).

---

## 5. Self-evaluation check (RULE 5 — calendar trigger)

**Trigger assessment:**
- Most recent self-eval file: `self-eval-2026-07-28.md` (dated 2026-07-28)
- Today: 2026-07-31
- Calendar days elapsed: 3 days — does NOT exceed the 7-day threshold
- `SELF-DEGRADATION DETECTED` flag in `self-eval-2026-07-28.md`: absent (`NO SELF-DEGRADATION DETECTED`, self-score 31/35 EXEMPLARY, all dimensions stable or improved)
- Counter trigger: not applicable (no active SELF-DEGRADATION flag)

**Calendar trigger does not fire. Self-evaluation skipped this run.**
