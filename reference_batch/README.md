# Reference batch — Shipment 039–044

This directory holds the validated reference inputs and outputs for the golden batch
(Estrella Jewels shipment 039–044, invoice date 2026-04-10).

Its purpose is **human inspection**, not automated testing.
Automated tests live in `test_pz_regression.py` with constants in `golden_constants.py`.

---

## Expected contents

```
reference_batch/
  invoices/
    039 Invoice EJL-26-27-039-10-04-26.pdf
    040 Invoice EJL-26-27-040-10-04-26.pdf
    041 Invoice EJL-26-27-041-11-04-26.pdf
    042 Invoice EJL-26-27-042-10-04-26.pdf
    043 Invoice EJL-26-27-043-10-04-26.pdf
    044 Invoice EJL-26-27-044-10-04-26.pdf
  ZC429_26PL44302D008N8OR0_1_PL.pdf
  expected_PZ.pdf
  expected_calc.xlsx
  README.md                        ← this file
```

### What goes here

| File | Source |
|---|---|
| `invoices/*.pdf` | Original supplier invoices from Estrella Jewels LLP |
| `ZC429_*.pdf` | Customs clearance document from ZC429 / SAD |
| `expected_PZ.pdf` | PDF produced by `save_pz_pdf()` on the validated batch |
| `expected_calc.xlsx` | Workbook produced by `export_pz_calculation_xlsx()` on the validated batch |

---

## How to regenerate the expected outputs

Run this after confirming `make verify` passes (90/90 tests green):

```bash
python3 pz_import_processor.py \
    --invoices reference_batch/invoices/ \
    --zc429    reference_batch/ZC429_26PL44302D008N8OR0_1_PL.pdf \
    --rate     3.6506 \
    --pdf      reference_batch/expected_PZ.pdf \
    --xlsx     reference_batch/expected_calc.xlsx \
    --doc-no   "PZ — Shipment 039–044 (reference)"
```

The `--rate 3.6506` pin ensures the output is deterministic and matches
the golden constants (NBP Table 069/A/NBP/2026, date 2026-04-09).

Do **not** regenerate with a live NBP rate — the output would differ from the
pinned values in `golden_constants.py` and would not serve as a stable reference.

---

## What a future operator uses this for

A new operator, or someone debugging a calculation discrepancy, can:

1. Open `expected_PZ.pdf` and `expected_calc.xlsx` to see what correct output looks like
2. Run the regeneration command to reproduce them
3. Compare the reproduced files against the stored ones — if they differ, something changed
4. Trace any discrepancy back to `golden_constants.py` and the source workbook

This directory is the concrete, human-readable proof that the pipeline produces
correct output on known input. The test suite verifies it programmatically;
this directory verifies it visually.

---

## Batch metadata (pinned)

| Field | Value |
|---|---|
| Invoices | EJL/26-27/039 – EJL/26-27/044 |
| Invoice date | 10-04-2026 |
| MRN | 26PL44302D008N8OR0 |
| LRN | 26S00Q8O0S |
| Clearance date | 15-04-2026 |
| NBP Table | 069/A/NBP/2026, date 2026-04-09 |
| Rate | 1 USD = 3.6506 PLN |
| Duty A00 | 1 225,00 PLN |
| Razem netto | 49 668,46 PLN |
| Razem brutto | 61 092,21 PLN |
| Lines | 16 |
