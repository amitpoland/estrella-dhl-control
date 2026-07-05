# C-1d — C-1 Verification Audit (Wave-1 close)

- **Date:** 2026-07-03 · read-only audit + census append · closes Constitution §16
  step 1 (Product) and step 2 (Customer, via C-2) → Wave 1 (Authority) COMPLETE.
- **Sequence honored (operator Ruling 1):** C-1e `7c4f6f0b` → Mirror Completeness
  Proof `37aaaf27` → C-1f `6a781ee4` → this audit.

## Success criteria, line by line

| # | Criterion | Evidence | Verdict |
|---|---|---|---|
| 1 | Mirror schema = exactly six columns (product + customer) | pin tests (a) + C-2a pin, 11/11 | ✅ |
| 2 | UNIQUE product_code + UNIQUE wfirma_id enforced | pin `test_mirror_has_unique...` | ✅ |
| 3 | Business ROUTE product access → Master/sync only | pin baseline 5 → **1**; the 1 = the single declared transitional dual-write (`wfdb.upsert_product` in the C-1w1 region), NOT a read | ✅ (residual declared) |
| 4 | Every confirmed-id product write path feeds the mirror | Mirror Completeness Proof `37aaaf27` (census table; 3 gaps closed) | ✅ |
| 5 | Fiscal (good_id) reads mirror-first, output-equivalent | C-1f gate: proforma suites 120✅, 9 new pins, golden 160/160, smoke 63 | ✅ |
| 6 | Inventory modules never touch wFirma/product caches | grep `wfirma_client\.|wfirma_db\.|wfirma_products` over inventory_*.py + routes_inventory*.py → EMPTY | ✅ |
| 7 | Customer: business modules → Customer Master only | C-2c full-app pin (starts at zero) 11/11 | ✅ |
| 8 | No new violation can land silently | pins fail on any new route violation (product) / any business file (customer) | ✅ |

## Declared residuals (carried into the ratification packet)

1. **Transitional dual-write** — `routes_proforma` C-1w1 region cache write
   (operator-ruled, "removed as a CLEANUP AFTER 1d"). Cleanup slice proposal:
   post-ratification, with its own equivalence check.
2. **Transitional cache-read passthroughs** — `get_cached_product/_batch/list_cached_products`
   (C-1w2/C-1e) + C-1f's non-identity cache field reads + loud fallback path.
   Retire together with (1) once a deploy-time mirror backfill re-run is verified
   against production data.
3. **Out-of-pin-scope census** (the ratified pin measures `app/api/routes_*.py` only;
   full-app sweep finds 6 more files with product-pattern hits — never part of the
   ratified baseline, recorded honestly, disposition = operator ratification):
   - `services/global_pz_push.py` (`list_products`) — PZ push service; migrate or whitelist
   - `services/wfirma_reservation.py` + `wfirma_reservation_create.py` (`get_product`) —
     wFirma reservation services; sync-adjacent → whitelist candidates or migrate
   - `tools/build_pz_batch.py`, `tools/send_wfirma_good_live_test.py`,
     `tools/send_wfirma_proforma_live_test.py` (`get_product_by_code`) — operator
     live-test/dev tools, wFirma-facing by purpose → exempt-by-purpose candidates
4. **Pre-existing test failures** (all root-caused, none slice-caused):
   storage-leak seeding test (task filed), 2× shipment-detail.html content
   assertions, 2× capabilities (contractor_search_hit, refresh_blocked_when_flag_off),
   3× test_audit_proforma_converted (operator's local main.py edits).

## Wave-1 ledger (all on deploy/latest)

Platform `575bb3f3` · Phase 0 `be0783c8` · C-1w2 `3833627c` · C-2a `18fb89ad` ·
C-2b `60a34f9e` · C-2c `0d0bf78d` · verdict `a4231850` · C-1e `7c4f6f0b` ·
MC-proof `37aaaf27` · C-1f `6a781ee4` · C-1d (this commit).
Budget: ~4h consumed of 8h. Dirty-tree protection honored throughout
(6 modified + 35 untracked operator entries intact; no stash/clean/reset since Ruling 5).

## Verdict

**Wave 1 (Authority) COMPLETE.** Product chain: business → Product Master/sync →
mirror → wFirma. Customer chain: business → Customer Master → (mirror built,
re-pointing = declared future slice) → wFirma. Campaign now HOLDS at the operator
stop-line: no Wave-2 entry without ratification of the restored Wave 2–4 plan.
