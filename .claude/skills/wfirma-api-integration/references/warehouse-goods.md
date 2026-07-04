# Warehouse / Stock (`goods` module + Magazyn) — READ BEFORE DESIGNING ANY STOCK SYNC

This is the single most important "don't get stuck" file in this skill for any integration that needs to track or move stock. **wFirma's public API does NOT support direct creation of warehouse documents.** This is confirmed repeatedly by wFirma support on their own forum, and has not changed as of the last check — always re-verify on doc.wfirma.pl before assuming this has changed, but architect defensively around this limitation.

## What the API CAN do

- **`goods` module**: read/write product (towar) records — name, price, EAN/code, and **current stock level** can be read via `/goods/find` and `/goods/get/{id}`.
- Products are referenced **by their wFirma `id`**, not by SKU/EAN/code — when building invoice line items that should pull from warehouse stock, you must resolve your external product identifier (EAN, SKU) to the wFirma `goods.id` first (via a `find` with a condition on the code/EAN field), then reference that id in the invoicecontent — do not assume the API accepts your external code directly as a line-item identifier.
- **Stock changes happen indirectly**, as a side effect of issuing sales/purchase documents through the API that ARE supported (invoices, receipts) — see below.

## What the API CANNOT do (as of last verification — re-check before relying on this)

- **No direct API endpoint to create warehouse documents**: PZ (przyjęcie zewnętrzne / goods receipt), WZ (wydanie zewnętrzne / goods issue), RW (rozchód wewnętrzny / internal consumption), PW (przyjęcie wewnętrzne / internal receipt), MM (przesunięcie międzymagazynowe / inter-warehouse transfer) **cannot be created directly via the API**. wFirma support has explicitly and repeatedly declined to commit to a timeline for adding this.
- **The only way to affect a WZ (stock reduction) via API is indirectly**, by issuing a sales document (invoice or receipt) via `/invoices/add` with:
  - Line items that reference actual `goods.id` records (not free-text lines), AND
  - `warehouse_type` **not** set to `"simple"` (see `invoices.md`)
  - This triggers wFirma's internal logic to auto-generate the WZ and decrement stock — the WZ itself still isn't something you POST directly; it's a side effect.
- **The only way to affect a PZ (stock increase) via API is indirectly**, similarly, by recording a purchase/expense document that includes goods line items — check the expenses module's own docs for the exact payload shape required to trigger this, since expenses aren't covered in depth in this skill (add a reference file here if the project's scope expands to expenses in detail).
- **Negative stock is blocked by design** — the system will not allow a stock level to go negative (this is intentional, related to FIFO valuation and JPK_MAG reporting requirements). If your integration logic assumes it can oversell and reconcile later, redesign around this — an API write that would drive stock negative should be expected to fail or be rejected, and your error handling must account for this as an expected case, not a bug.
- **Warehouse-level bulk import (CSV) is a UI-only feature** — there's no documented API equivalent for bulk product/stock import; if you need to seed/bulk-load stock, either use the UI's CSV importer once, or add products one-by-one via `/goods/add`.

## Architectural implication for the Estrella Jewels integration

Because warehouse *documents* aren't directly API-writable, do NOT design the integration around "create a WZ/PZ via API" as a primitive. Instead:

1. **For outbound stock (sales/shipping via DHL)**: model it as "issue an invoice/receipt with the shipped goods as line items, referencing `goods.id`, with warehouse effect enabled" — the WZ is a side effect you can read back afterward (via the invoice or via `goods` stock levels), not something you request directly.
2. **For inbound stock (purchases/receiving)**: model it through the expenses/purchase-document flow, not a direct warehouse-document call.
3. **For real-time stock visibility in the external system**: either poll `/goods/find` for current stock levels, or (better, per wFirma's own recommended pattern) use a **webhook on "Produkty » Zmiana ilości na magazynie" (Products » Stock quantity change)** to get pushed updates instead of polling — see `webhooks.md`.
4. **If a stakeholder asks for "create a WZ via the wFirma API directly"** — this is not possible today; the honest answer is that it must be done through the invoice/receipt/expense flow as a side effect, or manually in the wFirma UI. Flag this explicitly rather than attempting to build around it silently — it changes what's architecturally possible.

## Extended warehouse module (Magazyn) — context

The full warehouse module (reservations, production/kitting - kompletacja, expiry dates, price groups) is a UI-level feature set for VAT-registered and VAT-exempt users alike, gated by subscription package (Fakturowanie + Magazyn, or Księgowość online + Magazyn). None of these extended warehouse features (reservations, kitting/production documents, expiry-date tracking) have documented API write support as of last check — treat any request to automate them via API as currently infeasible until re-verified against doc.wfirma.pl.
