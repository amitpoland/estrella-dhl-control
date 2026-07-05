# BE-2 — Stock Promotion Note: read-only scope pass

- **Date:** 2026-07-02 · read-only · zero edits · disk-first
- **Operator contract (verbatim):** "Stock Promotion Note created on every
  Temp Warehouse -> Final Stock move, recording: source stage, destination
  stage, packing list / import reference, design numbers, batch numbers,
  piece count, operator, timestamp, reason/note, before/after inventory
  state."
- Model mapping (per DECISIONS): Temp Warehouse = PURCHASE_TRANSIT, Final
  Stock = WAREHOUSE_STOCK; the move = BE-1's shared `run_stock_promotion()`
  (0900b227).

## 1. WRITER INTEGRATION — one hook, both paths

The Note writes **inside `run_stock_promotion()`** (stock_promotion.py), after
the per-piece loop and before the summary mirror. Because BE-1 made this the
ONE shared function, the auto path (pz_created via routes_wfirma :2799 +
global_pz_push :633), the generation path (pz_generated via routes_upload
delegation), and the future manual endpoint all produce **identical Notes
with zero extra integration** — the manual path is just another caller.

In scope at the hook point (all already in local variables):
- `batch_id`, `trigger`, `source`, `operator`, `note` (function args)
- the per-piece loop (stock_promotion.py:82-104) holds each promoted piece's
  `sc` (scan_code), the full packing `line` dict, and the pre-transition
  state read `st` — **before/after state is capturable per piece without any
  extra query** (before = st["state"] == PURCHASE_TRANSIT precondition,
  after = WAREHOUSE_STOCK). The engine's event insert does not return its
  event id (inventory_state_engine.py:701-708, fresh uuid not surfaced), so
  the Note records before/after itself rather than referencing event rows.
- `wfirma_pz_doc_id`: read from `audit.json → wfirma_export.wfirma_pz_doc_id`
  (written at routes_wfirma.py:2734, read pattern :2616-2617) via
  `batch_service.get_output_dir(batch_id)` — the same best-effort audit
  access the mirrors already use. Empty on the pz_generated trigger (PZ not
  yet booked) — the Note stores whatever exists at promotion time.

Required change shape: the loop appends promoted pieces to a `moved` list;
after the loop, `if moved: note_no = write_promotion_note(...)` (best-effort,
never fails the promotion — same doctrine as the mirrors); `note_no` joins
the result dict and the summary-mirror detail.

## 2. REFERENCES AVAILABLE (join paths, cited)

Per promoted piece, the packing `line` dict is already in hand
(`pdb.get_packing_lines_for_batch` = `SELECT * FROM packing_lines`,
packing_db.py:894-903), carrying natively:
- `packing_document_id` (packing list reference) — packing_lines schema
- `invoice_no` + `invoice_line_position` (import invoice reference)
- `design_no`, `batch_no`, `quantity`, `product_code`, `bag_id`, `tray_id`
- `scan_code` (the piece identity)

**Premise correction (disclosed):** the instruction cites "invoice_no +
client_po (persisted as of 494c4665)" — that fix was the SALES table
(`sales_packing_lines` in document_db). The Note's pieces are PURCHASE-side
`packing_lines` (packing.db), which has carried `invoice_no` natively since
inception and has NO client_po (a customer PO has no meaning on an import
receipt). 494c4665 matters to the Note only if a future sales-side movement
document reuses this design.

`wfirma_pz_doc_id`: audit.json as in §1. Batch-level import refs (AWB, MRN):
audit.json `customs_declaration` / `inputs` (routes_wfirma.py:2569-2570) —
available if the operator wants them on the header.

## 3. TABLE SHAPE — header + lines, in warehouse.db

**Precedent named:** `packing_documents` + `packing_lines` (packing_db.py) is
the codebase's header+lines document precedent; `warehouse_receipt_db`
(warehouse_receipt_confirmations + _events, :63-84) is the precedent for a
dedicated `*_db` module creating its tables idempotently at init
(CREATE TABLE IF NOT EXISTS). The engine's own pattern of a module writing
warehouse.db through `wdb._db_path` (inventory_state_engine.py:345-349) is
the storage-attachment precedent.

Header + lines (NOT flat — the contract mixes batch-level facts with
per-piece facts; flat would repeat the header per piece and make piece_count
derived-but-denormalised):

```sql
CREATE TABLE IF NOT EXISTS stock_promotion_notes (
    id                TEXT PRIMARY KEY,
    note_no           TEXT NOT NULL UNIQUE,      -- SPN/NNN/YYYY
    batch_id          TEXT NOT NULL,
    source_stage      TEXT NOT NULL,             -- 'PURCHASE_TRANSIT' (Temp Warehouse)
    dest_stage        TEXT NOT NULL,             -- 'WAREHOUSE_STOCK'  (Final Stock)
    trigger           TEXT NOT NULL,             -- pz_created | pz_generated | manual
    source            TEXT NOT NULL,             -- wfirma_pz_create | correction_push | pz_pipeline | manual endpoint
    operator          TEXT NOT NULL DEFAULT '',
    reason_note       TEXT NOT NULL DEFAULT '',
    piece_count       INTEGER NOT NULL,
    wfirma_pz_doc_id  TEXT NOT NULL DEFAULT '',  -- '' when unbooked at promotion time
    created_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_promotion_note_lines (
    id                  TEXT PRIMARY KEY,
    note_id             TEXT NOT NULL,            -- FK → stock_promotion_notes.id
    scan_code           TEXT NOT NULL,
    design_no           TEXT NOT NULL DEFAULT '',
    batch_no            TEXT NOT NULL DEFAULT '',
    invoice_no          TEXT NOT NULL DEFAULT '',
    packing_document_id TEXT NOT NULL DEFAULT '',
    quantity            REAL NOT NULL DEFAULT 0,
    state_before        TEXT NOT NULL,            -- per-piece before/after
    state_after         TEXT NOT NULL
);
```
Home: **warehouse.db** (inventory domain; sample_out_events/returns_events
already live there), owned by a new `stock_promotion_note_db.py` attaching
via `wdb._db_path` and creating tables at init — table creation rides the
init path, no draft-migration file (warehouse_receipt precedent).

## 4. NUMBER SERIES — net-new; concurrency shape

**No local document-number series generator exists anywhere** — the greps
surface only `MAX(created_at)` (correction_registry.py:466), schema_version
counters (finance_postings_db.py:273), and clone_generation
(proforma_invoice_link_db.py:1593); PZ doc numbers are operator-supplied or
wFirma-series; proforma/invoice numbers come from wFirma (`series/find`,
wfirma_client.py:2745). SPN is the platform's FIRST local series.

Concurrency-safe shape (SQLite):
`INSERT` the header inside a single `BEGIN IMMEDIATE` transaction that
computes `SELECT COALESCE(MAX(CAST(substr(note_no,5,instr-4) AS INT)),0)+1`
scoped to the current year, with `note_no` UNIQUE as the backstop — on
IntegrityError (a racing writer won), retry once with the next number.
BEGIN IMMEDIATE serialises writers at the DB level; the module-level lock
idiom (ise `_lock`, inventory_state_engine.py:506) adds in-process
serialisation. Two promotions in the same moment → distinct sequential
numbers, no gap-on-success, no duplicates.

## 5. RENDER / VIEW — zero new pages

- **v0, zero UI work:** the Note's audit-timeline mirror event (note_no in
  the detail payload) surfaces automatically in the Shipment Detail page's
  activity timeline (page==='detail', wired to the full-audit authority) —
  operators see "SPN/001/2026 created, 12 pieces" with no frontend change.
- **v1 recommendation: Stock Hub** (`/v2/inventory`, inventory-page.jsx) — a
  sixth read-only panel ("Promotion notes", batch-id input → list, same
  InvPanel idiom as panel-batch/panel-audit, inventory-page.jsx:246-256).
  It is the inventory family's home authority, already renders per-batch
  lookups, and needs no new route/slug. Documents Hub is the runner-up but
  is batch-document-centric (shipment docs), not inventory-movement-centric.
- **PDF/print:** a render path EXISTS to reuse — the V2 document-viewer
  family (`DocumentViewerPage` exported from inventory-page.jsx, used via
  `openViewer`/`viewerDoc` in index.html; `estrella-doc-packing.jsx` is the
  table-document template). A future `estrella-doc-spn.jsx` would be a new
  COMPONENT file (not a new page/route) — flagged now: even that needs its
  own pre-flight per the authority rule. Root-level PDF engine: out of
  scope, heavy.

## 6. IDEMPOTENCY INTERACTION

- **No-op re-promotion → NO second Note**: the hook fires only when
  `moved` is non-empty (`result.promoted > 0`). BE-1's idempotent skip means
  a second run promotes zero pieces → zero Notes. PIN THIS in tests.
- **Partial promotion → one Note for the moved subset only** (skipped and
  errored pieces are absent from the lines; piece_count = promoted count).
- Ordering corollary: receipt-first-then-PZ promotes via the receipt path
  today WITHOUT a Note (dhl_delivery_bridge/direct transitions don't call
  run_stock_promotion) — the Note documents promotions through the shared
  function only. If the operator wants receipt-path promotions to carry
  Notes too, the receipt writers should be converted into callers of
  run_stock_promotion (a BE-2b candidate, not assumed).
- Crash window (disclosed): transitions committed but process dies before
  the Note write → promotion stands, Note absent. The Note is a derivative
  record, reconcilable from inventory_state_events; the writer is
  best-effort by doctrine (never fails the PZ flow). Acceptable residual.

## 7. VERDICT

**Build shape (BE-2 slice, backend only):**
1. `stock_promotion_note_db.py` — tables (§3) created at init on
   warehouse.db; `write_promotion_note(...)` (BEGIN IMMEDIATE + UNIQUE retry
   series, §4); `get_note(note_no)` + `list_notes(batch_id)` readers.
2. `stock_promotion.py` — collect `moved` lines in the loop; best-effort
   Note write after the loop; `note_no` into result + summary-mirror detail.
3. Read routes — `GET /api/v1/inventory/promotion-notes/{batch_id}` +
   `/promotion-note/{note_no}` (read-only, additive).
4. Tests — Note-on-promote (all contract fields round-trip), NO-Note-on-noop,
   partial-subset, series uniqueness under simulated concurrency, per-piece
   before/after capture, best-effort (Note failure never fails promotion),
   BOTH wFirma writers produce Notes via the shared function (source pin).

**Stays out (follow-ups):** Stock Hub viewer panel (UI slice, own
pre-flight); estrella-doc-spn print component (own pre-flight); PDF engine;
receipt-path Notes (BE-2b, operator decision); historical backfill.

**Blast radius:** additive tables on warehouse.db (init-time creation, rides
deploy under persistence reviewer); one extension inside stock_promotion.py
(covered by the existing 12-test BE-1 suite + new pins); two read-only
routes; zero UI files; no fiscal surface, no state-machine change, no wFirma
write.
