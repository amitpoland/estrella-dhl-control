# client_po silent-drop — read-only scope pass (data-integrity fix)

- **Date:** 2026-07-02 · read-only · zero edits · disk-first
- **Origin:** top-5 parity gap #3 (reports/inspection/2026-07-02T-wfirma-wireframe-inspection.md)
- **Scope target:** sales-side packing import (`sales_packing_lines` in
  document_db). Purchase-side `packing_lines` never parses client_po — not
  applicable there.

## 1. THE DROP (exact cites, verified first-hand this pass)

**Parsed:**
- `excel_column_mapper.py:53` — `client_po` is a canonical recognised column.
- `invoice_packing_extractor.py:480-481` — field map `"client_po": "client_po"`
  ("sales-side PO reference") plus alias `"order_no": "client_po"`.

**Carried to the DB boundary:**
- `routes_packing.py:1443` — the line-record dict includes
  `"client_po": r.get("client_po") or ""`.

**Dropped:**
- `document_db.py:2003-2009` — the `INSERT INTO sales_packing_lines` column
  list binds exactly 16 columns (id, batch_id, sales_document_id, client_name,
  client_ref, product_code, design_no, bag_id, quantity, remarks, unit_price,
  currency, total_value, price_source, client_contractor_id, created_at) —
  **no client_po**. The dict key is silently ignored.

**Second dropped field in the same INSERT:** the dict also carries
`"invoice_no": r.get("invoice_no", "")` (`routes_packing.py:1434`) and the
INSERT has no invoice_no column either — same silent drop, same fix shape.
No other dict keys are dropped (all 13 remaining keys bind).

## 2. SCHEMA

- `sales_packing_lines` base CREATE (`document_db.py:249-262`): 11 columns
  (id, batch_id, sales_document_id, client_name, client_ref, product_code,
  design_no, bag_id, quantity, remarks, created_at).
- Evolution idiom is **ALTER-on-init, in-place**: `document_db.py:370-380`
  adds unit_price/currency/total_value/price_source via
  `ALTER TABLE sales_packing_lines ADD COLUMN …` wrapped in
  try/except OperationalError; `:395-401` adds client_contractor_id the same
  way. document_db self-migrates at init — **no separate migration file is
  used for this DB** (unlike warehouse.db's draft migrations).
- **No table anywhere carries client_po today** (repo-wide grep: only parser,
  route dict, intake concat, and JSX display references).
- Migration shape: one more tuple in the same ALTER loop —
  `("client_po", "TEXT NOT NULL DEFAULT ''")` (and `("invoice_no", …)` if the
  operator approves fixing both). SQLite backfills existing rows with `''` on
  ALTER ADD COLUMN with a constant default — legacy rows stay valid, nothing
  blocks.

## 3. BACKFILL feasibility (report only — separate decision)

`sales_documents.source_file_path` exists (`document_db.py:239`) — each sales
document row references its original uploaded file. Historical re-parse for
client_po is **feasible** for every row whose source_file_path is non-empty
and whose file still exists under the storage tree (and WorkDrive holds
mirrored uploads per the standard flow). Not part of this slice.

## 4. CONSUMERS once persisted

- `proforma-detail.jsx:2542` — currently **fakes** the field:
  `client_po: pk.invoice_no || ln.client_ref || ''`. Would switch to the real
  column (UI follow-up, not this slice).
- `estrella-doc-packing.jsx:12,169` — the packing document renderer already
  has a "Client PO" column rendering `r.client_po || '—'`; lights up
  automatically once the API rows carry it.
- `document_db.py:1460` and `:2212` readers use `SELECT * FROM
  sales_packing_lines` — the new column **flows to API responses
  automatically** (additive JSON field).
- `routes_intake.py:1058, 2296` — parse-time concat consumers (unchanged).
- Consignment contract linkage (operator spec): the future
  Cons.ID ↔ Client PO ↔ Proforma join **requires this column** — this fix is
  its prerequisite.
- Explicit-column readers (`routes_wfirma_capabilities.py:1889`,
  `dual_valuation.py:165`, `document_db.py:2153`) name their columns —
  unaffected.

## 5. TESTS

Existing surface: `test_cpa_packing_wiring.py`, `test_global_packing_parser.py`,
`test_global_packing_pdf_parser.py`, `test_global_packing_first_authority.py`,
`test_intake*.py`, `test_cmr_packing_lines.py`,
`test_dashboard_packing_list_card.py` — none pins client_po persistence
(the field has never persisted).

The fix's pin test must assert:
1. **parse → persist → readback**: a line dict with `client_po` (and the
   `order_no` alias path at the extractor level) survives
   `replace_sales_packing_lines` and comes back from the `SELECT *` reader.
2. **NULL-safe legacy rows**: rows inserted before the ALTER read back with
   `client_po == ''` (never None/KeyError).
3. **INSERT column-count pin**: the INSERT binds client_po (source-grep or
   round-trip), so the drop cannot silently return.
4. Same three for `invoice_no` if approved.

## 6. VERDICT

**Fix shape (3 touches, backend-only, zero UI files):**
1. `document_db.py` ALTER loop: `+ ("client_po", "TEXT NOT NULL DEFAULT ''")`.
2. `document_db.py:2004-2025` INSERT: add column + `str(ln.get("client_po", ""))` bind.
3. New pin test (per §5). The route dict already carries the field — no route
   change.

**Blast radius:** minimal. Single write path (the one INSERT); `SELECT *`
readers gain an additive JSON field; no explicit-column reader affected; no
state machine, no wFirma, no fiscal surface. Prod schema self-migrates at
service restart — the ALTER rides the normal deploy under
deploy_persistence_storage_reviewer.

**The one reason it's not 100% trivial:** the same INSERT silently drops
**invoice_no** too. Fixing client_po alone leaves a known sibling drop in
place; fixing both doubles the (tiny) surface. OPERATOR CALL: one word —
"both" or "client_po only". Also note `proforma-detail.jsx:2542`'s faked
fallback becomes stale-but-harmless after the fix (prefers invoice_no over
the real value) — flag for the Move Location/inventory UI parity slice, not
this one.
