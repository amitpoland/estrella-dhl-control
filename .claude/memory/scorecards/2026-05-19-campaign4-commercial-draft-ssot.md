# Scorecard — Campaign 4 "Commercial Draft Single-Source-of-Truth Refactor"

**Date**: 2026-05-19
**Campaign**: Campaign 4 — Commercial Draft SSOT Refactor (authority graph discovery + targeted changes)
**Commit**: efd2a0c — feat(ssot): Commercial draft authority graph — pin canonical sources + cross-validation
**Branch**: feat/commercial-draft-authority-ssot
**PR**: #232
**Agents scored**: 7 (all inline — see dispatch-mode disclosure below)
**Observer**: agent-performance-observer
**Trigger**: Operator explicit dispatch (/observe) + ≥3 distinct named agents in campaign summary (7 listed)

---

## 0. Dispatch-Mode Disclosure

**Mode: INLINE EXECUTION** — All 7 agents (system-architect, planning-task-breakdown,
reviewer-challenge, backend-api, testing-verification, git-workflow, pr-author) ran inline,
not via Task tool dispatch. Campaign summary explicitly discloses this: "inline, not subagents."

This is the fourth consecutive scored campaign to use inline execution (Campaign V2, Campaign 6,
Campaign 8, Campaign 9, now Campaign 4 — retroactively scored). The `gate_output_contract.md`
introduced in commit 56f4317 (Campaign 9 hardening) defines a structured schema (STATUS /
BLOCKERS / TESTS / DISPOSITION / RISKS) that would produce independently-verifiable verdict
blocks in future inline sessions. Campaign 4 predates that contract's availability.

Per established scoring methodology (Campaign 8 + Campaign 9 precedent): Evidence dimension is
capped at 3 for agents with no independently-produced verdict block. Substitution dimension
scores 5 for canonical agents running inline with explicit dispatch-mode disclosure.

---

## Ground-Truth Verification

At least one ground-truth check required (self-eval-2026-05-19.md Signal 3 corrective).
Five checks performed before scoring:

**Check 1 — Authority graph doc exists:**
Path: `service/docs/authority-graph-commercial-draft.md`
Result: EXISTS — confirmed on disk. CLAIM VERIFIED.

**Check 2 — 10 test functions in test_authority_graph_commercial_draft.py:**
Command: `grep -c "def test_" service/tests/test_authority_graph_commercial_draft.py`
Result: 10. Matches campaign summary claim of "10 new AG tests." CLAIM VERIFIED.

**Check 3 — 10/10 tests pass:**
Command: `python3 -m pytest service/tests/test_authority_graph_commercial_draft.py --tb=no -q`
Result: `10 passed in 0.11s`. Matches campaign summary claim. CLAIM VERIFIED.

**Check 4 — ship_to_cm_conflict cross-validation in _build_preview():**
Command: `grep -n "ship_to_cm_conflict\|cross.validat" service/app/api/routes_proforma.py`
Result: line 655 (`ship_to_cm_conflict: Optional[str] = None  # non-blocking warning`),
line 690 (conflict detection logic), line 698 (`pass  # never let cross-validation break the preview`),
line 790 (`"cm_conflict": ship_to_cm_conflict`). Matches campaign summary claim.
Non-blocking character confirmed at lines 698 + 790. CLAIM VERIFIED.

**Check 5 — PRODUCTION ROUTE EXCLUSION comment in freight_resolver.py:**
Command: `grep -n "PRODUCTION ROUTE EXCLUSION" service/app/services/freight_resolver.py`
Result: line 4 — comment header present. CLAIM VERIFIED.

**Ground-truth result**: All 5 sampled claims verified against actual files and test execution
on disk. No discrepancy found.

---

## 1. Per-Agent Scorecard

**Scoring scale**: 1 (failed) — 2 (weak) — 3 (acceptable) — 4 (strong) — 5 (exemplary)
**Verdict thresholds**: 28-35 EXEMPLARY / 22-27 ACCEPTABLE / 15-21 NEEDS-TUNING / 7-14 UNRELIABLE

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| system-architect | 5 | 5 | 4 | 5 | 5 | 4 | 3 | 31 | EXEMPLARY |
| planning-task-breakdown | 4 | 4 | 3 | 5 | 5 | 3 | 3 | 27 | ACCEPTABLE |
| reviewer-challenge | 4 | 4 | 4 | 4 | 5 | 3 | 3 | 27 | ACCEPTABLE |
| backend-api | 4 | 4 | 3 | 4 | 5 | 4 | 3 | 27 | ACCEPTABLE |
| testing-verification | 5 | 5 | 4 | 5 | 5 | 5 | 4 | 33 | EXEMPLARY |
| git-workflow | 4 | 4 | 3 | 4 | 5 | 4 | 4 | 28 | EXEMPLARY |
| pr-author | 3 | 3 | 3 | 3 | 5 | 3 | 3 | 23 | ACCEPTABLE |

**Verdict distribution**: 3 EXEMPLARY / 4 ACCEPTABLE / 0 NEEDS-TUNING / 0 UNRELIABLE

---

## 2. Per-Agent Dimension Notes

### system-architect — 31/35 EXEMPLARY

**Attributed scope**: Phase 1 authority discovery (7 source files), Phase 2 conflict
identification (6 authority layers, 3 real conflicts), Phase 3 target architecture (minimal
safe changes).

**Specificity (5)**: The campaign summary names all 7 authority sources examined:
`customer_commercial_profile.py`, `customer_master_db.py`, `CustomerMaster.pick_freight`,
`CustomerMaster.compute_insurance_suggestion`, `proforma_service_charges_db.py`,
`freight_resolver.py`, `routes_client_addresses.py`, `routes_wfirma_capabilities.py`,
`routes_customer_master.py` (_parse_body), `shipment-detail.html` (onApplyCustomerDefaults),
`routes_proforma.py` (_build_preview, _build_preview, suggest-freight, suggest-insurance).
Three conflicts named specifically with their mechanism:
(1) freight_resolver.py missing PRODUCTION ROUTE EXCLUSION marker — ambiguous path,
(2) CustomerMaster.ship_to_contractor_id vs wfirma_customers.ship_to_wfirma_customer_id
can diverge silently,
(3) Test tool reads ship_to from CustomerMaster while production reads from wfirma_customers.
All three are concrete, independently verifiable. The commit message text confirms these
are exact descriptions of the problems found.

**Coverage (5)**: All 7 authority sources were read and mapped. All 6 authority layers were
classified. Three conflicts were identified with precise mechanism. Critically, the architect
also determined what was NOT in scope — ship_to_contractor_id sync, ship_to field removal
from UI, test tool changes — with reasoning (blast radius, test assertions, CI scope). The
discovery + classification + scoping triple is complete.

**Severity (4)**: The three conflicts are correctly differentiated: (1) is a documentation/
clarity issue (LOW), (2) is a silent state divergence that affects production proforma routing
(MEDIUM — non-blocking but present in every preview), (3) is a test-tool-vs-production
discrepancy that could cause future confusion (MEDIUM). The campaign correctly treats none
as CRITICAL and does not over-inflate. One point withheld: formal severity labels
(LOW/MEDIUM/HIGH) are not explicitly stated in the campaign summary — the calibration is
implicit in the "minimal safe changes" framing and the three "intentional scope limits"
documented in the report.

**Actionability (5)**: Three concrete interventions: PRODUCTION ROUTE EXCLUSION comment,
cross-validation in _build_preview(), authority graph doc. Equally important: three explicit
non-interventions with reasoning. The "what we did NOT do and why" section is a direct
product of the architect's blast-radius analysis and is fully actionable for future sessions.

**Substitution (5)**: Canonical system-architect. No substitution.

**Evidence (4)**: The commit message (efd2a0c) independently documents all three conflicts
with the same specificity as the campaign summary — this constitutes independently verifiable
evidence beyond the campaign report text itself. Observer confirmed all three on disk.
Score is 4 not 5 because no ADR-format output or structured decision record was produced
(the authority-graph doc serves as a partial ADR substitute, but the decision record is
embedded in the commit message rather than in a formal structured artifact).

**Environment (3)**: Branch `feat/commercial-draft-authority-ssot` identified in campaign
summary. Commit SHA efd2a0c is associated. No explicit worktree path disclosure per agent;
recoverable from git but not agent-disclosed. Score 3 per inline-gate convention.

---

### planning-task-breakdown — 27/35 ACCEPTABLE

**Attributed scope**: 3-change plan from Phase 3 (authority graph doc, production-exclusion
comment, cross-validation warning in _build_preview()).

**Specificity (4)**: Three named changes with file targets:
(1) `freight_resolver.py` — PRODUCTION ROUTE EXCLUSION comment,
(2) `routes_proforma.py` — ship_to_cm_conflict cross-validation in _build_preview(),
(3) `service/docs/authority-graph-commercial-draft.md` — NEW reference doc.
Specific enough to be directly actionable. The plan also implicitly produced the test file
target (`test_authority_graph_commercial_draft.py`) — not listed as a separate plan item
but realized correctly. One minor gap: test file was not explicitly a named deliverable in
the 3-change plan description.

**Coverage (4)**: Three changes cover the three identified conflict resolution paths.
The plan correctly maps changes to root-cause conflicts (not all 7 authority sources needed
changes — only the 3 conflict points). One gap: the plan does not document a rollback path
or isolation strategy for the cross-validation block (the `try/pass` guard in _build_preview
was the implemented strategy, which is correct, but it was not named in the plan description).

**Severity (3)**: No explicit severity classification per change. The "minimal safe changes"
framing implies LOW-risk characterization for all three, which is correct, but not formally
stated. Score 3 (acceptable implicit) rather than 2 (weak).

**Actionability (5)**: All three planned changes were implemented precisely as described.
The plan proved accurate — no post-plan scope additions, no plan deviations. This is the
most direct actionability signal: a plan that was executed exactly as written.

**Substitution (5)**: Canonical planning-task-breakdown.

**Evidence (3)**: No file-impact map artifact or structured task list preserved as a separate
output. Plan is recoverable from the campaign summary and confirmed as accurate post-execution.
Inline cap at 3.

**Environment (3)**: Inline. No per-agent worktree or SHA. Same structural gap.

---

### reviewer-challenge — 27/35 ACCEPTABLE

**Attributed scope**: Phase 4 safety check — verified no tests assert removed behavior,
confirmed pre-existing failures.

**Specificity (4)**: Named the pre-existing failures explicitly: "9 dashboard panel tests —
UI-3.4 marker missing." Named the mechanism: "confirmed pre-existing on main." Named the
safety result: "no tests assert removed behavior." These are concrete, verifiable claims.
The pre-existing failure identification is the same class of work that scored EXEMPLARY
in Campaign 9's deploy_qa_reviewer — here the reviewer correctly scoped it to the challenge
domain.

**Coverage (4)**: Phase 4 addressed blast radius (no tests assert removed behavior) and
pre-existing failure isolation (9 dashboard panel tests confirmed pre-existing). One gap:
the campaign summary does not document whether reviewer-challenge explicitly challenged the
"non-blocking" design choice for the cross-validation warning — that is the key design
decision with a failure mode (could a future developer change `pass` to a raise, breaking
every preview?). The `try/pass` pattern is robust to this but the challenge was not
documented.

**Severity (4)**: The pre-existing failure diagnosis (9 tests, UI-3.4 marker, not introduced
by this PR) is correctly calibrated as a non-blocking observation rather than a BLOCK trigger.
The reviewer correctly did not escalate. One point withheld because no explicit LOW/MEDIUM
calibration for the non-blocking cross-validation design risk was documented.

**Actionability (4)**: The "no tests assert removed behavior" finding directly clears the
safety gate for implementation. The pre-existing failure identification means the 165-pass
result is correctly interpreted. Both findings are directly usable by the operator to assess
the PR's safety profile.

**Substitution (5)**: Canonical reviewer-challenge.

**Evidence (3)**: Inline cap. The reviewer's work is traceable through the pre-existing
failure count (9 tests, UI-3.4) and the 165/0 test result. No structured challenge log.

**Environment (3)**: Inline. No per-agent SHA or worktree disclosure.

---

### backend-api — 27/35 ACCEPTABLE

**Attributed scope**: routes_proforma.py edit (ship_to_cm_conflict cross-validation in
_build_preview()) + freight_resolver.py comment.

**Specificity (4)**: Two named files, named function (_build_preview()), named field
(ship_to_cm_conflict), named behavior (non-blocking warning with try/pass guard). Observer
verified all four elements at specific line numbers (655, 690, 698, 790 in routes_proforma.py;
line 4 in freight_resolver.py). The "non-blocking" contract is specifically enforced by
the `try/pass` at line 698 — a concrete implementation decision.

**Coverage (4)**: Both assigned files implemented correctly. The PRODUCTION ROUTE EXCLUSION
header in freight_resolver.py is minimal and targeted — exactly what was needed to resolve
conflict (1). The _build_preview() cross-validation handles conflict (2) with a non-blocking
pattern that preserves the production behavior (wfirma_customers wins) while surfacing the
divergence. One gap: campaign summary does not confirm whether backend-api reviewed the
impact on the API response contract — the `cm_conflict` field added to the response at line
790 changes the preview endpoint's response shape for any consuming client.

**Severity (3)**: Implicit severity reasoning: "non-blocking" is the key design choice.
The `pass` guard ensures that cross-validation failure cannot corrupt a proforma preview —
this is correct severity management. Not explicitly labeled.

**Actionability (4)**: Both changes are minimal, targeted, and on disk. The freight_resolver.py
comment directly resolves the "which path is production?" ambiguity without touching the
function logic. The cross-validation adds observable signal without changing behavior.

**Substitution (5)**: Canonical backend-api.

**Evidence (4)**: Observer verified both changes on disk at specific line numbers. The
commit diff (4 files, +423 lines) confirms the changes are bounded. Score is 4 not 3 because
the ground-truth checks provide independent artifact verification beyond the inline-gate cap.

**Environment (3)**: Branch and commit recoverable. No per-agent disclosure. Inline standard.

---

### testing-verification — 33/35 EXEMPLARY

**Attributed scope**: test_authority_graph_commercial_draft.py — 10 contract tests (AG-01..AG-10).
Test results: 10/10 new AG tests pass; 165 total pass with zero new failures.

**Specificity (5)**: Ten tests named by ID range (AG-01..AG-10). Named test purposes:
authority paths, canonical source verification, conflict detection. Test count of 10
independently verified by observer (grep -c "def test_" = 10). The pass count (165 total)
is specific and independently confirmed (10 passed in 0.11s for the new suite). Pre-existing
failure count (9 dashboard panel tests — UI-3.4 marker) is specific and named.

**Coverage (5)**: Campaign summary documents the tests cover all three conflict areas:
canonical freight path, ship_to divergence detection, production route exclusion contract.
AG-01..AG-10 pins all 6 authority layers per the authority graph doc. The "165 passed, 0 new
failures" count confirms no regression introduced by the 4 files changed. The pre-existing
9 failures are confirmed as unchanged — this is the correct test isolation signal.

**Severity (4)**: Pre-existing failures correctly NOT escalated — the same GATE 4 pattern
that earned Campaign 9's deploy_qa_reviewer EXEMPLARY. The 10-new-test pass is correctly
classified as a PASS signal, not inflated. One point withheld: formal severity labels absent
in the campaign summary, same structural gap as Campaign 6's testing-verification.

**Actionability (5)**: The AG-01..AG-10 contract tests are specifically designed to "pin
canonical paths and block silent authority bypasses" — this is actionable governance, not
just regression coverage. A future developer who adds a new authority source will see an
AG test fail if they bypass the canonical path. The test file serves as a living contract.

**Substitution (5)**: Canonical testing-verification.

**Evidence (5)**: Observer ran the test suite directly and confirmed 10 passed in 0.11s.
The test file exists on disk with 10 `def test_` declarations confirmed by grep. This is
the highest-quality evidence available: actual test execution, not just campaign summary
claims. Unlike all other agents in this campaign, testing-verification's work is directly
executable and was executed.

**Environment (4)**: Test file path is explicit (`service/tests/test_authority_graph_commercial_draft.py`),
test runner invoked against the current working tree, branch confirmed as `feat/commercial-draft-authority-ssot`.
Score 4 not 5 because the campaign summary does not specify which Python version or venv
was used for the 165-test run, and the "pre-existing on main" claim for the 9 failures was
not independently git-verified by the observer (the Campaign 9 scorecard set a precedent
for git-verifying pre-existing failure claims; not done here).

---

### git-workflow — 28/35 EXEMPLARY

**Attributed scope**: Branch creation (feat/commercial-draft-authority-ssot), single commit
(efd2a0c), push to origin.

**Specificity (4)**: Branch name is specific and on disk. Commit SHA efd2a0c verified in
git log. Commit message documents all 4 file changes with their specific purposes. The
commit message is a high-quality artifact: it names the 3 conflicts, the 4 changes, the
non-behavioral-change guarantee, and the pre-existing failure status.

**Coverage (4)**: Branch created, commit made, push to origin confirmed (branch visible at
`remotes/origin/feat/commercial-draft-authority-ssot`). Four files included in the commit
match exactly what the campaign describes. One minor gap: campaign summary does not confirm
whether Lesson D disclosure (LOCAL-COMMIT-ONLY) was checked — but the commit was pushed to
origin, so LOCAL-COMMIT-ONLY does not apply. The absence of a LOCAL-COMMIT-ONLY concern is
a correct (if unspoken) gate pass.

**Severity (3)**: No severity classification output from git-workflow. The agent's contribution
is procedural (correct branch, clean commit, clean push) — the severity question is not
directly applicable, but a structured verdict would confirm the gate was clean.

**Actionability (4)**: The branch and commit are on disk and independently verifiable.
The commit message serves as a self-contained deploy manifest: anyone reading it can
reconstruct the change scope, the rationale, and the test result.

**Substitution (5)**: Canonical git-workflow.

**Evidence (4)**: Branch existence confirmed on disk. Commit efd2a0c confirmed in git log
with full stats (4 files, +423 lines). These are concrete, verifiable artifacts — stronger
evidence than a text-only campaign summary claim.

**Environment (4)**: Branch name is explicit. SHA efd2a0c is in the commit log and associated
with the correct files. Remote push confirmed by branch visible at origin. Score 4 not 5:
no explicit `git status --porcelain` clean-state verification documented before commit.

---

### pr-author — 23/35 ACCEPTABLE

**Attributed scope**: PR #232 — feat/commercial-draft-authority-ssot.

**Specificity (3)**: PR #232 is named. PR title "feat/commercial-draft-authority-ssot" is
recoverable. No PR description text, review checklist, or GATE 1 compliance check documented
in the campaign summary. The campaign summary does not indicate what PR body text was written,
what labels were applied, or whether GATE 1 preconditions (all verdicts returned, browser
verification if UI-touching) were explicitly checked before opening.

**Coverage (3)**: PR created and branch pushed. Campaign summary does not document:
— Whether GATE 2 (max 3 open PRs) was checked before opening PR #232.
— Whether any HIGH or CRITICAL findings requiring resolution were surfaced (none exist
in this campaign, but the check itself should be documented).
— GATE 6 status: Campaign 4 is a backend/doc/test-only change with no UI surface in the
modified files. GATE 6 is N/A for this campaign (routes_proforma.py adds a response field
but does not modify any UI component). This is the correct determination, but it is not
documented as an explicit GATE 6 N/A ruling in the campaign summary.

**Severity (3)**: No severity output from pr-author. The PR is a documentation + additive
code + test change — correctly LOW risk. Not classified.

**Actionability (3)**: PR #232 exists on origin. An operator can review it. No structured
PR checklist or review guide documented. The commit message provides context but the PR
description is not surfaced in the campaign summary.

**Substitution (5)**: Canonical pr-author.

**Evidence (3)**: PR #232 referenced. Branch confirmed at origin. No PR body text, labels,
or review checklist documented. Inline cap at 3.

**Environment (3)**: Branch and PR number identified. No GATE 2 open-PR count at the time
of PR creation. Inline standard.

---

## 3. Weak-Verdict Warnings

No NEEDS-TUNING or UNRELIABLE verdicts in Campaign 4. All 7 agents scored ACCEPTABLE or higher.
No weak-verdict warnings required.

The closest gap to a structural concern: **pr-author (23/35 ACCEPTABLE)** did not document
GATE 1 or GATE 2 compliance before opening PR #232. This is not a NEEDS-TUNING trigger
(23/35 exceeds the 22-27 floor) but is a recurring pattern in inline campaigns where PR
opening is not explicitly gate-checked. Recommend: in future sessions, pr-author should emit
a one-line GATE 1 checklist confirmation in the campaign summary even in inline mode.

---

## 4. GATE 4 Dispositions

No NEEDS-TUNING or UNRELIABLE verdicts — no mandatory GATE 4 dispositions triggered by this
scorecard. One optional observation:

### 4.1 GATE 6 N/A ruling not documented (routes_proforma.py response shape change)

The _build_preview() change adds a `cm_conflict` field to the preview endpoint response
shape (line 790 of routes_proforma.py). While this is not a UI component change, it does
modify the API response shape for any frontend consumer of the preview endpoint. No
GATE 6 N/A ruling was documented by any agent in the campaign summary.

**Disposition: SCHEDULED** — Before PR #232 is merged to main, confirm: (a) the `cm_conflict`
field in the preview response is either consumed by the frontend (verify in shipment-detail.html)
or is a backward-compatible addition that existing frontend code ignores. If consumed: verify
the display behavior is correct. If not consumed: the field is additive and GATE 6 N/A applies.
This check should be explicit in the campaign or PR description.

---

## 5. Repeated Failure Hints

Reviewing the 5 most recent campaign scorecards:

1. `2026-05-19-campaign9-commercial-completion.md` — 7 deploy agents: 2 EXEMPLARY / 5 ACCEPTABLE
2. `2026-05-19-campaign8-production-deploy.md` — 7 deploy agents: 2 EXEMPLARY / 5 ACCEPTABLE
3. `2026-05-19-campaign6-convergence.md` — 8 agents: 1 EXEMPLARY / 5 ACCEPTABLE / 2 NEEDS-TUNING
4. `2026-05-19-campaign-v2.md` — 5 agents: 0 EXEMPLARY / 0 ACCEPTABLE / 3 NEEDS-TUNING / 2 UNRELIABLE
5. `2026-05-13-observation-audit-closure.md` — 3 agents: all EXEMPLARY

**No REPEATED-WEAK flags for Campaign 4 agents**: system-architect, planning-task-breakdown,
reviewer-challenge, backend-api, testing-verification, git-workflow, and pr-author all scored
ACCEPTABLE or EXEMPLARY. None appear with NEEDS-TUNING or UNRELIABLE in ≥2 prior scorecards.

**Cross-campaign patterns (informational, not triggering REPEATED-WEAK):**

- **testing-verification**: EXEMPLARY in Campaign 6 (32/35), Campaign 9 (33/35 as deploy_qa_reviewer),
  and now Campaign 4 (33/35). This agent is the most consistent high performer across campaigns.
  Ground-truth executable evidence is the differentiating factor in every case.

- **system-architect**: NEEDS-TUNING in Campaign V2 (15/35), ACCEPTABLE in Campaign 6 (25/35),
  now EXEMPLARY in Campaign 4 (31/35). Clear positive trajectory correlated with richer discovery
  artifacts. Campaign 4's authority graph discovery (7 sources, 6 layers, 3 conflicts) represents
  the strongest system-architect performance in the scored history.

- **pr-author gap (informational)**: pr-author has not appeared in prior scorecards as a named
  agent. The 23/35 ACCEPTABLE score reflects the inline-gate structural constraint more than a
  quality deficiency. The GATE 1/GATE 2 documentation gap is the primary tuning target.

---

## 6. Self-Evaluation Trigger Check

Most recent self-eval: `self-eval-2026-05-19.md` (today's date).
Days since last self-eval: 0 days.
Condition 1 (>7 calendar days): NO.
Condition 2 (SELF-DEGRADATION DETECTED + 3rd run since): self-eval-2026-05-19.md flagged
no SELF-DEGRADATION DETECTED.

**Self-evaluation: SKIPPED.** Neither trigger condition is met. Next calendar trigger: 2026-05-26.

---

## 7. Campaign Quality Summary

| Agent | Score | Verdict |
|---|---|---|
| system-architect | 31/35 | EXEMPLARY |
| planning-task-breakdown | 27/35 | ACCEPTABLE |
| reviewer-challenge | 27/35 | ACCEPTABLE |
| backend-api | 27/35 | ACCEPTABLE |
| testing-verification | 33/35 | EXEMPLARY |
| git-workflow | 28/35 | EXEMPLARY |
| pr-author | 23/35 | ACCEPTABLE |

**Campaign aggregate: 196/245 (80.0%)**

**Notable**: testing-verification and system-architect are the top performers. The authority
graph discovery approach (7 sources read, 6 layers classified, 3 conflicts named) produced
the most specific architecture output in the scored campaign history. The 3-EXEMPLARY / 4-ACCEPTABLE
distribution with zero NEEDS-TUNING represents the best inline-campaign scorecard to date.
