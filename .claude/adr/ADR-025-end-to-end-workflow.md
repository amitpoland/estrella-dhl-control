# ADR-025: End-to-End Document→PZ→Invoice Workflow (master-data-driven, soft-validation)

**Status:** Proposed  
**Date:** 2026-06-01  
**Deciders:** Amit  
**Related:** ADR-023 (SSOT umbrella), ADR-024 (product master — pending), ADR-018 (flag model). Grounded in docs/inspection/workflow-reality-map-2026-06-01 + field-source-matrix-2026-05-31.

## Context

The target is the master-driven flow: purchase intake → product master + wFirma product sync → sales intake → draft proforma → PZ → wFirma post → convert to invoice, with inventory staged by DHL status and an operator goods-received confirmation. The workflow-reality map (a81982e) classifies the current system: intake wiring EXISTS; product-code thread, sales↔purchase match, stage machine, inventory engine are PARTIAL; the validate-against-master→inbox layer and the DHL-delivered→goods-received link are GAPs; and three gates (SAD, wFirma-product-sync, PZ-before-proforma) HTTP-422/400 the flow — which is why all 25 active shipments are jammed at SAD.

Two operator principles: (a) master data is the single source of truth (ADR-023); (b) validation is soft — detect → inbox → approve — never a hard block, because hard blocks break the running system and prevent end-to-end testing.

## Decision

Converge to the master-driven, soft-validation workflow incrementally:

1. **Soft validation (locked).** All validation surfaces as inbox proposals + operator approval/override. The existing workflow gates (SAD, product-sync, PZ-before-proforma) become ADVISORY — warn + raise an inbox item, operator may proceed.
2. **Master-driven identity.** Consignor ← supplier master; consignee ← company_profile (PR #416, flag-gated). Dropdowns already master-wired.
3. **product_code = the relational thread.** Minted at purchase intake, matched at sales intake, carried through PZ/inventory/proforma/invoice; close GAP 17 (logical/SQL validation from line tables to the product master) per ADR-024.
4. **wFirma product sync at intake.** Auto-register parsed products to wFirma at purchase intake (flag-gated write, WFIRMA_CREATE_PRODUCT_ALLOWED) so the code exists in wFirma before PZ — PZ becomes instant. Replaces lazy operator-triggered resolve.
5. **DHL-driven inventory + goods-received.** DHL status feeds inventory stages; DHL "delivered" raises an operator "mark received" prompt → PURCHASE_TRANSIT→WAREHOUSE_STOCK. "Received" is a soft readiness signal, not an enforced precondition.
6. **Validate-against-master → inbox.** New layer: on upload, compare parsed fields (supplier/client identity, product attributes, HS) to the masters and raise inbox proposals for mismatches. Extends the contractor-resolver (advisory) and the action-proposal infra (today email + wFirma-recovery only).

## The safety reconciliation (why "no hard block" is safe)

Soft applies to **workflow gates** (advancing stages, generating docs, previewing) — not to the **irreversible wFirma writes**, which stay behind their feature flags (CREATE_PROFORMA / CREATE_INVOICE / CREATE_PRODUCT, all default OFF). So an operator can move a shipment through the pipeline for testing/visibility without a SAD, but still cannot *write* to wFirma without the deliberate write flag. Soft workflow gates + hard (flag) write gates.

## Options

- **A (chosen):** converge incrementally — soft-validate, master-driven.
- **B:** keep hard gates, just fix data. Rejected — can't test end-to-end; doesn't reach SSOT.
- **C:** rewrite the pipeline as a formal state machine now. Deferred — the clearance_status string works; formalize only if it proves insufficient.

## Hard-stops to soften

- **HS-1 SAD** (guard_pz_requires_sad + guard_dhl_requires_email): advisory mode (warn + inbox), keep existing escape hatches. Immediate operational unblock for the 25 exists but should be used only after confirming why each is stuck.
- **HS-2 wFirma product sync before proforma post:** auto-resolve on post (flag on) + pre-flight inbox warning, not a 400.
- **HS-3 proforma-requires-PZ:** already only on final post (preview allowed); keep advisory.

## Invariant Preservation

Convert + wFirma write flags stay (off by default); soft-validation never bypasses them. No live wFirma/email writes in dev (mock). Additive/non-destructive migrations. product_code identity stable; 417G per ADR-024 D1.

## Consequences

Easier: end-to-end testing (no hard stops), one master source, instant PZ, dead-end prevention. Harder: building the validate→inbox layer; auto-register write-safety; reconciling the stage model. Revisit: formal state machine; 417G keying; whether "received" should ever be hard.

## Open Items (assumptions to confirm)

- Soften HS-1/2/3 to advisory (assumed yes).
- Auto-register products to wFirma at intake, flag-gated (assumed yes).
- "Received" is soft, not enforced (assumed yes).
- Whether/which of the 25 to unstick now operationally vs. wait for advisory mode.

## Action Items

1. [ ] Commit the workflow-reality map as docs/inspection/workflow-reality-map-2026-06-01.md.
2. [ ] Land PR #416 (customs identity, flag-gated).
3. [ ] Increment: advisory-mode flag for HS-1/2/3 + inbox proposals (unblocks testing).
4. [ ] ADR-024 product master + close GAP 17.
5. [ ] wFirma product auto-register at intake (flag-gated write).
6. [ ] Validate-against-master → inbox layer.
7. [ ] DHL-delivered → goods-received prompt → inventory transition.

---

This ADR establishes the architectural foundation for transitioning from the current gate-blocked system to a master-data-driven workflow with soft validation, enabling end-to-end testing while preserving operational safety through feature flags.