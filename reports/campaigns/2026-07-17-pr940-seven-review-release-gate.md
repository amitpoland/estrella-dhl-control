# PR #940 — Seven-Reviewer Release Gate @ 4c28f28f (2026-07-17)

## ✅ DEPLOYED TO PRODUCTION (2026-07-18, operator-reported) — deployed SHA=4676057
Operator deployed the merged squash to production (PZService, NSSM, port 47213) and reported the
post-deploy state (agent recorded it; agent did not perform or independently verify the deploy — the
standing no-`C:\PZ`/no-prod-access constraint remained in force for this session):
- **PZService running; application startup complete; deployed SHA = `4676057280e99e7c6774164b8c3a5bf9ecce1933`** (== merged main).
- **Operator smoke GREEN:** transport/CMR page loads · packing list renders · AWB modal opens ·
  legacy-rebook confirmation appears · **no new application errors**.
- **Remaining for Production Complete (Business Feature Completeness Standard):**
  (1) the leak-fix's own production correctness check — real production draft/booking shows no
  stale/cross-client carrier row (follow-up **`task_b76ee829`**, now running in its own session); this
  is the substantive GATE-6 item the smoke above does not by itself prove. (2) Business Owner sign-off
  (requirement 7). Deploy-time follow-up **`task_8284e722`** (carrier floor 584→596) also applies here.
- **Rollback:** `git revert 4676057280e99e7c6774164b8c3a5bf9ecce1933`.

**Operator lifecycle ruling (2026-07-18, ratified) — updated with validation result:**
- **Deployment Status: DEPLOYED ✅** (deploy + production smoke passed)
- **Production Validation: `task_b76ee829` = ✅ PASS** (no cross-client leak on real production data);
  **remaining: Business Owner / UAT sign-off** (human step).
- **Production Complete: PENDING** — gated only on the Business Owner/UAT sign-off now.

### `task_b76ee829` — production carrier-row no-leak validation: ✅ PASS (2026-07-18)
Read-only validation on the deployed `4676057` build (evidence:
`reports/inspection/2026-07-18-pr940-prod-noleak-validation.md`). Real deployed resolver
(`get_shipment_for_draft`) run against a **read-only SQLite-backup snapshot** of the production DBs
(`C:\PZ\storage\carrier\carrier_shipments.db` + `proforma_links.db`) — **zero production writes**
(prod file verified afterwards: still no `client_ref` column, 23 rows, mtime `Jul 15`). For **all 4**
real multi-client production batches (3–10 clients: `SHIPMENT_1003835895` / `_6769309142` /
`_8341809162` / `_9158478722`): every client draft resolves **honest-missing (None)** — never another
client's row — while the OLD batch-latest path would have leaked one AWB to every draft (e.g.
`4839461152` → all 10 of `_6769309142`). Legacy-rebook confirmation source (`get_legacy_shipment`)
present for every batch → gate fires; confirm→Cancel zero-write already proven in review at this exact
SHA. **Scope note:** existing prod rows predate `client_ref` (legacy/NULL), so the fix currently shows
as honest-missing (drafts that previously displayed a leaked AWB now correctly show none); per-client
positive resolution applies to new post-deploy bookings (covered by tests + review env).

No further engineering action is required for the deployment itself unless a follow-up validation task
reports an issue. The remaining step (Business Owner/UAT sign-off) is a human action, presented below.

---

## ✅ MERGED & VERIFIED (2026-07-17T22:27:37Z) — status=MERGED_VERIFIED
- **Squash merge SHA / new origin/main:** `4676057280e99e7c6774164b8c3a5bf9ecce1933`
- **Merged by:** operator (operator-only; agent `gh pr merge` is fail-closed by pz-deploy-guard).
- **PR #940:** closed, merged=true. Original head `779c1b5f`; squash parent `74a354a4` (#941).
- **Merged-main verification (C:\PZ-main @ 4676057):** `git switch main` + `reset --hard origin/main`
  → HEAD=4676057, `git status` clean, `git diff --check` CLEAN. Squash = **23 files**, includes
  `service/tests/test_carrier_shipment_client_scope.py`, **no** review-bootstrap additions, all **3
  anti-leak tests present**.
- **Tests on merged main:** client-scope module **15**; focused-repair + legacy-rebook +
  transport/document **95**; golden **160/160**; carrier **930 pass / 17 same pre-existing env
  failures / 0 new** (930 vs the branch's 929 = merged main additionally includes #941 + #939 — an
  additive difference, not a regression). The 3 anti-leak tests (multi-client→404, single-client
  control→200 w/ AWB-LEGACY, `_batch_not_multi_client` unit pin) present + PASS.
- **deployment_performed: false.** No `C:\PZ` sync, no baseline change, no production-data access, no
  branch deletion. **Rollback:** `git revert 4676057280e99e7c6774164b8c3a5bf9ecce1933` (anchor 13d442e9).

### Fresh post-merge re-verification (2026-07-18, live re-run on `C:\PZ-main` @ 4676057, clean tree = merged commit)
Re-executed on operator re-request (`TRANSPORT_M1_POST_MERGE_VERIFICATION_REQUIRED`), evidence not asserted from summary:
- `origin/main` read from the source-of-truth `C:\PZ-verify` tree = **4676057…**; `C:\PZ-main` HEAD = same,
  branch `main`, `status --short` empty, `diff --check` **CLEAN**. Squash parent `74a354a4` (#941), **23 files**,
  `test_carrier_shipment_client_scope.py` present, **no** review-bootstrap files.
- **client-scope module: 15 passed**; the 3 anti-leak tests present + green —
  `test_route_no_client_ref_multi_client_proforma_denies_legacy_fallback` (→404),
  `test_route_no_client_ref_single_client_proforma_resolves_legacy` (→200 AWB-LEGACY),
  `test_batch_not_multi_client_reads_proforma_db` (unit).
- **focused 95** reconciled exactly = weight_override 13 + cmr_transport_authority 20 + awb_legacy_rebook_confirm 51
  + cmr_number 6 + v2_packing_list_sr_origin 5 (broader 8-file superset ran 141 pass / 0 fail).
- **golden 160/160** (unittest runner; `#940` touches no root engine file, so golden is definitionally unaffected).
- **Metered carrier suite `tests/test_carrier_*.py` (deploy-gate metric, floor 584): 599 passed / 1 skipped / 4 failed / 0 err.**
  The 4 fails are the documented env-conditional `test_carrier_config_defaults` rows (host has DHL creds set) —
  proven-environmental, **0 new**; **floor 584 met** (599 = 584 + #940's 15 client-scope tests). This is the
  authoritative subset behind the earlier broad "930 pass / 17 env" figure (that superset's other 13 fails are
  pre-existing non-carrier files — dashboard_pipeline_summary / dhl_proactive_dispatch / e2e_carrier_shadow_create /
  master_data_hard_rules — outside the metered pattern and outside #940 scope). **0 failures introduced by #940.**
- Post-merge follow-ups filed as separate task records (not implemented):
  - `task_8284e722` — carrier required-pass floor 584→596 (test-baseline.md)
  - `task_b76ee829` — production carrier-row inspection at the #940 deploy gate
  - `task_996e374e` — extract `_batch_not_multi_client` into a shared carrier service
  - `task_14dc1752` — `purchase_invoice_no` rendering decision (render vs formally defer)
  - `task_65841510` — create_shipment base-vs-privileged auth (pre-existing; already tracked)
  - `task_799d6086` — X-Operator attribution on carrier bookings (system-wide, pre-existing)
  - `task_2450e646` — extend CMR country-name table coverage (JP/US/AE, real ship set)

---

**FINAL VERDICT (2026-07-18): TRANSPORT_M1_READY_FOR_OPERATOR_MERGE @ `779c1b5f`.**
The 7-reviewer gate @4c28f28f returned 7/7 ZERO BLOCKERS + ONE REQUIRED-BEFORE-MERGE (test-coverage
gap, not a code defect). Operator authorized ONE test-only commit → `779c1b5f` closes it; a 3-reviewer
delta re-gate returned all ZERO BLOCKERS + ZERO REQUIRED-BEFORE-MERGE. PR #940 marked READY (draft=false).

## Gap-closure commit `779c1b5f` (test-only; ff 4c28f28f..779c1b5f)
Added to `service/tests/test_carrier_shipment_client_scope.py` (no app change; guard code unchanged):
route multi-client→404 + single-client causation-control→200 (proves the proforma guard, not
carrier-side logic) + direct unit pin on `_batch_not_multi_client`. Seed via canonical
`auto_create_draft_from_sales_packing` (no raw SQL). Tests @779c1b5f: golden 160/160, client-scope 15,
carrier 929 pass/17 pre-existing (0 new), git diff --check clean, smoke skipped (test-only).
**Delta re-gate:** test-evidence / backend-safety / reviewer-challenge — all ZERO BLOCKERS + ZERO
REQUIRED-BEFORE-MERGE (the test-evidence reviewer who raised the gap confirmed closure). Registry
expected_head→779c1b5f, lock released.

---
_Original gate record below (@4c28f28f)._

**Original verdict: TRANSPORT_M1_HOLD** — 7/7 reviewers ZERO BLOCKERS, but ONE confirmed
REQUIRED-BEFORE-MERGE (test-coverage gap; not a code defect). [Now CLOSED by 779c1b5f — see above.]

## Frozen candidate
- Head: `4c28f28f947ff86fb6213c8fd02657a91f102fac` (immutable for all reviews).
- Branch: fix/proforma-multidraft-transport-docs; tree CLEAN; PR #940 OPEN/draft/MERGEABLE.
- Registry: expected_head=last_verified=4c28f28f, lock=null.
- Diff = **23 files** (12 source + 1 ADR + 10 tests); **no review-bootstrap files leaked**.

## #941 overlap (main = 74a354a4)
#941 = 5 additive bootstrap files (launch.json, gate6-review-environment.md, review_launch.py,
review_seed.py, test_review_bootstrap.py). **ZERO file overlap**, no semantic overlap; GitHub
MERGEABLE (clean 3-way). **Preserve exact head 4c28f28f — no rebase** (both operator conditions met).

## Seven review outcomes (all read-only; none edited files)
| # | Reviewer | Blockers | Result |
|---|---|---|---|
| 1 | backend-safety-reviewer | 0 | NO BLOCKERS — 5 safety props PASS (isolation 3-layer, tare after-snapshot @2987, no wFirma/DHL write, idempotency, param SQL) |
| 2 | security-write-action-reviewer | 0 | NO BLOCKERS — legacy warning before booking, Cancel=no write, no auth downgrade, empty-allowlist raises before HTTP, no cred exposure |
| 3 | reviewer-challenge | 0 | PASS — 7/7 challenges confirm; hardcoded India + Hallmark cert removed; single authorities intact |
| 4 | frontend-flow-reviewer | 0 | NO BLOCKERS — invoiceProjection authority, CMR India (single _CMR_COUNTRY_NAMES), honest-null, Lesson M OK |
| 5 | architecture authority (system-architect, GATE-5 sub) | 0 | NO BLOCKERS — one shipment resolver / idempotency / CMR number / country-name / invoiceProjection; Lesson-N separation |
| 6 | test-evidence (test-coverage-reviewer, GATE-5 sub) | 0 | **1 REQUIRED-BEFORE-MERGE** (see below) + post-merge test-hardening items |
| 7 | deploy-readiness (deploy-release-manager, GATE-5 sub) | 0 | CLEAR — forbidden-paths clean, additive schema, Lesson J N/A, Lesson G headers, rollback + sync plan |

GATE-5 substitutions disclosed (reviewers 5–7): no exact-named agents exist for architecture-authority /
test-evidence / deploy-readiness; substitutes cover the equivalent scope.

## The ONE REQUIRED-BEFORE-MERGE item (CONFIRMED by coordinator)
**`_batch_not_multi_client` (routes_carrier_actions.py:110) has no route-level or unit test of its
multi-client-detection.** The route fixture `_client_for` (test_carrier_shipment_client_scope.py:177)
overrides `_get_shipment_db_path` but NOT `settings.storage_root`, so the guard reads a non-existent
`proforma_links.db` and returns permissive; the route tests pass via carrier-side row logic, not the
proforma guard. Uncovered scenario: `GET /carrier/{batch}/shipment` with NO client_ref on a
multi-client proforma batch + a single legacy NULL-client_ref carrier row → must be 404. The guard's
CODE is verified correct by 4 reviewers; the RESOLVER (get_shipment_for_draft) is fully unit-tested
given the flag — but the FLAG COMPUTATION (proforma-DB multi-client read) is untested. For the PR's
primary anti-leak guard this is a genuine required-before-merge coverage gap.
**Remedy (test-only, small):** add a route test that monkeypatches `settings.storage_root` to a dir
with a `proforma_links.db` seeded with 2 client drafts for the batch + a single legacy carrier row,
GET without client_ref → assert 404. Not addable in this frozen-head review-only task (would move the
head off 4c28f28f). Real-world exposure is low (the V2 frontend always sends client_ref).

## Consolidated post-merge / deploy follow-ups (no reviewer proved a direct regression)
Pre-classified (operator list): carrier floor 584→596; production carrier-row inspection at deploy
(`_carrier_shipment_db_path` fix surfaces previously-invisible rows); private `_batch_not_multi_client`
import → extract to a shared service; `purchase_invoice_no` computed-not-rendered; task_65841510
(create_shipment/do-not-use base-vs-privileged auth, pre-existing on main); X-Operator attribution.
New (surfaced by reviewers, all POST-MERGE): non-atomic audit.json advisory write + CN23 zero-line
placeholder (backend-safety); stale tracking_ref comment + extend 24-country CMR table for JP/US/AE
(reviewer-challenge); tracking_url dead field (architecture); successive-override + source-grep-only
test hardening (test-evidence); §3 hardcoded-hex in the print-preview zone + missing modal-× testids
(frontend, pre-existing print-doc style).

## Test evidence @4c28f28f (from the prior verification round; reviewers corroborated the pins)
Root golden 160/160; focused-repair + legacy-rebook + transport/document 107; carrier 926 pass / 17
pre-existing-env (identical to pre-repair tip, 0 new); pre-commit smoke 63. Legacy confirm-and-cancel
browser sequence: panel VISIBLE before booking; Cancel → 0 POST /carrier/shipment, carrier DB
byte-identical (sha 5552c22b), no DHL egress.

## Disposition
#940 STAYS DRAFT. To clear to READY: operator authorizes the single test-only commit above (moving the
head to a new SHA → a fast re-gate of the delta), OR explicitly rules the code-verified guard's coverage
gap acceptable-as-post-merge and instructs the flip to ready. No merge/deploy/baseline change performed.
