# Agent Performance Scorecard — CIF Authority Consistency Guard (PR #643)

**Date:** 2026-06-17
**Campaign:** Single resolved-CIF authority backend guard
**Branch:** feat/cif-authority-consistency-guard
**Commit:** 20d6a0c
**PR:** #643
**Scope:** Backend gate + governance + tests (no frontend refactor — PR #633 already shipped UI/Polish-desc gate)
**Domain:** Customs/financial-adjacent — resolved CIF tri-state authority canonicalisation
**Outcome:** GATE 1 convergent review pre-open; 73 targeted tests passed; full baseline unchanged (+13 passing vs origin/main at merge-base 4652292); 6 modified modules import cleanly; ADR-030 written; GATE 2/4 compliant.
**Agents evaluated:** 5 roles (reviewer-challenge, backend-safety-reviewer, security-write-action-reviewer, testing-verification, adr-historian). Orchestrator applied fixes inline.

---

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| reviewer-challenge | 4 | 4 | 4 | 5 | 5 | 4 | 3 | 29 | EXEMPLARY |
| backend-safety-reviewer | 5 | 5 | 4 | 5 | 5 | 5 | 3 | 32 | EXEMPLARY |
| security-write-action-reviewer | 4 | 5 | 4 | 5 | 5 | 4 | 3 | 30 | EXEMPLARY |
| testing-verification | 4 | 5 | 4 | 5 | 4 | 4 | 3 | 29 | EXEMPLARY |
| adr-historian | 5 | 5 | 4 | 5 | 5 | 5 | 3 | 32 | EXEMPLARY |

---

## Scoring rationale per agent

### reviewer-challenge (29 — EXEMPLARY)

- **Specificity (4):** Correctly identified architectural failure scenarios against named call sites: routes_dhl_clearance, routes_dsk, routes_action_proposals, routes_dashboard. Raised the concrete risk of the `or 0` silent-zero pattern in routes_action_proposals. Named the DSK payload override audit concern as an assumption-under-test. Minor deduction: the campaign report does not surface a direct quote of the reviewer's assumption triplet or failure scenarios as separate named items — the review's outputs are recoverable via the findings that were resolved (silent-zero removal, payload override audit), but the structured output contract (3 assumptions, 3 scenarios, SPOF) is inferred from results rather than directly cited.
- **Coverage (4):** Covered the primary risk surfaces: call-site wiring correctness (6 wired routes), silent-zero elimination in action_proposals, DECLARED_ZERO/UNKNOWN block behaviour, and DSK payload override audit trail. Did not surface a separate concern about routes_agency honest-reason disclosure prior to implementation — that surface was covered by the orchestrator inline, which is acceptable but means reviewer-challenge did not lead the finding on that call site. Minor coverage gap on agency routing.
- **Severity (4):** Calibrated appropriately for a customs-financial-adjacent PR. The `or 0` silent-zero in action_proposals is correctly treated as a real risk (not inflated to CRITICAL, not suppressed to LOW). DECLARED_ZERO block presented as a correctness requirement rather than a blocking severity. No evidence of the severity inflation pattern seen in test-coverage-reviewer across prior campaigns.
- **Actionability (5):** All reviewer-challenge findings translated directly to code changes shipped in the PR: silent-zero `or 0` removed from routes_action_proposals, payload override audited on timeline in routes_dsk, DECLARED_ZERO+UNKNOWN block implemented. The GATE 1 pre-open resolution structure confirms the reviewer's findings were operator-actionable without ambiguity.
- **Substitution (5):** No substitution. reviewer-challenge is a canonical repo-installed agent (`.claude/agents/reviewer-challenge.md`). CLAUDE.md mandates this agent on every customs/financial PR — mandate was honoured.
- **Evidence (4):** Findings are evidenced by their downstream resolution (each resolved finding implies a verifiable diff change). Minor deduction: the campaign report does not cite a quoted reviewer output block with file:line assertions from reviewer-challenge's own verdict — the evidence is reconstructable from the PR body, not directly auditable from the agent's own structured return.
- **Environment (3):** Working tree path (C:\PZ-cif-guard, branch feat/cif-authority-consistency-guard, commit 20d6a0c) not explicitly self-reported in reviewer-challenge's verdict block per the campaign summary. Recoverable from campaign context. No evidence the missing disclosure masked a verification error (all review findings resolved against correct files). Structural disclosure gap, not a correctness failure.

---

### backend-safety-reviewer (32 — EXEMPLARY)

- **Specificity (5):** Named the six wired call sites explicitly: routes_dhl_clearance (generate_description + generate_customs_package), routes_dsk (generate_dsk + payload override audited on timeline), routes_agency (routing_pending honest reason), routes_action_proposals (G6/G7 prefer clearance_decision, removed `or 0`, legacy cif_state inference). Named the two new service functions: `get_cif_authority(audit)` (pure, never raises) and `require_resolved_cif(audit, action=...)` with its three specific raise codes (422 cif_unresolved / 422 cif_declared_zero / 500 resolver-contract-violation). This is the most complete call-site inventory in the campaign.
- **Coverage (5):** Full scope of the backend guard campaign covered: the new shared gate service (cif_authority.py), all six wired call sites across four route modules, the audit timeline write in routes_dsk payload override, and the dashboard DSK enablement via is_resolved. The `or 0` silent-zero in routes_action_proposals is a backend safety finding (silent suppression of a financial value) — correctly caught and resolved. No unsafe write surfaces identified, no false received=True pattern, no missing readiness check. Lesson A compliance confirmed: real-builder regression tests included, no stubs for the gate contract.
- **Severity (4):** Appropriately calibrated. The `or 0` silent-zero pattern in routes_action_proposals is a financial correctness risk — surfaced without inflation to CRITICAL. The 500 resolver-contract-violation case in require_resolved_cif is correctly identified as a backend contract enforcement mechanism, not a security blocker. DSK payload override audit write is a correctness-and-evidence concern, not a financial mutation risk. No deflation detected for a customs-adjacent change.
- **Actionability (5):** Every finding has a direct resolution traceable to the shipped code: `or 0` removed from routes_action_proposals, payload override now audited on timeline in routes_dsk, honest reason in routes_agency, DECLARED_ZERO+UNKNOWN blocks implemented across call sites. The three-raise-code specification for `require_resolved_cif` directly maps to the implementation in cif_authority.py. Operator can verify each resolution against the diff.
- **Substitution (5):** No substitution. backend-safety-reviewer is a canonical repo-installed agent (`.claude/agents/backend-safety-reviewer.md`). Tool grants: Read, Grep, Glob (inspect-only — correct for a review role on a customs-adjacent change).
- **Evidence (5):** Named function signatures, named raise codes, named call sites across four route modules. The `or 0` finding is a quoted pattern (a literal Python expression), not a vague assertion. The six-site wiring inventory is the highest-specificity backend review evidence in recent campaign history for an implementation-review (non-deploy) campaign. No fabrication risk — all claims are verifiable against cif_authority.py and the four route modules.
- **Environment (3):** Working tree path and examined commit SHA not explicitly self-reported in the verdict block. Shared disclosure gap with other agents in this campaign. No evidence of a correctness failure attributable to wrong-path inspection. Structural gap only.

---

### security-write-action-reviewer (30 — EXEMPLARY)

- **Specificity (4):** Named the four route modules with write actions reviewed: routes_dhl_clearance, routes_dsk, routes_agency, routes_action_proposals. Confirmed readiness gate present (require_resolved_cif at each write action call site). Confirmed audit/execution log for DSK payload override (audited on timeline). Confirmed no direct UI bypass (gate is backend-enforced in cif_authority.py). Minor deduction: the campaign report does not separately quote this agent's verdict block with specific line references for the write-action endpoints reviewed — coverage is inferred from the GATE 1 resolution record rather than a self-contained security-write-action-reviewer output with endpoint-by-endpoint evidence.
- **Coverage (5):** Full write-action surface for this PR covered: all three DHL clearance write paths, DSK generation with payload override, agency routing with honest reason, and action proposal approval paths (G6/G7). The idempotency question for require_resolved_cif (called at execution time, not just at proposal time — Lesson E execution-time validation property) was implicitly verified via the pure function design of get_cif_authority. The 422/500 raise pattern confirms no write action proceeds silently on unresolved CIF. No wFirma, VAT, or SAD posting paths were in scope (correctly identified as out-of-scope per campaign objective).
- **Severity (4):** Calibrated correctly for a customs-adjacent write-gate implementation. The GATE 1 pre-open resolution shows no HIGH or CRITICAL write-safety finding was left unresolved at PR-open time. Appropriate that this is a PASS with conditions rather than a BLOCKED verdict — the guard is being added, not removed.
- **Actionability (5):** GATE 1 compliance confirmed: all write-safety findings resolved pre-open and documented in PR body. Each write action call site has a named guard (require_resolved_cif), a named audit trace (timeline write in DSK), and a named honest-reason disclosure (agency routing). No ambiguity in how each write action is now guarded.
- **Substitution (5):** No substitution. security-write-action-reviewer is a canonical repo-installed agent (`.claude/agents/security-write-action-reviewer.md`). AGENT_REGISTRY confirms it is the mandatory reviewer for changes introducing or modifying write actions — correctly activated here.
- **Evidence (4):** Readiness gate evidence (require_resolved_cif at each call site) and audit trace evidence (DSK timeline write) are verifiable against the diff. Minor deduction: no direct quote of this agent's structured return (Unsafe action / Endpoint / UI location / Required guard fields) in the campaign report. The evidence floor is inferential from the GATE 1 resolution record rather than directly presented from the agent's own output.
- **Environment (3):** Same shared disclosure gap as other agents — working tree path and branch/commit not self-reported in verdict block. Structural gap; no correctness impact detected.

---

### testing-verification (29 — EXEMPLARY)

- **Specificity (4):** Named the test suite and test file explicitly: `test_cif_authority.py` with named fixture (AWB 2315714531 fixture), named edge cases (declared-zero, unknown, payload override), and named companion test scopes (action_proposals declared-zero + legacy-missing-cif_state, dashboard DSK enabled-from-AWB + disabled-on-unknown). Cited the count result (73 passed, +13 passing vs baseline, zero new failures against 99 pre-existing env failures on both branch and origin/main at merge-base 4652292). Minor deduction: the agent name "testing-verification" does not match a canonical repo-installed agent — the registry lists `test-coverage-reviewer` as the nearest canonical (INSPECT-ONLY, purpose: reviews tests for missing negative cases). See Substitution dimension.
- **Coverage (5):** Test coverage for this campaign is comprehensive: cif_authority.py helper + gate function, DSK route including payload override, declared-zero edge case, UNKNOWN block edge case, action_proposals legacy cif_state inference path, dashboard DSK enablement/disablement by resolution state. The pre-existing env-failure baseline comparison (99 failures on both branch and clean origin/main at same merge-base) is a strong negative-evidence check confirming no test regression was introduced. Lesson A compliance confirmed: real-builder regression tests included, no stubs for the gate contract.
- **Severity (4):** No severity inflation detected. The 73-test targeted suite pass is correctly sized as a completeness check. The +13 passing signal is correctly presented as a positive delta, not an inflated risk. Baseline comparison is correctly used as a zero-new-failures confirmation, not a suppressed pass. This is a clean calibration — notably absent is the "CRITICAL" inflation pattern that test-coverage-reviewer has exhibited 4 times in prior campaigns (REPEATED-WEAK flagged in 2026-06-12-cn-hsn-false-block-fix.md). Either the orchestrator performed test verification inline rather than dispatching the canonical test-coverage-reviewer, or the role was performed by a different execution path.
- **Actionability (5):** 73 passed / 0 new failures / +13 delta is an operator-ready test verdict. The baseline comparison at merge-base 4652292 (both branch and clean origin/main) eliminates the need for manual env-failure disambiguation. Named fixture (AWB 2315714531) and named edge cases (declared-zero, unknown) provide regression anchors for future CIF authority changes.
- **Substitution (4):** The agent role is identified as "testing-verification" in the campaign report, which does not match a canonical repo-installed agent name. The registry lists `test-coverage-reviewer` as the canonical agent for test coverage review (INSPECT-ONLY). "Testing-verification" as a role name appears to describe the orchestrator performing test execution and verification inline, supplemented by reviewing coverage adequacy. Deduction applied per GATE 5: while the capability gap is minimal (the test execution and coverage check was performed at the required depth), the registry mismatch is not explicitly disclosed in the campaign report as a GATE 5 substitution disclosure. The campaign report states "testing-verification (regression tests)" without a capability-equivalence statement or registry-mismatch log. Minor disclosure gap, not a coverage failure.
- **Evidence (4):** Concrete test counts (73 passed, +13 vs baseline, 99 pre-existing env failures on both branch and clean origin) are verifiable artifacts. Named test file (test_cif_authority.py) and named fixture (AWB 2315714531) provide direct verification anchors. Minor deduction: no quoted pytest output or test names confirming the 73-test scope; count is stated as a result without the underlying test run artifact cited.
- **Environment (3):** Working tree path (C:\PZ-cif-guard) and merge-base commit (4652292) are partially disclosed (the merge-base SHA is named, which is a stronger environment anchor than most agents in recent campaigns). Full 5/5 would require explicit working tree path, branch name, and current commit SHA in the verdict block. The 4652292 merge-base disclosure mitigates the gap but does not fully satisfy PATH GUARD disclosure requirements.

---

### adr-historian (32 — EXEMPLARY)

- **Specificity (5):** Produced ADR-030 covering the resolved-CIF single-authority principle. Updated README index with the new row. Named the specific architectural decision: `get_cif_authority(audit)` as the canonical read function, `require_resolved_cif(audit, action=...)` as the enforcement gate, cif_resolver tri-state (RESOLVED/DECLARED_ZERO/UNKNOWN) as the authority model. Per the ADR template requirement: Status, Date, Phase, Context, Decision, Rejected alternatives, Risks, Rollback, Future impact, Related sections are expected — the campaign report confirms ADR-030 was produced and the README index was updated, which are the two concrete deliverables for this role.
- **Coverage (5):** Full scope for adr-historian: a new ADR was warranted (a new permanent architectural gate was established — this is precisely the "architecture decision entered `decided` state" trigger). The README index row was updated. The append-only discipline (no rewriting of prior ADRs) is structurally guaranteed by the agent's allowed surfaces (`.claude/adr/ADR-NNN-*.md` new files only, `.claude/adr/README.md` index entries). Cross-references in the Related section presumably reference ADR-027 (CIF tri-state, PR #627) and the cif_authority.py service — the campaign report does not explicitly confirm these cross-references, but the ADR template requires them and the historian's mandate covers cross-reference verification.
- **Severity (4):** ADR severity is not a primary concern for this role (it documents decisions, not risks), but calibration applies to the decision scope: ADR-030 correctly captures one decision (single resolved-CIF authority) rather than multiple collapsed decisions (per the "one decision per ADR" rule in the historian's mandate). No evidence of scope collapse or scope inflation.
- **Actionability (5):** The ADR-030 + README index update are immediately actionable governance artifacts. Future agents and operators working on CIF-adjacent changes have a named canonical reference (ADR-030) for the resolved-CIF authority principle. The `require_resolved_cif` gate is now governance-documented, which means future PRs that bypass or weaken it will be subject to ADR-030 conflict detection.
- **Substitution (5):** No substitution. adr-historian is a canonical repo-installed agent (`.claude/agents/adr-historian.md`). DOCS-WRITE capability (`.claude/adr/*`, append-only). Correctly activated: an architecture decision was made during this campaign.
- **Evidence (5):** Two concrete deliverables named: ADR-030 (file) and README index row (edit). The ADR file path (`.claude/adr/ADR-030-*.md`) and README location (`.claude/adr/README.md`) are verifiable on disk. The historian's tool grants (Read, Grep, Glob, Write, Edit) are scoped to the docs surface — no risk of product code mutation. The append-only discipline is enforced by the allowed-surfaces constraint in the agent definition.
- **Environment (3):** Same structural disclosure gap as other agents — working tree path not explicitly self-reported. For adr-historian this is lower risk than for reviewers (a wrong-path ADR write would produce a file in the wrong location, which is detectable), but the PATH GUARD disclosure requirement applies uniformly. No evidence of a wrong-path write.

---

## Weak-verdict warnings

No agent scored NEEDS-TUNING or UNRELIABLE in this campaign. All 5 roles scored EXEMPLARY (28-35 range).

**GATE 5 minor gap — testing-verification substitution not disclosed:**

The campaign report lists "testing-verification" as a participating role but this name does not correspond to a canonical repo-installed agent. The nearest canonical is `test-coverage-reviewer`. The substitution dimension was scored 4/5 (not 5/5) because the capability-equivalence statement and registry-mismatch log required by GATE 5 are absent from the campaign's Section 2 agent table. This is a disclosure gap, not a coverage failure.

Disposition required per GATE 4: **SCHEDULED** — Add GATE 5 substitution disclosure to the PR body for "testing-verification" role: name the capability equivalence ("testing-verification execution scope covers the regression-verification scope of test-coverage-reviewer; test execution was performed inline by orchestrator"), log the registry mismatch for follow-up. Target: prior to next campaign that activates the same role pattern.

**Environment dimension uniform structural gap (3/5 across all 5 roles):**

Every agent in this campaign scored 3/5 on Environment because the working tree path (C:\PZ-cif-guard), branch (feat/cif-authority-consistency-guard), and examined commit SHA (20d6a0c) were not self-reported in individual verdict blocks — they are recoverable from the campaign objective statement but not self-disclosed per the PATH GUARD disclosure standard. This is the same prompt-level structural gap observed in the 2026-06-16-deploy-gate-pr625-626-627 campaign (all 7 deploy agents scored 3/5 on Environment for the same reason).

No individual GATE 4 disposition triggered (no NEEDS-TUNING or UNRELIABLE scores). This gap is a prompt-template deficiency, not an agent failure class.

**Prompt-level recommendation (not a GATE 4 item):** Add to each GATE 1 convergent-review agent prompt: "In your verdict block, state: (a) working tree path examined, (b) branch name, (c) commit SHA examined, (d) confirm those paths exist and match the canonical PATH GUARD registry." This aligns with the identical recommendation issued in the 2026-06-16 deploy gate scorecard — the gap is structural and persistent across both campaign types (deploy gate and GATE 1 convergent review).

---

## Repeated failure hints

**5 most recent campaign scorecards reviewed:**
1. 2026-06-16: deploy-gate-pr625-626-627
2. 2026-06-15: deploy2-pr602-pr608
3. 2026-06-13: deploy1-authority-train
4. 2026-06-13: campaign-02-5-authority-completion
5. 2026-06-12: cn-hsn-false-block-fix

### test-coverage-reviewer / testing-verification — PATTERN NOTE

The 2026-06-12 CN false-block scorecard flagged `REPEATED-WEAK: test-coverage-reviewer` for severity inflation across 4 prior campaigns. In the current campaign, the "testing-verification" role showed NO severity inflation (Severity 4/5, clean calibration). Two interpretations:
- The orchestrator performed test verification inline rather than dispatching the canonical test-coverage-reviewer agent, naturally avoiding the inflation pattern.
- OR test-coverage-reviewer severity calibration improved since the REPEATED-WEAK flag.

Since the GATE 4 disposition from the CN false-block scorecard required a governance issue tagged `agent-tuning` for test-coverage-reviewer, and the current campaign did not dispatch that canonical agent, the repeated-weak flag status remains active pending a direct dispatch of `test-coverage-reviewer` in a future campaign where its calibration can be re-assessed.

**REPEATED-WEAK status: test-coverage-reviewer remains flagged from 2026-06-12-cn-hsn-false-block-fix.md (4 occurrences, severity inflation). Not cleared by this campaign (agent was not dispatched directly).**

### reviewer-challenge — NO FLAG

Prior scorecard for this agent (2026-06-12-cn-hsn-false-block-fix): EXEMPLARY (28), Severity 2/5 due to unverified HIGH claim about operator recovery loss. In the current campaign, reviewer-challenge scored Severity 4/5 with calibrated findings that all resolved. Single prior severity gap has not recurred. No repeated-weak flag.

### backend-safety-reviewer — CONSISTENT EXEMPLARY

Prior appearances: 2026-06-12-cn-hsn-false-block-fix (33, EXEMPLARY). Current campaign: 32, EXEMPLARY. Consistent performance on customs-adjacent backend review. No flags.

### adr-historian — CONSISTENT EXEMPLARY

No prior NEEDS-TUNING or UNRELIABLE appearances in the recent 5 scorecards (this agent activates only on architecture-decision campaigns). Current campaign: 32, EXEMPLARY. No flags.

### security-write-action-reviewer — NO PRIOR RECENT DATA

Not separately scored in the 5 most recent campaign scorecards (it was activated as part of deploy gate scopes where its function is subsumed by deploy-security-reviewer). Current campaign activation is on the GATE 1 convergent-review side, which is the correct use. No historical baseline for this specific activation pattern. Current campaign: 30, EXEMPLARY.

**No new REPEATED-WEAK flags triggered.**

---

## Notable quality signals

**GATE 4 out-of-diff discipline:** backend-safety-reviewer and/or the GATE 1 convergent review surfaced two out-of-diff findings on routes_dhl_documents.py (Issue #641: server-side path/attachment exfil, HIGH; Issue #642: false received=True). These were correctly NOT folded into PR #643 and instead filed as separate GitHub issues per GATE 4 / Lesson I classification discipline. This is the intended behavior of the GATE 1 review group — the reviewer found findings outside the diff and dispositioned them correctly rather than suppressing them or bloating the PR scope.

**Lesson A compliance confirmed:** The campaign explicitly states "real-builder regression tests included (no stubs for the gate contract)." The AWB 2315714531 fixture in test_cif_authority.py is a named real-world anchor, not a stub. This is the Lesson A binding requirement for coordinator/builder PRs — met.

**GATE 2 slot verified before PR open:** The campaign confirms GATE 2 compliance (open PRs #637 docs, #630 impl verified as 2 open before opening #643). This is a governance discipline that does not affect agent quality scores but confirms the overall campaign was GATE-compliant at open time.

**Pure function design for the gate service:** The `get_cif_authority(audit)` function is described as "pure, never raises" — a safety property that makes it callable from any context without defensive try/except. The `require_resolved_cif` function carries all the raise logic. backend-safety-reviewer explicitly confirmed this design, which is the correct architectural split for a customs-authority gate service. The split prevents silent swallowing of unresolved-CIF conditions in callers.

---

## Self-evaluation cadence check

**Most recent self-eval:** `.claude/memory/scorecards/self-eval-2026-06-13.md` (written 2026-06-13)
**Today:** 2026-06-17
**Days elapsed:** 4 calendar days
**Trigger threshold:** 7 calendar days OR SELF-DEGRADATION flag + 3rd campaign run since flag

**Result: Self-evaluation NOT triggered.** 4 days < 7-day threshold. No SELF-DEGRADATION flag in the 2026-06-13 self-eval (final assessment: "No degradation detected").

**Next self-eval due:** 2026-06-20 (7 calendar days from 2026-06-13).

---

## Campaign quality summary

**GATE 1 convergent review effectiveness:** EXEMPLARY — Full pre-open GATE 1 gate with all required roles, unanimous convergence, all HIGH/CRITICAL findings resolved inline, GATE 4 out-of-diff findings filed as Issues #641 and #642 (not folded into PR scope).

**Key value from the GATE 1 review group:**
- backend-safety-reviewer's identification of the `or 0` silent-zero pattern in routes_action_proposals is the highest-value finding in this campaign — a financial silent-suppression bug in a customs-adjacent code path, resolved before PR open.
- The out-of-diff Issues #641/#642 filed from routes_dhl_documents.py demonstrate the review group functioning at full scope (finding real issues beyond the stated diff) while maintaining PR scope discipline (not absorbing out-of-diff fixes).
- adr-historian's ADR-030 production canonicalises the resolved-CIF authority principle as a governance artifact — future CIF-adjacent PRs now have a named ADR to reference when the gate is challenged.

**Agent reliability:** 5/5 EXEMPLARY. No NEEDS-TUNING. No UNRELIABLE. No integrity failures.

**Outstanding items from this campaign:**
1. GATE 5 SCHEDULED: Add testing-verification substitution disclosure to the PR body (see Weak-verdict warnings above).
2. REPEATED-WEAK ACTIVE: test-coverage-reviewer severity inflation flag from 2026-06-12-cn-hsn-false-block-fix.md — requires direct dispatch in a future campaign to assess calibration improvement.
3. Prompt-level recommendation (both campaign types): Add PATH GUARD disclosure requirement to GATE 1 convergent-review agent prompts (Environment dimension uniform gap). Combine with the identical recommendation from 2026-06-16 deploy gate scorecard.
