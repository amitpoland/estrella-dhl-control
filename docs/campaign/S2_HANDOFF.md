# S2 hand-off — what the allocation branch must change when it rebases

For `feat/packing-allocation-authority` (currently `39310922`, worktree
`C:\PZ-wt\packing-allocation`). Executable without re-reading S0.

## The identity you now bind to

- **`packing_line_key(line)`** — group-shaped, four parts:
  `invoice_no|product_code|design_no|quantity`, each normalised by
  `_norm_key_part`. Pure function of the row. There is **no ordinal** — two
  designs with one were proven wrong (list-position collapses under per-line
  calls; DB-ranked violates identity stability).
- A key names a **commercial group**, not a row. Several rows sharing it in one
  document are a lot; multiplicity is a count.

## Checklist

1. **Re-key**: `line_id` → `(batch_id, packing_line_key)` as the allocation
   subject. Allocation rows referencing a rowid break on re-ingestion; the group
   key survives it.
2. **Quantity-scoped** (R8): allocation carries `quantity`;
   invariant `SUM(allocations.quantity) per (batch_id, packing_line_key)
   <= SUM(packing_lines.quantity)` for that key — note the right side is the
   GROUP total (a lot of 3×1.0 gives budget 3.0).
3. **Refuse incomplete keys**: `line_key_is_incomplete(line)` is True for 123
   live rows (no invoice_no AND no product_code). Never bind money to them —
   surface them as needing operator resolution instead.
4. **Keep**: the `auto/confirmed/overridden` vocabulary, the
   `bill_to_contractor_id` binding, single-writer discipline. All correct.
5. **Suggestion vs confirm is unchanged** — supplier lists never bind without
   operator confirmation.
6. **Shared shape with credit allocation (W4-Z10)**: suggestion vs confirm,
   quantity-scoped, single writer, reversible. Build as ONE pattern — a second
   allocation shape is a second authority.

## What S0 guarantees you

- Two supplier forms of one line are ONE stored group (write-time absorb, same
  stage only, multiplicity-aware; 29-test suite `test_packing_upsert_dedupe.py`).
- Advance/final pairs are both stored, linked in `packing_doc_links` with
  `total_variance` / `line_count_variance` (R17); surface non-zero variance.
- The three data repairs (39 duplicate quarantine, orphan quarantine + FK,
  dead-DB rename) are proven modules pending the storage-variant gate.
