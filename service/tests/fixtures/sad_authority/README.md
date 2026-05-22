# SAD invoice-reference authority fixtures

Real-shaped `audit.json` fixtures for exercising
`service/app/services/sad_invoice_authority.py::derive_sad_invoice_authority`
against the four authority status outcomes.

## Why this exists

Production `C:\PZ\storage` contains audits where `zc429` is empty or `None`
(top-level `invoice_reference_check` carries the older flat shape). The
authority function reads from `audit["zc429"]["invoice_refs_method"]` —
no production audit at the time PR #293 merged exercised that contract
end-to-end. Without these fixtures, future SAD-authority regressions
(renderer drift, batch-detail injection breakage, status-string churn)
could ship undetected.

## Synthetic identifiers

All fixtures use synthetic batch / AWB / MRN / LRN values. No real shipment,
contractor, or customs identifier is committed.

| Fixture                       | batch_id                                        | AWB         |
|-------------------------------|-------------------------------------------------|-------------|
| `n935_match.json`             | `SHIPMENT_TEST1111111_2026-05_n935match`        | 1111111111  |
| `n935_absent.json`            | `SHIPMENT_TEST2222222_2026-05_n935absent`       | 2222222222  |
| `inferred_free_text.json`     | `SHIPMENT_TEST3333333_2026-05_inferred`         | 3333333333  |
| `n935_mismatch.json`          | `SHIPMENT_TEST4444444_2026-05_mismatch`         | 4444444444  |

## Expected authority outcomes

| Fixture                       | status                              | source         | references                |
|-------------------------------|-------------------------------------|----------------|---------------------------|
| `n935_match.json`             | `matched_structured_n935`           | `n935`         | `["EJL/26-27/039"]`       |
| `n935_absent.json`            | `n935_absent`                       | `none`         | `[]`                      |
| `inferred_free_text.json`     | `unverified_no_structured_reference`| `advisory_text`| `[]` (inferred excluded)  |
| `n935_mismatch.json`          | `n935_present_mismatch`             | `n935`         | `["EJL/26-27/039"]`       |

## Shape contract

Each fixture is a minimal-but-real `audit.json` dict carrying:

- `batch_id`, `shipment_id`, `awb`, `invoice_names`, `clearance_status` — top-level identity
- `zc429` — populated with the keys the authority reads (`invoice_refs_method`,
  `invoice_refs`, `inferred_refs`) plus realistic neighbours (`mrn`, `lrn`,
  `duty_pln`, `vat_pln`, `cn_code`, `goods_description`, `_parse_meta`) so
  the fixture is shaped like a real `customs_xml_parser` output rather than a
  hand-stripped minimum
- `verification` — populated with `invoice_refs_match` and `parsed_invoice_nos`
  for the N935 paths
- `invoice_reference_check` — older flat-shape mirror, present so callers
  that read both shapes are exercised together

## Loading fixtures into local storage

Use the helper to seed a synthetic batch directory under
`C:\PZ\storage\outputs\` (or your equivalent dev path):

```
python service/tests/fixtures/sad_authority/load_fixture_to_storage.py \
    --fixture n935_match \
    --storage-dir C:\PZ\storage\outputs
```

The helper refuses to overwrite a non-synthetic batch_id and refuses to
write outside a path whose final segment is `outputs`. Read its `--help`
before running against a non-dev storage directory.
