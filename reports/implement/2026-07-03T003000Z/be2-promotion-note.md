# BE-2 — Stock Promotion Note: build + test record

- **Date:** 2026-07-02/03 · backend only, zero UI files · no deploy
- **Declared:** PROJECT_STATE DECISIONS "BE-2 Stock Promotion Note" (appended
  before any edit). Scope evidence: 6d6d9d64. BE-2b (receipt-path Notes)
  declared-planned there, gap recorded not silent.
- **Operator contract (verbatim):** "Stock Promotion Note created on every
  Temp Warehouse -> Final Stock move, recording: source stage, destination
  stage, packing list / import reference, design numbers, batch numbers,
  piece count, operator, timestamp, reason/note, before/after inventory
  state."

## What was built

1. **`service/app/services/stock_promotion_note_db.py`** (NEW) —
   header+lines tables on warehouse.db, created idempotently on first touch
   (warehouse_receipt_db precedent; attaches via wdb._db_path like the state
   engine). Header: note_no, series_year/seq, batch_id, source_stage,
   dest_stage, trigger, source, operator, reason_note, packing_document_ids
   + invoice_nos (distinct-joined — a batch may span multiple invoices),
   wfirma_pz_doc_id, piece_count, created_at. Lines per piece: scan_code,
   design_no, batch_no, invoice_no, packing_document_id, state_before,
   state_after, transition_event_id (resolved from inventory_state_events —
   the engine does not return its event id).
   **SPN/NNN/YYYY = the platform's FIRST local document series and the
   LOCAL-SERIES PRECEDENT**: module _lock (in-process) + BEGIN IMMEDIATE
   (cross-process, lock-before-MAX) + MAX(series_seq)+1 per series_year +
   UNIQUE backstop + bounded IntegrityError retry.
2. **`stock_promotion.py`** (EDIT) — moved-subset capture in the loop; ONE
   Note written best-effort after the loop (STATE TRUTH > DOCUMENT: Note
   failure logs LOUDLY, never rolls back promotions — rationale in code);
   zero moved pieces → zero Note; note_no in the result and the
   summary-mirror detail (v0 view: surfaces in the Shipment Detail audit
   timeline for free). New `_read_wfirma_pz_doc_id()` best-effort audit read
   ('' when unbooked at promotion time, e.g. the pz_generated trigger).
3. **`routes_inventory.py`** (EDIT) — read-only GETs, GET-only per the
   file's contract: `/api/v1/inventory/promotion-notes/{batch_id}` (honest
   empty) and `/promotion-note/{note_no:path}` (slash-bearing note_no; 404
   `{"code": "NOTE_NOT_FOUND", ...}` matching the sibling convention).
4. **`tests/test_stock_promotion_note.py`** (NEW, 9 tests) — contract
   round-trip (every operator field incl. BOTH halves of "packing list /
   import reference"), note_no in the audit mirror, NO-Note-on-noop +
   zero-piece refusal, partial-subset single Note, series concurrency (8
   threads, gapless 1..8, no duplicates — PRECEDENT PIN), year rollover
   (SPN/001/2027 after SPN/002/2026), best-effort isolation (Note-db down →
   promotion stands), GET route shapes incl. the :path slashes and 404.
   Real DBs throughout (Lesson A).

## Adversarial verify pass (3-lens workflow, run wf_01b8758f-e2e)

Lenses: series/concurrency/transactions · isolation/single-writer/BE-1
regression · routes/contract/scope. **All three: refuted=false.** Two
confirmed findings fixed before commit:
1. 404 detail shape aligned to the sibling convention
   (`{"code", "detail"}` — routes_inventory_writes idiom), was
   `{"error", "code"}`.
2. Contract-field test gap closed: `packing_document_id` added to the test
   fixture; `packing_document_ids` (header) + per-line value now asserted —
   a silent drop of the packing-list reference can no longer pass.

Accepted residuals (INFO, documented): FK pragma not set (sole writer
inserts header+lines atomically; orphans impossible via production code);
sqlite3 context manager closes via CPython refcount; the IntegrityError
retry is an intentionally unreachable backstop given BEGIN IMMEDIATE
(belt-and-suspenders per module docstring); executescript's implicit COMMIT
is benign at current call order (noted in-code for future readers).

## Test evidence (at commit time)

```
pytest tests/test_stock_promotion_note.py tests/test_stock_promotion_be1.py
       tests/test_warehouse_stock_promotion.py -q
30 passed (9 BE-2 + 12 BE-1 + 9 pre-existing pins, unmodified)

PYTHONUTF8=1 python test_pz_regression.py
✅ All golden checks pass — no regression detected. (160/160)
```

## Follow-ups (recorded, not this slice)

BE-2b receipt-path Notes (declared-planned in DECISIONS) · Stock Hub viewer
panel (own pre-flight) · estrella-doc-spn print component (own pre-flight) ·
PDF · historical backfill. Prod schema: tables create on first touch after
deploy — rides the gate under deploy_persistence_storage_reviewer.
