# Phase 10B — Statement-of-Account Architecture

**Status:** Design pinned. Not yet implemented.

**Predecessors:**
- `docs/WFIRMA_LEDGER_REPORT_RESEARCH.md` — concluded "build custom"
  (Architecture D), wFirma offers no statement / ledger / balance
  endpoint and its UI cannot be embedded cross-origin.
- `docs/WFIRMA_PAYMENTS_PROBE_EVIDENCE.md` — Phase 10A.5 live probe
  confirming `payments/find` schema and filter acceptance, with
  invoice-side payment-state fields still unverified for a real id.
- `service/app/services/ledger_aggregator.py` — Phase 10A invoice
  ledger aggregator already in production; Phase 10B extends it.

**Successors (NOT in scope here):**
- Phase 10C — PDF renderer for Statement.
- Phase 10D — Dashboard surface for Statement.
- Phase 10E — Supplier-side ledger (mirror of this design over
  `expenses/find` + `payments/find` filtered by `expense/id`).


## 1. Decision

**Build custom. Architecture D — Hybrid: payments-driven aggregator
plus per-invoice PDF drill-down via the Phase 8
`invoices/download/{id}` proxy.**

The Statement of Account is computed by our backend from two wFirma
reads (`invoices/find`, `payments/find`) and emitted as JSON. wFirma
itself has no statement endpoint to embed, proxy, or wrap. The
embedding-feasibility analysis is in `WFIRMA_LEDGER_REPORT_RESEARCH.md`
§3 — both iframe and HTML-proxy paths are blocked at the protocol or
auth layer.


## 2. Verified evidence

The aggregator may rely on, and only on, the following fields. Every
other field that wFirma might surface is treated as unverified.

### 2.1 `<invoice>` element — verified by Phase 9 + the Phase 10A.5 baseline

| Field | Source of truth |
|---|---|
| `<id>` | snapshot tool, Phase 5/9 wrappers, Phase 10A.5 evidence |
| `<fullnumber>` | snapshot tool line 276; Phase 9 `_extract_fullnumber` |
| `<type>` | snapshot tool line 277 (`normal` / `correction` / `proforma`) |
| `<date>` | snapshot tool line 278 |
| `<currency>` | snapshot tool line 279 |
| `<netto>` | snapshot tool line 285 |
| `<brutto>` | snapshot tool line 286 |
| `<contractor>/<id>` | `parse_invoice_element` line 203-204 |

### 2.2 `<payment>` element — verified by Phase 10A.5 live probe

| Field | Evidence |
|---|---|
| `<id>` | leaf-tag inventory in evidence file |
| `<invoice>/<id>` | same |
| `<value>` | same |
| `<value_pln>` | same |
| `<date>` | same |
| `<currency_label>` | same |

### 2.3 `payments/find` filter shapes — verified by Phase 10A.5 live probe

- no filter → status `OK`, returns full collection (paginated)
- `contractor_id` `eq` → status `OK`, filter honoured (zero matches for
  placeholder = filter is applied, not silently dropped)
- `invoice_id` `eq` → status `OK`, filter honoured
- `date` `ge` / `le` → status `OK`


## 3. Forbidden assumptions

The aggregator MUST NOT consult, branch on, or surface any of these
invoice-side fields. Their presence and semantics are not verified in
this codebase as of the Phase 10A.5 placeholder-id run.

| Field | Reason it is forbidden |
|---|---|
| `<paymentstate>` | unverified on real `invoices/get` response |
| `<alreadypaid>` | unverified |
| `<remaining>` | unverified |
| `<paid_date>` | unverified |
| `<paymentdate>` (due date) | unverified — see §7 for fallback |

If a future real-id Phase 10A.5 follow-up confirms these fields, this
document is updated and the aggregator MAY add them as **secondary
cross-checks**. Until then, every value the Statement reports is
derived only from the §2 verified set.

`FORBIDDEN_ENTRY_FIELDS` in `ledger_aggregator.py` already pins this
contract for the Phase 10A invoice ledger; Phase 10B extends the same
list to the Statement output.


## 4. Data model

```jsonc
{
  "contractor": {
    "wfirma_contractor_id": "C-123",
    "name":     "Maison Aurélie",
    "country":  "FR",
    "vat_id":   "FR12345678901"
  },
  "generated_at": "2026-05-09T10:00:00Z",
  "period":       { "from": "2025-11-01", "to": "2026-05-09" },
  "currencies":   ["EUR", "USD"],     // sorted, only currencies with activity

  "entries_per_currency": {
    "EUR": [
      // Invoice entry (debit)
      {
        "type":          "invoice",     // invoice | correction | proforma | payment
        "wfirma_doc_id": "INV-9001",
        "doc_number":    "FV 92/2026",
        "date":          "2026-04-12",
        "currency":      "EUR",
        "debit":         "1500.00",     // invoice → debit
        "credit":        "0.00",
        "running_balance": "1500.00"    // chronological, per currency
      },
      // Payment entry (credit)
      {
        "type":            "payment",
        "wfirma_doc_id":   "PAY-3001",
        "doc_number":      "",          // payments don't have fullnumber
        "linked_invoice":  "INV-9001",  // <invoice>/<id> from <payment>
        "date":            "2026-04-30",
        "currency":        "EUR",
        "debit":           "0.00",
        "credit":          "1000.00",
        "running_balance": "500.00"
      }
    ]
  },

  "totals_per_currency": {
    "EUR": {
      "invoiced":    "1500.00",   // Σ invoice + correction + proforma debits
      "credited":    "0.00",      // Σ negative invoices (credit notes)
      "received":    "1000.00",   // Σ payment credits
      "outstanding": "500.00",    // invoiced - credited - received
      "entry_count": 2
    }
  },

  "aging_per_currency": {
    "EUR": {
      "method":  "invoice_age",   // invoice_age | due_date — see §7
      "current": "0.00",
      "1_30":    "500.00",
      "31_60":   "0.00",
      "61_90":   "0.00",
      "90_plus": "0.00",
      "total":   "500.00"
    }
  },

  "unmatched_payments_per_currency": {
    "EUR": []                     // payments whose <invoice>/<id> is empty
  },

  "warnings": [
    // Free-text strings the aggregator emits for operator attention
    // (overpayment on INV-9001, unmatched payment PAY-3050, etc.)
  ]
}
```

Decimals are emitted as quantised-2dp strings (matches Phase 10A
contract).


## 5. Reconciliation algorithm

Pure function `aggregate_statement(contractor_meta, invoice_nodes,
payment_nodes, statement_date, period)`.

```
1. parse_invoices(invoice_nodes)   → list of InvoiceFact dicts
2. parse_payments(payment_nodes)   → list of PaymentFact dicts
3. for each currency in (invoice currencies ∪ payment currencies):
     entries = []
     for inv in invoices_in(currency, sorted by date asc):
        debit  = inv.brutto                 // gross
        credit = 0
        entries.append(invoice_entry(inv, debit, credit))
     for pay in payments_in(currency, sorted by date asc):
        debit  = 0
        credit = pay.value
        entries.append(payment_entry(pay, debit, credit))
     entries.sort(key=(date, type, doc_id))     // see §5.1
     running = Decimal("0")
     for e in entries:
        running += e.debit - e.credit
        e.running_balance = q2(running)
4. compute totals_per_currency(entries)
5. compute aging_per_currency(invoices, payments, statement_date)
6. collect unmatched_payments_per_currency
7. collect warnings (overpayment, negative running balance, etc.)
```

### 5.1 Sort tie-break

Within a currency:
- primary: `date` ascending
- secondary: `type` rank — `invoice` (0) < `correction` (1) <
  `proforma` (2) < `payment` (3). This forces a same-day invoice to
  appear *before* its same-day payment so the running-balance line
  reads correctly.
- tertiary: `wfirma_doc_id` ascending — deterministic.


## 6. Payment aggregation strategy

**Source-of-truth field for "amount paid against invoice X":**

```
paid_against(X) = Σ payment.value
                  for payment in payments_for_contractor(X.contractor_id)
                  where payment.invoice/id == X.id
                    and payment.currency_label == X.currency
```

**Rationale:**

- We do not trust `<alreadypaid>` on the invoice (forbidden per §3).
- `payments/find?invoice_id=...` is verified to filter (Phase 10A.5).
- We additionally enforce `currency_label == invoice.currency` because
  wFirma allows payments in mixed currencies (e.g. EUR invoice paid
  with a PLN bank-side cashbox movement). Cross-currency payments
  surface as **unmatched** (§9), not silently summed against the
  invoice.

**`remaining_for(X)`:**

```
remaining_for(X) = X.brutto - paid_against(X)
```

If `remaining_for(X) < 0` → overpayment. See §9.

If `remaining_for(X) == X.brutto` → fully unpaid.

If `0 < remaining_for(X) < X.brutto` → partial payment.

**Performance note:** the route fetches `invoices/find` once and
`payments/find` once per contractor and walks them in O(n+m). No
per-invoice round-trip.


## 7. Aging algorithm

The wFirma API's `<paymentdate>` (due date) field is **NOT** verified
on `invoices/find` responses for this codebase. Phase 10B therefore
ships the **invoice-age** aging method by default, with an explicit
`method: "invoice_age"` label on the response.

If a future Phase 10A.5 real-id probe confirms `<paymentdate>` is
present, the algorithm switches to **due-date aging** and the label
becomes `method: "due_date"`. Operators see which method generated
their bucket totals.

### 7.1 Bucketing — invoice-age aging (default)

For each invoice with `remaining_for(X) > 0`:

```
days_old = (statement_date - invoice.date).days
bucket   = "current"   if days_old ≤ 0
         | "1_30"      if 1  ≤ days_old ≤ 30
         | "31_60"     if 31 ≤ days_old ≤ 60
         | "61_90"     if 61 ≤ days_old ≤ 90
         | "90_plus"   if days_old > 90
```

`remaining_for(X)` (not `brutto`) contributes to the bucket — partial
payments correctly reduce their invoice's contribution.

### 7.2 Bucketing — due-date aging (only when due date is verified)

Same buckets but using `(statement_date - invoice.paymentdate).days`.

### 7.3 Honesty rule

The output **always** carries `aging_per_currency.<ccy>.method`.
Operators must be able to tell whether they're looking at "money
overdue against contractually-agreed terms" (due-date aging) or "money
owed but timing depends on terms we couldn't read" (invoice-age aging).
Mixing the two methods in one report is forbidden.


## 8. Corrections and credit notes

wFirma's `<type>` discriminates:
- `normal` — sales invoice. Treat as positive debit (`+brutto`).
- `correction` — sales-invoice correction (`faktura korygująca`).
  May carry a positive OR negative `<brutto>`. Treat as debit
  signed-as-given. A negative correction (credit note) reduces the
  contractor's debit and contributes to `totals.credited`.
- `proforma` — proforma invoice. Treated as a debit by default (it's
  an obligation, not a settled sale). Emitted with type=`proforma`
  in entries so operators can distinguish.

**No special handling for "credit note" beyond reading the sign.**
wFirma does not have a separate `<type>credit_note</type>`; the
sign of `<brutto>` on a `correction` is the signal.

### 8.1 Cross-reference handling

A correction in wFirma references the original invoice via a
`<correction_invoice>/<id>` element on the corrected document. Phase
10B does **not** parse that link — it reports the correction as its
own entry. The dashboard or PDF (Phase 10D / 10C) may surface the
linkage; the JSON aggregator does not need to.


## 9. Overpayments and unmatched payments

### 9.1 Overpayment on a single invoice

If `paid_against(X) > X.brutto`:
- `remaining_for(X) < 0`. The invoice contributes `0` to the aging
  bucket (clamped at `Decimal("0")`).
- The excess `(paid_against(X) - X.brutto)` is reported as a warning:
  `"overpayment_on_invoice"` with `wfirma_doc_id` and amount.
- `totals.received` keeps the full `paid_against(X)` — the operator
  sees the actual money received.
- `totals.outstanding` may go **negative** in this case. That is
  intentional — it surfaces "we owe the customer money".

### 9.2 Unmatched payments

A payment with empty or missing `<invoice>/<id>` cannot be reconciled
to a specific invoice. It still belongs in the per-contractor
ledger.

- The payment IS added to the running balance (as a credit).
- It IS added to `totals.received`.
- It is ALSO listed in `unmatched_payments_per_currency.<ccy>` with
  its `wfirma_doc_id`, `value`, `date`, `currency_label`.
- A warning of type `"unmatched_payment"` is emitted.

The operator's responsibility is to either (a) link the payment to
an invoice in wFirma's UI, or (b) confirm it is an on-account credit.

### 9.3 Cross-currency mismatch

A payment whose `<currency_label>` does not match its linked invoice's
`<currency>` is treated as **unmatched**:
- It does NOT reduce the linked invoice's `remaining_for`.
- It IS added to its own currency bucket as a credit (so the
  bookkeeping balance is preserved on the wFirma side).
- It is listed in `unmatched_payments_per_currency.<ccy>` with a
  `currency_mismatch_with_invoice` warning carrying both the
  `linked_invoice` id and its currency.


## 10. Multi-currency policy

- **Per-currency aggregation only.** Every total, every aging bucket,
  every running balance is scoped to one currency. No FX conversion.
  No "in PLN reference column".
- **`value_pln` on `<payment>` is NOT used** by Phase 10B. Even though
  the field is verified to be present (Phase 10A.5), using it would
  imply a `today's-rate-vs-payment-date-rate` policy decision (and
  therefore an unrealised FX gain/loss policy). That decision is
  Phase 10C+ territory.
- **Currency list is the union of invoice currencies and payment
  currencies** the contractor has activity in. A currency with only
  payments (no invoices) appears with a credited running balance —
  surfacing exactly the on-account credit case.
- **Rendering is per-currency.** The dashboard / PDF (10C / 10D) shows
  one totals + aging block per currency. They are NOT additive across
  currencies.


## 11. Failure modes

| Failure | Symptom | Aggregator behaviour |
|---|---|---|
| wFirma `invoices/find` HTTP 5xx / `status != OK` | RuntimeError from `fetch_invoices_for_contractor` | Route returns 502; aggregator never runs. (Already implemented in Phase 10A.) |
| wFirma `payments/find` HTTP 5xx / `status != OK` | RuntimeError from new `fetch_payments_for_contractor` wrapper | Route returns 502; aggregator never runs. |
| Empty contractor | preflight returns `ok=false` | Route returns 404. (Phase 10A.) |
| Invalid date range | `from > to` or non-`YYYY-MM-DD` | Route returns 400. (Phase 10A.) |
| 5000-doc safety cap hit on `invoices/find` | partial invoice list | Aggregator runs on whatever wFirma returned; emits warning `"invoice_safety_cap_hit"` so the dashboard knows the totals may be undercounted. |
| 5000-doc safety cap hit on `payments/find` | partial payment list | Same: warning `"payment_safety_cap_hit"`. |
| Invoice with empty `<id>` | useless row | Skipped; warning `"invoice_with_empty_id"` |
| Invoice with empty `<currency>` | bucket-key ambiguity | Falls back to `"PLN"` for bucket key (matches Phase 10A's existing behaviour) and emits warning `"invoice_currency_missing"` |
| Payment with empty `<currency_label>` | bucket-key ambiguity | Skipped from per-currency totals, listed in unmatched, warning `"payment_currency_missing"` |
| Payment with negative `<value>` | unusual but legal in wFirma (reversal) | Treated as a debit (positive) on the running balance — equivalent to "money returned to customer". Warning `"reversal_payment"` for operator visibility. |
| Network failure mid-pagination | partial list with no error code | Already converts to RuntimeError in `fetch_invoices_for_contractor` per Phase 10A. Same pattern for the new payments wrapper. |

Aggregator never raises on field-level oddities; it emits warnings and
keeps producing output. The operator is the safety net.


## 12. Auditability guarantees

- Every entry carries its `wfirma_doc_id`. Operators can drill into
  any row by hitting `invoices/get/{id}` or `payments/get/{id}` (the
  Phase 10A.5 probe verified both work).
- Per-invoice PDF drill-down reuses Phase 8's
  `/api/v1/proforma/{batch}/{client}/document.pdf` for proformas, plus
  a new `/api/v1/ledgers/invoices/{id}/document.pdf` route in Phase
  10C/D for non-proforma invoices. Both ultimately call
  `wfirma_client.fetch_invoice_pdf` (read-only).
- The aggregator's input set is fully reproducible: given the same
  `(contractor_id, period)`, the wFirma reads return the same data
  modulo new payments; the aggregator is deterministic.
- All `warnings[]` strings carry the `wfirma_doc_id` of the
  contributing entry so an operator can audit any anomaly.
- No local DB writes in Phase 10B (caching is Phase 10D — see §13).


## 13. Caching policy

**Phase 10B: NO local caching.** Every call to the Statement endpoint
hits wFirma fresh. Reasons:

- Simpler correctness story for the first cut.
- wFirma's API has its own rate limits; the dashboard is operator-
  driven (low traffic) so cache miss cost is acceptable.
- Cache invalidation on payment / invoice events would require
  webhook integration we have not built.

**Phase 10D may add caching.** When/if it does:
- Extend `customer_invoice_snapshot_db` with payment-state columns
  (still NOT relying on `<paymentstate>` from wFirma — store our
  computed `remaining_for(X)` instead).
- Add a `customer_payments_snapshot` table mirroring the invoice
  snapshot pattern.
- Add a freshness window (TTL) and a `?refresh=1` query param.
- Add an operator "Refresh" button on the dashboard.
- Phase 10D's caching design is OUT OF SCOPE for this document.


## 14. Phase breakdown

| Phase | Scope | Owner | Gating evidence |
|---|---|---|---|
| **10A** | Invoice ledger JSON (no payments, no aging) | shipped | tests green, 553 sweep |
| **10A.5** | Live probe of `payments/find` + invoice payment-state fields | partial — placeholder run committed; real-id re-run still pending | `docs/WFIRMA_PAYMENTS_PROBE_EVIDENCE.md` |
| **10A.6** *(optional)* | Add `reports/find`, `balances/find`, `settlements/find` to the probe to rule out undocumented endpoints | not blocking | one extension to the existing probe |
| **10B** | Statement-of-Account JSON aggregator + `GET /api/v1/ledgers/clients/{id}/statement.json` route | not started | this document |
| **10C** | PDF renderer (`reportlab`) + `GET .../statement.pdf` route | deferred | needs Phase 10B JSON proven by use |
| **10D** | Dashboard surface (Phase 6 panel extension); local caching tables; operator Refresh action | deferred | needs Phase 10C |
| **10E** | Supplier-side ledger over `expenses/find` + `payments/find?expense_id=` | deferred | mirror of 10B once 10B is stable |
| **10F** *(indefinitely deferred)* | Write-side payment recording (`payments/add`) | not planned | out of perpetual scope |


## 15. What must not be built

| Forbidden | Reason |
|---|---|
| **Iframe of wFirma UI** | `X-Frame-Options: SAMEORIGIN` blocks cross-origin embedding; auth model mismatch (cookie vs API key). See research doc §3. |
| **Backend HTML proxy of wFirma UI** | Requires storing wFirma user passwords (credential-hoarding antipattern); renders against private (non-public) wFirma APIs; TOS risk. |
| **Headless-browser scraper** | Same auth + TOS issues; fragility across wFirma releases. |
| **Fake "wFirma statement wrapper" route** | wFirma has no statement endpoint — see research doc §1. A wrapper that pretends to call a wFirma report endpoint when none exists is a fake-button violation. |
| **Reliance on `<paymentstate>` / `<alreadypaid>` / `<remaining>` / `<paid_date>` from wFirma** | Unverified; see §3. Use payments-driven reconciliation instead (§6). |
| **`paymentdate`-based aging without verification** | Until Phase 10A.5 real-id probe lands, due-date aging is forbidden. Use invoice-age aging with explicit `method` label (§7.3). |
| **Cross-currency FX in totals** | Out of scope; would require an NBP-rate policy decision the project hasn't made. See §10. |
| **Local writes to wFirma** | All Phase 10B traffic is read-only. The aggregator never calls `add` / `edit` / `delete` / `send` / `fiscalise` on any module. |
| **Local DB schema changes** | Phase 10B is JSON-aggregator only. Schema work is Phase 10D's caching concern. |
| **Embedding the Phase 10A `invoice-ledger.json` route as the Statement endpoint** | Different contracts. The invoice-ledger surfaces invoices only; the Statement adds payments + balance + aging. They live at different URLs. |


## 16. Open questions

1. **Real-id `invoices/get` probe.** Are `<paymentstate>`,
   `<alreadypaid>`, `<remaining>`, `<paymentdate>`, `<paid_date>`
   present on a real `<invoice>` response? Until answered, the
   aggregator runs in payments-driven mode with invoice-age aging.
   Owner: operator running the probe with a real id.

2. **`reports/*` / `balances/*` / `settlements/*` endpoints.** The
   research doc could not actively probe these; they are absent from
   the Postman collection but a live `find` probe would cost one
   round-trip each. Worth adding to the existing probe tool as a
   Phase 10A.6 extension before Phase 10C work begins.

3. **Proforma-as-debit vs Proforma-as-memo.** Should a proforma
   contribute to the contractor's debit running balance the same way
   a regular invoice does, or should it be a memo-only line that
   doesn't affect totals? The current §8 design treats it as a debit;
   if Estrella's accounting policy disagrees, the aggregator emits a
   `proforma_treated_as_debit` warning so the policy is visible. Pin
   the answer with finance before Phase 10C ships.

4. **Aging cutoff date.** Is `statement_date` always "today (UTC)" or
   should it be operator-supplied for back-dated statements? Default
   to "today" with optional `?as_of=YYYY-MM-DD` query param;
   confirm with operator before Phase 10C.

5. **Correction-invoice linkage display.** §8.1 leaves the
   `<correction_invoice>/<id>` cross-reference out of the JSON. If
   the dashboard needs to render "correction X applies to invoice Y"
   in the entry list, add a `linked_correction_invoice` field on the
   entry. Decide before Phase 10D's UI work.

6. **Pagination beyond 5000.** A long-tenure customer may have more
   than 5000 invoices over the queried period. The route caps at
   5000 (Phase 10A safety) and emits a warning. Should there be a
   higher tier ("expanded fetch" with a separate cap) for accounting
   year-end statements? Defer until a real customer hits the cap.

7. **Webhook integration.** A future caching layer (Phase 10D)
   benefits from wFirma's webhooks (`webhooks/*` is confirmed in
   `WFIRMA_API_VALIDATED_MAP.md`). Decide whether the cache is
   webhook-driven (real-time) or TTL-driven (simpler) when 10D
   begins.
