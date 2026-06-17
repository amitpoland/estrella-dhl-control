# Agent Performance Scorecard — Deploy Gate: PR #632 OCR/AI Image-Only Extraction Fallback

**Date:** 2026-06-17
**Observer:** agent-performance-observer (RULE 2 mandatory fire — FINAL REPORT header + 7 distinct subagents in Section 2)
**Campaign:** PR #632 OCR/AI image-only extraction fallback deploy gate
**Branch:** feat/ocr-ai-image-only-extraction-fallback @ HEAD 7084931 (deploy target)
**Production SHA:** e4d96b5
**Review tree:** C:\PZ-ocr-fallback
**FINAL REPORT source:** C:\PZ-ocr-fallback\tmp_deploy_gate_report.md
**Context doc:** C:\PZ-ocr-fallback\tmp_deploy_gate_context.md
**Outcome:** READY-TO-DEPLOY (GO-WITH-CONDITIONS; conditions A/B resolved GREEN pre-report, C/D/E/F classified as GATE6/GATE4 follow-ups). All 7 canonical agents dispatched; GATE 5 clean.
**Agents evaluated:** 7

---

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| deploy-git-diff-reviewer | 4 | 5 | 5 | 5 | 5 | 3 | 3 | 30 | EXEMPLARY |
| deploy-backend-impact-reviewer | 5 | 5 | 5 | 5 | 5 | 5 | 3 | 33 | EXEMPLARY |
| deploy-persistence-storage-reviewer | 5 | 5 | 5 | 5 | 5 | 5 | 3 | 33 | EXEMPLARY |
| deploy-security-reviewer | 5 | 5 | 5 | 5 | 5 | 5 | 3 | 33 | EXEMPLARY |
| deploy-qa-reviewer | 5 | 5 | 5 | 5 | 5 | 5 | 3 | 33 | EXEMPLARY |
| deploy-release-manager | 4 | 5 | 5 | 5 | 5 | 4 | 3 | 31 | EXEMPLARY |
| deploy-lead-coordinator | 4 | 5 | 5 | 5 | 5 | 4 | 4 | 32 | EXEMPLARY |

---

## Scoring rationale per agent

### deploy-git-diff-reviewer (30 — EXEMPLARY)

**Specificity (4):** Verdict states all files are under `service/app/**`, flags V1 `shipment-detail.html`
with Lesson F/M compliance note, confirms no forbidden paths / schema / engine-core / auth changes. The
scope claim is correct and the compliance note is properly reasoned. Minor deduction: the verdict block
as captured in the FINAL REPORT is a single compound sentence without enumerating each changed file or
naming the specific forbidden-path check. The context doc provides the 10-file change table, but the
agent's own verdict should stand independent of the context doc.

**Coverage (5):** Full scope covered — forbidden paths, schema changes, engine-core, auth changes,
Lesson J compliance (no root-level engine files in diff → no separate C:\PZ\engine\ sync required),
and V1 freeze status (Lesson F/M). All mandatory diff-reviewer checklist items confirmed or cleared.
The Lesson J compliance determination is the most load-bearing coverage item for this change and it
is present.

**Severity (5):** CLEAR with a single non-blocking advisory (V1 shipment-detail.html, Lesson F/M
compliant) is correctly calibrated. The V1 flag is not inflated to a blocker — the context confirms
a +40 LOC display-only change consistent with Lesson M (capability not suppressed, testid surface
added). No suppression of real risk detected.

**Actionability (5):** Verdict directly enables pipeline progression. The non-blocking Lesson F/M
flag is classified with sufficient precision that the coordinator and operator can proceed without
ambiguity.

**Substitution (5):** No substitution. Section 5 of the FINAL REPORT confirms all 7 deploy agents
dispatched successfully. GATE 5 N/A.

**Evidence (3):** The verdict block as recorded in the FINAL REPORT does not enumerate a named file
list, a quoted diff excerpt, or an explicit forbidden-path check result. The conclusion is stated
but the supporting artifact (which files were checked, which paths were confirmed absent) is carried
in the context doc rather than in the agent's verdict. The context doc provides the 10-file table,
but that is orchestrator-prepared input, not agent-generated evidence. The deduction is structural:
a diff-reviewer verdict should enumerate findings, not assert a summary. Prior exemplary runs of
this agent (e.g. PR #582 on 2026-06-14) included explicit file classification. Score of 3 reflects
that the conclusion is correct but the evidence record is thin against this standard.

**Environment (3):** Working tree C:\PZ-ocr-fallback and deploy target SHA 7084931 are disclosed at
campaign level in the FINAL REPORT and context doc. The agent's verdict block does not self-report
the examined path or commit SHA. This is the systemic disclosure gap tracked across multiple recent
deploy-gate scorecards (GitHub Issue #597). Score of 3 reflects missing self-disclosure with no
source-drift impact (C:\PZ-ocr-fallback is a legitimate and correct review tree per PATH GUARD).

---

### deploy-backend-impact-reviewer (33 — EXEMPLARY)

**Specificity (5):** Four precise claims: (1) auth guards intact on all new routes; (2) no new routers
registered; (3) all 4 new deps present in requirements.txt; (4) vision imports use lazy try-except
(missing dep → no-op, never 500). Each claim is independently verifiable. The lazy-import characterization
is the most important specificity item — it names the exact safety mechanism for the new AI dependency
surface and distinguishes between a hard-import 500 failure mode and the actual graceful-degradation
path.

**Coverage (5):** Auth, router registration, dependency audit, and import safety pattern — the four
primary backend impact domains. The Step 5 non-fatal characterization extends coverage to the execution
ordering concern (Step 5 runs LAST after Step 4 atomic write; re-reads audit; no-ops unless CIF still
UNKNOWN) — this is the correct depth for a change that introduces a new non-blocking pipeline step.

**Severity (5):** LOW is correctly calibrated. The key risk surface (new AI dep causing startup
failures or 500 errors) is directly addressed by the lazy/try-except finding. "Missing dep → no-op,
never 500" is not reassurance — it names the specific failure mode that is being prevented. LOW for
an additive step with graceful degradation is non-deflated.

**Actionability (5):** The non-fatal Step 5 characterization and confirmed dep list give the coordinator
all the information needed to assess blast radius. No ambiguous conditions remain in the backend scope.

**Substitution (5):** Canonical agent. No substitution.

**Evidence (5):** "All 4 deps in requirements.txt" is a named count (fitz, anthropic, plus inferred
from the new services). "Try-except lazy import" is a named code pattern. "Step 5 doubly non-fatal
after step-4 atomic write" is a sequencing claim anchored in the routes_upload.py Step 5
characterization from the context doc. Strong evidence chain — each claim has an independently
verifiable mechanism.

**Environment (3):** Same campaign-level disclosure gap. No PATH GUARD violation, no source-drift
risk. Systemic issue per GitHub Issue #597.

---

### deploy-persistence-storage-reviewer (33 — EXEMPLARY)

**Specificity (5):** Three precisely named claims: (1) no DDL/migration; (2) `write_json_atomic` as
the write mechanism; (3) `_merge_awb_custom_val` and `_merge_precheck_invoice` using spread `**existing`
(#570-safe); (4) recheck preservation guard; (5) additive timeline event only. Function-level naming
on the merge guards is the critical specificity item — it references the exact #570 lesson (authority
merge never replace) applied at named functions.

**Coverage (5):** Full persistence surface: DDL (none), write atomicity (write_json_atomic), merge
pattern (#570-safe), recheck field preservation, and timeline event classification (additive only).
The `**existing` spread verification is the highest-stakes coverage item for a change that writes to
shared audit records — correctly prioritized. The additive timeline event classification closes the
scope boundary (no existing fields mutated, only EV_VISION_CIF_WRITTEN appended).

**Severity (5):** LOW with no conditions is correct. DDL-free, atomic writes, merge-safe pattern
verified, additive timeline — all four persistence dimensions are in the lowest-risk configuration.
LOW is not deflated because the evidence supports it.

**Actionability (5):** Unambiguous persistence clearance. The `**existing` spread finding is the
operator's assurance that the #570 failure class (authority-merge-never-replace) is not being
reintroduced by this change.

**Substitution (5):** Canonical agent. No substitution.

**Evidence (5):** Named functions (`_merge_awb_custom_val`, `_merge_precheck_invoice`) with `**existing`
spread are independently verifiable against the diff. The `write_json_atomic` mechanism is a named
function from the codebase. The `#570-safe` cross-reference is an engineering lesson application,
not a vague assertion. This is the correct evidence quality for a persistence reviewer.

**Environment (3):** Same campaign-level disclosure gap. No source-drift risk.

---

### deploy-security-reviewer (33 — EXEMPLARY)

**Specificity (5):** Four precisely scoped claims: (1) no secrets/hardcode; (2) CIF=0 fabrication
rejected at `_coerce_money` + prompt + confidence gate — a three-layer named mechanism; (3) AWB
2315714531 only in pre-existing comments/test fixtures — specific AWB string with specific location;
(4) off-limits paths untouched. The "canonical" label is self-asserted in the verdict block, providing
affirmative GATE 5 compliance disclosure. The Anthropic API advisory is explicitly scoped as "intended
design" with a GATE 4 follow-up.

**Coverage (5):** Secrets audit, hardcoded CIF fabrication vector (the primary financial-safety
concern for an AI extractor that could invent USD values), hardcoded AWB check, off-limits path
audit, and a novel security advisory for the external AI API call surface. The CIF fabrication
audit is the highest-stakes security concern for this specific change type and it is covered with
the most depth.

**Severity (5):** LOW with advisory is well-calibrated. The Anthropic API advisory is filed at the
right level — not a blocker (intended design) but requires a GATE 4 governance decision within 30
days (Section 4, condition [F]). The three-layer CIF fabrication defense makes LOW appropriate
for a financial-adjacent AI extractor.

**Actionability (5):** Each finding has a clear disposition. The GATE 4 advisory ([F]) has a named
timeline (30 days) and a named destination (PROJECT_STATE DECISIONS / ADR). The three-layer
fabrication defense names the functions, making any future regression detectable and actionable.

**Substitution (5):** "Canonical" explicitly stated in verdict block. This is affirmative GATE 5
compliance disclosure — the agent named its own registry status, not just implied it. Best
substitution disclosure practice.

**Evidence (5):** `_coerce_money` + prompt guard + confidence gate are three named, independently
verifiable code mechanisms. AWB 2315714531 in pre-existing fixtures is a specific string at a
specific location (verifiable by grep). Off-limits paths "untouched" is verifiable against the
diff. The three-layer defense is the strongest evidence chain in this campaign for a security claim.

**Environment (3):** Campaign-level disclosure gap, same as other agents.

---

### deploy-qa-reviewer (33 — EXEMPLARY)

**Specificity (5):** PZ 221/221 (exact count vs 221 baseline requirement), carrier 420/412 (exact
count vs 412 baseline), 31 new tests pass, zero ERRORs. Pre-existing failure identified by exact
test ID (`test_pz_batch.py::test_save_json_csv_ui_round_trip`), exact assertion string (`assert 8
== 4`), exact root cause (Windows `csv.writer \r\n → splitlines()` blank-line artifact), and exact
verification method (reproduced identically on prod SHA e4d96b5 in throwaway worktree). Two named
conditions (recheck-route integration test gap; CSV failure disposition).

**Coverage (5):** PZ baseline suite, Carrier baseline suite, new test suite, pre-existing failure
isolation and verification, and a prospective gap (recheck-route integration test missing for the
new AI fallback path). The pre-existing failure isolation is the highest-value coverage item: the
agent did not suppress the red test, did not report it as a new failure, and provided the evidence
chain to confirm it is not a regression. The recheck-route gap identification adds coverage depth
beyond passing counts.

**Severity (5):** GO-WITH-CONDITIONS is the correct verdict when all baselines pass and the one
failure is proven pre-existing with reproducible evidence. The conditions are correctly sized:
browser smoke (GATE 6) and recheck-route integration test (GATE 4 ISSUE) are both real gaps but
neither is a production blocker given the atomic-write Step 5 characterization from the backend
reviewer.

**Actionability (5):** Pre-existing failure is fully actionable — the operator has a named test,
a named mechanism, and confirmation it is not in the deploy diff. GATE 4 conditions [D] and [E]
(Section 4) provide explicit disposition paths. Browser smoke [C] is a concrete during-deploy
operator action. No ambiguity in what needs to happen next.

**Substitution (5):** Canonical agent. No substitution. The agent correctly consumed pre-run test
results from the context doc per the "DO NOT re-run, consume these" instruction — this is correct
behavior, not a coverage shortcut.

**Evidence (5):** This is the strongest evidence chain in the campaign. The pre-existing CSV
failure is proven by: (a) exact test ID; (b) exact assertion message; (c) exact root cause
mechanism (CRLF/splitlines artifact); (d) confirmed absent from `git diff --name-only e4d96b5..HEAD`;
(e) reproduced identically on prod SHA in throwaway worktree. Five independent evidence threads
on a single failure characterization. The 31 new tests passing and zero ERRORs in baseline suites
are concrete, verifiable counts. This is the gold standard for pre-existing failure evidence.

**Environment (3):** Campaign-level disclosure gap. Note: this agent consumed pre-supplied test
results from the context doc — the test runs themselves were executed against the correct tree
(C:\PZ-ocr-fallback / throwaway worktree on prod SHA). The environment is correct even if not
self-disclosed. Score of 3 reflects disclosure gap only, no correctness concern.

---

### deploy-release-manager (31 — EXEMPLARY)

**Specificity (4):** Branch hygiene clear, rollback to e4d96b5, standard robocopy + pycache purge
+ restart plan. Two conditions: fitz + anthropic_api_key verification. The robocopy plan is named
(standard robocopy + pycache purge + restart) but not enumerated with specific command syntax. The
rollback mechanism (rollback to e4d96b5) is specific in naming the SHA but not in naming the
rollback command. Minor deduction: prior exemplary deploy-release-manager runs have included explicit
rollback command syntax and full robocopy step enumeration. The dependency verification conditions
are the right specificity — they named what needed checking and the orchestrator ran the checks.

**Coverage (5):** Branch hygiene, rollback mechanism, sync plan, and critically: production
dependency verification (fitz, anthropic_api_key, AI_PARSER_ENABLED). The dependency
verification scope extension is the highest-value coverage item for an AI integration deploy
— correctly identifying that a new external-AI-call feature requires pre-deploy prod environment
verification, not just code review. The conditions were real blockers and the orchestrator's
GREEN resolution confirms the agent correctly scoped them.

**Severity (5):** GO-WITH-CONDITIONS is correct given the open dependency verification question.
Conditions were subsequently confirmed GREEN (PyMuPDF 1.26.5, key non-empty, AI_PARSER_ENABLED=true).
The agent correctly held the conditions open rather than assuming prod env parity — appropriate
caution for a new AI integration.

**Actionability (5):** The dependency conditions were actionable enough that the orchestrator
resolved them and documented the resolution (Section 3: "BOTH later VERIFIED GREEN by orchestrator").
This is the best possible actionability evidence — the conditions drove artifact collection and
the artifacts confirmed safety. Clean condition closure loop.

**Substitution (5):** Canonical agent. No substitution.

**Evidence (4):** The conditions (fitz + anthropic_api_key) are evidence-generating: they required
the orchestrator to run real verification commands. The results are now documented in the FINAL
REPORT (PyMuPDF 1.26.5, key non-empty, AI_PARSER_ENABLED=true). However, the deploy-release-manager
verdict block itself does not produce artifact-level evidence — it generates conditions that others
must satisfy. Minor deduction: no explicit robocopy command syntax, no Lesson J cross-reference
(though Lesson J applies — all changed files are under service/app/** and no engine files were
touched, so the standard sync is correct). The absence of an explicit Lesson J coverage statement
is a minor gap vs prior exemplary runs.

**Environment (3):** Same campaign-level disclosure gap. No source-drift risk.

---

### deploy-lead-coordinator (32 — EXEMPLARY)

**Specificity (4):** Named conditions A through F with resolution status. A/B (pre-sync) resolved
GREEN, C (GATE 6 browser smoke), D (recheck-route integration test → GATE 4 ISSUE), E (CSV failure
→ GATE 4 ISSUE or REJECTED), F (Anthropic API advisory → PROJECT_STATE/ADR within 30 days). The
condition labeling is clear and the resolution tracking is complete. Minor deduction: the coordinator's
synthesis does not cross-reference specific findings from individual agents (e.g., does not name
`_coerce_money` from security-reviewer or `_merge_awb_custom_val` from persistence-reviewer). Prior
exemplary coordinator runs have named the specialist findings. Score of 4 reflects correct synthesis
but thin cross-referencing.

**Coverage (5):** All 6 specialist verdicts synthesized. No hard blockers remain after A/B
resolution. All open items have explicit dispositions. The four-bucket structure (resolved/GATE6/
GATE4-ISSUE/GATE4-30day) covers the full disposition space. Section 4 maps dispositions cleanly.

**Severity (5):** READY-TO-DEPLOY is the correct synthesis verdict. No hard blockers, conditions
resolved or classified, all conditions explicitly dispositioned. The distinction between pre-sync
conditions (A/B — resolved) and post-deploy follow-ups (C/D/E/F — classified) is the right
severity architecture for a GO-WITH-CONDITIONS gate.

**Actionability (5):** The four-bucket disposition structure gives the operator a clear pre-sync
checklist (A/B closed, C during-deploy), GATE 4 filings needed (D/E), and governance work within
30 days (F). An operator receiving this verdict knows exactly what to do before sync, during
deploy, and after. No ambiguity.

**Substitution (5):** Canonical agent. Section 5 confirms no substitution across all 7 agents.
GATE 5 explicitly confirmed clean.

**Evidence (4):** Section 3 provides the primary evidence anchors: PZ 221/221, pre-existing CSV
reproduced on prod SHA, prod dep verification (PyMuPDF 1.26.5, key non-empty, AI_PARSER_ENABLED=true).
These are concrete artifacts. Minor deduction: the evidence in Section 3 summarizes the QA and
release-manager verification without naming the specific security mechanisms (three-layer CIF
fabrication defense) or persistence mechanisms (`**existing` spread) that make GO appropriate.
A coordinator verdict at maximum evidence quality would cite specialist findings by mechanism,
not just by verdict label.

**Environment (4):** The coordinator uniquely references the review tree (C:\PZ-ocr-fallback)
and the deploy delta (e4d96b5..7084931) in Section 1 and Section 3 of the FINAL REPORT. This
is above the 3/5 floor applied to all other agents — the coordinator synthesized the environment
disclosure from the context doc and surfaced it in the final output, making it reader-accessible
without requiring the context doc. Score of 4 (not 5) because the SHA examined by the coordinator
itself (HEAD 7084931) is referenced but the specific files confirmed out-of-scope are not enumerated
in the coordinator section (they live in Sections 2/3).

---

## Weak-verdict warnings

All 7 agents scored EXEMPLARY (30-33/35). No NEEDS-TUNING or UNRELIABLE verdicts.

**No GATE 4 salvage findings generated by agent verdicts.** All GATE 4 dispositions in this
campaign arise from the PR's own conditions (recheck-route integration test, CSV failure
classification, Anthropic API governance), not from agent quality failures.

**Recurring evidence gap — deploy-git-diff-reviewer (Evidence 3/5):** The diff-reviewer's
verdict as captured in the FINAL REPORT does not enumerate individual files or produce an
explicit forbidden-path check result. The conclusion is correct but the artifact is thin.
This gap has appeared in prior deploy-gate scorecards. No new GATE 4 disposition is generated
here (the existing systemic gap is tracked at GitHub Issue #597), but the pattern is noted for
the agent-prompt-refiner deferred backlog: diff-reviewer verdict blocks should enumerate named
files or at minimum named categories with file counts.

**Recurring environment disclosure gap (Environment 3/5 for 6 of 7 agents):** Systemic across
all deploy agents except the coordinator. GitHub Issue #597 is the open governance item. No new
GATE 4 filing generated here — this is a known, tracked debt.

---

## Historical comparison — deploy gate agents (5 most recent relevant scorecards)

| Scorecard | git-diff | backend-impact | persistence | security | qa | release-mgr | lead-coord |
|---|---|---|---|---|---|---|---|
| 2026-06-17 PR #632 (THIS) | EXEMPLARY (30) | EXEMPLARY (33) | EXEMPLARY (33) | EXEMPLARY (33) | EXEMPLARY (33) | EXEMPLARY (31) | EXEMPLARY (32) |
| 2026-06-16 PR #625/#626/#627 | EXEMPLARY (31) | EXEMPLARY (33) | EXEMPLARY (32) | EXEMPLARY (32) | EXEMPLARY (30) | EXEMPLARY (31) | EXEMPLARY (30) |
| 2026-06-15 deploy gate d37316e | EXEMPLARY | EXEMPLARY | EXEMPLARY | EXEMPLARY | EXEMPLARY | EXEMPLARY | EXEMPLARY |
| 2026-06-14 PR #582 | EXEMPLARY (34) | EXEMPLARY (34) | EXEMPLARY (34) | EXEMPLARY (34) | EXEMPLARY (34) | EXEMPLARY (34) | EXEMPLARY (34) |
| 2026-06-13 deploy-1 authority train | EXEMPLARY | EXEMPLARY | EXEMPLARY | EXEMPLARY | EXEMPLARY | EXEMPLARY | EXEMPLARY |

**No REPEATED-WEAK flags.** No agent meets the ≥2 NEEDS-TUNING or UNRELIABLE in 6 runs threshold.

**Trend observation:** The 2026-06-14 PR #582 scorecard showed uniform 34/35 across all 7 agents.
The subsequent three deploy gates (authority train, #625-627, and now #632) show a settled range
of 30-33/35, with the Environment dimension at 3/5 as the systemic floor. This is correctly
calibrated — the 34/35 run on PR #582 was a simpler single-file diff where Environment disclosure
was stronger; the more complex multi-service changes have a structural 3/5 Environment floor until
Issue #597 is addressed.

**deploy-qa-reviewer notable improvement:** This campaign produced the strongest QA evidence chain
in the recent deploy gate history — five independent evidence threads on the pre-existing CSV failure
characterization. The agent correctly consumed pre-supplied test results (per context doc instruction)
without re-running, and produced higher-quality failure isolation than campaigns where the agent ran
tests directly.

---

## Repeated failure hints

Reading 5 most recent prior scorecards (excluding this one and the PR #627 implementation scorecard):

**2026-06-16-pr627-cif-tristate-resolver.md** — 3 implementation agents: all EXEMPLARY. No deploy agents.
**2026-06-16-deploy-gate-pr625-626-627.md** — 7 deploy agents, all EXEMPLARY (30-33). Same Environment
floor (3/5 across all specialist agents). No REPEATED-WEAK.
**2026-06-15-pr522-merge-gate-wfirma-grammar.md** — 3 implementation agents, all EXEMPLARY. No deploy agents.
**2026-06-15-deploy-gate-d37316e-wfirma-grammar.md** — 7 deploy agents, all EXEMPLARY. Same pattern.
**2026-06-14-pr582-deploy-gate.md** — 7 deploy agents, all EXEMPLARY (34). Simpler diff, higher individual scores.

**No agent meets the ≥2 NEEDS-TUNING or UNRELIABLE in 6 runs threshold.**
**No REPEATED-WEAK flags generated.**

---

## RULE 5 self-evaluation cadence check

**Most recent self-eval:** `C:\PZ-ocr-fallback\.claude\memory\scorecards\self-eval-2026-06-16.md`
**Self-eval date:** 2026-06-16
**Calendar days elapsed from self-eval to today (2026-06-17):** 1 day
**7-day calendar threshold:** NOT MET (1 < 7)
**SELF-DEGRADATION DETECTED in self-eval-2026-06-16.md:** NO (explicitly "No SELF-DEGRADATION DETECTED")
**3rd-run counter active:** NO (SELF-DEGRADATION cleared; counter does not begin)

**Self-evaluation: SKIPPED — not triggered.**

---

## Campaign quality summary

**Campaign-level verdict:** EXEMPLARY — all 7 canonical agents dispatched successfully (GATE 5
clean), all returned substantive verdicts, no fabrication detected, no hard blockers found,
conditions resolved or correctly classified.

**Agent reliability:** 7/7 EXEMPLARY. Score range 30-33/35.

**Highest-performing agents this campaign:** deploy-backend-impact-reviewer, deploy-persistence-
storage-reviewer, deploy-security-reviewer, and deploy-qa-reviewer all at 33/35. The security
reviewer's three-layer CIF fabrication defense (`_coerce_money` + prompt + confidence gate) and
the QA reviewer's five-thread pre-existing failure proof are the standout evidence contributions.

**Structural quality signals:**
1. **Novel change type handled correctly:** This is the first AI-integration deploy gate in
   the project's history. The agents correctly adapted their standard checklists — backend
   reviewer added lazy-import safety, persistence reviewer verified merge-not-replace for
   AI-written audit fields, security reviewer added external-API advisory, release manager
   added prod env verification. No agent produced a generic review that ignored the AI-specific
   blast radius.

2. **No coordinator fabrication:** Deploy-lead-coordinator produced a clean synthesis with
   evidence-grounded conditions. No fabrication pattern (tracked across prior scorecards) recurs.

3. **Conditions were real blockers:** The two pre-sync conditions (fitz + anthropic_api_key)
   were verified GREEN before the report was finalized. This is the correct pipeline: conditions
   are gates, not suggestions. Both were verified before the coordinator issued READY-TO-DEPLOY.

4. **GATE 4 dispositions are complete:** All open items (D, E, F) have named dispositions in
   Section 4. D and E are GATE 4 ISSUE (follow-up GitHub issues). F is a 30-day governance
   action. No "recommendation noted" dispositions.

**Systemic debt remaining:** GitHub Issue #597 (agent self-disclosure of working tree and SHA in
verdict blocks) is the one open improvement. It does not affect verdict quality or deployment
safety — it affects scorecard verifiability. The Environment dimension will remain at 3/5 for
specialist agents until #597 is addressed at the agent-prompt level.
