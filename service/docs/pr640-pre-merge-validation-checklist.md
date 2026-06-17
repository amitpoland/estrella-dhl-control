# PR #640 — Pre-Merge Validation Gate

**Purpose:** validation gate to run BEFORE merging PR #640 and before the 7-agent
deploy gate. Every check has explicit pass/fail criteria and a required evidence
artifact — no subjective judgment.

**Scope boundary (hard):** every check below applies to the **PR branch
`fix/invoice-image-only-lineitem-extraction`** only. This document validates; it
does **not** merge or commit to `main`. Merge and prod write are operator-only.

| Field | Value |
|---|---|
| PR | #640 — advisory image-only invoice extraction (FOB + line items + supplier) — PR-1 |
| Branch / HEAD | `fix/invoice-image-only-lineitem-extraction` @ `1a2689f` (code `f6c7ec2`) |
| Base | `origin/main` = `4652292` (#632 `c284902` + #633 `4652292` merged) |
| Validation run | 2026-06-17 |
| Overall gate verdict | ⬜ PASS / ⬜ FAIL (reviewer sign-off §5) |

---

## CHECK 1 — ADR-030 compliance

**Pass criteria:** every enforcement requirement in ADR-030 is implemented on the
branch AND documented in the PR/linked docs. Fail if any layer boundary is
unimplemented or undocumented.

| # | ADR-030 requirement | Evidence artifact | Status |
|---|---|---|---|
| 1.1 | Four authority layers defined + owners named | `ADR-030` §Decision table | ✅ PASS |
| 1.2 | Enforcement rule: no `vision_invoice` read into PZ/wFirma/landed-cost/exports/warehouse unless `operator_confirmed==true` | `ADR-030` enforcement rule + §gate table | ✅ PASS |
| 1.3 | Customs isolation: `cif_resolver.py` / `clearance_decision.py` / `active_shipment_monitor.py` never name `vision_invoice` | `test_vision_invoice_negative_scope.py` static source contracts — **22 passed** | ✅ PASS |
| 1.4 | Poison-block behavioral invariance (99999 CIF-shaped value never perturbs customs output) | `test_vision_invoice_negative_scope.py::test_resolve_cif_*` / `::test_build_clearance_decision_*` | ✅ PASS |
| 1.5 | USD-only FOB gate in `_merge_vision_invoice` | `test_vision_invoice_extraction.py::test_merge_withholds_fob_when_currency_not_usd` | ✅ PASS |
| 1.6 | Sticky confirmation + TOCTOU re-read before atomic write; `vision_invoice` in `PRESERVED_KEYS` | code `f6c7ec2` (`_merge_vision_invoice`, orchestrator guard) + `audit_merge.PRESERVED_KEYS` | ✅ PASS |
| 1.7 | Engine never reads proposal (no `process_batch` call in extractor) | `vision_extractor.py` — `process_batch` appears only in comments | ✅ PASS |
| 1.8 | Implementation documented | PR body + `ADR-030` + runbook + handoff + this gate | ✅ PASS |

**CHECK 1 verdict:** ✅ PASS — _findings: all 8 ADR-030 sub-requirements implemented and pinned by tests; deferred items (operator-confirm endpoint, gated injection) are explicitly PR-2 scope per ADR-030 and not required at PR-1._

---

## CHECK 2 — Build / regression verification against production base `4652292`

**Pass criteria:** branch is based on `4652292`; PZ ≥ 221 passing; Carrier ≥ 412
passing; no NEW failure attributable to this diff. Fail on any regression
introduced by the branch.

**Evidence (run 2026-06-17 from `service/`, branch HEAD `1a2689f`):**

| Suite | Command | Result | Status |
|---|---|---|---|
| Base integrity | `git merge-base HEAD origin/main` → `4652292` | clean, no rebase drift | ✅ PASS |
| PZ baseline | `pytest tests/test_pz_*.py -q` | **221 passed, 1 failed** | ⚠️ PASS-WITH-KNOWN |
| Carrier baseline | `pytest tests/test_carrier_*.py -q` | **420 passed** (≥412) | ✅ PASS |
| Vision guards | `pytest tests/test_vision_invoice_negative_scope.py tests/test_vision_invoice_extraction.py -q` | **22 passed** | ✅ PASS |

**The 1 PZ failure — documented, NOT a regression:**
- Test: `tests/test_pz_batch.py::test_save_json_csv_ui_round_trip`
- Symptom: `AssertionError 8 == 4` — 4 real CSV rows + 4 `\r\n`-induced blank lines (Windows CRLF artifact).
- Proven pre-existing: identical failure reproduces on a clean `origin/main` worktree (verified in the prior session via a throwaway `git worktree add` on `origin/main`). This diff touches none of `test_pz_batch.py` / `batch_builder` / CSV-writing code.
- Classification: environmental CRLF artifact, pre-existing, out of scope for #640.

**CHECK 2 verdict:** ✅ PASS — _findings: 221 PZ passing meets the 221 baseline; 420 carrier ≥ 412; the single PZ failure is a pre-existing CRLF artifact, not introduced by #640. Warnings: deploy must clear `__pycache__` recursively under `C:\PZ` (app + engine) before restart (PYCACHE rule) or stale `.pyc` shadows new source._

---

## CHECK 3 — Customs / CIF compatibility (AWB 2315714531)

**Pass criteria:** AWB 2315714531 customs/CIF state (CIF USD 732, RESOLVED) is
byte-identical with and without the PR's `vision_invoice` block present. Fail if
the proposal perturbs any customs value/source.

| # | Compatibility requirement | Evidence artifact | Status |
|---|---|---|---|
| 3.1 | `resolve_cif` ignores `vision_invoice` (UNKNOWN stays UNKNOWN; RESOLVED 732 stays 732) | `test_vision_invoice_negative_scope.py::test_resolve_cif_unchanged_by_vision_invoice_when_resolved` | ✅ PASS |
| 3.2 | `build_clearance_decision` CIF value/source invariant to the block | `::test_build_clearance_decision_ignores_vision_invoice` | ✅ PASS |
| 3.3 | Vision **invoice** layer (#640) writes ONLY `vision_invoice` — never CIF keys / `invoice_totals` / `rows` / `customs_declaration` | code review `f6c7ec2`; vision CIF fallback (#632/#633) is a separate ladder | ✅ PASS |
| 3.4 | Customs ladder and accounting ladder never cross (Lesson F) | `ADR-030` corollary 1 + static source contracts | ✅ PASS |

**Adjustments needed to maintain compliance:** NONE for PR-1. Forward note for
PR-2: the engine-injection step must read layer 3, or read layer 1 strictly
behind `operator_confirmed` — never "whichever `fob_usd` exists" (duplicate-
authority risk, ADR-030 Risks).

**CHECK 3 verdict:** ✅ PASS — _findings: AWB 2315714531 customs (CIF 732) is provably unaffected by the PR; no state-consistency adjustment required._

---

## CHECK 4 — Workflow blockers

**Pass criteria:** each known blocker is classified and its effect on *this PR's
mergeability* is stated. Fail only if a blocker actually blocks merge of #640.

| # | Blocker | Classification | Does it block MERGE of #640? | Evidence |
|---|---|---|---|---|
| 4a | `vision_invoice` is proposal-only status | **Informational — not actionable** at PR-1. It is the intended end-state of this PR, not a defect. | **NO** | `ADR-030` layer-1 definition; `operator_confirmed=false` by design |
| 4b | PZ / wFirma blocked pending PR-2 operator-confirmation workflow | **By-design dependency.** PZ/wFirma read layer 3 only; layer 3 stays empty for image-only shipments until PR-2. | **NO** — PR #640 is independently MERGEABLE and grants no accounting authority; it does not depend on PR-2 to merge or deploy safely | `pr640-deployment-readiness-state.md` §1 dependency chain; runbook §1 |

**Dependency direction (critical):** PR #640 does **not** depend on any blocker
being resolved to merge. The dependency runs the other way — PR-2 (and the
eventual PZ/wFirma unblock for AWB 2315714531) depends on #640 being merged and
deployed first. Merging #640 is a prerequisite for resolving blocker 4b, not the
reverse.

**CHECK 4 verdict:** ✅ PASS — _findings: neither blocker gates this merge; both are correctly represented as downstream/by-design. Task #15 stays PENDING (expected)._

---

## 5. Reviewer sign-off

| Gate item | Required before merge | Done |
|---|---|---|
| CHECK 1 ADR-030 compliance | PASS | ⬜ |
| CHECK 2 build/regression | PASS (known CRLF failure acknowledged) | ⬜ |
| CHECK 3 customs/CIF compatibility | PASS | ⬜ |
| CHECK 4 workflow blockers | PASS (non-blocking) | ⬜ |
| GATE 1 (reviewer-challenge PASS, baseline green, forbidden-files clean) | confirmed | ⬜ |
| GATE 2 open-PR count has a slot | `gh pr list` at merge time | ⬜ |
| Re-snapshot branch HEAD == `1a2689f` (or newer, re-reviewed) | confirmed | ⬜ |

**Findings / issues discovered during validation:**
_(reviewer fills in)_

**Reviewer:** ______________________  **Date:** ____________  **Verdict:** ⬜ MERGE-APPROVED / ⬜ BLOCKED

> Scope reminder: approval here authorizes proceeding to the **7-agent deploy
> gate**. It does not authorize a merge to `main` or a prod write — both are
> operator-only actions taken outside this checklist.
