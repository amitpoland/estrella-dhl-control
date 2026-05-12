# Scorecard — W-5 P0 + ADR-018 + P2 Deployment Campaign

**Date:** 2026-05-13
**Campaign:** Consolidated W-5 P0 foundation + ADR-018 shadow-mode flag defaults + W-5 P2 proactive customs dispatch
**Commits scored:** `aed13f7` (W-5 P0), `0ac4769` (ADR-018), `996e9f0` (W-5 P2 + 8-agent fixes)
**PRs scored:** #33 (P0 re-review), #43 (ADR-018), #46 (P2)
**Agents dispatched:** 14 verdict blocks across 3 stages
**Observer:** agent-performance-observer (post PR #41 registry refresh validation)

---

## 1. Per-agent scorecard

| # | Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | adr-historian (ADR-018) | 5 | 5 | 5 | 4 | 5 | 5 | 5 | 34 | EXEMPLARY |
| 2 | system-architect (ADR-018) | 5 | 5 | 4 | 5 | 5 | 4 | 4 | 32 | EXEMPLARY |
| 3 | gap-hunter (ADR-018) | 5 | 5 | 4 | 5 | 5 | 5 | 4 | 33 | EXEMPLARY |
| 4 | final-consistency-review (ADR-018) | 4 | 5 | 4 | 4 | 5 | 4 | 4 | 30 | EXEMPLARY |
| 5 | adr-historian (PR #33 re-review) | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| 6 | system-architect (P2) | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| 7 | backend-safety-reviewer (P2) | 4 | 4 | 4 | 5 | 5 | 4 | 4 | 30 | EXEMPLARY |
| 8 | security-write-action-reviewer (P2) | 5 | 5 | 4 | 5 | 5 | 5 | 4 | 33 | EXEMPLARY |
| 9 | testing-verification (P2) | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| 10 | integration-boundary (P2) | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| 11 | gap-hunter (P2 canonical) | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| 12 | adr-historian (P2 canonical) | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| 13 | final-consistency-review (P2, customs-compliance sub) | 4 | 5 | 4 | 4 | 5 | 4 | 4 | 30 | EXEMPLARY |
| 14 | Phase 8 admin endpoint round-trip verification | 4 | 4 | 4 | 4 | 5 | 5 | 5 | 31 | EXEMPLARY |

**Verdict distribution:** 14 EXEMPLARY / 0 ACCEPTABLE / 0 NEEDS-TUNING / 0 UNRELIABLE

---

## 2. Weak-verdict warnings

None. All 14 verdicts scored EXEMPLARY (≥28/35).

The campaign demonstrates the highest signal-to-noise an observed campaign has produced under this layer to date. Notable signal density:

- **Agent #10 (integration-boundary, P2)** is the campaign's highest-value finding: caught a CRITICAL type-contract bug (`pkg["to"]` is `str` from real builder; coordinator iterating it as `List[str]` produced a corrupt comma-separated single-character recipient string) that **all unit tests masked** because they stubbed `to` as `List[str]`. The fix added `_normalise_recipient()` plus a regression test that exercises the real builder (`test_real_builder_to_field_is_str_not_list`) — closes the test/reality gap permanently. This is exactly the failure class integration-boundary exists to detect; full 35/35.

- **Agent #11 (gap-hunter, P2 canonical)** surfaced 7 distinct findings with appropriate severity gradient (2 P0/CRITICAL, 2 P1/HIGH, 3 P2/MEDIUM), 4 fixed inline + 3 cross-phase items filed to Issue #45. Severity calibration is textbook: F1 (`is_awb_stable_for(awb)` returning False 100% due to `db_path=None`) is correctly P0/CRITICAL because it blocks the entire dispatch happy path, while F7 (AWB subject) is correctly P2/MEDIUM as cosmetic.

- **Agent #12 (adr-historian, P2 canonical)** caught ADR-018 Invariant 4 violation that would have polluted state_history forever — shadow bit was embedded as substring `"p2_dispatch_shadow"` in `reason` instead of structured `shadow:True` field. Fix plumbed `shadow:bool` through `state_engine.transition()` + `manifest.record_transition()` with assertion tests. This is the kind of structural finding that prevents 6-month-out reasoning bugs.

- **Agent #5 (adr-historian, PR #33 re-review)** explicitly resolved a prior HIGH finding from the same agent earlier in the day under the new ADR-018 two-category model, demonstrating proper governance closure rather than silent invalidation. Per-flag table at `core/config.py:253-262` cited.

---

## 3. Repeated failure hints

**First substantive scorecard — no historical baseline.**

The post-PR-#41 validation scorecard was a placeholder (registry-reachability test only); this is the first scorecard with real verdict content. Future runs should compare against this campaign as the EXEMPLARY high-water mark for a 14-agent multi-stage campaign.

**Provisional baseline established by this scorecard:**
- Median total: 33/35
- Critical-finding rate: 2/14 agents surfaced CRITICAL findings (integration-boundary, gap-hunter)
- Inline-fix rate: 100% of CRITICAL findings fixed inline before PR open (GATE 1 honored)
- Substitution disclosure rate: 1/14 agents substituted (final-consistency-review for P2 customs-compliance scope) and disclosed per GATE 5

---

## 4. GATE 4 dispositions

No NEEDS-TUNING or UNRELIABLE verdicts produced. No GATE 4 salvage dispositions required for this scorecard.

(Reminder per CLAUDE.md RULE 6: any future NEEDS-TUNING / UNRELIABLE verdict must receive exactly one of SCHEDULED / ISSUE / REJECTED disposition; "recommendation noted" is not valid.)

---

## 5. Self-evaluation

**Skipped — first substantive scorecard.**

Per RULE 5 calendar-driven cadence, self-evaluation requires either (a) most recent self-eval older than 7 calendar days, or (b) prior self-eval flagged SELF-DEGRADATION + 3rd campaign run since. Neither condition is met (no prior self-eval exists). Self-evaluation will trigger at the next campaign scorecard whose date is ≥7 calendar days after a future self-eval, or after the 5th substantive campaign scorecard, whichever comes first.

Provisional self-eval target date: **2026-05-20** (or after 5th campaign scorecard).

---

## 6. Cross-cutting observations (advisory, not scoring)

1. **Multi-pass review caught the most expensive bug late.** The integration-boundary CRITICAL (Agent #10) was found in Stage 3 review, not Stage 1 architecture. This is correct sequencing — integration concerns surface only when implementation is concrete — but suggests integration-boundary should be a hard requirement for any agent dispatching/coordinator change, not an optional add-on.

2. **Shadow-mode discipline (ADR-018) was actively enforced.** Agent #12 catching the embedded-substring shadow tag and converting it to a structured field shows the new ADR is already producing review pressure. Worth tracking whether this becomes a pattern in P3/P4/P5 reviews.

3. **All 14 agents disclosed environment cleanly.** No wrong-worktree-path failures observed. The post-PR-#41 Environment dimension addition is producing its intended hygiene effect — every agent cited the worktree, branch, and (where relevant) commit SHA they actually examined.

4. **Substitution disclosure (GATE 5) was honored once and cleanly.** Agent #13 (final-consistency-review covering customs-compliance scope) was disclosed with capability-equivalence statement. No silent substitutions detected.

---

**Scorecard complete. Observation layer LIVE.**
