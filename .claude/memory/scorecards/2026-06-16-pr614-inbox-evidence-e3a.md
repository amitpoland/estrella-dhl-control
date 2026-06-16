# Agent Performance Scorecard — PR #614 Inbox Evidence E3a Backend

**Date:** 2026-06-16
**Campaign:** Campaign 03 Sprint 03.3 Scope C — "Full Evidence panel (+backend)", PR-E3a
**PR:** #614 (https://github.com/amitpoland/estrella-dhl-control/pull/614) — state OPEN
**Branch:** feat/inbox-evidence-endpoint-e3a @ 5206e6e
**Objective:** Add GET /api/v1/inbox/evidence/{item_id} — backend route + resolver only
**Outcome:** GATE 1 satisfied. All 3 HIGH findings from reviewer-challenge resolved inline before PR open.
  Tests: 51 passed (test_inbox_evidence.py 22 cases + test_inbox_contract.py + test_inbox_dhl_evidence_source.py).
  PZ regression: 221 passed / 1 pre-existing failure (verified pre-existing via stash test on clean base).
  GATE 4: Issues #611, #612, #613 filed.
**Agents evaluated:** 2 (backend-safety-reviewer, reviewer-challenge)
**Working tree:** Not explicitly stated in campaign context — campaign executed from scratch clone
  (C:\Users\Super Fashion\PZ APP). Path Guard note: canonical reads should target C:\PZ-verify.

---

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| backend-safety-reviewer | 3 | 3 | 4 | 3 | 5 | 3 | 2 | 23 | NEEDS-TUNING |
| reviewer-challenge | 5 | 5 | 5 | 5 | 5 | 5 | 2 | 32 | EXEMPLARY |

---

## Scoring rationale per agent

### backend-safety-reviewer (23 — NEEDS-TUNING)

- **Specificity (3):** The campaign report records only the outcome label "PASS-WITH-NITS" for this agent.
  No file:line references from backend-safety-reviewer's own verdict block are quoted in the campaign
  summary. The "nits" are unnamed — it is not stated what they were. A strong verdict block would name
  each nit with a file path and line reference. This is the core specificity gap: the agent produced a
  verdict that was recorded as a label without supporting citations.

- **Coverage (3):** The agent's stated scope covers: unsafe POST endpoints, server-side file paths from
  UI, false received=true, missing readiness checks, missing idempotency, direct audit writes. The E3a
  endpoint is GET-only with no writes, so several checklist items are structurally N/A. However, the
  agent should have explicitly confirmed N/A for each inapplicable item. More critically, reviewer-challenge
  subsequently identified 3 HIGH findings within the safety/data-exposure domain that are directly in scope
  for backend-safety-reviewer: (1) DHL summary returning raw unfiltered dict (data exposure), (2)
  matched_identifiers untested and potentially exposed, (3) limit=100000 unbounded email scan. Items 1
  and 3 in particular are safety concerns — unfiltered dict exposure and unbounded resource consumption
  — that fall squarely within "unsafe routes" and "missing readiness checks" scope. Backend-safety-reviewer
  missed all three. Coverage deduction is warranted: the agent's checklist was applied too narrowly to
  write-path concerns, missing read-path data exposure and resource-consumption risks.

- **Severity (4):** The PASS-WITH-NITS verdict is appropriate for a GET-only endpoint with no writes,
  no idempotency surface, and no audit mutations. The agent's severity calibration is not demonstrably
  inflated or deflated — the nits were described as non-blocking. Deduction of 1 point because the agent
  failed to escalate data exposure and unbounded scan (both surfaced by reviewer-challenge as HIGH) — an
  agent that misses HIGH items and returns PASS implicitly miscalibrates severity by omission.

- **Actionability (3):** The unnamed nits cannot be actioned. An operator reading "PASS-WITH-NITS"
  from this agent's verdict block has no specific items to address, follow up on, or file as GATE 4
  issues. The nits became invisible. In contrast, reviewer-challenge's findings directly produced 5
  code changes and 2 GATE 4 issues. The backend-safety-reviewer verdict contributed zero actionable
  items to the campaign record.

- **Substitution (5):** No substitution. The agent is in the canonical registry at
  `.claude/agents/backend-safety-reviewer.md`. GATE 5 N/A.

- **Evidence (3):** No quoted output, no grep citations, no file:line references from the agent's own
  run appear in the campaign report. The campaign records the verdict label only. For a review agent,
  the evidence is the verdict block — without it being quoted, the quality of the underlying analysis
  is unverifiable. The agent may have done thorough work internally, but without a quotable artifact
  the scorecard cannot credit what is not visible.

- **Environment (2):** The campaign does not record which working tree path backend-safety-reviewer
  operated against, which commit SHA was examined, or confirmation that the cited files exist at that
  path. The PATH GUARD convention requires C:\PZ-verify; the campaign was run from the scratch clone
  (C:\Users\Super Fashion\PZ APP), which is designated RETIRED per CLAUDE.md. The agent did not
  disclose its working path in the verdict block. This is a recurring environment-disclosure gap
  (see self-eval-2026-06-15.md §7) now receiving a score of 2 rather than the "standard" 3, because
  the underlying path is the retired scratch clone — a path the PATH GUARD explicitly prohibits as
  a source of truth. If the agent read files from the retired clone, any file-hash or line-reference
  claims carry source-drift risk. No disclosure = no ability to audit.

---

### reviewer-challenge (32 — EXEMPLARY)

- **Specificity (5):** First-pass verdict named 3 HIGH findings and multiple MEDIUMs with concrete
  specificity: Finding 1 identified DHL summary returning raw dict without allowlisting; Finding 2
  identified matched_identifiers as untested and potentially exposed; Finding 3 identified limit=100000
  as unbounded; Finding 5 identified exception-string leakage path; Finding 7 identified unbounded
  reason string. Each finding names the exposure class and the mechanism. Second-pass (post-fix)
  verdict confirmed all 3 HIGH findings closed with concrete artifact references (Test 17 pins
  matched_identifiers absent; `_DHL_SUMMARY_KEYS` allowlist with exactly 9 keys; limit=500).

- **Coverage (5):** The agent operated in two rounds — initial adversarial pass + post-fix confirmatory
  pass. Coverage spanned: admin-gate timing (pre-handler vs post-handler dispatch), data exposure
  (DHL summary dict, matched_identifiers), resource consumption (email scan limit, reason truncation),
  error information leakage (exception string in response body), and test coverage of security
  invariants. The second pass explicitly confirmed each resolved item. Multi-round coverage is the
  correct operating pattern for a PR gate reviewer.

- **Severity (5):** The three HIGHs are correctly calibrated. DHL summary unfiltered data exposure
  (attacker learns internal DHL tracking fields not included in the allowlist) is genuinely HIGH for
  a route accessible to non-admin roles for proposal items. Unbounded email scan limit=100000 is HIGH
  (resource exhaustion / DoS vector on an authenticated but non-admin-restricted path). Exception-string
  leakage and unbounded reason are correctly rated MEDIUM (information disclosure without direct
  exploitation path). After fixes, the second-pass PASS-WITH-NITS is correctly calibrated — the
  remaining nits are cosmetic, not safety-bearing. No severity inflation, no deflation.

- **Actionability (5):** Every finding translated directly to a code change: `_DHL_SUMMARY_KEYS`
  allowlist added, Test 17 added to pin matched_identifiers absent, limit bounded to 500, exc-string
  replaced with generic `evidence_read_error`, reason truncated `[:500]`. The second pass confirmed
  each fix landed correctly. The reviewer's output was the direct driver of 5 distinct code hardening
  actions, all of which are now pinned by tests. This is exemplary actionability.

- **Substitution (5):** No substitution. Canonical registry agent `.claude/agents/reviewer-challenge.md`
  invoked directly. GATE 5 N/A.

- **Evidence (5):** The campaign report quotes the finding structure: Finding 1 (DHL summary unfiltered),
  Finding 2 (matched_identifiers untested), Finding 3 (limit unbounded), Finding 5 (exc-string leak),
  Finding 7 (reason unbounded). The second-pass verdict named specific remediation artifacts (`_DHL_SUMMARY_KEYS`,
  Test 17, limit=500, `evidence_read_error`, `[:500]`) and confirmed `safe_to_act: yes`. The evidence
  chain from finding → fix → test is complete and verifiable.

- **Environment (2):** Same campaign, same environment disclosure gap as backend-safety-reviewer.
  The working tree path examined is not stated in the reviewer-challenge verdict block. Campaign executed
  from scratch clone (retired per PATH GUARD). Reviewer-challenge's file reads are inspect-only (Read/Grep/Glob
  tools) so the concern is source-drift risk on any grep/line citations, not write-path contamination.
  The agent's core findings are logic-based (contract analysis) rather than file-content-dependent,
  which partially mitigates the risk — but the disclosure gap remains a structural failing per the
  Environment dimension definition. Score of 2 matches the scorecard standard for "missing disclosure
  that masked a failure" where the failure class is PATH GUARD violation (retired clone as source).

---

## Weak-verdict warnings

### backend-safety-reviewer (NEEDS-TUNING — 23)

**Failed / weak dimensions:** Specificity (3), Coverage (3), Actionability (3), Evidence (3), Environment (2)

**Core gap:** The agent returned PASS-WITH-NITS but missed 3 findings later classified as HIGH by
reviewer-challenge — DHL summary unfiltered data exposure, matched_identifiers exposure, and unbounded
email scan limit. These are read-path data exposure and resource-consumption risks, which are within
the spirit of "unsafe routes" and "missing readiness checks" in the agent's prompt scope, even though
the endpoint has no writes.

**Verdict block evidence gap:** No quoted output from backend-safety-reviewer's verdict block appears
in the campaign record. The verdict is a label ("PASS-WITH-NITS") without supporting citations. This
makes it impossible to verify whether the agent checked and dismissed these risks, or simply did not
check them. Either outcome is a quality failure: dismissal of HIGH data-exposure risks without
documentation is a severity miscalibration; non-inspection is a coverage gap.

**Relevant excerpt from campaign report:**
> "backend-safety-reviewer — reviewed the route + resolver for unsafe writes, false evidence, fake
> paths, missing idempotency. Verdict: PASS-WITH-NITS. No HIGH/CRITICAL."

The 3 items subsequently found by reviewer-challenge (DHL summary filter, matched_identifiers, limit
bounding) were all present in the code at the time backend-safety-reviewer ran. The agent's checklist
is write-path focused; a GET-only endpoint requires a read-path safety adaptation that the current
prompt does not explicitly mandate. This is a prompt-scope gap as much as an individual run failure.

**GATE 4 disposition required** (RULE 6 — NEEDS-TUNING verdicts are GATE 4 salvage findings):
- **DISPOSITION: SCHEDULED** — Add read-path safety checklist to backend-safety-reviewer scope for
  GET endpoints: (a) does the response include any raw object that should be allowlisted? (b) are
  any query parameters unbounded (limit, offset, depth) without server-side capping? (c) does the
  error response leak exception detail? (d) is any field excluded from the response via explicit
  allowlist rather than by omission? Target: next agent prompt tuning session. Combine with
  deploy-persistence-storage-reviewer and deploy-release-manager SCHEDULED tuning items from
  2026-06-15-deploy2-pr602-pr608.md.

**Re-dispatch recommendation:** backend-safety-reviewer should be re-dispatched against PR #614 with
an explicit GET-endpoint safety checklist covering data allowlisting, unbounded parameters, and error
leakage — if the merge review window remains open. If the fixes are already in place and confirmed by
Test 17 + the 22-case suite, re-dispatch is optional but the prompt tuning is still mandatory.

---

## Repeated failure hints

**5 most recent campaign scorecards reviewed** (from C:\PZ-verify):
1. 2026-06-15-pr522-merge-gate-wfirma-grammar.md — backend-safety-reviewer: EXEMPLARY (29)
2. 2026-06-14-pr585-529-price-source-authority.md — backend-safety-reviewer: EXEMPLARY (34)
3. 2026-06-12-cn-hsn-false-block-fix.md — backend-safety-reviewer: EXEMPLARY (33); reviewer-challenge: EXEMPLARY (28)
4. 2026-06-12-pr563-apikey-nonascii-hotfix.md — backend-safety-reviewer rounds 1+2: EXEMPLARY (35); reviewer-challenge rounds 1+2: EXEMPLARY (35)
5. 2026-06-13-campaign-02-5-authority-completion.md — neither agent appeared

**backend-safety-reviewer pattern:**
- pr522 (2026-06-15): EXEMPLARY (29) — Lesson J path review, pure renderer confirmation
- pr585 (2026-06-14): EXEMPLARY (34) — caught genuine 500 risk (ValueError on non-numeric unit_price)
- cn-hsn (2026-06-12): EXEMPLARY (33) — precise audit path analysis with file:line references
- pr563 (2026-06-12): EXEMPLARY (35) — highest-quality run, complete auth surface verification
- PR-E3a (2026-06-16): NEEDS-TUNING (23) — missed 3 HIGH data exposure / resource risks on GET endpoint

**Assessment:** This is the first NEEDS-TUNING for backend-safety-reviewer across the 5 most recent
campaigns reviewed. The agent has a strong baseline (4 consecutive EXEMPLARY runs including a 35/35).
The E3a failure appears to be a prompt-scope mismatch — the agent's checklist is optimized for
write-path risks and was applied to a GET-only endpoint without the necessary read-path adaptation.
No REPEATED-WEAK flag triggered (requires ≥2 NEEDS-TUNING or UNRELIABLE in prior 6 runs; this is
the first such instance). However, the failure mode (missed data-exposure and resource risks on
read-only endpoints) is a novel failure class that should be addressed before the next read-path
endpoint review.

**reviewer-challenge pattern:**
- pr522 (2026-06-15): EXEMPLARY (33) — caught critical PR-body scope dishonesty
- pr585 (2026-06-14): EXEMPLARY (32) — found real 500 risk edge cases
- cn-hsn (2026-06-12): EXEMPLARY (28) — one unverified HIGH claim (dashboard recovery), but strong overall
- pr563 (2026-06-12): EXEMPLARY (35) — perfect run
- PR-E3a (2026-06-16): EXEMPLARY (32) — 3 HIGH findings all real, all fixed, second-pass confirmation clean

**Assessment:** reviewer-challenge shows consistent EXEMPLARY performance (5 consecutive EXEMPLARY
runs). No REPEATED-WEAK flag. The severity calibration issue noted in cn-hsn (unverified HIGH-1
claim) did not recur in PR-E3a — all 3 HIGHs in E3a were real and led to code changes. The agent
continues to function as the primary safety net for this codebase.

**No REPEATED-WEAK flags triggered.** Single NEEDS-TUNING instance for backend-safety-reviewer is
first occurrence; does not meet the ≥2 of 6 threshold for REPEATED-WEAK designation.

---

## Environment disclosure note (systemic)

Both agents scored 2/5 on Environment. This continues the systemic pattern documented in
self-eval-2026-06-15.md §7 (Environment honesty — 2/5, SELF-DEGRADATION DETECTED). That self-eval
recorded a GATE 4 ISSUE disposition (GitHub issue #597, labels: governance, follow-up). The E3a
campaign adds one additional data point: the scratch clone (C:\Users\Super Fashion\PZ APP) was used
as the working context despite being designated RETIRED per PATH GUARD. Agents that do not disclose
their working path cannot be audited for source-drift compliance. This is the primary systemic
governance debt the operator should track against issue #597.

---

## Self-evaluation cadence check

**Most recent self-eval:** C:\PZ-verify\.claude\memory\scorecards\self-eval-2026-06-15.md
**Written:** 2026-06-15
**Today:** 2026-06-16
**Calendar days elapsed:** 1 (threshold: 7)
**SELF-DEGRADATION DETECTED in that self-eval:** YES (Environment honesty dimension, 2/5)
**Trigger: 3rd campaign scorecard run since SELF-DEGRADATION flag?**
  - self-eval-2026-06-15.md was written 2026-06-15 (yesterday)
  - This E3a scorecard is the FIRST campaign scorecard run after that flag
  - Counter: 1 of 3 needed to trigger
**Result: Self-evaluation NOT triggered.** Neither condition met (1 day < 7-day threshold; 1 of 3
campaign runs since SELF-DEGRADATION flag, not yet 3).

**Next self-eval due:** 2026-06-22 (7 calendar days from 2026-06-15) OR at the 3rd campaign scorecard
run after self-eval-2026-06-15.md, whichever comes first. This is run 1 of 3.

---

## Campaign quality summary

**Gate effectiveness:** reviewer-challenge was the functional safety gate this campaign. Its
multi-round adversarial pattern (REVISE with 3 HIGHs → fixes applied → PASS-WITH-NITS) is exactly
the intended operating mode for GATE 1 compliance. The 3 HIGH findings were real, all fixed, all
now pinned by tests. GATE 1 was satisfied correctly.

**Structural gap:** backend-safety-reviewer and reviewer-challenge ran in parallel on the same code.
The expected behavior is defense-in-depth — backend-safety-reviewer catches write-path issues,
reviewer-challenge catches design and logic issues. In E3a, reviewer-challenge absorbed all safety
work because backend-safety-reviewer's checklist did not adapt to a GET-only data-exposure context.
The system remained safe (reviewer-challenge caught everything), but the defense-in-depth redundancy
failed to operate as designed.

**GATE 4 dispositions recorded in campaign:** Issues #611 (get_email_by_id follow-up), #612 (admin
helper extraction), #613 (pre-existing PZ CSV test failure). All dispositions filed per GATE 4. The
NEEDS-TUNING disposition for backend-safety-reviewer (SCHEDULED above) is the new disposition
added by this scorecard.

**Agent reliability:** 1/2 EXEMPLARY, 1/2 NEEDS-TUNING. reviewer-challenge is the reliable safety
layer; backend-safety-reviewer requires prompt tuning for read-path endpoint coverage.
