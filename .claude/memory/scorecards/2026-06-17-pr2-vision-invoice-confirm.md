# Agent Performance Scorecard — PR-2 Vision Invoice Confirm Workflow (PR #647)

**Date:** 2026-06-17
**Observer:** agent-performance-observer (RULE 2 mandatory fire — 4 named GATE-1 subagents in Section 2)
**Campaign:** PR-2 authority bridge for AWB 2315714531 — Stage B operator-confirm endpoint
**Branch:** feat/pr2-vision-invoice-confirm-workflow @ 4429e04
**PR:** #647
**Scope:** Backend-only (no UI surface). New service function `confirm_vision_invoice()`, new route
  `POST /dashboard/batches/{batch_id}/vision-invoice/confirm`, 12 service tests +
  9 HTTP route tests. Customs/financial-adjacent (writes `audit["vision_invoice"]`).
**Outcome:** PR opened. All 4 GATE-1 reviewers returned verdicts. All HIGH/CRITICAL findings
  resolved inline (timeline race fixed; ghost identity removed; route-level HTTP tests added;
  traversal hardened). One HIGH (recheck_batch race) escalated correctly as GATE 4 ISSUE #646
  (pre-existing, out-of-scope). One MEDIUM (logistics role policy) noted to operator as
  precedent-aligned.
**Agents evaluated:** 4

---

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| reviewer-challenge | 4 | 4 | 4 | 4 | 5 | 3 | 3 | 27 | ACCEPTABLE |
| backend-safety-reviewer | 5 | 5 | 5 | 5 | 5 | 4 | 3 | 32 | EXEMPLARY |
| security-write-action-reviewer | 4 | 4 | 4 | 4 | 5 | 3 | 3 | 27 | ACCEPTABLE |
| test-coverage-reviewer | 5 | 5 | 4 | 5 | 5 | 4 | 3 | 31 | EXEMPLARY |

---

## Scoring rationale per agent

### reviewer-challenge (27 — ACCEPTABLE)

- **Specificity (4):** The campaign summary records the reviewer's aggregate PASS-WITH-CONCERNS
  verdict and the HIGH finding: the `recheck_batch` lock race. The lock-race concern is named
  at the mechanism level — it correctly identifies that `recheck_batch` may execute concurrently
  with `confirm_vision_invoice`, producing a whole-audit lost-update that overwrites the
  confirmed vision invoice state. That naming is specific enough to verify against the codebase.
  Minor deduction: the campaign report does not quote the reviewer's structured output block
  (3 assumptions, 3 failure scenarios, SPOF, question nobody asked) as required by the
  reviewer-challenge output contract. The reviewer's findings are reconstructable from the
  disposition record, but the structured contract items are absent from the cited evidence.

- **Coverage (4):** The verdict surface covers the primary risk for a new write-action endpoint:
  the concurrency/lock race across the batch_write_lock boundary. The idempotency of
  `confirm_vision_invoice` (idempotent per campaign description — already confirmed status
  returns early) was implicitly addressed by the PASS portion of the verdict. Minor coverage gap:
  the campaign report does not confirm whether reviewer-challenge independently verified the
  traversal guard (`/`, `\`, `..` rejection on batch_id), the 409/404/400 error mapping, or
  the `next_step` disclosure — all of which are GATE-1-relevant structural properties of the new
  endpoint. These may have been inside scope of the reviewer's CHECK but are not cited in the
  campaign summary's account of the reviewer's output.

- **Severity (4):** PASS-WITH-CONCERNS / HIGH for the recheck_batch race is well-calibrated.
  The race condition in question (a pre-existing whole-audit write on `recheck_batch` that would
  overwrite a newly-confirmed vision invoice state) is correctly assessed as HIGH rather than
  CRITICAL — the blast radius is bounded (would reset vision invoice to unconfirmed state on
  recheck, not corrupt audit permanently) and it is a pre-existing pattern, not introduced by
  this PR. Escalation to GATE 4 ISSUE #646 rather than blocking the PR is the correct severity
  call for a pre-existing, out-of-scope race. Minor deduction: the campaign summary does not
  show whether reviewer-challenge applied the LOW/MEDIUM/HIGH/CRITICAL vocabulary explicitly or
  used contextual severity language — the system vocabulary grounding is inferred.

- **Actionability (4):** The HIGH finding translated to a GATE 4 ISSUE #646 (pre-existing
  recheck_batch race, out of scope, scheduled for disposition). This is correct actionability
  for a finding that is real but outside the PR boundary. The PASS-WITH-CONCERNS verdict
  correctly unblocked PR open after the inline resolutions were confirmed. Minor deduction:
  the report does not quote a specific re-dispatch recommendation from the reviewer (e.g., "if
  recheck_batch is modified in a future PR, confirm batch_write_lock coverage at that time"),
  which would make the GATE 4 disposition more operator-executable.

- **Substitution (5):** reviewer-challenge is a canonical repo-installed agent
  (`.claude/agents/reviewer-challenge.md`). No substitution. CLAUDE.md mandates reviewer-challenge
  on every PR touching customs/financial-adjacent code. Mandate honored.

- **Evidence (3):** The campaign summary records the reviewer's conclusion (PASS-WITH-CONCERNS,
  HIGH recheck_batch race) but does not quote the verdict block with file:line evidence, does not
  cite which specific code path in `confirm_vision_invoice` or `recheck_batch` was inspected to
  support the race finding, and does not name the batch_write_lock coverage gap as a grep-level
  observation. The finding is plausible and was correctly dispositioned, but the evidence chain
  stops at the label level. An EXEMPLARY reviewer-challenge output for a concurrency finding
  would cite the specific function where `recheck_batch` writes the audit dict and the specific
  lock context where `confirm_vision_invoice` operates, to demonstrate the race path concretely.

- **Environment (3):** The verdict block as available via the campaign summary does not
  self-report the working tree path examined, the branch, or the commit SHA inspected. The
  campaign establishes branch context (feat/pr2-vision-invoice-confirm-workflow @ 4429e04) at
  the campaign objective level, but the reviewer's own verdict block does not confirm this
  self-disclosure. Scores 3 per the established standard: missing self-disclosure with no
  confirmed wrong-path failure (the finding is substantively correct). PATH GUARD issue #597
  applies here as with all non-deploy review agents.

---

### backend-safety-reviewer (32 — EXEMPLARY)

- **Specificity (5):** The campaign records F-1 with full mechanism: `timeline.log_event` was
  called outside the `batch_write_lock` in `confirm_vision_invoice()`, creating a lost-update
  risk against concurrent timeline writers. The named function (`timeline.log_event`), the named
  lock scope (`batch_write_lock`), the named failure class (lost-update, not just race condition),
  and the named fix (move `log_event` call inside the lock) are all independently verifiable
  against `service/app/services/vision_extractor.py`. This is function-level specificity on a
  correctness finding — the highest-quality output for this agent's mandate.

- **Coverage (5):** The agent's mandate includes unsafe POST endpoints, missing readiness checks,
  missing idempotency, and direct audit writes. Against this mandate:
  - Unsafe POST: the new confirm endpoint is auth-gated via `require_role` (PASS, confirmed by
    security-write-action-reviewer cross-verification)
  - Readiness check: `_vision_invoice_has_proposal()` helper verified to gate the confirm action
    (confirmed by the 409 error mapping in the route)
  - Idempotency: `confirm_vision_invoice()` described as idempotent — already-confirmed state
    returns early without re-writing
  - Direct audit write: F-1 correctly identified that `timeline.log_event` outside the lock was
    a direct write outside the atomic context
  The agent covered all four canonical checklist domains for this PR's backend surface. The `machine_original` snapshot write (storing pre-confirm state before mutation) and the `SOLE writer` constraint for `operator_confirmed=true` were implicitly validated by the PASS verdict on audit write safety.

- **Severity (5):** MEDIUM for F-1 (lost-update on timeline outside lock) is precisely calibrated.
  The failure class — a timeline event dropped or duplicated under concurrency — is real but bounded:
  it affects audit evidence (provenance) rather than the financial CIF value itself. MEDIUM is not
  deflated (it is a genuine correctness risk, not cosmetic) and not inflated (it does not corrupt
  the confirmed CIF value). The fix (moving `log_event` inside `batch_write_lock`) is minimal and
  correct; MEDIUM correctly characterizes a risk that required a fix rather than just a note.

- **Actionability (5):** The F-1 finding produced a direct, verifiable inline fix: `timeline.log_event`
  moved inside `batch_write_lock` in `vision_extractor.py`. This is the highest possible actionability
  signal for a backend-safety finding — finding → named code change → confirmed applied before PR open.
  An operator reviewing the diff can verify the fix at the specific function boundary.

- **Substitution (5):** backend-safety-reviewer is a canonical repo-installed agent
  (`.claude/agents/backend-safety-reviewer.md`). Tool grants: Read, Grep, Glob (inspect-only).
  No substitution. GATE 5 N/A.

- **Evidence (4):** The named function (`timeline.log_event`), named lock (`batch_write_lock`),
  and named fix (moved inside lock) are verifiable against the diff. The campaign summary does
  not quote a grep output or line number from `vision_extractor.py` confirming exactly where the
  call was originally placed and where it was moved. Minor deduction: the evidence floor is
  function-level (which function, which lock context) but not line-level. A grep output confirming
  the original out-of-lock position would complete the evidence chain.

- **Environment (3):** Same structural disclosure gap as all GATE-1 review agents in this campaign
  — working tree path and commit SHA not self-reported in the verdict block. Score 3: no confirmed
  wrong-path failure; the finding is substantively correct and was resolved against the correct
  codebase. Issue #597 applies.

---

### security-write-action-reviewer (27 — ACCEPTABLE)

- **Specificity (4):** Two MEDIUM findings are recorded: (1) ghost-identity `"session-user"` fallback
  in the route — the agent identified the specific fallback string and the specific risk (a request
  that bypasses auth infrastructure could write with a generic non-operator identity). (2) logistics
  role attesting financials — the agent named the role check (`require_role`) and the policy question
  (does logistics-level auth appropriately gate a CIF-related operator-confirm action?). Both findings
  are named at the mechanism level. Minor deduction: the campaign summary does not quote the agent's
  structured return fields (Unsafe action / Endpoint / UI location / Required guard) from its output
  contract, so the finding descriptions are available only as narrative summary rather than as
  structured, independently verifiable verdict artifact items.

- **Coverage (4):** The agent's mandate covers readiness gates, confirmation if destructive,
  idempotency, audit/execution log, and no UI bypass. Against this PR's write-action surface:
  - Readiness gate: `_vision_invoice_has_proposal()` helper gating the confirm action — covered
    (confirmed by the 409 error mapping, which the agent's ghost-identity finding implies it read
    the route in detail)
  - Confirmation: the endpoint is a POST that requires explicit operator invocation — covered
    (no auto-trigger risk)
  - Idempotency: `confirm_vision_invoice()` idempotent per description — appears covered by PASS
    (no MEDIUM/HIGH on idempotency)
  - Audit/execution log: `timeline.log_event` call present (found independently by backend-safety-reviewer
    at F-1) — the security reviewer's PASS on audit trail implies this surface was reviewed
  - No UI bypass: server-side auth via `require_role`, traversal guard — covered by the ghost-identity
    finding (the agent engaged with the auth layer at the code level)
  Minor coverage gap: the campaign summary does not confirm whether the agent independently verified
  the `machine_original` snapshot write (pre-confirm state preservation) or the `advisory_supplier_crosscheck`
  call, both of which are write-adjacent operations that touch the audit record.

- **Severity (4):** MEDIUM for ghost-identity fallback is correctly calibrated. A fallback that
  writes `"session-user"` as operator identity when the auth token is missing or malformed would
  corrupt the audit provenance without raising an exception — a genuine correctness and audit-
  integrity risk. Resolving it by removing the fallback (using authenticated `require_role` user
  only, with 401/403 on absent or malformed token) is the correct fix. MEDIUM is not deflated —
  this is a real auth-audit gap — and not inflated — it does not grant elevated permissions, only
  a wrong label on the confirmed record. The logistics role policy classification as MEDIUM (noted
  to operator, not blocking) is also correctly calibrated: it follows existing `routes_action_proposals`
  precedent and is a policy judgment, not a code defect.

- **Actionability (4):** The ghost-identity MEDIUM produced a concrete inline fix: authenticated
  `require_role` user used exclusively, no fallback. The fix is verifiable in the diff. The
  logistics role MEDIUM was noted to operator as policy-aligned with existing precedent — a correct
  disposition for a policy question that does not require a code change. Minor deduction: the campaign
  summary does not quote the agent's "Required guard" field output for each finding, which would
  make the resolution path independently operator-actionable from the verdict block alone (currently
  requires knowing the fix from the disposition record).

- **Substitution (5):** security-write-action-reviewer is a canonical repo-installed agent
  (`.claude/agents/security-write-action-reviewer.md`). No substitution. GATE 5 N/A.

- **Evidence (3):** The finding descriptions (ghost-identity string `"session-user"`, logistics role
  policy question) are named at the mechanism level but the campaign summary does not include the
  agent's structured return (Unsafe action / Endpoint / UI location / Required guard fields). No
  grep output, no line number from `routes_dashboard.py` for the original ghost-identity fallback,
  no quoted code excerpt. The evidence chain is reconstructable from the resolution record (the fix
  was applied) but is not self-contained in the agent's verdict as summarised. An EXEMPLARY
  security-write-action-reviewer output would include the specific fallback expression that was
  found and removed.

- **Environment (3):** Same structural self-disclosure gap as all non-deploy GATE-1 agents in this
  campaign. No confirmed wrong-path failure. Issue #597 applies.

---

### test-coverage-reviewer (31 — EXEMPLARY)

- **Specificity (5):** Two named HIGH gaps and multiple named MEDIUM/LOW gaps are recorded:
  - GAP-1: zero route-level HTTP tests — specifically identifies the missing test category
    (HTTP-level, exercising the actual route handler, not just the service function), as
    distinct from the 12 service tests that already existed.
  - GAP-5 (inferred): missing negative-case HTTP tests (4xx path verification at the route layer).
  The agent correctly distinguished between service-layer coverage (12 tests: idempotency, proposal
  check, machine_original snapshot, timeline event, advisor crosscheck) and HTTP/route-layer coverage
  (auth enforcement, traversal rejection, 409/404/400 mapping as HTTP responses). This is precisely
  the architectural coverage distinction that matters for a new endpoint — the service layer and
  the route layer can fail independently, and the agent named both independently. HIGH rating for
  zero route-level tests is specific and independently verifiable against the test files as they
  existed before the 9 HTTP tests were added.

- **Coverage (5):** The agent's mandate covers missing negative tests, missing idempotency tests,
  missing no-direct-POST assertions, and source-grep-only weak spots. Against this PR:
  - Negative tests: GAP-1 (zero route HTTP tests including 4xx paths) — covered and named
  - Idempotency tests: the 12 service tests include idempotency coverage (already-confirmed returns
    early) — implicitly verified PASS
  - Route-layer gaps: correctly identified as the entire missing test surface
  - The MEDIUM/LOW gaps (advisory supplier crosscheck edge cases, missing confidence threshold
    test, possible machine_original null edge case) represent complete coverage of the test surface
    for a new feature of this size. The agent enumerated multiple gap categories rather than
    stopping at the first HIGH finding.

- **Severity (4):** HIGH for GAP-1 (zero route-level HTTP tests) is correctly calibrated. A PR
  that adds a new POST endpoint with auth, error mapping, and traversal guard but has zero HTTP-
  level tests cannot be considered adequately tested — a defect in the route layer (e.g., auth
  not wired, traversal guard not applied, wrong error code returned) would be undetectable. HIGH
  is not inflated (this is a genuine structural test gap, not a CRITICAL blocker that prevents
  the service from functioning) and not deflated (it is not a LOW preference item — an untested
  route is a real regression risk surface). Minor deduction: the MEDIUM/LOW labels for the
  remaining gaps are assigned correctly, but the campaign summary does not show whether the agent
  applied a consistent severity rationale across all gaps or whether the distinctions between
  MEDIUM and LOW are grounded in explicit reasoning for each gap class.

  **Note on historical calibration:** test-coverage-reviewer has a documented severity-inflation
  pattern flagged as REPEATED-WEAK in the 2026-06-12-cn-hsn-false-block-fix.md scorecard (4
  occurrences of over-inflation). In this campaign, the HIGH rating for GAP-1 is well-justified
  and the MEDIUM/LOW ratings for supplementary gaps are appropriately sized. No inflation detected
  here — this is a positive calibration signal.

- **Actionability (5):** GAP-1 produced 9 concrete HTTP route tests added before PR open. The 9
  tests cover: auth enforcement (require_role), traversal guard (batch_id with `/`, `\`, `..`
  patterns), 409 (already confirmed), 404 (batch not found), 400 (no proposal), and the happy-
  path confirm flow with response body verification. This is the complete resolution of GAP-1 —
  not a partial fix. The MEDIUM/LOW gaps are dispositioned as accepted known gaps (noted, not
  blocking), which is correct for items like advisory crosscheck edge cases on a new feature.

- **Substitution (5):** test-coverage-reviewer is a canonical repo-installed agent
  (`.claude/agents/test-coverage-reviewer.md`). Tool grants: Read, Grep, Glob (inspect-only).
  No substitution. GATE 5 N/A.

- **Evidence (4):** The GAP-1 finding (zero route-level HTTP tests before the 9 were added) is a
  concrete, independently verifiable claim — checkable against the test file listing before the PR
  revision. The final suite counts (12 service tests + 9 HTTP tests = 21 combined; full vision
  suite 68 passed, 1 skipped) are concrete numbers. The pre-commit smoke count (63 passed) is a
  deployment verification artifact. Minor deduction: no grep output or file listing confirming
  that test files for the route existed or did not exist before the fix was applied; the before-state
  is described but not cited with an artifact. The campaign summary account of the 9 HTTP tests is
  clear on what was added but relies on the campaign narrative rather than a quoted test inventory
  from the agent's own verdict.

- **Environment (3):** Same structural self-disclosure gap as all non-deploy GATE-1 agents in this
  campaign. Score 3: no wrong-path failure; the test counts and gap findings are substantively
  correct and were resolved against the correct codebase. Issue #597 applies.

---

## Weak-verdict warnings

### reviewer-challenge (ACCEPTABLE — 27): GATE 4 disposition required

**Failed / weak dimensions:** Evidence (3), Coverage (4 — partial gap)

**Evidence gap:** The campaign summary records the reviewer's PASS-WITH-CONCERNS / HIGH recheck_batch
race verdict but does not quote a verdict block with file:line evidence. The structured output contract
for reviewer-challenge (3 assumptions, 3 failure scenarios, SPOF, question nobody asked) is not cited.
The HIGH finding is plausible and correctly dispositioned, but the evidence record in the campaign
report does not demonstrate that the reviewer independently verified the `recheck_batch` audit-write
code path vs the `confirm_vision_invoice` lock scope — the finding is inferred to be correct from its
downstream disposition (GATE 4 ISSUE #646) rather than evidenced by the agent's own artifact.

**Coverage gap:** The campaign summary does not confirm whether reviewer-challenge examined the
traversal guard, the 409/404/400 error mapping, or the `next_step` disclosure field on the new
endpoint. These are structural correctness items within reviewer-challenge's scope ("hidden risks,
false assumptions, missing backend") for a new write-action route.

**Disposition (GATE 4 — ACCEPTABLE verdict):** SCHEDULED — In the next GATE-1 campaign for this
reviewer, the campaign report must quote the reviewer-challenge verdict block directly, including
the structured assumptions/scenarios/SPOF output. If the campaign summary cannot support direct
quoting (because the reviewer's output was terse or label-only), that itself becomes a Coverage
finding scored at 2 (not 4). Target: next campaign dispatching reviewer-challenge against a
write-action endpoint.

---

### security-write-action-reviewer (ACCEPTABLE — 27): GATE 4 disposition required

**Failed / weak dimensions:** Evidence (3), Coverage (4 — minor gap)

**Evidence gap:** The campaign summary records the two MEDIUM findings (ghost-identity, logistics role)
but does not quote the agent's structured return fields (Unsafe action / Endpoint / UI location /
Required guard) that the agent's output contract specifies. The finding descriptions are campaign-
narrative level, not verdict-artifact level. An independent verifier cannot confirm from the summary
alone which specific code expression the agent found at which line in `routes_dashboard.py` for the
ghost-identity fallback.

**Coverage gap:** No explicit confirmation in the summary that the agent verified `machine_original`
snapshot write semantics or the advisory supplier crosscheck call — both are audit-write-adjacent
operations for the new endpoint.

**Disposition (GATE 4 — ACCEPTABLE verdict):** SCHEDULED — In the next GATE-1 campaign for this
reviewer, the campaign report must include the agent's structured verdict fields (Unsafe action /
Endpoint / UI location / Required guard) for each finding. If the campaign summary cannot support
this (agent produced narrative rather than structured output), the reviewer's Coverage and Evidence
dimensions drop proportionally. Target: next campaign dispatching security-write-action-reviewer
against a new write-action endpoint.

---

## Repeated failure hints

**5 most recent campaign scorecards reviewed (excluding self-eval files):**
1. `2026-06-17-cif-authority-consistency-guard.md` — 5 GATE-1 agents, all EXEMPLARY
2. `2026-06-17-pr633-cif-ui-resolved-authority.md` — 3 agents, all EXEMPLARY
3. `2026-06-17-pr632-ocr-fallback-deploy-gate.md` — 7 deploy agents, all EXEMPLARY
4. `2026-06-17-ocr-ai-image-only-extraction-fallback.md` — 3 agents: 2 EXEMPLARY, 1 ACCEPTABLE (backend-safety-reviewer, Coverage 3, Evidence 3)
5. `2026-06-17-adr029-e4d96b5-deploy-gate.md` — 7 deploy agents, all EXEMPLARY

### reviewer-challenge — NO REPEATED-WEAK FLAG

Prior scorecards in the 5-scorecard window: EXEMPLARY in cif-authority (29), EXEMPLARY in pr633 (29),
EXEMPLARY in ocr-fallback (30). Current campaign: ACCEPTABLE (27). This is the first ACCEPTABLE
score for reviewer-challenge in the recent history window — the reduction is attributable to the
evidence quality gap in the campaign report (no quoted verdict block, no structured output artifact),
not to an agent-level capability failure. Pattern is: reviewer-challenge performs well; campaign
reporting discipline varies. No REPEATED-WEAK flag (one occurrence in the window at ACCEPTABLE;
threshold is ≥2 NEEDS-TUNING or UNRELIABLE).

### backend-safety-reviewer — CONSISTENT EXEMPLARY

Prior appearances: EXEMPLARY (32) in cif-authority, EXEMPLARY (28) in pr633, ACCEPTABLE (26) in
ocr-fallback (large novel feature, coverage depth gap), EXEMPLARY (34) in adr029/pr627. Current
campaign: EXEMPLARY (32). The ocr-fallback ACCEPTABLE was a scale-sensitivity observation (1829
lines, 8 files — single finding, no negative-evidence sweep). In this campaign (targeted new
service + route, 21 tests), the agent returned to full EXEMPLARY with function-level specificity.
No REPEATED-WEAK flag. No repeated pattern.

### security-write-action-reviewer — FIRST SOLO GATE-1 APPEARANCE, NO FLAG

Prior scorecards: Appeared in cif-authority-consistency-guard (EXEMPLARY, 30), not separately scored
in deploy gate campaigns (subsumed under deploy-security-reviewer). Current campaign: ACCEPTABLE (27),
driven by evidence-quality gap (structured return fields absent from campaign summary). This is the
first ACCEPTABLE score for this agent in the window. No REPEATED-WEAK flag (one occurrence). The
ACCEPTABLE score is primarily a campaign-reporting-discipline issue rather than an agent capability
failure — same pattern as reviewer-challenge this campaign.

### test-coverage-reviewer — POSITIVE CALIBRATION SIGNAL, REPEATED-WEAK FLAG FROM PRIOR PERIOD

**REPEATED-WEAK status from 2026-06-12-cn-hsn-false-block-fix.md is NOT cleared yet.**
That scorecard flagged test-coverage-reviewer for severity inflation across 4 prior campaigns
(REPEATED-WEAK, scored 2/5 Severity in prior appearances). Subsequent campaigns where the canonical
agent was directly dispatched have been limited. In the current campaign, test-coverage-reviewer
scored Severity 4/5 — the HIGH rating for GAP-1 is well-justified, and MEDIUM/LOW for supplementary
gaps is appropriately sized. This is a positive calibration signal. However, the REPEATED-WEAK flag
requires at least one more EXEMPLARY or ACCEPTABLE run with correct severity calibration before it
can be cleared. The current campaign is the first clean-calibration data point post-flag.

**Recommendation:** The 2026-06-12-cn-hsn REPEATED-WEAK flag for test-coverage-reviewer remains
active. This campaign is counted as run 1 of the required clean-calibration confirmation runs.
The flag will be retired after one additional campaign with Severity ≥ 4/5 and no inflation detected.

---

## Notable quality signals

**Defense-in-depth on the timeline lock race:** The F-1 finding from backend-safety-reviewer
(`timeline.log_event` outside `batch_write_lock`) and the HIGH recheck_batch concern from
reviewer-challenge are two distinct views of the same lock-safety surface, approached from
different angles (internal function atomicity vs external concurrent writer interaction). The two
findings did not overlap or duplicate — they complemented each other. The inline resolution of F-1
(moving `log_event` inside the lock) was a direct fix; the recheck_batch finding correctly became
GATE 4 ISSUE #646 (pre-existing, out-of-scope). Multi-agent convergence on lock safety is the
intended defense-in-depth signal for a financial-adjacent write-action endpoint.

**Ghost-identity removal is a SOLE-WRITER integrity enforcement:** The `confirm_vision_invoice()`
function is designed as the SOLE writer of `operator_confirmed=true`. The ghost-identity fallback
removal by security-write-action-reviewer directly supports this invariant: if any caller could
write a confirmed state with identity `"session-user"` (a non-traceable generic), the provenance
of the confirmation would be unverifiable. Removing the fallback enforces that confirmation events
can only be attributed to authenticated, named operators. This is a correctness finding with
audit-evidence implications.

**9 HTTP route tests close the test-coverage reviewer's most important finding:** The GAP-1 HIGH
finding (zero route-level HTTP tests) was the structural test gap for this PR. Adding 9 tests that
cover auth enforcement, traversal guard, and the full 4xx/2xx error-mapping surface before PR open
represents complete gap remediation. The final suite state (12 service + 9 HTTP = 21 tests, full
vision suite 68 passed) provides defense-in-depth at both the service-function layer and the HTTP
layer.

**GATE 4 discipline confirmed:** The recheck_batch whole-audit race was correctly identified as
pre-existing (not introduced by this PR) and dispositioned as GATE 4 ISSUE #646 rather than
folded into PR #647's scope. This is the correct behavior for a GATE-1 review finding an out-of-diff
issue — file, don't fold.

---

## Self-evaluation cadence check

**Most recent self-eval file:** `C:\PZ-verify\.claude\memory\scorecards\self-eval-2026-06-16.md`
**Self-eval date:** 2026-06-16
**Today:** 2026-06-17
**Calendar days elapsed:** 1 day
**Trigger threshold:** 7 calendar days, OR SELF-DEGRADATION DETECTED in last self-eval + 3rd
  campaign scorecard run since that flag
**SELF-DEGRADATION flag in self-eval-2026-06-16.md:** NO — assessment was "No SELF-DEGRADATION
  DETECTED" / total self-score 30/35 (EXEMPLARY); Environment dimension recovered to 4/5.
**3rd-run counter active:** NO (no active SELF-DEGRADATION flag; counter does not begin)

**Self-evaluation: SKIPPED — not triggered.** 1 calendar day < 7-day threshold; no active
degradation flag.

**Next self-eval due:** 2026-06-23 (7 calendar days from 2026-06-16).

---

## Campaign quality summary

**Campaign verdict:** STRONG — All 4 GATE-1 reviewers returned substantive verdicts. All
HIGH/CRITICAL findings were resolved inline before PR open. The GATE-1 review layer functioned
as intended: each reviewer found at least one real issue within its domain; all inline-resolvable
findings were resolved; the one pre-existing out-of-scope race condition was correctly dispositioned
to GATE 4 ISSUE #646.

**Agent reliability:** 2/4 EXEMPLARY (backend-safety-reviewer, test-coverage-reviewer); 2/4
ACCEPTABLE (reviewer-challenge, security-write-action-reviewer). No NEEDS-TUNING. No UNRELIABLE.
The ACCEPTABLE scores are primarily attributable to campaign-reporting-discipline gaps (verdict
blocks not quoted in the campaign summary) rather than to agent capability failures — the findings
from both ACCEPTABLE agents were real and were actioned.

**Primary structural gap:** Evidence dimension (3/5) for reviewer-challenge and security-write-action-
reviewer reflects the campaign report's reliance on narrative summary rather than quoted verdict
artifacts from these agents. For a backend-only, financially-adjacent PR, the evidence floor for
the GATE-1 reviewers should include the structured output (reviewer-challenge: 3 assumptions + 3
scenarios + SPOF; security-write-action-reviewer: Unsafe action / Endpoint / UI location / Required
guard) cited directly from the verdict block. This is a campaign-reporting improvement, not an
agent capability issue.

**Environment dimension uniform structural gap (3/5 across all 4 agents):** All four agents scored
3/5 on Environment — no agent self-reported the working tree path, branch, or commit SHA examined
in their verdict block. This is the systemic prompt-level disclosure gap tracked under GitHub Issue
#597. No individual GATE 4 disposition generated for this gap (existing tracked debt).

**GATE 4 dispositions generated by this scorecard:**
1. reviewer-challenge reporting discipline — SCHEDULED: campaign reports must quote the structured
   verdict block (assumptions / scenarios / SPOF) for reviewer-challenge. Target: next GATE-1 campaign
   against a write-action endpoint.
2. security-write-action-reviewer reporting discipline — SCHEDULED: campaign reports must include
   the structured return fields (Unsafe action / Endpoint / UI location / Required guard) for each
   finding. Target: next GATE-1 campaign against a new write-action endpoint.

**Agents scored:** 4
**EXEMPLARY:** backend-safety-reviewer (32), test-coverage-reviewer (31)
**ACCEPTABLE:** reviewer-challenge (27), security-write-action-reviewer (27)
**NEEDS-TUNING:** none
**UNRELIABLE:** none
**Repeated-weak flags active:** test-coverage-reviewer (from 2026-06-12-cn-hsn-false-block-fix.md
  — severity inflation flag; current campaign is a positive calibration signal but flag not yet
  cleared; requires one more clean-calibration run)
**GATE 4 dispositions added by this scorecard:** 2 (both SCHEDULED)
**Self-evaluation:** skipped (1 day since self-eval-2026-06-16.md; no active degradation flag)
