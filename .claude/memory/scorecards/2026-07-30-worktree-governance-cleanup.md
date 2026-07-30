# Campaign Scorecard: Worktree Governance Cleanup — 2026-07-30

**Date:** 2026-07-30
**Campaign slug:** worktree-governance-cleanup
**Observer trigger:** RULE 4 manual invocation (`/observe`). NOT the ≥3-subagent trigger (zero subagents were dispatched).
**Primary evidence:** `C:\PZ-verify\reports\campaigns\2026-07-30-worktree-governance-cleanup.md`
**Supporting evidence:**
- `C:\PZ-verify\.claude\memory\TASK_STATE.md` (DISCHARGED 2026-07-30 entry for nice-chaum-b2853b follow-up)
- `C:\PZ-verify\reports\deploy\2026-07-30-92222849-cliq-breaker-deploy-closure.md` (§7 item 4 — the follow-up this campaign closed)
- `C:\PZ-verify\CLAUDE.md` — PATH GUARD / WORKTREE DISCIPLINE rules 1–6; GATE 3; GATE 4
- `C:\PZ-verify\.claude\memory\scorecards\self-eval-2026-07-28.md` (RULE 5 baseline)

---

## Agent count and dispatch rationale

**Subagents dispatched: 0**

This is explicitly appropriate for a repository-governance campaign with the following characteristics:
- No application code was read for mutation; no service files were touched
- No PR was opened, no code merged — GATE 1 triggers did not fire
- The work was: `git worktree list` inspection, precondition validation, and `git worktree remove` / `git branch -d` execution
- No specialized agent exists in the registry for worktree governance work (no "worktree-auditor" or equivalent); GATE 5 has no applicable canonical agent to name or substitute
- The WORKTREE DISCIPLINE rules (CLAUDE.md) assign lifecycle and ownership decisions to the orchestration layer; the preconditions (0 dirty, 0 untracked, 0 unique commits, no active owner, no open PR) are verifiable by the orchestrator with standard `git` commands

Dispatching code-review, security, or QA agents would have been scope-inflation with no coverage benefit. The orchestrator-only execution is the correct form for this campaign type.

The scorecard below scores the orchestrator's execution using the standard 7 dimensions applied to orchestrator work rather than subagent verdict quality.

---

## 1. Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| orchestrator (sole executor) | 4 | 5 | 4 | 4 | 5 | 4 | 5 | 31 | EXEMPLARY |

---

## Dimension rationale

### Specificity (4/5)

Concreteness is high throughout the campaign report: all 15 removed trees cite specific HEAD SHAs (e.g., `6d6d272a`, `557b9eb3`), merged PR numbers with merge-evidence descriptions, and explicit branch names. The stash risk investigation names specific stash entry `stash@{0}: WIP on fix/action-proposals-reaction-409` at commit `c2811131`. The PZ-sales-campaign admin-dir investigation names the resolution artifact: "its `gitdir` file resolves to `C:/PZ-main/.git`". The retained Section 4 trees all have explicit blocking reasons with counts (tracked-dirty, untracked, unique-commit numbers).

One specificity gap: the report asserts "every row satisfied all preconditions, revalidated immediately before its own removal" but does not provide per-removal command logs or timestamps that independently confirm the sequence (per-tree verification immediately before that tree's removal vs. batch upfront verification). The assertion is consistent with the evidence quality elsewhere but remains a temporal-sequence claim without direct corroboration. This prevents a 5/5 score.

Score: **4/5**

---

### Coverage (5/5)

All six operator-named concerns are addressed in the campaign report:

1. **Authority map before mutation:** Section 1 is sequenced before Section 2 (removals). The pre-mutation inventory documents `git worktree list` count (35), `.git/worktrees` admin dir count (34), `prune --dry-run` result "(empty)", locked worktrees (0), and stash stack (13). This is a complete registry consistency pass before any removal.

2. **Per-removal revalidation:** Each row in Section 2 is documented with HEAD SHA, merge evidence, and the claimed revalidation result (0 dirty, 0 untracked, 0 unique commits, not locked, no active owner, no open PR). The `git branch -d` safe-delete mechanism provides structural enforcement against unmerged branch deletion.

3. **No bulk delete / no force-remove:** Report states "Forced removal used: never — `--force` was not passed on any pass." Branches were deleted with merged-only `git branch -d`, never `-D`. Two `Permission denied` exits were accepted (not forced) and the logical completion was verified.

4. **PZ-sales-campaign admin dir:** Section 1 explicitly investigates the stale admin directory name and resolves it via the `gitdir` file content. This is cross-referenced against MEMORY.md's documented cosmetic issue ("PZ-main admin-dir stale name 'PZ-sales-campaign'"). The resolution is evidence-based, not silent.

5. **Shared-stash risk:** Section 1 documents the stash as repo-wide (not per-worktree), names the stash-adjacent entry, explains why deleting the branch cannot orphan stash refs (they are independent `refs/stash` refs), and verifies empirically: "stash count still 13, `stash@{0}` still resolves to `c2811131`." Empirical, not assumed.

6. **Dirty/unmerged/owned/open-PR trees not removed:** Arithmetic verifies cleanly (35 − 15 removed = 20 retained; 3 protected + 17 blocked = 20). All 9 dirty trees are in Section 4a with specific dirty file counts. All 8 unique-commit trees are in Section 4b. PR #1039 (open) is explicitly called "off-limits this campaign." The `git branch -d` safe-delete mechanism enforces this structurally for branches.

One additional coverage signal: Section 5 documents the ownership inconsistency finding (17 trees with no registry owner) rather than leaving it undiscovered, and Section 7 carries forward GATE 4 dispositions for all outstanding items.

Score: **5/5**

---

### Severity calibration (4/5)

The two `Permission denied` exits were correctly classified as OS-level file-lock events, not governance failures. The consequence assessment is accurate: "0 files, 0 subdirectories, deregistered from `git worktree list`, admin dir gone, `prune --dry-run` clean" — logical removal complete, physical cleanup deferred. The distinction between logical completion and physical directory removal is correctly drawn. Declining to force was the right calibration.

The PZ-sales-campaign characterization: the `gitdir` evidence (resolves to `C:/PZ-main/.git`) justifies not treating this as an inconsistency requiring a campaign STOP. The CLAUDE.md PATH GUARD stops short of requiring STOP on pre-documented cosmetic issues; the MEMORY.md entry pre-classifies this exactly. However, the operator's instruction to score this specifically noted the rule was "stop immediately on registry inconsistencies" — the orchestrator re-characterized the entry as "not an inconsistency" via evidence rather than stopping-and-escalating. This interpretation is defensible but slightly assertive: a stricter reading of the rule would have surfaced this as a named HOLD with evidence, then resumed. Minor calibration deduction.

The 17 retained trees are correctly not over-blocked. The report does not invent emergency or critical severity where SCHEDULED is the correct disposition.

Score: **4/5**

---

### Actionability (4/5)

Section 7 provides four named GATE 4 dispositions:
1. SCHEDULED — salvage pass for 9 dirty scratch trees (path: `C:\PZ-archive\evidence-<date>\<tree>\`, then re-evaluate)
2. SCHEDULED — GATE 3 disposition for 7 unique-commit trees (method: `git cherry origin/main <branch>`, archive-tag sole-anchor commits)
3. BLOCKED (correctly) — `rollback-provenance` pending PR #1039 merge/close
4. SCHEDULED — register owners/lifecycle for retained trees in `active-campaigns.json`

All are actionable by an operator. The trivial cleanup (two empty directories, plain `rmdir` after session exits) is correctly categorized as not needing a formal disposition.

One gap against strict GATE 4 compliance: SCHEDULED dispositions should name "a specific target session" per GATE 4 language. The report says "separate, operator-visible salvage slice" and "Left for a separate, operator-visible salvage slice" rather than targeting a specific session number or campaign. This is more "intent to schedule" than a fully-compliant SCHEDULED disposition. A 5/5 score would require named target sessions.

Score: **4/5**

---

### Substitution honesty (5/5 — N/A)

No agents were dispatched; no substitution occurred. GATE 5 is not applicable. The zero-subagent choice is itself appropriate and documented at the start of this scorecard. Score 5 = N/A, correctly handled.

Score: **5/5**

---

### Evidence quality (4/5)

Verifiable artifacts present:
- Worktree counts before/after (35 → 20) traceable against the per-section accounting
- `prune --dry-run` result "(empty)" stated before and after mutations
- Per-tree HEAD SHAs for all 15 removed trees (independently checkable via `git log` on the merged PRs)
- Stash count before (13) and after (13) the stash-adjacent branch deletion, with specific `stash@{0}` SHA (`c2811131`)
- TASK_STATE.md DISCHARGED entry names `fix/cliq-breaker-recovery` removal with explicit precondition checklist and outcome

Same structural gap as Specificity: the per-removal revalidation is asserted as happening "immediately before its own removal" but the evidence record is the final state (preconditions met) rather than a timed command log showing the before-and-after sequence for each individual tree. An external reviewer cannot independently confirm the temporal claim from the artifacts provided. Evidence quality for what *was* checked is high; the gap is in the sequencing proof.

Score: **4/5**

---

### Environment honesty (5/5)

The orchestrator operated from `C:\PZ-verify`, which is correctly the canonical PATH GUARD SOURCE OF TRUTH for all git/file-hash checks (CLAUDE.md: "Subagent reading rule (enforced): All verification reads and git operations must use `C:\PZ-verify`"). Section 3 explicitly documents `C:\PZ-verify`'s own state: branch `fix/wfirma-resolve-mapping-error-classification` @ `160582e4`, 2 tracked-dirty + 37 untracked files — confirming the orchestrator was aware of its own working-tree's state and flagged it as the reason `C:\PZ-verify` was itself retained (not the removal source). All worktree paths throughout the report use absolute paths and are correctly anchored to the PATH GUARD registry.

Score: **5/5**

---

## 2. Assessment of operator-named concerns (scored above; summary here)

| Concern | Finding | Score impact |
|---|---|---|
| Authority map preceded mutations | Section 1 (registry consistency) is sequenced before Section 2 (removals). Confirmed. | Coverage 5/5 |
| Per-removal revalidation immediately before each removal | Asserted per-row; not evidenced via timestamped command log. The `git branch -d` safe-delete provides structural enforcement for branches. | Specificity 4/5, Evidence 4/5 |
| No bulk delete / no force | `git branch -d` only (never `-D`); `--force` never passed to `git worktree remove`. Two Permission-denied exits accepted rather than forced. | Severity 4/5 (correctly calibrated) |
| PZ-sales-campaign admin dir — evidence or wave-through | Evidence-based resolution: `gitdir` file contents named; cross-referenced against documented MEMORY.md cosmetic issue. Not an orphan; not touched. | Evidence 4/5; minor Severity deduction (could have surfaced as named HOLD-then-resume rather than re-characterizing) |
| Shared-stash risk — empirical or assumed | Empirically tested: stash count and `stash@{0}` SHA verified before and after the stash-adjacent branch deletion. | Coverage 5/5 |
| Dirty/unmerged/open-PR trees not removed | Arithmetic checks (35−15=20 = 3+17). 9 dirty trees in §4a, 8 unique-commit trees in §4b, PR #1039 explicitly off-limits. `git branch -d` structurally enforces. | Coverage 5/5 |
| 17 retained trees — no GATE-3 disposition, no registry ownership | Documented (§4 and §5 item 1). GATE 4 SCHEDULED dispositions issued in §7. SCHEDULED dispositions lack target-session specificity. | Actionability 4/5 |

---

## 3. Weak-verdict warnings

**None.** The orchestrator scored 31/35 (EXEMPLARY). No dimensions triggered a NEEDS-TUNING or UNRELIABLE verdict. No re-dispatch recommended.

---

## 4. Repeated failure hints

**5 most recent campaign scorecards reviewed (excluding self-evals, most recent first):**

1. 2026-07-30: `2026-07-30-pr1041-pr1040-deploy-gate.md` — 7 deploy agents; 6 EXEMPLARY, 1 ACCEPTABLE
2. 2026-07-30: `2026-07-30-c7903686-wfirma-breaker-deploy-closure.md` — multi-phase campaign with deploy agents
3. 2026-07-28: `2026-07-28-advisory-service-id-draft-fallback.md` — 2 agents
4. 2026-07-17: `2026-07-17-proforma-privileged-auth.md` — 4 agents
5. 2026-07-11: `2026-07-11-pr-queue-clear-b123bd4c-deploy-gate.md` — 8 agents

**New REPEATED-WEAK flags from this campaign: none.** No subagents were dispatched; no per-agent NEEDS-TUNING or UNRELIABLE scores produced.

**Carried REPEATED-WEAK flags (unchanged; agents not present in this campaign):**

`REPEATED-WEAK: agent frontend-flow-reviewer has scored ACCEPTABLE (Evidence 3/5) in 8+ consecutive campaign appearances.`
- GATE 4 ISSUE disposition first generated in `2026-06-21-freight-authority-blocker-repair.md`. The 2026-07-30-pr1041-pr1040-deploy-gate scorecard records this as the 9th+ consecutive cycle without operator confirmation. This agent does not appear in the current campaign.
- **Status: GATE 4 ISSUE — operator must confirm filed, or explicitly REJECTED/SCHEDULED with date. This obligation does not expire on "recommendation noted."**

`REPEATED-WEAK: agent backend-safety-reviewer — Issue #694 open.`
- Per self-eval-2026-07-28: the 2026-07-17 appearance produced a positive data point (EXEMPLARY 30). Issue remains open until one further clean severity-calibration run. Agent not present in this campaign.

**No new REPEATED-WEAK patterns introduced by this campaign.** Inherited flags carry forward unchanged.

---

## 5. RULE 5 self-evaluation check

- Most recent self-eval file: `self-eval-2026-07-28.md` (dated 2026-07-28)
- Today: 2026-07-30
- Calendar days elapsed: **2 days** — does NOT meet the ≥7-day threshold
- SELF-DEGRADATION flag in `self-eval-2026-07-28.md`: **NO SELF-DEGRADATION DETECTED** (total 31/35, EXEMPLARY; all dimensions stable or improved)
- 3rd-campaign-since-degradation counter: not applicable — no SELF-DEGRADATION flag active

**Self-evaluation: SKIPPED.** Neither trigger condition is met. This is campaign scorecard run 3 since `self-eval-2026-07-28.md` was produced; the next calendar trigger fires on or after **2026-08-04**.

---

## 6. GATE 4 dispositions from this scorecard

No NEEDS-TUNING or UNRELIABLE verdicts were produced. No mandatory GATE 4 agent-quality salvage dispositions are required.

**Carried GATE 4 items (no change from prior scorecards):**

- frontend-flow-reviewer REPEATED-WEAK — ISSUE (agent-tuning tag; operator confirmation overdue 9+ cycles)
- backend-safety-reviewer REPEATED-WEAK — ISSUE #694 (open; awaiting clean data point for closure)

**Campaign-level GATE 4 items (inherited from campaign report §7 — not scorecard-generated):**

1. **SCHEDULED** — salvage pass for 9 dirty `claude/*` scratch trees (§4a of campaign report)
2. **SCHEDULED** — GATE 3 disposition for 7 unique-commit trees in §4b excluding `rollback-provenance`
3. **BLOCKED (correctly)** — `C:\PZ-wt\rollback-provenance` pending PR #1039 merge or close
4. **SCHEDULED** — register owners/lifecycle for all retained worktrees in `active-campaigns.json`

These four items require operator-visible follow-through; they are SCHEDULED in intent but need named target sessions to reach strict GATE 4 compliance.
