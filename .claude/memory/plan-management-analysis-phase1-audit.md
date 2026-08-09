# Management Analysis Phase 1 — Shared read-path repair

**Date:** 2026-08-09  
**Worktree:** `C:\PZ-wt\management-analysis-p1` · `feat/management-analysis-phase1` · base `589c2869`  
**UI:** not started (correct). Shared AR facts repaired in-tree.

---

## Pagination root cause

Nested `<page><start>N</start><limit>K</limit></page>` is **ignored** by live wFirma for `invoices/find` (same defect previously proven for `contractors/find` on 2026-05-06). Requests with `start=0|20|40` all returned first id `97820621`.

## Verified bulk paging contract

Sibling parameters at `<parameters>` root:

```xml
<page>N</page><limit>K</limit>
```

- `page` is **1-indexed**
- `limit` is honoured (page 2 limit 10 → 10 rows)
- pages 1/2/3 return distinct first ids after fix: `97820621` / `134828156` / `145598597`

Iterator: `_paginate_find_collection` — stops on empty/short page, safety cap 5000, and when a page yields **no new ids** (broken paging guard). Dedupes by top-level document id.

Accounting Hub `start` offset → `page = start // limit + 1`.

## Payment ISO currency field

Live `payments/find` / `payments/get` leaf set has **no `<currency>` ISO tag**. Present FX fields:

| Field | Meaning |
|---|---|
| `currency_label` | NBP table reference (e.g. `083/A/NBP/2021`) or empty — **not ISO** |
| `currency_exchange` / `currency_date` | rate metadata |
| `value` | amount in **linked invoice document currency** |
| `value_pln` | PLN equivalent when present |

True ISO for a matched payment = linked invoice `<currency>` (USD/EUR/PLN).

## Currency parser fix

`_parse_payment_fact`: stores `currency_label` separately; `currency` only from real ISO `<currency>` (almost never present).  
`aggregate_statement`: match on `invoice/id`; inherit invoice ISO; never bucket under NBP labels; unmatched without ISO → `UNRESOLVED` + `payment_currency_unresolved`.  
Gross authority aligned with Accounting Hub: `brutto` → `total` → `total_brutto` (WDT FX invoices omit `brutto`).

## Type filter root cause (38533544 zero invoices)

Multiple `<condition><field>type</field><operator>eq</operator>…` are **AND**ed → empty set.  
Fix: `<operator>in</operator><value>normal,correction,proforma</value>` (live-proven).

## 38533544 invoice-ID diff

| | Before | After |
|---|---|---|
| Statement invoices (2020-01-01…2021-12-31) | **0** | **32** |
| Payment links outside window | many | **0** |
| Currency keys | NBP labels | **USD** only |
| `payment_links_invoice_outside_window` | yes | **0** |

## Statement period semantics (explicit)

**Period statement model** (unchanged intent, now correctly populated):

- Invoices: issue date in `[from, to]` (Python re-filter)
- Payments: payment date in `[from, to]` (Python re-filter)
- Window is **not** silently broadened when a payment links outside
- Opening-balance model is **not** mixed in

## One-client reconciliation (live, post-fix)

USD: invoiced `92548.72` − credited `2519.00` − received `50928.72` = outstanding `39101.00` (Δ `0.00`).  
Includes 12 `proforma_treated_as_debit` warnings (existing Phase 10B behaviour).

## Open-invoice paymentdate coverage (sibling scan)

697 unique normal invoices / 35 pages: **paymentdate present 697 / missing 0**.  
Open/partial: **42 / 42 have paymentdate (100%)**.

## Tests

`test_ledger_statement_phase10b.py` + `test_ledger_invoice_ledger_phase10a.py` + `test_accounting_hub_p0_normalize.py`: **pass** (incl. NBP-not-ISO, sibling page, type `in`, `total` gross fallback).

## HOLD/GO for Management Analysis UI

**GO** for Phase 1 Management Analysis UI on this branch — the three shared-fact gates pass.  
Still: no wFirma writes, no FX merge, no new accounting DB; portfolio KPIs must continue to reconcile to this statement authority within rounding tolerance before release.
