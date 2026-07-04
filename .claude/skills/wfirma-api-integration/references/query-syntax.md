# Query Syntax — `find` requests

Read `request-response-conventions.md` first for the envelope shape. This file covers the `parameters` block used by `find`-type actions (e.g. `/invoices/find`, `/goods/find`).

## Conditions

Conditions live under `parameters.conditions` and can be grouped with `and` / `or` / `not`. Each `condition` has:

- **`field`** — field name to filter on. Can be a bare field (`date`, `type`) or qualified with a related-module prefix (`Invoice.remaining`, `ContractorDetail.nip`) when filtering on a related 1:1 module's field.
- **`operator`** — one of: `eq` (==), `ne` (!=), `gt` (>), `lt` (<), `ge` (>=), `le` (<=), `like`, `not like`, `in`
- **`value`** — the comparison value. For `in`, pass a comma-separated list.

### XML example — combined OR + AND groups

```xml
<api>
  <invoices>
    <parameters>
      <conditions>
        <or>
          <condition>
            <field>fullnumber</field>
            <operator>like</operator>
            <value>FV 234/2015</value>
          </condition>
          <condition>
            <field>number</field>
            <operator>lt</operator>
            <value>200</value>
          </condition>
        </or>
        <and>
          <condition>
            <field>Invoice.remaining</field>
            <operator>gt</operator>
            <value>0</value>
          </condition>
          <condition>
            <field>ContractorDetail.nip</field>
            <operator>in</operator>
            <value>8982167294,8982073475</value>
          </condition>
        </and>
      </conditions>
    </parameters>
  </invoices>
</api>
```

### `not` example

```xml
<api>
  <goods>
    <parameters>
      <conditions>
        <not>
          <condition>
            <field>name</field>
            <operator>eq</operator>
            <value>test</value>
          </condition>
        </not>
      </conditions>
    </parameters>
  </goods>
</api>
```

### JSON equivalent (find, invoices example)

```json
{
  "parameters": {
    "conditions": [
      {
        "or": [
          { "condition": { "field": "type", "operator": "eq", "value": "proforma" } },
          { "condition": { "field": "type", "operator": "eq", "value": "correction" } }
        ],
        "and": [
          { "condition": { "field": "disposaldate", "operator": "gt", "value": "2024-05-00" } },
          { "condition": { "field": "disposaldate", "operator": "lt", "value": "2024-05-31" } }
        ]
      }
    ],
    "fields": [
      { "field": "Invoice.id" },
      { "field": "Invoice.date" },
      { "field": "Invoice.fullnumber" },
      { "field": "Contractor.name" },
      { "field": "Contractor.nip" }
    ],
    "order": [ { "desc": "date" } ],
    "page": 1,
    "limit": 5
  }
}
```

## Sorting

Sort on the main module's fields **or** fields of related modules that are in a **1-to-1 relation** with the main module (not 1-to-many — you can't reliably sort invoices by a field on a 1-to-many nested collection like invoicecontents).

## Pagination

Use `limit` (page size) and `page` (page number, 1-indexed). Always set an explicit `limit` for `find` calls in production code — don't rely on defaults, and don't assume the default limit is "all records." For bulk exports, page through results rather than assuming a single call returns everything.

## `fields` parameter (selecting a subset of returned fields)

- Format: array/list of `{"field": "Module.fieldname"}` objects (JSON) or `<field>Module.fieldname</field>` entries (XML).
- Field names here use **CamelCase.module_field** notation (`Invoice.total`, `InvoiceContent.name`, `ContractorDetail.name`), which differs from the lowercase branch names used in the response body itself (`invoice`, `invoicecontent`, `contractor_detail`). This is a frequent source of "my fields filter returns nothing" bugs — double-check casing/naming against the specific module's doc page rather than assuming a pattern.
- Multiple integrators report the `fields` documentation being incomplete for some modules/edge cases — if a `fields` filter silently returns unexpected results, fall back to omitting `fields` (get the full record) and filter client-side while you verify the correct qualified name, rather than assuming your code is broken.

## Query IDs / single-record actions

Some actions accept the record ID directly in the URL path (`/invoices/get/{id}`) rather than through `parameters` — check the module's own doc page for which convention (`get/{id}` vs a `find` with an `eq id` condition) is the intended approach for a given action.
