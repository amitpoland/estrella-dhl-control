# Mirror Completeness Proof — the ratified check (build record)

- **Date:** 2026-07-03 · ruled sequence: C-1e → **Mirror Completeness Proof** → C-1f → C-1d
- **Purpose:** before C-1f re-points the ~12 proforma fiscal reads (good_id source)
  from the legacy caches to `wfirma_product_mirror`, EVERY confirmed-id product write
  path must populate the mirror. A path that feeds only a legacy cache would make the
  mirror miss products → payload good_ids change → output-equivalence break.

## Census (grep evidence, comment-stripped)

All `.upsert_product(` / `upsert_wfirma_product_mapping(` / `upsert_product_mirror(` /
`register_product_identity(` call sites in service/app at proof time:

| Writer | Store | Mirror companion | Verdict |
|---|---|---|---|
| routes_proforma.py:4557 (service-charge @4527 region) | wfirma_products | :4542 `upsert_product_mirror` FIRST (C-1w1) | ✅ |
| routes_wfirma.py ×3 (:1951, :2093, :2435) | wfirma_products | via `register_product_identity` (C-1e) | ✅ |
| routes_wfirma_capabilities.py ×8 | wfirma_products | via `register_product_identity` (C-1w2) | ✅ |
| reservation_db.register_product_identity:668 | wfirma_products | mirror written first inside the helper | ✅ (is the mechanism) |
| reservation_db backfills (:355, :766, :819, :857) | mirror | — | ✅ (mirror-side) |
| wfirma_product_auto_register.py pending_adoption write (~:311) | wfirma_products | **exempt BY DESIGN** — `sync_status='pending_adoption'`, gated from PZ/proforma; mirror written at operator /adopt (C-1w2 endpoints) | ✅ documented |
| **wfirma_product_auto_register.py create path (~:387)** | wfirma_products (`matched`, confirmed id) | **GAP → FIXED**: canonical mirror written FIRST (init + upsert_product_mirror; collision → status=failed before cache; re-run adopts existing_mapped) | ✅ after fix |
| **wfirma_product_auto_register.py `_mirror_to_reservation_mapping`** | wfirma_product_mapping (`matched`, confirmed id) | **GAP → FIXED**: mirror upsert FIRST inside the helper; collision → warning string to caller | ✅ after fix |
| **reservation_worker.sync_wfirma_products_by_codes matched branch (:242)** | wfirma_product_mapping (`matched`, live-lookup id) | **GAP → FIXED**: mirror upsert first; collision → log.warning + new `collisions` list in the return dict (additive; mapping row still written so legacy consumers keep today's behaviour until 1d) | ✅ after fix |
| reservation_worker error/not_found branches (:221/:232) | wfirma_product_mapping (no confirmed id) | exempt — mirror holds confirmed ids only (C-1w1 ruling) | ✅ |

**Post-fix verdict: COMPLETE** — every confirmed-id product write path in
service/app now writes `wfirma_product_mirror` (mirror-first ordering), or is
documented-exempt (pending_adoption = mirror-at-adoption; no-id rows).

## Verification

- Suites: reservation_worker + auto_register + reservation_queue = 52 passed /
  1 skipped / 1 pre-existing error (see below). Pin 11/11. Smoke 63. Golden 160/160.
- Pre-existing failure disclosed (NOT caused by this patch — proven by connect-trace):
  `test_proforma_draft_pre_pz_gate.py::test_product_auto_register_works_without_sad`
  trips the storage-leak guard because the TEST seeds `ddb.store_invoice_lines`
  outside its storage_root patch and `document_db.store_invoice_lines`
  (document_db.py:1362) → `init_reservation_db` → `PRAGMA journal_mode=WAL`
  (reservation_db._DDL) modifies the live db mtime on every call. Every frame in
  the offending stack is committed pre-slice code. Filed as a spawned follow-up
  task (fix = move seeding inside the patch).

## Dirty-tree protection (Ruling 5)

Pre-flight 6 modified + 35 untracked operator entries — verified unchanged;
no stash/clean/reset executed.
