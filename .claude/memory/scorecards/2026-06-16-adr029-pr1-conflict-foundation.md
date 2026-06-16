# Agent Performance Scorecard — ADR-029 PR-1 Conflict Detection Foundation

**Date:** 2026-06-16
**Observer:** agent-performance-observer (RULE 2 auto-fire)
**Campaign:** ADR-029 §3 Conflict Detection Foundation — PR #626
**PR:** #626 opened (base: main). Commit c25af76. 8 files, 1919 insertions.
**Branch:** fix/cn-hsn-mixed-metal-false-block (stacked on PR-0 / PR #624)
**Objective:** Implement typed conflict-detection backend extension of ADR-025 soft-validation.
  Flags all OFF by default. Pure/local detection. No wFirma I/O (ADR-021 Invariant 7). No UI.
**Agents evaluated:** 2 (integration-boundary; orchestrator as implementer/verifier)
**Working tree note:** Session executed from C:\Users\Super Fashion\PZ APP (scratch clone).
  PATH GUARD applies to verification reads and git operations; implementation work on local
  branch is expected from the session worktree.

---

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| integration-boundary | 4 | 4 | 3 | 4 | 5 | 4 | 3 | 27 | ACCEPTABLE |
| orchestrator (implementer + verifier) | 4 | 4 | 4 | 4 | 3 | 4 | 3 | 26 | ACCEPTABLE |

---

## Scoring rationale per agent

### integration-boundary (27 — ACCEPTABLE)

#### 1. Specificity (4/5)

**Assessment: STRONG**

The GAP-1 (BROKEN-LINK) finding was specific and actionable: the customer lookup used
`int(cid)` to coerce a contractor ID before a SQLite query. The finding named the function
affected (`_resolve_customer_for_conflicts`), the data-type mismatch (int vs TEXT-affinity
column), and the downstream consequence (V3 currency_vs_customer_default and V8
service_charge_defaults_changed silently suppressed when a non-numeric contractor id is
provided). The fix path was clear and named (change `int(cid)` to `str(cid)`).

**Deduction (−1):** The verdict block was described as finding "always returns (None, None)"
for numeric contractor IDs — this claim was overstated (see Severity section). The
overstated scope reduction from "always returns (None, None)" to "returns (None, None) for
non-numeric IDs only" required orchestrator empirical correction. A fully specific finding
would have distinguished the two cases before asserting the breakage scope.

#### 2. Coverage (4/5)

**Assessment: STRONG**

Integration-boundary reviewed the boundary surfaces relevant to its scope for this PR:
the customer-lookup integration point (wFirma contractor ID → proforma_conflict_detector),
the flag-gating of the three new routes (CONFLICT_DETECTION_ENABLED guard), and the wFirma-
free claim for `proforma_conflict_detector.py` (no sqlite3 / requests / httpx imports
verified). The agent correctly identified the critical type-coercion gap at the
frontend-to-backend boundary — the primary integration seam in this PR.

**Deduction (−1):** Coverage of Invariant 4 (master_audit write on every conflict store
write) was not confirmed as part of the verdict block. The `proforma_conflict_db.py` write
path involves `has_open_blocking_conflict` and idempotent upsert; the master_audit-on-every-
write constraint (ADR-021 Invariant 4) is a backend-integrity boundary condition that
integration-boundary is well-positioned to verify. No explicit statement that this path was
inspected.

#### 3. Severity (3/5)

**Assessment: ACCEPTABLE — calibration error on scope**

The GAP-1 finding was correctly rated HIGH by the agent (a bug that silently suppresses
conflict validators V3 and V8, returning `customer_resolved:false` with no error surfaced to
the caller, is a real defect). However, the finding's stated effect — "always returns
(None, None)" — was overstated. SQLite TEXT-affinity coerces numeric-bound integers to
match TEXT-stored contractor IDs, so numeric contractor IDs did in fact resolve correctly
through the original `int(cid)` path. The breakage was real but narrower than stated:
only non-numeric contractor IDs triggered the ValueError → defensive except → (None, None)
path.

The fix (str(cid)) is still correct and aligns with the type contract of all 11 other
call sites. However, overstating the breakage scope as "always fails" rather than "fails on
non-numeric IDs" inflated the functional impact. This is a calibration error in the severity
justification, not a false finding. Severity of the finding (HIGH) may still be warranted
for a type mismatch that silently swallows exceptions; but the justification required
empirical correction by the orchestrator.

**Scoring note:** 3/5 reflects "correct finding, wrong magnitude statement" rather than
an inflated or fabricated severity. The finding was real; the scope was overstated.

#### 4. Actionability (4/5)

**Assessment: STRONG**

The fix path was unambiguous: `int(cid)` → `str(cid)` in `_resolve_customer_for_conflicts`.
The regression pin was specific: `test_scan_resolves_customer_and_emits_v3_currency_conflict`
with a non-numeric contractor ID, which would fail loudly on regression. The finding
translated directly to a one-line fix that the orchestrator executed and confirmed. This is
the operational definition of an actionable integration finding.

**Deduction (−1):** The actionability of the scope clarification — what to do when the
"always returns (None, None)" claim turned out to be overstated — was not addressed in the
verdict block. A complete actionable finding would have included the evidence basis for the
scope claim (e.g., "grep/read of SQLite TEXT-affinity for cid column") so the orchestrator
could independently verify it rather than needing to discover the overstatement empirically.

#### 5. Substitution honesty (5/5)

**Assessment: EXEMPLARY**

No substitution. Integration-boundary is the named and registered agent; it was dispatched
directly. GATE 5 compliant.

#### 6. Evidence quality (4/5)

**Assessment: STRONG**

The agent cited the specific function (`_resolve_customer_for_conflicts`), the type operation
(`int(cid)`), the import pattern (`proforma_conflict_detector.py` wFirma-free verified), and
the downstream validators affected (V3, V8). These are verifiable claims against the code.

**Deduction (−1):** The claim that numeric contractor IDs "always" trigger the ValueError →
(None, None) path was stated without SQLite TEXT-affinity evidence to support the scope.
A grep of the schema definition for the contractor id column, or a note on SQLite coercion
behavior, would have grounded the scope claim before it was corrected by orchestrator
empirical testing. The absence of that evidence is what allowed the scope overstatement to
persist until orchestrator testing.

#### 7. Environment honesty (3/5)

**Assessment: ACCEPTABLE**

Integration-boundary disclosed its inspect-only role (Read/Grep/Glob; Bash removed per repo-
canonical install). The verdict block does not explicitly state the working tree path examined
or the commit SHA at time of inspection. For this campaign, the implementation was on
`fix/cn-hsn-mixed-metal-false-block` at c25af76 — but the agent's verdict does not self-
state which tree or commit it read. The campaign context supplies this by implication, but
per Environment dimension scoring, full disclosure earns 5/5 and missing disclosure that
had no masked failure earns 3/5. No failure was masked by the missing path/SHA statement,
but the disclosure was absent.

---

### orchestrator (implementer + verifier) (26 — ACCEPTABLE)

**Framing note:** This campaign did not involve a separate QA-reviewer, deploy-reviewer, or
test-coverage-reviewer agent; the orchestrator both implemented and verified the work. The
scorecard scores the orchestrator's self-conducted verification against the 7 dimensions,
consistent with the precedent from the E3b scorecard (2026-06-16-pr621).

#### 1. Specificity (4/5)

**Assessment: STRONG**

The implementation record names specific files (routes_proforma.py, core/config.py,
services/wfirma_capabilities.py, services/proforma_conflict_detector.py,
services/proforma_conflict_db.py, 3 new test modules), specific validators (V3, V4, V5, V8),
specific flags (4 in core/config.py, all default OFF except conflict_ui_mode="panel"), and
specific test counts (65 tests in 3 new suites; 161 passed in the targeted run; 63 passed /
1 skipped in pre-commit smoke). The wFirma-free claim for proforma_conflict_detector.py is
supported by a specific import-level check (no sqlite3/requests/httpx). The one-char fix for
GAP-1 (int→str) is named with exact function scope.

**Deduction (−1):** The earlier `-k proforma` run showed F/E markers. The campaign context
explains these as artifacts of a killed/contended run (not reproducible deterministically;
logically impossible from a one-char change). This is plausible but the explanation rests on
logical inference rather than a deterministic re-run that cleaned the F/E markers. Specificity
would be stronger with a confirmed re-run showing zero failures in the proforma suite.

#### 2. Coverage (4/5)

**Assessment: STRONG**

The orchestrator covered the stated implementation scope thoroughly: 4 flag-gated routes,
pure detector (V3/V4/V5/V8), conflict store (idempotent upsert, terminal-row protection,
master_audit-on-write per Invariant 4), 65 tests across 3 suites. The GATE 2 check was
performed (2 impl PRs + 1 docs = within limit). The GAP-1 fix was discovered via
integration-boundary, incorporated, and pinned with a regression test.

**Deduction (−1):** V1/V2/V6/V7 validators are intentionally deferred to PR-2 (enum
registered, detectors not wired). This is correct per the PR scope. However, the coverage
record does not show an explicit check that the enum registration for deferred validators
does not surface dead code paths through the currently-wired route surface (i.e., that a
call to the scan route with a shipment where V1/V2 would fire silently returns an empty
result rather than an error or a stale enum reference). This is a minor gap in the
completeness of the "wired vs deferred" boundary verification.

#### 3. Severity (4/5)

**Assessment: STRONG**

The orchestrator correctly diagnosed GAP-1 (the int→str type coercion bug) as a real defect
requiring a fix, despite the overstated scope from integration-boundary. The empirical
correction (SQLite TEXT-affinity means numeric IDs still resolved) is a severity-calibration
win: the bug is real, the fix is correct, but the practical blast radius is narrower than
"always broken." Reporting this accurately (correct finding, overstated by the reviewing
agent, empirically narrowed) is appropriate severity calibration.

**Deduction (−1):** The F/E marker incident on the `-k proforma` run was treated as "not
reproducible deterministically; logically impossible from a one-char change." While this
is likely correct, treating test failures as artifacts without a confirmed clean re-run risks
understating the severity of a real test isolation issue. The logic is sound but the
evidence-without-rerun path is a mild severity gap.

#### 4. Actionability (4/5)

**Assessment: STRONG**

PR #626 is open with all stated deliverables. The regression test for GAP-1 is named and
pinned. The deferred validator scope (V1/V2/V6/V7 → PR-2) is explicitly stated with the
enum-registration-only contract. GATE 2 compliance is confirmed. An operator reading the
task context could proceed directly to GATE 1 review.

**Deduction (−1):** The operator has no explicit closure record for the F/E marker incident
(either a confirmed re-run showing clean, or a diagnosis naming the contended process). The
actionable recommendation — "re-run the proforma suite clean to close this" — is implicit
in the campaign context but not stated as a discrete action item.

#### 5. Substitution honesty (3/5)

**Assessment: ACCEPTABLE — partial disclosure**

Integration-boundary was dispatched for integration review. However, for a PR of this scope
(8 files, 1919 insertions, 3 new service modules, 3 new test suites), the standard GATE 1
preconditions include named subagents for multiple review surfaces. The campaign context
names integration-boundary as the only participating reviewer. No reviewer-challenge,
backend-safety-reviewer, or test-coverage-reviewer is mentioned as dispatched or explicitly
declined/waived.

This is not a GATE 5 substitution failure in the same class as E3b (where Lesson F makes
reviewer-challenge a mandatory auto-fire for V2 frontend PRs). ADR-029 PR-1 is a backend-
only PR with no UI surface, so Lesson F's mandatory reviewer-challenge for V2 pages does not
directly apply. However, GATE 1's general requirement ("Every named subagent has returned a
verdict block or explicitly failed dispatch with disclosure") implies that the set of named
subagents for a backend PR of this complexity should be explicitly stated, and any omissions
should be disclosed.

The campaign context does not record a reviewer-challenge waiver, a backend-safety-reviewer
verdict, or a test-coverage-reviewer verdict. These omissions are not flagged as omissions
within the campaign itself — they surface here as a Substitution dimension gap.

**Score (3):** Partial credit for dispatching the correct integration-boundary agent and
for the no-UI / backend-only scoping that reduces (but does not eliminate) the expected
reviewer surface. Full credit requires either dispatching the full named reviewer surface
or explicitly disclosing each omission with a capability-equivalence statement.

#### 6. Evidence quality (4/5)

**Assessment: STRONG**

Concrete counts throughout: 65 tests in 3 new suites, 161 passed / 0 failed in the
targeted run, 63 / 1 skipped in pre-commit smoke. GAP-1 fix is verifiable (one-char change,
function name, regression test named). Import-level verification for wFirma-free claim
(no sqlite3/requests/httpx in proforma_conflict_detector.py). Terminal-row protection and
master_audit-on-every-write stated as implemented in proforma_conflict_db.py.

**Deduction (−1):** The F/E marker incident on the earlier `-k proforma` run is described
but not resolved with a clean re-run artifact. The proforma suite clean-run evidence is
missing. The 161-passed count comes from a targeted explicit-path run across 7 named suites;
a full proforma suite run to clear the F/E markers would be the gold-standard evidence close.

#### 7. Environment honesty (3/5)

**Assessment: ACCEPTABLE**

The implementation branch is `fix/cn-hsn-mixed-metal-false-block`. The commit SHA is
c25af76 for the conflict-foundation changes. PR #626 is open with base main. These facts
are stated. The working tree for implementation is the scratch clone (C:\Users\Super Fashion\
PZ APP), which is the expected session worktree for implementation work.

**Deduction (−2):** Two environment disclosure gaps:

1. The campaign context does not explicitly state "implementation performed on
   C:\Users\Super Fashion\PZ APP at commit c25af76" — the SHA is implied from PR metadata
   but not self-stated as the worktree anchor.

2. More significantly: the campaign does not record whether C:\PZ-verify was consulted for
   any cross-reference reads during the implementation (e.g., verifying ADR-021 Invariant 4
   wording, confirming 11 other call sites for the str(cid) pattern). If those reads targeted
   the scratch clone rather than C:\PZ-verify, PATH GUARD may have been bypassed for
   verification-class reads. The campaign context is silent on this distinction.

Full disclosure earns 5/5; absent disclosure with no confirmed masked failure earns 3/5.

---

## Weak-verdict warnings

### integration-boundary (ACCEPTABLE — 27/35)

**Weak dimensions:** Severity (3), Evidence (4) — the evidence dimension is on the boundary
but is flagged because the single evidentiary gap (missing SQLite TEXT-affinity grounding)
is what caused the severity overstatement.

**Primary issue — overstated scope in the severity justification:**

The GAP-1 finding was real and actionable. The fix is correct. However, the claim that the
bug caused `_resolve_customer_for_conflicts` to "always return (None, None)" was factually
overstated. SQLite TEXT-affinity coerces numeric-bound ints, so numeric contractor IDs
(the common case) did resolve correctly. The actual breakage domain was non-numeric
contractor IDs only.

The practical consequence of this overstatement: the orchestrator had to run empirical tests
to verify the scope rather than relying on the agent's claim. In a production-critical path,
an overstated scope would lead to mis-estimating the blast radius of the defect. Severity
calibration requires that the evidence basis for the scope claim be explicit in the verdict
block.

**Verdict excerpt supporting the score:**

From the task context: "the agent's 'always returns (None, None)' claim was OVERSTATED —
empirically established SQLite TEXT-affinity coerces numeric bound ints so numeric ids still
matched."

**Recommendation:** Do not re-dispatch for this campaign (the finding was resolved inline
and the fix is merged). For future campaigns: when integration-boundary makes a scope claim
about failure domains (e.g., "always fails", "never resolves"), the verdict block must
include the evidence basis for that scope — not just the mechanism, but the proof of
universality or specificity. A grep of the schema definition or a note on the data type
affinity in the relevant storage layer would satisfy this requirement.

**GATE 4 disposition:**
- **DISPOSITION: SCHEDULED** — Add to integration-boundary prompt guidance: scope claims
  (especially "always" / "never" failure domain assertions) must be grounded in schema or
  type evidence, not inferred from exception behavior alone. Target: next prompt-tuning
  session for integration-boundary.

### orchestrator (implementer + verifier) (ACCEPTABLE — 26/35)

**Weak dimensions:** Substitution honesty (3), Environment (3).

**Primary issue — incomplete reviewer surface disclosure for a complex backend PR:**

PR #626 introduced 3 new service modules, 3 new test suites, and 1919 insertions across
8 files. The campaign dispatched only integration-boundary as a named reviewer. No
backend-safety-reviewer or test-coverage-reviewer verdict blocks appear in the campaign
record, and no explicit waivers or capability-equivalence statements for their absence are
recorded. This is not a Lesson F mandatory-auto-fire failure (no V2 frontend surface), but
GATE 1's "every named subagent" language implies the reviewer surface should be stated.

**Secondary issue — F/E marker incident without clean re-run:**

The earlier `-k proforma` run showed failure/error markers. The campaign context explains
these away as a killed/contended run artifact. This is likely correct but is an inference,
not evidence. A confirmed clean re-run would close this gap.

**Recommendation:** For the next ADR-029 PR (PR-2, V1/V2/V6/V7 validators):
1. Explicitly name the expected reviewer surface before implementation begins (integration-
   boundary + backend-safety-reviewer at minimum for a new-service PR).
2. If reviewers are omitted, record the waiver and capability-equivalence statement.
3. After any test run showing F/E markers, close with a confirmed clean re-run before
   recording the test verdict.

**GATE 4 disposition:**
- **DISPOSITION: SCHEDULED** — Apply to ADR-029 PR-2: dispatch backend-safety-reviewer in
  addition to integration-boundary for any PR introducing new service modules. Record
  explicit reviewer surface and waivers in the campaign pre-flight.

---

## Repeated failure hints

**5 most recent campaign scorecards reviewed:**
1. 2026-06-16: `2026-06-16-pr621-inbox-evidence-panel-e3b.md` — orchestrator (solo) ACCEPTABLE (25)
2. 2026-06-16: `2026-06-16-pr614-inbox-evidence-e3a.md` — backend-safety-reviewer NEEDS-TUNING (23), reviewer-challenge EXEMPLARY (32)
3. 2026-06-15: `2026-06-15-deploy-gate-d37316e-wfirma-grammar.md` — deploy-lead-coordinator ACCEPTABLE (27); 6 others EXEMPLARY
4. 2026-06-15: `2026-06-15-pr522-merge-gate-wfirma-grammar.md` — 3 agents, all EXEMPLARY
5. 2026-06-14: `2026-06-14-pr585-529-price-source-authority.md` — all agents EXEMPLARY

**integration-boundary:** No prior appearances in the 5 most recent campaign scorecards.
First scored instance in this window. No REPEATED-WEAK flag applicable.

**orchestrator (implementer/solo-verifier):** Second ACCEPTABLE verdict in the 5-scorecard
window (E3b: 25/35 ACCEPTABLE; this: 26/35 ACCEPTABLE). The pattern in both cases is
Substitution honesty (missing prospective disclosure for omitted reviewers) and Environment
honesty (working tree path not self-stated). However, the two campaigns involve different
execution contexts (E3b = V2 frontend SOLO; this = backend implementation with one named
reviewer). The shared root is the orchestrator's reviewer-surface disclosure practice.
This is not yet a REPEATED-WEAK flag (threshold: NEEDS-TUNING or UNRELIABLE in ≥2 of 6;
both scores are ACCEPTABLE) but the pattern warrants monitoring.

**backend-safety-reviewer:** NEEDS-TUNING in E3a (23/35). Single instance. SCHEDULED
disposition recorded in E3a scorecard. No REPEATED-WEAK flag (one occurrence).

**No REPEATED-WEAK flags triggered** for any agent in this campaign.

**Environment disclosure gap (systemic):** The self-eval-2026-06-15.md flagged
SELF-DEGRADATION DETECTED on the Environment honesty dimension — noting that the repeated
Environment gap across 15+ scorecards had not been escalated to GATE 4. This was
dispositioned as GitHub Issue #597 (ISSUE — governance, follow-up). This scorecard scores
both agents at 3/5 on Environment, consistent with the "absent disclosure, no confirmed
masked failure" standard. Issue #597 is the standing GATE 4 disposition for this pattern.

---

## Self-evaluation (triggered — 3rd campaign scorecard since SELF-DEGRADATION flag)

**Trigger:** SELF-DEGRADATION DETECTED in `self-eval-2026-06-15.md`. This is the 3rd
campaign scorecard since that flag (E3a = run 1, E3b = run 2, this ADR-029 = run 3).
Trigger condition met.

**5 campaign scorecards evaluated:**
1. 2026-06-16: `2026-06-16-pr621-inbox-evidence-panel-e3b.md`
2. 2026-06-16: `2026-06-16-pr614-inbox-evidence-e3a.md`
3. 2026-06-15: `2026-06-15-deploy-gate-d37316e-wfirma-grammar.md`
4. 2026-06-15: `2026-06-15-pr522-merge-gate-wfirma-grammar.md`
5. 2026-06-14: `2026-06-14-pr585-529-price-source-authority.md`

### Self-scoring (6 dimensions over 5 runs)

**1. Scoring calibration consistency**
Scores across these 5 campaigns range from NEEDS-TUNING (backend-safety-reviewer, E3a: 23)
through ACCEPTABLE (orchestrator E3b: 25; deploy-lead E3a deploy: 27) to EXEMPLARY (reviewer-
challenge E3a: 32). The distribution is plausible — not uniformly high, not uniformly low.
The E3b orchestrator-solo verdict (ACCEPTABLE, not EXEMPLARY despite thorough implementation)
reflects disciplined calibration: implementation quality and governance quality are scored
separately, and governance gaps correctly reduce the verdict. No inflation detected.
**Self-score: 4/5**

**2. Pattern detection accuracy**
Correctly identified: orchestrator Substitution honesty gap across E3b and now ADR-029
(two consecutive ACCEPTABLE on same dimension). Correctly maintained Environment disclosure
pattern tracking (Issue #597 as standing disposition). Correctly distinguished E3a reviewer-
challenge EXEMPLARY from backend-safety-reviewer NEEDS-TUNING in the same campaign.
Weakness: the orchestrator's F/E marker incident in ADR-029 was noted but no explicit
pattern check was made against prior campaigns for similar "non-deterministic failure
markers explained away without re-run" patterns.
**Self-score: 4/5**

**3. Evidence quality verification**
The self-eval-2026-06-15 flagged that some scorecards rely on campaign summaries rather than
raw agent verdict excerpts. Improvement observed: the E3b scorecard directly quoted the
"EXECUTION MODEL: SOLO" language from the campaign context. This ADR-029 scorecard directly
quotes the "always returns (None, None)" claim from the task context. The trend toward direct
quotation is measurable.
Remaining gap: the E3a backend-safety-reviewer NEEDS-TUNING verdict was scored from campaign
context rather than a direct verdict block transcript. Direct verdict quotes remain
inconsistently applied.
**Self-score: 3/5**

**4. Actionability of recommendations**
GATE 4 dispositions issued in E3b (2 × SCHEDULED) and in this scorecard (2 × SCHEDULED).
All four dispositions are specific: named agent, named finding, named next action, named
target campaign. The Environment disclosure gap received Issue disposition (Issue #597).
The self-eval-2026-06-15 flagged "weak at providing concrete remediation steps" — some
improvement observed: this scorecard's SCHEDULED dispositions are more specific than prior
pattern-noting without resolution paths.
**Self-score: 4/5**

**5. Verdict quality translation**
The ACCEPTABLE verdicts (orchestrator E3b: 25; orchestrator ADR-029: 26) correctly
distinguish governance-discipline gaps from implementation quality. Operators reading
these verdicts can distinguish "good code, incomplete review surface" from "unreliable
agent." The NEEDS-TUNING verdict on backend-safety-reviewer (E3a: 23) correctly surfaces
the working-tree PATH GUARD violation (Environment: 2/5) as the most serious issue.
**Self-score: 4/5**

**6. Cadence and self-blind-spot detection**
The SELF-DEGRADATION trigger fired correctly (3rd run since the 2026-06-15 flag). The
counter was tracked through E3b (run 2) and triggered here at run 3. The Environment
honesty governance gap (Issue #597) was correctly carried forward as standing context.
Improvement needed: the 2026-06-13 self-eval scored all 6 dimensions at 5/5 ("EXEMPLARY"),
which in retrospect appears inflated given that the 2026-06-15 self-eval immediately
identified significant gaps on the same dimension set. The calibration drift from 5/5 to
the more honest 3-4/5 range visible in the 2026-06-15 self-eval is the correct direction.
**Self-score: 4/5**

### Overall self-assessment

**Total self-score: 23/30 (ACCEPTABLE)**

**Calibration trajectory:** RECOVERING from the SELF-DEGRADATION flag. The 2026-06-15
self-eval correctly identified the Environment-disclosure governance gap and issued a
GATE 4 disposition. This scorecard follows through consistently — Environment scores
remain at 3/5 (absent disclosure, no masked failure), issue #597 is cited as standing
context, and no re-inflation of the score occurred despite potentially favorable surface
readings on well-structured campaigns.

**Remaining gaps from 2026-06-15 remediation plan:**

1. **Direct agent verdict quotes** — partially improved (direct quotes in E3b and ADR-029);
   not yet consistent across all agents in multi-agent campaigns.

2. **NEEDS-TUNING threshold for systemic patterns** — correctly maintained (no systemic
   pattern reached REPEATED-WEAK threshold in recent campaigns; Environment disclosure
   correctly managed via standing Issue #597 rather than re-escalating each campaign).

3. **Concrete remediation steps** — improved in SCHEDULED dispositions (more specific than
   prior versions); not yet at the level of "here is the exact prompt change to make."

**No new SELF-DEGRADATION detected.** Scoring calibration is recovering appropriately.
Next self-eval due on 2026-06-23 (7 calendar days from 2026-06-16) OR at the 3rd campaign
scorecard after a future SELF-DEGRADATION flag, whichever comes first.

---

*Self-evaluation output appended to this scorecard per RULE 5 (SELF-DEGRADATION triggered
at 3rd run; self-eval written inline with the triggering campaign scorecard rather than as
a separate file, as the 5-campaign evidence set is co-located here).*

---

## Campaign quality summary

**Implementation quality:** HIGH. 8 files, 1919 insertions. 4 flag-gated routes (all OFF by
default). Pure detector with 4 wired validators (V3/V4/V5/V8). Conflict store with idempotent
upsert, terminal-row protection, and Invariant 4 compliance. 65 new tests. The GAP-1 finding
from integration-boundary was resolved inline with a correct fix and a pinned regression test.

**Review quality:** ACCEPTABLE. Integration-boundary produced a real, actionable finding
(GAP-1), correctly fixed before PR open. The severity scope was overstated but the fix is
correct. No backend-safety-reviewer or test-coverage-reviewer verdict blocks were produced
for a complex backend PR — this is the primary governance gap. GATE 1 preconditions include
test pass verdict (satisfied — 161/0) and forbidden-files check (not explicitly confirmed in
the campaign record, but scope is tight: 8 named files).

**ADR-021 Invariant 7 compliance (no wFirma I/O):** Claimed and grounded via import-level
check (no sqlite3/requests/httpx in proforma_conflict_detector.py). This is the right
verification approach for a "pure/local detection" invariant.

**GATE 2 compliance:** 2 impl PRs (#625, #626) + 1 docs (#624) = within 3-PR limit. Confirmed.

**PR status:** #626 open, base main. Ready for formal code review. The conflict-detection
foundation is backend-only with all flags OFF — zero production behavior change at merge.

---

**Agents scored:** 2
**EXEMPLARY:** none
**ACCEPTABLE:** integration-boundary (27), orchestrator (26)
**NEEDS-TUNING:** none
**UNRELIABLE:** none
**Repeated-weak flags:** none
**GATE 4 dispositions added by this scorecard:** 2 (both SCHEDULED)
**Self-evaluation:** performed (3rd run since SELF-DEGRADATION flag on 2026-06-15)
**Self-eval result:** ACCEPTABLE (23/30) — recovering, no new degradation detected
