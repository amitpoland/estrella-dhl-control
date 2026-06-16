# Agent Performance Scorecard — OCR/AI Image-Only Extraction Fallback

**Date:** 2026-06-17
**Campaign:** OCR/AI image-only extraction fallback (feat/ocr-ai-image-only-extraction-fallback @ eca52c7 → PR #632)
**Scope:** Feature + workflow hardening — Document Extraction Pipeline. Customs/financial-adjacent. 8 files changed, +1829 insertions, 3 new files (vision_extractor.py, document_text_quality.py, test_vision_extraction_fallback.py). 42 tests pass.
**Outcome:** SHIPPED to PR (no deploy). GATE 1 satisfied (all reviewer verdicts returned, all HIGH/CRITICAL resolved before PR open). GATE 2 satisfied (1 open PR before → within 3-PR limit).
**Agents evaluated:** 3 (reviewer-challenge, security-permissions, backend-safety-reviewer)

---

## Per-agent scorecard

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| reviewer-challenge | 4 | 4 | 5 | 5 | 5 | 4 | 3 | 30 | EXEMPLARY |
| security-permissions | 5 | 5 | 5 | 5 | 2 | 5 | 3 | 30 | EXEMPLARY |
| backend-safety-reviewer | 4 | 3 | 4 | 4 | 5 | 3 | 3 | 26 | ACCEPTABLE |

---

## Scoring rationale per agent

### reviewer-challenge (30 — EXEMPLARY)

- **Specificity (4):** Named the concrete failure mode precisely: a blank-currency invoice amount could be written as USD CIF without confirming the currency denomination, producing a silent wrong-currency write. The finding named the affected write gate and the symmetric waybill path as the fix target. Follow-up confirmation named "Finding 1 is RESOLVED" with mitigation and disclosure terms. Minor deduction: the FINAL REPORT summary does not include explicit file:line references for where the write gate was inspected or where the fix was verified (vision_extractor.py is named in the change list but not cited with a line number in the reviewer's verdict block as summarised).

- **Coverage (4):** Caught the primary financial-authority risk (invoice CIF currency ambiguity). The follow-up verification loop was completed — the agent returned a second verdict confirming resolution rather than issuing a single-pass verdict and going silent. Minor gap: no explicit mention of scope-discipline coverage (wFirma booking, SAD/ZC429, VAT posting left untouched) and no independent waybill-path symmetry check cited; the symmetric fix was operator-described rather than independently verified by the reviewer.

- **Severity (5):** BLOCK is correct for an invoice write gate that could write a possibly-EUR amount as USD CIF. Currency denomination ambiguity in a CIF field is financial-authority-adjacent with direct impact on landed cost calculation — BLOCK is not inflated. Downgrade to RESOLVED after fix with Ship-with-mitigations is correctly calibrated (not lingering at BLOCK after demonstrated fix). This is the best severity calibration signal in the campaign — the reviewer escalated correctly and de-escalated correctly.

- **Actionability (5):** The finding directly produced two concrete actions: (1) the invoice write gate now requires explicit `custom_val_currency == "USD"`, withholding blank-currency amounts as `withheld_unknown_currency_invoice`; (2) the prompt was strengthened to always elicit `custom_val_currency` so valid USD invoices still resolve. Both actions are operator-verifiable against the diff. The follow-up confirmation with "mitigations and disclosures" is the correct closure step.

- **Substitution (5):** reviewer-challenge is repo-installed (canonical per RUNTIME_AGENT_AUDIT addendum 2026-06-06, installed from user-level with inspect-only tools Read/Grep/Glob). No substitution. No registry mismatch. Full GATE 5 compliance.

- **Evidence (4):** The reasoning chain (blank currency → possible EUR → written as USD CIF) is logically complete and independently verifiable against the vision_extractor.py write gate. Follow-up confirmation with "RESOLVED" is a concrete closed-loop signal. Minor deduction: no quoted code excerpt or line reference in the verdict summary establishing which exact code path triggered the concern; the reasoning is inferential from the task description rather than citing a line in the diff.

- **Environment (3):** No explicit disclosure in the reviewer's verdict block of which working tree path was examined (C:\PZ-ocr-fallback vs C:\PZ-verify), which branch/SHA was inspected, or confirmation that the cited files exist at the examined path. The campaign summary establishes branch context (feat/ocr-ai-image-only-extraction-fallback @ eca52c7) but this was not self-reported in the reviewer's verdict. Scores 3 rather than 1 because no evidence that a wrong-path failure occurred — the findings are substantively correct and the fix was confirmed. Structural disclosure gap only.

---

### security-permissions (30 — EXEMPLARY)

- **Specificity (5):** C1 CRITICAL is precisely characterised: the `cif_usd <= 0` branch in routes_dashboard.py preservation guard rescued only `invoice_cif_total_usd`, leaving `fob_total_usd`, `vision_extracted`, and `vision_source_page` unprotected — a named set of three specific fields that would be dropped. The "#570-class partial wipe" label correctly references the engineering lesson class (merge-not-replace / authority-data-merge-never-replace). H1 (invoice currency write gate) was independently confirmed, cross-referencing Finding 1 from reviewer-challenge without orchestrator prompting. Post-fix confirmation: "Both fixes are confirmed as applied correctly and fully resolve the two blocking findings ... No residual issues on C1 or H1." This is the most precisely characterised verdict in the campaign.

- **Coverage (5):** Two independent high-value findings from two distinct code paths (extraction write gate in vision_extractor.py; preservation guard in routes_dashboard.py). Independent rediscovery of H1 (the invoice currency block) validates reviewer-challenge's finding through a second authority. C1 CRITICAL is a net-new finding not raised by reviewer-challenge — the preservation guard partial-wipe is a distinct failure class from the currency write gate. Full post-fix verification loop completed for both. This is exemplary coverage depth for a customs/financial-adjacent feature.

- **Severity (5):** C1 CRITICAL is correctly calibrated. Loss of `fob_total_usd` + provenance fields in the preservation guard is a genuine #570-class regression — it would silently drop already-written vision authority data on a follow-up text-parse recheck, exactly the authority-data merge-never-replace class that caused a production incident. CRITICAL is not inflated for a field-drop in a customs data pipeline. H1 is correctly rated HIGH (could write wrong-currency CIF). Post-fix, "No residual issues" is the correct severity de-escalation. Severity management across both findings and both lifecycle phases (pre-fix / post-fix) is accurate throughout.

- **Actionability (5):** C1 produced a specific code change: the preservation guard in `routes_dashboard.py` was extended to preserve `fob_total_usd / vision_extracted / vision_source_page` before the field-specific `invoice_cif` rescue. H1 independently confirmed the resolution path already identified by reviewer-challenge. Both findings have concrete, verifiable fixes in the diff. Post-fix re-verification closes the loop without ambiguity.

- **Substitution (2):** `security-permissions` is a **user-level runtime agent, not a repo-canonical agent**. Per RUNTIME_AGENT_AUDIT §A (2026-06-06), it is listed as classification REV (install-review-only), deferred from repo installation. The canonical security review agents for this repository are `security-write-action-reviewer` (repo-canonical) and the deploy gate's `deploy_security_reviewer` (repo-canonical). The FINAL REPORT does not disclose the substitution, does not name the capability equivalence gap, and does not log the registry mismatch per GATE 5. Per GATE 5: "If a named subagent is not in the current registry, the substituting agent must... Be named explicitly in Section 2... Have capability equivalence stated... Have the registry mismatch logged for follow-up registry repair. Silent substitution is forbidden." The substitution was effective (the agent found real issues) but GATE 5 disclosure was absent. Score 2 rather than 1 because the quality of the work demonstrates the agent's capability was sufficient for the security review scope — the failure is disclosure, not competence.

- **Evidence (5):** Three named fields dropped by the preservation guard partial-wipe (`fob_total_usd`, `vision_extracted`, `vision_source_page`) represent verifiable negative-evidence claims — checkable against the `cif_usd <= 0` branch in `routes_dashboard.py`. "#570-class" cross-reference to a named incident class is engineering-lesson anchored. Independent confirmation of H1 from a different code inspection angle provides redundant positive evidence. Post-fix "confirmed as applied correctly" is a named closure artifact. This is the highest evidence-density verdict in the campaign.

- **Environment (3):** Same structural disclosure gap as reviewer-challenge — no explicit self-report of working tree path, branch, or SHA in the verdict block. Non-disclosure is doubly notable here because the GATE 5 substitution disclosure failure compounds: an unregistered agent that also does not self-disclose its examination environment creates two independent verification gaps. Score remains 3 (not 1) because the finding substance is verified correct by the campaign's fix confirmation — no wrong-path failure is evidenced.

---

### backend-safety-reviewer (26 — ACCEPTABLE)

- **Specificity (4):** Named the specific gap precisely: `_merge_precheck_invoice` did not set `cif_source`, meaning the preservation guard would carry stale `"not_parsed"` label rather than `"vision_llm"` after a vision CIF write. The named field (`cif_source`), the named function (`_merge_precheck_invoice`), and the named stale value (`"not_parsed"`) are all specific and verifiable. Minor deduction: the FINAL REPORT summary does not include a file:line citation for where in `_merge_precheck_invoice` the missing assignment was found, and no grep output or code excerpt is quoted.

- **Coverage (3):** The reported finding is a nit-level field-labelling gap — a real issue but the least severe of the three reviewer findings. The agent did not surface any additional findings on the 8-file / +1829-line change. Given the scope includes new vision extraction logic, new schema-validated AI output path, and new currency withheld-value logic, the coverage footprint from the FINAL REPORT is narrower than expected for a customs/financial-adjacent feature of this size. No negative-evidence statements for the paths not flagged (e.g., confirmed no unsafe write patterns in vision_extractor.py, confirmed idempotency on vision retry path, confirmed no direct audit writes bypassing merge guards). The agent's canonical scope per its definition includes "unsafe POST endpoints, missing idempotency, direct audit writes" — none of these are confirmed or cleared in the reported output.

- **Severity (4):** The nit label is correct: missing `cif_source` label does not corrupt data, it creates a stale provenance field. Not a blocker. Severity is appropriately calibrated — it is not inflated (not CRITICAL) and not suppressed (it was reported rather than silently waived). The fix is a one-line label assignment.

- **Actionability (4):** The finding is directly actionable: `_merge_precheck_invoice` now sets `cif_source="vision_llm"` (Edit D in the campaign). The fix is verifiable against the diff. Minor deduction: the report does not specify whether a regression test was added to cover the `cif_source` field label assertion, so the closure evidence is partial.

- **Substitution (5):** backend-safety-reviewer is repo-canonical (inspect-only, tools: Read, Grep, Glob). No substitution. Full GATE 5 compliance.

- **Evidence (3):** The named finding (missing `cif_source` assignment in `_merge_precheck_invoice`) is verifiable by reading that function. However, the FINAL REPORT does not include: a code excerpt showing the missing line, a grep output establishing that `cif_source` is set elsewhere for comparison, or a before/after showing the stale value that would have been written. For a 1829-line feature addition, one finding with no supporting grep output and no negative-evidence sweep is a thin evidence record. The finding is real and was fixed, but the evidentiary base does not demonstrate a proportionate inspection depth.

- **Environment (3):** Same structural disclosure gap as the other two agents — no explicit self-report of working tree path, branch, or SHA in the verdict block. Score 3 as no wrong-path failure is evidenced.

---

## Weak-verdict warnings

### backend-safety-reviewer (ACCEPTABLE — 26)

**Failed or weak dimensions:** Coverage (3), Evidence (3)

**Evidence gap excerpt from FINAL REPORT:** "backend-safety-reviewer — flagged that _merge_precheck_invoice did not set cif_source, so the preservation guard would carry stale 'not_parsed'; fixed (Edit D adds cif_source='vision_llm')."

This is a single sentence describing a single nit finding on an 8-file / +1829-line customs/financial-adjacent feature. The agent's canonical scope includes: unsafe POST endpoints, missing idempotency, direct audit writes, missing readiness checks. None of these are confirmed-clear or flagged in the reported output. The absence of negative-evidence statements means the Coverage score cannot be raised — absence of reported findings could mean "none found after thorough inspection" or "inspection was shallow."

**Coverage gap specifics:** Given the new files include `vision_extractor.py` (AI output write path with schema validation) and `document_text_quality.py` (classification logic), the following backend-safety topics are in scope but unreported:
- Whether the vision write path (`_merge_precheck_invoice`, `_merge_precheck_waybill`) carries readiness gates before writing CIF to shared audit state
- Whether the new withheld-value path (`withheld_unknown_currency_invoice`) handles partial-write idempotency correctly
- Whether the vision retry path uses safe merge-not-replace semantics on re-attempt (GATE 4 disclosed as an open question, suggesting this was not fully verified by any reviewer)

**Recommendation:** Re-dispatch backend-safety-reviewer against `vision_extractor.py` and `routes_dashboard.py` with explicit scope: (1) confirm all write paths carry readiness gates, (2) verify merge-not-replace semantics on vision CIF write AND on the vision retry path, (3) confirm no direct audit writes bypass the merge guard, (4) provide negative-evidence statement for idempotency on re-attempt. This is a SCHEDULED disposition (see GATE 4 note below).

**GATE 4 disposition for ACCEPTABLE verdict:** SCHEDULED — backend-safety-reviewer re-run against this PR's vision write paths to be conducted as part of the pre-deploy gate when PR #632 moves to production deploy. The GATE 4 disclosed follow-up items (batch_write_lock race, mtime-based retry signature) overlap with the idempotency and merge-not-replace gaps in the backend-safety verdict; a combined pre-deploy review covers both.

---

### security-permissions — GATE 5 disclosure failure (non-NEEDS-TUNING, but mandatory notation)

**Dimension failed:** Substitution (2)

`security-permissions` is a user-level runtime agent (RUNTIME_AGENT_AUDIT classification: REV / deferred, not repo-installed). The canonical security review agent for this project is `security-write-action-reviewer` (repo-canonical). The FINAL REPORT activates `security-permissions` without GATE 5 disclosure: no capability equivalence statement, no registry mismatch log, no named substitution acknowledgment.

The quality of the work — catching the #570-class fob_total_usd preservation wipe as C1 CRITICAL — demonstrates the agent was capability-sufficient for this review scope. The failure is governance disclosure, not competence. The Total score (30) remains EXEMPLARY because the six substantive dimensions are strong.

**GATE 4 disposition for Substitution-2:** SCHEDULED — Add to the pre-deploy gate for PR #632: require that the security reviewer dispatched is either `security-write-action-reviewer` (repo-canonical) or `deploy-security-reviewer` (repo-canonical deploy gate agent), with explicit substitution disclosure if either is unavailable per GATE 5. Log the `security-permissions` registry gap for registry-repair consideration in the next agent governance session.

---

## Repeated failure hints

**5 most recent campaign scorecards reviewed:**
1. 2026-06-16: deploy-gate-pr625-626-627 (7 deploy agents)
2. 2026-06-15: deploy2-pr602-pr608 (7 deploy agents)
3. 2026-06-13: deploy1-authority-train (7 deploy agents)
4. 2026-06-13: campaign-02-5-authority-completion
5. 2026-06-13: c02-authority-consolidation

**reviewer-challenge — prior scorecard appearances:**
- 2026-06-12 cn-hsn-false-block-fix: EXEMPLARY (28) — Severity scored 2/5 for unverified HIGH-1 claim about operator recovery loss (claim was factually incorrect, not verified before issue). Finding resolved in-campaign by independent verification.
- 2026-06-17 (this campaign): EXEMPLARY (30) — Severity scored 5/5 for correctly calibrated BLOCK that de-escalated after confirmed fix. No unverified claims observed.

**Signal:** The cn-hsn severity miscalibration (unverified HIGH claim) did not recur in this campaign. reviewer-challenge issued a BLOCK with sound reasoning and completed a full verification lifecycle (finding → fix → confirmed-resolved). No REPEATED-WEAK flag.

**security-permissions — prior scorecard appearances:**
No prior scorecards in the reviewed set contain `security-permissions` as a named scored agent. This is the first appearance in the scorecard record. No baseline for trend analysis.

**backend-safety-reviewer — prior scorecard appearances:**
- 2026-06-12 cn-hsn-false-block-fix: EXEMPLARY (33) — Specificity 5, Coverage 5, Evidence 5. Full file:line evidence (audit_scoring.py:89, cn_analyzer.py:156). Thorough coverage of engine changes and audit path modifications.
- 2026-06-17 (this campaign): ACCEPTABLE (26) — Coverage 3, Evidence 3. Single finding, no negative-evidence sweep, no grep output.

**Signal:** A single-campaign regression from EXEMPLARY (33) to ACCEPTABLE (26) is notable given the scope difference — the cn-hsn campaign was a targeted bug fix in known files, while this campaign adds 1829 lines across 8 files including a new AI extraction pathway. The evidence quality gap may reflect scale-sensitivity: backend-safety-reviewer performs well on contained, familiar code surfaces but may reduce coverage depth on large novel features. Not yet REPEATED-WEAK (one occurrence), but watch-list recommended for the next feature-PR campaign with backend-safety-reviewer.

**No REPEATED-WEAK flags triggered across all reviewed agents.**

---

## Notable quality signals

**High-value redundancy — two independent reviewers converged on the invoice-currency block:** reviewer-challenge raised Finding 1 (BLOCK) and security-permissions independently confirmed H1 without orchestrator prompting. This is the intended function of multi-reviewer campaigns — independent convergence validates that the finding is real rather than an artifact of one reviewer's assumptions. The campaign would have caught this finding even if one reviewer had missed it. This is a genuine defense-in-depth signal.

**C1 CRITICAL #570-class regression caught pre-merge:** security-permissions' C1 finding — that the `routes_dashboard.py` preservation guard rescued `invoice_cif_total_usd` but dropped `fob_total_usd / vision_extracted / vision_source_page` — is structurally identical to the #570 link-wipe incident (authority write replacing rather than merging a shared record). If this had reached production, a follow-up text-parse recheck would have silently dropped vision-written authority data with no error surfaced. This is the highest-value finding in the campaign and justifies the `security-permissions` activation even with its substitution disclosure gap.

**GATE 4 disclosed follow-ups are honest:** The three GATE 4 disclosed items (batch_write_lock race, variance/derived-CIF not surfaced in UI, mtime-based retry) are correctly classified as DISCLOSE rather than blocking. Each is bounded in blast radius (worst case: lost provenance run + one redundant API call, not wrong CIF) and represents a known limitation rather than a failure. This is the correct governance behavior — honest disclosure of open items rather than suppression or false-complete claims.

**scope discipline confirmed:** wFirma booking, SAD/ZC429 accounting, VAT posting, and production deploy scripts are all confirmed untouched. Unknown CIF represented as UNKNOWN (cif_usd=None)/extraction_gap, never fake 0. Lesson M and Lesson G binding sites both honored in the PR scope.

---

## Self-evaluation cadence check

**Most recent self-eval:** `.claude/memory/scorecards/self-eval-2026-06-13.md` (written 2026-06-13)
**Today:** 2026-06-17
**Days elapsed:** 4 calendar days
**Trigger threshold:** 7 calendar days OR SELF-DEGRADATION flag + 3rd campaign scorecard run since flag

**Result: Self-evaluation NOT triggered.** 4 days < 7-day threshold. The 2026-06-13 self-eval concluded "No degradation detected" — no SELF-DEGRADATION flag is active.

**Next self-eval due:** 2026-06-20 (7 calendar days from 2026-06-13).

---

## Campaign quality summary

**Three-reviewer gate effectiveness:** STRONG. All three reviewers returned verdicts. Two independent reviewers converged on the highest-severity finding (invoice currency block). security-permissions independently caught a #570-class regression (fob_total_usd wipe) that no other reviewer raised. backend-safety-reviewer caught a field-labelling nit. All findings were resolved before PR open.

**Key value from reviewers:**
- reviewer-challenge: Correct BLOCK on financial-authority-adjacent currency write gate, with full lifecycle (finding → fix → confirmed-resolved)
- security-permissions: Highest-value catch in the campaign — C1 CRITICAL #570-class preservation guard partial-wipe; independent H1 confirmation; both post-fix verified
- backend-safety-reviewer: Real (if nit-level) finding; nit correctly labelled; fix confirmed; coverage depth insufficient for feature scale

**Agent reliability:** 2/3 EXEMPLARY, 1/3 ACCEPTABLE. No NEEDS-TUNING. No UNRELIABLE. No integrity failures.

**Structural gaps to carry forward:**
1. Environment disclosure: all 3 agents scored 3/5 on Environment — no self-reported working tree path, branch, or SHA in verdict blocks. Prompt-template gap. No wrong-path failure evidenced.
2. GATE 5 substitution: security-permissions invoked without disclosure. Effective but non-compliant. SCHEDULED for pre-deploy gate correction.
3. backend-safety-reviewer scale-sensitivity: coverage depth regression on large novel feature. SCHEDULED for pre-deploy re-run against vision write paths.
