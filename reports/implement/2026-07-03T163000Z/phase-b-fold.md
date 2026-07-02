# Phase B FOLD — Move Location → Inventory Move Stock modal: build + parity + retirement

- **Date:** 2026-07-03 · existing Inventory authority extended; standalone page
  RETIRED · net page count −1 · no deploy
- **Declared:** PROJECT_STATE DECISIONS "Phase B FOLD" (rules verbatim + Lesson
  M relocation + the design-tension resolution). Wireframe of record:
  docs/design/estrella-dashboard-wireframe.html (sha256:f7dd5e3889…) +
  docs/design/inventory-page.design.jsx (the MoveStockModal at design lines
  1023-1142 is the ported region).

## Design-tension resolution (why the port isn't literal)

The wireframe MoveStockModal selects a stock_unit by a PASTE input + qty —
FORBIDDEN by the operator rule "no raw internal-ID paste." The only non-paste
live selection feed is BY-LOCATION: GET /warehouse/locations → GET
/warehouse/locations/{code}/inventory (the location feed carries scan_code,
the key movePieceLocation moves by). So selection = source-location SELECT →
pieces-at-location CHECKBOX → destination-location SELECT → note. Contexts with
no non-paste feed are PENDING-BADGED (never a paste box): (a) freshly-received
stock not yet at a location, (b) the wireframe's "Stage transition" type.

## STEP 3 — PARITY GATE (element-by-element; the gate could have failed)

Side-by-side, wireframe MoveStockModal vs the folded modal:

| Wireframe element | Folded modal | Verdict |
|---|---|---|
| Title "Move Stock", wide modal | window.Modal title="Move Stock" wide | ✅ match |
| Move-type toggle wh→wh / stage | ms-type-wh-wh (active) / ms-type-stage | ✅ match; stage **disabled + BACKEND-PENDING·PHASE C badge** (honest) |
| Stock-unit PASTE input + qty | REPLACED — source-location select + checkbox list | ✅ rule-compliant (no paste) |
| From / To selects | ms-source / ms-destination selects (real locations) | ✅ match, live data |
| Reason / notes textarea | ms-note textarea | ✅ match |
| Audit-preview line | per-piece results (ms-results / ms-result-row) | ✅ carried from page (real backend echoes) |
| Cancel / Confirm | ms-cancel / ms-submit (gold) | ✅ match |
| — (page behavior) | five error states, synthetic-disable, sequential per-piece + idempotency key | ✅ carried from move-location-page |
| — | unlocated-stock pending badge (ms-pending-unlocated) | ✅ honest Phase-C |

Grep pin (drop-can't-return): the modal's ONLY `<input>` is `type="checkbox"`
— zero paste inputs (test_phase_b_fold_parity).

## STEP 3c — render check (cold origin :8166, throwaway storage)

Seeded 2 real locations + 3 located WAREHOUSE_STOCK pieces (also in
packing_lines — the move route resolves pieces there). Live flow:
- Modal opens from the hub's ⇄ Move Stock action; stage-transition disabled +
  pending-badged; unlocated pending badge present.
- Source SHELF-A4 → 3 pieces listed from the real location feed → checkbox
  select → destination SHELF-B2 → submit.
- **Real moves executed: SC-F2, SC-F3 → "moved → SHELF-B2"** (green per-piece
  rows). Direct API confirm: SC-F1 POST → 200 `status:"moved"`, movement event
  written, from SHELF-A4 to SHELF-B2.
- Error states proven live: blank-operator refusal (identity guard) and
  404 PIECE_NOT_FOUND both rendered with their distinct hints.
- Collision pin holds: window._excluded undefined; AuditPanel types clean.
- Screenshot captured (modal in the wireframe's design language).

**PARITY VERDICT: PASS** → retirement authorized (STEP 4).

## STEP 4 — retirement (executed, parity having passed)

- `move-location-page.jsx` DELETED (git rm).
- index.html: script tag removed; render block removed; `move_location:
  'inventory'` added to ROUTE_REDIRECTS (stale-URL insurance, now 13 entries).
- components.jsx: g_inventory NAV group COLLAPSED → flat `{id:'inventory'}`.
- mock-badge.jsx: WIRED_PAGES 19 → 18 (move_location removed).
- test_move_location_promotion.py → renamed test_phase_b_fold_retirement.py,
  rewritten to pin the retirement + the folded modal.
- sprint43 count pin 19 → 18; sprint30 pins hold.

Net page count DECREASED by one; zero new pages/routes/HTML.

## Gates

```
test_phase_b_fold_retirement + test_phase_b_fold_parity + sprint30 + sprint43
  + phase_b2_b3 + v2_no_spread_rest → 120+ passed
targeted rerun (retirement+fold+sprint30+sprint43) → 77 passed
PYTHONUTF8=1 python test_pz_regression.py → 160/160 golden PASS
```

## Follow-ups (recorded, Phase C)

Non-paste picker for freshly-received (unlocated) stock; the Stage-transition
move-type (promotion/sample/return write UIs). Both pending-badged in the
modal, never faked. Next approved slice order: Sample/Returns tabs → B1 KPI.
