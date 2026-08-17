# AP payment→expense repair — 2026-08-17

Campaign continued from FINANCIAL-TRUTH-GATE-AP FAIL. Production SHA remains `b03143ee`. Diamond Point / AR not reopened.

## Root cause

`wfirma_payment_snapshots.expense_id` existed but `insert_payment_snapshot` never wrote it. Local Management Analysis therefore loaded 3023 payments with `linked_expense=""`. Live Supplier Ledger parsed `payment/expense/id` and knocked off correctly.

## wFirma relationship (proven, not guessed)

Field: `payment/expense/id`. Sentinel `0` = no link. Same extractor as `_parse_payment_fact`.

| Supplier | contractor_id | fetched | with expense/id | without |
|---|---|---|---|---|
| ESTRELLA JEWELS LLP | 38142296 | 555 | 555 | 0 |
| Urząd Skarbowy w Nowym Targu | 98777713 | 132 | 132 | 0 |
| EUROPE SIMPLEKS HURTOWNIA | 61517345 | 34 | 34 | 0 |
| Global Jewellery Pvt. Ltd. | 71554001 | 31 | 19 | 12 |
| DHL Express (Poland) | 38567354 | 356 | 356 | 0 |

Evidence: `.claude/memory/WFIRMA-PAYMENT-EXPENSE-PROOF-2026-08-17.json`

## Persistence

Additive column already present. Insert now stores `expense_id`. Re-sync **converges** `expense_id` on existing `payment_id` without duplicating rows or changing `contractor_id`.

Backup: `C:\PZ\storage\payment_state.db.bak-ap-expense-2026-08-17`

## Coverage

| | payments | with expense | without expense |
|---|---|---|---|
| Before | 3023 | 0 | 3023 |
| After contractor backfill | 3023 | 2004 | 1019 |
| After bulk payments/find | 3058 | 2038 | 1020 |

Without expense: 1018 are invoice-linked AR settlements; 2 have neither link (unapplied). None have both invoice and expense ids.

## Five-supplier (local remaining == captured/live remaining)

All PASS at 0.00 delta after DHL cross-contractor payment `232683830` (contractor `59764244`, PLN 1015.87) was linked.

## Full AP Class-C

| Ccy | Live | Local | Δ |
|---|---|---|---|
| CHF | 450.00 | 450.00 | 0.00 |
| EUR | 47,863.88 | 47,863.88 | 0.00 |
| PLN | 16,059.57 | 16,059.57 | 0.00 |
| USD | 732,427.86 | 732,427.86 | 0.00 |

Previous unexplained: EUR −50,930.19 / PLN −1,229,890.72 / USD −3,360,911.36 — eliminated.

Aging invariant `reconciliation_ok` true per currency (live and local).

## AR non-regression

EUR 212,383.49 / PLN 96,077.65 / USD 372,989.49 MATCH vs locked local 2026-08-17.

## Deploy

**Not deployed.** Production runtime is still `b03143ee`. `payment_state.db` on `C:\PZ\storage` **was** converged (local projection write). The persist code must ship or new scheduler inserts will omit `expense_id` again.

Rollback DB: restore `payment_state.db.bak-ap-expense-2026-08-17`.
Rollback code: not on production yet.

Gate JSON: `.claude/memory/FINANCIAL-TRUTH-GATE-AP-POST-REPAIR-2026-08-17.json`

Adversarial review: SHIP WITH MITIGATIONS (no blockers). Pre-deploy mitigations: converge-clear WARNING log; cross-contractor mismatch test pins advisory-only semantics. Finance comms: first post-deploy MA/payables load will show lower open AP (intended).
