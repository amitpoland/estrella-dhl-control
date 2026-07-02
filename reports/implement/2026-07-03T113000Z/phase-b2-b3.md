# Phase B slices B2 + B3 — build + render-check record

- **Date:** 2026-07-03 · existing authorities extended only, zero new
  pages/routes · no deploy
- **Declared:** PROJECT_STATE DECISIONS "Phase B slices B2+B3" before edits.

## What was built

**B2 — Promotion Notes panel** (the BE-2 v1 document viewer):
- pz-api.js: `getPromotionNotes(batchId)`, `getPromotionNote(noteNo)` —
  noteNo is slash-bearing (SPN/NNN/YYYY): encoded PER SEGMENT
  (split/map/join) so slashes stay literal separators for the :path route;
  whole-id encoding pinned OUT.
- inventory-page.jsx: sixth InvPanel `panel-promotion-notes` on the EXISTING
  Inventory page — batch input → header table (note_no/trigger/pieces/
  operator/created) → per-note Lines expansion (scan_code/design/before/
  after); honest empty state; read-only disclaimer; endpoints footer updated.

**B3 — real client_po**: proforma-detail.jsx :2542 now prefers
`pk.client_po` (persisted since 494c4665); `invoice_no || client_ref`
survives only as the legacy fallback for pre-fix '' rows. Comment cites
the commit + DECISIONS.

## DEFECT FOUND BY THE RENDER CHECK (pre-existing, production-affecting)

Typing into ANY Inventory-hub panel input crashed the page tree
("batchId.trim is not a function") — including the UNTOUCHED Sprint-30
AuditPanel. Root cause, proven live on the running app:
**Babel-standalone hoists compiled destructure helpers
(`var _excluded = [...]`) OUTSIDE each file's IIFE into global scope; every
later-loaded V2 script overwrites them.** `window._excluded` held another
file's Button prop-list (`children,onClick,disabled,title,warn,style`), so
InvInput's `rest` kept `onChange`, `{...rest}` overrode the wrapper, the
raw state setter landed on the `<input>`, and the first keystroke stored
the SyntheticEvent into state. Proof chain in-session: identical crash on
AuditPanel; isolated re-eval of the same file (fresh helpers) typed fine;
mounted fiber props showed native-code onChange; live `_excluded` globals
dumped. **Fixed for inventory-page.jsx in this slice**: spread-rest removed
from InvInput/InvFetchBtn via explicit `'data-testid'` destructuring —
call sites and sprint-30 source pins byte-identical; drop-can't-return pin
added (`test_inventory_page_has_no_spread_rest_components`).
**Follow-up (own slice, recorded in DECISIONS): sweep all v2 files for
spread-rest components exposed to the same collision.**

## Render check (LIVE app, throwaway storage copy — never the tracked DB)

Booted uvicorn on port 8156 with STORAGE_ROOT → a scratchpad copy of the
verify storage; seeded Note SPN/001/2026 (batch SHIPMENT_RENDER_B2, 2
lines) via the real writer, and stamped client_po='PO-RENDER-B3' on draft
1's sales lines.

- API sanity: GET /api/v1/inventory/promotion-notes/SHIPMENT_RENDER_B2 →
  200, total=1 (proves STORAGE_ROOT + route + seed).
- Inventory page: 6 panels mount; post-fix flow: typed batch id →
  Load notes → row `SPN/001/2026 · pz_created · 2 · render-check` →
  Lines expansion `SC-R1 D-101 PURCHASE_TRANSIT→WAREHOUSE_STOCK` +
  `SC-R2 D-102 …`. Zero NEW console errors (buffer entries are the
  pre-fix crash history). Screenshot taken (panels + subnav render clean).
- B3 visual: proforma detail draft 1 loads clean (draft data renders, no
  errors). HONEST LIMIT: the Client PO column lives in the packing/CMR
  DOCUMENT views; this draft's toolbar exposes only the proforma Print
  (no Client PO column by design), so PO-RENDER-B3 was not visually
  confirmable from this page — covered instead by the source pin, the
  semantics pin, and the persistence round-trip test (494c4665 suite).
  Full visual lands with the parity slice's document-view pass.

## Gates

```
tests/test_phase_b2_b3_pins.py            10 passed (incl. SPN/001/2026
  route round-trip + slash-encoding pins + spread-rest immunity pin)
sprint30 + sprint43 suites                 green, unmodified assertions
tests/test_stock_promotion_note.py         10 passed (route unchanged)
PYTHONUTF8=1 python test_pz_regression.py  160/160 golden PASS
```
