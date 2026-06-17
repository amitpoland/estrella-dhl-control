# PR #640 — Pre-Merge Validation Checklist

**Purpose:** validation gate to run BEFORE merging PR #640 and before the 7-agent
deploy gate. Each of the four categories below carries an explicit PASS/FAIL with
supporting evidence — no subjective judgment.

**Scope boundary (hard):** every check applies to the **PR branch
`fix/invoice-image-only-lineitem-extraction`** only. This document validates; it
does **not** merge or commit to `main`. Merge and prod write are operator-only.

| Field | Value |
|---|---|
| PR | #640 — advisory image-only invoice extraction (FOB + line items + supplier) — PR-1 |
| Branch / HEAD | `fix/invoice-image-only-lineitem-extraction` @ `8e8f9ba` (code `f6c7ec2`) |
| Base | `origin/main` = `4652292` (#632 `c284902` + #633 `4652292` merged, git-verified) |
| Validation run | 2026-06-17 |
| Overall gate verdict | ⬜ MERGE-APPROVED / ⬜ BLOCKED (reviewer sign-off §5) |

---

## Category 1 — Unit test results

**Pass criteria:** PZ ≥ 221 passing; Carrier ≥ 412 passing; vision guards all
green; no NEW failure attributable to this diff. Fail on any regression
introduced by the branch.

**Evidence (run 2026-06-17 from `service/`, branch HEAD `8e8f9ba`):**

| Suite | Command | Result | Status |
|---|---|---|---|
| PZ baseline | `pytest tests/test_pz_*.py -q` | **221 passed, 1 failed** | ⚠️ PASS-WITH-KNOWN |
| Carrier baseline | `pytest tests/test_carrier_*.py -q` | **420 passed** (≥ 412) | ✅ PASS |
| vision_invoice guards | `pytest tests/test_vision_invoice_negative_scope.py tests/test_vision_invoice_extraction.py -q` | **22 passed** | ✅ PASS |

**The 1 PZ failure — proven pre-existing, NOT a regression:**
- Test: `tests/test_pz_batch.py::test_save_json_csv_ui_round_trip`
- Symptom: `AssertionError 8 == 4` — 4 real CSV rows + 4 `\r\n`-induced blank lines (Windows CRLF artifact).
- Proof of pre-existence: identical `8 == 4` failure reproduces on a clean `origin/main` worktree (verified prior session via throwaway `git worktree add origin/main`). This diff touches none of `test_pz_batch.py` / `batch_builder` / CSV-writing code.
- Classification: environmental CRLF artifact, pre-existing, out of scope for #640.

**Category 1 verdict:** ✅ PASS — _221 PZ passing meets the 221 baseline; 420 carrier ≥ 412; 22 vision guards green; the single PZ failure is a pre-existing CRLF artifact, not introduced by #640._

---

## Category 2 — Blocker analysis

**Pass criteria:** every known blocker is classified and its effect on *this PR's
mergeability* is stated correctly. Fail only if a blocker actually blocks merge of #640.

| # | Blocker | Classification | Blocks MERGE of #640? | Evidence |
|---|---|---|---|---|
| 2a | `vision_invoice` is proposal-only | **Informational — not actionable.** It is the intended end-state of PR-1, not a defect. | **NO** | ADR-031 layer-1 definition; `operator_confirmed=false` by design |
| 2b | PZ / wFirma blocked pending PR-2 operator-confirmation workflow | **By-design dependency on the *shipment*, not the PR.** PZ/wFirma read layer 3 only; layer 3 stays empty for image-only shipments until PR-2. | **NO** | `pr640-deployment-readiness-state.md` §1; runbook §1 |

**Key finding (decisive):**
- **PR #640 is mergeable right now.** `mergeable=MERGEABLE`, clean base on `4652292`, reviewer PASS, baseline green.
- **What is blocked is the *shipment*** — PZ/wFirma goods-receipt for AWB 2315714531 — **not the PR.** The two are different objects; conflating them inverts the dependency.
- **Dependency direction:** PR-2 depends on **#640 landing first**, not vice-versa. Merging and deploying #640 is a *prerequisite* for building PR-2 (proposals must exist in production before a confirm-and-inject workflow has anything to act on). #640 does not wait on PR-2 for anything.

**Category 2 verdict:** ✅ PASS — _both blockers are downstream/by-design; neither is a precondition for merging #640; the dependency runs #640 → PR-2._

---

## Category 3 — Authority and ownership verification

**Pass criteria:** the PR respects the ADR-031 authority layers and the
established ownership boundaries (who may write what). Fail if any authority
boundary is crossed or any ownership rule is violated.

| # | Authority / ownership rule | Evidence artifact | Status |
|---|---|---|---|
| 3.1 | `vision_invoice` is layer-1 PROPOSAL only; cannot drive PZ/wFirma/landed-cost/exports/warehouse unless `operator_confirmed==true` | ADR-031 enforcement rule + gate table | ✅ PASS |
| 3.2 | Sole writer of the proposal is `vision_extractor`; `operator_confirmed` has NO writer yet (PR-2 endpoint will be the only one) | code `f6c7ec2`; ADR-031 owner column | ✅ PASS |
| 3.3 | Engine never reads the proposal (`process_batch` only in comments in `vision_extractor.py`) | source review `f6c7ec2` | ✅ PASS |
| 3.4 | Sticky confirmation + TOCTOU re-read before atomic write; `vision_invoice` in `audit_merge.PRESERVED_KEYS` | code `f6c7ec2`; `audit_merge.PRESERVED_KEYS` | ✅ PASS |
| 3.5 | Blocker-status authority lives in `PROJECT_STATE.md`, owned by `flow-context-keeper` (CLAUDE.md RULE 3) — this PR adds no competing authority | PROJECT_STATE FACTS 'PR #640' block | ✅ PASS |
| 3.6 | Merge / prod write are operator-only; this checklist does not perform either | this doc scope boundary | ✅ PASS |

**Category 3 verdict:** ✅ PASS — _authority layers and ownership boundaries are intact; the PR introduces a proposal layer with no write authority into accounting/customs and no competing state owner._

---

## Category 4 — Integration boundary checks

**Pass criteria:** the proposal layer is provably isolated from the customs and
accounting ladders — the customs/CIF state for AWB 2315714531 (CIF USD 732,
RESOLVED) is byte-identical with and without the `vision_invoice` block, and the
two ladders never cross. Fail if the proposal perturbs any customs/accounting value.

| # | Integration boundary | Evidence artifact | Status |
|---|---|---|---|
| 4.1 | `resolve_cif` ignores `vision_invoice` (UNKNOWN stays UNKNOWN; RESOLVED 732 stays 732) | `test_vision_invoice_negative_scope.py::test_resolve_cif_*` | ✅ PASS |
| 4.2 | `build_clearance_decision` CIF value/source invariant to the block | `::test_build_clearance_decision_ignores_vision_invoice` | ✅ PASS |
| 4.3 | Poison-block invariance: a `99999` CIF-shaped value in the proposal never perturbs customs output | `::_POISON_VISION_INVOICE` assertions | ✅ PASS |
| 4.4 | Static source contracts: `cif_resolver.py` / `clearance_decision.py` / `active_shipment_monitor.py` never name `vision_invoice` | static-contract tests (3) | ✅ PASS |
| 4.5 | Vision **invoice** layer (#640) writes ONLY `vision_invoice` — never CIF keys / `invoice_totals` / `rows` / `customs_declaration`; separate ladder from the vision **CIF** fallback (#632/#633) | code review `f6c7ec2`; ADR-031 corollary 1 | ✅ PASS |
| 4.6 | AWB 2315714531 customs/CIF (732) compatible with the PR — no adjustment needed | combination of 4.1–4.5 | ✅ PASS |

**Forward note for PR-2 (not a PR-1 blocker):** the engine-injection step must
read layer 3, or read layer 1 strictly behind `operator_confirmed` — never
"whichever `fob_usd` exists" (duplicate-authority risk, ADR-031 Risks).

**Category 4 verdict:** ✅ PASS — _customs and accounting ladders are provably isolated from the proposal; AWB 2315714531 (CIF 732) is unaffected; no state-consistency adjustment required._

---

## 5. Reviewer sign-off

| Category | Required before merge | Done |
|---|---|---|
| 1 — Unit test results | PASS (known CRLF failure acknowledged) | ⬜ |
| 2 — Blocker analysis | PASS (non-blocking) | ⬜ |
| 3 — Authority and ownership | PASS | ⬜ |
| 4 — Integration boundary | PASS | ⬜ |
| GATE 1 (reviewer-challenge PASS, baseline green, forbidden-files clean) | confirmed | ⬜ |
| GATE 2 open-PR count has a slot | `gh pr list` at merge time | ⬜ |
| Re-snapshot branch HEAD == `8e8f9ba` (or newer, re-reviewed) | confirmed | ⬜ |

**Findings / issues discovered during validation:** _(reviewer fills in)_

**Reviewer:** ______________________  **Date:** ____________  **Verdict:** ⬜ MERGE-APPROVED / ⬜ BLOCKED

---

## Conclusion

All four categories PASS (Category 1 with one acknowledged, proven pre-existing
CRLF failure that is not a regression). **Neither blocker gates the merge.**

> Scope reminder: approval here authorizes proceeding to the **7-agent deploy
> gate**. It does not authorize a merge to `main` or a prod write — both are
> operator-only actions taken outside this checklist.
