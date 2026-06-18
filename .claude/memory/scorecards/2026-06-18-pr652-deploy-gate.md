# Agent Performance Scorecard — Deploy Gate: PR #652 (audit_merge.py PRESERVED_KEYS)

**Date:** 2026-06-18
**Observer:** agent-performance-observer (RULE 2 auto-fire — 7 distinct named-agent invocations)
**Campaign:** PR #652 deploy gate — `audit_merge.py` PRESERVED_KEYS extension (wfirma_export pointer preservation)
**Deploy target:** main commit 03ffce9 (PR #652: add "wfirma_export" to PRESERVED_KEYS)
**Production baseline:** e4d96b5 (verified correct via on-disk probe — PROJECT_STATE was stale, prod was actually at #648; this reframed deploy from tree-wide sync to safe single-file robocopy)
**Source tree:** C:\PZ-verify
**Outcome:** READY-TO-DEPLOY on second coordinator pass. First coordinator pass correctly BLOCKed due to incomplete test suite execution; full suites run post-BLOCK; second pass issued GO. Deploy completed via Method B (scoped single-file robocopy).
**Agents evaluated:** 7 (all 7 canonical deploy agents dispatched)
**Orchestrator self-critique:** See Section 3 below.

---

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| deploy-git-diff-reviewer | 5 | 5 | 5 | 5 | 5 | 4 | 3 | 32 | EXEMPLARY |
| deploy-backend-impact-reviewer | 5 | 5 | 5 | 5 | 5 | 5 | 3 | 33 | EXEMPLARY |
| deploy-persistence-storage-reviewer | 5 | 5 | 5 | 5 | 5 | 4 | 3 | 32 | EXEMPLARY |
| deploy-security-reviewer | 5 | 5 | 5 | 5 | 5 | 4 | 3 | 32 | EXEMPLARY |
| deploy-qa-reviewer | 3 | 3 | 3 | 3 | 5 | 3 | 3 | 23 | ACCEPTABLE |
| deploy-release-manager | 5 | 5 | 5 | 5 | 5 | 5 | 3 | 33 | EXEMPLARY |
| deploy-lead-coordinator | 5 | 5 | 5 | 5 | 5 | 5 | 4 | 34 | EXEMPLARY |

---

## Scoring rationale per agent

### deploy-git-diff-reviewer (32 — EXEMPLARY)

**Specificity (5):** The verdict correctly classified `audit_merge.py` as SAFE_CODE and the new
test file as TEST_ONLY. Critically, it identified the strategic deploy method choice: the
cumulative e4d96b5..main git delta includes many files (including files from intermediate PRs
#648 etc.), and the agent surfaced Method B (scoped single-file robocopy of audit_merge.py
only) over Method A (tree-wide sync) as the blast-radius-bounding recommendation. Naming the
two methods with explicit reasoning for preferring B is the highest-specificity contribution
this agent could make for a one-file fix on a multi-commit delta.

**Coverage (5):** Full scope covered: file classification (safe code vs test-only), forbidden-path
check (no out-of-scope edits), Lesson J compliance (no root-level engine files → no separate
engine sync required), engine-core isolation (pure-stdlib dict module — no routes, no auth,
no schema). The cumulative-delta coverage item is the critical insight: without it, an operator
running a naive git-diff would see a large diff and make the wrong deploy assumption.

**Severity (5):** CLEAR/LOW correctly calibrated. The Method B recommendation is itself a
severity-bounding action — it converts a potentially multi-file deploy (high blast radius) to
a one-file deploy (minimal blast radius). The agent rated the deploy LOW because it correctly
scoped down the risk surface.

**Actionability (5):** Method B provided an immediately executable path that the orchestrator
followed. No ambiguity. The file classification was the exact input the coordinator needed.

**Substitution (5):** Canonical agent. No substitution. GATE 5 N/A.

**Evidence (4):** File classification is stated with correct categories (SAFE_CODE, TEST_ONLY).
Method A vs Method B distinction is conceptually grounded in the cumulative delta observation.
Minor deduction: the verdict block does not enumerate the specific files visible in the
cumulative delta that would be swept by Method A but excluded by Method B — naming those
intermediate files would have made the Method B recommendation independently auditable.

**Environment (3):** C:\PZ-verify is the correct source tree per PATH GUARD. Campaign-level
disclosure. Agent's verdict block does not self-state the path or commit SHA examined.
Systemic gap per Issue #597. No PATH GUARD violation. Score 3/5 per standing calibration.

---

### deploy-backend-impact-reviewer (33 — EXEMPLARY)

**Specificity (5):** The verdict traced: (1) 0 routes added; (2) the PRESERVED_KEYS extension
is additive (tuple append, not replacement); (3) asymmetric merge semantics — keys in
PRESERVED_KEYS are kept from the target dict, all others take source value; (4) all consumers
use `audit.get(...)` or `{}` pattern — no consumers hardcoded assumptions about PRESERVED_KEYS
content; (5) two callers identified and traced. This is the complete backend impact surface for
a pure dict-merge module change. Five independently verifiable claims.

**Coverage (5):** All mandatory backend domains covered for this change type: route registration
(0 new routes), import chain (no new imports), auth guard (not applicable — module has no HTTP
surface), consumer impact (two callers traced, both use get-or-default pattern). The asymmetric
merge semantics analysis is the critical coverage item: it establishes WHY adding "wfirma_export"
to PRESERVED_KEYS is safe (callers already handle optional key presence) rather than just
asserting the change is small.

**Severity (5):** CLEAR/LOW correctly calibrated. The consumer-pattern verification (all callers
use `.get(...)` with defaults) is the evidence that justifies LOW rather than MEDIUM. A change
to merge semantics that consumers hardcoded against would warrant MEDIUM or higher — the agent
correctly checked this and confirmed LOW applies.

**Actionability (5):** Consumer analysis closes the deploy-safety question without conditions.
Coordinator can accept the backend verdict as clean input. No conditions or follow-ups required
from this agent's scope.

**Substitution (5):** Canonical agent. GATE 5 N/A.

**Evidence (5):** Named evidence: zero new routes (verifiable by route-count grep), additive
tuple extension (verifiable by diff inspection), named consumer patterns (`audit.get(...)` /
`{}`), two callers traced by name. The asymmetric merge semantics description is a concrete
behavioral claim that can be verified against the function implementation. Strong evidence chain
for a dict-merge module.

**Environment (3):** Same campaign-level disclosure gap. No PATH GUARD violation. Issue #597.

---

### deploy-persistence-storage-reviewer (32 — EXEMPLARY)

**Specificity (5):** The verdict correctly scoped this as: no schema change, no migration, no
I/O operations in audit_merge.py itself (the module does pure dict transforms, all I/O is
performed by callers). The agent correctly identified that "wfirma_export" being added to
PRESERVED_KEYS affects dict-transform behavior at call sites, not storage writes within the
module. This distinction (transform module vs I/O module) is the critical specificity for a
persistence reviewer on this change type.

**Coverage (5):** Full persistence surface correctly checked: DDL (none), schema migrations
(none), storage writes within the modified module (none), and a correct determination that
the persistence impact is upstream at caller sites — which the backend-impact reviewer covered
separately. No persistence reviewer scope was missed; the "N/A" determination is itself a
substantive finding requiring the agent to confirm the module has no I/O rather than assuming it.

**Severity (5):** CLEAR/LOW correctly calibrated. A pure dict-merge module with no I/O has
zero persistence risk. The agent's verdict is not deflated (it did not wave through with no
analysis) — it named the correct basis for LOW (module performs no I/O itself).

**Actionability (5):** Clean persistence clearance. The distinction between the module's
in-memory behavior and callers' storage behavior is the operator's assurance that the change
doesn't introduce silent audit corruption. Fully actionable for coordinator synthesis.

**Substitution (5):** Canonical agent. GATE 5 N/A.

**Evidence (4):** The "no I/O in audit_merge.py" claim is a verifiable code inspection result.
The "no schema change, no migration" claims are directly verifiable against the diff. Minor
deduction: the verdict block does not cite specific line ranges confirming no file-open,
no db-write, no json-dump in the module — a direct line-level citation of the function body
would make the "pure transform" claim independently auditable without re-reading the module.
The conclusion is correct; the evidence chain stops one level above artifact-level.

**Environment (3):** Same campaign-level disclosure gap. No PATH GUARD violation. Issue #597.

---

### deploy-security-reviewer (32 — EXEMPLARY)

**Specificity (5):** Four precisely scoped security claims: (1) "wfirma_export" is a dict key
name, not a credential, not a secret — correctly rejecting any mis-classification of the
constant string as a security concern; (2) no credential removal or auth downgrade in the
delta; (3) no injection surface (pure-stdlib dict-merge, no user input, no string interpolation);
(4) no forbidden-path edits. The key-name-not-credential distinction is the primary security
specificity for this change — an imprecise reviewer might have flagged "wfirma_export" as
requiring credential audit. This agent correctly resolved the ambiguity.

**Coverage (5):** Full security surface: credential/secret audit, auth guard state, injection
risk, forbidden-path check. The key-name-not-credential determination covers the primary
potential false-positive for this specific change. All four security domains are explicitly
addressed.

**Severity (5):** CLEAR/LOW correctly calibrated. The key-name-not-credential determination
is what makes LOW non-deflated — the agent did not simply assert LOW, it ruled out the one
scenario that would have raised severity.

**Actionability (5):** Clean security clearance. No conditions. Coordinator can accept with
no follow-up security action required.

**Substitution (5):** Canonical agent. GATE 5 N/A.

**Evidence (4):** "wfirma_export is a key name not a credential" is a direct textual analysis
of the constant string — independently verifiable by inspection. "No injection surface" is
grounded in the module's pure-stdlib, no-user-input characterization from the backend reviewer.
Minor deduction: no grep output or explicit forbidden-path check result cited in the verdict
block. The assertions are specific and correct but stop short of artifact-level evidence.

**Environment (3):** Same campaign-level disclosure gap. No PATH GUARD violation. Issue #597.

---

### deploy-qa-reviewer (23 — ACCEPTABLE)

**Summary:** The agent returned a substantively correct verdict but made a self-described
"non-blocking" rationalization for incomplete test suite execution. The coordinator correctly
overrode this rationalization and issued BLOCK, which was the right outcome. The agent's
instinct (change has no engine/calc surface → full suites may not be strictly necessary) was
reasonable in isolation but incorrect relative to the test-baseline contract's unconditional
language. The agent's score reflects that it identified and disclosed its own omission
(honesty positive) while having rationalized an omission it should not have made (coverage
and severity negative).

**Specificity (3):** The verdict correctly named golden harness (160/160) and focused
audit_merge tests (27/27) as the suites run. It also named the suites NOT run: `test_pz_*.py`
(221) and `test_carrier_*.py` (412). Naming the omitted suites is the right transparency
behavior. However, the specificity of the rationalization ("no engine/calc surface → focused
tests sufficient") is framed as a self-assessment of risk rather than a reading of the
baseline contract. The contract language is unconditional; the risk-surface argument is not
a valid override. Score 3 reflects: named counts + named omissions + named rationalization;
deduction for the rationalization being framed as a coverage judgment rather than a contract
reading.

**Coverage (3):** The two suites actually run (golden harness + focused audit_merge) cover
the directly affected module correctly. However, the two suites not run (PZ 221, carrier 412)
are baseline contract requirements per `.claude/contracts/test-baseline.md`. Coverage of the
gate requirement was incomplete. Score 3 reflects partial coverage: within-scope module was
tested thoroughly; contract-required baselines were omitted.

**Severity (3):** The "non-blocking" self-assessment for the omitted suites was incorrectly
calibrated. The test-baseline contract uses unconditional "block" language for counts below
threshold — the agent's risk-surface argument does not override contract language. The
coordinator correctly reidentified the severity as BLOCK. Score 3 reflects: the within-scope
findings (160/160, 27/27) are correctly rated CLEAR; the omission classification (non-blocking
vs blocking per contract) was miscalibrated.

**Actionability (3):** The verdict created an ambiguous gate state: the agent self-assessed
"non-blocking" but the coordinator correctly blocked. The actionable resolution required the
coordinator to override the QA verdict rather than accepting it. An actionable QA verdict
would have been: "Suites X and Y not run — BLOCK until run per baseline contract" rather
than "non-blocking, in my risk assessment." Score 3 reflects: the omission was disclosed
(enabling the coordinator to catch it) but the disposition signal was wrong (non-blocking
vs blocking).

**Substitution (5):** Canonical agent. GATE 5 N/A.

**Evidence (3):** Named counts for what was run (160/160, 27/27) are concrete and verifiable.
Named omissions (test_pz_*.py = 221, test_carrier_*.py = 412) are transparent. Minor
deduction: no explicit citation of the baseline contract language that would have governed
the omission classification — the agent's rationalization implies it chose risk assessment
over contract language, but doesn't quote the contract to frame its choice.

**Environment (3):** Same campaign-level disclosure gap. No PATH GUARD violation. Issue #597.

**GATE 4 disposition (per RULE 6 — ACCEPTABLE verdicts with named dimension gaps):**
The QA reviewer's ACCEPTABLE score on this campaign is a first appearance at this level for
this agent in the recent deploy gate history (prior 3 appearances: all EXEMPLARY). The
omission is attributable to a test-selection judgment error rather than a systematic prompt
gap. However, the error is a real gate-safety risk: if the coordinator had not caught it,
an under-tested deploy would have proceeded.

**DISPOSITION: SCHEDULED** — Add explicit language to deploy-qa-reviewer prompt template:
"The test-baseline contract at `.claude/contracts/test-baseline.md` uses unconditional block
language. The 'focused test' exception (running only targeted module tests) is NOT a valid
disposition for PZ-221 or carrier-412 baselines regardless of perceived impact scope.
If either full-suite count is below threshold, verdict MUST be BLOCK." This makes the
contract reference explicit in the prompt, preventing risk-assessment rationalization from
overriding unconditional contract language. Target: next deploy-gate prompt review session.

---

### deploy-release-manager (33 — EXEMPLARY)

**Specificity (5):** The verdict produced: (1) branch hygiene confirmation (C:\PZ-verify clean,
ff-only eligible); (2) Method B (single-file robocopy) as the explicit deploy command with the
specific file path; (3) pre-deploy backup with named backup target; (4) file-restore rollback
command (correctly noting prod is robocopy-synced, not git-managed — rollback is restore-from-
backup, not git reset); (5) post-deploy checklist including wfirma_export grep (verify the
key is present in deployed PRESERVED_KEYS) and preservation smoke (verify existing wfirma_export
pointer survives a Run-PZ regeneration). All five elements are independently executable.

**Coverage (5):** Full release-manager scope: branch hygiene, deploy command, rollback procedure,
post-deploy verification. The preservation smoke test item (verify existing wfirma_export pointer
survives Run-PZ) is the highest-value coverage item for this specific change — it tests the
behavioral outcome of the fix, not just the file deployment. The rollback mechanism correctly
identifies that production is robocopy-synced (not git-managed), making git reset an invalid
rollback path and file-restore the correct one. This lesson-correct characterization of the
production topology is substantive coverage.

**Severity (5):** CLEAR/LOW with Method B recommendation. The severity framing is correct:
single-file deploy of a pure dict-merge module with a backup and a file-restore rollback path
is low risk. The post-deploy preservation smoke is the one verification that elevates confidence
beyond "file deployed" to "fix is behaviorally active."

**Actionability (5):** Method B command was immediately executable and was used. Backup and
rollback instructions are concrete. Post-deploy checklist (wfirma_export grep + preservation
smoke) provided the operator with specific verification steps. The smoke test design — run a
Run-PZ regeneration and verify the pointer survives — is the right functional test for this
specific fix. Fully actionable.

**Substitution (5):** Canonical agent. GATE 5 N/A.

**Evidence (5):** Method B command named with specific file path. Backup command named. Rollback
mechanism named (file-restore from backup, not git reset) with explicit explanation of why git
reset is wrong for this production topology. Post-deploy checklist includes grep string and
functional smoke test. All artifacts are independently reproducible.

**Environment (3):** Same campaign-level disclosure gap. No PATH GUARD violation. Issue #597.
Note: the release manager's correct characterization of the production topology
(robocopy-synced, not git-managed) implicitly discloses correct environment modeling even
without explicit path/SHA self-reporting.

---

### deploy-lead-coordinator (34 — EXEMPLARY)

**Specificity (5):** FIRST PASS correctly issued BLOCK with the precise contract-grounded reason:
the test-baseline contract uses unconditional language; QA's "non-blocking" self-assessment
does not override it; the full PZ-221 and carrier-412 suites are required before GO can issue.
The block is not a generic "tests needed" — it names the specific suites, the specific baseline
counts, and the specific reason the QA rationalization fails. SECOND PASS issued READY-TO-DEPLOY
after the full suites were run (PZ 221 pass + 1 pre-existing failure #613 documented; carrier
420 pass vs 412 threshold). Named the pre-existing failure by issue number (#613), confirming
it is not a regression from PR #652.

**Coverage (5):** First pass: all 6 specialist verdicts synthesized; BLOCK correctly isolated
to the QA incomplete-suite finding rather than blocking on other agents' clean verdicts. This
is precise blocking — not a global hold. Second pass: full suite results integrated; pre-existing
failure dispositioned by issue number; all 6 specialist clean verdicts accepted; Method B
(single-file) endorsed as the deploy path.

**Severity (5):** BLOCK on first pass is exactly right — the test-baseline contract override was
a genuine gate condition, not a style preference. READY-TO-DEPLOY on second pass is correctly
calibrated after suite completion. The coordinator's catching of the QA omission is the
campaign's highest-value gate action: it prevented an under-tested deploy from proceeding.
No severity inflation or deflation detected across either pass.

**Actionability (5):** First pass: actionable BLOCK with specific resolution path (run the two
named suites). Second pass: actionable GO with named pre-conditions confirmed, Method B
endorsed, post-deploy verification grounded in release manager's checklist. An operator
received a complete, executable deploy package from the coordinator's second pass.

**Substitution (5):** Canonical agent. GATE 5 N/A.

**Evidence (5):** First pass evidence: named suites (test_pz_*.py = 221, test_carrier_*.py = 412),
named contract reference, named reason QA rationalization fails (unconditional language).
Second pass evidence: named counts (PZ 221 pass, carrier 420 vs 412 threshold), named
pre-existing failure (Issue #613), named deploy method (Method B single-file robocopy).
Both passes are independently verifiable. The pre-existing failure tracking by issue number
is the strongest evidence item in the second pass.

**Environment (4):** The coordinator's two-pass structure is inherently environment-anchored:
the first pass was issued against the initial QA report (identifying its incompleteness as a
gate condition), and the second pass was issued after full suites were run against C:\PZ-verify.
The coordinator disclosed the deploy target (main commit 03ffce9) and production baseline
(e4d96b5) in the campaign-level framing. Score 4 (not 5): campaign-level disclosure present;
verdict block does not self-state the examined path/SHA per Issue #597 standard.

---

## Weak-verdict warnings

### deploy-qa-reviewer (ACCEPTABLE — 23/35)

**Failed dimensions:**

1. **Coverage (3/5):** Did not run the full PZ-221 and carrier-412 baseline suites required
   by the test-baseline contract. Ran golden harness (160/160) + focused audit_merge (27/27)
   only. The omitted suites are unconditionally required by contract, not contingent on
   impact-surface analysis.

2. **Severity (3/5):** Self-assessed the omission as "non-blocking" based on risk-surface
   reasoning ("change has no engine/calc surface"). The baseline contract language is
   unconditional; risk-surface reasoning does not override it. The coordinator correctly
   reclassified as BLOCK.

3. **Actionability (3/5):** The verdict created an incorrect gate signal ("non-blocking")
   that required coordinator override to correct. A properly calibrated verdict would have
   self-blocked: "suites not run → BLOCK per contract."

4. **Specificity (3/5):** Named omissions transparently (positive) but framed the
   rationalization as a risk assessment rather than a contract reading (negative). Specificity
   of the disposition logic was weak.

**Quoted excerpt supporting score:**
> QA returned CLEAR but with a self-described "non-blocking" flag that the FULL pytest suites
> (tests/test_pz_*.py=221, carrier=412) had NOT been run — only the golden harness (160/160)
> + focused audit_merge (27/27). It rationalized the omission as acceptable given the change
> had no engine/calc surface.

**Positive signal:** The agent disclosed the omission honestly rather than fabricating suite
completion. This transparency enabled the coordinator to catch it. Honesty about an omission
is better than a false-positive CLEAR, and the Coverage/Severity scores (3/5 rather than 1/5)
reflect that the partial coverage was real, just incomplete.

**Recommendation:** Do not re-dispatch for this campaign (deploy is complete). GATE 4 SCHEDULED
disposition applied (see above in agent section). The coordinator's BLOCK demonstrates the
system defense-in-depth functioning correctly: one agent's calibration gap was caught by the
integrating layer.

---

## Orchestrator process assessment

The campaign context surfaced three orchestrator-level process findings. Per RULE 2 mandate
(score the process, not just the agents), these are recorded here for completeness and
operator visibility.

**MISS 1 — Incomplete initial test suite execution (MEDIUM):**
The orchestrator initially ran golden harness (160) + focused tests (27) rather than the full
baseline suites required by `/deploy Step 4`. This forced the coordinator to BLOCK and required
a second full-suite run before the gate could proceed. The correct first-pass behavior: run
`tests/test_pz_*.py` + `tests/test_carrier_*.py` up front, per the baseline contract, before
dispatching the 7 agents. The QA agent's "non-blocking" rationalization reflected the
orchestrator's own initial framing — the orchestrator's test selection influenced the agent's
reporting. Root cause: orchestrator misjudged the baseline requirement as impact-scoped rather
than contract-unconditional. Same error as the QA agent, at the orchestrator level.

**MISS 2 — PYCACHE RULE omitted from deploy commands (LOW-MEDIUM):**
The operator deploy commands did not include the mandatory step to clear all `__pycache__`
directories recursively before PZService restart. This was not caught by any of the 7 agents
(none flagged the pycache omission in their verdicts — a minor gap in release-manager coverage
for this campaign). The omission did not bite: the deployed .py file mtime (15:02) was newer
than the cached .pyc mtime (14:06), so Python recompiled automatically. However, relying on
mtime-based recompile is not a substitute for the mandatory pycache clear — an edge case
with simultaneous edits or cached pre-deploy bytecode could produce stale execution silently.
The PYCACHE RULE must be included in all future deploy command blocks.

**POSITIVE — Stale PROJECT_STATE correctly detected and reframed deploy (COMMENDABLE):**
The orchestrator's on-disk probe discovered that the "last verified prod SHA = e4d96b5" in
PROJECT_STATE was stale — production was actually already at a later commit (#648 had deployed
after the e4d96b5 record was written). This discovery correctly reframed the deploy from a
potentially risky tree-wide sync (which would have swept many intermediate-commit files) to a
safe single-file deploy (Method B). This is the system working correctly: the orchestrator
checked ground truth rather than trusting stale state, and the corrected framing enabled the
minimal-blast-radius deploy path.

**POSITIVE — Post-deploy wfirma_export=None diagnosed and resolved correctly (COMMENDABLE):**
The preservation smoke initially showed wfirma_export=None (wiped by pre-restart regenerations
running old code before the fix was deployed). The orchestrator correctly diagnosed the root
cause read-only (old code ran before deploy completed), confirmed PR #652 was active
(PRESERVED_KEYS True, no stale-pyc shadow), and restored the pointer via reconcile_from_timeline.
The diagnosis was honest, the resolution was targeted, and the fix did not involve workarounds
that masked the underlying state.

---

## Repeated failure hints

Reading the 5 most recent campaign scorecards (non-self-eval):

1. **2026-06-17-pr633-cif-ui-resolved-authority.md** — 3 implementation agents, all EXEMPLARY
   (28-29). Environment 2/5 across all three agents (highest-risk environment disclosure gap
   in recent history — V1 file, dual-path risk).

2. **2026-06-17-pr632-ocr-fallback-deploy-gate.md** — 7 deploy agents, all EXEMPLARY (30-33).
   Environment 3/5 across all specialist agents. deploy-qa-reviewer EXEMPLARY (33) — 5/5
   Evidence with pre-existing CSV failure proven by five independent evidence threads.

3. **2026-06-17-adr029-e4d96b5-deploy-gate.md** — 7 deploy agents, all EXEMPLARY (30-34).
   deploy-release-manager factual error (storage directory) Severity 3/5; GATE 4 SCHEDULED.
   deploy-qa-reviewer EXEMPLARY (32); deploy-lead-coordinator EXEMPLARY (34).

4. **2026-06-16-pr627-cif-tristate-resolver.md** — 3 implementation agents, all EXEMPLARY
   (33-34). First test-coverage-reviewer appearance since cn-hsn-false-block; Severity 4/5
   (improvement from prior 1/5 cn-hsn inflation incident).

5. **2026-06-16-pr621-inbox-evidence-panel-e3b.md** (approximate position) — solo verifier
   ACCEPTABLE; GATE 5 substitution-honesty gap; GATE 4 SCHEDULED dispositions.

**deploy-qa-reviewer pattern check (past 4 appearances):**
- 2026-06-17 PR #632: EXEMPLARY (33) — best-in-campaign evidence, pre-existing failure proof
- 2026-06-17 ADR-029 gate: EXEMPLARY (32) — routes_upload gap advisory (GATE 4 SCHEDULED)
- 2026-06-16 PR #625-626-627: EXEMPLARY (30) — within range
- 2026-06-18 PR #652 (THIS): ACCEPTABLE (23) — first sub-EXEMPLARY in 4 appearances

This is the agent's first ACCEPTABLE verdict in the 5-scorecard window. The REPEATED-WEAK
threshold requires ≥2 NEEDS-TUNING or UNRELIABLE appearances in 6 runs. ACCEPTABLE (23) on
a single campaign does not meet this threshold. However, the error type — overriding contract
language with risk-surface reasoning — is a genuine safety risk for a deploy gate agent. The
SCHEDULED prompt-level fix (make contract reference explicit) is the correct first response.
Monitor next two appearances.

**deploy-release-manager pattern check:**
- 2026-06-17 ADR-029: EXEMPLARY (30) — Severity 3/5 for false storage-directory claim (GATE 4 SCHEDULED)
- 2026-06-18 PR #652 (THIS): EXEMPLARY (33) — correct Method B recommendation, correct rollback topology
This campaign shows strong recovery from the ADR-029 factual error. No REPEATED-WEAK concern.

**No REPEATED-WEAK flags generated.** No agent meets the ≥2 NEEDS-TUNING or UNRELIABLE in 6
runs threshold. The QA reviewer's ACCEPTABLE on this campaign is the first sub-EXEMPLARY
appearance in the current 5-scorecard window.

---

## RULE 5 self-evaluation cadence check

**Most recent self-eval:** `C:\PZ-verify\.claude\memory\scorecards\self-eval-2026-06-16.md`
**Self-eval date:** 2026-06-16
**Today:** 2026-06-18
**Calendar days elapsed:** 2 days
**7-day threshold reached:** NO (2 < 7; threshold would be reached 2026-06-23)
**SELF-DEGRADATION DETECTED in self-eval-2026-06-16.md:** NO — concluded EXEMPLARY (30/35),
  recovery from prior 2026-06-15 SELF-DEGRADATION confirmed, no new degradation detected.
**3rd-run counter active:** NO (SELF-DEGRADATION cleared in 2026-06-16 self-eval; counter
  does not begin)

**Self-evaluation: SKIPPED — not triggered.**

**Context note per task brief:** The 7-day threshold from the most recent self-eval
(2026-06-16) falls on 2026-06-23, not 2026-06-20 as the brief estimated (which counted
from an earlier self-eval date). The 2026-06-16 self-eval is the most recent in C:\PZ-verify
(self-eval-2026-06-16.md exists and post-dates self-eval-2026-06-13.md). Correct next due
date: 2026-06-23.

---

## Campaign quality summary

**Campaign-level verdict:** EXEMPLARY with one ACCEPTABLE (QA) caught correctly by coordinator

**7-agent gate system performance — key quality signal:** The coordinator's BLOCK on first pass
is the strongest possible evidence that the 7-agent gate functions as designed. Six specialist
agents returned clean CLEAR verdicts; the QA agent returned a partial verdict with an incorrect
"non-blocking" self-assessment; the coordinator identified the gap, issued a precise BLOCK
naming the exact missing suites, and required resolution before GO. The BLOCK was not a
false positive — the missing suites are a genuine gate requirement. The subsequent GO after
full suite completion is the correct outcome. This is the gate system catching a real omission
and requiring remediation before proceeding.

**Highest-performing agents:** deploy-backend-impact-reviewer and deploy-release-manager (33/35)
for their thorough consumer analysis and correct production topology characterization
respectively. deploy-lead-coordinator (34/35) for the two-pass BLOCK/GO structure.

**Structural quality signals:**
1. **Method B identification by git-diff-reviewer:** The cumulative-delta / single-file deploy
   insight converted a potentially high-blast-radius deploy to a minimal-risk one. This
   requires the reviewer to understand the deployment model, not just the diff.

2. **Production topology awareness by release-manager:** Correctly identifying that production
   is robocopy-synced (not git-managed) and that rollback is therefore file-restore (not git
   reset) reflects domain-specific release management knowledge. This is the lesson from prior
   campaigns (where robocopy-vs-git confusion has appeared).

3. **Consumer-pattern analysis by backend-impact-reviewer:** Confirming all callers use
   `.get(...)` with defaults rather than hardcoding PRESERVED_KEYS assumptions is the
   behavioral correctness check that makes this change safe. The agent did not just classify
   the change as small — it verified that smallness translates to safety at the call sites.

**Systemic debt remaining:**
1. **Issue #597** (agent self-disclosure of working tree and SHA in verdict blocks) — Environment
   dimension at 3/5 for all specialist agents. No new filing needed; standing governance item.
2. **deploy-qa-reviewer prompt fix** — GATE 4 SCHEDULED (see agent section). Make contract
   reference explicit in prompt to prevent risk-surface rationalization overriding contract
   language.
3. **PYCACHE RULE in operator deploy commands** — orchestrator miss (not agent miss). Release
   manager did not flag the omission in this campaign. Consider adding a pycache-clear step
   to deploy-release-manager's mandatory checklist in the prompt template.

---

## GATE 4 dispositions generated by this scorecard

1. **deploy-qa-reviewer contract-rationalization gap** — SCHEDULED: Add explicit baseline-
   contract reference to deploy-qa-reviewer prompt template: "PZ-221 and carrier-412 baselines
   are unconditional per `.claude/contracts/test-baseline.md`; risk-surface reasoning does NOT
   override contract language; if either full suite is not run, verdict MUST be BLOCK." Target:
   next deploy-gate prompt review session.

2. **PYCACHE RULE in deploy-release-manager checklist** — SCHEDULED: Add mandatory pycache-
   clear step (`Get-ChildItem -Recurse __pycache__ | Remove-Item -Recurse -Force`) to
   deploy-release-manager's post-robocopy / pre-restart checklist in its prompt template.
   Current scope: agent did not flag its own absence in this campaign. Target: next deploy-gate
   prompt review session (can be batched with item 1).
