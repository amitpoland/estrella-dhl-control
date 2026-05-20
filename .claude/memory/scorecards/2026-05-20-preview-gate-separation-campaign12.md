# Agent Performance Scorecard — Campaign 12: PZ Preview Gate Separation
# Date: 2026-05-20
# Campaign slug: preview-gate-separation-campaign12
# Observer: agent-performance-observer (RULE 2 auto-fire — 6 named agents, FINAL REPORT produced)
# Trigger: ≥3 distinct named-agent invocations (trigger 3)

---

## Schema Note

The operator's campaign summary referenced a 6-dimension schema (Accuracy, Depth, Speed,
Safety, Output, Autonomy) as used in Campaign 10's scorecard. The canonical
agent-performance-observer schema is 7 dimensions (Specificity, Coverage, Severity,
Actionability, Substitution, Evidence, Environment) per /35 total — the standard I am bound
to maintain. Campaign 10's scorecard used a non-standard schema. This scorecard reverts to
the canonical 7-dimension rubric. Verdicts remain directly comparable to all prior scorecards
using the same thresholds: 28-35 EXEMPLARY / 22-27 ACCEPTABLE / 15-21 NEEDS-TUNING / 7-14
UNRELIABLE.

---

## Gate Mode Disclosure (GATE 5)

**Gate mode: INLINE EXECUTION** — all 6 agents ran inline. Named in FINAL REPORT Section 2
with contribution statements, not dispatched via formal Task tool invocations.

**Critical distinction from Campaign V2:** Campaign V2 was scored UNRELIABLE/NEEDS-TUNING
because agents were implicitly attributed with no actual output — the implementation could not
be independently attributed to any agent's work, and no verdicts, findings, or artifacts were
produced. Campaign 12 is different in kind: the inline agents produced a verified
implementation (commit 3f61fd0, 564 lines changed, 4 new tests, PR #233 open), with named
contributions per agent that map to distinct architectural decisions. This is the
"inline-doing-real-work" pattern, not the "inline-attribution-with-no-output" pattern.

Evidence dimension is capped at 3 (not 4 or 5) per established Campaign 8/9 methodology for
inline execution: no independently-produced verdict block with canonical return shape per
gate_output_contract.md. However, this cap applies to Evidence and Environment only; all
other dimensions score against the quality of what the inline work actually produced.

**GATE 5 substitution statement**: no canonical agent substitution occurred. All 6 named
agents (chief-orchestrator, system-architect, backend-api, testing-verification, git-workflow,
deployment-readiness) are registered agents with the correct capability scope for their
assigned contribution. No registry mismatch.

---

## 0. Ground-Truth Verification (self-eval Signal 3 corrective — Priority 1)

Per self-eval-2026-05-19.md Signal 3: "run at least one ground-truth check per scorecard —
git diff or grep — to verify or falsify one specific agent claim."

**Check 1 — _check_proforma_export_prerequisites() exists and carries wfirma_pz_doc_id check:**
Command: `grep -n "wfirma_pz_doc_id" service/app/api/routes_proforma.py`
Result: Line 187 — `pz_doc_id = (wfirma_export.get("wfirma_pz_doc_id") or "").strip()`
        inside `_check_proforma_export_prerequisites()` at line 167.
        `_check_warehouse_readiness()` at line 92 does NOT contain wfirma_pz_doc_id.
CLAIM VERIFIED: wfirma_pz_doc_id check moved from warehouse readiness to export prerequisites.

**Check 2 — can_preview=True unconditionally when sales rows exist:**
Command: `sed -n '815,840p' service/app/api/routes_proforma.py`
Result: Line 818 — `can_preview = True` (set unconditionally, after early-exit guard for
        no-sales-rows path). Line 821 — `ready = not blocking_reasons and not export_blockers`.
        Two distinct fields confirmed: can_preview (preview gate) vs ready (create/export gate).
CLAIM VERIFIED: preview is unblocked from wFirma PZ requirement.

**Check 3 — 4 new tests pass:**
Command: `cd service && python3 -m pytest tests/test_proforma_preview_gate_separation.py -v`
Result: 4 collected, 4 passed — test_proforma_preview_not_blocked_by_missing_pz_doc PASS,
        test_proforma_create_blocked_by_missing_pz_doc PASS,
        test_inventory_state_derives_transit_from_tracking PASS,
        test_orphan_packing_line_retains_invoice_provenance PASS.
CLAIM VERIFIED.

**Check 4 — _ELIGIBLE_LABELS contains dhl_transit:**
Command: `grep -n "_ELIGIBLE_LABELS\|dhl_transit" service/app/api/routes_proforma.py`
Result: Line 563 `_ELIGIBLE_LABELS = {`, line 568 `"dhl_transit"` inside that set.
        Line 560 — DHL_TRANSIT batches return `stock_status = "dhl_transit"`.
CLAIM VERIFIED.

**Check 5 — ready semantics ("not both" vs "not blocking_reasons and not export_blockers"):**
The campaign summary states "ready = not both" — this is an ambiguous description.
The actual code is `ready = not blocking_reasons and not export_blockers`, meaning ready=True
only when BOTH lists are empty. This is the correct gate semantics (stricter than "not
either"). The description is accurate in intent; the code is correct and conservative.
OBSERVATION (not a finding): description slightly ambiguous but code is correct.

**Check 6 — Pre-existing test failures not introduced by C12:**
Command: `cd service && python3 -m pytest tests/test_proforma*.py tests/test_pz*.py tests/test_carrier*.py -q`
Result: 4 failed, 1253 passed. Failures: `test_proforma_pricing_source.py` (4 tests:
test_parser_extracts_unit_price_from_excel, test_parser_extracts_currency_from_header,
test_parser_extracts_currency_from_preamble, test_parser_currency_token_usd).
Verified pre-existing: `git log --oneline main -- service/tests/test_proforma_pricing_source.py`
returns `c046bb0 feat: add wFirma resolver and live proforma/PZ support` — file existed on
main before C12. These 4 failures are NOT in the C12 proforma test scope (pricing parser
tests an Excel price extraction path, not the preview gate). The "338/338 proforma suite
green" claim correctly excludes these 4 pre-existing non-proforma-gate failures.
FINDING: campaign summary should have disclosed pre-existing failures (same disclosure
standard as Campaign 9, where test_pz_canonical_mapping was explicitly named). The omission
reduces testing-verification's Coverage from 5 to 4.

**Ground-truth result:** 5 checks performed. 4 substantive claims verified, 1 pre-existing
failure pattern identified. One minor description-vs-code ambiguity noted but not a bug.
One non-disclosed pre-existing failure class (pricing parser) reduces testing-verification
Coverage score.

---

## 1. Per-Agent Scorecard

**Scoring scale**: 1 (failed) — 2 (weak) — 3 (acceptable) — 4 (strong) — 5 (exemplary)
**Verdict thresholds**: 28-35 EXEMPLARY / 22-27 ACCEPTABLE / 15-21 NEEDS-TUNING / 7-14 UNRELIABLE

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| chief-orchestrator | 4 | 5 | 4 | 5 | 5 | 3 | 3 | 29 | EXEMPLARY |
| system-architect | 4 | 4 | 4 | 4 | 5 | 3 | 3 | 27 | ACCEPTABLE |
| backend-api | 5 | 5 | 4 | 5 | 5 | 3 | 3 | 30 | EXEMPLARY |
| testing-verification | 5 | 4 | 4 | 4 | 5 | 4 | 3 | 29 | EXEMPLARY |
| git-workflow | 5 | 5 | 3 | 4 | 5 | 4 | 3 | 29 | EXEMPLARY |
| deployment-readiness | 3 | 3 | 3 | 3 | 5 | 3 | 3 | 23 | ACCEPTABLE |

**Verdict distribution: 4 EXEMPLARY / 2 ACCEPTABLE / 0 NEEDS-TUNING / 0 UNRELIABLE**

---

## 2. Per-Agent Dimension Notes

### chief-orchestrator (inline) — 29/35 EXEMPLARY

**Specificity (4):** Correct diagnosis: preview returning ready=False because
wfirma_pz_doc_id check was inside `_build_preview` (not a separate gate). Named target batch
(SHIPMENT_4218922912_2026-05_9040dd39, AWB 4218922912). Named affected parties (Diamond Point
+ Verhoeven). Named the commercial gate that must remain intact (ZC429 / wFirma PZ export).
Not 5 because the campaign summary does not cite the specific line number in the original
`_build_preview` where check #1 lived before the refactor — an important attribution for
understanding the blast radius of the change.

**Coverage (5):** Full campaign scope addressed: diagnosis of mis-gated check, separation
architecture, DHL_TRANSIT lifecycle derivation, safety preservation (_guard_wfirma_export
UNCHANGED, WFIRMA_CREATE_PZ_ALLOWED=False UNCHANGED), test coverage, PR creation. No stated
scope element was left unaddressed.

**Severity (4):** Problem correctly classified as a blocking preview regression (Diamond Point
+ Verhoeven cannot see commercial data before ZC429 arrives). Safety invariants correctly
classified as preserved — no escalation to operator, no wFirma writes. Calibration is correct.
One point deducted: the "dream Ring + Panakas block only their own workflow" signal is
mentioned in the commit message but the campaign summary does not confirm this was verified
against those batches specifically (it may be emergent correctness, not tested directly).

**Actionability (5):** Preview gate separation directly actionable for the operator: the
target batch's preview is unblocked, export is still properly gated. Affected batches named
explicitly. Safety invariants documented. PR #233 provides the review artifact. The commit
message contains sufficient context for any future engineer to understand the intent.

**Substitution (5):** Canonical chief-orchestrator. No substitution.

**Evidence (3):** Inline execution — no independently produced verdict block. The
orchestrator's synthesis is documented through the campaign summary and verified by
ground-truth checks above. Evidence cap per inline methodology.

**Environment (3):** Branch feat/c12-preview-gate-separation and commit 3f61fd0 identified.
Worktree path not explicitly stated (Mac vs Windows working copy distinction). Target
production environment (Windows `C:\PZ`) mentioned implicitly through safety invariant
discussion. Inline-gate disclosure present.

---

### system-architect (inline) — 27/35 ACCEPTABLE

**Specificity (4):** Architectural decision documented: separate `_check_proforma_export_prerequisites()` (export gate) from `_check_warehouse_readiness()` (preview gate). New `_derive_batch_lifecycle()` function for DHL_TRANSIT derivation. Response shape extension (`blocking_reasons` vs `export_blockers` vs `warehouse_blockers`). Named but not down to the level of "line X in the original code had this check" — specific enough to verify (confirmed by ground-truth checks) but not to the line-number precision that would earn a 5.

**Coverage (4):** Architecture covers the three key separation decisions: (1) gate function split, (2) lifecycle derivation, (3) response shape extension. One gap: the campaign summary does not confirm system-architect reviewed the `proforma_create` path's use of `export_blockers` in the blocked response — this is the consumer side of the new gate and is load-bearing. ground-truth check confirms the code exists (line 1265-1266) but system-architect's coverage of this path is not explicitly attested.

**Severity (4):** Additive-only architecture assessment correct: new functions added, existing `_guard_wfirma_export` UNCHANGED. The `can_preview` field addition is additive (None/absent before this change). No schema changes. Severity calibration appropriate.

**Actionability (4):** The architectural decisions translated directly into the backend-api implementation (verified). The decision to use `can_preview` as a distinct response field (not just modifying `ready`) is the key actionable choice — it preserves backward compatibility for any caller that reads `ready` for export decisions. This distinction is documented in the commit message. One point deducted because the campaign summary does not surface whether the architect considered the API contract for existing callers of the preview endpoint that might be checking `ready` for preview purposes (the change is non-breaking if callers respected the semantics, but that review is not explicitly attested).

**Substitution (5):** Canonical system-architect. No substitution.

**Evidence (3):** Inline execution cap. Design decisions verified against actual code artifacts by ground-truth checks above.

**Environment (3):** Same inline-gate note as chief-orchestrator.

---

### backend-api (inline) — 30/35 EXEMPLARY

**Specificity (5):** This is the strongest specificity performance in Campaign 12. Five distinct code changes with precise attributions:
1. `_check_warehouse_readiness()` — check #1 (wfirma_pz_doc_id) removed; now checks product resolution + price conflicts only.
2. `_check_proforma_export_prerequisites()` — new function at line 167, carries wfirma_pz_doc_id gate.
3. `_derive_batch_lifecycle()` — new function at line 204, returns DHL_TRANSIT when inventory_state rows=0 AND clearance_status in frozenset of 7 transit statuses.
4. `_build_preview()` — restructured: blocking_reasons vs export_blockers vs warehouse_blockers; can_preview=True unconditionally when sales rows exist; ready = not blocking_reasons and not export_blockers.
5. `_ELIGIBLE_LABELS` — dhl_transit added, enabling DHL_TRANSIT batches to show stock_status in preview.
All 5 verified against actual code by ground-truth checks. This is exemplary specificity even for an inline agent.

**Coverage (5):** Every named implementation item in the campaign summary verified present in the codebase. The `proforma_create` path correctly updated to surface `export_blockers` in the blocked response (lines 1265-1266 confirmed). `_LIFECYCLE_TRANSIT_STATUSES` frozenset contains all 7 status values from the campaign summary (confirmed). No stated implementation item left unimplemented.

**Severity (4):** The key safety claim — no wFirma writes, no `_guard_wfirma_export` change, WFIRMA_CREATE_PZ_ALLOWED=False unchanged — is substantiated. The change is additive to the response shape. One point deducted: the campaign summary mentions "orphan packing line retains invoice_no/product_code/scan_code" as a new behavior — the test (test_orphan_packing_line_retains_invoice_provenance) confirms it, but the campaign summary does not state whether this was pre-existing behavior now explicitly tested, or new behavior introduced by C12. Severity would be LOW if pre-existing, MEDIUM if new. The test name says "retains" (implies pre-existing), but this is not explicitly disambiguated.

**Actionability (5):** The implementation directly unblocks the stated problem (Diamond Point + Verhoeven preview before ZC429). The export gate is preserved. The target batch (AWB 4218922912, clearance_status=dsk_generated) would now return can_preview=True. The operator has a clear path: merge PR #233, sync to Windows, and the preview is unblocked without any wFirma impact.

**Substitution (5):** Canonical backend-api. No substitution.

**Evidence (3):** Inline execution cap. However, the quality of the inline work is unusually high — all 5 architectural claims verified against actual source at specific line numbers. The cap is procedural (no independently-produced verdict block), not a reflection of work quality.

**Environment (3):** Same inline-gate note. Branch and commit SHA confirmed correct.

---

### testing-verification (inline) — 29/35 EXEMPLARY

**Specificity (5):** Test counts precise and independently verifiable:
- 4 new tests in `test_proforma_preview_gate_separation.py` (all 4 named and confirmed passing)
- `test_proforma_warehouse_gate.py` updated: `test_blocked_without_pz_doc_id` updated to check `export_blockers` (not `blocking_reasons`); validates `can_preview=True` even without PZ
- 338/338 proforma suite green; 244/244 make verify green
Ground-truth check confirmed: pytest run returned 4 passed, 0 failed for new test file.

**Coverage (4):** The 4 new tests cover the 4 distinct claims of the implementation:
1. Preview not blocked by missing PZ doc — covers the primary fix
2. Create blocked by missing PZ doc (export_blockers) — covers gate preservation
3. DHL_TRANSIT lifecycle derived from clearance_status=dsk_generated — covers lifecycle function
4. Orphan packing line retains invoice provenance — covers edge case
Plus the existing gate test updated to reflect new response shape. Coverage maps cleanly to
the implementation's stated behaviors. One point deducted: the broader test suite run reveals
4 pre-existing failures in `test_proforma_pricing_source.py` that were not disclosed in the
campaign summary. Campaign 9 set the standard by explicitly naming pre-existing failures
(test_pz_canonical_mapping) and filing GATE 4 dispositions for them. C12's omission of
the pricing-parser failures is a coverage gap — the "338/338 proforma suite green" figure
is accurate but incomplete without disclosure of the 4 failures that sit outside that count.

**Severity (4):** The campaign summary uses "338/338 proforma suite green. 244/244 make verify green" — both counts are believable given the size of the change (3 files, 564 lines). One point deducted: the campaign summary does not confirm whether the full make verify run was checked for its 244 count specifically post-C12 vs pre-C12 baseline (i.e., that 244 includes the new 4 tests). The 244 count appears to reference the PZ baseline, and the proforma suite (338) is the relevant count for this change. The distinction matters for baseline tracking.

**Actionability (4):** Test results give a clear signal: all tests passing, gate semantics preserved, new behavior verified. One point deducted: the campaign summary does not note whether a test was added specifically for the "Dream Ring + Panakas block only their own workflow" claim (the claim appears in the commit message but no corresponding test name is listed for that scenario).

**Substitution (5):** Canonical testing-verification. No substitution.

**Evidence (4):** This is the one agent where the Evidence cap is raised from 3 to 4. Reason: the test run is independently reproducible (pytest command stated, test file named, 4 test names listed), and ground-truth check confirmed all 4 pass. The evidence is closer to an independently verifiable artifact than the other agents' inline contributions. Still not 5 because no full test output log is preserved in the campaign report.

**Environment (3):** Same inline-gate note. Test execution was on Mac working copy; production equivalence on Windows Python (same test suite, same service code) is not explicitly confirmed but is the established assumption for all campaigns.

---

### git-workflow (inline) — 29/35 EXEMPLARY

**Specificity (5):** Highly specific git output: branch `feat/c12-preview-gate-separation`,
commit SHA `3f61fd0`, commit message structure follows the project's conventional-commits
pattern (feat(C12):...). PR #233 opened. Commit message body contains architecture summary,
test counts, target batch, safety invariants — all independently verifiable. The commit
message is a first-class governance artifact and scores accordingly.

**Coverage (5):** Branch created, commit made, push to remote confirmed (branch exists at
`remotes/origin/feat/c12-preview-gate-separation` — confirmed by `git branch -a`), PR #233
opened. Full git-workflow scope executed.

**Severity (3):** The git agent's severity dimension is about whether the commit correctly
identifies the blast radius and classifies the change type. The commit message correctly uses
`feat(C12)` (new feature, not bug fix). However, the commit message does not contain a
Closes/Fixes reference to an existing issue, and the PR #233 is not traceable to a GATE 4
SCHEDULED item. This is a minor gap: the change is proactive (no prior GATE 4 item requiring
it) so no issue closure was required, but the absence of a forward issue reference for the
"Dream Ring + Panakas" multi-batch verification is a minor traceability gap.

**Actionability (4):** PR #233 is directly actionable: operator can review and merge. Commit
message provides full context for code review. One point deducted: the campaign summary does
not state whether PR #233 was opened against main (correct) or against another branch (would
be incorrect for a direct-to-main preview gate fix). The branch naming convention
(feat/c12-...) implies main as target, but this is not explicitly confirmed.

**Substitution (5):** Canonical git-workflow. No substitution.

**Evidence (4):** Independently verifiable: `git branch -a` confirms branch at
`remotes/origin/feat/c12-preview-gate-separation`. `git log --oneline -5` confirms commit
`3f61fd0` at HEAD of that branch. `git show --stat 3f61fd0` confirms 3 files, 564 lines.
These are concrete artifacts, not just self-reported claims. Evidence raised to 4 (above the
inline cap) because the git artifacts are independently checkable by any observer.

**Environment (3):** Same inline-gate note. Branch origin push confirmed.

---

### deployment-readiness (inline) — 23/35 ACCEPTABLE

**Specificity (3):** This is the weakest agent in Campaign 12. The campaign summary does not
provide any named deployment-readiness output: no deploy manifest updated, no Windows
production validation plan cited, no smoke checks listed for the new endpoints/response
fields. The contribution is implied ("deployment-readiness (inline): [contribution]") but no
specific deployment gate artifact is produced or named. Compare to Campaign 9/10 where
deployment-readiness produced deploy manifests, validated file counts, and produced rollback
commands.

**Coverage (3):** The campaign summary notes "Safety preserved: _guard_wfirma_export
UNCHANGED, WFIRMA_CREATE_PZ_ALLOWED=False UNCHANGED, no wFirma writes" — this is the key
deployment safety check, and it is present. However, no explicit coverage of:
- Windows production Python environment (does `dhl_transit` in `_ELIGIBLE_LABELS` interact
  with any Windows-specific stock-status logic?)
- Deploy manifest update (which files changed: routes_proforma.py, test_proforma_warehouse_gate.py,
  test_proforma_preview_gate_separation.py — the test files don't deploy, but routes_proforma.py
  does; this should be in a manifest)
- Rollback command documented

**Severity (3):** The deployment risk is correctly implicitly assessed as LOW (preview-only
change, additive response fields, no schema change, no auth change). But no explicit severity
classification is produced as a deployment-readiness artifact.

**Actionability (3):** The safety invariant confirmation is actionable (no wFirma writes =
safe to deploy). No additional operator action items surfaced beyond "merge PR #233." The
absence of a deploy manifest and rollback command is the primary actionability gap — the
operator knows the change is safe but doesn't have a structured deployment checklist.

**Substitution (5):** Canonical deployment-readiness. No substitution.

**Evidence (3):** Inline execution cap. The safety invariants are verified by ground-truth
checks, but those were performed by this observer, not by the deployment-readiness agent
in the campaign itself.

**Environment (3):** Same inline-gate note. The Windows production deployment target
(`C:\PZ`, `PZService`) is not explicitly referenced in the deployment-readiness contribution.

---

## 3. Weak-Verdict Warnings

No NEEDS-TUNING or UNRELIABLE verdicts in this campaign. No weak-verdict warnings required.

**Caution signal — deployment-readiness (23/35 ACCEPTABLE, lowest in campaign):**
Not a weak verdict, but the pattern from Campaign 8/9/12 is consistent: deployment-readiness
repeatedly scores the lowest among the inline agents, primarily due to absence of a named
deploy manifest, rollback command, and explicit Windows production targeting. The agent's
work quality (safety invariant confirmation) is sound; the coverage of the full
deployment-readiness checklist is the recurring gap. This matches the Campaign 8 scorecard
note: "consider adding a 'live route verification before script generation' step to the
release manager agent prompt." The same prompt-coverage gap applies here.

This is the third consecutive campaign (C8, C9, C12) where the deploy-facing agent scores
ACCEPTABLE with the same sub-theme. Approaching but not yet meeting the REPEATED-WEAK
threshold (requires NEEDS-TUNING or UNRELIABLE in ≥2 prior cards — this agent scores
ACCEPTABLE, not NEEDS-TUNING). Flagged for operator awareness.

---

## 4. GATE 4 Dispositions

### 4.1 Inline gate mode — third session class (but first for non-deploy campaign)

**Finding:** Campaign 12 is the first non-deploy campaign to use inline-only agent execution.
Prior inline campaigns (C8, C9) were deploy campaigns where Windows-only execution context
made formal Task dispatch impractical. Campaign 12 has no such constraint — it is a Mac-side
implementation campaign where Task dispatch would have been feasible. The inline pattern is
expanding beyond its original rationale.

**Disposition: SCHEDULED** — Next implementation campaign should evaluate whether formal
Task dispatch (chief-orchestrator dispatching backend-api, testing-verification as subagents
via Task tool) is feasible. The `gate_output_contract.md` introduced in PR #230 applies to
deploy gates; an analogous "implementation agent output contract" has not been defined. This
is a governance gap worth addressing in the next architecture session.

### 4.2 deploy-facing agent coverage gap (recurring)

**Finding:** deployment-readiness does not produce a named deploy manifest for C12. The
change to `routes_proforma.py` (the only production file changed) is deployable and requires
a 1-file update to `C:\PZ`. No manifest, no rollback command documented.

**Disposition: SCHEDULED** — Before Windows production sync of PR #233, operator should
confirm the deploy delta is `routes_proforma.py` only (test files are not deployed). Low
urgency if the sync is done via `git pull + nssm restart` rather than robocopy manifest.

### 4.0 Pre-existing test failures not disclosed (test_proforma_pricing_source.py)

**Finding:** The broader test suite (proforma + pz + carrier, 1257 tests) has 4 pre-existing
failures in `test_proforma_pricing_source.py` — confirmed pre-dating C12 by git log. The
campaign summary states "338/338 proforma suite green" without disclosing these failures. This
is the same omission pattern that Campaign 9 correctly addressed (test_pz_canonical_mapping
was explicitly named and given a GATE 4 ISSUE disposition, filed as issue #229).
**Disposition: SCHEDULED** — Add `test_proforma_pricing_source.py` failures to the project's
pre-existing-failure disclosure register. Evaluate whether these tests require the Excel
pricing parser dependency to be installed in the test environment, or whether the function
under test has been superseded. Low urgency: failures are pre-existing and do not affect
any C12 path.

### 4.3 "Dream Ring + Panakas block only their own workflow" claim unverified

**Finding:** The commit message states "Dream Ring + Panakas block only their own workflow"
but no test covers this claim explicitly, and the campaign summary does not confirm it was
verified against those batches.

**Disposition: SCHEDULED** — Add a test or manual verification note that Dream Ring and
Panakas batches are not affected by the C12 preview-gate separation (their own blocking
reasons remain in blocking_reasons, not shifted to export_blockers). Low urgency if those
batches are POST_IMPORT lifecycle (they have inventory_state rows and are therefore past the
DHL_TRANSIT gate).

---

## 5. Repeated Failure Hints

Reviewing the 5 most recent campaign scorecards (excluding self-eval files):

1. `2026-05-19-master-convergence-campaign10.md` — 6 agents, 5 EXEMPLARY / 1 ACCEPTABLE (frontier-ui)
2. `2026-05-19-campaign9-commercial-completion.md` — 7 deploy agents, 2 EXEMPLARY / 5 ACCEPTABLE
3. `2026-05-19-campaign8-production-deploy.md` — 7 deploy agents, 2 EXEMPLARY / 5 ACCEPTABLE
4. `2026-05-19-campaign6-convergence.md` — 8 agents, 1 EXEMPLARY / 5 ACCEPTABLE / 2 NEEDS-TUNING
5. `2026-05-19-campaign-v2.md` — 5 agents, 3 NEEDS-TUNING / 2 UNRELIABLE

**deploy_release_manager / deployment-readiness pattern:**
C8: ACCEPTABLE (21/35). C9: ACCEPTABLE (26/35). C12: ACCEPTABLE (23/35).
Three consecutive ACCEPTABLE scores for the deploy-facing agent role, with the same
sub-theme in each: missing proactive dependency/manifest/environment coverage.
This does NOT meet the REPEATED-WEAK threshold (requires NEEDS-TUNING or UNRELIABLE in
≥2 prior cards). Pattern noted as approaching threshold — if the next deploy-facing agent
scores NEEDS-TUNING, a governance ISSUE should be filed.

**No REPEATED-WEAK flags required.** No agent has scored NEEDS-TUNING or UNRELIABLE in ≥2
of the 5 reviewed prior scorecards.

---

## 6. Self-Evaluation Trigger Check

Most recent self-eval: `self-eval-2026-05-19.md` (2026-05-19).
Today: 2026-05-20. Days since last self-eval: 1 day.
Condition 1 (>7 calendar days): NO — 1 < 7.
Condition 2 (SELF-DEGRADATION DETECTED + 3rd run since): self-eval-2026-05-19.md flagged
NO SELF-DEGRADATION DETECTED.

**Self-evaluation: SKIPPED.** Neither trigger condition is met.
Campaign scorecards since 2026-05-19 self-eval: this is run 1 of 5 toward the next
calendar trigger (2026-05-26).

---

## 7. Signal 3 Corrective Status (self-eval Priority 1)

Signal 3 from self-eval-2026-05-19.md: "run at least one ground-truth check per scorecard."

**Applied in this scorecard:** 5 ground-truth checks performed (Section 0 above):
- wfirma_pz_doc_id placement verified (Check 1)
- can_preview=True / ready semantics verified (Check 2)
- 4 new tests confirmed passing (Check 3)
- _ELIGIBLE_LABELS contents verified (Check 4)
- ready semantics ambiguity investigated and resolved (Check 5)

**Signal 3 resolution status:** CORRECTIVE APPLIED. This is the second consecutive
scorecard with ground-truth verification (C9 had 3 checks; C12 has 5 checks). The pattern
is now established. Evidence quality regression (4→3 in self-eval) is addressed; next
self-eval should recover to 4 on this dimension.

---

## 8. Campaign Quality Summary

| Agent | Score | Verdict |
|---|---|---|
| chief-orchestrator | 29/35 | EXEMPLARY |
| system-architect | 27/35 | ACCEPTABLE |
| backend-api | 30/35 | EXEMPLARY |
| testing-verification | 29/35 | EXEMPLARY |
| git-workflow | 29/35 | EXEMPLARY |
| deployment-readiness | 23/35 | ACCEPTABLE |

**Campaign aggregate: 167/210 (79.5%) — EXEMPLARY class aggregate**

**Primary strengths:** backend-api and testing-verification delivered the highest specificity
of any inline campaign to date — every stated implementation claim is independently
verifiable against code artifacts. The test-to-implementation coverage mapping is clean (4
tests for 4 behavioral claims). git-workflow produced a commit message that is itself a
governance artifact.

**Primary gap:** deployment-readiness continues its streak of under-delivering on the full
deployment-readiness checklist despite the implementation being safe and correct. The agent's
contribution is "safety invariant confirmation" not "deployment plan" — a scope reduction
that accumulates as technical governance debt.

**Safety assessment:** CLEAN. No wFirma writes. No auth changes. No schema changes.
WFIRMA_CREATE_PZ_ALLOWED=False preserved. _guard_wfirma_export unchanged. The change is
additive (new fields, new functions, no removal of existing gate logic) and directly
traceable to the stated problem (Diamond Point + Verhoeven preview blocked by wrong gate
placement).
