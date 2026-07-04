# Contractors Module (`contractors` / kontrahenci)

Read `request-response-conventions.md` first.

## Core actions

- `POST /contractors/add` — create a contractor
- `GET /contractors/get/{id}`
- `POST /contractors/find`
- `PUT /contractors/edit/{id}`
- `DELETE /contractors/delete/{id}`

## Minimal add payload (JSON)

```json
{
  "contractors": {
    "contractor": {
      "name": "Jan Testowy",
      "street": "Testowa 69",
      "zip": "66-666",
      "city": "Miastowo",
      "email": "jan@testowy.pl"
    }
  }
}
```

## ⚠️ CRITICAL: `Contractor` id vs `ContractorDetail` id — do not conflate

This is one of the most common and confusing wFirma API traps, confirmed directly by wFirma support on the forum. When you retrieve invoices, each invoice record contains **two separate branches**, each with its own `id` field, referring to what looks like "the same contractor":

- **`contractor` branch** (`contractor.id`, `contractor.altname`) — this is the **CRM-level contractor ID**. This is the ID from the actual contractor directory (CRM » Kontrahenci). **This is the ID you must use when constructing API requests that reference "a contractor"** (e.g., `{"contractor": {"id": "..."}}` on an invoice add, or `/contractors/get/{id}`).
- **`contractor_detail` branch** (`contractor_detail.id`, plus a full set of address/name/etc. fields) — this is a **per-invoice snapshot** of the contractor's details at the time that specific invoice was issued. Its `id` is scoped to that invoice's detail record, **not** the CRM contractor. **This id changes across different invoices for the same underlying contractor** — do not use it to identify/deduplicate contractors, and do not pass it where the API expects a CRM contractor id.

**Implication for sync/dedup logic:** if you're syncing contractors from an external system (e.g. Estrella Jewels' order/DHL system) and matching them against wFirma contractors, always key off `contractor.id`, never `contractor_detail.id`. If you see `contractor.id` / `contractor.altname` empty on a fetched invoice, that means the invoice's contractor **was not saved to the CRM contractor directory** (was entered ad hoc) — there is no CRM-level ID to reconcile against in that case.

**Also note:** `Invoice.netto` + `Invoice.tax` gives the gross/brutto amount of the document — this addition is confirmed correct by wFirma support, useful for reconciliation code.

## Foreign contractors

Foreign (non-Polish) contractors are entered the same way as domestic ones, with some additional fields required for certain cases (VAT-EU procedures, country code, etc.) — check the current field reference for `country`/VAT-related fields on this module's doc page before assuming the domestic field set is sufficient, since Estrella Jewels' India↔Poland flows will hit this path.

## Related CRM data

Contact persons, correspondence documents, and cyclical/recurring services (usługa cykliczna) live under related CRM functionality but are documented on their own module pages (not this file) — don't assume they're sub-fields of the `contractor` payload without checking.
