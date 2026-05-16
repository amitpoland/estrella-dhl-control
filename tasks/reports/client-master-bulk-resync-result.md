# Bulk re-sync RESULT — B0 Client Master

**Date:** 2026-05-17 (initial pass) + 2026-05-17 (second-pass verification)
**Production SHA:** `ab5aabe` (PR #155 unchanged; this is a data-only operation)
**Service:** PZService RUNNING; local + public health 200 / 200
**Mode:** WRITE applied per-id; one wfirma_id per apply call

## Second-pass verification (run on operator re-request)

Re-scanned `customer_master` after the initial pass. 14 rows still appear
in the candidate-detection bucket (any of `bill_to_street`, `bill_to_city`,
`bill_to_postal_code`, `bill_to_email`, `default_language_id` empty):

| Bucket | Count | Status |
|---|---|---|
| Real wFirma contractors with one or more fields still empty | **10** | **Cannot be filled** — wFirma itself does not surface those values for the contractor |
| Synthetic test rows (`TEST-MD2-SMOKE`, `BATCH0-SMOKE-TEST`, `OSO-SMOKE-CM`, `B2-PROD-SMOKE`) | **4** | NOT FOUND in wFirma — `customer_master` rows left untouched |

Spot-probe evidence (live `contractors/get`):
- `64174775` BJB LTD (GB): wFirma `email=''`, `translation_language=''` → cannot fill these two locally
- `66503189` Queenhart (GB): wFirma `email=''`, `zip=''`, `translation_language=''` → cannot fill any of the three locally
- `58541318` MDS (FR): wFirma `translation_language=''` (email already filled in row) → cannot fill language

**Conclusion: bulk re-sync is at wFirma's ceiling.** Re-running apply for
the 10 real residual rows would be a no-op (COALESCE-NULLIF requires both
the local and incoming value to be non-empty; if wFirma has no value, no
write happens). No additional apply calls were issued in the second pass.

## Summary

| Metric | Value |
|---|---|
| Rows inspected (baseline snapshot) | 26 |
| Rows already enriched (skipped) | 1 (Railing 75483443) |
| Resync candidates | 25 |
| Synthetic test IDs (NOT FOUND in wFirma — skipped) | 4 |
| **Real apply candidates** | **21** |
| Applied successfully (`mode=write, updated=1` each) | **21 / 21** |
| Errors | **0** |
| New rows inserted | **0** (only updates — matches the "no bulk create" rule) |
| True preservation violations | **0** |

## Aggregate fills across the 21 rows

| Field | Rows filled | Notes |
|---|---|---|
| `bill_to_street`      | **21** | every contractor had a street |
| `bill_to_city`        | **21** | every contractor had a city |
| `bill_to_postal_code` | **20** | one wFirma contractor has empty zip |
| `bill_to_email`       | **2**  | most already had email from PR #152 deep-fetch |
| `bill_to_phone`       | **14** | filled only where local was empty |
| `default_language_id` | **11** | rest carry no language preference in wFirma |
| `payment_terms_days`  | **16** | filled from wFirma `<payment_days>` (7/14/30/60/90 day values) |
| `bank_account`        | 0      | wFirma did not surface for any candidate |
| `regon`               | 0      | wFirma did not surface for any candidate |

## Preservation guarantee (verified)

For each of the 21 updated rows, the following operator-managed columns
were checked pre-write vs post-write. **Zero true violations**:

- `freight_service_id` ✓ byte-identical
- `insurance_rate`     ✓ byte-identical
- `kyc_status`         ✓ byte-identical
- `default_currency`   ✓ byte-identical (when pre-set was non-empty)

A naïve diff counted 16 transitions on `payment_terms_days` (empty → wFirma
value); these are **legitimate fill-when-empty** writes per the documented
`COALESCE(payment_terms_days, ?)` rule. They are NOT violations: the column
was NULL pre-write and the operator had not set it locally.

Railing (excluded from resync — already enriched in PR #154) is byte-identical:
`freight_service_id=13002743`, `insurance_rate=0.0035`, `kyc_status=approved`,
`bill_to_street="302, KUSHWAH CHAMBERS,MAKWANA ROAD,MAROL NAKA,"`.

## Per-row outcome

| wfirma_id | country | filled |
|---|---|---|
| 38533544  | CZ | street, city, postal, phone, language |
| 58541318  | FR | street, city, postal, phone |
| 38533073  | FR | street, city, postal, phone, language |
| 188756259 | FI | street, city, postal |
| 66503189  | GB | street, city, phone |
| 63089035  | LV | street, city, postal |
| 65559320  | PL | street, city, postal, phone |
| 63091846  | LV | street, city, postal |
| 43469333  | FI | street, city, postal |
| 66074282  | FI | street, city, postal, phone |
| 190263843 | PL | street, city, postal, phone, language |
| 43467668  | EE | street, city, postal, phone, language |
| 38184104  | LV | street, city, postal, phone, language |
| 38582303  | NO | street, city, postal, phone, language |
| 38533856  | EE | street, city, postal, language |
| 182241571 | BE | street, city, postal, phone, language |
| 61633007  | EE | street, city, postal, phone, language |
| 90484280  | NL | street, city, postal, email, phone, language |
| 64853396  | SE | street, city, postal |
| 145067816 | FI | street, city, postal, email, phone, language |
| 64174775  | GB | street, city, postal |

## Synthetic / test IDs intentionally skipped

| wfirma_id | reason |
|---|---|
| TEST-MD2-SMOKE       | NOT FOUND in wFirma (synthetic) |
| BATCH0-SMOKE-TEST    | NOT FOUND in wFirma (synthetic) |
| OSO-SMOKE-CM         | NOT FOUND in wFirma (synthetic) |
| B2-PROD-SMOKE        | NOT FOUND in wFirma (synthetic) |

Their `customer_master` rows are untouched and still present.

## Side-effect checks

- stderr clean (uvicorn startup lines only)
- wFirma-write / finance_dual_write / create_contractor log entries: **0**
- No bulk Assign-all triggered; each apply was scoped to exactly one wfirma_id
- No new clients created from wFirma (`inserted=0` across all 21 calls)

## Tests

- `python test_pz_regression.py`: **160/160 pass**
- `python service/scripts/campaign_status.py doctor`: clean

## Output artefacts

- `.cm-baseline.json` — 26-row pre-write snapshot
- `.cm-dryrun.json` — 25-row deep-fetch + diff plan (dry-run)
- `.cm-apply-ids.txt` — 21 wfirma_ids slated for apply
- `.cm-apply-results.json` — per-id apply outcomes
- `.cm-postwrite.json` — per-row fill diff
- `tasks/reports/client-master-bulk-resync-dryrun.md`
- `tasks/reports/client-master-bulk-resync-result.md` (this file)

## Final verdict

```
Rows inspected   : 26
Rows updated     : 21
Rows skipped     : 5  (1 already-enriched Railing + 4 synthetic test IDs)
Fields filled    : 105 individual column writes across the 21 rows
                   (21×street + 21×city + 20×postal + 11×language +
                    14×phone + 2×email + 16×payment_terms = 105)
Fields preserved : 0 true violations (4 operator-owned fields verified
                   byte-identical across all 21 rows)
Errors           : 0
Logs             : clean; no wFirma write entries
Tests            : PZ 160/160; doctor clean
Final verdict    : BACKFILL COMPLETE
```

## Deferred — B0 dictionary refresh (live wFirma)

The user brief tail mentioned: live invoice series / proforma series / languages
dropdown labels. Scope notes for a follow-up batch:

- wFirma `contractors/get` does NOT expose `invoiceseries_id` or
  `proformaseries_id` at the contractor level (verified live on Railing
  in PR #154). Series and language catalogs would have to come from
  separate wFirma endpoints (`invoiceseries/find`, `proformaseries/find`,
  `languages/find`), none of which has a verified parser in
  `service/app/services/wfirma_client.py` yet.
- Baseline dictionary is in place (PR #153, `wfirma_dictionary_cache.py`)
  serving 3 VAT modes, 6 currencies, 7 languages, 1 placeholder series.
  UI dropdowns already render from it.
- The deferred follow-up requires:
  1. probing the three wFirma list endpoints with live credentials
  2. adding three parsers to `wfirma_client.py`
  3. wiring `refresh_from_wfirma()` (currently stub) to call them and
     merge into the in-process cache
  4. exposing a refresh button on the operator UI

That work is **out of scope for this batch** (a data-backfill batch).
Schedule as a separate runtime PR once operator approves the wFirma
endpoint probe.
