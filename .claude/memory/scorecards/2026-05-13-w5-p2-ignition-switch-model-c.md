# Scorecard — W-5 P2 Ignition Switch (Model C)

**Campaign**: PR #72 — W-5 P2 ignition switch Model C
**Merge commit**: 6ad26ed
**Date**: 2026-05-13
**Agents scored**: 8
**Observer**: agent-performance-observer
**Source**: FINAL REPORT for PR #72 (Model C admin force-bypass + boot-replay sweep)

---

## 1. Per-agent scorecard

Scoring scale: 1 (failed) — 2 (weak) — 3 (acceptable) — 4 (strong) — 5 (exemplary).
Per-agent verdict: 28-35 EXEMPLARY / 22-27 ACCEPTABLE / 15-21 NEEDS-TUNING / 7-14 UNRELIABLE.

| # | Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | system-architect | 5 | 5 | 4 | 4 | 5 | 4 | 5 | 32 | EXEMPLARY |
| 2 | adr-historian | 5 | 5 | 4 | 5 | 5 | 5 | 5 | 34 | EXEMPLARY |
| 3 | gap-hunter | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 35 | EXEMPLARY |
| 4 | backend-safety-reviewer | 5 | 5 | 4 | 4 | 5 | 4 | 5 | 32 | EXEMPLARY |
| 5 | security-write-action-reviewer | 5 | 5 | 4 | 5 | 5 | 5 | 5 | 34 | EXEMPLARY |
| 6 | testing-verification | 4 | 5 | 4 | 4 | 5 | 4 | 5 | 31 | EXEMPLARY |
| 7 | integration-boundary | 5 | 5 | 4 | 4 | 5 | 4 | 5 | 32 | EXEMPLARY |
| 8 | final-consistency-review | 5 | 5 | 4 | 5 | 5 | 5 | 5 | 34 | EXEMPLARY |

**Verdict distribution**: 8 EXEMPLARY / 0 ACCEPTABLE / 0 NEEDS-TUNING / 0 UNRELIABLE

---

## 2. Per-agent dimension notes

### Agent 1 — system-architect (32 / EXEMPLARY)
- **Specificity (5)**: All 8 architecture checks tied to concrete artifacts (boot-replay wiring order, settings re-read each tick, coordinator behavior). Verdict block cites enumerated checks.
- **Coverage (5)**: Examined boot-replay startup ordering, settings staleness path, sweep behavior, lock-cleanup memory profile.
- **Severity (4)**: LOW on un-implemented lock cleanup is correctly calibrated; LOW on the load-persisted-flags exception path is justified by the {} default and tick-level re-read but slightly under-tense given startup is a one-shot. Defensible.
- **Actionability (4)**: Notes are observational rather than action-required; appropriate for APPROVED-WITH-NOTES.
- **Substitution (5)**: Canonical agent, no substitution.
- **Evidence (4)**: Architectural reasoning chain stated; no file:line refs in verdict excerpt but argument is structurally cogent.
- **Environment (5)**: Implicit current-worktree examination; no path drift signal.

### Agent 2 — adr-historian (34 / EXEMPLARY)
- **Specificity (5)**: Pinpoints frontmatter table-style deviation; calls out specific ADR-013 amendment relationship.
- **Coverage (5)**: Walks ADR-019 against ADR-013 idempotency contract.
- **Severity (4)**: MEDIUM is the right tier — structurally the force-bypass IS an amendment to ADR-013's idempotency rule. Justified.
- **Actionability (5)**: Recommendation translated to inline fix (frontmatter updated + Relationship-to-ADR-013 section added).
- **Substitution (5)**: Canonical.
- **Evidence (5)**: Cited frontmatter line + new §Relationship section by name.
- **Environment (5)**: No drift; ADR file is in expected docs/adr/ path.
- **Standout call**: The "Amends ADR-013" determination is correct architectural rigor. Force-bypass is genuinely a structural amendment to the idempotency rule, not a side-note. This is the kind of catch that prevents future "wait, why does ADR-013 say X but the code does Y?" archaeology.

### Agent 3 — gap-hunter (35 / EXEMPLARY)
- **Specificity (5)**: 12 enumerated findings (F1-F12), each named with a specific code path / risk vector (silent double-dispatch, dispatch_failed recovery, R-C7 operator_hold, R-C5 _running flag divergence, lock-dict growth, P3 handoff doc, two-write atomicity, lifespan integration test, etc.).
- **Coverage (5)**: Spans operator-error paths, recovery paths, kill-switch wiring (R-C7), state-machine consistency (R-C5), memory pressure, doc handoff for P3, test pollution.
- **Severity (5)**: F1/F2 correctly tiered HIGH (silent double-dispatch + recovery hole); F3-F8 correctly MEDIUM; F9-F12 correctly LOW.
- **Actionability (5)**: Every finding has a clear disposition (FIXED INLINE / accepted with reasoning / followup) — no stranded findings.
- **Substitution (5)**: Canonical.
- **Evidence (5)**: 12 distinct risk vectors enumerated with structural rationale.
- **Environment (5)**: No drift.
- **Cross-cutting note**: F1/F2 HIGH being resolved inline rather than blocking PR is the correct call — the agent's own recommendation matched the fix path taken. This is the discipline pattern that should propagate (HIGH-but-fixable inline ≠ HIGH-blocker).

### Agent 4 — backend-safety-reviewer (32 / EXEMPLARY)
- **Specificity (5)**: All 7 dimensions enumerated; TOCTOU concurrent admin POST race + two-write atomicity gap named precisely.
- **Coverage (5)**: Touched concurrency, audit↔timeline split, force-bypass risk surface.
- **Severity (4)**: LOW on TOCTOU is correct (force is operator-driven, not adversarial); LOW on two-write split is correct (timeline is observational-only). Slightly under-tense on TOCTOU if we ever expose force=True non-operator-gated, but that path doesn't exist.
- **Actionability (4)**: Notes are accept-and-document tier rather than fix-required, which is correct for the calibrated severity.
- **Substitution (5)**: Canonical.
- **Evidence (4)**: 7 dimensions pass with structural reasoning; could have benefited from explicit file:line for the TOCTOU window but structurally complete.
- **Environment (5)**: No drift.

### Agent 5 — security-write-action-reviewer (34 / EXEMPLARY)
- **Specificity (5)**: Path-traversal vector named precisely; `_BATCH_ID_RE` allowlist + `INVALID_BATCH_ID` 400 + `_sanitise_free_text` 500/64 char caps are concrete remedies.
- **Coverage (5)**: Path-traversal, input sanitisation, error-code naming consistency all touched.
- **Severity (4)**: MEDIUM on path-traversal is calibrated (admin-only endpoint; real but not internet-exposed); LOW on naming inconsistency is correct.
- **Actionability (5)**: All findings translated to inline fixes with named symbols (regex constant, function name, error code).
- **Substitution (5)**: Canonical.
- **Evidence (5)**: Named the allowlist regex constant, the sanitiser function, and the new error code — verifiable artifacts.
- **Environment (5)**: No drift.
- **Calibration improvement vs PR #61**: This agent scored NEEDS-TUNING (16/35) on PR #61 for off-scope drift (security review of a validator PR with no security surface). On PR #72 with a genuine security surface (admin POST writing to disk + free-text fields in audit), the agent found two real fix-needed vulnerabilities and stayed in-scope. **The agent-tuning issue filed against PR #61 either worked, or the surface this time was genuinely in-scope and the agent calibrated naturally. Either way, the regression watch is now: ACCEPTABLE.** Continue monitoring for off-scope drift on no-security-surface PRs.

### Agent 6 — testing-verification (31 / EXEMPLARY)
- **Specificity (4)**: 33→45 tests with concrete count; 33/26 spec coverage cited; Lesson A pass per all 3 new files cited but file names not in summary excerpt.
- **Coverage (5)**: Spec coverage, Lesson A real-builder check, test pollution defense, boundary-test gap all addressed.
- **Severity (4)**: LOW on boundary tests missing is correct (deferred is appropriate when 33/26 spec already exceeded).
- **Actionability (4)**: Boundary-test deferral is named; could have linked to a GATE-4 followup ID explicitly.
- **Substitution (5)**: Canonical.
- **Evidence (4)**: Test counts (45 new + 1 adapted, 261 targeted pass, 7241/103 full-suite preserved) are concrete and verifiable.
- **Environment (5)**: No drift.

### Agent 7 — integration-boundary (32 / EXEMPLARY)
- **Specificity (5)**: Named the unknown-caller→"sweep" silent map; identified 2 non-documented response keys (audit_save_failed, audit_write_failed).
- **Coverage (5)**: Boundary contract, response shape, caller mapping all touched.
- **Severity (4)**: LOW on forward-compat fragility is calibrated; agent flagged that F1 fix already retired one of the 2 undocumented keys.
- **Actionability (4)**: Observation-tier; appropriate for LOW.
- **Substitution (5)**: Canonical.
- **Evidence (4)**: Specific symbol names cited (triggered_by="sweep" default).
- **Environment (5)**: No drift.

### Agent 8 — final-consistency-review (34 / EXEMPLARY)
- **Specificity (5)**: All 9 dimensions cited with evidence.
- **Coverage (5)**: End-to-end consistency check.
- **Severity (4)**: READY-NONE is the right verdict.
- **Actionability (5)**: No outstanding actions — verdict reflects state honestly.
- **Substitution (5)**: Canonical.
- **Evidence (5)**: **Used Lesson C disk-verification (Read tool) for ADR-019.** This is the pattern crystallising across the fleet — the agent didn't trust "I wrote it" claims and re-read the file off disk.
- **Environment (5)**: Lesson C compliance is itself environment honesty (verified the actual on-disk content, not the assumed content).

---

## 3. Weak-verdict warnings

None. All 8 agents scored EXEMPLARY (≥28/35).

---

## 4. Repeated failure hints

Comparing against the 4 prior scorecards on disk:

- `2026-05-13-w5-p0-adr018-p2-deployment-campaign.md`
- `2026-05-13-w5-pd-admin-runtime-flags-validator-RETROACTIVE.md`
- `2026-05-13-w5-validator-hardening-3pr-sequence.md`
- `2026-05-13-observation-audit-closure.md`

**Repeated agents in this campaign vs prior**:
- `system-architect` — prior runs all EXEMPLARY; this run EXEMPLARY. **Stable**.
- `adr-historian` — prior runs all EXEMPLARY; this run EXEMPLARY. **Stable**.
- `gap-hunter` — prior runs 35/35 EXEMPLARY (PR #52, #57, #61); this run 35/35 EXEMPLARY. **Perfect-score streak: 4 consecutive 35/35.**
- `backend-safety-reviewer` — prior EXEMPLARY; this run EXEMPLARY. **Stable**.
- `security-write-action-reviewer` — prior NEEDS-TUNING on PR #61 (16/35, off-scope drift); this run EXEMPLARY (34/35, genuine in-scope catches). **Recovery confirmed on next-with-real-security-surface campaign.** Continue watch for off-scope drift on no-surface PRs.
- `testing-verification` — prior EXEMPLARY; this run EXEMPLARY. **Stable**.
- `integration-boundary` — prior EXEMPLARY; this run EXEMPLARY. **Stable**.
- `final-consistency-review` — prior EXEMPLARY; this run EXEMPLARY. **Now demonstrating Lesson C disk-verification pattern in production.**

**No REPEATED-WEAK flags. No agent-tuning issue triggers.**

---

## 5. Cross-cutting observations

1. **gap-hunter HIGH-but-fixable-inline pattern**: F1 (silent double-dispatch) + F2 (dispatch_failed recovery) were HIGH severity but resolved inline rather than blocking PR. The agent's own recommendation matched the executed fix path. **This is the discipline pattern that should propagate: HIGH-but-fixable inline ≠ HIGH-blocker; the determinant is "can it be fixed in the same review pass without scope creep."**

2. **security-write-action-reviewer calibration improved**: PR #61 was NEEDS-TUNING (off-scope drift, no security surface present). PR #72 has a real security surface (admin POST writing batch_id to disk + free-text audit fields). Agent found two genuine fix-needed vulnerabilities. **Calibration improvement confirmed for this campaign; sustained recovery requires watching the next no-security-surface PR.**

3. **adr-historian architectural rigor**: The "Amends ADR-013" determination is structurally correct. Force-bypass is genuinely an amendment to the idempotency rule, not a side-note. **This is the catch that prevents future archaeology** ("why does ADR-013 say X but code does Y?").

4. **Lesson C pattern crystallising across the fleet**: final-consistency-review used Read tool to disk-verify ADR-019. This is the same Lesson C pattern this observer is using right now. **Fleet-wide pattern adoption signal.**

5. **GATE-4 followup discipline**: 5 followups filed (#67-#71). All NEEDS-TUNING/UNRELIABLE-analogous findings received explicit dispositions (FIXED INLINE / followup issue / accepted with reasoning). **GATE 4 honored throughout.**

6. **Verdict severity is healthy, not deflated**: 4 of 8 agents found MEDIUM-or-higher issues (gap-hunter HIGH×2 + MEDIUM×6, adr-historian MEDIUM, security MEDIUM×2). This is NOT a deflated-everything-LOW pattern. The system surfaces real risk; the system also resolves real risk inline. Both halves working.

---

## 6. Self-evaluation flag

This is the 5th substantive scorecard since the observation layer stood up. No prior self-eval exists. **RULE 5 self-evaluation IS triggered.** Self-eval written separately to `self-eval-2026-05-13.md`.

---

**Return shape**:

- SCORECARD WRITTEN: `.claude/memory/scorecards/2026-05-13-w5-p2-ignition-switch-model-c.md`
- Agents scored: 8
- EXEMPLARY: system-architect, adr-historian, gap-hunter, backend-safety-reviewer, security-write-action-reviewer, testing-verification, integration-boundary, final-consistency-review
- ACCEPTABLE: (none)
- NEEDS-TUNING: (none)
- UNRELIABLE: (none)
- Repeated-weak flags: none
- Self-evaluation: performed (5th run, no prior self-eval)
