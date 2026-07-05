# C-1c STAGE 1 (read migration) + STAGE 2 (residual) — build record

- **Date:** 2026-07-03/04 · verify-tree only, NO deploy · STAGE 1 read migrations
  (1a–1c done, 1d STOPPED) + STAGE 2 residual declaration.
- Pin refinement (STAGE 0) `e7927f4c`; ruling recorded in DECISIONS (verbatim R4).

## STAGE 1 — completed sub-commits

| sub | file | change | SHA | pin |
|---|---|---|---|---|
| 1a | routes_dashboard | proforma-readiness product count → `get_product_master.status=='mapped'` | `eafc5504` | 5→4 |
| 1b | routes_packing | lane-readiness `SELECT FROM wfirma_products` → `get_product_master_statuses` (additive read-only accessor) | `d284f9ab` | 4→3 |
| 1c | routes_wfirma_capabilities | 3 SEPARABLE diagnostic searches → `rdb.lookup_wfirma_product`; inseparable pre-write reads LEFT (R3) | `feeb1fbe` | 3 (stays) |

Each: affected suites green, introduced failures fixed, all others stash-confirmed
pre-existing; smoke + golden 160/160 per sub-commit.

## 1d — proforma READS: STOPPED (fiscal-payload risk + mirror-incompleteness)

Scoped all ~12 proforma `wfdb` reads. The DOMINANT field they produce is
**`wfirma_product_id` (the good_id)**, which flows into the **fiscal invoice /
proforma payload** (@1385, 1558, 2344, 4464, 4535, 5643, 7845 build/emit good_id;
@957/1711/7692 are advisory readiness). Routing these to the Master/mirror is NOT
value-safe **yet**, for an airtight structural reason:

**The Product MIRROR is incomplete by construction.** The legacy product WRITE
paths still write `wfirma_products` but NOT the mirror:
- routes_wfirma_capabilities create/adopt (`wfdb.upsert_product` @525, 599, 741,
  863, 1026) — the C-1w2 residual, NOT migrated;
- routes_proforma's own write (`wfdb.upsert_product` @4527) — the C-1w1 residual;
- routes_wfirma's `wfdb.upsert_product` ×3 — residual.
A product_code created via any of these exists in `wfirma_products` with a
`wfirma_product_id`, but has NO mirror row (and status ≠ 'mapped' in the Master).
So if proforma read the mirror/Master instead of `wfirma_products`, the payload
good_id for legacy-created codes would change or vanish → a **value/identity change
in a fiscal document** → the operator's output-equivalence gate FAILS.

**Ordering correction (finding):** the operator's plan assumed reads migrate
before writes. For FISCAL-PAYLOAD reads that depends on the mirror being the
COMPLETE authority — which only holds AFTER the write slices (C-1w1 + C-1w2) route
every product write through the Master/mirror. Therefore **1d (proforma reads)
must come AFTER C-1w1 + C-1w2**, not before. Attempting 1d now would either fail
the output-equivalence gate or silently change invoice good_ids.

**1d verdict: NOT ATTEMPTED — deferred behind the write slices.** No proforma code
mutated (customs-value-freeze honored by not touching it). Output-equivalence
harness + a mirror-completeness proof are prerequisites, best built as part of the
1d run once the mirror is authoritative.

## STAGE 2 — residual declaration (pin xfail = 3 files)

Post-STAGE-1 pin baseline = **3** {routes_proforma, routes_wfirma_capabilities,
routes_wfirma}. Work orders:

1. **C-1w1 — proforma write** (`wfdb.upsert_product` @4527) → route the product
   write through the Master/mirror so a proforma-created good is mirrored.
2. **C-1w2 — capabilities write path** — create_good_from_product_code / adopt /
   update_and_adopt / create_and_adopt (`create_product`/`edit_product`/
   `upsert_product`) + the inseparable pre-write `get_product_by_code` reads
   (@515, 700, 822, 962) + `wfdb.get_products_batch/get_product` (@1101, 1307) →
   route through the Master/mirror.
3. **routes_wfirma reads+writes (added residual, from STAGE 0)** — 5 `wfdb` reads
   (get_product, get_products_batch, list_products) + 3 `upsert_product` writes,
   the C-1b-deferred deprecating-reader path.
4. **1d — proforma reads (~12)** — deferred BEHIND #1–#3 (mirror must be complete
   first); done with the output-equivalence gate.

**Recommended sequence:** C-1w1 → C-1w2 → routes_wfirma → then 1d proforma reads
(now value-safe against a complete mirror) → C-1d verification audit. Each write
slice makes the mirror more complete; 1d closes last.

No deploy. No "PZ" rename (R1).
