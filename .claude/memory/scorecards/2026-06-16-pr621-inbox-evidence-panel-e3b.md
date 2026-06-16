# Agent Performance Scorecard — PR #621 Inbox Evidence Panel E3b (EvidencePanel Frontend)

**Date:** 2026-06-16
**Observer:** agent-performance-observer (RULE 2 auto-fire)
**Campaign:** Sprint 03.3 PR-E3b — EvidencePanel for Inbox V2 (frontend-only)
**PR:** #621 — MERGED, squash commit 2144c0b
**Branch:** feat/inbox-evidence-panel-e3b
**Objective:** Add read-only EvidencePanel to inbox-page.jsx consuming GET /api/v1/inbox/evidence/{item_id} (E3a endpoint from PR #614)
**Execution model:** SOLO — orchestrator only. Zero domain subagents dispatched.
**Files changed:** service/app/static/v2/inbox-page.jsx, service/tests/test_c03_inbox_evidence_panel.py (2 files)
**Outcome:** PR #621 merged, squash 2144c0b. Tests 14/14 green. GATE 6 self-performed. GATE 2 confirmed (0 open PRs at open time). Production unchanged pending deploy gate.

---

## Framing note: SOLO execution model

This campaign dispatched **zero subagents**. There is no multi-agent verdict table to score. The
scorecard instead scores the orchestrator's self-conducted verification across the standard
7 dimensions, applied to the orchestrator's own implementation work and gate compliance record.
This is a valid and important quality signal: the campaign touched a Lesson F/M V2 page
(inbox-page.jsx) and triggered GATE 6 (browser verification), yet ran without reviewer-challenge
or browser-verifier being formally dispatched.

The single "agent" entry below is the orchestrator acting as implementer + self-verifier.
The governance observations in each dimension reflect (a) what was actually done and (b) what
the standing governance rules require when a V2 frontend PR is executed.

---

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| orchestrator (solo) | 4 | 3 | 4 | 4 | 2 | 4 | 4 | 25 | ACCEPTABLE |

---

## Scoring rationale

### 1. Specificity (4/5)

**Assessment: STRONG**

The implementation record is specific at the code level. Named deliverables are concrete:
`EvidencePanel`, `renderEvidence`, `EvField` added to `inbox-page.jsx`; seven named marker
paths (loading / auth-403-no-retry / network-retry / 404-retry / gone-terminal /
degraded-retry / body); per-kind body renderers for `proposal`, `email`, `customs`,
`proforma_draft`, `unknown`; `customs.next_action` rendered as title + priority badge
(explicitly not `[object Object]`); `summary` true-flags only; thread lineage rendered.

The no-leak posture is specific: named forbidden fields (`body_html`, `body_text`,
`attachments`, `cc`, `bcc`, `matched_identifiers`, full line JSON). CSS custom-property
constraint named. `data-testid` coverage confirmed.

The GATE 6 verification record is specific: 10 named scenarios verified (4 kinds + gone +
degraded + 404 + 403 + network + Close), specific behaviours confirmed for each (customs
`next_action` title + HIGH badge confirmed not undefined/NaN; auth no-retry confirmed; Close
removes panel and deselects row). A real harness defect was diagnosed and fixed (unpkg
@babel/standalone react-preset automatic→classic JSX runtime conflict), with clear causal
attribution that production code was never at fault.

**Deduction (−1):** GATE 6 verification was self-performed with screenshot tooling timed
out twice, falling back to DOM-text + a11y-tree assertions. The specific evidence artifacts
(accessibility snapshot, DOM-text output) are described but not quoted in the campaign report.
An independent reviewer cannot validate the claimed console-zero-errors result without the
raw capture. Specificity at the gate-compliance level is weaker than at the implementation
level.

---

### 2. Coverage (3/5)

**Assessment: ACCEPTABLE — with governance gap**

**What was covered:**
- Implementation coverage: all seven marker paths, all four per-kind bodies, no-leak
  posture, CSS custom properties, data-testid coverage, ADR-028 transport pattern
  (EstrellaShared.apiFetch, URL-encoded id, never raw fetch, never write verb)
- Test coverage: 14 source-grep tests in `test_c03_inbox_evidence_panel.py`, all green
- GATE 2: live `gh pr list` confirmed 0 open PRs before opening #621 — gate honored
- GATE 1: tests green, browser verified, only 2 intended files changed — gate confirmed
- PATH GUARD: honored throughout (no retired-clone reads in this campaign)
- Harness defect investigation: real regression discovered and diagnosed (babel preset),
  production code exonerated

**Coverage gaps:**

**Gap 1 — reviewer-challenge not dispatched on a Lesson F/M V2 page (material).**
CLAUDE.md Lesson F states: "Reviewer-challenge MUST fire on any V2 PR automatically." Lesson
M states: "reviewer-challenge must flag any capability suppression." The inbox-page.jsx change
is a V2 page PR by definition. reviewer-challenge was not invoked. The V2 governance rules
make this dispatch mandatory, not advisory. No waiver or escalation was recorded to explain
the omission.

**Gap 2 — frontend-flow-reviewer not dispatched.**
CLAUDE.md Lesson M reviewer enforcement checklist calls for `frontend-flow-reviewer` to
verify that planned operator-visible capabilities are not suppressed or removed. Inbox V2
adds new capability (EvidencePanel); the reviewer is used to confirm capability surfaces are
correct and complete. Not dispatched; no disclosure.

**Gap 3 — GATE 6 self-performed without browser-verifier subagent.**
GATE 6 as stated in CLAUDE.md requires browser flow testing end-to-end with console errors
checked and network requests verified. A dedicated `browser-verifier` subagent exists in the
registry and is the standard mechanism for this gate. The orchestrator performed GATE 6 via a
static harness (stubbed list + evidence endpoint). This is not equivalent to a deployed
endpoint smoke; it is a harness simulation. See §Evidence for the rigour assessment.

**Gap 4 — no backend-safety-reviewer pass for the consumption-side contract.**
While E3a's backend was reviewed (PR #614 scorecard), E3b's consumption layer — particularly
the client-side URL-encoding of `item_id`, the no-raw-fetch posture, and the ADR-028
compliance of the fetch path — received no independent review. For a pure frontend PR this is
less critical than for a backend PR, but the omission is worth noting given the established
pattern of multi-agent verification on V2 pages.

**Mitigating factor:** The implementation is frontend-only (read-only, no writes, no new
auth rules). The blast radius of a frontend rendering defect is lower than a backend data
exposure or schema change. The SOLO execution model was described as operator-authorized. Even
so, the mandatory-auto-fire language in Lesson F is unconditional.

**Score (3):** Acceptable — implementation coverage is thorough, but two mandatory gate
agents (reviewer-challenge, as required by Lesson F) were not invoked and no waiver was
recorded. This is a structural coverage gap regardless of the low blast-radius context.

---

### 3. Severity calibration (4/5)

**Assessment: STRONG**

The campaign correctly treated this as a frontend-only, read-only PR with no backend
changes, no new auth rules, no schema mutations, and no raw evidence field exposure beyond
the endpoint's own projection. The risk profile of the work is accurately described: the
blast radius is limited to the rendering layer of inbox-page.jsx.

The harness defect discovered during GATE 6 (babel preset JSX runtime conflict) was correctly
diagnosed as a harness/development environment issue, not a production code defect. The
severity triage ("production code was never at fault") is accurate and well-explained.

The governance gap (absence of reviewer-challenge on a V2 page) was identified in the
campaign context as "a quality signal worth scoring" — this is appropriate self-awareness.
It is not described as "not a big deal" or dismissed. The calibration is honest.

**Deduction (−1):** The one calibration weakness is the implicit treatment of "SOLO,
operator-authorized" as sufficient to waive Lesson F's mandatory-auto-fire rule. That
lesson does not provide a solo-execution exception. Framing a mandatory gate as "a quality
signal worth scoring after the fact" rather than as a blocking requirement before PR open
represents a mild severity underestimate of the governance debt incurred. Not a critical
miscalibration — it is surfaced honestly — but it deserved a stronger label at the time
(GATE 1 precondition not fully satisfied; should have been treated as a BLOCK trigger,
with the operator explicitly authorizing the waiver).

---

### 4. Actionability (4/5)

**Assessment: STRONG**

The implementation deliverables are concretely actionable: the EvidencePanel is
production-ready per the record (all 7 marker paths, no-leak posture, full data-testid
coverage, CSS custom properties, 14 green tests). A deploy engineer reading the campaign
report could proceed to the 7-agent deploy gate with no ambiguity about what shipped.

The GATE 6 verification record translates into a specific statement: 10 scenarios confirmed,
Close removes panel and deselects row, zero console errors, customs badge renders correctly.

The harness defect is documented with a precise fix path (force classic runtime in harness
bootstrap) and an explicit clearing of production code — this is actionable for any future
harness operator.

**Deduction (−1):** The governance gap (no reviewer-challenge, no frontend-flow-reviewer)
is surfaced in the campaign context but does not translate to a concrete GATE 4 disposition
within the campaign record. The observation is: "this ran without reviewer-challenge — worth
scoring." The GATE 4 disposition (SCHEDULED / ISSUE / REJECTED for the missed mandatory
dispatch) should appear in the campaign's own closure record, not deferred entirely to the
scorecard. The current state leaves the governance debt unresolved pending this scorecard.
This scorecard records it as GATE 4 below.

---

### 5. Substitution honesty (2/5)

**Assessment: WEAK**

This is the critical governance dimension for this campaign.

GATE 5 requires: when a named agent is substituted (or omitted), the substituting agent
must be named explicitly, capability equivalence must be stated, and the registry mismatch
must be logged. The inverse applies: when a mandatory agent is simply not dispatched (rather
than substituted), GATE 5's spirit requires at minimum disclosure of the omission and a
waiver or escalation to the operator.

In this campaign:
- **reviewer-challenge** was not dispatched and not substituted. CLAUDE.md Lesson F states
  it MUST fire on any V2 PR automatically. No capability-equivalent agent was named. No
  disclosure of the omission appeared in the campaign record. No operator waiver was
  recorded before PR open.
- **frontend-flow-reviewer** was not dispatched and not disclosed as omitted.
- **browser-verifier** was not dispatched. The orchestrator self-performed GATE 6 via a
  static harness, but did not explicitly state "browser-verifier was not dispatched; the
  orchestrator substituted a static harness with the following capability-equivalence
  statement: ..." This is a GATE 5 substitution disclosure gap.

The campaign context acknowledges the omission retroactively ("this ran without
reviewer-challenge — note whether the self-performed verification was nonetheless rigorous
enough to satisfy the gate's intent"). Retroactive acknowledgement is better than silence,
but GATE 5 requires prospective disclosure and explicit capability-equivalence statements
before the PR is opened, not post-hoc scoring notes.

**Score (2):** Two mandatory agents omitted without prospective disclosure or
capability-equivalence statements. Browser-verifier functionally substituted (orchestrator
harness) without explicit GATE 5 disclosure. The campaign context names the omission after
the fact; GATE 5 requires disclosure before PR open.

**Note on mitigation:** The self-performed GATE 6 verification was substantively rigorous
(10 scenarios, real harness defect found and fixed, accessibility snapshot). The absence of
a browser-verifier subagent does not mean GATE 6 was superficial. However, rigour and
disclosure are orthogonal requirements — a rigorous unannounced substitution still fails
the disclosure gate.

---

### 6. Evidence quality (4/5)

**Assessment: STRONG**

The evidence record for the implementation itself is strong:
- 14/14 tests passing, test file named (`test_c03_inbox_evidence_panel.py`), 14 source-grep
  tests described as covering the panel structure
- 10 GATE 6 scenarios named and described with specific behaviour claims
- Harness defect: diagnosed with specific root cause (babel preset automatic→classic),
  specific fix confirmed, specific exoneration of production code
- No-leak posture: named forbidden fields list (not a vague "no raw fields")
- CSS constraint: named (custom properties only, no hardcoded hex)
- data-testid coverage: stated as full
- Customs badge: specific claim (title + HIGH badge, no [object Object]/undefined/NaN)

**Deduction (−1):** Screenshot tooling timed out twice; the fallback evidence (DOM-text +
a11y-tree assertions) is described but not quoted in the campaign report. The console-zero-
errors claim is unverifiable without a raw console capture. The accessibility snapshot is
described as "captured as proof" but not quoted. For a gate that explicitly requires
"Console errors checked (no new red entries)" (GATE 6 language), the evidence artifact
should be quotable in the record. The evidence is honest about its limitations (timeout
disclosed), which is valuable — but the limitation is a limitation on verifiability.

---

### 7. Environment honesty (4/5)

**Assessment: STRONG — notable improvement over prior campaigns**

This campaign is **PATH GUARD compliant**, which marks a significant improvement over the
prior E3a campaign (both agents scored 2/5 on Environment for operating on the retired
scratch clone). The campaign context states: "PATH GUARD honored throughout."

The GATE 6 browser verification was performed via a static harness, not against the deployed
production endpoint at C:\PZ — this is disclosed and appropriate for a frontend-only change
pending deploy gate. The harness environment is described clearly (stubbed list + evidence
endpoint).

The working tree for implementation is the current branch on the scratch clone
(`C:\Users\Super Fashion\PZ APP`, which is the git repo context for the session), but the
scorecard explicitly requires production file reads to use C:\PZ-verify. For implementation
work (writing new code, not verifying existing production files), operating from the local
branch is correct and expected. The PATH GUARD applies to verification reads and git
operations, which the campaign states were honored.

**Deduction (−1):** The campaign context does not explicitly state the branch tip commit SHA
at which the implementation was completed and submitted. "squash commit 2144c0b" is the
merge SHA, but the pre-merge branch tip is not recorded. For full environment auditability,
the campaign record should include: working tree path for implementation, branch tip SHA
at PR-open time, and confirmation that `C:\PZ-verify` was used for any cross-checks (if
any were performed). The record is honest and largely complete but lacks this one
traceability element.

---

## Weak-verdict warnings

### orchestrator (solo) — ACCEPTABLE (25/35)

**Overall assessment:** The implementation quality is high — the EvidencePanel is
production-ready per the record, GATE 2 was honored, PATH GUARD was honored, tests are
green, and GATE 6 verification was substantively rigorous despite tooling limitations. The
ACCEPTABLE verdict reflects a governance discipline gap, not an implementation quality gap.

**Primary failed/weak dimension: Substitution honesty (2/5)**

This is the structural weakness. Two mandatory agents (reviewer-challenge, frontend-flow-
reviewer) were not dispatched and not disclosed as omitted before PR #621 was opened. One
agent (browser-verifier) was functionally substituted by an orchestrator-run static harness
without an explicit GATE 5 capability-equivalence statement.

The Lesson F rule is unconditional: "Reviewer-challenge MUST fire on any V2 PR automatically."
There is no solo-execution exception in the governance language. GATE 1 language requires
"Every named subagent has returned a verdict block (or explicitly failed dispatch with
disclosure)" before a PR may be opened — the GATE 1 precondition for V2 PRs includes
reviewer-challenge by Lesson F.

**Excerpt from the campaign context that illustrates the gap:**
> "EXECUTION MODEL: SOLO — this was a direct single-thread implementation by the orchestrator.
> NO domain subagents were dispatched (no frontend-ui, no browser-verifier, no reviewer-
> challenge, etc.). This is itself a quality signal worth scoring."

The quality signal is being scored here as a GATE 4 finding.

**Secondary weak dimension: Coverage (3/5)**

Reviewer-challenge and frontend-flow-reviewer omission creates a structural coverage gap
for Lesson F/M territory. The implementation coverage is thorough; the review coverage is
not. These are different dimensions — an implementer cannot fully substitute for an
adversarial reviewer.

**GATE 4 disposition required** (RULE 6 — Coverage and Substitution gaps):

**Finding 1 — Reviewer-challenge mandatory auto-fire gap on V2 PRs in SOLO mode**
- **Nature:** Governance — Lesson F unconditional rule not applied in SOLO execution context
- **Risk:** A future V2 PR implemented in SOLO mode may suppress capability (Lesson M
  violation), introduce a layer-blurring pattern (Lesson F §5), or import V1 logic into V2
  without adversarial detection
- **DISPOSITION: SCHEDULED** — Before the next SOLO-mode V2 frontend PR opens, the
  orchestrator must either: (a) dispatch reviewer-challenge as a subagent before PR open,
  OR (b) record an explicit operator waiver naming the specific Lesson F rule being waived,
  the capability-equivalence analysis for the omission, and the residual risk accepted. A
  retroactive note in the campaign context is not sufficient. Target: apply to next V2 page
  PR (E3c or any subsequent inbox-page.jsx / V2 static file change).

**Finding 2 — GATE 5 browser-verifier substitution not prospectively disclosed**
- **Nature:** Process — GATE 6 was satisfied by substance (rigorous 10-scenario harness
  verification) but the substitution was not disclosed prospectively per GATE 5 requirements
- **Risk:** If future GATE 6 self-performance is less rigorous (timeout-only fallback,
  no DOM text), the absence of a disclosure protocol means the gap may not be caught
- **DISPOSITION: SCHEDULED** — Add to SOLO-mode V2 PR checklist: explicit GATE 5
  statement naming browser-verifier as the substituted agent, the harness as the substitute,
  and the scope of scenarios covered. Target: same session as Finding 1 resolution.

---

## Repeated failure hints

**5 most recent campaign scorecards reviewed:**
1. 2026-06-16: `2026-06-16-pr614-inbox-evidence-e3a.md` — backend-safety-reviewer NEEDS-TUNING (23), reviewer-challenge EXEMPLARY (32)
2. 2026-06-15: `2026-06-15-deploy-gate-d37316e-wfirma-grammar.md` — deploy-lead-coordinator ACCEPTABLE (27); 6 others EXEMPLARY
3. 2026-06-15: `2026-06-15-pr522-merge-gate-wfirma-grammar.md` — 3 agents, all EXEMPLARY
4. 2026-06-14: `2026-06-14-pr585-529-price-source-authority.md` — all agents EXEMPLARY
5. 2026-06-14: `2026-06-14-pr582-deploy-gate.md` — all agents EXEMPLARY/ACCEPTABLE

**Orchestrator-as-solo-verifier:** First instance of a SOLO execution model in the
scorecard record. No prior baseline for orchestrator self-verification campaigns. The
ACCEPTABLE verdict reflects a governance gap specific to this execution model, not a
pattern. However, the finding is important: if SOLO execution becomes a repeated pattern for
V2 frontend PRs, the Lesson F mandatory-auto-fire rule will be systematically bypassed.

**backend-safety-reviewer:** Single NEEDS-TUNING instance (E3a, 2026-06-16). No repeat.
SCHEDULED disposition recorded in E3a scorecard. No REPEATED-WEAK flag (threshold: ≥2 in
6 runs).

**deploy-lead-coordinator:** ACCEPTABLE in 2 of 5 recent scorecards (d37316e and pr573).
Pattern noted in prior scorecards. Not new; does not meet REPEATED-WEAK threshold (requires
NEEDS-TUNING or UNRELIABLE, not ACCEPTABLE). Monitoring continues.

**No REPEATED-WEAK flags triggered** for any agent in this campaign.

---

## Self-evaluation cadence check

**Most recent self-eval:** `self-eval-2026-06-15.md` (written 2026-06-15)
**Calendar days elapsed:** 1 (threshold: 7)
**SELF-DEGRADATION DETECTED in that file:** YES (Environment honesty dimension, 2/5)
**Campaign scorecards since SELF-DEGRADATION flag:**
  - Run 1: 2026-06-16-pr614-inbox-evidence-e3a.md (E3a backend)
  - Run 2: this scorecard (E3b frontend) ← current
  - Counter: 2 of 3 needed to trigger

**Self-evaluation NOT triggered.** Calendar threshold not met (1 day); SELF-DEGRADATION
counter at 2 of 3. Next self-eval triggers at the 3rd campaign scorecard after 2026-06-15
OR on 2026-06-22, whichever comes first.

---

## Campaign quality summary

**Implementation quality:** HIGH. The EvidencePanel deliverable is well-specified, all seven
marker paths are handled, no-leak posture is enforced via a named forbidden-field list, CSS
custom properties used throughout, data-testid coverage confirmed, ADR-028 transport pattern
followed. The harness defect (babel preset JSX runtime) was a real discovery that validated
the investigation rigour. Production code was exonerated cleanly.

**Governance quality:** ACCEPTABLE with a clear weakness. The SOLO execution model produced
a rigorous implementation but bypassed the mandatory-auto-fire governance layer (Lesson F
reviewer-challenge). The bypass was acknowledged in the campaign context but not treated as
a GATE 1 blocking condition at the time. The two SCHEDULED GATE 4 dispositions above close
the governance debt for this campaign.

**GATE 6 substance vs form:** The self-performed GATE 6 was substantively strong (10
scenarios, real defect caught, accessibility snapshot). The formal gap is the absence of a
prospective GATE 5 disclosure for the browser-verifier substitution. Future SOLO-mode V2
PRs should front-load this disclosure.

**Production status:** PR #621 merged to main at 2144c0b. Production unchanged pending
7-agent deploy gate. The merge is clean; the deploy gate will catch any remaining concerns.

---

**Total "agents" scored:** 1 (orchestrator in solo-verifier role)
**EXEMPLARY:** none
**ACCEPTABLE:** orchestrator (solo) — 25/35
**NEEDS-TUNING:** none
**UNRELIABLE:** none
**Repeated-weak flags:** none
**GATE 4 dispositions added by this scorecard:** 2 (both SCHEDULED)
**Self-evaluation:** skipped (run 2 of 3 since SELF-DEGRADATION flag; calendar day 1 of 7)
