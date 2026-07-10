# ADR: finance_postings.sqlite is DORMANT-BY-DESIGN (Phase 6F paused)

Status: Accepted (operator decision, MASTER-EXEC-1 Phase 3, 2026-07-09). Decision: **DEFER** — neither archive nor build; ratify the existing "paused, not abandoned" state.

## Context
Phase 6F shipped a 5-table charge/payment/allocation/settlement schema (finance_postings_db.py), a read-only breakdown endpoint, a flag-gated (default OFF) proforma-post dual-write (finance_dual_write.py), and a dry-run backfill CLI — ~90 contract tests. In production the DB is empty (schema only, dormant since 2026-05-16); finance_dual_write_enabled is unset/False; payments/payment_allocations/settlements have zero production writers (6F.4/6F.6 unbuilt); the /post route deliberately blocks service-charge drafts until wFirma service-products are seeded. The MASTER-ARCH-1 "dead schema" risk was ambiguity, not data risk.

## Decision
finance_postings is DORMANT-BY-DESIGN, not dead code. Do not delete; do not build now. The breakdown endpoint / Diagnostics panel must be presented as dormant (Lesson M), never as a live capability.

## Reopening trigger
EJ decides to (a) bill service charges (freight/insurance/duty) as itemized wFirma line items, or (b) needs a local per-charge-type / FX-delta / settlement-close ledger wFirma cannot provide. Reopening follows the 6F sequence: /post block-lift approval, shadow, live, 6F.4, 6F.6, UI.

## Rollback
Docs-only decision — nothing to roll back. If ARCHIVE is later chosen: staged removal (panel, then routes/dual-write/flags, then schema+tests), each reversible via git revert.
