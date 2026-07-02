# Sample/Returns tabs — scope-verify STOP (read-only)

- **Date:** 2026-07-03 · read-only scope-verify · zero UI built ·
  STOP per the operator's "anything uncertain → STOP and ask"
- **Authority identified:** InventoryPage (post-fold 0cee8173).
  Wireframe of record present: docs/design/estrella-dashboard-wireframe.html
  (sha256:f7dd5e3889…) + the four design tabs in
  docs/design/inventory-page.design.jsx (SampleOutTab :380, SampleReturnTab
  :432, ClientReturnTab :481, ProducerReturnTab :538).

## Why STOP: the premise "backend already live" is materially wrong

The slice was queued as "cheapest real parity — backend already live." The
scope-verify at HEAD shows the sample/returns backend is **write-only**.

### Endpoints (exhaustive, HEAD)

| Flow | Write (exists, Phase A) | Read/list (feeds the table) | Document artifact |
|---|---|---|---|
| Sample Out | `POST /inventory/pieces/{id}/sample-out` | **NONE** | none (Phase C) |
| Sample Return | `POST /inventory/pieces/{id}/sample-return` | **NONE** | none |
| Client Return (RMA) | `POST /inventory/pieces/{id}/return-from-client` | **NONE** | none |
| Return to Producer | `POST /inventory/pieces/{id}/return-to-producer` (+ `/return-from-producer`) | **NONE** | none |

Verified: zero GET routes read `sample_out_events` / `returns_events`; no
`list_*`/`get_*` read functions in `inventory_sample_writer.py` /
`inventory_returns_writer.py`. The evidence the wireframe tables show
(sample_id, issued-to, return-by, condition, RMA invoice, RTP AWB-out) lives
in those event tables with **no read endpoint**.

### The only live sample/returns data

`GET /inventory/stage2/aggregate` returns **counts only**: `SAMPLE_OUT`
count, and a combined `RETURNED_FROM_CLIENT + RETURNED_TO_PRODUCER` count.
The Inventory hub's **Stage2Panel already displays both**. There is no
per-sample / per-return list, no return-by dates, no RMA/RTP records to read.

### What each wireframe tab would be, built honestly today

| Tab | Live | Backend-pending · Phase C |
|---|---|---|
| Sample Out | 1 KPI (SAMPLE_OUT count) | table (all rows), 3 KPIs, +Issue Sample flow |
| Sample Return | — | entire table + all KPIs + actions |
| Client Return (RMA) | — | entire table + all KPIs + actions (no RMA model/read) |
| Return to Producer | — | entire table + all KPIs + actions (no RTP/AWB model) |

Net: ~90% of the four tabs would be `BACKEND-PENDING · PHASE C` badges. That
satisfies the contract's honesty rules but is **not** "real parity" — it is
four mostly-empty tabs. Building it silently would misrepresent the slice.

## Options for the operator (decision required)

- **(a) Build the honest pending-scaffold now** — four tabs present, the one
  live KPI wired, everything else Phase-C badged. Pros: structural parity with
  the wireframe nav; honest. Cons: mostly dead UI; the live counts already
  exist in Stage2Panel.
- **(b) Add the missing READ endpoints first** — small backend slice
  (`GET` list of `sample_out_events` / `returns_events`, and a per-sample /
  per-return read) so the tables have a real feed. **Requires a freeze
  exception** — backend is frozen for the inventory phase. This turns
  Sample/Returns into genuine parity, but it is a backend slice, not a UI one.
- **(c) Defer Sample/Returns to Phase C** and do **B1 (KPI tile polish)** now
  instead — B1 is real, needs no unfreezing, and uses live
  `/inventory/stage2/aggregate` data. **Recommended**: it keeps the "no fake
  data / real parity" bar while the read endpoints wait for a proper backend
  slice.

## Recommendation

**(c)** now (B1 KPI polish — real, live, no freeze exception), and schedule
**(b)** (the sample/returns read endpoints) as an explicit backend slice with
a freeze exception when you want the four tabs to be genuine. Building four
pending-badged tabs (a) is honest but low-value dead UI, and the operator's
"cheapest real parity" intent points away from it.

No UI was built; the InventoryPage is untouched. Slice HELD for your decision.
