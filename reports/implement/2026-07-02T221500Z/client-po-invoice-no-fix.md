# client_po + invoice_no persistence fix — build + test record

- **Date:** 2026-07-02 · backend only, zero UI files · no deploy
- **Operator decision:** "both" (fix client_po AND invoice_no)
- **Declared:** PROJECT_STATE DECISIONS "client_po + invoice_no silent-drop
  fix" (appended before any edit). Scope evidence: 2e05787e.
- **Pre-flight path correction (disclosed):** canonical file is
  `service/app/services/document_db.py` (instruction wrote `app/db/` — no
  such path exists).

## What changed

1. **ALTER-on-init** (`document_db.py:369-388`): two tuples appended to the
   existing sales_packing_lines evolution loop —
   `("client_po", "TEXT NOT NULL DEFAULT ''")`,
   `("invoice_no", "TEXT NOT NULL DEFAULT ''")` — with a DECISIONS-citing
   comment. Idempotent; legacy rows backfill to `''`.
2. **BOTH INSERTs** gained the columns + binds. Discovery during the edit
   (corrects the scope report's "single write path" claim):
   `replace_sales_packing_lines` carries its **own copy** of the INSERT
   rather than delegating — two identical blocks at `document_db.py:2013`
   (store_sales_packing_lines) and `:2089` (replace path). Fixing only one
   would have left a Logic-B drop; both were changed identically
   (16 → 18 columns, placeholder counts updated).
3. **New pin suite** `service/tests/test_packing_line_field_persistence.py`
   (8 tests): store-path readback, replace-path readback (both-write-paths
   pin), missing-fields default, legacy 16-column row reads back `''` via
   both SELECT * readers, ALTER idempotency re-init, drop-can't-return
   source pin (finds EXACTLY 2 INSERTs, each naming both columns with
   placeholder count == column count — a third write path breaks the pin on
   purpose), ALTER-tuple pin, extractor `order_no → client_po` alias pin.
   Real document_db against a temp DB — no stubs (Lesson A).

No route change needed: `routes_packing.py:1434/:1443` already carried both
fields to the DB boundary.

## Test evidence

```
pytest tests/test_packing_line_field_persistence.py -q
........                                                                 [100%]
8 passed in 5.60s

Existing packing/intake surface (9 suites):
16 failed, 178 passed, 8 skipped
TRIAGE: delta stashed, same 9 suites re-run at HEAD → identical 16 failures
(test_global_packing_first_authority ×3, test_cmr_packing_lines ×3,
test_intake ×1, test_intake_currency_and_pnd ×5,
test_dashboard_packing_contractor_resolution ×4) — ALL PRE-EXISTING at HEAD,
zero caused by this fix. Delta restored via stash pop, verified intact.

PYTHONUTF8=1 python test_pz_regression.py
✅ All golden checks pass — no regression detected. (160/160)
```

## Downstream (recorded, not this slice)

- Consignment contract linkage (Cons.ID ↔ Client PO ↔ Proforma) now has its
  prerequisite column.
- `proforma-detail.jsx:2542` still fakes client_po from
  `invoice_no || client_ref` — switch to the real column in the UI parity
  slice.
- Historical backfill feasible via `sales_documents.source_file_path`
  (separate decision).
- Prod schema self-migrates at service restart (ALTER-on-init) — rides the
  normal deploy under deploy_persistence_storage_reviewer.
