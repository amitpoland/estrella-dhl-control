# Phase B B1 — Overview KPI tile polish: build + render record

- **Date:** 2026-07-03 · InventoryPage restyle in place · no new pages/routes ·
  no deploy
- **Declared:** PROJECT_STATE DECISIONS "Phase B B1" (operator ruling "c":
  defer Sample/Returns, do B1, no pending-scaffold tabs, no fake read data;
  live-tabs-only assumption recorded).
- **Wireframe of record:** docs/design/estrella-dashboard-wireframe.html
  (sha256:f7dd5e3889…). Ported region: InvStatTile (design/
  inventory-page.design.jsx :28-43).

## What changed

- Ported the wireframe `InvStatTile` into inventory-page.jsx (label uppercase
  0.10em tracking · value fontSize 22 · optional pending badge).
- Stage-2 overview tiles restyled from 3 StatBadges to a 4-tile InvStatTile
  row: Final stock (green, `s2.final_stock.count`), Samples out (amber,
  `s2.samples.count`), Returns (red, `s2.returns.count` + client/producer
  subcounts), Consignment.
- **Consignment tile = clean BACKEND-PENDING · PHASE C badge** — the aggregate
  genuinely returns not-available (no CONSIGNMENT state/table); never a fake
  number. The engineer-facing basis stays in the API `data.limitations`.
- **Removed** the raw diagnostic limitations paragraph from the UI (the
  "…strict residual…" dump); its content lives in the API response.
- No new tabs, no layout restructure beyond the tile row.

## Acceptance gate

- **Side-by-side vs wireframe:** 4 KPI tiles in the InvStatTile look (label
  small-caps, large tone-colored value, hint below) — matches the design
  tile. Element count: 4 tiles (3 live + 1 pending), 1 refresh control.
- **No new page/route:** InventoryPage only; nav unchanged (single flat
  Inventory entry post-fold).
- **No fake data:** tiles read `/inventory/stage2/aggregate` only; grep pin
  asserts no wireframe demo numbers (2.41M / 1,847 / PLN 2.) leaked. Render
  check against the throwaway DB shows **real zeros** (correct — the DB has no
  stock) with the correct state labels.
- **Consignment honest:** pending badge, not a number.
- **Standing pins:** no raw-ID paste inputs added; no spread-rest
  (sweep pin green); collision-safe (`window._excluded` undefined live).
- **Render check (cold origin :8171, throwaway storage):** Final stock
  "0 · WAREHOUSE_STOCK", Samples out "0 · SAMPLE_OUT", Returns "0 · 0 client ·
  0 producer", Consignment "BACKEND-PENDING · PHASE C · physically with
  client · title retained"; diagnostic paragraph gone; console **clean**;
  screenshot captured.
- **Golden:** 160/160.

## Gates

```
test_phase_b1_kpi_tiles (7) + sprint30 + fold parity/retirement + sweep +
  rest-forwarding → all green (86+ across the run)
PYTHONUTF8=1 python test_pz_regression.py → 160/160 golden PASS
```

## Minor note (not blocking)

In the narrow 4th column the "BACKEND-PENDING · PHASE C" badge wraps to two
lines — functional and honest; a future polish pass could shorten the badge
or widen the tile. Recorded, not fixed (out of B1's tile-restyle scope).
