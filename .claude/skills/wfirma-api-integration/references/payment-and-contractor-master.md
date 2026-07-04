# Payment Terms & Contractor Master Data

Covers payment method/terms fields on invoices, and the full contractor field set worth syncing — directly relevant to keeping Estrella Jewels' contractor master (Verhoeven, Dream Rings, Juliany EOOD, Diamond Point, Clear Diamonds, and the Indian supplier side) in sync with wFirma's CRM.

Read `contractors.md` first for the `contractor.id` vs `contractor_detail.id` distinction — this file assumes that context.

## Payment fields on an invoice (confirmed from real responses)

```xml
<paymentmethod>transfer</paymentmethod>
<paymentdate>2017-10-15</paymentdate>
<paymentstate>paid</paymentstate>
<alreadypaid>123.00</alreadypaid>
<alreadypaid_initial>123.00</alreadypaid_initial>
<remaining>0.00</remaining>
```

- **`paymentmethod`** — confirmed values seen in real payloads/responses: `transfer`, `cash`. Older/legacy documentation also references `compensation` (offset/barter settlement) as a valid value. Before assuming a value not listed here is accepted (e.g. card, other electronic methods), verify against the current invoices module page — the confirmed set here is what's been directly observed in real requests/responses, not necessarily the complete list.
- **`paymentdate`** — the payment due date (termin płatności), `YYYY-MM-DD`. This is what "payment terms in days" ultimately resolves to on the document — see below for how to compute it from a terms-in-days value.
- **`paymentstate`** — read-only status reflecting whether the document is paid (`paid` seen in a real response). Useful for read/reconciliation flows (e.g. "has this WDT invoice been paid yet") — don't attempt to set this directly; it's derived from actual payment records against the document, not a settable field on `/invoices/add`.
- **`alreadypaid`** / **`alreadypaid_initial`** / **`remaining`** — running payment reconciliation figures on the document. Useful for AR/AP dashboards without needing a separate payments query, though the dedicated `payments` module (confirmed to exist via the community SDK) is the authoritative source if you need full payment history/detail rather than just the invoice-level summary.

## "Payment terms in days" — there's no such field; you compute `paymentdate` yourself

wFirma's invoice API doesn't take a standalone "net 30" style terms-in-days field — you compute the actual `paymentdate` (a concrete date) from whatever terms logic your business uses and pass that date directly. If Estrella Jewels' contractor agreements specify standard terms (e.g. "net 30 from invoice date" for a given client), that calculation belongs in your integration layer:

```
paymentdate = invoice.date + contractor's agreed terms (in days)
```

**Where to store the default terms-in-days per contractor**: wFirma's contractor record itself doesn't expose a dedicated "default payment terms in days" field in the confirmed field set below — if a per-contractor default is needed, store it in the external system (your own contractor master / config) and apply it when constructing each invoice's `paymentdate`, rather than assuming wFirma will remember or apply a default automatically. Re-verify against the current contractors module docs before ruling this out entirely, since field coverage there is known to be incompletely documented (see `contractors.md`).

## Contractor master fields (confirmed from a real `contractor_detail` response)

```xml
<street>Kiełbasiana 22</street>
<zip>11-100</zip>
<city>Zimne Wódki</city>
<country>PL</country>
<phone></phone>
<email></email>
<discount_percent>0.00</discount_percent>
<empty>0</empty>
<simple>0</simple>
<created>2017-10-17 21:03:33</created>
<modified>2017-10-17 21:03:33</modified>
```

Plus, from `contractors.md`: `name`, `altname`, `nip` (VAT/tax number). And for the **issuing company's own bank details** (`company_detail` branch on an invoice response — i.e. YOUR company's bank info as printed on the invoice, not the contractor's):

```xml
<bank_name>Mojbank</bank_name>
<bank_account>12 1234 1234 1234 1234 1234</bank_account>
<bank_swift>SWIFT</bank_swift>
<bank_address>adresbanku</bank_address>
```

These `bank_*` fields are confirmed to exist on the `company_detail` branch (your own issuing entity's bank info, e.g. Super Fashion / Estrella Jewels Sp. z o.o.'s bank account used for `transfer` payments). Whether a *contractor's own* bank details are stored/retrievable as a first-class field on the `contractor`/`contractor_detail` branch (useful if you ever need to pay a contractor rather than bill them) isn't confirmed from the sources gathered for this skill — check the current `contractors` module doc page directly if that's needed, since supplier-side (payable) bank details are a different use case from your own issuing bank details.

## `discount_percent`, `empty`, `simple` flags

- **`discount_percent`** — a default discount percentage associated with the contractor, applied when relevant (e.g. via price groups / contractor-level discount logic) — confirm exact application rules against the current docs if this needs to drive automated pricing.
- **`empty`** — flag indicating whether the record is a placeholder/blank in some contexts; treat as informational unless the specific module doc explains the semantics for your exact use case.
- **`simple`** — flag related to `warehouse_type: "simple"` document semantics discussed in `invoices.md`/`warehouse-goods.md` — on a contractor-linked branch this likely mirrors document-level state rather than being a contractor property; don't assume it's a persistent contractor setting.

## `contractor_id` — an undocumented-but-confirmed query field

When filtering invoices/other records by contractor, the documented field-qualification patterns (`Invoice.contractor`, `Contractor`, `Contractor.id`) **do not work** in `find` conditions. The field that actually works, confirmed via wFirma support on the forum, is the bare field name **`contractor_id`** — which does not appear anywhere in the official doc.wfirma.pl reference. Use this directly:

```json
{"condition": {"field": "contractor_id", "operator": "eq", "value": "4855812"}}
```

This is a good example of why `gotchas.md` and cross-referencing the forum matter — the official docs alone would not surface this.

## Syncing contractor master data — recommended pattern for this project

1. **Match/dedupe on `nip`** (VAT number) where available — this is the standard unique business identifier across EU contractors, more reliable than name matching for Verhoeven/Dream Rings/Juliany EOOD/Diamond Point/Clear Diamonds.
2. **Always resolve to `contractor.id`** (CRM-level, not `contractor_detail.id`) for any stored mapping — see `contractors.md`.
3. When creating a new contractor via `/contractors/add`, required fields observed to trigger validation errors if missing: `name`, `street`, `zip`, `city` (all four are confirmed mandatory from real validation-error responses) — always populate all four even for contractors where some of this data feels redundant (e.g. a contractor you mostly identify by NIP).
4. Payment terms/method defaults are a **your-system responsibility**, not something to expect wFirma's contractor record to drive automatically — compute `paymentmethod` and `paymentdate` per-invoice from your own business rules, keyed off the contractor.
