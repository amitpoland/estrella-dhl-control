# Campaign Scorecard: Tracking Cache Inner Record Fix

**Date:** 2026-07-31
**Campaign slug:** tracking-cache-inner-record
**PR:** #1052 (branch `fix/tracking-cache-inner-record`, OPEN)
**Worktree:** `C:\PZ-verify\.claude\worktrees\nifty-williamson-a68fec`
**Commit:** `a743e7b819ed7402dd621faad977a4a69a9e1c4a` (a743e7b8)
**Scope:** 4 files changed: `tracking_service.py` (2 shared helpers added), `routes_dashboard.py` (site 1 fix), `batch_state_normalizer.py` (site 2 fix), `test_tracking_cache_inner_record.py` (18 new tests).
**Task:** GATE-4 salvage finding — fix two production read paths that called `.get("status")` on the outer AWB-keyed `tracking_cache.json` dict, returning `""` always instead of reading the inner per-AWB record. Both `action_diagnostics` and `normalize_batch_state` were silently stuck in the empty/blocked state regardless of real shipment status.
**Outcome:** OPEN PR — both sites fixed, 18/18 tests pass, 160/160 golden regression, 19 pre-existing failures unchanged. Operator merge/deploy deferred per governance.
**Observer trigger:** RULE 4 manual invocation (`/observe`), ≥3-subagent threshold waived per operator directive. Single-agent execution scored.

Primary evidence sources:
- `C:\PZ-verify\.claude\worktrees\nifty-williamson-a68fec\service\app\services\tracking_service.py` (helpers at lines 245-292)
- `C:\PZ-verify\.claude\worktrees\nifty-williamson-a68fec\service\app\api\routes_dashboard.py` (site 1 fix, lines 1829-1846)
- `C:\PZ-verify\.claude\worktrees\nifty-williamson-a68fec\service\app\services\batch_state_normalizer.py` (site 2 fix)
- `C:\PZ-verify\.claude\worktrees\nifty-williamson-a68fec\service\tests\test_tracking_cache_inner_record.py` (18 tests)
- PR #1052 commit message (full mechanism narrative, sha `a743e7b8`)

---

## 1. Per-agent scorecard table

| Agent | Specificity | Coverage | Severity | Actionability | Substitution | Evidence | Environment | Total | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| orchestrator (sole implementer) | 5 | 5 | 4 | 5 | 5 | 5 | 5 | 34 | EXEMPLARY |

---

## Dimension rationale

### orchestrator (sole implementer) — 34/35 — EXEMPLARY

**Specificity (5):**

Root cause established at mechanism level, not asserted: `_save_cache(cache[tracking_no] = result)` in `tracking_service.py` proves the cache file is keyed by tracking number at the outer level. The reading paths' failure mode was then precisely located:

- Site 1: `action_diagnostics` in `routes_dashboard.py` — called `.get("status")` on the outer AWB-keyed dict (top level has AWB strings as keys, not "status")
- Site 2: `normalize_batch_state` in `batch_state_normalizer.py` — same structural mistake

Two new helpers are named and their signatures described:
- `resolve_batch_tracking_no(audit, batch_id)` — resolution order `audit.tracking_no` → `audit.awb` → `SHIPMENT_<awb>_<date>_<hash>` batch id parsing; returns `""`  when unresolvable
- `select_cached_tracking_record(cache, tracking_no)` — AWB-keyed lookup with fallback sequence: exact match → legacy flat record → single-entry fallback → `{}` (ambiguous, caller keeps its `audit.tracking` fallback)

Commit SHA `a743e7b8` named. PR #1052 named. Recovery event described specifically: pre-compaction edits made in `C:\PZ-verify` directly in detached HEAD `@66f6039a` rather than the assigned worktree; diagnosed on resume; patch-relocated with sha256 parity verification and base blob identity check before staging. All four changed files named. Test isolation numbers: CLEAN baseline 19 failed / 569 passed → WITH change 19 failed / 587 passed; delta = +18 new passing, 0 new failures.

**Coverage (5):**

Both silent-failure sites are fixed. Scope discipline is evidenced by the explicit "these two read paths ONLY; do NOT touch the in-flight PR #1043 tracking work" constraint — and confirmed by PR #1052 touching exactly 4 files with no overlap with PR #1043's file set. Helper extraction serves coverage by ensuring the AWB-resolution and inner-record-selection logic is not duplicated at each site (preventing future drift).

Edge-case coverage across the 18 tests:
- AWB-keyed direct hit
- Regression pin demonstrating the OLD buggy read path returns `""` while the new path returns the correct status (test_outer_dict_has_no_top_level_status)
- Legacy flat cache record (where the top level IS the record — backward compat)
- Single-entry fallback (no AWB known but only one record present)
- Ambiguous multi-entry + no AWB → `{}` (non-crash boundary)
- AWB derived from batch ID only (no `audit.tracking_no`)
- `not_found` status correctly propagates as `tracking_404_nonblocking`
- No-cache fallback to `audit.tracking` field (regression guard for pre-cache batches)
- Both sites tested end-to-end with real function calls

GATE-2 compliance verified (2 open impl PRs vs. limit 3). Memory files updated: `project-tracking-cache-inner-record-pr1052.md` created, MEMORY.md pointer added. No git stash used (concurrent-session rule honored). Explicit-path staging (no `-A`). PR body via `--body-file` to prevent the `C:\PZ` guard false-positive.

**Severity (4):**

The fix is treated as a production bug fix requiring a PR, tests, and operator merge — correct for a persistent silent failure. No emergency bypass requested (appropriate: the bug is a silent readout error, not data corruption or a security exposure). Scope restrained to the two read paths only (no inflation into a broader tracking rewrite). No false urgency injected. The GATE-4 salvage classification (appropriate for a diagnosed production silent failure) is honored by the PR-with-tests approach rather than a quick inline patch with no tests.

One-point deduction: the task narrative does not explicitly label a severity tier (HIGH / MEDIUM / CRITICAL). The correct implicit treatment is MEDIUM — production silent failure affecting operator diagnostic visibility with no data integrity or security consequence. The calibration is correct as evidenced by the treatment, but the absence of an explicit label makes per-item calibration less independently verifiable. A reviewer agent would have been expected to label severity explicitly; for an implementer, the treatment pattern serves as the proxy signal.

**Actionability (5):**

All stated deliverables are present and independently verifiable:

- Two read sites fixed at named function:line locations (`action_diagnostics` in routes_dashboard, `normalize_batch_state` in batch_state_normalizer)
- Two shared helpers published at tracking_service lines 245–292 for reuse by any future reader of the cache
- Legacy fallback and single-entry fallback handled so old batch folders without AWB-keyed cache files continue to work
- 18 tests pinning the corrected behavior across both helpers and both end-to-end read sites
- Pre-existing failure register (19 failures by ID) captured before staging — provides an objective baseline against which operator can confirm no new failures were introduced
- GATE-2 verified (2/3 open impl PRs)
- Memory pointer created for future-session recovery
- Operator boundary correctly respected: no self-merge, no self-deploy, no signing-key bypass

No finding or edge case is left with a "noted" non-disposition. The `--body-file` workaround for the C:\PZ literal guard and the explicit-path staging both reflect attention to governance detail that prevents downstream audit confusion.

**Substitution (5):**

Single-agent task. GATE 5 is not applicable. Score 5 = N/A, correctly handled.

**Evidence quality (5):**

Root cause confirmed by code inspection rather than assertion: reading `_save_cache` (the write path) proved the AWB-keyed format before the fix was written. This is the correct methodology — verify the wire format at the source, not by inferring from the symptom.

Independently verifiable artifacts:
- Test file `test_tracking_cache_inner_record.py` contains test_outer_dict_has_no_top_level_status which demonstrates the old buggy read: `cache.get("status", "") == ""` — this is an executable regression proof, not a narrative claim
- Helper function `select_cached_tracking_record` has directly testable boundary behaviors (ambiguous multi-entry returns `{}`, single-entry falls back, legacy flat record detected via key presence check for `"status"` or `"tracking_no"` at top level)
- Isolation methodology: two separate runs (clean baseline vs. with-change) reported with specific counts (19/569 → 19/587); delta arithmetic is exact and correct
- sha256 parity check on relocated patches gives an independent confirmation that the worktree-recovered files are identical to what the pre-compaction session produced
- PR #1052 commit message (full mechanism narrative) is a public artifact on GitHub confirming the commit and its content

No outcome-stated claims without verifiable backing. Every behavioral assertion maps to a test or a code inspection with a line reference.

**Environment honesty (5):**

Full disclosure at three levels:

1. **Nominal path:** Worktree `C:\PZ-verify\.claude\worktrees\nifty-williamson-a68fec`, branch `fix/tracking-cache-inner-record`, commit SHA `a743e7b8` — all disclosed and independently verified (git log confirms SHA, PR view confirms branch name).

2. **Incident disclosure:** The pre-compaction session made the edits in `C:\PZ-verify` directly (detached HEAD `@66f6039a`) instead of the assigned worktree. This is an instance of the wrong-worktree-path failure class this dimension is designed to catch — and the agent caught and disclosed it explicitly rather than silently leaving the work on the wrong tree.

3. **Correction evidence:** Base blobs verified identical before patch application (worktree base matched `C:\PZ-verify` base for all four files); sha256 parity check after patch application confirmed the relocated files are byte-identical to the pre-compaction edits; `C:\PZ-verify` restored to clean (pre-existing untracked files — wdt-series, vat-mode, pr1039 reports — left undisturbed). The correction methodology is verifiable: the parity check result is stated, and the worktree commit (`a743e7b8`) can be inspected to confirm the content matches the described fix.

The wrong-path incident was self-detected, fully disclosed, and corrected with documented evidence. This is the strongest possible Environment honesty signal — the agent actively prevented the path-drift failure class rather than allowing it to pass undetected.

---

## 2. Weak-verdict warnings

No agent scored NEEDS-TUNING (15-21) or UNRELIABLE (7-14). No formal weak-verdict warnings required. No new GATE 4 salvage dispositions triggered by this campaign's scored entities.

**Quality signal (informational — not a weak-verdict warning):**

The single one-point deduction (Severity 4/5) reflects the absence of explicit severity labels in a single-agent implementation task rather than a calibration error. The actual treatment pattern is correctly calibrated. This is a standing structural characteristic of single-agent implementation scorecards, not a tuning signal.

---

## 3. Repeated failure hints

**5 most recent prior campaign scorecards reviewed (excluding self-eval files):**

1. **2026-07-31** `2026-07-31-pr1039-rollback-provenance.md` — 3 agents: implementation-orchestrator EXEMPLARY (30), reviewer-challenge EXEMPLARY (31), security-permissions ACCEPTABLE (25).
2. **2026-07-30** `2026-07-30-worktree-governance-cleanup.md` — 1 entity: orchestrator EXEMPLARY (31).
3. **2026-07-30** `2026-07-30-pr1041-pr1040-deploy-gate.md` — 7 deploy agents: 6 EXEMPLARY, 1 ACCEPTABLE (deploy-security-reviewer 27).
4. **2026-07-30** `2026-07-30-c7903686-wfirma-breaker-deploy-closure.md` — multi-phase deploy campaign.
5. **2026-07-28** `2026-07-28-advisory-service-id-draft-fallback.md` — 2 agents: security-write-action-reviewer ACCEPTABLE (27), reviewer-challenge EXEMPLARY (31).

**orchestrator/implementation-orchestrator appearances in the prior 5-campaign window:**
- 2026-07-31: implementation-orchestrator EXEMPLARY (30)
- 2026-07-30: orchestrator EXEMPLARY (31)
- No NEEDS-TUNING or UNRELIABLE appearances. No REPEATED-WEAK flag triggered.

**No new REPEATED-WEAK patterns from this campaign.** The orchestrator continues to score in the EXEMPLARY range.

**Carried REPEATED-WEAK flags (unchanged from prior scorecards — agents not present in this campaign):**

`REPEATED-WEAK: agent frontend-flow-reviewer — GATE 4 ISSUE disposition first recorded in 2026-06-21-freight-authority-blocker-repair.md (agent-tuning tag). Now 10+ consecutive scorecard cycles without operator confirmation.`

This is now the 5th consecutive scorecard since self-eval-2026-07-28.md without resolution. The GATE 4 obligation is: SCHEDULED (name a specific session), ISSUE (confirm the GitHub issue was filed), or REJECTED (explicit operator reasoning in PROJECT_STATE.md DECISIONS). "Recommendation noted" is not valid. Frontend-flow-reviewer does not appear in this campaign (backend-only fix, no UI surface). Flag carries forward.

`REPEATED-WEAK: agent backend-safety-reviewer — Issue #694 open. Per 2026-07-31-pr1039-rollback-provenance scorecard: 2026-07-17 produced a positive data point (EXEMPLARY 30, Evidence 4/5). Awaiting one further clean severity-calibration run before closing the issue. Agent not present in this campaign.`

---

## 4. GATE 4 disposition

No NEEDS-TUNING or UNRELIABLE verdicts produced by this scorecard. No new mandatory GATE 4 salvage dispositions created by the campaign's scored entities.

**Existing GATE 4 open items (carried forward unchanged):**
- `frontend-flow-reviewer` REPEATED-WEAK — ISSUE (agent-tuning tag; operator confirmation overdue 10+ consecutive scorecard cycles since 2026-06-21). Must receive one of: SCHEDULED (named session), ISSUE (confirmed filed), REJECTED (explicit reasoning in PROJECT_STATE.md DECISIONS).
- `backend-safety-reviewer` REPEATED-WEAK — Issue #694 (open; awaiting one additional clean severity-calibration appearance).

---

## 5. Self-evaluation check (RULE 5 — calendar-driven cadence)

**Trigger assessment:**
- Most recent self-eval file: `self-eval-2026-07-28.md` (dated 2026-07-28)
- Today: 2026-07-31
- Calendar days elapsed: 3 days — does NOT exceed the 7-day threshold
- SELF-DEGRADATION flag in `self-eval-2026-07-28.md`: **NO SELF-DEGRADATION DETECTED** (self-score 31/35 EXEMPLARY; all dimensions stable or improved)
- Counter trigger: not applicable (no active SELF-DEGRADATION flag)

**Self-evaluation: SKIPPED.** This is scorecard run 5 since `self-eval-2026-07-28.md`. Calendar trigger fires on or after 2026-08-04.
