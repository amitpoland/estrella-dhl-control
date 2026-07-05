# C-1b.1 — reservations router registration (build record)

- **Date:** 2026-07-03 · verify-tree only, NO deploy · micro-slice closing the
  C-1b GATE-4 finding (task_d6fdfca9).
- **R1 scope-lock:** service/app/main.py + service/tests/test_reservation_queue.py
  + PROJECT_STATE/DECISIONS. Nothing else in the diff.
- **Commits:** impl `88b4816c` · this evidence (below) · Part A docs `574a6932`.

## Defect

`routes_reservations.py` defines a router (prefix `/api/v1`) but it was NEVER
registered via `app.include_router(...)` in `service/app/main.py`. Every
reservation endpoint was therefore unreachable in production:
- POST `/api/v1/wfirma/products/sync-by-codes` → **405** (shadowed by the
  wfirma_capabilities catch-all `PUT /api/v1/wfirma/products/{product_code:path}`,
  routes_wfirma_capabilities.py:236).
- `/api/v1/reservations/*` (queue, import-sales-packing, process-pending, reset)
  and `/api/v1/products/import-purchase-packing` → **404**.

This was the root cause of the 6 pre-existing `test_reservation_queue.py::test_api_*`
failures (stash-confirmed at HEAD during C-1a/C-1b).

## Fix

- **main.py**: `from .api.routes_reservations import router as reservations_router`
  + `app.include_router(reservations_router)` placed IMMEDIATELY BEFORE
  `app.include_router(wfirma_capabilities_router)`. Ordering rationale (in a code
  comment): registering the concrete POST route before the `{product_code:path}`
  catch-all makes the match unambiguous — defensive against the 405 shadow.
- **test_reservation_queue.py**: new HTTP-level regression test
  `test_reservations_router_is_registered_and_http_reachable` — POSTs to
  `/api/v1/wfirma/products/sync-by-codes` (mocked client + `_ensure_db`) and
  asserts **200** (not 404/405), and that the concrete POST route is present in
  `app.routes`. Guards against a future de-registration.

## Route-table proof (app.routes inspection)

```
OK  POST  /api/v1/wfirma/products/sync-by-codes        methods=[('POST',)]
OK  POST  /api/v1/reservations/import-sales-packing     methods=[('POST',)]
OK  POST  /api/v1/products/import-purchase-packing       methods=[('POST',)]
OK  GET   /api/v1/reservations/queue                     methods=[('GET',)]
OK  POST  /api/v1/reservations/process-pending           methods=[('POST',)]
    reset route: [('/api/v1/reservations/{queue_id}/reset', ('POST',))]
catch-all INTACT: [('/api/v1/wfirma/products/{product_code:path}', ('PUT',))]
duplicate (path,method) under /api/v1: NONE
```

## Gates

- **test_reservation_queue.py 21/21** — the 6 `test_api_*` (import_purchase_packing,
  import_sales_packing, get_reservation_queue, sync_by_codes, process_pending_dry_run,
  reset_queue_row) flipped RED → GREEN + the new registration regression test.
- Golden `test_pz_regression.py` **160/160**. Service smoke **63 passed / 1 skip**
  (pre-commit gate).
- Precise consumption pin baseline unchanged at **4** — this slice touched no
  product-authority read site.

## Baseline reconciliation

The 6 `test_api_*` failures were recorded as "pre-existing" in the C-1b evidence
report + the C-1b DECISIONS note; those are left as historical record (accurate at
C-1b time). `.claude/contracts/test-baseline.md` never listed them (it tracks a
different `test_pz_batch.py` CRLF pre-existing) — no contract change needed. The
C-1b.1 DECISIONS entry records the flip to green.

## Single-lane governance

The parallel task session (branch `claude/eager-swirles-*`, task_d6fdfca9) is
SUPERSEDED — this fix was reimplemented on deploy/latest per the operator's
single-lane rule. That branch must be ABANDONED / NOT merged. The parallel
worktree/branch was NOT deleted from here (it is a separate, possibly-active
session; deleting it could corrupt that session) — the operator / that session
discards it uncommitted.

No deploy. No file/table/service containing "PZ" renamed (R1).
