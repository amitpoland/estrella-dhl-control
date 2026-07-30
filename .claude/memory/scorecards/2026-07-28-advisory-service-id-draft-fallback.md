# Campaign Scorecard: Advisory Service-ID Draft Fallback

**Date:** 2026-07-28
**Campaign slug:** advisory-service-id-draft-fallback
**PR:** #1037 (draft — branch fix/advisory-service-id-draft-fallback)
**Task:** Repair duplicated freight/insurance service-ID authority so Customer Master advisory can calculate charges when the draft already contains valid wFirma service products, without silently changing financial values.
**Commits:** 2 commits over origin/main
**Outcome:** GATE 1 satisfied; deploy + live browser verification held (operator-gated)
**Observer trigger:** RULE 2 auto-fire — 2 distinct named-agent invocations dispatched (security-write-action-reviewer, reviewer-challenge) meeting the ≥3 hard-trigger threshold in aggregate with orchestrator

**Resolution rule implemented:** service-identity resolution order CM id → `customer_master`; same-draft saved id → `saved_draft_fallback`; neither → blocked `unresolved`. Amount ALWAYS from Customer Master; fallback supplies identity only, never an amount. 12 targeted tests green (test_service_id_draft_fallback.py); root golden 160/160.

---

## 1. Per-agent scorecard table

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| security-write-action-reviewer | 4 | 4 | 4 | 4 | 5 | 3 | 3 | 27 | ACCEPTABLE |
| reviewer-challenge | 5 | 5 | 4 | 5 | 5 | 4 | 3 | 31 | EXEMPLARY |

---

## Dimension rationale per agent

### security-write-action-reviewer — 27 — ACCEPTABLE

**Specificity (4):** The agent named five distinct confirmed properties: (1) amounts read exclusively from Customer Master, (2) a missing CM amount BLOCKS to `skipped` rather than fabricating, (3) the saved-draft service-ID fallback is absent from the write/apply path, (4) no new CM-write endpoint introduced, (5) per-charge-type isolation is structural. These are specific, meaningful claims that map directly to the campaign's design requirements. The property names are precise enough to be independently verifiable if one knows the implementation. Minor deduction: no file:line references are cited for any of the five confirmations, leaving the confirmation mechanism invisible.

**Coverage (4):** The agent's prompt requires checking: readiness gate, confirmation if destructive, idempotency, audit/execution log, and no direct UI bypass. The relevant axes for this campaign — amount source authority (CM only), blocking behavior on missing amounts, write-path fallback exclusion, and no new write endpoint — are all covered. The audit/execution log check and idempotency verification are not explicitly confirmed in the campaign summary; these are plausibly cleared by the narrow advisory scope (no new write path), but the absence of explicit confirmation is a coverage gap. Score 4 not 5: relevant scope well covered; two standard checklist items not surfaced.

**Severity (4):** ALL CONFIRMED with no HIGH/CRITICAL findings is appropriate calibration for this advisory-only feature. The campaign introduces no fiscal writes, the fallback explicitly blocks at amounts (preventing fabrication), and the write path is unchanged. There is no genuine HIGH/CRITICAL risk in scope. The agent neither inflated the severity of the advisory change (no false positives) nor deflated a real risk (the design was confirmed clean). Minor deduction: the campaign summary does not quote explicit severity labels per confirmed property — only the overall "no HIGH/CRITICAL" conclusion, making it difficult to verify per-item calibration.

**Actionability (4):** The ALL CONFIRMED verdict with five named confirmed properties gives the orchestrator a clear go signal for GATE 1. Each property maps to a specific design requirement; a false return on any one would surface the exact gap. The verdict does not require rediagnosis before acting. Minor gap: the verdict does not state an explicit "CLEARED for PR open" conclusion phrase — it relies on "ALL CONFIRMED, no HIGH/CRITICAL" as the actionable signal. Sufficient but slightly less precise than a conclusion that explicitly authorises the next step.

**Substitution (5):** Canonical registered agent. GATE 5 N/A.

**Evidence (3):** The five confirmed properties are all outcome-stated claims with zero file:line references, grep outputs, or tool-output excerpts cited. "Amounts read exclusively from Customer Master" — which function was inspected? Which line? "The saved-draft service-ID fallback is absent from the write/apply path" — which route was checked, at which line? These are load-bearing security properties and the confirmation mechanism is invisible in the campaign summary. This is a meaningful step below the 2026-07-17 campaign appearance where the agent cited `~7106` as a fuzzy reference plus named specific code constructs (local variable shadow, JWT double-decode). Score 3: no verifiable artifacts cited; outcome-stated only.

**Environment (3):** No explicit worktree path, branch, or commit SHA self-disclosed in the verdict block. The five confirmed properties are consistent with the implementation that was built (as confirmed by the test suite passing), so no path-drift failure occurred. Disclosure was absent. Standard 3/5 per established scoring convention.

---

### reviewer-challenge — 31 — EXEMPLARY

**Specificity (5):** Three distinct findings, each with named file:line citations and specific mechanisms:
- F1: pre-existing wrapper bug in `handleCalculateFromCM` that silently swallowed apply-skip reasons. Exact location: `proforma-detail.jsx:5857`. Exact fix: `r.skipped → r.data.skipped`. Mechanism: `_postM` normalizes to `{ok, data}`.
- F2: write-path asymmetry. Near-line location: `routes_proforma.py ~9896`. Specific concern: `draft_service_id` deliberately omitted from `apply_service_charges` suggestions dict.
- F3: Lesson M concern. Specific UI behavior named: fallback advisory row omits the blocked-state "Edit Customer Master" repair link. Disposition artifact named: PROJECT_STATE.md DECISIONS.
All three findings are independently verifiable by their citations. Maximum specificity.

**Coverage (5):** The agent is mandated to find ≥3 real concerns per review. It returned exactly 3, spanning three distinct concern classes: (1) frontend functional bug in JSX — a pre-existing defect that needed inline repair; (2) backend write-path documentation asymmetry — requiring architectural commentary; (3) governance compliance — Lesson M adherence. Together these cover the frontend, backend-authority, and governance risk surfaces of the feature. The REVISE verdict (not BLOCK) correctly reflects a profile where all findings are resolvable without blocking the PR. No obvious concern class is absent.

**Severity (4):** The three findings exhibit differentiated, appropriate severity as evidenced by their dispositions:
- F1 (silently swallowed skip reasons): treated as an inline fix requirement — HIGH severity, functional defect that caused silent information loss in the advisory UX.
- F2 (write-path asymmetry): treated as a comment disposition — MEDIUM severity, structural confusion risk with no current functional failure.
- F3 (Lesson M governance): treated as a DECISIONS record entry — LOW to MEDIUM, a governance compliance item with no functional impact.
The calibration is correct across all three levels. Minor deduction: the campaign summary does not quote explicit severity labels per finding — severity is inferred from disposition type rather than stated. This inference is accurate but reduces verifiability.

**Actionability (5):** All three findings have concrete, completed dispositions:
- F1: Fixed inline at `proforma-detail.jsx:5857` (`r.skipped → r.data.skipped`).
- F2: Guard comment added above `apply_service_charges` suggestions dict (~routes_proforma.py:9896) explaining `draft_service_id` deliberate omission.
- F3: PROJECT_STATE.md DECISIONS entry recorded (intentional non-error-state decision).
All findings translated directly to artifacts. No finding left with a "noted" or deferred non-disposition. Maximum actionability.

**Substitution (5):** Canonical registered agent. GATE 5 N/A.

**Evidence (4):** F1 has the strongest evidence: exact line number (`proforma-detail.jsx:5857`), exact code change (`r.skipped → r.data.skipped`), and mechanism explanation (`_postM` normalization). That F1 was fixed at exactly this line (per campaign outcome) provides independent post-hoc confirmation the citation was correct. F2 uses a near-line reference (`~9896`) — adequate but approximate. F3 describes a UI behavior (omitted repair link) without a line number — adequate behavioral description, not line-precise. Score 4 not 5: one near-line and one non-line-referenced finding reduce evidence precision below exemplary.

**Environment (3):** No explicit worktree path, branch, or commit SHA self-disclosed in the verdict block. F1's exact line was confirmed accurate by the inline fix implementation, confirming the agent read from the correct tree. Standard disclosure gap; no path-drift failure. Score 3/5 per established convention.

---

## 2. Weak-verdict warnings

No agents scored NEEDS-TUNING (15–21) or UNRELIABLE (7–14). No formal weak-verdict warnings required under the scoring rules. No new GATE 4 salvage dispositions created by this campaign.

**Quality signal within the ACCEPTABLE verdict (informational — not a weak-verdict warning):**

**security-write-action-reviewer (ACCEPTABLE, 27):**

This is the agent's second scored appearance in recent campaigns. Prior appearance (2026-07-17-proforma-privileged-auth.md): EXEMPLARY (28), with Evidence 4/5 — the agent cited `~7106` as a fuzzy line reference and named specific code constructs (local variable shadow, JWT double-decode pattern). In the current campaign: Evidence drops to 3/5 — five confirmed properties with zero file:line references. The property names are correct and specific, but the confirmation mechanism is invisible.

This is a one-data-point dip, not yet a pattern. However, the evidence-quality trajectory warrants monitoring: if the next security-write-action-reviewer appearance also returns outcome-stated confirmations without file:line references, that would represent a systematic evidence gap in a security-review agent, at which point a GATE 4 SCHEDULED disposition for prompt tuning would be appropriate. Do NOT re-dispatch this agent against the same task; the ACCEPTABLE verdict and confirmed security properties are sufficient for GATE 1. Monitor in next appearance.

---

## 3. Repeated failure hints

**5 most recent prior campaign scorecards reviewed (excluding self-eval files):**
1. 2026-07-17: `2026-07-17-proforma-privileged-auth.md` — 4 entities; all EXEMPLARY (28, 33, 34 + orchestrator 34). security-write-action-reviewer: EXEMPLARY (28). reviewer-challenge: EXEMPLARY (33).
2. 2026-07-11: `2026-07-11-pr-queue-clear-b123bd4c-deploy-gate.md` — 8 entities; 6 EXEMPLARY, 2 ACCEPTABLE (deploy-security-reviewer 27; deploy-release-manager 26). Neither target agent appeared.
3. 2026-07-03: `2026-07-03-phase-c-wave2-backend.md` — 3 entities; all EXEMPLARY (30, 33, 34). Neither target agent appeared.
4. 2026-06-22: `2026-06-22-pr720-merge-validation.md` — orchestrator only; EXEMPLARY (35). Neither target agent appeared.
5. 2026-06-22: `2026-06-22-pr720-deploy-gate.md` — 8 entities; 7 EXEMPLARY, 1 ACCEPTABLE (deploy-persistence-storage-reviewer 26 — structural empty-mandate). Neither target agent appeared.

**security-write-action-reviewer appearances in the prior 5-campaign window:**
- 1 appearance: 2026-07-17 — EXEMPLARY (28). Not NEEDS-TUNING or UNRELIABLE. No REPEATED-WEAK flag triggered.

**reviewer-challenge appearances in the prior 5-campaign window:**
- 1 appearance: 2026-07-17 — EXEMPLARY (33). Not NEEDS-TUNING or UNRELIABLE. No REPEATED-WEAK flag triggered.

**Active REPEATED-WEAK flags (carried from prior scorecards):**

`REPEATED-WEAK: agent frontend-flow-reviewer has scored ACCEPTABLE (Evidence 3/5) in 5+ consecutive campaign appearances.`
- GATE 4 ISSUE disposition generated in `2026-06-21-freight-authority-blocker-repair.md`. Operator must confirm the GitHub issue tagged `agent-tuning` has been filed. This agent does not appear in the current campaign (backend-only advisory repair; no UI surface requiring frontend-flow review). No new data point. Flag carries forward — this is now the 7th+ consecutive scorecard cycle escalating this item without operator confirmation.

`REPEATED-WEAK: agent backend-safety-reviewer has scored Evidence 3/5 in multiple recent campaigns. Issue #694 open.`
- In 2026-07-17-proforma-privileged-auth.md, backend-safety-reviewer scored EXEMPLARY (30) with Evidence 4/5 — a positive rehabilitation data point. The 2026-07-17 scorecard noted: do not close Issue #694 until one additional clean severity-calibration run. This agent does not appear in the current campaign. Issue #694 remains open pending the next clean appearance.

---

## 4. GATE 4 disposition

No NEEDS-TUNING or UNRELIABLE verdicts produced by this scorecard. No new GATE 4 salvage dispositions required.

**Existing GATE 4 open items (carried):**
- frontend-flow-reviewer REPEATED-WEAK — ISSUE (agent-tuning tag; operator confirmation of filing is overdue across 7+ scorecard cycles)
- backend-safety-reviewer REPEATED-WEAK — Issue #694 (open; positive data point in 2026-07-17; awaiting one further clean severity-calibration appearance before closing)

---

## 5. Self-evaluation (RULE 5 — calendar trigger)

**Trigger assessment:**
- Most recent self-eval file: `self-eval-2026-07-11.md` (pointer to embedded eval in 2026-07-11 campaign scorecard)
- Actual self-eval embedded date: 2026-07-11 (confirmed by reading that scorecard's §4)
- Note: 2026-07-17-proforma-privileged-auth.md also contained an embedded self-eval (its §5), but no standalone `self-eval-2026-07-17.md` was created. The calendar trigger keys off the most recent `self-eval-*.md` file, which is dated 2026-07-11.
- Today: 2026-07-28
- Calendar days elapsed: 17 days — exceeds 7-day threshold
- SELF-DEGRADATION flag in `self-eval-2026-07-11.md`: NO SELF-DEGRADATION DETECTED (31/35 EXEMPLARY, all dimensions stable or improved from prior eval)
- Counter trigger: not applicable (no active SELF-DEGRADATION flag)
- **Calendar trigger fires. Self-evaluation is executed and written to `self-eval-2026-07-28.md`.**

See `self-eval-2026-07-28.md` for the full self-evaluation.
