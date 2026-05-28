# Master Data Soft-Delete / V2 — Campaign Close-Out

**Status:** COMPLETE (2026-05-28)
**Scorecard:** `.claude/memory/scorecards/2026-05-28-master-data-soft-delete-v2-campaign.md`
**Design note:** `service/docs/product_local_soft_delete_design.md`

## What shipped

A governed master-data platform built incrementally over Phases 0–5 and
Phase 4A → 4D-ext-2 / Waves 1 → 4:

- **15/15 entities soft-deletable** with restore. Zero hard-delete-only left.
- Unified append-only `master_audit` (create/update/delete/restore/hard_delete).
- Role-gated writes (`master_role_enforcement`, default OFF; isolated
  master_admin/editor/viewer).
- Referential integrity for active references (409 `reference_conflict`).
- Structured error UX + `ReferencePicker` (active HS codes, active carriers).
- V2 customer detail surface (inline addresses + carrier accounts,
  composite-pk audit, inactive-state banner).

## Gates at close

- Full app import: 423 routes.
- Targeted master/audit/role/V2 suite: 956/956.
- PZ regression: 160/160.

## Authority invariants (preserved, test-pinned)

- product_local inactive = stop applying overlay (NOT product deletion);
  PZ engine decoupled.
- fx_rates reference-only (PZ uses live NBP).
- carriers_config never stores credentials.
- wFirma sync/apply/dictionary untouched; soft-delete imports no wFirma;
  PUT never reactivates.

## Open follow-ups (GATE 4 dispositions)

1. **SCHEDULED** — isolated V1 fix for the pre-existing
   `shipment-detail.html` ship_to→bill_to fallback contract test
   (`test_proforma_draft_editor_contract.py::test_ui_cascade_ship_to_payload...`).
   Exact prompt below.
2. **SCHEDULED** — Phase 5-ext: customer **Restore** button + default-address
   management inside the V2 customer detail surface.
3. **ISSUE** — surface "overlay inactive" provenance in the proforma UI when a
   product_local overlay is soft-deleted mid-workflow.

### Next exact task prompt (follow-up 1)

```
[TASK]: Fix the isolated shipment-detail.html ship_to→bill_to fallback
contract failure (V1 critical-fix exemption).

Failing test:
  test_proforma_draft_editor_contract.py::test_ui_cascade_ship_to_payload_uses_ship_to_then_bill_to_fallback

Scope:
- Edit only service/app/static/shipment-detail.html (V1 page — this is a
  critical-fix exemption under V1-FREEZE, operator-approved).
- Do not touch V2 pages, backend routes, DB modules, wFirma/PZ/DHL/proforma
  logic, or any master-data code.

Goal: in the onApplyCustomerDefaults callback, every ship_to_* payload field
must fall back to its bill_to_* counterpart via `||`, matching the contract
the test asserts:
  c.ship_to_street  || c.bill_to_street
  c.ship_to_city    || c.bill_to_city
  c.ship_to_zip     || c.bill_to_postal_code
  c.ship_to_country || c.country
  c.ship_to_email   || c.bill_to_email
  (plus any remaining lines the test enumerates)

Verify: run test_proforma_draft_editor_contract.py to green; run PZ regression
160/160; confirm git diff is shipment-detail.html only.
Final report: changed file, exact fallback lines added, test result, PZ status.
```
