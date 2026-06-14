# Campaign 02 — Reservation Pipeline Verification Report

**Date**: 2026-06-13 (verification executed 2026-06-12)
**Campaign**: 02 — EJ Dashboard Portal — Authority Consolidation & Workflow Completion
**Track**: P3 Workflow Completion — Reservation Pipeline Verification (VERIFY-ONLY, no redesign)
**Source of truth**: all reads against `C:\PZ-verify` @ `ff1f4b5` (= origin/main)
**Method**: verification agent + independent adversarial verdict per claimed gap

---

## Verdict summary

| Check | Status | Adversarial verdict |
|---|---|---|
| design_no mapping | VERIFIED | — |
| Product resolution | VERIFIED | — |
| Ambiguity handling | **GAP** | isReal = TRUE (confirmed) |
| Operator decision path | **BROKEN** | isReal = TRUE (confirmed) |

Overall: the mapping core is single-authority and collision-safe. The pipeline's
critical weakness is that ambiguity detection exists but the resolution path does
not — ambiguous mappings block PZ and proforma creation with no operator interface
to resolve them.

---

## Verified components

### 1. design_no mapping — VERIFIED
- `reservation_worker.py:144` — `get_product_code_by_design_no()` provides
  single-authority mapping via the `design_product_mapping` table.
- `sales_packing_matcher.py:194` — batch-scoped lookup prevents cross-batch
  collisions.
- Authority chain: purchase packing → `design_product_mapping` → `reservation_queue`.

### 2. Product resolution — VERIFIED
- `sales_packing_matcher.py:8` — `product_code` is minted exactly once by
  `store_invoice_lines` in `document_db.py` and copied by the matcher (never
  invented).
- `reservation_worker.py:145-153` — reservation rows reference the canonical
  `product_code` or are explicitly marked `UNMAPPED`.

---

## Confirmed gaps (one workflow class)

Both findings are facets of a single missing workflow class: **operator decision
workflow for ambiguous design_no mappings**. They should be fixed together.

### GAP — Ambiguity detected but unresolvable by the operator

**Workflow class**: operator decision workflow (Lesson I bucket: "operator confusion /
repeat operator action" → guided workflow).
**Authority owner**: Product Master (design→product mapping).

Evidence:
- `sales_packing_matcher.py:223-231` — detects ambiguous design codes
  (1 design → 2+ product_codes), reports via `designs_ambiguous` dict, logs warnings.
- `dashboard.html:16857-16863` and `shipment-detail.html:13050-13057` — ambiguity is
  displayed in a read-only amber badge ("design_code → product_code1, product_code2");
  no resolution controls.
- `proforma-v2.html:798-807` — V2 pages show the same display-only pattern.
- `routes_dashboard.py:2536` — `ready_for_pz_create` is explicitly blocked by
  `ambiguous_design_codes`.
- `routes_proforma.py:706-709` — proforma creation also blocked when a design_no
  maps to multiple product_codes.
- Exhaustive route search found NO endpoint for manual mapping selection. The only
  related controls are "Refresh Mapping" buttons, which re-run detection — not
  resolution. The workflow terminates at detection.

Operational consequence: any batch with a genuinely ambiguous design code is
hard-blocked from PZ and proforma creation until someone edits data out-of-band.

Proposed fix (NOT implemented — VERIFY-ONLY track):
1. Resolution endpoint: operator selects the correct product_code per ambiguous
   design_no (auditable, batch-scoped, writes through the existing
   `design_product_mapping` authority — never a side-table).
2. UI controls on the existing ambiguity surfaces (amber badge → actionable list).
3. Lesson M compliance: until built, the blocked state must continue to display the
   exact reason and reference this gap.

**GATE 4 disposition**: ISSUE — prepared; filing was blocked by session permission
policy (external write requires operator approval). Ready-to-file body below.

---

## Ready-to-file issue body (operator action required)

### Title
`Reservation pipeline: ambiguous design_no mappings have no operator resolution workflow (detection-only, blocks PZ + proforma)`

Body: GAP section above, verbatim. Suggested labels: `governance`, `follow-up`.

---

## Closure statement

Reservation Pipeline Verification (Campaign 02 P3) is COMPLETE as a verification
deliverable. The mapping and resolution core is verified single-authority and
collision-safe. The missing operator-decision workflow is documented, classified per
Lesson I as a workflow class (not a batch-specific patch), and carries a GATE 4
disposition pending operator approval to file the issue. No code was changed by this
track (VERIFY-ONLY mandate honored).
