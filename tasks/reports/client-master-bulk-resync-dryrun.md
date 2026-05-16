# Bulk re-sync DRY-RUN report — B0 Client Master

**Date:** 2026-05-17
**Production SHA:** `ab5aabe` (PR #155 — Client Profile UI polish)
**Service:** PZService RUNNING; local + public health 200 / 200
**Mode:** READ-ONLY dry-run. No DB writes performed.

## Scope

Re-sync existing Client Master rows that were assigned before PR #154
(deep-fetch parser + address columns). Goal: backfill the
`bill_to_street / bill_to_city / bill_to_postal_code / bill_to_email /
default_language_id / bill_to_phone / bank_account / regon` columns
from a fresh wFirma deep fetch.

Hard rule: only rows already present in `customer_master` are touched.
No new clients are ever created from this batch (the apply endpoint
inserts only when its proposal status is `new_candidate`; for these
rows the proposal status is `matched_existing` and the path is UPDATE
with `COALESCE(NULLIF(local_col, ''), NULLIF(?, ''))` — operator
values always win).

## Inventory

| Bucket | Count |
|---|---|
| Total `customer_master` rows | 26 |
| Rows with `bill_to_contractor_id` | 26 |
| Already enriched (no candidates) | 1 (Railing — verified post PR #154) |
| **Resync candidates** | **25** |
| ↳ Real wFirma contractors (apply candidates) | **21** |
| ↳ Synthetic/test IDs (not in wFirma — skip) | **4** |

Synthetic IDs that wFirma returns NOT FOUND for (will be skipped):
- `TEST-MD2-SMOKE`
- `BATCH0-SMOKE-TEST`
- `OSO-SMOKE-CM`
- `B2-PROD-SMOKE`

## Field-fill projection (across 21 real candidates)

| Field | Rows wFirma will fill | Rows already non-empty (preserved) |
|---|---|---|
| `bill_to_street`      | **21** | 0 |
| `bill_to_city`        | **21** | 0 |
| `bill_to_postal_code` | **20** | 1 (some contractors have empty zip in wFirma) |
| `bill_to_email`       | **2**  | 11 (already filled by PR #152 deep-fetch path) |
| `default_language_id` | **11** | 0 (10 contractors carry no language preference in wFirma) |
| `bill_to_phone`       | **up to 14** (where local empty) | n/a |
| `bank_account`        | 0 | wFirma did not surface for any candidate |
| `regon`               | 0 | wFirma did not surface for any candidate |

## Preservation guarantees (verified by `upsert_identity_only` COALESCE-NULLIF)

The following columns are NEVER touched on UPDATE — operator-set values
survive byte-identical:

- `freight_service_id`, `freight_fixed_amount_eur/usd`, `freight_mode`,
  `freight_currency`, freight labels
- `insurance_service_id`, `insurance_rate`, `insurance_min_*`,
  `insurance_enabled`, insurance labels
- `kuke_approved`, `kuke_limit`, `kuke_currency`, `kuke_*`
- `kyc_status`, `kyc_approved_on`, `kyc_expiry`, KYC compliance fields
- `vat_mode`, `notes`, `ship_to_*`
- `default_currency`, `payment_terms_days` if already non-empty
- `preferred_proforma_series_id`, `preferred_invoice_series_id` (operator-only)

## Apply candidates (21 wfirma_ids)

```
38533544, 58541318, 38533073, 188756259, 66503189, 63089035, 65559320,
63091846, 43469333, 66074282, 190263843, 43467668, 38184104, 38582303,
38533856, 182241571, 61633007, 90484280, 64853396, 145067816, 64174775
```

By country: PL=7, GB=2, FI=4, SE=1, LV=3, FR=2, EE=3, BE=1, NO=1, CZ=1, NL=1 (Railing IN excluded — already enriched).

## Decision

Proceed to write phase: per-id apply through
`POST /api/v1/customer-master/sync-from-wfirma/apply` with one wfirma_id
per call. Operator values protected by COALESCE-NULLIF.

The 4 synthetic IDs are not present in wFirma and are excluded from the
apply pass. Their `customer_master` rows are not touched.

## Output artefacts

- `.cm-baseline.json` — pre-write snapshot of all 26 rows
- `.cm-dryrun.json` — per-row deep-fetch + diff plan
- `.cm-apply-ids.txt` — 21 wfirma_ids slated for apply
- `tasks/reports/client-master-bulk-resync-result.md` — will be created
  after the write phase
