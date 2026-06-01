# ADR-024: Product Master Authority — Per-Line product_code Model

**Status:** Accepted
**Date:** 2026-06-01
**Deciders:** Amit
**Related:** ADR-023 (SSOT umbrella), ADR-025 (E2E workflow), docs/ATLAS_WORKFLOW_MAP.md §4

## Context

ADR-023 called for a "canonical product master" with composite identity =
`supplier_id + supplier_product_code + normalized_design_attributes`. The
campaign inspection (workflow-reality-map-2026-06-01) and Phase 4 implementation
revealed that:

1. `product_code` (= `invoice_no-N`) is already the identity used by every
   downstream system: PZ generation, inventory_state, proforma/invoice lines,
   wFirma goods.
2. The three composite columns (`supplier_id`, `supplier_product_code`,
   `normalized_design_attributes`) were added as additive metadata but are not
   a database primary key — `product_code` remains the UNIQUE column.
3. Making the composite the primary key would require renaming 57+ existing
   production `product_master` rows and updating every downstream reference.
4. EJL-class codes are already globally unique by construction (`invoice_no-N`
   is unique per invoice line). 417G-class codes are distinguished by
   `supplier_id` metadata + a partial composite unique index.

## Decision

**Adopt the per-line `product_code` as the canonical product master identity.**

The row identity in `product_master` is `product_code TEXT NOT NULL UNIQUE`.
`supplier_id`, `supplier_product_code`, and `normalized_design_attributes` are
additive metadata columns — they support supplier context and disambiguation
lookups but are not the primary key.

### What "composite authority" means in practice

- For EJL codes: `product_code` is globally unique and self-identifying.
- For 417G codes: `supplier_id` stored as metadata; composite partial index
  `(supplier_id, product_code) WHERE supplier_id != ''` enforces uniqueness
  per-supplier. Disambiguation is via `get_product_master_by_composite()`,
  not via a new primary key.
- The `disambiguation_417g` inbox proposal type is **removed** — it was defined
  but never implemented. 417G disambiguation happens through the composite
  lookup, not through an explicit proposal mechanism.

## Rationale (why canonical composite-collapse was rejected)

| Consideration | Per-line product_code (chosen) | Composite collapse (rejected) |
|---|---|---|
| Downstream compatibility | All existing systems unchanged | Requires renaming 57+ production rows + updating every caller |
| EJL uniqueness | Already globally unique by construction | Same uniqueness, more complexity |
| 417G disambiguation | Via `supplier_id` metadata + partial index | Same outcome, different implementation |
| Migration risk | Additive-only (zero destructive ops) | Requires data migration in production |
| Implementation complexity | Low | High |

## GAP-17 closure

`validate_product_code_in_master()` is called at:
1. `seed_purchase_transit()` in `routes_packing.py` — when inventory_state rows
   are seeded from packing lines
2. `_build_preview()` / proforma create path in `routes_proforma.py` — when
   editable_lines_json is first written

Both are **advisory** — a missing product_code emits a
`GAP17_PRODUCT_NOT_IN_MASTER` action_proposal (Inbox-visible) and the operation
continues. This is NOT a hard block; GAP-17 is closed at the advisory level.

Full SQL FK enforcement across line tables in different DB files is deferred
(requires consolidating DB files — separate ADR).

## Consequences

- **Easier:** no data migration required; existing 57 rows preserved unchanged;
  downstream systems (PZ, inventory, proforma) require no code changes.
- **Harder:** 417G disambiguation is metadata-based, not schema-enforced;
  `normalized_design_attributes` column exists but must be explicitly populated
  by callers that want to use it.
- **Revisit:** if 417G disambiguation becomes a significant operational problem,
  consider a separate `supplier_products` table with a true composite key.

## Action items (completed)

- [x] Add `supplier_id`, `supplier_product_code`, `normalized_design_attributes`,
      `is_globally_unique` columns to `product_master` (additive ALTER TABLE)
- [x] Add partial unique index `(supplier_id, product_code) WHERE supplier_id != ''`
- [x] `get_product_master_by_composite()` for supplier-context lookup
- [x] `validate_product_code_in_master()` for GAP-17 advisory validation
- [x] Wire GAP-17 at inventory seed and proforma create paths (advisory)
- [x] Remove `disambiguation_417g` from ALL_REVERIFICATION_TYPES
- [x] Update ATLAS_WORKFLOW_MAP.md §4 to record this decision
