# C-1w1 — proforma service-product write → mirror-completeness (build record)

- **Date:** 2026-07-04 · verify-tree only, NO deploy · C-1w1 (first write slice of
  the sequence lock C-1w1 → C-1w2 → routes_wfirma → 1d → C-1d).
- **R1:** routes_proforma.py (4527 region only) + reservation_db.py (C-1b helper
  reuse — none added) + test_service_product_registry_phase2_3.py + PROJECT_STATE.

## What changed

`register_service_product` (PUT /api/v1/proforma/service-products/{charge_type})
maps a service charge (freight/insurance) to an operator-supplied wFirma product
id. It cached the mapping in `wfirma_products` (keyed by ct). C-1w1 now also
writes the **mirror** so the mirror becomes the complete authority for slice 1d:

1. **Mirror write FIRST** (before the cache write): `upsert_product_mirror(ct → pid)`
   — the C-1b TOCTOU/collision-safe helper. On any exception → 500 (cache not yet
   written → no partial state). This eliminates the divergence window.
2. **Collision → 409:** the mirror-write result is inspected; if the wfirma_id is
   already owned by a different code, the endpoint raises 409 `wfirma_id_collision`
   (with the owner) instead of silently returning 200 with an unwritten mirror.
3. **Cache write LAST** (kept — transitional dual-write): the legacy
   `wfirma_products` write stays because the not-yet-migrated proforma reads
   (@1385/4464/1558/7845) still read the cache; removing it now would change the
   payload good_id and fail output-equivalence. Removed as a cleanup after 1d.
4. **No Product Master row:** a service charge is NOT a Product Master product; a
   master row would pollute the product-options picker. Only the mirror is written
   (mirror needs no master row — no FK). This keeps the change in the 4527 region
   (no picker edit) and keeps §6 clean.

No wFirma push here (the operator supplies an existing id). Identity/sync fields
only — ZERO value recomputation (customs-value-freeze).

## Output-equivalence gate — PASS

The change is purely additive to the write path; it touches NO read, NO value
logic, and KEEPS the cache write. Proven:
- Service-charge payload-emission tests (`TestBuildServiceChargeLines`, which pin
  the exact emitted good_ids + value fields) pass unchanged.
- `test_customer_invoice_snapshot` (full invoice payload good_ids/values) passes.
- Golden `test_pz_regression.py` 160/160.
The fiscal-equivalence review lens returned **CLEAN**.

## Adversarial review (4-lens, pre-commit) — 3 must-fix, all fixed

Ran the C-1b-pattern 4-lens workflow. fiscal-equivalence CLEAN; 12 raw findings →
3 confirmed must-fix (7 dismissed as false/deferred/style):
- **HIGH — collision result discarded** → captured; raises 409 on collision (+ test).
- **HIGH — write order (cache before mirror) left partial state on failure** →
  reordered mirror-first / cache-last + wrapped RDB block (500, no partial).
- **MEDIUM — service charges polluted the product picker** → write mirror-only, no
  master row (also keeps the change in the 4527 region).
Review transcript: tasks/wy420wncx.output.

## Behaviour note (disclosed)

C-1w1 introduces a stricter invariant: two charge types (or a charge type and a
product) claiming the SAME wfirma_id now yield 409 (mirror UNIQUE(wfirma_id)).
This did not exist in the cache-only path (which silently upserted). It surfaces a
real one-id-two-codes data error; valid single-owner registrations are unaffected,
so output-equivalence for valid drafts holds.

## Dual-write (disclosed, transitional) + pin

Grep at 4527 shows BOTH the cache write (`wfdb.upsert_product`) and the mirror
write (`_rdb.upsert_product_mirror`) — the disclosed transitional dual-write
(operator ruling 2026-07-04). Removed after 1d. Pin baseline UNCHANGED at 3
(proforma stays — its reads + the kept cache write remain); KNOWN =
{routes_proforma, routes_wfirma_capabilities, routes_wfirma}.

No deploy. No "PZ" rename (R1).
