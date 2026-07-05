# Document Output: Download, Print, Email, Notes/Description

Covers getting a finished wFirma document (invoice, proforma) out as a file, emailing it, printing warehouse documents, and customizing what appears on the printed/PDF document.

## Downloading a document as PDF

Confirmed action and parameters (via a working unofficial SDK example and older forum-confirmed usage):

```
GET/POST /invoices/download/{id}
```

Parameters seen in real usage:
- **`page`** — `"all"` or `"invoice"` (scope of what to render — e.g. include attachments/leaflets or just the invoice itself).
- **`address`** — `0`/`1` — include a mailing address page.
- **`leaflet`** — `0`/`1` — include a leaflet/insert page.
- **`duplicate`** — `0`/`1` — render as a duplicate copy (marked "duplikat") rather than the original.
- **`payment_cashbox_documents`** — `0`/`1` — include linked cashbox/payment documents.
- **`warehouse_documents`** — `0`/`1` — include the linked warehouse document (e.g. the WZ generated as a side-effect — see `warehouse-goods.md`) **in the same PDF bundle as the invoice**. This is the practical way to get a WZ printout via API: not as its own standalone download, but bundled into the invoice PDF that triggered it.

```
GET/POST /invoices/download/{id}?inputFormat=json
```
with `outputFormat`/`inputFormat` query params controlling request/response format (see `request-response-conventions.md`).

⚠️ **The action returns the raw PDF file bytes directly** (not a JSON envelope, not a URL) — a documented point of confusion on the forum, where an integrator expected a link and got a raw content stream instead. If your HTTP client is expecting JSON, you need a separate code path for this action that reads the raw response body and writes it as a binary file (set `Content-Type: application/pdf` if proxying it onward).

## Getting a public, no-auth-required link to a document (for sharing/emailing)

If you need a link a client can open without your API credentials (e.g. to embed in a custom email rather than using wFirma's own send action), `/invoices/get/{id}` returns a **`hash`** field. Confirmed link pattern:

```
https://wfirma.pl/invoice_externals/download/{ID}/{HASH}
```

⚠️ This link requires **no authentication** — the hash itself functions as the access control. Treat it like a bearer credential: don't log it in shared/insecure locations, don't put it in analytics URLs, and don't send it to anyone other than the intended recipient.

## Sending a document by email directly through wFirma

Confirmed action and parameters:

```
POST /invoices/send/{id}
```
with:
- **`email`** — recipient address (overrides the contractor's stored email if provided).
- **`subject`** — email subject line.
- **`body`** — email body text.
- **`page`** — which document view to attach (e.g. `"invoice"`).
- **`leaflet`**, **`duplicate`** — same meaning as in `download`.

This is the current REST-style action. Older SOAP-era documentation referenced a `sendInvoice()` method and an `auto_send` flag (`0`/`1`) on the invoice payload itself as an alternative way to trigger sending at creation time — **verify against the current invoices module docs whether `auto_send` still works as a payload flag on `/invoices/add`, or whether the dedicated `/invoices/send` action is now the only supported path**; don't assume both exist without checking, since the SOAP-era API and the current REST-style API aren't guaranteed to share every parameter.

## Printing WZ / PZ and other warehouse documents

**There is no standalone API download/print action for warehouse documents (WZ, PZ, RW, PW, MM)** — this follows directly from the fact that there's no warehouse-document module in the API at all (see `warehouse-goods.md`). Two practical consequences:

1. **The only API-accessible route to a WZ printout** is bundling it into an invoice's PDF via the `warehouse_documents=1` parameter on `/invoices/download` (see above) — this gets you the WZ that was auto-generated as a side-effect of that specific sales document, packaged alongside the invoice.
2. **PZ (goods receipt) and any warehouse document not tied to an invoice/sales document has no API download path at all.** If Estrella Jewels' workflow needs a standalone PZ printout (e.g. for the customs-clearance PZ receipt process referenced in the project's core workflow), that has to be retrieved/printed from the wFirma UI directly (MAGAZYN » DOKUMENTY) — there's no way around this via the API as of the sources gathered for this skill. Flag this explicitly to the user rather than trying to work around it silently if it comes up.

## Customizing document content — the `description` field (Uwagi/Notes)

Confirmed field for adding free-text notes to an invoice:

- **`description`** — optional, plain text, **max 320 characters** (confirmed limit from wFirma's own API documentation example). This is the "Uwagi" (notes) field that prints on the document.
- Confirmed present in both older SOAP-era payloads and current JSON payloads (`"description": ""` appears in a 2015-era JSON `/invoices/add` example) — this field name has been stable across API generations.
- Common uses observed in real integrations: VAT exemption legal basis text (required to print on the invoice when claiming certain exemptions), a bank account number for VAT specifically (when using split-payment-style arrangements), order/reference numbers, or any other free text the business needs printed.

**320 characters is a hard practical limit** — if Estrella Jewels needs to print structured info (e.g. sales-order number + shipment reference + customs note) via this field, keep it concise and consider a fixed abbreviation scheme, since there's no confirmed secondary free-text field beyond `description` in the sources gathered here.

## What always prints regardless of what you send (UI-configured, not API-configured)

Some elements of a printed invoice/proforma are controlled by **account-level or series-level settings in the wFirma UI**, not by anything you pass on `/invoices/add`:

- The issuing company's own name/address/NIP/bank details (from `company_detail` — see `payment-and-contractor-master.md` for confirmed fields like `bank_name`, `bank_account`, `bank_swift`).
- Any **default notes configured at the series level** — if a numbering series has default notes/text configured in the UI, those may appear on documents issued against that series regardless of what you send in `description`; if what's printing doesn't match what your integration sent, check the series configuration in Ustawienia before assuming it's an API bug (see `series-and-numbering.md`).
- Legal/regulatory annotations tied to invoice `type` or VAT settings (e.g. WDT-specific legal text, VAT-exemption basis) may be templated by the system based on `type`/VAT fields rather than being literal text you supply — don't try to manually write legally-mandated boilerplate into `description` if the system already generates it based on the document type; verify what actually prints via a test document on `test.api2.wfirma.pl` before assuming you need to add it yourself.
- Split-payment (mechanizm podzielonej płatności / MPP) annotations and GTU product-group codes are known Polish invoicing concepts that most Polish invoicing systems support in some form, but the exact wFirma API field name for either was not confirmed from the sources gathered for this skill — if either is needed (e.g. GTU codes are relevant for certain jewelry/precious-metal classifications), check the current `invoices`/`goods` module docs directly rather than assuming a field name from a different Polish invoicing system (several were referenced during research and their field names are NOT interchangeable with wFirma's).

## Practical checklist for "produce and deliver a document" flows

```
1. Build and POST /invoices/add (see invoices.md) — include `description` for any required notes.
2. If email delivery is needed: POST /invoices/send/{id} with email/subject/body,
   OR fetch GET /invoices/get/{id} and build your own email using the `hash`-based public link.
3. If a local PDF copy is needed: GET /invoices/download/{id} with the right page/address/
   leaflet/duplicate/warehouse_documents flags — remember this returns raw PDF bytes, not JSON.
4. If a WZ printout is needed alongside: set warehouse_documents=1 on the download call.
5. If a standalone PZ or other warehouse document printout is needed: this cannot be done via
   API — retrieve/print from the wFirma UI (MAGAZYN » DOKUMENTY) instead.
```
