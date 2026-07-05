# Document Lifecycle: Reservation → Proforma → Invoice

This is the real Estrella Jewels sales flow (matches the project's own documents: `PROF_XX_2026` proforma files converted into `Faktura_WDT_XX_2026`). It spans **three distinct wFirma concepts that behave very differently from an API standpoint** — read this before designing any code that assumes they're three stages of one linear API-writable pipeline. They are not equally API-accessible.

## The three stages and their API reality

| Stage | wFirma concept | API-writable? | Notes |
|---|---|---|---|
| 1. Reservation | Rezerwacja (MAGAZYN » REZERWACJE) | **No — UI-only** | Confirmed: no API endpoint to create/manage reservations. Only available in extended-warehouse packages. |
| 2. Proforma | Invoice with `type: "proforma"` | **Yes** | Same `/invoices/add` endpoint as a normal invoice, just a different `type` value and its own numbering series. |
| 3. Invoice (from proforma) | Invoice with `type: "normal"` (or the relevant VAT/non-VAT type) | **Yes, but NOT via a "convert" action — there isn't one** | Built as a **new** `/invoices/add` call using data read from the proforma, not an in-place conversion. |

## Stage 1 — Reservations: plan around UI-only, don't build API automation for it

Reservations (rezerwacje) are entirely a UI feature:
- Created manually in MAGAZYN » REZERWACJE » DODAJ (contractor + reserved goods list + price group + source warehouse).
- On save, status becomes **OCZEKUJĄCA** (pending), and the reserved quantity is moved from "available" to "reserved" in MAGAZYN » PRODUKTY stock views.
- Realized (WYSTAW) manually from the reservation into one of: **WZ, invoice, proforma invoice, sales receipt (dowód sprzedaży), fiscal receipt, or a new order** — any of these auto-decrements stock and links back to the reservation (an icon shows the linkage both ways).
- Status becomes **ZREALIZOWANA** (fulfilled) once a document is issued against it, or **W REALIZACJI** if an order was generated instead.
- wFirma explicitly introduced reservations as the **safer replacement for negative stock** (confirmed on the forum: "Ujemne stany magazynowe nie zostały całkowicie usunięte, zastąpiliśmy je bezpieczniejszą opcją - możliwością korzystania z rezerwacji" — negative stock wasn't fully removed, it was replaced by the safer option of reservations).

**Implication for the Estrella Jewels integration**: if the external system (order intake, DHL-linked workflow) needs to represent "this stock is earmarked for client X before we're ready to bill," that earmarking has to be tracked **in your own system**, not by calling a wFirma reservation API — there isn't one. You can still read current stock levels via `/goods/find` to see the net effect of any reservations made manually in the UI (reserved quantity is reflected in the stock numbers), but you cannot create/query/realize reservations programmatically. Don't design a feature around "auto-create a wFirma reservation via API" — redirect that requirement to either (a) a UI step a human does, or (b) tracking the earmark in the external system and only touching wFirma at the proforma/invoice stage.

## Stage 2 — Proforma invoices via API

A proforma is created exactly like a normal invoice via `/invoices/add`, with `type` set to the proforma value (confirmed via query examples filtering `type eq "proforma"`). Everything in `invoices.md` about payload shape, JSON numbering, and contractor references applies identically.

**Key difference from normal invoices — numbering series**: proformas draw from **their own dedicated numbering series** (Seria numeracji faktur pro forma), separate from the normal-invoice series. If your integration needs predictable numbering across both document types, don't assume they share a counter — check the specific `series.id` configured for proformas vs. normal invoices in Ustawienia, and pass the correct `series.id` explicitly for each (see `references/ui-help-center-index.md` → numbering series article for the UI-side configuration).

A proforma issued this way lands in **PRZYCHODY » PRO FORMY** (a separate tab from PRZYCHODY » SPRZEDAŻ where normal invoices live).

## Stage 3 — Converting proforma → invoice: there's no "convert" endpoint

⚠️ **This is a confirmed, documented trap** (from a wFirma-support forum reply): there is **no dedicated API action** like `/invoices/convert` or `/invoices/proforma-to-invoice`. Building an invoice "from" a proforma via the API means:

1. `GET /invoices/get/{proforma_id}` to read the proforma's data (contractor, line items, amounts).
2. Construct a **new, separate** `POST /invoices/add` request with `type` set to the real invoice type (e.g. `normal`), using the data pulled from the proforma.
3. **Do NOT blindly copy the entire proforma response into the new invoice payload.** wFirma support explicitly diagnosed a numbering bug as caused by an integrator passing proforma response data (including **internal fields that control numbering format**) directly into `/invoices/add`. The fix: construct the new invoice payload deliberately from only the fields actually needed to issue a VAT invoice (contractor, line items/content, dates, payment info, currency, `series.id` for the invoice series) — don't pass through the proforma's own `id`, `fullnumber`, `number`, or any numbering-related branch.

**Recommended implementation pattern for this project:**

```
1. Fetch proforma: GET /invoices/get/{proforma_id}
2. Extract only: contractor.id (or full contractor block), invoicecontents (line items),
   currency, payment terms/dates you want to reuse
3. Build a fresh invoice payload with type=normal (or the correct VAT/non-VAT type),
   an explicit series.id for the INVOICE series (not the proforma series),
   and today's/desired date — do not copy proforma.id / proforma.number / proforma.fullnumber
4. POST /invoices/add with that fresh payload
5. Store a mapping in YOUR OWN system between proforma_id and the resulting invoice_id —
   wFirma does not automatically link them the way it links a reservation-issued document
```

**If the reservation → document chain was realized via the UI** (WYSTAW from a reservation), wFirma *does* auto-link reservation ↔ resulting document with a visible icon in the UI — but that linkage is a UI/reservation-realization feature, not something the plain `/invoices/add` API call produces on its own. Don't assume calling `/invoices/add` for an invoice will automatically associate it with an earlier proforma or reservation — you must track that association yourself if the flow goes through the API rather than the UI's "WYSTAW" action.

## Full flow summary for this project

```
[External system: order confirmed, stock earmarked]
        │  (tracked in YOUR system — no wFirma API call yet, unless a human
        │   also creates a UI reservation for internal warehouse visibility)
        ▼
[Proforma invoice]  → POST /invoices/add, type=proforma, proforma series.id
        │  (sent to client for confirmation/prepayment — lands in PRZYCHODY » PRO FORMY)
        ▼
[Client confirms / pays]
        │
        ▼
[Real invoice]  → GET /invoices/get/{proforma_id} to pull data,
                   then POST /invoices/add, type=normal, invoice series.id
                   (fresh payload — don't copy proforma numbering fields)
        │  (KSeF send + warehouse WZ side-effect happen here if applicable —
        │   see invoices.md and warehouse-goods.md)
        ▼
[Your system: record proforma_id ↔ invoice_id mapping yourself]
```

Cross-references: `invoices.md` (payload shape, KSeF, warehouse_type), `warehouse-goods.md` (why reservations/warehouse documents aren't API-writable), `gotchas.md` (quick-scan entries for this flow).
