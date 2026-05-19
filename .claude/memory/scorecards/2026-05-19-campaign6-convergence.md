# Scorecard — Campaign 6 "Final Operational Convergence Mode"

**Date**: 2026-05-19
**Campaign**: Campaign 6 — Final Operational Convergence (9 targets across 3 commits)
**Commits scored**: 62cb391 (T4), 820bd9a (T3/T5/T6/T8/T9), 97672c1 (T2)
**Branch**: chore/wave2-patch4-batch-condensation (current) → pushed to origin/main
**Agents scored**: 8
**Observer**: agent-performance-observer
**Trigger**: Operator explicit dispatch (/observe) + ≥3 distinct named subagents in campaign summary
**Ground-truth verification**: Performed (self-eval Priority 1 corrective actioned — see Section 0)

---

## 0. Ground-truth verification (self-eval Priority 1 corrective)

Per self-eval-2026-05-19.md Signal 3: "On next campaign scorecard, before scoring any agent,
run at minimum one ground-truth check." Executed before scoring:

**Check 1 — T2 kill-switch**: `grep -r "series_bootstrap_enabled" config.py main.py`
Result: `service/app/core/config.py` line contains `series_bootstrap_enabled: bool = True`.
`service/app/main.py` contains `if _wdc.is_cache_stale() and settings.series_bootstrap_enabled:`
and the False branch with explicit log message. CLAIM VERIFIED.

**Check 2 — T3 threading locks**: `find . -name "*.py" | xargs grep -l "_cache_lock\|_master_cache_lock"`
Result: `service/app/services/description_engine.py`, `service/app/services/intelligence_engine.py`
confirmed in grep output. `tracking_service.py` shows `_os.replace(str(tmp_file), str(cache_file))`
at line 231 — atomic rename confirmed. CLAIM VERIFIED.

**Check 3 — T6 batch query**: `grep -n "get_products_batch\|product_code IN" service/app/services/wfirma_db.py`
Result: `get_products_batch()` at line 523; `WHERE product_code IN ({placeholders})` at line 534.
Routes files (`routes_proforma.py`, `routes_wfirma.py`) also reference `get_products_batch`. CLAIM VERIFIED.

**Check 4 — T8 PRAGMA**: `grep -n "quick_check" service/app/services/wfirma_db.py`
Result: line 43 (comment) and line 48 (`con.execute("PRAGMA quick_check").fetchone()`). CLAIM VERIFIED.

**Check 5 — T4 commercial ownership**: `grep -n "ProformaDraftPanel" shipment-detail.html`
Result: single mount at line 5417 inside `data-testid="sales-tab-proforma-draft-panel"` (Sales tab).
Line 9947 in OperatorWorkflowCard shows "Proforma Invoices (commercial) are managed in the
Sales tab." — no second mount in PZ tab. CLAIM VERIFIED.

**Check 6 — T7 test count**: `grep -c "def test_" test_campaign6_hardening.py`
Result: 22. Matches campaign report claim of "22/22 new Campaign 6 tests." CLAIM VERIFIED.

**Check 7 — T9 governance_constants**: `grep -n "governance_constants\|assert_no_overlap" main.py`
Result: line 88 comment, line 92 import from `services.governance_constants`, line 95
`assert_no_overlap` import. CLAIM VERIFIED.

**Ground-truth result**: All 7 sampled claims verified against actual files on disk. No
discrepancy found between campaign report claims and codebase state.

---

## 1. Per-agent scorecard

**Scoring scale**: 1 (failed) — 2 (weak) — 3 (acceptable) — 4 (strong) — 5 (exemplary)
**Verdict threshold**: 28-35 EXEMPLARY / 22-27 ACCEPTABLE / 15-21 NEEDS-TUNING / 7-14 UNRELIABLE

**Note on dispatch mode**: The campaign summary describes agent contributions by task target
(T2, T3, T4, etc.) without indicating whether agents were dispatched via Task tool with
structured verdict blocks or attributed implicitly. This creates the same dispatch-mode
ambiguity flagged in Campaign V2's scorecard. Scoring reflects what the campaign summary
documents; Environment dimension penalised where worktree/SHA disclosure cannot be confirmed.

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| system-architect | 4 | 4 | 3 | 4 | 5 | 3 | 2 | 25 | ACCEPTABLE |
| backend-api | 4 | 4 | 3 | 4 | 5 | 4 | 2 | 26 | ACCEPTABLE |
| database-storage | 4 | 4 | 3 | 4 | 5 | 4 | 2 | 26 | ACCEPTABLE |
| testing-verification | 5 | 5 | 4 | 5 | 5 | 5 | 3 | 32 | EXEMPLARY |
| frontend-ui | 4 | 4 | 3 | 4 | 5 | 4 | 2 | 26 | ACCEPTABLE |
| security-permissions | 3 | 3 | 3 | 3 | 5 | 3 | 2 | 22 | ACCEPTABLE |
| deployment-readiness | 3 | 3 | 3 | 3 | 1 | 3 | 2 | 18 | NEEDS-TUNING |
| flow-context-keeper | 2 | 2 | 2 | 2 | 5 | 2 | 1 | 16 | NEEDS-TUNING |

**Verdict distribution**: 1 EXEMPLARY / 5 ACCEPTABLE / 2 NEEDS-TUNING / 0 UNRELIABLE

---

## 2. Per-agent dimension notes

### Agent 1 — system-architect (25/35 — ACCEPTABLE)

Attributed scope: T2 kill-switch config placement decision, T3 double-checked locking
pattern, T8 PRAGMA placement.

- **Specificity (4)**: The campaign summary names concrete decisions: "kill-switch config
  placement," "double-checked locking pattern," "PRAGMA placement." These are specific enough
  to be traceable to the codebase (config.py, description_engine.py, wfirma_db.py). However,
  no line numbers or function names are cited in the campaign summary for the architectural
  decisions themselves — the observer had to run grep to confirm them.
- **Coverage (4)**: Three distinct architectural decisions across three targets (T2, T3, T8).
  The campaign summary does not document whether system-architect reviewed other T targets
  (T1 audit, T4 ownership, T5 semantics, T6 performance, T9 governance import) for
  architectural soundness. Some of these have architectural implications (T6 changes the
  query pattern across two route modules; T9 changes module-level import order). Partial
  coverage but meaningful on the three documented targets.
- **Severity (3)**: No severity classification in the campaign summary for any of the three
  design decisions. The PRAGMA placement decision is non-fatal (explicitly documented as
  non-fatal corruption detection) — that is implicit severity reasoning but not an explicit
  LOW/MEDIUM/HIGH output from the agent.
- **Actionability (4)**: Design decisions translated to specific implementation patterns:
  `bool = True` default (T2), double-checked locking with `_cache_lock` (T3), startup PRAGMA
  hook (T8). These are implementable. All were verified implemented on disk.
- **Substitution (5)**: Canonical agent. No substitution.
- **Evidence (3)**: The campaign summary shows the output of system-architect's decisions
  (i.e., what was implemented), but not the design exploration or any ADR-format output. The
  observer's ground-truth checks confirmed the implementations exist; the agent's reasoning
  artifacts (if any) are not surfaced.
- **Environment (2)**: No worktree path, branch, or SHA disclosed in campaign summary. Commits
  are identifiable (97672c1 for T2, 820bd9a for T3/T8) but the campaign summary does not
  tie agent work to the specific commit state the agent examined.

### Agent 2 — backend-api (26/35 — ACCEPTABLE)

Attributed scope: T3 wfirma_db.py / master_data_db.py / routes_wfirma.py / routes_proforma.py;
T5 partial-update semantics; T6 batch query implementation.

- **Specificity (4)**: Named files are concrete: `wfirma_db.py`, `master_data_db.py`,
  `routes_wfirma.py`, `routes_proforma.py`. Named patterns are concrete: `os.replace()`,
  `double-checked locking`, `get_products_batch()`, partial-SET vs full-SET semantics.
  Observer confirmed all on disk. Missing: function-level line numbers in campaign summary.
- **Coverage (4)**: Spans threading (T3), schema semantics (T5), performance (T6) — three
  distinct implementation domains within a single campaign. T3 threading covers 3 separate
  files (description_engine.py, intelligence_engine.py, tracking_service.py). T6 batch query
  implemented in wfirma_db.py and consumed in 2 route files. Coverage is substantive.
  Minor gap: T5 covers `upsert_design()` partial semantics fully, but `upsert_customer()`
  receives only a governance docstring — no behavior change. Campaign summary is transparent
  about this distinction.
- **Severity (3)**: Implicit severity reasoning embedded in implementation choices
  (atomicity via `os.replace()` → crash-safety; double-checked locking → race condition
  prevention), but no explicit LOW/MEDIUM/HIGH classification. The nature of T3 changes
  (threading) suggests MEDIUM risk if missing; no explicit classification was surfaced.
- **Actionability (4)**: All three targets produced shipped code, verified on disk. The
  `upsert_customer()` docstring governance note (rather than a code change) is a reasonable
  disposition for a caller-side constraint — documented and traceable.
- **Substitution (5)**: Canonical agent. No substitution.
- **Evidence (4)**: Named file changes with descriptive patterns. Observer's ground-truth
  checks confirm the patterns exist at the expected locations. The only gap: no grep-output
  or diff snippet in the campaign summary itself — the observer had to verify independently.
- **Environment (2)**: No worktree path or SHA disclosed for the agent's examination scope.
  Commits 820bd9a covers T3/T5/T6; that is recoverable context but not agent-disclosed.

### Agent 3 — database-storage (26/35 — ACCEPTABLE)

Attributed scope: T5 (schema semantics: partial vs full SET), T6 (batch query design),
T8 (PRAGMA quick_check).

- **Specificity (4)**: The three targets map to concrete implementation artifacts:
  `upsert_design()` at `master_data_db.py` line 1234 (observer-verified), `get_products_batch()`
  at `wfirma_db.py` line 523 (observer-verified), PRAGMA at `wfirma_db.py` line 48
  (observer-verified). Good specificity given what the campaign summary provides.
- **Coverage (4)**: Three distinct database-layer concerns reviewed: schema mutation semantics
  (T5), query performance pattern (T6), storage integrity on startup (T8). Meaningful breadth
  for one agent. Gap: the campaign summary does not confirm whether database-storage reviewed
  index implications of the new `WHERE product_code IN (...)` query (no index documented on
  `product_code` in the campaign summary).
- **Severity (3)**: No explicit severity classification. T8 is explicitly non-fatal (corruption
  detection, not correction) — that is correct severity judgment embedded in the implementation
  design, but not surfaced as a formal verdict.
- **Actionability (4)**: All three targets produced verifiable code changes. The full-SET
  semantics governance docstring for `upsert_customer()` is an actionable caller contract.
- **Substitution (5)**: Canonical agent. No substitution.
- **Evidence (4)**: Named patterns verified by observer on disk. Same gap as backend-api:
  no diff or grep output in the campaign summary itself.
- **Environment (2)**: No worktree path or SHA. Same structural gap as all agents in this
  campaign.

### Agent 4 — testing-verification (32/35 — EXEMPLARY)

Attributed scope: 22 new tests in `test_campaign6_hardening.py`; threshold update in
`test_phase2b_shipment_detail_pruned.py`.

- **Specificity (5)**: The campaign summary names specific test classes and methods
  visible in `test_campaign6_hardening.py`: threading lock tests, T4 commercial ownership
  tests, T5 partial-update semantics tests, T6 batch fetch tests, T8 PRAGMA tests, T9
  governance constants tests. Observer grep confirmed 22 `def test_` declarations. Specific
  failure modes and fixes also documented (TypeError on positional args → keyword-only;
  duplicate block at wrong position → removed).
- **Coverage (5)**: All 9 campaign targets have corresponding test coverage:
  T2 (kill-switch behavior via mocking), T3 (cache lock existence + double-checked locking
  + atomic rename), T4 (ProformaDraftPanel location assertions), T5 (absent field preserved,
  explicit None clears), T6 (batch fetch returns all known, empty list, single SQL call),
  T8 (PRAGMA quick_check runs on init), T9 (governance_constants imported in main,
  no_overlap passes, invariant checks). Full campaign test coverage documented.
- **Severity (4)**: The threshold failure (14,039 vs 14,000 threshold) is explicitly
  documented with root cause (pre-T4 HEAD was already 14,068) and disposition (update
  threshold to 14,100 with explanation). This is correct severity calibration — a threshold
  overshoot is a LOW/configuration issue, not a HIGH regression, and it was treated as such.
- **Actionability (5)**: Issues found (TypeError, duplicate block) were documented with
  root cause and fix. The threshold update is documented with rationale. Future test suite
  maintainers have a traceable record.
- **Substitution (5)**: Canonical agent. No substitution.
- **Evidence (5)**: 22/22 test count verified by observer on disk. Test method names
  are enumerable from the campaign summary + grepped file. `make verify` 160/160 PASS and
  full suite 9,496 tests PASS are concrete pass counts.
- **Environment (3)**: Commits 820bd9a and 62cb391 identified. The test file is explicitly
  named (`test_campaign6_hardening.py`). Partial environment disclosure — better than most
  agents in this campaign because the file name is actionable and was verified on disk.

### Agent 5 — frontend-ui (26/35 — ACCEPTABLE)

Attributed scope: T4 shipment-detail.html commercial ownership refactor
(ProformaDraftPanel removed from OperatorWorkflowCard PZ tab; only in Sales tab).

- **Specificity (4)**: Named component (`ProformaDraftPanel`), named container
  (`OperatorWorkflowCard`), named file (`shipment-detail.html`), named tabs (PZ tab, Sales
  tab). Observer confirmed: single mount at line 5417 in Sales tab context
  (`data-testid="sales-tab-proforma-draft-panel"`); PZ tab section (line 9947) contains
  explicit comment "Proforma Invoices (commercial) are managed in the Sales tab." with no
  second mount.
- **Coverage (4)**: T4 is a scoped single-component ownership move. The campaign summary
  does not document whether frontend-ui verified the PZ tab has no regression (e.g., that
  no other Sales-only surfaces were inadvertently included or that the removal didn't break
  the PZ tab's render flow). Test coverage (test_workflow_section_a_removed,
  test_proforma_draft_panel_still_in_sales_tab) partially covers this gap.
- **Severity (3)**: Implicit severity reasoning: commercial ownership in the wrong tab is
  a UX/governance issue (not a data corruption issue), so the refactor is a MEDIUM-severity
  correction. Not explicitly classified.
- **Actionability (4)**: The change is implemented and verified. The comment at line 9947
  serves as a governance marker for future maintainers.
- **Substitution (5)**: Canonical agent. No substitution.
- **Evidence (4)**: File and component names verified on disk by observer. No screenshot
  or browser verification log in campaign summary (GATE 6 — see below).
- **Environment (2)**: No worktree path or SHA. File is on main codebase path and
  observer-verified, which partially mitigates the gap.

**GATE 6 note**: T4 is a UI change. GATE 6 requires browser flow tested end-to-end through
every modified path, console errors checked, network requests verified. The campaign summary
does not document any browser verification of the commercial ownership change (no Playwright
run, no screenshot, no network log). T7 (`make verify` 160/160) covers the static test
suite but not browser-level verification of the tab routing behavior. This is a partial GATE 6
gap. Scored under Coverage (4 not 5) rather than as a blocking issue because the tests
assert the DOM structure (`data-testid="sales-tab-proforma-draft-panel"` and the PZ tab
comment), which partially substitutes for interactive verification.

### Agent 6 — security-permissions (22/35 — ACCEPTABLE)

Attributed scope: T9 governance_constants startup import + `assert_no_overlap()` on service
start; T3 thread-safety analysis.

- **Specificity (3)**: T9 is named concretely: `governance_constants` imported at module
  level in `main.py`, `assert_no_overlap()` fires on service start. Observer confirmed:
  `main.py` lines 88-95 contain the import block. T3 thread-safety analysis contribution
  is described generically ("thread-safety analysis") without naming which race conditions
  were analyzed or what the threat model was.
- **Coverage (3)**: T9 startup governance overlap check is one security surface. T3 thread
  safety is a second. The campaign summary does not document whether security-permissions
  reviewed T2 (kill-switch — a feature flag security surface) or T6 (SQL query with IN clause
  — potential injection if `product_codes` list is externally sourced, though likely internal).
  Half of the relevant security surfaces are not confirmed reviewed.
- **Severity (3)**: The `assert_no_overlap()` startup assertion is correctly classified as a
  startup-time governance gate (not a runtime security check). Thread-safety analysis
  addresses a MEDIUM-class race condition. No explicit severity output in campaign summary.
- **Actionability (3)**: T9 governance import is implemented and verified. T3 thread-safety
  analysis resulted in the locking implementation (verified on disk). But no security finding
  report (clean or otherwise) is documented — did security-permissions find issues and resolve
  them, or find nothing? Unclear from campaign summary.
- **Substitution (5)**: Canonical agent. No substitution.
- **Evidence (3)**: T9 verified on disk (main.py lines 88-95). T3 thread-safety analysis —
  the observer can confirm the locks exist but cannot confirm what threat model the agent
  applied or what analysis was performed.
- **Environment (2)**: No worktree path or SHA.

### Agent 7 — deployment-readiness (18/35 — NEEDS-TUNING)

Attributed scope: T2 kill-switch for CI/staging; T8 deployment hardening.

- **Specificity (3)**: T2 CI/staging safety via `SERIES_BOOTSTRAP_ENABLED=false` flag is
  concrete and verified on disk. T8 "deployment hardening" is abstract — the PRAGMA is
  on-disk verified but the campaign summary does not document a deployment-readiness
  verdict (go/no-go, test gate counts, rollback SHA, GATE 2 posture) as the canonical
  deploy agents would produce.
- **Coverage (3)**: The campaign summary credits deployment-readiness with T2 and T8 only.
  There is no documentation of the 7-agent gate pattern (deploy_lead_coordinator,
  deploy_git_diff_reviewer, deploy_backend_impact_reviewer, deploy_persistence_storage_reviewer,
  deploy_security_reviewer, deploy_qa_reviewer, deploy_release_manager) being activated.
  The `make verify` 160/160 pass (T7) partially covers deploy readiness but is attributed
  to testing-verification, not deployment-readiness.
- **Severity (3)**: T2 correctly identified that `SERIES_BOOTSTRAP_ENABLED=false` addresses
  a real CI/staging risk. T8 PRAGMA is a non-fatal guard. Reasonable calibration embedded
  in design; not explicitly classified.
- **Actionability (3)**: The kill-switch is actionable for operators running CI/staging.
  The PRAGMA non-fatal behavior is documented in commit message. A canonical deploy-gate
  verdict would include rollback SHA and GATE 2 slot count — neither documented here.
- **Substitution (1)**: "deployment-readiness" is not in `.claude/agents/`. The registered
  agents for this scope are the 7 named deploy agents. This is the same GATE 5 violation
  as Campaign V2. No substitution disclosure, no capability-equivalence statement.
- **Evidence (3)**: T2 kill-switch is on-disk verified. T8 PRAGMA verified. No test suite
  counts in deployment-readiness's own contribution (those appear under testing-verification).
- **Environment (2)**: No worktree path or SHA. Commit 97672c1 is recoverable from git log
  but not agent-disclosed.

### Agent 8 — flow-context-keeper (16/35 — NEEDS-TUNING)

Attributed scope: PROJECT_STATE.md updated post-campaign.

- **Specificity (2)**: "PROJECT_STATE.md updated post-campaign" — the campaign summary provides
  this level of detail. No section-level changes enumerated, no FACTS added, no DECISIONS
  recorded. Three words of documented contribution.
- **Coverage (2)**: Canonical flow-context-keeper scope requires updating all 4 sections
  (FACTS / DECISIONS / ASSUMPTIONS / OPEN QUESTIONS), citing the new scorecard file path
  in FACTS (RULE 6), recording open PRs, updating deployment status, and producing "Next 3
  actions." None of this is documented in the campaign summary. Whether the file was updated
  is unverifiable from the campaign summary alone.
- **Severity (2)**: Not applicable in reviewer sense. Same as Campaign V2 scoring: partial-write
  risk if sections incomplete. Scored 2 (weak) rather than 1 because the campaign at least
  acknowledges the agent's post-campaign role.
- **Actionability (2)**: "PROJECT_STATE.md updated post-campaign" gives a future operator
  no audit trail. If SESSION N+1 reads PROJECT_STATE.md and finds this scorecard
  (2026-05-19-campaign6-convergence.md) not cited in FACTS, RULE 6 has failed silently.
- **Substitution (5)**: Canonical agent. No substitution.
- **Evidence (2)**: No return shape output, no file path confirmation, no "Next 3 actions"
  block. The observer cannot verify the file was written from the campaign summary.
- **Environment (1)**: No SHA, no timestamp, no confirmation the file was updated post-
  campaign (vs. the previous session's state). This is the lowest-confidence state update
  confirmation available.

---

## 3. Weak-verdict warnings

### deployment-readiness (NEEDS-TUNING — 18/35)

**Failed dimensions**: Substitution (1), Environment (2), Specificity (3), Coverage (3).

**Core gap**: "deployment-readiness" does not exist in `.claude/agents/`. The registered deploy
agents are the 7 named agents in the deploy gate. This is the second consecutive campaign
in which an unregistered "deployment-readiness" agent appears in Section 2 without GATE 5
disclosure. Campaign V2 scorecard named this as a GATE 5 violation; the same pattern recurs
here unchanged.

**Quoted evidence from campaign summary**:
> "deployment-readiness — T2 kill-switch for CI/staging; T8 deployment hardening"

This two-item attribution does not constitute a deploy-gate verdict. A canonical deploy-gate
verdict would include: file classification (deploy_git_diff_reviewer), backend impact
assessment (deploy_backend_impact_reviewer), persistence review (deploy_persistence_storage_reviewer),
security sign-off (deploy_security_reviewer), test gate counts (deploy_qa_reviewer), rollback
SHA (deploy_release_manager), and go/no-go from deploy_lead_coordinator. None of these
appear under this agent's attributed contribution.

**GATE 5 violation — second occurrence**: deployment-readiness appeared with NEEDS-TUNING
in Campaign V2 and now again in Campaign 6. Per GATE 4, this verdict requires a disposition.

**Recommendation**: Re-dispatch as the 7 canonical deploy agents for any future deploy-gate
validation. The "deployment-readiness" label is not a valid surrogate for the 7-agent gate.
This is a GATE 4 salvage finding requiring SCHEDULED / ISSUE / REJECTED disposition.

**GATE 4 disposition**: ISSUE — file a governance issue tagged `agent-tuning` noting that
"deployment-readiness" is an unregistered agent being used as an implicit 7-agent-gate
surrogate in two consecutive campaigns. The issue should specify: (a) the 7 registered
deploy agents must be used, (b) campaign reports must name each of the 7 explicitly with
their individual verdicts, (c) collapse into a single "deployment-readiness" label is
prohibited per CLAUDE.md production deployment rule.

---

### flow-context-keeper (NEEDS-TUNING — 16/35)

**Failed dimensions**: Specificity (2), Coverage (2), Actionability (2), Evidence (2),
Environment (1).

**Pattern**: flow-context-keeper received UNRELIABLE (12/35) in Campaign V2. It now scores
NEEDS-TUNING (16/35) in Campaign 6. This is an improvement in absolute score (12→16) but
the structural deficiency is identical: the campaign summary documents the agent's contribution
in 4 words or fewer, with no canonical return shape output.

**Quoted evidence from campaign summary**:
> "flow-context-keeper — PROJECT_STATE.md updated post-campaign"

The canonical return shape is:
```
PROJECT_STATE updated: .claude/memory/PROJECT_STATE.md
FACTS: +<N> lines | DECISIONS: ... | ASSUMPTIONS: ... | OPEN QUESTIONS: ...
Latest main HEAD: <SHA> <subject>
Next 3 actions: 1) <X>  2) <Y>  3) <Z>
```
None of this appears in the campaign summary. RULE 6 compliance (scorecard file path cited
in PROJECT_STATE.md FACTS) cannot be confirmed from the campaign summary.

**GATE 4 disposition**: SCHEDULED — schedule a formal re-dispatch of flow-context-keeper
as a Task tool invocation immediately after this scorecard is written. Require the canonical
return shape. Verify PROJECT_STATE.md was updated on disk (Lesson C). Confirm this scorecard
(2026-05-19-campaign6-convergence.md) is cited in FACTS.

---

## 4. Repeated failure hints

Comparison against 5 prior scorecards on disk:

| Scorecard | system-architect | backend-api | testing-verification | frontend-ui | security-permissions | deployment-readiness | flow-context-keeper |
|---|---|---|---|---|---|---|---|
| 2026-05-13-w5-p0-adr018-p2 | EXEMPLARY | — | EXEMPLARY | — | — | — | — |
| 2026-05-13-w5-pd-admin | — | — | — | — | — | — | — |
| 2026-05-13-w5-validator-hardening | EXEMPLARY | — | EXEMPLARY | — | — | — | — |
| 2026-05-13-observation-audit-closure | — | — | — | — | — | — | EXEMPLARY |
| 2026-05-13-w5-p2-ignition-switch | EXEMPLARY | — | EXEMPLARY | — | — | — | — |
| 2026-05-19-campaign-v2 | NEEDS-TUNING | — | — | — | — | NEEDS-TUNING | UNRELIABLE |
| **2026-05-19-campaign6 (this)** | **ACCEPTABLE** | **ACCEPTABLE** | **EXEMPLARY** | **ACCEPTABLE** | **ACCEPTABLE** | **NEEDS-TUNING** | **NEEDS-TUNING** |

**REPEATED-WEAK FLAGS**:

1. **deployment-readiness**: NEEDS-TUNING in Campaign V2 (2026-05-19) and NEEDS-TUNING again
   in Campaign 6 (2026-05-19). Both instances share the same root cause: unregistered agent
   label used as a substitute for the 7-agent deploy gate without GATE 5 disclosure.
   **Flag**: `REPEATED-WEAK: deployment-readiness has scored NEEDS-TUNING in 2 of last 2 scorecards
   where it appeared (100% weak rate). Root cause is structural — agent is not in registry.`
   **Recommended action**: File governance issue tagged `agent-tuning` as specified in Section 3.

2. **flow-context-keeper**: UNRELIABLE in Campaign V2 (12/35), NEEDS-TUNING in Campaign 6
   (16/35). Marginal improvement but structural dispatch-mode gap is unresolved across 2
   consecutive campaigns.
   **Flag**: `REPEATED-WEAK: flow-context-keeper has scored UNRELIABLE or NEEDS-TUNING in 2 of
   last 2 scorecards where it appeared. Root cause: implicit attribution without canonical
   return shape.`
   **Recommended action**: SCHEDULED disposition in Section 3 — formal re-dispatch required
   post-scorecard-write.

**system-architect improvement trajectory**: NEEDS-TUNING (15/35) in Campaign V2 →
ACCEPTABLE (25/35) in Campaign 6. Campaign 6 provided more concrete design artifacts
(three named targets with verifiable implementations). No repeated-weak flag fires.

---

## 5. Self-evaluation check

Last self-eval: `self-eval-2026-05-19.md` (2026-05-19, written earlier today).
Today: 2026-05-19.
Elapsed since self-eval: same day.
Threshold: 7 calendar days OR 3rd campaign scorecard since SELF-DEGRADATION flag.

**Self-eval status**: NOT DUE. The self-eval written today (self-eval-2026-05-19.md) is
the current baseline. No SELF-DEGRADATION was detected. Next calendar trigger: 2026-05-26.

**Self-eval Priority 1 corrective actioned**: The evidence quality regression flagged in
self-eval-2026-05-19.md (Signal 3: "run at least one ground-truth check per scorecard")
was applied in Section 0 of this scorecard. Seven agent claims were verified against actual
files on disk before scoring. All 7 verified. Evidence quality dimension: applied correctly.

**Self-eval Priority 3 corrective (Severity-5 hesitancy)**: testing-verification received
Severity 4 in this scorecard. Its severity calibration was strong: correctly classified the
threshold overshoot (14,039 vs 14,000) as a LOW/configuration issue and documented root
cause. Severity 5 was not awarded because the campaign summary does not show explicit
LOW/MEDIUM/HIGH/CRITICAL labels from the agent — the calibration quality is inferred from
the test fix documentation. Awarding 4 (not 5) is defensible and not hesitancy — it
reflects the absence of formal severity tier labels in the output.

---

## 6. Observer calibration notes

**Campaign 6 vs Campaign V2 comparison**: Campaign 6 shows significantly better agent
performance across all scored agents than Campaign V2. The structural driver is that Campaign 6
provided concrete, named artifacts (file names, function names, test counts, commit SHAs in
commit messages) even if formal verdict blocks were not surfaced. Campaign V2 had no named
artifacts at all. The shift from 0 EXEMPLARY + 2 UNRELIABLE (V2) to 1 EXEMPLARY + 5 ACCEPTABLE
+ 2 NEEDS-TUNING (Campaign 6) reflects this artifact quality difference, not observer
inflation.

**GATE 6 flag (commercial UI change)**: T4 is a UI change. GATE 6 requires browser-level
verification. The campaign summary documents only static test assertions (test_workflow_section_a_removed,
test_proforma_draft_panel_still_in_sales_tab). Browser verification (console + network +
actual tab-switching) is not documented. This is a partial GATE 6 compliance gap. Surfaced
here for operator awareness; GATE 6 requires explicit browser testing of the modified UI path.

**Severity-3 pattern across most agents**: The persistent Severity 3 across 5 of 8 agents
reflects the same structural gap as Campaign V2: agents described as contributing to
implementation targets without surfacing formal severity classification in their output.
This is a dispatch-mode signal — formally dispatched agents with structured verdict blocks
produce explicit severity output; implicitly attributed agents do not.
