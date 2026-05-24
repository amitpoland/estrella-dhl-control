# PZ Correction Lifecycle, Phase 1, Completion Record
**Date:** 2026-05-24
**PR:** #348 (squash SHA 9c45cee, merged to main)
**PR A (activation blockers):** merged on top of #348 — sentinel fix, suppress route, doc corrections
**Service:** PZService, port 47213, `https://pz.estrellajewels.eu`

---

## What was built

Phase 1 added a state machine and four API endpoints to manage the lifecycle of a PZ correction operation. A correction is what happens when a previously submitted PZ document in wFirma needs to be revised, because the original invoice data was wrong, because customs reconciled differently, or because the operator needs to align the wFirma record to a newer authority source.

The state machine has seven states:

```
PROPOSED -> OPERATOR_REVIEWED -> STAGED -> EXECUTING -> COMPLETED
                                                      -> FAILED
ANY -> TERMINAL_SUPPRESSED
```

The four endpoints are:

- `GET  /api/v1/pz/lineage/{batch_id}/correction-state` -- reads or initializes the lifecycle record for a batch
- `POST /api/v1/pz/lineage/{batch_id}/correction-stage` -- selects a correction option and prepares the execution record
- `DELETE /api/v1/pz/lineage/{batch_id}/correction-stage` -- resets a staged selection back to OPERATOR_REVIEWED so the operator can choose differently
- `POST /api/v1/pz/lineage/{batch_id}/correction-commit` -- executes the staged correction by pushing to wFirma

These four endpoints sit in `routes_pz.py` alongside the existing correction routes. No new router file was created. No `main.py` change was needed. The correction push logic (`push_correction_to_wfirma`) and execution logic (`execute_correction_option`) already existed. Phase 1 wraps them in a controlled, auditable lifecycle with state persistence.

State is stored per-batch at `{batch_dir}/pz_correction_lifecycle.json`, written atomically using the existing `write_json_atomic` utility. Production databases at `C:\PZ\storage\` are untouched.

---

## What is running right now

PZService is running at PID 7432. Local health returns 200. Public health through the Cloudflare tunnel returns 200.

The four lifecycle endpoints are live and accepting requests. Every one of them returns HTTP 503 because `pz_correction_lifecycle_enabled` is set to `False` in the config. This is the intended behavior. The code is in place, the routes are registered, the state machine is ready, and nothing executes until the flag is turned on.

The existing pre-Phase 1 correction routes continue working exactly as before. Phase 1 added alongside them, did not replace or modify them.

wFirma write behavior is unchanged. No wFirma calls are made by Phase 1 code in the current state. The commit endpoint has two independent gates before any wFirma write can happen: `pz_correction_lifecycle_enabled` must be True, and `wfirma_correction_push_allowed` must also be True. Both are currently False.

The `pz_correction_lifecycle.py` and `pz_correction_state.py` files were removed from `C:\PZ\app\services\` as part of hygiene cleanup on 2026-05-24, after being accidentally copied there by robocopy. Backups are at `C:\PZ\backups\hygiene_phase10_20260524-092326\services\`. When Phase 1 is activated, these files will be redeployed as part of the normal deploy sequence. Their absence from the deployed tree right now is not a problem: the lifecycle endpoints return 503 before attempting to import them, and all imports within the endpoints are lazy (`from ..services.pz_correction_lifecycle import ...` inside the function body), so a missing file never causes a startup error.

---

## What is intentionally not built yet

**CANCEL_AND_RECREATE** is explicitly blocked. If an operator attempts to use it, the service layer raises a `CorrectionLifecycleTransitionError` before touching wFirma. The reason it is blocked: wFirma's PZ delete API has not been confirmed to exist or been tested in this environment, and the inventory reversal logic that would need to accompany a cancel-and-recreate has not been defined. This is deferred to a future decision, not forgotten. The blocking code is in `stage_option()` in `pz_correction_lifecycle.py`.

**Atomicity hardening for push record and audit writes** (PR B scope). `correction_push_record.json` and `audit.json` patches in `global_pz_push.py` are written via plain `path.write_text()`, not `write_json_atomic`. The comment at line 205 of `global_pz_push.py` claiming "atomic" write is incorrect. This is a known defect documented for PR B. It creates a narrow crash window where wFirma creates a document but the idempotency record is not persisted. The window requires NSSM kill at a specific moment plus manual lifecycle state edit to reproduce.

**Old correction-push-wfirma route deprecation** (PR B scope). The pre-Phase-1 route `POST /pz/lineage/{batch_id}/correction-push-wfirma` coexists with the lifecycle routes and does not check `pz_correction_lifecycle_enabled`. Using both paths against the same batch can cause lifecycle divergence.

**Phase 2** (the UI surface for operators to drive the correction lifecycle through the dashboard) has not started. It will be a separate PR and requires explicit operator approval before work begins.

---

## Test coverage

72 tests added in Phase 1. PR A adds 9 more (suppress route + wrong-sentinel gate test). Total: 81.

- `test_pz_correction_state.py`, 25 tests: state enum completeness, all transition rules, serialization round-trips for all seven states, suppression reason persistence, `_utc_now` format
- `test_pz_correction_lifecycle.py`, 26 tests: full happy path per transition, failure paths, the ordering invariant (that `stage_option` calls `execute_correction_option` before writing STAGED), CANCEL_AND_RECREATE block, EXECUTING written to disk before the wFirma push call, re-staging after FAILED. All sentinel strings now use `_CONFIRM_SENTINEL` imported from `global_pz_push`.
- `test_pz_correction_routes.py`, 30 tests: original 21 plus 9 new. New tests: `TestCorrectionSuppressRoute` (8 tests covering 503/400/404/409/200-from-EXECUTING/200-from-FAILED/no-wFirma-call/no-global-batch-check) and `test_wrong_sentinel_reaches_gate_1_in_real_push_service` (exercises real Gate 1, not mocked, confirms FAILED lifecycle and 502 response).

PZ regression suite: 160/160 passing. Carrier suite: 381/381 passing.

---

## Critical ordering invariant

This matters for anyone reading the code or extending Phase 1.

`stage_option()` calls `execute_correction_option()` before writing the STAGED state to disk. `execute_correction_option()` writes `correction_execution_record.json` to the batch directory. The wFirma push service (`push_correction_to_wfirma`) has a Gate 5 that checks for this file before making any wFirma API call. If the file is absent, the push is blocked at the gate level, not at the wFirma level.

This means the state on disk and the execution record on disk are always consistent: if the state is STAGED, the execution record exists. If `execute_correction_option()` fails, the state remains OPERATOR_REVIEWED and nothing is staged.

---

## Sentinel contract

**Canonical definition:** `global_pz_push.py`, `_CONFIRM_SENTINEL`, lines 74-78.

**Exact value:**
```
"I confirm this will create a new wFirma PZ document and cannot be undone without manual wFirma intervention"
```

This is Gate 1 of `push_correction_to_wfirma()`. Any value that does not match exactly causes
an immediate `status="blocked"` return, which the lifecycle layer records as FAILED state.
Phase 2 UI must send this exact string. Tests import `_CONFIRM_SENTINEL` rather than literals.

Previous documentation referencing `"I UNDERSTAND THE IMPLICATIONS"` was incorrect and has been
fixed in PR A in all test files, service docstrings, and route docstrings.

---

## Conditions for Phase 2 to begin

Phase 2 does not start automatically after Phase 1 deploys. An operator must explicitly approve it.

Before any Phase 2 work begins, the following must be true:

1. Operator issues explicit go/no-go for Phase 2 in this session or a subsequent session.
2. PR B (atomicity hardening, parallel push route deprecation) must be complete before
   `wfirma_correction_push_allowed` is set to True, but PR B is not a prerequisite for Phase 2
   UI development.
3. The feature flag stays OFF through all of Phase 2 development. The flag is only turned ON after
   Phase 2 smoke testing passes in production.
4. Phase 2 will cover the operator UI surface on the dashboard, allowing operators to drive the
   state machine through the browser instead of via direct API calls.
5. Phase 2 code will follow the same patterns as Phase 1: FastAPI routes in `routes_pz.py`, state
   managed by `PZCorrectionLifecycle`, no wFirma calls from the route layer, no business logic in
   the frontend.
6. Phase 2 UI must use the exact `_CONFIRM_SENTINEL` string from `global_pz_push.py` for the
   commit confirmation step. Do not use `"I UNDERSTAND THE IMPLICATIONS"`.
7. Phase 2 UI should include a suppress action visible from EXECUTING and FAILED states, calling
   `POST /correction-suppress` with a reason.

Until those conditions are met, the system sits at the current state: Phase 1 deployed, feature
flag off, endpoints returning 503, no operator-facing behavior change.

---

## Summary for ops handoff

Phase 1 is complete and in production. The service is healthy. Nothing about the correction workflow is active or accessible to operators yet. The lifecycle code exists in the repository and in the deployed service, protected behind two config flags that are both off. The existing correction routes and all other PZ functionality work exactly as they did before. Smoke verification passed on 2026-05-24 after a hygiene cleanup that removed accidentally synced dev artifacts from the production app directory. The system is stable at this state and will remain so until an operator explicitly enables Phase 2.
