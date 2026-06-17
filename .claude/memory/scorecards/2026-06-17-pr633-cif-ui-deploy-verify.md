# Agent Performance Scorecard — PR #633 CIF UI + Polish-Desc Gate Deploy & Live-Verify (2026-06-17)

**Date:** 2026-06-17
**Campaign:** PR #633 "fix(customs): UI + Polish-desc gate read resolved CIF authority, not raw invoice 0"
**Squash SHA deployed:** 4652292 (origin/main tip post-merge)
**Deploy source worktree:** C:\PZ-deploy-633 (immutable detached worktree, pinned at 4652292)
**AWB live-verified:** 2315714531
**Outcome:** Full 7-agent gate — GO. All 5 acceptance criteria green post-deploy. PZService RUNNING.
**Key incident:** One-session-rule violation on C:\PZ-verify during gate run. A concurrent Claude Code
session switched that tree mid-gate (to feat/pr1a-conflict-foundation-remediation, moving
085f93a→a0c7eff). Two reviewers (deploy-backend-impact-reviewer, deploy-release-manager) emitted
false BLOCKER verdicts; QA emitted a false "file absent" note. Contained by creating immutable
detached worktree C:\PZ-deploy-633 at 4652292 as the correct deploy source. Filed as GATE 4
ISSUE #636.
**Agents evaluated:** 7 (full mandatory deploy gate)

---

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| deploy-git-diff-reviewer | 5 | 5 | 5 | 5 | 5 | 5 | 4 | 34 | EXEMPLARY |
| deploy-backend-impact-reviewer | 4 | 5 | 3 | 4 | 5 | 3 | 2 | 26 | ACCEPTABLE |
| deploy-persistence-storage-reviewer | 5 | 5 | 5 | 5 | 5 | 5 | 4 | 34 | EXEMPLARY |
| deploy-security-reviewer | 5 | 5 | 5 | 5 | 5 | 5 | 4 | 34 | EXEMPLARY |
| deploy-qa-reviewer | 4 | 5 | 3 | 4 | 5 | 3 | 2 | 26 | ACCEPTABLE |
| deploy-release-manager | 4 | 5 | 3 | 4 | 5 | 3 | 2 | 26 | ACCEPTABLE |
| deploy-lead-coordinator | 5 | 5 | 5 | 5 | 5 | 5 | 4 | 34 | EXEMPLARY |

---

## Scoring rationale per agent

### deploy-git-diff-reviewer (34 — EXEMPLARY)

- **Specificity (5):** Returned CLEAR with named file classification. No forbidden paths detected. The
  change scope (UI cif_unresolved guard, Polish-desc gate read, resolve_cif resolver import) maps to
  specific, nameable files — the reviewer correctly identified the file set and classified each.
  Route-level auth surface confirmed (`require_api_key + require_role admin/logistics` present on
  affected route).
- **Coverage (5):** Full diff classification performed. Forbidden-paths check clean. Auth surface
  audit on the modified route. No out-of-scope edits detected. This is the correct scope for a
  targeted customs-UI fix touching a single route and two UI rendering guards.
- **Severity (5):** CLEAR is the correct verdict for a diff that carries no forbidden paths, no auth
  regression, no cross-cutting file risk. The change is surgically scoped to UI gate logic and a
  resolver import — CLEAR is not a deflated verdict here.
- **Actionability (5):** File classification + CLEAR provides unambiguous input to the coordinator.
  The auth surface confirmation (`require_api_key + require_role`) closes the highest-risk question
  for a customs-adjacent route change.
- **Substitution (5):** No substitution. Canonical agent dispatched.
- **Evidence (5):** File-level classification is the correct evidence artifact for this agent's role.
  Auth surface claim (`require_api_key + require_role admin/logistics`) is independently verifiable
  against the diff. Marker count verification (cif_unresolved = 2, `_dskBlocked = !_decResolved` = 1,
  resolver import = 1) confirms the agent examined actual file contents.
- **Environment (4):** The gate was subsequently re-run on C:\PZ-deploy-633 at SHA 4652292 after the
  C:\PZ-verify drift incident. The git-diff-reviewer operated against the correct squash SHA
  4652292. Minor deduction: self-reported working tree path and SHA not explicitly stated in verdict
  block (shared structural gap across campaign); however no false reading was produced, and the
  re-run worktree basis is documented at campaign level.

---

### deploy-backend-impact-reviewer (26 — ACCEPTABLE)

- **Specificity (4):** Re-run verdict (on C:\PZ-deploy-633) correctly identified the resolve_cif
  resolver as a pure stdlib function with no DB writes. Named the clearance_decision shape change as
  read-only computation. Named the import chain (resolve_cif added to routes_customs.py). Claims are
  specific enough to be verifiable but less granular than line-level evidence.
- **Coverage (5):** Covered all backend surfaces relevant to PR #633: route auth (unchanged, confirmed),
  resolve_cif import and function scope (stdlib, no side effects), clearance_decision shape (additive
  read fields), UI gate rendering path (cif_unresolved guard logic). No backend surface omitted.
- **Severity (3):** The initial false BLOCKER verdict is the severity-calibration failure event in this
  campaign. The re-run verdict (CLEAR after worktree correction) is correctly calibrated. Scoring
  reflects the agent's full run history for this campaign, including the drift-induced false positive.
  A false BLOCKER is a severity-calibration failure regardless of environmental cause — the agent
  emitted CRITICAL severity ("markers absent, deploy blocked") for a condition that was an environment
  artifact, not a code defect. The re-run corrects this, but the false positive counts against
  calibration. Score 3 (not 1, because the false positive had an identifiable environmental trigger
  that the agent could not independently detect without self-reporting its worktree path).
- **Actionability (4):** Re-run verdict (CLEAR) translates correctly to coordinator input. Initial
  verdict caused an unnecessary gate stall (re-dispatch required). The re-run actionability is strong;
  the initial verdict's actionability was harmful (false block). Score reflects recovery but not full
  credit given the gate-delay cost.
- **Substitution (5):** No substitution. Canonical agent dispatched.
- **Evidence (3):** Re-run evidence: stdlib-only resolver claim, route auth unchanged claim, no new
  DB writes claim — all verifiable against the diff. Initial run: "markers absent" evidence was a
  false reading of a drifted tree. Because the agent did not disclose its worktree path in either
  run, the false reading was only catchable by the orchestrator cross-checking the concurrent-session
  incident. Evidence score penalized for the false-reading run and for absence of worktree
  self-disclosure in both passes.
- **Environment (2):** This is the critical failure dimension. The agent read C:\PZ-verify at SHA
  085f93a→a0c7eff (a concurrent session had switched the branch) and reported "markers absent" without
  disclosing the working tree path or the SHA it actually examined. The PATH GUARD canon requires
  C:\PZ-verify for all verification reads, and that path was the correct target — but the tree had
  silently drifted. Had the agent self-reported "(examined C:\PZ-verify @ <SHA>)" the orchestrator
  could have caught the SHA mismatch immediately rather than requiring a separate diagnostic step.
  The false BLOCKER was a direct consequence of missing environment disclosure. Score 2 (not 1 because
  the drift was externally caused, not agent-originated deception; score 1 would apply if the agent
  fabricated environment claims).

---

### deploy-persistence-storage-reviewer (34 — EXEMPLARY)

- **Specificity (5):** Named the resolve_cif function explicitly as a pure computation with no storage
  writes. Confirmed cif_state is a transient per-call dict (not persisted). Confirmed no new DB tables,
  no schema mutations, no audit pointer updates. Three specific negative-evidence claims covering all
  persistence surfaces the change could have touched.
- **Coverage (5):** Covered all persistence surfaces: DB schema (no new tables), audit record mutation
  (none), transient state scope (cif_state per-call only), storage writes (none). Negative-evidence
  coverage for a "resolver is pure stdlib" change requires explicitly confirming the pure-function
  claim rather than simply stating "no schema changes" — this agent did exactly that.
- **Severity (5):** CLEAR is fully calibrated. A pure-function resolver that writes no state, touches
  no DB, and modifies no audit records is genuinely zero persistence risk. CLEAR is not deflated here.
- **Actionability (5):** Unambiguous CLEAR with named negative evidence. Coordinator receives clean
  persistence clearance without conditions.
- **Substitution (5):** No substitution. Canonical agent dispatched.
- **Evidence (5):** The resolve_cif pure-function claim and cif_state per-call dict claim are both
  verifiable against the diff. Negative-evidence scope (no DB writes, no schema mutation, no audit
  pointer updates) is the correct evidence class for a pure-computation change. No fabrication, no
  assertion without basis.
- **Environment (4):** Agent operated against the correct worktree (C:\PZ-deploy-633 at 4652292) on
  re-run, or was unaffected by the drift incident (persistence review of a pure-function resolver
  does not depend on the same file markers that triggered the false blockers). Minor deduction: same
  structural gap — working tree path and SHA not self-reported in verdict block.

---

### deploy-security-reviewer (34 — EXEMPLARY)

- **Specificity (5):** Named the route auth surface explicitly: `require_api_key + require_role
  admin/logistics` unchanged. Named React text interpolation as the XSS mitigation mechanism for
  CIF field rendering in UI. Named the resolver as stdlib-only (no exec, no subprocess, no SQL).
  Three specific, independently verifiable security claims.
- **Coverage (5):** Covered all security surfaces for this change: route auth (unchanged), UI
  rendering path (React text interpolation, XSS-safe), resolver execution model (stdlib, no
  injection surface), credential exposure (none). The React text interpolation call-out is high-value
  coverage — UI changes that render external data values (CIF amounts from customs docs) have an XSS
  surface that must be explicitly cleared.
- **Severity (5):** CLEAR with route auth confirmed and XSS mechanism named is fully calibrated.
  No inflation (no conditions added for already-confirmed security properties) and no deflation
  (XSS surface was named and cleared, not skipped).
- **Actionability (5):** CLEAR with named mechanism (React text interpolation for XSS safety) is
  directly actionable — the operator knows precisely why the XSS risk is cleared, not just that it is.
  Route auth unchanged is the most important security property for a customs route; it is confirmed.
- **Substitution (5):** No substitution. Canonical agent dispatched.
- **Evidence (5):** React text interpolation as XSS mitigation is a named, verifiable mechanism.
  Route auth (`require_api_key + require_role admin/logistics`) is a named, verifiable guard.
  Stdlib-only resolver is a named, verifiable execution model. All three claims can be confirmed
  against the diff without additional context.
- **Environment (4):** Agent operated correctly against the right worktree (no false reading
  produced). Minor deduction: same structural gap — self-reported working tree path and SHA absent
  from verdict block.

---

### deploy-qa-reviewer (26 — ACCEPTABLE)

- **Specificity (4):** Re-run verdict confirmed PZ 221/221 and carrier 412/412 on C:\PZ-deploy-633.
  Named the "file absent" observation from the initial run as an artifact of the C:\PZ-verify drift,
  not a real test gap. Baseline counts cross-referenced (test-baseline.md). Specific enough to be
  actionable.
- **Coverage (5):** PZ suite, carrier suite, and baseline cross-reference all covered. The initial
  "file absent" note, while a false signal, demonstrates the agent was examining the actual test file
  tree rather than asserting counts from memory — this is the correct approach even when the result
  is a drift-induced artifact.
- **Severity (3):** The initial "file absent" note is a severity-calibration failure of a different
  class than the backend reviewer's false BLOCKER — it is a drift-induced observation rather than a
  false block. However, a QA reviewer that cannot distinguish "test file missing from the tree I
  examined" from "test file genuinely absent" without self-disclosing the tree path leaves the
  orchestrator unable to triage the observation without additional investigation. Severity score 3
  (not 1, because the observation was flagged as an observation rather than a hard block, and the
  re-run corrected it).
- **Actionability (4):** Re-run verdict (221/221, 412/412) is actionable. Initial observation
  required orchestrator re-dispatch overhead. Score reflects the re-run quality; penalized for the
  initial ambiguous "file absent" observation that required diagnostic follow-up.
- **Substitution (5):** No substitution. Canonical agent dispatched.
- **Evidence (3):** Re-run evidence: concrete test counts (221/221, 412/412) verifiable against
  baseline. Initial run: "file absent" evidence was a false reading of the drifted tree. Same
  evidence-quality penalty as the backend reviewer — correct on re-run but the initial reading was
  unreliable due to undisclosed working tree state.
- **Environment (2):** Same failure mode as deploy-backend-impact-reviewer. The "file absent"
  observation was produced by reading C:\PZ-verify at the drifted SHA without self-disclosing the
  path or SHA examined. Had the QA reviewer stated "(examined C:\PZ-verify @ <SHA>)" the orchestrator
  could have immediately identified the tree state mismatch. Score 2 for same reasons as backend
  reviewer (externally caused drift, not fabrication, but missing disclosure that masked the cause).

---

### deploy-release-manager (26 — ACCEPTABLE)

- **Specificity (4):** Re-run verdict on C:\PZ-deploy-633 named the rollback target (SHA 4652292
  rollback → prior production SHA via backup restore), the required robocopy steps, and the
  `__pycache__` clear. Initial false BLOCKER ("markers absent") was retracted on re-run with explicit
  rationale (worktree drift). Re-run specificity is adequate for a release-manager execution plan.
- **Coverage (5):** Branch hygiene (FF-only from main, clean), Lesson D N/A (standard post-merge
  deploy), rollback procedure, robocopy step enumeration (service/app standard + any engine files per
  Lesson J scope check), service restart, post-deploy smoke. Full release-manager scope covered on
  re-run.
- **Severity (3):** Same false-BLOCKER calibration failure as backend reviewer, for the same
  environmental cause. Re-run verdict calibration is correct (GO-WITH-CONDITIONS, ordered execution
  plan). Severity score reflects the full campaign run including the false positive.
- **Actionability (4):** Re-run produces an operator-executable ordered plan. Initial false BLOCKER
  created a gate stall requiring re-dispatch. Score reflects re-run quality; penalized for initial
  gate-delay cost.
- **Substitution (5):** No substitution. Canonical agent dispatched.
- **Evidence (3):** Re-run evidence: rollback SHA named, robocopy steps enumerated, smoke step named.
  Initial run: "markers absent" evidence was a false reading. Same evidence-quality profile as
  backend reviewer. Missing worktree self-disclosure on both passes.
- **Environment (2):** Same failure mode. The initial "markers absent" false BLOCKER was produced by
  reading C:\PZ-verify at the drifted SHA without disclosing the path or SHA examined. Score 2 for
  same reasons as backend reviewer.

---

### deploy-lead-coordinator (34 — EXEMPLARY)

- **Specificity (5):** Identified the concurrent-session drift incident precisely. Named the
  containment action (create immutable detached worktree C:\PZ-deploy-633 at 4652292) rather than
  force-resetting C:\PZ-verify (which would have raced the other session). Named all 5 acceptance
  criteria and confirmed all green post-deploy. Final verdict GO with worktree-corrected re-run
  synthesis.
- **Coverage (5):** Full synthesis of all 6 specialist re-run inputs. Drift incident documented.
  Containment decision explained (why NOT force-reset, why immutable worktree instead). AWB
  2315714531 live-verification synthesis across all three independent verification methods: (a)
  deployed markers, (b) deployed code logic against live audit, (c) running service's stored
  clearance_decision. All 5 acceptance criteria checked by name.
- **Severity (5):** GO after re-run is the correct final verdict when all 6 specialists clear on
  the correct tree and all 5 acceptance criteria are verified. The coordinator correctly distinguished
  the drift-induced false blockers from real blockers and escalated to GATE 4 ISSUE #636 for the
  one-session-rule violation — not conflating the process failure with a code-quality blocker.
- **Actionability (5):** Named the GATE 4 filing (ISSUE #636 for the one-session-rule violation).
  Provided three-method verification summary that gives the operator independent confidence without
  requiring re-examination. The containment decision (immutable worktree) is documented as an
  operator-reproducible pattern for future concurrent-session conflicts.
- **Substitution (5):** No substitution. Canonical agent dispatched.
- **Evidence (5):** Three-method verification (deployed markers at named paths, resolver logic
  against live audit, running service's stored clearance_decision with ISO timestamp
  2026-06-17T12:28:36Z) is the strongest live-verification evidence chain in recent campaign history.
  GATE 4 ISSUE #636 is a named, verifiable governance artifact. All 5 acceptance criteria named and
  confirmed green.
- **Environment (4):** The coordinator explicitly documented the worktree path used for the
  authoritative re-run (C:\PZ-deploy-633 at 4652292) and the cause of the initial false readings
  (C:\PZ-verify drift to 085f93a→a0c7eff). This is the highest Environment score in the campaign
  because the coordinator self-disclosed the environment state that caused the incident. Minor
  deduction: the coordinator's own verdict block did not include a self-reported "I synthesised from
  C:\PZ-deploy-633 @ 4652292" line (it is available from the campaign narrative rather than the
  verdict block itself).

---

## Weak-verdict warnings

### Three agents scored ACCEPTABLE (26/35): deploy-backend-impact-reviewer, deploy-qa-reviewer, deploy-release-manager

**Root cause (shared):** All three ACCEPTABLE scores trace to a single environmental event — the
concurrent Claude Code session that switched C:\PZ-verify from SHA 4652292 to the
feat/pr1a-conflict-foundation-remediation branch (085f93a→a0c7eff) mid-gate. The false readings
(backend: "markers absent" BLOCKER; QA: "file absent" observation; release-manager: "markers absent"
BLOCKER) were all caused by reading a drifted tree without self-disclosing the working tree path or
SHA examined.

**Scoring treatment (per operator instruction):** The false verdicts are attributed to environment
(concurrent-session drift), not agent logic. However, they are still scored as reliability signals
because the correct mitigation — self-disclosing working tree path and SHA in every verdict block —
would have surfaced the drift immediately, avoiding the re-dispatch overhead. The agents are held to
the Environment dimension standard regardless of the drift's external cause.

**Quoted failure-mode evidence:**

deploy-backend-impact-reviewer initial verdict excerpt (reconstructed from campaign context):
> "markers absent — deploy blocked"

deploy-qa-reviewer initial observation excerpt:
> "file absent [artifact]"

deploy-release-manager initial verdict excerpt:
> "markers absent — BLOCKER"

All three were retracted on re-run against C:\PZ-deploy-633 and replaced with CLEAR/GO verdicts.

**GATE 4 disposition required (per RULES 2+6 / CLAUDE.md GATE 4):**
These are ACCEPTABLE verdicts, not NEEDS-TUNING or UNRELIABLE. GATE 4 mandatory disposition only
triggers for NEEDS-TUNING or UNRELIABLE. However, the three-agent false-positive cluster represents
a significant environment-sensitivity risk that warrants proactive disposition:

**Recommended disposition (operator decision required):**
- SCHEDULED: Add explicit worktree self-disclosure requirement ("In your verdict block, state:
  (a) working tree path examined, (b) commit SHA examined, (c) confirm path matches C:\PZ-verify
  or explicitly-named alternate worktree") to the prompt templates of all three affected agents.
  This converts an environment-sensitivity gap into a self-healing detection mechanism.

**Re-dispatch recommendation:** Not required — all three agents produced correct verdicts on re-run
against the correct worktree. The structural fix is prompt-level environment disclosure, not
agent replacement.

**Note on GATE 4 filing:** The one-session-rule violation that caused the drift has already been
filed as GATE 4 ISSUE #636 by the deploy-lead-coordinator. That covers the process failure. The
agent-level prompt gap (missing environment self-disclosure) is a separate, related finding that
should be SCHEDULED alongside or as a sub-task of #636.

---

## Repeated failure hints

**5 most recent campaign scorecards reviewed:**
1. 2026-06-16: deploy-gate-pr625-626-627
2. 2026-06-15: deploy2-pr602-pr608
3. 2026-06-13: deploy1-authority-train
4. 2026-06-13: campaign-02-5-authority-completion
5. 2026-06-13: c02-authority-consolidation

### deploy-backend-impact-reviewer — Pattern check

- 2026-06-13 deploy1-authority-train: EXEMPLARY
- 2026-06-15 deploy2-pr602-pr608: EXEMPLARY
- 2026-06-16 pr625-626-627: EXEMPLARY (33)
- 2026-06-17 pr633 (this campaign): ACCEPTABLE (26) — drift-induced false BLOCKER

**Assessment:** No REPEATED-WEAK flag. The ACCEPTABLE score is a single-campaign event with an
identified environmental cause (concurrent-session drift). The agent's re-run performance was clean.
Prior 3 campaigns: all EXEMPLARY. The drift incident is not a repeated agent failure; it is the
first environmental reliability event for this agent. Watch for recurrence in the next campaign
with a focus on Environment self-disclosure.

### deploy-qa-reviewer — Pattern check

- 2026-06-13 deploy1-authority-train: EXEMPLARY
- 2026-06-15 deploy2-pr602-pr608: EXEMPLARY (30)
- 2026-06-16 pr625-626-627: EXEMPLARY (30)
- 2026-06-17 pr633 (this campaign): ACCEPTABLE (26) — drift-induced false "file absent"

**Assessment:** No REPEATED-WEAK flag. Same single-campaign environmental event. Prior 3 campaigns:
all EXEMPLARY. Not a recurring failure pattern.

### deploy-release-manager — Pattern check

- 2026-06-13 deploy1-authority-train: EXEMPLARY (34)
- 2026-06-15 deploy2-pr602-pr608: ACCEPTABLE (26) — prior asserted hygiene without artifact citations
- 2026-06-16 pr625-626-627: EXEMPLARY (31) — recovered
- 2026-06-17 pr633 (this campaign): ACCEPTABLE (26) — drift-induced false BLOCKER

**History check:** The 2026-06-15 ACCEPTABLE was flagged in its campaign scorecard as a one-campaign
regression requiring monitoring. The 2026-06-16 campaign confirmed recovery. The 2026-06-17
ACCEPTABLE has a distinct, environmental cause rather than the structural gap (asserted hygiene
without artifact citations) that caused the 2026-06-15 ACCEPTABLE.

**REPEATED-WEAK assessment:** Two ACCEPTABLE scores in the last 5 campaigns (2026-06-15 and
2026-06-17), but with different root causes — one structural (assertion without artifacts), one
environmental (drift). This does not meet the REPEATED-WEAK threshold (same agent scoring
NEEDS-TUNING or UNRELIABLE in ≥2 prior scorecards). No REPEATED-WEAK flag triggered.

**Monitoring recommendation:** If deploy-release-manager scores ACCEPTABLE or below in the next
campaign for any reason (structural or environmental), the 3-of-6-run pattern check becomes
relevant. Note in next scorecard.

### deploy-git-diff-reviewer — Consistent EXEMPLARY

- Last 5 campaign appearances: EXEMPLARY range (31-34)
- No flags.

### deploy-persistence-storage-reviewer — Consistent EXEMPLARY

- Last 5 campaigns: EXEMPLARY (32-34 range, including recovery from two prior ACCEPTABLEs)
- No flags.

### deploy-security-reviewer — Consistent EXEMPLARY

- Last 5 campaigns: EXEMPLARY (32-34 range)
- No flags.

### deploy-lead-coordinator — Sustained EXEMPLARY recovery

- Last 5 campaigns: EXEMPLARY (30-34 range) since fabrication crisis recovery
- Fabrication pattern has not recurred. Recovery confirmed through this campaign.
- No flags.

**No REPEATED-WEAK flags triggered in this campaign.**

---

## Notable quality signals

**Containment decision quality (deploy-lead-coordinator):** The decision to NOT force-reset
C:\PZ-verify (which would have raced the concurrent session) and instead create an immutable
detached worktree C:\PZ-deploy-633 at the squash SHA 4652292 is the correct containment
action under the one-session-rule constraint. This is a pattern worth encoding: when C:\PZ-verify
is occupied by a concurrent session, an immutable detached worktree at a named SHA is the safe
alternative rather than force-resetting a shared verification resource.

**Three-method live verification:** The post-deploy verification against AWB 2315714531 used three
independent methods: (a) deployed file markers via Select-String, (b) deployed code logic
(resolve_cif / build_clearance_decision) against the live audit, (c) the running service's stored
clearance_decision with ISO timestamp (2026-06-17T12:28:36Z, post-merge). This is the correct
verification depth for a customs-authority change where the business outcome (cif_state=resolved,
clearance_path=dhl_self_clearance, require_polish_description=True, UI guards not blocking) must be
confirmed end-to-end, not just at the file-marker level.

**Environment disclosure as the campaign's single correctable failure class:** The only reason the
drift incident required a full re-dispatch cycle (rather than being diagnosed in < 1 minute) was
that neither the backend reviewer nor the release manager disclosed the working tree path or SHA in
their verdict blocks. Had they included "(examined C:\PZ-verify @ 085f93a)" the orchestrator would
have immediately identified the mismatch with the expected deploy SHA (4652292). The Environment
dimension scored 2/5 for both agents specifically because this disclosure gap materially delayed
the gate and required a containment workaround. This is the prompt-level fix: mandate PATH GUARD
self-disclosure in every deploy-agent verdict block.

**False-positive handling discipline:** Neither the orchestrator nor the operator force-resolved the
false BLOCKERs by overriding them — they were instead diagnosed, root-caused, and corrected by
re-run on a verified worktree. This is the correct discipline. A gate that accepts "override BLOCKER
with rationale" as a valid path is weaker than a gate that requires a re-run on a confirmed-clean
tree.

**GATE 4 ISSUE #636:** The one-session-rule violation that caused this incident has been correctly
filed as a GATE 4 issue. This is the appropriate escalation for a process-level violation of the
working-tree convention (rule 6 of `service/docs/ops/working-tree-convention.md`). The issue
documents the pattern and recommends a session-lock enforcement mechanism or an advisory warning
when a second session attempts to write to C:\PZ-verify.

---

## Self-evaluation cadence check

**Most recent self-eval file:** `.claude/memory/scorecards/self-eval-2026-06-13.md` (written 2026-06-13)
**Today:** 2026-06-17
**Days elapsed:** 4 calendar days
**Trigger threshold:** 7 calendar days OR SELF-DEGRADATION flag + 3rd campaign run since flag

**Self-evaluation NOT triggered.** 4 days < 7-day threshold. The 2026-06-13 self-eval returned
"No degradation detected" — no SELF-DEGRADATION flag is active. Neither trigger condition is met.

**Next self-eval due by:** 2026-06-20 (7 calendar days from 2026-06-13).

---

## Campaign quality summary

**Deploy gate effectiveness:** ACCEPTABLE with strong recovery. Initial run produced two false
BLOCKERs and one false observation due to concurrent-session tree drift. Correct containment
(immutable worktree at squash SHA) enabled valid re-run. Final gate result: GO. All 5 acceptance
criteria green post-deploy.

**Agent performance split:**
- EXEMPLARY (4): deploy-git-diff-reviewer, deploy-persistence-storage-reviewer,
  deploy-security-reviewer, deploy-lead-coordinator
- ACCEPTABLE (3): deploy-backend-impact-reviewer, deploy-qa-reviewer, deploy-release-manager
  (all ACCEPTABLE scores attributed to environment drift, not agent logic failure; re-run performance clean)
- NEEDS-TUNING: none
- UNRELIABLE: none

**Primary learning output:** Environment self-disclosure (working tree path + SHA in every verdict
block) is the single highest-leverage prompt-level fix available for the deploy gate. The cost of
missing this disclosure was a full gate re-dispatch cycle on this campaign. The fix costs 2-3 lines
per agent verdict block. The SCHEDULED disposition (recommended above, pending operator confirmation)
should target all 7 deploy agent prompt templates for the PATH GUARD disclosure requirement.

**Operator action required:**
1. Confirm SCHEDULED disposition for the agent prompt-level fix (PATH GUARD environment disclosure
   in all 7 deploy agent verdict blocks). Can be filed as a sub-task of GATE 4 ISSUE #636 or as
   a separate scheduling entry.
2. No agent re-dispatch required — all agents produced clean verdicts on re-run.
3. No PR or code changes required — deploy and live-verification are complete and verified.
