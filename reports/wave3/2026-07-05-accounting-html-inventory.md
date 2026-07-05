# Accounting — HTML DOM inventory + classification (authoritative spec, FULL HTML PORT)

**Date:** 2026-07-05 · Source: live Playwright DOM extraction of the pinned wireframe (f7dd5e38) Accounting screen (`AccountingHub`), not memory. Classification vs current React (`accounting-hub.jsx`).

## Compliance-term verdict (definitive)
**KSeF · JPK · KPO — ABSENT** from the wireframe (0 elements). VAT appears only in CSS variable/token names, not as a visible panel/label. → **Do NOT build KSeF/JPK/KPO/VAT panels** (never fabricate; the wireframe does not prescribe them).

## Left rail (HTML authority — document-type organization, 13 items / 5 groups)
`Overview` · **SALES DOCUMENTS**: Proforma(PI) · Invoice(INV) · Credit Note(CN) · **WAREHOUSE DOCUMENTS**: WZ · PZ · PW · RW · MM · **LEDGERS**: Client Balance · Client Ledger · Supplier Ledger · **SYSTEM**: wFirma Sync. + "Source" card ("mapped from wFirma · last sync 2h ago").

## Section inventory + classification

| Section | HTML content | Class | Backend |
|---|---|---|---|
| Overview | 4 KPI (Sales receivable/overdue/Supplier payable/Last-sync) + 2 count panels (Sales docs PI/INV/CN/WZ · Warehouse PZ/PW/RW/MM, **rows are jump-links**) + document-map (PI→INV→WZ→PZ→CN) | **REUSE + PORT** | KPI/counts = no aggregate endpoint → Backend Pending; jump-links = PORT |
| Proforma (PI) grid | Number/Date/Party/Net/Tax/Gross/Cur/State/wFirma/View | **REUSE** | `/proforma/search` exists (SalesProformaTab) |
| PZ grid | Number/Date/Party/Items/Linked/State/wFirma/View | **REUSE** | `/dashboard/batches` exists (PurchaseLedgerTab) |
| Client Ledger | dropdown(All clients) + Date/Party/Ref/Desc/Debit/Credit/Balance | **REUSE** | existing LedgersPage (ClientLedgerTab) |
| Invoice(INV)/Credit Note(CN)/WZ/PW/RW/MM grids | AccDocGrid tables (same shape) | **PORT** | **`GET /accounting/{type}` — does NOT exist → Backend Pending** |
| Client Balance | Client/Open/Overdue/Last30d/YTD/Cur/State | **PORT** | **`GET /ledger/clients` — does NOT exist → Backend Pending** |
| Supplier Ledger | dropdown(All suppliers) + Debit/Credit/Balance | **PORT** | **`GET /ledger/suppliers` — does NOT exist → Backend Pending** |
| wFirma Sync (inline) | 3 KPI (Synced 9/10 · Last sync · Failed 0) + mapping table (Type/Code/endpoint/Count/State/Re-sync) | **PORT** | **`POST /wfirma/sync/{type}` — does NOT exist → Backend Pending** (current React navigates out; HTML shows inline) |
| Header: API Checklist | opens API-wiring modal | REUSE (App-level `showApiChecklist`) | live |
| Header: Sync wFirma / Export; per-grid Sync/Export/+New/View; Refresh/Re-sync | wireframe **stubs** (no onClick) | PORT (render; execution Backend Pending / gated) | — |

## Interactions (HTML)
- Rail click → `setSection(id)` (in-component state, no URL change). Overview count rows → jump to section. API Checklist → modal. **Everything else is a wireframe stub** (Sync/Export/+New/View/Refresh/Re-sync/dropdown-onChange all unwired).

## Authority Gaps / Backend Gaps (new endpoints — operator approval)
1. `GET /api/v1/accounting/{type}` (INV/CN/WZ/PW/RW/MM grids).
2. `GET /api/v1/ledger/clients` (Client Balance).
3. `GET /api/v1/ledger/suppliers` (Supplier Ledger).
4. `POST /api/v1/wfirma/sync/{type}` (wFirma Sync re-sync + inline mapping counts).
   → Until these exist, render the complete UI with honest `Backend Pending` (UI-before-backend).

## Architecture conflict (STOP — one ruling needed)
The wireframe Accounting rail does **NOT** contain **Master Data** or **Audit Trail** (both currently in the live React rail, wired). FULL HTML PORT (HTML owns nav) implies they leave the Accounting rail — but that removes operator-visible capability (**Lesson M**). Master Data is still reachable via Setup nav; **Audit Trail's only entry point today is the Accounting rail.** Ruling needed: (a) remove both per HTML (Audit Trail must get an alternate entry point to satisfy Lesson M), or (b) retain them in the Accounting rail's System group as an EJ extension beyond the wireframe.

## Port plan (reuse-first; render all UI even where Backend Pending)
Rail → 13 document-type items. Sections: reuse SalesProformaTab (PI), PurchaseLedgerTab (PZ), ClientLedgerTab (Client Ledger); build AccDocGrid (INV/CN/WZ/PW/RW/MM), AccBalance (Client Balance), AccLedger (Supplier Ledger), inline AccWfirmaSync — all with honest Backend Pending. Overview kept (maps 1:1) + count-panel jump-links added.
