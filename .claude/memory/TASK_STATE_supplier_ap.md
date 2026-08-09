# Supplier AP fact audit — status

- **Status:** Fact authority **GO** for Payables UI build (JSX not started)
- **Branch:** `feat/supplier-ap-creditor-aging` @ `e2df8ab8` (= `0274cc34` + charter)
- **Evidence:** `.claude/memory/supplier-ap-fact-audit-v3.json` (scoped)
- **WITHDRAWN:** unscoped false GO — `supplier-ap-fact-audit-v3-WITHDRAWN.md`

## Gate proof — supplier 38142296 (ESTRELLA JEWELS LLP.)

| Metric | USD |
|---|---|
| Expenses | 636 |
| Payments (expense_only) | 555 |
| Gross+ | 3,567,977.34 |
| Credits/CN | 7,787.13 |
| Payments | 2,911,314.71 |
| Outstanding | 656,662.63 |
| Advances | 7,787.13 |
| Net | 648,875.50 |
| Aging Δ | **0.00** |

Aging: not_due 413762 · 1–30 66948 · 31–90 113530 · 91–180 43172 · >180 19250.63

## Proven contracts

- Sibling pagination; nested ignored
- Due field = `payment_date` (100% on scoped set)
- `invoice/id=0` / `expense/id=0` = no link
- `correction=1` → already negative brutto (credit note); do not re-flip
- Expense `<currency>` owns ISO
- wFirma `contractor.id` find filter ignored → client-side contractor filter required
