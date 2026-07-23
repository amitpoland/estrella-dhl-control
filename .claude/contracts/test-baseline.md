# Test Baseline — Deploy Pass Criteria

Single source of truth for required test counts.
Referenced by: `deploy_qa_reviewer.md`, `deploy_lead_coordinator.md`, `deploy.md`, `CLAUDE.md`.

---

## Current baseline

| Suite | File / pattern | Required pass count | Failure action |
|-------|---------------|---------------------|----------------|
| PZ regression | `tests/test_pz_*.py` | **258** | Unconditional deploy block |
| Carrier suite | `tests/test_carrier_*.py` | **604** | Unconditional deploy block |

Any test ERROR (not just FAILED) is also an unconditional block.
Any count below the required threshold is an unconditional block.

---

## Known-failing exclusions

The baseline is **not green** — it carries a small set of tracked, accepted reds. Any failure
listed here is accepted at gate time; any FAILED test NOT listed here, and any ERROR, is an
unconditional block.

| Test | Tracking | Reason |
|------|----------|--------|
| `test_carrier_config_defaults.py::test_carrier_live_allowlist_default_is_empty` | env: DHL creds set | ENVIRONMENTAL — asserts the *code default* of `carrier_live_allowlist`; fails only when `CARRIER_LIVE_ALLOWLIST` is set in the environment (as it is on any DHL-configured host incl. production `C:\PZ` and this review clone). PROVEN environmental: with DHL/carrier env vars cleared, `test_carrier_config_defaults.py` = 9/9 passed. Not a code regression. |
| `test_carrier_config_defaults.py::test_dhl_express_api_key_default_is_none` | env: DHL creds set | ENVIRONMENTAL — asserts `Settings().dhl_express_api_key is None`; `DHL_EXPRESS_API_KEY` is set in the deploy/review env → returns the live key. Passes with env cleared (see above). |
| `test_carrier_config_defaults.py::test_dhl_express_api_secret_default_is_none` | env: DHL creds set | ENVIRONMENTAL — asserts `Settings().dhl_express_api_secret is None`; `DHL_EXPRESS_API_SECRET` set in env. Passes with env cleared. |
| `test_carrier_config_defaults.py::test_dhl_express_account_number_default_is_none` | env: DHL creds set | ENVIRONMENTAL — asserts `Settings().dhl_express_account_number is None`; `DHL_EXPRESS_ACCOUNT_NUMBER` set in env. Passes with env cleared. |

The PZ metered suite (`tests/test_pz_*.py`) has **no documented failures** as of the #613 fix
(PR #1006). Required count bumped 257→258 (the +1 attributable to #613). Measured on current
`main`: **260 passed** — 2 additional `test_pz_*` tests were introduced by later PRs without a
floor bump; the floor is kept conservative below measured (Carrier convention), and that +2 drift
is flagged for a future reconciliation. Issue #802 (`test_ai_gateway_contract`) was likewise fixed
(PR #1000) and its stale exclusion removed; it is outside the metered PZ pattern, so no floor impact.

**Carrier env-conditional exclusions (4, reconciled 2026-07-09):** the four
`test_carrier_config_defaults.py` rows above assert the *code defaults are unset*; they fail on any
host where the DHL credentials are configured (the deploy target `C:\PZ` and this review clone both
are). They are NOT regressions — proven by a clean-env full-suite run (all `DHL_EXPRESS_*` +
`CARRIER_*` unset → **588 passed, 1 skipped, 0 failed, 0 errors**). With creds set (gate-host
reality) the carrier suite is **589 collected → 584 passed / 4 failed (these env rows) / 1 skipped,
0 errors**. The 584 required-pass floor is the creds-set worst case.

The former `box_types_endpoint_returns_correct_shape` ERROR exclusion was **removed 2026-07-09**: it
was not env-conditional but full-suite teardown contamination leaking from four stale carrier tests
broken by PR #824 (`test_carrier_live_adapter_gate.py` ×3 receiver-phone gate;
`test_carrier_awb_modal_fields.py::test_receiver_details_email_absent_*` empty-string→omit). With
those four fixed (test-only), `box_types` and `test_shipment_request_body_forwards_product_code` no
longer error (0 errors across 3 full-suite runs). The carrier suite now carries **no skips**:
`test_carrier_shipment_db.py::test_tracking_ref_not_in_schema` was `skip`-superseded in-source from
2026-07-09 and **deleted 2026-07-19** (see history row) — `tracking_ref` has been a persisted column
since PR #819, so the assertion was provably false rather than merely unproven. The surviving
AWB-exclusion invariant (live results are never inserted) is covered by
`test_carrier_shipment_db.py::test_live_result_insert_raises`, and the persisted-column rationale is
documented at `service/app/services/carrier/persistence/shipment_db.py:48`.

---

## Update protocol

When a new golden batch is committed or a new test is added:

1. Update the count in the table above.
2. Add a row to the History table below with date and reason.
3. The relevant test file AND this file must change in the same commit.
4. No count changes are needed in any referencing file — they all read from here.

---

## History

| Date | PZ required | Carrier required | Reason |
|------|-------------|------------------|--------|
| 2026-07-23 | 258 | 604 | PZ floor 257→258 (+1): Issue #613 (`test_pz_batch.py::test_save_json_csv_ui_round_trip`) FIXED and deployed by PR #1006 (`write_bytes` instead of `write_text` — Windows/py3.9 was doubling the csv `\r\n` into `\r\r\n`). Its known-failing exclusion row is removed per the update protocol. Also removed the stale Issue #802 exclusion (`test_ai_gateway_contract.py::test_call_returns_model_response_text`, fixed by PR #1000) — outside the metered PZ pattern, no floor impact. Both were merged without their same-commit baseline update; this row reconciles both. Fresh evidence on `main`: `tests/test_pz_*.py` **260 passed** (258 floor kept conservative below measured; +2 vs 258 is prior drift from later-PR test additions, flagged for reconciliation), root golden 160/160, Carrier 619 pass / 4 documented env fail. This file changed as a post-deploy follow-up (the fix PRs predated it). |
| 2026-07-19 | 257 | 604 | **No floor change — dead-test cleanup of the obsolete `tracking_ref` AWB-exclusion invariant (GATE-4 SCHEDULED disposition, operator-ratified 2026-07-19).** `tracking_ref` has been a persisted column since PR #819 (squash `ae6c73b9`, operator decision 2026-07-06 duplicate-AWB incident fix — idempotency replay returns the stored result with zero adapter calls), so both tests asserting `"tracking_ref" not in row` asserted a **provably false** invariant. Deleted: (1) `test_carrier_shipment_db.py::test_tracking_ref_not_in_schema` — carried `@pytest.mark.skip` since the 2026-07-09 reconciliation; a skip that can never be un-skipped is dead code. (2) `test_e2e_carrier_shadow_create.py::test_shipment_db_row_has_no_tracking_ref_column` — was **actively FAILING on `main` and undocumented** (not listed in any exclusion row); outside both metered patterns, so it never tripped a gate. **Floor stays 604: deleting a *skipped* test removes 0 passes.** Fresh creds-set measurement on this branch: carrier `tests/test_carrier_*.py` = **619 passed / 4 documented env fail (`test_carrier_config_defaults.py`) / 0 skipped / 0 errors** — pass count identical to the 2026-07-18 row's measured 619, with the 1 skip now gone; `test_e2e_carrier_shadow_create.py` 17/17 (was 16 pass + 1 fail). Surviving AWB-exclusion invariant `test_live_result_insert_raises` passes and is untouched. No production code changed. Test files + this file changed in the same commit per update protocol. |
| 2026-07-18 | 257 | 604 | Carrier floor 584→604 (+20): new `test_carrier_operator_attribution.py` adds X-Operator booking attribution coverage (DB `booked_by` column, coordinator fresh/replay preservation, route header→audit→response, sanitiser, do-not-use header fallback). Test file + this file changed in the same commit per update protocol. Bump is the minimal delta attributable to the new file on top of the recorded 584 floor; fresh creds-set full-suite evidence measured **619 pass / 4 documented env fail (`test_carrier_config_defaults.py`) / 1 skip / 0 errors**, so 604 stays conservative below measured. PZ 257 pass / 1 documented #613 fail; root golden 160/160. |
| 2026-07-16 | 257 | 584 | GATE-4 SCHEDULED disposition from PR #925 deploy gate (no floor change): registered `test_proforma_to_invoice_routes.py::test_dashboard_renders_two_step_convert_flow` as a known-failing exclusion (Issue #927) — stale V1 shipment-detail.html string pins, proven pre-existing on `origin/main` `28784270`, outside both metered suites. Gate-time fresh evidence for #925: PZ 257 pass / 1 documented #613 fail; Carrier 584 pass / 4 documented env fails / 1 skip / 0 err. |
| 2026-07-16 | 257 | 584 | **Removed** the Issue #927 exclusion row (no floor change): `test_dashboard_renders_two_step_convert_flow` DELETED — its stale V1 shipment-detail.html pins were repointed at the canonical V2 convert surface (`app/static/v2/proforma-detail.jsx` ConvertToInvoiceModal) as 8 new pins in `test_convert_modal_truth.py` §"Issue #927" (entry button, two-step preview→execute, exact confirm token YES_CREATE_FINAL_INVOICE_FROM_PROFORMA, irreversibility warning + acknowledgement checkbox, execute gating, single execute call site). Suite is outside both metered PZ/Carrier patterns; test file + this file changed in the same commit per update protocol. Closes #927. |
| 2026-07-17 | 257 | 584 | Stale-suite repair campaign (no floor change; all outside the metered suites). 29 failures proven pre-existing on `origin/main` `d5a453fd` diagnosed: 26 repaired test-only — `test_invoice_verify_after_create.py` ×19 (suite predates the PR #925 step-2c convert readiness gate; added the Lesson-A readiness stub — suite scope is verify-after-create, readiness has dedicated no-stub coverage), `test_insurance_wording_invoice_approval.py` ×4 (mock repointed from retired `wfdb.get_product` to C-3g mirror-first `_c1f_mirror_good_id` + `pildb.get_all_service_product_meta`), `test_sprint36_proforma_detail_authority.py` ×2 (over-broad `totalEur * ` grep vs the PR #875 display-only KUKE premium estimate — narrowed to FX forms; Generate-button reason re-pinned to the PR #707 "not yet wired" wording, disabled invariant kept), `test_toolbar_authority_map.py` ×1 (blanket `cmr` substring vs PR #922/#925-era CMR prose — narrowed to route-decorator scan). Remaining 3 = REAL DEFECT pins (readiness ambiguity gate fail-open since #684, preview key mismatch) registered above; fix chip `task_81ea7aea`. Side discovery repaired in the same PR: `test_proforma_fullnumber_phase9.py` had 4 order-dependent isolation-run failures (stale `_resolve_customer` lambda missing the `client_contractor_id` kwarg; fake-PDF stub under the 200-byte Lesson-G blank-guard floor) — now 19/19; its Lesson-A readiness stub was also completed to the real 12-key shape (reviewer finding). |
| 2026-07-17 | 257 | 584 | **Removed** the 3 `task_81ea7aea` defect-pin rows (no floor change): the fail-open design-ambiguity readiness gate is FIXED — `_derive_draft_readiness` now reads the nested `preview["design_product_bridge"]["ambiguous_design_codes"]` (one line; the top-level key never existed). Evidence on this branch: `test_proforma_readiness_single_authority.py` **12/12** (was 9/3 on the dead gate), `test_proforma_privileged_auth.py` 19/19 (#934 guards untouched), root golden 160/160. Fix + test file + this file in the same commit per update protocol. |
| 2026-05-13 | 160 | 366 | Baseline established (V2.0 engine) |
| 2026-05-22 | 160 | 381 | count update — carrier suite grew from new adapter/idempotency tests |
| 2026-06-09 | 160 | 412 | count update — carrier suite grew from phase5/plt/doc-package/routes tests |
| 2026-06-10 | 221 | 412 | file-reference fix: test_pz_regression.py never existed; actual PZ suite is tests/test_pz_*.py (221 passing, 1 pre-existing failure in test_pz_batch.py::test_save_json_csv_ui_round_trip) |
| 2026-06-23 | 221 | 430 | carrier suite grew by 10 tests — test_carrier_live_adapter.py added in PR #734 (Phase D live DHL Express AWB); gate tests updated from NotImplementedError stubs to mock-based HTTP call verification (net 0 change) |
| 2026-06-23 | 221 | 434 | carrier suite grew by 4 tests — sandbox URL routing fix (DHL_EXPRESS_USE_SANDBOX flag + _api_path() method + double-path guard tests) |
| 2026-06-23 | 221 | 469 | carrier suite grew by 35 tests — AWB modal upgrade (test_carrier_awb_modal_fields.py): product_code/description/customer_reference/shipment_reference/receiver_eori/receiver_vat_id/email/currency fields + GET /carrier/services endpoint + box_types authority validation |
| 2026-06-27 | 257 | 469 | PZ 221→257: quantity-validator hardening (#730/#731) merged; 258 collected, 257 passing; #613 formalized as known-failing exclusion |
| 2026-07-06 | 257 | 469 | PR #818 deploy gate: registered 5 env-conditional carrier exclusions (`test_carrier_config_defaults.py` ×4 + `test_carrier_awb_modal_fields::test_box_types_endpoint_returns_correct_shape` ERROR) — fail only when DHL creds are set in the env (deploy target + review clone); proven 9/9 pass with env cleared. Carrier now 548 collected / 543 passed; 469 floor unchanged. |
| 2026-07-09 | 257 | 584 | TEST-BASELINE-1 reconciliation (PR #856 gate stragglers). Carrier floor 469→584 (suite grew to 589 collected; 584 pass creds-set / 588 pass clean). Fixed 4 stale carrier tests broken by #824 (`test_carrier_live_adapter_gate.py` ×3 add receiver-phone fixture; `test_carrier_awb_modal_fields` email absent → assert omitted, renamed). Skipped `test_carrier_shipment_db::test_tracking_ref_not_in_schema` (operator decision 2026-07-06 persists tracking_ref). **Removed** the `box_types` ERROR exclusion — it + `test_shipment_request_body_forwards_product_code` were full-suite teardown contamination from those 4 stale tests, gone once fixed (0 errors ×3 runs). No production code changed. Also (outside carrier suite) skipped 3 stale C14A/C16A guards in `test_c18a_unified_proforma_truth.py` (c27.1 `89f68179` deleted the Pro-Forma sales-linkage transit surface; matches the already-skipped copies in `test_c19a_single_authority_renderer.py`). |
| 2026-07-12 | 257 | 584 | **Test storage-isolation root-cause fix (test-only; `service/tests/conftest.py`; no floor change).** On fresh-storage hosts the full `service/tests` suite produced non-deterministic `STORAGE LEAK` teardown ERRORs (measured before fix: **199 errors, ~193 storage-leak**). `_guard_storage_root` watches the real `service/app/storage` roots, but four write classes escaped every per-test sandbox and landed there: (1) `app.main` lifespan startup (~20 root-level DBs), (2) background sweeper/watcher/orchestrator threads writing after teardown, (3) import-time module path constants, and (4) `importlib.reload(app.core.config)` in `test_compliance_resolver_injection` (never restored) replacing the shared `settings` with a fresh real-root object that every later call-time `settings` resolver then reads/writes. The guard blamed whichever test was in teardown ("implicates the next test, not the culprit"). **Fix:** conftest redirects `settings.storage_root` to a per-session temp dir at IMPORT time (object attr — covers 1–3) **and** exports `STORAGE_ROOT=<sandbox>` (covers 4 — any reload-created `Settings()`); the guard still watches the real roots as a backstop for hardcoded-path writes; `atexit` cleanup. Measured full-suite: storage-leak errors **199→0** (object-attr-only interim still leaked 13 → the `STORAGE_ROOT` export closed the reload class); real root byte/mtime-identical across the entire run and **never recreated on a clean (moved-aside) host**. Deterministic and storage-pre-seeding-independent: **PZ 257 pass / 1 documented #613 fail / 0 err**; **Carrier creds-set 584 pass / 4 documented env fail / 1 skip / 0 err**; **Carrier creds-cleared 588 pass / 1 skip / 0 err**. **Carrier collection remains 589.** No floor change; **no** env-conditional ERROR exclusions added; **no** teardown-attributed test IDs added as exclusions. Remaining 8 full-suite ERRORs are pre-existing, order-dependent, **non-storage** (7× `sys.modules` mock contamination in `test_reservation_queue.py` — 0 in isolation; 1× `test_atlas_v2_sprint1` prod-client) — present in the pre-fix run, unrelated to storage, filed as a separate follow-up; they do not affect the isolated PZ/carrier gate subsets. |
