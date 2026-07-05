# Inventory Mapping Gate — design authority ↔ existing V2 (Phase B)

- **Date:** 2026-07-03 · read-only mapping + one design copy · no UI edits ·
  ends with STOP-for-operator-approval.
- **Authorities:** UI = the wireframe, now durable at
  [docs/design/inventory-page.design.jsx](docs/design/inventory-page.design.jsx)
  (copied from the estrella-dashboard bundle; the builder now HAS the design).
  Code = `service/app/static/v2/inventory-page.jsx` (the sole Inventory
  authority; no duplicate page).
- **Disposition (i) CONFIRMED by the wireframe:** the design has NO standalone
  move page — "Move Stock" is an Overview action CARD opening a
  `MoveStockModal` (design lines 663-685, 1023-1142). Folding
  move-location-page.jsx into Inventory as an action/modal is exactly the
  design, not just the operator's call.

## The gap in one line

The design is an **11-tab merchandising Inventory screen**; the live V2 is a
**6-panel read-only lookup hub**. Most of the parity gap is **frozen-blocked**
(no backend). This is a multi-slice campaign, not one slice — the map below is
the sequencing input, and it ends at a STOP for the operator to pick order +
approve the fold.

## Design surface (what the wireframe shows)

Tabs (grouped): Overview · [S1] Temp Purchase / Temp Warehouse / Temp Sale ·
[S2] Consignment / Final Stock / Sample Out / Sample Return / Goods Return
from Client / Return to Producer · Identity/Mapping. Each tab = KPI stat-tile
row + a real-column table + contextual actions. Overview = 3 action cards
(Upload Document, Move Stock, Identity/Mapping) + KPI tiles + Stage-1/Stage-2
navigator cards + a recent-movements ledger. Two modals: MoveStockModal
(wh→wh transfer OR stage transition), UploadDocumentModal (typed drop-zone →
routes to the matching tab).

## Mapping table (design element → V2 element → disposition)

Disposition legend: **LIVE** = backend exists, portable now · **PARTIAL** =
some backend, needs enrichment · **FROZEN** = needs backend that is frozen
(Phase C) · **N/A-DESIGN** = mock-only design affordance, no real data source.

| Design element | Existing V2 | Backend today | Disposition |
|---|---|---|---|
| Overview: KPI tiles (stock units/pieces/value/reorder) | Stage2Panel StatBadges (Final/Samples/Returns) | GET /inventory/stage2/aggregate | **LIVE (B1)** — polish tiles to design tone; value/reorder tiles are FROZEN (no valuation/reorder backend) |
| Overview: Move Stock action card → MoveStockModal | move-location-page.jsx (standalone, LIVE) | POST /inventory/pieces/{id}/location | **LIVE fold (step 6)** — port page into an Inventory modal; retire the standalone page (Lesson M) |
| Overview: Upload Document card → UploadDocumentModal | — (Documents hub is separate authority) | routes_upload exists | **PARTIAL** — link to existing upload authority, not a new uploader; typed-routing is FROZEN |
| Overview: Identity/Mapping card + tab | IdentityMappingPage stub (wireframe-update.jsx) / wfirma_setup | wfirma mapping reads | **PARTIAL/FROZEN** — the 8-field identity model + trace_barcode is largely net-new backend |
| Overview: recent-movements ledger | — | inventory_state_events + promotion notes exist | **PARTIAL** — a real movement feed is buildable from events; design's per-SU rows need the stock-unit model (FROZEN) |
| Promotion Notes panel (our BE-2 addition) | panel-promotion-notes (LIVE, shipped 0602ddd3) | promotion-notes GETs | **LIVE — already shipped.** Not literally in the wireframe (the design's equivalent is the movement ledger); keep as the document-trail viewer |
| Batch/Piece/Location/Audit lookup panels | 4 live panels | live read endpoints | **LIVE** — these are honest read tools; keep (design folds them into Final Stock / trace, but no need to remove working reads) |
| Final Stock tab (Stock Unit ID/Family/Design/Batch/Bag/Qty/Location/Value/wF ref) | LocationPanel + Stage2 final count | WAREHOUSE_STOCK state; NO stock_unit_id / valuation / location-value model | **FROZEN** — merchandising columns need the joined read (design_no in state; karat/stone/weights in packing_lines) + a stock-unit + valuation model |
| Temp Purchase / Temp Warehouse / Temp Sale tabs | none (redirect slugs) | PURCHASE_TRANSIT state exists; temp-warehouse discrepancy / temp-sale reservation gate = net-new | **FROZEN** — the temp-stage document layer is Phase C |
| Consignment tab | ConsignmentTab stub (unused) | NONE (no state/table/route) + wFirma MM API answer still open | **FROZEN ×2** (no backend + MM-gated) |
| Sample Out / Sample Return tabs | redirect slugs; design stubs | routes_inventory_sample LIVE (evidence-gated writes + idempotent events) | **PARTIAL — cheapest real win**: backend exists, UI absent; port design tabs wired to the live routes |
| Goods Return / Return to Producer tabs | redirect slugs; design stubs | routes_inventory_returns LIVE (returns migration pending at deploy) | **PARTIAL** — same as above; credit/debit-note affordances stay FROZEN (Sales/wFirma) |
| client_po column (design Temp Purchase) | proforma-detail real column | client_po persisted (494c4665) | **LIVE — shipped (B3).** |

## Reconciliation with the operator's 6-step order

- Steps **4 (B2) and 5 (B3) are ALREADY SHIPPED** (0602ddd3 / cf409ef3) —
  Promotion Notes panel live on Stock Hub, client_po real column live. No
  rebuild. (B2 is our own document-trail addition; the wireframe's nearest
  equivalent is the movement ledger — keep B2 as the Note viewer.)
- Step **1 (wireframe)** — done this turn (copied to docs/design/).
- Step **2 (mapping gate)** — this document.
- Step **3 (B1 KPI polish)** — the next buildable slice (LIVE data; the
  value/reorder tiles stay honest-pending).
- Step **6 (fold)** — LIVE and wireframe-confirmed; it needs its OWN pre-flight
  (Lesson M relocation record: retire move-location-page.jsx, nav child,
  WIRED_PAGES, redirect, rewrite the 27-ref promotion test to pin the modal).

## Honest scope statement

Full design parity = ~9 tabs + 2 modals + a stock-unit/valuation model. **The
majority is FROZEN behind Phase-C backend** (temp stages, consignment+MM,
stock units, valuation, identity model, typed upload routing). What is
buildable NOW without unfreezing anything: **B1** (KPI polish), the **fold**
(step 6), and **Sample/Returns tabs** (backend already live — the cheapest
real parity gain). Everything else waits for Phase C, shown honestly as
`planned`/`backend-pending` (Lesson M five-state), never faked.

## STOP — operator decisions needed before any Inventory edit

1. **Order the buildable slices**: B1 (KPI polish) · fold (step 6) ·
   Sample/Returns tabs — which first? (My recommendation: **fold first** — it's
   the (i) decision already made and clears the standalone-page debt; then B1;
   then Sample/Returns as the first real parity expansion.)
2. **Confirm the fold's retirement scope** (move-location-page.jsx + nav +
   WIRED_PAGES + redirect + test rewrite) for its pre-flight.
3. **Tab adoption**: do you want the full 11-tab shell scaffolded now (with
   FROZEN tabs shown as backend-pending), or added tab-by-tab as backend
   unfreezes? (Recommendation: tab-by-tab — a scaffold of 9 empty
   backend-pending tabs is mostly dead UI today.)
