# C-1a — Product Master Authority: schema + mirror + backfill (build record)

- **Date:** 2026-07-03 · verify-tree only, NO deploy · sub-slice 1 of 4 of
  "EJ Dashboard Master Authority Establishment" (C-1).
- **Declared:** PROJECT_STATE DECISIONS "C-1 RATIFIED" (objective, Master
  Consumption Rule, Layer Responsibilities, revised queue, success criteria,
  product_local fold) — also in the CLAUDE.md constitution.

## What changed (schema + code, reservation_queue.db authority)

- **wfirma_product_mirror** (NEW, sync layer ONLY) — EXACTLY six columns:
  `wfirma_id, product_code, sync_version, last_sync, hash, deleted_flag`.
  UNIQUE(product_code) + partial UNIQUE(wfirma_id WHERE !=''). No business
  logic; pinned to exactly six columns.
- **product_master promoted to the authority** — added authority columns
  `status` (default 'mapping_required'; enum mapping_required/mapped/…),
  `is_active`, and the fields folded from product_local: `unit`,
  `origin_country`, `notes`, `design_code_link` (hs_code_override folds into
  the existing hsn_code at backfill — no dup column). Via the established
  `_add_column_if_missing` ALTER-on-init idiom (fresh trees self-migrate).
- **backfill_product_authority()** — populates the mirror from the two
  deprecating split sources (wfirma.db/wfirma_products +
  reservation.db/wfirma_product_mapping), folds product_local into the master,
  sets master.status from mirror presence. **Collision-safe & idempotent**
  (ownership-aware UNIQUE-wfirma_id: a re-run never collides a row with its
  own prior entry; a genuine two-codes-one-wfirma_id collision is stored with
  an empty mirror id and reported, not crashed).
- Draft migration `draft_20260703_c1a_product_authority.py.draft` (backup +
  rollback documented; runs the backfill; verify-tree only).

## Data-integrity finding (surfaced, not hidden)

The backfill hit a real collision: **two product_codes claim the same
wfirma_id** (1 collision in the verify tree). One wFirma product should map to
one code; the mirror's UNIQUE(wfirma_id) enforces that. The colliding row is
stored with an empty mirror id and counted (`wfirma_id_collisions`) so the
invariant holds and the data problem is visible for later cleanup — the
migration does not silently drop or crash.

## Backfill result (verify-tree)

```
mirror_rows=4 (3 with a wfirma_id, 1 collision held empty)
status_set=0  (no overlap between the 4 wFirma-mapped codes and the 25
               product_master rows IN THIS verify DB — logic proven separately:
               a seeded overlapping row correctly flipped to status='mapped')
local_folded=0 (no product_local rows in this verify DB)
master rows=25 (all status='mapping_required' — none of the 25 has a wFirma id here)
wfirma_id_collisions=1
```
Idempotent: a second run inserts 0 new mirror rows and preserves the
wfirma_ids (ownership-aware collision check).

## Gates

- `test_master_consumption_rule.py` (NEW standing pin) **5/5**:
  (a) mirror schema = exactly the six columns; (b) UNIQUE product_code +
  wfirma_id; product_master has the authority columns; (b) no NEW
  business-module product-direct violations beyond the documented baseline;
  baseline count pinned at 8 files (must shrink to 0 by C-1d).
- Golden `test_pz_regression.py` **160/160**.
- Reservation/product suites: **zero new failures** — the 7 flakes are all
  PRE-EXISTING (triaged by stash): 6 reservation-API 405/404 in
  test_reservation_queue.py, and 1 product_code-mint grep in
  customs_position_aggregator.py + global_packing_parser.py (files C-1a never
  touched).

## Standing pin baseline (shrinks per sub-slice)

KNOWN_PRODUCT_VIOLATION_FILES (8): routes_proforma, routes_packing,
routes_dashboard, routes_wfirma, routes_reservations, routes_master_data,
routes_admin, routes_wfirma_capabilities. C-1b removes routes_wfirma +
routes_reservations (V1/V6); C-1c removes the readers + product_local; **0 by
C-1d.** A NEW business file with a product-direct read fails immediately.

## Migration / deploy note

Schema self-migrates at init (ALTER-on-init); the DATA backfill rides the
deploy under deploy_persistence_storage_reviewer via the draft (rename to .py,
backup reservation_queue.db first). Verify-tree backup taken:
reservation_queue.db.pre-c1a-20260703.bak. No prod touch.
