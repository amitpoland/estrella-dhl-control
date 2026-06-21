# ADR — Product Identity Authority (single source of truth)

**Status:** Accepted (Product Authority Consolidation, Phase 0–2)
**Date:** 2026-06-21
**Supersedes scattered, recomputed resolution in design_product_bridge / proforma_draft_sync / sales_packing_matcher.**

## Context

Product identity was derived independently in several places, each running its own
`SELECT DISTINCT design_no, product_code FROM packing_lines` with slightly different
normalisation and null handling. That divergence produced false ambiguity blockers and
inconsistent readiness behaviour (symptoms patched by #684 and #686). product_master is a
coarse `UNIQUE(product_code)` registry that **cannot** represent a mixed lot at per-piece
grain (one row per product_code, `design_no` often blank), and is not read by any hard gate.

## Decision — the authority chain

| Store | Role | Mutability |
|---|---|---|
| **invoice_lines** (documents.db) | **Immutable product_code MINT** — `product_code = product_code OR f"{invoice_no}-{line_position}"`, `INSERT OR IGNORE`. | append-only / immutable |
| **packing_lines** (packing.db) | **Per-piece OPERATIONAL authority.** The single read source for product identity, design→code resolution, and available quantity. | re-uploadable (DELETE+INSERT) |
| **product_master** (reservation_queue.db) | **Cross-batch REGISTRY / advisory only.** Identity metadata + wFirma link. **MUST NOT become a hard gate.** | upsert preserve-on-blank |
| **sales_packing_lines** (documents.db) | **Sales projection** (what is billed). | re-uploadable |

## Identity anchors (rules)

1. `packing_lines` is the per-piece authority.
2. `product_code` = `invoice_no + invoice_line_position` is the **mixed-lot** authority (one
   invoice line may hold several designs/pieces).
3. `design_no` is **descriptive, not unique**.
4. A `product_code` may cover multiple design rows and quantities.
5. A billed `product_code` **wins** when it validates against `packing_lines`.
6. Total billed quantity for a `product_code` **must not exceed** the available packing quantity.
7. `design_no`-alone is only a fallback when product_code authority is absent.
8. NULL/blank `product_code` rows **must not** inflate ambiguity candidates.
9. `product_master` is **advisory only**.

## Consequence

All product-identity derivation goes through **`product_authority_resolver`**:
`resolve_batch_product_authority`, `design_to_product_codes`,
`available_quantity_by_product_code`, `validate_billed_product_code`,
`reconcile_billed_ambiguity` (#684), `analyze_product_code_billing` (#686),
`reconcile_billed_lines`. `design_product_bridge`, `proforma_draft_sync`, and
`sales_packing_matcher` are repointed to it. Behaviour is preserved (characterization +
equivalence tests). **No schema migration, no `product_master_lines`, no data mutation** in
this phase. A durable cross-batch per-piece registry (`product_master_lines`) remains a
separate, deferred decision.
