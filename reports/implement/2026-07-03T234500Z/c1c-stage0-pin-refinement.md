# C-1c STAGE 0 — pin refinement + honest baseline (build record)

- **Date:** 2026-07-03 · verify-tree only, NO deploy · STAGE 0 of the operator's
  resumed C-1c plan (ruling recorded in DECISIONS 2026-07-03, verbatim R4).
- **R1 (STAGE 0):** service/tests/test_master_consumption_rule.py + PROJECT_STATE.

## What changed

`test_master_consumption_rule.py` detector refined from the crude/precise
`table:wfirma_products` substring proxy to measure **REAL product-authority
access only** (operator ruling Q1). After stripping comments + docstrings, a
business file is a violation iff it contains:
- **(a) SQL** targeting a split product table — `FROM/JOIN/INTO/UPDATE
  wfirma_products` (or `_mapping` / `_mirror`). Real SQL keywords, never a
  substring inside a status string.
- **(b) accessor** — `.get_product( / .get_products_batch( / .list_products( /
  .upsert_product(` (wfirma_db split-cache).
- **(c) API** — `.get_product_by_code( / .create_product( / .edit_product(`.
Product MASTER accessors (`get_product_master`, `list_product_masters`) are the
correct path and are NOT matched. Prose / status strings / status-keys are
EXCLUDED by construction. **ANTI-GAMING RULE recorded**: editing prose to change
pin counts is forbidden. Positive-control tests: one seeded violation per
category (a/b/c) flags; a prose/status-key/Master-read block does NOT flag.

## Honest baseline (measured across all business routes_*.py)

| file | real-access sites | breakdown |
|---|---|---|
| routes_wfirma_capabilities.py | **22** | get_product 1, get_products_batch 2, list_products 1, upsert_product 7, create_product 2, edit_product 2, get_product_by_code 7 |
| routes_proforma.py | **13** | get_product 9, get_products_batch 2, list_products 1, upsert_product 1 |
| routes_wfirma.py | **8** | get_product 1, get_products_batch 1, list_products 3, upsert_product 3 |
| routes_dashboard.py | **1** | get_product 1 |
| routes_packing.py | **1** | sql:wfirma_products 1 (`SELECT … FROM wfirma_products`) |

**Honest baseline = 5 files** (the prior "4" was the prose-proxy view).
`KNOWN_PRODUCT_VIOLATION_FILES` set to these 5. Pin **8/8** green.

## DEVIATION DISCLOSED — routes_wfirma re-appears (5th file)

The operator's C-1c ruling named **3** read surfaces (packing, dashboard, proforma)
and treated capabilities as the write slice — total 4 files in view. The refined
detector surfaces a **5th: routes_wfirma.py** (8 wfirma_db accessor sites). This is
NOT a regression: C-1b removed routes_wfirma's wFirma **CLIENT** calls
(get_product_by_code / create_product / edit_product) and explicitly LEFT its
wfirma_db **accessor** reads/writes as the "C-1c-deprecating reader path" (recorded
in the C-1b commit + DECISIONS). The refined pin now measures that residual
honestly. routes_wfirma has **5 reads** (get_product 1, get_products_batch 1,
list_products 3) + **3 writes** (upsert_product 3).

## Planned trajectory (STAGE 1 migrates the 3 NAMED read surfaces)

- 1a dashboard (1 read) → 0 → leaves. baseline 5→4.
- 1b packing (1 SQL read) → 0 → leaves. baseline 4→3.
- 1c capabilities READS where separable → its WRITES remain → STAYS (write slice).
- 1d proforma READS (~12) → its 1 WRITE @4527 remains → STAYS (write slice).
Post-STAGE-1 baseline = **3** {proforma (write only), wfirma_capabilities (writes +
any inseparable reads), routes_wfirma (reads + writes)}.

## Residual after STAGE 1 (STAGE 2 work orders)

1. **C-1w1** — proforma cache write @4527 (`wfdb.upsert_product`).
2. **C-1w2** — routes_wfirma_capabilities write path (create/edit/upsert + the
   get_product_by_code reads inseparable from create/edit control-flow).
3. **NEW (needs operator ruling)** — routes_wfirma wfirma_db reads (5) + writes (3).
   NOT in the operator's named C-1c scope; disclosed here as an added residual —
   fold its READS into C-1c, or give it its own read+write slice. Awaiting direction
   (does not block STAGE 1 on the 3 named files).

No code migrated in STAGE 0 (detector only). No deploy. No "PZ" rename (R1).
