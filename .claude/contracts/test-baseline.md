# Test Baseline — Deploy Pass Criteria

Single source of truth for required test counts.
Referenced by: `deploy_qa_reviewer.md`, `deploy_lead_coordinator.md`, `deploy.md`, `CLAUDE.md`.

---

## Current baseline

| Suite | File / pattern | Required pass count | Failure action |
|-------|---------------|---------------------|----------------|
| PZ regression | `tests/test_pz_*.py` | **257** | Unconditional deploy block |
| Carrier suite | `tests/test_carrier_*.py` | **584** | Unconditional deploy block |

Any test ERROR (not just FAILED) is also an unconditional block.
Any count below the required threshold is an unconditional block.

---

## Known-failing exclusions

The baseline is **not green** — it carries a small set of tracked, accepted reds. Any failure
listed here is accepted at gate time; any FAILED test NOT listed here, and any ERROR, is an
unconditional block.

| Test | Tracking | Reason |
|------|----------|--------|
| `test_pz_batch.py::test_save_json_csv_ui_round_trip` | Issue #613 | Windows `csv.writer` CRLF / `splitlines()` round-trip artifact (asserts 8 == 4). Proven pre-existing on clean `origin/main`; not a regression. |
| `test_ai_gateway_contract.py::test_call_returns_model_response_text` | Issue #802 | `AttributeError: app.services.ai_redactor` — patch target mismatch. `ai_gateway.py` imports `ai_redactor` with a local binding (`from . import ai_redactor as redactor`); the patch targets module-level attribute on `app.services` which does not exist. Pre-existing on `origin/main`; not introduced by any Phase 2/3 PR. |
| `test_carrier_config_defaults.py::test_carrier_live_allowlist_default_is_empty` | env: DHL creds set | ENVIRONMENTAL — asserts the *code default* of `carrier_live_allowlist`; fails only when `CARRIER_LIVE_ALLOWLIST` is set in the environment (as it is on any DHL-configured host incl. production `C:\PZ` and this review clone). PROVEN environmental: with DHL/carrier env vars cleared, `test_carrier_config_defaults.py` = 9/9 passed. Not a code regression. |
| `test_carrier_config_defaults.py::test_dhl_express_api_key_default_is_none` | env: DHL creds set | ENVIRONMENTAL — asserts `Settings().dhl_express_api_key is None`; `DHL_EXPRESS_API_KEY` is set in the deploy/review env → returns the live key. Passes with env cleared (see above). |
| `test_carrier_config_defaults.py::test_dhl_express_api_secret_default_is_none` | env: DHL creds set | ENVIRONMENTAL — asserts `Settings().dhl_express_api_secret is None`; `DHL_EXPRESS_API_SECRET` set in env. Passes with env cleared. |
| `test_carrier_config_defaults.py::test_dhl_express_account_number_default_is_none` | env: DHL creds set | ENVIRONMENTAL — asserts `Settings().dhl_express_account_number is None`; `DHL_EXPRESS_ACCOUNT_NUMBER` set in env. Passes with env cleared. |

The PZ suite reports `1 failed, 257 passed` (258 collected). The gate accepts **only** the
documented failure(s). When #613 is fixed: remove this row and bump the PZ required count to 258.

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
longer error (0 errors across 3 full-suite runs). One carrier test is now `skip`-superseded in-source
rather than baseline-listed: `test_carrier_shipment_db.py::test_tracking_ref_not_in_schema`
(operator decision 2026-07-06 persists `tracking_ref`; surviving AWB-exclusion invariant covered by
`test_live_result_insert_raises`).

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
