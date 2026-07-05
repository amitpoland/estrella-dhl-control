# Request / Response Envelope Conventions

Understanding this structure is required before writing ANY request or parsing ANY response — it's the same shape across all modules.

## Top-level structure

Every request or response has **at most two top-level branches**. In XML these are wrapped in a root `<api>` element; in JSON there is no such wrapper element (see JSON numbering quirk below).

1. **`status`** branch — contains a `code` sub-branch with the general result code for the request (e.g. `OK`, or an error code).
2. **A module-name branch, plural form** (e.g. `invoices`) — the collection wrapper. Inside it:
   - One or more **module-name branches, singular form** (e.g. `invoice`) — one per record. There can be any number of these.

## ⚠️ JSON numbering quirk (very common source of bugs)

In XML, repeated sibling branches (like multiple `<invoice>` entries) are just repeated tags — no special handling needed.

**In JSON, repeated branches must ALWAYS be numbered with a key, even when there's only one.** This trips up almost every integrator on their first `/add` call. Example — adding ONE invoice:

```json
{
  "invoices": {
    "invoice": {
      "contractor": { "id": "4855812" },
      "paymentmethod": "transfer",
      "date": "2024-07-24",
      "paymentdate": "2024-07-27",
      "type": "normal",
      "currency": "PLN",
      "invoicecontents": {
        "0": {
          "invoicecontent": {
            "name": "Produkt 1",
            "unit": "szt.",
            "count": "1",
            "price": 50,
            "vat": 23
          }
        },
        "1": {
          "invoicecontent": {
            "name": "Produkt 2",
            "unit": "szt.",
            "count": "2",
            "price": 30,
            "vat": 23
          }
        }
      }
    }
  }
}
```

Note: `invoicecontents` (the nested collection of line items) **requires** the `"0"`, `"1"`, ... numeric-string keys even for a single line item. Missing this numbering has caused documented "Internal server error" failures on `/invoices/add` (confirmed on the wFirma forum). Always number nested repeatable collections defensively, even when you're only sending one.

## Related-module branches

A record branch can contain nested branches identifying related modules, e.g. the content of an invoice (`invoice_content`/`invoicecontents`) lives inside the `invoice` record. Field-level docs for each branch live on that module's specific doc page — don't assume field names are shared 1:1 across modules just because the branch name looks similar (see the Contractor vs ContractorDetail gotcha).

## Field-level validation errors

When a write request partially fails validation, wFirma returns **per-field error branches nested inside the relevant record/sub-record**, not just a flat top-level error list. Example (invoice with a missing contractor address and a bad date):

```xml
<api>
  <invoices>
    <invoice>
      <paymentmethod>cash</paymentmethod>
      <paymentdate>2011-08-15</paymentdate>
      <type>normal</type>
      <errors>
        <error>
          <field>date</field>
          <message>Data musi być w formacie RRRR-MM-DD</message>
        </error>
      </errors>
      <contractor>
        <errors>
          <error><field>name</field><message>Pole nie może być puste</message></error>
          <error><field>street</field><message>Pole nie może być puste</message></error>
          <error><field>zip</field><message>Pole nie może być puste</message></error>
          <error><field>city</field><message>Pole nie może być puste</message></error>
        </errors>
      </contractor>
      <invoicecontents>
        <invoicecontent>
          <name>nazwa produktu</name>
          <!-- ... -->
          <errors>
            <error><field>name</field><message>Treść nie może być pusta</message></error>
          </errors>
        </invoicecontent>
      </invoicecontents>
    </invoice>
  </invoices>
</api>
```

**Implication for error-handling code:** don't just check a top-level `status.code`. Recursively walk the response for `errors`/`error` branches at every nesting level (invoice, contractor, each invoicecontent) to build a complete, field-attributed error report — otherwise your integration will silently swallow partial validation failures on nested records (e.g. a bad line item won't surface if you only look at the top level).

## Filtering the response with `fields`

You can request only a subset of fields (reduces payload size, and is sometimes required to reach fields on related 1:1 modules — see `query-syntax.md`). Field names in the `fields` parameter are qualified with the **CamelCase module name**, e.g. `Invoice.total`, `InvoiceContent.name`, `ContractorDetail.name` — not the lowercase branch names used in the response body. This asymmetry (lowercase in payload branches, CamelCase.field in query/fields parameters) is easy to get wrong — see `query-syntax.md` for full examples.
