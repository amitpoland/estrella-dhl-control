# C-1b — Product write-path reroute through the Master (build record)

- **Date:** 2026-07-03 · verify-tree only, NO deploy · sub-slice 2 of 4 of
  "EJ Dashboard Master Authority Establishment" (C-1).
- **Ruling:** operator-approved **Path B + honest baseline 4** (2026-07-03;
  discovery `a4720dd3`, [reports/inspection/2026-07-03T-c1b-writepath-discovery.md]).
- **R1 scope-lock:** routes_wfirma.py, routes_reservations.py, reservation_db.py,
  the two route test files + the consumption pin, PROJECT_STATE. (main.py is NOT
  in scope — see the registration finding below.)

## What changed

**reservation_db.py** — new sync-layer write helpers (the ONLY entry points a
business module uses to touch wFirma product data):
- `lookup_wfirma_product(code)` — read passthrough (V6 + batch-resolve read).
- `wfirma_product_sync_client()` — client shim factory for the worker (V6).
- `set_product_master_status(db, code, status, *, is_active=None)`.
- `upsert_product_mirror(db, *, wfirma_id, product_code, name, also_set_master_status=None)`
  — the ONLY sync-identity write; UNIQUE(wfirma_id) collision-safe (pre-check +
  IntegrityError catch = the constraint is the real boundary); when
  `also_set_master_status` is set the status flip runs in the SAME transaction.
- `create_wfirma_product_via_master(...)` — gated push already decided by the
  route; writes MIRROR + flips status='mapped' atomically on confirmed wfirma_id;
  mirror-write failure is caught and reported, never masks the successful create.
- `edit_wfirma_product_via_master(...)` — pushes edit; bumps MIRROR sync fields
  (preserving the mapping); mirror failure caught so it never masquerades as an
  edit failure.

**routes_wfirma.py** — `resolve`: read via `rdb.lookup_wfirma_product`;
Master-first `upsert_product_master` + status='mapping_required' BEFORE the gate
(survives gate-off = sync-pending); create via `rdb.create_wfirma_product_via_master`;
a mirror collision is surfaced as a `failed_detail` (not silently mapped).
`sync_names`: edit via `rdb.edit_wfirma_product_via_master`; `_reservation_db()`
hoisted out of the per-product loop. The write GATE
(`settings.wfirma_create_product_allowed`) STAYS in the route — gating unchanged.

**routes_reservations.py** — `sync_products_by_codes` (V6): removed the direct
`get_product_by_code` import + shim; routes through `rdb.wfirma_product_sync_client()`;
response augmented with each matched code's Master `status` (Master read).

**test_master_consumption_rule.py** — pin refined from crude substrings to precise
ACCESS (strip comments+docstrings via `re.sub(r"\s+#.*$")`, match real
call/table patterns) + a positive-control test; baseline corrected to the real
4 remaining offenders {routes_dashboard, routes_packing, routes_proforma,
routes_wfirma_capabilities}.

## Write-sequence (operator contract) — realized

Master-first → gated push (gate in route) → Mirror-on-confirmed-id +
status='mapped' (atomic) → gate-off/failure keeps Master (sync-pending), no
mirror. No dual-writes: the legacy `wfirma_db` cache write stays (deprecates in
C-1c); the Master/Mirror are the new authority writes.

## Pin — measured

Precise offender set = **4** (identical file-set to the crude pin, proven at
discovery). routes_wfirma + routes_reservations now have ZERO precise hits
(rerouted). Baseline 8→4 honest (the C-1a "8" carried 2 phantom files that never
violated + the 2 files rerouted here). Trajectory to 0 by C-1d.

## Adversarial review (pre-commit) — 4 lenses + synthesis

Ran a 4-lens adversarial workflow (write-sequence · pin-soundness · layer-safety ·
test-adequacy) → 26 raw findings → synthesis confirmed 12 must-fix.

**Fixed in-scope (11):**
- HIGH: `upsert_product_mirror` TOCTOU — wrapped INSERT/UPDATE in
  `except sqlite3.IntegrityError` → re-query owner → collision (constraint is the
  real boundary; docstring corrected).
- HIGH: `edit_wfirma_product_via_master` mirror-write failure after a successful
  remote edit — wrapped + reported, never masks the edit result.
- HIGH: `resolve` silently discarded the mirror-collision result — now surfaced
  as a `failed_detail` (mirror_collision + existing_owner), skips the legacy write.
- MEDIUM: `sync_names` called `_reservation_db()` per product — hoisted before loop.
- MEDIUM: create wrote mirror + status in two transactions — combined into one
  (`also_set_master_status`), so they never diverge.
- MEDIUM×3: resolve tests 3/4/5 — test 3 dead `get_product` patch → `get_products_batch={}`;
  tests 4/5 now DB-readback assert Master-written / no-mirror-when-pending /
  mirror-linkage / status='mapped'.
- MEDIUM: pin comment-stripper missed tab-hash inline comments → `re.sub(r"\s+#.*$")`.
- LOW×2: V6 test asserts the status VALUE; edit test asserts `assert_called_once_with(args)`.

**Surfaced out-of-scope (1) — GATE 4 disposition: SCHEDULED (task chip `task_d6fdfca9`):**
- HIGH: `routes_reservations` router is NOT registered in `service/app/main.py`,
  so ALL reservation endpoints (queue, import-sales-packing, process-pending,
  reset, and the V6 sync-by-codes) are unreachable in production (404, or 405 via
  the `PUT /wfirma/products/{product_code:path}` catch-all). PRE-EXISTING (present
  at HEAD; it is the root cause of the 6 pre-existing `test_reservation_queue.py::test_api_*`
  failures). main.py is outside R1 scope, so it was surfaced as a separate task,
  not fixed inline. The V6 authority reroute is still correct and complete; the
  registration is a distinct reachability bug. The V6 test exercises the handler
  directly (documented), so it does not mask this gap.

**Dismissed** (false alarm / out-of-scope): found-path skips Master/Mirror
(intentional — C-1b covers create/edit only); edit-collision ValueError safe;
getattr/parenthesized-import pin evasion (deliberate-evasion, not the pin's remit);
routes_packing direct SQL (already in the C-1c baseline).

## Gates

- Precise pin `test_master_consumption_rule.py` **8/8** (schema + unique + master
  cols + no-new-violations + rerouted-files-left + baseline==4 + positive control).
- C-1b acceptance `test_c1b_product_write_path.py` **7/7** (create flag-off →
  Master+sync-pending; create success → Mirror+mapped; edit preserves mapping;
  V6 → Master fields; + collision/status/client robustness).
- resolve/sync_names/goods-authority/phase6 suites — all green.
- Golden `test_pz_regression.py` **160/160**. Service smoke **63 passed / 1 skip**.
- Combined sweep: **69 passed**, 6 failed — the 6 are the PRE-EXISTING
  `test_reservation_queue.py::test_api_*` route-collision failures (unregistered
  router; stash-confirmed at HEAD; zero new failures from C-1b).
- Test-isolation fix: V6 test uses `get_event_loop().run_until_complete` (not
  `asyncio.run`, which would close the loop the resolve handler-tests reuse).

## Notes

- reservation_db now makes function-local `wfirma_client` imports (whitelisted
  sync layer, operator-anticipated "Master/Mirror write helpers"). The gate stays
  in the route; reservation_db never checks `settings`.
- No file/table/service containing "PZ" renamed (R1). No deploy.
