# C-1c Consumer Migration — scoping + STOP-report (read-only)

- **Date:** 2026-07-03 · read-only scoping, ZERO code mutated · precedes any C-1c edit.
- **Slice:** C-1c — route product READS in the 4 pin-baseline files
  (routes_dashboard, routes_packing, routes_proforma, routes_wfirma_capabilities)
  through the Product Master; goal baseline 4→0.
- **Outcome:** the scoping FALSIFIES the spec's core assumption (that the pin
  baseline = the real product-read surface). STOP-report per §18/§20 + R3.

## The core finding: the pin measures PROSE, the real reads are elsewhere

The precise pin's `table:wfirma_products` dimension matches the literal string
`wfirma_products` on any non-comment/non-docstring line — which includes **status
messages and string-key comparisons**, NOT just table access. Meanwhile the REAL
split-cache reads go through `wfdb.get_product* / list_products` accessors (and one
raw SQL), which contain NO literal `wfirma_products` and are therefore **unflagged**.

| file | pin-flagged site(s) | nature | REAL product reads (UNFLAGGED unless noted) |
|---|---|---|---|
| routes_dashboard | 2415 | status f-string `"…not in wfirma_products"` (PROSE) | **2408 `wfdb.get_product(c)`** (real, unflagged) |
| routes_packing | **2105 `FROM wfirma_products`** | real SQL (flagged — literal in SQL) | 2100-2108 direct `sqlite3` SELECT on wfirma.db (the same site) |
| routes_proforma | 160,1016,1574,2461,5407,5409,5605,5652,5656,7861 | ALL PROSE strings / string-key comparisons | **~12 accessor reads: 151,957,1385,1558,1711,2344,4154,4464,4535,5643,7692,7845** + **write 4527 `wfdb.upsert_product`** (all unflagged) |
| routes_wfirma_capabilities | 310,373,440,515,700,822,962 (`get_product_by_code` reads) + 573,1000 (`create_product`) + 849,1340 (`edit_product`) | real reads + real WRITES | same (flagged) |

Consequences:
1. **"pin baseline 0" ≠ "no direct product reads."** Migrating the real `wfdb`
   accessor reads would NOT change the pin (it doesn't flag them). Reaching pin 0
   means either rewording innocent status strings (gaming the gate) or refining the
   pin to ignore string literals (precision). Neither migrates the real reads.
2. **The real migration surface is larger and mostly unmeasured** — proforma alone
   has ~12 accessor reads + 1 cache WRITE, invoice/XML-adjacent.

## Per-file dispositions

- **routes_packing** — 1 genuine direct-SQL cache read (2100-2108: `SELECT
  product_code, sync_status FROM wfirma_products` — a lane-readiness check). Clean
  migration target: resolve readiness via the Product Master (`status='mapped'`).
  Migrating it also removes the pin hit. **Achievable, low risk.**
- **routes_dashboard** — 1 real read (2408 `wfdb.get_product`, readiness) + 1 prose
  pin hit (2415). Migrating the read is clean; clearing the pin needs the prose
  handled (pin precision, not rewording). **Achievable but needs the pin decision.**
- **routes_proforma** — the real work: ~12 `wfdb.get_product*/list_products` reads
  (readiness/resolution, e.g. 957 checks `wfirma_product_id` + `sync_status=='matched'`
  → Master `status=='mapped'`) + a cache WRITE (4527). Invoice-adjacent →
  customs-value-freeze + output-equivalence gate. Its pin hits are ALL prose.
  **Substantial; scope + the write need confirmation.**
- **routes_wfirma_capabilities** — real product READS (`get_product_by_code` ×7) AND
  real WRITES (`create_product`/`edit_product` — the goods create/adopt endpoints
  behind the PUT catch-all). Rerouting reads leaves the writes flagged → it CANNOT
  reach 0 in a reads-only slice. **R3 STOP-report (operator pre-authorized): needs a
  separate write-reroute slice like C-1b did for routes_wfirma.**

## Recommendation (needs operator ruling before any mutation)

The pin's `table:` dimension should measure REAL access, not prose. Recommended
refined C-1c:

- **Q1 — Pin precision:** refine `table:wfirma_products|_mapping|_mirror` to match
  real access only — raw SQL (`FROM/JOIN/INTO/UPDATE wfirma_products`) **and** the
  split-cache accessor calls (`wfdb.get_product`, `.get_products_batch`,
  `.list_products`) — and NOT string literals. This makes the pin measure the true
  violation surface (proforma's 12 real reads become the flagged target; the prose
  false-positives drop). Positive control extended to prove a real accessor read is
  caught and a prose mention is not. Approve?
- **Q2 — Real read migration:** route the `wfdb.get_product*/list_products` reads
  (+ packing's SQL) through a Product Master accessor (`reservation_db.get_product_master`
  → `status`, + a sync-layer mapping helper where a wfirma_id is genuinely needed).
  Confirm the scope = proforma ~12 (output-equivalence gated) + dashboard 1 + packing 1.
- **Q3 — proforma cache WRITE (4527 `wfdb.upsert_product`):** in or out of C-1c
  (a reads slice)? Recommend **OUT** → a separate write slice.
- **Q4 — wfirma_capabilities:** confirm STOP-report → separate write-reroute slice;
  C-1c reroutes its reads only; it stays in the baseline until that slice. So the
  honest C-1c end-state is **baseline reflecting real reads migrated + pin upgraded**,
  with wfirma_capabilities' WRITES the sole remaining product-authority item.

No code mutated. No file/table containing "PZ" renamed (R1). Awaiting operator
ruling on Q1–Q4 before mutation (esp. proforma — invoice-adjacent).
