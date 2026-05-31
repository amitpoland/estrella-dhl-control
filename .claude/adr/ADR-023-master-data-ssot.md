# ADR-023: Master Data as Single Source of Truth

**Status:** Proposed — umbrella / program-level ADR
**Date:** 2026-05-31
**Deciders:** Amit
**Related:** ADR-021 (detect-before-gate), ADR-022 (post-time snapshot), ADR-018 (flag model)

## Context

The field-source inspection (`docs/inspection/field-source-matrix-2026-05-31.md`) established that PZ has no authoritative canonical data layer. Master data is fragmented across four SQLite databases (`customer_master.sqlite`, `wfirma.db`, `master_data.sqlite`, `documents.db`) as 13 separate masters (M1–M13). Product attributes are split across four tables (M3 `wfirma_products`, M4 `product_local`, M5 `product_descriptions`, M6 `designs`) with no single record and no FK enforcement. Several document fields are hardcoded constants (consignor/consignee — GAP 1/2) or free text that bypasses masters (overrides — GAP 9/10, remarks — GAP 11). wFirma authors some values the local DB merely caches (VAT-code numeric IDs, server-assigned numbers/series).

The 17 gaps are not 17 independent problems. They are symptoms of one root cause: each surface re-derives its values independently from scattered sources, which is what produces dead-ends (B1–B9) and silent drift. Convert-to-invoice cannot safely go live while data integrity is this loose.

## Decision

Make **master data the single source of truth.** Three flows:

1. **Inbound (ingest → master).** All data arriving from wFirma (customer/product mappings, series, VAT IDs) and all data extracted from parsed invoices and packing lists is normalized and persisted into master data as the canonical record.
2. **Canonical read (master → surfaces).** Proforma, inventory, sales, and ledger read exclusively from master data. No surface re-derives values from free text, hardcoded constants, or parse output.
3. **Outbound (master → wFirma).** Requests to wFirma are built from master data in canonical form, so what wFirma feeds in and what PZ sends back are the same shape (round-trip integrity).

### Field ownership & direction (load-bearing)

Every field has exactly one authoritative owner and a defined direction:

- **wFirma-authored, master-cached:** internal VAT-code IDs, server-assigned proforma/invoice fullnumbers, wFirma-defined series IDs. Master caches and refreshes; never claims to author.
- **Master-authored:** customer identity / EORI / incoterm / currency / payment defaults (M1), the canonical product record, designs (M6), HS codes (M7), seller/consignor/consignee (M8 `company_profile`), the VAT semantic rule (country→regime).

The inspection's field-source matrix is the seed; the first deliverable converts it into an explicit ownership/direction matrix.

### Canonical product master (the largest missing piece)

Create one authoritative product record keyed by product/design id holding HS, PL+EN description, category, metal/karat, origin, and unit — consolidating M3/M4/M5/M6. All line-bearing tables (`inventory_state`, `editable_lines_json`, `packing_lines`, `invoice_lines`) FK to it. Closes GAP 16/17 and removes the source of several dead-ends.

## Options Considered

### Option A — SSOT hub (this decision)
| Dimension | Assessment |
|-----------|------------|
| Complexity | High (migration + ownership definition) |
| Blast radius | Managed via per-increment flags + reconciliation |
| Root cause | Addressed — eliminates the no-canonical-layer cause |
| Convert safety | Enables it |

**Pros:** closes the 17 gaps by construction; one place to govern; eliminates drift; new surfaces (sales/ledger) wire in cheaply. **Cons:** large migration; must define ownership per field; must reconcile fragmented existing data.

### Option B — Point validation only (original BUILD B / what PR #412 started)
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low |
| Blast radius | Small |
| Root cause | Not addressed — treats symptoms |
| Convert safety | Partial |

**Pros:** incremental, safe. **Cons:** fragmentation and drift persist; each surface still re-derives; the 17 gaps get closed one-by-one indefinitely. *Valid as a first increment under A, insufficient as a destination.*

### Option C — wFirma as SSOT (PZ a thin client)
**Pros:** no local master to maintain. **Cons:** wFirma can't hold PZ-specific fields (EORI wiring, designs, PL/EN customs descriptions, carrier accounts); parsed invoice/packing-list data has no canonical home; couples PZ to wFirma's model; parse-first workflows break. **Rejected.**

## Trade-off Analysis

A is the only option that addresses the root cause. B is a strict subset of A and a safe first increment, but as a destination it leaves fragmentation and drift in place. C inverts ownership in a way that breaks PZ-specific and parse-first needs. A's cost (migration + ownership definition) is mitigated by sequencing: stand up the canonical product master first, then rewire one surface at a time behind a flag, reconciling data per increment. Drift is handled by the ownership/direction rule — master-cached fields refresh from wFirma; master-authored fields push to wFirma.

## Invariant Preservation

- The convert gate stays exactly where it is; SSOT does not move or weaken it.
- No live wFirma writes in dev/test (shared prod account, no sandbox) — mock.
- All migrations additive/non-destructive; existing data reconciled, never discarded.
- Round-trip integrity: a value ingested from wFirma and later sent back is unchanged unless a master-authored field deliberately overrides it.
- ADR-022's post-time snapshot remains valid as a stepping stone; its role narrows once master holds the canonical values.

## Consequences

- **Easier:** governance (one place), convert safety, dead-end prevention, consistent customs documents, wiring new surfaces.
- **Harder:** initial migration; maintaining the ownership matrix; reconciling data across four DBs.
- **Revisit:** whether to physically consolidate the four SQLite DBs or unify them logically behind a master-data access layer; the scope of "ledger."

## Action Items (sequenced; each a separate later PR — none started, pending tree reconciliation)

1. [ ] Convert the field-source matrix into a field **ownership & direction** matrix (owner · direction · cache-vs-author).
2. [ ] Define and build the **canonical product master** (consolidate M3/M4/M5/M6); additive schema; reconcile existing rows. *(Recommended first increment — most gaps hang off it.)*
3. [ ] Add FKs from line-bearing tables to the product master (GAP 17).
4. [ ] Rewire proforma build to read buyer/ship-to/series/VAT/currency/payment/incoterm from master (GAPs 7, 9, 10, 12, 13, 14, 15) — behind a flag.
5. [ ] Wire seller/consignor/consignee/EORI from `company_profile` + `customer_master` (GAPs 1, 2, 3, 4).
6. [ ] Make outbound wFirma request builders source from master (round-trip integrity; GAP 13 drift).
7. [ ] Wire inventory, sales, and **ledger** reads to master. *(Ledger scope — OPEN ITEM: new PZ surface vs. wFirma/accounting view.)*
8. [ ] Define reconciliation/refresh for wFirma-cached fields (VAT IDs, series, numbers).
9. [ ] Per increment: additive migration + flag + data reconciliation; nothing destructive.

## Open Items
- **Ledger** definition (new PZ surface or wFirma/accounting side).
- Physical DB consolidation vs. logical unification behind an access layer.
- Confirm the first increment (recommend the canonical product master).