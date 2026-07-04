# Currency & Multi-Currency Invoicing

Directly relevant to Estrella Jewels: invoices are issued in EUR to Verhoeven Joaillier (France), Dream Rings (Czechia), Juliany EOOD (Bulgaria), Diamond Point (Netherlands), Clear Diamonds (UK) — all WDT (intra-EU 0% VAT) transactions — while the underlying accounting is in PLN.

## Fields on the invoice object

Confirmed from a real invoice response (via `test.api2.wfirma.pl`):

```xml
<currency>PLN</currency>
<currency_exchange>1.0000</currency_exchange>
```

- **`currency`** — ISO-style currency code as a string (`PLN`, `EUR`, `USD`, etc.). Set this on `/invoices/add`.
- **`currency_exchange`** — the exchange rate actually applied/recorded on the document (returned on read; PLN-currency invoices show `1.0000`). For foreign-currency invoices this reflects the rate used to convert to PLN for accounting purposes.

Before assuming exactly how to *supply* a manual rate on write (as opposed to letting the system resolve it), verify against the current `invoices` module page on doc.wfirma.pl or test on `test.api2.wfirma.pl` — the write-side field name/behavior for manually overriding the rate isn't confirmed from public sources at the time of writing this file, whereas the read-side `currency_exchange` field is confirmed. If your integration needs a specific NBP rate applied (see WDT rule below), the safe pattern is: compute the correct rate yourself (see NBP API below) and pass whatever rate-related field the current module docs specify for write, testing on the sandbox first; don't assume the system will silently do the right thing for a WDT-specific rate without you supplying it if the field exists.

## The WDT rate rule (locked, confirmed) — critical for this project

For **WDT (wewnątrzwspólnotowa dostawa towaru — intra-EU supply of goods, 0% VAT)** transactions specifically, the conversion to PLN **always** uses the **average NBP rate from the last business day preceding the invoice's issue date** — this is a fixed rule, not a choice, and doesn't follow the general "date of sale / tax point" logic that applies to other invoice types. This matches the project's own locked principle: *NBP rate must always be resolved to the business day before invoice date.*

Non-WDT foreign-currency invoices can follow different date-of-reference rules (general sales-date-based logic) — if Estrella Jewels ever issues a non-WDT foreign-currency document, don't assume the WDT rate rule applies; check the specific rule for that document type before hardcoding date logic.

## Getting the correct NBP rate programmatically

wFirma's own UI-side currency analysis (Start » Analizy » Kursy walut) shows NBP average rates for reference, but for integration purposes, query the **National Bank of Poland's own free public API** directly rather than trying to extract it from wFirma:

```
GET https://api.nbp.pl/api/exchangerates/rates/A/{CODE}/{DATE}/?format=json
```

- `{CODE}` — currency code, e.g. `EUR`, `USD` (case-insensitive in practice, but use uppercase).
- `{DATE}` — `YYYY-MM-DD`. **For the WDT rule, this must be the last business day before the invoice issue date, not the issue date itself** — if the issue date is a Monday, this is the preceding Friday (or earlier if that Friday was a holiday); build this with an actual Polish-holiday-aware business-day calculation, not a naive "subtract one day."
- No authentication required; it's a public API.
- Returns 404 if no rate was published for that exact date (e.g. weekends, holidays) — this is expected for non-business days; step backward a day at a time until a rate is found, rather than treating 404 as an error to surface.
- Response shape: `{"table":"A","currency":"...","code":"EUR","rates":[{"no":"...","effectiveDate":"YYYY-MM-DD","mid":4.xxxx}]}` — the rate is in `rates[0].mid`.
- Table type: use table **A** (average rates) for standard accounting conversions — this matches "średni kurs NBP" (average NBP rate) referenced throughout wFirma's own documentation for this purpose. Table C (buy/sell) is a different use case (e.g. cash exchange), not relevant here.

## Expense-side currency handling (for context, if the project later touches wydatki)

For foreign-currency **purchase** invoices (costs), wFirma's UI supports a separate manual rate specifically for VAT purposes distinct from the income-tax-purposes rate (toggle: "VAT w PLN" with a manual or NBP-date-selected rate) — see `expenses.md`. This is a UI-only nuance as of last check; if expense automation is ever built via API, re-verify whether this dual-rate mechanism is exposed on write.

## Practical pattern for this project

```
1. Determine invoice type (WDT vs other) and issue date.
2. If WDT: compute "last business day before issue date" (Poland calendar-aware).
3. Query https://api.nbp.pl/api/exchangerates/rates/A/{CODE}/{that date}/?format=json
   (step backward on 404 until a rate is found).
4. Cross-check against the project's NBP_Rate.pdf reference documents if available,
   since Estrella Jewels already tracks these rates manually for reconciliation —
   the API-derived rate should match what's on the manually-tracked reference.
5. Set `currency` on the invoice payload; confirm the correct write-side rate field
   against current doc.wfirma.pl / test.api2.wfirma.pl before assuming a field name.
```
