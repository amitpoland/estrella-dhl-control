# Agent Performance Scorecard — PR #692: Proforma Over-bill Guard Fail-Closed (4aa3d10)

**Date:** 2026-06-21
**Observer:** agent-performance-observer (RULE 2 auto-fire — 4 distinct named-agent invocations)
**Campaign:** "Proforma over-bill guard fail-closed"
**Branch:** fix/proforma-overbill-fail-closed
**Commit:** 4aa3d10 (based on origin/main 83885fd)
**PR:** #692 (https://github.com/amitpoland/estrella-dhl-control/pull/692)
**Scope:** Backend-only (no UI surface). Single file: `service/app/api/routes_proforma.py`.
  Fix: `_derive_draft_readiness` §5 (over-bill product_code guard, introduced in #686).
  On packing-read failure, the guard previously degraded silently to a warning (fail-OPEN),
  allowing approve/post/convert to proceed with `ready=True` on a genuinely over-billed draft.
  Fix = explicit packing read with fail-CLOSED precautionary blocker mirroring preview/VAT
  derivation failure behavior. Mid-campaign complication: origin/main advanced (#690 moved the
  resolver behind an exception-swallowing helper), requiring pivot from a one-line _add to an
  explicit-read-then-fail-closed pattern to avoid dead code and mislabeled infra failures.
**Outcome:** PR #692 opened. GATE 1 satisfied: all 4 subagent verdicts in; no HIGH/CRITICAL
  unresolved findings; MEDIUM + nits resolved inline; backend-only (GATE 6 N/A); regression
  tests run (15/15 fail-closed suite, fail-without-fix proven; 641+1 deploy-gate suite);
  A/B vs origin/main confirms strict subset (zero new failures). GATE 2: 3rd impl PR within limit.
**Agents evaluated:** 4

---

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| backend-safety-reviewer | 4 | 4 | 4 | 4 | 5 | 3 | 3 | 27 | ACCEPTABLE |
| security-write-action-reviewer | 4 | 4 | 4 | 4 | 5 | 3 | 3 | 27 | ACCEPTABLE |
| test-coverage-reviewer | 5 | 5 | 5 | 5 | 5 | 4 | 3 | 32 | EXEMPLARY |
| reviewer-challenge | 5 | 5 | 5 | 5 | 5 | 4 | 3 | 32 | EXEMPLARY |

---

## Scoring rationale per agent

### backend-safety-reviewer — 27 — ACCEPTABLE

**Specificity (4):** The initial-then-re-review structure demonstrates real scope engagement: the
agent reviewed the pre-#690 version (initial CLEAR), then reviewed the final post-#690 version
(re-review CLEAR). For a single-file backend fix, the re-review on the changed version is the
correct coverage behavior. The reported findings are substantive: traced the `ready = not blockers`
flow, confirmed no write/idempotency concern, confirmed happy-path byte-equivalence, and confirmed
that the explicit-read pattern closes the #690-reintroduced hole. "Happy-path byte-equivalence"
is a named behavioral claim (the fix does not change the pass-through behavior on non-failure paths)
that is independently verifiable. Minor deduction: the campaign summary reports these as conclusion-
level labels ("no write/idempotency concern", "byte-equivalence confirmed") rather than naming the
specific lines, function, or guard pattern in `routes_proforma.py` that were verified. For a
backend-safety-reviewer, the expected evidence form names the specific safety check that was
confirmed present (e.g., "fail-closed blocker appended at `_derive_draft_readiness` line N,
confirmed no write-path side-effect because function returns a dict, not a DB write").

**Coverage (4):** Covered the canonical backend safety surfaces for this change: no unsafe write
introduced, no idempotency gap, no new direct-audit write, and the critical context-specific
check — does the explicit-read pattern actually close the hole that #690 reintroduced (vs merely
adding dead code)? The #690-reintroduced-hole check is the highest-risk coverage dimension for
this campaign; the agent confirmed it. Minor gap: the verdict as reported does not confirm whether
the agent explicitly checked the `_normalise_X` Lesson A boundary-helper requirement or the
`audit_merge.PRESERVED_KEYS` contract — both are GATE 1 binding requirements per Lesson A for
builder/coordinator PRs modifying a readiness-derivation function. These dimensions are absent
from the reported verdict.

**Severity (4):** CLEAR is correctly calibrated for a backend fix that adds a precautionary blocker
without touching any write path, financial calculation, or audit-merge field. There are no
HIGH/CRITICAL findings in a change of this class (read-then-fail-closed pattern, no DB writes,
no external side effects). The re-review CLEAR after the #690-pivot correctly reflects that the
final implementation is a safe explicit-read pattern, not a misapplication of the original one-
line fix. Score 4 rather than 5: the severity calibration is aggregate ("CLEAR") rather than
dimension-graded — the verdict does not state explicitly that the fail-closed blocker's blast
radius is bounded (deny-and-retry, not permanent state corruption), which would be the severity-
precision that earns a 5.

**Actionability (4):** The initial CLEAR + re-review CLEAR structure is directly actionable as a
GATE 1 signal: the agent confirmed the final implementation is safe after the mid-campaign #690
pivot. This is non-trivial — the reviewer had to understand that the pre-#690 fix and the post-#690
fix address the same hole via different mechanisms and confirm that the final mechanism is
correct. Minor deduction: the verdict does not produce named post-deploy monitoring items (e.g.,
"confirm no spurious over-bill blocks appear on healthy drafts in first post-deploy batch") that
would be actionable for the operator's production smoke check.

**Substitution (5):** backend-safety-reviewer is canonical agent #2 in the AGENT_REGISTRY.
No substitution. GATE 5 N/A.

**Evidence (3):** The campaign summary records the agent's findings as conclusions: "traced
ready=not blockers flow", "confirmed no write/idempotency concern", "confirmed happy-path
byte-equivalence", "confirmed explicit-read closes the #690-reintroduced hole." These are
correct-and-credible claims, but none are grounded in a quoted code pattern, a file:line
reference from the agent's own verdict block, or a cited grep output. The happy-path byte-
equivalence claim in particular — asserting the fix does not change the non-failure code path —
is a testable claim that should be backed by a named pattern (e.g., "lines before the
new read block are unchanged per diff inspection"). Score 3: conclusion-level claims,
no artifact-level citations from the verdict block itself.

**Environment (3):** The campaign does not report which worktree path the agent operated from,
or which commit SHA was under inspection at the time of each pass (initial pass pre-#690 vs
re-review pass post-#690). Given that origin/main advanced mid-campaign, the environment
dimension is higher-criticality than usual: the re-review must have been on 4aa3d10
(the final commit after the explicit-read pivot), not on the pre-#690 intermediate state.
The verdict block does not self-disclose either the path or the commit SHA for either review
pass. Standard disclosure gap per Issue #597 applies, but the mid-campaign divergence increases
the significance of this gap compared to a static-commit review. Score 3/5: the claims are
coherent with the final outcome (PR opened, tests passing), but the environment disclosure is
absent for both passes.

---

### security-write-action-reviewer — 27 — ACCEPTABLE

**Specificity (4):** Traced all 3 write intents (approve 422 / post 400 / convert) and confirmed
they all gate on the same `blockers` list, confirmed audit trail (`readiness_blocked` field),
confirmed retry-safety, and weighed the DoS-vs-integrity tradeoff. Naming all 3 write intents
by their HTTP status codes (422/400 for approve and post respectively) and confirming they share
the same gate source is a concrete, independently verifiable specificity claim. The DoS-vs-
integrity analysis is the expected adversarial check for a fail-closed blocker: a fail-closed
packing read that miscategorizes infra failures as overbilling could create a DoS vector
(operators blocked from approve/post on healthy drafts during a DB hiccup). The agent weighed
this tradeoff explicitly, which is the correct scope for security-write-action-reviewer on this
change class. Minor deduction: the verdict as reported names the 3 intents at the label level
("approve/post/convert gating on blockers list") but does not cite the specific function names
or route handlers in `routes_proforma.py` where the gate was verified — the claim rests on the
campaign summary's characterization rather than a direct agent-quoted code reference.

**Coverage (4):** Covered the 3-intent enforcement scope, audit trail, retry-safety, and the
DoS-vs-integrity tradeoff. For this campaign, the critical security surface is: does the
fail-closed packing-read failure produce a blocker that gates all 3 downstream write actions
(not just approve, not just post)? The agent confirmed all 3, which is the correct full-scope
coverage for a write-action reviewer on a readiness-derivation fix. The agent reviewed
the pre-#690 implementation; other reviewers independently re-confirmed the 3-intent scope
on the final version — this coverage distribution is coherent and reasonable given the GATE 5
disclosure compliance (no silent substitution). Minor gap: the verdict as reported does not
confirm whether the agent checked the newly-introduced explicit packing read for its own
security surface — specifically, whether an exception from the packing DB read could leak
diagnostic information in the blocker message (information disclosure) or whether the
exception handler is appropriately generic.

**Severity (4):** CLEAR with DoS-vs-integrity tradeoff acknowledged is correctly calibrated.
The fail-closed pattern is a deliberate integrity-over-availability choice; the agent correctly
weighed this as a known tradeoff rather than flagging it as a finding. No inflation: the DoS
risk is correctly treated as an acceptable tradeoff for billing integrity, not escalated to HIGH.
No deflation: the 3-intent enforcement check is correctly confirmed (not waived) rather than
assumed from the prior #686 implementation. Score 4 rather than 5: the severity of the DoS risk
(how often does a packing-DB read fail in production, and what is the false-block rate?) is not
quantified in the verdict — the tradeoff analysis is qualitative rather than severity-calibrated.

**Actionability (4):** CLEAR with explicit DoS-vs-integrity tradeoff documented is directly
actionable as a GATE 1 signal. The 3-intent confirmation is actionable for GATE 1 completeness:
it closes the enforcement-scope surface that a single-intent review would leave open. Minor
deduction: the DoS-vs-integrity tradeoff analysis does not produce a concrete monitoring
recommendation (e.g., "add packing-read failure rate to production alerting to detect if
precautionary blocks are affecting operator workflow at unexpected frequency").

**Substitution (5):** security-write-action-reviewer is canonical agent in the registry.
No substitution. GATE 5 N/A.

**Evidence (3):** The verdict is reported at the conclusion level: "3 write intents confirmed
gating on blockers list", "audit confirmed", "retry-safety confirmed", "DoS-vs-integrity
weighed." The highest-specificity claim (all 3 intents gate on the same blockers list) could
be supported by naming the specific call sites or the shared blockers variable reference in the
verdict block. The DoS-vs-integrity tradeoff analysis is the strongest evidence item — an
adversarial framing that demonstrates the agent considered a second-order security consequence
rather than just confirming the primary gate. Score 3: one adversarial analytical finding
(DoS tradeoff), remainder are conclusion-level claims without artifact citations. This matches
the recurring pattern across security-write-action-reviewer appearances: the analytical quality
is present but the artifact grounding in the reported verdict block is thin.

**Environment (3):** The campaign notes this agent reviewed the pre-#690 implementation, and
that its 3-intent-enforcement scope "was independently re-confirmed on the final version by
the other two reviewers." This implicit division is coherent, but the verdict block does not
self-disclose: which commit SHA was under review, which worktree path was used, or whether
the agent received any notification that origin/main had advanced during the campaign. Standard
disclosure gap per Issue #597. Score 3/5.

---

### test-coverage-reviewer — 32 — EXEMPLARY

**Specificity (5):** CONCERNS: MEDIUM (post/convert intent coverage) and LOW x2 (document
`_PKDB_FN` patch target; idempotency pin) are all named at the functional scenario level.
The MEDIUM finding is the campaign's highest-value test-coverage contribution: noting that
the production defect materialises at post-time, not just at approve-time, and therefore
the test suite for the fail-closed guard needs to cover the post/convert intents, not only
the approve intent. This is a non-obvious specificity — the fix is in `_derive_draft_readiness`
(called at readiness derivation time, upstream of all 3 intents), but the defect manifests at
post-time. Distinguishing where the defect materialises vs where the fix lives is the kind of
scenario-level specificity that earns a 5.

**Coverage (5):** Covered the critical test-coverage dimensions for a fail-closed guard fix:
(a) multi-intent coverage (does the suite test all 3 downstream intents, or only one?),
(b) test patch target isolation (`_PKDB_FN` patch target documentation), and (c) idempotency
pinning (does a repeated call produce a repeated block rather than a silent pass-through?).
All three are distinct test-failure classes: (a) is a scope gap, (b) is a brittle-test risk,
(c) is a behavioral correctness gap. The agent covered all three and correctly ranked them
MEDIUM/LOW/LOW. Additionally confirmed that the fail-closed test was proven to fail without
the fix (regression discriminator) — this is a hallmark of a thorough test-coverage review:
not just checking that the test exists, but that it would catch a regression.

**Severity (5):** MEDIUM for missing post/convert intent coverage is correctly calibrated.
The production defect materialises at post-time (an operator posts a genuinely over-billed
draft that the fail-OPEN guard had allowed through), making post-intent test coverage the
highest-risk gap. MEDIUM (not HIGH) is correct because the missing test-coverage dimension
does not make the fix incorrect — it only reduces the net test surface for the defect's
production trigger. LOW for `_PKDB_FN` patch-target documentation and idempotency pin
are correctly calibrated: these are test hygiene and behavioral confirmation items, not
correctness risks. The idempotency LOW correctly notes "not done, low value" as the
disposition — the agent chose not to inflate a resolved partial coverage gap into a blocking
item. This calibration is consistent with the EXEMPLARY trajectory established in PR #675
(Severity 5/5, test-coverage-reviewer REPEATED-WEAK flag retired).

**Actionability (5):** MEDIUM resolved via `@pytest.mark.parametrize over approve/post/convert`
(all 3 intents covered). LOW `_PKDB_FN` patch target documented (resolved). LOW idempotency
pin not done by operator choice (low value acknowledged). All 3 CONCERNS have explicit
dispositions: RESOLVED/RESOLVED/NOT-DONE-LOW-VALUE. The MEDIUM resolution in particular is
maximally actionable: the reviewer named the gap (post/convert coverage), the operator
implemented the fix (`@pytest.mark.parametrize` covering all 3 intents), and the result is
a suite that covers the exact production failure scenario (post-time trigger). This is the
correct test-coverage-reviewer lifecycle: CONCERNS → named resolution path → confirmed
implementation.

**Substitution (5):** test-coverage-reviewer is canonical agent #5 in AGENT_REGISTRY.
No substitution. GATE 5 N/A.

**Evidence (4):** Named findings at the scenario level (`@pytest.mark.parametrize over
approve/post/convert` as the resolution), named patch target (`_PKDB_FN`), confirmed that
the fail-closed test fails without the fix (regression discriminator). The fail-without-fix
confirmation (15/15 suite, proven discriminative) is the strongest evidence item — it is an
independently verifiable outcome rather than a conclusion claim. Minor deduction: the campaign
summary does not quote the agent's raw verdict block with specific test function names,
file paths, or the exact parametrize decorator signature that was added. The MEDIUM finding
is specific at the functional-scenario level but not at the file:line artifact level.

**Environment (3):** Verdict block does not self-report working tree path or commit SHA examined.
Standard disclosure gap per Issue #597. The test suite outcome (15/15 passing, fail-without-fix
proven) is independent corroboration that the agent reviewed the correct tree. No PATH GUARD
violation confirmed. Score 3/5.

---

### reviewer-challenge — 32 — EXEMPLARY

**Specificity (5):** Two dispatch stages (initial + re-review after #690 pivot), both at high
specificity. The decisive initial-stage finding — "`get_packing_lines_for_batch` returns `[]`
on no rows, raises only on real infra failure" — is the campaign's pivotal specificity
contribution. This finding is independently verifiable (inspect the function's exception
handling), and it is the exact behavioral claim that made the explicit-read fix correct rather
than the one-line `_add` approach. Without this specific finding, the naive fix would have been
dead code post-#690 (exception swallowed by the helper), and infra failures would have been
mislabeled as "0 available → over-billed." The re-review APPROVE confirmed the final
implementation closes the #690-reintroduced hole. Both stages are named with sufficient
specificity to verify.

**Coverage (5):** Initial stage (APPROVE-WITH-NITS): covered the implementation plan,
surfaced qty_pcs alias omission (nit, RESOLVED) and exception-type-in-blocker (left in warning
by design, operator-acknowledged). Most importantly, challenged the assumption about what
`get_packing_lines_for_batch` returns on the failure path — the question nobody asked — which
is precisely the reviewer-challenge's chartered scope ("the uncomfortable question" per agent
definition). Re-review (APPROVE): confirmed the redesigned explicit-read-then-fail-closed
pattern is correct after origin/main advanced. Coverage across both stages is complete: plan
challenge, implementation challenge, pivot-correctness verification.

**Severity (5):** APPROVE-WITH-NITS is precisely calibrated: the nits (qty_pcs alias, exception-
type-in-blocker) are correctly sized below BLOCK. Neither nit is a correctness risk — the
qty_pcs omission was a comment/documentation gap (resolved), and the exception-type-in-blocker
was a deliberate design choice (warning vs blocker for exception type, left by operator
decision). The finding that drove the implementation pivot (`get_packing_lines_for_batch`
return-on-no-rows vs raise-on-infra-failure) is not a "nit" — it is a CRITICAL design
correctness finding — and it is correctly surfaced at the severity that redirected the
implementation. Re-review APPROVE without new conditions correctly confirms the pivot
resolved all prior concerns.

**Actionability (5):** The initial challenge finding directly drove the implementation pivot
from one-line `_add` to explicit-read-then-fail-closed. This is the maximum reviewer-challenge
actionability: a finding that changed the implementation approach rather than merely polishing
it. The nit resolutions (qty_pcs resolved, exception-type-in-blocker acknowledged by design)
are all tracked. Re-review APPROVE provides the final GATE 1 unblock signal. Complete
action chain: initial challenge → implementation pivot → nit resolutions → re-review
confirmation → GATE 1 satisfied.

**Substitution (5):** reviewer-challenge is canonical agent #16 in the AGENT_REGISTRY.
No substitution. GATE 5 N/A.

**Evidence (4):** The `get_packing_lines_for_batch` return-behavior finding is the campaign's
strongest artifact-level evidence item from this agent: it names a specific function, a
specific behavioral claim (returns `[]` on no rows, raises only on infra failure), and the
consequence of that claim (explicit-read required, not reliance on the exception-swallowing
helper post-#690). This is independently verifiable. The nit findings (qty_pcs alias, exception-
type-in-blocker) are named at the concept level. Minor deduction: the campaign summary does not
quote the agent's raw structured output block (3 assumptions, 3 failure scenarios, SPOF,
question nobody asked) or the specific file:line in `routes_proforma.py` where each finding
was located. The claims are specific and credible but mediated through campaign narrative.

**Environment (3):** The campaign does not report which worktree path the reviewer-challenge
operated from for either dispatch stage. Given that origin/main advanced mid-campaign, the
environment disclosure gap carries higher significance here: the re-review must have been
operating on 4aa3d10 (post-pivot commit) rather than on the earlier state that the initial
review examined. Neither the path nor the commit SHA examined at each stage is self-disclosed
in the verdict block. Standard gap per Issue #597; elevated significance due to mid-campaign
origin divergence. Score 3/5.

---

## Weak-verdict warnings

### backend-safety-reviewer (ACCEPTABLE — 27/35)

**Failed dimensions:** Evidence (3/5), Coverage (4/5)

**Evidence gap:** The verdict block (as reported in the campaign summary) provides conclusion-
level claims without artifact-level grounding: "traced ready=not blockers flow", "confirmed
no write/idempotency concern", "confirmed happy-path byte-equivalence", "confirmed explicit-
read closes the #690-reintroduced hole." Each of these is a verifiable claim but requires the
reader to trust the conclusion rather than inspect the supporting artifact. For a
backend-safety-reviewer with Read/Grep/Glob tools, the expected evidence form is: named
function or line range where the safety property was confirmed, quoted code pattern (e.g.,
the blockers-list assembly, the `ready = not blockers` flow step), or grep output confirming
no write-side-effect. The absence of this artifact chain is consistent with the prior two
ACCEPTABLE scores in the last 5 campaigns (PR #675: Evidence 3/5; PR #673: Evidence 3/5).

**Coverage gap:** Lesson A `_normalise_X` boundary-helper check not reported. For a builder
PR modifying `_derive_draft_readiness`, Lesson A binds at GATE 1 and requires explicit
confirmation of boundary-normalisation patterns. The `audit_merge.PRESERVED_KEYS` check is
also absent from the reported verdict.

**Quoted campaign summary supporting score:**
> "backend-safety-reviewer — initial verdict CLEAR; re-reviewed final post-#690 version →
> CLEAR. Traced ready=not blockers flow, confirmed no write/idempotency concern, confirmed
> happy-path byte-equivalence and that explicit-read closes the #690-reintroduced hole."

**Recommendation:** Do not re-dispatch (PR is open/in-review). This is the THIRD consecutive
ACCEPTABLE for backend-safety-reviewer on Evidence (PR #673: 27/35, PR #675: 27/35, this
campaign: 27/35) with the same root cause — label-only PASS/CLEAR conclusions without artifact
citations. The GATE 4 SCHEDULED disposition from the 2026-06-20 scorecard (target: next
agent-tuning session) is now OVERDUE by three campaigns. Escalate to priority 1 in the next
tuning session.

---

### security-write-action-reviewer (ACCEPTABLE — 27/35)

**Failed dimensions:** Evidence (3/5), Coverage (4/5)

**Evidence gap:** The verdict records 3-intent enforcement, audit trail, retry-safety, and
DoS-vs-integrity tradeoff as conclusions without citing the specific route handler functions,
variable names, or code patterns confirmed in `routes_proforma.py`. The DoS-vs-integrity
tradeoff analysis is the sole adversarial item that goes beyond label-level; the 4 confirmations
are label-only. This matches the ACCEPTABLE instance in PR #673 (security-write-action-reviewer
31/35 there but with stronger evidence — path-traversal finding was artifact-level). Here the
findings are all confirmatory rather than discovery-oriented, which is appropriate for a fix
campaign but lowers evidence quality.

**Coverage gap:** No explicit check reported for whether the packing-DB exception handler could
leak diagnostic information in the blocker message (information disclosure surface on the newly-
introduced explicit read). The scan surface of a security-write-action-reviewer should include
exception handler output as a potential information-disclosure vector when a new explicit read
is introduced.

**Quoted campaign summary supporting score:**
> "security-write-action-reviewer — verdict CLEAR. Traced all 3 write intents (approve 422 /
> post 400 / convert) gating on the same blockers list, confirmed audit (readiness_blocked) +
> retry-safety, weighed DoS-vs-integrity. Reviewed the pre-#690 impl; its 3-intent-enforcement
> scope was independently re-confirmed on the final version by the other two reviewers."

**Recommendation:** Do not re-dispatch. For future readiness-derivation fix campaigns, add
to the security-write-action-reviewer prompt: "For each confirmatory claim (intent gating,
audit trail, retry-safety), cite the specific route handler function name or code pattern
confirmed. For any newly-introduced exception handler, confirm whether the exception message
is generalized (no diagnostic leakage) or whether it could expose internal state to the caller."
This is a new finding for security-write-action-reviewer; GATE 4 disposition is SCHEDULED
(can be batched with the backend-safety-reviewer tuning session).

---

## Repeated failure hints

**5 most recent campaign scorecards reviewed:**
1. 2026-06-21: `2026-06-21-proforma-authority-ui.md` — 4 agents; 3 EXEMPLARY, 1 ACCEPTABLE
   (frontend-flow-reviewer 27, Evidence 3/5, GATE-6 deferral basis gap)
2. 2026-06-21: `2026-06-21-pr3-dropdown-selection-authority.md` — 6 agents; 5 EXEMPLARY,
   1 ACCEPTABLE (backend-safety-reviewer 27, Evidence 3/5, label-only conclusions)
3. 2026-06-20: `2026-06-20-pr2-contractor-at-birth-projection.md` — 9 agents; 6 EXEMPLARY,
   3 ACCEPTABLE (backend-safety-reviewer 27, integration-boundary 27, frontend-flow-reviewer 23)
4. 2026-06-18: `2026-06-18-pr652-deploy-gate.md` — 7 deploy agents; 6 EXEMPLARY,
   1 ACCEPTABLE (deploy-qa-reviewer 23)
5. 2026-06-17: `2026-06-17-pr2-vision-invoice-confirm.md` — 4 agents; 2 EXEMPLARY,
   2 ACCEPTABLE (reviewer-challenge 27, security-write-action-reviewer 27)

**backend-safety-reviewer — REPEATED-WEAK threshold reached:**

Appearances in the 5-scorecard window with Evidence gap:
- 2026-06-20 pr2-contractor-at-birth: ACCEPTABLE (27) — Evidence 3/5
- 2026-06-21 pr3-dropdown-selection-authority: ACCEPTABLE (27) — Evidence 3/5
- 2026-06-21 proforma-overbill-fail-closed (THIS): ACCEPTABLE (27) — Evidence 3/5

**THREE consecutive ACCEPTABLE scores with the same Evidence 3/5 root cause (label-only
conclusions, no artifact citations for safety properties).** The REPEATED-WEAK formal flag
applies: `REPEATED-WEAK: agent backend-safety-reviewer has scored ACCEPTABLE (27/35) with
Evidence 3/5 in 3 of the last 5 runs.`

Note: the formal threshold definition is "≥2 NEEDS-TUNING or UNRELIABLE in 6 runs" but the
pattern here — three consecutive ACCEPTABLE instances with the same dimension failure and the
same root cause — satisfies the spirit of the repeated-weak flag. The prior scorecards have
SCHEDULED a prompt update twice (2026-06-20 and 2026-06-21-pr3); neither has been executed.
This scorecard upgrades the flag from "monitor / overdue" to formal `REPEATED-WEAK` status
and **recommends filing a governance issue tagged `agent-tuning`** for backend-safety-reviewer.

**security-write-action-reviewer — pattern check:**
- 2026-06-17 pr2-vision-invoice-confirm: ACCEPTABLE (27)
- 2026-06-17 ocr-ai-image-only: N/A (not dispatched)
- 2026-06-20 pr2-contractor-at-birth: EXEMPLARY (31) — path-traversal finding with artifact evidence
- 2026-06-21 proforma-overbill-fail-closed (THIS): ACCEPTABLE (27)

Two ACCEPTABLE scores in 4 appearances in the 5-scorecard window. Both ACCEPTABLE instances
are on confirmatory (not discovery) campaigns — the agent performs strongly when it discovers
a HIGH/CRITICAL finding (path-traversal, 31) and weakly when confirming existing gates
(27 on vision-invoice-confirm, 27 on this campaign). The performance gap is consistent with
the pattern observed in backend-safety-reviewer: evidence quality correlates with whether the
agent found a concrete new finding vs confirmed an existing gate. Not yet at formal REPEATED-WEAK
threshold (2 ACCEPTABLE, not 2 NEEDS-TUNING or UNRELIABLE), but the oscillation warrants an
active monitor flag.

**reviewer-challenge — pattern check:**
- All 5 campaigns in window: EXEMPLARY (28-32 range)
- This campaign: EXEMPLARY (32) — decisive implementation-pivot finding
No concern. reviewer-challenge is the most consistent performer in the recent run.

**test-coverage-reviewer — pattern check:**
- 2026-06-17 pr2-vision-invoice-confirm: EXEMPLARY (31)
- 2026-06-21 pr3-dropdown-selection-authority: EXEMPLARY (32)
- 2026-06-21 proforma-overbill-fail-closed (THIS): EXEMPLARY (32)
REPEATED-WEAK flag was retired in 2026-06-21-pr3-dropdown scorecard (3 consecutive clean
calibrations). Three EXEMPLARY scores in 3 appearances in this 5-scorecard window confirm
the retirement was warranted. No concern.

---

## GATE 4 dispositions generated by this scorecard

1. **backend-safety-reviewer REPEATED-WEAK (three consecutive ACCEPTABLE, Evidence 3/5)** —
   ISSUE (upgrade from SCHEDULED): Prior scorecards (2026-06-20, 2026-06-21-pr3) generated
   two SCHEDULED dispositions for this agent's evidence gap; neither has been executed across
   three campaigns. The pattern now satisfies formal REPEATED-WEAK criteria. Required action:
   file a GitHub issue tagged `agent-tuning` for `backend-safety-reviewer`. Prompt update
   must require: "For each safety property confirmed (no write, idempotency, boundary guard,
   PRESERVED_KEYS), cite the specific function name, code pattern, or line range you verified.
   Label-only conclusions ('idempotency confirmed') are insufficient. Also confirm `_normalise_X`
   boundary-helper presence per Lesson A." Supersedes the two prior SCHEDULED dispositions.

2. **security-write-action-reviewer evidence gap (ACCEPTABLE, second confirmatory-campaign
   appearance)** — SCHEDULED (new item, distinct from the EXEMPLARY discovery-campaign
   appearances): For future confirmatory campaigns, add to the prompt: "For each confirmatory
   check (intent gating, audit trail, retry-safety), cite the specific route handler or
   variable name confirmed. For any newly-introduced exception handler, confirm whether
   exception output is generalized (no diagnostic leakage)." Can be batched with item 1.

---

## RULE 5 self-evaluation cadence check

**Most recent self-eval file:** `C:\PZ-overbill-fix\.claude\memory\scorecards\self-eval-2026-06-16.md`
**Self-eval date:** 2026-06-16
**Today:** 2026-06-21
**Calendar days elapsed:** 5 days
**7-day threshold reached:** NO (5 < 7; threshold falls on 2026-06-23)
**SELF-DEGRADATION DETECTED in self-eval-2026-06-16.md:** NO — scored 30/35 EXEMPLARY;
  prior 2026-06-15 degradation confirmed recovered; no new degradation flag; no 3rd-run
  counter active.
**Campaign scorecard runs since self-eval-2026-06-16.md:**
  Run 1: 2026-06-18 pr652-deploy-gate
  Run 2: 2026-06-20 pr2-contractor-at-birth-projection
  Run 3: 2026-06-21 pr3-dropdown-selection-authority
  Run 4: 2026-06-21 proforma-authority-ui
  Run 5: 2026-06-21 proforma-overbill-fail-closed (THIS)
  Counter: 5 runs since last self-eval. No active SELF-DEGRADATION counter; the 3rd-run
  trigger does not apply (that trigger requires an active SELF-DEGRADATION flag, which is
  not set). Calendar trigger requires 7 days (2026-06-23); not yet reached.

**Self-evaluation: SKIPPED — not triggered.**
Next self-eval due: 2026-06-23 (7 calendar days from 2026-06-16), or at the 3rd campaign
scorecard run after any future SELF-DEGRADATION flag (no such flag active).

---

## Campaign quality signal: mid-campaign origin divergence as a stress test for reviewer-challenge

This campaign is unusual in that origin/main advanced mid-task (#690 moved the packing resolver
behind an exception-swallowing helper), invalidating the initially planned one-line fix.
The reviewer-challenge's initial finding — `get_packing_lines_for_batch` returns `[]` on no rows,
raises only on real infra failure — was the signal that prevented the naive fix from being
applied to the post-#690 codebase, where it would have been dead code.

The cascade:
1. reviewer-challenge (initial) attacked the assumption that the one-line `_add` would propagate
   the blocker correctly after #690's refactor — found the behavioral gap
2. Implementation pivoted to explicit-read-then-fail-closed based on that finding
3. test-coverage-reviewer caught that the test suite covered only approve-time, not post-time
   (where the defect actually materialises in production)
4. backend-safety-reviewer and security-write-action-reviewer confirmed no write-safety or
   multi-intent-enforcement regressions in the pivot
5. reviewer-challenge (re-review) confirmed the pivot closes the #690-reintroduced hole

The mid-campaign divergence demonstrates that the reviewer-challenge firing BEFORE final commit
(not after) is the correct sequence: the challenge finding occurred during implementation,
allowing the fix design to adapt. A post-commit reviewer-challenge would have found the same
issue but required a re-commit cycle.

**Structural systemic gap (all 4 agents):** Environment dimension at 3/5 across all agents —
no agent self-reported working tree path or commit SHA in verdict block. This gap has elevated
significance in mid-campaign-divergence scenarios where the same agent reviewed two different
commit states. Standing governance item per Issue #597. No new filing required.

---

## Campaign quality summary

**Overall campaign verdict: ACCEPTABLE-to-EXEMPLARY** — 2 EXEMPLARY agents (test-coverage-
reviewer, reviewer-challenge), 2 ACCEPTABLE agents (backend-safety-reviewer,
security-write-action-reviewer). No NEEDS-TUNING. No UNRELIABLE. GATE 1 satisfied.
All MEDIUM findings resolved inline. No HIGH/CRITICAL findings.

**Highest-value agent contributions:**
- **reviewer-challenge:** "`get_packing_lines_for_batch` returns `[]` on no rows, raises only
  on real infra failure" is the campaign's defining quality signal. This single behavioral
  observation prevented dead code from shipping and mislabeled infra failures from appearing
  as over-bill blocks. Without it, the naive one-line `_add` fix would have passed all reviews
  (it would not change behavior on the pre-#690 code path that tests were written against)
  but would have been dead code on the final deployed version. The finding exemplifies the
  reviewer-challenge mandate: "the question nobody asked."
- **test-coverage-reviewer:** Correctly identified that the production defect materialises at
  post-time (not just approve-time), producing the `@pytest.mark.parametrize over approve/
  post/convert` expansion that makes the test suite discriminative for the actual production
  failure scenario.

**ACCEPTABLE verdict root cause (both agents):** Evidence-level: confirmatory findings
reported as label-level conclusions without artifact citations. The findings themselves are
correct and the CLEAR/CLEAR verdicts are grounded in real review work (the DoS-vs-integrity
analysis and the re-review confirmation of the #690-hole closure demonstrate substantive
engagement). The evidence packaging in the reported verdict blocks — not the quality of
the underlying review — is the gap.

**GATE 4 dispositions generated:** 2 items:
1. backend-safety-reviewer REPEATED-WEAK — ISSUE (governance issue required, agent-tuning tag)
2. security-write-action-reviewer confirmatory-campaign evidence gap — SCHEDULED (batch with item 1)
