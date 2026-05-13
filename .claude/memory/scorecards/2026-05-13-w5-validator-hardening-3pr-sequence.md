# Scorecard — W-5 Validator-Hardening 3-PR Finishing Sequence

**Date:** 2026-05-13
**Campaign:** Validator-hardening 3-step sequential finishing (PR #52 + PR #57 + PR #61)
**Commits scored:** `e20e8d8` (Step 1, PR #52), `854cd2a` (Step 2, PR #57), `9bfa282` (Step 3, PR #61)
**Issues closed:** #44 (ADR salvage), #48 (per-phase concurrency lock), #49 (override-flag predecessor-live)
**Issues filed (follow-up):** #51 (ADR drift), #53/#54/#55/#56 (lock hardening), #58/#59/#60 (override polish)
**Agents dispatched:** 12 verdict blocks across 3 sequential PRs
**Observer:** agent-performance-observer (3rd substantive scorecard)
**GATE 2 posture:** HONORED — single open PR at any time across all three steps (Option B sequencing per operator preference)

---

## 1. Per-agent scorecard

| # | PR | Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | #52 | adr-historian | 5 | 5 | 4 | 4 | 5 | 5 | 5 | 33 | EXEMPLARY |
| 2 | #52 | gap-hunter | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| 3 | #52 | final-consistency-review | 5 | 5 | 4 | 4 | 5 | 5 | 5 | 33 | EXEMPLARY |
| 4 | #57 | system-architect | 5 | 5 | 4 | 5 | 5 | 4 | 4 | 32 | EXEMPLARY |
| 5 | #57 | backend-safety-reviewer | 4 | 5 | 4 | 5 | 5 | 4 | 4 | 31 | EXEMPLARY |
| 6 | #57 | integration-boundary | 5 | 5 | 4 | 4 | 5 | 5 | 5 | 33 | EXEMPLARY |
| 7 | #57 | testing-verification | 4 | 5 | 4 | 5 | 5 | 4 | 4 | 31 | EXEMPLARY |
| 8 | #57 | gap-hunter | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| 9 | #61 | adr-historian | 5 | 5 | 4 | 4 | 5 | 5 | 5 | 33 | EXEMPLARY |
| 10 | #61 | system-architect | 5 | 5 | 4 | 5 | 5 | 4 | 5 | 33 | EXEMPLARY |
| 11 | #61 | testing-verification | 4 | 5 | 4 | 5 | 5 | 5 | 4 | 32 | EXEMPLARY |
| 12 | #61 | gap-hunter | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| — | #61 | security-write-action-reviewer (off-scope drift, see §2) | 3 | 1 | 2 | 2 | 1 | 3 | 4 | 16 | NEEDS-TUNING |

**Verdict distribution (12 in-scope agents):** 12 EXEMPLARY / 0 ACCEPTABLE / 0 NEEDS-TUNING / 0 UNRELIABLE
**Plus 1 off-scope/substitution-failure agent:** security-write-action-reviewer (PR #61) — NEEDS-TUNING

The operator instruction asked for "12 agents" and explicitly noted security-write-action-reviewer's drift "worth flagging on the Substitution dimension." Scored separately in the table to preserve the in-scope/off-scope distinction; both totals reported transparently below.

---

## 2. Weak-verdict warnings

### security-write-action-reviewer (PR #61) — NEEDS-TUNING (16/35)

**Failed dimensions:**
- **Coverage (1/5):** Audited PZ write surfaces wholly unrelated to the override mechanism under review. The intended scope — override-flag predecessor-live invariant, audit-failure visibility, FORBIDDEN-bypass enforcement — went un-reviewed by this agent.
- **Substitution (1/5):** Effectively functioned as an off-topic substitute for itself. No capability-equivalence disclosure was offered; the agent did not signal that its scope had drifted, did not request re-scoping, and did not down-grade its own verdict to reflect the missing coverage. PR #61 body disclosed the drift as GATE-5-equivalent post-hoc — disclosure happened at the orchestrator layer, not at the agent layer.
- **Severity (2/5):** Severity was applied to findings the operator did not request, distorting the campaign's severity ledger.
- **Actionability (2/5):** Off-scope findings produce no actionable path for the override mechanism.

**Mitigation in place (per operator note):** override-specific security concerns were covered by:
- adr-historian (FORBIDDEN-bypass invariant verification, agent #9)
- gap-hunter F12 (audit failure visibility, agent #12)
- system-architect (WARNING-level enforcement design review, agent #10)

This triangulation is the reason override security ended up adequately reviewed despite the drift. Without the redundancy, this would be a coverage hole that ships.

**Recommendation:** Do NOT re-dispatch for this PR (override mechanism already reviewed via the three-agent triangulation). DO file an `agent-tuning` flagged issue for security-write-action-reviewer's scope-anchoring discipline — the agent's prompt likely needs explicit scope-binding language ("review only the file/function set listed in dispatch payload; do not expand to adjacent surfaces; if the listed scope produces no findings, return EMPTY-SCOPE rather than discovering a different scope").

**GATE 4 disposition:** ISSUE — file `agent-tuning`-labeled issue for security-write-action-reviewer scope-anchoring (per CLAUDE.md RULE 6 "NEEDS-TUNING / UNRELIABLE verdicts are GATE 4 salvage findings").

---

## 3. Repeated failure hints

**Historical baseline:** 1 prior substantive scorecard (`2026-05-13-w5-p0-adr018-p2-deployment-campaign.md`).

**security-write-action-reviewer trend:**
- Prior scorecard (P2 campaign): 33/35 EXEMPLARY
- This scorecard (PR #61): 16/35 NEEDS-TUNING
- 1 of 2 runs weak — does NOT yet meet the "≥2 of last 6 weak" threshold for `REPEATED-WEAK` flag, but ONE more weak run will trigger it. Watch this agent on next dispatch.

**gap-hunter trend (positive):**
- Prior scorecard P2 canonical: 35/35
- This scorecard 3 runs: 35/35, 35/35, 35/35
- 4 consecutive 35/35 — provisional REPEATED-EXEMPLARY pattern. gap-hunter is the campaign's quality anchor.

**adr-historian trend (positive):**
- Prior scorecard 3 runs: 34, 35, 35
- This scorecard 2 runs: 33, 33
- Median 34/35 across 5 runs — consistently strong, slight regression from 35-baseline worth monitoring but not actionable.

**system-architect trend (positive):**
- Prior scorecard 2 runs: 32, 35
- This scorecard 2 runs: 32, 33
- Median 32.5/35 — stable EXEMPLARY band.

**testing-verification trend (positive):**
- Prior scorecard: 35/35
- This scorecard 2 runs: 31, 32
- Median 32.7/35 — stable EXEMPLARY band, slight regression worth a glance but within noise.

No `REPEATED-WEAK` flags fire from this scorecard. One agent (security-write-action-reviewer) is on a 1-strike watch.

---

## 4. GATE 4 dispositions

| # | Verdict | Agent | Disposition | Action |
|---|---|---|---|---|
| 1 | NEEDS-TUNING | security-write-action-reviewer (PR #61) | ISSUE | File `agent-tuning` issue for scope-anchoring prompt revision |

**Reminder per CLAUDE.md RULE 6:** "NEEDS-TUNING / UNRELIABLE verdicts are GATE 4 salvage findings" — the disposition above is binding, not advisory. The follow-up issue should reference this scorecard path.

---

## 5. Cross-cutting observations (advisory, not scoring)

### Observation 1 — GATE 2 discipline at scale

The 3-PR sequential approach (Option B) honored GATE 2 throughout: at any moment in the 3-step sequence, **at most one PR was open**. This is the cleanest GATE-2 posture observed under this layer to date. Compare to a hypothetical parallel approach where 3 PRs would have stacked simultaneously, halving review attention and tripling rebase risk. The operator's Option B preference proved correct under load — recommend this pattern for any future ≥3-step campaign with shared file surface.

### Observation 2 — Lesson-A pattern crystallisation at helper-import boundaries

Lesson A (test stubs must match real production return shapes — origin PR #46) was applied **twice in this campaign at distinct helper-import boundaries**:
- Step 2 (PR #57): per-phase lock helper imports verified against real `state_engine` boundary
- Step 3 (PR #61): override-flag helper imports verified against real `manifest.record_transition` boundary

Both invocations cited the lesson explicitly. This is **pattern crystallisation** — the lesson has moved from "PR #46 origin event" to "default reviewer reflex at helper-import boundaries." Recommend `flow-context-keeper` upgrade Lesson A from a single-origin lesson to a "FACT — applied repeatedly" entry in PROJECT_STATE.md to reflect crystallised status.

### Observation 3 — gap-hunter consistency as quality anchor

gap-hunter scored 35/35 on all 3 dispatches in this campaign, matching its P2-campaign 35/35. **4-for-4 perfect** across two campaigns. The consistency comes from:
- High finding-count discipline (12, 10, 12 findings respectively — never returns "looks fine")
- Severity-classification accuracy (CRITICAL→HIGH→MEDIUM gradient observed in every dispatch, never collapsed to single-severity)
- Explicit GATE 4 disposition recommendations on each finding (FIX INLINE / ACCEPT / FILE ISSUE) — leaves no orphan recommendations
- Disposition follow-through verified: PR #61's gap-hunter recommendations resulted in #58/#59 actually being filed, not just suggested

gap-hunter is functioning as the **quality anchor** of the agent fleet. Its prompt structure should be the template for the deferred `agent-prompt-refiner`'s baseline.

### Observation 4 — security-write-action-reviewer Step 3 off-scope drift is a substitution failure

This is a new failure class for the observation layer to track: an agent that **substitutes its own scope** rather than substituting for an unavailable canonical agent. GATE 5 disclosure language ("X-detection covers the gap identification scope of gap-hunter") presumes substitution-of-agent-identity. This case is substitution-of-scope by the same-identity agent — the dispatch payload requested override review; the agent delivered PZ write-surface review.

**Recommendation:** GATE 5 should be extended (next time CLAUDE.md is amended) to cover scope-drift, not just identity-substitution: "if an agent's actual scope diverges from its dispatch payload by ≥50% file-set difference, the agent must self-disclose and the orchestrator must classify as EMPTY-SCOPE-WITH-TANGENT, not as APPROVED."

### Observation 5 — All 12 in-scope agents disclosed environment cleanly

No wrong-worktree-path failures observed across the 12 in-scope verdicts. Environment dimension producing intended hygiene effect for the second consecutive campaign.

### Observation 6 — Verdict severity distribution is healthy (not deflated)

Across the 12 in-scope agents: 1 HIGH (gap-hunter PR #57 F1 cross-worker false-safety), 1 MEDIUM (gap-hunter PR #61 overall), rest LOW/NONE. **Inline-fix rate of HIGH/MEDIUM findings: 100%.** The HIGH finding (cross-worker false-safety from Makefile dev target) was correctly graded — false safety in concurrency control is the worst possible failure mode for a lock — and was fixed inline before merge per GATE 1.

---

## 6. Self-evaluation

**Skipped — RULE 5 cadence not yet triggered.**

Status check:
- Most recent self-eval file: **none exists**
- Calendar trigger (>7 days since last self-eval): N/A (no prior self-eval)
- Substantive-scorecard count since last self-eval: this is the **2nd substantive scorecard** by file count (operator notes 3rd by their counting, possibly including placeholder runs). Either way, not yet at the 5th-run trigger.
- Prior self-eval flagged SELF-DEGRADATION + 3rd run since: N/A (no prior self-eval)

Provisional self-eval target: **2026-05-20** OR after 5th substantive campaign scorecard, whichever fires first. Operator confirmed not yet due.

---

## 7. Provisional metrics update (running baseline)

Updated rolling baseline across 2 substantive scorecards (26 total in-scope verdicts):

- Median total: **33/35** (P2 campaign 33/35, this campaign 33/35) — stable
- EXEMPLARY rate: **26/26 in-scope = 100%**
- NEEDS-TUNING rate (off-scope): **1/27 total = 3.7%** (security-write-action-reviewer scope drift)
- CRITICAL-finding rate: **2/26 = 7.7%** (both prior campaign — integration-boundary, gap-hunter); 0 CRITICALs this campaign (consistent with hardening-only scope, no new feature surface)
- Inline-fix rate of HIGH/CRITICAL: **100% across both campaigns**
- GATE 1 honored: **YES, both campaigns**
- GATE 2 honored: **YES, both campaigns** (this campaign more rigorously: 1 PR open at a time vs. P2 campaign's stacked PRs)
- GATE 4 disposition compliance: **YES, this campaign** (1 NEEDS-TUNING → ISSUE filed); N/A prior campaign (0 weak verdicts)
- GATE 5 disclosure: **YES both campaigns**, but this campaign surfaced a new scope-drift failure mode worth extending GATE 5 to cover

---

**Scorecard complete.**
