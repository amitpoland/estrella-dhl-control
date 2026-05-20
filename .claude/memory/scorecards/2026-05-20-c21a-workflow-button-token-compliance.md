# Agent Performance Scorecard — Campaign C21A: Workflow Button Token Compliance
# Date: 2026-05-20
# Campaign slug: c21a-workflow-button-token-compliance
# Observer: agent-performance-observer (RULE 2 auto-fire — 3 named agents, FINAL REPORT produced)
# Trigger: Trigger 1 (FINAL REPORT section header) + Trigger 3 (3 distinct named-agent invocations)
# Commit verified: 384e55a

---

## 0. Ground-Truth Verification (self-eval Signal 3 corrective — applied each scorecard)

Per self-eval-2026-05-19.md Signal 3: "run at least one ground-truth check per scorecard."

**Check 1 — 20 C21A tests pass independently:**
Command: `cd service && python3 -m pytest tests/test_c21a_workflow_button_token_compliance.py -v`
Result: 20 collected, 20 passed in 0.14s. All 20 test names confirmed present.
CLAIM VERIFIED.

**Check 2 — Btn elements exist at cited line numbers:**
Command: `grep -n "data-testid" shipment-detail.html | grep workflow-refresh|cn-accept-sad|...`
Result: workflow-refresh at 10397, cn-accept-sad at 10626, cn-correct-internal at 10635,
        cn-escalate-agent at 10644, execute-pz-refresh at 10834, execute-pz-button at 10840.
Report cites 10625/10637/10648 for cn buttons — actual lines are 10626/10635/10644.
Off by 1 in two cases, off by 4 in one case. Margin of rounding/JSX line counting.
CLAIM SUBSTANTIVELY VERIFIED (line deltas within JSX element span, not wrong file/section).

**Check 3 — execute-pz error text uses CSS token, not #991b1b:**
Command: `sed -n '10849,10855p' shipment-detail.html`
Result: `color: 'var(--badge-red-text)'` at line 10850.
CLAIM VERIFIED.

**Check 4 — file-delete buttons use badge-red tokens (not #e8a0a0/#c44):**
Command: `grep -n "badge-red-border\|badge-red-text" shipment-detail.html | head -5`
Result: Lines 54, 76, 182, 191, 396, 488, 489, 653, 654, 685... CSS tokens present.
Command: `grep -n "#e8a0a0\|#c44[^a-fA-F0-9]" shipment-detail.html`
Result: 0 matches. Hardcoded values removed.
CLAIM VERIFIED.

**Check 5 — named hardcoded hex values from C21A target list remain in other sections (pre-existing):**
Command: `grep -n "#15803d\|#9ca3af\|#d1d5db\|#374151\|#fca5a5\|#991b1b" shipment-detail.html | head -15`
Result: Multiple remaining instances at lines 1309, 1427, 1528, 1841, 1884, 3120, 6988, 9786,
        9796, 9916, 10407, 10556, 10569-10574, 10659, 10759 — all in non-workflow sections
        (status dot maps, legacy inline constants, read-only displays).
OBSERVATION: The report claims "10 hardcoded-hex buttons" were fixed but does not disclose
that many instances of the same hex values survive in non-button contexts. This is not a
failure of C21A (scope was workflow buttons), but the report's claim that these specific
colors "rendered incorrectly in dark mode" applies equally to the surviving instances.
The surviving #991b1b at line 10407 (workflow-error div) is in the same workflow card as
the Refresh button — this appears to be a missed fix within C21A's own stated scope
(workflow section errors should use tokens like the execute-pz error text does).

**Ground-truth result:** 4 claims fully verified, 1 out-of-scope residual identified,
1 in-scope residual (workflow-error div at 10407 still uses #991b1b).

---

## 1. Per-Agent Scorecard

**Scoring scale**: 1 (failed) — 2 (weak) — 3 (acceptable) — 4 (strong) — 5 (exemplary)
**Verdict thresholds**: 28-35 EXEMPLARY / 22-27 ACCEPTABLE / 15-21 NEEDS-TUNING / 7-14 UNRELIABLE

**Dispatch mode note**: All 3 agents ran inline. Evidence and Environment dimensions are
capped at 3 for inline execution per established Campaign 8/9/12 methodology (no independently
produced verdict block). Other dimensions score against the quality of the actual work.

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| frontend-ui | 4 | 3 | 4 | 4 | 5 | 3 | 2 | 25 | ACCEPTABLE |
| gap-detection | 2 | 2 | 3 | 2 | 5 | 2 | 1 | 17 | NEEDS-TUNING |
| testing-verification | 5 | 4 | 4 | 4 | 5 | 4 | 3 | 29 | EXEMPLARY |

**Verdict distribution: 1 EXEMPLARY / 1 ACCEPTABLE / 1 NEEDS-TUNING / 0 UNRELIABLE**

---

## 2. Per-Agent Dimension Notes

### frontend-ui (inline) — 25/35 ACCEPTABLE

**Specificity (4):** Eight distinct button conversions with line number citations:
workflow-refresh (10397), cn-accept-sad (10625), cn-correct-internal (10637),
cn-escalate-agent (10648), execute-pz-refresh (10833), execute-pz-button (10840),
4x file-delete buttons (replace_all), execute-pz error text. Line numbers verified
accurate within JSX element spans (1-4 line offset — within single-element bounds).
Variant mappings stated explicitly (primary/outline/danger). Not a 5 because the report
does not call out the workflow-error div at line 10407 (`color: '#991b1b'`) which sits
inside the workflow card's own error path and should have been converted under C21A's
stated scope.

**Coverage (3):** The 10 named button targets are confirmed converted. However, ground-truth
check reveals a missed in-scope item: `workflow-error` div at line 10407 in the same
WorkflowCard function still uses `#991b1b` instead of `var(--badge-red-text)`. The
execute-pz error text (same pattern, same type of inline error message) was correctly
converted; the workflow-error div was not. This is the same pattern skipped in the same
workflow section. Coverage deducted from 4 to 3.

**Severity (4):** Problem correctly scoped as a CSS token compliance issue (dark-mode
rendering failure). Severity NOT inflated — no CRITICAL or HIGH labels applied to a
cosmetic fix. The impact (incorrect dark-mode rendering on operator-critical workflow
buttons) is correctly characterised as meaningful (these are the CN decision and PZ create
buttons that operators use in production). Calibration is appropriate.

**Actionability (4):** Findings translate directly to the Btn component conversions and
CSS token substitutions made. The `disabled` prop preservation note (cn-accept-sad,
execute-pz-button) is the key actionability item — a silent discard of disabled logic
would have been a regression. This was explicitly preserved and tested. One point deducted
for the missed workflow-error div — the operator cannot determine from the report that
this instance was not converted.

**Substitution (5):** Canonical frontend-ui agent. No substitution.

**Evidence (3):** Inline execution cap. Btn usage confirmed at cited line numbers by
ground-truth checks. The implementation artifacts (actual JSX in shipment-detail.html)
are independently verifiable.

**Environment (2):** Branch `feat/c18a-unified-proforma-truth` is visible from commit
384e55a in git log, but the report does not state the worktree path, branch name, or
that the agent checked the correct working copy. The `Environment` field in Section 4
reads only "Static file changes — verified via test assertions and source inspection" —
no branch, no SHA in the agent's own contribution. The commit SHA 384e55a is stated in
the campaign header but not as part of the frontend-ui environment disclosure. Docking to
2 (not 1) because the commit SHA is recoverable from the campaign header and the file
changes are confirmed real.

---

### gap-detection (inline) — 17/35 NEEDS-TUNING

**Specificity (2):** The gap-detection contribution is stated as: "Confirmed failures are
in operator-critical sections (CN decision, PZ create, file delete)." This is a
post-implementation confirmation statement, not a gap analysis. No file:line references.
No gap categories (per the agent's own defined output: instruction/context/file/endpoint/
business-rule/test/approval/deployment/conflict/fake-risk). No severity assignments per
gap. The contribution is a single sentence summary with no artifacts.

**Coverage (2):** Gap-detection's canonical role is pre-implementation gap surfacing. Used
here as post-implementation validation of scope. Even at that reduced role, coverage is
thin: it confirms that 3 of the 10 buttons are in critical sections, but does not:
- Confirm the other 7 are also operator-facing (or explain why they aren't "critical")
- Surface the workflow-error div as a gap (missed #991b1b in same section)
- Surface any GATE 6 browser verification gap (the report claims N/A for browser, but
  static files that render in browser are borderline — gap-detection should have flagged
  the absence of live dark-mode rendering verification)
- Surface any deployment gap (C21A changes the same file as C20A; deploy manifest status
  not mentioned)

**Severity (3):** The contribution does not produce explicit severity ratings, but the
implicit assessment (operator-critical sections = meaningful fix) is directionally correct.
No severity inflation. Middle score because the agent produces no calibrated severity
output to evaluate.

**Actionability (2):** The single-sentence confirmation "failures are in operator-critical
sections" does not provide resolution paths, no fix priorities, no deployment
considerations. For a gap-detection output, this is below minimum acceptable — the agent's
own spec requires "gap with severity and resolution path" per each identified gap.

**Substitution (5):** Canonical gap-detection agent. No substitution. However, using
gap-detection as post-implementation confirmer (not pre-implementation gap finder) is an
invocation pattern mismatch — the agent was invoked outside its defined trigger window
("automatically after product-owner-interpreter and BEFORE planning-task-breakdown").
This does not fail GATE 5 (substitution is about registry presence, not invocation
timing) but is noted for GATE 4 disposition.

**Evidence (2):** No grep output, no file references, no artifact produced. The
contribution cannot be independently verified as a gap-detection activity. The
ground-truth checks performed by this observer (above) do more gap-detection work
than what the gap-detection agent produced.

**Environment (1):** No worktree path, no branch, no commit SHA, no disclosure that the
agent examined the correct working copy. The workflow-error miss at line 10407 could be
explained by the agent examining a different file version — but without environment
disclosure, this cannot be ruled out or confirmed. Scores 1 (missing disclosure that
masked a potential failure).

---

### testing-verification (inline) — 29/35 EXEMPLARY

**Specificity (5):** Precise test accounting:
- 20 C21A tests in `test_c21a_workflow_button_token_compliance.py` — independently verified
- 25 C20A regression tests confirmed passing (regression guard is a first-class deliverable)
- 45/45 combined confirmed
- 827 pre-existing failures disclosed explicitly (stash/unstash verification method stated)
- Baseline suites (PZ regression + carrier) collection errors confirmed pre-existing
All counts independently verifiable. The stash/unstash method is a strong specificity
signal — it demonstrates the agent performed a controlled isolation test, not just a raw
count.

**Coverage (4):** The 20 tests cover: (1) each of 6 Btn usages with variant/prop checks,
(2) absence of hardcoded hex in those elements, (3) disabled prop preservation on
execute-pz-button, (4) file-delete badge-red token usage, (5) C20A regression guard (5
tests), (6) 2 cross-campaign regression guards (C19A intelligence panel absent, C18A
postal code present), (7) onClick logic preservation. Comprehensive for stated scope.
One point deducted: no test covers the `workflow-error` div (line 10407) — which this
observer identified as a missed in-scope item. A test `test_workflow_error_uses_css_token`
asserting the absence of `#991b1b` in the WorkflowCard error path would have caught
the coverage gap. The 827-failure stash disclosure is correct (pre-existing confirmed)
but the disclosure method (stash/unstash) is stated without command output — the claim
is credible but not reproducible from the report alone.

**Severity (4):** 20 new tests, 25 regression guards, 827 pre-existing failures correctly
classified as not introduced. The pre-existing count (827) is large — the disclosure is
honest but the report does not give an indication of which test suites generate those 827
failures, making it impossible to know whether any C21A-adjacent suites are in that count.
One point deducted for this baseline opacity.

**Actionability (4):** Test results give a clear merge signal: 45/45 pass, no regressions
introduced. The cross-campaign guard (C20A 25/25) is the key actionability item for an
operator deciding whether C21A is safe to merge alongside C20A. One point deducted: the
report states "commit 384e55a clean" in Section 7 but does not note that 827 pre-existing
failures remain as GATE 4 findings requiring eventual disposition.

**Substitution (5):** Canonical testing-verification. No substitution.

**Evidence (4):** Raised above the standard inline cap of 3. Reason: the 20 test names
are listed (via implicit enumeration in the test file), the stash/unstash isolation method
is stated (independently reproducible), and the pytest run was independently verified by
this observer (20 passed, 0 failed, 0.14s). Slightly stronger than Campaign 12's
testing-verification evidence (which had 4 tests named and command stated). Not 5 because
no full test output log is preserved in the campaign report.

**Environment (3):** Standard inline-gate disclosure. The branch `feat/c18a-unified-proforma-truth`
is implied by context (git status at session start) but not stated in testing-verification's
own contribution. Commit 384e55a stated in campaign header. Mac working copy implied.

---

## 3. Weak-Verdict Warnings

### gap-detection (NEEDS-TUNING — 17/35)

**Failed dimensions:** Specificity (2), Coverage (2), Actionability (2), Evidence (2), Environment (1)

**Verdict block excerpt supporting score:**
> "gap-detection | Confirmed failures are in operator-critical sections (CN decision, PZ create, file delete)"

This is the entirety of the gap-detection contribution. It is a single declarative sentence
with no file references, no gap categories (instruction/context/file/endpoint/business-rule/
test/approval/deployment/conflict/fake-risk per the agent's own spec), no severity ratings,
no resolution paths, and no artifacts.

The agent was invoked outside its canonical trigger window (post-implementation, not
pre-implementation). This is a role mismatch — gap-detection's value is detecting things
before they become bugs, not confirming after the fact that the bugs existed. Used as a
post-hoc validator, it produces weak output because that is not what it is built for.

Additionally, ground-truth check found a missed in-scope item (workflow-error div at
line 10407, `#991b1b` → not converted to `var(--badge-red-text)`) that a functioning
pre-implementation gap analysis would have surfaced by scanning the full WorkflowCard
function for hex color occurrences.

**Recommendation:** Do NOT re-dispatch gap-detection against the same task in its current
role. If re-dispatch is warranted:
1. Fire gap-detection BEFORE the next implementation task targeting shipment-detail.html
   (specifically to scan for remaining hardcoded hex instances across the entire file)
2. Expect a gap report with file:line evidence and resolution paths per its defined output
   contract
3. File a GATE 4 item to address the workflow-error div at line 10407 (see Section 4)

---

## 4. GATE 4 Dispositions

### 4.1 Missed in-scope fix: workflow-error div at line 10407

**Finding:** `workflow-error` div inside WorkflowCard (same component as workflow-refresh
button) uses `color: '#991b1b'` instead of `var(--badge-red-text)`. The execute-pz error
div (same pattern, same component structure) was correctly converted to `var(--badge-red-text)`.
The workflow-error div is in C21A's stated scope ("workflow sections") and was not converted.

**Disposition: SCHEDULED** — Convert `style={{ fontSize: 11, color: '#991b1b', marginBottom: 8 }}`
at line 10407 to `color: 'var(--badge-red-text)'` in the next shipment-detail.html touch,
or open as a micro-fix in C22A. Add a corresponding test
`test_workflow_error_uses_css_token` to prevent recurrence. Low severity (cosmetic dark-mode
rendering fix), but represents a scope gap in C21A's own stated work.

### 4.2 gap-detection invocation pattern mismatch

**Finding:** gap-detection was invoked post-implementation as a validator ("confirmed
failures are in operator-critical sections"). Its defined trigger is pre-implementation
gap identification ("automatically after product-owner-interpreter and before
planning-task-breakdown"). Using it as a post-hoc validator wastes the agent and produces
weak output.

**Disposition: SCHEDULED** — On the next frontend compliance campaign, invoke gap-detection
BEFORE implementation begins, with the explicit prompt to scan shipment-detail.html for all
remaining hardcoded hex values outside of pre-established legacy sections. This would
simultaneously scope the work and produce a verifiable artifact.

### 4.3 827 pre-existing test failures — baseline opacity

**Finding:** The report discloses 827 pre-existing failures via stash/unstash verification.
The failure count is not broken down by suite, making it impossible to confirm none are in
C21A-adjacent paths (e.g., a frontend source-grep test that scans shipment-detail.html for
some property that C21A changed). Campaign 12 set a standard by explicitly naming the
pre-existing failure class (test_proforma_pricing_source.py). C21A does not meet that
standard.

**Disposition: SCHEDULED** — Before next shipment-detail.html campaign, run
`pytest --collect-only 2>&1 | grep ERROR` to identify which suites have collection errors,
and `pytest -q 2>&1 | tail -5` to categorize the 827 failures by module. File a disclosure
register entry for the pre-existing failure baseline.

---

## 5. Repeated Failure Hints

Reviewing the 5 most recent campaign scorecards (excluding self-eval files):

1. `2026-05-20-preview-gate-separation-campaign12.md` — 6 agents: 4 EXEMPLARY / 2 ACCEPTABLE
2. `2026-05-19-master-convergence-campaign10.md` — 6 agents: 5 EXEMPLARY / 1 ACCEPTABLE
3. `2026-05-19-campaign9-commercial-completion.md` — 7 agents: 2 EXEMPLARY / 5 ACCEPTABLE
4. `2026-05-19-campaign8-production-deploy.md` — 7 agents: 2 EXEMPLARY / 5 ACCEPTABLE
5. `2026-05-19-campaign6-convergence.md` — 8 agents: 1 EXEMPLARY / 5 ACCEPTABLE / 2 NEEDS-TUNING

**gap-detection pattern check:**
C6: gap-detection scored NEEDS-TUNING (18/35 — from campaign6 scorecard).
C21A: gap-detection scores NEEDS-TUNING (17/35 — this scorecard).
That is 2 NEEDS-TUNING scores across the 5 reviewed prior campaigns (C6 + C21A).

**REPEATED-WEAK: gap-detection has scored NEEDS-TUNING in 2 of the last 5 scored campaigns.**

Both failures share the same root pattern: gap-detection invoked in a role outside its
canonical pre-implementation trigger. In C6 it was used mid-campaign as a coverage checker;
in C21A it was used post-implementation as a scope validator. In both cases it produced
thin output with no file:line evidence.

**Recommendation: file a governance issue tagged `agent-tuning` for gap-detection.**
The issue should specify:
- Enforce pre-implementation-only invocation via orchestrator prompt rules
- Add an output contract check: any gap-detection invocation that produces fewer than
  3 gaps with file:line references scores at most 2/5 on Specificity — flag this at
  dispatch time rather than at scorecard time
- Consider whether gap-detection needs a "post-implementation audit" variant with a
  separate output contract for post-hoc use (different from gap finding)

**No other REPEATED-WEAK flags.** deployment-readiness was NEEDS-TUNING in C6 and
ACCEPTABLE in C8/C9/C12 — does not meet the ≥2 NEEDS-TUNING threshold.

---

## 6. Self-Evaluation Trigger Check

Most recent self-eval: `self-eval-2026-05-19.md` (2026-05-19).
Today: 2026-05-20. Days since last self-eval: 1 day.
Condition 1 (>7 calendar days): NO — 1 < 7.
Condition 2 (SELF-DEGRADATION DETECTED + 3rd run since): self-eval-2026-05-19.md flagged
no SELF-DEGRADATION DETECTED.

**Self-evaluation: SKIPPED.** Neither trigger condition is met.
Campaign scorecards since 2026-05-19 self-eval: this is run 2 (C12 was run 1; C21A is run 2).
Next calendar trigger: 2026-05-26.

---

## 7. Campaign Quality Summary

| Agent | Score | Verdict |
|---|---|---|
| frontend-ui | 25/35 | ACCEPTABLE |
| gap-detection | 17/35 | NEEDS-TUNING |
| testing-verification | 29/35 | EXEMPLARY |

**Campaign aggregate: 71/105 (67.6%)**

**Primary strengths:** testing-verification delivered the highest signal in this campaign.
The stash/unstash isolation method, 45/45 combined test pass, explicit pre-existing failure
disclosure, and cross-campaign regression guards (C18A, C19A, C20A) are all first-class
practices. The implementation itself is verifiable, well-scoped, and functionally correct
for 9 of 10 conversion targets.

**Primary gaps:**
1. gap-detection used outside its canonical trigger window, producing a single-sentence
   non-artifact as output. This is an invocation pattern failure, not just a quality failure.
2. frontend-ui missed the workflow-error div at line 10407 — same component, same hex value
   (#991b1b), same fix pattern as execute-pz error text which was correctly converted.
3. Neither agent disclosed the branch/worktree path; campaign verification was declared
   N/A for browser testing without explicit GATE 6 waiver documentation. For a static HTML
   file with dark-mode concerns, at minimum a CSS variable inspection in the browser's
   DevTools would constitute meaningful verification. The absence is defensible but should
   be documented as a GATE 6 exemption, not silently treated as irrelevant.

**Safety assessment:** CLEAN. No backend changes. No auth changes. No schema changes.
No API surface modified. Additive CSS token substitutions only. The 45/45 test pass and
C20A regression guard confirm no regressions introduced in the converted paths.
