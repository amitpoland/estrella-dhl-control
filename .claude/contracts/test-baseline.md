# Test Baseline — Deploy Pass Criteria

Single source of truth for required test counts.
Referenced by: `deploy_qa_reviewer.md`, `deploy_lead_coordinator.md`, `deploy.md`, `CLAUDE.md`.

---

## Current baseline

| Suite | File / pattern | Required pass count | Failure action |
|-------|---------------|---------------------|----------------|
| PZ regression | `tests/test_pz_*.py` | **260** | Unconditional deploy block |
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
| `test_proforma_authority_ui.py::TestCanonicalDescription::test_labelled_display_only_not_wfirma_line_name` | #1015 | MISSING UI — the "Display only" / "design_no / product_code" label is absent from V1 `shipment-detail.html` (frozen, Lesson F). Outside both metered suites; no floor impact. |
| `test_proforma_authority_ui.py::TestBlockedRecordsVisible::test_cm_link_only_when_contractor_id` | #1015 | MISSING UI — the cid-gated customer-master link (`"cid &&"` + `"customer-master"`) is not wired in the blocked-records panel of `shipment-detail.html`. Outside metered suites. |
| `test_proforma_policy_phase7.py::test_html_has_btn_draft_intelligence` | #1015 | MISSING UI — the draft-intelligence panel is not built in any `app/static/` file; it would surface `detect_operator_override_mismatches` (backend shipped in #1014). Outside metered suites. |
| `test_proforma_policy_phase7.py::test_html_has_intelligence_panel_testid` | #1015 | MISSING UI — `draft-intelligence-panel` testid absent from all `app/static/`. Outside metered suites. |
| `test_proforma_policy_phase7.py::test_html_anomaly_row_testid` | #1015 | MISSING UI — `draft-anomaly-row` testid absent from all `app/static/`. Outside metered suites. |
| `test_proforma_policy_phase7.py::test_html_suggestion_row_testid` | #1015 | MISSING UI — `draft-suggestion-row` testid absent from all `app/static/`. Outside metered suites. |

**Out-of-pattern pre-existing failures — 6 modules (SCHEDULED, registered 2026-07-27, PR #1036 deploy gate):**
The PR #1036 deploy gate ran the metered subsets via `-k "test_pz_ or test_carrier_"`, which name-matches
test *functions* beginning `test_pz_*` living in **non-metered files**. Those surfaced a set of failing tests
in six modules — **all OUTSIDE both metered file-globs** (`tests/test_pz_*.py`, `tests/test_carrier_*.py`);
these are `test_dashboard_*`, `test_global_*`, `test_wfirma_*` files, so they contribute **nothing** to either
floor. Isolation run (6 modules, no `-k`): **36 failed / 164 passed**. Two failure classes identified:
- **Stale V1 source-grep pins** — `test_dashboard_detail_design.py` asserts strings (e.g. `pzCreateConfirm`,
  per-tab references) against the **frozen** V1 `shipment-detail.html` (Lesson F). Consistent failures; the
  pinned strings are simply absent from the current V1 page.
- **Order-dependent full-suite contamination** — `test_dashboard_pz_operator_header.py`,
  `test_global_pz_lineage.py`, `test_wfirma_pz_document_view.py`, `test_wfirma_pz_lock_status.py`,
  `test_wfirma_pz_supplier_resolution.py`: individual tests pass in small selections but fail in aggregate
  (asyncio event-loop / module-mock leakage — `RuntimeError: There is no current event loop in thread 'MainThread'`).

**PROVEN PRE-EXISTING (not #1036):** the deployed change is exactly 3 files — `git diff c8be511f dd59559f` =
`service/app/static/v2/proforma-detail.jsx` + `test_proforma_product_mapping_resolver.py` +
`test_proforma_service_charges_panel.py`. None of the six failing modules, and none of their targets
(`shipment-detail.html`, `routes_wfirma*.py`), are in the diff — a JSX-only change cannot alter Python
source-grep pins or backend routes. **Zero floor impact; did NOT gate the #1036 deploy.**
**GATE-4 disposition: SCHEDULED** — repair campaign (trichotomize per class: repoint/retire the stale V1 pins;
fix the isolation-leak fixtures in the wfirma/dashboard-pz modules). Not enumerated per-test here (36 rows would
bloat the table); the six module names above are the tracked scope.

The PZ metered suite (`tests/test_pz_*.py`) has **no documented failures** as of the #613 fix
(PR #1006). Required count bumped 257→258 (the +1 attributable to #613), then **258→260
(2026-07-25) reconciling the long-flagged +2 drift** — the 2 additional `test_pz_*` tests
introduced by later PRs are now folded into the floor. Fresh clean-env measurement on `main`
`48cdab25`: **260 passed / 0 failed / 0 errors**, so the floor now equals measured (no remaining
drift). Issue #802 (`test_ai_gateway_contract`) was likewise fixed
(PR #1000) and its stale exclusion removed; it is outside the metered PZ pattern, so no floor impact.

**Carrier env-conditional exclusions (4, reconciled 2026-07-09; figures refreshed 2026-07-31):** the
four `test_carrier_config_defaults.py` rows above assert the *code defaults are unset*; they fail on
any host where the DHL credentials are configured (the deploy target `C:\PZ` and this review clone
both are). They are NOT regressions — proven originally by a clean-env full-suite run (all
`DHL_EXPRESS_*` + `CARRIER_*` unset → 0 failed, 0 errors), and these four remain the only carrier
reds on a creds-set host.

Current measured reality, creds-set on the DHL-configured host (`tests/test_carrier_*.py`,
2026-07-31, `main` @ `1ce0e76d`): **650 collected → 646 passed / 4 failed (these env rows) / 0
skipped / 0 errors**. The required-pass floor is **604** (see the table above) — deliberately
conservative below the measured 646, so incidental suite growth does not silently raise the gate.
The floor was raised 584→604 on 2026-07-18, and the suite has carried **no skips** since the
`tracking_ref` dead-test cleanup of 2026-07-19; any earlier prose citing 584 as the current floor,
or 588/589 as current counts, is historical, not current.

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
| 2026-08-05 | 260 | 604 | **No floor change — PR #1094 adds ~180 tests entirely outside both metered patterns.** `service/tests/test_gate_evidence.py` (new) and `service/tests/test_deploy_reconcile_signing.py` (extended) cover the strict-JSON seven-agent gate evidence format that replaced a tolerant Markdown parser. Neither file matches `tests/test_pz_*.py` or `tests/test_carrier_*.py`, so both floors are untouched — recorded per the update protocol, same convention as the #1015/#927/#1021/#1029 out-of-pattern rows. Gate-time evidence at `12376dc6`: `tests/test_pz_*.py` **260 passed / 0 failed / 0 errors** (floor 260, zero headroom); `tests/test_carrier_*.py` **650 passed / 0 failed / 0 errors** on a creds-CLEARED host — the same 650 collection count this file records at 2026-07-31, with the four documented `test_carrier_config_defaults.py` env rows green because the DHL vars are unset here; the deploy host will show 646 + those 4 documented fails, and both satisfy 604. Root golden 160/160. Aggregate CI is red on 234 inherited failures, proven pre-existing by node-ID set-difference against merge base `6e1de8b1` (identical sets, zero new) — those 234 are **larger than this file's registered exclusions** and are flagged as GATE-4 governance debt for a separate disposition; they are outside both metered globs and did not gate this PR. |
| 2026-07-31 | 260 | 604 | **Documentation-only correction — no floor change, no test change (rebased from the 2026-07-19 `docs/test-baseline-carrier-prose-correction` branch onto `main` `1ce0e76d`).** The "Carrier env-conditional exclusions" prose block still carried pre-2026-07-18 figures (588 clean-env pass / 589 collected → 584 pass creds-set / 1 skipped) and asserted "the 584 required-pass floor is the creds-set worst case" — stale on three counts: the floor was raised 584→604 (2026-07-18), the lone skip was deleted (2026-07-19 `tracking_ref` dead-test cleanup, merged via PR #959), and the suite has since grown. Prose refreshed against a fresh creds-set measurement on `main` `1ce0e76d`: `python -m pytest tests/test_carrier_*.py` → **650 collected / 646 passed / 4 failed (documented `test_carrier_config_defaults.py` env rows, DHL creds set on this host) / 0 skipped / 0 errors**; root `python test_pz_regression.py` → 160/160. Floor 604 unchanged (conservative below measured 646). Figures were measured at the immediate predecessor tip `92222849` and re-confirmed at `1ce0e76d` — the only intervening merge (#1039, rollback-provenance) is deploy/docs-only and touches neither `test_carrier_*.py` nor `test_pz_*.py`. This row supersedes the branch's original 2026-07-19 correction row, whose 624/619/1-skip @ `a4da80b2` figures were themselves invalidated by intervening main growth. Earlier History rows are untouched — their figures were correct when written. |
| 2026-07-27 | 260 | 604 | **No floor change — GATE-4 SCHEDULED disposition from the PR #1036 single-file deploy gate.** Registered 6 out-of-pattern modules (`test_dashboard_detail_design.py`, `test_dashboard_pz_operator_header.py`, `test_global_pz_lineage.py`, `test_wfirma_pz_document_view.py`, `test_wfirma_pz_lock_status.py`, `test_wfirma_pz_supplier_resolution.py`) carrying pre-existing failures — surfaced by the metered `-k "test_pz_ or test_carrier_"` subset run (which name-matches `test_pz_*` functions in non-metered files). All are OUTSIDE both metered file-globs → zero floor impact; did not gate the deploy. Two classes: stale V1 `shipment-detail.html` source-grep pins (frozen, Lesson F) + order-dependent full-suite asyncio/mock contamination. Proven pre-existing: `#1036` diff = exactly 3 files (`proforma-detail.jsx` + 2 new proforma tests), none touching these modules or their targets. See the "Out-of-pattern pre-existing failures" block above. Deploy parity confirmed (`proforma-detail.jsx` content-hash `4E11B971…`, PZService `4 RUNNING`). |
| 2026-07-25 | 260 | 604 | **PZ floor 258→260 (+2 drift reconciliation); #1021/#1029 add tests outside both metered patterns (zero floor impact).** (1) **Reconciles the long-flagged +2 PZ drift:** `tests/test_pz_*.py` has measured 260 pass since earlier-PR test additions while the floor stayed 258 (kept conservative). Fresh clean-env measurement on `main` `48cdab25`: **260 passed / 0 failed / 0 errors** — floor raised to equal measured, no remaining drift. (2) #1029 added `test_wfirma_client_contract.py::test_http_request_rejects_non_numeric_id_suffix` (+1; guards the URL-encoded `id_suffix` path segment — issue #1028) and #1021 added `test_proforma_mapping_repair_ui.py` + `test_proforma_packing_sync.py` (manual-line preservation + honest re-check + unmapped-designs; 35 pass together in isolation). All three are OUTSIDE `tests/test_pz_*.py` and `tests/test_carrier_*.py` (wfirma/proforma suites), so they contribute **nothing** to either metered floor — recorded per the update protocol (same convention as the #1015/#927 out-of-pattern rows). Both PRs merged + deployed to prod (`48cdab25`, full parity). Carrier `tests/test_carrier_*.py` **619 passed / 4 documented env fail** (floor 604 unchanged), root golden 160/160. |
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
