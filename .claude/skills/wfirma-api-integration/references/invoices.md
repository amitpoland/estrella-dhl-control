# Invoices Module (`invoices` / faktury)

Read `request-response-conventions.md` and `query-syntax.md` first.

**If the task involves proformas, reservations, or converting a proforma into a real invoice — stop and read `proforma-reservations-flow.md` first.** That's a separate document lifecycle with its own traps (no convert endpoint, separate numbering series, reservations being UI-only) that this file doesn't cover.

## Core actions

- `POST /invoices/add` — create an invoice (or a draft — see below)
- `GET /invoices/get/{id}` — fetch a single invoice by ID
- `POST /invoices/find` — query invoices (see `query-syntax.md`)
- `PUT /invoices/edit/{id}` — edit an invoice (full support for **drafts**; edits to already-issued/numbered invoices are more restricted — verify against the current module doc page before assuming a field is editable post-issue)
- `/invoices/download` — non-standard action, returns the invoice PDF (documented example of a module having an action outside the standard find/get/add/edit/delete set — always check a module's own page for these)

## Minimal add payload shape (JSON)

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
      "series": { "id": null },
      "invoicecontents": {
        "0": {
          "invoicecontent": {
            "name": "Produkt 1",
            "unit": "szt.",
            "count": "1",
            "price": 50,
            "discount": 0,
            "discount_percent": 0,
            "vat": 23
          }
        }
      }
    }
  }
}
```

⚠️ Remember the JSON numbering requirement for `invoicecontents` even with a single line item (see `request-response-conventions.md`).

## Contractor on an invoice: full object vs id-only

- You can pass a **full contractor object inline** (name/street/zip/city/etc.) — wFirma will create/match a contractor.
- You can pass **only `{"contractor": {"id": "..."}}`** to attach an existing contractor by ID.
- ⚠️ Documented forum issue: passing only the contractor `id` has, in some cases, produced a 500 "Internal server error" where the full-object form succeeds. If an invoice add with contractor-id-only fails unexpectedly, try the full-object form as a diagnostic step, and test the id-only path on `test.api2.wfirma.pl` before relying on it in production. See also `contractors.md` for the Contractor-vs-ContractorDetail id distinction — this is a separate, related trap.

## Draft invoices (wersje robocze)

wFirma supports draft invoices created via API:

- Create: `POST /invoices/add` with the appropriate `type` value marking it as a draft (check current module doc page for the exact accepted draft type value(s), as this has been a recently-documented/changing area).
- Edit: `PUT /invoices/edit/{id}` — drafts can be updated (unlike issued invoices).
- **Draft invoice properties:**
  - **No number assigned** — drafts don't consume a slot in the numbering series until approved/finalized in the wFirma UI.
  - **Not sent to KSeF** — drafts are not automatically transmitted to the Polish e-invoicing system.
  - **Visible in the UI** under PRZYCHODY » SPRZEDAŻ (Income » Sales) once added via API.

## KSeF (Krajowy System e-Faktur) — relevant for any Poland-VAT company

Since Estrella Jewels' Poland entity (Super Fashion) issues invoices, KSeF behavior directly affects invoice-issuing code paths:

- **Status/number retrieval is async.** `/invoices/get/{id}` (or the add response) does **not** immediately return the KSeF reference number — the system is still waiting on the Ministry of Finance servers to process the document at the moment `/invoices/add` responds.
- To get KSeF status/number, either:
  1. **Poll**: call `/invoices/get/{id}` after some delay; on success it returns `ksef_reference_number`, `ksef_registration_date`, and `ksef_status`.
  2. **Webhook** (preferred for production): configure a webhook that fires automatically once KSeF processing completes (success or error) — see `webhooks.md`. This avoids polling and gets you the status as soon as it's known.
- **Per-user KSeF authorization matters.** Invoices issued via API are attributed in wFirma to the specific user whose API key was used to configure the integration. If that user has not personally authorized KSeF (uploaded their certificate/token under Przychody » KSeF i Integracje in the wFirma UI), API-issued invoices will be **blocked with an authorization error even if a company admin has KSeF enabled generally**. This is a common, non-obvious failure mode: "KSeF is enabled for the company but invoices via API still fail" → check whether the *API-key-owning user specifically* has completed their own KSeF authorization step.
- **Action if this bites you:** the user whose API key is used must log into wfirma.pl themselves, go to Przychody » KSeF i Integracje, and complete certificate/token authorization — this cannot be done via the API itself.

## Warehouse effect (`warehouse_type`) — critical cross-reference

Every sales document (invoice, fiscal or non-fiscal receipt) **by default** triggers a warehouse effect: it reduces stock and auto-generates a WZ (goods-issue) warehouse document, if the warehouse module is enabled on the account.

- To issue a sales document **without** triggering this warehouse effect, set `warehouse_type` to `"simple"` in the invoice payload.
- If you need the opposite (guaranteed warehouse effect and correct stock tracking), do **not** set `warehouse_type` to `"simple"`, and ensure the invoice line items reference actual `goods` records by ID (not free-text line items) — free-text lines that don't map to a `goods` record won't affect stock the way you'd expect.
- **Full detail on why this matters architecturally**: `warehouse-goods.md` — read it before designing any part of the integration that needs accurate stock levels.
