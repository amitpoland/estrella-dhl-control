# PZ Import Processor

Reads Estrella Jewels supplier invoice PDFs + a ZC429/SAD customs PDF,
fetches the correct NBP USD/PLN exchange rate, calculates landed costs,
and prints a wFirma.pl-ready PZ document.

---

## System invariants

These must never change without a deliberate, tested decision:

| Invariant | Where enforced |
|---|---|
| `process_batch()` is the **only** calculation path | `test_pz_regression.py` — all output values traced back to it |
| `golden_constants.py` is the **only** source of reference values | Imported directly; no inline numbers in the test file |
| All outputs (PDF / XLSX / clipboard) render from the **same result object** | Single `_result` dict passed to every export step in `main()` |
| `verify.sh` (or `make verify`) must pass before any live batch | Release rule below; pre-commit hook in `hooks/pre-commit` |
| `golden_constants.py` changes only after tests **first go red** on new data | Commit template in the file header; pre-commit hook blocks if tests fail |

If any of these is violated, the system's correctness guarantees no longer hold.

---

## Release rule

> **`python3 test_pz_regression.py` must pass (exit 0) before any live batch is processed.**

If the unit tests fail, the parser or formula has regressed. Do not run against new invoices until all tests are green.

## Operational rules (hard stops during live batch generation)

Never generate or submit a PZ document if either condition is true:

**1. Corrections log contains a blocked phrase**

The processor writes warnings to `corrections_log`. The following phrases indicate a parse failure or forced fallback — they are never expected in clean data:

```
reparsed · not found · suspicious · failed · invalid · manual entry · could not
```

"Filename date differs" warnings are expected and safe. Everything else is a hard stop.

**2. CIF-to-SAD reconciliation exceeds ±1 USD**

The sum of all invoice CIF values must match the value declared in the ZC429 customs document within 1 USD. A larger gap means a missing invoice, a duplicate invoice, or a parsing error in invoice totals.

Both conditions are enforced automatically by `test_pz_regression.py --e2e`. The same logic should be applied manually if the processor is run outside the test harness.

---

## Canonical run command

```bash
# 1. Verify no regression (unit + format tests — fast, no PDFs needed)
python3 test_pz_regression.py          # or: make verify

# 2. Generate PZ for a new batch — full output in one command
python3 pz_import_processor.py \
    --invoices ./batch/ \
    --zc429    ZC429_xxx_PL.pdf \
    --clipboard \
    --pdf      PZ_039_044.pdf \
    --xlsx     PZ_039_044_calc.xlsx \
    --doc-no   "PZ 12/3/2026"
```

`--clipboard` copies the wFirma-ready table + UWAGI to the macOS clipboard (pbcopy).  
`--pdf` and `--xlsx` are required deliverables — the run exits non-zero if either is not produced.  
`--doc-no` sets the document number in the PDF header and workbook Summary sheet.

Pass `--rate 3.6506` to override the NBP fetch with a fixed exchange rate:

```bash
python3 pz_import_processor.py \
    --invoices ./batch/ \
    --zc429    ZC429_xxx_PL.pdf \
    --rate     3.6506
```

Folder mode: `--invoices ./batch/` reads all `*.pdf` files from the folder, sorted alphabetically.

---

## Golden regression test (full)

```bash
# Unit + format checks + end-to-end PDF pipeline against shipment 039–044
python3 test_pz_regression.py --e2e
```

Expected output: `90/90 tests passed | 0 failed`

The `--e2e` run calls `process_batch()` on the real PDFs with `rate=3.6506` and asserts:

| Check | Golden value |
|---|---|
| Line count | 16 |
| Razem netto | 49 668,46 PLN |
| Razem brutto | 61 092,21 PLN |
| Duty A00 | 1 225,00 PLN |
| All 16 Cena netto per unit | ±0.05 PLN vs workbook |

---

## Project files

| File | Purpose |
|---|---|
| `pz_import_processor.py` | Main engine — parsing, cost calculation, CLI (steps 1–10) |
| `pz_pdf_export.py` | PDF renderer (`save_pz_pdf`); requires `reportlab` |
| `pz_dual_export.py` | XLSX audit workbook + combined `save_pz_outputs`; requires `openpyxl` |
| `golden_constants.py` | Pinned reference values — treat as a ledger, never edit without a validated workbook |
| `test_pz_regression.py` | 90-test regression suite across 15 sections |
| `verify.sh` | One-shot gate script (`./verify.sh` fast, `./verify.sh --full` with PDFs) |
| `Makefile` | `make verify` / `make verify-full` shortcuts |
| `CLAUDE_PZ_IMPORT_PROCESSOR_WITH_MEMORY.md` | Locked parser rules (retained corrections) |
| `PZ_calculation_template_39_44.xlsx` | Audit reference workbook (validated 2026-04-22) |

```
pip install pdfplumber requests reportlab openpyxl
```

---

## Cost formula chain

```
FOB (USD)
  + Freight + Insurance (per invoice, allocated proportionally to lines)
= CIF (USD)

CIF (USD) × NBP rate
= Value before duty (PLN)

Value before duty (PLN) × duty_rate
  where duty_rate = A00_PLN / total_before_duty_PLN
= Allocated duty per line

Value before duty + Allocated duty
= Netto per line

Netto per line × 1.23
= Brutto per line
```

**Critical rule:** Shipping ($15 freight + $10 insurance per invoice) is allocated
*within each invoice* by item FOB share — not spread globally across all invoices.

---

## Locked parser rules (from validated batch 039–044)

1. **Quantity** — always the field after the second UOM token (`PCS`/`PRS`) on the item line
2. **A00 duty** — use `stawka opł.:` value only; never the `Kwota:` taxable base
3. **LRN** — supports bracketed format `Numer LRN [12 09]: 26S00Q8O0S`
4. **Invoice date** — always from PDF body; filename date is ignored if different
5. **Silver items** — use `Silver Plain` family with `WISIOREK SREBRNY PRÓBY 925` template
6. **Sanity aborts** — quantity matching an HSN code, or duty rate > 20%, aborts with an error

---

## Dependencies

```bash
pip3 install pdfplumber requests
```

Python ≥ 3.9 required.
