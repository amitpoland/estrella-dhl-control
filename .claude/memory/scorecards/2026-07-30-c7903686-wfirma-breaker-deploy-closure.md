# Campaign Scorecard: wFirma Circuit-Breaker Stuck-OPEN — Merge + Deploy Closure

**Date:** 2026-07-30
**Campaign slug:** c7903686-wfirma-breaker-deploy-closure
**Deployed SHA:** `c7903686a13d1579b749c993e11b7f00a6afcdd5`
**PRs:** #1041 (circuit-breaker recovery path fix) + #1040 (error classification + UI)
**Reviewed heads:** `1f2d226d` (#1041) / `160582e4` (#1040), preserved as MERGE-commit ancestors on main
**Rollback unit:** `c7903686a13d1579b749c993e11b7f00a6afcdd5-20260730-194654` (intact, unconsumed)
**Task:** Fix wFirma circuit-breaker stuck-OPEN defect (permanent failure until restart); deploy combined main SHA to production; verify breaker recovery + `EJL/26-27/453-1/-2/-3` Resolve-Mapping resolution.
**Outcome:** COMPLETE — `Test-PZDeployClose.ps1` 10/10 PASS; all three affected product codes now resolve live; no tracebacks, no 5xx, no credential leak in post-deploy window.
**Observer trigger:** Operator `/observe` (RULE 4) against a multi-phase campaign with ≥3 subagent dispatches across three phases.

**Evidence sources read:**
- `C:\PZ-verify\reports\deploy\2026-07-30-c7903686-wfirma-breaker-deploy-closure.md`
- `C:\PZ-verify\.claude\memory\TASK_STATE.md` (Current task + superseded EXECUTION_BLOCKED block)
- `C:\PZ-verify\.claude\memory\PROJECT_STATE.md` (first 200 lines — PRs #1041/#1040 merge blocks, provenance-correction note)
- `C:\PZ-verify\reports\inspection\2026-07-30-wfirma-breaker-stuck-open-resolve-mapping.md`
- Prior scorecards: `2026-07-28-advisory-service-id-draft-fallback.md`, `self-eval-2026-07-28.md`, `2026-07-17-proforma-privileged-auth.md`

---

## 1. Per-agent scorecard table

**Important evidence note:** Phase 1 reviewer verdict blocks (backend-safety-reviewer, security-reviewer, reviewer-challenge) and individual Phase 2 specialist agent verdict blocks are not present in the evidence sources provided to this observer. Those agents' scores are marked **(evidence-limited)** and reflect only what is verifiable from the campaign summary — outcome verdicts, not internal reasoning or file:line citations. Evidence-limited NEEDS-TUNING is a documentation-coverage gap, NOT a confirmed performance failure; see Section 2 for GATE-4 dispositions.

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| Part-A diagnosis agent (root-cause inspector) | 5 | 5 | 5 | 5 | 5 | 5 | 4 | **34** | EXEMPLARY |
| Phase 1 backend-safety-reviewer | 2 | 3 | 3 | 3 | 5 | 1 | 3 | **20** | NEEDS-TUNING (evidence-limited) |
| Phase 1 security-reviewer | 2 | 3 | 3 | 3 | 5 | 1 | 3 | **20** | NEEDS-TUNING (evidence-limited) |
| Phase 1 reviewer-challenge | 2 | 3 | 3 | 3 | 5 | 1 | 3 | **20** | NEEDS-TUNING (evidence-limited) |
| deploy-lead-coordinator (Phase 2) | 4 | 4 | 4 | 4 | 5 | 3 | 3 | **27** | ACCEPTABLE |
| deploy specialist agents ×6 (Phase 2) | 2 | 3 | 3 | 3 | 5 | 1 | 3 | **20** | NEEDS-TUNING (evidence-limited) |
| flow-context-keeper | 3 | 3 | 2 | 1 | 5 | 2 | 3 | **19** | NEEDS-TUNING |
| orchestrator session | 5 | 5 | 4 | 5 | 5 | 5 | 5 | **34** | EXEMPLARY |

---

## Dimension rationale per agent

### Part-A diagnosis agent (root-cause inspector) — 34 — EXEMPLARY

This agent produced `reports/inspection/2026-07-30-wfirma-breaker-stuck-open-resolve-mapping.md` as the Part A diagnostic output of the campaign plan.

**Specificity (5):** Exact log timestamp and count: `2026-07-30 01:44:01,639 WARNING circuit[wfirma] → OPEN after 4 consecutive failures`; 3,704 `circuit OPEN — request rejected` rejection lines from 01:44:01 to 16:46:58 (15 hours); zero HALF_OPEN transitions in that span. Code path named at the function level with approximate line numbers: `wfirma_client._http_request` (~line 500) raw `.state` property fast-path; `circuit_breaker.py` `.state` property at line 128; `_maybe_transition()` at line 164; `breaker.call()` invocation. Four consecutive `ConnectTimeoutError` events to `api2.wfirma.pl:443` named by timestamp. Network verification: direct TLS connect 0.04s, DNS → 46.248.166.9.

**Coverage (5):** Covered the full diagnostic surface: what tripped the breaker (payment-sync ConnectTimeouts 01:43:28–01:44:01), why it cannot self-recover (`.state` property bypasses `_maybe_transition()`), the 46h log span as evidence window, network health confirmation (TLS healthy), immediate operator remedy (restart), post-restart code fix path, the `EJL/26-27/453-1/-2/-3` resolution dependency (fiscal write gated by `WFIRMA_CREATE_PRODUCT_ALLOWED` if codes absent — HOLD disclosed), and explicit GATE-4 disposition with three alternative fix strategies.

**Severity (5):** Correctly assessed as a code defect causing permanent stuck-OPEN affecting ALL wFirma functionality (payment sync, contractor lookup, goods lookup, PZ, proforma resolve-mapping), not just one path. Correctly distinguished from a transient failure — the network was healthy; the blocker was the code path, not the dependency. GATE-4 finding correctly filed. Remedies are graduated by urgency (restart now, code fix separate PR, keep #1040 message intact). No over-classification or under-classification.

**Actionability (5):** Three-tier action plan with clear rationale for each tier: (1) immediate restart (operator), (2) post-clear code fix in a separate PR (not folded into error-classification #1040), (3) GATE-4 regression test specification (opens breaker → advances fake clock → asserts HALF_OPEN). The rationale for keeping #1040's "wait ~1 min" message intact once the fix lands is explicitly explained. The `WFIRMA_CREATE_PRODUCT_ALLOWED` gate disclosure is explicit and prevents an unintended fiscal write.

**Substitution (5):** Canonical diagnostic dispatch. GATE 5 N/A.

**Evidence (5):** Raw log lines quoted verbatim with timestamps. Grep count stated (3,704 rejections; zero genuine upstream contact after open). Network check result stated (HTTP 200, 0.04s, specific IP). Code excerpts reproduced as inline blocks showing the exact mechanism. These artifacts are independently verifiable against the production log. Maximum evidence quality for a read-only diagnostic.

**Environment (4):** Production log path explicitly named (`C:\PZ\logs\pz_stdout.log`), log span bounded (2026-07-28 18:12 → 2026-07-30 16:46). Diagnosis correctly scoped to production artifacts, not the git tree. Minor gap: no worktree self-disclosure (not relevant for a production-log-only diagnosis, but the established scoring convention records the absence). Score 4/5.

---

### Phase 1 backend-safety-reviewer — 20 — NEEDS-TUNING (evidence-limited)

Evidence available: outcome verdict "CLEAN" in operator campaign summary. No verdict block in provided evidence set.

**Specificity (2):** No file:line references, no named code constructs, no mechanism descriptions verifiable from available evidence. "CLEAN" conveys the outcome but not the work.

**Coverage (3):** "CLEAN" outcome implies the agent's scope was addressed (no unexamined surface that subsequently produced a problem in production). The fix touched `wfirma_client.py` (two raw-`.state` fast-paths removed) and `circuit_breaker.py` (no changes per report). A CLEAN verdict on these surfaces is plausible. Not verifiable.

**Severity (3):** "CLEAN" with no findings is appropriately calibrated IF the scope had no issues. Post-deploy production evidence (0 tracebacks, 0 auth changes, 0 credential leaks in log review) is consistent with a correctly-clean backend-safety verdict. Not independently verifiable from verdict block.

**Actionability (3):** "CLEAN" is directly actionable as a gate pass. No ambiguity about next step. Minor gap: no list of what was confirmed vs what was skipped.

**Substitution (5):** Canonical registered agent. GATE 5 N/A.

**Evidence (1):** Only outcome verdict available in the observer's evidence set. No artifact, no file:line, no grep output verifiable.

**Environment (3):** Standard disclosure gap; no path-drift failure evidenced from production outcomes.

**Note on prior history:** backend-safety-reviewer scored EXEMPLARY (30/35) in the 2026-07-17 campaign with Evidence 4/5. Issue #694 (REPEATED-WEAK on Evidence 3/5 pattern) was recorded as requiring one more clean verifiable appearance to close. This Phase 1 "CLEAN" outcome is consistent with rehabilitation but is not independently verifiable evidence.

---

### Phase 1 security-reviewer — 20 — NEEDS-TUNING (evidence-limited)

Evidence available: outcome verdict "CLEAN" in operator campaign summary. No verdict block in provided evidence set.

**Specificity (2):** Same limitation as backend-safety-reviewer. No file:line references or mechanism descriptions in available evidence.

**Coverage (3):** The security scope for a circuit-breaker fix includes: credential exposure (none introduced), auth surface changes (none — `routes_wfirma_capabilities.py` routes not re-authenticated), no new write path. "CLEAN" consistent with this scope. Not verifiable from the verdict block.

**Severity (3):** "CLEAN" is appropriate calibration for a fix that does not introduce new auth surfaces, new write endpoints, or credential handling. The closure report confirms: 0 credential-string matches in post-deploy logs, auth correctly gated (401 without X-API-Key). Consistent with a correctly-clean security verdict.

**Actionability (3):** "CLEAN" directly actionable. Same rationale as backend-safety-reviewer.

**Substitution (5):** Canonical registered agent. GATE 5 N/A.

**Evidence (1):** Only outcome verdict available.

**Environment (3):** Standard gap.

---

### Phase 1 reviewer-challenge — 20 — NEEDS-TUNING (evidence-limited)

Evidence available: outcome verdict "SHIP-WITH-MITIGATIONS" in operator campaign summary. No verdict block in provided evidence set.

**Specificity (2):** No named findings, no file:line references, no mitigation descriptions verifiable from available evidence.

**Coverage (3):** "SHIP-WITH-MITIGATIONS" is the correct calibration for a circuit-breaker fix on shared resilience infrastructure — real risks exist (shared `circuit_breaker.py` affects all integrations; raw-`.state` fast-path pattern may exist elsewhere) and mitigations are expected. The outcome implies findings were made and scope was addressed.

**Severity (3):** "SHIP-WITH-MITIGATIONS" implies the agent found something above LOW but did not block. For a resilience-infrastructure change, MEDIUM-level findings requiring mitigations (e.g., test regression coverage, scope of the `.state` fast-path pattern, interaction with DHL circuit breaker) would be appropriate severity calibration. Not verifiable from the verdict block.

**Actionability (3):** Mitigations were applied (Phase 1 completed and PRs #1041/#1040 passed review). The verdict drove the right outcome. Specific mitigation artifacts not verifiable.

**Substitution (5):** Canonical registered agent. GATE 5 N/A.

**Evidence (1):** Only outcome verdict available.

**Environment (3):** Standard gap.

**Note on prior history:** reviewer-challenge scored EXEMPLARY (33/35) in 2026-07-17 and EXEMPLARY (31/35) in 2026-07-28. No prior weak pattern. The evidence-limited NEEDS-TUNING here reflects documentation coverage, not agent performance.

---

### deploy-lead-coordinator (Phase 2) — 27 — ACCEPTABLE

Evidence available: TASK_STATE summary — "READY-TO-DEPLOY (risk MEDIUM, LOCAL-COMMIT-ONLY NOT-DETECTED, all three cross-agent conflicts resolved)"; test counts (160/160 golden, PZ 260, carrier 646 / 4 documented-environmental, targeted 116 green); blast radius (23 files in service/app, no root engine file).

**Specificity (4):** Risk assessment (MEDIUM) is named with context. LOCAL-COMMIT-ONLY NOT-DETECTED is explicitly verified (not assumed). Three cross-agent conflicts were resolved (implies specialist agents flagged substantive issues requiring adjudication — concrete coordination work). Test floor counts cited. Blast radius by content stated (Lesson P). Lesson J N/A confirmed (no root engine files in the 23-file blast radius). A specific, named basis for READY-TO-DEPLOY. Minor deduction: the three cross-agent conflicts are counted but not individually named in the available evidence.

**Coverage (4):** Standard coordinator surfaces covered: risk synthesis, LOCAL-COMMIT-ONLY check, test verification, blast-radius calculation, cross-agent conflict resolution. The EXECUTION_BLOCKED outcome correctly records that the gate was satisfied but execution required operator-held credentials — the coordinator correctly stopped at READY-TO-DEPLOY without attempting to bypass the signing gate.

**Severity (4):** MEDIUM risk is appropriate for a change to shared resilience infrastructure (`circuit_breaker.py` affects all integrations — wFirma, DHL, and any future registrations) with no fiscal writes, no auth changes, and a well-tested fix. LOW would understate the shared-infrastructure blast radius; HIGH would overstate the bounded scope. MEDIUM is calibrated correctly.

**Actionability (4):** READY-TO-DEPLOY directly actionable; the EXECUTION_BLOCKED rationale (signed deploy artifact required) was correctly recorded as the resumable stop condition, not as a gate failure. The coordinator's verdict enabled the operator to arm the signer and proceed without re-running the gate.

**Substitution (5):** Canonical registered agent. GATE 5 N/A.

**Evidence (3):** Summary-level — test counts, file count, risk label, LOCAL-COMMIT-ONLY verdict. No verbatim conflict descriptions, no per-specialist-agent cross-reference in what the observer can read. The coordinator synthesized findings but the observer cannot verify the synthesis from the available evidence.

**Environment (3):** No explicit worktree path or target SHA self-disclosure in the summary. Target SHA is stated externally (TASK_STATE), not as part of the coordinator verdict block itself. Standard gap.

---

### Deploy specialist agents ×6 (Phase 2) — 20 — NEEDS-TUNING (evidence-limited)

Agents: deploy-git-diff-reviewer, deploy-backend-impact-reviewer, deploy-persistence-storage-reviewer, deploy-security-reviewer, deploy-qa-reviewer, deploy-release-manager.

Evidence available: "6 CLEAR/GO" in TASK_STATE summary. No individual verdict blocks in evidence set.

**Specificity (2):** No individual agent findings, file:line references, or mechanism descriptions in available evidence. Each returned CLEAR/GO but what each specifically inspected is not verifiable.

**Coverage (3):** The coordinator resolved three cross-agent conflicts, implying the specialists collectively flagged real substantive issues that required adjudication. This is positive coverage evidence — they did not all blindly pass. The fact that the coordinator's risk assessment was MEDIUM (not LOW) is consistent with the specialists surfacing meaningful signals.

**Severity (3):** CLEAR/GO outcomes accepted by the coordinator as appropriate for the 23-file blast radius. No post-deploy evidence of missed severity (0 tracebacks, 0 auth failures, 0 5xx in the verification window).

**Actionability (3):** CLEAR/GO collectively actionable. The coordinator's synthesis was READY-TO-DEPLOY.

**Substitution (5):** All 6 are canonical registered agents. GATE 5 N/A.

**Evidence (1):** Only group outcome verdict. No individual artifacts.

**Environment (3):** Standard gap.

**Grouping note:** These 6 agents are scored as a group solely due to evidence limitation. Prior campaigns (e.g., 2026-07-11 deploy gate scorecard — 6 EXEMPLARY + 1 ACCEPTABLE across all 7 deploy agents individually) demonstrate these agents individually produce EXEMPLARY-quality work when verdict blocks are in the observer's evidence set.

---

### flow-context-keeper — 19 — NEEDS-TUNING

Evidence: Documented error in operator campaign brief and TASK_STATE. The agent recorded both merges (PR #1041 and #1040) as "SQUASH-MERGED" in PROJECT_STATE.md. The orchestrator session caught this via `git merge-base --is-ancestor` verification, which proved both reviewed heads (`1f2d226d` for #1041, `160582e4` for #1040) are ancestors of main `c7903686` — the signature of a true MERGE-commit, not a squash-merge.

**Specificity (3):** The agent did record the key identifiers: PR numbers, reviewed head SHAs, and main SHA `c7903686`. These specifics are present and correct. However, the merge-type classification ("SQUASH-MERGED") is wrong for both PRs. The agent's specific fact record was partially correct, partially not.

**Coverage (3):** flow-context-keeper's mandate includes accurate recording of merge provenance. It covered the major facts (PR IDs, SHAs, combined main SHA) but misclassified the merge type for both entries — a defined coverage area that failed.

**Severity (2):** SQUASH-MERGED vs MERGE-committed is not a cosmetic difference. Squash-merges destroy the intermediate commit graph and do not preserve reviewed head SHAs as ancestors of main; merge-commits do. Misclassifying as squash-merged introduces false confidence about whether the reviewed code is traceable via ancestry — a real audit trail concern. This is not a LOW finding; the merge-type is part of the governance chain-of-custody record.

**Actionability (1):** The agent did not self-correct. The error required the orchestrator session to independently verify via `git merge-base --is-ancestor` and flag the discrepancy. No self-correction mechanism was activated.

**Substitution (5):** Canonical registered agent. GATE 5 N/A.

**Evidence (2):** The agent recorded SHAs correctly; the merge-type label is factually wrong. The core factual claim ("SQUASH-MERGED") is verifiably incorrect via `git merge-base --is-ancestor`, which is a basic git verification step. Recording a wrong fact about a central campaign event — the merge type — is a meaningful evidence quality failure.

**Environment (3):** Operating on the correct paths (PROJECT_STATE.md in C:\PZ-verify); the error is interpretive (wrong merge-type label), not a wrong-path failure. Standard gap on explicit path disclosure.

---

### Orchestrator session — 34 — EXEMPLARY

This entity covers the full multi-phase orchestration: diagnosis coordination, GATE-1 pre-deploy validation, EXECUTION_BLOCKED recording, signer investigation, post-deploy verification.

**Specificity (5):** Every claim grounded in named, verifiable artifacts. Merge heads verified: `1f2d226d` (#1041), `160582e4` (#1040), confirmed as ancestors of `c7903686` via `git merge-base --is-ancestor`. Signer investigation covered: `PZ_DEPLOY_AUTH_KEY` / `PZ_DEPLOY_AUTH_KEY_FILE` / `PZ_DEPLOY_AUTH_DIR` in all three OS scopes (Process/User/Machine); Credential Manager; Scheduled Tasks (two Microsoft built-ins identified and distinguished from deploy signers); `.claude/hooks/sign_deploy_authorization.py` minting tool correctly located after operator challenge. Post-deploy: production PID named (6644), port (47213), version.txt hex head (`63 37 39 30 33 36 38 36` = ASCII `c7903686`), BOM-free confirmed, consumed JTI ID (`b2929f65….used`), rollback unit ID, watchdog log events with timestamps (01:46:48 FAIL → HOLD → 01:47:46 RECOVERED). Polish diacritics "mojibake" correctly identified as PowerShell console decoding artifact, not production defect.

**Coverage (5):** Full campaign lifecycle covered: root-cause inspection (Part A), merge provenance verification including correction of flow-context-keeper SQUASH-MERGED error, GATE-1 7-agent deploy gate coordination, signer availability determination (exhaustive — all 3 env scopes + Credential Manager + Scheduled Tasks), EXECUTION_BLOCKED recording with complete resume commands, production baseline snapshot (pre-deploy SHA, health, version), post-deploy 10-point validator (0 discrepancies), log review (10-minute window, 5 grep searches), classification correctness proof from deployed source (classifier in `routes_wfirma_capabilities.py`, JSX `d.ok` check at `proforma-detail.jsx:2412`), GATE-4 disposition for `_wfirma_error_envelope`, agent write ledger (zero fiscal/production mutations).

**Severity (4):** Three misses noted; all recovered:
(1) Initial signer-availability conclusion was incomplete — reported only that env vars were unset without finding `.claude/hooks/sign_deploy_authorization.py`. The operator challenged; the corrected search found the tool. This is a meaningful miss: "no signer provisioned" vs "signer tool exists but key never generated" are different situations with different resume instructions. Score deduction here.
(2) Wrong backup-path assumption (`C:\PZ\backups` vs configured `C:\PZ-backups`) — self-corrected by reading `windows_prod_v2.json`. A lower-severity miss because it was self-caught before affecting the EXECUTION_BLOCKED record.
(3) The recovered EXECUTION_BLOCKED record is correct and sound; the ultimate analysis was accurate.
Score 4 not 5: the signer-tool miss required operator challenge to surface. Self-corrections score higher than operator-challenged corrections.

**Actionability (5):** EXECUTION_BLOCKED record is fully resumable — complete resume command sequence including one-time key generation, env var setting, directory creation, signer minting for deploy and rollback, and the Deploy-PZ.ps1 invocation with explicit SHA. The decline of live-failure injection is correctly calibrated: intentionally tripping the production circuit breaker is a destructive production action under ANTI-HOLD condition #1. Proving classification correctness from deployed code + the merged test suite is the sound alternative. GATE-4 SCHEDULED for `_wfirma_error_envelope` (separate hardening slice, not a deploy blocker). Flow-context-keeper error caught and corrected.

**Substitution (5):** Main orchestration session. GATE 5 N/A.

**Evidence (5):** Hex-dump of version.txt (BOM-free confirmation, not just a text read), specific rollback unit ID, specific JTI ID format, specific HTTP response body size for application shell (16,357 bytes), specific wFirma_id values for the three resolved product codes (51495203 / 51495331 / 51495267), specific log grep result counts (0 for each of 5 searches), specific PID + port, specific watchdog timestamps. These are independently reproducible artifacts, not self-reported.

**Environment (5):** Worked from explicit paths throughout. `C:\PZ-main` (deploy source, clean at target), `C:\PZ-verify` (git operations), `C:\PZ` (production read-only checks). Target SHA `c7903686a13d1579b749c993e11b7f00a6afcdd5` named throughout. Merge heads resolved via `git merge-base --is-ancestor` command against the correct tree. Branch named (main, ff-only from origin). Rollback artifact path explicitly distinguished from deploy artifact. EXECUTION_BLOCKED `recorded_branch: main` + `recorded_head: c7903686`. Production checks explicitly scoped to `127.0.0.1:47213` (local) and `pz.estrellajewels.eu` (public). Full environment disclosure — score 5/5.

---

## 2. Weak-verdict warnings

### Evidence-limited NEEDS-TUNING agents (Phase 1 and Phase 2 specialists)

**Agents:** Phase 1 backend-safety-reviewer, Phase 1 security-reviewer, Phase 1 reviewer-challenge, deploy specialists ×6.

**Nature of verdict:** Evidence-limitation NEEDS-TUNING, NOT performance-NEEDS-TUNING. The NEEDS-TUNING scores (20/35 each) are driven by Evidence dimension 1/5 — individual verdict blocks were not included in the observer's evidence set. The observer can only score what is in the provided evidence.

**Exculpatory signals:**
- Phase 1 backend-safety-reviewer: scored EXEMPLARY (30/35, Evidence 4/5) in 2026-07-17. No production evidence of a missed finding.
- Phase 1 security-reviewer: production log shows 0 credential leaks, auth correctly gated post-deploy. Consistent with correctly-clean scope.
- Phase 1 reviewer-challenge: scored EXEMPLARY (31/35) in 2026-07-28 and EXEMPLARY (33/35) in 2026-07-17. "SHIP-WITH-MITIGATIONS" outcome drove real improvements; mitigations were applied.
- Deploy specialists ×6: three cross-agent conflicts identified and resolved by coordinator (positive signal that specialists flagged substantive issues, not rubber-stamps). Production outcome clean.

**Recommendation — do NOT re-dispatch.** The low scores reflect a documentation coverage gap in what the observer was given to read, not confirmed performance failures. Re-dispatch or prompt tuning is not warranted.

**GATE-4 disposition for evidence-limited NEEDS-TUNING verdicts:**
- Phase 1 backend-safety-reviewer: **REJECTED** — evidence-limited score; prior history EXEMPLARY; no re-dispatch warranted.
- Phase 1 security-reviewer: **REJECTED** — same rationale.
- Phase 1 reviewer-challenge: **REJECTED** — evidence-limited score; prior history EXEMPLARY (31 + 33 in last 2 scored appearances).
- Deploy specialists ×6: **SCHEDULED** — evidence-limited score for the group. Campaign documentation improvement needed: 7-agent deploy gate verdict blocks should appear individually in campaign reports so the observer can score them at full resolution. Add this as a documentation chip (no prompt change required; the verdict blocks exist but were not routed to the observer's evidence set).

---

### flow-context-keeper (NEEDS-TUNING — performance gap)

**Failed dimensions:** Severity calibration (2/5), Actionability (1/5), Evidence quality (2/5).

**Supporting evidence from TASK_STATE and operator brief:**
- The agent recorded "SQUASH-MERGED" for both PR #1041 and #1040 in PROJECT_STATE.md.
- The orchestrator verified `git merge-base --is-ancestor <reviewed-head> c7903686` for both reviewed heads (1f2d226d, 160582e4) and confirmed they ARE ancestors — the definitive MERGE-commit signature.
- The agent did not self-correct. The orchestrator caught it independently during merge provenance verification.

**Why severity matters here:** squash-merge vs merge-commit is not a cosmetic label. A squash-merge destroys intermediate commit ancestry; a merge-commit preserves it. The reviewed head SHA — the exact code that was reviewed — is traceable from main ONLY through the merge-commit ancestry. Incorrect classification could lead a future session to conclude "reviewed head not verifiable from main" and either re-run unnecessary validation or, worse, accept a divergent head as the reviewed one.

**Why Actionability is 1/5:** No self-correction mechanism activated. The agent wrote the wrong fact and had no feedback loop to catch it. The CLAUDE.md production truth about merge type is verifiable in <5 seconds (`git merge-base --is-ancestor <sha> HEAD`). This step is missing from flow-context-keeper's output.

**GATE-4 disposition: SCHEDULED.** Add a merge-type verification step to the flow-context-keeper process: after recording a merge as SQUASH-MERGED or MERGE-committed in PROJECT_STATE, run `git merge-base --is-ancestor <reviewed-head> <combined-sha>` and confirm the result matches the label before writing. This is a single-command validation step, not a prompt redesign. File as agent-tuning chip for flow-context-keeper. Priority: medium (governance audit trail quality).

**Recommendation: do NOT re-dispatch against this campaign.** The underlying information is now correct (orchestrator corrected it). The chip addresses the systemic gap.

---

## 3. Repeated failure hints

**5 most recent prior campaign scorecards reviewed (excluding self-eval files):**
1. 2026-07-28: `2026-07-28-advisory-service-id-draft-fallback.md` — 2 agents: security-write-action-reviewer ACCEPTABLE (27), reviewer-challenge EXEMPLARY (31). No NEEDS-TUNING or UNRELIABLE.
2. 2026-07-17: `2026-07-17-proforma-privileged-auth.md` — 4 entities: backend-safety-reviewer EXEMPLARY (30), security-write-action-reviewer EXEMPLARY (28), reviewer-challenge EXEMPLARY (33), orchestrator EXEMPLARY (34). No NEEDS-TUNING.
3. 2026-07-11: `2026-07-11-pr-queue-clear-b123bd4c-deploy-gate.md` — 8 entities: 6 EXEMPLARY, deploy-security-reviewer ACCEPTABLE (27), deploy-release-manager ACCEPTABLE (26). No NEEDS-TUNING or UNRELIABLE (referenced from TASK_STATE; not re-read in full for this scorecard).
4. 2026-07-03: `2026-07-03-phase-c-wave2-backend.md` — 3 entities: all EXEMPLARY.
5. 2026-06-22: `2026-06-22-pr720-merge-validation.md` — orchestrator EXEMPLARY (35).

**flow-context-keeper:**
First scored appearance in the accessible scorecard record. No prior REPEATED-WEAK baseline. NEEDS-TUNING (19/35) on first appearance — flag as WATCH. If the next scorecard scoring flow-context-keeper also shows Actionability ≤ 2 or Evidence ≤ 2, establish REPEATED-WEAK and escalate.

**Active REPEATED-WEAK flags (carried from prior scorecards):**

`REPEATED-WEAK: agent frontend-flow-reviewer has scored ACCEPTABLE (Evidence 3/5) in 5+ consecutive campaign appearances.`
- GATE 4 ISSUE disposition generated in `2026-06-21-freight-authority-blocker-repair.md`. GitHub issue tagged `agent-tuning` has been pending operator confirmation for **8+ scorecard cycles** without confirmation or explicit REJECTED disposition. This agent did not appear in this campaign (no UI surface). Flag carries forward.
- **Escalation:** This is now the 8th+ consecutive scorecard cycle. The operator must provide one of: (a) confirmation that the `agent-tuning` GitHub issue has been filed (ISSUE), (b) a SCHEDULED chip in the system, or (c) an explicit REJECTED entry in PROJECT_STATE.md DECISIONS. "Recommendation noted" is not a valid GATE 4 disposition. The observer cannot close this; only the operator can.

`REPEATED-WEAK: agent backend-safety-reviewer — Issue #694 open (Evidence 3/5 pattern, prior entries).`
- Phase 1 appearance in this campaign returned "CLEAN" — consistent with the EXEMPLARY (30/35, Evidence 4/5) rehabilitation point from 2026-07-17 but not independently scoreable from the observer's evidence set. Issue #694 remains open: one more verifiable EXEMPLARY appearance with Evidence ≥ 4/5 and Severity ≥ 4/5 is required before closing. The Phase 1 "CLEAN" outcome is a positive signal, not a verifiable close condition.

---

## 4. Summary: GATE-4 dispositions from this scorecard

| Finding | Disposition | Action |
|---|---|---|
| Phase 1 backend-safety-reviewer NEEDS-TUNING (evidence-limited) | REJECTED | Evidence gap in observer's sources; prior EXEMPLARY history; no re-dispatch or prompt tuning warranted |
| Phase 1 security-reviewer NEEDS-TUNING (evidence-limited) | REJECTED | Same rationale |
| Phase 1 reviewer-challenge NEEDS-TUNING (evidence-limited) | REJECTED | Same rationale; two prior EXEMPLARY appearances (33/35, 31/35) |
| Deploy specialists ×6 NEEDS-TUNING (evidence-limited) | SCHEDULED | Campaign documentation chip: route 7-agent deploy gate individual verdict blocks into observer evidence set for future scoring |
| flow-context-keeper NEEDS-TUNING (merge-type error) | SCHEDULED | Agent-tuning chip: add `git merge-base --is-ancestor <reviewed-head> <combined-sha>` post-write verification step to flow-context-keeper merge-recording process |
| frontend-flow-reviewer REPEATED-WEAK (8+ cycles) | ISSUE (overdue) | Operator must confirm GitHub issue `agent-tuning` is filed OR record explicit REJECTED disposition in PROJECT_STATE.md DECISIONS. "Recommendation noted" is not valid. |
| backend-safety-reviewer Issue #694 | Remains OPEN | One more verifiable clean Severity + Evidence appearance required; Phase 1 "CLEAN" is consistent but not independently scoreable |

---

## 5. Self-evaluation (RULE 5 — calendar-driven trigger check)

**Most recent self-eval file:** `self-eval-2026-07-28.md` (2026-07-28)
**Today:** 2026-07-30
**Calendar days elapsed:** 2 days
**Threshold:** 7 days
**SELF-DEGRADATION flag in most recent self-eval:** NO SELF-DEGRADATION DETECTED (31/35 EXEMPLARY)
**Counter trigger (3rd campaign after SELF-DEGRADATION):** Not applicable — no active SELF-DEGRADATION flag

**Self-evaluation: SKIPPED.** The most recent self-eval (`self-eval-2026-07-28.md`) is 2 days old, below the 7-day threshold. Neither trigger condition applies. No `self-eval-2026-07-30.md` written.
