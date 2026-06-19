# PR: feat/supplier-header-templates → feat/excel-column-mapping-governance

## Title
feat(packing): Tier 0 supplier header templates — operator-approved column learning

## Summary

- Adds **supplier-specific Excel header templates** keyed by Supplier Master ID (`supplier_id`).
  Operator-approved `raw_header → canonical_field` mappings are stored in
  `supplier_header_templates` and applied as **Tier 0** in the column mapper before
  existing alias/fuzzy/LLM tiers.
- **LLM output is never auto-saved.** Only an explicit operator `POST` to
  `approve-header-mapping` with `operator_confirmed: true` persists a template.
- Governance hardened in commit `ae0e0d6`: `source_method` audit column, explicit
  `window.confirm()` preview dialog, backend gate on unconfirmed LLM rows.

## Files changed (this branch only — 2 commits, 7 files)

| File | Change |
|---|---|
| `app/services/packing_db.py` | `supplier_header_templates` table; `supplier_id` on `packing_documents`; `source_method` audit column; CRUD functions |
| `app/services/excel_column_mapper.py` | Tier 0 block + `build_col_map` includes `supplier_template` |
| `app/services/invoice_packing_extractor.py` | `supplier_id` threaded end-to-end |
| `app/api/routes_intake.py` | `supplier_contractor_id` → `supplier_id` on packing upload |
| `app/api/routes_packing.py` | `POST /{batch_id}/approve-header-mapping` endpoint |
| `app/static/shipment-detail.html` | Green "template" badge + governed approval button |
| `tests/test_supplier_header_templates.py` | 26 tests (migration, CRUD, Tier 0, governance) |

## DB migration safety

All schema changes use `CREATE TABLE IF NOT EXISTS` + `_add_column_if_missing()`.
Migration is **idempotent** — running `init_packing_db()` twice on an old production
DB produces no errors and no duplicate columns.

Migration simulation (26/26 checks passed):
- Old DB without `supplier_id` or `supplier_header_templates` → migrated successfully
- Existing `packing_documents` rows readable with `supplier_id = NULL` after migration
- Second `init_packing_db()` call: no exception, no duplicate columns
- Upsert without `supplier_id` still works (backward compat)
- COALESCE preserves existing `supplier_id` when re-upsert omits it

## Safety contracts

1. **No PZ/wFirma/product/customer/inventory writes** — only `supplier_header_templates` is written
2. **Supplier identity comes from operator dropdown** (`supplier_contractor_id` in intake) — never inferred from file content
3. **LLM output never auto-saved** — verified by `test_llm_suggestions_not_auto_saved`
4. **Backend rejects** LLM rows without `operator_confirmed=true`
5. `source_method` column records origin (alias/fuzzy/llm/operator_approved) for audit

## Tests

| Suite | Result |
|---|---|
| `test_supplier_header_templates.py` | 26/26 PASS |
| `test_packing_db.py` | 28/28 PASS |
| `test_packing_integration.py` | 3/3 PASS |
| `test_intake.py` | 29 pass, 8 skip, 1 fail (pre-existing: macOS path hardcoded in test fixture) |
| `test_excel_column_mapper.py` | 46/46 PASS |
| `test_timeline_events.py` | 17/17 PASS |

**Pre-existing failures (not introduced by this PR):**
- `test_packing_doc_related_invoice_no_is_parsed_invoice_no` — hardcoded macOS path
  (`/Users/amitgupta/Library/...`) that does not exist on this Windows machine
- `test_packing_enrichment.py` (8 tests) — `_build_wfirma_rows()` missing
  `packing_enrichment` kwarg, pre-dates this PR

## Rollback

```powershell
# Revert both commits (leaves branch intact)
git revert ae0e0d6 --no-edit
git revert 859e4be --no-edit
# Or reset branch to parent
git reset --hard origin/feat/excel-column-mapping-governance
```

## Stacked on

PR #524 (`feat/excel-column-mapping-governance`) — must merge first.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
