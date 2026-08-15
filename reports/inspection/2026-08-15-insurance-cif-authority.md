# Insurance Export — CIF field authority reconciliation

**Date:** 2026-08-15
**Tree:** `C:\PZ-verify\.claude\worktrees\beautiful-bardeen-dfb6ac` @ `628f41cf` (branch
`claude/insurance-export-statement-c52527`, PR #1249)
**Source:** live wFirma production account (`C:\PZ\.env`, `ENVIRONMENT=prod`)
**Access:** **READ-ONLY.** `GET invoices/find` (period `2026-05-01`…`2026-05-31`, types
`normal`+`correction`) followed by `GET invoices/get/{id}` per document. No `add`, no `edit`,
no warehouse or accounting writes were issued.

## Why this artifact exists

`insurance_export_statement._build_row()` reads Inv CIF as `fact["brutto"]`, which resolves
through `ledger_aggregator._invoice_gross_raw()` (XML tag preference
`brutto` → `total` → `total_brutto`). The code comment asserted this had been "proven, not
assumed" against four real May-2026 WDT documents, but no evidence artifact existed — the claim
was self-referential and could not be independently re-checked. This artifact replaces the
assertion with a reproducible observation.

## Method

Each document was located by exact `fullnumber` match within the period result set; all four
resolved to exactly one candidate (no ambiguity, no near-miss numbering). The full invoice XML
was then re-fetched by numeric id and read field by field. `observed_cif` is the literal return
value of `_invoice_gross_raw()` on that XML — the same function the report calls, not a
re-implementation. `expected_historical_cif` is the operator-supplied historical statement value.

Reproduce with the same two read-only calls against the four ids below.

## Field-level observations

| document_number | wfirma_invoice_id | currency | `<brutto>` | `<total>` | `<total_brutto>` | `<total_composed>` | Σ line netto | Σ line brutto |
|---|---|---|---|---|---|---|---|---|
| WDT 82/2026 | 464623139 | EUR | ABSENT | 2199.00 | ABSENT | 2199.00 | 2199.00 | 2199.00 |
| WDT 83/2026 | 464998051 | USD | ABSENT | 2686.00 | ABSENT | 2686.00 | 2686.00 | 2686.00 |
| WDT 87/2026 | 467541283 | EUR | ABSENT | 405.00 | ABSENT | 405.00 | 405.00 | 405.00 |
| WDT 89/2026 | 467787875 | USD | ABSENT | 723.55 | ABSENT | 723.55 | 723.55 | 723.55 |

`<netto>` on all four carries the **PLN** conversion, not the document currency, and is therefore
never a CIF candidate. Its observed values (9353.89 / 9765.22 / 1712.50 / 2600.95) are recorded
here only to document that mismatch; they are not CIF.

## Reconciliation

| document_number | chosen_cif_field | expected_historical_cif | observed_cif | match |
|---|---|---|---|---|
| WDT 82/2026 | `<total>` via `_invoice_gross_raw()` | EUR 2,199.00 | EUR 2,199.00 | ✅ |
| WDT 83/2026 | `<total>` via `_invoice_gross_raw()` | USD 2,686.00 | USD 2,686.00 | ✅ |
| WDT 87/2026 | `<total>` via `_invoice_gross_raw()` | EUR   405.00 | EUR   405.00 | ✅ |
| WDT 89/2026 | `<total>` via `_invoice_gross_raw()` | USD   723.55 | USD   723.55 | ✅ |

## Conclusion

```
PROVEN
canonical field = wFirma invoice <total>  (== <total_composed> on all four)
resolved in code by ledger_aggregator._invoice_gross_raw()  (brutto → total → total_brutto)
4/4 historical matches
```

Every sub-claim in the `_build_row()` comment was checked individually and holds on all four
documents: `<brutto>` is absent on WDT invoices; `<netto>` carries the PLN conversion; the
document-currency gross sits in `<total>`; and `<total> == <total_composed> == Σ line netto ==
Σ line brutto` (the latter two coincide because WDT is 0% VAT).

Note for future maintenance: `<total_composed>` **is** present on these documents and equals
`<total>`, but it is not a tag `_invoice_gross_raw()` reads. The equality is an observed property
of wFirma's WDT documents, not a fallback the code relies on.

## Scope and limits

- Four documents, one period (2026-05), two currencies (EUR, USD), all `type=normal`.
  No `correction`-type document is covered by this reconciliation.
- Domestic (PLN, VAT-bearing) invoices are **not** covered here; on those `<brutto>` is present
  and is taken first by the same function. That branch remains pinned by unit tests only.
- Evidence of field identity, not of FX or of the insurance multiplier — those are separate
  authorities (`insurance_fx_provider`, fail-closed).

## PII

Sanitized by construction. Contains document numbers, wFirma numeric invoice ids, currency
codes, and amounts only. No contractor names, addresses, tax ids, emails, raw XML, or
credentials. The raw XML responses were read in a scratchpad process and never written into
this repository.
