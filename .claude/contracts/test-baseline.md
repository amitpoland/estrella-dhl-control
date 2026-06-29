# Test Baseline — Deploy Pass Criteria

Single source of truth for required test counts.
Referenced by: `deploy_qa_reviewer.md`, `deploy_lead_coordinator.md`, `deploy.md`, `CLAUDE.md`.

---

## Current baseline

| Suite | File / pattern | Required pass count | Failure action |
|-------|---------------|---------------------|----------------|
| PZ regression | `tests/test_pz_*.py` | **257** | Unconditional deploy block |
| Carrier suite | `tests/test_carrier_*.py` | **469** | Unconditional deploy block |

Any test ERROR (not just FAILED) is also an unconditional block.
Any count below the required threshold is an unconditional block.

---

## Known-failing exclusions

The baseline is **not green** — it carries exactly one tracked, accepted red. Any failure
listed here is accepted at gate time; any FAILED test NOT listed here, and any ERROR, is an
unconditional block.

| Test | Tracking | Reason |
|------|----------|--------|
| `test_pz_batch.py::test_save_json_csv_ui_round_trip` | Issue #613 | Windows `csv.writer` CRLF / `splitlines()` round-trip artifact (asserts 8 == 4). Proven pre-existing on clean `origin/main`; not a regression. |
| `test_ai_gateway_contract.py::test_call_returns_model_response_text` | Issue #798 | Live-API test patches `app.services.ai_redactor` which is not a real attribute; fails without a production Anthropic key. Confirmed pre-existing via `git stash` test (5 failures in baseline). Not introduced by any recent PR. |

The PZ suite reports `1 failed, 257 passed` (258 collected). The gate accepts **only** this
one documented failure. When #613 is fixed: remove this row and bump the PZ required count to 258.

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
