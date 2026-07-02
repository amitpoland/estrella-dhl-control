# C-2c — Customer Authority verification sweep (build record)

- **Date:** 2026-07-03 · verify-tree only, NO deploy · closes C-2 (C-2a → C-2b → C-2c)
- **R1:** service/tests/test_master_consumption_rule.py (additive pin) + this record.

## Sweep (comment-stripped, all of service/app)

Direct wFirma customer API call sites (`search_customer` / `fetch_contractor_by_id` /
`create_customer`) remaining after C-2b, by file:

| File | Sites | Disposition |
|---|---|---|
| routes_wfirma_capabilities.py :294, :1525, :1564 | contractor probe (read) + customer sync/create tooling | wFirma-setup/diagnostic surface — "wFirma-facing by purpose, NOT counted as violations" (audit §Q3-amend); create path flag-gated |
| wfirma_customer_auto_resolve.py :345 area, :1134 | auto-resolve machinery + single gated create | customer SYNC layer — analog of wfirma_product_auto_register (whitelisted in the product pin) |
| routes_customer_master.py | own-sync fetches | the Master's own sync (authority doing its job — V7 design-debt note; mirror-layer insertion is future work, not a C-2 violation) |
| routes_proforma.py :3010 | comment only | not code |

**Zero business-module violations.** V4 (proforma), V5 (ledgers), V7 (suppliers)
all clean post-C-2b.

## New standing pin

`test_no_business_module_calls_wfirma_customer_apis` — full `app/**` sweep;
whitelist `_CUSTOMER_SYNC_WHITELIST` = {wfirma_client, wfirma_db,
customer_master_db, reservation_db, wfirma_customer_auto_resolve,
routes_customer_master, routes_wfirma_capabilities}. Any new direct customer
call outside the sync layer fails immediately (no baseline — starts at zero).

## Verification

- Pin suite 11/11 (was 10; +1 full-sweep customer pin).
- Constitution §3 chain state after C-2: business modules → Customer Master
  passthroughs → wfirma_client. Mirror re-pointing (passthroughs consult
  wfirma_customer_mirror before live wFirma) remains future equivalence-gated
  work — C-2a built the mirror + backfill; the resolver chain is unchanged.

## NOT in this slice

No code changes to any route/service. No cache retirement (wfirma_customers /
wfirma_customer_mapping stay until the mirror re-pointing slice). No deploy.
