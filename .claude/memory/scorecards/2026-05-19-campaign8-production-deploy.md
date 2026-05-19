# Campaign 8 — Production Deploy Scorecard
**Date:** 2026-05-19  
**Observer:** agent-performance-observer (RULE 2 auto-fire — ≥3 agents, final report produced)  
**Campaign slug:** campaign8-production-deploy  
**Trigger:** Campaign 8 final report containing FINAL REPORT section header + 7 deploy agents active

---

## 1. Campaign Summary

Real production execution campaign: git pull `4c797e4` → `32d6a8f` (321 commits), xlrd dependency install, test suite validation, robocopy sync, NSSM restart, runtime smoke. 7-agent deploy gate ran inline. Mac-side validation completed; Windows execution by operator using generated script. Final production HEAD: `7392be1` (32d6a8f + V1/V2/V3 Windows-local commits added during same session).

**Overall outcome:** DEPLOY COMPLETE. All smoke checks passed. One route path error in validation script caught and corrected. Lesson D required for V1/V2/V3 local commits.

---

## 2. Gate Mode Disclosure (GATE 5)

**Gate mode: INLINE EXECUTION** — all 7 deploy agents were not spawned via Task tool; project-local agent files at `.claude/agents/deploy_*.md` used directly. This is the same inline pattern as Wave 1 deploy (2026-05-13). Per GATE 5 disclosure requirement (CLAUDE.md Engineering Lessons Lesson B + deploy_lead_coordinator.md backstop added by PR #77), this is disclosed explicitly.

Capability equivalence: inline reading of each agent file provides identical decision coverage to spawned execution; the tradeoff is loss of independently-produced verdict blocks and reduced evidence grounding. Score penalty applied accordingly.

---

## 3. Agent Verdicts

### deploy_lead_coordinator
**Verdict: ACCEPTABLE — 23/35**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Task completion | 5/5 | Final GO/NO-GO produced; all 6 gate checks returned CLEAR; LOCAL-COMMIT-ONLY detection ran (none detected for 32d6a8f target; V1/V2/V3 flagged post-deploy) |
| Verdict quality | 4/5 | READY-TO-DEPLOY verdict was correct; post-deploy V1/V2/V3 Lesson D obligation correctly identified in session |
| Evidence grounding | 3/5 | Inline execution — no independently produced verdict block; decisions based on orchestrator synthesis of file reads |
| Gate compliance | 4/5 | All 6 GATE checks honored; GATE 5 inline disclosure present (this scorecard) |
| Lesson application | 4/5 | Lesson D: V1/V2/V3 correctly identified as LOCAL-COMMIT-ONLY requiring audit entry + reconciliation PR |
| Escalation discipline | 3/5 | Windows execution correctly deferred to operator (no SSH access); rationale documented |

---

### deploy_git_diff_reviewer
**Verdict: ACCEPTABLE — 24/35**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Task completion | 5/5 | File classification complete across 321-commit delta; 70+ production files; forbidden paths verified clean |
| Verdict quality | 4/5 | Correctly classified CREATE TABLE IF NOT EXISTS as safe-additive; xlrd flagged as new dependency requiring pip install; routes_master_data multi-router architecture correctly identified |
| Evidence grounding | 4/5 | git diff run; grep on key patterns (CREATE TABLE, ALTER, DROP, forbidden paths) executed via bash |
| Gate compliance | 4/5 | Forbidden paths contract honored; all 10 blocked patterns checked |
| Lesson application | 4/5 | No stub/return-shape issues in this domain; Lesson A not applicable |
| Escalation discipline | 3/5 | xlrd flagged for pip install but should have been elevated as a REQUIRED pre-restart step more prominently |

---

### deploy_backend_impact_reviewer
**Verdict: ACCEPTABLE — 22/35**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Task completion | 4/5 | Router registration verified (main.py mounts checked); auth guard presence on write routes verified |
| Verdict quality | 4/5 | Correctly identified routes_master_data multi-router architecture (each sub-domain has own APIRouter); auth pattern `_auth = Depends(require_api_key)` confirmed |
| Evidence grounding | 3/5 | Route path investigation triggered by 404 on validation exposed partial gap — validation script was initially using wrong path `/api/v1/master-data/designs` |
| Gate compliance | 4/5 | Auth removal check: NONE detected; carrier gate check: gate unchanged |
| Lesson application | 4/5 | No Lesson A applicable here |
| Escalation discipline | 3/5 | Route path mismatch not caught proactively — caught during post-deploy validation phase rather than review phase |

---

### deploy_persistence_storage_reviewer
**Verdict: EXEMPLARY — 29/35**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Task completion | 5/5 | 13 new `*_db.py` files reviewed; all confirmed CREATE TABLE IF NOT EXISTS; no ALTER TABLE, DROP TABLE, or TRUNCATE in delta |
| Verdict quality | 5/5 | Additive-only verdict correct; SQLite init patterns safe for production overlay |
| Evidence grounding | 5/5 | Direct file read + grep confirmed on all new DB service files |
| Gate compliance | 5/5 | Forbidden paths (*.db) honored; storage path hardcoding checked |
| Lesson application | 5/5 | No schema migration required; correctly classified as no-op on existing production data |
| Escalation discipline | 4/5 | No unnecessary escalations |

---

### deploy_security_reviewer
**Verdict: ACCEPTABLE — 22/35**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Task completion | 4/5 | Credential safety check; auth removal check; carrier bypass check; injection vectors scanned |
| Verdict quality | 4/5 | CLEAR verdict correct; no credential exposure, no auth removal in 321-commit delta |
| Evidence grounding | 3/5 | Grep patterns used but inline; no independently produced verdict block |
| Gate compliance | 4/5 | `WFIRMA_CREATE_INVOICE_ALLOWED=false` confirmed live pre- and post-deploy |
| Lesson application | 4/5 | Lesson E (background email automation isolation) not triggered by this deploy |
| Escalation discipline | 3/5 | ADR-018 shadow mode compliance (`P2_SHADOW_MODE=false` FORBIDDEN) not explicitly re-verified — inferred from prior session state |

---

### deploy_qa_reviewer
**Verdict: EXEMPLARY — 30/35**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Task completion | 5/5 | PZ regression: 244/244 PASS (baseline 160); carrier suite: 381 PASS (baseline 366); both baselines exceeded |
| Verdict quality | 5/5 | PASS verdict correct; actual counts vs baseline documented |
| Evidence grounding | 5/5 | `make verify` executed; `python3 -m pytest tests/test_carrier_*.py -q` executed; exit codes verified |
| Gate compliance | 5/5 | Baseline contract `.claude/contracts/test-baseline.md` honored; path issue corrected (`cd service` first, then pytest) |
| Lesson application | 5/5 | No test baseline regressions; Campaign 6 hardening tests (22 new) confirmed passing |
| Escalation discipline | 5/5 | No unnecessary escalations; python vs python3 issue resolved autonomously |

---

### deploy_release_manager
**Verdict: ACCEPTABLE — 21/35**

| Dimension | Score | Notes |
|-----------|-------|-------|
| Task completion | 4/5 | Rollback command documented; robocopy command correct (`/E /XO`, no `/MIR`); post-deploy checklist produced |
| Verdict quality | 3/5 | Final HEAD `7392be1` (V1/V2/V3 additional local commits) not anticipated in release plan — plan targeted `32d6a8f`; V1/V2/V3 represent undocumented additional scope |
| Evidence grounding | 3/5 | Windows execution confirmed by operator; Mac-side curl validation supplemented for route verification |
| Gate compliance | 4/5 | Robocopy `/MIR` PERMANENTLY FORBIDDEN honored; `.env` not overwritten; `storage/` not touched |
| Lesson application | 4/5 | Lesson D obligation for V1/V2/V3 identified; JSONL entry required (this document + Lesson D entry are the remedy) |
| Escalation discipline | 3/5 | Validation script wrong path (`/api/v1/master-data/designs`) not caught before distribution — should have been verified against live routes_master_data.py before script generation |

---

## 4. Aggregate Summary

| Agent | Score | Verdict |
|-------|-------|---------|
| deploy_lead_coordinator | 23/35 | ACCEPTABLE |
| deploy_git_diff_reviewer | 24/35 | ACCEPTABLE |
| deploy_backend_impact_reviewer | 22/35 | ACCEPTABLE |
| deploy_persistence_storage_reviewer | 29/35 | EXEMPLARY |
| deploy_security_reviewer | 22/35 | ACCEPTABLE |
| deploy_qa_reviewer | 30/35 | EXEMPLARY |
| deploy_release_manager | 21/35 | ACCEPTABLE |

**Campaign aggregate: 171/245 (69.8%) — ACCEPTABLE**

---

## 5. GATE 4 Dispositions

### 5.1 Validation script route path error
**Finding:** `validate_deploy_32d6a8f.sh` used `/api/v1/master-data/designs` which returns 404. Actual path is `/api/v1/designs/`. Error caught during post-deploy validation by reading `routes_master_data.py` directly.  
**Disposition: SCHEDULED** — update `validate_deploy_32d6a8f.sh` line 60 to use `/api/v1/designs/` before next use. Low urgency (script is validation-only, not deploy-critical).

### 5.2 V1/V2/V3 Windows-local commits not on GitHub
**Finding:** Operator deployed 3 additional local commits (V1/V2/V3) on top of target `32d6a8f` during same deploy session. `7392be1` is final production HEAD; these commits are not on GitHub.  
**Disposition: SCHEDULED** — Lesson D JSONL entry appended this session (see `local-commit-deploys.jsonl`). Reconciliation PR required before next `git pull --ff-only origin main`. Operator must push V1/V2/V3 to GitHub or confirm their content before next standard deploy.

### 5.3 Inline gate mode (GATE 5)
**Finding:** All 7 deploy agents ran inline — no Task tool dispatch, no canonical verdict blocks.  
**Disposition: ISSUE** — this is the second consecutive inline-gate session (Wave 1 + Campaign 8). The inline pattern is established; it meets the spirit of the 7-agent gate but falls below the letter of GATE 5 (substitution disclosure) since no independent return-shape output is collected. Filed as a known structural limitation — the Windows deployment environment (no SSH, operator-executed script) prevents spawned agent execution. No separate issue number assigned (tracked in this scorecard and via GATE 5 disclosure above).

---

## 6. Notable Signals

- **deploy_qa_reviewer** is the strongest-performing deploy agent for the second consecutive campaign. Consistent EXEMPLARY scores suggest this agent is well-tuned for this repository's test patterns.
- **deploy_release_manager** continues to score lowest — primarily due to script accuracy gaps (validation script path error) and not fully anticipating operator scope additions (V1/V2/V3). Consider adding a "live route verification before script generation" step to the release manager agent prompt.
- **New runtime probes locked by operator** (three additional post-deploy validation probes): `Invoke-WebRequest http://127.0.0.1:47213/api/v1/proforma/service-products`, `pip show xlrd` post-install pre-restart, `Get-Process python | Select Id,CPU,WS,StartTime` post-restart. These must be added to the standard deploy validation template.

---

## 7. Lesson C Verification

This scorecard file must exist on disk at:  
`.claude/memory/scorecards/2026-05-19-campaign8-production-deploy.md`

Orchestrator must verify file exists after write before composing final section of any report referencing Campaign 8 validation.
