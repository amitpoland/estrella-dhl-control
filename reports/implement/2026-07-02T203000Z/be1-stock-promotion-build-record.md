# B×7-1b BE-1 — auto stock promotion on PZ creation: build + test record

- **Date:** 2026-07-02 · branch `deploy/latest` · backend only, no UI, no deploy
- **Operator decision (a) (verbatim):** "App-pipeline PZs only for now. Direct
  wFirma PZ bookings should not block BE-1. Record direct-wFirma PZ
  auto-promotion as BE-1c / future extension. Rule: If PZ is created through
  Atlas/EJ pipeline, auto-promote PURCHASE_TRANSIT → WAREHOUSE_STOCK. If PZ is
  created directly inside wFirma, it remains manual/exception handling until
  webhook/poll extension is approved."
- **ASSUMPTION (reversible with one word):** auto-promotion fires on
  APP-PIPELINE PZ creation only; direct-booked PZs promote via
  physical-receipt confirm or the future manual exception page until BE-1c.

## What was built

`service/app/services/stock_promotion.py` — `run_stock_promotion(batch_id,
trigger=, source=, operator=)`: the ONE shared promotion authority.
Idempotent skip (only PURCHASE_TRANSIT moves; promoted/beyond/unseeded →
skipped), never raises, single-writer preserved (all state changes via
`inventory_state_engine.transition()`), trigger recorded on every transition
audit row, best-effort audit mirrors (summary
`inventory_warehouse_stock_promoted` + per-line
`inventory_transition_failed`, no financial fields).

Callers (all app-pipeline PZ writers):
1. `routes_wfirma.wfirma_pz_create` — after EV_WFIRMA_PZ_CREATED, **outside**
   `_pz_write_lock`; result in the create response as `stock_promotion`.
2. `global_pz_push` (correction push) — after its EV_WFIRMA_PZ_CREATED;
   errors surfaced in PushResult warnings.
3. `routes_upload._promote_to_warehouse_stock` (internal PZ generation) —
   pre-existing inline loop EXTRACTED into the shared function; wrapper
   delegates (`trigger="pz_generated"`). Pre-existing 9-test pin suite green
   unmodified. Disclosed delta: generation-path transitions now record
   trigger/operator; summary mirror gains skipped/errors/trigger keys.

NOT hooked (disclosed): PZ ADOPT (re-linking an existing wFirma document) —
separate business question, not assumed.

## Adversarial verify pass (3-lens workflow, run wf_57f9330a-c5e)

Lenses: unsafe-writes/single-writer · idempotency/replay/ordering ·
scope/authority/Lesson-N. **All three: refuted=false.** Hardenings applied
same day before commit:
1. Hook moved outside `_pz_write_lock` (in-lock placement widened the 409
   PZ_WRITE_LOCKED window by N engine transitions; latent unbound-name risk).
2. Benign-race recheck: concurrent promoter winning between get_state and
   transition → counted skipped, not error; no failure mirror (pinned by
   `test_benign_race_counts_as_skipped_not_error`).

Residuals accepted (documented in PROJECT_STATE DECISIONS): already_created
fast path returns before the hook (crash-window stragglers fall to the
receipt path / next generation run); global_pz_push replay
duplicate-document window is pre-existing, unchanged (promotion no-ops on
replay); single-writer invariant independently confirmed by grep.

## Test evidence (fresh run at commit time, 2026-07-02)

```
pytest tests/test_stock_promotion_be1.py -q
............                                                             [100%]
12 passed in 8.72s

pytest tests/test_warehouse_stock_promotion.py -q   (pre-existing pins, unmodified)
.........                                                                [100%]
9 passed in 7.30s

PYTHONUTF8=1 python test_pz_regression.py
160/160 tests passed | 0 failed — all golden checks pass, no regression.
```

Earlier full blast-radius run (same code): 125/125 across
test_global_pz_push, test_global_pz_execution, test_authority_separation,
test_routes_upload_cif_e2e, test_awb9158478722_import_pz_sales_authority,
test_pz_lifecycle_state, test_audit_persist + the two suites above.

Operator-required ordering pins: double promotion no-op ·
receipt-first-then-PZ · PZ-first-then-receipt — all in
`test_stock_promotion_be1.py`, no stubs (real packing_db + warehouse_db +
seed_purchase_transit; Lesson A).

## Transport-channel note

The wFirma+wireframe inspection report ("Deliverables 1+2") referenced by the
operator does NOT exist on disk in C:\PZ-verify (searched reports/,
reports/inspection/, *.md repo-wide, and the Downloads working dir) — it was
lost in the chat transport channel and was never persisted by this session.
Deliverable 1 §E (the operator wFirma-requirements checklist) was re-composed
fresh from the repository's actual wFirma integration
(docs/WFIRMA_API_RESEARCH.md, wfirma_client.py, routes_wfirma guards) and
delivered in-channel with the BE-1 commit report.
